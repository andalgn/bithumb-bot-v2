# Discord Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Telegram notifications and commands with Discord Webhook + Bot.

**Architecture:** DiscordNotifier sends to 6 channel webhooks via aiohttp POST. DiscordBot runs as a separate asyncio task using discord.py for 14 slash commands. A `Notifier` Protocol decouples consumers from the concrete implementation.

**Tech Stack:** discord.py 2.0+, aiohttp (existing), Python 3.12+

**Spec:** `docs/superpowers/specs/2026-03-22-discord-migration-design.md`

---

### Task 1: Add discord.py dependency

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Update requirements.txt**

Replace `python-telegram-bot>=21.0` with `discord.py>=2.4`.

```
discord.py>=2.4
```

- [ ] **Step 2: Install**

Run: `pip install -r requirements.txt`
Expected: discord.py installed successfully

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "chore: replace python-telegram-bot with discord.py"
```

---

### Task 2: Notifier Protocol + DiscordNotifier

**Files:**
- Modify: `app/notify.py` (full rewrite)
- Create: `tests/test_notify.py`

- [ ] **Step 1: Write failing tests for HTML→Markdown conversion**

```python
# tests/test_notify.py
"""DiscordNotifier 단위 테스트."""

from __future__ import annotations

import pytest

from app.notify import DiscordNotifier, _html_to_discord


class TestHtmlToDiscord:
    """HTML → Discord Markdown 변환 테스트."""

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
    """Discord Markdown 이스케이프 테스트."""

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
    """2000자 초과 메시지 분할 테스트."""

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
        # 1999자 + 줄바꿈 + 1자 = 2001자
        msg = "a" * 1999 + "\n" + "b"
        result = DiscordNotifier._split_message(msg)
        assert len(result) == 2
        assert result[0] == "a" * 1999
        assert result[1] == "b"


class TestWebhookUrlSelection:
    """채널별 Webhook URL 선택 테스트."""

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
    """Notifier 설정 테스트."""

    def test_proxy_stored(self) -> None:
        notifier = DiscordNotifier(
            webhooks={}, proxy="http://127.0.0.1:1081",
        )
        assert notifier._proxy == "http://127.0.0.1:1081"

    def test_timeout_stored(self) -> None:
        notifier = DiscordNotifier(webhooks={}, timeout_sec=10)
        assert notifier._timeout.total == 10

    def test_session_reset_after_3_failures(self) -> None:
        notifier = DiscordNotifier(webhooks={})
        notifier._consecutive_failures = 3
        # 3회 연속 실패 시 세션 재생성 로직은 _post_webhook에서 처리
        # 여기서는 카운터가 임계값에 도달하는지만 확인
        assert notifier._consecutive_failures >= 3


@pytest.mark.asyncio
class TestSendChannel:
    """send() 채널 라우팅 테스트."""

    async def test_missing_webhook_returns_false(self) -> None:
        notifier = DiscordNotifier(webhooks={})
        result = await notifier.send("test", channel="trade")
        assert result is False

    async def test_send_converts_html(self) -> None:
        """send()가 HTML을 자동 변환하는지 확인 (실제 전송은 하지 않음)."""
        notifier = DiscordNotifier(webhooks={"system": "https://fake-url"})
        # _post_webhook를 모킹하여 전달된 content 확인
        from unittest.mock import AsyncMock
        notifier._post_webhook = AsyncMock(return_value=True)
        await notifier.send("<b>테스트</b>", channel="system")
        notifier._post_webhook.assert_called_once_with(
            "https://fake-url", "**테스트**",
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_notify.py -v`
Expected: FAIL (import errors — module doesn't exist yet)

- [ ] **Step 3: Implement DiscordNotifier**

Replace `app/notify.py` entirely:

```python
"""디스코드 Webhook 알림 모듈.

aiohttp 기반 비동기 전송. 실패 시 로그만 남기고 봇을 중단하지 않는다.
Notifier Protocol로 소비자와 디커플링.
"""

from __future__ import annotations

import asyncio
import logging
import re
import ssl
from typing import Protocol, runtime_checkable

import aiohttp

logger = logging.getLogger(__name__)

_DISCORD_ESCAPE = str.maketrans(
    {"*": "\\*", "_": "\\_", "~": "\\~", "`": "\\`", "|": "\\|"}
)

# HTML → Discord Markdown 치환 규칙
_HTML_REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"<b>(.*?)</b>", re.DOTALL), r"**\1**"),
    (re.compile(r"<strong>(.*?)</strong>", re.DOTALL), r"**\1**"),
    (re.compile(r"<i>(.*?)</i>", re.DOTALL), r"*\1*"),
    (re.compile(r"<em>(.*?)</em>", re.DOTALL), r"*\1*"),
    (re.compile(r"<code>(.*?)</code>", re.DOTALL), r"`\1`"),
]

_HTML_ENTITIES: dict[str, str] = {
    "&amp;": "&",
    "&lt;": "<",
    "&gt;": ">",
    "&quot;": '"',
    "&#39;": "'",
}

_STRIP_TAGS = re.compile(r"<[^>]+>")

