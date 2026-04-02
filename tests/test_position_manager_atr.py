"""ATR 기반 포지션 사이징 단위 테스트."""

from __future__ import annotations

import numpy as np

from app.config import SizingConfig
from app.data_types import OrderSide, Pool, Regime, Signal, Tier
from strategy.coin_profiler import Tier as ProfilerTier
from strategy.coin_profiler import TierParams
from strategy.correlation_monitor import CorrelationMonitor
from strategy.indicators import IndicatorPack
from strategy.pool_manager import PoolManager, PoolState
from strategy.position_manager import PositionManager
from strategy.rule_engine import SizeDecision


def _make_pm(atr_sizing_enabled: bool = False, atr_target_pct: float = 0.01) -> PositionManager:
    pool = PoolManager.__new__(PoolManager)
    pool._pools = {
        Pool.ACTIVE: PoolState(total_balance=1_000_000.0, allocated=0.0, position_count=0),
        Pool.CORE: PoolState(total_balance=500_000.0, allocated=0.0, position_count=0),
        Pool.RESERVE: PoolState(total_balance=200_000.0, allocated=0.0, position_count=0),
    }
    corr = CorrelationMonitor.__new__(CorrelationMonitor)
    corr._corr_matrix = {}
    corr._skip_threshold = 0.85
    corr._reduce_threshold_min = 0.70
    corr._reduce_threshold_max = 0.85
    corr._reduce_mult = 0.5
    cfg = SizingConfig(
        active_risk_pct=0.07,
        atr_sizing_enabled=atr_sizing_enabled,
        atr_target_pct=atr_target_pct,
    )
    return PositionManager(pool, corr, cfg)


def _make_signal() -> Signal:
    return Signal(
        symbol="BTC",
        direction=OrderSide.BUY,
        strategy="trend_follow",
        score=80,
        entry_price=50_000_000.0,
        stop_loss=48_000_000.0,
        take_profit=54_000_000.0,
        regime=Regime.STRONG_UP,
        tier=Tier.TIER1,
    )


def _make_tier() -> TierParams:
    return TierParams(
        tier=ProfilerTier.TIER1,
        atr_pct=0.005,
        position_mult=1.0,
        rsi_min=35,
        rsi_max=65,
        atr_stop_mult=2.5,
        spread_limit=0.0018,
    )


def _make_ind(atr_val: float) -> IndicatorPack:
    atr_arr = np.full(100, atr_val)
    return IndicatorPack(atr=atr_arr)


def test_atr_sizing_disabled_uses_vol_target():
    """ATR 사이징 비활성화 시 기존 vol_target_mult 방식 사용."""
    pm = _make_pm(atr_sizing_enabled=False)
    result = pm.calculate_size(
        signal=_make_signal(),
        tier_params=_make_tier(),
        size_decision=SizeDecision.FULL,
        active_positions=[],
        ind_1h=_make_ind(500_000.0),
        current_price=50_000_000.0,
    )
    assert result.size_krw > 0
    assert "vol_target_mult" in result.detail


def test_atr_sizing_enabled_uses_atr_mult():
    """ATR 사이징 활성화 시 atr_mult 키가 detail에 존재."""
    pm = _make_pm(atr_sizing_enabled=True, atr_target_pct=0.01)
    # ATR = 500_000 KRW, price = 50_000_000 → atr_pct = 0.01 → mult = 1.0
    result = pm.calculate_size(
        signal=_make_signal(),
        tier_params=_make_tier(),
        size_decision=SizeDecision.FULL,
        active_positions=[],
        ind_1h=_make_ind(500_000.0),
        current_price=50_000_000.0,
    )
    assert result.size_krw > 0
    assert "atr_mult" in result.detail
    assert abs(result.detail["atr_mult"] - 1.0) < 0.01


def test_atr_sizing_high_volatility_reduces_size():
    """ATR 높을 때 포지션 축소."""
    pm = _make_pm(atr_sizing_enabled=True, atr_target_pct=0.01)
    # ATR = 1_000_000 KRW, price = 50_000_000 → atr_pct = 0.02 → mult = 0.5
    result = pm.calculate_size(
        signal=_make_signal(),
        tier_params=_make_tier(),
        size_decision=SizeDecision.FULL,
        active_positions=[],
        ind_1h=_make_ind(1_000_000.0),
        current_price=50_000_000.0,
    )
    assert result.detail.get("atr_mult", 1.0) <= 0.6


def test_atr_sizing_no_ind_falls_back():
    """ind_1h 없을 때 vol_target_mult fallback."""
    pm = _make_pm(atr_sizing_enabled=True)
    result = pm.calculate_size(
        signal=_make_signal(),
        tier_params=_make_tier(),
        size_decision=SizeDecision.FULL,
        active_positions=[],
        ind_1h=None,
        current_price=0.0,
    )
    assert result.size_krw > 0
    assert "vol_target_mult" in result.detail
