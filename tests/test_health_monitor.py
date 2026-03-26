"""HealthMonitor 단위 테스트."""
from __future__ import annotations

import pytest

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