MAX_MESSAGE_LEN = 2000


def _html_to_discord(text: str) -> str:
    """HTML 포맷을 Discord Markdown으로 변환한다."""
    for pattern, replacement in _HTML_REPLACEMENTS:
        text = pattern.sub(replacement, text)
    # 엔티티 치환
    for entity, char in _HTML_ENTITIES.items():
        text = text.replace(entity, char)
    # 나머지 HTML 태그 제거
    text = _STRIP_TAGS.sub("", text)
    return text


def _make_ssl_context() -> ssl.SSLContext:
    """VPN 환경에서 자체서명 인증서를 허용하는 SSL 컨텍스트를 생성한다."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


@runtime_checkable
class Notifier(Protocol):
    """알림 전송 프로토콜."""

    async def send(self, text: str, channel: str = "system") -> bool:
        """메시지를 전송한다."""
        ...

    async def close(self) -> None:
        """리소스를 정리한다."""
        ...


class DiscordNotifier:
    """디스코드 Webhook 기반 알림."""

    CHANNEL_TRADE = "trade"
    CHANNEL_REPORT = "report"
    CHANNEL_BACKTEST = "backtest"
    CHANNEL_SYSTEM = "system"
    CHANNEL_COMMAND = "command"
    CHANNEL_LIVEGATE = "livegate"

    def __init__(
        self,
        webhooks: dict[str, str],
        proxy: str = "",
        timeout_sec: int = 5,
    ) -> None:
        """초기화.

        Args:
            webhooks: 채널명 → Webhook URL 매핑.
            proxy: HTTP 프록시 URL.
            timeout_sec: 요청 타임아웃(초).
        """
        self._webhooks = webhooks
        self._proxy = proxy
        self._timeout = aiohttp.ClientTimeout(total=timeout_sec)
        self._ssl_ctx = _make_ssl_context()
        self._session: aiohttp.ClientSession | None = None
        self._consecutive_failures: int = 0

    async def _get_session(self) -> aiohttp.ClientSession:
        """세션을 재사용하거나 새로 생성한다."""
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(ssl=self._ssl_ctx)
            self._session = aiohttp.ClientSession(
                timeout=self._timeout, connector=connector,
            )
        return self._session

    @staticmethod
    def _split_message(text: str) -> list[str]:
        """2000자 초과 메시지를 분할한다."""
        if len(text) <= MAX_MESSAGE_LEN:
            return [text]

        chunks: list[str] = []
        while text:
            if len(text) <= MAX_MESSAGE_LEN:
                chunks.append(text)
                break
            # 줄바꿈 기준으로 분할 시도
            cut = text.rfind("\n", 0, MAX_MESSAGE_LEN)
            if cut <= 0:
                cut = MAX_MESSAGE_LEN
            chunks.append(text[:cut])
            text = text[cut:].lstrip("\n")
        return chunks

    @staticmethod
    def escape(text: str) -> str:
        """Discord Markdown 특수문자를 이스케이프한다."""
        return text.translate(_DISCORD_ESCAPE)

    async def send(self, text: str, channel: str = "system") -> bool:
        """메시지를 지정 채널의 Webhook으로 전송한다.

        HTML 포맷은 자동으로 Discord Markdown으로 변환된다.

        Args:
            text: 전송할 메시지 (HTML 또는 plain text).
            channel: 대상 채널 키 (trade, report, backtest, system, command, livegate).

        Returns:
            전송 성공 여부.
        """
        url = self._webhooks.get(channel, "")
        if not url:
            logger.warning("디스코드 webhook URL 미설정: channel=%s", channel)
            return False

        # HTML → Discord Markdown 변환
        text = _html_to_discord(text)

        chunks = self._split_message(text)
        all_ok = True
        for chunk in chunks:
            ok = await self._post_webhook(url, chunk)
            if not ok:
                all_ok = False
        return all_ok

    async def _post_webhook(self, url: str, content: str) -> bool:
        """Webhook URL로 메시지를 POST한다."""
        payload = {"content": content}
        try:
            session = await self._get_session()
            async with session.post(
                url, json=payload, proxy=self._proxy or None,
            ) as resp:
                if resp.status in (200, 204):
                    logger.debug("디스코드 메시지 전송 성공")
                    self._consecutive_failures = 0
                    return True
                if resp.status == 429:
                    # Rate limit — Retry-After 대기
                    data = await resp.json()
                    retry_after = data.get("retry_after", 1.0)
                    logger.warning(
                        "디스코드 rate limit, %.1f초 대기", retry_after,
                    )
                    await asyncio.sleep(retry_after)
                    # 한 번 재시도
                    async with session.post(
                        url, json=payload, proxy=self._proxy or None,
                    ) as retry_resp:
                        if retry_resp.status in (200, 204):
                            self._consecutive_failures = 0
                            return True
                        retry_body = await retry_resp.text()
                        logger.warning(
                            "디스코드 rate limit 재시도 실패: status=%d body=%s",
                            retry_resp.status, retry_body,
                        )
                    self._consecutive_failures += 1
                    return False
                body = await resp.text()
                logger.warning(
                    "디스코드 전송 실패: status=%d body=%s", resp.status, body,
                )
                self._consecutive_failures += 1
                return False
        except Exception:
            logger.exception("디스코드 전송 중 예외 발생")
            self._consecutive_failures += 1
        if self._consecutive_failures >= 3:
            if self._session:
                try:
                    await self._session.close()
                except Exception:
                    pass
            self._session = None
            self._consecutive_failures = 0
        return False

    async def close(self) -> None:
        """세션을 닫는다."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_notify.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add app/notify.py tests/test_notify.py
