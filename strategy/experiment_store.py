"""실험 기록 + 파라미터 변경 로그 저장소."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp INTEGER NOT NULL,
    source TEXT NOT NULL,
    strategy TEXT NOT NULL,
    params TEXT NOT NULL,
    old_params TEXT,
    pf REAL NOT NULL,
    mdd REAL NOT NULL,
    trades INTEGER NOT NULL,
    verdict TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS param_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp INTEGER NOT NULL,
    source TEXT NOT NULL,
    strategy TEXT NOT NULL,
    old_params TEXT NOT NULL,
    new_params TEXT NOT NULL,
    backup_path TEXT NOT NULL,
    monitoring_until INTEGER NOT NULL,
    baseline_pf REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'monitoring'
);
"""

MONITORING_DAYS = 7


class ExperimentStore:
    """실험 기록 + 파라미터 변경 추적 저장소."""

    def __init__(self, db_path: str = "data/experiment_history.db") -> None:
        """초기화."""
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def record(
        self,
        source: str,
        strategy: str,
        params: dict,
        pf: float,
        mdd: float,
        trades: int,
        verdict: str,
        old_params: dict | None = None,
    ) -> None:
        """실험 결과를 기록한다."""
        self._conn.execute(
            "INSERT INTO experiments "
            "(timestamp, source, strategy, params, old_params, "
            "pf, mdd, trades, verdict) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                int(time.time()),
                source,
                strategy,
                json.dumps(params),
                json.dumps(old_params) if old_params else None,
                pf,
                mdd,
                trades,
                verdict,
            ),
        )
        self._conn.commit()

    def get_history(self, strategy: str, limit: int = 50) -> list[dict]:
        """전략별 실험 이력을 조회한다."""
        rows = self._conn.execute(
            "SELECT * FROM experiments WHERE strategy = ? ORDER BY timestamp DESC LIMIT ?",
            (strategy, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def count_similar_failures(
        self,
        strategy: str,
        param_key: str,
        direction: str,
    ) -> int:
        """유사한 방향의 실패 횟수를 조회한다.

        Args:
            strategy: 전략 이름.
            param_key: 파라미터 키 (예: "sl_mult").
            direction: "increase" 또는 "decrease".
        """
        rows = self._conn.execute(
            "SELECT params, old_params FROM experiments "
            "WHERE strategy = ? AND verdict IN ('revert', 'rolled_back')",
            (strategy,),
        ).fetchall()
        count = 0
        for row in rows:
            params = json.loads(row["params"])
            if param_key not in params:
                continue
            # old_params가 없으면 방향 판단 불가 → 카운트
            old_raw = row["old_params"] if "old_params" in row.keys() else None
            if old_raw is None:
                count += 1
                continue
            old_params = json.loads(old_raw)
            old_val = old_params.get(param_key, 0)
            new_val = params[param_key]
            if direction == "increase" and new_val > old_val:
                count += 1
            elif direction == "decrease" and new_val < old_val:
                count += 1
        return count

    def log_param_change(
        self,
        source: str,
        strategy: str,
        old_params: dict,
        new_params: dict,
        backup_path: str,
        baseline_pf: float,
    ) -> None:
        """파라미터 변경을 로그한다."""
        now = int(time.time())
        self._conn.execute(
            "INSERT INTO param_changes "
            "(timestamp, source, strategy, old_params, new_params, "
            "backup_path, monitoring_until, baseline_pf, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'monitoring')",
            (
                now,
                source,
                strategy,
                json.dumps(old_params),
                json.dumps(new_params),
                backup_path,
                now + MONITORING_DAYS * 86400,
                baseline_pf,
            ),
        )
        self._conn.commit()

    def get_active_changes(self) -> list[dict]:
        """모니터링 중인 변경 건을 조회한다."""
        rows = self._conn.execute(
            "SELECT * FROM param_changes WHERE status = 'monitoring'",
        ).fetchall()
        return [dict(r) for r in rows]

    def update_change_status(self, change_id: int, status: str) -> None:
        """변경 건의 상태를 업데이트한다."""
        self._conn.execute(
            "UPDATE param_changes SET status = ? WHERE id = ?",
            (status, change_id),
        )
        self._conn.commit()

    def close(self) -> None:
        """연결을 닫는다."""
        self._conn.close()
