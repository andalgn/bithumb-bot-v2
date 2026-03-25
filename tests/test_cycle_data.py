from app.cycle_data import MarketData
from app.data_types import Regime


def test_market_data_defaults():
    data = MarketData()
    assert data.snapshots == {}
    assert data.current_prices == {}
    assert data.indicators_1h == {}
    assert data.regimes == {}


def test_market_data_populated():
    data = MarketData(
        current_prices={"BTC": 100_000_000.0},
        regimes={"BTC": Regime.STRONG_UP},
    )
    assert data.current_prices["BTC"] == 100_000_000.0
    assert data.regimes["BTC"] == Regime.STRONG_UP
