"""정규화 모듈 테스트."""

from market.normalizer import (
    MIN_ORDER_KRW,
    get_tick_size,
    normalize_price,
    normalize_qty,
    validate_order,
)


class TestTickSize:
    """tick_size 테스트."""

    def test_btc_price(self) -> None:
        """BTC 가격대 (5천만원대) → tick 1000원."""
        assert get_tick_size(50_000_000) == 1000

    def test_xrp_price(self) -> None:
        """XRP 가격대 (1000원대) → tick 5원."""
        assert get_tick_size(1500) == 5

    def test_low_price(self) -> None:
        """저가 코인 (0.5원) → tick 0.001원."""
        assert get_tick_size(0.5) == 0.001


class TestNormalizePrice:
    """가격 정규화 테스트."""

    def test_bid_round_down(self) -> None:
        """매수(bid) → 내림(유리한 가격)."""
        assert normalize_price(50_000_500, "bid") == 50_000_000

    def test_ask_round_up(self) -> None:
        """매도(ask) → 올림(유리한 가격)."""
        assert normalize_price(50_000_999, "ask") == 50_001_000


class TestNormalizeQty:
    """수량 정규화 테스트."""

    def test_btc_4_decimals(self) -> None:
        """BTC → 소수점 4자리."""
        assert normalize_qty("BTC", 0.12345) == 0.1234

    def test_xrp_0_decimals(self) -> None:
        """XRP → 정수."""
        assert normalize_qty("XRP", 10.7) == 10


class TestValidateOrder:
    """주문 유효성 검증 테스트."""

    def test_valid_order(self) -> None:
        """유효한 주문."""
        order = validate_order("BTC", 50_000_000, 0.001)
        assert order.valid is True
        assert order.total_krw >= MIN_ORDER_KRW

    def test_below_min_order(self) -> None:
        """최소 주문금액 미달."""
        order = validate_order("ETH", 3_000_000, 0.001)
        assert order.valid is False
        assert "최소 주문금액" in order.reject_reason

    def test_zero_qty(self) -> None:
        """수량 0."""
        order = validate_order("BTC", 50_000_000, 0)
        assert order.valid is False
