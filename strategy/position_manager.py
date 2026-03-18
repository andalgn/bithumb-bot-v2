"""Pool 기반 2단계 사이징 모듈.

SIZING_SPEC.md 기반.
1단계: 기회 사이즈 (base × tier_mult × score_mult × vol_target_mult)
2단계: 방어 조정 (regime_mult × dd_mult × loss_streak_mult, clamp [0.3, 1.0])
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from app.config import SizingConfig
from app.data_types import Candle, Pool, Regime, Signal, Tier
from strategy.coin_profiler import TierParams
from strategy.correlation_monitor import CorrelationMonitor
from strategy.pool_manager import PoolManager
from strategy.rule_engine import SizeDecision

logger = logging.getLogger(__name__)

# 국면별 방어 배수
REGIME_DEFENSE_MULT: dict[Regime, float] = {
    Regime.STRONG_UP: 1.5,
    Regime.WEAK_UP: 1.0,
    Regime.RANGE: 1.0,
    Regime.WEAK_DOWN: 0.6,
    Regime.CRISIS: 0.0,
}

# 점수 결정별 사이즈 배수
SCORE_MULT: dict[str, float] = {
    SizeDecision.FULL: 1.0,
    SizeDecision.PROBE: 0.4,
    SizeDecision.HOLD: 0.0,
}


@dataclass
class SizingResult:
    """사이징 결과."""

    pool: Pool
    size_krw: float
    detail: dict[str, float]


class PositionManager:
    """Pool 기반 2단계 사이징."""

    def __init__(
        self,
        pool_manager: PoolManager,
        correlation: CorrelationMonitor,
        sizing_config: SizingConfig | None = None,
    ) -> None:
        """초기화.

        Args:
            pool_manager: 풀 관리자.
            correlation: 상관관계 모니터.
            sizing_config: 사이징 설정.
        """
        self._pool = pool_manager
        self._correlation = correlation
        self._cfg = sizing_config or SizingConfig()

        # 연속 손실 카운터 (사이징용, RiskGate와 별도)
        self._consecutive_losses = 0

    def calculate_size(
        self,
        signal: Signal,
        tier_params: TierParams,
        size_decision: str,
        active_positions: list[str],
        weekly_dd_pct: float = 0.0,
        candles_1h: list[Candle] | None = None,
    ) -> SizingResult:
        """Active Pool 사이징을 계산한다.

        Args:
            signal: 매매 신호.
            tier_params: Tier 파라미터.
            size_decision: Full/Probe/HOLD 판정.
            active_positions: 현재 보유 코인 목록.
            weekly_dd_pct: 주간 DD 비율.
            candles_1h: 1H 캔들 (vol_target 계산용).

        Returns:
            SizingResult.
        """
        detail: dict[str, float] = {}

        if size_decision == SizeDecision.HOLD:
            return SizingResult(pool=Pool.ACTIVE, size_krw=0, detail={"reason": 0})

        # ─── 1단계: 기회 사이즈 ───
        active_balance = self._pool.get_balance(Pool.ACTIVE)
        base = active_balance * self._cfg.active_risk_pct
        detail["base"] = base

        tier_mult = tier_params.position_mult
        detail["tier_mult"] = tier_mult

        score_mult = SCORE_MULT.get(size_decision, 1.0)
        detail["score_mult"] = score_mult

        vol_target_mult = self._calc_vol_target_mult(candles_1h)
        detail["vol_target_mult"] = vol_target_mult

        opportunity = base * tier_mult * score_mult * vol_target_mult
        detail["opportunity"] = opportunity

        # ─── 2단계: 방어 조정 ───
        regime_mult = REGIME_DEFENSE_MULT.get(signal.regime, 1.0)
        detail["regime_mult"] = regime_mult

        dd_mult = self._calc_dd_mult(weekly_dd_pct)
        detail["dd_mult"] = dd_mult

        loss_streak_mult = self._calc_loss_streak_mult()
        detail["loss_streak_mult"] = loss_streak_mult

        defense = regime_mult * dd_mult * loss_streak_mult
        defense = max(self._cfg.defense_mult_min, min(self._cfg.defense_mult_max, defense))
        detail["defense"] = defense

        final = opportunity * defense

        # ─── 가드레일 ───
        cap = active_balance * self._cfg.pool_cap_pct
        final = min(final, cap)

        # 상관관계 축소
        corr = self._correlation.check_correlation(signal.symbol, active_positions)
        if not corr.allowed:
            detail["corr_skip"] = 1.0
            return SizingResult(pool=Pool.ACTIVE, size_krw=0, detail=detail)
        if corr.size_mult < 1.0:
            final *= corr.size_mult
            detail["corr_mult"] = corr.size_mult

        # 하한 체크
        if final < self._cfg.active_min_krw:
            final = 0

        detail["final"] = final
        return SizingResult(pool=Pool.ACTIVE, size_krw=final, detail=detail)

    def calculate_core_size(
        self,
        tier_params: TierParams,
        regime: Regime,
        weekly_dd_pct: float = 0.0,
        candles_1h: list[Candle] | None = None,
    ) -> SizingResult:
        """Core Pool 사이징을 계산한다 (승격/추가매수용).

        Args:
            tier_params: Tier 파라미터.
            regime: 현재 국면.
            weekly_dd_pct: 주간 DD 비율.
            candles_1h: 1H 캔들.

        Returns:
            SizingResult.
        """
        detail: dict[str, float] = {}

        core_balance = self._pool.get_balance(Pool.CORE)
        base = core_balance * self._cfg.core_risk_pct
        detail["base"] = base

        tier_mult = tier_params.position_mult
        detail["tier_mult"] = tier_mult

        vol_target_mult = self._calc_vol_target_mult(candles_1h)
        detail["vol_target_mult"] = vol_target_mult

        opportunity = base * tier_mult * vol_target_mult
        detail["opportunity"] = opportunity

        regime_mult = REGIME_DEFENSE_MULT.get(regime, 1.0)
        dd_mult = self._calc_dd_mult(weekly_dd_pct)
        loss_streak_mult = self._calc_loss_streak_mult()

        defense = regime_mult * dd_mult * loss_streak_mult
        defense = max(self._cfg.defense_mult_min, min(self._cfg.defense_mult_max, defense))
        detail["defense"] = defense

        final = opportunity * defense
        cap = core_balance * self._cfg.pool_cap_pct
        final = min(final, cap)

        if final < self._cfg.core_min_krw:
            final = 0

        detail["final"] = final
        return SizingResult(pool=Pool.CORE, size_krw=final, detail=detail)

    def calculate_dca_size(self) -> float:
        """DCA 사이징 (Core Pool × 4%, 고정)."""
        return self._pool.get_balance(Pool.CORE) * self._cfg.dca_core_pct

    def calculate_addtional_buy_size(self, tier: Tier) -> float:
        """추가매수 금액을 계산한다.

        Args:
            tier: 코인 Tier.

        Returns:
            추가매수 금액(KRW).
        """
        core_balance = self._pool.get_balance(Pool.CORE)
        if tier == Tier.TIER1:
            return core_balance * 0.15
        return core_balance * 0.08  # Tier 2

    def record_trade_result(self, is_loss: bool) -> None:
        """거래 결과를 기록한다 (사이징용)."""
        if is_loss:
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0

    def _calc_vol_target_mult(self, candles_1h: list[Candle] | None) -> float:
        """변동성 타기팅 배수를 계산한다."""
        if not candles_1h or len(candles_1h) < 20:
            return 1.0

        closes = np.array([c.close for c in candles_1h[-480:]], dtype=np.float64)
        if len(closes) < 20:
            return 1.0

        returns = np.diff(closes) / closes[:-1]
        realized_vol = float(np.std(returns)) * np.sqrt(24)  # 일일 환산

        if realized_vol <= 0:
            return 1.0

        target_vol = 0.02  # 목표 변동성 2%
        mult = target_vol / realized_vol

        return max(self._cfg.vol_target_mult_min, min(self._cfg.vol_target_mult_max, mult))

    def _calc_dd_mult(self, weekly_dd_pct: float) -> float:
        """DD 기반 방어 배수를 계산한다."""
        if weekly_dd_pct > 0.06:
            return 0.5
        if weekly_dd_pct > 0.04:
            return 0.7
        return 1.0

    def _calc_loss_streak_mult(self) -> float:
        """연속 손실 기반 방어 배수를 계산한다."""
        if self._consecutive_losses >= 3:
            return 0.5
        if self._consecutive_losses >= 2:
            return 0.7
        return 1.0
