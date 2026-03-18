"""Darwin 엔진 테스트."""

import pytest

from app.data_types import (
    MarketSnapshot,
    OrderSide,
    Regime,
    Signal,
    Strategy,
    Tier,
)
from strategy.darwin_engine import DarwinEngine, ShadowParams


@pytest.fixture
def engine() -> DarwinEngine:
    """테스트용 DarwinEngine."""
    return DarwinEngine(population_size=10)


def _make_signal(symbol: str = "BTC", score: float = 75.0) -> Signal:
    """테스트용 신호."""
    return Signal(
        symbol=symbol,
        direction=OrderSide.BUY,
        strategy=Strategy.TREND_FOLLOW,
        score=score,
        regime=Regime.STRONG_UP,
        tier=Tier.TIER1,
        entry_price=50_000_000,
        stop_loss=49_000_000,
        take_profit=52_000_000,
    )


def _make_snapshot(symbol: str = "BTC", price: float = 50_500_000) -> MarketSnapshot:
    """테스트용 스냅샷."""
    return MarketSnapshot(symbol=symbol, current_price=price)


class TestDarwinInit:
    """초기화 테스트."""

    def test_population_size(self, engine: DarwinEngine) -> None:
        """인구 크기 확인."""
        assert engine.shadow_count == 10

    def test_champion_exists(self, engine: DarwinEngine) -> None:
        """챔피언 존재."""
        assert engine.champion.shadow_id == "champion"


class TestShadowRecord:
    """Shadow 기록 테스트."""

    def test_record_cycle(self, engine: DarwinEngine) -> None:
        """매 사이클 기록."""
        signals = [_make_signal()]
        snapshots = {"BTC": _make_snapshot()}
        count = engine.record_cycle(snapshots, signals)
        assert count > 0

    def test_performance_updated(self, engine: DarwinEngine) -> None:
        """성과 업데이트 확인."""
        signals = [_make_signal(score=90)]
        snapshots = {"BTC": _make_snapshot(price=51_000_000)}
        engine.record_cycle(snapshots, signals)

        # 최소 1개 Shadow에서 trade_count > 0
        has_trades = any(
            p.trade_count > 0
            for p in engine.performances.values()
            if p.shadow_id != "champion"
        )
        assert has_trades


class TestTournament:
    """토너먼트 테스트."""

    def test_tournament_runs(self, engine: DarwinEngine) -> None:
        """토너먼트 실행."""
        # 데이터 축적
        for _ in range(10):
            signals = [_make_signal(score=80)]
            snapshots = {"BTC": _make_snapshot(price=51_000_000)}
            engine.record_cycle(snapshots, signals)

        scores = engine.run_tournament(top_survive=3)
        # 결과 리스트 반환
        assert isinstance(scores, list)

    def test_population_preserved(self, engine: DarwinEngine) -> None:
        """토너먼트 후 인구 유지."""
        for _ in range(10):
            engine.record_cycle(
                {"BTC": _make_snapshot()},
                [_make_signal()],
            )
        engine.run_tournament(top_survive=3)
        assert engine.shadow_count == 10


class TestChampionReplacement:
    """챔피언 교체 테스트."""

    def test_no_replacement_without_data(self, engine: DarwinEngine) -> None:
        """데이터 부족 시 교체 없음."""
        result = engine.check_champion_replacement()
        assert result is None

    def test_replace_champion(self, engine: DarwinEngine) -> None:
        """챔피언 교체."""
        new = ShadowParams(shadow_id="new_champ", cutoff=60)
        engine.replace_champion(new)
        assert engine.champion.cutoff == 60


class TestTopShadows:
    """상위 Shadow 조회."""

    def test_get_top(self, engine: DarwinEngine) -> None:
        """상위 3개."""
        for _ in range(5):
            engine.record_cycle(
                {"BTC": _make_snapshot()},
                [_make_signal()],
            )
        top = engine.get_top_shadows(3)
        assert len(top) <= 3 + 1  # champion 포함 가능
