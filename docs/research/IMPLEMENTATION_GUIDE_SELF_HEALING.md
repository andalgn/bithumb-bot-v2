# Implementation Guide: Self-Healing Trading Bot (3-Phase Rollout)

**Target:** Bithumb KRW bot with Claude CLI
**Timeline:** 3-4 weeks (minimal risk, incremental rollout)
**Success Metric:** MTTR (Mean Time To Recovery) < 10 minutes

---

## Phase 1: Foundation (Days 1-5)

### Goal
Establish observability: event logging + health monitoring backbone without changing trading logic.

### 1.1 Create Event Log Infrastructure

**File:** `app/event_store.py`

```python
import sqlite3
import json
import time
from typing import Optional, Dict, List, Any
from pathlib import Path
from dataclasses import dataclass, asdict

@dataclass
class Event:
    """Immutable event in system audit trail"""
    ts: float  # Unix timestamp
    event_type: str  # e.g., 'order_placed', 'error_occurred', 'health_check_failed'
    component: str  # e.g., 'order_manager', 'price_feed', 'watchdog'
    severity: str  # 'INFO', 'WARN', 'ERROR'
    data: Dict[str, Any]  # Event-specific data

class EventStore:
    """Thread-safe immutable event log (SQLite)"""

    def __init__(self, db_path: str = "data/events.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Create schema if needed"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    component TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    data TEXT NOT NULL,
                    inserted_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON events(ts)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_type ON events(event_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_severity ON events(severity)")
            conn.commit()

    def record(self, event: Event):
        """Append immutable event"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO events
                   (ts, event_type, component, severity, data)
                   VALUES (?, ?, ?, ?, ?)""",
                (event.ts, event.event_type, event.component,
                 event.severity, json.dumps(event.data))
            )
            conn.commit()

    def query_recent(self,
                    event_type: Optional[str] = None,
                    severity: Optional[str] = None,
                    minutes: int = 60) -> List[Event]:
        """Query recent events for analysis"""
        with sqlite3.connect(self.db_path) as conn:
            query = "SELECT ts, event_type, component, severity, data FROM events WHERE ts > ?"
            params = [time.time() - minutes * 60]

            if event_type:
                query += " AND event_type = ?"
                params.append(event_type)
            if severity:
                query += " AND severity = ?"
                params.append(severity)

            query += " ORDER BY ts DESC LIMIT 100"

            rows = conn.execute(query, params).fetchall()

        return [
            Event(
                ts=r[0],
                event_type=r[1],
                component=r[2],
                severity=r[3],
                data=json.loads(r[4])
            )
            for r in rows
        ]

    def get_errors_since(self, minutes: int = 120) -> List[Event]:
        """Convenience: fetch all errors in time window"""
        return self.query_recent(severity="ERROR", minutes=minutes)


# Global instance (use in app.main module)
event_store = EventStore()
```

**Usage in existing code:**

```python
# In app/execution/order_manager.py - on order rejection:
event_store.record(Event(
    ts=time.time(),
    event_type="order_rejected",
    component="order_manager",
    severity="WARN",
    data={
        'exchange_error_code': 10001,
        'exchange_error_msg': 'position idx not match position mode',
        'symbol': 'BTC',
        'side': 'buy',
        'qty': 0.5,
        'order_id': None
    }
))

# In app/risk/risk_gate.py - on halt:
event_store.record(Event(
    ts=time.time(),
    event_type="trading_halted",
    component="risk_gate",
    severity="ERROR",
    data={
        'reason': 'max_drawdown_exceeded',
        'current_mdd': 0.18,
        'threshold': 0.15
    }
))
```

---

### 1.2 Create Health Monitor (Background Task)

**File:** `app/health_monitor.py`

