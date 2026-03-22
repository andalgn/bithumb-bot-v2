"""Drawdown Kill Switch 모듈.

일일 4%, 주간 8%, 월간 12%, 총 20%.
SELL은 차단하지 않음. 매일 00:00 KST 일일 기준 리셋.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))


@dataclass
class DDState:
    """Drawdown 상태."""

    # 기준 자산 (각 기간 시작 시점)
    daily_base: float = 0.0
    weekly_base: float = 0.0
    monthly_base: float = 0.0
    total_base: float = 0.0

    # 리셋 시각 (epoch sec)
    daily_reset_at: float = 0.0
    weekly_reset_at: float = 0.0
    monthly_reset_at: float = 0.0

    # 현재 자산
    current_equity: float = 0.0


class DDLimits:
    """Drawdown Kill Switch."""

    def __init__(
        self,
        daily_pct: float = 0.04,
        weekly_pct: float = 0.08,
        monthly_pct: float = 0.12,
        total_pct: float = 0.20,
    ) -> None:
        """초기화.

        Args:
            daily_pct: 일일 DD 한도.
            weekly_pct: 주간 DD 한도.
            monthly_pct: 월간 DD 한도.
            total_pct: 총 DD 한도.
        """
        self._daily_pct = daily_pct
        self._weekly_pct = weekly_pct
        self._monthly_pct = monthly_pct
        self._total_pct = total_pct
        self._state = DDState()

    def initialize(self, equity: float) -> None:
        """초기 자산을 설정한다.

        Args:
            equity: 현재 총 자산(KRW).
        """
        now = datetime.now(KST)
        self._state.current_equity = equity
        self._state.total_base = equity

        self._state.daily_base = equity
        self._state.daily_reset_at = self._next_daily_reset(now)

        self._state.weekly_base = equity
        self._state.weekly_reset_at = self._next_weekly_reset(now)

        self._state.monthly_base = equity
        self._state.monthly_reset_at = self._next_monthly_reset(now)

    def _next_daily_reset(self, now: datetime) -> float:
        """다음 00:00 KST를 epoch seconds로 반환한다."""
        tomorrow = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return tomorrow.timestamp()

    def _next_weekly_reset(self, now: datetime) -> float:
        """다음 월요일 00:00 KST를 반환한다.

        월요일이면 오늘 00:00이 아직 안 지났으면 오늘, 지났으면 다음 주 월요일.
        """
        days_ahead = (7 - now.weekday()) % 7
        monday = (now + timedelta(days=days_ahead)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        # 이미 지난 시각이면 다음 주 월요일로
        if monday <= now:
            monday += timedelta(days=7)
        return monday.timestamp()

    def _next_monthly_reset(self, now: datetime) -> float:
        """다음 달 1일 00:00 KST를 반환한다."""
        if now.month == 12:
            first = now.replace(year=now.year + 1, month=1, day=1,
                                hour=0, minute=0, second=0, microsecond=0)
        else:
            first = now.replace(month=now.month + 1, day=1,
                                hour=0, minute=0, second=0, microsecond=0)
        return first.timestamp()

    def _check_resets(self) -> None:
        """기간별 리셋을 확인한다."""
        now = datetime.now(KST)
        now_ts = now.timestamp()

        if now_ts >= self._state.daily_reset_at:
            self._state.daily_base = self._state.current_equity
            self._state.daily_reset_at = self._next_daily_reset(now)
            logger.info("일일 DD 리셋: base=%.0f", self._state.daily_base)

        if now_ts >= self._state.weekly_reset_at:
            self._state.weekly_base = self._state.current_equity
            self._state.weekly_reset_at = self._next_weekly_reset(now)
            logger.info("주간 DD 리셋: base=%.0f", self._state.weekly_base)

        if now_ts >= self._state.monthly_reset_at:
            self._state.monthly_base = self._state.current_equity
            self._state.monthly_reset_at = self._next_monthly_reset(now)
            logger.info("월간 DD 리셋: base=%.0f", self._state.monthly_base)

    def update_equity(self, equity: float) -> None:
        """현재 자산을 갱신한다.

        Args:
            equity: 현재 총 자산(KRW).
        """
        self._state.current_equity = equity
        # total_base만 HWM 갱신 (총 DD는 전고점 기준)
        # daily/weekly/monthly base는 _check_resets()에서 기간 경계 시점에만 설정
        if equity > self._state.total_base:
            self._state.total_base = equity

    def _calc_dd(self, base: float) -> float:
        """DD 비율을 계산한다."""
        if base <= 0:
            return 0.0
        return max(0.0, (base - self._state.current_equity) / base)

    def check_daily(self) -> tuple[bool, float]:
        """일일 DD를 확인한다.

        Returns:
            (차단 여부, 현재 DD 비율).
        """
        self._check_resets()
        dd = self._calc_dd(self._state.daily_base)
        return dd >= self._daily_pct, dd

    def check_weekly(self) -> tuple[bool, float]:
        """주간 DD를 확인한다."""
        dd = self._calc_dd(self._state.weekly_base)
        return dd >= self._weekly_pct, dd

    def check_monthly(self) -> tuple[bool, float]:
        """월간 DD를 확인한다."""
        dd = self._calc_dd(self._state.monthly_base)
        return dd >= self._monthly_pct, dd

    def check_total(self) -> tuple[bool, float]:
        """총 DD를 확인한다."""
        dd = self._calc_dd(self._state.total_base)
        return dd >= self._total_pct, dd

    def is_buy_blocked(self) -> tuple[bool, str]:
        """BUY가 차단되는지 확인한다. SELL은 항상 허용.

        Returns:
            (차단 여부, 차단 사유).
        """
        self._check_resets()

        blocked, dd = self.check_total()
        if blocked:
            return True, f"P2: 총 DD {dd:.1%} (한도 {self._total_pct:.0%})"

        blocked, dd = self.check_monthly()
        if blocked:
            return True, f"P3: 월간 DD {dd:.1%} (한도 {self._monthly_pct:.0%})"

        blocked, dd = self.check_weekly()
        if blocked:
            return True, f"P4: 주간 DD {dd:.1%} (한도 {self._weekly_pct:.0%})"

        blocked, dd = self.check_daily()
        if blocked:
            return True, f"P5: 일일 DD {dd:.1%} (한도 {self._daily_pct:.0%})"

        return False, ""

    @property
    def state(self) -> DDState:
        """현재 DD 상태를 반환한다."""
        return self._state

    def load_state(self, data: dict) -> None:
        """저장된 상태를 복원한다."""
        self._state = DDState(
            daily_base=data.get("daily_base", 0),
            weekly_base=data.get("weekly_base", 0),
            monthly_base=data.get("monthly_base", 0),
            total_base=data.get("total_base", 0),
            daily_reset_at=data.get("daily_reset_at", 0),
            weekly_reset_at=data.get("weekly_reset_at", 0),
            monthly_reset_at=data.get("monthly_reset_at", 0),
            current_equity=data.get("current_equity", 0),
        )

    def dump_state(self) -> dict:
        """상태를 딕셔너리로 반환한다."""
        s = self._state
        return {
            "daily_base": s.daily_base,
            "weekly_base": s.weekly_base,
            "monthly_base": s.monthly_base,
            "total_base": s.total_base,
            "daily_reset_at": s.daily_reset_at,
            "weekly_reset_at": s.weekly_reset_at,
            "monthly_reset_at": s.monthly_reset_at,
            "current_equity": s.current_equity,
        }
