"""MockMarketData — MarketDataProvider Protocol 구현체."""

from __future__ import annotations

from app.data_types import Candle


class MockMarketData:
    """픽스처 캔들을 반환하는 Mock."""

    def __init__(self, candles: list[Candle] | None = None) -> None:
        self._candles = candles or []
        self.call_count = 0

    async def get_candles(self, symbol: str, interval: str, limit: int) -> list[Candle]:
        """고정 캔들을 반환한다."""
        self.call_count += 1
        return self._candles[-limit:] if limit else self._candles