```python
import asyncio
import time
from typing import Callable, Dict, Any, Optional
from app.event_store import Event, event_store
from app.notify import notify_error

class HealthMonitor:
    """Decoupled watchdog-based health monitoring"""

    def __init__(self, check_interval_sec: int = 30):
        self.check_interval = check_interval_sec
        self.checks: Dict[str, Callable] = {}
        self.health_status: Dict[str, Dict[str, Any]] = {}
        self.running = False

    def register_check(self, name: str, check_fn: Callable):
        """Register async health check function

        Args:
            name: Check identifier
            check_fn: async() -> {'ok': bool, 'msg': str}
        """
        self.checks[name] = check_fn

    async def run(self):
        """Main monitoring loop (run as background task in main.py)"""
        self.running = True
        while self.running:
            try:
                for name, check_fn in self.checks.items():
                    try:
                        result = await asyncio.wait_for(check_fn(), timeout=10)
                        self.health_status[name] = {
                            'ok': result.get('ok', False),
                            'msg': result.get('msg', ''),
                            'ts': time.time()
                        }

                        if not result.get('ok'):
                            await self._on_check_failed(name, result)

                    except asyncio.TimeoutError:
                        await self._on_check_failed(name, {
                            'ok': False,
                            'msg': f"Check timeout (>10s)"
                        })
                    except Exception as e:
                        await self._on_check_failed(name, {
                            'ok': False,
                            'msg': f"Check crashed: {str(e)}"
                        })

            except Exception as e:
                print(f"HealthMonitor loop error: {e}")

            await asyncio.sleep(self.check_interval)

    async def _on_check_failed(self, name: str, result: Dict):
        """Handle health check failure"""
        # Record event
        event_store.record(Event(
            ts=time.time(),
            event_type="health_check_failed",
            component=name,
            severity="WARN",
            data={
                'check_name': name,
                'msg': result.get('msg', 'Unknown error')
            }
        ))

        # Notify operator
        await notify_error(
            f"⚠️ Health Check Failed: {name}\n"
            f"Detail: {result.get('msg', 'Unknown')}"
        )

    def stop(self):
        self.running = False

    def get_status(self) -> Dict[str, Any]:
        """Return current health status (for dashboard/status endpoint)"""
        return self.health_status
```

**Register checks in app/main.py:**

```python
# In Orchestrator.__init__:
self.health = HealthMonitor(check_interval_sec=30)

# Register checks
async def check_price_feed() -> Dict[str, Any]:
    """Verify price data is arriving"""
    from market.datafeed import datafeed
    elapsed = time.time() - getattr(datafeed, 'last_price_ts', 0)
    if elapsed > 120:  # 2 min timeout
        return {'ok': False, 'msg': f'Price stale: {elapsed:.0f}s'}
    return {'ok': True, 'msg': f'OK ({elapsed:.0f}s)'}

async def check_exchange_api() -> Dict[str, Any]:
    """Verify exchange connectivity"""
    from market.bithumb_api import bithumb_api
    try:
        result = await asyncio.wait_for(
            bithumb_api.fetch_tickers(['BTC'], limit=1),
            timeout=5
        )
        if result:
            return {'ok': True, 'msg': 'Connected'}
    except Exception as e:
        return {'ok': False, 'msg': f'API error: {str(e)[:50]}'}
    return {'ok': False, 'msg': 'No data'}

self.health.register_check('price_feed', check_price_feed)
self.health.register_check('exchange_api', check_exchange_api)

# In main loop startup:
asyncio.create_task(self.health.run())
```

---

### 1.3 Update Notify Module

**File:** `app/notify.py` (extend existing)

```python
async def notify_error(message: str, include_context: bool = True):
    """Notify operator of error + recent events"""

    if include_context:
        # Attach last 5 errors for context
        recent_errors = event_store.get_errors_since(minutes=30)[:5]
        context = "\n".join([
            f"[{int(e.ts % 3600)}s] {e.component}: {e.data.get('reason', e.data)}"
            for e in recent_errors
        ])
        message = f"{message}\n\nContext:\n{context}"

    # Send to Discord webhook
    await send_webhook(message)
```

---

### 1.4 Update Systemd Service

