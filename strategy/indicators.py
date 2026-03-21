"""기술적 지표 계산 모듈.

numpy 기반. RSI, MACD, ATR, ADX, SuperTrend, EMA, OBV, BB, Z-score.
IndicatorPack dataclass로 15M + 1H 이중 계산 지원.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from app.data_types import Candle


@dataclass
class MACDResult:
    """MACD 계산 결과."""

    macd_line: NDArray
    signal_line: NDArray
    histogram: NDArray


@dataclass
class ADXResult:
    """ADX 계산 결과."""

    adx: NDArray
    plus_di: NDArray
    minus_di: NDArray


@dataclass
class BollingerBands:
    """볼린저 밴드 결과."""

    upper: NDArray
    middle: NDArray
    lower: NDArray


@dataclass
class SuperTrendResult:
    """SuperTrend 결과."""

    supertrend: NDArray
    direction: NDArray  # 1=상승, -1=하락


@dataclass
class IndicatorPack:
    """전체 지표 패키지."""

    rsi: NDArray = field(default_factory=lambda: np.array([]))
    macd: MACDResult | None = None
    atr: NDArray = field(default_factory=lambda: np.array([]))
    adx: ADXResult | None = None
    supertrend: SuperTrendResult | None = None
    ema20: NDArray = field(default_factory=lambda: np.array([]))
    ema50: NDArray = field(default_factory=lambda: np.array([]))
    ema200: NDArray = field(default_factory=lambda: np.array([]))
    obv: NDArray = field(default_factory=lambda: np.array([]))
    bb: BollingerBands | None = None
    zscore: NDArray = field(default_factory=lambda: np.array([]))


def _to_arrays(
    candles: list[Candle],
) -> tuple[NDArray, NDArray, NDArray, NDArray, NDArray]:
    """캔들 리스트를 numpy 배열로 변환한다.

    Returns:
        (open, high, low, close, volume) 배열 튜플.
    """
    o = np.array([c.open for c in candles], dtype=np.float64)
    h = np.array([c.high for c in candles], dtype=np.float64)
    lo = np.array([c.low for c in candles], dtype=np.float64)
    c = np.array([c.close for c in candles], dtype=np.float64)
    v = np.array([c.volume for c in candles], dtype=np.float64)
    return o, h, lo, c, v


def calc_ema(data: NDArray, period: int) -> NDArray:
    """EMA를 계산한다 (Wilder 방식이 아닌 표준 EMA).

    Args:
        data: 입력 데이터 배열.
        period: EMA 기간.

    Returns:
        EMA 배열.
    """
    if len(data) < period:
        return np.full_like(data, np.nan)

    result = np.full_like(data, np.nan)
    alpha = 2.0 / (period + 1)

    # 첫 SMA
    result[period - 1] = np.mean(data[:period])
    for i in range(period, len(data)):
        result[i] = data[i] * alpha + result[i - 1] * (1 - alpha)
    return result


def _wilder_smooth(data: NDArray, period: int) -> NDArray:
    """Wilder 스무딩을 적용한다.

    Args:
        data: 입력 데이터 배열.
        period: 스무딩 기간.

    Returns:
        스무딩된 배열.
    """
    if len(data) < period:
        return np.full_like(data, np.nan)

    result = np.full_like(data, np.nan)
    result[period - 1] = np.mean(data[:period])
    for i in range(period, len(data)):
        result[i] = (result[i - 1] * (period - 1) + data[i]) / period
    return result


def calc_rsi(close: NDArray, period: int = 14) -> NDArray:
    """RSI를 계산한다 (Wilder smoothing).

    Args:
        close: 종가 배열.
        period: RSI 기간.

    Returns:
        RSI 배열 (0~100).
    """
    if len(close) < period + 1:
        return np.full_like(close, np.nan)

    delta = np.diff(close)
    gains = np.where(delta > 0, delta, 0.0)
    losses = np.where(delta < 0, -delta, 0.0)

    avg_gain = _wilder_smooth(gains, period)
    avg_loss = _wilder_smooth(losses, period)

    with np.errstate(divide="ignore", invalid="ignore"):
        rs = np.where(avg_loss != 0, avg_gain / avg_loss, 100.0)
    rsi = 100.0 - 100.0 / (1.0 + rs)

    # delta보다 close가 1개 더 많으므로 앞에 nan 추가
    return np.concatenate([[np.nan], rsi])


def calc_macd(
    close: NDArray,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> MACDResult:
    """MACD를 계산한다.

    Args:
        close: 종가 배열.
        fast: 단기 EMA 기간.
        slow: 장기 EMA 기간.
        signal: 시그널 EMA 기간.

    Returns:
        MACDResult.
    """
    ema_fast = calc_ema(close, fast)
    ema_slow = calc_ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calc_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return MACDResult(macd_line=macd_line, signal_line=signal_line, histogram=histogram)


def calc_atr(
    high: NDArray, low: NDArray, close: NDArray, period: int = 14
) -> NDArray:
    """ATR을 계산한다 (Wilder smoothing).

    Args:
        high: 고가 배열.
        low: 저가 배열.
        close: 종가 배열.
        period: ATR 기간.

    Returns:
        ATR 배열.
    """
    if len(close) < 2:
        return np.full_like(close, np.nan)

    tr1 = high[1:] - low[1:]
    tr2 = np.abs(high[1:] - close[:-1])
    tr3 = np.abs(low[1:] - close[:-1])
    tr = np.maximum(tr1, np.maximum(tr2, tr3))

    atr = _wilder_smooth(tr, period)
    return np.concatenate([[np.nan], atr])


def calc_adx(
    high: NDArray, low: NDArray, close: NDArray, period: int = 14
) -> ADXResult:
    """ADX, +DI, -DI를 계산한다 (Wilder smoothing).

    Args:
        high: 고가 배열.
        low: 저가 배열.
        close: 종가 배열.
        period: ADX 기간.

    Returns:
        ADXResult.
    """
    n = len(close)
    plus_di = np.full(n, np.nan)
    minus_di = np.full(n, np.nan)
    adx = np.full(n, np.nan)

    if n < period * 2 + 1:
        return ADXResult(adx=adx, plus_di=plus_di, minus_di=minus_di)

    # +DM, -DM
    up_move = high[1:] - high[:-1]
    down_move = low[:-1] - low[1:]
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    # True Range
    tr = np.maximum(
        high[1:] - low[1:],
        np.maximum(
            np.abs(high[1:] - close[:-1]),
            np.abs(low[1:] - close[:-1]),
        ),
    )

    # Wilder smoothing
    sm_tr = _wilder_smooth(tr, period)
    sm_plus_dm = _wilder_smooth(plus_dm, period)
    sm_minus_dm = _wilder_smooth(minus_dm, period)

    # +DI, -DI
    with np.errstate(divide="ignore", invalid="ignore"):
        di_plus = np.where(sm_tr != 0, 100.0 * sm_plus_dm / sm_tr, 0.0)
        di_minus = np.where(sm_tr != 0, 100.0 * sm_minus_dm / sm_tr, 0.0)

    # DX
    di_sum = di_plus + di_minus
    with np.errstate(divide="ignore", invalid="ignore"):
        dx = np.where(di_sum != 0, 100.0 * np.abs(di_plus - di_minus) / di_sum, 0.0)

    # ADX = Wilder smoothing of DX (nan 구간 건너뛰기)
    # dx에서 첫 유효값 인덱스 찾기
    first_valid = 0
    for i in range(len(dx)):
        if not np.isnan(dx[i]):
            first_valid = i
            break

    adx_raw = np.full_like(dx, np.nan)
    valid_dx = dx[first_valid:]
    if len(valid_dx) >= period:
        smoothed = _wilder_smooth(valid_dx, period)
        adx_raw[first_valid:] = smoothed

    # 배열 길이 맞추기 (diff로 인해 1개 줄어듦)
    plus_di[1:] = di_plus
    minus_di[1:] = di_minus
    adx[1:] = adx_raw

    return ADXResult(adx=adx, plus_di=plus_di, minus_di=minus_di)


def calc_supertrend(
    high: NDArray, low: NDArray, close: NDArray,
    period: int = 10, multiplier: float = 3.0,
) -> SuperTrendResult:
    """SuperTrend를 계산한다.

    Args:
        high: 고가 배열.
        low: 저가 배열.
        close: 종가 배열.
        period: ATR 기간.
        multiplier: ATR 배수.

    Returns:
        SuperTrendResult.
    """
    n = len(close)
    atr = calc_atr(high, low, close, period)
    hl2 = (high + low) / 2.0

    upper_band = hl2 + multiplier * atr
    lower_band = hl2 - multiplier * atr

    supertrend = np.full(n, np.nan)
    direction = np.zeros(n, dtype=np.float64)

    # 첫 유효 인덱스 찾기
    first_valid = period
    if first_valid >= n:
        return SuperTrendResult(supertrend=supertrend, direction=direction)

    supertrend[first_valid] = upper_band[first_valid]
    direction[first_valid] = -1

    for i in range(first_valid + 1, n):
        if np.isnan(atr[i]):
            continue

        # upper band 조정
        if upper_band[i] < upper_band[i - 1] or close[i - 1] > upper_band[i - 1]:
            pass
        else:
            upper_band[i] = upper_band[i - 1]

        # lower band 조정
        if lower_band[i] > lower_band[i - 1] or close[i - 1] < lower_band[i - 1]:
            pass
        else:
            lower_band[i] = lower_band[i - 1]

        # direction & supertrend
        if direction[i - 1] == 1:  # 이전 상승
            if close[i] < lower_band[i]:
                direction[i] = -1
                supertrend[i] = upper_band[i]
            else:
                direction[i] = 1
                supertrend[i] = lower_band[i]
        else:  # 이전 하락
            if close[i] > upper_band[i]:
                direction[i] = 1
                supertrend[i] = lower_band[i]
            else:
                direction[i] = -1
                supertrend[i] = upper_band[i]

    return SuperTrendResult(supertrend=supertrend, direction=direction)


def calc_obv(close: NDArray, volume: NDArray) -> NDArray:
    """OBV(On-Balance Volume)를 계산한다.

    Args:
        close: 종가 배열.
        volume: 거래량 배열.

    Returns:
        OBV 배열.
    """
    if len(close) < 2:
        return np.zeros_like(close)

    obv = np.zeros(len(close))
    obv[0] = volume[0]
    for i in range(1, len(close)):
        if close[i] > close[i - 1]:
            obv[i] = obv[i - 1] + volume[i]
        elif close[i] < close[i - 1]:
            obv[i] = obv[i - 1] - volume[i]
        else:
            obv[i] = obv[i - 1]
    return obv


def calc_bollinger_bands(
    close: NDArray, period: int = 20, std_mult: float = 2.0
) -> BollingerBands:
    """볼린저 밴드를 계산한다.

    Args:
        close: 종가 배열.
        period: SMA 기간.
        std_mult: 표준편차 배수.

    Returns:
        BollingerBands.
    """
    n = len(close)
    middle = np.full(n, np.nan)
    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)

    for i in range(period - 1, n):
        window = close[i - period + 1 : i + 1]
        sma = np.mean(window)
        std = np.std(window, ddof=1)
        middle[i] = sma
        upper[i] = sma + std_mult * std
        lower[i] = sma - std_mult * std

    return BollingerBands(upper=upper, middle=middle, lower=lower)


def calc_zscore(close: NDArray, period: int = 20) -> NDArray:
    """Z-score를 계산한다.

    Args:
        close: 종가 배열.
        period: 룩백 기간.

    Returns:
        Z-score 배열.
    """
    n = len(close)
    zscore = np.full(n, np.nan)

    for i in range(period - 1, n):
        window = close[i - period + 1 : i + 1]
        mean = np.mean(window)
        std = np.std(window, ddof=1)
        if std > 0:
            zscore[i] = (close[i] - mean) / std
        else:
            zscore[i] = 0.0

    return zscore


def compute_indicators(candles: list[Candle]) -> IndicatorPack:
    """캔들 데이터에서 전체 지표를 계산한다.

    Args:
        candles: Candle 리스트 (시간순).

    Returns:
        IndicatorPack.
    """
    if len(candles) < 2:
        return IndicatorPack()

    _, high, low, close, volume = _to_arrays(candles)

    return IndicatorPack(
        rsi=calc_rsi(close, 14),
        macd=calc_macd(close, 12, 26, 9),
        atr=calc_atr(high, low, close, 14),
        adx=calc_adx(high, low, close, 14),
        supertrend=calc_supertrend(high, low, close, 10, 3.0),
        ema20=calc_ema(close, 20),
        ema50=calc_ema(close, 50),
        ema200=calc_ema(close, 200),
        obv=calc_obv(close, volume),
        bb=calc_bollinger_bands(close, 20, 2.0),
        zscore=calc_zscore(close, 20),
    )
