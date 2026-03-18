"""거래소-로컬 상태 동기화 모듈.

매 사이클 거래소 주문 상태 ↔ 로컬 상태 비교.
미지의 주문 감지 → manual_intervention 플래그.
"""

from __future__ import annotations

import logging

from app.data_types import OrderStatus, RunMode
from execution.order_manager import TERMINAL_STATES, OrderManager
from market.bithumb_api import BithumbClient

logger = logging.getLogger(__name__)


class Reconciler:
    """거래소-로컬 상태 동기화."""

    def __init__(
        self,
        client: BithumbClient,
        order_manager: OrderManager,
        run_mode: RunMode = RunMode.DRY,
    ) -> None:
        """초기화.

        Args:
            client: 빗썸 API 클라이언트.
            order_manager: 주문 관리자.
            run_mode: 운영 모드.
        """
        self._client = client
        self._order_manager = order_manager
        self._run_mode = run_mode
        self.manual_intervention_needed: bool = False
        self.unknown_orders: list[str] = []

    async def reconcile(self, coins: list[str]) -> dict[str, int]:
        """전체 코인의 주문 상태를 동기화한다.

        Args:
            coins: 동기화할 코인 목록.

        Returns:
            {"synced": 동기화 건수, "unknown": 미지 주문 건수}.
        """
        if self._run_mode in (RunMode.DRY, RunMode.PAPER):
            return {"synced": 0, "unknown": 0}

        synced = 0
        unknown = 0

        active_tickets = self._order_manager.get_active_tickets()
        if not active_tickets:
            return {"synced": 0, "unknown": 0}

        for ticket in active_tickets:
            if ticket.status in TERMINAL_STATES:
                continue

            try:
                detail = await self._client.get_order_detail(
                    ticket.symbol, ticket.exchange_order_id
                )
                order_status = detail.get("order_status", "")

                if order_status == "Completed":
                    ticket.status = OrderStatus.FILLED
                    contracts = detail.get("contract", [])
                    if contracts:
                        total_price = sum(
                            float(c.get("price", 0)) * float(c.get("units", 0))
                            for c in contracts
                        )
                        total_units = sum(
                            float(c.get("units", 0)) for c in contracts
                        )
                        if total_units > 0:
                            ticket.filled_price = total_price / total_units
                            ticket.filled_qty = total_units
                    synced += 1
                elif order_status == "Cancel":
                    ticket.status = OrderStatus.CANCELED
                    synced += 1
                # PARTIAL 등 다른 상태는 유지
            except Exception:
                logger.debug("동기화 실패: %s/%s", ticket.symbol, ticket.ticket_id)

        # 미지의 주문 감지는 LIVE에서만
        if self._run_mode == RunMode.LIVE:
            for coin in coins:
                try:
                    orders_data = await self._client.get_orders(coin)
                    if isinstance(orders_data, list):
                        exchange_ids = {
                            str(o.get("order_id", "")) for o in orders_data
                        }
                        local_ids = {
                            t.exchange_order_id
                            for t in active_tickets
                            if t.symbol == coin
                        }
                        unknown_ids = exchange_ids - local_ids - {""}
                        if unknown_ids:
                            unknown += len(unknown_ids)
                            self.unknown_orders.extend(unknown_ids)
                            logger.warning(
                                "미지의 주문 발견: %s — %s", coin, unknown_ids
                            )
                except Exception:
                    pass  # orders 조회 실패는 무시

        if unknown > 0:
            self.manual_intervention_needed = True

        return {"synced": synced, "unknown": unknown}
