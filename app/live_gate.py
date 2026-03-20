"""LIVE 승인 자동 검증 모듈.

LIVE_GATE.md 기반 9개 조건 자동 체크.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class LiveGateResult:
    """LIVE 게이트 검증 결과."""

    approved: bool = False
    checks: dict[str, bool] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)


class LiveGate:
    """LIVE 승인 자동 검증."""

    def __init__(
        self,
        min_paper_days: int = 28,
        min_trades: int = 120,
        max_mdd_pct: float = 0.08,
        max_daily_dd_pct: float = 0.035,
        min_uptime_pct: float = 0.99,
        slippage_error_pct: float = 0.25,
    ) -> None:
        """초기화.

        Args:
            min_paper_days: 최소 PAPER 운영 일수.
            min_trades: 최소 총 거래 수.
            max_mdd_pct: 최대 MDD 비율.
            max_daily_dd_pct: 최대 일일 DD 비율.
            min_uptime_pct: 최소 가동률.
            slippage_error_pct: 허용 슬리피지 모델 오차.
        """
        self._min_paper_days = min_paper_days
        self._min_trades = min_trades
        self._max_mdd = max_mdd_pct
        self._max_daily_dd = max_daily_dd_pct
        self._min_uptime = min_uptime_pct
        self._slippage_error = slippage_error_pct

    def evaluate(
        self,
        paper_days: int,
        total_trades: int,
        strategy_expectancy: dict[str, float],
        mdd_pct: float,
        max_daily_dd_pct: float,
        uptime_pct: float,
        unresolved_auth_errors: int,
        slippage_model_error_pct: float,
        wf_pass_count: int,
        wf_total: int,
        mc_p5_pnl: float,
    ) -> LiveGateResult:
        """9개 조건을 검증한다.

        Args:
            paper_days: PAPER 모드 운영 일수.
            total_trades: 총 거래 수.
            strategy_expectancy: 전략별 기대값 딕셔너리.
            mdd_pct: 최대 낙폭 비율.
            max_daily_dd_pct: 최대 일일 낙폭 비율.
            uptime_pct: 가동률.
            unresolved_auth_errors: 미해결 인증 오류 수.
            slippage_model_error_pct: 슬리피지 모델 오차 비율.
            wf_pass_count: Walk-Forward 통과 수.
            wf_total: Walk-Forward 총 수.
            mc_p5_pnl: Monte Carlo P5 PnL.

        Returns:
            LiveGateResult: 검증 결과.
        """
        checks: dict[str, bool] = {}
        failures: list[str] = []

        # 1. PAPER 일수
        checks["paper_days"] = paper_days >= self._min_paper_days
        if not checks["paper_days"]:
            failures.append(f"PAPER {paper_days}일 < {self._min_paper_days}일")

        # 2. 총 거래 수
        checks["total_trades"] = total_trades >= self._min_trades
        if not checks["total_trades"]:
            failures.append(f"거래 {total_trades}건 < {self._min_trades}건")

        # 3. 전략 Expectancy > 0
        neg_strats = [s for s, e in strategy_expectancy.items() if e <= 0]
        checks["expectancy"] = len(neg_strats) == 0
        if not checks["expectancy"]:
            failures.append(f"Expectancy<=0: {neg_strats}")

        # 4. MDD
        checks["mdd"] = mdd_pct < self._max_mdd
        if not checks["mdd"]:
            failures.append(f"MDD {mdd_pct:.1%} >= {self._max_mdd:.0%}")

        # 5. 일일 DD
        checks["daily_dd"] = max_daily_dd_pct < self._max_daily_dd
        if not checks["daily_dd"]:
            failures.append(f"일일DD {max_daily_dd_pct:.1%} >= {self._max_daily_dd:.1%}")

        # 6. 가동률
        checks["uptime"] = uptime_pct >= self._min_uptime
        if not checks["uptime"]:
            failures.append(f"가동률 {uptime_pct:.1%} < {self._min_uptime:.0%}")

        # 7. 인증 오류
        checks["auth_errors"] = unresolved_auth_errors == 0
        if not checks["auth_errors"]:
            failures.append(f"인증오류 {unresolved_auth_errors}건 미해결")

        # 8. 슬리피지 모델 오차
        checks["slippage"] = abs(slippage_model_error_pct) <= self._slippage_error
        if not checks["slippage"]:
            failures.append(
                f"슬리피지 오차 {slippage_model_error_pct:.0%} > "
                f"\u00b1{self._slippage_error:.0%}"
            )

        # 9. Walk-Forward
        wf_min = max(1, wf_total - 1)  # 4 중 3
        checks["walk_forward"] = wf_pass_count >= wf_min
        if not checks["walk_forward"]:
            failures.append(f"WF {wf_pass_count}/{wf_total} < {wf_min}/{wf_total}")

        # 10. Monte Carlo P5
        checks["monte_carlo"] = mc_p5_pnl > -0.02
        if not checks["monte_carlo"]:
            failures.append(f"MC P5 {mc_p5_pnl:.1%} <= -2%")

        approved = all(checks.values())
        return LiveGateResult(approved=approved, checks=checks, failures=failures)

    def format_report(self, result: LiveGateResult) -> str:
        """검증 결과를 텔레그램 메시지로 포맷한다.

        Args:
            result: LiveGateResult 검증 결과.

        Returns:
            포맷된 문자열.
        """
        status = "APPROVED" if result.approved else "NOT APPROVED"
        lines = [f"<b>[LIVE Gate] {status}</b>"]
        lines.append("")
        for name, passed in result.checks.items():
            mark = "V" if passed else "X"
            lines.append(f"  [{mark}] {name}")
        if result.failures:
            lines.append("")
            lines.append("<b>실패 사유:</b>")
            for f in result.failures:
                lines.append(f"  - {f}")
        return "\n".join(lines)
