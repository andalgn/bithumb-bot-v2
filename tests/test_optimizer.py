"""파라미터 최적화 테스트."""

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
