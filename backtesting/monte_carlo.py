"""Monte Carlo 시뮬레이션.

최근 30일 거래를 1,000번 랜덤 셔플.
하위 5% PnL, 최악 MDD, Sharpe 분포 산출.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class MonteCarloResult:
    """Monte Carlo 결과."""

    iterations: int = 0
    pnl_percentile_5: float = 0.0
    pnl_percentile_50: float = 0.0
    pnl_percentile_95: float = 0.0
    worst_mdd: float = 0.0
    avg_mdd: float = 0.0
    sharpe_median: float = 0.0
    verdict: str = ""  # "safe", "caution", "danger"
    sizing_warning: bool = False


class MonteCarlo:
    """Monte Carlo 시뮬레이션."""

    def __init__(
        self,
        iterations: int = 1000,
        safe_pnl_positive: bool = True,
        danger_mdd_pct: float = 0.20,
    ) -> None:
        """초기화.

        Args:
            iterations: 시뮬레이션 횟수.
            safe_pnl_positive: 하위5% PnL > 0이면 "safe".
            danger_mdd_pct: MDD 위험 기준.
        """
        self._iterations = iterations
        self._safe_positive = safe_pnl_positive
        self._danger_mdd = danger_mdd_pct

    def run(
        self, pnl_list: list[float], initial_equity: float = 1_000_000
    ) -> MonteCarloResult:
        """Monte Carlo 시뮬레이션을 실행한다.

        Args:
            pnl_list: 거래별 net_pnl 리스트.
            initial_equity: 초기 자본.

        Returns:
            MonteCarloResult.
        """
        if not pnl_list:
            return MonteCarloResult(verdict="caution")

        final_pnls: list[float] = []
        mdds: list[float] = []
        sharpes: list[float] = []

        for _ in range(self._iterations):
            shuffled = pnl_list.copy()
            random.shuffle(shuffled)

            # 누적 에퀴티 커브
            equity = initial_equity
            peak = initial_equity
            max_dd = 0.0

            for pnl in shuffled:
                equity += pnl
                if equity > peak:
                    peak = equity
                dd = (peak - equity) / peak if peak > 0 else 0
                if dd > max_dd:
                    max_dd = dd

            final_pnl = equity - initial_equity
            final_pnls.append(final_pnl)
            mdds.append(max_dd)

            # Sharpe (간이)
            arr = np.array(shuffled)
            mean_r = float(np.mean(arr))
            std_r = float(np.std(arr))
            sharpe = mean_r / std_r if std_r > 0 else 0
            sharpes.append(sharpe)

        # 통계
        sorted_pnls = sorted(final_pnls)
        n = len(sorted_pnls)
        p5_idx = max(0, int(n * 0.05))
        p50_idx = int(n * 0.5)
        p95_idx = min(n - 1, int(n * 0.95))

        pnl_p5 = sorted_pnls[p5_idx]
        pnl_p50 = sorted_pnls[p50_idx]
        pnl_p95 = sorted_pnls[p95_idx]
        worst_mdd = max(mdds) if mdds else 0
        avg_mdd = float(np.mean(mdds)) if mdds else 0
        sharpe_med = float(np.median(sharpes)) if sharpes else 0

        # 판정
        sizing_warning = worst_mdd > self._danger_mdd
        if pnl_p5 > 0:
            verdict = "safe"
        elif pnl_p5 > -initial_equity * 0.03:
            verdict = "caution"
        else:
            verdict = "danger"

        result = MonteCarloResult(
            iterations=self._iterations,
            pnl_percentile_5=pnl_p5,
            pnl_percentile_50=pnl_p50,
            pnl_percentile_95=pnl_p95,
            worst_mdd=worst_mdd,
            avg_mdd=avg_mdd,
            sharpe_median=sharpe_med,
            verdict=verdict,
            sizing_warning=sizing_warning,
        )

        logger.info(
            "Monte Carlo: P5=%.0f, P50=%.0f, P95=%.0f, MDD=%.1f%% -> %s",
            pnl_p5, pnl_p50, pnl_p95, worst_mdd * 100, verdict,
        )
        return result
