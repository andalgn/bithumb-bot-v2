# Self-Evolving Orchestrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a 4-layer orchestrator that monitors bot health, auto-recovers from failures, evolves trading strategies autonomously, and self-repairs code/parameters via Claude Code CLI.

**Architecture:** 5 independent phases, each producing working software. Phase 1 (HealthMonitor) is the foundation. Phases 2-5 build on it but are independently testable. Each phase is self-contained — a fresh agent can implement any phase by reading only that phase's section plus the "Shared Context" block.

**Tech Stack:** Python 3.12, asyncio, SQLite (WAL), aiohttp, sdnotify, Discord webhooks, `claude -p` (headless CLI)

**Context Management:** Each phase starts with a `### Context for This Phase` block containing all file paths, class signatures, and interfaces the implementer needs. This eliminates the need to read the full codebase or prior phases.

---

## Shared Context (Read Once)

### Key Files & Interfaces

| File | Key Class | Purpose |
|------|-----------|---------|
| `app/main.py` | `TradingBot` | Orchestrator. `_run_cycle()` is the 15-min main loop. Components init in `__init__()`. Background tasks via `asyncio.create_task()`. |
| `app/journal.py` | `Journal` | SQLite WAL DB at `data/journal.db`. Tables: trades, signals, executions, risk_events, shadow_trades, backtest_results, feedback. Methods: `record_trade()`, `get_recent_trades()`, `get_consecutive_losses()`. |
| `app/notify.py` | `DiscordNotifier` | `send(text, channel="system")`. Channels: trade, report, backtest, system, command, livegate. Auto-splits >2000 chars. |
| `app/config.py` | `AppConfig` | Frozen dataclasses. Loaded from `configs/config.yaml`. Hot-reload via `_check_config_reload()` in main.py. |
| `app/data_types.py` | — | Enums: `Regime`, `Strategy`, `Tier`, `OrderStatus`, `RunMode`. Dataclasses: `Candle`, `MarketSnapshot`, `Signal`, `Position`, `OrderTicket`. |
| `strategy/darwin_engine.py` | `DarwinEngine` | Shadow population (20-30). `record_cycle()`, `run_tournament()`, `check_champion_replacement()`. Mutation only (no crossover). 5-metric CompositeScore. |
| `strategy/review_engine.py` | `ReviewEngine` | `run_daily_review()` (rule-based), `run_weekly_review()` (DeepSeek). Adjustments stored in ExperimentStore. |
| `strategy/auto_researcher.py` | `AutoResearcher` | `run_session()` → DeepSeek proposes params → backtest → KEEP/REVERT. |
| `strategy/experiment_store.py` | `ExperimentStore` | SQLite. `record()`, `log_param_change()`, `get_history()`. |
| `risk/dd_limits.py` | `DDLimits` | `check(side, equity)` → (allowed, reason, priority). Limits: daily 4%, weekly 8%, monthly 12%, total 20%. |
| `risk/risk_gate.py` | `RiskGate` | `check(signal, equity, positions)` → (allowed, reason). P0-P10 priority system. |
| `market/bithumb_api.py` | `BithumbClient` | `get_ticker()`, `get_balance()`, `get_orderbook()`. Proxy via `self._proxy`. Rate limiting: 15 pub/10 priv per sec. |
| `configs/config.yaml` | — | All runtime config. Hot-reloadable `strategy_params` section. |

### Testing Conventions

- Framework: `pytest` + `pytest-asyncio`
- Fixtures: `tests/fixtures/candles.py` (strong_up, weak_down, range, crisis candles), `tests/fixtures/indicators.py`
- Run: `python -m pytest tests/ -q --ignore=tests/test_bithumb_api.py`
- All 430+ existing tests must continue to pass after each task

### Commit Convention

- English, Conventional Commits (`feat:`, `fix:`, `test:`, `refactor:`)
- `Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>`

---

## Phase 1: HealthMonitor Core

### Context for This Phase

**What we're building:** An async background task in the bot process that runs 8 health checks every 15 minutes, computes a 0-100 health score, stores results in SQLite, and sends alerts to Discord.

**New files to create:**
- `app/health_monitor.py` — HealthMonitor, AlertManager, CheckResult classes
- `tests/test_health_monitor.py` — Unit tests

**Files to modify:**
- `app/journal.py` — Add `health_checks` table
- `app/config.py` — Add `HealthMonitorConfig` dataclass
- `configs/config.yaml` — Add `health_monitor:` section
- `app/main.py` — Integrate HealthMonitor into bot lifecycle

