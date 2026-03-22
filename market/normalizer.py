"""가격/수량 정규화 모듈.

코인별 소수점 자리수, tick_size, 최소 주문금액 검증.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# 빗썸 코인별 가격 tick_size 및 수량 소수점 규칙
# 가격대별 tick_size (KRW)
PRICE_TICK_RULES: list[tuple[float, float]] = [
    (2_000_000, 1000),  # 200만 이상: 1,000원 단위
    (1_000_000, 500),  # 100만~200만: 500원 단위
    (500_000, 100),  # 50만~100만: 100원 단위
    (100_000, 50),  # 10만~50만: 50원 단위
    (10_000, 10),  # 1만~10만: 10원 단위
    (1_000, 5),  # 1,000~1만: 5원 단위
    (100, 1),  # 100~1,000: 1원 단위
    (10, 0.1),  # 10~100: 0.1원 단위
    (1, 0.01),  # 1~10: 0.01원 단위
    (0, 0.001),  # 1원 미만: 0.001원 단위
]

# 코인별 수량 소수점 자리수
QTY_DECIMALS: dict[str, int] = {
    "BTC": 4,
    "ETH": 4,
    "XRP": 0,
    "SOL": 4,
    "RENDER": 2,
    "VIRTUAL": 2,
    "EIGEN": 2,
    "ONDO": 2,
    "TAO": 4,
    "LDO": 2,
}

MIN_ORDER_KRW = 5000


@dataclass
class NormalizedOrder:
    """정규화된 주문 정보."""

    coin: str
    price: float
    qty: float
    total_krw: float
    valid: bool
    reject_reason: str = ""


def get_tick_size(price: float) -> float:
    """가격에 해당하는 tick_size를 반환한다.

    Args:
        price: 현재 가격(KRW).

    Returns:
        해당 가격대의 tick_size.
    """
    for threshold, tick in PRICE_TICK_RULES:
        if price >= threshold:
            return tick
    return 0.001


def normalize_price(price: float, side: str = "bid") -> float:
    """가격을 tick_size에 맞게 정규화한다.

    Args:
        price: 원래 가격.
        side: bid(매수) → 내림(유리한 가격), ask(매도) → 올림(유리한 가격).

    Returns:
        정규화된 가격.
    """
    tick = get_tick_size(price)
    if tick >= 1:
        if side == "bid":
            return math.floor(price / tick) * tick
        return math.ceil(price / tick) * tick
    # 소수점 tick
    decimals = len(str(tick).rstrip("0").split(".")[-1])
    if side == "bid":
        return round(math.floor(price / tick) * tick, decimals)
    return round(math.ceil(price / tick) * tick, decimals)


def normalize_qty(coin: str, qty: float) -> float:
    """수량을 코인별 소수점 자리수에 맞게 내림 정규화한다.

    Args:
        coin: 코인 심볼.
        qty: 원래 수량.

    Returns:
        정규화된 수량.
    """
    decimals = QTY_DECIMALS.get(coin, 4)
    factor = 10**decimals
    return math.floor(qty * factor) / factor


def validate_order(coin: str, price: float, qty: float) -> NormalizedOrder:
    """주문을 정규화하고 유효성을 검증한다.

    Args:
        coin: 코인 심볼.
        price: 주문 가격.
        qty: 주문 수량.

    Returns:
        정규화된 주문 정보.
    """
    norm_price = normalize_price(price, side="bid")
    norm_qty = normalize_qty(coin, qty)
    total_krw = norm_price * norm_qty

    if norm_qty <= 0:
        return NormalizedOrder(
            coin=coin,
            price=norm_price,
            qty=0,
            total_krw=0,
            valid=False,
            reject_reason="수량이 0 이하",
        )

    if total_krw < MIN_ORDER_KRW:
        return NormalizedOrder(
            coin=coin,
            price=norm_price,
            qty=norm_qty,
            total_krw=total_krw,
            valid=False,
            reject_reason=f"최소 주문금액 {MIN_ORDER_KRW}원 미달 ({total_krw:.0f}원)",
        )

    return NormalizedOrder(
        coin=coin,
        price=norm_price,
        qty=norm_qty,
        total_krw=total_krw,
        valid=True,
    )
