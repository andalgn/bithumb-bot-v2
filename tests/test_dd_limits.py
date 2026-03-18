"""DD Kill Switch 테스트."""

import pytest

from risk.dd_limits import DDLimits


@pytest.fixture
def dd() -> DDLimits:
    """테스트용 DDLimits."""
    d = DDLimits(daily_pct=0.04, weekly_pct=0.08, monthly_pct=0.12, total_pct=0.20)
    d.initialize(1_000_000)
    return d


class TestDDLimits:
    """DD Kill Switch 테스트."""

    def test_no_block_initially(self, dd: DDLimits) -> None:
        """초기 상태에서 차단 없음."""
        blocked, reason = dd.is_buy_blocked()
        assert blocked is False

    def test_daily_dd_block(self, dd: DDLimits) -> None:
        """일일 DD 4% 초과 시 차단."""
        dd._state.current_equity = 950_000  # 5% DD
        blocked, reason = dd.is_buy_blocked()
        assert blocked is True
        assert "P5" in reason

    def test_total_dd_block(self, dd: DDLimits) -> None:
        """총 DD 20% 초과 시 차단 (P2 우선)."""
        dd._state.current_equity = 750_000  # 25% DD
        blocked, reason = dd.is_buy_blocked()
        assert blocked is True
        assert "P2" in reason

    def test_sell_not_blocked(self, dd: DDLimits) -> None:
        """is_buy_blocked은 BUY만 차단. SELL 여부는 호출측에서 판단."""
        dd._state.current_equity = 750_000
        blocked, reason = dd.is_buy_blocked()
        assert blocked is True  # BUY는 차단

    def test_hwm_update(self, dd: DDLimits) -> None:
        """High-water mark 갱신."""
        dd.update_equity(1_100_000)
        assert dd._state.daily_base == 1_100_000
        assert dd._state.total_base == 1_100_000

    def test_state_dump_load(self, dd: DDLimits) -> None:
        """상태 직렬화/역직렬화."""
        dd.update_equity(900_000)
        state = dd.dump_state()
        assert state["current_equity"] == 900_000

        dd2 = DDLimits()
        dd2.load_state(state)
        assert dd2.state.current_equity == 900_000
