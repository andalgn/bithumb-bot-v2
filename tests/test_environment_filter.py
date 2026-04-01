"""EnvironmentFilter 직접 단위 테스트."""
from __future__ import annotations

import pytest

from app.data_types import (
    Candle,
    MarketSnapshot,
    Orderbook,
    OrderbookEntry,
    Regime,
    Tier,
)
from strategy.coin_profiler import TierParams
from strategy.environment_filter import EnvironmentFilter
from strategy.spread_profiler import SpreadProfiler
from tests.fixtures.candles import range_candles, strong_up_candles
from tests.fixtures.indicators import indicators_from_candles


def _make_tier_params(tier: Tier = Tier.TIER1, spread_limit: float = 0.0018) -> TierParams:
    """테스트용 TierParams를 생성한다."""
    return TierParams(
        tier=tier,
        atr_pct=0.005,
        position_mult=1.0,
        rsi_min=35,
        rsi_max=65,
        atr_stop_mult=2.5,
        spread_limit=spread_limit,
    )


def _make_1h_candle(open_price: float, close_price: float) -> Candle:
    """테스트용 1H 캔들을 생성한다."""
    return Candle(
        timestamp=0,
        open=open_price,
        high=max(open_price, close_price) * 1.001,
        low=min(open_price, close_price) * 0.999,
        close=close_price,
        volume=1000.0,
    )


def _make_snap(candles: list[Candle], spread_pct: float = 0.001) -> MarketSnapshot:
    """테스트용 MarketSnapshot을 생성한다."""
    bid_price = 50_000_000.0
    ask_price = bid_price * (1 + spread_pct)
    ob = Orderbook(
        timestamp=0,
        bids=[OrderbookEntry(price=bid_price, quantity=1.0)],
        asks=[OrderbookEntry(price=ask_price, quantity=1.0)],
    )
    return MarketSnapshot(
        symbol="BTC",
        current_price=bid_price,
        candles_15m=candles,
        orderbook=ob,
    )


def test_check_pass_normal_conditions():
    """정상 조건(STRONG_UP 국면, 낮은 스프레드)에서 통과한다."""
    candles = strong_up_candles()
    ind = indicators_from_candles(candles)
    snap = _make_snap(candles, spread_pct=0.001)
    tier_params = _make_tier_params(tier=Tier.TIER1, spread_limit=0.0018)
    ef = EnvironmentFilter(SpreadProfiler(db_path="/tmp/nonexistent_test.db"))
    passed, reason = ef.check(Regime.STRONG_UP, snap, ind, tier_params)
    assert passed is True
    assert reason == ""


def test_check_reject_crisis_regime():
    """CRISIS 국면에서 L1 필터가 거부한다."""
    candles = range_candles()
    ind = indicators_from_candles(candles)
    snap = _make_snap(candles, spread_pct=0.001)
    tier_params = _make_tier_params(tier=Tier.TIER1, spread_limit=0.0018)
    ef = EnvironmentFilter(SpreadProfiler(db_path="/tmp/nonexistent_test.db"))
    passed, reason = ef.check(Regime.CRISIS, snap, ind, tier_params)
    assert passed is False
    assert "CRISIS" in reason


def test_check_reject_high_spread():
    """스프레드가 Tier 한도를 초과하면 L1 필터가 거부한다."""
    candles = strong_up_candles()
    ind = indicators_from_candles(candles)
    # 스프레드 0.5% — Tier1 한도(0.18%) 훨씬 초과
    snap = _make_snap(candles, spread_pct=0.005)
    tier_params = _make_tier_params(tier=Tier.TIER1, spread_limit=0.0018)
    ef = EnvironmentFilter(SpreadProfiler(db_path="/tmp/nonexistent_test.db"))
    passed, reason = ef.check(Regime.STRONG_UP, snap, ind, tier_params)
    assert passed is False
    assert "스프레드" in reason


def test_check_reject_1h_momentum_burst():
    """직전 1H 봉 변동 ≥ 1.5%이면 L1 필터가 거부한다."""
    candles = strong_up_candles()
    ind = indicators_from_candles(candles)
    base = 50_000_000.0
    # 직전 완성봉: 1.6% 급등
    c_prev = _make_1h_candle(base, base * 1.016)
    # 현재 형성 중인 봉 ([-1])
    c_curr = _make_1h_candle(base * 1.016, base * 1.017)
    snap = _make_snap(candles)
    snap = MarketSnapshot(
        symbol="BTC",
        current_price=base,
        candles_15m=candles,
        candles_1h=[c_prev, c_curr],
        orderbook=snap.orderbook,
    )
    tier_params = _make_tier_params(tier=Tier.TIER1, spread_limit=0.0018)
    ef = EnvironmentFilter(SpreadProfiler(db_path="/tmp/nonexistent_test.db"))
    passed, reason = ef.check(Regime.STRONG_UP, snap, ind, tier_params)
    assert passed is False
    assert "1H" in reason


def test_check_pass_1h_small_move():
    """직전 1H 봉 변동 < 1.5%이면 L1 필터가 통과한다."""
    candles = strong_up_candles()
    ind = indicators_from_candles(candles)
    base = 50_000_000.0
    # 0.5% 소폭 상승 — 버스트 임계값 미만
    c_prev = _make_1h_candle(base, base * 1.005)
    c_curr = _make_1h_candle(base * 1.005, base * 1.006)
    snap = MarketSnapshot(
        symbol="BTC",
        current_price=base,
        candles_15m=candles,
        candles_1h=[c_prev, c_curr],
        orderbook=_make_snap(candles).orderbook,
    )
    tier_params = _make_tier_params(tier=Tier.TIER1, spread_limit=0.0018)
    ef = EnvironmentFilter(SpreadProfiler(db_path="/tmp/nonexistent_test.db"))
    passed, reason = ef.check(Regime.STRONG_UP, snap, ind, tier_params)
    assert passed is True
    assert reason == ""


def test_check_pass_no_1h_candles():
    """candles_1h가 없거나 1봉 이하이면 버스트 체크를 건너뛰고 통과한다."""
    candles = strong_up_candles()
    ind = indicators_from_candles(candles)
    # candles_1h 미제공 (기본값 빈 리스트)
    snap = _make_snap(candles)
    tier_params = _make_tier_params(tier=Tier.TIER1, spread_limit=0.0018)
    ef = EnvironmentFilter(SpreadProfiler(db_path="/tmp/nonexistent_test.db"))
    passed, reason = ef.check(Regime.STRONG_UP, snap, ind, tier_params)
    assert passed is True
    assert reason == ""
