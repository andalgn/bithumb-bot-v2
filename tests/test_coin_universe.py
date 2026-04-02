"""CoinUniverse 단위 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from strategy.coin_universe import CoinUniverse


def _make_ticker_data(coins: list[tuple[str, float, float, float, float]]) -> dict:
    """
    ticker 데이터 생성.

    Args:
        coins: [(심볼, 24h_거래량, 가격, bid, ask), ...]

    Returns:
        {심볼: {acc_trade_value_24H, last, bid, ask}, ...}
    """
    return {
        sym: {
            "acc_trade_value_24H": str(vol_24h),
            "last": str(price),
            "bid": str(bid),
            "ask": str(ask),
        }
        for sym, vol_24h, price, bid, ask in coins
    }


def _make_candlestick_data(
    num_candles: int = 168, price: float = 50000.0, vol: float = 1000.0
) -> list[list]:
    """
    1시간 캔들 데이터 생성 (7d = 168시간).

    Bithumb format: [timestamp, open, close, high, low, volume]

    Args:
        num_candles: 캔들 수 (기본 168 = 7일).
        price: 각 캔들의 close 가격.
        vol: 각 캔들의 volume.

    Returns:
        [[timestamp, open, close, high, low, volume], ...]
    """
    return [[i * 3600, price, price, price + 100, price - 100, vol] for i in range(num_candles)]


class MockCoinUniverse(CoinUniverse):
    """Test용 CoinUniverse 서브클래스: tick size 오버라이드."""

    def __init__(self, *args, **kwargs):
        """초기화."""
        super().__init__(*args, **kwargs)
        self._tick_overrides: dict[float, float] = {}

    def set_tick_override(self, price: float, tick: float) -> None:
        """특정 가격에 대한 tick size를 오버라이드한다."""
        self._tick_overrides[price] = tick

    def _passes_hard_cutoffs(
        self, coin: str, ticker: dict, rolling_vol: float
    ) -> tuple[bool, str | None]:
        """Hard cutoff을 통과하는지 검사한다 (tick size 오버라이드 적용)."""
        from strategy.coin_universe import _get_tick_size

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

        # 2. TICK-PRICE FILTER with override
        try:
            price = float(ticker.get("last", 0))
            if price <= 0:
                return False, "price <= 0"

            # Use override if available, else real function
            if price in self._tick_overrides:
                tick = self._tick_overrides[price]
            else:
                tick = _get_tick_size(price)

            tick_ratio = tick / price
            if tick_ratio > self.MAX_TICK_PRICE_RATIO:
                return False, f"tick_ratio {tick_ratio:.4f} > {self.MAX_TICK_PRICE_RATIO}"
        except (TypeError, ValueError):
            return False, "invalid price"

        # 3. VOLUME FILTER
        if rolling_vol < self.MIN_7D_ROLLING_VOLUME_KRW:
            return False, f"vol_7d {rolling_vol:.0f} < {self.MIN_7D_ROLLING_VOLUME_KRW}"

        return True, None


@pytest.mark.asyncio
async def test_refresh_returns_top_n_by_volume():
    """상위 top_n 코인을 거래량 기준으로 반환한다 (hard cutoff 통과)."""
    client = MagicMock()
    # Bid/ask spreads must be < 0.5% (< 0.005) to pass
    # Formula: spread = 1 - (bid / ask)
    # For <0.5% spread: bid/ask > 0.995 → bid = ask * 0.9951 (=0.3% spread)
    client.get_all_tickers = AsyncMock(
        return_value=_make_ticker_data(
            [
                ("BTC", 1_000_000_000, 50_000, 49_756, 50_000),  # spread ~0.3%
                ("ETH", 800_000_000, 3_000, 2_986, 3_000),  # spread ~0.3%
                ("XRP", 500_000_000, 1_500, 1_492_800, 1_500),  # spread ~0.3%
                ("SOL", 300_000_000, 150, 147, 150),  # spread ~2% (reject)
                ("DOGE", 100_000_000, 25, 24, 25),  # spread ~4% (reject)
            ]
        )
    )

    async def mock_get_candlestick(coin: str, interval: str):
        volumes = {
            "BTC": 1000,  # 50000 * 1000 * 168 = 8.4B > 100M
            "ETH": 2000,  # 3000 * 2000 * 168 = 1.008B > 100M
            "XRP": 5000,  # 1500 * 5000 * 168 = 1.26B > 100M
            "SOL": 10,  # 150 * 10 * 168 = 252K < 100M
            "DOGE": 5,  # 25 * 5 * 168 = 21K < 100M
        }
        price = {
            "BTC": 50_000,
            "ETH": 3_000,
            "XRP": 1_500,
            "SOL": 150,
            "DOGE": 25,
        }.get(coin, 1000)
        return _make_candlestick_data(168, price, volumes.get(coin, 1000))

    client.get_candlestick = AsyncMock(side_effect=mock_get_candlestick)

    universe = MockCoinUniverse(client, top_n=5, base_coins=[])
    # Override ticks to allow these prices to pass (all at ~0.5% ratio)
    universe.set_tick_override(50_000, 250)  # 250/50000 = 0.5% OK
    universe.set_tick_override(3_000, 15)  # 15/3000 = 0.5% OK
    universe.set_tick_override(1_500, 7.5)  # 7.5/1500 = 0.5% OK
    universe.set_tick_override(150, 0.75)  # 0.75/150 = 0.5% OK (but spread fails)
    universe.set_tick_override(25, 0.125)  # 0.125/25 = 0.5% OK (but spread fails)

    result = await universe.refresh()

    # BTC, ETH, XRP pass all filters
    # SOL, DOGE fail on spread
    assert "BTC" in result
    assert "ETH" in result
    assert "XRP" in result
    assert "SOL" not in result
    assert "DOGE" not in result


@pytest.mark.asyncio
async def test_refresh_includes_base_coins():
    """base_coins는 항상 포함된다 (필터링 제외)."""
    client = MagicMock()
    client.get_all_tickers = AsyncMock(
        return_value=_make_ticker_data(
            [
                ("BTC", 1_000_000_000, 50_000, 49_756, 50_000),
                ("UNKNOWN", 10, 10, 5, 10),  # 매우 낮은 거래량
            ]
        )
    )
    client.get_candlestick = AsyncMock(return_value=_make_candlestick_data(168, 50000, 1000))

    universe = MockCoinUniverse(client, top_n=2, base_coins=["ETH", "XRP"])
    universe.set_tick_override(50_000, 250)
    universe.set_tick_override(10, 0.1)

    result = await universe.refresh()

    # base_coins는 필터링되지 않음 (universe에 포함)
    assert "ETH" in result
    assert "XRP" in result
    assert "BTC" in result


@pytest.mark.asyncio
async def test_refresh_api_failure_returns_base_coins():
    """API 실패 시 base_coins 안전망이 작동한다."""
    client = MagicMock()
    client.get_all_tickers = AsyncMock(return_value={})

    universe = MockCoinUniverse(client, top_n=5, base_coins=["BTC", "ETH"])

    result = await universe.refresh()

    # API 실패 → base_coins만 반환
    assert "BTC" in result
    assert "ETH" in result
    assert len(result) == 2


@pytest.mark.asyncio
async def test_refresh_excludes_stable_coins():
    """USDT, USDC 등 스테이블코인은 제외된다."""
    client = MagicMock()
    client.get_all_tickers = AsyncMock(
        return_value=_make_ticker_data(
            [
                ("USDT", 10_000_000_000, 1_000, 995, 1_000),
                ("USDC", 5_000_000_000, 1_000, 995, 1_000),
                ("BTC", 1_000_000_000, 50_000, 49_756, 50_000),
                ("ETH", 800_000_000, 3_000, 2_986, 3_000),
            ]
        )
    )

    async def mock_get_candlestick(coin: str, interval: str):
        return _make_candlestick_data(168, 50000 if coin == "BTC" else 3_000, 1000)

    client.get_candlestick = AsyncMock(side_effect=mock_get_candlestick)

    universe = MockCoinUniverse(client, top_n=4, base_coins=[])
    universe.set_tick_override(50_000, 250)
    universe.set_tick_override(3_000, 15)
    universe.set_tick_override(1_000, 5)

    result = await universe.refresh()

    assert "USDT" not in result
    assert "USDC" not in result
    assert "BTC" in result
    assert "ETH" in result


@pytest.mark.asyncio
async def test_hard_cutoff_spread_filter():
    """스프레드 > 0.5% 코인은 제외한다."""
    client = MagicMock()
    client.get_all_tickers = AsyncMock(
        return_value=_make_ticker_data(
            [
                ("GOOD", 1_000_000_000, 50_000, 49_756, 50_000),  # <0.5% spread
                ("BADSPREAD", 500_000_000, 100, 50, 101),  # ~50% spread
            ]
        )
    )

    async def mock_get_candlestick(coin: str, interval: str):
        price = 50_000 if coin == "GOOD" else 100
        return _make_candlestick_data(168, price, 1000)

    client.get_candlestick = AsyncMock(side_effect=mock_get_candlestick)

    universe = MockCoinUniverse(client, top_n=2, base_coins=[])
    universe.set_tick_override(50_000, 250)
    universe.set_tick_override(100, 1)

    result = await universe.refresh()

    assert "GOOD" in result
    assert "BADSPREAD" not in result
    assert "BADSPREAD" in universe.filtered_out
    assert "spread" in universe.filtered_out["BADSPREAD"]


@pytest.mark.asyncio
async def test_hard_cutoff_tick_price_ratio():
    """tick_ratio > 1% 코인은 제외한다 (극저가 코인)."""
    client = MagicMock()

    # GOODTICK at 50,000 KRW (will use override for 0.5% ratio)
    # BADTICK at 50 KRW (real tick = 1 KRW, ratio = 2% > 1% threshold → REJECT)
    ticker_data = {
        "GOODTICK": {
            "acc_trade_value_24H": "1000000000",
            "last": "50000",
            "bid": "49756",
            "ask": "50000",
        },
        "BADTICK": {
            "acc_trade_value_24H": "500000000",
            "last": "50",  # Price in 1-100 range: tick = 1 KRW → 1/50 = 2% > 1%
            "bid": "49",
            "ask": "50",
        },
    }

    client.get_all_tickers = AsyncMock(return_value=ticker_data)

    # Candlestick data returns appropriate price per coin
    async def mock_get_candlestick(coin: str, interval: str):
        if coin == "GOODTICK":
            return _make_candlestick_data(168, 50000, 1000)  # Price for GOODTICK
        else:
            return _make_candlestick_data(168, 50, 1000)  # Price for BADTICK

    client.get_candlestick = AsyncMock(side_effect=mock_get_candlestick)

    universe = MockCoinUniverse(client, top_n=2, base_coins=[])
    # GOODTICK gets override for good tick ratio (0.5%)
    universe.set_tick_override(50_000, 250)  # 250/50000 = 0.5%

    result = await universe.refresh()

    # GOODTICK passes: override gives 0.5% tick ratio, spread OK, volume OK
    # BADTICK fails: real tick at 50 KRW = 1 KRW, ratio = 2% > 1% threshold
    assert "GOODTICK" in result
    assert "BADTICK" not in result


@pytest.mark.asyncio
async def test_hard_cutoff_volume_filter():
    """7d rolling vol < 100M KRW 코인은 제외한다."""
    client = MagicMock()
    client.get_all_tickers = AsyncMock(
        return_value=_make_ticker_data(
            [
                ("HIGHVOL", 1_000_000_000, 50_000, 49_756, 50_000),
                ("LOWVOL", 500_000_000, 50_000, 49_756, 50_000),
            ]
        )
    )

    async def mock_get_candlestick(coin: str, interval: str):
        if coin == "HIGHVOL":
            return _make_candlestick_data(168, 50000, 1000)  # 8.4B > 100M
        else:
            return _make_candlestick_data(168, 50000, 5)  # 42M < 100M

    client.get_candlestick = AsyncMock(side_effect=mock_get_candlestick)

    universe = MockCoinUniverse(client, top_n=2, base_coins=[])
    universe.set_tick_override(50_000, 250)

    result = await universe.refresh()

    assert "HIGHVOL" in result
    assert "LOWVOL" not in result
    assert "LOWVOL" in universe.filtered_out
    assert "vol_7d" in universe.filtered_out["LOWVOL"]


@pytest.mark.asyncio
async def test_filtered_out_property():
    """filtered_out 프로퍼티는 제외된 코인 + 사유를 반환한다."""
    client = MagicMock()
    client.get_all_tickers = AsyncMock(
        return_value=_make_ticker_data(
            [
                ("BTC", 1_000_000_000, 50_000, 49_756, 50_000),
                ("REJECTED", 500_000_000, 100, 50, 101),  # Bad spread
            ]
        )
    )

    async def mock_get_candlestick(coin: str, interval: str):
        price = 50_000 if coin == "BTC" else 100
        return _make_candlestick_data(168, price, 1000)

    client.get_candlestick = AsyncMock(side_effect=mock_get_candlestick)

    universe = MockCoinUniverse(client, top_n=2, base_coins=[])
    universe.set_tick_override(50_000, 250)
    universe.set_tick_override(100, 1)

    await universe.refresh()

    assert "REJECTED" in universe.filtered_out
    assert "spread" in universe.filtered_out["REJECTED"]
