"""승인 워크플로우 — 진화 변경의 인간 승인 관리.

Evolution Orchestrator가 제안한 파라미터 변경을
저장하고, Discord를 통해 인간 승인을 대기한다.
승인 시 config.yaml을 원자적으로 업데이트한다.

사용:
    workflow = ApprovalWorkflow(config_path)
    change_id = workflow.propose(change)
    # Discord: /approve <change_id>
    workflow.approve(change_id)
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# 기본 경로
_DEFAULT_PENDING_PATH = Path("data/pending_changes.json")
_DEFAULT_CONFIG_PATH = Path("configs/config.yaml")


@dataclass
class PendingChange:
    """대기 중인 변경 제안."""

    change_id: str
    proposed_params: dict[str, Any]
    current_params: dict[str, Any]
    changes: dict[str, list[float]]  # {param: [old, new]} (JSON 호환)
    risk_score: float
    risk_level: str
    fitness_improvement: float
    rationale: str
    experiment_count: int
    created_at: str
    status: str = "pending"  # pending | approved | rejected | expired

    def to_dict(self) -> dict[str, Any]:
        """JSON 직렬화용 딕셔너리."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PendingChange:
        """딕셔너리에서 생성."""
        from dataclasses import fields as dc_fields

        valid_keys = {f.name for f in dc_fields(cls)}
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)


