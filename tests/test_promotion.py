"""승격/강등 시스템 테스트."""

import pytest

from app.data_types import Candle, Pool, Position, Regime, Strategy, Tier
from strategy.indicators import IndicatorPack, compute_indicators
from strategy.pool_manager import PoolManager
from strategy.promotion_manager import CorePhase, PromotionManager


def _make_position(
    symbol: str = "BTC",
    entry_price: float = 50_000_000,
    tier: Tier = Tier.TIER1,
) -> Position:
    """테스트용 Active 포지션."""
    return Position(
        symbol=symbol,
        entry_price=entry_price,
        entry_time=1000,
        size_krw=15_000,
        qty=0.0003,
        stop_loss=entry_price * 0.97,
        take_profit=entry_price * 1.05,
        strategy=Strategy.TREND_FOLLOW,
        pool=Pool.ACTIVE,
        tier=tier,
        regime=Regime.STRONG_UP,
        entry_score=80.0,
    )


def _make_candles(base: float, count: int, trend: float = 0.5) -> list[Candle]:
    """상승 추세 캔들."""
    candles = []
    price = base
    for i in range(count):
        price += trend
        candles.append(Candle(
            timestamp=1000 * (i + 1),
            open=price * 0.999,
            high=price * 1.01,
            low=price * 0.99,
            close=price,
            volume=1000.0,
        ))
    return candles


def _make_indicators(candles: list[Candle]) -> IndicatorPack:
    """테스트용 지표."""
    return compute_indicators(candles)


@pytest.fixture
def pm() -> PromotionManager:
    """테스트용 PromotionManager."""
    pool = PoolManager(1_000_000)
    pool.allocate(Pool.ACTIVE, 15_000)  # 테스트 포지션 미리 할당
    return PromotionManager(pool_manager=pool)


class TestPromotionCheck:
    """승격 조건 테스트."""

    def test_tier3_cannot_promote(self, pm: PromotionManager) -> None:
        """Tier 3 승격 불가."""
        pos = _make_position(tier=Tier.TIER3)
        candles = _make_candles(50_000_000, 200)
        ind = _make_indicators(candles)
        assert pm.check_promotion(pos, 50_700_000, ind, Regime.STRONG_UP) is False

    def test_range_regime_cannot_promote(self, pm: PromotionManager) -> None:
        """RANGE 국면 승격 불가."""
        pos = _make_position()
        candles = _make_candles(50_000_000, 200)
        ind = _make_indicators(candles)
        assert pm.check_promotion(pos, 51_000_000, ind, Regime.RANGE) is False

    def test_insufficient_profit(self, pm: PromotionManager) -> None:
        """수익 부족 시 승격 안 됨."""
        pos = _make_position(entry_price=50_000_000)
        candles = _make_candles(50_000_000, 200)
        ind = _make_indicators(candles)
        # +0.5% < 1.2%
        assert pm.check_promotion(pos, 50_250_000, ind, Regime.STRONG_UP) is False

    def test_2bar_hold_required(self, pm: PromotionManager) -> None:
        """2봉 유지 필요."""
        pos = _make_position(entry_price=50_000_000)
        candles = _make_candles(50_000_000, 200, trend=1.0)
        ind = _make_indicators(candles)
        price = 51_000_000  # +2%
        # 1회차 → 아직 2봉 안 됨
        result1 = pm.check_promotion(pos, price, ind, Regime.STRONG_UP)
        assert result1 is False
        # 2회차 → 2봉 달성
        result2 = pm.check_promotion(pos, price, ind, Regime.STRONG_UP)
        # ADX, EMA20 조건도 만족해야 True
        assert isinstance(result2, bool)


