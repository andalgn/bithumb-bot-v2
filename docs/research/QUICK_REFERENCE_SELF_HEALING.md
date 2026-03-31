# Quick Reference: Self-Healing Trading Bot Patterns

**Use this as a cheat sheet while implementing.**

---

## Architecture Pattern

```
┌──────────────────────────────────────┐
│  Trading Bot Main Loop (15-min)      │
└────────────────┬─────────────────────┘
                 │
    ┌────────────┼────────────┐
    │            │            │
    ▼            ▼            ▼
┌────────┐  ┌────────┐  ┌──────────┐
│Watchdog│  │EventLog│  │Anomaly   │
│Monitor │  │(SQLite)│  │Detector  │
└────┬───┘  └────┬───┘  └────┬─────┘
     │           │           │
     └───────────┼───────────┘
                 │
         ┌───────▼────────┐
         │ Claude Diagnose│
         └───────┬────────┘
                 │
         ┌───────▼────────┐
         │ GuardAgent     │
         │ Validate       │
         └───────┬────────┘
                 │
         ┌───────▼────────┐
         │ Human Approval │
         │ (Discord)      │
         └───────┬────────┘
                 │
         ┌───────▼────────┐
         │ Remediate      │
         │ (Tier 1 only)  │
         └────────────────┘
```

---

## Event Types to Log

### Order Execution
```python
event_store.record(Event(
    ts=time.time(),
    event_type="order_placed",
    component="order_manager",
    severity="INFO",
    data={
        'symbol': 'BTC',
        'side': 'buy',
        'qty': 0.5,
        'price': 50000,
        'exchange_order_id': 'ABC123'
    }
))
```

### Error Events
```python
event_store.record(Event(
    ts=time.time(),
    event_type="order_rejected",
    component="order_manager",
    severity="ERROR",
    data={
        'symbol': 'BTC',
        'side': 'buy',
        'error_code': 10001,
        'error_msg': 'position idx not match position mode'
    }
))
```

### Health Check
```python
event_store.record(Event(
    ts=time.time(),
    event_type="health_check_failed",
    component="price_feed",
    severity="WARN",
    data={
        'check_name': 'price_freshness',
        'msg': 'Last price 150s ago (timeout: 120s)'
    }
))
```

### Risk Events
```python
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

## Health Check Registration

```python
# In Orchestrator.__init__:
self.health = HealthMonitor(check_interval_sec=30)

async def check_price_feed() -> Dict[str, Any]:
    elapsed = time.time() - datafeed.last_price_ts
    return {
        'ok': elapsed < 120,
        'msg': f'Last price {elapsed:.0f}s ago'
    }

async def check_exchange_api() -> Dict[str, Any]:
    try:
        result = await asyncio.wait_for(
            bithumb_api.fetch_tickers(['BTC'], limit=1),
            timeout=5
        )
        return {'ok': bool(result), 'msg': 'Connected'}
    except Exception as e:
        return {'ok': False, 'msg': str(e)[:50]}

self.health.register_check('price_feed', check_price_feed)
self.health.register_check('exchange_api', check_exchange_api)

# In main loop startup:
asyncio.create_task(self.health.run())
```

---

## Claude Diagnosis Pattern

**Good prompt:**
```
Error Code: 10001
Exchange: Bybit
Context: Order fails on short entry in Hedge mode
Hypothesis: positionIdx mismatch (bot sends 0, Hedge uses 1)
Requirements:
1. Detect position mode from exchange API on startup
2. Store in Config enum (ONE_WAY | HEDGE)
3. Derive correct positionIdx from (side + mode) when creating orders
4. Add retry logic with mode re-detection for ErrCode 10001

Expected fix: What code changes implement this?
```

**Bad prompt:**
```
Why aren't my orders working?
```

---

## Error Analysis Levels

### Level 1: Single Error (Likely OK)
```python
if len(recent_errors) < 3:
    return  # Don't diagnose yet
```

### Level 2: Error Pattern (Diagnose)
```python
if 3 <= len(recent_errors) < 10:
    diagnosis = await diagnoser.diagnose_error_pattern()
    await notify_error(f"⚠️ Pattern detected: {diagnosis}")
```

### Level 3: Error Cascade (Halt)
```python
if len(recent_errors) >= 10:
    await halt_trading("Error cascade detected")
    await notify_error("🚨 HALTED: Too many errors")
```

---

## Guardrail Tiers

| Tier | Example | Auto-Approve? | Human Required? |
|------|---------|---------------|-----------------|
| **1** | Restart, health check, logs | Yes (cooldown) | No |
| **2** | Config reload, reset cache | Yes (validated) | No |
| **3** | Place order, change strategy | Never | Yes |

---

## Remediation Actions

### Restart (Tier 1)
```python
await executor.execute(RemediationAction.RESTART, reason="Health check recovered; restart to clear")
```

### Reload Config (Tier 2)
```python
await executor.execute(RemediationAction.RELOAD_CONFIG, reason="Config updated; reloading")
```

### Halt Trading (Tier 3)
```python
await executor.execute(RemediationAction.HALT_TRADING, reason="Order rejection rate >50%")
# Requires human approval in real usage
```

---

## Query Event Log

```python
# Recent errors
errors = event_store.get_errors_since(minutes=120)

# Specific type
rejections = event_store.query_recent(
    event_type="order_rejected",
    minutes=60
)

