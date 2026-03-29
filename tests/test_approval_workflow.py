"""approval_workflow 단위 테스트."""

import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import yaml

from app.approval_workflow import ApprovalWorkflow, PendingChange


@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    """테스트용 임시 디렉토리에 config.yaml 생성."""
    config = {
        "run_mode": "PAPER",
        "strategy_params": {
            "trend_follow": {"sl_mult": 5.0, "tp_rr": 1.5},
            "mean_reversion": {"sl_mult": 7.0},
        },
        "risk_gate": {"daily_dd_pct": 0.04, "weekly_dd_pct": 0.08},
        "sizing": {"active_risk_pct": 0.07},
    }
    config_path = tmp_path / "configs" / "config.yaml"
    config_path.parent.mkdir(parents=True)
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, sort_keys=False)

    (tmp_path / "data").mkdir()
    return tmp_path


@pytest.fixture
def workflow(tmp_dir: Path) -> ApprovalWorkflow:
    return ApprovalWorkflow(
        config_path=tmp_dir / "configs" / "config.yaml",
        pending_path=tmp_dir / "data" / "pending_changes.json",
    )


@pytest.fixture
def sample_change() -> PendingChange:
    return PendingChange(
        change_id="abc12345",
        proposed_params={"tf_sl_mult": 3.0, "daily_dd_pct": 0.04},
        current_params={"tf_sl_mult": 5.0, "daily_dd_pct": 0.04},
        changes={"tf_sl_mult": [5.0, 3.0]},
        risk_score=0.12,
        risk_level="low",
        fitness_improvement=0.05,
        rationale="backtest PF 1.82 → 1.95",
        experiment_count=8,
        created_at=datetime.now().isoformat(),
    )


class TestPropose:
    """변경 제안."""

    def test_propose_returns_change_id(
        self, workflow: ApprovalWorkflow, sample_change: PendingChange
    ):
        """propose는 change_id를 반환한다."""
        cid = workflow.propose(sample_change)
        assert cid == "abc12345"

    def test_propose_persists_to_file(
        self, workflow: ApprovalWorkflow, sample_change: PendingChange, tmp_dir: Path
    ):
        """propose 후 JSON 파일에 저장된다."""
        workflow.propose(sample_change)
        path = tmp_dir / "data" / "pending_changes.json"
        assert path.exists()
        with open(path) as f:
            data = json.load(f)
        assert "abc12345" in data
        assert data["abc12345"]["status"] == "pending"

    def test_propose_multiple(
        self, workflow: ApprovalWorkflow, sample_change: PendingChange
    ):
        """여러 건 제안 가능."""
        workflow.propose(sample_change)
        change2 = PendingChange(
            change_id="def67890",
            proposed_params={"mr_sl_mult": 6.0},
            current_params={"mr_sl_mult": 7.0},
            changes={"mr_sl_mult": [7.0, 6.0]},
            risk_score=0.08,
            risk_level="low",
            fitness_improvement=0.03,
            rationale="test",
            experiment_count=5,
            created_at=datetime.now().isoformat(),
        )
        workflow.propose(change2)
        pending = workflow.list_pending()
        assert len(pending) == 2


class TestApprove:
    """변경 승인."""

    def test_approve_updates_config(
        self, workflow: ApprovalWorkflow, tmp_dir: Path
    ):
        """승인 시 config.yaml이 업데이트된다."""
        change = PendingChange(
            change_id="cfg_test",
            proposed_params={
                "tf_sl_mult": 3.0, "tf_tp_rr": 1.5, "tf_cutoff": 75,
                "tf_w_trend_align": 30.0, "tf_w_macd": 25.0,
                "tf_w_volume": 20.0, "tf_w_rsi_pullback": 15.0,
                "tf_w_supertrend": 10.0,
                "mr_sl_mult": 7.0, "mr_tp_rr": 1.5,
                "bo_sl_mult": 2.0, "bo_tp_rr": 3.0,
                "dca_sl_pct": 0.05, "dca_tp_pct": 0.03,
                "daily_dd_pct": 0.04, "weekly_dd_pct": 0.08,
                "consecutive_loss_limit": 3, "cooldown_min": 60,
                "max_exposure_pct": 0.9,
                "active_risk_pct": 0.07, "pool_cap_pct": 0.25,
                "defense_mult_min": 0.3, "defense_mult_max": 1.0,
                "vol_target_mult_min": 0.8, "vol_target_mult_max": 1.5,
                "regime_adx_strong": 25, "regime_atr_spike_mult": 2.5,
                "l1_volume_ratio": 0.8, "l1_momentum_burst_pct": 0.015,
                "promotion_profit_pct": 0.012,
                "promotion_hold_bars": 2, "promotion_adx_min": 20,
            },
            current_params={
                "tf_sl_mult": 5.0, "tf_tp_rr": 1.5, "tf_cutoff": 75,
                "tf_w_trend_align": 30.0, "tf_w_macd": 25.0,
                "tf_w_volume": 20.0, "tf_w_rsi_pullback": 15.0,
                "tf_w_supertrend": 10.0,
                "mr_sl_mult": 7.0, "mr_tp_rr": 1.5,
                "bo_sl_mult": 2.0, "bo_tp_rr": 3.0,
                "dca_sl_pct": 0.05, "dca_tp_pct": 0.03,
                "daily_dd_pct": 0.04, "weekly_dd_pct": 0.08,
                "consecutive_loss_limit": 3, "cooldown_min": 60,
                "max_exposure_pct": 0.9,
                "active_risk_pct": 0.07, "pool_cap_pct": 0.25,
                "defense_mult_min": 0.3, "defense_mult_max": 1.0,
                "vol_target_mult_min": 0.8, "vol_target_mult_max": 1.5,
                "regime_adx_strong": 25, "regime_atr_spike_mult": 2.5,
                "l1_volume_ratio": 0.8, "l1_momentum_burst_pct": 0.015,
                "promotion_profit_pct": 0.012,
                "promotion_hold_bars": 2, "promotion_adx_min": 20,
            },
            changes={"tf_sl_mult": [5.0, 3.0]},
            risk_score=0.1,
            risk_level="low",
            fitness_improvement=0.05,
            rationale="test",
            experiment_count=5,
            created_at=datetime.now().isoformat(),
        )
        workflow.propose(change)
        result = workflow.approve("cfg_test")
        assert result is True

        # config.yaml 확인
        config_path = tmp_dir / "configs" / "config.yaml"
        with open(config_path) as f:
            raw = yaml.safe_load(f)
        assert raw["strategy_params"]["trend_follow"]["sl_mult"] == 3.0

    def test_approve_creates_backup(
        self, workflow: ApprovalWorkflow, sample_change: PendingChange, tmp_dir: Path
    ):
        """승인 시 백업 파일이 생성된다."""
        workflow.propose(sample_change)
        workflow.approve("abc12345")
        backups = list((tmp_dir / "configs").glob("*.bak.*"))
        assert len(backups) >= 1

    def test_approve_changes_status(
        self, workflow: ApprovalWorkflow, sample_change: PendingChange
    ):
        """승인 후 status가 approved로 변경된다."""
        workflow.propose(sample_change)
        workflow.approve("abc12345")
        change = workflow.get("abc12345")
        assert change is not None
        assert change.status == "approved"

    def test_approve_nonexistent_fails(self, workflow: ApprovalWorkflow):
        """존재하지 않는 change_id → False."""
        assert workflow.approve("nonexistent") is False

    def test_approve_already_approved_fails(
        self, workflow: ApprovalWorkflow, sample_change: PendingChange
    ):
        """이미 승인된 변경 재승인 → False."""
        workflow.propose(sample_change)
        workflow.approve("abc12345")
        assert workflow.approve("abc12345") is False


