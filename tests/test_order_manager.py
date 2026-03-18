"""주문 FSM 테스트."""

import pytest
import pytest_asyncio

from app.data_types import OrderSide, OrderStatus, RunMode
from execution.order_manager import OrderManager
from market.bithumb_api import BithumbClient


@pytest_asyncio.fixture
async def order_manager(tmp_path):
    """PAPER 모드 OrderManager."""
    client = BithumbClient(api_key="", api_secret="")
    om = OrderManager(
        client=client,
        run_mode=RunMode.PAPER,
        state_path=str(tmp_path / "tickets.json"),
    )
    yield om
    await client.close()


@pytest.mark.asyncio
async def test_paper_buy_fills_immediately(order_manager: OrderManager) -> None:
    """PAPER 모드에서 매수 → 즉시 체결."""
    ticket = order_manager.create_ticket("BTC", OrderSide.BUY, 50_000_000, 0.001)
    assert ticket.status == OrderStatus.NEW

    ticket = await order_manager.execute_order(ticket)
    assert ticket.status == OrderStatus.FILLED
    assert ticket.filled_qty == 0.001
    assert ticket.filled_price == 50_000_000


@pytest.mark.asyncio
async def test_paper_sell_fills_immediately(order_manager: OrderManager) -> None:
    """PAPER 모드에서 매도 → 즉시 체결."""
    ticket = order_manager.create_ticket("ETH", OrderSide.SELL, 3_000_000, 0.1)
    ticket = await order_manager.execute_order(ticket)
    assert ticket.status == OrderStatus.FILLED


@pytest.mark.asyncio
async def test_cancel_order(order_manager: OrderManager) -> None:
    """PAPER 모드에서 주문 취소."""
    ticket = order_manager.create_ticket("XRP", OrderSide.BUY, 1000, 100)
    ticket = await order_manager.cancel_order(ticket)
    assert ticket.status == OrderStatus.CANCELED


@pytest.mark.asyncio
async def test_active_tickets(order_manager: OrderManager) -> None:
    """활성 티켓 조회."""
    t1 = order_manager.create_ticket("BTC", OrderSide.BUY, 50_000_000, 0.001)
    order_manager.create_ticket("ETH", OrderSide.BUY, 3_000_000, 0.01)

    assert len(order_manager.get_active_tickets()) == 2

    await order_manager.execute_order(t1)
    assert len(order_manager.get_active_tickets()) == 1


@pytest.mark.asyncio
async def test_dry_mode(tmp_path) -> None:
    """DRY 모드에서도 시뮬레이션 체결."""
    client = BithumbClient(api_key="", api_secret="")
    om = OrderManager(
        client=client,
        run_mode=RunMode.DRY,
        state_path=str(tmp_path / "tickets.json"),
    )
    ticket = om.create_ticket("SOL", OrderSide.BUY, 200_000, 0.5)
    ticket = await om.execute_order(ticket)
    assert ticket.status == OrderStatus.FILLED
    await client.close()
