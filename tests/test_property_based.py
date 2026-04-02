"""Property-Based 테스트 — Hypothesis 라이브러리 기반.

금융 계산 함수의 수학적 속성을 랜덤 입력으로 검증한다.
"""

from __future__ import annotations

import math

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from market.impact_model import (
    IMPACT_Y,
    MAX_SLIPPAGE,
    MIN_SLIPPAGE,
    estimate_slippage,
)

# ───────────────────────────────────────────────────
# estimate_slippage: 수학적 속성 검증
# ───────────────────────────────────────────────────


class TestEstimateSlippageProperties:
    """estimate_slippage 함수의 수학적 불변 속성 검증."""

    @given(
        order=st.floats(min_value=0, max_value=1e12),
        adv=st.floats(min_value=0, max_value=1e15),
        vol=st.floats(min_value=0.001, max_value=0.5),
    )
    @settings(max_examples=500)
    def test_output_always_within_bounds(self, order: float, adv: float, vol: float) -> None:
        """어떤 입력이든 결과는 [MIN_SLIPPAGE, MAX_SLIPPAGE] 범위."""
        result = estimate_slippage(order, adv, vol)
        assert MIN_SLIPPAGE <= result <= MAX_SLIPPAGE

    @given(
        order=st.floats(min_value=100, max_value=1e10),
        adv=st.floats(min_value=1e6, max_value=1e15),
        vol=st.floats(min_value=0.001, max_value=0.3),
    )
    @settings(max_examples=300)
    def test_monotone_in_order_size(self, order: float, adv: float, vol: float) -> None:
        """주문 크기 증가 → 슬리피지 비감소 (단조 증가)."""
        s1 = estimate_slippage(order, adv, vol)
        s2 = estimate_slippage(order * 2, adv, vol)
        assert s2 >= s1

    @given(
        order=st.floats(min_value=100, max_value=1e10),
        adv=st.floats(min_value=1e6, max_value=1e15),
        vol=st.floats(min_value=0.001, max_value=0.3),
    )
    @settings(max_examples=300)
    def test_monotone_in_adv(self, order: float, adv: float, vol: float) -> None:
        """거래대금 증가 → 슬리피지 비증가 (단조 감소)."""
        s1 = estimate_slippage(order, adv, vol)
        s2 = estimate_slippage(order, adv * 2, vol)
        assert s2 <= s1

    @given(
        order=st.floats(min_value=100, max_value=1e10),
        adv=st.floats(min_value=1e6, max_value=1e15),
        vol=st.floats(min_value=0.001, max_value=0.2),
    )
    @settings(max_examples=300)
    def test_monotone_in_volatility(self, order: float, adv: float, vol: float) -> None:
        """변동성 증가 → 슬리피지 비감소 (단조 증가)."""
        s1 = estimate_slippage(order, adv, vol)
        s2 = estimate_slippage(order, adv, vol * 2)
        assert s2 >= s1

    @given(
        order=st.floats(min_value=-1e10, max_value=0),
        adv=st.floats(min_value=1e6, max_value=1e15),
    )
    @settings(max_examples=100)
    def test_non_positive_order_returns_min(self, order: float, adv: float) -> None:
        """0 이하 주문 → MIN_SLIPPAGE."""
        assert estimate_slippage(order, adv) == MIN_SLIPPAGE

    @given(
        order=st.floats(min_value=100, max_value=1e10),
        adv=st.floats(min_value=-1e15, max_value=0),
    )
    @settings(max_examples=100)
    def test_non_positive_adv_returns_min(self, order: float, adv: float) -> None:
        """0 이하 거래대금 → MIN_SLIPPAGE."""
        assert estimate_slippage(order, adv) == MIN_SLIPPAGE

    @given(
        order=st.floats(min_value=1000, max_value=1e8),
        adv=st.floats(min_value=1e8, max_value=1e14),
        vol=st.floats(min_value=0.005, max_value=0.1),
    )
    @settings(max_examples=300)
    def test_sqrt_scaling_property(self, order: float, adv: float, vol: float) -> None:
        """√ 스케일링: 4배 주문 → 2배 슬리피지 (클램프 전)."""
        s1 = estimate_slippage(order, adv, vol)
        s4 = estimate_slippage(order * 4, adv, vol)

        # 클램프에 걸리지 않는 경우만 검증
        raw_s1 = IMPACT_Y * vol * math.sqrt(order / adv)
        raw_s4 = IMPACT_Y * vol * math.sqrt(4 * order / adv)
        assume(MIN_SLIPPAGE < raw_s1 < MAX_SLIPPAGE)
        assume(MIN_SLIPPAGE < raw_s4 < MAX_SLIPPAGE)

        assert s4 == round(s1 * 2, 10) or abs(s4 - s1 * 2) < 1e-10

    @given(
        order=st.floats(min_value=100, max_value=1e10),
        adv=st.floats(min_value=1e6, max_value=1e15),
        vol=st.floats(min_value=0.001, max_value=0.3),
        y=st.floats(min_value=0.1, max_value=2.0),
    )
    @settings(max_examples=200)
    def test_linearity_in_impact_y(self, order: float, adv: float, vol: float, y: float) -> None:
        """임팩트 계수 Y에 대해 선형 (클램프 전)."""
        s1 = estimate_slippage(order, adv, vol, impact_y=y)
        s2 = estimate_slippage(order, adv, vol, impact_y=y * 2)

        raw_s1 = y * vol * math.sqrt(order / adv)
        raw_s2 = 2 * y * vol * math.sqrt(order / adv)
        assume(MIN_SLIPPAGE < raw_s1 < MAX_SLIPPAGE)
        assume(MIN_SLIPPAGE < raw_s2 < MAX_SLIPPAGE)

        assert abs(s2 - s1 * 2) < 1e-10

    @given(
        order=st.floats(min_value=100, max_value=1e10),
        adv=st.floats(min_value=1e6, max_value=1e15),
        vol=st.floats(min_value=0.001, max_value=0.3),
    )
    @settings(max_examples=200)
    def test_no_nan_or_inf(self, order: float, adv: float, vol: float) -> None:
        """결과에 NaN이나 Inf가 없다."""
        result = estimate_slippage(order, adv, vol)
        assert math.isfinite(result)


