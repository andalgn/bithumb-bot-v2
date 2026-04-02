"""자동 최적화 + config 반영 테스트."""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from app.config import BacktestConfig
from backtesting.daemon import BacktestDaemon


def test_auto_optimize_disabled():
    """auto_optimize_enabled=False면 최적화를 건너뛴다."""
    config = BacktestConfig(auto_optimize_enabled=False)
    journal = MagicMock()
    daemon = BacktestDaemon(journal=journal, config=config)
    result = asyncio.get_event_loop().run_until_complete(daemon._run_auto_optimize())
    assert result == []


def test_auto_optimize_no_store():
    """store 없으면 최적화를 건너뛴다."""
    journal = MagicMock()
    daemon = BacktestDaemon(journal=journal)
    result = asyncio.get_event_loop().run_until_complete(daemon._run_auto_optimize())
    assert result == []


def test_collect_candles_no_store():
    """store 없으면 데이터 수집을 건너뛴다."""
    journal = MagicMock()
    daemon = BacktestDaemon(journal=journal)
    result = asyncio.get_event_loop().run_until_complete(daemon._collect_candles())
    assert result == 0


def test_propose_via_approval_creates_pending():
    """_propose_via_approval이 ApprovalWorkflow에 PendingChange를 생성한다."""
    from app.approval_workflow import ApprovalWorkflow
    from strategy.guard_agent import GuardAgent
    from strategy.strategy_params import EvolvableParams

    journal = MagicMock()
    approval = ApprovalWorkflow(
        pending_path=Path(tempfile.mktemp(suffix=".json")),
    )
    current = EvolvableParams()  # 기본값
    daemon = BacktestDaemon(
        journal=journal,
        approval=approval,
        guard=GuardAgent(),
        current_params=current,
    )

    candidate = {
        "strategy": "trend_follow",
        "params": {"sl_mult": 3.0, "tp_rr": 2.0},
        "pf": 1.8,
        "source": "auto_optimize",
        "trades": 50,
    }

    asyncio.get_event_loop().run_until_complete(daemon._propose_via_approval(candidate))

    pending = approval.list_pending()
    assert len(pending) == 1
    assert pending[0].risk_level in ("low", "medium", "high")
    assert pending[0].status == "pending"


def test_propose_via_approval_skips_without_approval():
    """ApprovalWorkflow 미설정 시 건너뛴다."""
    journal = MagicMock()
    daemon = BacktestDaemon(journal=journal)

    candidate = {
        "strategy": "trend_follow",
        "params": {"sl_mult": 3.0},
        "pf": 1.5,
        "source": "test",
    }

    # Should not raise
    asyncio.get_event_loop().run_until_complete(daemon._propose_via_approval(candidate))


def test_parse_time():
    """시간 문자열 파싱."""
    assert BacktestDaemon._parse_time("02:30") == (2, 30)
    assert BacktestDaemon._parse_time("00:00") == (0, 0)


def test_parse_weekday():
    """요일 문자열 파싱."""
    assert BacktestDaemon._parse_weekday("sunday") == 6
    assert BacktestDaemon._parse_weekday("monday") == 0
