"""3풀 자금 관리 모듈.

Core(60%) / Active(30%) / Reserve(10%) 관리.
Pool 잔액 실시간 추적, 자금 이동 인터페이스.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.data_types import Pool

logger = logging.getLogger(__name__)

# 기본 배분 비율
DEFAULT_RATIOS: dict[Pool, float] = {
    Pool.CORE: 0.60,
    Pool.ACTIVE: 0.30,
    Pool.RESERVE: 0.10,
}

# Pool별 동시 포지션 제한
MAX_POSITIONS: dict[Pool, int] = {
    Pool.CORE: 3,
    Pool.ACTIVE: 5,
    Pool.RESERVE: 1,
}


@dataclass
class PoolState:
    """풀별 상태."""

    total_balance: float  # Pool 전체 잔액
    allocated: float  # 포지션에 할당된 금액
    position_count: int  # 현재 포지션 수

    @property
    def available(self) -> float:
        """가용 잔액."""
        return max(0.0, self.total_balance - self.allocated)


class PoolManager:
    """3풀 자금 관리자."""

    def __init__(self, total_equity: float) -> None:
        """초기화.

        Args:
            total_equity: 총 자산(KRW).
        """
        self._total_equity = total_equity
        self._pools: dict[Pool, PoolState] = {}
        self._initialize(total_equity)

    def _initialize(self, equity: float) -> None:
        """풀을 초기 배분한다."""
        for pool, ratio in DEFAULT_RATIOS.items():
            self._pools[pool] = PoolState(
                total_balance=equity * ratio,
                allocated=0.0,
                position_count=0,
            )
        logger.info(
            "Pool 초기화: Core=%.0f, Active=%.0f, Reserve=%.0f",
            self._pools[Pool.CORE].total_balance,
            self._pools[Pool.ACTIVE].total_balance,
            self._pools[Pool.RESERVE].total_balance,
        )

    def get_available(self, pool: Pool) -> float:
        """가용 잔액을 반환한다.

        Args:
            pool: 풀 유형.

        Returns:
            가용 금액(KRW).
        """
        return self._pools[pool].available

    def get_balance(self, pool: Pool) -> float:
        """풀 전체 잔액을 반환한다."""
        return self._pools[pool].total_balance

    def get_position_count(self, pool: Pool) -> int:
        """현재 포지션 수를 반환한다."""
        return self._pools[pool].position_count

    def can_allocate(self, pool: Pool, amount: float) -> bool:
        """할당 가능한지 확인한다.

        Args:
            pool: 풀 유형.
            amount: 할당할 금액.

        Returns:
            할당 가능 여부.
        """
        state = self._pools[pool]
        if state.position_count >= MAX_POSITIONS[pool]:
            return False
        return state.available >= amount

    def allocate(self, pool: Pool, amount: float) -> bool:
        """자금을 할당한다 (포지션 진입 시).

        Args:
            pool: 풀 유형.
            amount: 할당 금액.

        Returns:
            성공 여부.
        """
        if not self.can_allocate(pool, amount):
            logger.warning(
                "Pool %s 할당 실패: 요청=%.0f, 가용=%.0f, 포지션=%d/%d",
                pool.value, amount, self._pools[pool].available,
                self._pools[pool].position_count, MAX_POSITIONS[pool],
            )
            return False

        self._pools[pool].allocated += amount
        self._pools[pool].position_count += 1
        return True

    def release(self, pool: Pool, amount: float, pnl: float = 0.0) -> None:
        """자금을 반환한다 (포지션 청산 시).

        Args:
            pool: 풀 유형.
            amount: 원래 할당 금액.
            pnl: 실현 손익(KRW).
        """
        state = self._pools[pool]
        state.allocated = max(0.0, state.allocated - amount)
        state.position_count = max(0, state.position_count - 1)
        # PnL 반영
        state.total_balance += pnl

    def transfer(self, from_pool: Pool, to_pool: Pool, amount: float) -> bool:
        """풀 간 자금을 이동한다 (승격/강등 시).

        Args:
            from_pool: 출발 풀.
            to_pool: 도착 풀.
            amount: 이동 금액.

        Returns:
            성공 여부.
        """
        src = self._pools[from_pool]
        dst = self._pools[to_pool]

        # 출발 풀에서 allocated 감소
        src.allocated = max(0.0, src.allocated - amount)
        src.position_count = max(0, src.position_count - 1)

        # 도착 풀에 allocated 증가
        if dst.position_count >= MAX_POSITIONS[to_pool]:
            logger.warning(
                "이관 실패: %s→%s, 도착 풀 포지션 초과", from_pool.value, to_pool.value
            )
            # 롤백
            src.allocated += amount
            src.position_count += 1
            return False

        dst.allocated += amount
        dst.position_count += 1

        logger.info(
            "Pool 이관: %s→%s, 금액=%.0f",
            from_pool.value, to_pool.value, amount,
        )
        return True

    def update_equity(self, total_equity: float) -> None:
        """총 자산 변동 시 풀 잔액을 갱신한다.

        현재 allocated는 유지하고, 미할당분을 비율대로 재배분.
        """
        total_allocated = sum(s.allocated for s in self._pools.values())
        free = total_equity - total_allocated
        if free < 0:
            free = 0

        for pool, ratio in DEFAULT_RATIOS.items():
            state = self._pools[pool]
            state.total_balance = state.allocated + free * ratio

        self._total_equity = total_equity

    @property
    def total_exposure(self) -> float:
        """총 익스포저를 반환한다."""
        return sum(s.allocated for s in self._pools.values())

    @property
    def utilization_pct(self) -> float:
        """자금 활용률을 반환한다."""
        if self._total_equity <= 0:
            return 0.0
        return self.total_exposure / self._total_equity

    def dump_state(self) -> dict:
        """상태를 딕셔너리로 반환한다."""
        return {
            "total_equity": self._total_equity,
            "pools": {
                pool.value: {
                    "total_balance": state.total_balance,
                    "allocated": state.allocated,
                    "position_count": state.position_count,
                }
                for pool, state in self._pools.items()
            },
        }

    def load_state(self, data: dict) -> None:
        """저장된 상태를 복원한다."""
        self._total_equity = data.get("total_equity", self._total_equity)
        pools_data = data.get("pools", {})
        for pool in Pool:
            if pool.value in pools_data:
                pd = pools_data[pool.value]
                self._pools[pool] = PoolState(
                    total_balance=pd.get("total_balance", 0),
                    allocated=pd.get("allocated", 0),
                    position_count=pd.get("position_count", 0),
                )
