"""국면별 파라미터 오버라이드 테스트."""

from __future__ import annotations


class TestRegimeOverride:
    """regime_override 병합 테스트."""

    def test_base_only(self) -> None:
        """regime_override 없으면 기본값 사용."""
        from strategy.rule_engine import _merge_strategy_params

        sp = {"sl_mult": 7.0, "tp_rr": 1.5}
        result = _merge_strategy_params(sp, tier=1, regime="RANGE")
        assert result["sl_mult"] == 7.0

    def test_regime_overrides_base(self) -> None:
        """regime_override가 기본값을 덮어쓴다."""
        from strategy.rule_engine import _merge_strategy_params

        sp = {
            "sl_mult": 7.0,
            "tp_rr": 1.5,
            "regime_override": {
                "WEAK_DOWN": {"sl_mult": 8.0, "tp_rr": 1.2},
            },
        }
        result = _merge_strategy_params(sp, tier=1, regime="WEAK_DOWN")
        assert result["sl_mult"] == 8.0
        assert result["tp_rr"] == 1.2

    def test_regime_overrides_tier(self) -> None:
        """regime_override가 tier보다 우선한다."""
        from strategy.rule_engine import _merge_strategy_params

        sp = {
            "sl_mult": 7.0,
            "tier1": {"sl_mult": 6.0},
            "regime_override": {
                "WEAK_DOWN": {"sl_mult": 8.0},
            },
        }
        result = _merge_strategy_params(sp, tier=1, regime="WEAK_DOWN")
        assert result["sl_mult"] == 8.0

    def test_no_matching_regime(self) -> None:
        """매칭 국면 없으면 base+tier 사용."""
        from strategy.rule_engine import _merge_strategy_params

        sp = {
            "sl_mult": 7.0,
            "regime_override": {"CRISIS": {"sl_mult": 10.0}},
        }
        result = _merge_strategy_params(sp, tier=1, regime="RANGE")
        assert result["sl_mult"] == 7.0
