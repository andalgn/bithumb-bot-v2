"""고정 캔들에서 IndicatorPack을 계산하는 헬퍼."""
from __future__ import annotations

from app.data_types import Candle
from strategy.indicators import IndicatorPack, compute_indicators


def indicators_from_candles(candles: list[Candle]) -> IndicatorPack:
    """캔들 리스트로 IndicatorPack을 계산한다."""
    return compute_indicators(candles)
