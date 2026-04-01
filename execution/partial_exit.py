"""부분청산 + 트레일링 스톱 모듈.

전략별 부분청산 규칙, 트레일링 스톱 관리.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

from app.data_types import ExitReason, Position, Strategy, Tier

logger = logging.getLogger(__name__)

# Tier별 ATR 트레일링 배수 (Active)
ACTIVE_TRAIL_MULT: dict[Tier, float] = {
    Tier.TIER1: 2.5,
    Tier.TIER2: 2.0,
    Tier.TIER3: 1.5,
}

# 트레일링 활성화 수익률
TRAILING_ACTIVATION_PCT = 0.03
# 콜백률
TRAILING_CALLBACK_PCT = 0.01
# 부분청산 최대 재시도 횟수
MAX_PARTIAL_RETRIES = 3


class ExitAction(str, Enum):
    """청산 액션 유형."""

    NONE = "none"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    PARTIAL_EXIT = "partial_exit"
    TRAILING_STOP = "trailing_stop"
    TIME_EXIT = "time_exit"
    DEMOTION = "demotion"
    CRISIS_EXIT = "crisis_exit"


@dataclass
class ExitDecision:
    """청산 판정 결과."""

    action: ExitAction
    exit_ratio: float = 1.0  # 0.0~1.0 (부분청산 비율)
    exit_price: float = 0.0
    reason: ExitReason = ExitReason.SL
    detail: str = ""


@dataclass
class TrailingState:
    """트레일링 스톱 상태."""

    active: bool = False
    highest_price: float = 0.0
    trailing_stop: float = 0.0


@dataclass
class PartialExitState:
    """부분청산 상태."""

    # 전략 A: +3%→30%, +6%→30%, 나머지 트레일링
    trench_1_done: bool = False  # +3% 30%
    trench_2_done: bool = False  # +6% 30%
    # 전략 B: BB 중간선→50%
    bb_exit_done: bool = False
    # 남은 비율
    remaining_ratio: float = 1.0
    # 누적 수수료
    cumulative_fee_krw: float = 0.0
    # 롤백 추적: 마지막 세팅된 플래그
    _last_flag: str = ""
    # 플래그별 재시도 횟수
    _retry_counts: dict[str, int] = field(default_factory=dict)


class PartialExitManager:
    """부분청산 + 트레일링 관리자."""

    def __init__(self) -> None:
        """초기화."""
        self._trailing: dict[str, TrailingState] = {}
        self._partial: dict[str, PartialExitState] = {}

    def init_position(self, symbol: str) -> None:
        """포지션 초기화 시 상태를 생성한다."""
        self._trailing[symbol] = TrailingState()
        self._partial[symbol] = PartialExitState()

    def remove_position(self, symbol: str) -> None:
        """포지션 종료 시 상태를 제거한다."""
        self._trailing.pop(symbol, None)
        self._partial.pop(symbol, None)

    # _partial_close_position에서 사용하는 별칭
    clear_position = remove_position

    def rollback_partial_exit(self, symbol: str) -> None:
        """부분청산 실패 시 플래그를 되돌린다.

        최대 MAX_PARTIAL_RETRIES회까지 재시도를 허용하고,
        초과 시 플래그를 유지하여 무한 재시도를 방지한다.
        """
        state = self._partial.get(symbol)
        if state is None or not state._last_flag:
            return

        flag = state._last_flag
        count = state._retry_counts.get(flag, 0) + 1
        state._retry_counts[flag] = count

        if count >= MAX_PARTIAL_RETRIES:
            logger.warning(
                "부분청산 재시도 한도 초과 — 포기: %s %s (%d회)",
                symbol, flag, count,
            )
            state._last_flag = ""
            return

        # 플래그 리셋 + 비율 복원
        if flag == "bb":
            state.bb_exit_done = False
            state.remaining_ratio += 0.5
        elif flag == "trench_1":
            state.trench_1_done = False
            state.remaining_ratio += 0.3
        elif flag == "trench_2":
            state.trench_2_done = False
            state.remaining_ratio += 0.3

        state._last_flag = ""
        logger.info(
            "부분청산 플래그 롤백: %s %s (재시도 %d/%d)",
            symbol, flag, count, MAX_PARTIAL_RETRIES,
        )

    def evaluate(
        self,
        position: Position,
        current_price: float,
        atr_value: float,
        bb_middle: float = 0.0,
        is_core: bool = False,
        core_stop_loss: float = 0.0,
    ) -> ExitDecision:
        """청산 판정을 수행한다 (우선순위 적용).

        청산 우선순위:
        - Core: 손절 > 강등 > 부분청산 > 트레일링
        - Active: 손절 > 부분청산 > 타임아웃

        Args:
            position: 현재 포지션.
            current_price: 현재 가격.
            atr_value: 현재 ATR.
            bb_middle: BB 중간선 (전략 B용).
            is_core: Core 포지션 여부.
            core_stop_loss: Core 손절가 (Core일 때).

        Returns:
            ExitDecision.
        """
        symbol = position.symbol
        entry = position.entry_price
        if entry <= 0 or current_price <= 0:
            return ExitDecision(action=ExitAction.NONE)

        pnl_pct = (current_price - entry) / entry
        sl = core_stop_loss if is_core and core_stop_loss > 0 else position.stop_loss

        # ─── 1. 손절 (최우선) ───
        if current_price <= sl:
            return ExitDecision(
                action=ExitAction.STOP_LOSS,
                exit_ratio=1.0,
                exit_price=current_price,
                reason=ExitReason.SL,
                detail=f"SL hit: {current_price:.0f} <= {sl:.0f}",
            )

        # ─── 2. 트레일링 스톱 체크 ───
        trailing_decision = self._check_trailing(
            symbol, position, current_price, atr_value, is_core,
        )
        if trailing_decision.action == ExitAction.TRAILING_STOP:
            return trailing_decision

        # ─── 3. 부분청산 체크 ───
        partial_decision = self._check_partial_exit(
            symbol, position, current_price, pnl_pct, bb_middle,
        )
        if partial_decision.action == ExitAction.PARTIAL_EXIT:
            return partial_decision

        # ─── 4. 고정 TP (전략 D 스캘핑) ───
        if position.strategy == Strategy.SCALPING:
            if pnl_pct >= 0.015:
                return ExitDecision(
                    action=ExitAction.TAKE_PROFIT,
                    exit_ratio=1.0,
                    exit_price=current_price,
                    reason=ExitReason.TP,
                    detail=f"스캘핑 TP: +{pnl_pct:.1%}",
                )

        # ─── 5. 트레일링 업데이트 (히트 안 했으면) ───
        self._update_trailing(symbol, position, current_price, atr_value, is_core)

        return ExitDecision(action=ExitAction.NONE)

    def check_time_exit(
        self, position: Position, now_ms: int, max_hold_ms: int = 7200_000
    ) -> ExitDecision:
        """시간 제한 청산을 확인한다 (전략 D: 2시간).

        Args:
            position: 현재 포지션.
            now_ms: 현재 시각 (epoch ms).
            max_hold_ms: 최대 보유 시간 (ms). 기본 2시간.

        Returns:
            ExitDecision.
        """
        if position.strategy != Strategy.SCALPING:
            return ExitDecision(action=ExitAction.NONE)

        hold_ms = now_ms - position.entry_time
        if hold_ms >= max_hold_ms:
            return ExitDecision(
                action=ExitAction.TIME_EXIT,
                exit_ratio=1.0,
                exit_price=0,
                reason=ExitReason.TIME,
                detail=f"스캘핑 시간 제한: {hold_ms / 1000:.0f}초",
            )
        return ExitDecision(action=ExitAction.NONE)

    def _check_trailing(
        self,
        symbol: str,
        position: Position,
        current_price: float,
        atr_value: float,
        is_core: bool,
    ) -> ExitDecision:
        """트레일링 스톱 히트를 확인한다."""
        state = self._trailing.get(symbol)
        if state is None or not state.active:
            return ExitDecision(action=ExitAction.NONE)

        if current_price <= state.trailing_stop:
            return ExitDecision(
                action=ExitAction.TRAILING_STOP,
                exit_ratio=self._get_remaining(symbol),
                exit_price=current_price,
                reason=ExitReason.TRAILING,
                detail=(
                    f"trailing hit: {current_price:.0f}"
                    f" <= {state.trailing_stop:.0f}"
                    f" (peak: {state.highest_price:.0f})"
                ),
            )
        return ExitDecision(action=ExitAction.NONE)

    def _update_trailing(
        self,
        symbol: str,
        position: Position,
        current_price: float,
        atr_value: float,
        is_core: bool,
    ) -> None:
        """트레일링 스톱을 업데이트한다."""
        if symbol not in self._trailing:
            self._trailing[symbol] = TrailingState()

        state = self._trailing[symbol]
        entry = position.entry_price
        pnl_pct = (current_price - entry) / entry if entry > 0 else 0

        # 활성화 조건: +3% 도달 시
        if not state.active and pnl_pct >= TRAILING_ACTIVATION_PCT:
            state.active = True
            state.highest_price = current_price
            if is_core:
                trail_dist = atr_value * 2.5 if atr_value > 0 else current_price * 0.025
            else:
                mult = ACTIVE_TRAIL_MULT.get(position.tier, 2.0)
                trail_dist = atr_value * mult if atr_value > 0 else current_price * 0.02
            state.trailing_stop = current_price - trail_dist
            logger.info(
                "트레일링 활성화: %s @ %.0f, TS=%.0f",
                symbol, current_price, state.trailing_stop,
            )
            return

        # 이미 활성화: 최고가 갱신 + 트레일링 끌어올림
        if state.active and current_price > state.highest_price:
            state.highest_price = current_price
            # 콜백 기반 트레일링
            callback_stop = current_price * (1 - TRAILING_CALLBACK_PCT)
            # ATR 기반 트레일링
            if is_core:
                trail_dist = atr_value * 2.5 if atr_value > 0 else current_price * 0.025
            else:
                mult = ACTIVE_TRAIL_MULT.get(position.tier, 2.0)
                trail_dist = atr_value * mult if atr_value > 0 else current_price * 0.02
            atr_stop = current_price - trail_dist
            # 더 높은(보수적) 쪽 선택
            new_stop = max(callback_stop, atr_stop)
            if new_stop > state.trailing_stop:
                state.trailing_stop = new_stop

    def _check_partial_exit(
        self,
        symbol: str,
        position: Position,
        current_price: float,
        pnl_pct: float,
        bb_middle: float,
    ) -> ExitDecision:
        """전략별 부분청산을 확인한다."""
        if symbol not in self._partial:
            self._partial[symbol] = PartialExitState()

        state = self._partial[symbol]
        strategy = position.strategy

        # ─── 전략 A (추세추종): +3%→30%, +6%→30% ───
        if strategy == Strategy.TREND_FOLLOW:
            if pnl_pct >= 0.06 and not state.trench_2_done:
                state.trench_2_done = True
                state.remaining_ratio -= 0.3
                state._last_flag = "trench_2"
                return ExitDecision(
                    action=ExitAction.PARTIAL_EXIT,
                    exit_ratio=0.3,
                    exit_price=current_price,
                    reason=ExitReason.TP,
                    detail=f"전략A 2차 부분청산 +{pnl_pct:.1%}",
                )
            if pnl_pct >= 0.03 and not state.trench_1_done:
                state.trench_1_done = True
                state.remaining_ratio -= 0.3
                state._last_flag = "trench_1"
                return ExitDecision(
                    action=ExitAction.PARTIAL_EXIT,
                    exit_ratio=0.3,
                    exit_price=current_price,
                    reason=ExitReason.TP,
                    detail=f"전략A 1차 부분청산 +{pnl_pct:.1%}",
                )

        # ─── 전략 B (반전포착): BB 중간선→50% ───
        elif strategy == Strategy.MEAN_REVERSION:
            if bb_middle > 0 and current_price >= bb_middle and not state.bb_exit_done:
                state.bb_exit_done = True
                state.remaining_ratio -= 0.5
                state._last_flag = "bb"
                return ExitDecision(
                    action=ExitAction.PARTIAL_EXIT,
                    exit_ratio=0.5,
                    exit_price=current_price,
                    reason=ExitReason.TP,
                    detail=f"전략B BB중간선 부분청산 @ {current_price:.0f}",
                )

        # 전략 C, D: 부분청산 없음
        return ExitDecision(action=ExitAction.NONE)

    def _get_remaining(self, symbol: str) -> float:
        """남은 포지션 비율을 반환한다."""
        state = self._partial.get(symbol)
        if state is None:
            return 1.0
        return max(0.0, state.remaining_ratio)

    def add_fee(self, symbol: str, fee_krw: float) -> None:
        """수수료를 누적한다."""
        state = self._partial.get(symbol)
        if state:
            state.cumulative_fee_krw += fee_krw

    def get_cumulative_fee(self, symbol: str) -> float:
        """누적 수수료를 반환한다."""
        state = self._partial.get(symbol)
        return state.cumulative_fee_krw if state else 0.0

    def get_trailing_state(self, symbol: str) -> TrailingState | None:
        """트레일링 상태를 반환한다."""
        return self._trailing.get(symbol)

    def get_partial_state(self, symbol: str) -> PartialExitState | None:
        """부분청산 상태를 반환한다."""
        return self._partial.get(symbol)
