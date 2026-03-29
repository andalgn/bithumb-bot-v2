"""Evolution Pipeline 통합 테스트.

Auto-Optimize, Auto-Research, Darwin 후보를 비교하여
최고 PF 1개만 ApprovalWorkflow로 제안하는 파이프라인 검증.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import yaml

from app.config import BacktestConfig
from backtesting.daemon import BacktestDaemon


def _make_daemon(
    trades: list[dict] | None = None,
    auto_optimize_enabled: bool = True,
    auto_research_enabled: bool = True,
    darwin: object | None = None,
) -> BacktestDaemon:
    """테스트용 BacktestDaemon 생성."""
    config = BacktestConfig(
        auto_optimize_enabled=auto_optimize_enabled,
        auto_research_enabled=auto_research_enabled,
        auto_apply_min_pf=1.0,
        auto_apply_min_trades=5,
    )
    journal = MagicMock()
    journal.get_recent_trades.return_value = trades or []
    notifier = AsyncMock()
    notifier.send = AsyncMock(return_value=True)
    return BacktestDaemon(
        journal=journal,
        notifier=notifier,
        config=config,
        darwin=darwin,
    )


def test_pipeline_skips_when_insufficient_trades():
    """거래 10건 미만이면 파이프라인을 건너뛴다."""
    daemon = _make_daemon(trades=[{"net_pnl_krw": 100}] * 5)

    asyncio.get_event_loop().run_until_complete(
        daemon._run_evolution_pipeline()
    )

    daemon._notifier.send.assert_called_once()
    call_msg = daemon._notifier.send.call_args[0][0]
    assert "부족" in call_msg


def test_pipeline_selects_best_candidate():
    """3개 후보 중 PF 최고를 선택한다."""
    # baseline PF = 500/900 ≈ 0.56
    trades = [{"net_pnl_krw": 50}] * 10 + [{"net_pnl_krw": -90}] * 10
    daemon = _make_daemon(trades=trades)

    # 후보 목록 직접 주입 (각 모듈을 모킹)
    opt_candidates = [
        {"source": "auto_optimize", "strategy": "trend_follow",
         "params": {"sl_mult": 4.0}, "pf": 1.5, "trades": 40, "win_rate": 0.6},
    ]
    research_candidates = [
        {"source": "auto_research", "strategy": "mean_reversion",
         "params": {"sl_mult": 7.0}, "pf": 1.8, "trades": 35, "win_rate": 0.55},
    ]
    darwin_candidates = [
        {"source": "darwin", "strategy": "dca",
         "params": {"sl_pct": 0.05}, "pf": 1.3, "trades": 50, "win_rate": 0.65},
    ]

    with (
        patch.object(daemon, "_run_auto_optimize", new_callable=AsyncMock, return_value=opt_candidates),
        patch.object(daemon, "_run_auto_research", new_callable=AsyncMock, return_value=research_candidates),
        patch.object(daemon, "_run_darwin_candidate", return_value=darwin_candidates),
        patch.object(daemon, "_propose_via_approval", new_callable=AsyncMock) as mock_propose,
    ):
        asyncio.get_event_loop().run_until_complete(
            daemon._run_evolution_pipeline()
        )

        # PF 1.8 (auto_research)이 선택되어야 함
        mock_propose.assert_called_once()
        candidate = mock_propose.call_args[0][0]
        assert candidate["strategy"] == "mean_reversion"
        assert candidate["params"] == {"sl_mult": 7.0}


def test_pipeline_skips_when_all_worse_than_baseline():
    """모든 후보가 baseline PF보다 낮으면 적용하지 않는다."""
    # baseline PF = 15/20 = 0.75... 사실 PF = gross_wins/gross_losses
    # 15 * 100 = 1500 wins, 5 * 80 = 400 losses → PF = 1500/400 = 3.75
    trades = [{"net_pnl_krw": 100}] * 15 + [{"net_pnl_krw": -80}] * 5
    daemon = _make_daemon(trades=trades)

    # baseline PF = 3.75, 후보 PF 모두 이하
    weak_candidates = [
        {"source": "auto_optimize", "strategy": "trend_follow",
         "params": {"sl_mult": 4.0}, "pf": 1.2, "trades": 40, "win_rate": 0.5},
    ]

    with (
        patch.object(daemon, "_run_auto_optimize", new_callable=AsyncMock, return_value=weak_candidates),
        patch.object(daemon, "_run_auto_research", new_callable=AsyncMock, return_value=[]),
        patch.object(daemon, "_run_darwin_candidate", return_value=[]),
        patch.object(daemon, "_propose_via_approval", new_callable=AsyncMock) as mock_propose,
    ):
        asyncio.get_event_loop().run_until_complete(
            daemon._run_evolution_pipeline()
        )
        mock_propose.assert_not_called()


def test_pipeline_applies_config_once_only():
    """config.yaml 적용이 정확히 1회만 발생한다."""
    trades = [{"net_pnl_krw": 50}] * 10 + [{"net_pnl_krw": -90}] * 10
    daemon = _make_daemon(trades=trades)

    # baseline PF = 500/900 ≈ 0.56, 후보 2개 모두 baseline 초과
    candidates = [
        {"source": "auto_optimize", "strategy": "trend_follow",
         "params": {"sl_mult": 4.0}, "pf": 1.5, "trades": 40, "win_rate": 0.6},
        {"source": "auto_research", "strategy": "mean_reversion",
         "params": {"sl_mult": 7.0}, "pf": 2.0, "trades": 35, "win_rate": 0.55},
    ]

    with (
        patch.object(daemon, "_run_auto_optimize", new_callable=AsyncMock, return_value=candidates[:1]),
        patch.object(daemon, "_run_auto_research", new_callable=AsyncMock, return_value=candidates[1:]),
        patch.object(daemon, "_run_darwin_candidate", return_value=[]),
        patch.object(daemon, "_propose_via_approval", new_callable=AsyncMock) as mock_propose,
    ):
        asyncio.get_event_loop().run_until_complete(
            daemon._run_evolution_pipeline()
        )
        assert mock_propose.call_count == 1


def test_pipeline_darwin_champion_replacement():
    """Darwin 후보가 선택되면 replace_champion이 호출된다."""
    trades = [{"net_pnl_krw": 50}] * 10 + [{"net_pnl_krw": -90}] * 10
    darwin = MagicMock()
    daemon = _make_daemon(trades=trades, darwin=darwin)

    mock_champion = MagicMock()
    darwin_candidates = [
        {"source": "darwin", "strategy": "mean_reversion",
         "params": {"sl_mult": 6.0}, "pf": 3.0, "trades": 50, "win_rate": 0.7,
         "_new_champion": mock_champion},
    ]

    with (
        patch.object(daemon, "_run_auto_optimize", new_callable=AsyncMock, return_value=[]),
        patch.object(daemon, "_run_auto_research", new_callable=AsyncMock, return_value=[]),
        patch.object(daemon, "_run_darwin_candidate", return_value=darwin_candidates),
        patch.object(daemon, "_propose_via_approval", new_callable=AsyncMock),
    ):
        asyncio.get_event_loop().run_until_complete(
            daemon._run_evolution_pipeline()
        )
        darwin.replace_champion.assert_called_once_with(mock_champion)


def test_darwin_candidate_no_darwin():
    """darwin 객체가 없으면 빈 리스트를 반환한다."""
    daemon = _make_daemon(darwin=None)
    assert daemon._run_darwin_candidate() == []


def test_auto_research_returns_candidates():
    """auto_research가 후보 리스트를 반환한다 (config 미적용)."""
    daemon = _make_daemon()

    mock_result = MagicMock()
    mock_result.verdict = "KEEP"
    mock_result.strategy = "mean_reversion"
    mock_result.params_changed = {"sl_mult": 6.5}
    mock_result.result_pf = 1.8
    mock_result.result_trades = 40

    with patch("strategy.auto_researcher.AutoResearcher") as MockResearcher:
        instance = MockResearcher.return_value
        instance.run_session = AsyncMock(return_value=[mock_result])
        daemon._store = MagicMock()

        result = asyncio.get_event_loop().run_until_complete(
            daemon._run_auto_research()
        )

        assert len(result) == 1
        assert result[0]["source"] == "auto_research"
        assert result[0]["strategy"] == "mean_reversion"
        assert result[0]["pf"] == 1.8
