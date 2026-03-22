"""Tier별 전략 파라미터 테스트."""

from app.data_types import Tier


def test_tier_specific_params_merge():
    """Tier별 파라미터가 공통값 위에 오버라이드된다."""
    sp = {
        "sl_mult": 3.0,
        "tp_rr": 2.5,
        "tier1": {"sl_mult": 2.5, "tp_rr": 2.5},
        "tier2": {"sl_mult": 2.5, "tp_rr": 3.5},
        "tier3": {"sl_mult": 3.0, "tp_rr": 2.0},
    }

    # Tier1 병합
    tier_key = f"tier{Tier.TIER1.value}"
    tier_sp = sp.get(tier_key, {})
    merged = {k: v for k, v in {**sp, **tier_sp}.items() if not isinstance(v, dict)}
    assert merged["sl_mult"] == 2.5
    assert merged["tp_rr"] == 2.5

    # Tier2 병합
    tier_key = f"tier{Tier.TIER2.value}"
    tier_sp = sp.get(tier_key, {})
    merged = {k: v for k, v in {**sp, **tier_sp}.items() if not isinstance(v, dict)}
    assert merged["sl_mult"] == 2.5
    assert merged["tp_rr"] == 3.5

    # Tier3 병합
    tier_key = f"tier{Tier.TIER3.value}"
    tier_sp = sp.get(tier_key, {})
    merged = {k: v for k, v in {**sp, **tier_sp}.items() if not isinstance(v, dict)}
    assert merged["sl_mult"] == 3.0
    assert merged["tp_rr"] == 2.0


def test_tier_fallback_to_common():
    """Tier별 키가 없으면 공통값을 사용한다."""
    sp = {
        "sl_mult": 3.0,
        "tp_rr": 2.5,
    }

    tier_key = f"tier{Tier.TIER1.value}"
    tier_sp = sp.get(tier_key, {})
    merged = {k: v for k, v in {**sp, **tier_sp}.items() if not isinstance(v, dict)}
    assert merged["sl_mult"] == 3.0
    assert merged["tp_rr"] == 2.5


def test_tier_partial_override():
    """Tier별 키가 일부만 있으면 나머지는 공통값을 사용한다."""
    sp = {
        "sl_mult": 3.0,
        "tp_rr": 2.5,
        "tier1": {"sl_mult": 2.0},
    }

    tier_key = f"tier{Tier.TIER1.value}"
    tier_sp = sp.get(tier_key, {})
    merged = {k: v for k, v in {**sp, **tier_sp}.items() if not isinstance(v, dict)}
    assert merged["sl_mult"] == 2.0  # tier1 오버라이드
    assert merged["tp_rr"] == 2.5  # 공통값 유지