**File:** `scripts/bithumb-bot.service` (extend existing)

```ini
[Unit]
Description=Bithumb Auto Trading Bot v2
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=bythejune
WorkingDirectory=/home/bythejune/projects/bithumb-bot-v2
Environment="PROXY=http://127.0.0.1:1081"
ExecStart=/usr/bin/python3 /home/bythejune/projects/bithumb-bot-v2/run_bot.py
Restart=always
RestartSec=10

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=bithumb-bot

# Limits
TimeoutStartSec=30
TimeoutStopSec=10

[Install]
WantedBy=multi-user.target
```

---

### 1.5 Test & Deploy Phase 1

**Verification checklist:**

```bash
# 1. Unit tests
cd /home/bythejune/projects/bithumb-bot-v2
python -m pytest tests/test_event_store.py -v
python -m pytest tests/test_health_monitor.py -v

# 2. Start bot in test environment
export TRADING_MODE=PAPER
python run_bot.py

# 3. Check event log created
ls -la data/events.db
sqlite3 data/events.db "SELECT COUNT(*) FROM events"

# 4. Check health monitor running
# (Look for health checks in logs every 30 seconds)
grep "health_check_failed" data/bot.log

# 5. Trigger test error, verify event recorded
# (Manually send bad request to exchange)
sqlite3 data/events.db "SELECT * FROM events WHERE severity='ERROR' ORDER BY ts DESC LIMIT 3"
```

---

## Phase 2: Auto-Diagnosis (Days 6-10)

### Goal
Add LLM-powered error analysis (info-only, no action yet).

### 2.1 Create Claude Diagnosis Module

**File:** `app/claude_diagnosis.py`

```python
import subprocess
import asyncio
import json
from typing import Optional, Dict, Any
from app.event_store import Event, event_store
import logging

logger = logging.getLogger(__name__)

class ClaudeDiagnoser:
    """Use Claude CLI to diagnose trading errors"""

    def __init__(self, max_events: int = 30):
        self.max_events = max_events

    async def diagnose_error_pattern(self,
                                    event_type: str = "order_rejected",
                                    minutes: int = 120) -> Optional[str]:
        """Analyze recent error pattern with Claude

        Args:
            event_type: Which error pattern to analyze
            minutes: Time window to examine

        Returns:
            Claude's diagnosis as string, or None if failed
        """

        # Fetch recent errors
        errors = event_store.query_recent(
            event_type=event_type,
            severity="ERROR",
            minutes=minutes
        )

        if not errors:
            return None

        # Format for Claude (token-efficient)
        error_lines = []
        for e in errors[:self.max_events]:
            data_str = json.dumps(e.data, default=str)[:100]  # Truncate
            error_lines.append(f"[{int(e.ts) % 3600:04d}s] {e.component}: {data_str}")

        error_context = "\n".join(error_lines)

        prompt = f"""You are a trading bot error analyst. Analyze these recent error events and provide:

Error Type: {event_type}
Recent Errors (last {minutes} min):
{error_context}

Provide:
1. Root cause (1-2 sentences)
2. Immediate action: 'restart', 'reload_config', 'halt_trading', or 'investigate_further'
3. Prevention: 1-sentence code fix

Keep response under 150 words. Be technical and specific."""

        try:
            # Call Claude CLI with proxy
            result = await asyncio.wait_for(
                self._call_claude(prompt),
                timeout=30
            )
            return result

        except asyncio.TimeoutError:
            return "Claude diagnosis timed out (>30s)"
        except Exception as e:
            logger.error(f"Claude diagnosis failed: {e}")
            return None

    async def _call_claude(self, prompt: str) -> str:
        """Execute Claude CLI in subprocess"""
        # Note: claude-cli handles proxy via ~/.claude.json + PROXY env var
        return await asyncio.to_thread(
            subprocess.run,
            ["claude", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=30
        ).stdout

    async def diagnose_health_check_failures(self) -> Optional[str]:
        """Diagnose recent health check failures"""
        return await self.diagnose_error_pattern(
            event_type="health_check_failed",
            minutes=60
        )
```

