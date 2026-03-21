"""BacktestConfig 파싱 + daemon 설정 주입 테스트."""

from unittest.mock import MagicMock

from app.config import BacktestConfig, load_config
from backtesting.daemon import BacktestDaemon


def test_config_has_backtest():
    """config에 backtest 필드가 있다."""
    config = load_config()
    assert hasattr(config, "backtest")


def test_backtest_wf_fields():
    """backtest.wf 필드가 config.yaml 값을 반영한다."""
    config = load_config()
    bt = config.backtest
    assert bt.wf_time == "00:30"
    assert bt.wf_data_days == 30
    assert bt.wf_segments == 4


def test_backtest_mc_fields():
    """backtest.mc 필드가 config.yaml 값을 반영한다."""
    config = load_config()
    bt = config.backtest
    assert bt.mc_time == "01:00"
    assert bt.mc_day == "sunday"
    assert bt.mc_iterations == 1000


def test_backtest_sens_fields():
    """backtest.sensitivity 필드가 config.yaml 값을 반영한다."""
    config = load_config()
    bt = config.backtest
    assert bt.sens_variation_pct == 0.1
    assert bt.sens_steps == 5


def test_daemon_uses_config_wf_segments():
    """데몬이 config의 wf_segments를 사용한다."""
    bt_config = BacktestConfig(wf_segments=6, wf_data_days=180)
    journal = MagicMock()
    daemon = BacktestDaemon(journal=journal, config=bt_config)
    assert daemon._walk_forward._num_segments == 6


def test_daemon_uses_config_mc_iterations():
    """데몬이 config의 mc_iterations를 사용한다."""
    bt_config = BacktestConfig(mc_iterations=500)
    journal = MagicMock()
    daemon = BacktestDaemon(journal=journal, config=bt_config)
    assert daemon._monte_carlo._iterations == 500


def test_daemon_uses_config_sens_steps():
    """데몬이 config의 sens_steps를 사용한다."""
    bt_config = BacktestConfig(sens_steps=3, sens_variation_pct=0.2)
    journal = MagicMock()
    daemon = BacktestDaemon(journal=journal, config=bt_config)
    assert daemon._sensitivity._steps == 3
