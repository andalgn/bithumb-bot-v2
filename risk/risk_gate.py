"""통합 리스크 게이트웨이 모듈.

P0~P10 우선순위 체계. 모든 주문은 반드시 이 모듈을 경유해야 한다.
Hard Stop / Soft Stop 구분.
Expected Edge 필터 + 호가 잔량 필터 포함.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from app.data_types import Orderbook, OrderSide, Signal, Tier
from execution.quarantine import QuarantineManager
from risk.dd_limits import DDLimits

logger = logging.getLogger(__name__)

# 수수료 (매수+매도)
TOTAL_FEE_PCT = 0.0050

# Tier별 슬리피지 (매수+매도)
SLIPPAGE_BY_TIER: dict[Tier, float] = {
    Tier.TIER1: 0.0010,
    Tier.TIER2: 0.0020,
    Tier.TIER3: 0.0040,
}

# Tier별 호가 잔량 배수 요건
ORDERBOOK_DEPTH_MULT: dict[Tier, int] = {
    Tier.TIER1: 5,
    Tier.TIER2: 3,
    Tier.TIER3: 2,
}

# Tier별 스프레드 한도
SPREAD_LIMIT: dict[Tier, float] = {
    Tier.TIER1: 0.0018,
    Tier.TIER2: 0.0025,
    Tier.TIER3: 0.0035,
}


@dataclass
class RiskCheckResult:
    """리스크 체크 결과."""

    allowed: bool
    reason: str = ""
    priority: str = ""  # P0~P10
    size_mult: float = 1.0  # 사이즈 조정 배수 (상관관계 필터 등)


@dataclass
class RiskGateState:
    """RiskGate 내부 상태."""

    consecutive_losses: int = 0
    last_entry_time: dict[str, float] = field(default_factory=dict)
    total_exposure_krw: float = 0.0
    total_equity_krw: float = 0.0
    # 전략별 최근 30일 Expectancy (외부에서 주입)
    strategy_expectancy: dict[str, float] = field(default_factory=dict)
    # 전략별 최근 30일 실패율 × 평균손실
    strategy_failure_penalty: dict[str, float] = field(default_factory=dict)


class RiskGate:
    """통합 리스크 게이트웨이."""

    def __init__(
        self,
        dd_limits: DDLimits,
        quarantine: QuarantineManager,
        max_exposure_pct: float = 0.90,
        consecutive_loss_limit: int = 5,
        cooldown_min: int = 60,
        notifier: object | None = None,
    ) -> None:
        """초기화.

        Args:
            dd_limits: DD Kill Switch.
            quarantine: 격리 관리자.
            max_exposure_pct: 최대 익스포저 비율.
            consecutive_loss_limit: 연속 손실 한도.
            cooldown_min: 쿨다운(분).
            notifier: 텔레그램 알림 (선택).
        """
        self._dd = dd_limits
        self._quarantine = quarantine
        self._max_exposure_pct = max_exposure_pct
        self._consecutive_loss_limit = consecutive_loss_limit
        self._cooldown_sec = cooldown_min * 60
        self._notifier = notifier
        self._state = RiskGateState()

    def update_state(
        self,
        total_exposure_krw: float,
        total_equity_krw: float,
    ) -> None:
        """상태를 갱신한다."""
        self._state.total_exposure_krw = total_exposure_krw
        self._state.total_equity_krw = total_equity_krw
        self._dd.update_equity(total_equity_krw)

    def update_strategy_stats(
        self,
        expectancy: dict[str, float],
        failure_penalty: dict[str, float],
    ) -> None:
        """전략별 통계를 갱신한다 (일일 리뷰에서 호출).

        Args:
            expectancy: 전략별 최근 30일 Expectancy.
            failure_penalty: 전략별 실패 페널티.
        """
        self._state.strategy_expectancy = expectancy
        self._state.strategy_failure_penalty = failure_penalty

    def record_trade_result(self, is_loss: bool) -> None:
        """거래 결과를 기록한다."""
        if is_loss:
            self._state.consecutive_losses += 1
        else:
            self._state.consecutive_losses = 0

    def check(
        self,
        signal: Signal,
        orderbook: Orderbook | None = None,
        order_krw: float = 0,
    ) -> RiskCheckResult:
        """신호에 대해 리스크 체크를 수행한다.

        Args:
            signal: 매매 신호.
            orderbook: 호가창 (호가 잔량 필터용).
            order_krw: 주문 금액 (호가 잔량 필터용).

        Returns:
            RiskCheckResult.
        """
        is_buy = signal.direction == OrderSide.BUY

        # P1: 인증 오류 격리
        if self._quarantine.is_auth_quarantined():
            return RiskCheckResult(
                allowed=False,
                reason="P1: 인증 오류 격리 중",
                priority="P1",
            )

        # P2~P5: DD Kill Switch (BUY만 차단)
        if is_buy:
            dd_blocked, dd_reason = self._dd.is_buy_blocked()
            if dd_blocked:
                return RiskCheckResult(
                    allowed=False,
                    reason=dd_reason,
                    priority=dd_reason[:2],
                )

        # P6: 총 익스포저 90% 초과
        if is_buy and self._state.total_equity_krw > 0:
            exposure_pct = (
                self._state.total_exposure_krw / self._state.total_equity_krw
            )
            if exposure_pct >= self._max_exposure_pct:
                return RiskCheckResult(
                    allowed=False,
                    reason=(
                        f"P6: 총 익스포저 {exposure_pct:.1%}"
                        f" (한도 {self._max_exposure_pct:.0%})"
                    ),
                    priority="P6",
                )

        # P7: 전역 격리
        if self._quarantine.is_globally_quarantined():
            return RiskCheckResult(
                allowed=False,
                reason="P7: 전역 격리 중",
                priority="P7",
            )

        # P8: 종목 격리
        if self._quarantine.is_coin_quarantined(signal.symbol):
            return RiskCheckResult(
                allowed=False,
                reason=f"P8: {signal.symbol} 종목 격리 중",
                priority="P8",
            )

        # P9: 연속 손실 5회
        if is_buy and self._state.consecutive_losses >= self._consecutive_loss_limit:
            return RiskCheckResult(
                allowed=False,
                reason=f"P9: 연속 손실 {self._state.consecutive_losses}회",
                priority="P9",
            )

        # P10: 쿨다운 (60분)
        if is_buy:
            last_entry = self._state.last_entry_time.get(signal.symbol, 0)
            elapsed = time.time() - last_entry
            if elapsed < self._cooldown_sec:
                remaining = int(self._cooldown_sec - elapsed)
                return RiskCheckResult(
                    allowed=False,
                    reason=f"P10: {signal.symbol} 쿨다운 잔여 {remaining}초",
                    priority="P10",
                )

        # Expected Edge 필터
        if is_buy:
            edge_ok, edge_reason = self._check_expected_edge(signal)
            if not edge_ok:
                return RiskCheckResult(
                    allowed=False,
                    reason=edge_reason,
                    priority="EDGE",
                )

        # 호가 잔량 필터
        if is_buy and orderbook and order_krw > 0:
            ob_ok, ob_reason = self._check_orderbook_depth(
                signal.tier, orderbook, order_krw, signal.entry_price,
            )
            if not ob_ok:
                return RiskCheckResult(
                    allowed=False,
                    reason=ob_reason,
                    priority="OB",
                )

        return RiskCheckResult(allowed=True)

    def _check_expected_edge(self, signal: Signal) -> tuple[bool, str]:
        """Expected Edge 필터.

        expected_edge = expectancy - (fee + slippage + failure_penalty)
        ≤ 0이면 거부. 표본 미달 시 edge=0으로 간주하여 통과.

        Returns:
            (통과 여부, 거부 사유).
        """
        strat_key = signal.strategy.value
        expectancy = self._state.strategy_expectancy.get(strat_key)

        # 표본 미달 시 (expectancy가 None) 통과
        if expectancy is None:
            return True, ""

        slippage = SLIPPAGE_BY_TIER.get(signal.tier, 0.002)
        failure_penalty = self._state.strategy_failure_penalty.get(strat_key, 0)
        expected_edge = expectancy - (TOTAL_FEE_PCT + slippage + failure_penalty)

        if expected_edge <= 0:
            return False, (
                f"Expected Edge 음수: {expected_edge:.4f}"
                f" (exp={expectancy:.4f}, fee={TOTAL_FEE_PCT},"
                f" slip={slippage:.4f}, penalty={failure_penalty:.4f})"
            )
        return True, ""

    def _check_orderbook_depth(
        self,
        tier: Tier,
        orderbook: Orderbook,
        order_krw: float,
        entry_price: float,
    ) -> tuple[bool, str]:
        """호가 잔량 필터.

        best 3 levels 잔량이 주문량 × Tier별 배수 이상이어야 함.
        스프레드가 Tier별 한도 이내여야 함.

        Returns:
            (통과 여부, 거부 사유).
        """
        # 스프레드 확인
        spread_limit = SPREAD_LIMIT.get(tier, 0.0035)
        if orderbook.spread_pct > spread_limit:
            return False, (
                f"호가 스프레드 초과: {orderbook.spread_pct:.4f}"
                f" > {spread_limit:.4f} (Tier {tier.value})"
            )

        # best 3 levels 잔량 확인
        depth_mult = ORDERBOOK_DEPTH_MULT.get(tier, 3)
        if entry_price > 0:
            order_qty = order_krw / entry_price
        else:
            return True, ""

        required_qty = order_qty * depth_mult

        # 매수 → asks 확인, 매도 → bids 확인 (매수 시 asks에서 체결)
        levels = orderbook.asks[:3]
        total_depth = sum(e.quantity for e in levels)

        if total_depth < required_qty:
            return False, (
                f"호가 잔량 부족: {total_depth:.4f}"
                f" < {required_qty:.4f} (x{depth_mult}, Tier {tier.value})"
            )

        return True, ""

    def record_entry(self, symbol: str) -> None:
        """진입을 기록한다 (쿨다운 타이머 시작)."""
        self._state.last_entry_time[symbol] = time.time()

    def load_state(self, data: dict) -> None:
        """저장된 상태를 복원한다."""
        self._state.consecutive_losses = data.get("consecutive_losses", 0)
        self._state.last_entry_time = data.get("last_entry_time", {})
        self._state.total_exposure_krw = data.get("total_exposure_krw", 0)
        self._state.total_equity_krw = data.get("total_equity_krw", 0)

    def dump_state(self) -> dict:
        """상태를 딕셔너리로 반환한다."""
        return {
            "consecutive_losses": self._state.consecutive_losses,
            "last_entry_time": self._state.last_entry_time,
            "total_exposure_krw": self._state.total_exposure_krw,
            "total_equity_krw": self._state.total_equity_krw,
        }