---

### 2.2 Create Diagnosis Analyzer

**File:** `app/diagnosis_analyzer.py`

```python
import re
from typing import Optional, Dict

class DiagnosisAnalyzer:
    """Parse Claude's diagnosis to extract actionable recommendations"""

    @staticmethod
    def parse_diagnosis(diagnosis: str) -> Dict[str, str]:
        """Extract root_cause, action, prevention from Claude response

        Returns:
            {
                'root_cause': str,
                'action': 'restart' | 'reload_config' | 'halt_trading' | 'investigate',
                'prevention': str,
                'confidence': 'HIGH' | 'MEDIUM' | 'LOW',
                'raw': str  # Full response
            }
        """

        if not diagnosis:
            return {
                'root_cause': 'Unknown',
                'action': 'investigate',
                'prevention': 'Manual review required',
                'confidence': 'LOW',
                'raw': diagnosis or ''
            }

        # Extract key phrases
        root_cause = ""
        action = "investigate"
        prevention = ""

        # Look for numbered sections
        lines = diagnosis.split('\n')
        for i, line in enumerate(lines):
            if '1.' in line or 'cause' in line.lower():
                root_cause = line.replace('1.', '').strip()[:200]
            elif '2.' in line or 'action' in line.lower():
                action_text = line.replace('2.', '').strip().lower()
                # Classify action
                if 'restart' in action_text:
                    action = 'restart'
                elif 'reload' in action_text or 'config' in action_text:
                    action = 'reload_config'
                elif 'halt' in action_text or 'stop' in action_text:
                    action = 'halt_trading'
                else:
                    action = 'investigate'
            elif '3.' in line or 'prevention' in line.lower():
                prevention = line.replace('3.', '').strip()[:200]

        # Assess confidence based on language
        confidence = 'MEDIUM'
        if any(word in diagnosis.lower() for word in ['likely', 'clearly', 'definitely']):
            confidence = 'HIGH'
        elif any(word in diagnosis.lower() for word in ['may be', 'could', 'possibly']):
            confidence = 'LOW'

        return {
            'root_cause': root_cause or "Check logs for details",
            'action': action,
            'prevention': prevention or "See full diagnosis",
            'confidence': confidence,
            'raw': diagnosis
        }
```

---

### 2.3 Trigger Diagnosis on Error

**File:** `app/main.py` (add to Orchestrator)

```python
async def _on_errors_detected(self):
    """Check for error patterns and diagnose"""

    # Only diagnose if we've seen multiple errors
    recent_errors = event_store.get_errors_since(minutes=60)
    if len(recent_errors) < 3:
        return

    logger.info(f"Diagnosing {len(recent_errors)} recent errors...")

    diagnoser = ClaudeDiagnoser()
    diagnosis = await diagnoser.diagnose_error_pattern(
        event_type="order_rejected",
        minutes=60
    )

    if diagnosis:
        analysis = DiagnosisAnalyzer.parse_diagnosis(diagnosis)

        # Log analysis
        logger.info(f"Diagnosis: {analysis['root_cause']}")
        logger.info(f"Suggested action: {analysis['action']}")
        logger.info(f"Confidence: {analysis['confidence']}")

        # Notify operator (info only, no action yet)
        await notify_error(
            f"🔍 **Error Pattern Detected**\n"
            f"Root Cause: {analysis['root_cause']}\n"
            f"Suggested Action: {analysis['action']}\n"
            f"Confidence: {analysis['confidence']}\n\n"
            f"Full Analysis:\n{analysis['raw']}"
        )

        # Store diagnosis for Phase 3
        event_store.record(Event(
            ts=time.time(),
            event_type="diagnosis_generated",
            component="claude_diagnoser",
            severity="INFO",
            data={
                'root_cause': analysis['root_cause'],
                'action': analysis['action'],
                'confidence': analysis['confidence']
            }
        ))

# In main loop, after trading:
await self._on_errors_detected()
```

