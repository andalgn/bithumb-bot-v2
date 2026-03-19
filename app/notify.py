"""텔레그램 알림 모듈.

aiohttp 기반 비동기 전송. 실패 시 로그만 남기고 봇을 중단하지 않는다.
VPN 환경의 SSL 인증서 문제 대응 포함.
"""

from __future__ import annotations

import logging
import ssl

import aiohttp

logger = logging.getLogger(__name__)


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
            connector = aiohttp.TCPConnector(ssl=self._ssl_ctx)
            async with aiohttp.ClientSession(
                timeout=self._timeout, connector=connector
            ) as session:
                async with session.post(self._url, json=payload) as resp:
                    if resp.status == 200:
                        logger.info("텔레그램 메시지 전송 성공")
                        return True
                    body = await resp.text()
                    logger.warning(
                        "텔레그램 전송 실패: status=%d body=%s", resp.status, body
                    )
                    return False
        except Exception:
            logger.exception("텔레그램 전송 중 예외 발생")
            return False
