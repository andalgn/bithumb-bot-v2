"""봇 핵심 컴포넌트 Protocol 인터페이스.

테스트 시 Mock으로 교체 가능하도록 런타임 의존성을 추상화한다.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.data_types import Candle, MarketSnapshot
from strategy.indicators import IndicatorPack


@runtime_checkable
class MarketDataProvider(Protocol):
    """캔들 + 오더북 데이터 제공."""

    async def get_candles(
        self, symbol: str, interval: str, limit: int
    ) -> list[Candle]:
        """캔들 리스트를 반환한다."""
        ...


@runtime_checkable
class OrderExecutor(Protocol):
    """주문 실행."""

    async def place_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        price: float,
    ) -> dict:
        """주문을 실행하고 응답을 반환한다."""
        ...


@runtime_checkable
class NotificationSender(Protocol):
    """알림 전송."""

    async def send(self, text: str, channel: str = "system") -> bool:
        """알림을 전송하고 성공 여부를 반환한다."""
        ...


@runtime_checkable
class StrategyInputProvider(Protocol):
    """RuleEngine 테스트용 — 고정된 IndicatorPack + MarketSnapshot 제공."""

    def get_indicators_15m(self, symbol: str) -> IndicatorPack:
        """15분봉 지표를 반환한다."""
        ...

    def get_indicators_1h(self, symbol: str) -> IndicatorPack:
        """1시간봉 지표를 반환한다."""
        ...

    def get_snapshot(self, symbol: str) -> MarketSnapshot:
        """시장 스냅샷을 반환한다."""
        ...
