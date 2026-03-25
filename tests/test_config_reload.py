"""Config 핫 리로드 테스트."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml


class TestConfigReload:
    """_check_config_reload 테스트."""

    def _make_bot(self, tmp_path: Path) -> MagicMock:
        """최소한의 TradingBot mock을 생성한다."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            yaml.dump(
                {
                    "run_mode": "DRY",
                    "coins": ["BTC"],
                    "strategy_params": {"mean_reversion": {"sl_mult": 3.0}},
                }
            )
        )

        bot = MagicMock()
        bot._config_path = config_path
        bot._config_mtime = config_path.stat().st_mtime
        bot._rule_engine = MagicMock()
        bot._rule_engine._strategy_params = {"mean_reversion": {"sl_mult": 3.0}}
        return bot

    def test_no_reload_when_unchanged(self, tmp_path: Path) -> None:
        """mtime 미변경 시 리로드하지 않는다."""
        from app.main import TradingBot

        bot = self._make_bot(tmp_path)
        old_params = bot._rule_engine._strategy_params

        TradingBot._check_config_reload(bot)

        # strategy_params가 변경되지 않아야 함
        assert bot._rule_engine._strategy_params == old_params

    def test_reload_when_changed(self, tmp_path: Path) -> None:
        """mtime 변경 시 strategy_params를 리로드한다."""
        from app.main import TradingBot

        bot = self._make_bot(tmp_path)

        # config 수정
        time.sleep(0.1)  # mtime 차이 확보
        bot._config_path.write_text(
            yaml.dump(
                {
                    "run_mode": "DRY",
                    "coins": ["BTC"],
                    "strategy_params": {"mean_reversion": {"sl_mult": 5.0}},
                }
            )
        )

        with patch("app.main.load_config") as mock_load:
            mock_config = MagicMock()
            mock_config.strategy_params = {"mean_reversion": {"sl_mult": 5.0}}
            mock_load.return_value = mock_config

            TradingBot._check_config_reload(bot)

            mock_load.assert_called_once()
            bot._rule_engine.update_strategy_params.assert_called_once_with(
                {"mean_reversion": {"sl_mult": 5.0}}
            )

    def test_keeps_old_config_on_parse_error(self, tmp_path: Path) -> None:
        """파싱 실패 시 기존 설정을 유지한다."""
        from app.main import TradingBot

        bot = self._make_bot(tmp_path)
        old_params = {"mean_reversion": {"sl_mult": 3.0}}
        bot._rule_engine._strategy_params = old_params

        # config를 잘못된 내용으로 수정
        time.sleep(0.1)
        bot._config_path.write_text("invalid: yaml: [[[")

        with patch("app.main.load_config", side_effect=Exception("parse error")):
            TradingBot._check_config_reload(bot)

        bot._rule_engine.update_strategy_params.assert_not_called()