# All events in window
all_events = event_store.query_recent(minutes=30)
```

---

## Circuit Breaker Examples

```python
# Max drawdown
if mdd > config.max_drawdown_pct:
    await halt_trading(f"MDD {mdd:.1%} > {config.max_drawdown_pct:.1%}")

# Daily loss
if daily_loss > portfolio.equity * 0.02:  # 2% max
    await halt_trading("Daily loss limit hit")

# Order rejection rate
rejection_rate = rejections / (rejections + accepted)
if rejection_rate > 0.30:  # 30% reject rate
    await halt_trading("Order rejection rate too high")

# Position concentration
max_pos = max(pos.value for pos in positions)
if max_pos > portfolio.equity * 0.10:  # >10% in one coin
    await halt_trading("Position too concentrated")
```

---

## Discord Notification Format

```python
await notify_error(
    f"🔍 **Diagnosis Generated**\n"
    f"Root Cause: {analysis['root_cause']}\n"
    f"Suggested Action: {analysis['action']}\n"
    f"Confidence: {analysis['confidence']}\n\n"
    f"Full Analysis:\n{analysis['raw']}"
)

await notify_error(
    f"✅ **Remediation Executed**\n"
    f"Action: {action}\n"
    f"Reason: {reason}\n"
    f"Bot will restart in 10 seconds..."
)

await notify_error(
    f"🚨 **Manual Review Required**\n"
    f"Action: {action}\n"
    f"Reason: {validation['reason']}\n\n"
    f"Please approve with `/approve remediation`"
)
```

---

## Testing

### Unit Tests
```python
# tests/test_event_store.py
def test_record_and_query():
    event = Event(ts=time.time(), event_type="test", component="test",
                  severity="INFO", data={'key': 'value'})
    event_store.record(event)
    results = event_store.query_recent(event_type="test")
    assert len(results) > 0

# tests/test_diagnosis_analyzer.py
def test_parse_diagnosis():
    diagnosis = "1. API timeout. 2. restart the service. 3. add timeout=10"
    parsed = DiagnosisAnalyzer.parse_diagnosis(diagnosis)
    assert parsed['action'] == 'restart'
    assert parsed['root_cause'] != ""
```

### Manual Testing
```bash
# Generate event
python -c "
from app.event_store import Event, event_store
import time
event = Event(
    ts=time.time(),
    event_type='test_error',
    component='test',
    severity='ERROR',
    data={'test': 'value'}
)
event_store.record(event)
"

# Check event logged
sqlite3 data/events.db "SELECT * FROM events WHERE event_type='test_error' ORDER BY ts DESC LIMIT 1"

# Run health check
python -c "
import asyncio
from app.main import Orchestrator
o = Orchestrator()
status = asyncio.run(o.get_bot_status())
print(status)
"
```

---

## Common Issues & Fixes

### Issue: Event log grows too large
**Fix:** Add cleanup task
```python
async def cleanup_old_events(days: int = 7):
    """Remove events older than N days"""
    while True:
        with sqlite3.connect(event_store.db_path) as conn:
            conn.execute(
                "DELETE FROM events WHERE ts < ?",
                (time.time() - days * 86400,)
            )
            conn.commit()
        await asyncio.sleep(86400)  # Once per day

asyncio.create_task(cleanup_old_events(days=7))
```

### Issue: Claude CLI timeout
**Fix:** Increase timeout or use shorter prompt
```python
# Increase timeout
result = await asyncio.wait_for(
    self._call_claude(prompt),
    timeout=60  # Was 30
)

# Or: Truncate events
error_context = "\n".join(error_lines[:10])  # Only last 10
```

### Issue: Health check false positives
**Fix:** Add hysteresis
```python
class HealthMonitor:
    def __init__(self):
        self.failure_count = {}  # Track consecutive failures
        self.failure_threshold = 3  # Require 3 consecutive failures

    async def _on_check_failed(self, name: str, result: Dict):
        self.failure_count[name] = self.failure_count.get(name, 0) + 1
        if self.failure_count[name] >= self.failure_threshold:
            await self._on_check_failed(name, result)
        else:
            logger.debug(f"{name} failed {self.failure_count[name]}/3")

    async def _on_check_succeeded(self, name: str):
        self.failure_count[name] = 0
```

---

## Deployment Checklist

- [ ] Event log schema created + indexed
- [ ] Health monitor running + all checks registered
- [ ] Claude CLI available (`which claude`)
- [ ] Diagnosis analyzer tested (unit tests pass)
- [ ] GuardAgent validation rules reviewed
- [ ] Remediation executor tested with cooldown
- [ ] Discord notification format approved
- [ ] Event cleanup task scheduled
- [ ] Systemd service updated with logging
- [ ] PAPER mode tests completed (24 hours)
- [ ] Circuit breakers all active
- [ ] Rollback procedure documented

---

## Key Metrics

Track these in Discord daily:

```
24h Status:
- Errors: 3 (down from 12)
- Diagnoses: 1 (order_rejected pattern)
- Remediations: 0 (awaiting approval)
- MTTR: 8 min (target: <10)
- Uptime: 99.2%
- Last restart: 6h ago
```

---

**Bookmark these files for reference:**

1. `research_self_healing_trading_bots.md` — Full theory + case studies
2. `IMPLEMENTATION_GUIDE_SELF_HEALING.md` — Step-by-step code
3. `QUICK_REFERENCE_SELF_HEALING.md` — This file (patterns + snippets)

---

**Version:** 1.0
**Last Updated:** March 31, 2026
