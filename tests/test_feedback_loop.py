"""FeedbackLoop 단위 테스트."""
from __future__ import annotations
import pytest
from unittest.mock import MagicMock
from strategy.feedback_loop import FeedbackLoop, FailurePattern


@pytest.fixture
def mock_journal():
    journal = MagicMock()
    # Return trades that include 2 regime_mismatch + STRONG_UP + breakout
    # and 1 signal_quality + RANGE + mean_reversion
    import time
    now_ms = int(time.time() * 1000)
    day_ms = 86400 * 1000
    journal.get_recent_trades.return_value = [
        {"tag": "regime_mismatch", "strategy": "breakout", "regime": "STRONG_UP",
         "net_pnl_krw": -5000, "exit_time": now_ms - 1000},
        {"tag": "regime_mismatch", "strategy": "breakout", "regime": "STRONG_UP",
         "net_pnl_krw": -3000, "exit_time": now_ms - 2000},
        {"tag": "signal_quality", "strategy": "mean_reversion", "regime": "RANGE",
         "net_pnl_krw": -2000, "exit_time": now_ms - 3000},
        {"tag": "winner", "strategy": "breakout", "regime": "STRONG_UP",
         "net_pnl_krw": 8000, "exit_time": now_ms - 4000},
    ]
    return journal


def test_get_failure_patterns_returns_top_3(mock_journal):
    """실패 패턴을 count 기준으로 정렬하여 최대 3개 반환한다."""
    fb = FeedbackLoop(mock_journal)
    patterns = fb.get_failure_patterns(days=7)
    assert len(patterns) <= 3
    # regime_mismatch/breakout/STRONG_UP should be first (count=2)
    assert patterns[0].tag == "regime_mismatch"
    assert patterns[0].count == 2
    assert patterns[0].avg_loss_krw == pytest.approx(-4000.0)


def test_winners_excluded_from_patterns(mock_journal):
    """winner 태그는 패턴에서 제외된다."""
    fb = FeedbackLoop(mock_journal)
    patterns = fb.get_failure_patterns(days=7)
    assert all(p.tag != "winner" for p in patterns)


def test_old_trades_excluded(mock_journal):
    """기간 외 거래는 제외된다."""
    import time
    now_ms = int(time.time() * 1000)
    old_ms = now_ms - 10 * 86400 * 1000  # 10 days ago
    mock_journal.get_recent_trades.return_value = [
        {"tag": "signal_quality", "strategy": "breakout", "regime": "RANGE",
         "net_pnl_krw": -5000, "exit_time": old_ms},
    ]
    fb = FeedbackLoop(mock_journal)
    patterns = fb.get_failure_patterns(days=7)
    assert len(patterns) == 0


def test_generate_hypotheses_empty_on_no_patterns():
    """패턴 없으면 빈 목록을 반환한다."""
    import asyncio
    from unittest.mock import MagicMock
    fb = FeedbackLoop(MagicMock())
    result = asyncio.get_event_loop().run_until_complete(
        fb.generate_hypotheses([], {})
    )
    assert result == []


def test_generate_hypotheses_empty_on_claude_failure(mock_journal):
    """Claude CLI 실패 시 빈 목록을 반환한다."""
    import asyncio
    from unittest.mock import AsyncMock, patch

    patterns = [
        FailurePattern(
            tag="regime_mismatch", strategy="breakout", regime="STRONG_UP",
            count=2, avg_loss_krw=-4000.0, total_loss_krw=-8000.0,
        )
    ]
    fb = FeedbackLoop(mock_journal)
    with patch("app.llm_client.call_claude", new_callable=AsyncMock, return_value=None):
        result = asyncio.get_event_loop().run_until_complete(
            fb.generate_hypotheses(patterns, {"cutoff": 72.0})
        )
    assert result == []
