"""MockOrderExecutor — OrderExecutor Protocol 구현체."""

from __future__ import annotations


class MockOrderExecutor:
    """주문을 기록하는 Mock. 실제 API 미호출."""

    def __init__(self) -> None:
        self.orders: list[dict] = []

    async def place_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        price: float,
    ) -> dict:
        """주문을 기록하고 성공 응답을 반환한다."""
        order = {"symbol": symbol, "side": side, "qty": qty, "price": price, "status": "filled"}
        self.orders.append(order)
        return order