---

### 2.4 Test Phase 2

```bash
# Test diagnosis module
python -m pytest tests/test_claude_diagnosis.py -v

# Trigger test error, watch for diagnosis
# (Set PAPER mode, force API error)
export TRADING_MODE=PAPER
python run_bot.py

# Check diagnosis in event log
sqlite3 data/events.db "SELECT * FROM events WHERE event_type='diagnosis_generated' ORDER BY ts DESC LIMIT 1"

# Verify Discord notification (should have diagnosis info)
tail -50 data/bot.log | grep "Diagnosis:"
```

---

## Phase 3: Guarded Remediation (Days 11-20)

### Goal
Add bounded auto-remediation (Tier 1: restart service only).

### 3.1 Create ApprovalWorkflow Extension

**File:** `app/remediation_executor.py`

```python
import asyncio
from enum import Enum
from typing import Optional, Dict, Any
from app.event_store import Event, event_store
import subprocess
import signal

class RemediationAction(Enum):
    RESTART = "restart"  # Restart bot (graceful shutdown + restart)
    RELOAD_CONFIG = "reload_config"  # Reload config.yaml
    HALT_TRADING = "halt_trading"  # Set risk gate to halt
    INVESTIGATE = "investigate"  # Manual review needed

class RemediationExecutor:
    """Execute bounded remediation actions with validation"""

    def __init__(self, orchestrator):
        self.orchestrator = orchestrator
        self.last_restart_ts = 0
        self.restart_cooldown_sec = 300  # 5 min between restarts

    async def execute(self, action: RemediationAction, reason: str) -> bool:
        """Execute remediation action

        Args:
            action: What to do
            reason: Why (for logging)

        Returns:
            True if successful, False otherwise
        """

        # Validate action
        if not isinstance(action, RemediationAction):
            logger.error(f"Invalid remediation action: {action}")
            return False

        # Tier 1: Restart (bounded by cooldown)
        if action == RemediationAction.RESTART:
            return await self._restart_with_cooldown(reason)

        # Tier 2: Config reload (bounded by validation)
        elif action == RemediationAction.RELOAD_CONFIG:
            return await self._reload_config(reason)

        # Tier 3: Halt trading (approved by human first)
        elif action == RemediationAction.HALT_TRADING:
            return await self._halt_trading(reason)

        # Unknown: escalate
        else:
            await notify_error(f"Unknown remediation: {action}")
            return False

    async def _restart_with_cooldown(self, reason: str) -> bool:
        """Restart bot with cooldown protection"""
        import time

        now = time.time()
        if now - self.last_restart_ts < self.restart_cooldown_sec:
            logger.warn(f"Restart rejected (cooldown active): {reason}")
            event_store.record(Event(
                ts=now,
                event_type="remediation_rejected",
                component="executor",
                severity="WARN",
                data={'action': 'restart', 'reason': 'cooldown_active'}
            ))
            return False

        logger.info(f"Executing restart: {reason}")

        event_store.record(Event(
            ts=now,
            event_type="remediation_executed",
            component="executor",
            severity="INFO",
            data={'action': 'restart', 'reason': reason}
        ))

        # Graceful shutdown
        await self.orchestrator.shutdown()

        # Send SIGTERM to self (systemd will restart)
        import os
        os.kill(os.getpid(), signal.SIGTERM)

        return True

    async def _reload_config(self, reason: str) -> bool:
        """Reload config.yaml with validation"""
        try:
            from app.config import load_config, validate_config

            new_config = load_config()
            errors = validate_config(new_config)

            if errors:
                logger.error(f"Config validation failed: {errors}")
                event_store.record(Event(
                    ts=time.time(),
                    event_type="remediation_rejected",
                    component="executor",
                    severity="ERROR",
                    data={'action': 'reload_config', 'reason': str(errors)}
                ))
                return False

            # Config is valid, apply it
            self.orchestrator.config = new_config
            logger.info(f"Config reloaded: {reason}")

            event_store.record(Event(
                ts=time.time(),
                event_type="remediation_executed",
                component="executor",
                severity="INFO",
                data={'action': 'reload_config', 'reason': reason}
            ))
            return True

        except Exception as e:
            logger.error(f"Config reload failed: {e}")
            return False

    async def _halt_trading(self, reason: str) -> bool:
        """Halt trading (requires human approval in real usage)"""
        logger.warn(f"Halting trading: {reason}")

        # Set risk gate
        from app.risk.risk_gate import RiskGate
        risk_gate = RiskGate()
        await risk_gate.set_halted(True, reason=reason)

        event_store.record(Event(
            ts=time.time(),
            event_type="remediation_executed",
            component="executor",
            severity="WARN",
            data={'action': 'halt_trading', 'reason': reason}
        ))
        return True
```

