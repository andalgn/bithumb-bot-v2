"""DiscordBot 단위 테스트."""

from __future__ import annotations

from unittest.mock import MagicMock

import discord

from bot_discord.bot import DiscordBot


class TestDiscordBotInit:
    """DiscordBot 초기화 테스트."""

    def test_creates_with_required_args(self) -> None:
        mock_bot = MagicMock()
        discord_bot = DiscordBot(
            token="test-token",
            bot=mock_bot,
            guild_id=12345,
        )
        assert discord_bot._token == "test-token"
        assert discord_bot._guild_id == 12345

    def test_has_all_commands(self) -> None:
        mock_bot = MagicMock()
        discord_bot = DiscordBot(
            token="test-token",
            bot=mock_bot,
            guild_id=12345,
        )
        expected_commands = {
            "status",
            "positions",
            "pnl",
            "regime",
            "risk",
            "shadows",
            "pool",
            "balance",
            "pause",
            "resume",
            "golive",
            "close",
            "restore_params",
            "help",
        }
        guild = discord.Object(id=12345)
        registered = {cmd.name for cmd in discord_bot._tree.get_commands(guild=guild)}
        assert registered == expected_commands

    def test_admin_commands_have_checks(self) -> None:
        mock_bot = MagicMock()
        discord_bot = DiscordBot(
            token="test-token",
            bot=mock_bot,
            guild_id=12345,
        )
        guild = discord.Object(id=12345)
        admin_cmds = {"pause", "resume", "golive", "close", "restore_params"}
        for cmd in discord_bot._tree.get_commands(guild=guild):
            if cmd.name in admin_cmds:
                assert len(cmd.checks) > 0, f"{cmd.name} should have admin check"

    def test_proxy_passed_to_client(self) -> None:
        mock_bot = MagicMock()
        discord_bot = DiscordBot(
            token="test-token",
            bot=mock_bot,
            guild_id=12345,
            proxy="http://127.0.0.1:1081",
        )
        assert discord_bot._proxy == "http://127.0.0.1:1081"
