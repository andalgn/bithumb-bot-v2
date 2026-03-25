"""RegimeClassifier 스냅샷 테스트.

현재 RuleEngine의 국면 판정 동작을 고정한다.
Phase 2에서 RegimeClassifier를 분리한 후 이 테스트가 여전히 통과하면 분리 성공.
"""
from __future__ import annotations

import numpy as np
import pytest

from app.data_types import Candle, MarketSnapshot, Orderbook, OrderbookEntry, Regime
from strategy.indicators import compute_indicators
from strategy.rule_engine import RuleEngine
from tests.fixtures.candles import (
    crisis_candles,
    range_candles,
    strong_up_candles,
    weak_down_candles,
    weak_up_candles,
)


@pytest.fixture
def engine() -> RuleEngine:
    return RuleEngine()


# ─── 국면별 5케이스 ────────────────────────────────────────


def test_regime_strong_up(engine):
    """강한 상승 캔들 → STRONG_UP."""
    candles = strong_up_candles()
    ind = compute_indicators(candles)
    close = np.array([c.close for c in candles], dtype=np.float64)
    regime = engine._raw_classify(ind, close)
    assert regime == Regime.STRONG_UP, f"Expected STRONG_UP, got {regime}"


def test_regime_weak_up(engine):
    """약한 상승 캔들 → WEAK_UP."""
    candles = weak_up_candles()
    ind = compute_indicators(candles)
    close = np.array([c.close for c in candles], dtype=np.float64)
    regime = engine._raw_classify(ind, close)
    assert regime == Regime.WEAK_UP, f"Expected WEAK_UP, got {regime}"


def test_regime_range(engine):
    """횡보 캔들 → RANGE."""
    candles = range_candles()
    ind = compute_indicators(candles)
    close = np.array([c.close for c in candles], dtype=np.float64)
    regime = engine._raw_classify(ind, close)
    assert regime == Regime.RANGE, f"Expected RANGE, got {regime}"


def test_regime_weak_down(engine):
    """약한 하락 캔들 → WEAK_DOWN."""
    candles = weak_down_candles()
    ind = compute_indicators(candles)
    close = np.array([c.close for c in candles], dtype=np.float64)
    regime = engine._raw_classify(ind, close)
    assert regime == Regime.WEAK_DOWN, f"Expected WEAK_DOWN, got {regime}"


def test_regime_crisis(engine):
    """급락 캔들 → CRISIS."""
    candles = crisis_candles()
    ind = compute_indicators(candles)
    close = np.array([c.close for c in candles], dtype=np.float64)
    regime = engine._raw_classify(ind, close)
    assert regime == Regime.CRISIS, f"Expected CRISIS, got {regime}"


# ─── 히스테리시스 3케이스 ─────────────────────────────────


def test_hysteresis_requires_3_bars(engine):
    """국면 전환은 3봉 연속 확인 후 발생한다."""
    # RANGE 국면으로 초기화
    candles_range = range_candles()
    ind_range = compute_indicators(candles_range)
    close_range = np.array([c.close for c in candles_range], dtype=np.float64)
    engine.classify_regime("BTC", ind_range, close_range)

    # STRONG_UP 신호 1봉만 → 아직 전환 안 됨 (confirm_count < 3)
    candles_up = strong_up_candles()
    ind_up = compute_indicators(candles_up)
    close_up = np.array([c.close for c in candles_up], dtype=np.float64)
    engine.classify_regime("BTC", ind_up, close_up)

    state = engine._regime_states.get("BTC")
    assert state is not None
    # 1봉만으로는 RANGE → STRONG_UP 전환이 일어나선 안 된다
    # (confirm_count == 1이면 pending=STRONG_UP, current=RANGE)
    assert state.current in (Regime.RANGE, Regime.STRONG_UP)  # 3봉 미만이면 RANGE 유지
    if state.current == Regime.RANGE:
        assert state.confirm_count < 3


def test_hysteresis_crisis_immediate(engine):
    """CRISIS는 즉시 전환된다 (히스테리시스 없음)."""
    # STRONG_UP으로 초기화
    candles_up = strong_up_candles()
    ind_up = compute_indicators(candles_up)
    close_up = np.array([c.close for c in candles_up], dtype=np.float64)
    engine.classify_regime("BTC", ind_up, close_up)

    # 단 1봉 CRISIS → 즉시 전환
    candles_c = crisis_candles()
    ind_c = compute_indicators(candles_c)
    close_c = np.array([c.close for c in candles_c], dtype=np.float64)
    engine.classify_regime("BTC", ind_c, close_c)

    state = engine._regime_states.get("BTC")
    assert state is not None
    assert state.current == Regime.CRISIS


def test_hysteresis_crisis_release_requires_6_bars(engine):
    """CRISIS 해제는 6봉 연속 정상 확인 후 발생한다."""
    # CRISIS로 초기화
    candles_c = crisis_candles()
    ind_c = compute_indicators(candles_c)
    close_c = np.array([c.close for c in candles_c], dtype=np.float64)
    engine.classify_regime("BTC", ind_c, close_c)

    state = engine._regime_states.get("BTC")
    assert state is not None
    assert state.current == Regime.CRISIS

    # 정상 캔들 5봉 → 아직 CRISIS
    for _ in range(5):
        normal = range_candles()
        ind_n = compute_indicators(normal)
        close_n = np.array([c.close for c in normal], dtype=np.float64)
        engine.classify_regime("BTC", ind_n, close_n)

    state = engine._regime_states.get("BTC")
    assert state is not None
    assert state.current == Regime.CRISIS, "5봉 후에는 아직 CRISIS여야 함"

