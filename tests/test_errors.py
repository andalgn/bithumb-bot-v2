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
