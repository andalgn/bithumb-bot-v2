"""국면별 고정 캔들 시퀀스 팩토리.

각 함수는 해당 국면 판정을 확실하게 만드는 200봉 이상의 캔들을 반환한다.
(IndicatorPack 계산에 최소 200봉 필요)
"""
from __future__ import annotations

from app.data_types import Candle


def _make_candle(ts: int, price: float, volume: float = 1000.0) -> Candle:
    return Candle(
        timestamp=ts,
        open=price * 0.999,
        high=price * 1.002,
        low=price * 0.998,
        close=price,
        volume=volume,
    )


def strong_up_candles(count: int = 250) -> list[Candle]:
    """STRONG_UP 국면 캔들.

    강한 상승 추세: 매봉 0.3% 상승, 높은 거래량.
    EMA20 > EMA50 > EMA200, ADX > 25 조건 충족.
    """
    candles = []
    price = 50_000_000.0
    for i in range(count):
        price *= 1.003  # 0.3% 상승
        candles.append(_make_candle(i * 900_000, price, volume=5000.0 + i * 10))
    return candles


def weak_up_candles(count: int = 250) -> list[Candle]:
    """WEAK_UP 국면 캔들.

    약한 상승 추세: 매봉 0.08% 상승, 보통 거래량.
    EMA20 > EMA50, 20 ≤ ADX ≤ 25 조건 충족.
    """
    candles = []
    price = 50_000_000.0
    for i in range(count):
        price *= 1.0008
        candles.append(_make_candle(i * 900_000, price, volume=2000.0))
    return candles


def range_candles(count: int = 250) -> list[Candle]:
    """RANGE 국면 캔들.

    횡보: 가격이 좁은 범위에서 진동, ADX < 20.
    """
    import math
    candles = []
    base = 50_000_000.0
    for i in range(count):
        price = base + base * 0.01 * math.sin(i * 0.3)
        candles.append(_make_candle(i * 900_000, price, volume=1500.0))
    return candles


def weak_down_candles(count: int = 250) -> list[Candle]:
    """WEAK_DOWN 국면 캔들.

    약한 하락 추세: 매봉 0.08% 하락.
    EMA20 < EMA50, -DI > +DI 조건 충족.
    """
    candles = []
    price = 50_000_000.0
    for i in range(count):
        price *= 0.9992
        candles.append(_make_candle(i * 900_000, price, volume=2000.0))
    return candles


def crisis_candles(count: int = 250) -> list[Candle]:
    """CRISIS 국면 캔들.

    정상 횡보 후 마지막 24봉에서 급락 (-12%).
    ATR > ATR_avg × 2.5, 24h 변화 < -10% 조건 충족.
    """
    import math
    candles = []
    base = 50_000_000.0
    normal_count = count - 24
    # 정상 구간
    for i in range(normal_count):
        price = base + base * 0.005 * math.sin(i * 0.2)
        candles.append(_make_candle(i * 900_000, price, volume=1500.0))
    # 급락 구간 (변동성 크게 + 하락)
    crash_price = base
    for j in range(24):
        crash_price *= 0.9948  # 24봉 누적 -12%
        candles.append(
            Candle(
                timestamp=(normal_count + j) * 900_000,
                open=crash_price * 1.02,
                high=crash_price * 1.03,
                low=crash_price * 0.95,   # ATR 크게
                close=crash_price,
                volume=8000.0,
            )
        )
    return candles
