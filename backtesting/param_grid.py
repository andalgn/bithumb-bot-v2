"""파라미터 그리드 정의.

전략별 최적화 대상 파라미터와 탐색 범위.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product


@dataclass
class ParamRange:
    """파라미터 탐색 범위."""

    name: str
    values: list[float]


@dataclass
class StrategyParamGrid:
    """전략별 파라미터 그리드."""

    strategy: str
    params: list[ParamRange] = field(default_factory=list)

    def combinations(self) -> list[dict[str, float]]:
        """모든 파라미터 조합을 생성한다."""
        if not self.params:
            return [{}]
        names = [p.name for p in self.params]
        values = [p.values for p in self.params]
        return [dict(zip(names, combo)) for combo in product(*values)]


def build_grids() -> dict[str, StrategyParamGrid]:
    """전략별 파라미터 그리드를 생성한다."""
    grids = {}

    # 전략 A: 추세추종 (5 x 6 x 4 = 120)
    grids["trend_follow"] = StrategyParamGrid(
        strategy="trend_follow",
        params=[
            ParamRange("sl_mult", [1.0, 1.5, 2.0, 2.5, 3.0]),
            ParamRange("tp_rr", [1.5, 2.0, 2.5, 3.0, 3.5, 4.0]),
            ParamRange("cutoff_full", [70, 75, 80, 85]),
        ],
    )

    # 전략 B: 반전포착 (4 x 5 x 4 = 80)
    grids["mean_reversion"] = StrategyParamGrid(
        strategy="mean_reversion",
        params=[
            ParamRange("sl_mult", [1.0, 1.5, 2.0, 2.5]),
            ParamRange("tp_rr", [1.2, 1.6, 2.0, 2.4, 3.0]),
            ParamRange("cutoff_full", [70, 75, 80, 85]),
        ],
    )

    # 전략 C: 브레이크아웃 (5 x 5 x 4 = 100)
    grids["breakout"] = StrategyParamGrid(
        strategy="breakout",
        params=[
            ParamRange("sl_mult", [1.5, 2.0, 2.5, 3.0, 3.5]),
            ParamRange("tp_rr", [2.0, 2.5, 3.0, 4.0, 5.0]),
            ParamRange("cutoff_full", [75, 80, 85, 90]),
        ],
    )

    # 전략 D: 스캘핑 (5 x 5 = 25)
    grids["scalping"] = StrategyParamGrid(
        strategy="scalping",
        params=[
            ParamRange("sl_pct", [0.005, 0.008, 0.010, 0.012, 0.015]),
            ParamRange("tp_pct", [0.010, 0.015, 0.020, 0.025, 0.030]),
        ],
    )

    return grids
