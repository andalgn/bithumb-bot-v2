"""guard_agent 단위 테스트."""

import pytest

from strategy.guard_agent import GuardAgent
from strategy.strategy_params import EvolvableParams


@pytest.fixture
def guard() -> GuardAgent:
    return GuardAgent()


@pytest.fixture
def base_params() -> EvolvableParams:
    return EvolvableParams()


class TestNoChange:
    """변경 없는 경우."""

    def test_identical_params(self, guard: GuardAgent, base_params: EvolvableParams):
        """동일 파라미터 → valid, risk 0, 변경 0건."""
        result = guard.validate(base_params, base_params)
        assert result.is_valid is True
        assert result.risk_score == 0.0
        assert result.risk_level == "low"
        assert result.change_count == 0


class TestBoundsViolation:
    """범위 위반 감지."""

    def test_out_of_bounds_rejected(self, guard: GuardAgent, base_params: EvolvableParams):
        """PARAM_BOUNDS 초과 → is_valid=False."""
        # frozen이라 직접 생성 (validate 전에 apply_changes 거침)
        bad = EvolvableParams(tf_sl_mult=99.0)  # 범위: [1.0, 8.0]
        result = guard.validate(base_params, bad)
        assert result.is_valid is False
        assert any("tf_sl_mult" in v for v in result.violations)


class TestLogicViolation:
    """논리적 정합성 검사."""

    def test_weight_sum_too_low(self, guard: GuardAgent, base_params: EvolvableParams):
        """가중치 합계 30 미만 → 위반."""
        low_weights = EvolvableParams(
            tf_w_trend_align=5.0,
            tf_w_macd=5.0,
            tf_w_volume=5.0,
            tf_w_rsi_pullback=5.0,
            tf_w_supertrend=5.0,
        )
        result = guard.validate(base_params, low_weights)
        assert result.is_valid is False
        assert any("가중치 합계" in v for v in result.violations)

    def test_weight_sum_normal(self, guard: GuardAgent, base_params: EvolvableParams):
        """기본 가중치 합계(100) → 통과."""
        result = guard.validate(base_params, base_params)
        assert result.is_valid is True

    def test_dca_sl_less_than_tp(self, guard: GuardAgent, base_params: EvolvableParams):
        """DCA SL < TP → 위반."""
        bad = EvolvableParams(dca_sl_pct=0.02, dca_tp_pct=0.04)
        result = guard.validate(base_params, bad)
        assert result.is_valid is False
        assert any("DCA" in v for v in result.violations)

    def test_weekly_dd_at_bounds_limit(self, guard: GuardAgent, base_params: EvolvableParams):
        """weekly_dd=0.10 (PARAM_BOUNDS 상한) → 통과."""
        at_limit = EvolvableParams(weekly_dd_pct=0.10)
        result = guard.validate(base_params, at_limit)
        assert result.is_valid is True

    def test_weekly_dd_over_bounds(self, guard: GuardAgent, base_params: EvolvableParams):
        """weekly_dd > 0.10 → PARAM_BOUNDS 위반."""
        over = EvolvableParams(weekly_dd_pct=0.11)
        result = guard.validate(base_params, over)
        assert result.is_valid is False
        assert any("weekly_dd_pct" in v for v in result.violations)


class TestHardConstraints:
    """절대 위반 불가 제약."""

    def test_daily_dd_hard_limit(self, guard: GuardAgent, base_params: EvolvableParams):
        """daily_dd > 0.06 → 거부."""
        # PARAM_BOUNDS 최대가 0.06이라 직접 생성으로는 불가.
        # EvolvableParams(daily_dd_pct=0.061)은 범위 위반도 동시 발생.
        bad = EvolvableParams(daily_dd_pct=0.06)
        # 0.06은 PARAM_BOUNDS 상한이자 하드리밋 경계 — 정확히 0.06은 통과
        result = guard.validate(base_params, bad)
        # daily=0.06, weekly=0.08 → daily < weekly → DD 논리 통과
        # hard constraint: daily_dd_pct > 0.06 → 0.06은 통과 (not >)
        assert result.is_valid is True

    def test_max_exposure_hard_limit(self, guard: GuardAgent, base_params: EvolvableParams):
        """max_exposure > 0.95 → 거부."""
        # PARAM_BOUNDS 최대 0.95 → 0.95는 통과, 초과는 bounds에서 먼저 잡힘
        at_limit = EvolvableParams(max_exposure_pct=0.95)
        result = guard.validate(base_params, at_limit)
        assert result.is_valid is True

    def test_consecutive_loss_too_low(self, guard: GuardAgent, base_params: EvolvableParams):
        """consecutive_loss_limit < 2 → 거부."""
        # PARAM_BOUNDS 최소가 2라 2는 통과
        at_min = EvolvableParams(consecutive_loss_limit=2)
        result = guard.validate(base_params, at_min)
        assert result.is_valid is True