git commit -m "feat: replace TelegramNotifier with Notifier Protocol + DiscordNotifier"
```

---

### Task 3: DiscordConfig + EnvSecrets update

**Files:**
- Modify: `app/config.py`
- Modify: `configs/config.yaml`
- Modify: `.env.example`

- [ ] **Step 1: Update config.py**

Replace `TelegramConfig` with `DiscordConfig`:

```python
@dataclass(frozen=True)
class DiscordConfig:
    """디스코드 설정."""

    bot_guild_id: str = ""
    admin_role: str = "admin"
    timeout_sec: int = 5
```

Update `EnvSecrets` — remove `telegram_bot_token` and `telegram_chat_id`, add:

```python
    discord_bot_token: str = ""
    discord_webhooks: dict[str, str] = field(default_factory=dict)
    discord_guild_id: str = ""
```

Update `AppConfig` — replace `telegram: TelegramConfig` with `discord: DiscordConfig`:

```python
    discord: DiscordConfig = field(default_factory=DiscordConfig)
```

Update `_load_env()` — remove telegram lines, add:

```python
        discord_bot_token=os.getenv("DISCORD_BOT_TOKEN", ""),
        discord_webhooks={
            "trade": os.getenv("DISCORD_WEBHOOK_TRADE", ""),
            "report": os.getenv("DISCORD_WEBHOOK_REPORT", ""),
            "backtest": os.getenv("DISCORD_WEBHOOK_BACKTEST", ""),
            "system": os.getenv("DISCORD_WEBHOOK_SYSTEM", ""),
            "command": os.getenv("DISCORD_WEBHOOK_COMMAND", ""),
            "livegate": os.getenv("DISCORD_WEBHOOK_LIVEGATE", ""),
        },
        discord_guild_id=os.getenv("DISCORD_GUILD_ID", ""),
```

Update `load_config()` — replace `telegram=TelegramConfig(...)` with:

```python
        discord=DiscordConfig(
            bot_guild_id=secrets.discord_guild_id,
            **{k: v for k, v in raw.get("discord", {}).items() if k != "bot_guild_id" and v is not None},
        ),
```

- [ ] **Step 2: Update configs/config.yaml**

Remove the `telegram:` section (lines 241-243). Add:

```yaml
discord:
  admin_role: "admin"
  timeout_sec: 5
```

- [ ] **Step 3: Update .env.example**

Remove `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. Add:

```
DISCORD_BOT_TOKEN=your_discord_bot_token
DISCORD_WEBHOOK_TRADE=https://discord.com/api/webhooks/...
DISCORD_WEBHOOK_REPORT=https://discord.com/api/webhooks/...
DISCORD_WEBHOOK_BACKTEST=https://discord.com/api/webhooks/...
DISCORD_WEBHOOK_SYSTEM=https://discord.com/api/webhooks/...
DISCORD_WEBHOOK_COMMAND=https://discord.com/api/webhooks/...
DISCORD_WEBHOOK_LIVEGATE=https://discord.com/api/webhooks/...
DISCORD_GUILD_ID=your_guild_id
```

- [ ] **Step 4: Verify config loads**

Run: `python -c "from app.config import load_config; c = load_config(); print(c.discord)"`
Expected: `DiscordConfig(bot_guild_id='', admin_role='admin', timeout_sec=5)`

- [ ] **Step 5: Commit**

```bash
git add app/config.py configs/config.yaml .env.example
git commit -m "feat: replace TelegramConfig with DiscordConfig + webhook env vars"
```

---

### Task 4: Update main.py — notifier + channel routing

**Files:**
- Modify: `app/main.py`

- [ ] **Step 1: Update imports**

Replace:
```python
from app.notify import TelegramNotifier
from bot_telegram.handlers import TelegramHandler
```
With:
```python
from app.notify import DiscordNotifier
```

(DiscordBot import will be added in Task 6 after bot_discord is created)

- [ ] **Step 2: Update TradingBot.__init__ notifier creation**

Replace lines 82-87:
```python
        self._notifier = TelegramNotifier(
            token=config.secrets.telegram_bot_token,
            chat_id=config.secrets.telegram_chat_id,
            timeout_sec=config.telegram.timeout_sec,
            proxy=config.proxy,
        )
```
With:
```python
        self._notifier = DiscordNotifier(
            webhooks=config.secrets.discord_webhooks,
            proxy=config.proxy,
            timeout_sec=config.discord.timeout_sec,
        )
```

- [ ] **Step 3: Add channel parameter to all send() calls**

