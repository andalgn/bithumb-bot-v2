"""FrozenStrategyInput — StrategyInputProvider Protocol 구현체."""

from __future__ import annotations

from app.data_types import Candle, MarketSnapshot, Orderbook, OrderbookEntry
from strategy.indicators import IndicatorPack, compute_indicators


def _make_orderbook(mid_price: float, spread_pct: float = 0.001) -> Orderbook:
    half = mid_price * spread_pct / 2
    return Orderbook(
        timestamp=0,
        bids=[OrderbookEntry(price=mid_price - half, quantity=100.0)],
        asks=[OrderbookEntry(price=mid_price + half, quantity=100.0)],
    )


def _resample_to_1h(candles_15m: list[Candle]) -> list[Candle]:
    """15분봉 4개를 1시간봉 1개로 리샘플링한다."""
    result = []
    for i in range(0, len(candles_15m) - 3, 4):
        chunk = candles_15m[i : i + 4]
        result.append(
            Candle(
                timestamp=chunk[0].timestamp,
                open=chunk[0].open,
                high=max(c.high for c in chunk),
                low=min(c.low for c in chunk),
                close=chunk[-1].close,
                volume=sum(c.volume for c in chunk),
            )
        )
    return result


class FrozenStrategyInput:
    """고정 캔들로 초기화된 StrategyInputProvider.

    테스트에서 결정론적 입력을 보장한다.
    """

    def __init__(
        self,
        candles_15m: list[Candle],
        candles_1h: list[Candle] | None = None,
        symbol: str = "BTC",
        current_price: float | None = None,
        spread_pct: float = 0.001,
    ) -> None:
        self._symbol = symbol
        self._candles_15m = candles_15m
        # 1H 캔들이 없으면 15M의 4봉을 1봉으로 합산
        self._candles_1h = candles_1h or _resample_to_1h(candles_15m)
        self._price = current_price or candles_15m[-1].close
        self._spread_pct = spread_pct

    def get_indicators_15m(self, symbol: str) -> IndicatorPack:
        """15분봉 지표를 반환한다."""
        return compute_indicators(self._candles_15m)

    def get_indicators_1h(self, symbol: str) -> IndicatorPack:
        """1시간봉 지표를 반환한다."""
        return compute_indicators(self._candles_1h)

    def get_snapshot(self, symbol: str) -> MarketSnapshot:
        """시장 스냅샷을 반환한다."""
        return MarketSnapshot(
            symbol=self._symbol,
            current_price=self._price,
            candles_15m=self._candles_15m,
            candles_1h=self._candles_1h,
            orderbook=_make_orderbook(self._price, self._spread_pct),
        )
