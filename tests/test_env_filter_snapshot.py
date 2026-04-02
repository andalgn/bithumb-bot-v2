"""EnvironmentFilter(L1 필터) 스냅샷 테스트.

거부/통과 동작을 고정한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.data_types import Candle, MarketSnapshot, Orderbook, OrderbookEntry, Regime, Tier
from strategy.coin_profiler import TierParams
from strategy.indicators import compute_indicators
from strategy.rule_engine import RuleEngine
from strategy.spread_profiler import SpreadProfiler
from tests.fixtures.candles import range_candles

KST = timezone(timedelta(hours=9))


@pytest.fixture
def engine():
    return RuleEngine(spread_profiler=SpreadProfiler(db_path="/tmp/nonexistent_test.db"))


@pytest.fixture
def tier1_params():
    return TierParams(
        tier=Tier.TIER1,
        atr_pct=0.01,
        position_mult=1.2,
        rsi_min=35,
        rsi_max=65,
        atr_stop_mult=2.5,
        spread_limit=0.0018,
    )


@pytest.fixture
def tier3_params():
    return TierParams(
        tier=Tier.TIER3,
        atr_pct=0.03,
        position_mult=1.0,
        rsi_min=25,
        rsi_max=75,
        atr_stop_mult=1.5,
        spread_limit=0.0035,
    )


def _make_snap(candles, volume_override=None, spread_pct=0.001):
    """테스트용 스냅샷 생성."""
    if volume_override is not None:
        candles = [
            Candle(c.timestamp, c.open, c.high, c.low, c.close, volume_override) for c in candles
        ]
    price = candles[-1].close
    ob = Orderbook(
        timestamp=0,
        bids=[OrderbookEntry(price=price * (1 - spread_pct / 2), quantity=100.0)],
        asks=[OrderbookEntry(price=price * (1 + spread_pct / 2), quantity=100.0)],
    )
    return MarketSnapshot(
        symbol="TEST", current_price=price, candles_15m=candles, candles_1h=candles, orderbook=ob
    )


def test_l1_pass_normal(engine, tier1_params):
    """정상 조건 → L1 통과."""
    candles = range_candles()
    snap = _make_snap(candles)
    ind = compute_indicators(candles)
    # 심야가 아닌 시간대로 고정
    day_kst = datetime(2026, 3, 25, 14, 0, 0, tzinfo=KST)
    with patch("strategy.environment_filter.datetime") as mock_dt:
        mock_dt.now.return_value = day_kst
        passed, reason = engine._check_layer1(Regime.RANGE, snap, ind, tier1_params)
    assert passed, f"정상 조건인데 거부됨: {reason}"


def test_l1_reject_crisis(engine, tier1_params):
    """CRISIS 국면 → L1 거부."""
    candles = range_candles()
    snap = _make_snap(candles)
    ind = compute_indicators(candles)
    passed, reason = engine._check_layer1(Regime.CRISIS, snap, ind, tier1_params)
    assert not passed
    assert "CRISIS" in reason


def test_l1_reject_low_volume(engine, tier1_params):
    """거래량 부족 → L1 거부.

    _check_layer1은 candles[-2] (마지막 완성봉)을 기준으로 평균 거래량 대비 40% 미만이면 거부한다.
    앞 20봉의 평균 거래량을 유지하고, -2번째 봉만 50%로 낮춘다.
    """
    candles = range_candles()
    avg_vol = sum(c.volume for c in candles[-22:-2]) / 20
    low_vol = avg_vol * 0.3  # 평균의 30% → 40% 기준 미달 (D_적극 시나리오)

    # 마지막 완성봉(-2)만 거래량을 낮추고 나머지는 유지
    patched = list(candles)
    c = patched[-2]
    patched[-2] = Candle(c.timestamp, c.open, c.high, c.low, c.close, low_vol)
    snap = _make_snap(patched)
    ind = compute_indicators(patched)

    day_kst = datetime(2026, 3, 25, 14, 0, 0, tzinfo=KST)
    with patch("strategy.environment_filter.datetime") as mock_dt:
        mock_dt.now.return_value = day_kst
        passed, reason = engine._check_layer1(Regime.RANGE, snap, ind, tier1_params)
    assert not passed
    assert "거래량" in reason


def test_l1_reject_high_spread(engine, tier1_params):
    """스프레드 초과 → L1 거부 (Tier1 한도 0.0018)."""
    candles = range_candles()
    snap = _make_snap(candles, spread_pct=0.005)  # 0.5% >> 0.18%
    ind = compute_indicators(candles)
    day_kst = datetime(2026, 3, 25, 14, 0, 0, tzinfo=KST)
    with patch("strategy.environment_filter.datetime") as mock_dt:
        mock_dt.now.return_value = day_kst
        passed, reason = engine._check_layer1(Regime.RANGE, snap, ind, tier1_params)
    assert not passed
    assert "스프레드" in reason


def test_l1_pass_nighttime_tier3(engine, tier3_params):
    """심야(03:00 KST) + Tier3 → L1 통과 (사이징에서 30% 축소, D_적극 시나리오)."""
    candles = range_candles()
    snap = _make_snap(candles)
    ind = compute_indicators(candles)
    night_kst = datetime(2026, 3, 25, 3, 0, 0, tzinfo=KST)
    with patch("strategy.environment_filter.datetime") as mock_dt:
        mock_dt.now.return_value = night_kst
        passed, reason = engine._check_layer1(Regime.RANGE, snap, ind, tier3_params)
    assert passed
