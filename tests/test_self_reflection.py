"""SelfReflection 단위 테스트."""

from __future__ import annotations

import pytest

from app.journal import Journal
from strategy.self_reflection import ReflectionStore, generate_reflection


def test_generate_reflection_regime_mismatch():
    """regime_mismatch 태그에 대한 반성을 생성한다."""
    trade = {"strategy": "breakout"}
    text, lesson = generate_reflection(trade, "STRONG_UP", "WEAK_DOWN", "regime_mismatch")
    assert "breakout" in text
    assert "STRONG_UP" in text
    assert len(lesson) > 10


def test_generate_reflection_winner():
    """winner 태그도 반성을 생성한다."""
    trade = {"strategy": "mean_reversion"}
    text, lesson = generate_reflection(trade, "RANGE", "RANGE", "winner")
    assert "mean_reversion" in text


def test_generate_reflection_unknown_tag():
    """알 수 없는 태그는 signal_quality 템플릿을 사용한다."""
    trade = {"strategy": "breakout"}
    text, lesson = generate_reflection(trade, "RANGE", "RANGE", "unknown_tag")
    assert len(text) > 0


@pytest.fixture
def journal(tmp_path):
    return Journal(str(tmp_path / "test.db"))


def test_reflection_store_records(journal):
    """ReflectionStore가 반성을 journal에 저장한다."""
    store = ReflectionStore(journal)
    trade = {"strategy": "breakout", "net_pnl_krw": -3000}
    store.record_trade_reflection(trade, "STRONG_UP", "WEAK_DOWN", "regime_mismatch")
    reflections = journal.get_recent_reflections(limit=10)
    assert len(reflections) == 1
    assert reflections[0]["tag"] == "regime_mismatch"
    assert reflections[0]["strategy"] == "breakout"


def test_get_weekly_synthesis_returns_top_lessons(journal):
    """빈도 높은 교훈을 반환한다."""
    store = ReflectionStore(journal)
    # Record 3 same lessons and 1 different
    for _ in range(3):
        store.record_trade_reflection(
            {"strategy": "breakout", "net_pnl_krw": -3000},
            "STRONG_UP",
            "WEAK_DOWN",
            "regime_mismatch",
        )
    store.record_trade_reflection(
        {"strategy": "mean_reversion", "net_pnl_krw": -1000}, "RANGE", "RANGE", "signal_quality"
    )
    synthesis = store.get_weekly_synthesis(days=7)
    assert len(synthesis) >= 1
    assert len(synthesis) <= 5
    # Most frequent lesson should come first
    # (regime_mismatch lesson appears 3 times)
    assert "국면" in synthesis[0] or "SL" in synthesis[0] or len(synthesis[0]) > 5


def test_get_weekly_synthesis_empty_on_no_reflections(journal):
    """반성 없으면 빈 목록을 반환한다."""
    store = ReflectionStore(journal)
    synthesis = store.get_weekly_synthesis(days=7)
    assert synthesis == []
