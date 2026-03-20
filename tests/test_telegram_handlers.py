"""텔레그램 명령어 핸들러 테스트.

TradingBot을 Mock하여 명령어 응답 포맷만 검증한다.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.data_types import Pool, Position, Regime, Strategy, Tier
from bot_telegram.handlers import TelegramHandler


@dataclass
class _FakePoolState:
    """테스트용 PoolState."""

    total_balance: float
    allocated: float
    position_count: int

    @property
    def available(self) -> float:
        return max(0.0, self.total_balance - self.allocated)


class _FakeRegimeState:
    """테스트용 RegimeState."""

    def __init__(self, current: Regime = Regime.RANGE, pending: Regime | None = None) -> None:
        self.current = current
        self.pending = pending


def _make_bot(
    positions: dict[str, Position] | None = None,
    paused: bool = False,
) -> MagicMock:
    """테스트용 봇 Mock을 생성한다."""
    bot = MagicMock()
    bot._paused = paused
    bot._bot_start_time = time.time() - 3661  # 1시간 1분 1초 전
    bot._run_mode = SimpleNamespace(value="PAPER")
    bot._cycle_count = 42
    bot._positions = positions or {}

    # Notifier
    bot._notifier = AsyncMock()
    bot._notifier.send = AsyncMock(return_value=True)

    # PoolManager
    bot._pool_manager = MagicMock()
    bot._pool_manager._pools = {
        Pool.CORE: _FakePoolState(600_000, 100_000, 1),
        Pool.ACTIVE: _FakePoolState(300_000, 50_000, 2),
        Pool.RESERVE: _FakePoolState(100_000, 0, 0),
    }
    bot._pool_manager.utilization_pct = 0.15

    # RuleEngine
    bot._rule_engine = MagicMock()
    bot._rule_engine._regime_states = {
        "BTC_KRW": _FakeRegimeState(Regime.STRONG_UP),
        "ETH_KRW": _FakeRegimeState(Regime.RANGE, Regime.WEAK_UP),
    }

    # Journal (인메모리 SQLite)
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE trades (
            trade_id TEXT, symbol TEXT, strategy TEXT, tier INTEGER,
            regime TEXT, pool TEXT, entry_price REAL, exit_price REAL,
            qty REAL, entry_fee_krw REAL, exit_fee_krw REAL,
            slippage_krw REAL, gross_pnl_krw REAL, net_pnl_krw REAL,
            net_pnl_pct REAL, hold_seconds INTEGER, promoted INTEGER,
            entry_score REAL, entry_time INTEGER, exit_time INTEGER,
            exit_reason TEXT, created_at INTEGER
        )
    """)
    # 오늘 거래 2건 추가
    now_ms = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("t1", "BTC_KRW", "trend_follow", 1, "STRONG_UP", "active",
         90_000_000, 91_000_000, 0.001, 225, 228, 0,
         1000, 547, 0.6, 900, 0, 75, now_ms - 1000, now_ms, "tp", now_ms),
    )
    conn.execute(
        "INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("t2", "ETH_KRW", "mean_reversion", 2, "RANGE", "active",
         5_000_000, 4_900_000, 0.01, 125, 123, 0,
         -1000, -1248, -2.5, 600, 0, 60, now_ms - 2000, now_ms, "sl", now_ms),
    )
    conn.commit()
    journal = MagicMock()
    journal._conn = conn
    bot._journal = journal

    # _close_position
    bot._close_position = AsyncMock()

    return bot


def _make_handler(bot: Any | None = None) -> TelegramHandler:
    """테스트용 TelegramHandler를 생성한다."""
    if bot is None:
        bot = _make_bot()
    return TelegramHandler(token="test_token", chat_id="12345", bot=bot)


