"""Pool Manager 테스트."""

import pytest

from app.data_types import Pool
from strategy.pool_manager import PoolManager


@pytest.fixture
def pm() -> PoolManager:
    """총 100만원 PoolManager."""
    return PoolManager(1_000_000)


class TestPoolManager:
    """3풀 자금 관리 테스트."""

    def test_initial_allocation(self, pm: PoolManager) -> None:
        """초기 배분: Core 40%, Active 50%, Reserve 10%."""
        assert pm.get_balance(Pool.CORE) == pytest.approx(400_000)
        assert pm.get_balance(Pool.ACTIVE) == pytest.approx(500_000)
        assert pm.get_balance(Pool.RESERVE) == pytest.approx(100_000)

    def test_allocate_success(self, pm: PoolManager) -> None:
        """할당 성공."""
        assert pm.allocate(Pool.ACTIVE, 10_000) is True
        assert pm.get_available(Pool.ACTIVE) == pytest.approx(490_000)
        assert pm.get_position_count(Pool.ACTIVE) == 1

    def test_allocate_exceeds_balance(self, pm: PoolManager) -> None:
        """잔액 초과 할당 실패."""
        assert pm.allocate(Pool.ACTIVE, 600_000) is False

    def test_allocate_max_positions(self, pm: PoolManager) -> None:
        """최대 포지션 초과 할당 실패 (Active 최대 8건, D_적극 시나리오)."""
        for _ in range(8):
            pm.allocate(Pool.ACTIVE, 10_000)
        assert pm.allocate(Pool.ACTIVE, 10_000) is False

    def test_release_with_profit(self, pm: PoolManager) -> None:
        """청산 + 수익 반영."""
        pm.allocate(Pool.ACTIVE, 10_000)
        pm.release(Pool.ACTIVE, 10_000, pnl=5_000)
        assert pm.get_balance(Pool.ACTIVE) == pytest.approx(505_000)
        assert pm.get_position_count(Pool.ACTIVE) == 0

    def test_release_with_loss(self, pm: PoolManager) -> None:
        """청산 + 손실 반영."""
        pm.allocate(Pool.ACTIVE, 10_000)
        pm.release(Pool.ACTIVE, 10_000, pnl=-3_000)
        assert pm.get_balance(Pool.ACTIVE) == pytest.approx(497_000)

    def test_transfer_active_to_core(self, pm: PoolManager) -> None:
        """승격: Active → Core 이관."""
        pm.allocate(Pool.ACTIVE, 20_000)
        assert pm.transfer(Pool.ACTIVE, Pool.CORE, 20_000) is True
        assert pm.get_position_count(Pool.ACTIVE) == 0
        assert pm.get_position_count(Pool.CORE) == 1

    def test_transfer_core_to_active(self, pm: PoolManager) -> None:
        """강등: Core → Active 이관."""
        pm.allocate(Pool.CORE, 50_000)
        assert pm.transfer(Pool.CORE, Pool.ACTIVE, 50_000) is True

    def test_transfer_fails_when_full(self, pm: PoolManager) -> None:
        """도착 풀 포지션 초과 시 이관 실패."""
        for _ in range(5):  # Core 최대 5건 (D_적극 시나리오)
            pm.allocate(Pool.CORE, 10_000)
        pm.allocate(Pool.ACTIVE, 10_000)
        assert pm.transfer(Pool.ACTIVE, Pool.CORE, 10_000) is False

    def test_total_exposure(self, pm: PoolManager) -> None:
        """총 익스포저 계산."""
        pm.allocate(Pool.ACTIVE, 10_000)
        pm.allocate(Pool.CORE, 50_000)
        assert pm.total_exposure == pytest.approx(60_000)

    def test_utilization(self, pm: PoolManager) -> None:
        """활용률 계산."""
        pm.allocate(Pool.ACTIVE, 100_000)
        assert pm.utilization_pct == pytest.approx(0.10)

    def test_dump_load_state(self, pm: PoolManager) -> None:
        """상태 직렬화/역직렬화."""
        pm.allocate(Pool.ACTIVE, 15_000)
        state = pm.dump_state()

        pm2 = PoolManager(1_000_000)
        pm2.load_state(state)
        assert pm2.get_position_count(Pool.ACTIVE) == 1
        assert pm2.get_available(Pool.ACTIVE) == pytest.approx(
            pm.get_available(Pool.ACTIVE)
        )
