"""DataFeed 테스트.

캐시 TTL, 파싱, 스냅샷 조회를 모킹 기반으로 테스트한다.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.data_types import Candle, MarketSnapshot, Orderbook, Ticker
from app.errors import DataFetchError
from market.bithumb_api import BithumbAPIError, BithumbClient
from market.datafeed import CACHE_TTL_SEC, MAX_CANDLES, DataFeed, _CacheEntry

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_client() -> MagicMock:
    """BithumbClient 모킹 객체."""
    client = MagicMock(spec=BithumbClient)
    client.get_candlestick = AsyncMock()
    client.get_ticker = AsyncMock()
    client.get_orderbook = AsyncMock()
    return client


@pytest.fixture
def feed(mock_client: MagicMock) -> DataFeed:
    """DataFeed 인스턴스."""
    return DataFeed(client=mock_client, coins=["BTC", "ETH"])


# ---------------------------------------------------------------------------
# _CacheEntry
# ---------------------------------------------------------------------------

class TestCacheEntry:
    """_CacheEntry 유효성 테스트."""

    def test_valid_entry(self) -> None:
        """만료 전 캐시는 유효하다."""
        entry = _CacheEntry(data="hello", expires_at=time.time() + 100)
        assert entry.is_valid is True

    def test_expired_entry(self) -> None:
        """만료된 캐시는 유효하지 않다."""
        entry = _CacheEntry(data="hello", expires_at=time.time() - 1)
        assert entry.is_valid is False


# ---------------------------------------------------------------------------
# _get_cached / _set_cached
# ---------------------------------------------------------------------------

class TestCache:
    """캐시 get/set 테스트."""

    def test_get_cached_miss(self, feed: DataFeed) -> None:
        """캐시 미스 시 None을 반환한다."""
        assert feed._get_cached("nonexistent") is None

    def test_set_and_get_cached(self, feed: DataFeed) -> None:
        """캐시에 저장 후 조회하면 데이터를 반환한다."""
        feed._set_cached("key1", [1, 2, 3])
        assert feed._get_cached("key1") == [1, 2, 3]

    def test_get_cached_expired(self, feed: DataFeed) -> None:
        """만료된 캐시는 None을 반환한다."""
        feed._cache["old"] = _CacheEntry(data="stale", expires_at=time.time() - 10)
        assert feed._get_cached("old") is None

    def test_set_cached_overwrites(self, feed: DataFeed) -> None:
        """같은 키에 다시 저장하면 덮어쓴다."""
        feed._set_cached("k", "v1")
        feed._set_cached("k", "v2")
        assert feed._get_cached("k") == "v2"

    def test_set_cached_ttl(self, feed: DataFeed) -> None:
        """캐시 TTL이 CACHE_TTL_SEC 이내로 설정된다."""
        before = time.time()
        feed._set_cached("k", "v")
        entry = feed._cache["k"]
        assert entry.expires_at >= before + CACHE_TTL_SEC - 1
        assert entry.expires_at <= before + CACHE_TTL_SEC + 1


# ---------------------------------------------------------------------------
# _parse_candles
# ---------------------------------------------------------------------------

class TestParseCandles:
    """_parse_candles 테스트."""

    def test_valid_candles(self, feed: DataFeed) -> None:
        """유효한 캔들 데이터를 올바르게 파싱한다."""
        raw = [
            [1000, "100.0", "105.0", "110.0", "95.0", "50.0"],
            [2000, "105.0", "108.0", "112.0", "103.0", "60.0"],
        ]
        result = feed._parse_candles(raw)
        assert len(result) == 2
        assert isinstance(result[0], Candle)
        assert result[0].timestamp == 1000
        assert result[0].open == 100.0
        assert result[0].close == 105.0
        assert result[0].high == 110.0
        assert result[0].low == 95.0
        assert result[0].volume == 50.0

    def test_sorted_by_timestamp(self, feed: DataFeed) -> None:
        """캔들이 시간순으로 정렬된다."""
        raw = [
            [3000, "1", "2", "3", "0.5", "10"],
            [1000, "1", "2", "3", "0.5", "10"],
            [2000, "1", "2", "3", "0.5", "10"],
        ]
        result = feed._parse_candles(raw)
        timestamps = [c.timestamp for c in result]
        assert timestamps == [1000, 2000, 3000]

    def test_max_candles_limit(self, feed: DataFeed) -> None:
        """MAX_CANDLES 개를 초과하면 최신 것만 남긴다."""
        raw = [[i, "1", "2", "3", "0.5", "10"] for i in range(MAX_CANDLES + 50)]
        result = feed._parse_candles(raw)
        assert len(result) == MAX_CANDLES
        # 가장 오래된 것이 50번째부터 시작
        assert result[0].timestamp == 50

    def test_invalid_data_skipped(self, feed: DataFeed) -> None:
        """잘못된 데이터는 건너뛴다."""
        raw = [
            [1000, "100.0", "105.0", "110.0", "95.0", "50.0"],  # 유효
            [2000, "bad"],  # IndexError
            "not_a_list",  # TypeError
            [3000, "100.0", "abc", "110.0", "95.0", "50.0"],  # ValueError
            [4000, "100.0", "105.0", "110.0", "95.0", "50.0"],  # 유효
        ]
        result = feed._parse_candles(raw)
        assert len(result) == 2
        assert result[0].timestamp == 1000
        assert result[1].timestamp == 4000

    def test_empty_input(self, feed: DataFeed) -> None:
        """빈 리스트는 빈 결과를 반환한다."""
        assert feed._parse_candles([]) == []


# ---------------------------------------------------------------------------
# _parse_ticker
# ---------------------------------------------------------------------------

class TestParseTicker:
    """_parse_ticker 테스트."""

    def test_full_ticker(self, feed: DataFeed) -> None:
        """모든 필드가 있는 ticker를 파싱한다."""
        raw = {
            "closing_price": "50000000",
            "opening_price": "49000000",
            "min_price": "48000000",
            "max_price": "51000000",
            "units_traded": "100.5",
            "acc_trade_value": "5000000000",
            "prev_closing_price": "49500000",
            "units_traded_24H": "200.3",
            "fluctate_24H": "500000",
            "fluctate_rate_24H": "1.01",
        }
        result = feed._parse_ticker("BTC", raw)
        assert isinstance(result, Ticker)
        assert result.coin == "BTC"
        assert result.closing_price == 50000000.0
        assert result.units_traded_24h == 200.3

    def test_missing_fields_default_zero(self, feed: DataFeed) -> None:
        """누락 필드는 0으로 기본 설정된다."""
        result = feed._parse_ticker("ETH", {})
        assert result.closing_price == 0.0
        assert result.opening_price == 0.0


# ---------------------------------------------------------------------------
# _parse_orderbook
# ---------------------------------------------------------------------------

class TestParseOrderbook:
    """_parse_orderbook 테스트."""

    def test_valid_orderbook(self, feed: DataFeed) -> None:
        """유효한 호가창 데이터를 파싱한다."""
        raw = {
            "timestamp": 1700000000000,
            "bids": [
                {"price": "50000000", "quantity": "0.5"},
                {"price": "49900000", "quantity": "1.0"},
            ],
            "asks": [
                {"price": "50100000", "quantity": "0.3"},
            ],
        }
        result = feed._parse_orderbook(raw)
        assert isinstance(result, Orderbook)
        assert result.timestamp == 1700000000000
        assert len(result.bids) == 2
        assert len(result.asks) == 1
        assert result.bids[0].price == 50000000.0
        assert result.asks[0].quantity == 0.3

    def test_empty_orderbook(self, feed: DataFeed) -> None:
        """빈 호가창도 정상 파싱된다."""
        result = feed._parse_orderbook({})
        assert result.bids == []
        assert result.asks == []


# ---------------------------------------------------------------------------
# get_candles (async, 캐시 적용)
# ---------------------------------------------------------------------------

class TestGetCandles:
    """get_candles 비동기 테스트."""

    @pytest.mark.asyncio
    async def test_fetches_and_caches(
        self, feed: DataFeed, mock_client: MagicMock
    ) -> None:
        """첫 호출은 API를 호출하고 캐시에 저장한다."""
        mock_client.get_candlestick.return_value = [
            [1000, "1", "2", "3", "0.5", "10"],
        ]
        result = await feed.get_candles("BTC", "5m")
        assert len(result) == 1
        mock_client.get_candlestick.assert_called_once_with("BTC", "5m")

        # 두 번째 호출은 캐시 히트
        result2 = await feed.get_candles("BTC", "5m")
        assert result2 == result
        mock_client.get_candlestick.assert_called_once()  # 추가 호출 없음

    @pytest.mark.asyncio
    async def test_api_error_raises_data_fetch_error(
        self, feed: DataFeed, mock_client: MagicMock
    ) -> None:
        """API 에러 시 DataFetchError를 발생시킨다."""
        mock_client.get_candlestick.side_effect = BithumbAPIError("NETWORK", "network error")
        with pytest.raises(DataFetchError) as exc_info:
            await feed.get_candles("BTC", "5m")
        assert exc_info.value.symbol == "BTC"


# ---------------------------------------------------------------------------
# get_ticker (async)
# ---------------------------------------------------------------------------

class TestGetTicker:
    """get_ticker 비동기 테스트."""

    @pytest.mark.asyncio
    async def test_fetches_ticker(
        self, feed: DataFeed, mock_client: MagicMock
    ) -> None:
        """ticker를 정상 조회한다."""
        mock_client.get_ticker.return_value = {
            "closing_price": "50000000",
            "opening_price": "49000000",
            "min_price": "48000000",
            "max_price": "51000000",
            "units_traded": "100",
            "acc_trade_value": "5000000000",
            "prev_closing_price": "49500000",
            "units_traded_24H": "200",
            "fluctate_24H": "500000",
            "fluctate_rate_24H": "1.0",
        }
        result = await feed.get_ticker("BTC")
        assert result is not None
        assert result.closing_price == 50000000.0

    @pytest.mark.asyncio
    async def test_api_error_raises_data_fetch_error(
        self, feed: DataFeed, mock_client: MagicMock
    ) -> None:
        """API 에러 시 DataFetchError를 발생시킨다."""
        mock_client.get_ticker.side_effect = BithumbAPIError("NETWORK", "fail")
        with pytest.raises(DataFetchError) as exc_info:
            await feed.get_ticker("BTC")
        assert exc_info.value.symbol == "BTC"


# ---------------------------------------------------------------------------
# get_orderbook (async)
# ---------------------------------------------------------------------------

class TestGetOrderbook:
    """get_orderbook 비동기 테스트."""

    @pytest.mark.asyncio
    async def test_fetches_orderbook(
        self, feed: DataFeed, mock_client: MagicMock
    ) -> None:
        """호가창을 정상 조회한다."""
        mock_client.get_orderbook.return_value = {
            "timestamp": 1700000000000,
            "bids": [{"price": "50000000", "quantity": "0.5"}],
            "asks": [{"price": "50100000", "quantity": "0.3"}],
        }
        result = await feed.get_orderbook("BTC")
        assert result is not None
        assert len(result.bids) == 1

    @pytest.mark.asyncio
    async def test_api_error_raises_data_fetch_error(
        self, feed: DataFeed, mock_client: MagicMock
    ) -> None:
        """API 에러 시 DataFetchError를 발생시킨다."""
        mock_client.get_orderbook.side_effect = BithumbAPIError("NETWORK", "fail")
        with pytest.raises(DataFetchError) as exc_info:
            await feed.get_orderbook("BTC")
        assert exc_info.value.symbol == "BTC"


# ---------------------------------------------------------------------------
# get_snapshot (async)
# ---------------------------------------------------------------------------

class TestGetSnapshot:
    """get_snapshot 비동기 테스트."""

    @pytest.mark.asyncio
    async def test_returns_market_snapshot(
        self, feed: DataFeed, mock_client: MagicMock
    ) -> None:
        """MarketSnapshot을 올바르게 구성한다."""
        mock_client.get_ticker.return_value = {
            "closing_price": "50000000",
            "opening_price": "49000000",
            "min_price": "48000000",
            "max_price": "51000000",
            "units_traded": "100",
            "acc_trade_value": "5000000000",
            "prev_closing_price": "49500000",
            "units_traded_24H": "200",
            "fluctate_24H": "500000",
            "fluctate_rate_24H": "1.0",
        }
        mock_client.get_candlestick.return_value = [
            [1000, "1", "2", "3", "0.5", "10"],
        ]
        mock_client.get_orderbook.return_value = {
            "timestamp": 1700000000000,
            "bids": [{"price": "50000000", "quantity": "0.5"}],
            "asks": [{"price": "50100000", "quantity": "0.3"}],
        }

        snapshot = await feed.get_snapshot("BTC")
        assert isinstance(snapshot, MarketSnapshot)
        assert snapshot.symbol == "BTC"
        assert snapshot.current_price == 50000000.0
        assert len(snapshot.candles_5m) == 1
        assert len(snapshot.candles_15m) == 1
        assert len(snapshot.candles_1h) == 1
        assert snapshot.orderbook is not None
        assert snapshot.ticker is not None

    @pytest.mark.asyncio
    async def test_snapshot_with_ticker_failure_raises(
        self, feed: DataFeed, mock_client: MagicMock
    ) -> None:
        """ticker 실패 시 DataFetchError가 발생한다."""
        mock_client.get_ticker.side_effect = BithumbAPIError("NETWORK", "fail")
        mock_client.get_candlestick.return_value = []
        mock_client.get_orderbook.side_effect = BithumbAPIError("NETWORK", "fail")

        with pytest.raises(DataFetchError) as exc_info:
            await feed.get_snapshot("BTC")
        assert exc_info.value.symbol == "BTC"
