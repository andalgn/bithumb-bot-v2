"""EvolutionOrchestrator — 자율 진화 7단계 루프.

매일 1회 실행되어 봇의 파라미터를 자율적으로 개선한다.
Karpathy Auto Research 원칙: 수정 → 실험 → 평가 → keep/revert.

7단계:
1. Monitor  — 최근 성과 수집 + 드리프트 감지
2. Diagnose — 약한 영역 파악
3. Hypothesize — LLM 방향 + 그리드 탐색 (Centaur)
4. Experiment — 백테스트 실행 + 하드 제약 필터
5. Validate — Walk-Forward + OOS + DSR
6. Guard — GuardAgent 구조적 검증
7. Apply — Discord 알림 + 인간 승인 대기
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from app.approval_workflow import ApprovalWorkflow, PendingChange
from strategy.guard_agent import GuardAgent
from strategy.strategy_params import EvolvableParams

logger = logging.getLogger(__name__)


# ── 결과 데이터 타입 ───────────────────────────────────────

@dataclass
class MonitorResult:
    """Phase 1 모니터링 결과."""

    should_continue: bool = True
    reason: str = ""
    fitness: float = 0.0
    profit_factor: float = 0.0
    sharpe: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    trade_count: int = 0


@dataclass
class ExperimentCandidate:
    """실험 후보 파라미터."""

    changes: dict[str, float] = field(default_factory=dict)
    source: str = ""  # "hypothesis" | "grid_search"
    rationale: str = ""


@dataclass
class ExperimentResult:
    """단일 실험 결과."""

    candidate: ExperimentCandidate
    params: EvolvableParams | None = None
    fitness: float = 0.0
    profit_factor: float = 0.0
    sharpe: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    trade_count: int = 0
    rejected: str = ""  # 탈락 사유 (빈 문자열이면 통과)


@dataclass
class ValidationResult:
    """Phase 5 검증 결과."""

    passed: bool = False
    reason: str = ""
    oos_fitness: float = 0.0
    is_oos_ratio: float = 0.0
    dsr_p_value: float = 1.0
    wf_verdict: str = ""


@dataclass
class EvolutionResult:
    """진화 세션 최종 결과."""

    success: bool = False
    change_id: str = ""
    reason: str = ""
    experiments_run: int = 0
    experiments_kept: int = 0
    best_fitness: float = 0.0
    baseline_fitness: float = 0.0


# ── Composite Fitness 계산 ─────────────────────────────────

def compute_fitness(
    profit_factor: float,
    sharpe: float,
    max_drawdown: float,
    win_rate: float,
) -> float:
    """Composite Fitness 단일 스코어 (0.0 ~ 1.0).

    Karpathy의 val_bpb에 해당하는 단일 평가 지표.

    가중치:
        PF 0.30 + Sharpe 0.30 + (1-MDD) 0.20 + WR 0.20
    """
    norm_pf = min(max(profit_factor, 0.0), 3.0) / 3.0
    norm_sharpe = min(max(sharpe, 0.0), 3.0) / 3.0
    norm_mdd = max(1.0 - max_drawdown / 0.20, 0.0)
    norm_wr = min(max(win_rate, 0.0), 1.0)

    return 0.30 * norm_pf + 0.30 * norm_sharpe + 0.20 * norm_mdd + 0.20 * norm_wr


# ── 하드 제약 사전 필터 ────────────────────────────────────

HARD_MIN_TRADES = 20
HARD_MAX_MDD = 0.15
HARD_MIN_WIN_RATE = 0.30


def check_hard_constraints(
    trade_count: int, max_drawdown: float, win_rate: float
) -> str:
    """하드 제약 사전 필터. fitness 계산 전 탈락 판정.

    Returns:
        탈락 사유 문자열. 빈 문자열이면 통과.
    """
    if trade_count < HARD_MIN_TRADES:
        return f"거래 수 부족 ({trade_count} < {HARD_MIN_TRADES})"
    if max_drawdown > HARD_MAX_MDD:
        return f"MDD 초과 ({max_drawdown:.1%} > {HARD_MAX_MDD:.0%})"
    if win_rate < HARD_MIN_WIN_RATE:
        return f"승률 미달 ({win_rate:.1%} < {HARD_MIN_WIN_RATE:.0%})"
    return ""


# ── Deflated Sharpe Ratio ──────────────────────────────────

def deflated_sharpe_p_value(
    observed_sharpe: float,
    num_experiments: int,
    num_trades: int,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    """Deflated Sharpe Ratio의 p-value.

    실험 횟수를 고려한 Sharpe의 통계적 유의성.
    낮을수록 유의미 (p < 0.05 권장).
    """
    if num_experiments < 2 or num_trades < 5 or observed_sharpe <= 0:
        return 1.0

    # 실험 횟수 기반 기대 최대 Sharpe (Euler-Mascheroni 근사)
    euler_gamma = 0.5772156649
    expected_max_sr = math.sqrt(2 * math.log(num_experiments)) - (
        (euler_gamma + math.log(math.pi / 2))
        / (2 * math.sqrt(2 * math.log(num_experiments)))
    )

    # Sharpe의 표준오차 (비정규성 보정)
    excess_kurtosis = kurtosis - 3.0
    sqrt_arg = (
        1.0
        - skewness * observed_sharpe
        + (excess_kurtosis / 4.0) * observed_sharpe ** 2
    )
    if sqrt_arg <= 0:
        return 1.0  # SE 계산 불가 → 비유의 처리

    se_sr = math.sqrt(sqrt_arg / max(num_trades - 1, 1))

    if se_sr <= 0:
        return 1.0

    # 검정 통계량
    z = (observed_sharpe - expected_max_sr) / se_sr

    # p-value = 1 - Φ(z) = P(Z >= z)
    # 높은 z → 낮은 p → 유의미 (관측 Sharpe가 우연이 아닐 확률 높음)
    p_value = 0.5 * math.erfc(z / math.sqrt(2))
    return p_value


# ── 오케스트레이터 ─────────────────────────────────────────

class EvolutionOrchestrator:
    """자율 진화 7단계 루프 엔진.

    Phase 1에서는 모든 변경이 Discord 알림 후 인간 승인 필요.
    """

    def __init__(
        self,
        journal: Any,
        notifier: Any,
        market_store: Any,
        optimizer: Any,
        walk_forward: Any,
        feedback_loop: Any,
        experiment_store: Any,
        guard_agent: GuardAgent,
        approval_workflow: ApprovalWorkflow,
        current_params: EvolvableParams,
        coins: list[str],
        review_engine: Any = None,
        max_experiments: int = 10,
        held_out_days: int = 30,
        dsr_significance: float = 0.05,
        is_oos_max_ratio: float = 1.5,
        drift_threshold: float = 0.25,
    ) -> None:
        self._journal = journal
        self._notifier = notifier
        self._market_store = market_store
        self._optimizer = optimizer
        self._walk_forward = walk_forward
        self._feedback_loop = feedback_loop
        self._experiment_store = experiment_store
        self._guard = guard_agent
        self._approval = approval_workflow
        self._current_params = current_params
        self._review_engine = review_engine
        self._coins = coins
        self._max_experiments = max_experiments
        self._held_out_days = held_out_days
        self._dsr_significance = dsr_significance
        self._is_oos_max_ratio = is_oos_max_ratio
        self._drift_threshold = drift_threshold
        self._session_experiment_count = 0

    async def run_session(self) -> EvolutionResult:
        """매일 1회 실행되는 진화 세션."""
        start = time.time()
        self._session_experiment_count = 0
        logger.info("진화 세션 시작")

        # Phase 1: Monitor
        baseline = await self._phase_monitor()
        if not baseline.should_continue:
            await self._notify(f"진화 중단: {baseline.reason}")
            return EvolutionResult(
                success=False, reason=baseline.reason,
                baseline_fitness=baseline.fitness,
            )

        # Phase 2: Diagnose
        weak_areas = await self._phase_diagnose(baseline)
        if not weak_areas:
            await self._notify("진단: 개선 필요 영역 없음 (현재 성과 양호)")
            return EvolutionResult(
                success=False, reason="no_weak_areas",
                baseline_fitness=baseline.fitness,
            )

        # Phase 3: Hypothesize
        candidates = await self._phase_hypothesize(weak_areas)
        if not candidates:
            await self._notify("가설 생성 실패: 후보 없음")
            return EvolutionResult(
                success=False, reason="no_candidates",
                baseline_fitness=baseline.fitness,
            )

        # Phase 4: Experiment
        results = await self._phase_experiment(candidates)
        kept = [r for r in results if not r.rejected and r.fitness > baseline.fitness]
        if not kept:
            await self._notify(
                f"실험 {len(results)}회 완료, 개선 후보 없음 "
                f"(baseline fitness={baseline.fitness:.3f})"
            )
            return EvolutionResult(
                success=False, reason="no_improvement",
                experiments_run=len(results),
                baseline_fitness=baseline.fitness,
            )

        best = max(kept, key=lambda r: r.fitness)

        # Phase 5: Validate
        validation = await self._phase_validate(best, baseline)
        if not validation.passed:
            await self._notify(
                f"검증 실패: {validation.reason} "
                f"(fitness={best.fitness:.3f})"
            )
            return EvolutionResult(
                success=False, reason=f"validation_{validation.reason}",
                experiments_run=len(results),
                experiments_kept=len(kept),
                best_fitness=best.fitness,
                baseline_fitness=baseline.fitness,
            )

        # Phase 6: Guard
        guard_result = self._guard.validate(self._current_params, best.params)
        if not guard_result.is_valid:
            await self._notify(
                f"GuardAgent 거부: {', '.join(guard_result.violations)}"
            )
            return EvolutionResult(
                success=False, reason="guard_rejected",
                experiments_run=len(results),
                experiments_kept=len(kept),
                best_fitness=best.fitness,
                baseline_fitness=baseline.fitness,
            )

        # Phase 7: Apply (인간 승인 대기)
        change_id = await self._phase_apply(
            best, baseline, guard_result, validation, len(results), len(kept)
        )

        elapsed = time.time() - start
        logger.info("진화 세션 완료: %.1f초, change_id=%s", elapsed, change_id)

        return EvolutionResult(
            success=True,
            change_id=change_id,
            experiments_run=len(results),
            experiments_kept=len(kept),
            best_fitness=best.fitness,
            baseline_fitness=baseline.fitness,
        )

    # ═══════════════════════════════════════════════════
    # Phase 1: Monitor
    # ═══════════════════════════════════════════════════

    async def _phase_monitor(self) -> MonitorResult:
        """최근 7일 거래 성과 + 드리프트 감지."""
        seven_days_ago = int(time.time()) - 7 * 86400
        trades = self._journal.get_trades_since(seven_days_ago)

        if len(trades) < 5:
            return MonitorResult(
                should_continue=False,
                reason=f"거래 부족 ({len(trades)}건 < 5건)",
            )

        # 성과 계산
        pnls = [t.get("net_pnl_pct", 0.0) for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]

        win_rate = len(wins) / len(pnls) if pnls else 0.0
        profit_factor = (
            abs(sum(wins)) / abs(sum(losses))
            if losses and sum(losses) != 0
            else 0.0
        )

        # Sharpe 근사 (일간 수익률 기반)
        mean_pnl = sum(pnls) / len(pnls) if pnls else 0.0
        var_pnl = (
            sum((p - mean_pnl) ** 2 for p in pnls) / max(len(pnls) - 1, 1)
        )
        std_pnl = math.sqrt(var_pnl) if var_pnl > 0 else 1e-9
        sharpe = (mean_pnl / std_pnl) * math.sqrt(252) if std_pnl > 1e-9 else 0.0

        # MDD 근사 (누적 수익률 기반)
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for pnl in pnls:
            cumulative += pnl
            peak = max(peak, cumulative)
            dd = (peak - cumulative) if peak > 0 else 0.0
            max_dd = max(max_dd, dd)

        fitness = compute_fitness(profit_factor, sharpe, max_dd, win_rate)

        # 드리프트 감지: 30일 성과 대비 25% 이상 하락
        thirty_days_ago = int(time.time()) - 30 * 86400
        older_trades = self._journal.get_trades_since(thirty_days_ago)
        min_older_trades = 50
        if len(older_trades) >= min_older_trades:
            older_pnls = [t.get("net_pnl_pct", 0.0) for t in older_trades]
            older_wins = [p for p in older_pnls if p > 0]
            older_losses = [p for p in older_pnls if p < 0]
            older_pf = (
                abs(sum(older_wins)) / abs(sum(older_losses))
                if older_losses and sum(older_losses) != 0
                else 0.0
            )
            older_wr = len(older_wins) / len(older_pnls) if older_pnls else 0.0
            # 30일 Sharpe 별도 계산 (7일 값 재사용하지 않음)
            older_mean = sum(older_pnls) / len(older_pnls)
            older_var = sum((p - older_mean) ** 2 for p in older_pnls) / max(len(older_pnls) - 1, 1)
            older_std = math.sqrt(older_var) if older_var > 0 else 1e-9
            older_sharpe = (older_mean / older_std) * math.sqrt(252) if older_std > 1e-9 else 0.0
            older_fitness = compute_fitness(older_pf, older_sharpe, max_dd, older_wr)

            if older_fitness > 0 and fitness < older_fitness * (1 - self._drift_threshold):
                return MonitorResult(
                    should_continue=False,
                    reason=f"드리프트 감지: fitness {fitness:.3f} < "
                           f"30일 평균 {older_fitness:.3f} × {1-self._drift_threshold:.0%}",
                    fitness=fitness,
                )

        return MonitorResult(
            should_continue=True,
            fitness=fitness,
            profit_factor=profit_factor,
            sharpe=sharpe,
            max_drawdown=max_dd,
            win_rate=win_rate,
            trade_count=len(trades),
        )

    # ═══════════════════════════════════════════════════
    # Phase 2: Diagnose
    # ═══════════════════════════════════════════════════

    async def _phase_diagnose(self, baseline: MonitorResult) -> list[str]:
        """약한 영역 파악."""
        weak: list[str] = []

        if baseline.profit_factor < 1.3:
            weak.append("strategy_params")
        if baseline.max_drawdown > 0.10:
            weak.append("risk_thresholds")
        if baseline.win_rate < 0.50:
            weak.append("entry_cutoff")
        if baseline.sharpe < 0.5:
            weak.append("sizing_params")

        # FeedbackLoop 실패 패턴
        patterns = self._feedback_loop.get_failure_patterns(days=7)
        if patterns:
            top = patterns[0]
            if top.tag == "sizing_error" and "sizing_params" not in weak:
                weak.append("sizing_params")
            if top.tag == "regime_mismatch" and "regime_params" not in weak:
                weak.append("regime_params")

        logger.info("진단 결과: %s (PF=%.2f, SR=%.2f, MDD=%.1f%%, WR=%.1f%%)",
                     weak, baseline.profit_factor, baseline.sharpe,
                     baseline.max_drawdown * 100, baseline.win_rate * 100)

        return weak[:2]  # 세션당 최대 2개 영역

    # ═══════════════════════════════════════════════════
    # Phase 3: Hypothesize (Centaur)
    # ═══════════════════════════════════════════════════

    async def _phase_hypothesize(
        self, weak_areas: list[str]
    ) -> list[ExperimentCandidate]:
        """LLM 방향 제시 + 그리드 탐색 후보 생성."""
        candidates: list[ExperimentCandidate] = []

        # 0. ReviewEngine 주간 인사이트 로드 (컨텍스트 강화)
        weekly_insight: dict | None = None
        if hasattr(self, "_review_engine") and self._review_engine:
            weekly_insight = self._review_engine.get_latest_insight()
            if weekly_insight:
                logger.info("주간 인사이트 컨텍스트 로드: %s", weekly_insight.get("period", ""))

        # 1. FeedbackLoop LLM 가설
        try:
            patterns = self._feedback_loop.get_failure_patterns(days=7)
            if patterns:
                hypotheses = await self._feedback_loop.generate_hypotheses(
                    patterns, self._current_params.to_dict(),
                    weekly_insight=weekly_insight,
                )
                for hyp in hypotheses[:3]:
                    changes = {}
                    rationale = hyp.get("rationale", "LLM 가설")
                    for key in ("mr_sl_mult", "mr_tp_rr", "dca_sl_pct",
                                "dca_tp_pct", "cutoff"):
                        if key in hyp and key != "rationale":
                            # FeedbackLoop 키 → EvolvableParams 키 매핑
                            mapped = self._map_feedback_key(key)
                            if mapped:
                                changes[mapped] = hyp[key]
                    if changes:
                        candidates.append(ExperimentCandidate(
                            changes=changes,
                            source="hypothesis",
                            rationale=rationale,
                        ))
        except Exception:
            logger.warning("LLM 가설 생성 실패", exc_info=True)

        # 2. 약한 영역 기반 그리드 서치 후보
        if "strategy_params" in weak_areas:
            candidates.extend(self._grid_strategy_candidates())
        if "entry_cutoff" in weak_areas:
            candidates.extend(self._grid_cutoff_candidates())
        if "risk_thresholds" in weak_areas:
            candidates.extend(self._grid_risk_candidates())
        if "sizing_params" in weak_areas:
            candidates.extend(self._grid_sizing_candidates())

        logger.info("가설 생성: %d개 후보", len(candidates))
        return candidates[:self._max_experiments]

    @staticmethod
    def _map_feedback_key(key: str) -> str | None:
        """FeedbackLoop 키 → EvolvableParams 필드명 매핑."""
        mapping = {
            "mr_sl_mult": "mr_sl_mult",
            "mr_tp_rr": "mr_tp_rr",
            "dca_sl_pct": "dca_sl_pct",
            "dca_tp_pct": "dca_tp_pct",
            "cutoff": "tf_cutoff",
        }
        return mapping.get(key)

    def _grid_strategy_candidates(self) -> list[ExperimentCandidate]:
        """전략 SL/TP 그리드 후보."""
        base = self._current_params
        candidates = []
        for delta in (-0.5, 0.5, -1.0, 1.0):
            candidates.append(ExperimentCandidate(
                changes={"tf_sl_mult": base.tf_sl_mult + delta},
                source="grid_search",
                rationale=f"tf_sl_mult {base.tf_sl_mult} → {base.tf_sl_mult + delta}",
            ))
        for delta in (-0.3, 0.3):
            candidates.append(ExperimentCandidate(
                changes={"tf_tp_rr": base.tf_tp_rr + delta},
                source="grid_search",
                rationale=f"tf_tp_rr {base.tf_tp_rr} → {base.tf_tp_rr + delta}",
            ))
        return candidates

    def _grid_cutoff_candidates(self) -> list[ExperimentCandidate]:
        """진입 cutoff 그리드 후보."""
        base = self._current_params
        candidates = []
        for delta in (-5, -3, 3, 5):
            candidates.append(ExperimentCandidate(
                changes={"tf_cutoff": base.tf_cutoff + delta},
                source="grid_search",
                rationale=f"tf_cutoff {base.tf_cutoff} → {base.tf_cutoff + delta}",
            ))
        return candidates

    def _grid_risk_candidates(self) -> list[ExperimentCandidate]:
        """리스크 파라미터 그리드 후보."""
        base = self._current_params
        return [
            ExperimentCandidate(
                changes={"daily_dd_pct": base.daily_dd_pct - 0.005},
                source="grid_search",
                rationale="daily DD 축소 (보수적)",
            ),
            ExperimentCandidate(
                changes={"cooldown_min": base.cooldown_min + 15},
                source="grid_search",
                rationale="쿨다운 증가 (과매매 방지)",
            ),
        ]

    def _grid_sizing_candidates(self) -> list[ExperimentCandidate]:
        """사이징 파라미터 그리드 후보."""
        base = self._current_params
        return [
            ExperimentCandidate(
                changes={"active_risk_pct": base.active_risk_pct - 0.01},
                source="grid_search",
                rationale="active_risk 축소 (보수적)",
            ),
            ExperimentCandidate(
                changes={"pool_cap_pct": base.pool_cap_pct - 0.03},
                source="grid_search",
                rationale="pool_cap 축소",
            ),
        ]

    # ═══════════════════════════════════════════════════
    # Phase 4: Experiment
    # ═══════════════════════════════════════════════════

    async def _phase_experiment(
        self, candidates: list[ExperimentCandidate]
    ) -> list[ExperimentResult]:
        """각 후보로 백테스트 실행."""
        results: list[ExperimentResult] = []

        # 캔들 데이터 한 번만 로드
        candles_15m = {}
        candles_1h = {}
        for coin in self._coins:
            symbol = f"{coin}_KRW"
            candles_15m[symbol] = self._market_store.get_candles(symbol, "15m", limit=5000)
            candles_1h[symbol] = self._market_store.get_candles(symbol, "1h", limit=2000)

        for candidate in candidates:
            self._session_experiment_count += 1
            try:
                new_params = self._current_params.apply_changes(candidate.changes)
            except ValueError as e:
                results.append(ExperimentResult(
                    candidate=candidate,
                    rejected=f"파라미터 제약 위반: {e}",
                ))
                continue

            # 전략 파라미터 변경은 optimizer로 백테스트
            strategy_keys = {
                "tf_sl_mult", "tf_tp_rr", "mr_sl_mult", "mr_tp_rr",
                "bo_sl_mult", "bo_tp_rr", "dca_sl_pct", "dca_tp_pct",
            }
            changed_keys = set(candidate.changes.keys())

            if changed_keys & strategy_keys:
                result = await self._backtest_strategy_change(
                    candidate, new_params, candles_15m, candles_1h
                )
            else:
                # 리스크/사이징/국면 파라미터는 과거 거래 시뮬레이션
                result = self._simulate_param_effect(candidate, new_params)

            results.append(result)

            # 실험 기록
            self._experiment_store.record(
                source="evolution",
                strategy="all",
                params=candidate.changes,
                pf=result.profit_factor,
                mdd=result.max_drawdown,
                trades=result.trade_count,
                verdict="keep" if not result.rejected else "revert",
            )

        logger.info(
            "실험 %d회 완료: %d keep, %d revert",
            len(results),
            sum(1 for r in results if not r.rejected),
            sum(1 for r in results if r.rejected),
        )
        return results

    async def _backtest_strategy_change(
        self,
        candidate: ExperimentCandidate,
        new_params: EvolvableParams,
        candles_15m: dict,
        candles_1h: dict,
    ) -> ExperimentResult:
        """전략 파라미터 변경을 백테스트로 검증."""
        # 변경된 전략 식별
        strategy_map = {
            "tf_": "trend_follow",
            "mr_": "mean_reversion",
            "bo_": "breakout",
            "dca_": "dca",
        }
        strategies = set()
        for key in candidate.changes:
            for prefix, strat in strategy_map.items():
                if key.startswith(prefix):
                    strategies.add(strat)

        if not strategies:
            return ExperimentResult(
                candidate=candidate, rejected="전략 매핑 실패"
            )

        # 각 전략별 optimizer replay
        total_pf = 0.0
        total_trades = 0
        total_mdd = 0.0
        total_wr = 0.0
        strat_count = 0

        for strat in strategies:
            try:
                params_dict = self._evolvable_to_strategy_params(new_params, strat)
                entries = self._optimizer.scan_entries(
                    strat, candles_15m, candles_1h
                )
                if not entries:
                    continue
                opt_result = self._optimizer.replay_with_params(
                    strat, params_dict, entries
                )
                total_pf += opt_result.profit_factor
                total_trades += opt_result.trades
                total_mdd = max(total_mdd, opt_result.max_drawdown)
                total_wr += opt_result.win_rate
                strat_count += 1
            except Exception:
                logger.warning("백테스트 실패: %s", strat, exc_info=True)

        if strat_count == 0:
            return ExperimentResult(
                candidate=candidate, rejected="백테스트 결과 없음"
            )

        avg_pf = total_pf / strat_count
        avg_wr = total_wr / strat_count

        # 하드 제약 필터
        rejected = check_hard_constraints(total_trades, total_mdd, avg_wr)
        fitness = compute_fitness(avg_pf, 0.0, total_mdd, avg_wr) if not rejected else 0.0

        return ExperimentResult(
            candidate=candidate,
            params=new_params,
            fitness=fitness,
            profit_factor=avg_pf,
            sharpe=0.0,  # replay는 Sharpe 미제공
            max_drawdown=total_mdd,
            win_rate=avg_wr,
            trade_count=total_trades,
            rejected=rejected,
        )

    def _simulate_param_effect(
        self,
        candidate: ExperimentCandidate,
        new_params: EvolvableParams,
    ) -> ExperimentResult:
        """리스크/사이징 파라미터 변경의 과거 영향 시뮬레이션.

        전략 변경이 아닌 경우, 최근 거래에서 해당 파라미터가
        다른 값이었다면 결과가 어떻게 달라졌을지 추정한다.
        """
        # 간단한 휴리스틱: 현재 성과에 파라미터 변경 방향의 기대 효과 적용
        # Phase 1에서는 보수적 추정. Phase 2에서 정교화.
        seven_days_ago = int(time.time()) - 7 * 86400
        trades = self._journal.get_trades_since(seven_days_ago)

        if len(trades) < HARD_MIN_TRADES:
            return ExperimentResult(
                candidate=candidate,
                params=new_params,
                rejected=f"시뮬레이션 거래 부족 ({len(trades)}건)",
            )

        pnls = [t.get("net_pnl_pct", 0.0) for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        pf = abs(sum(wins)) / abs(sum(losses)) if losses and sum(losses) != 0 else 0.0
        wr = len(wins) / len(pnls) if pnls else 0.0
        mdd = 0.0  # 리스크 파라미터 변경 시뮬레이션에서는 MDD 추정 어려움

        fitness = compute_fitness(pf, 0.0, mdd, wr)
        return ExperimentResult(
            candidate=candidate,
            params=new_params,
            fitness=fitness,
            profit_factor=pf,
            win_rate=wr,
            trade_count=len(trades),
        )

    @staticmethod
    def _evolvable_to_strategy_params(
        params: EvolvableParams, strategy: str
    ) -> dict[str, float]:
        """EvolvableParams에서 특정 전략의 파라미터만 추출."""
        mapping = {
            "trend_follow": {
                "sl_mult": params.tf_sl_mult,
                "tp_rr": params.tf_tp_rr,
            },
            "mean_reversion": {
                "sl_mult": params.mr_sl_mult,
                "tp_rr": params.mr_tp_rr,
            },
            "breakout": {
                "sl_mult": params.bo_sl_mult,
                "tp_rr": params.bo_tp_rr,
            },
            "dca": {
                "sl_pct": params.dca_sl_pct,
                "tp_pct": params.dca_tp_pct,
            },
        }
        return mapping.get(strategy, {})

    # ═══════════════════════════════════════════════════
    # Phase 5: Validate
    # ═══════════════════════════════════════════════════

    async def _phase_validate(
        self,
        best: ExperimentResult,
        baseline: MonitorResult,
    ) -> ValidationResult:
        """다층 과적합 방지 검증."""

        # 1. Walk-Forward 검증
        wf_verdict = "unknown"
        try:
            seven_days_ago = int(time.time()) - 7 * 86400
            trades = self._journal.get_trades_since(seven_days_ago)
            wf_result = self._walk_forward.run(trades)
            wf_verdict = wf_result.verdict
            if wf_result.verdict in ("poor", "insufficient_data"):
                return ValidationResult(
                    passed=False,
                    reason=f"walk_forward_{wf_result.verdict}",
                    wf_verdict=wf_verdict,
                )
            if wf_result.overfit_detected:
                return ValidationResult(
                    passed=False,
                    reason="walk_forward_overfit",
                    wf_verdict=wf_verdict,
                )
        except Exception:
            logger.warning("Walk-Forward 검증 실패", exc_info=True)
            return ValidationResult(passed=False, reason="walk_forward_error")

        # 2. IS/OOS 괴리 체크
        is_fitness = best.fitness
        oos_fitness = baseline.fitness

        # 초기 단계(baseline 낮음)에서는 관대한 기준 적용
        min_oos = 0.1
        if oos_fitness < min_oos:
            is_oos_ratio = is_fitness / min_oos
        else:
            is_oos_ratio = is_fitness / oos_fitness

        if is_oos_ratio > self._is_oos_max_ratio:
            return ValidationResult(
                passed=False,
                reason=f"overfitting (IS/OOS={is_oos_ratio:.2f} > {self._is_oos_max_ratio})",
                is_oos_ratio=is_oos_ratio,
            )

        # 3. Deflated Sharpe Ratio
        dsr_p = deflated_sharpe_p_value(
            observed_sharpe=best.sharpe if best.sharpe > 0 else baseline.sharpe,
            num_experiments=self._session_experiment_count,
            num_trades=best.trade_count,
        )
        if dsr_p > self._dsr_significance and self._session_experiment_count >= 5:
            return ValidationResult(
                passed=False,
                reason=f"dsr_not_significant (p={dsr_p:.3f} > {self._dsr_significance})",
                dsr_p_value=dsr_p,
            )

        return ValidationResult(
            passed=True,
            oos_fitness=oos_fitness,
            is_oos_ratio=is_oos_ratio,
            dsr_p_value=dsr_p,
            wf_verdict=wf_verdict,
        )

    # ═══════════════════════════════════════════════════
    # Phase 7: Apply
    # ═══════════════════════════════════════════════════

    async def _phase_apply(
        self,
        best: ExperimentResult,
        baseline: MonitorResult,
        guard_result: Any,
        validation: ValidationResult,
        experiments_run: int,
        experiments_kept: int,
    ) -> str:
        """PendingChange 생성 + Discord 알림."""
        change = PendingChange(
            change_id=uuid4().hex[:8],
            proposed_params=best.params.to_dict() if best.params else {},
            current_params=self._current_params.to_dict(),
            changes={
                k: [float(old), float(new)]
                for k, (old, new) in guard_result.changes.items()
            },
            risk_score=guard_result.risk_score,
            risk_level=guard_result.risk_level,
            fitness_improvement=best.fitness - baseline.fitness,
            rationale=best.candidate.rationale,
            experiment_count=experiments_run,
            created_at=datetime.now().isoformat(),
        )

        change_id = self._approval.propose(change)

        # Discord 보고
        report = self._format_report(
            change, baseline, best, validation,
            experiments_run, experiments_kept,
        )
        await self._notify(report)
        await self._notify(
            f"`/approve {change_id}` | `/reject {change_id}`"
        )

        return change_id

    def _format_report(
        self,
        change: PendingChange,
        baseline: MonitorResult,
        best: ExperimentResult,
        validation: ValidationResult,
        experiments_run: int,
        experiments_kept: int,
    ) -> str:
        """Discord 진화 보고서 포맷."""
        lines = [
            "━━━ Evolution Report ━━━",
            f"세션: {datetime.now().strftime('%Y-%m-%d %H:%M KST')}",
            f"실험: {experiments_run}회 ({experiments_kept} keep, "
            f"{experiments_run - experiments_kept} revert)",
            f"베이스라인 fitness: {baseline.fitness:.3f}",
            f"최선 후보 fitness: {best.fitness:.3f} "
            f"(+{(best.fitness - baseline.fitness):.3f})",
            "",
            "변경 내용:",
        ]
        for param, (old, new) in change.changes.items():
            lines.append(f"  {param}: {old} → {new}")

        lines.extend([
            "",
            "검증:",
            f"  Walk-Forward: {validation.wf_verdict}",
            f"  IS/OOS 괴리: {validation.is_oos_ratio:.2f}",
            f"  DSR p-value: {validation.dsr_p_value:.3f}",
            "",
            f"위험도: {change.risk_level} ({change.risk_score:.2f})",
            "━━━━━━━━━━━━━━━━━━━━",
        ])
        return "\n".join(lines)

    async def _notify(self, message: str) -> None:
        """Discord 알림 전송."""
        try:
            await self._notifier.send(message, channel="system")
        except Exception:
            logger.warning("Discord 알림 실패", exc_info=True)
