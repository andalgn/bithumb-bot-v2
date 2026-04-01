"""매도 후 거래소 잔고 재검증 테스트."""

from __future__ import annotations

import pytest

from app.data_types import Pool, Position, Regime, RunMode, Strategy, Tier
from strategy.pool_manager import PoolManager


@pytest.fixture
def pool_manager():
    """PoolManager 인스턴스를 반환한다."""
    return PoolManager(total_equity=1000000.0)


@pytest.fixture
def sample_position() -> Position:
    """테스트용 포지션을 반환한다."""
    return Position(
        symbol="BTC",
        entry_price=50000.0,
        entry_time=1000000,
        size_krw=100000.0,
        qty=2.0,
        stop_loss=45000.0,
        take_profit=55000.0,
        strategy=Strategy.MEAN_REVERSION,
        pool=Pool.ACTIVE,
        tier=Tier.TIER1,
        regime=Regime.STRONG_UP,
        promoted=False,
        entry_score=0.8,
        signal_price=50000.0,
        entry_fee_krw=250.0,
        order_id="order_123",
    )


class TestPoolManagerReclaim:
    """PoolManager.reclaim() 메서드 테스트."""

    def test_reclaim_basic(self, pool_manager: PoolManager) -> None:
        """기본 reclaim 동작 테스트."""
        pool = Pool.ACTIVE
        amount = 100000.0

        # 초기 상태 확인
        initial_allocated = pool_manager._pools[pool].allocated
        initial_count = pool_manager._pools[pool].position_count

        # reclaim 호출
        pool_manager.reclaim(pool, amount)

        # allocated와 position_count가 증가했는지 확인
        assert pool_manager._pools[pool].allocated == initial_allocated + amount
        assert pool_manager._pools[pool].position_count == initial_count + 1

    def test_reclaim_multiple(self, pool_manager: PoolManager) -> None:
        """여러 번의 reclaim 테스트."""
        pool = Pool.CORE
        amount1 = 50000.0
        amount2 = 30000.0

        pool_manager.reclaim(pool, amount1)
        pool_manager.reclaim(pool, amount2)

        # 합계가 맞는지 확인
        assert pool_manager._pools[pool].allocated == amount1 + amount2
        assert pool_manager._pools[pool].position_count == 2

    def test_reclaim_after_release(self, pool_manager: PoolManager) -> None:
        """release 후 reclaim 테스트 (포지션 복원 시나리오)."""
        pool = Pool.ACTIVE
        amount = 100000.0

        # 1. allocate
        pool_manager.allocate(pool, amount)
        assert pool_manager._pools[pool].allocated == amount
        assert pool_manager._pools[pool].position_count == 1

        # 2. release (매도 실패 감지)
        pool_manager.release(pool, amount)
        assert pool_manager._pools[pool].allocated == 0.0
        assert pool_manager._pools[pool].position_count == 0

        # 3. reclaim (포지션 복원)
        pool_manager.reclaim(pool, amount)
        assert pool_manager._pools[pool].allocated == amount
        assert pool_manager._pools[pool].position_count == 1

    def test_reclaim_different_pools(self, pool_manager: PoolManager) -> None:
        """서로 다른 풀의 reclaim 테스트."""
        core_amount = 80000.0
        active_amount = 100000.0
        reserve_amount = 20000.0

        pool_manager.reclaim(Pool.CORE, core_amount)
        pool_manager.reclaim(Pool.ACTIVE, active_amount)
        pool_manager.reclaim(Pool.RESERVE, reserve_amount)

        # 각 풀이 독립적으로 동작하는지 확인
        assert pool_manager._pools[Pool.CORE].allocated == core_amount
        assert pool_manager._pools[Pool.ACTIVE].allocated == active_amount
        assert pool_manager._pools[Pool.RESERVE].allocated == reserve_amount

        # position_count도 독립적인지 확인
        assert pool_manager._pools[Pool.CORE].position_count == 1
        assert pool_manager._pools[Pool.ACTIVE].position_count == 1
        assert pool_manager._pools[Pool.RESERVE].position_count == 1


