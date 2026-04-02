"""StrategyScorer 직접 단위 테스트."""

from __future__ import annotations

from app.data_types import Strategy
from strategy.strategy_scorer import ScoreResult, StrategyScorer
from tests.fixtures.candles import strong_up_candles, weak_down_candles
from tests.fixtures.indicators import indicators_from_candles


def test_score_strategy_a_returns_score_result():
    """score_strategy_a는 TREND_FOLLOW 전략의 ScoreResult를 반환한다."""
    candles = strong_up_candles()
    ind = indicators_from_candles(candles)
    scorer = StrategyScorer()
    result = scorer.score_strategy_a(ind_15m=ind, ind_1h=ind, candles_15m=candles)
    assert isinstance(result, ScoreResult)
    assert result.strategy == Strategy.TREND_FOLLOW
    assert 0.0 <= result.score <= 100.0
    assert isinstance(result.detail, dict)


def test_score_strategy_b_returns_score_result():
    """score_strategy_b는 MEAN_REVERSION 전략의 ScoreResult를 반환한다."""
    candles = weak_down_candles()
    ind = indicators_from_candles(candles)
    scorer = StrategyScorer()
    result = scorer.score_strategy_b(ind_15m=ind, candles_15m=candles)
    assert isinstance(result, ScoreResult)
    assert result.strategy == Strategy.MEAN_REVERSION
    assert result.score >= 0.0
    assert isinstance(result.detail, dict)


def test_score_strategy_a_strong_up_higher_than_weak_down():
    """STRONG_UP 캔들에서 전략 A 점수가 WEAK_DOWN보다 높다."""
    candles_up = strong_up_candles()
    candles_down = weak_down_candles()
    ind_up = indicators_from_candles(candles_up)
    ind_down = indicators_from_candles(candles_down)
    scorer = StrategyScorer()
    score_up = scorer.score_strategy_a(ind_15m=ind_up, ind_1h=ind_up, candles_15m=candles_up).score
    score_down = scorer.score_strategy_a(
        ind_15m=ind_down, ind_1h=ind_down, candles_15m=candles_down
    ).score
    assert score_up > score_down


def test_get_weights_returns_dict():
    """get_weights는 전략 가중치 dict를 반환한다."""
    scorer = StrategyScorer()
    weights = scorer.get_weights("trend_follow")
    assert isinstance(weights, dict)
    assert len(weights) > 0
    # 가중치 합계가 100에 가까워야 한다
    total = sum(weights.values())
    assert 99.0 <= total <= 101.0


def test_get_weights_config_override():
    """strategy_params에 w_ 접두사 항목이 있으면 가중치가 오버라이드된다."""
    params = {"trend_follow": {"w_trend_align": 50.0}}
    scorer = StrategyScorer(strategy_params=params)
    weights = scorer.get_weights("trend_follow")
    assert weights["trend_align"] == 50.0


def test_score_strategy_c_has_bb_squeeze_key():
    """score_strategy_c 결과에 bb_squeeze 키가 항상 존재한다."""
    candles = strong_up_candles()
    ind = indicators_from_candles(candles)
    scorer = StrategyScorer()
    result = scorer.score_strategy_c(ind_15m=ind, ind_1h=ind, candles_15m=candles)
    assert "bb_squeeze" in result.detail
    assert result.detail["bb_squeeze"] >= 0.0


def test_score_strategy_c_bb_squeeze_not_applied_when_adx_low():
    """ADX < 20 환경에서는 bb_squeeze 보너스가 0이다."""
    # range_candles는 ADX < 20 조건을 충족
    from tests.fixtures.candles import range_candles

    candles = range_candles()
    ind = indicators_from_candles(candles)
    scorer = StrategyScorer()
    result = scorer.score_strategy_c(ind_15m=ind, ind_1h=ind, candles_15m=candles)
    # ADX < 20이므로 bb_squeeze 보너스 없음
    assert result.detail.get("bb_squeeze", 0.0) == 0.0
