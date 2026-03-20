"""LIVE 게이트 테스트."""

import pytest

from app.live_gate import LiveGate


@pytest.fixture
def gate() -> LiveGate:
    """기본 LiveGate 인스턴스."""
    return LiveGate()


def _passing_kwargs() -> dict:
    """모든 조건을 통과하는 인자."""
    return {
        "paper_days": 30,
        "total_trades": 150,
        "strategy_expectancy": {"trend_follow": 100, "mean_reversion": 50},
        "mdd_pct": 0.05,
        "max_daily_dd_pct": 0.02,
        "uptime_pct": 0.995,
        "unresolved_auth_errors": 0,
        "slippage_model_error_pct": 0.10,
        "wf_pass_count": 3,
        "wf_total": 4,
        "mc_p5_pnl": 0.01,
    }


class TestLiveGate:
    """LiveGate 검증 테스트."""

    def test_all_pass(self, gate: LiveGate) -> None:
        """모든 조건 통과."""
        result = gate.evaluate(**_passing_kwargs())
        assert result.approved is True
        assert len(result.failures) == 0

    def test_paper_days_fail(self, gate: LiveGate) -> None:
        """PAPER 일수 미달."""
        kw = _passing_kwargs()
        kw["paper_days"] = 20
        result = gate.evaluate(**kw)
        assert result.approved is False
        assert result.checks["paper_days"] is False

    def test_trades_fail(self, gate: LiveGate) -> None:
        """거래 수 미달."""
        kw = _passing_kwargs()
        kw["total_trades"] = 50
        result = gate.evaluate(**kw)
        assert result.approved is False

    def test_expectancy_fail(self, gate: LiveGate) -> None:
        """Expectancy 음수 전략 존재."""
        kw = _passing_kwargs()
        kw["strategy_expectancy"] = {"a": 100, "b": -10}
        result = gate.evaluate(**kw)
        assert result.approved is False
        assert any("Expectancy" in f for f in result.failures)

    def test_mdd_fail(self, gate: LiveGate) -> None:
        """MDD 초과."""
        kw = _passing_kwargs()
        kw["mdd_pct"] = 0.10
        result = gate.evaluate(**kw)
        assert result.approved is False

    def test_daily_dd_fail(self, gate: LiveGate) -> None:
        """일일 DD 초과."""
        kw = _passing_kwargs()
        kw["max_daily_dd_pct"] = 0.04
        result = gate.evaluate(**kw)
        assert result.approved is False

    def test_uptime_fail(self, gate: LiveGate) -> None:
        """가동률 미달."""
        kw = _passing_kwargs()
        kw["uptime_pct"] = 0.95
        result = gate.evaluate(**kw)
        assert result.approved is False

    def test_auth_errors_fail(self, gate: LiveGate) -> None:
        """인증 오류 미해결."""
        kw = _passing_kwargs()
        kw["unresolved_auth_errors"] = 2
        result = gate.evaluate(**kw)
        assert result.approved is False

    def test_slippage_fail(self, gate: LiveGate) -> None:
        """슬리피지 오차 초과."""
        kw = _passing_kwargs()
        kw["slippage_model_error_pct"] = 0.40
        result = gate.evaluate(**kw)
        assert result.approved is False

    def test_wf_fail(self, gate: LiveGate) -> None:
        """Walk-Forward 미달."""
        kw = _passing_kwargs()
        kw["wf_pass_count"] = 1
        result = gate.evaluate(**kw)
        assert result.approved is False

    def test_mc_fail(self, gate: LiveGate) -> None:
        """Monte Carlo P5 미달."""
        kw = _passing_kwargs()
        kw["mc_p5_pnl"] = -0.05
        result = gate.evaluate(**kw)
        assert result.approved is False

    def test_format_report(self, gate: LiveGate) -> None:
        """리포트 포맷 - 통과."""
        result = gate.evaluate(**_passing_kwargs())
        report = gate.format_report(result)
        assert "APPROVED" in report

    def test_single_failure_details(self, gate: LiveGate) -> None:
        """리포트 포맷 - 실패 상세."""
        kw = _passing_kwargs()
        kw["paper_days"] = 10
        result = gate.evaluate(**kw)
        report = gate.format_report(result)
        assert "NOT APPROVED" in report
        assert "paper" in report.lower()
