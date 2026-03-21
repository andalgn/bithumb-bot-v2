"""텔레그램 알림 모듈.

aiohttp 기반 비동기 전송. 실패 시 로그만 남기고 봇을 중단하지 않는다.
VPN 환경의 SSL 인증서 문제 대응 포함.
"""

from __future__ import annotations

import logging
import ssl

import aiohttp

logger = logging.getLogger(__name__)

_HTML_ESCAPE = str.maketrans({"&": "&amp;", "<": "&lt;", ">": "&gt;"})


def _make_ssl_context() -> ssl.SSLContext:
    """VPN 환경에서 자체서명 인증서를 허용하는 SSL 컨텍스트를 생성한다."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


class TelegramNotifier:
    """텔레그램 메시지 전송기."""

    BASE_URL = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(self, token: str, chat_id: str, timeout_sec: int = 5) -> None:
        """초기화.

        Args:
            token: 텔레그램 봇 토큰.
            chat_id: 메시지를 보낼 채팅 ID.
            timeout_sec: 요청 타임아웃(초).
        """
        self._token = token
        self._chat_id = chat_id
        self._timeout = aiohttp.ClientTimeout(total=timeout_sec)
        self._url = self.BASE_URL.format(token=token)
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

    async def send(self, text: str, parse_mode: str = "HTML") -> bool:
        """메시지를 전송한다.

        Args:
            text: 전송할 메시지 텍스트.
            parse_mode: 파싱 모드 (HTML 또는 Markdown).

        Returns:
            전송 성공 여부.
        """
        if not self._token or not self._chat_id:
            logger.warning("텔레그램 토큰 또는 chat_id가 설정되지 않음")
            return False

        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }

        try:
            session = await self._get_session()
            async with session.post(self._url, json=payload) as resp:
                if resp.status == 200:
                    logger.info("텔레그램 메시지 전송 성공")
                    self._consecutive_failures = 0
                    return True
                body = await resp.text()
                logger.warning(
                    "텔레그램 전송 실패: status=%d body=%s", resp.status, body,
                )
                return False
        except Exception:
            logger.exception("텔레그램 전송 중 예외 발생")
            self._consecutive_failures += 1
            if self._consecutive_failures >= 3:
                # 3회 연속 실패 후에만 세션 재생성 (세션 폭풍 방지)
                self._session = None
                self._consecutive_failures = 0
            return False

    @staticmethod
    def escape(text: str) -> str:
        """HTML 특수문자를 이스케이프한다."""
        return text.translate(_HTML_ESCAPE)

    async def close(self) -> None:
        """세션을 닫는다."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
