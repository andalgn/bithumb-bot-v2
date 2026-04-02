"""CoinUniverse 단위 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from strategy.coin_universe import CoinUniverse


def _make_ticker_data(coins: list[tuple[str, float]]) -> dict:
    return {sym: {"acc_trade_value_24H": str(vol)} for sym, vol in coins}


@pytest.mark.asyncio
async def test_refresh_returns_top_n_by_volume():
    client = MagicMock()
    client.get_all_tickers = AsyncMock(
        return_value=_make_ticker_data(
            [
                ("BTC", 1_000_000_000),
                ("ETH", 800_000_000),
                ("XRP", 500_000_000),
                ("SOL", 300_000_000),
                ("DOGE", 100_000_000),
            ]
        )
    )
    universe = CoinUniverse(client, top_n=3, base_coins=[])
    result = await universe.refresh()
    assert result[:3] == ["BTC", "ETH", "XRP"]
    assert len(result) == 3


@pytest.mark.asyncio
async def test_refresh_includes_base_coins():
    client = MagicMock()
    client.get_all_tickers = AsyncMock(
        return_value=_make_ticker_data(
            [
                ("BTC", 1_000_000_000),
                ("ETH", 800_000_000),
                ("XRP", 500_000_000),
            ]
        )
    )
    universe = CoinUniverse(client, top_n=2, base_coins=["RENDER", "SOL"])
    result = await universe.refresh()
    assert "RENDER" in result
    assert "SOL" in result
    assert "BTC" in result


@pytest.mark.asyncio
async def test_refresh_api_failure_returns_base_coins():
    client = MagicMock()
    client.get_all_tickers = AsyncMock(return_value={})
    universe = CoinUniverse(client, top_n=5, base_coins=["BTC", "ETH"])
    result = await universe.refresh()
    assert set(result) == {"BTC", "ETH"}


@pytest.mark.asyncio
async def test_refresh_excludes_stable_coins():
    client = MagicMock()
    client.get_all_tickers = AsyncMock(
        return_value=_make_ticker_data(
            [
                ("BTC", 1_000_000_000),
                ("USDT", 999_000_000),
                ("USDC", 888_000_000),
                ("ETH", 800_000_000),
            ]
        )
    )
    universe = CoinUniverse(client, top_n=3, base_coins=[])
    result = await universe.refresh()
    assert "USDT" not in result
    assert "USDC" not in result
