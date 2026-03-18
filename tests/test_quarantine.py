"""격리 시스템 테스트."""


import pytest

from execution.quarantine import QuarantineManager


@pytest.fixture
def qm(tmp_path) -> QuarantineManager:
    """테스트용 QuarantineManager."""
    return QuarantineManager(
        coin_fail_limit=3,
        coin_quarantine_sec=120,
        global_fail_limit=8,
        global_quarantine_sec=60,
        auth_quarantine_sec=600,
        state_path=str(tmp_path / "quarantine.json"),
    )


class TestQuarantine:
    """격리 테스트."""

    def test_no_quarantine_initially(self, qm: QuarantineManager) -> None:
        """초기 상태에서 격리 없음."""
        assert qm.is_blocked("BTC") is False

    def test_coin_quarantine_after_3_failures(self, qm: QuarantineManager) -> None:
        """종목 3회 실패 → 격리."""
        for _ in range(3):
            qm.record_failure("BTC")
        assert qm.is_coin_quarantined("BTC") is True
        assert qm.is_coin_quarantined("ETH") is False

    def test_auth_quarantine(self, qm: QuarantineManager) -> None:
        """인증 오류 → 전체 격리."""
        qm.record_failure("BTC", is_auth_error=True)
        assert qm.is_auth_quarantined() is True
        assert qm.is_blocked("BTC") is True
        assert qm.is_blocked("ETH") is True

    def test_state_persistence(self, tmp_path) -> None:
        """상태 영속화 및 복원."""
        path = str(tmp_path / "quarantine.json")
        qm1 = QuarantineManager(state_path=path)
        qm1.record_failure("BTC", is_auth_error=True)

        qm2 = QuarantineManager(state_path=path)
        assert qm2.is_auth_quarantined() is True