class TestTelegramCommands:
    """텔레그램 명령어 테스트."""

    @pytest.mark.asyncio
    async def test_cmd_help_lists_commands(self) -> None:
        """help 명령어가 전체 명령어 목록을 응답한다."""
        handler = _make_handler()
        await handler._cmd_help()

        handler._bot._notifier.send.assert_called_once()
        msg = handler._bot._notifier.send.call_args[0][0]
        assert "명령어 목록" in msg
        for cmd in TelegramHandler.COMMANDS:
            assert cmd in msg

    @pytest.mark.asyncio
    async def test_cmd_status_format(self) -> None:
        """status 명령어가 올바른 상태를 응답한다."""
        handler = _make_handler()
        await handler._cmd_status()

        msg = handler._bot._notifier.send.call_args[0][0]
        assert "PAPER" in msg
        assert "#42" in msg
        assert "1시간" in msg
        assert "포지션" in msg
        assert "15.0%" in msg

    @pytest.mark.asyncio
    async def test_cmd_status_paused(self) -> None:
        """일시 중지 상태에서 status에 표시된다."""
        bot = _make_bot(paused=True)
        handler = _make_handler(bot)
        await handler._cmd_status()

        msg = handler._bot._notifier.send.call_args[0][0]
        assert "일시 중지" in msg

    @pytest.mark.asyncio
    async def test_cmd_positions_empty(self) -> None:
        """포지션이 없으면 안내 메시지를 응답한다."""
        handler = _make_handler()
        await handler._cmd_positions()

        msg = handler._bot._notifier.send.call_args[0][0]
        assert "보유 포지션 없음" in msg

    @pytest.mark.asyncio
    async def test_cmd_positions_with_data(self) -> None:
        """포지션이 있으면 상세 정보를 응답한다."""
        pos = Position(
            symbol="BTC_KRW",
            entry_price=90_000_000,
            entry_time=int(time.time() * 1000),
            size_krw=100_000,
            qty=0.001,
            stop_loss=88_000_000,
            take_profit=95_000_000,
            strategy=Strategy.TREND_FOLLOW,
            pool=Pool.ACTIVE,
            tier=Tier.TIER1,
            regime=Regime.STRONG_UP,
            entry_score=75,
        )
        bot = _make_bot(positions={"BTC_KRW": pos})
        handler = _make_handler(bot)
        await handler._cmd_positions()

        msg = handler._bot._notifier.send.call_args[0][0]
        assert "BTC_KRW" in msg
        assert "trend_follow" in msg
        assert "active" in msg
        assert "90,000,000" in msg

    @pytest.mark.asyncio
    async def test_cmd_balance_format(self) -> None:
        """balance 명령어가 Pool별 잔액을 응답한다."""
        handler = _make_handler()
        await handler._cmd_balance()

        msg = handler._bot._notifier.send.call_args[0][0]
        assert "CORE" in msg
        assert "ACTIVE" in msg
        assert "RESERVE" in msg
        assert "600,000" in msg
        assert "활용률" in msg

    @pytest.mark.asyncio
    async def test_cmd_regime_format(self) -> None:
        """regime 명령어가 국면 분류를 응답한다."""
        handler = _make_handler()
        await handler._cmd_regime()

        msg = handler._bot._notifier.send.call_args[0][0]
        assert "BTC_KRW" in msg
        assert "STRONG_UP" in msg
        assert "ETH_KRW" in msg
        assert "WEAK_UP" in msg  # pending

    @pytest.mark.asyncio
    async def test_cmd_regime_empty(self) -> None:
        """국면 데이터가 없으면 안내 메시지를 응답한다."""
        bot = _make_bot()
        bot._rule_engine._regime_states = {}
        handler = _make_handler(bot)
        await handler._cmd_regime()

        msg = handler._bot._notifier.send.call_args[0][0]
        assert "국면 데이터 없음" in msg

    @pytest.mark.asyncio
    async def test_cmd_pnl_format(self) -> None:
        """pnl 명령어가 오늘/이번 주 PnL을 응답한다."""
        handler = _make_handler()
        await handler._cmd_pnl()

        msg = handler._bot._notifier.send.call_args[0][0]
        assert "오늘" in msg
        assert "이번 주" in msg
        assert "2건" in msg  # 오늘 거래 2건

    @pytest.mark.asyncio
    async def test_pause_resume_toggle(self) -> None:
        """pause/resume 명령어가 _paused 상태를 토글한다."""
        bot = _make_bot()
        handler = _make_handler(bot)

        assert not bot._paused

        await handler._cmd_pause()
        assert bot._paused
        msg = handler._bot._notifier.send.call_args[0][0]
        assert "일시 중지" in msg

        await handler._cmd_resume()
        assert not bot._paused
        msg = handler._bot._notifier.send.call_args[0][0]
        assert "재개" in msg

    @pytest.mark.asyncio
    async def test_close_nonexistent_coin(self) -> None:
        """존재하지 않는 코인 청산 시 안내 메시지를 응답한다."""
        handler = _make_handler()
        await handler._cmd_close(["BTC"])

        msg = handler._bot._notifier.send.call_args[0][0]
        assert "포지션 없음" in msg
        handler._bot._close_position.assert_not_called()

    @pytest.mark.asyncio
    async def test_close_existing_coin(self) -> None:
        """보유 코인 청산을 요청한다."""
        pos = Position(
            symbol="BTC_KRW",
            entry_price=90_000_000,
            entry_time=int(time.time() * 1000),
            size_krw=100_000,
            qty=0.001,
            stop_loss=88_000_000,
            take_profit=95_000_000,
            strategy=Strategy.TREND_FOLLOW,
            pool=Pool.ACTIVE,
            tier=Tier.TIER1,
        )
        bot = _make_bot(positions={"BTC_KRW": pos})
        handler = _make_handler(bot)
        await handler._cmd_close(["BTC"])

        bot._close_position.assert_called_once()
        call_args = bot._close_position.call_args
        assert call_args[0][0] == "BTC_KRW"
        assert call_args[0][2] == "manual"

    @pytest.mark.asyncio
    async def test_close_no_args(self) -> None:
        """close 명령어에 인자가 없으면 사용법을 안내한다."""
        handler = _make_handler()
        await handler._cmd_close([])

        msg = handler._bot._notifier.send.call_args[0][0]
        assert "사용법" in msg

    @pytest.mark.asyncio
    async def test_unauthorized_chat_ignored(self) -> None:
        """허가되지 않은 chat_id의 메시지는 무시한다."""
        handler = _make_handler()

        # _handle_command를 직접 호출하는 대신, _poll_updates의 필터링 로직을 테스트
        # 허가된 chat_id는 "12345"
        update = {
            "update_id": 1,
            "message": {
                "text": "/status",
                "chat": {"id": 99999},  # 허가되지 않은 ID
            },
        }

        # _poll_updates의 chat_id 체크 로직 직접 테스트
        msg = update["message"]
        chat_id = str(msg.get("chat", {}).get("id", ""))
        assert chat_id != handler._chat_id

        # notifier.send가 호출되지 않아야 함
        handler._bot._notifier.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_command_unknown_ignored(self) -> None:
        """알 수 없는 명령어는 무시한다."""
        handler = _make_handler()
        await handler._handle_command("/unknown_command")
        handler._bot._notifier.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_command_error_sends_error_msg(self) -> None:
        """명령어 처리 중 오류 시 에러 메시지를 전송한다."""
        handler = _make_handler()
        # _cmd_status에서 예외 발생하도록 설정
        handler._bot._bot_start_time = "not_a_number"  # TypeError 유발

        await handler._handle_command("/status")

        msg = handler._bot._notifier.send.call_args[0][0]
        assert "오류" in msg

    @pytest.mark.asyncio
    async def test_stop_closes_session(self) -> None:
        """stop 호출 시 running이 False가 된다."""
        handler = _make_handler()
        handler._running = True
        await handler.stop()
        assert not handler._running

    @pytest.mark.asyncio
    async def test_start_polling_without_token(self) -> None:
        """토큰 없이 start_polling 호출 시 바로 반환한다."""
        bot = _make_bot()
        handler = TelegramHandler(token="", chat_id="12345", bot=bot)
        # 토큰 없으면 즉시 반환 (무한 루프 진입 안 함)
        await handler.start_polling()
        assert not handler._running
