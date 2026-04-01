"""공통 데이터 타입 정의."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RunMode(str, Enum):
    """운영 모드."""

    DRY = "DRY"
    PAPER = "PAPER"
    LIVE = "LIVE"


class Regime(str, Enum):
    """시장 국면."""

    STRONG_UP = "STRONG_UP"
    WEAK_UP = "WEAK_UP"
    RANGE = "RANGE"
    WEAK_DOWN = "WEAK_DOWN"
    CRISIS = "CRISIS"


class Tier(int, Enum):
    """코인 Tier 분류."""

    TIER1 = 1
    TIER2 = 2
    TIER3 = 3


class Strategy(str, Enum):
    """전략 유형."""

    TREND_FOLLOW = "trend_follow"
    MEAN_REVERSION = "mean_reversion"
    BREAKOUT = "breakout"
    SCALPING = "scalping"
    DCA = "dca"


class Pool(str, Enum):
    """자금 풀 유형."""

    ACTIVE = "active"
    CORE = "core"
    RESERVE = "reserve"


class OrderStatus(str, Enum):
    """주문 상태."""

    NEW = "NEW"
    PLACED = "PLACED"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"


class OrderSide(str, Enum):
    """주문 방향."""

    BUY = "bid"
    SELL = "ask"


class ExitReason(str, Enum):
    """청산 사유."""

    TP = "tp"
    SL = "sl"
    TRAILING = "trailing"
    TIME = "time"
    REGIME = "regime"
    MANUAL = "manual"
    CRISIS = "crisis"
    DEMOTION = "demotion"


@dataclass
class Candle:
    """캔들 데이터."""

    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float


def parse_raw_candles(raw: list[Any]) -> list[Candle]:
    """빗썸 API 캔들 응답을 Candle 리스트로 변환한다.

    Args:
        raw: 빗썸 API 캔들 응답 리스트.

    Returns:
        Candle 리스트.
    """
    candles: list[Candle] = []
    for item in raw:
        try:
            candles.append(
                Candle(
                    timestamp=int(item[0]),
                    open=float(item[1]),
                    close=float(item[2]),
                    high=float(item[3]),
                    low=float(item[4]),
                    volume=float(item[5]),
                )
            )
        except (IndexError, ValueError, TypeError):
            continue
    return candles


@dataclass
class Ticker:
    """현재가 정보."""

    coin: str
    closing_price: float
    opening_price: float
    min_price: float
    max_price: float
    units_traded: float
    acc_trade_value: float
    prev_closing_price: float
    units_traded_24h: float
    fluctate_24h: float
    fluctate_rate_24h: float


@dataclass
class OrderbookEntry:
    """호가 항목."""

    price: float
    quantity: float


@dataclass
class Orderbook:
    """호가창 데이터."""

    timestamp: int
    bids: list[OrderbookEntry] = field(default_factory=list)
    asks: list[OrderbookEntry] = field(default_factory=list)

    @property
    def best_bid(self) -> float:
        """최우선 매수 호가."""
        return self.bids[0].price if self.bids else 0.0

    @property
    def best_ask(self) -> float:
        """최우선 매도 호가."""
        return self.asks[0].price if self.asks else 0.0

    @property
    def spread_pct(self) -> float:
        """스프레드 비율."""
        if self.best_bid <= 0:
            return 0.0
        return (self.best_ask - self.best_bid) / self.best_bid


@dataclass
class MarketSnapshot:
    """시장 스냅샷."""

    symbol: str
    current_price: float
    candles_5m: list[Candle] = field(default_factory=list)
    candles_15m: list[Candle] = field(default_factory=list)
    candles_1h: list[Candle] = field(default_factory=list)
    orderbook: Orderbook | None = None
    ticker: Ticker | None = None


@dataclass
class Signal:
    """매매 신호."""

    symbol: str
    direction: OrderSide
    strategy: Strategy
    score: float
    regime: Regime
    tier: Tier
    entry_price: float
    stop_loss: float
    take_profit: float
    timestamp: int = 0
    adv_krw: float = 0.0  # 일평균 거래대금 (슬리피지 동적 계산용)
    volatility: float = 0.0  # 일일 변동성 (슬리피지 동적 계산용)


@dataclass
class Position:
    """포지션 정보."""

    symbol: str
    entry_price: float
    entry_time: int
    size_krw: float
    qty: float
    stop_loss: float
    take_profit: float
    strategy: Strategy
    pool: Pool
    tier: Tier
    regime: Regime = Regime.RANGE
    promoted: bool = False
    entry_score: float = 0.0
    signal_price: float = 0.0
    entry_fee_krw: float = 0.0
    order_id: str = ""


@dataclass
class OrderTicket:
    """주문 티켓."""

    ticket_id: str
    symbol: str
    side: OrderSide
    price: float
    qty: float
    status: OrderStatus = OrderStatus.NEW
    exchange_order_id: str = ""
    filled_qty: float = 0.0
    filled_price: float = 0.0
    created_at: int = 0
    updated_at: int = 0
    retry_count: int = 0
    error_msg: str = ""
