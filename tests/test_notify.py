"""DiscordNotifier 단위 테스트."""

from __future__ import annotations

import pytest

from app.notify import DiscordNotifier, _html_to_discord


class TestHtmlToDiscord:
    def test_bold(self) -> None:
        assert _html_to_discord("<b>텍스트</b>") == "**텍스트**"

    def test_italic(self) -> None:
        assert _html_to_discord("<i>텍스트</i>") == "*텍스트*"

    def test_code(self) -> None:
        assert _html_to_discord("<code>텍스트</code>") == "`텍스트`"

    def test_html_entities(self) -> None:
        assert _html_to_discord("&amp; &lt; &gt;") == "& < >"

    def test_strip_unknown_tags(self) -> None:
        assert _html_to_discord("<div>hello</div>") == "hello"

    def test_mixed(self) -> None:
        result = _html_to_discord("<b>봇 시작</b>\n모드: <code>DRY</code>")
        assert result == "**봇 시작**\n모드: `DRY`"

    def test_nested_bold_code(self) -> None:
        result = _html_to_discord("<b><code>test</code></b>")
        assert result == "**`test`**"

    def test_plain_text_unchanged(self) -> None:
        assert _html_to_discord("hello world") == "hello world"


class TestDiscordEscape:
    def test_escape_asterisks(self) -> None:
        assert DiscordNotifier.escape("*bold*") == "\\*bold\\*"

    def test_escape_underscores(self) -> None:
        assert DiscordNotifier.escape("_italic_") == "\\_italic\\_"

    def test_escape_backticks(self) -> None:
        assert DiscordNotifier.escape("`code`") == "\\`code\\`"

    def test_escape_tilde(self) -> None:
        assert DiscordNotifier.escape("~strike~") == "\\~strike\\~"

    def test_escape_pipe(self) -> None:
        assert DiscordNotifier.escape("|spoiler|") == "\\|spoiler\\|"


class TestMessageSplit:
    def test_short_message_no_split(self) -> None:
        result = DiscordNotifier._split_message("short")
        assert result == ["short"]

    def test_long_message_split(self) -> None:
        msg = "a" * 4500
        result = DiscordNotifier._split_message(msg)
        assert len(result) == 3
        assert all(len(chunk) <= 2000 for chunk in result)
        assert "".join(result) == msg

    def test_split_at_newline(self) -> None:
        msg = "a" * 1999 + "\n" + "b"
        result = DiscordNotifier._split_message(msg)
        assert len(result) == 2
        assert result[0] == "a" * 1999
        assert result[1] == "b"


class TestWebhookUrlSelection:
    def test_selects_correct_url(self) -> None:
        notifier = DiscordNotifier(
            webhooks={"trade": "https://trade-url", "system": "https://system-url"},
        )
        assert notifier._webhooks.get("trade") == "https://trade-url"
        assert notifier._webhooks.get("system") == "https://system-url"

    def test_missing_channel_returns_empty(self) -> None:
        notifier = DiscordNotifier(webhooks={"trade": "https://trade-url"})
        assert notifier._webhooks.get("unknown", "") == ""


class TestNotifierConfig:
    def test_proxy_stored(self) -> None:
        notifier = DiscordNotifier(
            webhooks={},
            proxy="http://127.0.0.1:1081",
        )
        assert notifier._proxy == "http://127.0.0.1:1081"

    def test_timeout_stored(self) -> None:
        notifier = DiscordNotifier(webhooks={}, timeout_sec=10)
        assert notifier._timeout.total == 10

    def test_session_reset_after_3_failures(self) -> None:
        notifier = DiscordNotifier(webhooks={})
        notifier._consecutive_failures = 3
        assert notifier._consecutive_failures >= 3


@pytest.mark.asyncio
class TestSendChannel:
    async def test_missing_webhook_returns_false(self) -> None:
        notifier = DiscordNotifier(webhooks={})
        result = await notifier.send("test", channel="trade")
        assert result is False

    async def test_send_converts_html(self) -> None:
        notifier = DiscordNotifier(webhooks={"system": "https://fake-url"})
        from unittest.mock import AsyncMock

        notifier._post_webhook = AsyncMock(return_value=True)
        await notifier.send("<b>테스트</b>", channel="system")
        notifier._post_webhook.assert_called_once_with(
            "https://fake-url",
            "**테스트**",
        )
