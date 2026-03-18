"""Monte Carlo 시뮬레이션 테스트."""

import pytest

from backtesting.monte_carlo import MonteCarlo


@pytest.fixture
def mc() -> MonteCarlo:
    """테스트용 MonteCarlo (100회로 축소)."""
    return MonteCarlo(iterations=100)


class TestMonteCarlo:
    """Monte Carlo 테스트."""

    def test_empty_pnl(self, mc: MonteCarlo) -> None:
        """빈 PnL → caution."""
        result = mc.run([])
        assert result.verdict == "caution"

    def test_all_positive(self, mc: MonteCarlo) -> None:
        """전부 수익 → safe."""
        pnl = [1000.0] * 30
        result = mc.run(pnl)
        assert result.verdict == "safe"
        assert result.pnl_percentile_5 > 0

    def test_all_negative(self, mc: MonteCarlo) -> None:
        """전부 손실 → danger."""
        pnl = [-5000.0] * 30
        result = mc.run(pnl)
        assert result.verdict == "danger"
        assert result.pnl_percentile_5 < 0

    def test_mixed_pnl(self, mc: MonteCarlo) -> None:
        """혼합 PnL."""
        pnl = [2000, -1000, 3000, -500, 1500, -2000] * 5
        result = mc.run(pnl)
        assert result.iterations == 100
        assert result.worst_mdd >= 0

    def test_mdd_warning(self) -> None:
        """MDD 경고."""
        mc = MonteCarlo(iterations=50, danger_mdd_pct=0.01)
        pnl = [10000, -50000, 20000, -30000] * 5
        result = mc.run(pnl)
        assert result.sizing_warning is True

    def test_percentiles_order(self, mc: MonteCarlo) -> None:
        """P5 <= P50 <= P95."""
        pnl = [1000, -500, 2000, -1500, 3000] * 6
        result = mc.run(pnl)
        assert result.pnl_percentile_5 <= result.pnl_percentile_50
        assert result.pnl_percentile_50 <= result.pnl_percentile_95