class TestReject:
    """변경 거부."""

    def test_reject_changes_status(
        self, workflow: ApprovalWorkflow, sample_change: PendingChange
    ):
        """거부 후 status가 rejected로 변경된다."""
        workflow.propose(sample_change)
        result = workflow.reject("abc12345")
        assert result is True
        change = workflow.get("abc12345")
        assert change is not None
        assert change.status == "rejected"

    def test_reject_nonexistent_fails(self, workflow: ApprovalWorkflow):
        """존재하지 않는 change_id → False."""
        assert workflow.reject("nonexistent") is False


class TestListPending:
    """대기 목록 조회."""

    def test_empty_initially(self, workflow: ApprovalWorkflow):
        """초기 상태에서 빈 목록."""
        assert workflow.list_pending() == []

    def test_approved_not_in_pending(
        self, workflow: ApprovalWorkflow, sample_change: PendingChange
    ):
        """승인된 변경은 pending 목록에 없다."""
        workflow.propose(sample_change)
        workflow.approve("abc12345")
        assert len(workflow.list_pending()) == 0


class TestExpire:
    """만료 처리."""

    def test_expire_old_changes(
        self, workflow: ApprovalWorkflow, tmp_dir: Path
    ):
        """48시간 이상 경과한 pending → expired."""
        old_time = (datetime.now() - timedelta(hours=50)).isoformat()
        change = PendingChange(
            change_id="old_one",
            proposed_params={},
            current_params={},
            changes={},
            risk_score=0.1,
            risk_level="low",
            fitness_improvement=0.0,
            rationale="test",
            experiment_count=0,
            created_at=old_time,
        )
        workflow.propose(change)
        expired = workflow.expire_old(hours=48)
        assert expired == 1
        result = workflow.get("old_one")
        assert result is not None
        assert result.status == "expired"

    def test_recent_not_expired(
        self, workflow: ApprovalWorkflow, sample_change: PendingChange
    ):
        """최근 변경은 만료되지 않는다."""
        workflow.propose(sample_change)
        expired = workflow.expire_old(hours=48)
        assert expired == 0


class TestGet:
    """단건 조회."""

    def test_get_existing(
        self, workflow: ApprovalWorkflow, sample_change: PendingChange
    ):
        """존재하는 change_id → PendingChange."""
        workflow.propose(sample_change)
        result = workflow.get("abc12345")
        assert result is not None
        assert result.change_id == "abc12345"

    def test_get_nonexistent(self, workflow: ApprovalWorkflow):
        """없는 change_id → None."""
        assert workflow.get("nope") is None


class TestDeepMerge:
    """중첩 딕셔너리 병합."""

    def test_simple_merge(self):
        base = {"a": 1, "b": 2}
        patch = {"b": 3, "c": 4}
        ApprovalWorkflow._deep_merge(base, patch)
        assert base == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self):
        base = {"strategy_params": {"trend_follow": {"sl_mult": 5.0, "tp_rr": 1.5}}}
        patch = {"strategy_params": {"trend_follow": {"sl_mult": 3.0}}}
        ApprovalWorkflow._deep_merge(base, patch)
        assert base["strategy_params"]["trend_follow"]["sl_mult"] == 3.0
        assert base["strategy_params"]["trend_follow"]["tp_rr"] == 1.5  # 유지

    def test_new_section_added(self):
        base = {"a": 1}
        patch = {"b": {"c": 2}}
        ApprovalWorkflow._deep_merge(base, patch)
        assert base["b"]["c"] == 2
