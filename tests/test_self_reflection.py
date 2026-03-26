"""SelfReflection 단위 테스트."""
from __future__ import annotations
import pytest
from strategy.self_reflection import generate_reflection, ReflectionStore
from app.journal import Journal


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
