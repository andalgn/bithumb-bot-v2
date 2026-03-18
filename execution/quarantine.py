"""격리 시스템 모듈.

종목 격리 (3회 실패 → 120초), 전역 격리 (8회 실패 → 60초),
인증 오류 (1회 → 600초). 300초 비활성 후 카운트 리셋.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

INACTIVE_RESET_SEC = 300


@dataclass
class QuarantineState:
    """격리 상태."""

    # 종목별 실패 카운트
    coin_failures: dict[str, int] = field(default_factory=dict)
    # 종목별 격리 해제 시각 (epoch sec)
    coin_until: dict[str, float] = field(default_factory=dict)
    # 종목별 마지막 실패 시각
    coin_last_failure: dict[str, float] = field(default_factory=dict)
    # 전역 실패 카운트
    global_failures: int = 0
    # 전역 격리 해제 시각
    global_until: float = 0.0
    # 전역 마지막 실패 시각
    global_last_failure: float = 0.0
    # 인증 오류 격리 해제 시각
    auth_until: float = 0.0


class QuarantineManager:
    """격리 관리자."""

    def __init__(
        self,
        coin_fail_limit: int = 3,
        coin_quarantine_sec: int = 120,
        global_fail_limit: int = 8,
        global_quarantine_sec: int = 60,
        auth_quarantine_sec: int = 600,
        state_path: str | Path = "data/quarantine_state.json",
    ) -> None:
        """초기화.

        Args:
            coin_fail_limit: 종목 격리 실패 횟수.
            coin_quarantine_sec: 종목 격리 시간(초).
            global_fail_limit: 전역 격리 실패 횟수.
            global_quarantine_sec: 전역 격리 시간(초).
            auth_quarantine_sec: 인증 오류 격리 시간(초).
            state_path: 상태 영속화 경로.
        """
        self._coin_fail_limit = coin_fail_limit
        self._coin_quarantine_sec = coin_quarantine_sec
        self._global_fail_limit = global_fail_limit
        self._global_quarantine_sec = global_quarantine_sec
        self._auth_quarantine_sec = auth_quarantine_sec
        self._state_path = Path(state_path)
        self._state = QuarantineState()
        self._load_state()

    def _load_state(self) -> None:
        """저장된 상태를 복원한다."""
        if self._state_path.exists():
            try:
                with open(self._state_path, encoding="utf-8") as f:
                    data = json.load(f)
                self._state = QuarantineState(
                    coin_failures=data.get("coin_failures", {}),
                    coin_until={k: float(v) for k, v in data.get("coin_until", {}).items()},
                    coin_last_failure={
                        k: float(v) for k, v in data.get("coin_last_failure", {}).items()
                    },
                    global_failures=data.get("global_failures", 0),
                    global_until=data.get("global_until", 0.0),
                    global_last_failure=data.get("global_last_failure", 0.0),
                    auth_until=data.get("auth_until", 0.0),
                )
            except Exception:
                logger.exception("격리 상태 로딩 실패, 초기화")

    def _save_state(self) -> None:
        """상태를 파일에 저장한다."""
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "coin_failures": self._state.coin_failures,
            "coin_until": self._state.coin_until,
            "coin_last_failure": self._state.coin_last_failure,
            "global_failures": self._state.global_failures,
            "global_until": self._state.global_until,
            "global_last_failure": self._state.global_last_failure,
            "auth_until": self._state.auth_until,
        }
        with open(self._state_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def _check_inactive_reset(self, now: float) -> None:
        """300초 비활성 후 카운트를 리셋한다."""
        # 종목별
        for coin in list(self._state.coin_last_failure.keys()):
            last = self._state.coin_last_failure.get(coin, 0)
            if now - last > INACTIVE_RESET_SEC:
                self._state.coin_failures.pop(coin, None)
                self._state.coin_last_failure.pop(coin, None)

        # 전역
        if (
            self._state.global_last_failure > 0
            and now - self._state.global_last_failure > INACTIVE_RESET_SEC
        ):
            self._state.global_failures = 0

    def record_failure(self, coin: str, is_auth_error: bool = False) -> None:
        """실패를 기록하고 필요 시 격리를 발동한다.

        Args:
            coin: 코인 심볼.
            is_auth_error: 인증 오류 여부.
        """
        now = time.time()

        if is_auth_error:
            self._state.auth_until = now + self._auth_quarantine_sec
            logger.warning("인증 오류 — %d초 전체 격리", self._auth_quarantine_sec)
            self._save_state()
            return

        # 비활성 리셋 확인
        self._check_inactive_reset(now)

        # 종목별 실패
        self._state.coin_failures[coin] = self._state.coin_failures.get(coin, 0) + 1
        self._state.coin_last_failure[coin] = now

        if self._state.coin_failures[coin] >= self._coin_fail_limit:
            self._state.coin_until[coin] = now + self._coin_quarantine_sec
            self._state.coin_failures[coin] = 0
            logger.warning("%s 종목 격리 — %d초", coin, self._coin_quarantine_sec)

        # 전역 실패
        self._state.global_failures += 1
        self._state.global_last_failure = now

        if self._state.global_failures >= self._global_fail_limit:
            self._state.global_until = now + self._global_quarantine_sec
            self._state.global_failures = 0
            logger.warning("전역 격리 — %d초", self._global_quarantine_sec)

        self._save_state()

    def is_coin_quarantined(self, coin: str) -> bool:
        """종목이 격리 중인지 확인한다.

        Args:
            coin: 코인 심볼.

        Returns:
            격리 중이면 True.
        """
        now = time.time()
        return now < self._state.coin_until.get(coin, 0)

    def is_globally_quarantined(self) -> bool:
        """전역 격리 중인지 확인한다."""
        return time.time() < self._state.global_until

    def is_auth_quarantined(self) -> bool:
        """인증 오류 격리 중인지 확인한다."""
        return time.time() < self._state.auth_until

    def is_blocked(self, coin: str) -> bool:
        """주어진 코인이 어떤 이유로든 격리 중인지 확인한다.

        Args:
            coin: 코인 심볼.

        Returns:
            격리 중이면 True.
        """
        return (
            self.is_auth_quarantined()
            or self.is_globally_quarantined()
            or self.is_coin_quarantined(coin)
        )

    def record_success(self) -> None:
        """성공을 기록하여 비활성 리셋 타이머를 갱신한다."""
        self._check_inactive_reset(time.time())
