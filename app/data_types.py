"""공통 데이터 타입 정의."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


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


@dataclass
class Candle:
    """캔들 데이터."""

    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float


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
