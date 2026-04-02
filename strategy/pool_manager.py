"""3풀 자금 관리 모듈.

Core(40%) / Active(50%) / Reserve(10%) 관리.
Pool 잔액 실시간 추적, 자금 이동 인터페이스.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.data_types import Pool

logger = logging.getLogger(__name__)

# 기본 배분 비율
DEFAULT_RATIOS: dict[Pool, float] = {
    Pool.CORE: 0.40,
    Pool.ACTIVE: 0.50,
    Pool.RESERVE: 0.10,
}

# Pool별 동시 포지션 제한
MAX_POSITIONS: dict[Pool, int] = {
    # Pool.CORE: 3,  # 원래 값
    # Pool.ACTIVE: 5,
    Pool.CORE: 5,  # 3→5 (D_적극 시나리오)
    Pool.ACTIVE: 8,  # 5→8 (D_적극 시나리오)
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
                pool.value,
                amount,
                self._pools[pool].available,
                self._pools[pool].position_count,
                MAX_POSITIONS[pool],
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

    def reclaim(self, pool: Pool, amount: float) -> None:
        """반환된 자금을 다시 할당 상태로 되돌린다 (포지션 복원 시 사용).

        Args:
            pool: 풀 유형.
            amount: 복원할 금액.
        """
        state = self._pools[pool]
        state.allocated += amount
        state.position_count += 1

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
            logger.warning("이관 실패: %s→%s, 도착 풀 포지션 초과", from_pool.value, to_pool.value)
            # 롤백
            src.allocated += amount
            src.position_count += 1
            return False

        dst.allocated += amount
        dst.position_count += 1

        # total_balance도 이동 (잔액 정합성)
        src.total_balance = max(0.0, src.total_balance - amount)
        dst.total_balance += amount

        logger.info(
            "Pool 이관: %s→%s, 금액=%.0f",
            from_pool.value,
            to_pool.value,
            amount,
        )
        return True

    def update_equity(self, total_equity: float) -> None:
        """전체 에퀴티를 업데이트한다. 각 풀 비율을 유지하며 갱신."""
        if total_equity <= 0:
            return
        # 현재 각 풀의 비율을 유지하며 갱신 (재분배 없음)
        current_total = sum(p.total_balance for p in self._pools.values())
        if current_total <= 0:
            # 초기화 시에만 기본 비율로 분배
            for pool_type, pool in self._pools.items():
                pool.total_balance = total_equity * DEFAULT_RATIOS[pool_type]
            self._total_equity = total_equity
            return
        # 기존 비율 유지하며 스케일링
        scale = total_equity / current_total
        for pool in self._pools.values():
            pool.total_balance *= scale
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

    def reconcile(self, positions: dict) -> None:
        """실제 포지션 기준으로 Pool 할당 상태를 재계산한다.

        Args:
            positions: 현재 활성 포지션 딕셔너리 {symbol: Position}.
        """
        actual_alloc: dict[Pool, float] = {p: 0.0 for p in Pool}
        actual_count: dict[Pool, int] = {p: 0 for p in Pool}

        for pos in positions.values():
            pool = pos.pool if isinstance(pos.pool, Pool) else Pool(pos.pool)
            actual_alloc[pool] += pos.size_krw
            actual_count[pool] += 1

        corrected = False
        for pool in Pool:
            state = self._pools[pool]
            if (
                abs(state.allocated - actual_alloc[pool]) > 1.0
                or state.position_count != actual_count[pool]
            ):
                logger.warning(
                    "Pool %s 정합성 보정: allocated %.0f→%.0f, count %d→%d",
                    pool.value,
                    state.allocated,
                    actual_alloc[pool],
                    state.position_count,
                    actual_count[pool],
                )
                state.allocated = actual_alloc[pool]
                state.position_count = actual_count[pool]
                corrected = True

        if corrected:
            logger.info("Pool reconciliation 완료")

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
