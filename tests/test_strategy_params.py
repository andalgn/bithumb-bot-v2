"""strategy_params 단위 테스트."""

import pytest

from strategy.strategy_params import PARAM_BOUNDS, EvolvableParams


class TestEvolvableParamsDefaults:
    """기본값 검증."""

    def test_default_values_within_bounds(self):
        """모든 기본값이 PARAM_BOUNDS 범위 내에 있어야 한다."""
        params = EvolvableParams()
        violations = params.validate()
        assert violations == [], f"기본값 범위 위반: {violations}"

    def test_all_fields_have_bounds(self):
        """모든 필드에 PARAM_BOUNDS 항목이 있어야 한다."""
        from dataclasses import fields

        for f in fields(EvolvableParams):
            assert f.name in PARAM_BOUNDS, f"{f.name}에 범위 미정의"

    def test_bounds_min_less_than_max(self):
        """모든 범위의 min < max 확인."""
        for name, (lo, hi) in PARAM_BOUNDS.items():
            assert lo < hi, f"{name}: min({lo}) >= max({hi})"


class TestValidation:
    """범위 검증."""

    def test_out_of_bounds_detected(self):
        """범위 초과 시 violations 반환."""
        params = EvolvableParams(tf_sl_mult=99.0)
        violations = params.validate()
        assert any("tf_sl_mult" in v for v in violations)

    def test_under_bounds_detected(self):
        """범위 미달 시 violations 반환."""
        params = EvolvableParams(dca_sl_pct=0.001)
        violations = params.validate()
        assert any("dca_sl_pct" in v for v in violations)

    def test_defense_mult_logic(self):
        """defense_mult_min >= defense_mult_max 시 위반."""
        params = EvolvableParams(defense_mult_min=0.9, defense_mult_max=0.8)
        violations = params.validate()
        assert any("defense_mult_min" in v for v in violations)

    def test_vol_target_mult_logic(self):
        """vol_target_mult_min >= vol_target_mult_max 시 위반."""
        params = EvolvableParams(vol_target_mult_min=1.5, vol_target_mult_max=1.0)
        violations = params.validate()
        assert any("vol_target_mult_min" in v for v in violations)

    def test_dd_logic(self):
        """daily_dd >= weekly_dd 시 위반."""
        params = EvolvableParams(daily_dd_pct=0.05, weekly_dd_pct=0.04)
        violations = params.validate()
        assert any("daily_dd_pct" in v for v in violations)

    def test_valid_params_no_violations(self):
        """정상 파라미터는 violations 없음."""
        params = EvolvableParams()
        assert params.validate() == []


class TestDiff:
    """차이 비교."""

    def test_no_diff_same_params(self):
        """동일 파라미터 간 차이 없음."""
        a = EvolvableParams()
        b = EvolvableParams()
        assert a.diff(b) == {}

    def test_single_diff(self):
        """단일 파라미터 변경 감지."""
        a = EvolvableParams(tf_sl_mult=2.5)
        b = EvolvableParams(tf_sl_mult=3.0)
        d = a.diff(b)
        assert d == {"tf_sl_mult": (2.5, 3.0)}

    def test_multiple_diff(self):
        """복수 파라미터 변경 감지."""
        a = EvolvableParams()
        b = EvolvableParams(tf_sl_mult=3.0, mr_tp_rr=2.0, daily_dd_pct=0.035)
        d = a.diff(b)
        assert len(d) == 3
        assert "tf_sl_mult" in d
        assert "mr_tp_rr" in d
        assert "daily_dd_pct" in d


class TestApplyChanges:
    """변경 적용."""

    def test_apply_single_change(self):
        """단일 변경 적용."""
        params = EvolvableParams()
        new_params = params.apply_changes({"tf_sl_mult": 3.0})
        assert new_params.tf_sl_mult == 3.0
        assert params.tf_sl_mult == 5.0  # 원본 불변

    def test_apply_clamping(self):
        """범위 초과 시 클램핑."""
        params = EvolvableParams()
        new_params = params.apply_changes({"tf_sl_mult": 100.0})
        assert new_params.tf_sl_mult == PARAM_BOUNDS["tf_sl_mult"][1]

    def test_apply_unknown_key_ignored(self):
        """알 수 없는 키 무시."""
        params = EvolvableParams()
        new_params = params.apply_changes({"nonexistent": 42.0})
        assert params.to_dict() == new_params.to_dict()

    def test_apply_int_rounding(self):
        """int 필드는 반올림된다."""
        params = EvolvableParams()
        new_params = params.apply_changes({"consecutive_loss_limit": 4.7})
        assert new_params.consecutive_loss_limit == 5
        assert isinstance(new_params.consecutive_loss_limit, int)

    def test_apply_cross_field_violation_raises(self):
        """교차 필드 제약 위반 시 ValueError."""
        params = EvolvableParams()
        # daily_dd_pct(max=0.06) >= weekly_dd_pct(min=0.04) → 위반 가능
        with pytest.raises(ValueError, match="교차 필드 제약 위반"):
            params.apply_changes({
                "daily_dd_pct": 0.06,
                "weekly_dd_pct": 0.04,
            })