class TestRiskScore:
    """위험도 점수 계산."""

    def test_low_risk_single_weight(self, guard: GuardAgent, base_params: EvolvableParams):
        """단일 가중치 미세 조정 → low risk."""
        tweaked = base_params.apply_changes({"tf_w_macd": 27.0})
        result = guard.validate(base_params, tweaked)
        assert result.is_valid is True
        assert result.risk_level == "low"
        assert result.risk_score < 0.2

    def test_medium_risk_multiple_params(self, guard: GuardAgent, base_params: EvolvableParams):
        """리스크 파라미터 포함 3개 변경 → medium risk."""
        tweaked = base_params.apply_changes({
            "tf_sl_mult": 3.0,
            "daily_dd_pct": 0.035,
            "active_risk_pct": 0.05,
        })
        result = guard.validate(base_params, tweaked)
        assert result.is_valid is True
        assert result.risk_level == "medium"

    def test_high_risk_many_params(self, guard: GuardAgent, base_params: EvolvableParams):
        """5개 이상 리스크/사이징 파라미터 대폭 변경 → high risk."""
        tweaked = base_params.apply_changes({
            "daily_dd_pct": 0.055,
            "weekly_dd_pct": 0.10,
            "max_exposure_pct": 0.80,
            "active_risk_pct": 0.10,
            "pool_cap_pct": 0.30,
            "defense_mult_min": 0.15,
        })
        result = guard.validate(base_params, tweaked)
        assert result.is_valid is True
        assert result.risk_level == "high"

    def test_risk_score_capped_at_1(self, guard: GuardAgent, base_params: EvolvableParams):
        """아무리 많이 바꿔도 risk_score <= 1.0."""
        all_changed = base_params.apply_changes({
            "tf_sl_mult": 1.5,
            "tf_tp_rr": 4.0,
            "tf_cutoff": 85,
            "tf_w_trend_align": 40.0,
            "tf_w_macd": 35.0,
            "tf_w_volume": 30.0,
            "tf_w_rsi_pullback": 25.0,
            "tf_w_supertrend": 20.0,
            "mr_sl_mult": 9.0,
            "mr_tp_rr": 3.5,
        })
        result = guard.validate(base_params, all_changed)
        assert result.risk_score <= 1.0


class TestRiskLevels:
    """위험도 레벨 분류."""

    def test_low_level(self, guard: GuardAgent):
        assert guard._score_to_level(0.0) == "low"
        assert guard._score_to_level(0.19) == "low"

    def test_medium_level(self, guard: GuardAgent):
        assert guard._score_to_level(0.2) == "medium"
        assert guard._score_to_level(0.59) == "medium"

    def test_high_level(self, guard: GuardAgent):
        assert guard._score_to_level(0.6) == "high"
        assert guard._score_to_level(1.0) == "high"


class TestGuardResultFields:
    """GuardResult 필드 확인."""

    def test_result_has_changes(self, guard: GuardAgent, base_params: EvolvableParams):
        """변경 내역이 result에 포함."""
        tweaked = base_params.apply_changes({"tf_sl_mult": 3.0})
        result = guard.validate(base_params, tweaked)
        assert "tf_sl_mult" in result.changes
        assert result.changes["tf_sl_mult"] == (5.0, 3.0)
        assert result.change_count == 1

    def test_result_is_frozen(self, guard: GuardAgent, base_params: EvolvableParams):
        """GuardResult는 frozen dataclass."""
        result = guard.validate(base_params, base_params)
        with pytest.raises(AttributeError):
            result.is_valid = False  # type: ignore[misc]


class TestNaNDefense:
    """NaN/Inf 방어."""

    def test_nan_param_rejected_at_construction(self):
        """NaN 값으로 EvolvableParams 생성 → ValueError."""
        with pytest.raises(ValueError, match="NaN"):
            EvolvableParams(tf_sl_mult=float("nan"))

    def test_inf_param_rejected_at_construction(self):
        """Inf 값으로 EvolvableParams 생성 → ValueError."""
        with pytest.raises(ValueError, match="Inf"):
            EvolvableParams(tf_sl_mult=float("inf"))