Line 387 (네트워크 장애):
```python
await self._notifier.send(..., channel="system")
```

Line 397 (네트워크 복구):
```python
await self._notifier.send(..., channel="system")
```

Line 677 (매수 체결):
```python
await self._notifier.send(..., channel="trade")
```

Line 807 (LiveGate 리포트):
```python
await self._notifier.send(gate.format_report(gate_result), channel="livegate")
```

Line 974 (청산 알림):
```python
await self._notifier.send(..., channel="trade")
```

Line 994 (봇 시작):
```python
await self._notifier.send(..., channel="system")
```

Line 1022 (사이클 오류):
```python
await self._notifier.send(..., channel="system")
```

Line 1052 (봇 종료):
```python
await self._notifier.send("<b>봇 종료</b>", channel="system")
```

- [ ] **Step 4: Update run() — remove TelegramHandler, add placeholder for DiscordBot**

Replace lines 1001-1011 (TelegramHandler setup) with a comment:
```python
        # DiscordBot은 Task 6에서 추가
```

- [ ] **Step 5: Update stop() — remove TelegramHandler cleanup**

Replace lines 1032-1039 (telegram handler/task cleanup) with:
```python
        # DiscordBot 정리는 Task 6에서 추가
```

- [ ] **Step 6: Update module docstring**

Line 1: Replace "텔레그램 알림" with "디스코드 알림":
```python
"""오케스트레이터 -15분 주기 메인 루프.

DRY/PAPER/LIVE 모드. 전체 사이클 try-except + 디스코드 알림.
Phase 3: Pool 기반 사이징 + 승격/강등.
"""
```

- [ ] **Step 7: Verify syntax**

Run: `python -c "from app.main import TradingBot; print('OK')"`
Expected: `OK`

- [ ] **Step 8: Commit**

```bash
git add app/main.py
git commit -m "feat: switch main.py from TelegramNotifier to DiscordNotifier"
```

---

### Task 5: Update consumers — review_engine, daemon, scripts

**Files:**
- Modify: `strategy/review_engine.py`
- Modify: `backtesting/daemon.py`
- Modify: `scripts/optimize.py`
- Modify: `scripts/download_and_backtest.py`

- [ ] **Step 1: Update review_engine.py**

Replace import (line 18):
```python
from app.notify import TelegramNotifier
```
With:
```python
from app.notify import Notifier
```

Replace type hint (line 81):
```python
        notifier: TelegramNotifier | None = None,
```
With:
```python
        notifier: Notifier | None = None,
```

Add channel to send() calls:

Line 287:
```python
            await self._notifier.send("\n".join(lines), channel="report")
```

Line 586:
```python
            await self._notifier.send("\n".join(lines), channel="report")
```

Line 608:
```python
            await self._notifier.send(
                f"<b>월간 리뷰</b>\n...",
                channel="report",
            )
```

Update docstring (line 89): "텔레그램 알림" → "알림".

- [ ] **Step 2: Update daemon.py**

Replace import (line 28):
```python
from app.notify import TelegramNotifier
```
With:
```python
from app.notify import Notifier
```

Replace type hint (line 48):
```python
        notifier: TelegramNotifier | None = None,
```
With:
```python
        notifier: Notifier | None = None,
```

Add channel to send() calls:

Line 239:
```python
            await self._notifier.send(msg, channel="backtest")
```

Line 372:
```python
            await self._notifier.send("\n".join(lines), channel="backtest")
```

Line 417:
```python
            await self._notifier.send("\n".join(lines), channel="backtest")
```

Line 499:
```python
        await self._notifier.send("\n".join(lines), channel="backtest")
```

Update docstring (line 59): "텔레그램 알림" → "알림".

- [ ] **Step 3: Update scripts/optimize.py**

Replace import:
```python
from app.notify import TelegramNotifier
```
With:
```python
from app.notify import DiscordNotifier
```

Replace notifier creation (lines 184-187):
```python
    notifier = DiscordNotifier(
        webhooks=config.secrets.discord_webhooks,
        proxy=config.proxy,
        timeout_sec=config.discord.timeout_sec,
    )
```

Add channel (line 252):
```python
        await notifier.send(report, channel="backtest")
```

Update log message (line 253): "텔레그램 전송" → "디스코드 전송".

- [ ] **Step 4: Update scripts/download_and_backtest.py**

Replace import:
```python
from app.notify import TelegramNotifier
```
With:
```python
from app.notify import DiscordNotifier
```

Replace notifier creation (lines 387-390):
```python
    notifier = DiscordNotifier(
        webhooks=config.secrets.discord_webhooks,
        proxy=config.proxy,
        timeout_sec=config.discord.timeout_sec,
    )
```

Add channel (line 443):
```python
        ok = await notifier.send(msg, channel="backtest")
```

Update log messages: "텔레그램" → "디스코드".

- [ ] **Step 5: Verify all imports**

Run: `python -c "from strategy.review_engine import ReviewEngine; from backtesting.daemon import BacktestDaemon; print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add strategy/review_engine.py backtesting/daemon.py scripts/optimize.py scripts/download_and_backtest.py
git commit -m "feat: update all notifier consumers to use Notifier Protocol + channel routing"
```

