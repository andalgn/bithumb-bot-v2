"""MomentumRanker — 코인 간 횡단면 모멘텀 점수 계산 및 순위 결정.

점수 = 0.4 × 7일수익률 + 0.3 × 3일수익률 - 0.2 × (변동성비율-1) + 0.1 × (RSI-50)/50
캔들 부족 코인은 최하위 배치.
"""

from __future__ import annotations

import logging

import numpy as np

from app.data_types import Candle

logger = logging.getLogger(__name__)

# 1H 캔들 기준 기간
_BARS_7D = 168
_BARS_3D = 72
_BARS_1D = 24
_MIN_BARS = 80


class MomentumRanker:
    """코인 간 횡단면 모멘텀 기반 순위 결정기."""

    def rank(self, candles_map: dict[str, list[Candle]]) -> list[str]:
        """코인을 모멘텀 점수 순서로 정렬하여 반환한다.

        Args:
            candles_map: {심볼: 1H 캔들 리스트} 딕셔너리.

        Returns:
            모멘텀 점수 내림차순 코인 목록. 캔들 부족 코인은 뒤로.
        """
        scores: dict[str, float] = {}
        insufficient: list[str] = []

        for symbol, candles in candles_map.items():
            if len(candles) < _MIN_BARS:
                insufficient.append(symbol)
                continue
            scores[symbol] = self._compute_raw_score(candles)

        if not scores:
            return list(candles_map.keys())

        ranked = sorted(scores.keys(), key=lambda s: scores[s], reverse=True)
        return ranked + insufficient

    def _compute_raw_score(self, candles: list[Candle]) -> float:
        """개별 코인의 모멘텀 raw 점수를 계산한다."""
        closes = np.array([c.close for c in candles], dtype=np.float64)
        n = len(closes)

        # 7일 수익률
        idx_7d = max(0, n - _BARS_7D - 1)
        ret_7d = (closes[-1] - closes[idx_7d]) / closes[idx_7d] if closes[idx_7d] > 0 else 0.0

        # 3일 수익률
        idx_3d = max(0, n - _BARS_3D - 1)
        ret_3d = (closes[-1] - closes[idx_3d]) / closes[idx_3d] if closes[idx_3d] > 0 else 0.0

        # 변동성 비율 (최근 24H / 이전): 낮을수록 유리
        recent = closes[-_BARS_1D:] if n >= _BARS_1D else closes
        historical = closes[-_BARS_7D:-_BARS_1D] if n >= _BARS_7D else closes[:-_BARS_1D]
        vol_recent = float(np.std(recent)) if len(recent) > 1 else 0.0
        vol_hist = float(np.std(historical)) if len(historical) > 1 else 1.0
        vol_ratio = vol_recent / vol_hist if vol_hist > 0 else 1.0

        # RSI 근사
        rsi_score = self._approx_rsi(closes[-14:]) if n >= 14 else 50.0

        score = 0.4 * ret_7d + 0.3 * ret_3d - 0.2 * (vol_ratio - 1.0) + 0.1 * (rsi_score - 50) / 50
        return float(score)

    def _approx_rsi(self, closes: np.ndarray) -> float:
        """RSI 근사값을 계산한다 (0~100)."""
        if len(closes) < 2:
            return 50.0
        diffs = np.diff(closes)
        gains = diffs[diffs > 0].mean() if (diffs > 0).any() else 0.0
        losses = -diffs[diffs < 0].mean() if (diffs < 0).any() else 0.0
        if losses == 0:
            return 100.0
        rs = gains / losses
        return float(100 - 100 / (1 + rs))
