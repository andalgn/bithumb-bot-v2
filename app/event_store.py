"""시스템 이벤트 감사 로그 (Event Sourcing).

모든 시스템 이벤트를 불변(immutable) SQLite 로그에 기록.
충돌 복구 + 규제 감사 추적 + 자동 진단용 구조화된 컨텍스트.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Event:
    """시스템 이벤트 (불변)."""

    ts: float  # Unix timestamp (초)
    event_type: str  # "order_placed", "order_rejected", "health_check_failed", etc.
    component: str  # "order_manager", "price_feed", "risk_gate", etc.
    severity: str  # "INFO", "WARN", "ERROR", "CRITICAL"
    data: dict[str, Any]  # 이벤트별 컨텍스트

    def to_dict(self) -> dict[str, Any]:
        """딕셔너리로 변환 (직렬화용)."""
        return asdict(self)

    def to_json(self) -> str:
        """JSON 문자열로 변환."""
        d = self.to_dict()
        return json.dumps(d, ensure_ascii=False)


class EventStore:
    """불변 감사 로그 (SQLite + WAL)."""

    def __init__(self, db_path: str | Path = "data/journal.db") -> None:
        """초기화.

        Args:
            db_path: SQLite DB 경로. 기존 journal.db를 재사용.
        """
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()
        logger.info("EventStore 초기화: %s", self._db_path)

    def _init_schema(self) -> None:
        """이벤트 테이블 생성."""
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS system_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                event_type TEXT NOT NULL,
                component TEXT NOT NULL,
                severity TEXT NOT NULL,
                data TEXT NOT NULL,
                inserted_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_events_ts ON system_events(ts)")
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_type ON system_events(event_type)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_severity ON system_events(severity)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_component ON system_events(component)"
        )
        self._conn.commit()

    def record(self, event: Event) -> None:
        """이벤트를 불변 로그에 기록.

        Args:
            event: 기록할 Event 객체.
        """
        self._conn.execute(
            """INSERT INTO system_events
               (ts, event_type, component, severity, data)
               VALUES (?, ?, ?, ?, ?)""",
            (event.ts, event.event_type, event.component, event.severity, event.to_json()),
        )
        self._conn.commit()

    def query_recent(
        self,
        event_type: str | None = None,
        severity: str | None = None,
        component: str | None = None,
        minutes: int = 60,
        limit: int = 100,
    ) -> list[Event]:
        """최근 이벤트를 조회.

        Args:
            event_type: 필터링할 event_type (optional).
            severity: 필터링할 severity (optional).
            component: 필터링할 component (optional).
            minutes: 지난 N분간의 이벤트.
            limit: 반환할 최대 레코드 수.

        Returns:
            Event 객체 리스트 (최신순).
        """
        query = "SELECT ts, event_type, component, severity, data FROM system_events WHERE ts > ?"
        params: list[Any] = [time.time() - minutes * 60]

        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)
        if severity:
            query += " AND severity = ?"
            params.append(severity)
        if component:
            query += " AND component = ?"
            params.append(component)

        query += " ORDER BY ts DESC LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(query, params).fetchall()
        return [
            Event(
                ts=r[0],
                event_type=r[1],
                component=r[2],
                severity=r[3],
                data=json.loads(r[4]),
            )
            for r in rows
        ]

    def get_errors_since(self, minutes: int = 120) -> list[Event]:
        """최근 N분간의 모든 ERROR/CRITICAL 이벤트를 반환.

        Args:
            minutes: 지난 N분.

        Returns:
            severity가 ERROR 또는 CRITICAL인 Event 리스트.
        """
        cutoff = time.time() - minutes * 60
        rows = self._conn.execute(
            """SELECT ts, event_type, component, severity, data FROM system_events
               WHERE ts > ? AND severity IN ('ERROR', 'CRITICAL')
               ORDER BY ts DESC""",
            (cutoff,),
        ).fetchall()
        return [
            Event(
                ts=r[0],
                event_type=r[1],
                component=r[2],
                severity=r[3],
                data=json.loads(r[4]),
            )
            for r in rows
        ]

    def get_error_pattern(self, minutes: int = 60) -> dict[str, int]:
        """N분간의 error_type별 count를 반환 (Claude 진단용).

        Returns:
            {"order_rejected": 3, "api_timeout": 2, ...}
        """
        cutoff = time.time() - minutes * 60
        rows = self._conn.execute(
            """SELECT event_type, COUNT(*) FROM system_events
               WHERE ts > ? AND severity IN ('ERROR', 'CRITICAL')
               GROUP BY event_type""",
            (cutoff,),
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def cleanup_old_events(self, days: int = 7) -> int:
        """N일 이상 된 이벤트를 삭제.

        Args:
            days: 보관 기간(일).

        Returns:
            삭제된 레코드 수.
        """
        cutoff = time.time() - days * 86400
        cursor = self._conn.execute(
            "DELETE FROM system_events WHERE ts < ?",
            (cutoff,),
        )
        self._conn.commit()
        deleted = cursor.rowcount
        if deleted > 0:
            logger.info("EventStore 정리: %d건 삭제 (>%d일)", deleted, days)
        return deleted

    def close(self) -> None:
        """DB 연결 종료."""
        self._conn.close()

    def __del__(self) -> None:
        """GC 시 자동 종료."""
        try:
            self._conn.close()
        except sqlite3.Error:
            pass


# 싱글톤 인스턴스 (전역 접근용)
_event_store_instance: EventStore | None = None


def get_event_store(db_path: str | Path = "data/journal.db") -> EventStore:
    """전역 EventStore 인스턴스를 반환 (또는 생성).

    Args:
        db_path: DB 경로 (첫 호출 시만 사용).

    Returns:
        EventStore 인스턴스.
    """
    global _event_store_instance
    if _event_store_instance is None:
        _event_store_instance = EventStore(db_path)
    return _event_store_instance