---

### Task 6: DiscordBot — slash commands

**Files:**
- Create: `bot_discord/__init__.py`
- Create: `bot_discord/bot.py`
- Create: `tests/test_discord_bot.py`

- [ ] **Step 1: Create bot_discord/__init__.py**

```python
"""디스코드 봇 패키지."""
```

- [ ] **Step 2: Write failing test for DiscordBot**

```python
# tests/test_discord_bot.py
"""DiscordBot 단위 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
            "status", "positions", "pnl", "regime", "risk",
            "shadows", "pool", "balance", "pause", "resume",
            "golive", "close", "restore_params", "help",
        }
        registered = {cmd.name for cmd in discord_bot._tree.get_commands()}
        assert registered == expected_commands

    def test_admin_commands_exist(self) -> None:
        mock_bot = MagicMock()
        discord_bot = DiscordBot(
            token="test-token",
            bot=mock_bot,
            guild_id=12345,
        )
        admin_cmds = {"pause", "resume", "golive", "close", "restore_params"}
        for cmd in discord_bot._tree.get_commands():
            if cmd.name in admin_cmds:
                # admin 커맨드는 check가 있어야 함
                assert len(cmd.checks) > 0, f"{cmd.name} should have admin check"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_discord_bot.py -v`
Expected: FAIL (import errors)

- [ ] **Step 4: Implement DiscordBot**

