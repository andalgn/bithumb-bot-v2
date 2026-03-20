"""장기 시장 데이터 축적 모듈.

SQLite에 5M/15M/1H 캔들 + 호가창 스냅샷을 장기 저장한다.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path

from app.data_types import Candle, Orderbook

logger = logging.getLogger(__name__)

# 보관 정책 (일)
DEFAULT_RETENTION = {
    "5m": 180,
    "15m": -1,  # 영구
    "1h": -1,   # 영구
    "orderbook": 90,
}

DAY_SEC = 86400


class MarketStore:
    """장기 시장 데이터 저장소."""

    def __init__(
        self,
        db_path: str | Path = "data/market_data.db",
        retention: dict[str, int] | None = None,
    ) -> None:
        """초기화.

        Args:
            db_path: SQLite DB 파일 경로.
            retention: 보관 정책 (일). -1이면 영구.
        """
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._retention = retention or DEFAULT_RETENTION
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._create_tables()

    def _create_tables(self) -> None:
        """테이블을 생성한다."""
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS candles (
                symbol TEXT NOT NULL,
                interval TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                PRIMARY KEY (symbol, interval, timestamp)
            );
            CREATE INDEX IF NOT EXISTS idx_candles_lookup
                ON candles(symbol, interval, timestamp);

            CREATE TABLE IF NOT EXISTS orderbook_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                bids TEXT NOT NULL,
                asks TEXT NOT NULL,
                spread_pct REAL NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ob_symbol_ts
                ON orderbook_snapshots(symbol, timestamp);
        """)
        self._conn.commit()

    def store_candles(
        self, symbol: str, interval: str, candles: list[Candle]
    ) -> int:
        """캔들 데이터를 저장한다.

        Args:
            symbol: 코인 심볼.
            interval: 캔들 간격.
            candles: 캔들 리스트.

        Returns:
            저장된 레코드 수.
        """
        if not candles:
            return 0
        rows = [
            (symbol, interval, c.timestamp, c.open, c.high, c.low, c.close, c.volume)
            for c in candles
        ]
        self._conn.executemany(
            """INSERT OR IGNORE INTO candles
               (symbol, interval, timestamp, open, high, low, close, volume)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        self._conn.commit()
        return len(rows)

    def store_orderbook(self, symbol: str, orderbook: Orderbook) -> None:
        """호가창 스냅샷을 저장한다.

        Args:
            symbol: 코인 심볼.
            orderbook: 호가창 데이터.
        """
        bids_json = json.dumps(
            [{"price": b.price, "quantity": b.quantity} for b in orderbook.bids]
        )
        asks_json = json.dumps(
            [{"price": a.price, "quantity": a.quantity} for a in orderbook.asks]
        )
        self._conn.execute(
            """INSERT INTO orderbook_snapshots
               (symbol, timestamp, bids, asks, spread_pct, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                symbol,
                orderbook.timestamp,
                bids_json,
                asks_json,
                orderbook.spread_pct,
                int(time.time() * 1000),
            ),
        )
        self._conn.commit()

    def get_candles(
        self, symbol: str, interval: str, limit: int = 200
    ) -> list[Candle]:
        """저장된 캔들을 조회한다.

        Args:
            symbol: 코인 심볼.
            interval: 캔들 간격.
            limit: 최대 개수.

        Returns:
            Candle 리스트 (오래된 순).
        """
        rows = self._conn.execute(
            """SELECT timestamp, open, high, low, close, volume
               FROM candles
               WHERE symbol = ? AND interval = ?
               ORDER BY timestamp DESC
               LIMIT ?""",
            (symbol, interval, limit),
        ).fetchall()
        return [
            Candle(timestamp=r[0], open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5])
            for r in reversed(rows)
        ]

    def cleanup(self) -> int:
        """보관 기간 지난 데이터를 삭제한다.

        Returns:
            삭제된 레코드 수.
        """
        now_ms = int(time.time() * 1000)
        total_deleted = 0

        for interval, days in self._retention.items():
            if days < 0:
                continue
            if interval == "orderbook":
                cutoff = now_ms - days * DAY_SEC * 1000
                cursor = self._conn.execute(
                    "DELETE FROM orderbook_snapshots WHERE created_at < ?",
                    (cutoff,),
                )
            else:
                cutoff = now_ms - days * DAY_SEC * 1000
                cursor = self._conn.execute(
                    "DELETE FROM candles WHERE interval = ? AND timestamp < ?",
                    (interval, cutoff),
                )
            total_deleted += cursor.rowcount

        self._conn.commit()
        if total_deleted > 0:
            logger.info("MarketStore 정리: %d건 삭제", total_deleted)
        return total_deleted

    def close(self) -> None:
        """DB 연결을 닫는다."""
        self._conn.close()
