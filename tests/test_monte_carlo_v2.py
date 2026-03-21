"""Monte Carlo P10 추가 테스트."""
from backtesting.monte_carlo import MonteCarlo


def test_mc_result_has_p10():
    """MonteCarloResult에 pnl_percentile_10 필드가 있다."""
    mc = MonteCarlo(iterations=100)
    pnl_list = [100, -50, 200, -30, 150, -80, 120, -40, 90, -60] * 10
    result = mc.run(pnl_list, initial_equity=10_000_000)
    assert hasattr(result, "pnl_percentile_10")
    assert isinstance(result.pnl_percentile_10, float)


def test_mc_verdict_uses_p10():
    """P10 > 0 AND P5 > -2% 기준으로 verdict 판단."""
    mc = MonteCarlo(iterations=100)
    # 대부분 수익인 PnL → safe
    pnl_list = [100_000] * 80 + [-50_000] * 20
    result = mc.run(pnl_list, initial_equity=10_000_000)
    assert result.verdict == "safe"
