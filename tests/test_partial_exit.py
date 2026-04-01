"""부분청산 + 트레일링 테스트."""

import pytest

from app.data_types import Pool, Position, Regime, Strategy, Tier
from execution.partial_exit import (
    ExitAction,
    PartialExitManager,
)


def _make_position(
    symbol: str = "BTC",
    entry_price: float = 50_000_000,
    strategy: Strategy = Strategy.TREND_FOLLOW,
    tier: Tier = Tier.TIER1,
) -> Position:
    """테스트용 포지션."""
    return Position(
        symbol=symbol,
        entry_price=entry_price,
        entry_time=1000,
        size_krw=20_000,  # 부분청산 30% = 6,000원 > 최소 5,000원
        qty=0.0003,
        stop_loss=entry_price * 0.97,
        take_profit=entry_price * 1.05,
        strategy=strategy,
        pool=Pool.ACTIVE,
        tier=tier,
        regime=Regime.STRONG_UP,
    )


@pytest.fixture
def em() -> PartialExitManager:
    """테스트용 PartialExitManager."""
    return PartialExitManager()


class TestStopLoss:
    """손절 테스트 (최우선)."""

    def test_sl_hit(self, em: PartialExitManager) -> None:
        """손절가 이탈 시 전량 청산."""
        pos = _make_position(entry_price=50_000_000)
        em.init_position("BTC")
        decision = em.evaluate(pos, 48_000_000, atr_value=500_000)
        assert decision.action == ExitAction.STOP_LOSS
        assert decision.exit_ratio == 1.0

    def test_above_sl(self, em: PartialExitManager) -> None:
        """손절가 위면 손절 안 함."""
        pos = _make_position(entry_price=50_000_000)
        em.init_position("BTC")
        decision = em.evaluate(pos, 49_000_000, atr_value=500_000)
        assert decision.action != ExitAction.STOP_LOSS


class TestPartialExitStrategyA:
    """전략 A 부분청산 테스트."""

    def test_3pct_30pct(self, em: PartialExitManager) -> None:
        """+3% → 30% 부분청산."""
        pos = _make_position(strategy=Strategy.TREND_FOLLOW)
        em.init_position("BTC")
        decision = em.evaluate(pos, 51_500_000, atr_value=500_000)
        assert decision.action == ExitAction.PARTIAL_EXIT
        assert decision.exit_ratio == pytest.approx(0.3)

    def test_6pct_30pct(self, em: PartialExitManager) -> None:
        """+6% → 30% 2차 부분청산."""
        pos = _make_position(strategy=Strategy.TREND_FOLLOW)
        em.init_position("BTC")
        # 1차 트리거
        em.evaluate(pos, 51_500_000, atr_value=500_000)
        # 2차 트리거
        decision = em.evaluate(pos, 53_000_000, atr_value=500_000)
        assert decision.action == ExitAction.PARTIAL_EXIT
        assert decision.exit_ratio == pytest.approx(0.3)

    def test_no_triple_exit(self, em: PartialExitManager) -> None:
        """2회 부분청산 후 더 이상 부분청산 없음."""
        pos = _make_position(strategy=Strategy.TREND_FOLLOW)
        em.init_position("BTC")
        em.evaluate(pos, 51_500_000, atr_value=500_000)  # 1차
        em.evaluate(pos, 53_000_000, atr_value=500_000)  # 2차
        decision = em.evaluate(pos, 55_000_000, atr_value=500_000)
        assert decision.action != ExitAction.PARTIAL_EXIT


class TestPartialExitStrategyB:
    """전략 B 부분청산 테스트."""

    def test_bb_middle_50pct(self, em: PartialExitManager) -> None:
        """BB 중간선 도달 → 50% 부분청산."""
        pos = _make_position(strategy=Strategy.MEAN_REVERSION)
        em.init_position("BTC")
        decision = em.evaluate(
            pos, 51_000_000, atr_value=500_000, bb_middle=50_800_000,
        )
        assert decision.action == ExitAction.PARTIAL_EXIT
        assert decision.exit_ratio == pytest.approx(0.5)


