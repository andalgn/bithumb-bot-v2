"""RiskGate 테스트."""

import time

import pytest

from app.data_types import OrderSide, Regime, Signal, Strategy, Tier
from execution.quarantine import QuarantineManager
from risk.dd_limits import DDLimits
from risk.risk_gate import RiskGate
from strategy.spread_profiler import SpreadProfiler


def _make_signal(
    symbol: str = "BTC",
    direction: OrderSide = OrderSide.BUY,
) -> Signal:
    """테스트용 신호 생성."""
    return Signal(
        symbol=symbol,
        direction=direction,
        strategy=Strategy.MEAN_REVERSION,
        score=70.0,
        regime=Regime.RANGE,
        tier=Tier.TIER2,
        entry_price=50000000,
        stop_loss=49000000,
        take_profit=52000000,
        timestamp=int(time.time() * 1000),
    )


@pytest.fixture
def risk_gate(tmp_path) -> RiskGate:
    """RiskGate 인스턴스를 생성한다."""
    dd = DDLimits(daily_pct=0.04, weekly_pct=0.08, monthly_pct=0.12, total_pct=0.20)
    dd.initialize(1_000_000)  # 100만원
    quarantine = QuarantineManager(
        state_path=str(tmp_path / "quarantine.json"),
    )
    return RiskGate(
        dd_limits=dd,
        quarantine=quarantine,
        spread_profiler=SpreadProfiler(),
        max_exposure_pct=0.90,
        consecutive_loss_limit=5,
        cooldown_min=60,
    )


class TestRiskGateBasic:
    """기본 리스크 체크 테스트."""

    def test_allow_normal_buy(self, risk_gate: RiskGate) -> None:
        """정상 상황에서 BUY 허용."""
        risk_gate.update_state(total_exposure_krw=100_000, total_equity_krw=1_000_000)
        result = risk_gate.check(_make_signal())
        assert result.allowed is True

    def test_allow_sell_always(self, risk_gate: RiskGate) -> None:
        """SELL은 DD로 차단하지 않음."""
        # DD 100% 초과 상태
        risk_gate._dd.update_equity(1_000_000)
        risk_gate._dd._state.current_equity = 500_000  # 50% DD
        risk_gate.update_state(total_exposure_krw=0, total_equity_krw=500_000)
        result = risk_gate.check(_make_signal(direction=OrderSide.SELL))
        assert result.allowed is True


class TestDDBlock:
    """DD Kill Switch 테스트."""

    def test_daily_dd_block(self, risk_gate: RiskGate) -> None:
        """일일 DD 4% 초과 시 BUY 차단."""
        risk_gate._dd._state.current_equity = 950_000  # 5% DD
        risk_gate.update_state(total_exposure_krw=0, total_equity_krw=950_000)
        result = risk_gate.check(_make_signal())
        assert result.allowed is False
        assert "P5" in result.reason

    def test_total_dd_block(self, risk_gate: RiskGate) -> None:
        """총 DD 20% 초과 시 BUY 차단."""
        risk_gate._dd._state.current_equity = 750_000  # 25% DD
        risk_gate.update_state(total_exposure_krw=0, total_equity_krw=750_000)
        result = risk_gate.check(_make_signal())
        assert result.allowed is False
        assert "P2" in result.reason


class TestExposure:
    """익스포저 테스트."""

    def test_exposure_block(self, risk_gate: RiskGate) -> None:
        """총 익스포저 90% 초과 시 BUY 차단."""
        risk_gate.update_state(
            total_exposure_krw=950_000,
            total_equity_krw=1_000_000,
        )
        result = risk_gate.check(_make_signal())
        assert result.allowed is False
        assert "P6" in result.reason


class TestQuarantine:
    """격리 테스트."""

    def test_coin_quarantine(self, risk_gate: RiskGate) -> None:
        """종목 격리 시 차단."""
        for _ in range(3):
            risk_gate._quarantine.record_failure("BTC")
        risk_gate.update_state(total_exposure_krw=0, total_equity_krw=1_000_000)
        result = risk_gate.check(_make_signal(symbol="BTC"))
        assert result.allowed is False
        assert "P8" in result.reason

    def test_auth_quarantine(self, risk_gate: RiskGate) -> None:
        """인증 오류 격리 시 차단."""
        risk_gate._quarantine.record_failure("BTC", is_auth_error=True)
        risk_gate.update_state(total_exposure_krw=0, total_equity_krw=1_000_000)
        result = risk_gate.check(_make_signal())
        assert result.allowed is False
        assert "P1" in result.reason


class TestConsecutiveLoss:
    """연속 손실 테스트."""

    def test_consecutive_loss_block(self, risk_gate: RiskGate) -> None:
        """연속 손실 5회 시 BUY 차단."""
        for _ in range(5):
            risk_gate.record_trade_result(is_loss=True)
        risk_gate.update_state(total_exposure_krw=0, total_equity_krw=1_000_000)
        result = risk_gate.check(_make_signal())
        assert result.allowed is False
        assert "P9" in result.reason

    def test_loss_reset_on_win(self, risk_gate: RiskGate) -> None:
        """수익 발생 시 연속 손실 리셋."""
        for _ in range(4):
            risk_gate.record_trade_result(is_loss=True)
        risk_gate.record_trade_result(is_loss=False)
        risk_gate.update_state(total_exposure_krw=0, total_equity_krw=1_000_000)
        result = risk_gate.check(_make_signal())
        assert result.allowed is True


class TestCooldown:
    """쿨다운 테스트."""

    def test_cooldown_block(self, risk_gate: RiskGate) -> None:
        """쿨다운 중 재진입 차단."""
        risk_gate.record_entry("BTC")
        risk_gate.update_state(total_exposure_krw=0, total_equity_krw=1_000_000)
        result = risk_gate.check(_make_signal(symbol="BTC"))
        assert result.allowed is False
        assert "P10" in result.reason

    def test_different_coin_no_cooldown(self, risk_gate: RiskGate) -> None:
        """다른 코인은 쿨다운 무관."""
        risk_gate.record_entry("BTC")
        risk_gate.update_state(total_exposure_krw=0, total_equity_krw=1_000_000)
        result = risk_gate.check(_make_signal(symbol="ETH"))
        assert result.allowed is True