**Dependencies:** None (Phase 1 is standalone)

---

### Task 1: health_checks Table + Config

**Files:**
- Modify: `app/journal.py`
- Modify: `app/config.py`
- Modify: `configs/config.yaml`
- Test: `tests/test_health_monitor.py`

- [ ] **Step 1: Add health_checks table to Journal**

In `app/journal.py`, find the `_init_db()` method and add after existing CREATE TABLE statements:

```python
cursor.execute("""
    CREATE TABLE IF NOT EXISTS health_checks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        score INTEGER NOT NULL,
        verdict TEXT NOT NULL,
        results_json TEXT NOT NULL,
        alerts_json TEXT DEFAULT '[]',
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
""")
```

Add two new methods to the `Journal` class:

```python
def record_health_check(self, score: int, verdict: str, results: list[dict], alerts: list[dict]) -> None:
    """헬스 체크 결과를 기록한다."""
    import json
    self._execute(
        "INSERT INTO health_checks (score, verdict, results_json, alerts_json) VALUES (?, ?, ?, ?)",
        (score, verdict, json.dumps(results, ensure_ascii=False), json.dumps(alerts, ensure_ascii=False)),
    )

def get_recent_health_checks(self, limit: int = 96) -> list[dict]:
    """최근 헬스 체크 결과를 반환한다."""
    import json
    rows = self._fetch_all(
        "SELECT score, verdict, results_json, alerts_json, created_at FROM health_checks ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    return [
        {"score": r[0], "verdict": r[1], "results": json.loads(r[2]), "alerts": json.loads(r[3]), "created_at": r[4]}
        for r in rows
    ]
```

Also add a cleanup line in the existing `cleanup()` method:

```python
self._execute("DELETE FROM health_checks WHERE created_at < datetime('now', '-90 days')")
```

- [ ] **Step 2: Add HealthMonitorConfig to config.py**

In `app/config.py`, add before the `AppConfig` class:

```python
@dataclass(frozen=True)
class HealthMonitorConfig:
    """헬스 모니터 설정."""

    enabled: bool = True
    interval_sec: int = 900
    reconciliation_interval_sec: int = 3600
    discord_check_interval_sec: int = 14400
    heartbeat_warn_sec: int = 1200
    heartbeat_critical_sec: int = 1800
    api_timeout_sec: int = 5
    api_consecutive_fail_critical: int = 3
    data_freshness_warn_min: int = 20
    data_freshness_critical_min: int = 40
    memory_warn_pct: int = 70
    disk_critical_pct: int = 90
    wal_warn_mb: int = 100
    daily_dd_warn_pct: float = 2.0
    daily_dd_critical_pct: float = 3.0
    alert_cooldown_critical_min: int = 30
    alert_cooldown_warning_min: int = 120
    retention_days: int = 90
```

Add `health_monitor: HealthMonitorConfig = field(default_factory=HealthMonitorConfig)` to the `AppConfig` class. Import `field` from dataclasses if not already imported. Make sure `AppConfig` is NOT frozen (it uses `field(default_factory=...)`).

- [ ] **Step 3: Add config.yaml section**

Append to `configs/config.yaml`:

```yaml
health_monitor:
  enabled: true
  interval_sec: 900
  heartbeat_warn_sec: 1200
  heartbeat_critical_sec: 1800
  api_timeout_sec: 5
  api_consecutive_fail_critical: 3
  data_freshness_warn_min: 20
  data_freshness_critical_min: 40
  memory_warn_pct: 70
  disk_critical_pct: 90
  daily_dd_warn_pct: 2.0
  daily_dd_critical_pct: 3.0
  alert_cooldown_critical_min: 30
  alert_cooldown_warning_min: 120
```

- [ ] **Step 4: Write test for health_checks table**

Create `tests/test_health_monitor.py`:

```python
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
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_health_monitor.py -v`
Expected: PASS

Then run full suite: `python -m pytest tests/ -q --ignore=tests/test_bithumb_api.py`
Expected: All pass (430+)

- [ ] **Step 6: Commit**

```bash
git add app/journal.py app/config.py configs/config.yaml tests/test_health_monitor.py
git commit -m "feat: add health_checks table, HealthMonitorConfig, and config section"
```

---

### Task 2: CheckResult + AlertManager

**Files:**
- Create: `app/health_monitor.py`
- Test: `tests/test_health_monitor.py`

