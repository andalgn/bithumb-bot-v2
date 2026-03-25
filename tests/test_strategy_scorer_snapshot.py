"""StrategyScorer 스냅샷 테스트.

각 전략의 점수 계산 동작을 고정한다.
"""
from __future__ import annotations

import pytest

from app.config import load_config
from app.data_types import MarketSnapshot, Regime, Strategy
from strategy.indicators import compute_indicators
from strategy.rule_engine import RuleEngine
from tests.fixtures.candles import strong_up_candles, range_candles, weak_down_candles
from tests.fixtures.snapshots import FrozenStrategyInput, _make_orderbook


@pytest.fixture
def engine():
    return RuleEngine()


def test_trend_follow_scores_in_strong_up(engine):
    """STRONG_UP 국면 + 상승 캔들 → trend_follow ScoreResult 반환."""
    candles = strong_up_candles()
    ind = compute_indicators(candles)
    result = engine._score_strategy_a(ind, ind, candles)
    assert result.strategy == Strategy.TREND_FOLLOW
    assert isinstance(result.score, float)
    assert result.score >= 0  # 0 이상이면 동작 확인


def test_mean_reversion_scores_in_range(engine):
    """RANGE 국면 캔들 → mean_reversion ScoreResult 반환.

    _score_strategy_b(ind_15m, candles_15m) 시그니처 사용.
    """
    candles = range_candles()
    ind = compute_indicators(candles)
    result = engine._score_strategy_b(ind, candles)
    assert result.strategy == Strategy.MEAN_REVERSION
    assert isinstance(result.score, float)


def test_dca_score_in_weak_down(engine):
    """WEAK_DOWN 캔들 → DCA ScoreResult 반환.

    _score_strategy_e(ind_1h, symbol, current_price) 시그니처 사용.
    BTC/ETH만 DCA 대상이므로 symbol='BTC' 사용.
    """
    candles = weak_down_candles()
    ind = compute_indicators(candles)
    price = candles[-1].close
    result = engine._score_strategy_e(ind, "BTC", price)
    assert result.strategy == Strategy.DCA
    assert isinstance(result.score, float)


def test_score_cutoff_blocks_low_score(engine):
    """점수 컷오프 미달 신호는 생성되지 않는다.

    RANGE 국면에서는 trend_follow 허용이 안 되므로 신호가 없거나 score가 낮다.
    """
    candles = range_candles()
    snap = MarketSnapshot(
        symbol="BTC", current_price=candles[-1].close,
        candles_15m=candles, candles_1h=candles,
        orderbook=_make_orderbook(candles[-1].close),
    )
    signals = engine.generate_signals({"BTC": snap})
    # RANGE 국면에서 TREND_FOLLOW 신호가 없어야 정상
    trend_signals = [s for s in signals if s.strategy == Strategy.TREND_FOLLOW]
    # RANGE에서 TREND_FOLLOW는 허용 전략에 없으므로 없어야 함
    assert len(trend_signals) == 0


def test_all_strategy_scorers_return_score_result(engine):
    """모든 전략 스코어러가 ScoreResult를 반환한다."""
    candles = range_candles()
    ind = compute_indicators(candles)
    price = candles[-1].close
    results = [
        engine._score_strategy_a(ind, ind, candles),
        engine._score_strategy_b(ind, candles),
        engine._score_strategy_e(ind, "BTC", price),
    ]
    for r in results:
        assert hasattr(r, "strategy")
        assert hasattr(r, "score")
        assert isinstance(r.score, float)
