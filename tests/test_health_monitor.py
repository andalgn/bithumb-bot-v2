"""HealthMonitor 단위 테스트."""
from __future__ import annotations

import asyncio
import time

import pytest

from app.health_monitor import Alert, AlertManager, CheckResult, SCORE_WEIGHTS
from app.journal import Journal


@pytest.fixture
def journal(tmp_path):
    """임시 Journal을 생성한다."""
    db_path = tmp_path / "test_journal.db"
    j = Journal(str(db_path))
    return j


def test_record_and_get_health_check(journal):
    """헬스 체크 기록 후 조회할 수 있다."""
    results = [{"name": "heartbeat", "status": "ok", "message": "정상"}]
    alerts = [{"level": "warning", "message": "API 지연"}]
    journal.record_health_check(score=85, verdict="healthy", results=results, alerts=alerts)

    checks = journal.get_recent_health_checks(limit=10)
    assert len(checks) == 1
    assert checks[0]["score"] == 85
    assert checks[0]["verdict"] == "healthy"
    assert checks[0]["results"][0]["name"] == "heartbeat"
    assert checks[0]["alerts"][0]["level"] == "warning"


def test_check_result_defaults():
    """CheckResult가 기본값으로 생성된다."""
    cr = CheckResult(name="test", status="ok", message="정상")
    assert cr.status == "ok"
    assert cr.checked_at > 0


def test_alert_manager_cooldown():
    """동일 알림은 쿨다운 내 중복 추가되지 않는다."""
    am = AlertManager(cooldown_critical_sec=60, cooldown_warning_sec=120)
    a1 = Alert(level="critical", category="api", message="API 실패")
    assert am.add(a1) is True

    # flush하여 last_sent 기록
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(am.flush(None))
    finally:
        loop.close()

    a2 = Alert(level="critical", category="api", message="API 실패 2")
    assert am.add(a2) is False  # 쿨다운 내


def test_alert_manager_suppression():
    """상관 억제 대상 카테고리는 추가되지 않는다."""
    am = AlertManager()
    am.set_suppressed({"data_freshness"})
    a = Alert(level="warning", category="data_freshness", message="데이터 오래됨")
    assert am.add(a) is False


def test_alert_manager_info_goes_to_daily():
    """INFO 알림은 daily_buffer에 들어간다."""
    am = AlertManager()
    a = Alert(level="info", category="heartbeat", message="정상")
    am.add(a)
    assert len(am._pending) == 0
    buf = am.get_daily_buffer()
    assert len(buf) == 1