- [ ] **Step 1: Create app/health_monitor.py with data types + AlertManager**

```python
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

        if alert.level == "info":
            self._daily_buffer.append(alert)
            return True

        self._pending.append(alert)
        return True

    async def flush(self, notifier: DiscordNotifier | None) -> list[Alert]:
        """대기 중인 알림을 전송하고 반환한다."""
        if not self._pending or not notifier:
            sent = list(self._pending)
            self._pending.clear()
            return sent

        criticals = [a for a in self._pending if a.level == "critical"]
        warnings = [a for a in self._pending if a.level == "warning"]

        for alert in criticals:
            key = f"{alert.category}:{alert.level}"
            self._last_sent[key] = time.time()
            await notifier.send(f"**CRITICAL** {alert.message}", channel="system")

        if warnings:
            key_base = "warning_batch"
            self._last_sent[key_base] = time.time()
            lines = [f"- {a.message}" for a in warnings]
            for a in warnings:
                self._last_sent[f"{a.category}:{a.level}"] = time.time()
            await notifier.send(
                f"**WARNING** ({len(warnings)}건)\n" + "\n".join(lines),
                channel="system",
            )

        sent = list(self._pending)
        self._pending.clear()
        return sent

    def get_daily_buffer(self) -> list[Alert]:
        """일일 요약용 INFO 알림을 반환하고 비운다."""
        buf = list(self._daily_buffer)
        self._daily_buffer.clear()
        return buf
```

- [ ] **Step 2: Write tests for AlertManager**

Append to `tests/test_health_monitor.py`:

```python
from app.health_monitor import Alert, AlertManager, CheckResult, SCORE_WEIGHTS


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
    import asyncio
    asyncio.get_event_loop().run_until_complete(am.flush(None))

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
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_health_monitor.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add app/health_monitor.py tests/test_health_monitor.py
git commit -m "feat: add CheckResult, Alert, AlertManager with cooldown and suppression"
```

---

### Task 3: HealthMonitor Core + 4 Basic Checks

**Files:**
- Modify: `app/health_monitor.py`
- Test: `tests/test_health_monitor.py`

- [ ] **Step 1: Add HealthMonitor class with checks 1-4**

Append to `app/health_monitor.py`:

```python
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
        self._get_last_candle_ts: callable | None = None  # () -> float
        self._get_positions: callable | None = None        # () -> dict
        self._get_exchange_balances: callable | None = None # async () -> dict
        self._get_bithumb_client: callable | None = None   # () -> BithumbClient

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
                alerts_data: list[dict] = []
                for r in results:
                    if r.status == "critical":
                        alert = Alert(level="critical", category=r.name, message=r.message)
                        self._alert_manager.add(alert)
                    elif r.status == "warn":
                        alert = Alert(level="warning", category=r.name, message=r.message)
                        self._alert_manager.add(alert)

                sent = await self._alert_manager.flush(self._notifier)
                alerts_data = [{"level": a.level, "category": a.category, "message": a.message} for a in sent]

                # 저장
                results_data = [{"name": r.name, "status": r.status, "message": r.message, "value": r.value} for r in results]
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

        age_min = (time.time() - last_ts / 1000) / 60  # timestamp가 ms일 수 있음
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
```

- [ ] **Step 2: Write tests for HealthMonitor checks 1-4**

Append to `tests/test_health_monitor.py`:

