"""거래 기록 모듈.

SQLite WAL 모드. Trade Schema 21필드.
테이블: signals, executions, risk_events, feedback, shadow_trades.
90일 자동 정리.
"""

from __future__ import annotations

import logging
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

RETENTION_DAYS = 90
DAY_MS = 86400 * 1000


class Journal:
    """거래 기록 저장소."""

    def __init__(self, db_path: str | Path = "data/journal.db") -> None:
        """초기화.

        Args:
            db_path: SQLite DB 파일 경로.
        """
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._create_tables()

    def _create_tables(self) -> None:
        """전체 테이블을 생성한다."""
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS trades (
                trade_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                strategy TEXT NOT NULL,
                tier INTEGER NOT NULL,
                regime TEXT NOT NULL,
                pool TEXT NOT NULL,
                entry_price REAL,
                exit_price REAL,
                qty REAL,
                entry_fee_krw REAL DEFAULT 0,
                exit_fee_krw REAL DEFAULT 0,
                slippage_krw REAL DEFAULT 0,
                gross_pnl_krw REAL DEFAULT 0,
                net_pnl_krw REAL DEFAULT 0,
                net_pnl_pct REAL DEFAULT 0,
                hold_seconds INTEGER DEFAULT 0,
                promoted INTEGER DEFAULT 0,
                entry_score REAL DEFAULT 0,
                entry_time INTEGER,
                exit_time INTEGER,
                exit_reason TEXT,
                created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
            CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy);
            CREATE INDEX IF NOT EXISTS idx_trades_entry_time ON trades(entry_time);

            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                strategy TEXT NOT NULL,
                score REAL,
                regime TEXT,
                tier INTEGER,
                entry_price REAL,
                stop_loss REAL,
                take_profit REAL,
                accepted INTEGER DEFAULT 0,
                reject_reason TEXT DEFAULT '',
                created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_signals_time ON signals(created_at);

            CREATE TABLE IF NOT EXISTS executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id TEXT,
                ticket_id TEXT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                price REAL,
                qty REAL,
                filled_price REAL,
                filled_qty REAL,
                status TEXT NOT NULL,
                error_msg TEXT DEFAULT '',
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS risk_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                priority TEXT NOT NULL,
                symbol TEXT DEFAULT '',
                detail TEXT DEFAULT '',
                created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_risk_time ON risk_events(created_at);

            CREATE TABLE IF NOT EXISTS shadow_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shadow_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                strategy TEXT NOT NULL,
                params_json TEXT DEFAULT '{}',
                would_enter INTEGER DEFAULT 0,
                signal_score REAL DEFAULT 0,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id TEXT,
                feedback_type TEXT NOT NULL,
                content TEXT DEFAULT '',
                created_at INTEGER NOT NULL
            );
        """)
        self._conn.commit()

    def record_trade(self, trade_data: dict[str, Any]) -> str:
        """거래를 기록한다.

        Args:
            trade_data: Trade Schema 21필드 딕셔너리.

        Returns:
            trade_id.
        """
        trade_id = trade_data.get("trade_id", str(uuid.uuid4())[:8])
        now = int(time.time() * 1000)

        self._conn.execute(
            """INSERT OR REPLACE INTO trades
               (trade_id, symbol, strategy, tier, regime, pool,
                entry_price, exit_price, qty, entry_fee_krw, exit_fee_krw,
                slippage_krw, gross_pnl_krw, net_pnl_krw, net_pnl_pct,
                hold_seconds, promoted, entry_score, entry_time, exit_time,
                exit_reason, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                trade_id,
                trade_data.get("symbol", ""),
                trade_data.get("strategy", ""),
                trade_data.get("tier", 2),
                trade_data.get("regime", ""),
                trade_data.get("pool", ""),
                trade_data.get("entry_price"),
                trade_data.get("exit_price"),
                trade_data.get("qty"),
                trade_data.get("entry_fee_krw", 0),
                trade_data.get("exit_fee_krw", 0),
                trade_data.get("slippage_krw", 0),
                trade_data.get("gross_pnl_krw", 0),
                trade_data.get("net_pnl_krw", 0),
                trade_data.get("net_pnl_pct", 0),
                trade_data.get("hold_seconds", 0),
                1 if trade_data.get("promoted") else 0,
                trade_data.get("entry_score", 0),
                trade_data.get("entry_time"),
                trade_data.get("exit_time"),
                trade_data.get("exit_reason", ""),
                now,
            ),
        )
        self._conn.commit()
        return trade_id

    def record_signal(self, signal_data: dict[str, Any]) -> None:
        """신호를 기록한다."""
        now = int(time.time() * 1000)
        self._conn.execute(
            """INSERT INTO signals
               (symbol, direction, strategy, score, regime, tier,
                entry_price, stop_loss, take_profit, accepted, reject_reason, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                signal_data.get("symbol", ""),
                signal_data.get("direction", ""),
                signal_data.get("strategy", ""),
                signal_data.get("score", 0),
                signal_data.get("regime", ""),
                signal_data.get("tier", 2),
                signal_data.get("entry_price"),
                signal_data.get("stop_loss"),
                signal_data.get("take_profit"),
                1 if signal_data.get("accepted") else 0,
                signal_data.get("reject_reason", ""),
                now,
            ),
        )
        self._conn.commit()

    def record_risk_event(
        self, event_type: str, priority: str, symbol: str = "", detail: str = ""
    ) -> None:
        """리스크 이벤트를 기록한다."""
        now = int(time.time() * 1000)
        self._conn.execute(
            """INSERT INTO risk_events
               (event_type, priority, symbol, detail, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (event_type, priority, symbol, detail, now),
        )
        self._conn.commit()

    def record_execution(self, exec_data: dict[str, Any]) -> None:
        """체결 이벤트를 기록한다."""
        now = int(time.time() * 1000)
        self._conn.execute(
            """INSERT INTO executions
               (trade_id, ticket_id, symbol, side, price, qty,
                filled_price, filled_qty, status, error_msg, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                exec_data.get("trade_id", ""),
                exec_data.get("ticket_id", ""),
                exec_data.get("symbol", ""),
                exec_data.get("side", ""),
                exec_data.get("price"),
                exec_data.get("qty"),
                exec_data.get("filled_price"),
                exec_data.get("filled_qty"),
                exec_data.get("status", ""),
                exec_data.get("error_msg", ""),
                now,
            ),
        )
        self._conn.commit()

    def get_recent_trades(
        self, strategy: str = "", limit: int = 50
    ) -> list[dict]:
        """최근 거래를 조회한다."""
        if strategy:
            rows = self._conn.execute(
                """SELECT * FROM trades WHERE strategy = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (strategy, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM trades ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_consecutive_losses(self) -> int:
        """현재 연속 손실 횟수를 조회한다."""
        rows = self._conn.execute(
            "SELECT net_pnl_krw FROM trades ORDER BY rowid DESC LIMIT 20"
        ).fetchall()
        count = 0
        for row in rows:
            if row[0] is not None and row[0] < 0:
                count += 1
            else:
                break
        return count

    def cleanup(self) -> int:
        """90일 지난 데이터를 정리한다.

        Returns:
            삭제된 레코드 수.
        """
        cutoff = int(time.time() * 1000) - RETENTION_DAYS * DAY_MS
        total = 0
        for table in ("signals", "executions", "risk_events", "shadow_trades", "feedback"):
            cursor = self._conn.execute(
                f"DELETE FROM {table} WHERE created_at < ?",  # noqa: S608
                (cutoff,),
            )
            total += cursor.rowcount
        self._conn.commit()
        if total > 0:
            logger.info("Journal 정리: %d건 삭제", total)
        return total

    def close(self) -> None:
        """DB 연결을 닫는다."""
        self._conn.close()