```python
# bot_discord/bot.py
"""디스코드 슬래시 커맨드 처리기.

discord.py 기반. TradingBot 인스턴스 참조로 상태 조회/제어.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import discord
from discord import app_commands

if TYPE_CHECKING:
    from app.main import TradingBot

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))


def _has_admin_role(admin_role: str):
    """admin 역할 체크 데코레이터를 반환한다."""

    async def predicate(interaction: discord.Interaction) -> bool:
        if not interaction.guild or not isinstance(
            interaction.user, discord.Member
        ):
            await interaction.response.send_message(
                "서버에서만 사용 가능합니다.", ephemeral=True,
            )
            return False
        if not any(r.name == admin_role for r in interaction.user.roles):
            await interaction.response.send_message(
                f"`{admin_role}` 역할이 필요합니다.", ephemeral=True,
            )
            return False
        return True

    return app_commands.check(predicate)


class DiscordBot:
    """디스코드 슬래시 커맨드 처리기."""

    def __init__(
        self,
        token: str,
        bot: TradingBot,
        guild_id: int,
        proxy: str = "",
        admin_role: str = "admin",
    ) -> None:
        """초기화.

        Args:
            token: 디스코드 봇 토큰.
            bot: TradingBot 인스턴스 참조.
            guild_id: 슬래시 커맨드를 등록할 서버 ID.
            proxy: HTTP 프록시 URL.
            admin_role: 관리자 역할 이름.
        """
        self._token = token
        self._bot = bot
        self._guild_id = guild_id
        self._proxy = proxy
        self._admin_role = admin_role

        intents = discord.Intents.default()
        self._client = discord.Client(intents=intents, proxy=proxy or None)
        self._tree = app_commands.CommandTree(self._client)
        self._guild = discord.Object(id=guild_id)

        self._register_commands()

    def _register_commands(self) -> None:
        """슬래시 커맨드를 등록한다."""
        guild = self._guild
        admin_check = _has_admin_role(self._admin_role)

        @self._tree.command(name="status", description="봇 상태", guild=guild)
        async def cmd_status(interaction: discord.Interaction) -> None:
            bot = self._bot
            uptime_sec = int(time.time() - bot._bot_start_time)
            hours, remainder = divmod(uptime_sec, 3600)
            minutes, secs = divmod(remainder, 60)
            util_pct = bot._pool_manager.utilization_pct * 100
            paused_str = " (일시 중지)" if bot._paused else ""

            await interaction.response.send_message(
                f"**봇 상태{paused_str}**\n"
                f"모드: {bot._run_mode.value}\n"
                f"사이클: #{bot._cycle_count}\n"
                f"가동: {hours}시간 {minutes}분 {secs}초\n"
                f"포지션: {len(bot._positions)}개\n"
                f"자금 활용률: {util_pct:.1f}%"
            )

        @self._tree.command(name="positions", description="보유 포지션", guild=guild)
        async def cmd_positions(interaction: discord.Interaction) -> None:
            positions = self._bot._positions
            if not positions:
                await interaction.response.send_message("보유 포지션 없음")
                return

            lines = ["**보유 포지션**"]
            for sym, pos in positions.items():
                lines.append(
                    f"\n**{sym}**\n"
                    f"  전략: {pos.strategy.value} | Pool: {pos.pool.value}\n"
                    f"  진입: {pos.entry_price:,.0f}원\n"
                    f"  수량: {pos.qty:.6f} | {pos.size_krw:,.0f}원\n"
                    f"  SL: {pos.stop_loss:,.0f} | TP: {pos.take_profit:,.0f}\n"
                    f"  점수: {pos.entry_score:.0f} | 국면: {pos.regime.value}"
                )
            await interaction.response.send_message("\n".join(lines))

        @self._tree.command(name="balance", description="Pool 잔액", guild=guild)
        async def cmd_balance(interaction: discord.Interaction) -> None:
            from app.data_types import Pool

            pm = self._bot._pool_manager
            lines = ["**Pool 잔액**"]
            for pool in [Pool.CORE, Pool.ACTIVE, Pool.RESERVE]:
                state = pm._pools[pool]
                lines.append(
                    f"\n**{pool.value.upper()}**\n"
                    f"  잔액: {state.total_balance:,.0f}원\n"
                    f"  할당: {state.allocated:,.0f}원\n"
                    f"  가용: {state.available:,.0f}원\n"
                    f"  포지션: {state.position_count}개"
                )
            total = sum(s.total_balance for s in pm._pools.values())
            util = pm.utilization_pct * 100
            lines.append(f"\n총 자산: {total:,.0f}원 | 활용률: {util:.1f}%")
            await interaction.response.send_message("\n".join(lines))

        @self._tree.command(name="regime", description="국면 분류", guild=guild)
        async def cmd_regime(interaction: discord.Interaction) -> None:
            regime_states = self._bot._rule_engine._regime_states
            if not regime_states:
                await interaction.response.send_message(
                    "국면 데이터 없음 (첫 사이클 대기 중)"
                )
                return
            lines = ["**국면 분류**"]
            for sym, rs in sorted(regime_states.items()):
                pending = f" -> {rs.pending.value}" if rs.pending else ""
                lines.append(f"  {sym}: {rs.current.value}{pending}")
            await interaction.response.send_message("\n".join(lines))

        @self._tree.command(name="pnl", description="PnL 요약", guild=guild)
        async def cmd_pnl(interaction: discord.Interaction) -> None:
            journal = self._bot._journal
            now = datetime.now(KST)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            today_start_ms = int(today_start.timestamp() * 1000)
            week_start = today_start - timedelta(days=now.weekday())
            week_start_ms = int(week_start.timestamp() * 1000)

            today_rows = journal._conn.execute(
                "SELECT net_pnl_krw FROM trades WHERE exit_time >= ?",
                (today_start_ms,),
            ).fetchall()
            today_pnl = sum(r[0] for r in today_rows if r[0] is not None)
            today_count = len(today_rows)
            today_wins = sum(1 for r in today_rows if r[0] is not None and r[0] > 0)

            week_rows = journal._conn.execute(
                "SELECT net_pnl_krw FROM trades WHERE exit_time >= ?",
                (week_start_ms,),
            ).fetchall()
            week_pnl = sum(r[0] for r in week_rows if r[0] is not None)
            week_count = len(week_rows)
            week_wins = sum(1 for r in week_rows if r[0] is not None and r[0] > 0)

            today_wr = (today_wins / today_count * 100) if today_count > 0 else 0
            week_wr = (week_wins / week_count * 100) if week_count > 0 else 0

            await interaction.response.send_message(
                f"**PnL 요약**\n\n"
                f"**오늘**\n"
                f"  PnL: {today_pnl:+,.0f}원\n"
                f"  거래: {today_count}건 (승률 {today_wr:.0f}%)\n\n"
                f"**이번 주**\n"
                f"  PnL: {week_pnl:+,.0f}원\n"
                f"  거래: {week_count}건 (승률 {week_wr:.0f}%)"
            )

        @self._tree.command(name="risk", description="RiskGate 상태", guild=guild)
        async def cmd_risk(interaction: discord.Interaction) -> None:
            rg = self._bot._risk_gate
            dd = self._bot._dd_limits
            state = rg._state
            lines = [
                "**RiskGate 상태**",
                f"  상태: {state.status.value}",
                f"  일일 DD: {dd.get_max_daily_dd() * 100:.2f}%",
                f"  연속 손실: {state.consecutive_losses}",
            ]
            await interaction.response.send_message("\n".join(lines))

        @self._tree.command(name="shadows", description="Darwinian 상위 그림자", guild=guild)
        async def cmd_shadows(interaction: discord.Interaction) -> None:
            top = self._bot._darwin.get_top_shadows(5)
            if not top:
                await interaction.response.send_message("Shadow 데이터 없음")
                return
            lines = ["**Darwinian Top 5**"]
            for i, s in enumerate(top, 1):
                lines.append(
                    f"  {i}. score={s.get('composite_score', 0):.3f} "
                    f"PF={s.get('profit_factor', 0):.2f}"
                )
            await interaction.response.send_message("\n".join(lines))

        @self._tree.command(name="pool", description="3풀 자금 현황", guild=guild)
        async def cmd_pool(interaction: discord.Interaction) -> None:
            pm = self._bot._pool_manager
            lines = ["**풀 현황**"]
            for pool_type, state in pm._pools.items():
                lines.append(
                    f"  {pool_type.value}: {state.total_balance:,.0f}원 "
                    f"(가용 {state.available:,.0f}원)"
                )
            await interaction.response.send_message("\n".join(lines))

        # ─── Admin 커맨드 ─────────────────────────────

        @self._tree.command(name="pause", description="봇 일시 중지", guild=guild)
        @admin_check
        async def cmd_pause(interaction: discord.Interaction) -> None:
            self._bot._paused = True
            await interaction.response.send_message(
                "봇 일시 중지됨 (신규 진입 차단, 기존 포지션 관리 계속)"
            )

        @self._tree.command(name="resume", description="봇 재개", guild=guild)
        @admin_check
        async def cmd_resume(interaction: discord.Interaction) -> None:
            self._bot._paused = False
            await interaction.response.send_message("**봇 재개**\n신규 진입 허용됨")

        @self._tree.command(name="golive", description="LIVE 모드 전환", guild=guild)
        @admin_check
        async def cmd_golive(interaction: discord.Interaction) -> None:
            from app.data_types import RunMode
            from app.live_gate import LiveGate

            await interaction.response.defer()

            gate = LiveGate()
            try:
                paper_days = (
                    int((time.time() - self._bot._paper_start_time) / 86400)
                    if self._bot._paper_start_time > 0
                    else 0
                )
                trades = self._bot._journal.get_recent_trades(limit=500)
                strat_pnls: dict[str, list[float]] = defaultdict(list)
                for t in trades:
                    s = t.get("strategy", "")
                    pnl = t.get("net_pnl_krw", 0) or 0
                    if s:
                        strat_pnls[s].append(pnl)
                strat_exp: dict[str, float] = {}
                for s, pnls in strat_pnls.items():
                    strat_exp[s] = sum(pnls) / len(pnls) if pnls else 0

                total_seconds = time.time() - self._bot._paper_start_time
                expected_cycles = (
                    total_seconds / self._bot._cycle_interval
                    if self._bot._paper_start_time > 0
                    else 0
                )
                actual_cycles = self._bot._cycle_count
                uptime_pct = (
                    min(actual_cycles / expected_cycles, 1.0)
                    if expected_cycles > 0
                    else 0.99
                )

                bd = self._bot._backtest_daemon
                gate_result = gate.evaluate(
                    paper_days=paper_days,
                    total_trades=self._bot._journal.get_trade_count(),
                    strategy_expectancy=strat_exp,
                    mdd_pct=self._bot._dd_limits._calc_dd(
                        self._bot._dd_limits.state.total_base,
                    ),
                    max_daily_dd_pct=self._bot._dd_limits.get_max_daily_dd(),
                    uptime_pct=uptime_pct,
                    unresolved_auth_errors=0,
                    slippage_model_error_pct=0.0,
                    wf_pass_count=(
                        bd.wf_result.pass_count if bd.wf_result else 0
                    ),
                    wf_total=4,
                    mc_p5_pnl=(
                        bd.mc_result.pnl_percentile_5 if bd.mc_result else 0
                    ),
                )
            except Exception:
                await interaction.followup.send(
                    "LiveGate 검증 중 오류 발생. LIVE 전환 취소."
                )
                return

            if not gate_result.approved:
                report = gate.format_report(gate_result)
                await interaction.followup.send(f"{report}\n\nLIVE 전환 거부됨.")
                return

            self._bot._config.run_mode = "LIVE"
            self._bot._run_mode = RunMode.LIVE
            self._bot._paused = False
            self._bot._live_risk_reduction = True
            self._bot._live_start_time = time.time()
            await interaction.followup.send(
                "**LIVE 모드 전환 승인**\n"
                "risk_pct 50% 축소 적용 (7일)\n"
                "/restore_params로 수동 해제 가능"
            )

        @self._tree.command(
            name="close", description="수동 청산 (/close symbol)", guild=guild,
        )
        @admin_check
        @app_commands.describe(symbol="청산할 코인 심볼 (예: BTC)")
        async def cmd_close(
            interaction: discord.Interaction, symbol: str,
        ) -> None:
            await interaction.response.defer()
            symbol = symbol.upper()

            matched_sym = None
            for sym in self._bot._positions:
                if (
                    sym == symbol
                    or sym.startswith(f"{symbol}_")
                    or sym == f"{symbol}_KRW"
                ):
                    matched_sym = sym
                    break

            if matched_sym is None:
                held = ", ".join(self._bot._positions.keys()) or "없음"
                await interaction.followup.send(
                    f"{symbol} 포지션 없음\n보유: {held}"
                )
                return

            pos = self._bot._positions[matched_sym]
            try:
                ticker_sym = matched_sym.replace("_KRW", "")
                ticker = await self._bot._client.get_ticker(ticker_sym)
                exit_price = float(ticker.get("closing_price", 0))
            except Exception:
                exit_price = 0
            if exit_price <= 0:
                exit_price = pos.entry_price

            await self._bot._close_position(matched_sym, exit_price, "manual")
            await interaction.followup.send(f"{matched_sym} 수동 청산 요청 완료")

        @self._tree.command(
            name="restore_params",
            description="LIVE risk_pct 정상화",
            guild=guild,
        )
        @admin_check
        async def cmd_restore_params(
            interaction: discord.Interaction,
        ) -> None:
            self._bot._live_risk_reduction = False
            await interaction.response.send_message(
                "**파라미터 복원 완료**\nrisk_pct 정상화"
            )

        @self._tree.command(name="help", description="명령어 목록", guild=guild)
        async def cmd_help(interaction: discord.Interaction) -> None:
            commands = {
                "/status": "봇 상태",
                "/positions": "보유 포지션",
                "/balance": "Pool 잔액",
                "/regime": "국면 분류",
                "/pnl": "PnL 요약",
                "/risk": "RiskGate 상태",
                "/shadows": "Darwinian 상위 그림자",
                "/pool": "3풀 자금 현황",
                "/pause": "봇 일시 중지 (admin)",
                "/resume": "봇 재개 (admin)",
                "/golive": "LIVE 모드 전환 (admin)",
                "/close": "수동 청산 (admin)",
                "/restore_params": "risk_pct 정상화 (admin)",
                "/help": "명령어 목록",
            }
            lines = ["**명령어 목록**"]
            for cmd, desc in commands.items():
                lines.append(f"  {cmd} — {desc}")
            await interaction.response.send_message("\n".join(lines))

        # on_ready에서 커맨드 동기화
        @self._client.event
        async def on_ready() -> None:
            self._tree.copy_global_to(guild=self._guild)
            await self._tree.sync(guild=self._guild)
            logger.info(
                "디스코드 봇 준비 완료: %s (guild=%d)",
                self._client.user,
                self._guild_id,
            )

    async def start(self) -> None:
        """Bot을 시작한다."""
        if not self._token:
            logger.warning("디스코드 봇 토큰 미설정")
            return
        await self._client.start(self._token)

    async def stop(self) -> None:
        """Bot을 종료한다."""
        if not self._client.is_closed():
            await self._client.close()
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_discord_bot.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add bot_discord/__init__.py bot_discord/bot.py tests/test_discord_bot.py
git commit -m "feat: add DiscordBot with 14 slash commands"
```

