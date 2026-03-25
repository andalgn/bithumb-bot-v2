"""SQLite 기반 단일 상태 저장소.

WAL 모드. 키-값 행 단위 저장으로 부분 롤백 지원.
migration_complete 플래그로 구 방식 fallback 제어.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at INTEGER NOT NULL
);
"""

_MIGRATION_KEY = "__migration_complete__"


class StateStore:
    """SQLite 기반 키-값 상태 저장소."""

    def __init__(self, db_path: str | Path = "data/bot.db") -> None:
        """초기화.

        Args:
            db_path: bot.db 경로.
        """
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        logger.info("StateStore 초기화: %s", self._path)

    def get(self, key: str, default: Any = None) -> Any:
        """키에 해당하는 값을 반환한다.

        Args:
            key: 조회할 키.
            default: 키가 없을 때 반환할 기본값.

        Returns:
            저장된 값 (JSON 역직렬화) 또는 default.
        """
        row = self._conn.execute(
            "SELECT value FROM app_state WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return default
        return json.loads(row[0])

    def set(self, key: str, value: Any) -> None:
        """키-값 쌍을 저장한다.

        Args:
            key: 저장할 키.
            value: JSON 직렬화 가능한 값.
        """
        self._conn.execute(
            "INSERT OR REPLACE INTO app_state (key, value, updated_at) VALUES (?, ?, ?)",
            (key, json.dumps(value, ensure_ascii=False), int(time.time())),
        )
        self._conn.commit()

    def all_keys(self) -> list[str]:
        """저장된 모든 키 목록을 반환한다."""
        rows = self._conn.execute("SELECT key FROM app_state").fetchall()
        return [r[0] for r in rows]

    def is_migration_complete(self) -> bool:
        """마이그레이션 완료 여부를 반환한다."""
        return self.get(_MIGRATION_KEY) is True

    def set_migration_complete(self) -> None:
        """마이그레이션 완료 플래그를 기록한다."""
        self.set(_MIGRATION_KEY, True)

    def close(self) -> None:
        """DB 연결을 닫는다."""
        self._conn.close()

    def __del__(self) -> None:
        """GC 시 연결을 자동으로 닫는다."""
        try:
            self._conn.close()
        except sqlite3.Error:
            pass
