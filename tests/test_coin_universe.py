"""CoinUniverse 단위 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from strategy.coin_universe import CoinUniverse


def _make_all_tickers_data(coins: list[tuple[str, float]]) -> dict:
    """
    get_all_tickers() 응답 데이터 생성 (24h 거래량만 포함).

    Args:
        coins: [(심볼, 24h_거래량), ...]

    Returns:
        {심볼: {acc_trade_value_24H}, ...}
    """
    return {
        sym: {
            "acc_trade_value_24H": str(vol_24h),
        }
        for sym, vol_24h in coins
    }


def _make_ticker_response(price: float, bid: float, ask: float) -> dict:
    """
    get_ticker(coin) 응답 데이터 생성 (가격 정보 포함).

    Args:
        price: closing_price
        bid: 매수가
        ask: 매도가

    Returns:
        {closing_price, bid, ask, ...}
    """
    return {
        "closing_price": str(price),
        "bid": str(bid),
        "ask": str(ask),
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
            price = float(ticker.get("closing_price", 0))
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
    # get_all_tickers: 24h 거래량 정보만 (top_n 선택 용)
    client.get_all_tickers = AsyncMock(
        return_value=_make_all_tickers_data(
            [
                ("BTC", 1_000_000_000),
                ("ETH", 800_000_000),
                ("XRP", 500_000_000),
                ("SOL", 300_000_000),
                ("DOGE", 100_000_000),
            ]
        )
    )

    # get_ticker: 개별 코인의 가격 정보
    async def mock_get_ticker(coin: str):
        tickers = {
            "BTC": _make_ticker_response(50_000, 49_756, 50_000),  # spread ~0.3%
            "ETH": _make_ticker_response(3_000, 2_986, 3_000),  # spread ~0.3%
            "XRP": _make_ticker_response(1_500, 1_492_800, 1_500),  # spread ~0.3%
            "SOL": _make_ticker_response(150, 147, 150),  # spread ~2% (reject)
            "DOGE": _make_ticker_response(25, 24, 25),  # spread ~4% (reject)
        }
        return tickers.get(coin, {})

    client.get_ticker = AsyncMock(side_effect=mock_get_ticker)

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
        return_value=_make_all_tickers_data(
            [
                ("BTC", 1_000_000_000),
                ("UNKNOWN", 10),
            ]
        )
    )

    async def mock_get_ticker(coin: str):
        tickers = {
            "BTC": _make_ticker_response(50_000, 49_756, 50_000),
            "UNKNOWN": _make_ticker_response(10, 5, 10),
            "ETH": _make_ticker_response(3_000, 2_986, 3_000),
            "XRP": _make_ticker_response(1_500, 1_492, 1_500),
        }
        return tickers.get(coin, {})

    client.get_ticker = AsyncMock(side_effect=mock_get_ticker)
    client.get_candlestick = AsyncMock(return_value=_make_candlestick_data(168, 50000, 1000))

    universe = MockCoinUniverse(client, top_n=2, base_coins=["ETH", "XRP"])
    universe.set_tick_override(50_000, 250)
    universe.set_tick_override(10, 0.1)
    universe.set_tick_override(3_000, 15)
    universe.set_tick_override(1_500, 7.5)

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
    client.get_ticker = AsyncMock(side_effect=Exception("API error"))

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
        return_value=_make_all_tickers_data(
            [
                ("USDT", 10_000_000_000),
                ("USDC", 5_000_000_000),
                ("BTC", 1_000_000_000),
                ("ETH", 800_000_000),
            ]
        )
    )

    async def mock_get_ticker(coin: str):
        tickers = {
            "USDT": _make_ticker_response(1_000, 995, 1_000),
            "USDC": _make_ticker_response(1_000, 995, 1_000),
            "BTC": _make_ticker_response(50_000, 49_756, 50_000),
            "ETH": _make_ticker_response(3_000, 2_986, 3_000),
        }
        return tickers.get(coin, {})

    client.get_ticker = AsyncMock(side_effect=mock_get_ticker)

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
        return_value=_make_all_tickers_data(
            [
                ("GOOD", 1_000_000_000),
                ("BADSPREAD", 500_000_000),
            ]
        )
    )

    async def mock_get_ticker(coin: str):
        tickers = {
            "GOOD": _make_ticker_response(50_000, 49_756, 50_000),  # <0.5% spread
            "BADSPREAD": _make_ticker_response(100, 50, 101),  # ~50% spread
        }
        return tickers.get(coin, {})

    client.get_ticker = AsyncMock(side_effect=mock_get_ticker)

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

    client.get_all_tickers = AsyncMock(
        return_value=_make_all_tickers_data(
            [
                ("GOODTICK", 1_000_000_000),
                ("BADTICK", 500_000_000),
            ]
        )
    )

    async def mock_get_ticker(coin: str):
        tickers = {
            "GOODTICK": _make_ticker_response(50_000, 49_756, 50_000),
            "BADTICK": _make_ticker_response(
                50, 49, 50
            ),  # Price in 1-100 range: tick = 1 KRW → 1/50 = 2% > 1%
        }
        return tickers.get(coin, {})

    client.get_ticker = AsyncMock(side_effect=mock_get_ticker)

    async def mock_get_candlestick(coin: str, interval: str):
        if coin == "GOODTICK":
            return _make_candlestick_data(168, 50000, 1000)
        else:
            return _make_candlestick_data(168, 50, 1000)

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
        return_value=_make_all_tickers_data(
            [
                ("HIGHVOL", 1_000_000_000),
                ("LOWVOL", 500_000_000),
            ]
        )
    )

    async def mock_get_ticker(coin: str):
        return _make_ticker_response(50_000, 49_756, 50_000)

    client.get_ticker = AsyncMock(side_effect=mock_get_ticker)

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
        return_value=_make_all_tickers_data(
            [
                ("BTC", 1_000_000_000),
                ("REJECTED", 500_000_000),
            ]
        )
    )

    async def mock_get_ticker(coin: str):
        tickers = {
            "BTC": _make_ticker_response(50_000, 49_756, 50_000),
            "REJECTED": _make_ticker_response(100, 50, 101),  # Bad spread
        }
        return tickers.get(coin, {})

    client.get_ticker = AsyncMock(side_effect=mock_get_ticker)

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


# ─── Phase 2: Tradeability Score Tests ───


class TestTradeabilityScore:
    """compute_tradeability_score 함수 테스트."""

    def test_high_quality_coin_scores_high(self) -> None:
        """우량 코인 (높은 거래량, 낮은 스프레드) → 높은 점수."""
        from strategy.coin_universe import compute_tradeability_score

        score = compute_tradeability_score(
            vol_7d=50_000_000_000,  # 500억
            spread_ratio=0.001,  # 0.1%
            tick_ratio=0.001,  # 0.1%
            volatility=0.03,  # 3% (최적 구간)
            vol_consistency=0.8,  # 일관적
        )
        assert score > 70

    def test_low_quality_coin_scores_low(self) -> None:
        """저품질 코인 (낮은 거래량, 높은 스프레드) → 낮은 점수."""
        from strategy.coin_universe import compute_tradeability_score

        score = compute_tradeability_score(
            vol_7d=200_000_000,  # 2억 (겨우 통과)
            spread_ratio=0.004,  # 0.4% (거의 한계)
            tick_ratio=0.008,  # 0.8% (거의 한계)
            volatility=0.10,  # 10% (너무 높음)
            vol_consistency=0.2,  # 불안정
        )
        assert score < 30

    def test_score_monotone_in_volume(self) -> None:
        """거래량 증가 → 점수 비감소."""
        from strategy.coin_universe import compute_tradeability_score

        kwargs = dict(spread_ratio=0.002, tick_ratio=0.003, volatility=0.03, vol_consistency=0.5)
        s1 = compute_tradeability_score(vol_7d=500_000_000, **kwargs)
        s2 = compute_tradeability_score(vol_7d=50_000_000_000, **kwargs)
        assert s2 >= s1

    def test_score_monotone_in_spread(self) -> None:
        """스프레드 감소 → 점수 비감소."""
        from strategy.coin_universe import compute_tradeability_score

        kwargs = dict(vol_7d=10_000_000_000, tick_ratio=0.003, volatility=0.03, vol_consistency=0.5)
        s_wide = compute_tradeability_score(spread_ratio=0.004, **kwargs)
        s_tight = compute_tradeability_score(spread_ratio=0.001, **kwargs)
        assert s_tight >= s_wide

    def test_volatility_sweet_spot(self) -> None:
        """2~5% 변동성이 최적 (mean_reversion 전략)."""
        from strategy.coin_universe import compute_tradeability_score

        kwargs = dict(
            vol_7d=10_000_000_000, spread_ratio=0.002, tick_ratio=0.003, vol_consistency=0.5
        )
        s_low = compute_tradeability_score(volatility=0.01, **kwargs)
        s_optimal = compute_tradeability_score(volatility=0.03, **kwargs)
        s_high = compute_tradeability_score(volatility=0.12, **kwargs)
        assert s_optimal > s_low
        assert s_optimal > s_high

    def test_score_range_0_to_100(self) -> None:
        """점수는 항상 0~100 범위."""
        from strategy.coin_universe import compute_tradeability_score

        # 최악
        s_min = compute_tradeability_score(0, 0.005, 0.01, 0.0, 0.0)
        # 최고
        s_max = compute_tradeability_score(1e12, 0.0, 0.0, 0.03, 1.0)
        assert 0 <= s_min <= 100
        assert 0 <= s_max <= 100


@pytest.mark.asyncio
async def test_refresh_with_scoring_ranks_by_score():
    """Phase 2: Hard cutoff 통과 후 점수 기반 순위 선정."""
    client = MagicMock()

    client.get_all_tickers = AsyncMock(
        return_value=_make_all_tickers_data(
            [
                ("COIN_A", 1_000_000_000),
                ("COIN_B", 800_000_000),
                ("COIN_C", 500_000_000),
            ]
        )
    )

    async def mock_get_ticker(coin: str):
        tickers = {
            "COIN_A": _make_ticker_response(50_000, 49_900, 50_000),  # 좁은 스프레드
            "COIN_B": _make_ticker_response(50_000, 49_800, 50_000),  # 적당한 스프레드
            "COIN_C": _make_ticker_response(50_000, 49_700, 50_000),  # 넓은 스프레드
        }
        return tickers.get(coin, {})

    client.get_ticker = AsyncMock(side_effect=mock_get_ticker)
    client.get_candlestick = AsyncMock(return_value=_make_candlestick_data(168, 50000, 1000))

    universe = MockCoinUniverse(client, top_n=3, base_coins=[], max_universe=2)
    universe.set_tick_override(50_000, 250)

    result = await universe.refresh()

    # 3개 중 점수 상위 2개만 선정
    assert len(result) <= 2
    # 점수가 기록됨
    assert len(universe.scores) > 0


@pytest.mark.asyncio
async def test_base_coins_bypass_score_limit():
    """base_coins는 점수 순위에 관계없이 포함."""
    client = MagicMock()

    client.get_all_tickers = AsyncMock(
        return_value=_make_all_tickers_data(
            [
                ("TOP1", 1_000_000_000),
                ("TOP2", 800_000_000),
            ]
        )
    )

    async def mock_get_ticker(coin: str):
        return _make_ticker_response(50_000, 49_900, 50_000)

    client.get_ticker = AsyncMock(side_effect=mock_get_ticker)
    client.get_candlestick = AsyncMock(return_value=_make_candlestick_data(168, 50000, 1000))

    universe = MockCoinUniverse(client, top_n=2, base_coins=["BASE_SAFE"], max_universe=1)
    universe.set_tick_override(50_000, 250)

    result = await universe.refresh()

    # max_universe=1 이지만 base_coins는 추가됨
    assert "BASE_SAFE" in result