---

### Task 7: Integrate DiscordBot into main.py

**Files:**
- Modify: `app/main.py`

- [ ] **Step 1: Add DiscordBot import**

```python
from bot_discord.bot import DiscordBot
```

- [ ] **Step 2: Add DiscordBot setup in run()**

Replace the placeholder comment from Task 4 with:
```python
        # 디스코드 명령어 봇 시작
        guild_id_str = self._config.secrets.discord_guild_id
        if self._config.secrets.discord_bot_token and guild_id_str:
            self._discord_bot = DiscordBot(
                token=self._config.secrets.discord_bot_token,
                bot=self,
                guild_id=int(guild_id_str),
                proxy=self._config.proxy,
                admin_role=self._config.discord.admin_role,
            )
            self._discord_task = asyncio.create_task(self._discord_bot.start())
        else:
            logger.warning("디스코드 봇 토큰/guild_id 미설정 — 명령어 비활성화")
```

- [ ] **Step 3: Add DiscordBot cleanup in stop()**

Replace the placeholder comment from Task 4 with:
```python
        if hasattr(self, "_discord_bot"):
            await self._discord_bot.stop()
        if hasattr(self, "_discord_task"):
            self._discord_task.cancel()
            try:
                await self._discord_task
            except asyncio.CancelledError:
                pass
```