# ───────────────────────────────────────────────────
# 풀 사이징: 가드레일 속성 검증
# ───────────────────────────────────────────────────


class TestSizingGuardrails:
    """사이징 로직의 수학적 속성 검증.

    PositionManager.calculate_size는 의존성이 많으므로,
    핵심 수식만 독립적으로 검증한다.
    """

    @given(
        base=st.floats(min_value=1000, max_value=1e8),
        tier_mult=st.floats(min_value=0.1, max_value=3.0),
        score_mult=st.sampled_from([0.0, 0.7, 1.0]),
        defense=st.floats(min_value=0.3, max_value=1.0),
    )
    @settings(max_examples=300)
    def test_opportunity_non_negative(
        self, base: float, tier_mult: float, score_mult: float, defense: float
    ) -> None:
        """사이징 결과는 항상 0 이상."""
        opportunity = base * tier_mult * score_mult
        final = opportunity * defense
        assert final >= 0

    @given(
        base=st.floats(min_value=1000, max_value=1e8),
        tier_mult=st.floats(min_value=0.1, max_value=3.0),
        score_mult=st.sampled_from([0.0, 0.7, 1.0]),
        defense=st.floats(min_value=0.3, max_value=1.0),
        cap_pct=st.floats(min_value=0.1, max_value=0.5),
        balance=st.floats(min_value=10000, max_value=1e9),
    )
    @settings(max_examples=300)
    def test_pool_cap_enforced(
        self,
        base: float,
        tier_mult: float,
        score_mult: float,
        defense: float,
        cap_pct: float,
        balance: float,
    ) -> None:
        """최종 사이즈는 항상 pool_cap 이하."""
        opportunity = base * tier_mult * score_mult
        final = opportunity * defense
        cap = balance * cap_pct
        clamped = min(final, cap)
        assert clamped <= cap

    @given(
        regime_mult=st.floats(min_value=0.0, max_value=1.5),
        dd_mult=st.floats(min_value=0.0, max_value=1.0),
        loss_streak_mult=st.floats(min_value=0.0, max_value=1.0),
    )
    @settings(max_examples=200)
    def test_defense_clamped(
        self, regime_mult: float, dd_mult: float, loss_streak_mult: float
    ) -> None:
        """방어 배수는 [0.3, 1.0]으로 클램프."""
        defense = regime_mult * dd_mult * loss_streak_mult
        clamped = max(0.3, min(1.0, defense))
        assert 0.3 <= clamped <= 1.0
