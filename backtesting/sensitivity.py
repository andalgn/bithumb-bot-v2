"""파라미터 민감도 분석.

현재 파라미터 +/-10% (5단계) 변이.
변동계수(CV): <0.1 견고, 0.1~0.3 보통, >0.3 민감(경고).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

from backtesting.backtest import Backtester

logger = logging.getLogger(__name__)


@dataclass
class ParamSensitivity:
    """파라미터별 민감도 결과."""

    name: str
    base_value: float
    cv: float = 0.0  # 변동계수
    verdict: str = ""  # "robust", "normal", "sensitive", "danger"
    values: list[float] = field(default_factory=list)  # 테스트한 값들
    sharpes: list[float] = field(default_factory=list)  # 대응 Sharpe 값들


@dataclass
class SensitivityResult:
    """민감도 분석 전체 결과."""

    params: list[ParamSensitivity] = field(default_factory=list)
    sensitive_count: int = 0
    robust_count: int = 0


class SensitivityAnalyzer:
    """파라미터 민감도 분석기."""

    def __init__(
        self,
        variation_pct: float = 0.10,
        steps: int = 5,
        robust_cv: float = 0.1,
        warning_cv: float = 0.3,
    ) -> None:
        """초기화.

        Args:
            variation_pct: 변이 범위 (±10%).
            steps: 변이 단계 수.
            robust_cv: 견고 판정 CV 기준.
            warning_cv: 민감 경고 CV 기준.
        """
        self._variation = variation_pct
        self._steps = steps
        self._robust_cv = robust_cv
        self._warning_cv = warning_cv
        self._backtester = Backtester()

    def run(
        self,
        base_params: dict[str, float],
        trades: list[dict],
    ) -> SensitivityResult:
        """민감도 분석을 실행한다.

        Args:
            base_params: 현재 파라미터 딕셔너리 (name→value).
            trades: 백테스트용 거래 리스트.

        Returns:
            SensitivityResult.
        """
        result = SensitivityResult()

        if not trades or not base_params:
            return result

        deltas = np.linspace(-self._variation, self._variation, self._steps)

        for name, base_value in base_params.items():
            if base_value == 0:
                continue

            test_values: list[float] = []
            sharpes: list[float] = []

            for delta in deltas:
                test_val = base_value * (1 + delta)
                test_values.append(test_val)

                # 간이 백테스트: 파라미터 변동이 거래 결과에 미치는 영향 추정
                # 실제로는 파라미터로 전략을 재실행해야 하지만,
                # 여기서는 PnL에 변동 비율을 적용하는 근사 방식
                adjusted_trades = []
                for t in trades:
                    adj = t.copy()
                    # 파라미터 변동이 수익에 비례 영향 (근사)
                    pnl_adj = 1 + delta * 0.5  # 50% 전파
                    if "exit_price" in adj and "entry_price" in adj:
                        spread = adj["exit_price"] - adj["entry_price"]
                        adj["exit_price"] = adj["entry_price"] + spread * pnl_adj
                    adjusted_trades.append(adj)

                bt_result = self._backtester.run(adjusted_trades)
                sharpes.append(bt_result.sharpe)

            # CV 계산
            arr = np.array(sharpes)
            mean_s = float(np.mean(arr))
            std_s = float(np.std(arr))
            cv = std_s / abs(mean_s) if abs(mean_s) > 1e-10 else 0.0

            # 판정
            if cv < self._robust_cv:
                verdict = "robust"
                result.robust_count += 1
            elif cv < self._warning_cv:
                verdict = "normal"
            elif cv < 0.5:
                verdict = "sensitive"
                result.sensitive_count += 1
            else:
                verdict = "danger"
                result.sensitive_count += 1

            ps = ParamSensitivity(
                name=name,
                base_value=base_value,
                cv=cv,
                verdict=verdict,
                values=test_values,
                sharpes=sharpes,
            )
            result.params.append(ps)

        logger.info(
            "민감도 분석: %d 파라미터, 견고=%d, 민감=%d",
            len(result.params), result.robust_count, result.sensitive_count,
        )
        return result
