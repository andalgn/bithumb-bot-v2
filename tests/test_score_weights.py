"""점수 가중치 외부화 테스트."""

from strategy.rule_engine import DEFAULT_WEIGHTS, RuleEngine


def test_default_weights():
    """strategy_params 없으면 기본 가중치를 사용한다."""
    engine = RuleEngine()
    weights = engine._get_weights("trend_follow")
    assert weights["trend_align"] == 30
    assert weights["macd"] == 25
    assert weights["volume"] == 20
    assert weights["rsi_pullback"] == 15
    assert weights["supertrend"] == 10


def test_custom_weights():
    """strategy_params에서 가중치를 읽는다."""
    params = {
        "trend_follow": {
            "sl_mult": 3.0,
            "w_trend_align": 35,
            "w_macd": 30,
        },
    }
    engine = RuleEngine(strategy_params=params)
    weights = engine._get_weights("trend_follow")
    assert weights["trend_align"] == 35
    assert weights["macd"] == 30
    assert weights["volume"] == 20  # default
    assert weights["rsi_pullback"] == 15  # default


def test_default_weights_constant():
    """DEFAULT_WEIGHTS에 trend_follow이 있다."""
    assert "trend_follow" in DEFAULT_WEIGHTS
    assert sum(DEFAULT_WEIGHTS["trend_follow"].values()) == 100
