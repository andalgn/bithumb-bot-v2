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
        self._get_last_candle_ts: object | None = None   # () -> float
        self._get_positions: object | None = None         # () -> dict
        self._get_exchange_balances: object | None = None # async () -> dict
        self._get_bithumb_client: object | None = None    # () -> BithumbClient

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
        """8개 점검을 실행한다 (현재는 4개 구현)."""
        checks = [
            self._check_heartbeat(),
            await self._check_event_loop_lag(),
            await self._check_api(),
            self._check_data_freshness(),
        ]
        return checks

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