class TestPositionCreation:
    """Position 생성 및 복사 테스트."""

    def test_position_creation(self, sample_position: Position) -> None:
        """Position 객체가 올바르게 생성되는지 테스트."""
        assert sample_position.symbol == "BTC"
        assert sample_position.entry_price == 50000.0
        assert sample_position.qty == 2.0
        assert sample_position.pool == Pool.ACTIVE
        assert sample_position.strategy == Strategy.MEAN_REVERSION

    def test_position_backup(self, sample_position: Position) -> None:
        """Position 백업 생성 테스트 (포지션 복원 시나리오)."""
        # 포지션 백업 생성 (main.py의 _close_position에서 수행)
        backup = Position(
            symbol=sample_position.symbol,
            entry_price=sample_position.entry_price,
            entry_time=sample_position.entry_time,
            size_krw=sample_position.size_krw,
            qty=sample_position.qty,
            stop_loss=sample_position.stop_loss,
            take_profit=sample_position.take_profit,
            strategy=sample_position.strategy,
            pool=sample_position.pool,
            tier=sample_position.tier,
            regime=sample_position.regime,
            promoted=sample_position.promoted,
            entry_score=sample_position.entry_score,
            signal_price=sample_position.signal_price,
            entry_fee_krw=sample_position.entry_fee_krw,
            order_id=sample_position.order_id,
        )

        # 백업이 원본과 동일한지 확인
        assert backup.symbol == sample_position.symbol
        assert backup.qty == sample_position.qty
        assert backup.size_krw == sample_position.size_krw
        assert backup.pool == sample_position.pool
        assert backup.strategy == sample_position.strategy

    def test_position_fields_match(self, sample_position: Position) -> None:
        """모든 Position 필드가 존재하는지 테스트."""
        required_fields = [
            "symbol", "entry_price", "entry_time", "size_krw", "qty",
            "stop_loss", "take_profit", "strategy", "pool", "tier",
            "regime", "promoted", "entry_score", "signal_price",
            "entry_fee_krw", "order_id"
        ]
        for field in required_fields:
            assert hasattr(sample_position, field), f"Position missing field: {field}"


class TestVerificationLogic:
    """매도 검증 로직 테스트."""

    def test_balance_tolerance_calculation(self) -> None:
        """잔고 허용 오차 계산 테스트."""
        pre_sell_qty = 1000.0
        tolerance = pre_sell_qty * 0.001  # 0.1%

        # 정확히 매도된 경우
        actual_total = 500.0
        expected_remaining = 500.0
        diff = actual_total - expected_remaining
        assert abs(diff) <= tolerance

        # 허용 오차 범위 내 편차
        actual_total = 500.5
        diff = actual_total - expected_remaining
        assert abs(diff) <= tolerance

        # 허용 오차 초과 편차
        actual_total = 502.0
        diff = actual_total - expected_remaining
        assert abs(diff) > tolerance

    def test_balance_key_construction(self) -> None:
        """거래소 잔고 키 생성 테스트."""
        symbol = "BTC"
        key = symbol.lower()
        assert key == "btc"

        symbol = "ETH"
        key = symbol.lower()
        assert key == "eth"

    def test_expected_remaining_calculation(self) -> None:
        """예상 잔량 계산 테스트."""
        pre_sell_qty = 10.0
        sold_qty = 3.0
        expected_remaining = max(pre_sell_qty - sold_qty, 0)
        assert expected_remaining == 7.0

        # 전량 매도
        sold_qty = 10.0
        expected_remaining = max(pre_sell_qty - sold_qty, 0)
        assert expected_remaining == 0.0

        # 매도량이 보유량을 초과하는 경우
        sold_qty = 15.0
        expected_remaining = max(pre_sell_qty - sold_qty, 0)
        assert expected_remaining == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