```python
from app.health_monitor import HealthMonitor, compute_health_score


def test_compute_health_score_all_ok():
    """모든 점검이 ok이면 100점이다."""
    results = [
        CheckResult(name="heartbeat", status="ok", message=""),
        CheckResult(name="event_loop", status="ok", message=""),
        CheckResult(name="api", status="ok", message=""),
        CheckResult(name="data_freshness", status="ok", message=""),
        CheckResult(name="reconciliation", status="ok", message=""),
        CheckResult(name="system_resources", status="ok", message=""),
        CheckResult(name="trading_metrics", status="ok", message=""),
        CheckResult(name="discord", status="ok", message=""),
    ]
    score, verdict = compute_health_score(results)
    assert score == 100
    assert verdict == "healthy"


def test_compute_health_score_mixed():
    """warn 항목은 절반 점수를 받는다."""
    results = [
        CheckResult(name="heartbeat", status="ok", message=""),
        CheckResult(name="api", status="warn", message=""),
        CheckResult(name="data_freshness", status="critical", message=""),
    ]
    score, _ = compute_health_score(results)
    assert score == 20 + 10 + 0  # heartbeat ok(20) + api warn(10) + data critical(0)


def test_check_heartbeat_ok():
    """최근 heartbeat은 ok를 반환한다."""
    hm = HealthMonitor()
    hm.record_heartbeat()
    result = hm._check_heartbeat()
    assert result.status == "ok"


def test_check_heartbeat_critical():
    """오래된 heartbeat은 critical을 반환한다."""
    hm = HealthMonitor()
    hm._last_heartbeat = time.time() - 2000
    result = hm._check_heartbeat()
    assert result.status == "critical"


@pytest.mark.asyncio
async def test_check_event_loop_lag_ok():
    """이벤트 루프 지연이 낮으면 ok를 반환한다."""
    hm = HealthMonitor()
    result = await hm._check_event_loop_lag()
    assert result.status == "ok"


def test_check_data_freshness_no_source():
    """데이터 소스 미설정 시 ok를 반환한다."""
    hm = HealthMonitor()
    result = hm._check_data_freshness()
    assert result.status == "ok"


import time  # noqa: E402 — already imported above but needed for test_check_heartbeat_critical
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_health_monitor.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add app/health_monitor.py tests/test_health_monitor.py
git commit -m "feat: add HealthMonitor with checks 1-4 (heartbeat, event_loop, api, data_freshness)"
```

---

### Task 4: Checks 5-8 (Reconciliation, Resources, Trading, Discord)

**Files:**
- Modify: `app/health_monitor.py`
- Test: `tests/test_health_monitor.py`

- [ ] **Step 1: Add checks 5-8 to HealthMonitor**

Add these methods to the `HealthMonitor` class and update `_run_all_checks`:

```python
    async def _run_all_checks(self) -> list[CheckResult]:
        """8개 점검을 실행한다."""
        checks = [
            self._check_heartbeat(),
            await self._check_event_loop_lag(),
            await self._check_api(),
            self._check_data_freshness(),
            await self._check_reconciliation(),
            self._check_system_resources(),
            self._check_trading_metrics(),
            await self._check_discord(),
        ]
        return checks

    # ─── Check 5: 포지션 정합성 ───

    async def _check_reconciliation(self) -> CheckResult:
        """봇 포지션과 거래소 잔고를 비교한다."""
        if not self._get_positions or not self._get_exchange_balances:
            return CheckResult(name="reconciliation", status="ok", message="정합성 검사 미설정")

        # 주기 제한 (1시간마다)
        now = time.time()
        interval = getattr(self._config, "reconciliation_interval_sec", 3600)
        if not hasattr(self, "_last_reconciliation"):
            self._last_reconciliation = 0.0
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
            return CheckResult(name="reconciliation", status="ok",
                               message=f"정합성 정상 ({len(positions)}종)")
        except Exception as e:
            return CheckResult(name="reconciliation", status="warn",
                               message=f"정합성 검사 실패: {e}")

    # ─── Check 6: 시스템 리소스 ───

    def _check_system_resources(self) -> CheckResult:
        """CPU/메모리/디스크 사용량을 확인한다."""
        import shutil
        import os

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

            issues = []
            status = "ok"
            if disk_pct > crit_disk:
                issues.append(f"디스크 {disk_pct:.0f}%")
                status = "critical"
            if mem_pct > warn_mem:
                issues.append(f"메모리 {mem_pct:.0f}%")
                status = max(status, "warn", key=lambda s: ["ok", "warn", "critical"].index(s))
            if wal_mb > warn_wal:
                issues.append(f"WAL {wal_mb:.0f}MB")
                status = max(status, "warn", key=lambda s: ["ok", "warn", "critical"].index(s))

            if issues:
                return CheckResult(name="system_resources", status=status, message=", ".join(issues))
            return CheckResult(name="system_resources", status="ok",
                               message=f"메모리 {mem_pct:.0f}%, 디스크 {disk_pct:.0f}%")
        except Exception as e:
            return CheckResult(name="system_resources", status="warn", message=f"리소스 확인 실패: {e}")

    # ─── Check 7: 거래 지표 ───

    def _check_trading_metrics(self) -> CheckResult:
        """연속 손실, 일일 DD 등을 확인한다."""
        if not self._journal:
            return CheckResult(name="trading_metrics", status="ok", message="저널 미설정")

        try:
            consec = self._journal.get_consecutive_losses()
            # 최근 24시간 거래의 순익
            trades = self._journal.get_recent_trades(limit=50)
            today_start = time.time() - 86400
            today_trades = [t for t in trades if (t.get("exit_time", 0) or 0) / 1000 > today_start]
            daily_pnl = sum(t.get("net_pnl_krw", 0) or 0 for t in today_trades)

            warn_dd = getattr(self._config, "daily_dd_warn_pct", 2.0)
            crit_dd = getattr(self._config, "daily_dd_critical_pct", 3.0)

            issues = []
            status = "ok"
            if consec >= 3:
                issues.append(f"연속 {consec}패")
                status = "critical"
            elif consec >= 2:
                issues.append(f"연속 {consec}패")
                status = "warn"

            if daily_pnl < 0 and today_trades:
                # 간이 DD 추정 (전체 자본 대비는 아니지만 경고 목적)
                total_size = sum(abs(t.get("net_pnl_krw", 0) or 0) for t in today_trades)
                if total_size > 0:
                    dd_pct = abs(daily_pnl) / max(total_size, 1) * 100
                    if dd_pct > crit_dd:
                        issues.append(f"일일 DD {dd_pct:.1f}%")
                        status = "critical"
                    elif dd_pct > warn_dd:
                        issues.append(f"일일 DD {dd_pct:.1f}%")
                        status = max(status, "warn", key=lambda s: ["ok", "warn", "critical"].index(s))

            if issues:
                return CheckResult(name="trading_metrics", status=status, message=", ".join(issues))
            return CheckResult(name="trading_metrics", status="ok",
                               message=f"연속손실 {consec}회, 금일 {len(today_trades)}건")
        except Exception as e:
            return CheckResult(name="trading_metrics", status="warn", message=f"지표 확인 실패: {e}")

    # ─── Check 8: 디스코드 연결 ───

    async def _check_discord(self) -> CheckResult:
        """디스코드 webhook 연결을 확인한다."""
        if not self._notifier:
            return CheckResult(name="discord", status="ok", message="알림 미설정")

        # 주기 제한 (4시간마다)
        interval = getattr(self._config, "discord_check_interval_sec", 14400)
        if not hasattr(self, "_last_discord_check"):
            self._last_discord_check = 0.0
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
```

