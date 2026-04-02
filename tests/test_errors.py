from unittest.mock import AsyncMock, MagicMock

import pytest

from app.errors import (
    APIAuthError,
    BotError,
    DataFetchError,
    InsufficientBalanceError,
    OrderTimeoutError,
    PositionLimitExceededError,
)


def test_exception_hierarchy():
    """모든 커스텀 예외가 BotError를 상속한다."""
    assert issubclass(InsufficientBalanceError, BotError)
    assert issubclass(OrderTimeoutError, BotError)
    assert issubclass(DataFetchError, BotError)
    assert issubclass(PositionLimitExceededError, BotError)
    assert issubclass(APIAuthError, BotError)


def test_bot_error_is_exception():
    assert issubclass(BotError, Exception)


def test_data_fetch_error_carries_symbol():
    err = DataFetchError("BTC", "캔들 조회 실패")
    assert "BTC" in str(err)
    assert err.symbol == "BTC"
    assert err.reason == "캔들 조회 실패"


def test_order_timeout_error_carries_ticket_id():
    err = OrderTimeoutError("ticket-123", "30초 초과")
    assert "ticket-123" in str(err)
    assert err.ticket_id == "ticket-123"


def test_api_auth_error():
    err = APIAuthError("API 키 만료")
    assert isinstance(err, BotError)
    assert "API 키 만료" in str(err)


def test_data_fetch_error_caught_as_bot_error():
    """DataFetchError가 BotError로 catch 가능하다 (복구 핸들러 설계 검증)."""
    with pytest.raises(BotError) as exc_info:
        raise DataFetchError("ETH", "타임아웃")
    assert exc_info.value.symbol == "ETH"


def test_api_auth_error_caught_separately_from_data_fetch():
    """APIAuthError와 DataFetchError는 별도 처리 가능하다."""
    errors = []
    for exc in [DataFetchError("BTC", ""), APIAuthError("키 만료")]:
        try:
            raise exc
        except APIAuthError:
            errors.append("auth")
        except DataFetchError:
            errors.append("data")
    assert errors == ["data", "auth"]


# ─── Raise-site tests ───


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 403])
async def test_bithumb_client_raises_api_auth_error_on_auth_failure(status_code: int) -> None:
    """_private_get이 401/403 응답 시 APIAuthError를 발생시킨다."""
    from market.bithumb_api import BithumbClient

    client = BithumbClient(api_key="dummy_key", api_secret="dummy_secret")

    mock_resp = MagicMock()
    mock_resp.status = status_code
    mock_resp.json = AsyncMock(
        return_value={"error": {"name": "unauthorized", "message": "인증 실패"}}
    )
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.closed = False
    client._session = mock_session

    with pytest.raises(APIAuthError) as exc_info:
        await client._private_get("/v1/accounts")

    assert str(status_code) in str(exc_info.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 403])
async def test_bithumb_client_post_raises_api_auth_error_on_auth_failure(status_code: int) -> None:
    """_private_post이 401/403 응답 시 APIAuthError를 발생시킨다."""
    from market.bithumb_api import BithumbClient

    client = BithumbClient(api_key="dummy_key", api_secret="dummy_secret")

    mock_resp = MagicMock()
    mock_resp.status = status_code
    mock_resp.json = AsyncMock(
        return_value={"error": {"name": "unauthorized", "message": "인증 실패"}}
    )
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.closed = False
    client._session = mock_session

    with pytest.raises(APIAuthError) as exc_info:
        await client._private_post("/v1/orders", {"market": "KRW-BTC"})

    assert str(status_code) in str(exc_info.value)
