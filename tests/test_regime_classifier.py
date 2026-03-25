"""RegimeClassifier 직접 단위 테스트."""
from __future__ import annotations

import numpy as np
import pytest

from app.data_types import Regime
from strategy.regime_classifier import RegimeClassifier, RegimeState
from tests.fixtures.candles import (
    crisis_candles,
    range_candles,
    strong_up_candles,
    weak_down_candles,
    weak_up_candles,
)
from tests.fixtures.indicators import indicators_from_candles


# ── raw_classify 테스트 ──────────────────────────────────────────────────────

def test_raw_classify_strong_up():
    """STRONG_UP 캔들에서 STRONG_UP 국면이 반환된다."""
    candles = strong_up_candles()
    ind = indicators_from_candles(candles)
    close = np.array([c.close for c in candles])
    clf = RegimeClassifier()
    result = clf.raw_classify(ind, close)
    assert result == Regime.STRONG_UP


def test_raw_classify_range():
    """RANGE 캔들에서 RANGE 국면이 반환된다."""
    candles = range_candles()
    ind = indicators_from_candles(candles)
    close = np.array([c.close for c in candles])
    clf = RegimeClassifier()
    result = clf.raw_classify(ind, close)
    assert result == Regime.RANGE


def test_raw_classify_weak_down():
    """WEAK_DOWN 캔들에서 WEAK_DOWN 국면이 반환된다."""
    candles = weak_down_candles()
    ind = indicators_from_candles(candles)
    close = np.array([c.close for c in candles])
    clf = RegimeClassifier()
    result = clf.raw_classify(ind, close)
    assert result == Regime.WEAK_DOWN


def test_raw_classify_crisis():
    """CRISIS 캔들에서 CRISIS 국면이 반환된다."""
    candles = crisis_candles()
    ind = indicators_from_candles(candles)
    close = np.array([c.close for c in candles])
    clf = RegimeClassifier()
    result = clf.raw_classify(ind, close)
    assert result == Regime.CRISIS


# ── classify (히스테리시스) 테스트 ──────────────────────────────────────────

def test_classify_crisis_immediate():
    """CRISIS는 히스테리시스 없이 즉시 전환된다."""
    candles = crisis_candles()
    ind = indicators_from_candles(candles)
    close = np.array([c.close for c in candles])
    clf = RegimeClassifier()
    regime, _aux = clf.classify("BTC", ind, close)
    assert regime == Regime.CRISIS


def test_classify_returns_regime_and_aux_flags():
    """classify()는 (Regime, AuxFlags) 튜플을 반환한다."""
    candles = strong_up_candles()
    ind = indicators_from_candles(candles)
    close = np.array([c.close for c in candles])
    clf = RegimeClassifier()
    result = clf.classify("BTC", ind, close)
    assert isinstance(result, tuple) and len(result) == 2
    regime, aux = result
    assert isinstance(regime, Regime)
    assert hasattr(aux, "range_volatile")
    assert hasattr(aux, "down_accel")


# ── get_state / states 테스트 ────────────────────────────────────────────────

def test_get_state_unknown_symbol_returns_default():
    """알 수 없는 심볼에 대해 기본 RegimeState가 반환된다."""
    clf = RegimeClassifier()
    state = clf.get_state("UNKNOWN")
    assert isinstance(state, RegimeState)
    assert state.current == Regime.RANGE


def test_get_state_after_classify_returns_state():
    """classify 후 get_state는 업데이트된 RegimeState를 반환한다."""
    candles = strong_up_candles()
    ind = indicators_from_candles(candles)
    close = np.array([c.close for c in candles])
    clf = RegimeClassifier()
    clf.classify("ETH", ind, close)
    state = clf.get_state("ETH")
    assert isinstance(state, RegimeState)


def test_states_property_returns_dict():
    """states 프로퍼티는 dict를 반환한다."""
    clf = RegimeClassifier()
    assert isinstance(clf.states, dict)
    candles = range_candles()
    ind = indicators_from_candles(candles)
    close = np.array([c.close for c in candles])
    clf.classify("XRP", ind, close)
    assert "XRP" in clf.states