- [ ] **Step 2: Write tests for checks 5-8**

Append to `tests/test_health_monitor.py`:

```python
def test_check_system_resources():
    """시스템 리소스 점검이 실행된다."""
    hm = HealthMonitor()
    result = hm._check_system_resources()
    assert result.name == "system_resources"
    assert result.status in ("ok", "warn", "critical")


def test_check_trading_metrics_no_journal():
    """저널 미설정 시 ok를 반환한다."""
    hm = HealthMonitor()
    result = hm._check_trading_metrics()
    assert result.status == "ok"


@pytest.mark.asyncio
async def test_check_reconciliation_not_configured():
    """정합성 미설정 시 ok를 반환한다."""
    hm = HealthMonitor()
    result = await hm._check_reconciliation()
    assert result.status == "ok"


@pytest.mark.asyncio
async def test_check_discord_not_configured():
    """알림 미설정 시 ok를 반환한다."""
    hm = HealthMonitor()
    result = await hm._check_discord()
    assert result.status == "ok"
```

- [ ] **Step 3: Run tests, commit**

Run: `python -m pytest tests/test_health_monitor.py -v`
Then: `python -m pytest tests/ -q --ignore=tests/test_bithumb_api.py`

```bash
git add app/health_monitor.py tests/test_health_monitor.py
git commit -m "feat: add health checks 5-8 (reconciliation, resources, trading, discord)"
```

---

### Task 5: Integrate HealthMonitor into main.py

**Files:**
- Modify: `app/main.py`

- [ ] **Step 1: Add HealthMonitor to TradingBot.__init__**

In `app/main.py`, add import at top:
```python
from app.health_monitor import HealthMonitor
```

In `__init__`, after BacktestDaemon initialization, add:

```python
# Phase: HealthMonitor
hm_cfg = self._config.health_monitor
self._health_monitor = HealthMonitor(
    interval_sec=hm_cfg.interval_sec,
    notifier=self._notifier,
    journal=self._journal,
    config=hm_cfg,
)
self._health_monitor._get_bithumb_client = lambda: self._bithumb_client
self._health_monitor._get_positions = lambda: {k: v.__dict__ if hasattr(v, '__dict__') else v for k, v in self._positions.items()}
self._health_monitor._get_exchange_balances = lambda: self._bithumb_client.get_balance()
self._health_monitor._get_last_candle_ts = lambda: max(
    (s.candles_15m[-1].timestamp if s.candles_15m else 0 for s in self._snapshots.values()),
    default=0,
)
```

