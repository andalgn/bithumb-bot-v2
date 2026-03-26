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
