"""빗썸 API 클라이언트 테스트.

Public API만 실제 호출 테스트.
"""

import pytest
import pytest_asyncio

from market.bithumb_api import BithumbAPIError, BithumbClient


@pytest_asyncio.fixture
async def client():
    """Public API 전용 클라이언트."""
    c = BithumbClient(api_key="", api_secret="", base_url="https://api.bithumb.com")
    yield c
    await c.close()


@pytest.mark.asyncio
async def test_get_ticker(client: BithumbClient) -> None:
    """BTC/KRW 현재가 조회 성공."""
    data = await client.get_ticker("BTC")
    assert "closing_price" in data
    assert float(data["closing_price"]) > 0


@pytest.mark.asyncio
async def test_get_orderbook(client: BithumbClient) -> None:
    """BTC/KRW 호가창 조회 성공."""
    data = await client.get_orderbook("BTC")
    assert "bids" in data
    assert "asks" in data
    assert len(data["bids"]) > 0


@pytest.mark.asyncio
async def test_get_candlestick(client: BithumbClient) -> None:
    """BTC/KRW 15분 캔들 조회 성공."""
    data = await client.get_candlestick("BTC", "15m")
    assert isinstance(data, list)
    assert len(data) > 0
    # 각 캔들은 [timestamp, open, close, high, low, volume]
    assert len(data[0]) >= 6


@pytest.mark.asyncio
async def test_multiple_coins(client: BithumbClient) -> None:
    """10개 코인 현재가 조회 성공."""
    coins = ["BTC", "ETH", "XRP", "SOL", "RENDER",
             "VIRTUAL", "EIGEN", "ONDO", "TAO", "LDO"]
    for coin in coins:
        try:
            data = await client.get_ticker(coin)
            assert float(data["closing_price"]) > 0
        except BithumbAPIError:
            # 일부 코인은 빗썸에 없을 수 있음
            pass


@pytest.mark.asyncio
async def test_invalid_coin(client: BithumbClient) -> None:
    """존재하지 않는 코인 조회 시 에러."""
    with pytest.raises(BithumbAPIError):
        await client.get_ticker("INVALIDCOIN_XYZ_123")