- [ ] **Step 2: Start HealthMonitor as background task**

Find where BacktestDaemon task is created (look for `asyncio.create_task` and `_on_daemon_done`). Add similarly:

```python
if self._config.health_monitor.enabled:
    hm_task = asyncio.create_task(self._health_monitor.run_forever())
    hm_task.add_done_callback(lambda t: logger.error("HealthMonitor 종료: %s", t.exception()) if t.exception() else None)
```

- [ ] **Step 3: Add heartbeat call in main cycle**

At the END of `_run_cycle()` (or the method that runs every 15 minutes), add:

```python
self._health_monitor.record_heartbeat()
```

- [ ] **Step 4: Run full test suite**

Run: `python -m pytest tests/ -q --ignore=tests/test_bithumb_api.py`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add app/main.py
git commit -m "feat: integrate HealthMonitor into TradingBot lifecycle"
```

---

### Task 6: systemd Watchdog

**Files:**
- Modify: `scripts/bithumb-bot.service`
- Modify: `app/main.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Install sdnotify**

```bash
pip install sdnotify && pip freeze | grep sdnotify >> requirements.txt
```

- [ ] **Step 2: Update service file**

Read `scripts/bithumb-bot.service`, change `Type=simple` to `Type=notify` and add `WatchdogSec=300`.

- [ ] **Step 3: Add sd_notify to main loop**

In `app/main.py`, at the top:
```python
try:
    import sdnotify
    _sd_notifier = sdnotify.SystemdNotifier()
except ImportError:
    _sd_notifier = None
```

At the end of `_run_cycle()` (after `record_heartbeat`):
```python
if _sd_notifier:
    _sd_notifier.notify("WATCHDOG=1")
    _sd_notifier.notify(f"STATUS=Cycle ok, {len(self._positions)} positions")
```

- [ ] **Step 4: Run tests, commit, restart bot**

```bash
python -m pytest tests/ -q --ignore=tests/test_bithumb_api.py
git add scripts/bithumb-bot.service app/main.py requirements.txt
git commit -m "feat: add systemd watchdog with sd_notify"
sudo cp scripts/bithumb-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart bithumb-bot
```

---

## Phase 2: DarwinEngine Enhancement

### Context for This Phase

**What we're building:** Enhance the existing DarwinEngine with crossover operator, expanded fitness metrics (8→11), market-aware mutation, and diversity enforcement.

**Files to modify:**
- `strategy/darwin_engine.py` — Core changes
- `tests/test_darwin_engine.py` or similar — Tests

**Current DarwinEngine key structures:**
- `ShadowParams`: 7 params (mr_sl_mult, mr_tp_rr, dca_sl_pct, dca_tp_pct, cutoff, group, shadow_id)
- `MUTATION_RANGES`: dict with (delta, min, max) tuples
- `CompositeScore`: expectancy(30%), PF(20%), MDD(20%), Sharpe(20%), exec_quality(10%)
- `_mutate(params, variation)`: random delta per param within bounds
- `run_tournament(regime)`: top 70% survive, bottom 30% extinct, survivors breed via mutation
- No crossover operator exists

**Target enhancements (from CGA-Agent paper):**
1. Add `_crossover(parent_a, parent_b)` — single-point crossover between two ShadowParams
2. Expand CompositeScore to 8 metrics: add Sortino, Calmar, consecutive_loss_penalty
3. Market-aware mutation: wider range in CRISIS/WEAK_DOWN, narrower in STRONG_UP
4. Diversity enforcement: Euclidean distance check, inject random if diversity < threshold

---

### Task 7: Add Crossover Operator

- [ ] **Step 1: Read current darwin_engine.py** to find `_mutate` method location and `run_tournament` logic
- [ ] **Step 2: Write failing test**

```python
def test_crossover_produces_valid_params():
    """crossover는 두 부모의 파라미터 범위 내 자식을 생성한다."""
    from strategy.darwin_engine import DarwinEngine, ShadowParams
    engine = DarwinEngine(...)
    parent_a = ShadowParams(mr_sl_mult=1.5, mr_tp_rr=2.0, ...)
    parent_b = ShadowParams(mr_sl_mult=3.0, mr_tp_rr=1.0, ...)
    child = engine._crossover(parent_a, parent_b)
    # 자식의 각 파라미터는 부모 A 또는 B의 값 중 하나
    for field_name in ["mr_sl_mult", "mr_tp_rr", "dca_sl_pct", "dca_tp_pct", "cutoff"]:
        val = getattr(child, field_name)
        assert val in (getattr(parent_a, field_name), getattr(parent_b, field_name))
```