class TestPartialExitStrategyCD:
    """전략 C/D 부분청산 없음."""

    def test_breakout_no_partial(self, em: PartialExitManager) -> None:
        """전략 C 부분청산 없음."""
        pos = _make_position(strategy=Strategy.BREAKOUT)
        em.init_position("BTC")
        decision = em.evaluate(pos, 52_000_000, atr_value=500_000)
        assert decision.action in (ExitAction.NONE, ExitAction.TRAILING_STOP)

    def test_scalping_fixed_tp(self, em: PartialExitManager) -> None:
        """전략 D 고정 TP 1.5%."""
        pos = _make_position(
            strategy=Strategy.SCALPING, entry_price=50_000_000,
        )
        pos.stop_loss = 50_000_000 * 0.992  # 0.8% SL
        em.init_position("BTC")
        decision = em.evaluate(pos, 50_750_000, atr_value=100_000)
        assert decision.action == ExitAction.TAKE_PROFIT
        assert decision.exit_ratio == 1.0


class TestTrailingStop:
    """트레일링 스톱 테스트."""

    def test_activation_at_3pct(self, em: PartialExitManager) -> None:
        """트레일링 +3%에서 활성화."""
        pos = _make_position(strategy=Strategy.BREAKOUT)
        em.init_position("BTC")
        # +3.5%
        em.evaluate(pos, 51_750_000, atr_value=500_000)
        state = em.get_trailing_state("BTC")
        assert state is not None
        assert state.active is True

    def test_trailing_hit(self, em: PartialExitManager) -> None:
        """트레일링 히트 시 청산."""
        pos = _make_position(strategy=Strategy.BREAKOUT)
        em.init_position("BTC")
        # 활성화 (+4%)
        em.evaluate(pos, 52_000_000, atr_value=500_000)
        # 고점 갱신
        em.evaluate(pos, 55_000_000, atr_value=500_000)
        state = em.get_trailing_state("BTC")
        # 트레일링 스톱 아래로 하락
        decision = em.evaluate(pos, state.trailing_stop - 1, atr_value=500_000)
        assert decision.action == ExitAction.TRAILING_STOP

    def test_not_active_below_3pct(self, em: PartialExitManager) -> None:
        """3% 미만에서는 트레일링 비활성."""
        pos = _make_position(strategy=Strategy.BREAKOUT)
        em.init_position("BTC")
        em.evaluate(pos, 50_500_000, atr_value=500_000)  # +1%
        state = em.get_trailing_state("BTC")
        assert state is not None
        assert state.active is False


class TestTimeExit:
    """시간 제한 청산 테스트."""

    def test_scalping_2h_limit(self, em: PartialExitManager) -> None:
        """스캘핑 2시간 제한."""
        pos = _make_position(strategy=Strategy.SCALPING)
        pos.entry_time = 1000
        # 2시간 + 1초 후
        decision = em.check_time_exit(pos, 1000 + 7201_000)
        assert decision.action == ExitAction.TIME_EXIT

    def test_non_scalping_no_time_limit(self, em: PartialExitManager) -> None:
        """비스캘핑 전략은 시간 제한 없음."""
        pos = _make_position(strategy=Strategy.TREND_FOLLOW)
        pos.entry_time = 1000
        decision = em.check_time_exit(pos, 1000 + 100_000_000)
        assert decision.action == ExitAction.NONE


class TestPriority:
    """청산 우선순위 테스트."""

    def test_sl_overrides_partial(self, em: PartialExitManager) -> None:
        """손절이 부분청산보다 우선."""
        pos = _make_position(strategy=Strategy.TREND_FOLLOW, entry_price=50_000_000)
        pos.stop_loss = 51_000_000  # 의도적으로 SL을 현재가 위에 설정
        em.init_position("BTC")
        # 현재가가 SL 이하면 손절이 우선
        decision = em.evaluate(pos, 50_900_000, atr_value=500_000)
        assert decision.action == ExitAction.STOP_LOSS


class TestFeeTracking:
    """수수료 추적 테스트."""

    def test_add_fee(self, em: PartialExitManager) -> None:
        """수수료 누적."""
        em.init_position("BTC")
        em.add_fee("BTC", 125)
        em.add_fee("BTC", 130)
        assert em.get_cumulative_fee("BTC") == pytest.approx(255)

    def test_remove_clears(self, em: PartialExitManager) -> None:
        """포지션 제거 시 수수료 초기화."""
        em.init_position("BTC")
        em.add_fee("BTC", 100)
        em.remove_position("BTC")
        assert em.get_cumulative_fee("BTC") == 0
