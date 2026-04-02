"""상태 영속화 모듈.

data/app_state.json 읽기/쓰기. 재시작 시 상태 복원.
DD 상태, Pool 잔액, 포지션, 런타임 플래그 저장.
migration_complete 플래그가 True이면 StateStore(bot.db)로 위임한다.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from app.state_store import StateStore

logger = logging.getLogger(__name__)

DEFAULT_STATE_PATH = "data/app_state.json"


class StateStorage:
    """JSON 상태 영속화. migration_complete 이후 StateStore로 위임."""

    def __init__(self, path: str | Path = DEFAULT_STATE_PATH) -> None:
        """초기화.

        Args:
            path: 상태 파일 경로.
        """
        self._path = Path(path)
        self._state: dict[str, Any] = {}
        self._store: StateStore | None = None
        self._try_init_store()
        self.load()

    def _try_init_store(self) -> None:
        """bot.db가 존재하고 migration_complete이면 StateStore를 초기화한다."""
        try:
            bot_db = Path("data/bot.db")
            if bot_db.exists():
                store = StateStore(db_path=bot_db)
                if store.is_migration_complete():
                    self._store = store
                    logger.info("StateStorage: bot.db 위임 모드")
                else:
                    store.close()
        except (OSError, ValueError) as exc:
            logger.debug("StateStore 초기화 실패 — JSON fallback: %s", exc)

    def load(self) -> dict[str, Any]:
        """저장된 상태를 로딩한다.

        Returns:
            상태 딕셔너리.
        """
        if self._store is not None:
            # bot.db에서 모든 키를 로딩
            for key in self._store.all_keys():
                if key.startswith("__"):
                    continue
                val = self._store.get(key)
                if val is not None:
                    self._state[key] = val
            logger.info("상태 복원 (bot.db): %d키", len(self._state))
            return self._state

        # 기존 JSON fallback
        if self._path.exists():
            try:
                with open(self._path, encoding="utf-8") as f:
                    self._state = json.load(f)
                logger.info("상태 복원: %s", self._path)
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                logger.exception("상태 로딩 실패, 초기화: %s", exc)
                self._state = {}
        return self._state

    def save(self) -> None:
        """상태를 저장한다. migration_complete이면 bot.db, 아니면 JSON atomic write."""
        if self._store is not None:
            for key, value in self._state.items():
                self._store.set(key, value)
            return

        # 기존 JSON atomic write
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(
                dir=str(self._path.parent),
                suffix=".tmp",
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._state, f, indent=2, ensure_ascii=False)
            os.replace(tmp, str(self._path))
        except OSError as exc:
            logger.exception("상태 저장 실패: %s", exc)
            # 임시파일 정리
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    def get(self, key: str, default: Any = None) -> Any:
        """상태 값을 조회한다."""
        return self._state.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """상태 값을 설정한다."""
        self._state[key] = value

    def update(self, data: dict[str, Any]) -> None:
        """상태를 일괄 갱신한다."""
        self._state.update(data)

    @property
    def state(self) -> dict[str, Any]:
        """전체 상태를 반환한다."""
        return self._state

    @property
    def state_store(self) -> StateStore | None:
        """내부 StateStore 인스턴스를 반환한다. 마이그레이션 미완료 시 None."""
        return self._store
