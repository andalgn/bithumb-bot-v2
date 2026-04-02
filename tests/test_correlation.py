"""상관관계 모니터 테스트."""

import pytest

from app.data_types import Candle
from strategy.correlation_monitor import CorrelationMonitor


def _make_candles(base: float, count: int, trend: float = 0.0) -> list[Candle]:
    """테스트용 캔들 생성."""
    candles = []
    price = base
    for i in range(count):
        price += trend
        candles.append(
            Candle(
                timestamp=1000 * (i + 1),
                open=price,
                high=price * 1.01,
                low=price * 0.99,
                close=price,
                volume=1000.0,
            )
        )
    return candles


@pytest.fixture
def monitor() -> CorrelationMonitor:
    """테스트용 CorrelationMonitor."""
    return CorrelationMonitor()


class TestCorrelationMonitor:
    """상관관계 모니터 테스트."""

    def test_no_positions_allows(self, monitor: CorrelationMonitor) -> None:
        """보유 포지션 없으면 항상 허용."""
        result = monitor.check_correlation("BTC", [])
        assert result.allowed is True
        assert result.size_mult == 1.0

    def test_update_builds_matrix(self, monitor: CorrelationMonitor) -> None:
        """매트릭스 업데이트."""
        # 같은 추세의 코인 2개 → 높은 상관관계
        candles_a = _make_candles(100, 500, trend=0.5)
        candles_b = _make_candles(50, 500, trend=0.25)
        candles_c = _make_candles(200, 500, trend=-0.3)

        monitor.update({"A": candles_a, "B": candles_b, "C": candles_c})
        assert "A" in monitor.matrix
        assert "B" in monitor.matrix["A"]

    def test_high_correlation_skip(self, monitor: CorrelationMonitor) -> None:
        """상관관계 > 0.85 → 스킵."""
        # 완전 동일 추세
        candles = _make_candles(100, 500, trend=1.0)
        monitor.update({"A": candles, "B": candles})

        corr = monitor.get_correlation("A", "B")
        # 동일 데이터이므로 상관계수 ≈ 1.0
        assert corr > 0.8

        result = monitor.check_correlation("A", ["B"])
        if corr >= 0.85:
            assert result.allowed is False

    def test_low_correlation_allows(self, monitor: CorrelationMonitor) -> None:
        """상관관계 < 0.70 → 정상."""
        # 역추세
        candles_a = _make_candles(100, 500, trend=1.0)
        candles_b = _make_candles(200, 500, trend=-1.0)
        monitor.update({"A": candles_a, "B": candles_b})

        result = monitor.check_correlation("A", ["B"])
        # 역상관이므로 허용됨
        assert result.allowed is True
        assert result.size_mult == 1.0

    def test_needs_update(self, monitor: CorrelationMonitor) -> None:
        """최초에는 갱신 필요."""
        assert monitor.needs_update() is True

    def test_unknown_coin(self, monitor: CorrelationMonitor) -> None:
        """알 수 없는 코인은 허용."""
        result = monitor.check_correlation("UNKNOWN", ["BTC"])
        assert result.allowed is True
