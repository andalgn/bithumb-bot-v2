"""Square-Root Impact 모델 단위 테스트."""

from __future__ import annotations

import math

import pytest

from market.impact_model import (
    IMPACT_Y,
    MAX_SLIPPAGE,
    MIN_SLIPPAGE,
    estimate_slippage,
)


class TestEstimateSlippage:
    """estimate_slippage 함수 테스트."""

    def test_basic_calculation(self) -> None:
        """기본 공식 검증: Y × σ × √(Q/V)."""
        order = 30_000  # 3만원 주문
        adv = 100_000_000  # 1억원 일평균 거래대금
        vol = 0.03  # 3% 변동성

        expected = IMPACT_Y * vol * math.sqrt(order / adv)
        result = estimate_slippage(order, adv, vol)
        assert result == pytest.approx(expected)

    def test_larger_order_higher_slippage(self) -> None:
        """주문 크기가 클수록 슬리피지 증가."""
        adv = 100_000_000
        small = estimate_slippage(10_000, adv)
        large = estimate_slippage(1_000_000, adv)
        assert large > small

    def test_lower_adv_higher_slippage(self) -> None:
        """거래대금이 작을수록 슬리피지 증가."""
        order = 30_000
        liquid = estimate_slippage(order, 1_000_000_000)  # 10억
        illiquid = estimate_slippage(order, 10_000_000)  # 1천만
        assert illiquid > liquid

    def test_higher_volatility_higher_slippage(self) -> None:
        """변동성이 높을수록 슬리피지 증가."""
        order, adv = 30_000, 100_000_000
        calm = estimate_slippage(order, adv, volatility=0.01)
        volatile = estimate_slippage(order, adv, volatility=0.10)
        assert volatile > calm

    def test_min_clamp(self) -> None:
        """매우 작은 주문/큰 거래대금 → 최소값."""
        result = estimate_slippage(100, 10_000_000_000)  # 100원/100억
        assert result == MIN_SLIPPAGE

    def test_max_clamp(self) -> None:
        """매우 큰 주문/작은 거래대금 → 최대값."""
        result = estimate_slippage(50_000_000, 1_000_000)  # 5천만/100만
        assert result == MAX_SLIPPAGE

    def test_zero_order(self) -> None:
        """주문 0원 → 최소값."""
        assert estimate_slippage(0, 100_000_000) == MIN_SLIPPAGE

    def test_zero_adv(self) -> None:
        """거래대금 0 → 최소값."""
        assert estimate_slippage(30_000, 0) == MIN_SLIPPAGE

    def test_realistic_tier1(self) -> None:
        """BTC 실제 시나리오: 3만원 / 500억 거래대금 / 2% 변동성."""
        slip = estimate_slippage(30_000, 50_000_000_000, 0.02)
        assert slip < 0.001  # 0.1% 미만 (유동성 우수)

    def test_realistic_tier3(self) -> None:
        """소형코인 실제 시나리오: 3만원 / 500만 거래대금 / 5% 변동성."""
        slip = estimate_slippage(30_000, 5_000_000, 0.05)
        assert slip > 0.001  # 0.1% 이상 (유동성 부족)

    def test_sqrt_scaling(self) -> None:
        """√ 스케일링 검증: 4배 주문 → 2배 슬리피지."""
        adv, vol = 100_000_000, 0.03
        s1 = estimate_slippage(10_000, adv, vol)
        s4 = estimate_slippage(40_000, adv, vol)
        assert s4 == pytest.approx(s1 * 2, rel=0.01)
