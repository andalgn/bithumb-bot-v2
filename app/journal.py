"""거래 기록 모듈.

SQLite WAL 모드. Trade Schema 21필드.
테이블: signals, executions, risk_events, feedback, shadow_trades.
90일 자동 정리.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

RETENTION_DAYS = 90
TRADES_RETENTION_DAYS = 365  # trades는 1년 보관
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
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
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
                tag TEXT DEFAULT 'untagged',
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

            CREATE TABLE IF NOT EXISTS backtest_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_type TEXT NOT NULL,
                verdict TEXT NOT NULL,
                details TEXT,
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
        # 기존 DB에 tag 컬럼이 없을 경우 마이그레이션
        try:
            self._conn.execute("ALTER TABLE trades ADD COLUMN tag TEXT DEFAULT 'untagged'")
            self._conn.commit()
        except sqlite3.OperationalError:
            pass  # 이미 존재하는 컬럼 — 무시

        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS health_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                score INTEGER NOT NULL,
                verdict TEXT NOT NULL,
                results_json TEXT NOT NULL,
                alerts_json TEXT DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS reflections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id TEXT,
                strategy TEXT NOT NULL,
                regime_entry TEXT NOT NULL,
                regime_exit TEXT NOT NULL,
                tag TEXT NOT NULL,
                reflection_text TEXT NOT NULL,
                lesson TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
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
                exit_reason, tag, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                trade_data.get("tag", "untagged"),
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

    def record_shadow_trade(self, data: dict[str, Any]) -> None:
        """Shadow 거래를 기록한다."""
        now = int(time.time() * 1000)
        self._conn.execute(
            """INSERT INTO shadow_trades
               (shadow_id, symbol, strategy, params_json, would_enter, signal_score, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                data["shadow_id"],
                data["symbol"],
                data["strategy"],
                data.get("params_json", ""),
                data.get("would_enter", 0),
                data.get("signal_score", 0),
                now,
            ),
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

    def get_trade_count(self) -> int:
        """전체 거래 수를 반환한다."""
        row = self._conn.execute("SELECT COUNT(*) FROM trades").fetchone()
        return row[0] if row else 0

    def get_recent_trades(self, strategy: str = "", limit: int = 50) -> list[dict]:
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

    def get_trades_since(self, timestamp_sec: int) -> list[dict]:
        """지정 시각 이후의 거래를 조회한다."""
        timestamp_ms = timestamp_sec * 1000
        rows = self._conn.execute(
            "SELECT * FROM trades WHERE exit_time >= ?",
            (timestamp_ms,),
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

    def record_health_check(self, score: int, verdict: str, results: list[dict], alerts: list[dict]) -> None:
        """헬스 체크 결과를 기록한다."""
        self._conn.execute(
            "INSERT INTO health_checks (score, verdict, results_json, alerts_json) VALUES (?, ?, ?, ?)",
            (score, verdict, json.dumps(results, ensure_ascii=False), json.dumps(alerts, ensure_ascii=False)),
        )
        self._conn.commit()

    def get_recent_health_checks(self, limit: int = 96) -> list[dict]:
        """최근 헬스 체크 결과를 반환한다."""
        rows = self._conn.execute(
            "SELECT score, verdict, results_json, alerts_json, created_at FROM health_checks ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {"score": r[0], "verdict": r[1], "results": json.loads(r[2]), "alerts": json.loads(r[3]), "created_at": r[4]}
            for r in rows
        ]

    def record_reflection(
        self,
        trade_id: str,
        strategy: str,
        regime_entry: str,
        regime_exit: str,
        tag: str,
        reflection_text: str,
        lesson: str,
    ) -> None:
        """거래 반성 기록을 저장한다."""
        self._conn.execute(
            """INSERT INTO reflections
               (trade_id, strategy, regime_entry, regime_exit, tag, reflection_text, lesson)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (trade_id, strategy, regime_entry, regime_exit, tag, reflection_text, lesson),
        )
        self._conn.commit()

    def get_recent_reflections(self, limit: int = 50) -> list[dict]:
        """최근 반성 기록을 반환한다."""
        rows = self._conn.execute(
            """SELECT trade_id, strategy, regime_entry, regime_exit, tag,
                      reflection_text, lesson, created_at
               FROM reflections ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [
            {
                "trade_id": r[0], "strategy": r[1],
                "regime_entry": r[2], "regime_exit": r[3], "tag": r[4],
                "reflection_text": r[5], "lesson": r[6], "created_at": r[7],
            }
            for r in rows
        ]

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

        # trades는 1년 보관
        trades_cutoff = int(time.time() * 1000) - TRADES_RETENTION_DAYS * DAY_MS
        cursor = self._conn.execute(
            "DELETE FROM trades WHERE created_at < ?",
            (trades_cutoff,),
        )
        total += cursor.rowcount

        cursor = self._conn.execute("DELETE FROM health_checks WHERE created_at < datetime('now', '-90 days')")
        total += cursor.rowcount

        self._conn.execute("DELETE FROM reflections WHERE created_at < datetime('now', '-90 days')")

        self._conn.commit()
        if total > 0:
            logger.info("Journal 정리: %d건 삭제", total)
        return total

    def close(self) -> None:
        """DB 연결을 닫는다."""
        self._conn.close()
