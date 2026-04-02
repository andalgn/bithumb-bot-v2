"""CoinUniverse — 빗썸 거래량 기준 동적 코인 유니버스 관리.

daily refresh로 상위 top_n 코인을 선정하고 base_coins(안전망)와 합집합으로 최종 목록 결정.
스테이블코인 및 원화(KRW) 자동 제외.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from market.bithumb_api import BithumbClient

logger = logging.getLogger(__name__)

_EXCLUDE: frozenset[str] = frozenset(
    {
        "USDT",
        "USDC",
        "BUSD",
        "DAI",
        "TUSD",
        "USDP",
        "GUSD",
        "KRW",
        "KRWC",
    }
)


class CoinUniverse:
    """빗썸 거래량 기준 동적 코인 유니버스 관리자."""

    def __init__(
        self,
        client: BithumbClient,
        top_n: int = 20,
        base_coins: list[str] | None = None,
    ) -> None:
        """초기화.

        Args:
            client: 빗썸 API 클라이언트.
            top_n: 거래량 기준 상위 선정 수.
            base_coins: 항상 포함할 안전망 코인 목록.
        """
        self._client = client
        self._top_n = top_n
        self._base_coins: list[str] = list(base_coins or [])
        self._current: list[str] = list(base_coins or [])

    @property
    def coins(self) -> list[str]:
        """현재 코인 목록을 반환한다."""
        return list(self._current)

    async def refresh(self) -> list[str]:
        """빗썸 API에서 전체 티커를 조회해 코인 목록을 갱신한다.

        Returns:
            갱신된 코인 목록.
        """
        all_tickers = await self._client.get_all_tickers()
        if not all_tickers:
            logger.warning("get_all_tickers 빈 응답 — base_coins 유지")
            self._current = list(self._base_coins)
            return list(self._base_coins)

        volumes: list[tuple[str, float]] = []
        for sym, info in all_tickers.items():
            if sym in _EXCLUDE:
                continue
            try:
                vol = float(info.get("acc_trade_value_24H", 0))
            except (TypeError, ValueError):
                vol = 0.0
            volumes.append((sym, vol))

        volumes.sort(key=lambda x: x[1], reverse=True)
        top_coins = [sym for sym, _ in volumes[: self._top_n]]

        seen: set[str] = set(top_coins)
        extra = [c for c in self._base_coins if c not in seen]
        result = top_coins + extra

        self._current = result
        logger.info(
            "코인 유니버스 갱신: %d개 (top%d + base%d)",
            len(result),
            len(top_coins),
            len(extra),
        )
        return result
