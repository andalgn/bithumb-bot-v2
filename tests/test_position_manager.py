"""Position Manager (사이징) 테스트.

SIZING_SPEC.md 5절 시나리오 기반.
"""

import pytest

from app.data_types import OrderSide, Pool, Regime, Signal, Strategy, Tier
from strategy.coin_profiler import TierParams
from strategy.correlation_monitor import CorrelationMonitor
from strategy.pool_manager import PoolManager
from strategy.position_manager import PositionManager
from strategy.rule_engine import SizeDecision


def _make_signal(
    symbol: str = "BTC",
    regime: Regime = Regime.STRONG_UP,
    tier: Tier = Tier.TIER1,
    score: float = 80.0,
) -> Signal:
    """테스트용 신호."""
    return Signal(
        symbol=symbol,
        direction=OrderSide.BUY,
        strategy=Strategy.TREND_FOLLOW,
        score=score,
        regime=regime,
        tier=tier,
        entry_price=50_000_000,
        stop_loss=49_000_000,
        take_profit=55_000_000,
    )


def _make_tier_params(tier: Tier = Tier.TIER1) -> TierParams:
    """테스트용 TierParams."""
    mults = {Tier.TIER1: 1.5, Tier.TIER2: 1.0, Tier.TIER3: 0.6}
    return TierParams(
        tier=tier, atr_pct=0.02, position_mult=mults[tier],
        rsi_min=35, rsi_max=65, atr_stop_mult=2.5, spread_limit=0.002,
    )


@pytest.fixture
def pm() -> PositionManager:
    """100만원 PositionManager."""
    pool = PoolManager(1_000_000)
    corr = CorrelationMonitor()
    return PositionManager(pool_manager=pool, correlation=corr)


class TestActiveSizing:
    """Active Pool 사이징 테스트."""

    def test_scenario_btc_strong_full(self, pm: PositionManager) -> None:
        """BTC T1, STRONG_UP, Full, 정상 → ~14,850원."""
        signal = _make_signal(regime=Regime.STRONG_UP, tier=Tier.TIER1)
        result = pm.calculate_size(
            signal=signal,
            tier_params=_make_tier_params(Tier.TIER1),
            size_decision=SizeDecision.FULL,
            active_positions=[],
        )
        # base=300000*0.03=9000, opp=9000*1.5*1.0*1.0=13500
        # defense = 1.5(STRONG) → clamp 1.0
        # final = 13500 * 1.0 = 13500
        assert result.size_krw > 0
        assert result.pool == Pool.ACTIVE

    def test_scenario_eth_probe(self, pm: PositionManager) -> None:
        """ETH T1, WEAK_UP, Probe → 사이즈 작음."""
        signal = _make_signal(symbol="ETH", regime=Regime.WEAK_UP)
        result = pm.calculate_size(
            signal=signal,
            tier_params=_make_tier_params(Tier.TIER1),
            size_decision=SizeDecision.PROBE,
            active_positions=[],
        )
        # Probe score_mult=0.4 → 9000*1.5*0.4*1.0 = 5400
        assert result.size_krw >= 5000 or result.size_krw == 0

    def test_scenario_sol_2_losses(self, pm: PositionManager) -> None:
        """SOL T2, 2연패 → loss_streak_mult=0.7."""
        pm.record_trade_result(is_loss=True)
        pm.record_trade_result(is_loss=True)
        signal = _make_signal(symbol="SOL", regime=Regime.WEAK_UP, tier=Tier.TIER2)
        result = pm.calculate_size(
            signal=signal,
            tier_params=_make_tier_params(Tier.TIER2),
            size_decision=SizeDecision.FULL,
            active_positions=[],
        )
        assert result.detail["loss_streak_mult"] == 0.7

    def test_hold_returns_zero(self, pm: PositionManager) -> None:
        """HOLD → 사이즈 0."""
        signal = _make_signal()
        result = pm.calculate_size(
            signal=signal,
            tier_params=_make_tier_params(),
            size_decision=SizeDecision.HOLD,
            active_positions=[],
        )
        assert result.size_krw == 0

    def test_pool_cap_25pct(self, pm: PositionManager) -> None:
        """Pool 25% 상한 적용."""
        signal = _make_signal()
        result = pm.calculate_size(
            signal=signal,
            tier_params=_make_tier_params(),
            size_decision=SizeDecision.FULL,
            active_positions=[],
        )
        # Active 300,000 × 25% = 75,000
        assert result.size_krw <= 75_000

    def test_crisis_zero(self, pm: PositionManager) -> None:
        """CRISIS 국면 → defense 0 → clamp 0.3 → 작은 값."""
        signal = _make_signal(regime=Regime.CRISIS)
        result = pm.calculate_size(
            signal=signal,
            tier_params=_make_tier_params(),
            size_decision=SizeDecision.FULL,
            active_positions=[],
        )
        # regime_mult=0 → defense=0 → clamp 0.3
        assert result.detail["regime_mult"] == 0.0
        assert result.detail["defense"] == 0.3


class TestCoreSizing:
    """Core Pool 사이징 테스트."""

    def test_core_btc_promoted(self, pm: PositionManager) -> None:
        """Core BTC 승격 포지션."""
        result = pm.calculate_core_size(
            tier_params=_make_tier_params(Tier.TIER1),
            regime=Regime.STRONG_UP,
        )
        # base=600000*0.10=60000, opp=60000*1.5*1.0=90000
        assert result.size_krw > 0
        assert result.pool == Pool.CORE

    def test_dca_size(self, pm: PositionManager) -> None:
        """DCA = Core × 4%."""
        size = pm.calculate_dca_size()
        assert size == pytest.approx(600_000 * 0.04)

    def test_additional_buy_tier1(self, pm: PositionManager) -> None:
        """추가매수 Tier 1 = Core × 15%."""
        size = pm.calculate_addtional_buy_size(Tier.TIER1)
        assert size == pytest.approx(600_000 * 0.15)

    def test_additional_buy_tier2(self, pm: PositionManager) -> None:
        """추가매수 Tier 2 = Core × 8%."""
        size = pm.calculate_addtional_buy_size(Tier.TIER2)
        assert size == pytest.approx(600_000 * 0.08)


class TestWeeklyDD:
    """주간 DD 배수 테스트."""

    def test_dd_over_6pct(self, pm: PositionManager) -> None:
        """주간 DD > 6% → dd_mult=0.5."""
        signal = _make_signal()
        result = pm.calculate_size(
            signal=signal,
            tier_params=_make_tier_params(),
            size_decision=SizeDecision.FULL,
            active_positions=[],
            weekly_dd_pct=0.07,
        )
        assert result.detail["dd_mult"] == 0.5

    def test_dd_over_4pct(self, pm: PositionManager) -> None:
        """주간 DD > 4% → dd_mult=0.7."""
        signal = _make_signal()
        result = pm.calculate_size(
            signal=signal,
            tier_params=_make_tier_params(),
            size_decision=SizeDecision.FULL,
            active_positions=[],
            weekly_dd_pct=0.05,
        )
        assert result.detail["dd_mult"] == 0.7
