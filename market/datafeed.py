"""데이터 수집 모듈.

10개 코인의 5M/15M/1H 캔들 데이터 수집 + TTL 캐시 60초.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from app.data_types import (
    Candle,
    MarketSnapshot,
    Orderbook,
    OrderbookEntry,
    Ticker,
    parse_raw_candles,
)
from app.errors import DataFetchError
from market.bithumb_api import BithumbAPIError, BithumbClient

logger = logging.getLogger(__name__)

CACHE_TTL_SEC = 60
MAX_CANDLES = 200


@dataclass
class _CacheEntry:
    """캐시 항목."""

    data: object
    expires_at: float = 0.0

    @property
    def is_valid(self) -> bool:
        """캐시가 유효한지 확인한다."""
        return time.time() < self.expires_at


class DataFeed:
    """시장 데이터 수집기."""

    def __init__(self, client: BithumbClient, coins: list[str]) -> None:
        """초기화.

        Args:
            client: 빗썸 API 클라이언트.
            coins: 대상 코인 목록.
        """
        self._client = client
        self._coins = coins
        self._cache: dict[str, _CacheEntry] = {}

    def _get_cached(self, key: str) -> object | None:
        """캐시에서 데이터를 가져온다."""
        entry = self._cache.get(key)
        if entry and entry.is_valid:
            return entry.data
        return None

    def _set_cached(self, key: str, data: object) -> None:
        """캐시에 데이터를 저장한다."""
        self._cache[key] = _CacheEntry(data=data, expires_at=time.time() + CACHE_TTL_SEC)

    def _parse_candles(self, raw: list) -> list[Candle]:
        """빗썸 캔들 응답을 Candle 리스트로 변환한다.

        Args:
            raw: 빗썸 API 캔들 응답 리스트.

        Returns:
            Candle 리스트 (최신 MAX_CANDLES개).
        """
        candles = parse_raw_candles(raw)
        # 시간순 정렬, 최근 MAX_CANDLES개만
        candles.sort(key=lambda c: c.timestamp)
        return candles[-MAX_CANDLES:]

    def _parse_ticker(self, coin: str, raw: dict) -> Ticker:
        """빗썸 ticker 응답을 Ticker로 변환한다."""
        return Ticker(
            coin=coin,
            closing_price=float(raw.get("closing_price", 0)),
            opening_price=float(raw.get("opening_price", 0)),
            min_price=float(raw.get("min_price", 0)),
            max_price=float(raw.get("max_price", 0)),
            units_traded=float(raw.get("units_traded", 0)),
            acc_trade_value=float(raw.get("acc_trade_value", 0)),
            prev_closing_price=float(raw.get("prev_closing_price", 0)),
            units_traded_24h=float(raw.get("units_traded_24H", 0)),
            fluctate_24h=float(raw.get("fluctate_24H", 0)),
            fluctate_rate_24h=float(raw.get("fluctate_rate_24H", 0)),
        )

    def _parse_orderbook(self, raw: dict) -> Orderbook:
        """빗썸 orderbook 응답을 Orderbook으로 변환한다."""
        bids = [
            OrderbookEntry(price=float(b["price"]), quantity=float(b["quantity"]))
            for b in raw.get("bids", [])
        ]
        asks = [
            OrderbookEntry(price=float(a["price"]), quantity=float(a["quantity"]))
            for a in raw.get("asks", [])
        ]
        return Orderbook(
            timestamp=int(raw.get("timestamp", int(time.time() * 1000))),
            bids=bids,
            asks=asks,
        )

    def update_coins(self, coins: list[str]) -> None:
        """거래 대상 코인 목록을 갱신한다.

        Args:
            coins: 새 코인 목록.
        """
        self._coins = list(coins)

    async def get_candles(self, coin: str, interval: str) -> list[Candle]:
        """캔들 데이터를 조회한다 (캐시 적용).

        Args:
            coin: 코인 심볼.
            interval: 캔들 간격 (5m, 15m, 1h).

        Returns:
            Candle 리스트.
        """
        cache_key = f"candle:{coin}:{interval}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached  # type: ignore[return-value]

        try:
            raw = await self._client.get_candlestick(coin, interval)
            candles = self._parse_candles(raw)
            self._set_cached(cache_key, candles)
            return candles
        except (BithumbAPIError, ValueError) as exc:
            raise DataFetchError(coin, f"{interval} 캔들 조회: {exc}") from exc

    async def get_ticker(self, coin: str) -> Ticker | None:
        """현재가를 조회한다 (캐시 적용).

        Args:
            coin: 코인 심볼.

        Returns:
            Ticker 또는 None.
        """
        cache_key = f"ticker:{coin}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached  # type: ignore[return-value]

        try:
            raw = await self._client.get_ticker(coin)
            ticker = self._parse_ticker(coin, raw)
            self._set_cached(cache_key, ticker)
            return ticker
        except (BithumbAPIError, ValueError) as exc:
            raise DataFetchError(coin, f"현재가 조회: {exc}") from exc

    async def get_orderbook(self, coin: str) -> Orderbook | None:
        """호가창을 조회한다 (캐시 적용).

        Args:
            coin: 코인 심볼.

        Returns:
            Orderbook 또는 None.
        """
        cache_key = f"orderbook:{coin}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached  # type: ignore[return-value]

        try:
            raw = await self._client.get_orderbook(coin)
            ob = self._parse_orderbook(raw)
            self._set_cached(cache_key, ob)
            return ob
        except (BithumbAPIError, ValueError) as exc:
            raise DataFetchError(coin, f"호가창 조회: {exc}") from exc

    async def get_snapshot(self, coin: str) -> MarketSnapshot:
        """코인의 전체 시장 스냅샷을 가져온다.

        Args:
            coin: 코인 심볼.

        Returns:
            MarketSnapshot.
        """
        # 병렬 조회
        import asyncio

        ticker_task = asyncio.create_task(self.get_ticker(coin))
        candles_5m_task = asyncio.create_task(self.get_candles(coin, "5m"))
        candles_15m_task = asyncio.create_task(self.get_candles(coin, "15m"))
        candles_1h_task = asyncio.create_task(self.get_candles(coin, "1h"))
        orderbook_task = asyncio.create_task(self.get_orderbook(coin))

        ticker = await ticker_task
        candles_5m = await candles_5m_task
        candles_15m = await candles_15m_task
        candles_1h = await candles_1h_task
        orderbook = await orderbook_task

        current_price = ticker.closing_price if ticker else 0.0

        return MarketSnapshot(
            symbol=coin,
            current_price=current_price,
            candles_5m=candles_5m,
            candles_15m=candles_15m,
            candles_1h=candles_1h,
            orderbook=orderbook,
            ticker=ticker,
        )

    async def get_all_snapshots(self) -> dict[str, MarketSnapshot]:
        """전체 코인의 스냅샷을 가져온다.

        Returns:
            코인별 MarketSnapshot 딕셔너리.
        """
        import asyncio

        tasks = {coin: asyncio.create_task(self.get_snapshot(coin)) for coin in self._coins}
        results: dict[str, MarketSnapshot] = {}
        for coin, task in tasks.items():
            try:
                results[coin] = await task
            except DataFetchError as exc:
                logger.warning("데이터 조회 실패: %s — %s", coin, exc)
                results[coin] = MarketSnapshot(symbol=coin, current_price=0.0)
        return results