- [ ] **Step 3: Implement `_crossover` method** in DarwinEngine — uniform crossover (each param randomly from A or B)
- [ ] **Step 4: Update `run_tournament`** to use crossover for 50% of new population, mutation for other 50%
- [ ] **Step 5: Run tests, commit**

### Task 8: Expand Composite Score to 8 Metrics

- [ ] **Step 1: Write test** for new Sortino, Calmar, consecutive_loss metrics in CompositeScore
- [ ] **Step 2: Add `sortino_ratio`, `calmar_ratio`, `max_consecutive_loss` to ShadowPerformance**
- [ ] **Step 3: Update `_calc_composite_score`** weights: expectancy(25%), PF(15%), MDD(15%), Sharpe(15%), Sortino(10%), Calmar(10%), consec_loss_penalty(5%), exec_quality(5%)
- [ ] **Step 4: Run tests, commit**

### Task 9: Market-Aware Mutation + Diversity

- [ ] **Step 1: Write test** for mutation range varies by regime
- [ ] **Step 2: Modify `_mutate`** to accept regime parameter, scale variation: CRISIS/WEAK_DOWN → 1.5x, RANGE → 1.0x, STRONG_UP/WEAK_UP → 0.7x
- [ ] **Step 3: Add diversity metric** — calculate population centroid, enforce min Euclidean distance, inject random if diversity drops below 0.15
- [ ] **Step 4: Run tests, commit**

---

## Phase 3: Closed-Loop Feedback System

### Context for This Phase

**What we're building:** A feedback loop where trade outcomes are tagged by failure mode, patterns are detected, and LLM-generated hypotheses are auto-injected as new Darwin shadows.

**New files:**
- `strategy/trade_tagger.py` — Classify trade outcomes
- `strategy/feedback_loop.py` — Pattern aggregation + hypothesis → shadow injection

**Files to modify:**
- `strategy/review_engine.py` — Add self-reflection data to weekly review prompt
- `strategy/darwin_engine.py` — Add `inject_shadow(params, source)` method
- `app/journal.py` — Add `feedback` table usage

**Trade failure categories:**
- `regime_mismatch`: Entry regime ≠ exit regime (market shifted)
- `timing_error`: Correct direction but SL hit before TP (entry too early/late)
- `sizing_error`: Won but profit < fees (position too small)
- `signal_quality`: Wrong direction entirely
- `external`: Exchange error, API failure, minimum order amount

---

### Task 10: Trade Outcome Tagger

- [ ] **Step 1: Create `strategy/trade_tagger.py`** with `tag_trade(trade_dict, entry_regime, exit_regime) -> str` function
- [ ] **Step 2: Write tests** for each failure category classification
- [ ] **Step 3: Integrate** — call `tag_trade` when recording closed trades in main.py
- [ ] **Step 4: Commit**

### Task 11: Pattern Aggregator

- [ ] **Step 1: Add `get_failure_patterns(days=7)` to feedback_loop.py** — groups trades by tag + strategy + regime, returns top 3 patterns
- [ ] **Step 2: Write tests**
- [ ] **Step 3: Commit**

### Task 12: LLM Hypothesis Generator + Shadow Injection

- [ ] **Step 1: Add `generate_hypotheses(patterns, current_params)` to feedback_loop.py** — calls DeepSeek with failure patterns, returns param suggestions
- [ ] **Step 2: Add `inject_shadow(params, source="feedback")` to DarwinEngine** — inserts new shadow into population
- [ ] **Step 3: Wire into BacktestDaemon** weekly schedule (after review, before tournament)
- [ ] **Step 4: Write tests, commit**

---

## Phase 4: Self-Reflection Module

### Context for This Phase

**What we're building:** Post-trade analysis that accumulates experience across reviews, inspired by TradingGroup's self-reflection mechanism.

**New files:**
- `strategy/self_reflection.py` — ReflectionEntry dataclass + ReflectionStore

**Files to modify:**
- `strategy/review_engine.py` — Inject top reflections into DeepSeek prompt
- `app/journal.py` — Add `reflections` table

