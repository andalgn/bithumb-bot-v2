"""CoinUniverse — 빗썸 거래량 기준 동적 코인 유니버스 관리 + Phase 1 Hard Cutoffs.

Phase 1 Hard Cutoffs (극저가 코인 제외):
1. VOLUME FILTER: 7일 이동평균 거래량 > 100M KRW (1시간 캔들 기반)
2. SPREAD FILTER: bid/ask 스프레드 < 0.5%
3. TICK-PRICE FILTER: tick_size / price < 1% (극저가 코인 제외) ← CRITICAL
4. EXCLUDE LIST: 스테이블코인, KRW 등

daily refresh로 상위 top_n 코인을 선정하고 hard cutoff로 필터링한 후,
base_coins(안전망)와 합집합으로 최종 목록 결정.

예상 결과:
- Before: 20개 (10 KRW 코인 다수 포함, 스프레드 1% 이상)
- After: 12-15개 (모두 1% 이상의 최소호가 비율, 스프레드 < 0.5%)
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

# Bithumb tick size table (가격대별 최소 호가 단위)
# Reference: https://docs.bithumb.com/docs/price-precision
_TICK_SIZE_TABLE: dict[tuple[float, float], float] = {
    (0, 100): 1.0,  # 1-100 KRW: 1 KRW 단위
    (100, 1_000): 10.0,  # 100-1,000 KRW: 10 KRW 단위
    (1_000, 10_000): 100.0,  # 1,000-10,000 KRW: 100 KRW 단위
    (10_000, 100_000): 1_000.0,  # 10,000-100,000 KRW: 1,000 KRW 단위
    (100_000, float("inf")): 10_000.0,  # 100,000+ KRW: 10,000 KRW 단위
}


def _get_tick_size(price: float) -> float:
    """가격대별 최소 호가 단위를 반환한다.

    Args:
        price: 현재가 (KRW).

    Returns:
        최소 호가 단위 (KRW).
    """
    for (min_price, max_price), tick in _TICK_SIZE_TABLE.items():
        if min_price <= price < max_price:
            return tick
    return 10_000.0  # Fallback


class CoinUniverse:
    """빗썸 거래량 기준 동적 코인 유니버스 관리자 (Phase 1 Hard Cutoffs 포함)."""

    # Phase 1 Hard Cutoff 임계값
    MIN_7D_ROLLING_VOLUME_KRW = 100_000_000  # 100M KRW
    MAX_SPREAD_RATIO = 0.005  # 0.5%
    MAX_TICK_PRICE_RATIO = 0.01  # 1%

    def __init__(
        self,
        client: BithumbClient,
        top_n: int = 20,
        base_coins: list[str] | None = None,
    ) -> None:
        """초기화.

        Args:
            client: 빗썸 API 클라이언트.
            top_n: 거래량 기준 상위 선정 수 (필터 전).
            base_coins: 항상 포함할 안전망 코인 목록.
        """
        self._client = client
        self._top_n = top_n
        self._base_coins: list[str] = list(base_coins or [])
        self._current: list[str] = list(base_coins or [])
        self._filtered_out: dict[str, str] = {}  # 필터링된 코인 + 사유

    @property
    def coins(self) -> list[str]:
        """현재 코인 목록을 반환한다."""
        return list(self._current)

    @property
    def filtered_out(self) -> dict[str, str]:
        """필터링된 코인 목록 + 사유를 반환한다.

        Returns:
            {코인: 필터링 사유} 딕셔너리.
        """
        return dict(self._filtered_out)

    async def _compute_7d_rolling_volume(self, coin: str) -> float:
        """7일 이동평균 거래량을 계산한다 (1시간 캔들 기반).

        Args:
            coin: 코인 심볼.

        Returns:
            7일 이동평균 거래량 (KRW). 실패 시 0.0.
        """
        try:
            # get_candlestick returns list[list]: [timestamp, open, close, high, low, volume]
            candles = await self._client.get_candlestick(coin, "1h")
            if not candles:
                return 0.0
            # 최근 168시간 (7일)만 사용
            recent_candles = candles[-168:] if len(candles) >= 168 else candles
            # 거래량 KRW = close * volume (모든 1시간 캔들 합산)
            vol_krw = sum(
                float(c[2]) * float(c[5])  # c[2]=close, c[5]=volume
                for c in recent_candles
                if len(c) >= 6
            )
            return vol_krw
        except Exception as e:
            logger.debug("7d rolling volume 계산 실패 (%s): %s", coin, e)
            return 0.0

    def _passes_hard_cutoffs(
        self, coin: str, ticker: dict, rolling_vol: float
    ) -> tuple[bool, str | None]:
        """Hard cutoff을 통과하는지 검사한다.

        Args:
            coin: 코인 심볼.
            ticker: 빗썸 ticker 딕셔너리.
            rolling_vol: 7일 이동평균 거래량 (KRW).

        Returns:
            (통과 여부, 실패 사유). 통과 시 (True, None).
        """
        # 1. SPREAD FILTER
        try:
            bid = float(ticker.get("bid", 0))
            ask = float(ticker.get("ask", 0))
            if bid > 0 and ask > 0:
                spread_ratio = 1 - (bid / ask)
                if spread_ratio > self.MAX_SPREAD_RATIO:
                    return False, f"spread {spread_ratio:.4f} > {self.MAX_SPREAD_RATIO}"
        except (TypeError, ValueError):
            return False, "invalid bid/ask"

        # 2. TICK-PRICE FILTER (극저가 코인 제외) ← CRITICAL
        try:
            price = float(ticker.get("last", 0))
            if price <= 0:
                return False, "price <= 0"
            tick = _get_tick_size(price)
            tick_ratio = tick / price
            if tick_ratio > self.MAX_TICK_PRICE_RATIO:
                return False, f"tick_ratio {tick_ratio:.4f} > {self.MAX_TICK_PRICE_RATIO}"
        except (TypeError, ValueError):
            return False, "invalid price"

        # 3. VOLUME FILTER (7일 이동평균)
        if rolling_vol < self.MIN_7D_ROLLING_VOLUME_KRW:
            return False, f"vol_7d {rolling_vol:.0f} < {self.MIN_7D_ROLLING_VOLUME_KRW}"

        # All cutoffs passed
        return True, None

    async def refresh(self) -> list[str]:
        """빗썸 API에서 전체 티커를 조회해 코인 목록을 갱신한다 (hard cutoff 적용).

        Returns:
            갱신된 코인 목록.
        """
        all_tickers = await self._client.get_all_tickers()
        if not all_tickers:
            logger.warning("get_all_tickers 빈 응답 — base_coins 유지")
            self._current = list(self._base_coins)
            self._filtered_out = {}
            return list(self._base_coins)

        # Step 1: 거래량 기준 상위 top_n 선정 (24h 기준, 필터 전)
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
        candidates = [sym for sym, _ in volumes[: self._top_n]]

        logger.info("코인 유니버스 상위 %d개 후보: %s", len(candidates), candidates)

        # Step 2: Hard cutoff 적용
        self._filtered_out = {}
        passed_coins: list[tuple[str, float]] = []

        for coin in candidates:
            ticker = all_tickers.get(coin, {})

            # 7일 이동평균 거래량 계산 (비동기)
            rolling_vol = await self._compute_7d_rolling_volume(coin)

            # Hard cutoff 검사
            passes, reason = self._passes_hard_cutoffs(coin, ticker, rolling_vol)
            if not passes:
                self._filtered_out[coin] = reason or "unknown"
                logger.debug("코인 제외 (%s): %s", coin, reason)
            else:
                vol_7d = float(ticker.get("acc_trade_value_24H", 0))
                passed_coins.append((coin, vol_7d))

        # Step 3: base_coins 안전망 추가
        passed_set = {c for c, _ in passed_coins}
        base_not_in_passed = [c for c in self._base_coins if c not in passed_set]

        result = [c for c, _ in passed_coins] + base_not_in_passed

        self._current = result
        logger.info(
            "코인 유니버스 갱신: %d개 최종 (top%d 중 %d 통과, base %d, 제외 %d개)",
            len(result),
            len(candidates),
            len(passed_coins),
            len(base_not_in_passed),
            len(self._filtered_out),
        )

        # 제외된 코인 로그
        if self._filtered_out:
            excluded_str = ", ".join(
                f"{coin}({reason})" for coin, reason in self._filtered_out.items()
            )
            logger.info("제외된 코인: %s", excluded_str)

        return result
