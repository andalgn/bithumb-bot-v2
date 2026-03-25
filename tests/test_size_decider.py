"""SizeDecider 직접 단위 테스트."""
from __future__ import annotations

import pytest

from app.data_types import Strategy
from strategy.size_decider import SizeDecider, SizeDecision


def test_high_score_returns_full():
    """점수가 FULL 컷오프(75) 이상이면 FULL을 반환한다."""
    decider = SizeDecider()
    result = decider.decide(Strategy.TREND_FOLLOW, score=80.0)
    assert result == SizeDecision.FULL


def test_mid_score_returns_probe():
    """점수가 PROBE 범위(60~75)이면 PROBE를 반환한다."""
    decider = SizeDecider()
    result = decider.decide(Strategy.TREND_FOLLOW, score=65.0)
    assert result == SizeDecision.PROBE


def test_low_score_returns_hold():
    """점수가 컷오프(60) 미만이면 HOLD를 반환한다."""
    decider = SizeDecider()
    result = decider.decide(Strategy.TREND_FOLLOW, score=50.0)
    assert result == SizeDecision.HOLD


def test_group2_cutoffs():
    """그룹 2 전략(BREAKOUT)은 더 높은 컷오프(full=80, probe_min=65)를 사용한다."""
    decider = SizeDecider()
    # 79점: FULL 미달이지만 PROBE 범위
    assert decider.decide(Strategy.BREAKOUT, score=79.0) == SizeDecision.PROBE
    # 80점: FULL
    assert decider.decide(Strategy.BREAKOUT, score=80.0) == SizeDecision.FULL
    # 64점: HOLD
    assert decider.decide(Strategy.BREAKOUT, score=64.0) == SizeDecision.HOLD


def test_constructor_accepts_score_cutoff_none():
    """score_cutoff=None으로 생성하면 기본값을 사용한다."""
    decider = SizeDecider(score_cutoff=None)
    # 기본 그룹1 컷오프: full=75
    assert decider.decide(Strategy.TREND_FOLLOW, score=75.0) == SizeDecision.FULL
    assert decider.decide(Strategy.TREND_FOLLOW, score=74.9) == SizeDecision.PROBE
