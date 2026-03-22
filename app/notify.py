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

_DISCORD_ESCAPE = str.maketrans({"*": "\\*", "_": "\\_", "~": "\\~", "`": "\\`", "|": "\\|"})

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
    text = _STRIP_TAGS.sub("", text)
    for entity, char in _HTML_ENTITIES.items():
        text = text.replace(entity, char)
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
            webhooks: 채널명 -> Webhook URL 매핑.
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
                timeout=self._timeout,
                connector=connector,
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
            channel: 대상 채널 키.

        Returns:
            전송 성공 여부.
        """
        url = self._webhooks.get(channel, "")
        if not url:
            logger.warning("디스코드 webhook URL 미설정: channel=%s", channel)
            return False

        text = _html_to_discord(text)

        chunks = self._split_message(text)
        all_ok = True
        for chunk in chunks:
            ok = await self._post_webhook(url, chunk)
            if not ok:
                all_ok = False
        return all_ok

    async def _handle_failure(self) -> None:
        """연속 실패 카운터를 증가시키고, 3회 이상이면 세션을 재생성한다."""
        self._consecutive_failures += 1
        if self._consecutive_failures >= 3:
            if self._session:
                try:
                    await self._session.close()
                except Exception:
                    pass
            self._session = None
            self._consecutive_failures = 0

    async def _post_webhook(self, url: str, content: str) -> bool:
        """Webhook URL로 메시지를 POST한다."""
        payload = {"content": content}
        try:
            session = await self._get_session()
            async with session.post(
                url,
                json=payload,
                proxy=self._proxy or None,
            ) as resp:
                if resp.status in (200, 204):
                    logger.debug("디스코드 메시지 전송 성공")
                    self._consecutive_failures = 0
                    return True
                if resp.status == 429:
                    retry_after = float(resp.headers.get("Retry-After", "1"))
                    try:
                        data = await resp.json()
                        retry_after = data.get("retry_after", retry_after)
                    except Exception:
                        pass
                    logger.warning(
                        "디스코드 rate limit, %.1f초 대기",
                        retry_after,
                    )
                    await asyncio.sleep(retry_after)
                    async with session.post(
                        url,
                        json=payload,
                        proxy=self._proxy or None,
                    ) as retry_resp:
                        if retry_resp.status in (200, 204):
                            self._consecutive_failures = 0
                            return True
                        retry_body = await retry_resp.text()
                        logger.warning(
                            "디스코드 rate limit 재시도 실패: status=%d body=%s",
                            retry_resp.status,
                            retry_body,
                        )
                    await self._handle_failure()
                    return False
                body = await resp.text()
                logger.warning(
                    "디스코드 전송 실패: status=%d body=%s",
                    resp.status,
                    body,
                )
                await self._handle_failure()
                return False
        except Exception:
            logger.exception("디스코드 전송 중 예외 발생")
            await self._handle_failure()
        return False

    async def close(self) -> None:
        """세션을 닫는다."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
