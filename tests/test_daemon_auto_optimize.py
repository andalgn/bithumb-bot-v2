"""자동 최적화 + config 반영 테스트."""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import yaml

from app.config import BacktestConfig
from backtesting.daemon import BacktestDaemon


def test_auto_optimize_disabled():
    """auto_optimize_enabled=False면 최적화를 건너뛴다."""
    config = BacktestConfig(auto_optimize_enabled=False)
    journal = MagicMock()
    daemon = BacktestDaemon(journal=journal, config=config)
    result = asyncio.get_event_loop().run_until_complete(
        daemon._run_auto_optimize()
    )
    assert result == []


def test_auto_optimize_no_store():
    """store 없으면 최적화를 건너뛴다."""
    journal = MagicMock()
    daemon = BacktestDaemon(journal=journal)
    result = asyncio.get_event_loop().run_until_complete(
        daemon._run_auto_optimize()
    )
    assert result == []


def test_collect_candles_no_store():
    """store 없으면 데이터 수집을 건너뛴다."""
    journal = MagicMock()
    daemon = BacktestDaemon(journal=journal)
    result = asyncio.get_event_loop().run_until_complete(
        daemon._collect_candles()
    )
    assert result == 0


def test_apply_params_creates_backup():
    """config 적용 시 백업 파일이 생성된다."""
    config = BacktestConfig(auto_apply_min_pf=1.0, auto_apply_min_trades=5)
    journal = MagicMock()
    daemon = BacktestDaemon(journal=journal, config=config)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False,
    ) as f:
        yaml.dump({"strategy_params": {"trend_follow": {"sl_mult": 1.0}}}, f)
        tmp_path = Path(f.name)

    try:
        daemon._apply_optimized_params(
            strategy="trend_follow",
            params={"sl_mult": 3.0, "tp_rr": 2.0},
            config_path=tmp_path,
        )
        backups = list(tmp_path.parent.glob(f"{tmp_path.stem}*.bak.*"))
        assert len(backups) >= 1

        with open(tmp_path) as f:
            updated = yaml.safe_load(f)
        assert updated["strategy_params"]["trend_follow"]["sl_mult"] == 3.0
        assert updated["strategy_params"]["trend_follow"]["tp_rr"] == 2.0
    finally:
        tmp_path.unlink(missing_ok=True)
        for b in tmp_path.parent.glob(f"{tmp_path.stem}*.bak.*"):
            b.unlink(missing_ok=True)


def test_parse_time():
    """시간 문자열 파싱."""
    assert BacktestDaemon._parse_time("02:30") == (2, 30)
    assert BacktestDaemon._parse_time("00:00") == (0, 0)


def test_parse_weekday():
    """요일 문자열 파싱."""
    assert BacktestDaemon._parse_weekday("sunday") == 6
    assert BacktestDaemon._parse_weekday("monday") == 0