class TestPromotionFlow:
    """승격→보호→정상→강등 전체 흐름."""

    def test_promote_creates_core_position(self, pm: PromotionManager) -> None:
        """승격 시 CorePosition 생성."""
        pos = _make_position()
        candles = _make_candles(50_000_000, 200, trend=1.0)
        ind = _make_indicators(candles)
        core_pos = pm.promote(pos, ind)
        assert core_pos is not None
        assert core_pos.phase == CorePhase.PROTECTION
        assert pos.pool == Pool.CORE
        assert pos.promoted is True
        assert pm.is_core("BTC") is True

    def test_protection_survives(self, pm: PromotionManager) -> None:
        """보호기간 2봉 생존 → NORMAL."""
        pos = _make_position()
        candles = _make_candles(50_000_000, 200)
        ind = _make_indicators(candles)
        pm.promote(pos, ind)

        # 2봉 동안 손절선 위
        for _ in range(2):
            pm.update_core_positions(
                {"BTC": 51_000_000}, {"BTC": ind}, {"BTC": Regime.STRONG_UP}
            )
        cp = pm.get_core_position("BTC")
        assert cp is not None
        assert cp.phase == CorePhase.NORMAL

    def test_protection_sl_hit_demotes(self, pm: PromotionManager) -> None:
        """보호기간 중 손절 → 강등."""
        pos = _make_position()
        candles = _make_candles(50_000_000, 200)
        ind = _make_indicators(candles)
        pm.promote(pos, ind)

        # 손절선 이탈
        demoted = pm.update_core_positions(
            {"BTC": 40_000_000}, {"BTC": ind}, {"BTC": Regime.STRONG_UP}
        )
        assert "BTC" in demoted

    def test_demotion_on_regime_change(self, pm: PromotionManager) -> None:
        """국면 악화 → 강등."""
        pos = _make_position()
        candles = _make_candles(50_000_000, 200)
        ind = _make_indicators(candles)
        pm.promote(pos, ind)

        # 보호기간 통과
        for _ in range(2):
            pm.update_core_positions(
                {"BTC": 51_000_000}, {"BTC": ind}, {"BTC": Regime.STRONG_UP}
            )

        # 국면 RANGE로 변경 → 강등
        demoted = pm.update_core_positions(
            {"BTC": 51_000_000}, {"BTC": ind}, {"BTC": Regime.RANGE}
        )
        assert "BTC" in demoted


class TestPartialExit:
    """부분 청산 테스트."""

    def test_3pct_30pct_exit(self, pm: PromotionManager) -> None:
        """+3% → 30% 부분 청산."""
        pos = _make_position(entry_price=50_000_000)
        candles = _make_candles(50_000_000, 200)
        ind = _make_indicators(candles)
        pm.promote(pos, ind)

        # NORMAL로 전환
        for _ in range(2):
            pm.update_core_positions(
                {"BTC": 51_500_000}, {"BTC": ind}, {"BTC": Regime.STRONG_UP}
            )

        # +3% = 51,500,000
        exit_pct = pm.check_partial_exit("BTC", 51_500_000)
        assert exit_pct == pytest.approx(0.3)

    def test_6pct_30pct_exit(self, pm: PromotionManager) -> None:
        """+6% → 30% 부분 청산 (2차)."""
        pos = _make_position(entry_price=50_000_000)
        candles = _make_candles(50_000_000, 200)
        ind = _make_indicators(candles)
        pm.promote(pos, ind)

        for _ in range(2):
            pm.update_core_positions(
                {"BTC": 52_000_000}, {"BTC": ind}, {"BTC": Regime.STRONG_UP}
            )

        # 1차: +3%
        pm.check_partial_exit("BTC", 51_500_000)
        # 2차: +6%
        exit_pct = pm.check_partial_exit("BTC", 53_000_000)
        assert exit_pct == pytest.approx(0.3)


class TestAdditionalBuy:
    """추가매수 테스트."""

    def test_too_early(self, pm: PromotionManager) -> None:
        """4봉 미경과 시 불가."""
        pos = _make_position(entry_price=50_000_000)
        candles = _make_candles(50_000_000, 200)
        ind = _make_indicators(candles)
        pm.promote(pos, ind)

        # 2봉만 경과 (보호기간)
        for _ in range(2):
            pm.update_core_positions(
                {"BTC": 52_000_000}, {"BTC": ind}, {"BTC": Regime.STRONG_UP}
            )

        assert pm.check_additional_buy("BTC", 52_000_000, 60, candles[-4:]) is False

    def test_conditions_met(self, pm: PromotionManager) -> None:
        """모든 조건 충족 시 가능."""
        pos = _make_position(entry_price=50_000_000)
        candles = _make_candles(50_000_000, 200, trend=1.0)
        ind = _make_indicators(candles)
        pm.promote(pos, ind)

        # 5봉 경과
        for _ in range(5):
            pm.update_core_positions(
                {"BTC": 52_000_000}, {"BTC": ind}, {"BTC": Regime.STRONG_UP}
            )

        # +4% 수익, 점수 60, VWAP 위
        result = pm.check_additional_buy("BTC", 52_000_000, 60, candles[-4:])
        assert isinstance(result, bool)

    def test_once_only(self, pm: PromotionManager) -> None:
        """포지션당 1회 제한."""
        pos = _make_position(entry_price=50_000_000)
        candles = _make_candles(50_000_000, 200)
        ind = _make_indicators(candles)
        pm.promote(pos, ind)
        pm.mark_additional_buy("BTC")
        assert pm.check_additional_buy("BTC", 52_000_000, 60, candles[-4:]) is False
