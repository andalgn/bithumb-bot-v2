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
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from app.approval_workflow import ApprovalWorkflow, PendingChange
from app.config import BacktestConfig
from app.journal import Journal
from app.notify import Notifier
from backtesting.monte_carlo import MonteCarlo, MonteCarloResult
from backtesting.sensitivity import SensitivityAnalyzer, SensitivityResult
from backtesting.walk_forward import WalkForward, WalkForwardResult
from strategy.guard_agent import GuardAgent
from strategy.strategy_params import EvolvableParams

if TYPE_CHECKING:
    from market.bithumb_api import BithumbClient
    from market.market_store import MarketStore

# (strategy_name) → EvolvableParams 필드명 접두사 매핑
_STRATEGY_PREFIX: dict[str, str] = {
    "trend_follow": "tf",
    "mean_reversion": "mr",
    "breakout": "bo",
    "dca": "dca",
}

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
        experiment_store: object | None = None,
        darwin: object | None = None,
        approval: ApprovalWorkflow | None = None,
        guard: GuardAgent | None = None,
        current_params: EvolvableParams | None = None,
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
            experiment_store: ExperimentStore 인스턴스 (자율 연구용).
            darwin: DarwinEngine 인스턴스 (진화 파이프라인용).
        """
        self._journal = journal
        self._notifier = notifier
        self._config = config or BacktestConfig()
        self._store = store
        self._client = client
        self._coins = coins or []
        self._deepseek_key = deepseek_api_key
        self._experiment_store = experiment_store
        self._darwin = darwin
        self._approval = approval
        self._guard = guard or GuardAgent()
        self._current_params = current_params
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
        self._last_pipeline: str = ""

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
        # Evolution Pipeline: auto_optimize_day/time 기준 통합 실행
        # (auto_research.time은 무시 — 파이프라인이 순차 처리)
        pipeline_h, pipeline_m = self._parse_time(c.auto_optimize_time)
        pipeline_weekday = self._parse_weekday(c.auto_optimize_day)

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

                # Evolution Pipeline 통합: 매주 (Optimize + Research + Darwin)
                if (
                    (c.auto_optimize_enabled or c.auto_research_enabled)
                    and now.weekday() == pipeline_weekday
                    and now.hour == pipeline_h
                    and now.minute >= pipeline_m
                    and self._last_pipeline != week_key
                ):
                    self._last_pipeline = week_key
                    await self._run_evolution_pipeline()

            except Exception:  # noqa: BLE001 — 백테스트 데몬 루프 가드, 프로세스 유지를 위한 의도적 광역 포착
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
                except Exception:  # noqa: BLE001 — 백테스트 데몬 루프 가드, 프로세스 유지를 위한 의도적 광역 포착
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
            if self.wf_result.verdict == "insufficient_data":
                msg = (
                    f"**Walk-Forward**: 거래 {len(wf_trades)}건 — "
                    f"데이터 부족으로 검증 보류"
                )
            else:
                msg = (
                    f"**Walk-Forward**: {self.wf_result.pass_count}/"
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

    async def _run_auto_optimize(self) -> list[dict]:
        """자동 파라미터 최적화를 실행하고 후보 목록을 반환한다.

        config.yaml을 직접 수정하지 않는다. 후보만 생성하여 반환.
        """
        if not self._config.auto_optimize_enabled:
            return []
        if not self._store:
            return []

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
            return []

        # rule_engine 로그 억제
        import logging as _logging

        _logging.getLogger("strategy.rule_engine").setLevel(_logging.WARNING)

        optimizer = ParameterOptimizer(self._coins, config)
        grids = build_grids()
        candidates: list[dict] = []

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
            if (
                best.profit_factor >= self._config.auto_apply_min_pf
                and best.trades >= self._config.auto_apply_min_trades
            ):
                candidates.append({
                    "source": "auto_optimize",
                    "strategy": strategy,
                    "params": best.params,
                    "pf": best.profit_factor,
                    "trades": best.trades,
                    "win_rate": best.win_rate,
                })
            logger.info(
                "최적화 %s: PF=%.2f WR=%.0f%% (%d건)",
                strategy,
                best.profit_factor,
                best.win_rate * 100,
                best.trades,
            )

        self.optimize_result = {c["strategy"]: c for c in candidates}
        return candidates

    async def _run_auto_research(self) -> list[dict]:
        """자율 연구 세션을 실행하고 후보 목록을 반환한다.

        config.yaml을 직접 수정하지 않는다. 후보만 생성하여 반환.
        """
        if not self._store:
            return []
        logger.info("자율 연구 세션 시작")

        from strategy.auto_researcher import AutoResearcher

        researcher = AutoResearcher(
            store=self._store,
            coins=self._coins,
            deepseek_api_key=self._deepseek_key,
            max_experiments=self._config.auto_research_max_experiments,
            max_consecutive_failures=self._config.auto_research_max_failures,
            experiment_store=self._experiment_store,
        )
        results = await researcher.run_session()

        kept = [r for r in results if r.verdict == "KEEP"]
        candidates: list[dict] = []
        if kept:
            # 전략별로 최종 KEEP 파라미터를 묶어서 후보 생성
            by_strategy: dict[str, dict[str, float]] = {}
            best_pf: dict[str, float] = {}
            best_trades: dict[str, int] = {}
            for r in kept:
                by_strategy.setdefault(r.strategy, {}).update(r.params_changed)
                best_pf[r.strategy] = r.result_pf
                best_trades[r.strategy] = getattr(r, "result_trades", 0)
            for strategy, params in by_strategy.items():
                candidates.append({
                    "source": "auto_research",
                    "strategy": strategy,
                    "params": params,
                    "pf": best_pf.get(strategy, 0.0),
                    "trades": best_trades.get(strategy, 0),
                    "win_rate": 0.0,
                })

        return candidates

    def _run_darwin_candidate(self) -> list[dict]:
        """Darwin 토너먼트를 실행하고 챔피언 후보를 반환한다.

        config.yaml을 직접 수정하지 않는다. 후보만 생성하여 반환.
        """
        if not self._darwin:
            return []

        logger.info("Darwin 토너먼트 후보 생성 시작")

        from app.data_types import Regime

        # 현재 국면 추정 (최근 거래의 regime 또는 기본값)
        market_regime = Regime.RANGE
        trades = self._journal.get_recent_trades(limit=5)
        if trades:
            last_regime = trades[0].get("regime", "")
            for r in Regime:
                if r.value == last_regime:
                    market_regime = r
                    break

        self._darwin.run_tournament(market_regime=market_regime)
        new_champion = self._darwin.check_champion_replacement()
        if not new_champion:
            logger.info("Darwin: 챔피언 교체 후보 없음")
            return []

        perf = self._darwin.get_shadow_performance(new_champion.shadow_id)
        if not (perf and perf.trade_count >= 30):
            logger.info("Darwin: 후보 거래 수 부족 (%d < 30)", perf.trade_count if perf else 0)
            return []

        if perf.max_drawdown > 0.15:
            logger.info("Darwin: 후보 MDD 초과 (%.1f%% > 15%%)", perf.max_drawdown * 100)
            return []

        champ_params = {
            "mean_reversion": {
                "sl_mult": new_champion.mr_sl_mult,
                "tp_rr": new_champion.mr_tp_rr,
            },
            "dca": {
                "sl_pct": new_champion.dca_sl_pct,
                "tp_pct": new_champion.dca_tp_pct,
            },
        }

        candidates = []
        for strategy, params in champ_params.items():
            candidates.append({
                "source": "darwin",
                "strategy": strategy,
                "params": params,
                "pf": perf.profit_factor,
                "trades": perf.trade_count,
                "win_rate": perf.win_rate,
                "shadow_id": new_champion.shadow_id,
                "_new_champion": new_champion,
            })

        logger.info(
            "Darwin 후보: PF=%.2f WR=%.0f%% MDD=%.1f%% (%d건)",
            perf.profit_factor,
            perf.win_rate * 100,
            perf.max_drawdown * 100,
            perf.trade_count,
        )
        return candidates

    async def _run_evolution_pipeline(self) -> None:
        """자율진화 통합 파이프라인.

        Auto-Optimize, Auto-Research, Darwin 토너먼트를 순차 실행하여
        후보를 수집하고, PF 기준 최고 1개만 config.yaml에 적용한다.
        """
        logger.info("=" * 50)
        logger.info("Evolution Pipeline 시작")

        # baseline PF 계산
        recent_trades = self._journal.get_recent_trades(limit=100)
        if len(recent_trades) < 10:
            logger.info("Evolution Pipeline: 거래 %d건 부족 (최소 10), 건너뜀", len(recent_trades))
            if self._notifier:
                await self._notifier.send(
                    "**Evolution Pipeline**: 거래 부족으로 건너뜀"
                    f" ({len(recent_trades)}건 < 10)",
                    channel="backtest",
                )
            return

        baseline_pf = self._calc_pf(recent_trades)
        logger.info("Baseline PF: %.2f (%d건)", baseline_pf, len(recent_trades))

        # 1. Auto-Optimize 후보
        all_candidates: list[dict] = []
        try:
            opt_candidates = await self._run_auto_optimize()
            all_candidates.extend(opt_candidates)
            logger.info("Auto-Optimize: %d개 후보", len(opt_candidates))
        except Exception:
            logger.exception("Auto-Optimize 실패")

        # 2. Auto-Research 후보
        try:
            research_candidates = await self._run_auto_research()
            all_candidates.extend(research_candidates)
            logger.info("Auto-Research: %d개 후보", len(research_candidates))
        except Exception:
            logger.exception("Auto-Research 실패")

        # 3. Darwin 후보
        try:
            darwin_candidates = self._run_darwin_candidate()
            all_candidates.extend(darwin_candidates)
            logger.info("Darwin: %d개 후보", len(darwin_candidates))
        except Exception:
            logger.exception("Darwin 토너먼트 실패")

        # baseline보다 좋은 후보만 필터
        viable = [c for c in all_candidates if c["pf"] > baseline_pf]
        logger.info(
            "후보 %d개 중 baseline(%.2f) 초과: %d개",
            len(all_candidates),
            baseline_pf,
            len(viable),
        )

        # PF 기준 최고 후보 선택
        selected = max(viable, key=lambda c: c["pf"]) if viable else None

        # Discord 리포트 생성
        report_lines = [
            "**Evolution Pipeline 결과**",
            f"Baseline PF: {baseline_pf:.2f} ({len(recent_trades)}건)",
            "",
        ]
        for c in all_candidates:
            delta = (c["pf"] / baseline_pf - 1) * 100 if baseline_pf > 0 else 0
            is_selected = selected is not None and c is selected
            icon = ">> " if is_selected else "   "
            mark = " **SELECTED**" if is_selected else ""
            report_lines.append(
                f"{icon}[{c['source']}] {c['strategy']}: "
                f"PF={c['pf']:.2f} ({delta:+.1f}%) "
                f"({c['trades']}건){mark}"
            )

        if not all_candidates:
            report_lines.append("   후보 없음")

        report_lines.append("")

        # 적용
        if selected:
            # Darwin 선택 시 챔피언을 먼저 교체 (config 쓰기 전 상태 일관성 보장)
            if selected["source"] == "darwin" and "_new_champion" in selected:
                self._darwin.replace_champion(selected["_new_champion"])
                logger.info("Darwin 챔피언 교체 완료")
                report_lines.append("Darwin 챔피언 교체 + Pilot 모드(50% × 20건)")

            await self._propose_via_approval(selected)
            report_lines.append(
                f"적용: {selected['source']} → {selected['strategy']} "
                f"(PF {baseline_pf:.2f} → {selected['pf']:.2f})"
            )
        else:
            report_lines.append("적용 없음 — baseline 초과 후보 없음")

        logger.info("Evolution Pipeline 완료")

        if self._notifier:
            await self._notifier.send("\n".join(report_lines), channel="backtest")

    async def _propose_via_approval(self, candidate: dict[str, Any]) -> None:
        """진화 후보를 GuardAgent 검증 + ApprovalWorkflow 경유로 제안한다.

        직접 config.yaml에 쓰지 않고, 검증 파이프라인을 거쳐
        인간 승인 후에만 적용되도록 한다.

        Args:
            candidate: {"strategy", "params", "pf", "source", "trades"} 딕셔너리.
        """
        if not self._approval:
            logger.warning("ApprovalWorkflow 미설정 — 후보 제안 건너뜀")
            return

        if not self._current_params:
            logger.warning("current_params 미설정 — 후보 제안 건너뜀")
            return

        strategy = candidate["strategy"]
        params = candidate["params"]

        # (strategy, config_key) → EvolvableParams 필드명 변환
        prefix = _STRATEGY_PREFIX.get(strategy)
        if not prefix:
            logger.warning("알 수 없는 전략: %s — 후보 제안 건너뜀", strategy)
            return

        changes: dict[str, float] = {}
        for k, v in params.items():
            if k == "cutoff_full":
                continue
            field_name = f"{prefix}_{k}"
            if hasattr(self._current_params, field_name):
                changes[field_name] = round(v, 4) if isinstance(v, float) else v
            else:
                logger.debug("매핑 없는 파라미터 무시: %s.%s", strategy, k)

        if not changes:
            logger.info("변경 사항 없음 — 후보 제안 건너뜀")
            return

        # EvolvableParams 생성 (범위 클램핑 + 교차 필드 검증 포함)
        try:
            proposed = self._current_params.apply_changes(changes)
        except ValueError as e:
            logger.warning("파라미터 교차 필드 제약 위반: %s", e)
            return

        # GuardAgent 검증
        guard_result = self._guard.validate(self._current_params, proposed)
        if not guard_result.is_valid:
            logger.warning(
                "GuardAgent 거부 (daemon): %s", guard_result.violations,
            )
            return
        if guard_result.risk_level == "high":
            logger.warning(
                "GuardAgent 고위험 (daemon): risk=%.2f — 거부",
                guard_result.risk_score,
            )
            return

        # PendingChange 생성 → ApprovalWorkflow
        from uuid import uuid4

        change = PendingChange(
            change_id=uuid4().hex[:8],
            proposed_params=proposed.to_dict(),
            current_params=self._current_params.to_dict(),
            changes={
                k: [float(old), float(new)]
                for k, (old, new) in guard_result.changes.items()
            },
            risk_score=guard_result.risk_score,
            risk_level=guard_result.risk_level,
            fitness_improvement=candidate.get("pf", 0.0),
            rationale=f"BacktestDaemon {candidate.get('source', 'auto')}: {strategy}",
            experiment_count=1,
            created_at=datetime.now().isoformat(),
        )

        change_id = self._approval.propose(change)
        logger.info(
            "Daemon 후보 제안 완료: %s (strategy=%s, risk=%s)",
            change_id, strategy, guard_result.risk_level,
        )

        if self._notifier:
            await self._notifier.send(
                f"**Daemon Evolution 제안** [{change_id}]\n"
                f"전략: {strategy} | 위험도: {guard_result.risk_level} "
                f"({guard_result.risk_score:.2f})\n"
                f"`/approve {change_id}` | `/reject {change_id}`",
                channel="backtest",
            )

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
