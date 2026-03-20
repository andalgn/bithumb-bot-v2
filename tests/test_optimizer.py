"""파라미터 최적화 테스트."""

from backtesting.optimizer import OptResult, ParameterOptimizer
from backtesting.param_grid import ParamRange, StrategyParamGrid, build_grids


class TestParamRange:
    def test_values(self) -> None:
        pr = ParamRange("test", [1.0, 2.0, 3.0])
        assert pr.name == "test"
        assert len(pr.values) == 3


class TestStrategyParamGrid:
    def test_empty_params(self) -> None:
        grid = StrategyParamGrid(strategy="test")
        assert grid.combinations() == [{}]

    def test_single_param(self) -> None:
        grid = StrategyParamGrid(
            strategy="test",
            params=[ParamRange("a", [1.0, 2.0, 3.0])],
        )
        combos = grid.combinations()
        assert len(combos) == 3
        assert combos[0] == {"a": 1.0}

    def test_multi_params(self) -> None:
        grid = StrategyParamGrid(
            strategy="test",
            params=[
                ParamRange("a", [1.0, 2.0]),
                ParamRange("b", [10.0, 20.0, 30.0]),
            ],
        )
        combos = grid.combinations()
        assert len(combos) == 6
        assert {"a": 1.0, "b": 10.0} in combos
        assert {"a": 2.0, "b": 30.0} in combos

    def test_combo_keys(self) -> None:
        grid = StrategyParamGrid(
            strategy="test",
            params=[
                ParamRange("sl_mult", [1.0]),
                ParamRange("tp_rr", [2.0]),
            ],
        )
        combo = grid.combinations()[0]
        assert "sl_mult" in combo
        assert "tp_rr" in combo


class TestBuildGrids:
    def test_all_strategies_present(self) -> None:
        grids = build_grids()
        assert "trend_follow" in grids
        assert "mean_reversion" in grids
        assert "breakout" in grids
        assert "scalping" in grids

    def test_trend_follow_count(self) -> None:
        grids = build_grids()
        assert len(grids["trend_follow"].combinations()) == 5 * 6 * 4

    def test_mean_reversion_count(self) -> None:
        grids = build_grids()
        assert len(grids["mean_reversion"].combinations()) == 4 * 5 * 4

    def test_breakout_count(self) -> None:
        grids = build_grids()
        assert len(grids["breakout"].combinations()) == 5 * 5 * 4

    def test_scalping_count(self) -> None:
        grids = build_grids()
        assert len(grids["scalping"].combinations()) == 5 * 5

    def test_total_combinations(self) -> None:
        grids = build_grids()
        total = sum(len(g.combinations()) for g in grids.values())
        assert total == 120 + 80 + 100 + 25  # 325


# ─── ParameterOptimizer 테스트 ───


def _make_candles(base: float, count: int, trend: float = 0.0) -> list:
    """테스트용 캔들 생성 헬퍼."""
    from app.data_types import Candle

    candles = []
    price = base
    for i in range(count):
        price += trend
        candles.append(
            Candle(
                timestamp=1000 * (i + 1),
                open=price * 0.999,
                high=price * 1.01,
                low=price * 0.99,
                close=price,
                volume=1000.0 + i * 10,
            )
        )
    return candles


class TestOptResult:
    def test_defaults(self) -> None:
        r = OptResult()
        assert r.trades == 0
        assert r.profit_factor == 0.0

    def test_with_values(self) -> None:
        r = OptResult(trades=10, win_rate=0.5, profit_factor=1.5)
        assert r.trades == 10


class TestCalcStats:
    def test_empty_pnls(self) -> None:
        r = ParameterOptimizer._calc_stats("test", {}, [])
        assert r.trades == 0

    def test_all_wins(self) -> None:
        r = ParameterOptimizer._calc_stats("test", {}, [0.01, 0.02, 0.03])
        assert r.trades == 3
        assert r.win_rate == 1.0
        assert r.profit_factor == 10.0

    def test_mixed(self) -> None:
        r = ParameterOptimizer._calc_stats("test", {}, [0.05, -0.02, 0.03, -0.01])
        assert r.trades == 4
        assert r.win_rate == 0.5
        assert r.profit_factor > 1.0


class TestCalcTradePnl:
    def test_profit(self) -> None:
        pnl = ParameterOptimizer._calc_trade_pnl(100, 110)
        assert pnl > 0

    def test_loss(self) -> None:
        pnl = ParameterOptimizer._calc_trade_pnl(100, 90)
        assert pnl < 0

    def test_breakeven_loses_to_fees(self) -> None:
        pnl = ParameterOptimizer._calc_trade_pnl(100, 100)
        assert pnl < 0  # fees make breakeven a loss
