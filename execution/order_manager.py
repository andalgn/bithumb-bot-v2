"""주문 상태 머신 (FSM) 모듈.

NEW → PLACED → PARTIAL → FILLED / CANCELED / FAILED / EXPIRED.
30초 타임아웃, 1초 폴링. PAPER 모드 즉시 체결 시뮬레이션.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
import uuid
from pathlib import Path

from app.data_types import OrderSide, OrderStatus, OrderTicket, RunMode
from market.bithumb_api import BithumbAPIError, BithumbClient
from market.normalizer import validate_order

logger = logging.getLogger(__name__)

MAX_TICKETS_MEMORY = 1000
MAX_TICKETS_TERMINAL = 100
ORDER_TIMEOUT_SEC = 30
POLL_INTERVAL_SEC = 1.0
MAX_RETRIES = 3
RETRY_BASE_MS = 500

TERMINAL_STATES = {
    OrderStatus.FILLED,
    OrderStatus.CANCELED,
    OrderStatus.FAILED,
    OrderStatus.EXPIRED,
}


class OrderManager:
    """주문 관리자."""

    def __init__(
        self,
        client: BithumbClient,
        run_mode: RunMode = RunMode.DRY,
        state_path: str | Path = "data/order_tickets.json",
        timeout_sec: int = ORDER_TIMEOUT_SEC,
        max_retries: int = MAX_RETRIES,
    ) -> None:
        """초기화.

        Args:
            client: 빗썸 API 클라이언트.
            run_mode: 운영 모드.
            state_path: 티켓 영속화 경로.
            timeout_sec: 주문 타임아웃(초).
            max_retries: 최대 재시도 횟수.
        """
        self._client = client
        self._run_mode = run_mode
        self._state_path = Path(state_path)
        self._timeout_sec = timeout_sec
        self._max_retries = max_retries
        self._tickets: dict[str, OrderTicket] = {}
        self._load_state()

    def _load_state(self) -> None:
        """저장된 티켓을 복원한다."""
        if not self._state_path.exists():
            return
        try:
            with open(self._state_path, encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                ticket = OrderTicket(
                    ticket_id=item["ticket_id"],
                    symbol=item["symbol"],
                    side=OrderSide(item["side"]),
                    price=item["price"],
                    qty=item["qty"],
                    status=OrderStatus(item["status"]),
                    exchange_order_id=item.get("exchange_order_id", ""),
                    filled_qty=item.get("filled_qty", 0),
                    filled_price=item.get("filled_price", 0),
                    created_at=item.get("created_at", 0),
                    updated_at=item.get("updated_at", 0),
                    retry_count=item.get("retry_count", 0),
                    error_msg=item.get("error_msg", ""),
                )
                self._tickets[ticket.ticket_id] = ticket
        except Exception:
            logger.exception("주문 티켓 로딩 실패")

    def _save_state(self) -> None:
        """티켓을 파일에 저장한다."""
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        items = []
        for t in self._tickets.values():
            items.append(
                {
                    "ticket_id": t.ticket_id,
                    "symbol": t.symbol,
                    "side": t.side.value,
                    "price": t.price,
                    "qty": t.qty,
                    "status": t.status.value,
                    "exchange_order_id": t.exchange_order_id,
                    "filled_qty": t.filled_qty,
                    "filled_price": t.filled_price,
                    "created_at": t.created_at,
                    "updated_at": t.updated_at,
                    "retry_count": t.retry_count,
                    "error_msg": t.error_msg,
                }
            )
        tmp_fd, tmp_path = tempfile.mkstemp(dir=str(self._state_path.parent), suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(items, f, indent=2)
            os.replace(tmp_path, self._state_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _cleanup_tickets(self) -> None:
        """티켓 메모리를 관리한다. 터미널 상태 100개, 전체 1000개."""
        terminal = [t for t in self._tickets.values() if t.status in TERMINAL_STATES]
        if len(terminal) > MAX_TICKETS_TERMINAL:
            terminal.sort(key=lambda t: t.updated_at)
            for t in terminal[: len(terminal) - MAX_TICKETS_TERMINAL]:
                del self._tickets[t.ticket_id]

        if len(self._tickets) > MAX_TICKETS_MEMORY:
            all_sorted = sorted(self._tickets.values(), key=lambda t: t.updated_at)
            for t in all_sorted[: len(all_sorted) - MAX_TICKETS_MEMORY]:
                if t.status in TERMINAL_STATES:
                    del self._tickets[t.ticket_id]

    def create_ticket(self, symbol: str, side: OrderSide, price: float, qty: float) -> OrderTicket:
        """주문 티켓을 생성한다.

        Args:
            symbol: 코인 심볼.
            side: 주문 방향.
            price: 주문 가격.
            qty: 주문 수량.

        Returns:
            생성된 OrderTicket.
        """
        now = int(time.time() * 1000)
        ticket = OrderTicket(
            ticket_id=str(uuid.uuid4())[:12],
            symbol=symbol,
            side=side,
            price=price,
            qty=qty,
            status=OrderStatus.NEW,
            created_at=now,
            updated_at=now,
        )
        self._tickets[ticket.ticket_id] = ticket
        self._cleanup_tickets()
        return ticket

    async def execute_order(self, ticket: OrderTicket) -> OrderTicket:
        """주문을 실행한다.

        Args:
            ticket: 주문 티켓.

        Returns:
            업데이트된 OrderTicket.
        """
        # DRY 모드: 아무것도 안 함
        if self._run_mode == RunMode.DRY:
            ticket.status = OrderStatus.FILLED
            ticket.filled_qty = ticket.qty
            ticket.filled_price = ticket.price
            ticket.updated_at = int(time.time() * 1000)
            logger.info(
                "[DRY] 주문 시뮬레이션: %s %s %.4f @ %.0f",
                ticket.side.value,
                ticket.symbol,
                ticket.qty,
                ticket.price,
            )
            self._save_state()
            return ticket

        # PAPER 모드: 즉시 체결
        if self._run_mode == RunMode.PAPER:
            ticket.status = OrderStatus.FILLED
            ticket.filled_qty = ticket.qty
            ticket.filled_price = ticket.price
            ticket.updated_at = int(time.time() * 1000)
            logger.info(
                "[PAPER] 가상 체결: %s %s %.4f @ %.0f",
                ticket.side.value,
                ticket.symbol,
                ticket.qty,
                ticket.price,
            )
            self._save_state()
            return ticket

        # LIVE 모드: 실제 주문
        return await self._execute_live(ticket)

    async def execute_with_price_check(
        self,
        ticket: OrderTicket,
        current_price: float,
        max_deviation: float = 0.003,
    ) -> OrderTicket:
        """가격 이탈 체크 후 주문을 실행한다.

        Args:
            ticket: 주문 티켓.
            current_price: 현재 시장가.
            max_deviation: 최대 가격 이탈률 (기본 0.3%).

        Returns:
            업데이트된 OrderTicket.
        """
        if ticket.price > 0 and current_price > 0:
            deviation = abs(current_price - ticket.price) / ticket.price
            if deviation > max_deviation:
                ticket.status = OrderStatus.FAILED
                ticket.error_msg = (
                    f"가격 이탈: {deviation:.2%} > {max_deviation:.2%}"
                    f" (신호가={ticket.price:.0f}, 현재={current_price:.0f})"
                )
                ticket.updated_at = int(time.time() * 1000)
                logger.warning("주문 포기 (가격 이탈): %s", ticket.error_msg)
                self._save_state()
                return ticket

        return await self.execute_order(ticket)

    async def _execute_live(self, ticket: OrderTicket) -> OrderTicket:
        """LIVE 모드에서 주문을 실행한다."""
        # 유효성 검증
        order = validate_order(ticket.symbol, ticket.price, ticket.qty, side=ticket.side.value)
        if not order.valid:
            ticket.status = OrderStatus.FAILED
            ticket.error_msg = order.reject_reason
            ticket.updated_at = int(time.time() * 1000)
            self._save_state()
            return ticket

        for attempt in range(self._max_retries):
            try:
                result = await self._client.place_order(
                    coin=ticket.symbol,
                    side=ticket.side.value,
                    price=ticket.price,
                    qty=ticket.qty,
                )
                ticket.exchange_order_id = str(result.get("uuid", ""))
                ticket.retry_count = attempt
                ticket.updated_at = int(time.time() * 1000)

                # v1 API: 즉시 체결 확인
                result_state = result.get("state", "wait")
                if result_state == "done":
                    ticket.status = OrderStatus.FILLED
                    ticket.filled_qty = float(result.get("executed_volume", ticket.qty))
                    ticket.filled_price = ticket.price
                    self._save_state()
                    return ticket

                ticket.status = OrderStatus.PLACED
                break
            except BithumbAPIError as e:
                ticket.error_msg = e.message
                if e.status_code in ("401", "403"):
                    ticket.status = OrderStatus.FAILED
                    ticket.updated_at = int(time.time() * 1000)
                    self._save_state()
                    raise
                if attempt < self._max_retries - 1:
                    delay = RETRY_BASE_MS * (2**attempt) / 1000
                    logger.warning(
                        "주문 재시도 %d/%d (%s): %.1f초 후",
                        attempt + 1,
                        self._max_retries,
                        e.message,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    ticket.status = OrderStatus.FAILED
                    ticket.updated_at = int(time.time() * 1000)
                    self._save_state()
                    return ticket

        # 폴링으로 체결 확인
        if ticket.status == OrderStatus.PLACED:
            ticket = await self._poll_order(ticket)

        self._save_state()
        return ticket

    async def _poll_order(self, ticket: OrderTicket) -> OrderTicket:
        """주문 체결을 폴링한다.

        Args:
            ticket: PLACED 상태의 주문 티켓.

        Returns:
            업데이트된 OrderTicket.
        """
        start = time.time()
        while time.time() - start < self._timeout_sec:
            try:
                detail = await self._client.get_order_detail(
                    ticket.symbol, ticket.exchange_order_id
                )
                state = detail.get("state", "")
                executed_vol = float(detail.get("executed_volume", 0))

                if state == "done":
                    ticket.status = OrderStatus.FILLED
                    ticket.filled_qty = executed_vol if executed_vol > 0 else ticket.qty
                    # 실제 체결가: trades에서 가중평균
                    trades = detail.get("trades", [])
                    if trades:
                        total_funds = sum(float(t.get("funds", 0)) for t in trades)
                        total_vol = sum(float(t.get("volume", 0)) for t in trades)
                        if total_vol > 0:
                            ticket.filled_price = total_funds / total_vol
                            ticket.filled_qty = total_vol
                    else:
                        ticket.filled_price = ticket.price
                    ticket.updated_at = int(time.time() * 1000)
                    return ticket

                elif state == "cancel":
                    ticket.status = OrderStatus.CANCELED
                    ticket.updated_at = int(time.time() * 1000)
                    return ticket

                elif executed_vol > 0:
                    # 부분 체결
                    ticket.status = OrderStatus.PARTIAL
                    ticket.filled_qty = executed_vol

            except Exception:
                logger.debug("주문 폴링 오류 (재시도 중)")

            await asyncio.sleep(POLL_INTERVAL_SEC)

        # 타임아웃 -> 미체결 취소
        logger.warning("주문 타임아웃 -> 취소 시도: %s", ticket.ticket_id)
        try:
            await self._client.cancel_order(
                ticket.symbol, ticket.exchange_order_id, ticket.side.value
            )
        except Exception:
            logger.debug("주문 취소 실패 (이미 체결된 경우)")

        # 취소 후 최종 상태 확인
        try:
            final = await self._client.get_order_detail(ticket.symbol, ticket.exchange_order_id)
            final_executed = float(final.get("executed_volume", 0))
            if final_executed > 0:
                ticket.status = OrderStatus.FILLED
                ticket.filled_qty = final_executed
                trades = final.get("trades", [])
                if trades:
                    total_funds = sum(float(t.get("funds", 0)) for t in trades)
                    total_vol = sum(float(t.get("volume", 0)) for t in trades)
                    if total_vol > 0:
                        ticket.filled_price = total_funds / total_vol
                else:
                    ticket.filled_price = ticket.price
            else:
                ticket.status = OrderStatus.EXPIRED
        except Exception:
            ticket.status = OrderStatus.EXPIRED

        ticket.updated_at = int(time.time() * 1000)
        return ticket

    async def cancel_order(self, ticket: OrderTicket) -> OrderTicket:
        """주문을 취소한다.

        Args:
            ticket: 취소할 주문 티켓.

        Returns:
            업데이트된 OrderTicket.
        """
        if ticket.status in TERMINAL_STATES:
            return ticket

        if self._run_mode in (RunMode.DRY, RunMode.PAPER):
            ticket.status = OrderStatus.CANCELED
            ticket.updated_at = int(time.time() * 1000)
            self._save_state()
            return ticket

        try:
            ticket.status = OrderStatus.CANCEL_REQUESTED
            await self._client.cancel_order(
                ticket.symbol, ticket.exchange_order_id, ticket.side.value
            )
            ticket.status = OrderStatus.CANCELED
        except Exception:
            logger.exception("주문 취소 실패: %s", ticket.ticket_id)
            ticket.status = OrderStatus.FAILED

        ticket.updated_at = int(time.time() * 1000)
        self._save_state()
        return ticket

    def get_active_tickets(self) -> list[OrderTicket]:
        """활성(비터미널) 티켓 목록을 반환한다."""
        return [t for t in self._tickets.values() if t.status not in TERMINAL_STATES]

    def get_ticket(self, ticket_id: str) -> OrderTicket | None:
        """티켓 ID로 티켓을 조회한다."""
        return self._tickets.get(ticket_id)