class TestSerialization:
    """직렬화/역직렬화."""

    def test_roundtrip(self):
        """to_dict → from_dict 라운드트립."""
        original = EvolvableParams(tf_sl_mult=3.5, mr_tp_rr=2.0)
        restored = EvolvableParams.from_dict(original.to_dict())
        assert original == restored

    def test_from_dict_ignores_extra_keys(self):
        """알 수 없는 키는 무시."""
        data = EvolvableParams().to_dict()
        data["unknown_param"] = 999
        params = EvolvableParams.from_dict(data)
        assert not hasattr(params, "unknown_param")

    def test_clone_independence(self):
        """clone은 독립적인 복사본."""
        a = EvolvableParams()
        b = a.clone()
        assert a == b
        assert a is not b

    def test_frozen_prevents_mutation(self):
        """frozen dataclass는 직접 변경 불가."""
        params = EvolvableParams()
        with pytest.raises(AttributeError):
            params.tf_sl_mult = 99.0  # type: ignore[misc]


class TestConfigPatches:
    """config.yaml 패치 생성."""

    def test_no_changes_empty_patches(self):
        """변경 없으면 빈 패치."""
        a = EvolvableParams()
        patches = a.to_config_patches(a)
        assert patches == {}

    def test_strategy_param_patch(self):
        """전략 파라미터 변경 → strategy_params 섹션 패치."""
        current = EvolvableParams()
        proposed = EvolvableParams(tf_sl_mult=3.0)
        patches = proposed.to_config_patches(current)
        assert patches["strategy_params"]["trend_follow"]["sl_mult"] == 3.0

    def test_risk_param_patch(self):
        """리스크 파라미터 변경 → risk_gate 섹션 패치."""
        current = EvolvableParams()
        proposed = EvolvableParams(daily_dd_pct=0.035)
        patches = proposed.to_config_patches(current)
        assert patches["risk_gate"]["daily_dd_pct"] == 0.035

    def test_sizing_param_patch(self):
        """사이징 파라미터 변경 → sizing 섹션 패치."""
        current = EvolvableParams()
        proposed = EvolvableParams(active_risk_pct=0.05)
        patches = proposed.to_config_patches(current)
        assert patches["sizing"]["active_risk_pct"] == 0.05

    def test_int_conversion(self):
        """int 타입 필드는 int로 변환."""
        current = EvolvableParams()
        proposed = EvolvableParams(consecutive_loss_limit=5.0)
        patches = proposed.to_config_patches(current)
        value = patches["risk_gate"]["consecutive_loss_limit"]
        assert isinstance(value, int)
        assert value == 5

    def test_l1_filter_not_in_patches(self):
        """l1_* 파라미터는 config.yaml에 매핑 없음 → 패치에 미포함."""
        current = EvolvableParams()
        proposed = EvolvableParams(l1_volume_ratio=0.6)
        patches = proposed.to_config_patches(current)
        assert "l1_volume_ratio" not in str(patches)


class TestFromConfig:
    """AppConfig에서 로드."""

    def test_from_config_with_mock(self):
        """Mock AppConfig에서 정상 로드."""
        from dataclasses import dataclass, field

        @dataclass
        class MockScoreCutoffGroup:
            full: int = 75

        @dataclass
        class MockScoreCutoff:
            group1: MockScoreCutoffGroup = field(
                default_factory=MockScoreCutoffGroup
            )

        @dataclass
        class MockRiskGate:
            daily_dd_pct: float = 0.04
            weekly_dd_pct: float = 0.08
            consecutive_loss_limit: int = 3
            cooldown_min: int = 60
            max_exposure_pct: float = 0.90

        @dataclass
        class MockSizing:
            active_risk_pct: float = 0.07
            pool_cap_pct: float = 0.25
            defense_mult_min: float = 0.3
            defense_mult_max: float = 1.0
            vol_target_mult_min: float = 0.8
            vol_target_mult_max: float = 1.5

        @dataclass
        class MockRegime:
            strong_up_adx: int = 25
            crisis_atr_mult: float = 2.5

        @dataclass
        class MockPromotion:
            profit_pct: float = 0.012
            profit_hold_bars: int = 2
            adx_min: int = 20

        @dataclass
        class MockConfig:
            strategy_params: dict = field(default_factory=lambda: {
                "trend_follow": {
                    "sl_mult": 4.0,
                    "tp_rr": 2.0,
                    "w_trend_align": 30,
                    "w_macd": 25,
                    "w_volume": 20,
                    "w_rsi_pullback": 15,
                    "w_supertrend": 10,
                },
                "mean_reversion": {"sl_mult": 7.0, "tp_rr": 1.5},
                "breakout": {"sl_mult": 2.0, "tp_rr": 3.0},
                "dca": {"sl_pct": 0.05, "tp_pct": 0.03},
            })
            score_cutoff: MockScoreCutoff = field(
                default_factory=MockScoreCutoff
            )
            risk_gate: MockRiskGate = field(default_factory=MockRiskGate)
            sizing: MockSizing = field(default_factory=MockSizing)
            regime: MockRegime = field(default_factory=MockRegime)
            promotion: MockPromotion = field(default_factory=MockPromotion)

        config = MockConfig()
        params = EvolvableParams.from_config(config)

        assert params.tf_sl_mult == 4.0
        assert params.tf_tp_rr == 2.0
        assert params.mr_sl_mult == 7.0
        assert params.daily_dd_pct == 0.04
        assert params.active_risk_pct == 0.07
        assert params.regime_adx_strong == 25.0
        assert params.promotion_profit_pct == 0.012
        assert params.validate() == []
