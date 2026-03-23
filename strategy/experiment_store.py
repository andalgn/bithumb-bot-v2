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

CREATE TABLE IF NOT EXISTS shadow_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shadow_id TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    would_enter INTEGER NOT NULL,
    signal_score REAL NOT NULL,
    virtual_pnl REAL NOT NULL DEFAULT 0.0
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
                continue  # 방향 판단 불가 → 건너뜀
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

    def record_shadow_trade(
        self,
        shadow_id: str,
        symbol: str,
        strategy: str,
        would_enter: bool,
        signal_score: float,
        virtual_pnl: float,
    ) -> None:
        """Shadow 가상 거래를 기록한다."""
        self._conn.execute(
            "INSERT INTO shadow_trades "
            "(shadow_id, timestamp, symbol, strategy, would_enter, signal_score, virtual_pnl) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                shadow_id,
                int(time.time()),
                symbol,
                strategy,
                int(would_enter),
                signal_score,
                virtual_pnl,
            ),
        )
        self._conn.commit()

    def get_shadow_trades(self, shadow_id: str, days: int = 30) -> list[dict]:
        """Shadow의 최근 N일 거래를 조회한다."""
        cutoff = int(time.time()) - days * 86400
        rows = self._conn.execute(
            "SELECT * FROM shadow_trades WHERE shadow_id = ? AND timestamp >= ? ORDER BY timestamp",
            (shadow_id, cutoff),
        ).fetchall()
        return [dict(r) for r in rows]

    def cleanup_old_shadow_trades(self, days: int = 30) -> int:
        """N일 이전 Shadow 거래를 삭제한다."""
        cutoff = int(time.time()) - days * 86400
        cursor = self._conn.execute(
            "DELETE FROM shadow_trades WHERE timestamp < ?",
            (cutoff,),
        )
        self._conn.commit()
        return cursor.rowcount

    def close(self) -> None:
        """연결을 닫는다."""
        self._conn.close()
