"""상태 영속화 모듈.

data/app_state.json 읽기/쓰기. 재시작 시 상태 복원.
DD 상태, Pool 잔액, 포지션, 런타임 플래그 저장.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_STATE_PATH = "data/app_state.json"


class StateStorage:
    """JSON 상태 영속화."""

    def __init__(self, path: str | Path = DEFAULT_STATE_PATH) -> None:
        """초기화.

        Args:
            path: 상태 파일 경로.
        """
        self._path = Path(path)
        self._state: dict[str, Any] = {}
        self.load()

    def load(self) -> dict[str, Any]:
        """저장된 상태를 로딩한다.

        Returns:
            상태 딕셔너리.
        """
        if self._path.exists():
            try:
                with open(self._path, encoding="utf-8") as f:
                    self._state = json.load(f)
                logger.info("상태 복원: %s", self._path)
            except Exception:
                logger.exception("상태 로딩 실패, 초기화")
                self._state = {}
        return self._state

    def save(self) -> None:
        """상태를 파일에 저장한다."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._state, f, indent=2, ensure_ascii=False)
        except Exception:
            logger.exception("상태 저장 실패")

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
