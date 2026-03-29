"""디스코드 슬래시 커맨드 처리기.

discord.py 기반. TradingBot 인스턴스 참조로 상태 조회/제어.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import discord
from discord import app_commands

if TYPE_CHECKING:
    from app.main import TradingBot

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))


def _has_admin_role(admin_role: str):
    """admin 역할 체크 데코레이터를 반환한다."""

    async def predicate(interaction: discord.Interaction) -> bool:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "서버에서만 사용 가능합니다.",
                ephemeral=True,
            )
            return False
        if not any(r.name == admin_role for r in interaction.user.roles):
            await interaction.response.send_message(
                f"`{admin_role}` 역할이 필요합니다.",
                ephemeral=True,
            )
            return False
        return True

    return app_commands.check(predicate)


class DiscordBot:
    """디스코드 슬래시 커맨드 처리기."""

    def __init__(
        self,
        token: str,
        bot: TradingBot,
        guild_id: int,
        proxy: str = "",
        admin_role: str = "admin",
    ) -> None:
        """초기화.

        Args:
            token: 디스코드 봇 토큰.
            bot: TradingBot 인스턴스 참조.
            guild_id: 슬래시 커맨드를 등록할 서버 ID.
            proxy: HTTP 프록시 URL.
            admin_role: 관리자 역할 이름.
        """
        self._token = token
        self._bot = bot
        self._guild_id = guild_id
        self._proxy = proxy
        self._admin_role = admin_role

        intents = discord.Intents.default()
        self._client = discord.Client(intents=intents, proxy=proxy or None)
        self._tree = app_commands.CommandTree(self._client)
        self._guild = discord.Object(id=guild_id)

        self._register_commands()

    def _register_commands(self) -> None:
        """슬래시 커맨드를 등록한다."""
        guild = self._guild
        admin_check = _has_admin_role(self._admin_role)

        @self._tree.command(name="status", description="봇 상태", guild=guild)
        async def cmd_status(interaction: discord.Interaction) -> None:
            bot = self._bot
            uptime_sec = int(time.time() - bot._bot_start_time)
            hours, remainder = divmod(uptime_sec, 3600)
            minutes, secs = divmod(remainder, 60)
            util_pct = bot._pool_manager.utilization_pct * 100
            paused_str = " (일시 중지)" if bot._paused else ""

            await interaction.response.send_message(
                f"**봇 상태{paused_str}**\n"
                f"모드: {bot._run_mode.value}\n"
                f"사이클: #{bot._cycle_count}\n"
                f"가동: {hours}시간 {minutes}분 {secs}초\n"
                f"포지션: {len(bot._positions)}개\n"
                f"자금 활용률: {util_pct:.1f}%"
            )

        @self._tree.command(name="positions", description="보유 포지션", guild=guild)
        async def cmd_positions(interaction: discord.Interaction) -> None:
            positions = self._bot._positions
            if not positions:
                await interaction.response.send_message("보유 포지션 없음")
                return

            lines = ["**보유 포지션**"]
            for sym, pos in positions.items():
                lines.append(
                    f"\n**{sym}**\n"
                    f"  전략: {pos.strategy.value} | Pool: {pos.pool.value}\n"
                    f"  진입: {pos.entry_price:,.0f}원\n"
                    f"  수량: {pos.qty:.6f} | {pos.size_krw:,.0f}원\n"
                    f"  SL: {pos.stop_loss:,.0f} | TP: {pos.take_profit:,.0f}\n"
                    f"  점수: {pos.entry_score:.0f} | 국면: {pos.regime.value}"
                )
            await interaction.response.send_message("\n".join(lines))

        @self._tree.command(name="balance", description="Pool 잔액", guild=guild)
        async def cmd_balance(interaction: discord.Interaction) -> None:
            from app.data_types import Pool

            pm = self._bot._pool_manager
            lines = ["**Pool 잔액**"]
            for pool in [Pool.CORE, Pool.ACTIVE, Pool.RESERVE]:
                state = pm._pools[pool]
                lines.append(
                    f"\n**{pool.value.upper()}**\n"
                    f"  잔액: {state.total_balance:,.0f}원\n"
                    f"  할당: {state.allocated:,.0f}원\n"
                    f"  가용: {state.available:,.0f}원\n"
                    f"  포지션: {state.position_count}개"
                )
            total = sum(s.total_balance for s in pm._pools.values())
            util = pm.utilization_pct * 100
            lines.append(f"\n총 자산: {total:,.0f}원 | 활용률: {util:.1f}%")
            await interaction.response.send_message("\n".join(lines))

        @self._tree.command(name="regime", description="국면 분류", guild=guild)
        async def cmd_regime(interaction: discord.Interaction) -> None:
            regime_states = self._bot._rule_engine._regime_states
            if not regime_states:
                await interaction.response.send_message("국면 데이터 없음 (첫 사이클 대기 중)")
                return
            lines = ["**국면 분류**"]
            for sym, rs in sorted(regime_states.items()):
                pending = f" -> {rs.pending.value}" if rs.pending else ""
                lines.append(f"  {sym}: {rs.current.value}{pending}")
            await interaction.response.send_message("\n".join(lines))

        @self._tree.command(name="pnl", description="PnL 요약", guild=guild)
        async def cmd_pnl(interaction: discord.Interaction) -> None:
            journal = self._bot._journal
            now = datetime.now(KST)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            today_start_ms = int(today_start.timestamp() * 1000)
            week_start = today_start - timedelta(days=now.weekday())
            week_start_ms = int(week_start.timestamp() * 1000)

            today_rows = journal._conn.execute(
                "SELECT net_pnl_krw FROM trades WHERE exit_time >= ?",
                (today_start_ms,),
            ).fetchall()
            today_pnl = sum(r[0] for r in today_rows if r[0] is not None)
            today_count = len(today_rows)
            today_wins = sum(1 for r in today_rows if r[0] is not None and r[0] > 0)

            week_rows = journal._conn.execute(
                "SELECT net_pnl_krw FROM trades WHERE exit_time >= ?",
                (week_start_ms,),
            ).fetchall()
            week_pnl = sum(r[0] for r in week_rows if r[0] is not None)
            week_count = len(week_rows)
            week_wins = sum(1 for r in week_rows if r[0] is not None and r[0] > 0)

            today_wr = (today_wins / today_count * 100) if today_count > 0 else 0
            week_wr = (week_wins / week_count * 100) if week_count > 0 else 0

            await interaction.response.send_message(
                f"**PnL 요약**\n\n"
                f"**오늘**\n"
                f"  PnL: {today_pnl:+,.0f}원\n"
                f"  거래: {today_count}건 (승률 {today_wr:.0f}%)\n\n"
                f"**이번 주**\n"
                f"  PnL: {week_pnl:+,.0f}원\n"
                f"  거래: {week_count}건 (승률 {week_wr:.0f}%)"
            )

        @self._tree.command(name="risk", description="RiskGate 상태", guild=guild)
        async def cmd_risk(interaction: discord.Interaction) -> None:
            rg = self._bot._risk_gate
            dd = self._bot._dd_limits
            state = rg._state
            lines = [
                "**RiskGate 상태**",
                f"  상태: {state.status.value}",
                f"  일일 DD: {dd.get_max_daily_dd() * 100:.2f}%",
                f"  연속 손실: {state.consecutive_losses}",
            ]
            await interaction.response.send_message("\n".join(lines))

        @self._tree.command(name="shadows", description="Darwinian 상위 그림자", guild=guild)
        async def cmd_shadows(interaction: discord.Interaction) -> None:
            top = self._bot._darwin.get_top_shadows(5)
            if not top:
                await interaction.response.send_message("Shadow 데이터 없음")
                return
            lines = ["**Darwinian Top 5**"]
            for i, s in enumerate(top, 1):
                lines.append(
                    f"  {i}. score={s.get('composite_score', 0):.3f} "
                    f"PF={s.get('profit_factor', 0):.2f}"
                )
            await interaction.response.send_message("\n".join(lines))

        @self._tree.command(name="pool", description="3풀 자금 현황", guild=guild)
        async def cmd_pool(interaction: discord.Interaction) -> None:
            pm = self._bot._pool_manager
            lines = ["**풀 현황**"]
            for pool_type, state in pm._pools.items():
                lines.append(
                    f"  {pool_type.value}: {state.total_balance:,.0f}원 "
                    f"(가용 {state.available:,.0f}원)"
                )
            await interaction.response.send_message("\n".join(lines))

        # --- Admin 커맨드 ---

        @self._tree.command(name="pause", description="봇 일시 중지", guild=guild)
        @admin_check
        async def cmd_pause(interaction: discord.Interaction) -> None:
            self._bot._paused = True
            await interaction.response.send_message(
                "봇 일시 중지됨 (신규 진입 차단, 기존 포지션 관리 계속)"
            )

        @self._tree.command(name="resume", description="봇 재개", guild=guild)
        @admin_check
        async def cmd_resume(interaction: discord.Interaction) -> None:
            self._bot._paused = False
            await interaction.response.send_message("**봇 재개**\n신규 진입 허용됨")

        @self._tree.command(name="golive", description="LIVE 모드 전환", guild=guild)
        @admin_check
        async def cmd_golive(interaction: discord.Interaction) -> None:
            from app.data_types import RunMode
            from app.live_gate import LiveGate

            await interaction.response.defer()

            gate = LiveGate()
            try:
                paper_days = (
                    int((time.time() - self._bot._paper_start_time) / 86400)
                    if self._bot._paper_start_time > 0
                    else 0
                )
                trades = self._bot._journal.get_recent_trades(limit=500)
                strat_pnls: dict[str, list[float]] = defaultdict(list)
                for t in trades:
                    s = t.get("strategy", "")
                    pnl = t.get("net_pnl_krw", 0) or 0
                    if s:
                        strat_pnls[s].append(pnl)
                strat_exp: dict[str, float] = {}
                for s, pnls in strat_pnls.items():
                    strat_exp[s] = sum(pnls) / len(pnls) if pnls else 0

                total_seconds = time.time() - self._bot._paper_start_time
                expected_cycles = (
                    total_seconds / self._bot._cycle_interval
                    if self._bot._paper_start_time > 0
                    else 0
                )
                actual_cycles = self._bot._cycle_count
                uptime_pct = (
                    min(actual_cycles / expected_cycles, 1.0) if expected_cycles > 0 else 0.99
                )

                bd = self._bot._backtest_daemon
                gate_result = gate.evaluate(
                    paper_days=paper_days,
                    total_trades=self._bot._journal.get_trade_count(),
                    strategy_expectancy=strat_exp,
                    mdd_pct=self._bot._dd_limits._calc_dd(
                        self._bot._dd_limits.state.total_base,
                    ),
                    max_daily_dd_pct=self._bot._dd_limits.get_max_daily_dd(),
                    uptime_pct=uptime_pct,
                    unresolved_auth_errors=0,
                    slippage_model_error_pct=0.0,
                    wf_pass_count=(bd.wf_result.pass_count if bd.wf_result else 0),
                    wf_total=4,
                    mc_p5_pnl=(bd.mc_result.pnl_percentile_5 if bd.mc_result else 0),
                )
            except Exception:  # noqa: BLE001 — Discord 커맨드 핸들러, 봇 유지를 위한 의도적 광역 포착
                await interaction.followup.send("LiveGate 검증 중 오류 발생. LIVE 전환 취소.")
                return

            if not gate_result.approved:
                report = gate.format_report(gate_result)
                await interaction.followup.send(f"{report}\n\nLIVE 전환 거부됨.")
                return

            self._bot._config.run_mode = "LIVE"
            self._bot._run_mode = RunMode.LIVE
            self._bot._paused = False
            self._bot._live_risk_reduction = True
            self._bot._live_start_time = time.time()
            await interaction.followup.send(
                "**LIVE 모드 전환 승인**\n"
                "risk_pct 50% 축소 적용 (7일)\n"
                "/restore_params로 수동 해제 가능"
            )

        @self._tree.command(
            name="close",
            description="수동 청산 (/close symbol)",
            guild=guild,
        )
        @admin_check
        @app_commands.describe(symbol="청산할 코인 심볼 (예: BTC)")
        async def cmd_close(
            interaction: discord.Interaction,
            symbol: str,
        ) -> None:
            await interaction.response.defer()
            symbol = symbol.upper()

            matched_sym = None
            for sym in self._bot._positions:
                if sym == symbol or sym.startswith(f"{symbol}_") or sym == f"{symbol}_KRW":
                    matched_sym = sym
                    break

            if matched_sym is None:
                held = ", ".join(self._bot._positions.keys()) or "없음"
                await interaction.followup.send(f"{symbol} 포지션 없음\n보유: {held}")
                return

            pos = self._bot._positions[matched_sym]
            try:
                ticker_sym = matched_sym.replace("_KRW", "")
                ticker = await self._bot._client.get_ticker(ticker_sym)
                exit_price = float(ticker.get("closing_price", 0))
            except Exception:  # noqa: BLE001 — Discord 커맨드 핸들러, 봇 유지를 위한 의도적 광역 포착
                exit_price = 0
            if exit_price <= 0:
                exit_price = pos.entry_price

            await self._bot._close_position(matched_sym, exit_price, "manual")
            await interaction.followup.send(f"{matched_sym} 수동 청산 요청 완료")

        @self._tree.command(
            name="restore_params",
            description="LIVE risk_pct 정상화",
            guild=guild,
        )
        @admin_check
        async def cmd_restore_params(
            interaction: discord.Interaction,
        ) -> None:
            self._bot._live_risk_reduction = False
            await interaction.response.send_message("**파라미터 복원 완료**\nrisk_pct 정상화")

        @self._tree.command(name="help", description="명령어 목록", guild=guild)
        async def cmd_help(interaction: discord.Interaction) -> None:
            commands = {
                "/status": "봇 상태",
                "/positions": "보유 포지션",
                "/balance": "Pool 잔액",
                "/regime": "국면 분류",
                "/pnl": "PnL 요약",
                "/risk": "RiskGate 상태",
                "/shadows": "Darwinian 상위 그림자",
                "/pool": "3풀 자금 현황",
                "/pause": "봇 일시 중지 (admin)",
                "/resume": "봇 재개 (admin)",
                "/golive": "LIVE 모드 전환 (admin)",
                "/close": "수동 청산 (admin)",
                "/restore_params": "risk_pct 정상화 (admin)",
                "/help": "명령어 목록",
            }
            lines = ["**명령어 목록**"]
            for cmd, desc in commands.items():
                lines.append(f"  {cmd} -- {desc}")
            await interaction.response.send_message("\n".join(lines))

        # ── 자율 진화 명령어 ──────────────────────────────

        @self._tree.command(
            name="approve", description="진화 변경 승인", guild=guild
        )
        @admin_check
        async def cmd_approve(
            interaction: discord.Interaction, change_id: str
        ) -> None:
            workflow = self._bot._approval_workflow
            change = workflow.get(change_id)
            if not change:
                await interaction.response.send_message(
                    f"변경 `{change_id}` 없음", ephemeral=True
                )
                return
            if change.status != "pending":
                await interaction.response.send_message(
                    f"상태: {change.status} (pending만 승인 가능)", ephemeral=True
                )
                return

            ok = workflow.approve(change_id)
            if ok:
                await interaction.response.send_message(
                    f"변경 `{change_id}` 승인 완료. "
                    f"config.yaml 업데이트됨 (다음 사이클부터 반영)."
                )
            else:
                await interaction.response.send_message(
                    f"승인 실패: `{change_id}`", ephemeral=True
                )

        @self._tree.command(
            name="reject", description="진화 변경 거부", guild=guild
        )
        @admin_check
        async def cmd_reject(
            interaction: discord.Interaction, change_id: str
        ) -> None:
            workflow = self._bot._approval_workflow
            ok = workflow.reject(change_id)
            if ok:
                await interaction.response.send_message(
                    f"변경 `{change_id}` 거부됨."
                )
            else:
                await interaction.response.send_message(
                    f"거부 실패: `{change_id}` (없거나 pending 아님)",
                    ephemeral=True,
                )

        @self._tree.command(
            name="pending", description="대기 중인 진화 변경 목록", guild=guild
        )
        @admin_check
        async def cmd_pending(interaction: discord.Interaction) -> None:
            workflow = self._bot._approval_workflow
            changes = workflow.list_pending()
            if not changes:
                await interaction.response.send_message("대기 중인 변경 없음")
                return

            lines = ["**대기 중인 변경**"]
            for c in changes:
                param_str = (
                    ", ".join(f"{k}: {v[0]}→{v[1]}" for k, v in c.changes.items())
                    if c.changes
                    else "(변경 없음)"
                )
                lines.append(
                    f"\n`{c.change_id}` ({c.risk_level}, {c.risk_score:.2f})\n"
                    f"  {param_str}\n"
                    f"  fitness: +{c.fitness_improvement:.3f}"
                )
            await interaction.response.send_message("\n".join(lines))

        @self._client.event
        async def on_ready() -> None:
            self._tree.copy_global_to(guild=self._guild)
            await self._tree.sync(guild=self._guild)
            logger.info(
                "디스코드 봇 준비 완료: %s (guild=%d)",
                self._client.user,
                self._guild_id,
            )

    async def start(self) -> None:
        """Bot을 시작한다."""
        if not self._token:
            logger.warning("디스코드 봇 토큰 미설정")
            return
        await self._client.start(self._token)

    async def stop(self) -> None:
        """Bot을 종료한다."""
        if not self._client.is_closed():
            await self._client.close()
