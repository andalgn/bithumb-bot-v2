"""빗썸 REST API 클라이언트.

HMAC-SHA512 인증, 비동기 aiohttp 기반.
Public API: ticker, orderbook, candlestick
Private API: balance, orders, order_detail, place, cancel, market_buy, market_sell
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import time
import urllib.parse
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


class BithumbAPIError(Exception):
    """빗썸 API 오류."""

    def __init__(self, status_code: str, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"Bithumb API Error [{status_code}]: {message}")


class BithumbClient:
    """빗썸 REST API 비동기 클라이언트."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str = "https://api.bithumb.com",
        public_rate_limit: int = 15,
        private_rate_limit: int = 10,
    ) -> None:
        """초기화.

        Args:
            api_key: 빗썸 API 키.
            api_secret: 빗썸 API 시크릿.
            base_url: API 베이스 URL.
            public_rate_limit: Public API 초당 호출 제한.
            private_rate_limit: Private API 초당 호출 제한.
        """
        self._api_key = api_key
        self._api_secret = api_secret
        self._base_url = base_url.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=10)
        self._session: aiohttp.ClientSession | None = None

        # Rate limiting (token bucket)
        self._public_semaphore = asyncio.Semaphore(public_rate_limit)
        self._private_semaphore = asyncio.Semaphore(private_rate_limit)
        self._public_rate_limit = public_rate_limit
        self._private_rate_limit = private_rate_limit

    async def _get_session(self) -> aiohttp.ClientSession:
        """세션을 가져오거나 생성한다."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session

    async def close(self) -> None:
        """세션을 닫는다."""
        if self._session and not self._session.closed:
            await self._session.close()

    def _make_signature(self, endpoint: str, params: dict[str, str]) -> dict[str, str]:
        """HMAC-SHA512 서명을 생성한다.

        Args:
            endpoint: API 엔드포인트 경로.
            params: 요청 파라미터.

        Returns:
            인증 헤더 딕셔너리.
        """
        nonce = str(int(time.time() * 1000))
        query_string = urllib.parse.urlencode(params)

        # hmac_data = endpoint + chr(0) + query_string + chr(0) + nonce
        hmac_data = endpoint + chr(0) + query_string + chr(0) + nonce

        signature = hmac.new(
            self._api_secret.encode("utf-8"),
            hmac_data.encode("utf-8"),
            hashlib.sha512,
        ).hexdigest()

        return {
            "Api-Key": self._api_key,
            "Api-Sign": signature,
            "Api-Nonce": nonce,
            "Content-Type": "application/x-www-form-urlencoded",
        }

    async def _rate_limited(self, semaphore: asyncio.Semaphore, rate: int) -> None:
        """Rate limiting을 적용한다."""
        await semaphore.acquire()
        # 1초 후 세마포어 릴리즈 (토큰 버킷 방식)
        asyncio.get_event_loop().call_later(1.0 / rate, semaphore.release)

    async def _public_request(self, path: str) -> dict[str, Any]:
        """Public API GET 요청.

        Args:
            path: API 경로 (예: /public/ticker/BTC_KRW).

        Returns:
            응답 데이터.

        Raises:
            BithumbAPIError: API 오류 시.
        """
        await self._rate_limited(self._public_semaphore, self._public_rate_limit)
        url = f"{self._base_url}{path}"
        session = await self._get_session()

        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    raise BithumbAPIError(str(resp.status), f"HTTP {resp.status}")
                data = await resp.json(content_type=None)
        except aiohttp.ClientError as e:
            raise BithumbAPIError("NETWORK", str(e)) from e
        except asyncio.TimeoutError as e:
            raise BithumbAPIError("TIMEOUT", "Request timed out") from e

        if data.get("status") != "0000":
            raise BithumbAPIError(
                data.get("status", "UNKNOWN"),
                data.get("message", "Unknown error"),
            )
        return data.get("data", {})

    async def _private_request(
        self, endpoint: str, params: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """Private API POST 요청.

        Args:
            endpoint: API 엔드포인트 (예: /info/balance).
            params: 요청 파라미터.

        Returns:
            응답 데이터.

        Raises:
            BithumbAPIError: API 오류 시.
        """
        await self._rate_limited(self._private_semaphore, self._private_rate_limit)
        if params is None:
            params = {}
        params["endpoint"] = endpoint

        headers = self._make_signature(endpoint, params)
        url = f"{self._base_url}{endpoint}"
        session = await self._get_session()

        try:
            async with session.post(
                url, data=urllib.parse.urlencode(params), headers=headers
            ) as resp:
                if resp.status == 401 or resp.status == 403:
                    raise BithumbAPIError(str(resp.status), "Authentication error")
                if resp.status != 200:
                    raise BithumbAPIError(str(resp.status), f"HTTP {resp.status}")
                data = await resp.json(content_type=None)
        except aiohttp.ClientError as e:
            raise BithumbAPIError("NETWORK", str(e)) from e
        except asyncio.TimeoutError as e:
            raise BithumbAPIError("TIMEOUT", "Request timed out") from e

        if data.get("status") != "0000":
            raise BithumbAPIError(
                data.get("status", "UNKNOWN"),
                data.get("message", "Unknown error"),
            )
        return data.get("data", {})

    # ─── Public API ───

    async def get_ticker(self, coin: str) -> dict[str, Any]:
        """현재가 정보를 조회한다.

        Args:
            coin: 코인 심볼 (예: BTC).

        Returns:
            현재가 데이터.
        """
        return await self._public_request(f"/public/ticker/{coin}_KRW")

    async def get_orderbook(self, coin: str) -> dict[str, Any]:
        """호가창을 조회한다.

        Args:
            coin: 코인 심볼.

        Returns:
            호가창 데이터.
        """
        return await self._public_request(f"/public/orderbook/{coin}_KRW")

    async def get_candlestick(
        self, coin: str, interval: str = "15m"
    ) -> list[list]:
        """캔들 데이터를 조회한다.

        Args:
            coin: 코인 심볼.
            interval: 캔들 간격 (1m, 3m, 5m, 10m, 15m, 30m, 1h, 6h, 12h, 24h).

        Returns:
            캔들 데이터 리스트. 각 항목: [timestamp, open, close, high, low, volume]
        """
        chart_intervals = interval.replace("m", "m").replace("h", "h")
        return await self._public_request(
            f"/public/candlestick/{coin}_KRW/{chart_intervals}"
        )

    # ─── Private API ───

    async def get_balance(self, coin: str = "ALL") -> dict[str, Any]:
        """잔고를 조회한다.

        Args:
            coin: 코인 심볼. ALL이면 전체.

        Returns:
            잔고 데이터.
        """
        currency = "ALL" if coin == "ALL" else coin
        return await self._private_request(
            "/info/balance",
            {"order_currency": currency, "payment_currency": "KRW"},
        )

    async def get_orders(
        self, coin: str, order_id: str = "", order_type: str = ""
    ) -> dict[str, Any]:
        """주문 내역을 조회한다.

        Args:
            coin: 코인 심볼.
            order_id: 주문 ID (선택).
            order_type: 주문 유형 bid/ask (선택).

        Returns:
            주문 내역 데이터.
        """
        params: dict[str, str] = {
            "order_currency": coin,
            "payment_currency": "KRW",
        }
        if order_id:
            params["order_id"] = order_id
        if order_type:
            params["type"] = order_type
        return await self._private_request("/info/orders", params)

    async def get_order_detail(
        self, coin: str, order_id: str
    ) -> dict[str, Any]:
        """주문 상세를 조회한다.

        Args:
            coin: 코인 심볼.
            order_id: 주문 ID.

        Returns:
            주문 상세 데이터.
        """
        return await self._private_request(
            "/info/order_detail",
            {
                "order_currency": coin,
                "payment_currency": "KRW",
                "order_id": order_id,
            },
        )

    async def place_order(
        self,
        coin: str,
        side: str,
        price: float,
        qty: float,
    ) -> dict[str, Any]:
        """지정가 주문을 실행한다.

        Args:
            coin: 코인 심볼.
            side: bid(매수) 또는 ask(매도).
            price: 주문 가격.
            qty: 주문 수량.

        Returns:
            주문 결과 데이터.
        """
        return await self._private_request(
            "/trade/place",
            {
                "order_currency": coin,
                "payment_currency": "KRW",
                "units": str(qty),
                "price": str(int(price)),
                "type": side,
            },
        )

    async def cancel_order(
        self, coin: str, order_id: str, side: str
    ) -> dict[str, Any]:
        """주문을 취소한다.

        Args:
            coin: 코인 심볼.
            order_id: 주문 ID.
            side: bid(매수) 또는 ask(매도).

        Returns:
            취소 결과 데이터.
        """
        return await self._private_request(
            "/trade/cancel",
            {
                "order_currency": coin,
                "payment_currency": "KRW",
                "order_id": order_id,
                "type": side,
            },
        )

    async def market_buy(self, coin: str, total_krw: float) -> dict[str, Any]:
        """시장가 매수를 실행한다.

        Args:
            coin: 코인 심볼.
            total_krw: 매수 총 금액(KRW).

        Returns:
            주문 결과 데이터.
        """
        return await self._private_request(
            "/trade/market_buy",
            {
                "order_currency": coin,
                "payment_currency": "KRW",
                "units": str(total_krw),
            },
        )

    async def market_sell(self, coin: str, qty: float) -> dict[str, Any]:
        """시장가 매도를 실행한다.

        Args:
            coin: 코인 심볼.
            qty: 매도 수량.

        Returns:
            주문 결과 데이터.
        """
        return await self._private_request(
            "/trade/market_sell",
            {
                "order_currency": coin,
                "payment_currency": "KRW",
                "units": str(qty),
            },
        )