class ApprovalWorkflow:
    """진화 변경 승인 워크플로우.

    변경 제안을 JSON 파일에 저장하고,
    승인 시 config.yaml을 원자적으로 업데이트한다.
    """

    def __init__(
        self,
        config_path: Path | None = None,
        pending_path: Path | None = None,
    ) -> None:
        from app.config import PROJECT_ROOT

        self._config_path = config_path or (PROJECT_ROOT / _DEFAULT_CONFIG_PATH)
        self._pending_path = pending_path or (PROJECT_ROOT / _DEFAULT_PENDING_PATH)
        self._pending_path.parent.mkdir(parents=True, exist_ok=True)

    def propose(self, change: PendingChange) -> str:
        """변경 제안을 저장한다.

        Args:
            change: 대기 중인 변경.

        Returns:
            change_id.
        """
        pending = self._load_all()
        pending[change.change_id] = change.to_dict()
        self._save_all(pending)
        logger.info(
            "진화 변경 제안: %s (risk=%s, fitness_delta=%.4f)",
            change.change_id,
            change.risk_level,
            change.fitness_improvement,
        )
        return change.change_id

    def approve(self, change_id: str) -> bool:
        """변경을 승인하고 config.yaml을 업데이트한다.

        Args:
            change_id: 승인할 변경 ID.

        Returns:
            성공 여부.
        """
        pending = self._load_all()
        entry = pending.get(change_id)
        if not entry or entry["status"] != "pending":
            logger.warning("승인 실패: %s (없거나 pending 아님)", change_id)
            return False

        change = PendingChange.from_dict(entry)

        # config.yaml에 패치 적용
        patches = self._build_patches(change)
        if patches:
            self._apply_config_patches(patches)
        else:
            logger.warning("승인되었으나 실제 변경 사항 없음: %s", change_id)

        # 상태 업데이트
        entry["status"] = "approved"
        self._save_all(pending)

        logger.info("진화 변경 승인 완료: %s", change_id)
        return True

    def reject(self, change_id: str) -> bool:
        """변경을 거부한다.

        Args:
            change_id: 거부할 변경 ID.

        Returns:
            성공 여부.
        """
        pending = self._load_all()
        entry = pending.get(change_id)
        if not entry or entry["status"] != "pending":
            logger.warning("거부 실패: %s (없거나 pending 아님)", change_id)
            return False

        entry["status"] = "rejected"
        self._save_all(pending)
        logger.info("진화 변경 거부: %s", change_id)
        return True

    def list_pending(self) -> list[PendingChange]:
        """대기 중인 변경 목록을 반환한다."""
        pending = self._load_all()
        return [
            PendingChange.from_dict(v)
            for v in pending.values()
            if v.get("status") == "pending"
        ]

    def get(self, change_id: str) -> PendingChange | None:
        """특정 변경을 조회한다."""
        pending = self._load_all()
        entry = pending.get(change_id)
        if not entry:
            return None
        return PendingChange.from_dict(entry)

    def expire_old(self, hours: int = 48) -> int:
        """오래된 pending 변경을 만료 처리한다.

        Args:
            hours: 만료 기준 시간.

        Returns:
            만료된 건수.
        """
        pending = self._load_all()
        now = datetime.now()
        expired_count = 0

        for entry in pending.values():
            if entry["status"] != "pending":
                continue
            created = datetime.fromisoformat(entry["created_at"])
            elapsed = (now - created).total_seconds() / 3600
            if elapsed > hours:
                entry["status"] = "expired"
                expired_count += 1
                logger.info(
                    "진화 변경 만료: %s (%.1f시간 경과)",
                    entry["change_id"],
                    elapsed,
                )

        if expired_count > 0:
            self._save_all(pending)
        return expired_count

    # ── config 원자 업데이트 ──────────────────────────

    def _build_patches(self, change: PendingChange) -> dict[str, Any]:
        """변경 내역에서 config.yaml 패치를 생성한다."""
        from strategy.strategy_params import EvolvableParams

        current = EvolvableParams.from_dict(change.current_params)
        proposed = EvolvableParams.from_dict(change.proposed_params)
        return proposed.to_config_patches(current)

    def _apply_config_patches(self, patches: dict[str, Any]) -> None:
        """config.yaml에 패치를 원자적으로 적용한다.

        기존 daemon.py의 패턴 재사용:
        1. 백업 생성
        2. 파일 잠금 (fcntl)
        3. YAML read → merge → atomic write
        """
        config_path = self._config_path

        # 1. 백업
        backup_path = config_path.with_suffix(
            f".yaml.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        shutil.copy2(config_path, backup_path)
        logger.info("config 백업: %s", backup_path)

        # 2. 파일 잠금 후 read-modify-write
        with open(config_path, "r+", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                try:
                    raw = yaml.safe_load(f)
                except yaml.YAMLError as e:
                    logger.error("config YAML 파싱 실패: %s — 백업에서 복구", e)
                    shutil.copy2(backup_path, config_path)
                    raise RuntimeError(
                        f"config YAML 손상, 백업으로 복구됨: {e}"
                    ) from e

                # 3. 패치 병합 (중첩 딕셔너리)
                self._deep_merge(raw, patches)

                # 4. 원자적 쓰기
                tmp_fd, tmp_path = tempfile.mkstemp(
                    dir=str(config_path.parent),
                    suffix=".yaml.tmp",
                )
                try:
                    with os.fdopen(tmp_fd, "w", encoding="utf-8") as tmp_f:
                        yaml.dump(
                            raw,
                            tmp_f,
                            default_flow_style=False,
                            allow_unicode=True,
                            sort_keys=False,
                        )
                    os.replace(tmp_path, str(config_path))
                except Exception:
                    os.unlink(tmp_path)
                    raise
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

        logger.info("config 패치 적용: %s", list(patches.keys()))

    @staticmethod
    def _deep_merge(base: dict, patch: dict) -> None:
        """중첩 딕셔너리를 재귀적으로 병합한다 (base를 in-place 수정)."""
        for key, value in patch.items():
            if (
                key in base
                and isinstance(base[key], dict)
                and isinstance(value, dict)
            ):
                ApprovalWorkflow._deep_merge(base[key], value)
            else:
                base[key] = value

    # ── JSON 저장/로드 ───────────────────────────────

    def _load_all(self) -> dict[str, Any]:
        """pending_changes.json 로드."""
        if not self._pending_path.exists():
            return {}
        try:
            with open(self._pending_path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            logger.warning("pending_changes.json 파싱 실패, 초기화")
            return {}

    def _save_all(self, data: dict[str, Any]) -> None:
        """pending_changes.json 저장 (원자적)."""
        tmp_path = self._pending_path.with_suffix(".json.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(str(tmp_path), str(self._pending_path))
