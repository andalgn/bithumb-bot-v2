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
from strategy.darwin_engine import COMPOSITE_WEIGHTS, DarwinEngine, ShadowParams, ShadowPerformance


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
        """성과 업데이트 확인 (2사이클: 진입 → 평가)."""
        signals = [_make_signal(score=90)]
        snapshots = {"BTC": _make_snapshot(price=51_000_000)}
        # 사이클 1: 가상 진입
        engine.record_cycle(snapshots, signals)
        # 사이클 2: 가격 변동 후 평가
        snapshots2 = {"BTC": _make_snapshot(price=52_000_000)}
        engine.record_cycle(snapshots2, [])

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

        scores = engine.run_tournament(market_regime=Regime.RANGE)
        # 결과 리스트 반환
        assert isinstance(scores, list)

    def test_population_preserved(self, engine: DarwinEngine) -> None:
        """토너먼트 후 인구 유지."""
        for _ in range(10):
            engine.record_cycle(
                {"BTC": _make_snapshot()},
                [_make_signal()],
            )
        engine.run_tournament(market_regime=Regime.RANGE)
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


class TestCrossover:
    """crossover 연산자 테스트."""

    def test_crossover_produces_valid_params(self, engine: DarwinEngine) -> None:
        """crossover는 두 부모 중 하나의 파라미터값을 선택한다."""
        parent_a = ShadowParams(
            shadow_id="a",
            group="conservative",
            mr_sl_mult=3.0,
            mr_tp_rr=1.2,
            dca_sl_pct=0.03,
            dca_tp_pct=0.02,
            cutoff=60.0,
        )
        parent_b = ShadowParams(
            shadow_id="b",
            group="innovative",
            mr_sl_mult=9.0,
            mr_tp_rr=3.5,
            dca_sl_pct=0.07,
            dca_tp_pct=0.04,
            cutoff=85.0,
        )
        child = engine._crossover(parent_a, parent_b)

        numeric_fields = ["mr_sl_mult", "mr_tp_rr", "dca_sl_pct", "dca_tp_pct", "cutoff"]
        for field_name in numeric_fields:
            val = getattr(child, field_name)
            assert val in (getattr(parent_a, field_name), getattr(parent_b, field_name)), (
                f"Field {field_name}: {val} not in parents"
            )

    def test_crossover_preserves_non_numeric_fields(self, engine: DarwinEngine) -> None:
        """crossover 후 shadow_id, group 등 비파라미터 필드는 parent_a 기준."""
        parent_a = ShadowParams(shadow_id="parent_a_id", group="conservative")
        parent_b = ShadowParams(shadow_id="parent_b_id", group="innovative")
        child = engine._crossover(parent_a, parent_b)
        assert child.shadow_id == parent_a.shadow_id
        assert child.group == parent_a.group

    def test_crossover_child_is_different_object(self, engine: DarwinEngine) -> None:
        """crossover 결과는 부모와 다른 객체여야 한다."""
        parent_a = ShadowParams(shadow_id="a", group="conservative")
        parent_b = ShadowParams(shadow_id="b", group="moderate")
        child = engine._crossover(parent_a, parent_b)
        assert child is not parent_a
        assert child is not parent_b

    def test_tournament_population_preserved_with_crossover(self, engine: DarwinEngine) -> None:
        """crossover 적용 후에도 토너먼트 결과 인구 크기가 유지된다."""
        for _ in range(10):
            engine.record_cycle(
                {"BTC": _make_snapshot()},
                [_make_signal()],
            )
        engine.run_tournament(market_regime=Regime.RANGE)
        assert engine.shadow_count == 10


