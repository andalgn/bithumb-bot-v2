"""코인 프로파일러 테스트."""

import pytest

from app.data_types import Candle, Tier
from strategy.coin_profiler import CoinProfiler


def _make_candles(
    base: float, count: int, volatility: float = 0.01
) -> list[Candle]:
    """테스트용 캔들 생성."""
    candles = []
    price = base
    for i in range(count):
        candles.append(Candle(
            timestamp=1000 * (i + 1),
            open=price,
            high=price * (1 + volatility),
            low=price * (1 - volatility),
            close=price,
            volume=1000.0,
        ))
    return candles


@pytest.fixture
def profiler() -> CoinProfiler:
    """테스트용 CoinProfiler."""
    return CoinProfiler(tier1_atr_max=0.009, tier3_atr_min=0.014)


class TestCoinProfiler:
    """코인 프로파일러 테스트."""

    def test_low_volatility_tier1(self, profiler: CoinProfiler) -> None:
        """낮은 변동성 → Tier 1."""
        # 변동성 0.3% → ATR% < 0.9%
        candles = _make_candles(50000000, 400, volatility=0.003)
        params = profiler.classify("BTC", candles)
        assert params.tier == Tier.TIER1
        assert params.position_mult == 1.0

    def test_high_volatility_tier3(self, profiler: CoinProfiler) -> None:
        """높은 변동성 → Tier 3."""
        # 변동성 1.0% → ATR% > 1.4%
        candles = _make_candles(1000, 400, volatility=0.01)
        params = profiler.classify("SMALL", candles)
        assert params.tier == Tier.TIER3
        assert params.position_mult == 1.0

    def test_medium_volatility_tier2(self, profiler: CoinProfiler) -> None:
        """중간 변동성 → Tier 2."""
        # volatility=0.005 → ATR% ~0.9~1.4% 범위
        candles = _make_candles(3000000, 400, volatility=0.005)
        params = profiler.classify("ETH", candles)
        assert params.tier == Tier.TIER2
        assert params.position_mult == 1.0

    def test_default_tier2_for_unknown(self, profiler: CoinProfiler) -> None:
        """미분류 코인 → 기본 Tier 2."""
        params = profiler.get_tier("UNKNOWN")
        assert params.tier == Tier.TIER2

    def test_classify_all(self, profiler: CoinProfiler) -> None:
        """전체 분류."""
        btc = _make_candles(50000000, 400, volatility=0.003)
        small = _make_candles(1000, 400, volatility=0.01)
        result = profiler.classify_all({"BTC": btc, "SMALL": small})
        assert "BTC" in result
        assert "SMALL" in result

    def test_needs_update(self, profiler: CoinProfiler) -> None:
        """최초에는 갱신 필요."""
        assert profiler.needs_update() is True

    def test_tier_params_fields(self, profiler: CoinProfiler) -> None:
        """TierParams 필드 확인."""
        candles = _make_candles(50000000, 400, volatility=0.003)
        params = profiler.classify("BTC", candles)
        assert params.rsi_min > 0
        assert params.rsi_max > params.rsi_min
        assert params.atr_stop_mult > 0
        assert params.spread_limit > 0
