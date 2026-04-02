"""빗썸 REST API 클라이언트.

JWT (HS256) 인증, 비동기 aiohttp 기반.
Public API: ticker, orderbook, candlestick
Private API: balance, orders, order_detail, place, cancel, market_buy, market_sell
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import ssl
import time
import urllib.parse
import uuid
from typing import Any

import aiohttp
import jwt

from app.errors import APIAuthError

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
        proxy: str = "",
        verify_ssl: bool = True,
    ) -> None:
        """초기화.

        Args:
            api_key: 빗썸 API 키.
            api_secret: 빗썸 API 시크릿.
            base_url: API 베이스 URL.
            public_rate_limit: Public API 초당 호출 제한.
            private_rate_limit: Private API 초당 호출 제한.
            proxy: HTTP 프록시 URL (예: http://127.0.0.1:1081). 미지정 시 빈 문자열.
            verify_ssl: SSL 인증서 검증 여부. False이면 검증 비활성화 (VPN 환경용).
        """
        self._api_key = api_key
        self._api_secret = api_secret
        self._base_url = base_url.rstrip("/")
        self._proxy = proxy
        self._timeout = aiohttp.ClientTimeout(total=10)
        self._session: aiohttp.ClientSession | None = None

        # SSL 설정: verify_ssl=True이면 기본 검증, False이면 비활성화
        if verify_ssl:
            self._ssl_ctx: ssl.SSLContext | None = None
        else:
            self._ssl_ctx = ssl.create_default_context()
            self._ssl_ctx.check_hostname = False
            self._ssl_ctx.verify_mode = ssl.CERT_NONE

        # Rate limiting (token bucket)
        self._public_semaphore = asyncio.Semaphore(public_rate_limit)
        self._private_semaphore = asyncio.Semaphore(private_rate_limit)
        self._public_rate_limit = public_rate_limit
        self._private_rate_limit = private_rate_limit

    async def _get_session(self) -> aiohttp.ClientSession:
        """세션을 가져오거나 생성한다."""
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(ssl=self._ssl_ctx)
            self._session = aiohttp.ClientSession(timeout=self._timeout, connector=connector)
        return self._session

    async def close(self) -> None:
        """세션을 닫는다."""
        if self._session and not self._session.closed:
            await self._session.close()

    def _make_auth_headers(
        self,
        params: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        """JWT 인증 헤더를 생성한다.

        Args:
            params: 요청 파라미터 (없으면 파라미터 없는 요청).

        Returns:
            인증 헤더 딕셔너리.
        """
        payload: dict[str, object] = {
            "access_key": self._api_key,
            "nonce": str(uuid.uuid4()),
            "timestamp": round(time.time() * 1000),
        }

        if params:
            query = urllib.parse.urlencode(params).encode()
            h = hashlib.sha512()
            h.update(query)
            payload["query_hash"] = h.hexdigest()
            payload["query_hash_alg"] = "SHA512"

        token = jwt.encode(payload, self._api_secret, algorithm="HS256")
        return {"Authorization": f"Bearer {token}"}

    async def _rate_limited(self, semaphore: asyncio.Semaphore, rate: int) -> None:
        """Rate limiting을 적용한다."""
        await semaphore.acquire()
        # 1초 후 세마포어 릴리즈 (토큰 버킷 방식)
        asyncio.get_running_loop().call_later(1.0 / rate, semaphore.release)

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
            async with session.get(url, proxy=self._proxy or None) as resp:
                if resp.status != 200:
                    raise BithumbAPIError(str(resp.status), f"HTTP {resp.status}")
                data = await resp.json(content_type=None)
        except aiohttp.ClientError as e:
            raise BithumbAPIError("NETWORK", str(e)) from e
        except TimeoutError as e:
            raise BithumbAPIError("TIMEOUT", "Request timed out") from e

        if data.get("status") != "0000":
            raise BithumbAPIError(
                data.get("status", "UNKNOWN"),
                data.get("message", "Unknown error"),
            )
        return data.get("data", {})

    async def _private_get(
        self,
        path: str,
        params: dict[str, str] | None = None,
    ) -> Any:
        """Private API GET 요청.

        Args:
            path: API 경로 (예: /v1/accounts).
            params: 쿼리 파라미터.

        Returns:
            응답 데이터.

        Raises:
            BithumbAPIError: API 오류 시.
        """
        await self._rate_limited(self._private_semaphore, self._private_rate_limit)
        headers = self._make_auth_headers(params)
        url = f"{self._base_url}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        session = await self._get_session()

        try:
            async with session.get(
                url,
                headers=headers,
                proxy=self._proxy or None,
            ) as resp:
                data = await resp.json(content_type=None)
                if resp.status in (401, 403):
                    raise APIAuthError(f"빗썸 API 인증 실패: HTTP {resp.status}")
                if resp.status != 200:
                    err = data.get("error", {})
                    raise BithumbAPIError(
                        str(resp.status),
                        f"{err.get('name', 'unknown')}: {err.get('message', resp.status)}",
                    )
                return data
        except aiohttp.ClientError as e:
            raise BithumbAPIError("NETWORK", str(e)) from e
        except TimeoutError as e:
            raise BithumbAPIError("TIMEOUT", "Request timed out") from e

    async def _private_post(
        self,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> Any:
        """Private API POST 요청 (JSON body).

        Args:
            path: API 경로 (예: /v1/orders).
            body: JSON 요청 바디.

        Returns:
            응답 데이터.

        Raises:
            BithumbAPIError: API 오류 시.
        """
        await self._rate_limited(self._private_semaphore, self._private_rate_limit)
        headers = self._make_auth_headers(body)
        headers["Content-Type"] = "application/json"
        url = f"{self._base_url}{path}"
        session = await self._get_session()

        try:
            async with session.post(
                url,
                json=body,
                headers=headers,
                proxy=self._proxy or None,
            ) as resp:
                data = await resp.json(content_type=None)
                if resp.status in (401, 403):
                    raise APIAuthError(f"빗썸 API 인증 실패: HTTP {resp.status}")
                if resp.status not in (200, 201):
                    err = data.get("error", {})
                    raise BithumbAPIError(
                        str(resp.status),
                        f"{err.get('name', 'unknown')}: {err.get('message', resp.status)}",
                    )
                return data
        except aiohttp.ClientError as e:
            raise BithumbAPIError("NETWORK", str(e)) from e
        except TimeoutError as e:
            raise BithumbAPIError("TIMEOUT", "Request timed out") from e

    async def _private_delete(
        self,
        path: str,
        params: dict[str, str] | None = None,
    ) -> Any:
        """Private API DELETE 요청.

        Args:
            path: API 경로 (예: /v1/order).
            params: 쿼리 파라미터.

        Returns:
            응답 데이터.

        Raises:
            BithumbAPIError: API 오류 시.
        """
        await self._rate_limited(self._private_semaphore, self._private_rate_limit)
        headers = self._make_auth_headers(params)
        url = f"{self._base_url}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        session = await self._get_session()

        try:
            async with session.delete(
                url,
                headers=headers,
                proxy=self._proxy or None,
            ) as resp:
                data = await resp.json(content_type=None)
                if resp.status in (401, 403):
                    raise APIAuthError(f"빗썸 API 인증 실패: HTTP {resp.status}")
                if resp.status != 200:
                    err = data.get("error", {})
                    raise BithumbAPIError(
                        str(resp.status),
                        f"{err.get('name', 'unknown')}: {err.get('message', resp.status)}",
                    )
                return data
        except aiohttp.ClientError as e:
            raise BithumbAPIError("NETWORK", str(e)) from e
        except TimeoutError as e:
            raise BithumbAPIError("TIMEOUT", "Request timed out") from e

    # ─── Public API ───

    async def get_ticker(self, coin: str) -> dict[str, Any]:
        """현재가 정보를 조회한다.

        Args:
            coin: 코인 심볼 (예: BTC).

        Returns:
            현재가 데이터.
        """
        return await self._public_request(f"/public/ticker/{coin}_KRW")

    async def get_all_tickers(self) -> dict[str, dict]:
        """전체 KRW 마켓 현재가 및 거래량을 조회한다.

        Returns:
            {심볼: {acc_trade_value_24H: 거래대금, ...}} 딕셔너리.
            오류 시 빈 딕셔너리 반환.
        """
        try:
            data = await self._public_request("/public/ticker/ALL_KRW")
            return {k: v for k, v in data.items() if k != "date" and isinstance(v, dict)}
        except Exception:
            logger.exception("get_all_tickers 실패")
            return {}

    async def get_orderbook(self, coin: str) -> dict[str, Any]:
        """호가창을 조회한다.

        Args:
            coin: 코인 심볼.

        Returns:
            호가창 데이터.
        """
        return await self._public_request(f"/public/orderbook/{coin}_KRW")

    async def get_candlestick(self, coin: str, interval: str = "15m") -> list[list]:
        """캔들 데이터를 조회한다.

        Args:
            coin: 코인 심볼.
            interval: 캔들 간격 (1m, 3m, 5m, 10m, 15m, 30m, 1h, 6h, 12h, 24h).

        Returns:
            캔들 데이터 리스트. 각 항목: [timestamp, open, close, high, low, volume]
        """
        chart_intervals = interval
        data = await self._public_request(f"/public/candlestick/{coin}_KRW/{chart_intervals}")
        if not isinstance(data, list):
            return []
        return data

    # ─── Private API ───

    async def get_balance(self, coin: str = "ALL") -> dict[str, Any]:
        """잔고를 조회한다.

        Args:
            coin: 코인 심볼. ALL이면 전체.

        Returns:
            잔고 데이터 (레거시 호환 형식).
        """
        accounts = await self._private_get("/v1/accounts")
        # v1 응답을 레거시 형식으로 변환
        result: dict[str, Any] = {}
        for acc in accounts:
            currency = acc["currency"].lower()
            result[f"available_{currency}"] = acc["balance"]
            result[f"locked_{currency}"] = acc.get("locked", "0")
            result[f"avg_buy_price_{currency}"] = acc.get("avg_buy_price", "0")
        return result

    async def get_orders(
        self, coin: str, order_id: str = "", order_type: str = ""
    ) -> dict[str, Any]:
        """주문 내역을 조회한다.

        Args:
            coin: 코인 심볼.
            order_id: 주문 ID (선택, 미사용).
            order_type: 주문 유형 bid/ask (선택).

        Returns:
            주문 내역 데이터.
        """
        params: dict[str, str] = {"market": f"KRW-{coin}", "state": "wait"}
        if order_type:
            params["side"] = order_type
        return await self._private_get("/v1/orders", params)

    async def get_order_detail(self, coin: str, order_id: str) -> dict[str, Any]:
        """주문 상세를 조회한다.

        Args:
            coin: 코인 심볼.
            order_id: 주문 UUID.

        Returns:
            주문 상세 데이터.
        """
        return await self._private_get("/v1/order", {"uuid": order_id})

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
        body = {
            "market": f"KRW-{coin}",
            "side": side,
            "volume": str(qty),
            "price": str(int(price)),
            "ord_type": "limit",
        }
        return await self._private_post("/v1/orders", body)

    async def cancel_order(self, coin: str, order_id: str, side: str) -> dict[str, Any]:
        """주문을 취소한다.

        Args:
            coin: 코인 심볼.
            order_id: 주문 UUID.
            side: bid(매수) 또는 ask(매도) (v1에서는 미사용).

        Returns:
            취소 결과 데이터.
        """
        return await self._private_delete("/v1/order", {"uuid": order_id})

    async def market_buy(self, coin: str, total_krw: float) -> dict[str, Any]:
        """시장가 매수를 실행한다.

        Args:
            coin: 코인 심볼.
            total_krw: 매수 총 금액(KRW).

        Returns:
            주문 결과 데이터.
        """
        body = {
            "market": f"KRW-{coin}",
            "side": "bid",
            "price": str(int(total_krw)),
            "ord_type": "price",
        }
        return await self._private_post("/v1/orders", body)

    async def market_sell(self, coin: str, qty: float) -> dict[str, Any]:
        """시장가 매도를 실행한다.

        Args:
            coin: 코인 심볼.
            qty: 매도 수량.

        Returns:
            주문 결과 데이터.
        """
        body = {
            "market": f"KRW-{coin}",
            "side": "ask",
            "volume": str(qty),
            "ord_type": "market",
        }
        return await self._private_post("/v1/orders", body)
