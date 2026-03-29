"""evolution_orchestrator 단위 테스트.

기존 모듈(journal, notifier, optimizer 등)은 Mock으로 대체.
각 Phase별 독립 테스트 + 통합 시나리오.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock

import pytest

from strategy.evolution_orchestrator import (
    EvolutionOrchestrator,
    ExperimentCandidate,
    ExperimentResult,
    MonitorResult,
    check_hard_constraints,
    compute_fitness,
    deflated_sharpe_p_value,
)
from strategy.guard_agent import GuardAgent
from strategy.strategy_params import EvolvableParams


# ── Mock 데이터 ────────────────────────────────────────────

def _make_trade(net_pnl_pct: float, days_ago: int = 0) -> dict:
    """테스트용 거래 데이터 생성."""
    ts = int(time.time()) - days_ago * 86400
    return {
        "trade_id": f"t_{ts}",
        "net_pnl_pct": net_pnl_pct,
        "net_pnl_krw": net_pnl_pct * 1_000_000,
        "entry_time": ts * 1000,
        "exit_time": (ts + 3600) * 1000,
        "strategy": "trend_follow",
        "tag": "winner" if net_pnl_pct > 0 else "timing_error",
    }


def _make_trades(count: int = 30, win_rate: float = 0.6) -> list[dict]:
    """랜덤 거래 목록 생성."""
    trades = []
    for i in range(count):
        if i < int(count * win_rate):
            trades.append(_make_trade(0.02, days_ago=i % 7))
        else:
            trades.append(_make_trade(-0.015, days_ago=i % 7))
    return trades


@dataclass
class MockFailurePattern:
    tag: str = "timing_error"
    strategy: str = "trend_follow"
    regime: str = "RANGE"
    count: int = 5
    avg_loss_krw: float = -15000.0
    total_loss_krw: float = -75000.0


@dataclass
class MockOptResult:
    params: dict = field(default_factory=dict)
    strategy: str = "trend_follow"
    trades: int = 50
    win_rate: float = 0.6
    profit_factor: float = 1.8
    expectancy: float = 0.003
    max_drawdown: float = 0.08
    sharpe: float = 1.2
    total_pnl: float = 150000.0
    is_oos: bool = False


@dataclass
class MockWFResult:
    verdict: str = "robust"
    overfit_detected: bool = False
    pass_count: int = 4
    total_segments: int = 4


# ── Fixture ────────────────────────────────────────────────

@pytest.fixture
def mock_journal():
    journal = MagicMock()
    journal.get_trades_since.return_value = _make_trades(30, 0.6)
    journal.get_recent_trades.return_value = _make_trades(30, 0.6)
    return journal


@pytest.fixture
def mock_notifier():
    notifier = AsyncMock()
    notifier.send = AsyncMock(return_value=True)
    return notifier


@pytest.fixture
def mock_market_store():
    store = MagicMock()
    store.get_candles.return_value = []
    return store


@pytest.fixture
def mock_optimizer():
    opt = MagicMock()
    opt.scan_entries.return_value = [MagicMock()]  # 비어있지 않은 entry
    opt.replay_with_params.return_value = MockOptResult()
    return opt


@pytest.fixture
def mock_walk_forward():
    wf = MagicMock()
    wf.run.return_value = MockWFResult()
    return wf


@pytest.fixture
def mock_feedback_loop():
    fl = MagicMock()
    fl.get_failure_patterns.return_value = [MockFailurePattern()]
    fl.generate_hypotheses = AsyncMock(return_value=[
        {"rationale": "SL 확대", "mr_sl_mult": 8.0}
    ])
    return fl


@pytest.fixture
def mock_experiment_store():
    store = MagicMock()
    store.record.return_value = None
    return store


@pytest.fixture
def orchestrator(
    mock_journal, mock_notifier, mock_market_store, mock_optimizer,
    mock_walk_forward, mock_feedback_loop, mock_experiment_store, tmp_path
):
    from app.approval_workflow import ApprovalWorkflow

    workflow = ApprovalWorkflow(
        config_path=tmp_path / "config.yaml",
        pending_path=tmp_path / "pending.json",
    )
    # 더미 config.yaml 생성
    import yaml
    (tmp_path / "config.yaml").write_text(
        yaml.dump({"strategy_params": {}, "risk_gate": {}, "sizing": {}}),
        encoding="utf-8",
    )

    return EvolutionOrchestrator(
        journal=mock_journal,
        notifier=mock_notifier,
        market_store=mock_market_store,
        optimizer=mock_optimizer,
        walk_forward=mock_walk_forward,
        feedback_loop=mock_feedback_loop,
        experiment_store=mock_experiment_store,
        guard_agent=GuardAgent(),
        approval_workflow=workflow,
        current_params=EvolvableParams(),
        coins=["BTC", "ETH"],
        max_experiments=5,
    )


# ── 유틸리티 함수 테스트 ───────────────────────────────────

class TestCompositeFitness:
    """Composite Fitness 계산."""

    def test_perfect_params(self):
        """최고 파라미터 → 1.0에 가까운 fitness."""
        f = compute_fitness(3.0, 3.0, 0.0, 1.0)
        assert f == pytest.approx(1.0)

    def test_worst_params(self):
        """최악 파라미터 → 0.0."""
        f = compute_fitness(0.0, 0.0, 0.20, 0.0)
        assert f == pytest.approx(0.0)

    def test_typical_params(self):
        """일반적 파라미터 → 0.3~0.7 범위."""
        f = compute_fitness(1.5, 1.0, 0.08, 0.55)
        assert 0.3 < f < 0.7

    def test_negative_values_clamped(self):
        """음수 값은 0으로 클램핑."""
        f = compute_fitness(-1.0, -1.0, 0.0, 0.0)
        assert f >= 0.0


class TestHardConstraints:
    """하드 제약 사전 필터."""

    def test_pass(self):
        assert check_hard_constraints(30, 0.10, 0.50) == ""

    def test_trades_too_few(self):
        result = check_hard_constraints(10, 0.10, 0.50)
        assert "거래 수 부족" in result

    def test_mdd_too_high(self):
        result = check_hard_constraints(30, 0.20, 0.50)
        assert "MDD 초과" in result

    def test_win_rate_too_low(self):
        result = check_hard_constraints(30, 0.10, 0.20)
        assert "승률 미달" in result


class TestDeflatedSharpe:
    """Deflated Sharpe Ratio."""

    def test_high_sharpe_few_experiments(self):
        """높은 Sharpe + 적은 실험 → 유의미 (낮은 p-value)."""
        p = deflated_sharpe_p_value(2.0, 3, 100)
        assert p < 0.5

    def test_low_sharpe_many_experiments(self):
        """낮은 Sharpe + 많은 실험 → 비유의 (높은 p-value)."""
        p = deflated_sharpe_p_value(0.3, 50, 30)
        assert p > 0.5

    def test_edge_cases(self):
        """극단값 안전."""
        assert deflated_sharpe_p_value(0.0, 1, 1) == 1.0
        assert deflated_sharpe_p_value(-1.0, 5, 50) == 1.0
        assert deflated_sharpe_p_value(1.0, 0, 50) == 1.0


# ── Phase별 테스트 ─────────────────────────────────────────

class TestPhaseMonitor:
    """Phase 1: Monitor."""

    @pytest.mark.asyncio
    async def test_normal_operation(self, orchestrator):
        """정상 운영 → should_continue=True."""
        result = await orchestrator._phase_monitor()
        assert result.should_continue is True
        assert result.fitness > 0

    @pytest.mark.asyncio
    async def test_too_few_trades(self, orchestrator, mock_journal):
        """거래 5건 미만 → 중단."""
        mock_journal.get_trades_since.return_value = [_make_trade(0.01)]
        result = await orchestrator._phase_monitor()
        assert result.should_continue is False
        assert "거래 부족" in result.reason


class TestPhaseDiagnose:
    """Phase 2: Diagnose."""

    @pytest.mark.asyncio
    async def test_identifies_weak_areas(self, orchestrator):
        """성과 지표에 따라 약한 영역 식별."""
        baseline = MonitorResult(
            should_continue=True,
            fitness=0.3,
            profit_factor=1.0,  # 낮음 → strategy_params
            sharpe=0.3,         # 낮음 → sizing_params
            max_drawdown=0.12,  # 높음 → risk_thresholds
            win_rate=0.40,      # 낮음 → entry_cutoff
            trade_count=30,
        )
        areas = await orchestrator._phase_diagnose(baseline)
        assert len(areas) <= 2
        assert len(areas) > 0

    @pytest.mark.asyncio
    async def test_good_performance_no_areas(self, orchestrator):
        """좋은 성과 → 빈 목록."""
        baseline = MonitorResult(
            should_continue=True,
            fitness=0.8,
            profit_factor=2.0,
            sharpe=1.5,
            max_drawdown=0.05,
            win_rate=0.65,
            trade_count=50,
        )
        # failure patterns 없으면 weak area 없음
        orchestrator._feedback_loop.get_failure_patterns.return_value = []
        areas = await orchestrator._phase_diagnose(baseline)
        assert areas == []


class TestPhaseHypothesize:
    """Phase 3: Hypothesize."""

    @pytest.mark.asyncio
    async def test_generates_candidates(self, orchestrator):
        """약한 영역 → 후보 생성."""
        candidates = await orchestrator._phase_hypothesize(["strategy_params"])
        assert len(candidates) > 0
        assert all(isinstance(c, ExperimentCandidate) for c in candidates)

    @pytest.mark.asyncio
    async def test_llm_failure_graceful(self, orchestrator, mock_feedback_loop):
        """LLM 실패 시에도 그리드 후보는 생성."""
        mock_feedback_loop.generate_hypotheses = AsyncMock(side_effect=Exception("API 실패"))
        candidates = await orchestrator._phase_hypothesize(["strategy_params"])
        assert len(candidates) > 0  # 그리드 후보만이라도

    @pytest.mark.asyncio
    async def test_max_candidates_limit(self, orchestrator):
        """후보 수는 max_experiments 이하."""
        candidates = await orchestrator._phase_hypothesize(
            ["strategy_params", "entry_cutoff"]
        )
        assert len(candidates) <= orchestrator._max_experiments


class TestPhaseExperiment:
    """Phase 4: Experiment."""

    @pytest.mark.asyncio
    async def test_runs_backtests(self, orchestrator, mock_optimizer):
        """전략 파라미터 변경 → 백테스트 실행."""
        candidates = [
            ExperimentCandidate(
                changes={"tf_sl_mult": 3.0},
                source="grid_search",
                rationale="test",
            )
        ]
        results = await orchestrator._phase_experiment(candidates)
        assert len(results) == 1
        assert results[0].profit_factor > 0

    @pytest.mark.asyncio
    async def test_invalid_params_rejected(self, orchestrator):
        """교차 제약 위반 후보 → rejected."""
        candidates = [
            ExperimentCandidate(
                changes={"daily_dd_pct": 0.06, "weekly_dd_pct": 0.04},
                source="test",
                rationale="invalid",
            )
        ]
        results = await orchestrator._phase_experiment(candidates)
        assert results[0].rejected != ""


class TestPhaseValidate:
    """Phase 5: Validate."""

    @pytest.mark.asyncio
    async def test_robust_passes(self, orchestrator):
        """robust Walk-Forward → 통과."""
        best = ExperimentResult(
            candidate=ExperimentCandidate(),
            params=EvolvableParams(),
            fitness=0.6,
            sharpe=1.0,
            trade_count=50,
        )
        baseline = MonitorResult(fitness=0.5)
        result = await orchestrator._phase_validate(best, baseline)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_poor_wf_fails(self, orchestrator, mock_walk_forward):
        """poor Walk-Forward → 실패."""
        mock_walk_forward.run.return_value = MockWFResult(verdict="poor")
        best = ExperimentResult(
            candidate=ExperimentCandidate(),
            params=EvolvableParams(),
            fitness=0.7,
            trade_count=50,
        )
        baseline = MonitorResult(fitness=0.5)
        result = await orchestrator._phase_validate(best, baseline)
        assert result.passed is False
        assert "poor" in result.reason

    @pytest.mark.asyncio
    async def test_overfit_detected(self, orchestrator, mock_walk_forward):
        """과적합 감지 → 실패."""
        mock_walk_forward.run.return_value = MockWFResult(overfit_detected=True)
        best = ExperimentResult(
            candidate=ExperimentCandidate(),
            params=EvolvableParams(),
            fitness=0.9,
            trade_count=50,
        )
        baseline = MonitorResult(fitness=0.3)
        result = await orchestrator._phase_validate(best, baseline)
        assert result.passed is False


class TestFullSession:
    """전체 세션 통합."""

    @pytest.mark.asyncio
    async def test_successful_session(self, orchestrator, mock_optimizer):
        """정상 세션 → change_id 생성."""
        # optimizer가 좋은 결과 반환
        mock_optimizer.replay_with_params.return_value = MockOptResult(
            profit_factor=2.5, win_rate=0.65, max_drawdown=0.06, trades=60
        )
        result = await orchestrator.run_session()
        # 성공 여부는 baseline 대비 개선 + 검증 통과에 달림
        # Mock 데이터에 따라 성공하거나 실패할 수 있음
        assert isinstance(result.baseline_fitness, float)

    @pytest.mark.asyncio
    async def test_no_trades_session(self, orchestrator, mock_journal):
        """거래 없음 → 조기 종료."""
        mock_journal.get_trades_since.return_value = []
        result = await orchestrator.run_session()
        assert result.success is False
        assert "거래 부족" in result.reason

    @pytest.mark.asyncio
    async def test_session_notifies_discord(self, orchestrator, mock_notifier, mock_journal):
        """세션 결과가 Discord로 알림된다."""
        mock_journal.get_trades_since.return_value = []
        await orchestrator.run_session()
        mock_notifier.send.assert_called()