**Reflection entry:** After each trade closes, record: what signals triggered, what regime at entry/exit, did trade follow strategy intent, what could be improved.

---

### Task 13: Reflection Store

- [ ] **Step 1: Add `reflections` table** to journal.py (trade_id, strategy, regime_entry, regime_exit, tag, reflection_text, lesson, created_at)
- [ ] **Step 2: Create `strategy/self_reflection.py`** with `generate_reflection(trade, entry_regime, exit_regime, tag) -> str` — deterministic template-based (no LLM needed)
- [ ] **Step 3: Write tests, commit**

### Task 14: Weekly Synthesis + Context Injection

- [ ] **Step 1: Add `get_weekly_synthesis(days=7)` to self_reflection.py** — aggregates reflections, finds top 5 lessons by frequency
- [ ] **Step 2: Modify ReviewEngine.run_weekly_review()** — prepend synthesis to DeepSeek prompt as "past lessons learned"
- [ ] **Step 3: Write tests, commit**

---

## Phase 5: Auto-Fix Pipeline (cron + claude -p)

### Context for This Phase

**What we're building:** A cron-based pipeline that triggers Claude Code CLI to analyze issues and propose/apply fixes.

**New files:**
- `scripts/daily_report.sh` — cron job for daily Claude analysis
- `scripts/daily_report_prompt.txt` — Prompt template
- `scripts/auto_fix.sh` — Triggered by HealthMonitor on strategy degradation
- `scripts/send_discord_report.py` — Pipes Claude output to Discord webhook

**No bot code changes** — this phase is pure scripting/infrastructure.

---

### Task 15: Daily Report Pipeline

- [ ] **Step 1: Create `scripts/daily_report_prompt.txt`** — structured prompt telling Claude to read journal.db, health_checks, generate report
- [ ] **Step 2: Create `scripts/send_discord_report.py`** — reads stdin, sends to Discord webhook via requests
- [ ] **Step 3: Create `scripts/daily_report.sh`** — `claude -p` with `--allowedTools "Read,Grep,Glob,Bash(python3 *)"` piped to send script
- [ ] **Step 4: Test manually** — `bash scripts/daily_report.sh`
- [ ] **Step 5: Add crontab entry** — `0 0 * * * bythejune bash /home/bythejune/projects/bithumb-bot-v2/scripts/daily_report.sh`
- [ ] **Step 6: Commit**

### Task 16: Auto-Fix Pipeline

- [ ] **Step 1: Create `scripts/auto_fix.sh`** — accepts strategy name + reason, runs Opus analysis (read-only) → Sonnet implementation (Edit+pytest) → auto-apply or branch
- [ ] **Step 2: Add trigger mechanism** — HealthMonitor check_trading_metrics detects degradation → calls auto_fix.sh via subprocess
- [ ] **Step 3: Add frequency limiter** — `data/last_auto_fix_{strategy}.ts` file, 7-day minimum gap
- [ ] **Step 4: Test manually, commit**

---

## Execution Order & Dependencies

```
Phase 1 (Tasks 1-6): HealthMonitor + systemd     [독립, 최우선]
    ↓
Phase 2 (Tasks 7-9): DarwinEngine Enhancement    [독립, Phase 1과 병렬 가능]
    ↓
Phase 3 (Tasks 10-12): Closed-Loop Feedback       [Phase 2의 inject_shadow 필요]
    ↓
Phase 4 (Tasks 13-14): Self-Reflection            [Phase 3의 trade tagger 필요]
    ↓
Phase 5 (Tasks 15-16): Auto-Fix Pipeline          [Phase 1의 health_checks 테이블 필요]
```

**병렬 실행 가능:**
- Phase 1 + Phase 2 동시 시작
- Phase 5는 Phase 1 완료 후 바로 시작 가능 (Phase 2-4와 무관)

---

## Verification Checklist

After all phases complete:

- [ ] `python -m pytest tests/ -q --ignore=tests/test_bithumb_api.py` — All pass
- [ ] `sudo systemctl restart bithumb-bot && sleep 5 && systemctl is-active bithumb-bot` — active
- [ ] `sudo journalctl -u bithumb-bot -n 20` — HealthMonitor 시작 로그 확인
- [ ] Wait 15 min → Discord "system" 채널에 health ping 수신 확인
- [ ] `python -m pytest tests/test_health_monitor.py -v` — All pass
- [ ] `bash scripts/daily_report.sh` — 리포트 생성 + 디스코드 전송 확인
