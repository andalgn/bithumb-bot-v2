"""백테스트 검증 데몬.

별도 스레드에서 실행. 메인 루프에 영향 없음.
- Walk-Forward: 매일 00:30 KST
- Monte Carlo: 매주 일요일 01:00 KST
- 민감도 분석: 매주 일요일 01:30 KST
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.journal import Journal
from app.notify import TelegramNotifier
from backtesting.monte_carlo import MonteCarlo, MonteCarloResult
from backtesting.sensitivity import SensitivityAnalyzer, SensitivityResult
from backtesting.walk_forward import WalkForward, WalkForwardResult

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))


class BacktestDaemon:
    """백테스트 검증 데몬."""

    def __init__(
        self,
        journal: Journal,
        notifier: TelegramNotifier | None = None,
    ) -> None:
        """초기화.

        Args:
            journal: 거래 기록.
            notifier: 텔레그램 알림 (선택).
        """
        self._journal = journal
        self._notifier = notifier
        self._walk_forward = WalkForward()
        self._monte_carlo = MonteCarlo(iterations=1000)
        self._sensitivity = SensitivityAnalyzer()
        self._running = False

        # 마지막 실행 시각
        self._last_wf: str = ""
        self._last_mc: str = ""
        self._last_sens: str = ""

        # 최근 결과
        self.wf_result: WalkForwardResult | None = None
        self.mc_result: MonteCarloResult | None = None
        self.sens_result: SensitivityResult | None = None

    async def run(self) -> None:
        """데몬을 시작한다."""
        self._running = True
        logger.info("BacktestDaemon 시작")

        while self._running:
            try:
                now = datetime.now(KST)
                date_key = now.strftime("%Y-%m-%d")
                week_key = f"{date_key}-w"

                # Walk-Forward: 매일 00:30
                if now.hour == 0 and now.minute >= 30 and self._last_wf != date_key:
                    self._last_wf = date_key
                    await self._run_walk_forward()

                # Monte Carlo + 민감도: 매주 일요일 01:00~01:30
                if now.weekday() == 6:  # 일요일
                    if now.hour == 1 and now.minute >= 0 and self._last_mc != week_key:
                        self._last_mc = week_key
                        await self._run_monte_carlo()

                    if now.hour == 1 and now.minute >= 30 and self._last_sens != week_key:
                        self._last_sens = week_key
                        await self._run_sensitivity()
                        await self._send_weekly_report()

            except Exception:
                logger.exception("BacktestDaemon 오류")

            await asyncio.sleep(60)

    async def stop(self) -> None:
        """데몬을 중지한다."""
        self._running = False

    async def _run_walk_forward(self) -> None:
        """Walk-Forward를 실행한다."""
        logger.info("Walk-Forward 검증 시작")
        trades = self._journal.get_recent_trades(limit=200)
        if not trades:
            logger.info("Walk-Forward: 거래 데이터 없음, 건너뜀")
            return

        wf_trades = []
        for i, t in enumerate(reversed(trades)):
            wf_trades.append({
                "entry_price": t.get("entry_price", 0) or 0,
                "exit_price": t.get("exit_price", 0) or 0,
                "qty": t.get("qty", 0) or 0,
                "day": i // 10,
            })

        self.wf_result = self._walk_forward.run(wf_trades)

        if self._notifier:
            msg = (
                f"<b>Walk-Forward</b>: {self.wf_result.pass_count}/"
                f"{self.wf_result.total_segments} -> {self.wf_result.verdict}"
            )
            await self._notifier.send(msg)

    async def _run_monte_carlo(self) -> None:
        """Monte Carlo를 실행한다."""
        logger.info("Monte Carlo 시뮬레이션 시작")
        trades = self._journal.get_recent_trades(limit=200)
        if not trades:
            return

        pnl_list = [
            t.get("net_pnl_krw", 0) or 0
            for t in trades
            if t.get("net_pnl_krw") is not None
        ]

        if not pnl_list:
            return

        self.mc_result = self._monte_carlo.run(pnl_list)

    async def _run_sensitivity(self) -> None:
        """민감도 분석을 실행한다."""
        logger.info("민감도 분석 시작")
        trades = self._journal.get_recent_trades(limit=200)
        if not trades:
            return

        bt_trades = []
        for t in reversed(trades):
            bt_trades.append({
                "entry_price": t.get("entry_price", 0) or 0,
                "exit_price": t.get("exit_price", 0) or 0,
                "qty": t.get("qty", 0) or 0,
            })

        base_params = {
            "rsi_lower": 30.0,
            "rsi_upper": 70.0,
            "atr_mult": 2.0,
            "cutoff": 72.0,
            "tp_pct": 0.03,
            "sl_pct": 0.02,
        }

        self.sens_result = self._sensitivity.run(base_params, bt_trades)

    async def _send_weekly_report(self) -> None:
        """주간 통합 검증 리포트를 전송한다."""
        if not self._notifier:
            return

        lines = ["<b>주간 검증 리포트</b>", "=" * 20]

        # Walk-Forward
        if self.wf_result:
            wf = self.wf_result
            lines.append(
                f"[Walk-Forward] {wf.pass_count}/{wf.total_segments} -> {wf.verdict}"
            )

        # Monte Carlo
        if self.mc_result:
            mc = self.mc_result
            lines.append(
                f"[Monte Carlo] P5={mc.pnl_percentile_5:.0f},"
                f" MDD={mc.worst_mdd:.1%} -> {mc.verdict}"
            )

        # 민감도
        if self.sens_result:
            sens = self.sens_result
            param_summary = []
            for p in sens.params:
                icon = ""
                if p.verdict == "sensitive" or p.verdict == "danger":
                    icon = " (!)"
                param_summary.append(f"{p.name}:{p.verdict}{icon}")
            lines.append(f"[민감도] {', '.join(param_summary)}")

        lines.append("=" * 20)
        await self._notifier.send("\n".join(lines))

    async def run_all_now(self) -> None:
        """즉시 전체 검증을 실행한다 (테스트용)."""
        await self._run_walk_forward()
        await self._run_monte_carlo()
        await self._run_sensitivity()
