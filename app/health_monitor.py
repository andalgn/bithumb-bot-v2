"""HealthMonitor — 봇 건강 감시 시스템.

15분마다 8개 항목을 점검하고, 건강 점수(0-100)를 산출하며,
이상 발생 시 디스코드로 알림을 전송한다.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from app.llm_client import call_claude

if TYPE_CHECKING:
    from app.config import AppConfig
    from app.journal import Journal
    from app.notify import DiscordNotifier
    from market.bithumb_api import BithumbClient

logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))


@dataclass
class CheckResult:
    """단일 점검 결과."""

    name: str
    status: Literal["ok", "warn", "critical"]
    message: str
    value: float | None = None
    checked_at: float = field(default_factory=time.time)


@dataclass
class Alert:
    """알림 항목."""

    level: Literal["info", "warning", "critical"]
    category: str
    message: str
    created_at: float = field(default_factory=time.time)


# 건강 점수 가중치
SCORE_WEIGHTS: dict[str, int] = {
    "heartbeat": 20,
    "event_loop": 10,
    "api": 20,
    "data_freshness": 15,
    "reconciliation": 10,
    "system_resources": 5,
    "trading_metrics": 10,
    "discord": 5,
    "pipeline": 5,
    "utilization": 5,
    "balance_check": 5,
}

# 상관 억제: 이 카테고리가 critical이면 하위 카테고리 경보 억제
CORRELATION_SUPPRESS: dict[str, list[str]] = {
    "api": ["data_freshness", "trading_metrics", "reconciliation"],
}


class AlertManager:
    """알림 쿨다운, 배치, 상관 억제를 관리한다."""

    def __init__(
        self,
        cooldown_critical_sec: int = 1800,
        cooldown_warning_sec: int = 7200,
    ) -> None:
        """초기화."""
        self._cooldown_critical = cooldown_critical_sec
        self._cooldown_warning = cooldown_warning_sec
        self._last_sent: dict[str, float] = {}
        self._pending: list[Alert] = []
        self._daily_buffer: list[Alert] = []
        self._suppressed: set[str] = set()

    def set_suppressed(self, categories: set[str]) -> None:
        """상관 억제 대상 카테고리를 설정한다."""
        self._suppressed = categories

    def add(self, alert: Alert) -> bool:
        """알림을 추가한다. 쿨다운/억제 시 False 반환."""
        if alert.category in self._suppressed:
            return False

        key = f"{alert.category}:{alert.level}"
        cooldown = self._cooldown_critical if alert.level == "critical" else self._cooldown_warning
        last = self._last_sent.get(key, 0)
        if time.time() - last < cooldown:
            return False

        self._last_sent[key] = time.time()

        if alert.level == "info":
            self._daily_buffer.append(alert)
            return True

        self._pending.append(alert)
        return True

    async def flush(self, notifier: DiscordNotifier | None) -> list[Alert]:
        """대기 중인 알림을 전송하고 반환한다."""
        if not self._pending:
            return []

        to_send = list(self._pending)
        self._pending.clear()

        criticals = [a for a in to_send if a.level == "critical"]
        warnings = [a for a in to_send if a.level == "warning"]

        for alert in criticals:
            if notifier:
                await notifier.send(f"**CRITICAL** {alert.message}", channel="system")

        if warnings:
            lines = [f"- {a.message}" for a in warnings]
            if notifier:
                await notifier.send(
                    f"**WARNING** ({len(warnings)}건)\n" + "\n".join(lines),
                    channel="system",
                )

        return to_send

    def get_daily_buffer(self) -> list[Alert]:
        """일일 요약용 INFO 알림을 반환하고 비운다."""
        buf = list(self._daily_buffer)
        self._daily_buffer.clear()
        return buf


def compute_health_score(results: list[CheckResult]) -> tuple[int, str]:
    """건강 점수(0-100)와 verdict를 계산한다."""
    score = 0
    for r in results:
        weight = SCORE_WEIGHTS.get(r.name, 0)
        if r.status == "ok":
            score += weight
        elif r.status == "warn":
            score += weight // 2
    verdict = "healthy" if score >= 80 else "degraded" if score >= 50 else "critical"
    return score, verdict


class HealthMonitor:
    """15분마다 건강 점검을 실행한다."""

    def __init__(
        self,
        interval_sec: int = 900,
        notifier: DiscordNotifier | None = None,
        journal: Journal | None = None,
        config: AppConfig | None = None,
    ) -> None:
        """초기화."""
        self._interval = interval_sec
        self._notifier = notifier
        self._journal = journal
        self._config = config
        self._alert_manager = AlertManager(
            cooldown_critical_sec=getattr(config, "alert_cooldown_critical_min", 30) * 60,
            cooldown_warning_sec=getattr(config, "alert_cooldown_warning_min", 120) * 60,
        )
        self._running = False
        self._start_time: float = time.time()
        self._last_heartbeat: float = time.time()
        self._api_consecutive_fails: int = 0
        self._last_reconciliation: float = 0.0
        self._low_util_since: float = 0.0
        self._last_balance_check: float = 0.0

        # 외부에서 주입하는 상태 참조
        self._get_last_candle_ts: Callable[[], float] | None = None
        self._get_positions: Callable[[], dict] | None = None
        self._get_exchange_balances: Callable[[], Coroutine[None, None, dict]] | None = None
        self._get_bithumb_client: Callable[[], BithumbClient] | None = None
        self._get_equity: Callable[[], float] | None = None

    def record_heartbeat(self) -> None:
        """메인 루프에서 매 사이클 호출한다."""
        self._last_heartbeat = time.time()

    async def run_forever(self) -> None:
        """백그라운드 감시 루프."""
        self._running = True
        logger.info("HealthMonitor 시작 (주기: %ds)", self._interval)
        while self._running:
            try:
                results = await self._run_all_checks()
                score, verdict = compute_health_score(results)

                # 상관 억제 계산
                critical_cats = {r.name for r in results if r.status == "critical"}
                suppressed: set[str] = set()
                for cat in critical_cats:
                    suppressed.update(CORRELATION_SUPPRESS.get(cat, []))
                self._alert_manager.set_suppressed(suppressed)

                # 알림 생성
                for r in results:
                    if r.status == "critical":
                        alert = Alert(level="critical", category=r.name, message=r.message)
                        self._alert_manager.add(alert)
                    elif r.status == "warn":
                        alert = Alert(level="warning", category=r.name, message=r.message)
                        self._alert_manager.add(alert)

                alerts_sent = await self._alert_manager.flush(self._notifier)
                # WARNING/CRITICAL 알림에 대해 자동 진단 트리거
                for alert in alerts_sent:
                    if alert.level in ("warning", "critical"):
                        await self.trigger_diagnosis(
                            alert.category,
                            alert.message,
                            {"level": alert.level, "source": "health_monitor"},
                        )
                alerts_data = [{"level": a.level, "category": a.category, "message": a.message} for a in alerts_sent]

                # 저장
                results_data = [
                    {"name": r.name, "status": r.status, "message": r.message, "value": r.value}
                    for r in results
                ]
                if self._journal and hasattr(self._journal, "record_health_check"):
                    self._journal.record_health_check(score, verdict, results_data, alerts_data)

                logger.info("HealthMonitor: score=%d (%s)", score, verdict)
            except Exception:
                logger.exception("HealthMonitor 점검 실패")

            await asyncio.sleep(self._interval)

    async def stop(self) -> None:
        """감시를 중지한다."""
        self._running = False

    async def _run_all_checks(self) -> list[CheckResult]:
        """11개 점검을 실행한다."""
        return [
            self._check_heartbeat(),
            await self._check_event_loop_lag(),
            await self._check_api(),
            self._check_data_freshness(),
            await self._check_reconciliation(),
            self._check_system_resources(),
            self._check_trading_metrics(),
            await self._check_discord(),
            self._check_pipeline_health(),
            self._check_utilization(),
            await self._check_balance_integrity(),
        ]

    # ─── Check 1: 메인 루프 심장박동 ───

    def _check_heartbeat(self) -> CheckResult:
        """메인 루프 심장박동을 확인한다."""
        elapsed = time.time() - self._last_heartbeat
        warn_sec = getattr(self._config, "heartbeat_warn_sec", 1200)
        crit_sec = getattr(self._config, "heartbeat_critical_sec", 1800)

        if elapsed > crit_sec:
            return CheckResult(name="heartbeat", status="critical",
                               message=f"메인 루프 {elapsed:.0f}초 미응답", value=elapsed)
        if elapsed > warn_sec:
            return CheckResult(name="heartbeat", status="warn",
                               message=f"메인 루프 {elapsed:.0f}초 미응답", value=elapsed)
        return CheckResult(name="heartbeat", status="ok",
                           message=f"정상 ({elapsed:.0f}초 전)", value=elapsed)

    # ─── Check 2: 이벤트 루프 지연 ───

    async def _check_event_loop_lag(self) -> CheckResult:
        """이벤트 루프 지연을 측정한다."""
        t0 = time.monotonic()
        await asyncio.sleep(0.1)
        lag = time.monotonic() - t0 - 0.1

        if lag > 10.0:
            return CheckResult(name="event_loop", status="critical",
                               message=f"이벤트 루프 지연 {lag:.1f}초", value=lag)
        if lag > 3.0:
            return CheckResult(name="event_loop", status="warn",
                               message=f"이벤트 루프 지연 {lag:.1f}초", value=lag)
        return CheckResult(name="event_loop", status="ok",
                           message=f"정상 (지연 {lag:.2f}초)", value=lag)

    # ─── Check 3: API 연결 ───

    async def _check_api(self) -> CheckResult:
        """빗썸 API 연결을 확인한다."""
        if not self._get_bithumb_client:
            return CheckResult(name="api", status="ok", message="API 클라이언트 미설정")

        client = self._get_bithumb_client()
        timeout = getattr(self._config, "api_timeout_sec", 5)
        fail_limit = getattr(self._config, "api_consecutive_fail_critical", 3)

        try:
            t0 = time.monotonic()
            await asyncio.wait_for(client.get_ticker("BTC"), timeout=timeout)
            latency = time.monotonic() - t0
            self._api_consecutive_fails = 0

            if latency > 2.0:
                return CheckResult(name="api", status="warn",
                                   message=f"API 응답 지연 ({latency:.1f}초)", value=latency)
            return CheckResult(name="api", status="ok",
                               message=f"정상 ({latency:.2f}초)", value=latency)
        except Exception as e:
            self._api_consecutive_fails += 1
            if self._api_consecutive_fails >= fail_limit:
                return CheckResult(name="api", status="critical",
                                   message=f"API 연속 {self._api_consecutive_fails}회 실패: {e}")
            return CheckResult(name="api", status="warn",
                               message=f"API 실패 ({self._api_consecutive_fails}회): {e}")

    # ─── Check 4: 데이터 신선도 ───

    def _check_data_freshness(self) -> CheckResult:
        """마지막 캔들 데이터의 신선도를 확인한다."""
        if not self._get_last_candle_ts:
            return CheckResult(name="data_freshness", status="ok", message="데이터 소스 미설정")

        last_ts = self._get_last_candle_ts()
        if last_ts <= 0:
            return CheckResult(name="data_freshness", status="warn", message="캔들 데이터 없음")

        age_min = (time.time() - last_ts / 1000) / 60  # ms → sec → min
        warn_min = getattr(self._config, "data_freshness_warn_min", 20)
        crit_min = getattr(self._config, "data_freshness_critical_min", 40)

        if age_min > crit_min:
            return CheckResult(name="data_freshness", status="critical",
                               message=f"데이터 {age_min:.0f}분 경과", value=age_min)
        if age_min > warn_min:
            return CheckResult(name="data_freshness", status="warn",
                               message=f"데이터 {age_min:.0f}분 경과", value=age_min)
        return CheckResult(name="data_freshness", status="ok",
                           message=f"정상 ({age_min:.0f}분 전)", value=age_min)

    # ─── Check 5: 포지션 정합성 ───

    async def _check_reconciliation(self) -> CheckResult:
        """봇 포지션과 거래소 잔고를 비교한다."""
        if not self._get_positions or not self._get_exchange_balances:
            return CheckResult(name="reconciliation", status="ok", message="정합성 검사 미설정")

        # 주기 제한 (1시간마다)
        now = time.time()
        interval = getattr(self._config, "reconciliation_interval_sec", 3600)
        if now - self._last_reconciliation < interval:
            return CheckResult(name="reconciliation", status="ok", message="주기 미도래")
        self._last_reconciliation = now

        try:
            positions = self._get_positions()
            balances = await self._get_exchange_balances()
            drifts = []
            for symbol, pos in positions.items():
                # get_balance() returns flat keys like "available_btc"
                exchange_qty = float(balances.get(f"available_{symbol.lower()}", 0))
                local_qty = pos.get("qty", 0) if isinstance(pos, dict) else getattr(pos, "qty", 0)
                if local_qty > 0 and abs(exchange_qty - local_qty) / local_qty > 0.05:
                    drifts.append(f"{symbol}: 봇={local_qty:.4f} 거래소={exchange_qty:.4f}")

            if drifts:
                msg = "포지션 drift: " + ", ".join(drifts)
                return CheckResult(name="reconciliation", status="critical", message=msg)
            return CheckResult(
                name="reconciliation", status="ok",
                message=f"정합성 정상 ({len(positions)}종)",
            )
        except Exception as e:
            return CheckResult(name="reconciliation", status="warn",
                               message=f"정합성 검사 실패: {e}")

    # ─── Check 6: 시스템 리소스 ───

    def _check_system_resources(self) -> CheckResult:
        """CPU/메모리/디스크/WAL 사용량을 확인한다."""
        try:
            # 메모리 (psutil 없이 /proc/meminfo 사용)
            with open("/proc/meminfo") as f:
                lines = f.readlines()
            mem_total = int(lines[0].split()[1])
            mem_avail = int(lines[2].split()[1])
            mem_pct = (1 - mem_avail / mem_total) * 100 if mem_total > 0 else 0

            # 디스크
            disk = shutil.disk_usage("/")
            disk_pct = disk.used / disk.total * 100

            # WAL 파일 크기
            wal_path = (str(self._journal._db_path) + "-wal") if self._journal else "data/journal.db-wal"
            wal_mb = os.path.getsize(wal_path) / (1024 * 1024) if os.path.exists(wal_path) else 0

            warn_mem = getattr(self._config, "memory_warn_pct", 70)
            crit_disk = getattr(self._config, "disk_critical_pct", 90)
            warn_wal = getattr(self._config, "wal_warn_mb", 100)

            status: Literal["ok", "warn", "critical"] = "ok"
            issues: list[str] = []

            if disk_pct > crit_disk:
                issues.append(f"디스크 {disk_pct:.0f}%")
                status = "critical"
            if mem_pct > warn_mem:
                issues.append(f"메모리 {mem_pct:.0f}%")
                if status == "ok":
                    status = "warn"
            if wal_mb > warn_wal:
                issues.append(f"WAL {wal_mb:.0f}MB")
                if status == "ok":
                    status = "warn"

            if issues:
                return CheckResult(name="system_resources", status=status, message=", ".join(issues))
            return CheckResult(
                name="system_resources", status="ok",
                message=f"메모리 {mem_pct:.0f}%, 디스크 {disk_pct:.0f}%",
            )
        except Exception as e:
            return CheckResult(name="system_resources", status="warn",
                               message=f"리소스 확인 실패: {e}")

    # ─── Check 7: 거래 지표 ───

    def _check_trading_metrics(self) -> CheckResult:
        """연속 손실, 일일 DD 등을 확인한다."""
        if not self._journal:
            return CheckResult(name="trading_metrics", status="ok", message="저널 미설정")

        try:
            consec = self._journal.get_consecutive_losses()
            trades = self._journal.get_recent_trades(limit=50)
            today_start = time.time() - 86400
            today_trades = [
                t for t in trades
                if (t.get("exit_time", 0) or 0) / 1000 > today_start
            ]
            daily_pnl = sum(t.get("net_pnl_krw", 0) or 0 for t in today_trades)

            warn_dd = getattr(self._config, "daily_dd_warn_pct", 2.0)
            crit_dd = getattr(self._config, "daily_dd_critical_pct", 3.0)

            status: Literal["ok", "warn", "critical"] = "ok"
            issues: list[str] = []

            if consec >= 3:
                issues.append(f"연속 {consec}패")
                status = "critical"
            elif consec >= 2:
                issues.append(f"연속 {consec}패")
                status = "warn"

            if daily_pnl < 0 and today_trades:
                equity = self._get_equity() if self._get_equity else 0
                if equity > 0:
                    dd_pct = abs(daily_pnl) / equity * 100
                    if dd_pct > crit_dd:
                        issues.append(f"일일 DD {dd_pct:.1f}%")
                        if status != "critical":
                            status = "critical"
                    elif dd_pct > warn_dd:
                        issues.append(f"일일 DD {dd_pct:.1f}%")
                        if status == "ok":
                            status = "warn"

            # 전략별 7일 승률 체크 (별도 쿼리 — 200건)
            win_rate_threshold = getattr(self._config, "auto_fix_win_rate_threshold", 0.30)
            min_trades = getattr(self._config, "auto_fix_min_trades", 10)
            seven_days_ago = time.time() - 7 * 86400

            try:
                recent7d = self._journal.get_trades_since(int(seven_days_ago))
                strategy_trades: dict[str, list[dict]] = {}
                for t in recent7d:
                    strategy = t.get("strategy", "unknown")
                    strategy_trades.setdefault(strategy, []).append(t)

                for strategy, strades in strategy_trades.items():
                    if len(strades) >= min_trades:
                        wins = sum(1 for t in strades if (t.get("net_pnl_krw", 0) or 0) > 0)
                        wr = wins / len(strades)
                        if wr < win_rate_threshold:
                            self._trigger_auto_fix(strategy, f"win_rate_{wr:.0%}_below_30pct")
            except Exception:
                logger.exception("전략별 승률 체크 실패")

            if issues:
                return CheckResult(name="trading_metrics", status=status, message=", ".join(issues))
            return CheckResult(
                name="trading_metrics", status="ok",
                message=f"연속손실 {consec}회, 금일 {len(today_trades)}건",
            )
        except Exception as e:
            return CheckResult(name="trading_metrics", status="warn",
                               message=f"지표 확인 실패: {e}")

    def _trigger_auto_fix(self, strategy: str, reason: str) -> None:
        """전략 자동 수정 스크립트를 비동기적으로 실행한다.

        HealthMonitor 주기를 차단하지 않으며, 예외를 절대 외부로 전파하지 않는다.
        """
        try:
            project_root = Path(__file__).resolve().parent.parent
            ts_file = project_root / "data" / f"last_auto_fix_{strategy}.ts"
            if ts_file.exists():
                try:
                    last_run = float(ts_file.read_text().strip())
                    if time.time() - last_run < 7 * 86400:
                        logger.info(
                            "auto-fix skipped (cooldown): strategy=%s reason=%s",
                            strategy, reason,
                        )
                        return
                except (ValueError, OSError):
                    pass

            subprocess.Popen(
                ["bash", "scripts/auto_fix.sh", strategy, reason],
                cwd=str(project_root),
                start_new_session=True,
            )
            logger.info("auto-fix triggered: strategy=%s reason=%s", strategy, reason)
        except Exception:  # noqa: BLE001
            logger.exception("auto-fix 실행 실패 (무시)")


    # ─── Check 10: 자본 활용률 ───

    def _check_utilization(self) -> CheckResult:
        """자본 활용률이 임계값 이상인지 확인한다."""
        if not self._get_positions or not self._get_equity:
            return CheckResult(name="utilization", status="ok", message="활용률 검사 미설정")

        try:
            positions = self._get_positions()
            total_equity = self._get_equity()

            if total_equity <= 0:
                return CheckResult(name="utilization", status="ok", message="자본금 정보 없음")

            # 포지션의 size_krw 합산
            total_allocated = 0.0
            for symbol, pos in positions.items():
                if isinstance(pos, dict):
                    total_allocated += pos.get("size_krw", 0)
                else:
                    total_allocated += getattr(pos, "size_krw", 0)

            util_pct = (total_allocated / total_equity) * 100 if total_equity > 0 else 0
            warn_threshold = getattr(self._config, "utilization_warn_pct", 10)
            warn_duration_h = getattr(self._config, "utilization_warn_duration_h", 6)

            if util_pct < warn_threshold:
                now = time.time()
                if self._low_util_since == 0:
                    self._low_util_since = now
                    return CheckResult(
                        name="utilization", status="ok",
                        message=f"저활용 시작: {util_pct:.1f}% (임계값 {warn_threshold}%)",
                        value=util_pct,
                    )

                elapsed_h = (now - self._low_util_since) / 3600
                if elapsed_h >= warn_duration_h:
                    return CheckResult(
                        name="utilization", status="warn",
                        message=f"활용률 {util_pct:.1f}% < {warn_threshold}% ({elapsed_h:.1f}h 지속)",
                        value=util_pct,
                    )
                return CheckResult(
                    name="utilization", status="ok",
                    message=f"저활용: {util_pct:.1f}% ({elapsed_h:.1f}h/{warn_duration_h}h)",
                    value=util_pct,
                )
            else:
                # 활용률이 정상으로 돌아옴
                self._low_util_since = 0
                return CheckResult(
                    name="utilization", status="ok",
                    message=f"정상: {util_pct:.1f}% > {warn_threshold}%",
                    value=util_pct,
                )
        except Exception as e:
            return CheckResult(
                name="utilization", status="warn",
                message=f"활용률 점검 실패: {e}",
            )

    # ─── Check 11: 잔고 정합성 ───

    async def _check_balance_integrity(self) -> CheckResult:
        """거래소 잔고가 봇 포지션과 일치하는지 확인한다."""
        if not self._get_positions or not self._get_exchange_balances:
            return CheckResult(name="balance_check", status="ok", message="잔고 점검 미설정")

        # 주기 제한 (1시간마다)
        now = time.time()
        interval = getattr(self._config, "balance_check_interval_sec", 3600)
        if now - self._last_balance_check < interval:
            return CheckResult(name="balance_check", status="ok", message="주기 미도래")
        self._last_balance_check = now

        try:
            positions = self._get_positions()
            balances = await self._get_exchange_balances()
            issues = []

            # Check 1: 봇이 포지션을 보유하는데 거래소 잔고가 50% 미만
            for symbol, pos in positions.items():
                local_qty = pos.get("qty", 0) if isinstance(pos, dict) else getattr(pos, "qty", 0)
                if local_qty > 0:
                    # balances 키는 "available_btc" 형식
                    exchange_qty = float(balances.get(f"available_{symbol.lower()}", 0))
                    if exchange_qty < local_qty * 0.5:
                        issues.append(
                            f"{symbol}: 거래소={exchange_qty:.4f} < 봇={local_qty:.4f}*0.5"
                        )

            if issues:
                msg = "CRITICAL 잔고 불일치: " + ", ".join(issues)
                return CheckResult(name="balance_check", status="critical", message=msg)

            # Check 2: 거래소에 봇 포지션 외에 먼지 잔고(> 100 KRW) 존재
            dust_coins = []
            for key, value in balances.items():
                if key.startswith("available_"):
                    coin = key.replace("available_", "").upper()
                    qty = float(value)
                    if qty > 0 and coin not in positions:
                        # 가격 추정: avg_buy_price 사용
                        avg_price_key = f"avg_buy_price_{coin.lower()}"
                        avg_price = float(balances.get(avg_price_key, 0))
                        value_krw = qty * avg_price if avg_price > 0 else 0
                        if value_krw > 100:
                            dust_coins.append(f"{coin} {qty:.4f} ≈ {value_krw:.0f}원")

            if dust_coins:
                msg = "WARNING 미관리 잔고: " + ", ".join(dust_coins)
                return CheckResult(name="balance_check", status="warn", message=msg)

            return CheckResult(
                name="balance_check", status="ok",
                message=f"잔고 정합성 정상 ({len(positions)}종 추적)",
            )
        except Exception as e:
            return CheckResult(
                name="balance_check", status="warn",
                message=f"잔고 점검 실패: {e}",
            )

    # ─── 자동 진단 시스템 ───

    # Tier 분류 규칙
    _TIER3_PATTERNS = frozenset({
        "reconciliation_drift", "balance_mismatch", "mdd_exceeded",
        "consecutive_loss_critical", "daily_dd_critical",
    })
    _TIER1_PATTERNS = frozenset({
        "api_timeout", "network_error", "data_fetch_single",
    })

    _diagnosis_cooldown: dict[str, float] = {}
    _DIAGNOSIS_COOLDOWN_SEC = 1800  # 30분
    _STARTUP_GRACE_SEC = 600  # 시작 후 10분간 진단 건너뛰기 (데이터 수집 대기)

    def _classify_tier(self, error_type: str, details: str = "") -> int:
        """오류를 Tier 1/2/3으로 분류한다."""
        if error_type in self._TIER3_PATTERNS:
            return 3
        if error_type in self._TIER1_PATTERNS:
            return 1
        return 2

    async def trigger_diagnosis(
        self,
        error_type: str,
        details: str,
        context: dict | None = None,
    ) -> None:
        """오류 자동 진단을 실행한다.

        Tier 분류 후:
        - T1: 로그만 기록
        - T2: Claude 진단 → Discord 보고
        - T3: 긴급 알림 + Claude 진단
        """
        tier = self._classify_tier(error_type, details)

        if tier == 1:
            logger.debug("T1 오류 무시: %s — %s", error_type, details)
            return

        # 시작 직후 워밍업 기간에는 T2 진단 건너뛰기 (T3 긴급만 허용)
        if tier == 2 and hasattr(self, "_start_time"):
            if time.time() - self._start_time < self._STARTUP_GRACE_SEC:
                logger.debug("워밍업 기간 T2 진단 건너뛰기: %s", error_type)
                return

        # 쿨다운 체크
        ctx = context or {}
        cooldown_key = error_type + ":" + ctx.get("symbol", "")
        last = self._diagnosis_cooldown.get(cooldown_key, 0)
        if time.time() - last < self._DIAGNOSIS_COOLDOWN_SEC:
            logger.debug("진단 쿨다운: %s", cooldown_key)
            return
        self._diagnosis_cooldown[cooldown_key] = time.time()

        # T3: 긴급 알림 먼저
        if tier == 3 and self._notifier:
            msg = "\U0001f6a8 **긴급** " + error_type + ": " + details + "\n자동 진단 시작..."
            await self._notifier.send(msg, channel="system")

        # Claude 진단 (비동기, 논블로킹)
        task = asyncio.create_task(self._run_diagnosis(error_type, details, ctx, tier))
        task.add_done_callback(
            lambda t: logger.exception("진단 태스크 실패: %s", t.exception())
            if t.exception() else None
        )

    async def _run_diagnosis(
        self, error_type: str, details: str, context: dict, tier: int,
    ) -> None:
        """Claude CLI로 오류를 진단하고 결과를 Discord에 보고한다."""
        try:
            # 최근 파이프라인 이벤트 조회
            recent_events = ""
            try:
                import sqlite3
                db_path = str(Path(__file__).resolve().parent.parent / "data" / "journal.db")
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT event_type, symbol, data_json, "
                    "datetime(created_at/1000, 'unixepoch', '+9 hours') as kst "
                    "FROM pipeline_events ORDER BY created_at DESC LIMIT 10"
                ).fetchall()
                if rows:
                    lines = []
                    for r in rows:
                        lines.append("  " + r["kst"] + " " + r["event_type"] + " " + r["symbol"] + " " + r["data_json"][:100])
                    recent_events = "\n".join(lines)
                conn.close()
            except Exception:
                pass

            prompt = (
                "당신은 빗썸 KRW 마켓 자동매매 봇의 운영 진단 전문가입니다.\n\n"
                "## 시스템 구조\n"
                "- Python asyncio 기반, 5분 주기 사이클\n"
                "- 전략: mean_reversion (주력), DCA (BTC/ETH 매집)\n"
                "- 파이프라인: 시장데이터 수집 → L1 필터 → 전략 점수 → 사이징 → 주문\n"
                "- L1 필터: 거래량(20봉 평균×0.4), 스프레드(Tier별 한도×2), 1H 급변동\n"
                "- 사이징: Active Pool 15%, 심야 T3 30% 축소\n"
                "- 주문: normalize_price(tick 내림) + normalize_qty(소수점 내림) → validate_order(최소 4999원)\n"
                "- HealthMonitor: 15분마다 9개 항목 점검\n"
                "- 봇 시작 직후에는 캔들 데이터 미수집 상태가 정상\n\n"
                "## 오류 정보\n"
                "- 유형: " + error_type + "\n"
                "- 상세: " + details + "\n"
                "- 컨텍스트: " + str(context) + "\n"
                "- 심각도: Tier " + str(tier) + "\n\n"
                "## 최근 파이프라인 이벤트\n"
                + (recent_events or "(없음)") + "\n\n"
                "## 요청사항\n"
                "1. 근본 원인 (이 시스템 구조 기반으로 구체적으로, 1~2줄)\n"
                "2. 수정안 (이 프로젝트의 실제 파일/함수명 사용. 추측 금지)\n"
                "3. 긴급도 (즉시/다음 점검/관찰 필요)\n\n"
                "간결하게 답변. 최대 10줄. 프로젝트에 없는 코드를 제안하지 마세요."
            )

            response = await call_claude(prompt, model="haiku", timeout=30)

            if not response:
                logger.warning("진단 실패: Claude 응답 없음 (%s)", error_type)
                if self._notifier:
                    msg = "\u26a0 **" + error_type + "** 자동 진단 실패 (Claude 응답 없음)\n" + details
                    await self._notifier.send(msg, channel="system")
                return

            # Discord 보고
            tier_emoji = "\U0001f6a8" if tier == 3 else "\u26a0"
            report = (
                tier_emoji + " **자동 진단 보고**\n"
                "오류: " + error_type + "\n"
                "상세: " + details + "\n\n"
                "\U0001f4cb **분석 결과:**\n" + response
            )

            if self._notifier:
                await self._notifier.send(report, channel="system")

            logger.info("자동 진단 완료: %s → %s", error_type, response[:100])

        except Exception:
            logger.exception("자동 진단 실행 중 오류 (%s)", error_type)

    # ─── Check 8: 디스코드 연결 ───

    async def _check_discord(self) -> CheckResult:
        """디스코드 webhook 연결을 확인한다."""
        if not self._notifier:
            return CheckResult(name="discord", status="ok", message="알림 미설정")
        # Verify system channel webhook is configured
        if not getattr(self._notifier, "_webhooks", {}).get("system"):
            return CheckResult(name="discord", status="warn", message="system 채널 webhook 미설정")
        return CheckResult(name="discord", status="ok", message="알림 설정됨")

    # ─── Check 9: 파이프라인 건전성 ───

    def _check_pipeline_health(self) -> CheckResult:
        """시그널→거래 파이프라인 전환율을 점검한다."""
        if not self._journal:
            return CheckResult(name="pipeline", status="ok", message="저널 미설정")

        try:
            stats = self._journal.get_pipeline_stats(hours=4)
            sizing_done = stats.get("sizing_done", 0)
            filled = stats.get("order_filled", 0)
            risk_rejected = stats.get("risk_rejected", 0)
            corr_rejected = stats.get("corr_rejected", 0)

            # 사이징까지 도달한 시그널 수 (risk/corr 거절 제외)
            total_signals = sizing_done + risk_rejected + corr_rejected
            # 사이징 통과율 (size_krw > 0 → order_filled)
            sizing_zero = sizing_done - filled  # sizing은 했지만 체결 안 된 수

            if total_signals == 0:
                return CheckResult(
                    name="pipeline", status="ok",
                    message="시그널 없음 (4h)", value=0,
                )

            if sizing_done == 0:
                return CheckResult(
                    name="pipeline", status="ok",
                    message=f"사이징 도달 0건 (risk거절 {risk_rejected}, corr거절 {corr_rejected})",
                )

            conversion = filled / sizing_done if sizing_done > 0 else 0

            # 사이징까지 도달했는데 전부 0원 → 파이프라인 교착
            if filled == 0 and sizing_done >= 5:
                return CheckResult(
                    name="pipeline", status="critical",
                    message=f"파이프라인 교착: 사이징 {sizing_done}건 전부 미진입 (4h)",
                    value=conversion,
                )
            if filled == 0 and sizing_done >= 2:
                return CheckResult(
                    name="pipeline", status="warn",
                    message=f"전환율 0%: 사이징 {sizing_done}건, 체결 0건 (4h)",
                    value=conversion,
                )

            return CheckResult(
                name="pipeline", status="ok",
                message=f"전환율 {conversion:.0%}: 사이징 {sizing_done}→체결 {filled} (4h)",
                value=conversion,
            )
        except Exception as e:
            return CheckResult(
                name="pipeline", status="warn",
                message=f"파이프라인 점검 실패: {e}",
            )
