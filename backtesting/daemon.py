"""백테스트 검증 데몬.

별도 asyncio task로 실행. 메인 루프에 영향 없음.
config.yaml의 backtest 섹션에서 스케줄 읽음.

- 데이터 수집: 매일 (data_collect_time)
- Walk-Forward: 매일 (wf_time)
- Monte Carlo: 매주 (mc_day, mc_time)
- 민감도 분석: 매주 (mc_day, sens_time)
- 자동 최적화: 매주 (auto_optimize_day, auto_optimize_time)
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from app.config import BacktestConfig
from app.journal import Journal
from app.notify import Notifier
from backtesting.monte_carlo import MonteCarlo, MonteCarloResult
from backtesting.sensitivity import SensitivityAnalyzer, SensitivityResult
from backtesting.walk_forward import WalkForward, WalkForwardResult

if TYPE_CHECKING:
    from market.bithumb_api import BithumbClient
    from market.market_store import MarketStore

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))


class BacktestDaemon:
    """백테스트 검증 데몬."""

    def __init__(
        self,
        journal: Journal,
        notifier: Notifier | None = None,
        config: BacktestConfig | None = None,
        store: MarketStore | None = None,
        client: BithumbClient | None = None,
        coins: list[str] | None = None,
        deepseek_api_key: str = "",
    ) -> None:
        """초기화.

        Args:
            journal: 거래 기록.
            notifier: 알림 (선택).
            config: 백테스트 설정 (없으면 기본값).
            store: 시장 데이터 저장소 (선택, 데이터 수집/최적화용).
            client: 빗썸 API 클라이언트 (선택, 데이터 수집용).
            coins: 대상 코인 목록 (선택).
            deepseek_api_key: DeepSeek API 키 (자율 연구용).
        """
        self._journal = journal
        self._notifier = notifier
        self._config = config or BacktestConfig()
        self._store = store
        self._client = client
        self._coins = coins or []
        self._deepseek_key = deepseek_api_key
        self._running = False

        c = self._config
        self._walk_forward = WalkForward(
            data_days=c.wf_data_days,
            slide_days=c.wf_slide_days,
            num_segments=c.wf_segments,
            overfit_threshold=c.wf_overfit_diff_pct,
        )
        self._monte_carlo = MonteCarlo(
            iterations=c.mc_iterations,
            danger_mdd_pct=c.mc_danger_mdd_pct,
        )
        self._sensitivity = SensitivityAnalyzer(
            variation_pct=c.sens_variation_pct,
            steps=c.sens_steps,
        )

        # 마지막 실행 시각
        self._last_collect: str = ""
        self._last_wf: str = ""
        self._last_mc: str = ""
        self._last_sens: str = ""
        self._last_optimize: str = ""
        self._last_research: str = ""

        # 최근 결과
        self.wf_result: WalkForwardResult | None = None
        self.mc_result: MonteCarloResult | None = None
        self.sens_result: SensitivityResult | None = None
        self.optimize_result: dict[str, Any] | None = None

    async def run(self) -> None:
        """데몬을 시작한다."""
        self._running = True
        logger.info("BacktestDaemon 시작")

        c = self._config
        collect_h, collect_m = self._parse_time(c.data_collect_time)
        wf_h, wf_m = self._parse_time(c.wf_time)
        mc_h, mc_m = self._parse_time(c.mc_time)
        sens_h, sens_m = self._parse_time(c.sens_time)
        mc_weekday = self._parse_weekday(c.mc_day)
        opt_h, opt_m = self._parse_time(c.auto_optimize_time)
        opt_weekday = self._parse_weekday(c.auto_optimize_day)

        while self._running:
            try:
                now = datetime.now(KST)
                date_key = now.strftime("%Y-%m-%d")
                week_key = f"{date_key}-w"

                # 데이터 수집: 매일
                if (
                    now.hour == collect_h
                    and now.minute >= collect_m
                    and self._last_collect != date_key
                ):
                    self._last_collect = date_key
                    await self._collect_candles()

                # Walk-Forward: 매일
                if now.hour == wf_h and now.minute >= wf_m and self._last_wf != date_key:
                    self._last_wf = date_key
                    await self._run_walk_forward()

                # Monte Carlo + 민감도: 매주
                if now.weekday() == mc_weekday:
                    if now.hour == mc_h and now.minute >= mc_m and self._last_mc != week_key:
                        self._last_mc = week_key
                        await self._run_monte_carlo()

                    if now.hour == sens_h and now.minute >= sens_m and self._last_sens != week_key:
                        self._last_sens = week_key
                        await self._run_sensitivity()
                        await self._send_weekly_report()

                # 자동 최적화: 매주
                if (
                    c.auto_optimize_enabled
                    and now.weekday() == opt_weekday
                    and now.hour == opt_h
                    and now.minute >= opt_m
                    and self._last_optimize != week_key
                ):
                    self._last_optimize = week_key
                    await self._run_auto_optimize()

                # 자율 연구: 매주
                if c.auto_research_enabled:
                    research_h, research_m = self._parse_time(c.auto_research_time)
                    research_weekday = self._parse_weekday(c.auto_research_day)
                    if (
                        now.weekday() == research_weekday
                        and now.hour == research_h
                        and now.minute >= research_m
                        and self._last_research != week_key
                    ):
                        self._last_research = week_key
                        await self._run_auto_research()

            except Exception:
                logger.exception("BacktestDaemon 오류")

            await asyncio.sleep(60)

    async def stop(self) -> None:
        """데몬을 중지한다."""
        self._running = False

    # ═══════════════════════════════════════════
    # 데이터 수집
    # ═══════════════════════════════════════════

    async def _collect_candles(self) -> int:
        """최신 캔들 데이터를 수집한다. 수집한 봉 수를 반환."""
        if not self._store or not self._client:
            return 0

        from app.data_types import parse_raw_candles

        total = 0
        for coin in self._coins:
            for interval in ["15m", "1h"]:
                try:
                    raw = await self._client.get_candlestick(coin, interval)
                    candles = parse_raw_candles(raw)
                    stored = self._store.store_candles(coin, interval, candles)
                    total += stored
                except Exception:
                    logger.exception("캔들 수집 실패: %s %s", coin, interval)
                await asyncio.sleep(0.15)

        logger.info("캔들 데이터 수집 완료: %d건", total)
        return total

    # ═══════════════════════════════════════════
    # 검증 실행
    # ═══════════════════════════════════════════

    async def _run_walk_forward(self) -> None:
        """Walk-Forward를 실행한다."""
        logger.info("Walk-Forward 검증 시작")
        trades = self._journal.get_recent_trades(limit=200)
        if not trades:
            logger.info("Walk-Forward: 거래 데이터 없음, 건너뜀")
            return

        wf_trades = []
        for i, t in enumerate(reversed(trades)):
            wf_trades.append(
                {
                    "entry_price": t.get("entry_price", 0) or 0,
                    "exit_price": t.get("exit_price", 0) or 0,
                    "qty": t.get("qty", 0) or 0,
                    "day": i // 10,
                }
            )

        self.wf_result = self._walk_forward.run(wf_trades)

        if self._notifier:
            msg = (
                f"<b>Walk-Forward</b>: {self.wf_result.pass_count}/"
                f"{self.wf_result.total_segments} -> {self.wf_result.verdict}"
            )
            await self._notifier.send(msg, channel="backtest")

    async def _run_monte_carlo(self) -> None:
        """Monte Carlo를 실행한다."""
        logger.info("Monte Carlo 시뮬레이션 시작")
        trades = self._journal.get_recent_trades(limit=200)
        if not trades:
            return

        pnl_list = [
            t.get("net_pnl_krw", 0) or 0 for t in trades if t.get("net_pnl_krw") is not None
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
            bt_trades.append(
                {
                    "entry_price": t.get("entry_price", 0) or 0,
                    "exit_price": t.get("exit_price", 0) or 0,
                    "qty": t.get("qty", 0) or 0,
                }
            )

        base_params = {
            "rsi_lower": 30.0,
            "rsi_upper": 70.0,
            "atr_mult": 2.0,
            "cutoff": 72.0,
            "tp_pct": 0.03,
            "sl_pct": 0.02,
        }

        # 근사치 방식 사용: daemon은 journal 거래 데이터 기반이므로
        # replay_with_optimizer는 적용 불가 (entry 캐시 필요).
        # 정밀 분석은 scripts/optimize.py에서 수동 실행.
        self.sens_result = self._sensitivity.run(base_params, bt_trades)

    # ═══════════════════════════════════════════
    # 자동 파라미터 최적화
    # ═══════════════════════════════════════════

    async def _run_auto_optimize(self) -> dict | None:
        """자동 파라미터 최적화를 실행한다."""
        if not self._config.auto_optimize_enabled:
            return None
        if not self._store:
            return None

        logger.info("자동 파라미터 최적화 시작")

        from app.config import load_config
        from backtesting.optimizer import ParameterOptimizer
        from backtesting.param_grid import build_grids

        config = load_config()

        # 데이터 로딩
        candles_15m: dict[str, list] = {}
        candles_1h: dict[str, list] = {}
        for coin in self._coins:
            candles_15m[coin] = self._store.get_candles(coin, "15m", limit=5000)
            candles_1h[coin] = self._store.get_candles(coin, "1h", limit=5000)

        if not any(len(v) > 200 for v in candles_15m.values()):
            logger.warning("자동 최적화: 데이터 부족, 건너뜀")
            return None

        # rule_engine 로그 억제
        import logging as _logging

        _logging.getLogger("strategy.rule_engine").setLevel(_logging.WARNING)

        optimizer = ParameterOptimizer(self._coins, config)
        grids = build_grids()
        results: dict[str, dict] = {}

        for strategy, grid in grids.items():
            combos = grid.combinations()
            oos_list = optimizer.optimize(
                strategy,
                combos,
                candles_15m,
                candles_1h,
            )
            if not oos_list:
                continue
            best = max(oos_list, key=lambda r: r.profit_factor)
            results[strategy] = {
                "params": best.params,
                "pf": best.profit_factor,
                "trades": best.trades,
                "wr": best.win_rate,
            }
            logger.info(
                "최적화 %s: PF=%.2f WR=%.0f%% (%d건)",
                strategy,
                best.profit_factor,
                best.win_rate * 100,
                best.trades,
            )

        # 기준 충족 시 자동 적용 (현재 config 대비 개선된 경우만)
        config_path = Path("configs/config.yaml")
        applied = []
        # 현재 config로 baseline PF 계산
        current_trades = self._journal.get_recent_trades(limit=100)
        current_pf = self._calc_pf(current_trades) if current_trades else 0.0
        for strategy, r in results.items():
            if (
                r["pf"] >= self._config.auto_apply_min_pf
                and r["trades"] >= self._config.auto_apply_min_trades
                and r["pf"] > current_pf
            ):
                self._apply_optimized_params(strategy, r["params"], config_path)
                applied.append(f"{strategy}: PF={r['pf']:.2f} (현재={current_pf:.2f})")

        # 디스코드 알림
        if self._notifier:
            lines = ["<b>자동 최적화 완료</b>"]
            for s, r in results.items():
                lines.append(f"  {s}: PF={r['pf']:.2f} ({r['trades']}건)")
            if applied:
                lines.append(f"\n<b>자동 적용:</b> {', '.join(applied)}")
            else:
                lines.append("\n기준 미달 — 적용 없음")
            await self._notifier.send("\n".join(lines), channel="backtest")

        self.optimize_result = results
        return results

    async def _run_auto_research(self) -> None:
        """자율 연구 세션을 실행한다."""
        if not self._store:
            return
        logger.info("자율 연구 세션 시작")

        from strategy.auto_researcher import AutoResearcher

        researcher = AutoResearcher(
            store=self._store,
            coins=self._coins,
            deepseek_api_key=self._deepseek_key,
            max_experiments=self._config.auto_research_max_experiments,
            max_consecutive_failures=self._config.auto_research_max_failures,
        )
        results = await researcher.run_session()

        # KEEP된 최종 파라미터를 config에 적용
        kept = [r for r in results if r.verdict == "KEEP"]
        if kept:
            final_params: dict[str, float] = {}
            for r in kept:
                final_params.update(r.params_changed)
            config_path = Path("configs/config.yaml")
            self._apply_optimized_params(
                kept[-1].strategy,
                final_params,
                config_path,
            )

        # 디스코드 리포트
        if self._notifier and results:
            total = len(results)
            keep_count = len(kept)
            lines = [f"<b>자율 연구 완료</b> ({keep_count}/{total} 개선)"]
            for r in results:
                icon = "+" if r.verdict == "KEEP" else "-"
                lines.append(
                    f"  {icon} {r.params_changed} PF {r.baseline_pf:.2f}->{r.result_pf:.2f}"
                )
            await self._notifier.send("\n".join(lines), channel="backtest")

    def _apply_optimized_params(
        self,
        strategy: str,
        params: dict[str, float],
        config_path: Path,
    ) -> None:
        """최적 파라미터를 config.yaml에 백업 후 적용한다."""
        # 백업
        backup_path = config_path.with_suffix(
            f".yaml.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        shutil.copy2(config_path, backup_path)
        logger.info("config 백업: %s", backup_path)

        # 업데이트
        with open(config_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        sp = raw.setdefault("strategy_params", {})
        if strategy not in sp:
            sp[strategy] = {}
        for k, v in params.items():
            if k == "cutoff_full":
                continue
            sp[strategy][k] = round(v, 4)

        # 원자적 쓰기: 임시 파일에 쓴 뒤 rename (같은 파일시스템이면 atomic)
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=config_path.parent,
            suffix=".tmp",
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                yaml.dump(
                    raw,
                    f,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                )
            os.replace(tmp_path, config_path)
        except Exception:
            os.unlink(tmp_path)
            raise

        logger.info("config 업데이트: %s → %s", strategy, params)

    # ═══════════════════════════════════════════
    # 리포트
    # ═══════════════════════════════════════════

    async def _send_weekly_report(self) -> None:
        """주간 통합 검증 리포트를 전송한다."""
        if not self._notifier:
            return

        lines = ["<b>주간 검증 리포트</b>", "=" * 20]

        if self.wf_result:
            wf = self.wf_result
            lines.append(f"[Walk-Forward] {wf.pass_count}/{wf.total_segments} -> {wf.verdict}")

        if self.mc_result:
            mc = self.mc_result
            lines.append(
                f"[Monte Carlo] P5={mc.pnl_percentile_5:.0f},"
                f" MDD={mc.worst_mdd:.1%} -> {mc.verdict}"
            )

        if self.sens_result:
            sens = self.sens_result
            param_summary = []
            for p in sens.params:
                icon = ""
                if p.verdict in ("sensitive", "danger"):
                    icon = " (!)"
                param_summary.append(f"{p.name}:{p.verdict}{icon}")
            lines.append(f"[민감도] {', '.join(param_summary)}")

        lines.append("=" * 20)
        await self._notifier.send("\n".join(lines), channel="backtest")

    # ═══════════════════════════════════════════
    # 유틸
    # ═══════════════════════════════════════════

    async def run_all_now(self) -> None:
        """즉시 전체 검증을 실행한다 (테스트용)."""
        await self._run_walk_forward()
        await self._run_monte_carlo()
        await self._run_sensitivity()

    @staticmethod
    def _calc_pf(trades: list[dict]) -> float:
        """거래 목록에서 Profit Factor를 계산한다."""
        gross_profit = sum(
            t.get("net_pnl_krw", 0) for t in trades if (t.get("net_pnl_krw") or 0) > 0
        )
        gross_loss = abs(
            sum(t.get("net_pnl_krw", 0) for t in trades if (t.get("net_pnl_krw") or 0) < 0)
        )
        if gross_loss == 0:
            return 99.0 if gross_profit > 0 else 0.0
        return gross_profit / gross_loss

    @staticmethod
    def _parse_time(time_str: str) -> tuple[int, int]:
        """'HH:MM' → (hour, minute)."""
        parts = time_str.split(":")
        return int(parts[0]), int(parts[1])

    @staticmethod
    def _parse_weekday(day_str: str) -> int:
        """요일 문자열 → weekday (0=월, 6=일)."""
        mapping = {
            "monday": 0,
            "tuesday": 1,
            "wednesday": 2,
            "thursday": 3,
            "friday": 4,
            "saturday": 5,
            "sunday": 6,
        }
        return mapping.get(day_str.lower(), 6)
