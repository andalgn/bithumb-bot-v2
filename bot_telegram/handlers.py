"""텔레그램 명령어 핸들러.

aiohttp 기반 long polling. TradingBot 인스턴스 참조로 상태 조회/제어.
"""

from __future__ import annotations

import asyncio
import logging
import ssl
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import aiohttp

if TYPE_CHECKING:
    from app.main import TradingBot

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))


class TelegramHandler:
    """텔레그램 명령어 처리기."""

    COMMANDS: dict[str, str] = {
        "/status": "봇 상태",
        "/positions": "보유 포지션",
        "/balance": "Pool 잔액",
        "/regime": "국면 분류",
        "/pnl": "PnL 요약",
        "/pause": "봇 일시 중지",
        "/resume": "봇 재개 (pause 해제)",
        "/golive": "LIVE 모드 전환 (risk 50% 축소 7일)",
        "/close": "수동 청산 (/close BTC)",
        "/restore_params": "LIVE risk_pct 정상화",
        "/help": "명령어 목록",
    }

    def __init__(
        self,
        token: str,
        chat_id: str,
        bot: TradingBot,
        *,
        verify_ssl: bool = True,
    ) -> None:
        """초기화.

        Args:
            token: 텔레그램 봇 토큰.
            chat_id: 허가된 채팅 ID.
            bot: TradingBot 인스턴스 참조.
            verify_ssl: SSL 인증서 검증 여부. 프록시 환경에서는 False.
        """
        self._token = token
        self._chat_id = chat_id
        self._bot = bot
        self._running = False
        self._offset = 0
        self._base_url = f"https://api.telegram.org/bot{token}"
        self._ssl_ctx = ssl.create_default_context()
        if not verify_ssl:
            self._ssl_ctx.check_hostname = False
            self._ssl_ctx.verify_mode = ssl.CERT_NONE
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """세션을 재사용하거나 새로 생성한다."""
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(ssl=self._ssl_ctx)
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=35),
                connector=connector,
            )
        return self._session

    async def start_polling(self) -> None:
        """Long polling을 시작한다."""
        if not self._token or not self._chat_id:
            logger.warning("텔레그램 핸들러: 토큰/chat_id 미설정")
            return

        self._running = True
        logger.info("텔레그램 명령어 핸들러 시작")

        while self._running:
            try:
                await self._poll_updates()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("텔레그램 polling 오류")
                await asyncio.sleep(5)

    async def stop(self) -> None:
        """핸들러를 중지한다."""
        self._running = False
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
        logger.info("텔레그램 명령어 핸들러 종료")

    async def _poll_updates(self) -> None:
        """getUpdates로 새 메시지를 가져온다."""
        session = await self._get_session()
        url = f"{self._base_url}/getUpdates"
        params = {"offset": self._offset, "timeout": 30}

        async with session.get(url, params=params) as resp:
            if resp.status != 200:
                await asyncio.sleep(1)
                return
            data = await resp.json()

        if not data.get("ok"):
            return

        for update in data.get("result", []):
            self._offset = update["update_id"] + 1
            msg = update.get("message", {})
            text = msg.get("text", "")
            chat_id = str(msg.get("chat", {}).get("id", ""))

            # 허가된 채팅만 응답
            if chat_id != self._chat_id:
                continue

            await self._handle_command(text)

    async def _handle_command(self, text: str) -> None:
        """명령어를 파싱하고 핸들러를 호출한다."""
        text = text.strip()
        parts = text.split()
        cmd = parts[0].lower() if parts else ""
        args = parts[1:] if len(parts) > 1 else []

        handlers: dict[str, object] = {
            "/status": self._cmd_status,
            "/positions": self._cmd_positions,
            "/balance": self._cmd_balance,
            "/regime": self._cmd_regime,
            "/pnl": self._cmd_pnl,
            "/pause": self._cmd_pause,
            "/resume": self._cmd_resume,
            "/golive": self._cmd_golive,
            "/close": lambda: self._cmd_close(args),
            "/restore_params": self._cmd_restore_params,
            "/help": self._cmd_help,
        }

        handler = handlers.get(cmd)
        if handler is None:
            return

        try:
            await handler()  # type: ignore[misc]
        except Exception:
            logger.exception("명령어 처리 오류: %s", cmd)
            await self._reply("명령 처리 중 오류가 발생했습니다.")

    async def _reply(self, text: str) -> None:
        """텔레그램으로 응답을 보낸다."""
        await self._bot._notifier.send(text)

    # ─── 명령어 구현 ─────────────────────────────────────

    async def _cmd_status(self) -> None:
        """봇 상태를 응답한다."""
        bot = self._bot
        uptime_sec = int(time.time() - bot._bot_start_time)
        hours, remainder = divmod(uptime_sec, 3600)
        minutes, secs = divmod(remainder, 60)

        util_pct = bot._pool_manager.utilization_pct * 100
        paused_str = " (일시 중지)" if bot._paused else ""

        msg = (
            f"<b>봇 상태{paused_str}</b>\n"
            f"모드: {bot._run_mode.value}\n"
            f"사이클: #{bot._cycle_count}\n"
            f"가동: {hours}시간 {minutes}분 {secs}초\n"
            f"포지션: {len(bot._positions)}개\n"
            f"자금 활용률: {util_pct:.1f}%"
        )
        await self._reply(msg)

    async def _cmd_positions(self) -> None:
        """보유 포지션을 응답한다."""
        positions = self._bot._positions
        if not positions:
            await self._reply("보유 포지션 없음")
            return

        lines = ["<b>보유 포지션</b>"]
        for sym, pos in positions.items():
            # 간단히 entry_price 기준으로만 표시 (실시간 가격은 스냅샷 없음)
            lines.append(
                f"\n<b>{sym}</b>\n"
                f"  전략: {pos.strategy.value} | Pool: {pos.pool.value}\n"
                f"  진입: {pos.entry_price:,.0f}원\n"
                f"  수량: {pos.qty:.6f} | {pos.size_krw:,.0f}원\n"
                f"  SL: {pos.stop_loss:,.0f} | TP: {pos.take_profit:,.0f}\n"
                f"  점수: {pos.entry_score:.0f} | 국면: {pos.regime.value}"
            )

        await self._reply("\n".join(lines))

    async def _cmd_balance(self) -> None:
        """Pool별 잔액을 응답한다."""
        from app.data_types import Pool

        pm = self._bot._pool_manager
        lines = ["<b>Pool 잔액</b>"]

        for pool in [Pool.CORE, Pool.ACTIVE, Pool.RESERVE]:
            state = pm._pools[pool]
            lines.append(
                f"\n<b>{pool.value.upper()}</b>\n"
                f"  잔액: {state.total_balance:,.0f}원\n"
                f"  할당: {state.allocated:,.0f}원\n"
                f"  가용: {state.available:,.0f}원\n"
                f"  포지션: {state.position_count}개"
            )

        total = sum(s.total_balance for s in pm._pools.values())
        util = pm.utilization_pct * 100
        lines.append(f"\n총 자산: {total:,.0f}원 | 활용률: {util:.1f}%")
        await self._reply("\n".join(lines))

    async def _cmd_regime(self) -> None:
        """코인별 국면 분류를 응답한다."""
        regime_states = self._bot._rule_engine._regime_states
        if not regime_states:
            await self._reply("국면 데이터 없음 (첫 사이클 대기 중)")
            return

        lines = ["<b>국면 분류</b>"]
        for sym, rs in sorted(regime_states.items()):
            pending = f" -> {rs.pending.value}" if rs.pending else ""
            lines.append(f"  {sym}: {rs.current.value}{pending}")

        await self._reply("\n".join(lines))

    async def _cmd_pnl(self) -> None:
        """오늘/이번 주 PnL을 응답한다."""
        journal = self._bot._journal
        now = datetime.now(KST)

        # 오늘 00:00 KST
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_start_ms = int(today_start.timestamp() * 1000)

        # 이번 주 월요일 00:00 KST
        week_start = today_start - timedelta(days=now.weekday())
        week_start_ms = int(week_start.timestamp() * 1000)

        # TODO: m1 — journal._conn 직접 접근을 Journal public 메서드로 리팩토링
        # 오늘 PnL
        today_rows = journal._conn.execute(
            "SELECT net_pnl_krw FROM trades WHERE exit_time >= ?",
            (today_start_ms,),
        ).fetchall()
        today_pnl = sum(r[0] for r in today_rows if r[0] is not None)
        today_count = len(today_rows)
        today_wins = sum(1 for r in today_rows if r[0] is not None and r[0] > 0)

        # 이번 주 PnL
        week_rows = journal._conn.execute(
            "SELECT net_pnl_krw FROM trades WHERE exit_time >= ?",
            (week_start_ms,),
        ).fetchall()
        week_pnl = sum(r[0] for r in week_rows if r[0] is not None)
        week_count = len(week_rows)
        week_wins = sum(1 for r in week_rows if r[0] is not None and r[0] > 0)

        today_wr = (today_wins / today_count * 100) if today_count > 0 else 0
        week_wr = (week_wins / week_count * 100) if week_count > 0 else 0

        msg = (
            f"<b>PnL 요약</b>\n\n"
            f"<b>오늘</b>\n"
            f"  PnL: {today_pnl:+,.0f}원\n"
            f"  거래: {today_count}건 (승률 {today_wr:.0f}%)\n\n"
            f"<b>이번 주</b>\n"
            f"  PnL: {week_pnl:+,.0f}원\n"
            f"  거래: {week_count}건 (승률 {week_wr:.0f}%)"
        )
        await self._reply(msg)

    async def _cmd_pause(self) -> None:
        """봇을 일시 중지한다 (신규 진입만 차단)."""
        self._bot._paused = True
        await self._reply("봇 일시 중지됨 (신규 진입 차단, 기존 포지션 관리 계속)")

    async def _cmd_resume(self) -> None:
        """봇을 재개한다 (pause 해제만, LIVE 전환은 /golive)."""
        self._bot._paused = False
        await self._reply("<b>봇 재개</b>\n신규 진입 허용됨")

    async def _cmd_golive(self) -> None:
        """LIVE 모드로 전환한다 (LiveGate 검증 필수)."""
        from app.data_types import RunMode
        from app.live_gate import LiveGate

        # LiveGate 검증
        gate = LiveGate()
        try:
            paper_days = (
                int((time.time() - self._bot._paper_start_time) / 86400)
                if self._bot._paper_start_time > 0
                else 0
            )
            bd = self._bot._backtest_daemon
            gate_result = gate.evaluate(
                paper_days=paper_days,
                total_trades=self._bot._journal.get_trade_count(),
                strategy_expectancy={},
                mdd_pct=self._bot._dd_limits._calc_dd(
                    self._bot._dd_limits.state.total_base,
                ),
                max_daily_dd_pct=self._bot._dd_limits.get_max_daily_dd(),
                uptime_pct=0.99,
                unresolved_auth_errors=0,
                slippage_model_error_pct=0.0,
                wf_pass_count=(bd.wf_result.pass_count if bd.wf_result else 0),
                wf_total=4,
                mc_p5_pnl=(bd.mc_result.pnl_percentile_5 if bd.mc_result else 0),
            )
        except Exception:
            await self._reply("LiveGate 검증 중 오류 발생. LIVE 전환 취소.")
            return

        if not gate_result.approved:
            report = gate.format_report(gate_result)
            await self._reply(f"{report}\n\nLIVE 전환 거부됨.")
            return

        self._bot._config.run_mode = "LIVE"
        self._bot._run_mode = RunMode.LIVE
        self._bot._paused = False
        self._bot._live_risk_reduction = True
        self._bot._live_start_time = time.time()
        await self._reply(
            "<b>LIVE 모드 전환 승인</b>\n"
            "risk_pct 50% 축소 적용 (7일)\n"
            "/restore_params로 수동 해제 가능"
        )

    async def _cmd_restore_params(self) -> None:
        """LIVE risk_pct 축소를 수동 해제한다."""
        self._bot._live_risk_reduction = False
        await self._reply("<b>파라미터 복원 완료</b>\nrisk_pct 정상화")

    async def _cmd_close(self, args: list[str]) -> None:
        """특정 코인을 수동 청산한다."""
        if not args:
            await self._reply("사용법: /close BTC (심볼 지정 필요)")
            return

        symbol = args[0].upper()

        # 포지션에서 심볼 찾기 (BTC → BTC_KRW 등 매핑)
        matched_sym = None
        for sym in self._bot._positions:
            if sym == symbol or sym.startswith(f"{symbol}_") or sym == f"{symbol}_KRW":
                matched_sym = sym
                break

        if matched_sym is None:
            held = ", ".join(self._bot._positions.keys()) or "없음"
            await self._reply(f"{symbol} 포지션 없음\n보유: {held}")
            return

        pos = self._bot._positions[matched_sym]
        # 현재가 조회 (ticker API — 심볼에서 _KRW 접미사 제거)
        try:
            ticker_sym = matched_sym.replace("_KRW", "")
            ticker = await self._bot._client.get_ticker(ticker_sym)
            exit_price = float(ticker.get("closing_price", 0))
        except Exception:
            exit_price = 0
        if exit_price <= 0:
            exit_price = pos.entry_price  # fallback

        await self._bot._close_position(matched_sym, exit_price, "manual")
        await self._reply(f"{matched_sym} 수동 청산 요청 완료")

    async def _cmd_help(self) -> None:
        """명령어 목록을 응답한다."""
        lines = ["<b>명령어 목록</b>"]
        for cmd, desc in self.COMMANDS.items():
            lines.append(f"  {cmd} — {desc}")
        await self._reply("\n".join(lines))
