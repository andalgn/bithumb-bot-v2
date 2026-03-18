"""진입점 — 환경 셋업 확인 및 연결 테스트.

1. config.yaml + .env 로딩
2. 빗썸 Public API: BTC/KRW 현재가 조회
3. 텔레그램 테스트 메시지 전송
4. "DRY 모드 준비 완료" 로그
"""

from __future__ import annotations

import asyncio
import logging
import time

import aiohttp

from app.config import load_config
from app.notify import TelegramNotifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def test_bithumb_api(base_url: str) -> dict | None:
    """빗썸 Public API로 BTC/KRW 현재가를 조회한다.

    Args:
        base_url: 빗썸 API 베이스 URL.

    Returns:
        응답 데이터 dict 또는 None.
    """
    url = f"{base_url}/public/ticker/BTC_KRW"
    timeout = aiohttp.ClientTimeout(total=10)

    start = time.monotonic()
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                elapsed_ms = (time.monotonic() - start) * 1000
                data = await resp.json(content_type=None)

                if data.get("status") == "0000":
                    price = data["data"]["closing_price"]
                    logger.info(
                        "빗썸 API 연결 성공 — BTC/KRW: %s원 (응답 %.0fms)",
                        price,
                        elapsed_ms,
                    )
                    return data["data"]
                else:
                    logger.error("빗썸 API 오류: %s", data.get("message", "unknown"))
                    return None
    except Exception:
        logger.exception("빗썸 API 연결 실패")
        return None


async def main() -> None:
    """메인 연결 테스트."""
    logger.info("=" * 50)
    logger.info("Bithumb Auto Trading Bot v2 — 환경 셋업 확인")
    logger.info("=" * 50)

    # 1. 설정 로딩
    config = load_config()
    logger.info("설정 로딩 완료 — 모드: %s, 대상 코인: %d개", config.run_mode, len(config.coins))

    # 2. 빗썸 Public API 테스트
    base_url = config.secrets.bithumb_api_url or config.bithumb.base_url
    ticker_data = await test_bithumb_api(base_url)
    if ticker_data is None:
        logger.warning("빗썸 API 테스트 실패 — VPN 연결 상태를 확인하세요")

    # 3. 텔레그램 테스트
    notifier = TelegramNotifier(
        token=config.secrets.telegram_bot_token,
        chat_id=config.secrets.telegram_chat_id,
        timeout_sec=config.telegram.timeout_sec,
    )
    price_str = ticker_data["closing_price"] if ticker_data else "N/A"
    msg = (
        f"<b>🤖 Bithumb Bot v2 — 환경 셋업 완료</b>\n"
        f"모드: {config.run_mode}\n"
        f"BTC/KRW: {price_str}원\n"
        f"대상 코인: {len(config.coins)}개"
    )
    sent = await notifier.send(msg)
    if not sent:
        logger.warning("텔레그램 메시지 전송 실패 — 토큰/chat_id를 확인하세요")

    # 4. 완료
    logger.info("%s 모드 준비 완료", config.run_mode)
    logger.info("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
