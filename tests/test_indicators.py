"""기술적 지표 테스트."""

import numpy as np
import pytest

from app.data_types import Candle
from strategy.indicators import (
    calc_adx,
    calc_atr,
    calc_bollinger_bands,
    calc_ema,
    calc_macd,
    calc_obv,
    calc_rsi,
    calc_supertrend,
    calc_zscore,
    compute_indicators,
)


def _make_candles(closes: list[float], n: int = 0) -> list[Candle]:
    """테스트용 캔들 생성."""
    candles = []
    for i, c in enumerate(closes):
        candles.append(Candle(
            timestamp=1000 * (i + 1),
            open=c * 0.999,
            high=c * 1.01,
            low=c * 0.99,
            close=c,
            volume=1000.0,
        ))
    return candles


class TestEMA:
    """EMA 테스트."""

    def test_ema_basic(self) -> None:
        """EMA 기본 계산 검증."""
        data = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
        result = calc_ema(data, 3)
        # 첫 SMA = (1+2+3)/3 = 2.0
        assert result[2] == pytest.approx(2.0)
        # 나머지는 nan이 아님
        assert not np.isnan(result[-1])

    def test_ema_too_short(self) -> None:
        """데이터가 부족하면 전부 nan."""
        data = np.array([1.0, 2.0])
        result = calc_ema(data, 5)
        assert np.all(np.isnan(result))


class TestRSI:
    """RSI 테스트."""

    def test_rsi_rising(self) -> None:
        """상승장에서 RSI > 50."""
        closes = np.array([float(i) for i in range(1, 30)])
        rsi = calc_rsi(closes, 14)
        # 마지막 RSI는 높아야 함
        assert rsi[-1] > 50

    def test_rsi_falling(self) -> None:
        """하락장에서 RSI < 50."""
        closes = np.array([float(30 - i) for i in range(30)])
        rsi = calc_rsi(closes, 14)
        assert rsi[-1] < 50

    def test_rsi_range(self) -> None:
        """RSI는 0~100 범위."""
        closes = np.array([100.0 + i * (-1) ** i for i in range(50)])
        rsi = calc_rsi(closes, 14)
        valid = rsi[~np.isnan(rsi)]
        assert np.all(valid >= 0)
        assert np.all(valid <= 100)


class TestMACD:
    """MACD 테스트."""

    def test_macd_histogram(self) -> None:
        """MACD histogram = macd_line - signal_line."""
        closes = np.array([float(100 + i) for i in range(50)])
        result = calc_macd(closes, 12, 26, 9)
        # histogram 검증
        valid = ~np.isnan(result.histogram) & ~np.isnan(result.macd_line)
        idx = valid & ~np.isnan(result.signal_line)
        np.testing.assert_allclose(
            result.histogram[idx],
            result.macd_line[idx] - result.signal_line[idx],
            atol=1e-10,
        )


class TestATR:
    """ATR 테스트."""

    def test_atr_positive(self) -> None:
        """ATR은 항상 양수."""
        high = np.array([float(100 + i * 2) for i in range(30)])
        low = np.array([float(98 + i * 2) for i in range(30)])
        close = np.array([float(99 + i * 2) for i in range(30)])
        atr = calc_atr(high, low, close, 14)
        valid = atr[~np.isnan(atr)]
        assert len(valid) > 0
        assert np.all(valid > 0)


class TestADX:
    """ADX 테스트."""

    def test_adx_trending(self) -> None:
        """강한 추세에서 ADX가 계산되어야 함."""
        n = 100
        high = np.array([100.0 + i * 1.5 for i in range(n)])
        low = np.array([98.0 + i * 1.5 for i in range(n)])
        close = np.array([99.0 + i * 1.5 for i in range(n)])
        result = calc_adx(high, low, close, 14)
        valid_adx = result.adx[~np.isnan(result.adx)]
        assert len(valid_adx) > 0
        # 강한 추세이므로 마지막 ADX > 0
        assert valid_adx[-1] > 0


class TestBollingerBands:
    """볼린저 밴드 테스트."""

    def test_bb_order(self) -> None:
        """upper > middle > lower."""
        closes = np.array([float(100 + i % 5) for i in range(30)])
        bb = calc_bollinger_bands(closes, 20, 2.0)
        idx = ~np.isnan(bb.upper)
        assert np.all(bb.upper[idx] >= bb.middle[idx])
        assert np.all(bb.middle[idx] >= bb.lower[idx])


class TestOBV:
    """OBV 테스트."""

    def test_obv_rising(self) -> None:
        """가격 상승 시 OBV 증가."""
        closes = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        volume = np.array([100.0, 100.0, 100.0, 100.0, 100.0])
        obv = calc_obv(closes, volume)
        # 계속 상승이므로 OBV는 단조증가
        assert obv[-1] > obv[0]


class TestZScore:
    """Z-score 테스트."""

    def test_zscore_at_mean(self) -> None:
        """평균에서 Z-score ≈ 0."""
        closes = np.array([100.0] * 20 + [100.0])
        zscore = calc_zscore(closes, 20)
        assert zscore[-1] == pytest.approx(0.0)


class TestSuperTrend:
    """SuperTrend 테스트."""

    def test_supertrend_shape(self) -> None:
        """SuperTrend 결과 배열 길이가 입력과 같아야 함."""
        n = 30
        high = np.array([100.0 + i for i in range(n)])
        low = np.array([98.0 + i for i in range(n)])
        close = np.array([99.0 + i for i in range(n)])
        result = calc_supertrend(high, low, close, 10, 3.0)
        assert len(result.supertrend) == n
        assert len(result.direction) == n


class TestComputeIndicators:
    """compute_indicators 통합 테스트."""

    def test_all_indicators(self) -> None:
        """전체 지표가 계산되는지 확인."""
        closes = [100.0 + i * 0.5 * (-1) ** i for i in range(200)]
        candles = _make_candles(closes)
        pack = compute_indicators(candles)

        assert len(pack.rsi) == 200
        assert pack.macd is not None
        assert len(pack.atr) == 200
        assert pack.adx is not None
        assert pack.supertrend is not None
        assert len(pack.ema20) == 200
        assert pack.bb is not None
        assert len(pack.zscore) == 200

    def test_empty_candles(self) -> None:
        """빈 캔들 입력 시 빈 결과."""
        pack = compute_indicators([])
        assert len(pack.rsi) == 0