---

### 3.2 Create GuardAgent Extension

**File:** `strategy/guard_agent.py` (extend existing)

```python
async def validate_remediation(action: str, reason: str) -> Dict[str, Any]:
    """Validate proposed remediation before execution

    Returns:
        {
            'approved': bool,
            'reason': str,
            'tier': 1 | 2 | 3,
            'requires_human': bool
        }
    """

    # Tier 3 (financial): Always requires human
    tier_3_keywords = ['place order', 'trade', 'buy', 'sell', 'position', 'execute']
    if any(kw in action.lower() for kw in tier_3_keywords):
        return {
            'approved': False,
            'reason': 'Financial action requires human approval',
            'tier': 3,
            'requires_human': True
        }

    # Tier 2 (config): Requires validation + bounds check
    if 'config' in action.lower() or 'reload' in action.lower():
        try:
            from app.config import load_config, validate_config

            test_config = load_config()
            errors = validate_config(test_config)

            if errors:
                return {
                    'approved': False,
                    'reason': f'Config invalid: {errors}',
                    'tier': 2,
                    'requires_human': True
                }

            return {
                'approved': True,
                'reason': 'Config validated successfully',
                'tier': 2,
                'requires_human': False
            }
        except Exception as e:
            return {
                'approved': False,
                'reason': f'Config validation crashed: {e}',
                'tier': 2,
                'requires_human': True
            }

    # Tier 1 (restart, info): Auto-approved with cooldown
    tier_1_keywords = ['restart', 'health', 'check', 'log', 'report', 'reset']
    if any(kw in action.lower() for kw in tier_1_keywords):
        return {
            'approved': True,
            'reason': 'Bounded operational action (5 min cooldown)',
            'tier': 1,
            'requires_human': False
        }

    # Unknown: escalate to human
    return {
        'approved': False,
        'reason': f'Cannot classify action: {action}',
        'tier': 0,
        'requires_human': True
    }
```

---

### 3.3 Connect Diagnosis → Remediation

**File:** `app/main.py` (update)

```python
async def _on_errors_detected(self):
    """Full diagnostic + remediation flow"""

    recent_errors = event_store.get_errors_since(minutes=60)
    if len(recent_errors) < 3:
        return

    logger.info(f"Error pattern detected: {len(recent_errors)} errors")

    # Step 1: Get diagnosis
    diagnoser = ClaudeDiagnoser()
    diagnosis = await diagnoser.diagnose_error_pattern(
        event_type="order_rejected",
        minutes=60
    )

    if not diagnosis:
        return

    # Step 2: Analyze diagnosis
    analysis = DiagnosisAnalyzer.parse_diagnosis(diagnosis)

    # Step 3: Validate action
    from strategy.guard_agent import validate_remediation
    validation = await validate_remediation(analysis['action'], analysis['root_cause'])

    if not validation['approved']:
        # Escalate to human
        await notify_error(
            f"🚨 **Action Requires Human Approval**\n"
            f"Reason: {validation['reason']}\n\n"
            f"Suggested Action: {analysis['action']}\n"
            f"Root Cause: {analysis['root_cause']}\n\n"
            f"Please review and approve with `/approve remediation`"
        )
        return

    # Step 4: Execute remediation (Tier 1 only)
    if validation['tier'] == 1:
        executor = RemediationExecutor(self)
        success = await executor.execute(
            RemediationAction(analysis['action']),
            reason=analysis['root_cause']
        )

        if success:
            await notify_error(f"✅ Remediation executed: {analysis['action']}")
        else:
            await notify_error(f"❌ Remediation failed: {analysis['action']}")
```

