"""코인 프로파일러 — 자동 Tier 분류.

매일 00:00 KST 실행. 최근 14일 ATR% 기반으로 Tier 1/2/3 자동 분류.
Tier별 파라미터 세트 (RSI 범위, ATR 손절 배수, 포지션 배수) 반환.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import numpy as np

from app.data_types import Candle, Tier
from strategy.indicators import calc_atr

logger = logging.getLogger(__name__)

# 1일 = 24봉(1H 기준)
BARS_PER_DAY = 24
LOOKBACK_DAYS = 14


@dataclass
class TierParams:
    """Tier별 파라미터 세트."""

    tier: Tier
    atr_pct: float  # 계산된 ATR%
    position_mult: float  # 포지션 배수
    rsi_min: int  # RSI 하한
    rsi_max: int  # RSI 상한
    atr_stop_mult: float  # ATR 손절 배수
    spread_limit: float  # 스프레드 한도


# 기본 Tier 파라미터 (config에서 오버라이드 가능)
DEFAULT_TIER_PARAMS: dict[Tier, dict] = {
    Tier.TIER1: {
        "position_mult": 1.0,
        "rsi_min": 35,
        "rsi_max": 65,
        "atr_stop_mult": 2.5,
        "spread_limit": 0.0018,
    },
    Tier.TIER2: {
        "position_mult": 1.0,
        "rsi_min": 30,
        "rsi_max": 70,
        "atr_stop_mult": 2.0,
        "spread_limit": 0.0025,
    },
    Tier.TIER3: {
        "position_mult": 1.0,
        "rsi_min": 25,
        "rsi_max": 75,
        "atr_stop_mult": 1.5,
        "spread_limit": 0.0035,
    },
}


class CoinProfiler:
    """코인 프로파일러."""

    def __init__(
        self,
        tier1_atr_max: float = 0.009,
        tier3_atr_min: float = 0.014,
    ) -> None:
        """초기화.

        Args:
            tier1_atr_max: Tier 1 ATR% 상한.
            tier3_atr_min: Tier 3 ATR% 하한.
        """
        self._tier1_max = tier1_atr_max
        self._tier3_min = tier3_atr_min
        self._profiles: dict[str, TierParams] = {}
        self._last_update: float = 0.0

    def classify(self, symbol: str, candles_1h: list[Candle]) -> TierParams:
        """코인의 Tier를 분류한다.

        Args:
            symbol: 코인 심볼.
            candles_1h: 최근 1H 캔들 (최소 14일 = 336봉).

        Returns:
            TierParams.
        """
        atr_pct = self._calc_atr_pct(candles_1h)
        tier = self._classify_tier(atr_pct)
        defaults = DEFAULT_TIER_PARAMS[tier]

        params = TierParams(
            tier=tier,
            atr_pct=atr_pct,
            position_mult=defaults["position_mult"],
            rsi_min=defaults["rsi_min"],
            rsi_max=defaults["rsi_max"],
            atr_stop_mult=defaults["atr_stop_mult"],
            spread_limit=defaults["spread_limit"],
        )

        self._profiles[symbol] = params
        return params

    def classify_all(
        self, candles_map: dict[str, list[Candle]]
    ) -> dict[str, TierParams]:
        """전체 코인을 분류한다.

        Args:
            candles_map: 코인별 1H 캔들 딕셔너리.

        Returns:
            코인별 TierParams 딕셔너리.
        """
        for symbol, candles in candles_map.items():
            self.classify(symbol, candles)
        self._last_update = time.time()

        tier_summary = {}
        for t in Tier:
            coins = [s for s, p in self._profiles.items() if p.tier == t]
            if coins:
                tier_summary[t.name] = coins

        logger.info("Tier 분류 완료: %s", tier_summary)
        return self._profiles.copy()

    def get_tier(self, symbol: str) -> TierParams:
        """코인의 Tier 파라미터를 반환한다.

        Args:
            symbol: 코인 심볼.

        Returns:
            TierParams (미분류 시 기본 Tier 2).
        """
        if symbol in self._profiles:
            return self._profiles[symbol]
        return TierParams(
            tier=Tier.TIER2,
            atr_pct=0.05,
            **DEFAULT_TIER_PARAMS[Tier.TIER2],
        )

    def needs_update(self) -> bool:
        """갱신이 필요한지 확인한다 (24시간 경과)."""
        return time.time() - self._last_update > 86400

    def _calc_atr_pct(self, candles_1h: list[Candle]) -> float:
        """14일 평균 ATR%를 계산한다."""
        needed = LOOKBACK_DAYS * BARS_PER_DAY
        if len(candles_1h) < 30:
            return 0.05  # 기본값

        use_candles = candles_1h[-needed:] if len(candles_1h) >= needed else candles_1h

        high = np.array([c.high for c in use_candles], dtype=np.float64)
        low = np.array([c.low for c in use_candles], dtype=np.float64)
        close = np.array([c.close for c in use_candles], dtype=np.float64)

        atr = calc_atr(high, low, close, 14)
        valid_atr = atr[~np.isnan(atr)]
        if len(valid_atr) == 0 or close[-1] <= 0:
            return 0.05

        avg_atr = float(np.mean(valid_atr))
        avg_close = float(np.mean(close[~np.isnan(close)]))
        if avg_close <= 0:
            return 0.05

        return avg_atr / avg_close

    def _classify_tier(self, atr_pct: float) -> Tier:
        """ATR%로 Tier를 결정한다."""
        if atr_pct < self._tier1_max:
            return Tier.TIER1
        if atr_pct >= self._tier3_min:
            return Tier.TIER3
        return Tier.TIER2

    @property
    def profiles(self) -> dict[str, TierParams]:
        """전체 프로파일을 반환한다."""
        return self._profiles.copy()
