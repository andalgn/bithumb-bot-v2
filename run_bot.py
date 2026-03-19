"""진입점 — 봇 실행 및 Windows 서비스 준비.

nssm 또는 pm2로 Windows 서비스 등록 가능한 구조.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys

from app.config import load_config
from app.main import TradingBot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("data/bot.log", encoding="utf-8"),
    ],
)
# 전략 엔진 디버그 로그 활성화 (국면/점수 상세)
logging.getLogger("strategy.rule_engine").setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)


async def run_bot(once: bool = False) -> None:
    """봇을 실행한다.

    Args:
        once: True이면 사이클 1회 실행 후 종료.
    """
    config = load_config()
    bot = TradingBot(config)

    # 종료 신호 핸들러
    loop = asyncio.get_event_loop()
    stop_event = asyncio.Event()

    def _shutdown(*_: object) -> None:
        logger.info("종료 신호 수신")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except NotImplementedError:
            # Windows에서는 signal handler 미지원
            signal.signal(sig, _shutdown)

    if once:
        await bot.run_once()
        return

    # 메인 루프
    bot_task = asyncio.create_task(bot.run())

    try:
        await stop_event.wait()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        await bot.stop()
        bot_task.cancel()
        try:
            await bot_task
        except asyncio.CancelledError:
            pass


def main() -> None:
    """CLI 진입점."""
    parser = argparse.ArgumentParser(description="Bithumb Auto Trading Bot v2")
    parser.add_argument(
        "--once", action="store_true",
        help="사이클 1회 실행 후 종료",
    )
    parser.add_argument(
        "--mode", choices=["DRY", "PAPER", "LIVE"],
        help="운영 모드 오버라이드",
    )
    args = parser.parse_args()

    # data 디렉토리 생성
    from pathlib import Path
    Path("data").mkdir(exist_ok=True)

    logger.info("Bithumb Auto Trading Bot v2 시작")
    asyncio.run(run_bot(once=args.once))


if __name__ == "__main__":
    main()