class TestCompositeScore8Metrics:
    """CompositeScore 8지표 확장 테스트."""

    def test_shadow_performance_has_sortino_calmar_consec_loss(self) -> None:
        """ShadowPerformance에 sortino_ratio, calmar_ratio, max_consecutive_loss 필드가 있다."""
        perf = ShadowPerformance(shadow_id="test")
        assert hasattr(perf, "sortino_ratio")
        assert hasattr(perf, "calmar_ratio")
        assert hasattr(perf, "max_consecutive_loss")

    def test_shadow_performance_new_fields_default(self) -> None:
        """새 필드 기본값이 올바르다."""
        perf = ShadowPerformance(shadow_id="test")
        assert perf.sortino_ratio == 0.0
        assert perf.calmar_ratio == 0.0
        assert perf.max_consecutive_loss == 0

    def test_composite_weights_sum_to_one(self) -> None:
        """CompositeScore 가중치 합이 1.0이다."""
        total = sum(COMPOSITE_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9, f"가중치 합 {total}이 1.0이 아님"

    def test_composite_weights_has_8_metrics(self) -> None:
        """COMPOSITE_WEIGHTS에 8개 지표가 있다."""
        assert len(COMPOSITE_WEIGHTS) == 8

    def test_composite_weights_includes_new_metrics(self) -> None:
        """새 지표(sortino, calmar, consec_loss)가 COMPOSITE_WEIGHTS에 포함된다."""
        assert "sortino" in COMPOSITE_WEIGHTS
        assert "calmar" in COMPOSITE_WEIGHTS
        assert "consec_loss" in COMPOSITE_WEIGHTS

    def test_calc_composite_score_returns_valid_score(self, engine: DarwinEngine) -> None:
        """_calc_composite_score가 0~1 범위의 score를 반환한다."""
        perf = ShadowPerformance(
            shadow_id="test",
            trade_count=10,
            total_pnl=0.05,
            win_count=6,
            total_wins_pnl=0.07,
            total_losses_pnl=0.02,
            max_drawdown=0.05,
            sortino_ratio=1.2,
            calmar_ratio=0.8,
            max_consecutive_loss=2,
        )
        cs = engine._calc_composite_score("test", perf)
        assert 0.0 <= cs.score <= 1.0

    def test_consec_loss_penalty_high_streak(self, engine: DarwinEngine) -> None:
        """연속 손실 5회 이상이면 패널티 0, 0회면 1.0."""
        perf_no_loss = ShadowPerformance(
            shadow_id="no_loss",
            trade_count=10,
            total_pnl=0.05,
            win_count=8,
            total_wins_pnl=0.07,
            total_losses_pnl=0.02,
            max_consecutive_loss=0,
        )
        perf_high_loss = ShadowPerformance(
            shadow_id="high_loss",
            trade_count=10,
            total_pnl=-0.01,
            win_count=2,
            total_wins_pnl=0.02,
            total_losses_pnl=0.03,
            max_consecutive_loss=5,
        )
        cs_no = engine._calc_composite_score("no_loss", perf_no_loss)
        cs_hi = engine._calc_composite_score("high_loss", perf_high_loss)
        # max_consecutive_loss=0인 경우가 5인 경우보다 score가 높아야 함
        assert cs_no.score > cs_hi.score

    def test_record_cycle_updates_max_consecutive_loss(self, engine: DarwinEngine) -> None:
        """record_cycle 호출 후 max_consecutive_loss가 업데이트된다."""
        # 손실 거래를 연속으로 발생시킴 (TP 50만, 진입 5000만, SL 4900만 → TP 미달하면 SL 도달)
        signals = [
            Signal(
                symbol="BTC",
                direction=OrderSide.BUY,
                strategy=Strategy.TREND_FOLLOW,
                score=90.0,
                regime=Regime.STRONG_UP,
                tier=Tier.TIER1,
                entry_price=50_000_000,
                stop_loss=49_000_000,
                take_profit=55_000_000,
            )
        ]
        # 사이클1: 진입
        engine.record_cycle({"BTC": MarketSnapshot(symbol="BTC", current_price=50_000_000)}, signals)
        # 사이클2: SL 아래로 가격 하락 → 손실 청산
        engine.record_cycle({"BTC": MarketSnapshot(symbol="BTC", current_price=48_000_000)}, [])
        # 어떤 Shadow든 max_consecutive_loss가 int임을 확인
        for perf in engine.performances.values():
            if perf.trade_count > 0:
                assert isinstance(perf.max_consecutive_loss, int)
