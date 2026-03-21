"""Sensitivity 분석기 재작성 테스트."""

from unittest.mock import MagicMock

from backtesting.sensitivity import SensitivityAnalyzer


def test_sensitivity_calls_replay() -> None:
    """Sensitivity가 근사치가 아닌 replay_with_params를 호출한다."""
    analyzer = SensitivityAnalyzer()
    mock_optimizer = MagicMock()
    mock_optimizer.replay_with_params.return_value = MagicMock(
        sharpe=1.5,
        profit_factor=1.8,
        trades=50,
        win_rate=0.55,
        expectancy=100,
        max_drawdown=0.05,
        total_pnl=5000,
    )
    analyzer.run_with_optimizer(
        optimizer=mock_optimizer,
        base_params={"sl_mult": 2.0, "tp_rr": 3.0},
        strategy_name="trend_follow",
        entries=[],
    )
    assert mock_optimizer.replay_with_params.call_count >= 5  # steps=5


def test_sensitivity_cv_calculation() -> None:
    """CV가 올바르게 계산된다."""
    analyzer = SensitivityAnalyzer(steps=3)
    mock_optimizer = MagicMock()
    mock_optimizer.replay_with_params.return_value = MagicMock(
        sharpe=1.5,
        profit_factor=1.8,
        trades=50,
        win_rate=0.55,
        expectancy=100,
        max_drawdown=0.05,
        total_pnl=5000,
    )
    result = analyzer.run_with_optimizer(
        optimizer=mock_optimizer,
        base_params={"sl_mult": 2.0},
        strategy_name="trend_follow",
        entries=[],
    )
    assert len(result.params) == 1
    assert result.params[0].cv < 0.01  # 동일 결과이므로 CV ≈ 0
    assert result.params[0].verdict == "robust"
