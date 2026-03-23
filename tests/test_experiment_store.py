"""ExperimentStore 테스트."""

from __future__ import annotations

from pathlib import Path

from strategy.experiment_store import ExperimentStore


class TestExperimentStore:
    """실험 기록 저장 테스트."""

    def test_record_and_query(self, tmp_path: Path) -> None:
        store = ExperimentStore(db_path=str(tmp_path / "exp.db"))
        store.record(
            source="darwin",
            strategy="mean_reversion",
            params={"sl_mult": 7.0},
            pf=1.2,
            mdd=0.08,
            trades=35,
            verdict="keep",
        )
        results = store.get_history("mean_reversion", limit=10)
        assert len(results) == 1
        assert results[0]["verdict"] == "keep"

    def test_count_failures(self, tmp_path: Path) -> None:
        store = ExperimentStore(db_path=str(tmp_path / "exp.db"))
        for i in range(4):
            store.record(
                source="auto_research",
                strategy="mean_reversion",
                params={"sl_mult": 8.0 + i * 0.1},
                pf=0.8,
                mdd=0.12,
                trades=30,
                verdict="revert",
            )
        count = store.count_similar_failures(
            strategy="mean_reversion",
            param_key="sl_mult",
            direction="increase",
        )
        assert count >= 3

    def test_param_change_log(self, tmp_path: Path) -> None:
        store = ExperimentStore(db_path=str(tmp_path / "exp.db"))
        store.log_param_change(
            source="darwin",
            strategy="mean_reversion",
            old_params={"sl_mult": 5.0},
            new_params={"sl_mult": 6.2},
            backup_path="configs/config.yaml.bak.20260323",
            baseline_pf=1.15,
        )
        active = store.get_active_changes()
        assert len(active) == 1
        assert active[0]["status"] == "monitoring"

    def test_rollback_change(self, tmp_path: Path) -> None:
        store = ExperimentStore(db_path=str(tmp_path / "exp.db"))
        store.log_param_change(
            source="darwin",
            strategy="mean_reversion",
            old_params={"sl_mult": 5.0},
            new_params={"sl_mult": 6.2},
            backup_path="configs/config.yaml.bak.20260323",
            baseline_pf=1.15,
        )
        active = store.get_active_changes()
        store.update_change_status(active[0]["id"], "rolled_back")
        updated = store.get_active_changes()
        assert len(updated) == 0
