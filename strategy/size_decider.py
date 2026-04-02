"""SizeDecider — 포지션 사이즈 결정.

전략 점수와 그룹을 기반으로 FULL/PROBE/HOLD 버킷을 결정한다.
"""

from __future__ import annotations

from app.data_types import Strategy

# 전략 → 점수 그룹 매핑
STRATEGY_GROUP: dict[Strategy, int] = {
    Strategy.TREND_FOLLOW: 1,
    Strategy.MEAN_REVERSION: 1,
    Strategy.BREAKOUT: 2,
    Strategy.SCALPING: 2,
    Strategy.DCA: 3,
}


class SizeDecision:
    """Full / Probe / Hold 판정 상수."""

    FULL = "FULL"
    PROBE = "PROBE"
    HOLD = "HOLD"


class SizeDecider:
    """전략 점수 그룹별 컷오프 기반 사이즈 결정 담당."""

    def __init__(self, score_cutoff: object | None = None) -> None:
        """초기화.

        Args:
            score_cutoff: ScoreCutoffConfig 객체. None이면 기본값 사용.
        """
        self._score_cutoff = score_cutoff

    def decide(self, strategy: Strategy, score: float) -> str:
        """FULL / PROBE / HOLD 중 하나를 반환한다.

        Args:
            strategy: 전략 enum 값.
            score: 0~100 범위의 전략 점수.

        Returns:
            "FULL" / "PROBE" / "HOLD" 문자열.
        """
        group = STRATEGY_GROUP.get(strategy, 1)

        if self._score_cutoff:
            if group == 1:
                g = self._score_cutoff.group1  # type: ignore[union-attr]
            elif group == 2:
                g = self._score_cutoff.group2  # type: ignore[union-attr]
            else:
                g = self._score_cutoff.group3  # type: ignore[union-attr]
            full = g.full
            probe_min = g.probe_min
        else:
            # 기본값 (config.yaml과 동일)
            if group == 1:
                full, probe_min = 75, 60
            elif group == 2:
                full, probe_min = 80, 65
            else:
                full, probe_min = 75, 68

        if score >= full:
            return SizeDecision.FULL
        if score >= probe_min:
            return SizeDecision.PROBE
        return SizeDecision.HOLD
