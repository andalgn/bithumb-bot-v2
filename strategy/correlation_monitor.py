"""코인 간 상관관계 모니터링.

매일 00:00 KST: 10개 코인 간 20일 롤링 수익률 상관관계 매트릭스 계산.
진입 전 확인: 상관계수 > 0.85 → 스킵, 0.70~0.85 → 50% 축소, < 0.70 → 정상.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import numpy as np

from app.data_types import Candle

logger = logging.getLogger(__name__)

# 1일 = 24봉 (1H 기준)
BARS_PER_DAY = 24
ROLLING_DAYS = 20


@dataclass
class CorrelationResult:
    """상관관계 확인 결과."""

    allowed: bool = True
    size_mult: float = 1.0  # 사이즈 배수 (0.5 or 1.0)
    reason: str = ""
    max_corr: float = 0.0
    correlated_with: str = ""


class CorrelationMonitor:
    """코인 간 상관관계 모니터링."""

    def __init__(
        self,
        skip_threshold: float = 0.85,
        reduce_threshold_min: float = 0.70,
        reduce_threshold_max: float = 0.85,
        reduce_mult: float = 0.5,
    ) -> None:
        """초기화.

        Args:
            skip_threshold: 진입 스킵 상관계수 (이상).
            reduce_threshold_min: 사이즈 축소 하한.
            reduce_threshold_max: 사이즈 축소 상한.
            reduce_mult: 축소 배수.
        """
        self._skip = skip_threshold
        self._reduce_min = reduce_threshold_min
        self._reduce_max = reduce_threshold_max
        self._reduce_mult = reduce_mult

        # 상관관계 매트릭스 (코인 쌍별)
        self._corr_matrix: dict[str, dict[str, float]] = {}
        self._last_update: float = 0.0

    def update(self, candles_map: dict[str, list[Candle]]) -> None:
        """상관관계 매트릭스를 갱신한다.

        Args:
            candles_map: 코인별 1H 캔들 딕셔너리.
        """
        returns: dict[str, np.ndarray] = {}

        needed = ROLLING_DAYS * BARS_PER_DAY

        for sym, candles in candles_map.items():
            if len(candles) < needed:
                continue
            closes = np.array(
                [c.close for c in candles[-needed:]], dtype=np.float64
            )
            # 일일 수익률 (24봉 단위로 리샘플링)
            daily_closes = closes[::BARS_PER_DAY]
            if len(daily_closes) < 3:
                continue
            daily_returns = np.diff(daily_closes) / daily_closes[:-1]
            returns[sym] = daily_returns

        # 매트릭스 계산
        self._corr_matrix = {}
        valid_symbols = list(returns.keys())
        for i, s1 in enumerate(valid_symbols):
            self._corr_matrix.setdefault(s1, {})
            for j, s2 in enumerate(valid_symbols):
                if i == j:
                    self._corr_matrix[s1][s2] = 1.0
                    continue
                r1, r2 = returns[s1], returns[s2]
                min_len = min(len(r1), len(r2))
                if min_len < 3:
                    self._corr_matrix[s1][s2] = 0.0
                    continue
                corr = float(np.corrcoef(r1[-min_len:], r2[-min_len:])[0, 1])
                if np.isnan(corr):
                    corr = 0.0
                self._corr_matrix[s1][s2] = corr

        self._last_update = time.time()
        logger.info("상관관계 매트릭스 갱신 완료: %d개 코인", len(valid_symbols))

    def check_correlation(
        self, new_coin: str, active_positions: list[str]
    ) -> CorrelationResult:
        """진입 전 상관관계를 확인한다.

        Args:
            new_coin: 진입하려는 코인.
            active_positions: 현재 보유 중인 코인 목록.

        Returns:
            CorrelationResult.
        """
        if not active_positions:
            return CorrelationResult()

        if new_coin not in self._corr_matrix:
            return CorrelationResult()

        max_corr = 0.0
        correlated_with = ""

        for held_coin in active_positions:
            corr = self._corr_matrix.get(new_coin, {}).get(held_coin, 0.0)
            if abs(corr) > abs(max_corr):
                max_corr = corr
                correlated_with = held_coin

        # 판정
        if max_corr >= self._skip:
            return CorrelationResult(
                allowed=False,
                size_mult=0.0,
                reason=(
                    f"상관관계 {max_corr:.2f} > {self._skip}"
                    f" ({new_coin}↔{correlated_with})"
                ),
                max_corr=max_corr,
                correlated_with=correlated_with,
            )

        if max_corr >= self._reduce_min:
            return CorrelationResult(
                allowed=True,
                size_mult=self._reduce_mult,
                reason=(
                    f"상관관계 {max_corr:.2f} → 사이즈 {self._reduce_mult}배"
                    f" ({new_coin}↔{correlated_with})"
                ),
                max_corr=max_corr,
                correlated_with=correlated_with,
            )

        return CorrelationResult(max_corr=max_corr, correlated_with=correlated_with)

    def needs_update(self) -> bool:
        """갱신이 필요한지 확인한다 (24시간 경과)."""
        return time.time() - self._last_update > 86400

    def get_correlation(self, coin1: str, coin2: str) -> float:
        """두 코인 간 상관계수를 반환한다."""
        return self._corr_matrix.get(coin1, {}).get(coin2, 0.0)

    @property
    def matrix(self) -> dict[str, dict[str, float]]:
        """전체 상관관계 매트릭스를 반환한다."""
        return self._corr_matrix.copy()