---

### 3.4 Test Phase 3

```bash
# Test remediation
python -m pytest tests/test_remediation_executor.py -v

# Test full flow in PAPER mode
export TRADING_MODE=PAPER
python run_bot.py

# Force error pattern (e.g., bad API calls)
# Watch for: diagnosis → validation → execution

# Check remediation in event log
sqlite3 data/events.db "SELECT * FROM events WHERE event_type='remediation_executed' ORDER BY ts DESC LIMIT 5"
```

---

## Monitoring & Metrics

### Dashboard Queries

```python
# In app/main.py, add status endpoint:

async def get_bot_status() -> Dict[str, Any]:
    """Health status + diagnostics"""
    recent_errors = event_store.get_errors_since(minutes=120)
    diagnoses = event_store.query_recent(
        event_type="diagnosis_generated",
        minutes=120
    )
    remediations = event_store.query_recent(
        event_type="remediation_executed",
        minutes=120
    )

    return {
        'health': self.health.get_status(),
        'error_count_2h': len(recent_errors),
        'diagnoses_2h': len(diagnoses),
        'remediations_2h': len(remediations),
        'uptime_sec': time.time() - self.start_ts,
        'position_count': len(self.cycle_data.positions),
        'last_error': recent_errors[0].data if recent_errors else None
    }
```

---

## Rollback Plan

If Phase N introduces issues:

```bash
# Stop bot immediately
sudo systemctl stop bithumb-bot

# Revert code
cd /home/bythejune/projects/bithumb-bot-v2
git checkout HEAD~1 app/main.py  # Revert one commit

# Restart
sudo systemctl start bithumb-bot

# Review what broke
git diff HEAD~1..HEAD app/main.py
```

---

## Success Criteria

- [ ] Event log records all errors in <100ms
- [ ] Health checks run every 30s with <500ms latency
- [ ] Claude diagnosis completes in <30s
- [ ] No trades made during remediation window
- [ ] All remediations logged + reversible
- [ ] MTTR (Mean Time To Recovery) < 10 minutes

---

## Files Checklist

Create these files:

- [ ] `app/event_store.py` — EventStore + Event classes
- [ ] `app/health_monitor.py` — HealthMonitor watchdog
- [ ] `app/claude_diagnosis.py` — Claude CLI wrapper
- [ ] `app/diagnosis_analyzer.py` — Parse Claude output
- [ ] `app/remediation_executor.py` — Execute bounded fixes
- [ ] `tests/test_event_store.py` — Unit tests
- [ ] `tests/test_health_monitor.py` — Unit tests
- [ ] `tests/test_remediation_executor.py` — Unit tests
- [ ] Update `app/notify.py` — Add context to errors
- [ ] Update `strategy/guard_agent.py` — Add validation
- [ ] Update `app/main.py` — Integrate all 3 phases

---

## Timeline

- **Days 1-5:** Phase 1 (foundation)
- **Days 6-10:** Phase 2 (auto-diagnosis)
- **Days 11-20:** Phase 3 (guarded remediation)
- **Days 21-28:** Testing + hardening in PAPER mode
- **Day 29+:** Consider Tier 2 (config reload) based on stability

**DO NOT rush to Tier 3 (trading decisions).** Event sourcing alone warrants 1-2 months PAPER testing.

---

**Version:** 1.0
**Last Updated:** March 31, 2026
