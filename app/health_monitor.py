"""HealthMonitor — 봇 건강 감시 시스템.

15분마다 8개 항목을 점검하고, 건강 점수(0-100)를 산출하며,
이상 발생 시 디스코드로 알림을 전송한다.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from app.notify import DiscordNotifier

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
    "reconciliation": 15,
    "system_resources": 5,
    "trading_metrics": 10,
    "discord": 5,
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
        journal: object | None = None,
        config: object | None = None,
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
        self._last_heartbeat: float = time.time()
        self._api_consecutive_fails: int = 0

        # 외부에서 주입하는 상태 참조
        self._get_last_candle_ts: Callable[[], float] | None = None
        self._get_positions: Callable[[], dict] | None = None
        self._get_exchange_balances: Callable[[], Coroutine[None, None, dict]] | None = None
        self._get_bithumb_client: Callable[[], object] | None = None

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
        """8개 점검을 실행한다."""
        return [
            self._check_heartbeat(),
            await self._check_event_loop_lag(),
            await self._check_api(),
            self._check_data_freshness(),
            await self._check_reconciliation(),
            self._check_system_resources(),
            self._check_trading_metrics(),
            await self._check_discord(),
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
        if not hasattr(self, "_last_reconciliation"):
            self._last_reconciliation: float = 0.0
        if now - self._last_reconciliation < interval:
            return CheckResult(name="reconciliation", status="ok", message="주기 미도래")
        self._last_reconciliation = now

        try:
            positions = self._get_positions()
            balances = await self._get_exchange_balances()
            drifts = []
            for symbol, pos in positions.items():
                exchange_qty = float(balances.get(symbol, {}).get("available", 0))
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
        import os
        import shutil

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
            wal_path = "data/journal.db-wal"
            wal_mb = os.path.getsize(wal_path) / (1024 * 1024) if os.path.exists(wal_path) else 0

            warn_mem = getattr(self._config, "memory_warn_pct", 70)
            crit_disk = getattr(self._config, "disk_critical_pct", 90)
            warn_wal = getattr(self._config, "wal_warn_mb", 100)

            status: Literal["ok", "warn", "critical"] = "ok"
            issues: list[str] = []
            severity_order = ["ok", "warn", "critical"]

            if disk_pct > crit_disk:
                issues.append(f"디스크 {disk_pct:.0f}%")
                status = "critical"
            if mem_pct > warn_mem:
                issues.append(f"메모리 {mem_pct:.0f}%")
                if severity_order.index("warn") > severity_order.index(status):
                    status = "warn"
            if wal_mb > warn_wal:
                issues.append(f"WAL {wal_mb:.0f}MB")
                if severity_order.index("warn") > severity_order.index(status):
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

            severity_order = ["ok", "warn", "critical"]
            status: Literal["ok", "warn", "critical"] = "ok"
            issues: list[str] = []

            if consec >= 3:
                issues.append(f"연속 {consec}패")
                status = "critical"
            elif consec >= 2:
                issues.append(f"연속 {consec}패")
                status = "warn"

            if daily_pnl < 0 and today_trades:
                total_size = sum(abs(t.get("net_pnl_krw", 0) or 0) for t in today_trades)
                if total_size > 0:
                    dd_pct = abs(daily_pnl) / total_size * 100
                    if dd_pct > crit_dd:
                        issues.append(f"일일 DD {dd_pct:.1f}%")
                        if severity_order.index("critical") > severity_order.index(status):
                            status = "critical"
                    elif dd_pct > warn_dd:
                        issues.append(f"일일 DD {dd_pct:.1f}%")
                        if severity_order.index("warn") > severity_order.index(status):
                            status = "warn"

            if issues:
                return CheckResult(name="trading_metrics", status=status, message=", ".join(issues))
            return CheckResult(
                name="trading_metrics", status="ok",
                message=f"연속손실 {consec}회, 금일 {len(today_trades)}건",
            )
        except Exception as e:
            return CheckResult(name="trading_metrics", status="warn",
                               message=f"지표 확인 실패: {e}")

    # ─── Check 8: 디스코드 연결 ───

    async def _check_discord(self) -> CheckResult:
        """디스코드 webhook 연결을 확인한다."""
        if not self._notifier:
            return CheckResult(name="discord", status="ok", message="알림 미설정")

        # 주기 제한 (4시간마다)
        interval = getattr(self._config, "discord_check_interval_sec", 14400)
        if not hasattr(self, "_last_discord_check"):
            self._last_discord_check: float = 0.0
        if time.time() - self._last_discord_check < interval:
            return CheckResult(name="discord", status="ok", message="주기 미도래")
        self._last_discord_check = time.time()

        try:
            ok = await self._notifier.send("health ping", channel="system")
            if ok:
                return CheckResult(name="discord", status="ok", message="연결 정상")
            return CheckResult(name="discord", status="critical", message="디스코드 전송 실패")
        except Exception as e:
            return CheckResult(name="discord", status="critical", message=f"디스코드 오류: {e}")