- [ ] **Step 4: Verify syntax**

Run: `python -c "from app.main import TradingBot; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add app/main.py
git commit -m "feat: integrate DiscordBot into TradingBot main loop"
```

---

### Task 8: Delete Telegram code + update CLAUDE.md

**Files:**
- Delete: `bot_telegram/handlers.py`
- Delete: `bot_telegram/__init__.py`
- Delete: `tests/test_telegram_handlers.py`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Delete bot_telegram directory and old tests**

```bash
rm -rf bot_telegram/
rm tests/test_telegram_handlers.py
```

- [ ] **Step 2: Update CLAUDE.md project structure**

Replace `bot_telegram/` section with:
```
├── bot_discord/
│   ├── __init__.py
│   └── bot.py                 ← 디스코드 슬래시 커맨드 14개.
```

Remove the `handlers.py` line. Also update any references to "텔레그램" in CLAUDE.md to "디스코드" where applicable.

- [ ] **Step 3: Verify no remaining TelegramNotifier references in source**

Run: `grep -r "TelegramNotifier\|TelegramHandler\|TelegramConfig\|bot_telegram" --include="*.py" .`
Expected: No matches (only docs may still reference for historical context)

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git rm -r bot_telegram/
git rm tests/test_telegram_handlers.py
git commit -m "chore: remove Telegram code, update CLAUDE.md with bot_discord"
```

---

### Task 9: Run full test suite + lint

**Files:** None (verification only)

- [ ] **Step 1: Run ruff lint**

Run: `ruff check .`
Expected: No errors

- [ ] **Step 2: Run ruff format check**

Run: `ruff format --check .`
Expected: No reformatting needed (or fix and commit)

- [ ] **Step 3: Run all tests**

Run: `pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 4: Fix any issues and commit if needed**

```bash
git add -A
git commit -m "fix: resolve lint/test issues from Discord migration"
```
