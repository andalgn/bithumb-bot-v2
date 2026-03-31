# Phase 1 Instrumentation Guide: EventStore Integration

**Objective:** Instrument existing code to log system events to EventStore.
**Status:** EventStore created (`app/event_store.py`). Now add logging calls.
**Timeline:** 2-3 days
**Risk:** NONE (read-only, no behavior changes)

---

## Quick Start

### Import EventStore
```python
from app.event_store import Event, get_event_store
import time

event_store = get_event_store()
```

### Record an Event
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
        'exchange_order_id': 'ABC123'
    }
))
```

---

## Instrumentation Checklist

### 1. OrderManager (execution/order_manager.py)

#### Location 1.1: On successful order placement
```python
# In OrderManager.place_order() after successful API call

event_store.record(Event(
    ts=time.time(),
    event_type="order_placed",
    component="order_manager",
    severity="INFO",
    data={
        'symbol': order.symbol,
        'side': order.side.value,
        'qty': order.qty,
        'limit_price': order.limit_price,
        'exchange_order_id': response['order_id'],
        'ticket_id': ticket_id
    }
))
```

#### Location 1.2: On order rejection
```python
# In OrderManager.place_order() in exception handler

event_store.record(Event(
    ts=time.time(),
    event_type="order_rejected",
    component="order_manager",
    severity="ERROR",
    data={
        'symbol': order.symbol,
        'side': order.side.value,
        'qty': order.qty,
        'error_code': response.get('error_code'),
        'error_msg': response.get('error_msg'),
        'reason': str(e)[:200]
    }
))
```

#### Location 1.3: On order cancellation
```python
# In OrderManager.cancel_order()

event_store.record(Event(
    ts=time.time(),
    event_type="order_cancelled",
    component="order_manager",
    severity="INFO",
    data={
        'symbol': order.symbol,
        'exchange_order_id': order.exchange_order_id,
        'reason': 'manual_cancel' or 'timeout' or 'risk_gate'
    }
))
```

---

### 2. RiskGate (risk/risk_gate.py)

#### Location 2.1: Trading halted (circuit breaker triggered)
```python
# In RiskGate.check() or evaluate() when trading halts

event_store.record(Event(
    ts=time.time(),
    event_type="trading_halted",
    component="risk_gate",
    severity="CRITICAL",
    data={
        'reason': 'max_drawdown_exceeded',  # or 'daily_loss_limit', 'rejection_rate'
        'current_value': 0.18,  # actual MDD
        'threshold': 0.15,
        'detail': 'MDD exceeded 15% threshold'
    }
))
```

#### Location 2.2: Risk gate resume
```python
# When trading resumes after being halted

event_store.record(Event(
    ts=time.time(),
    event_type="trading_resumed",
    component="risk_gate",
    severity="WARN",
    data={
        'from_state': 'halted',
        'to_state': 'active',
        'reason': 'manual_reset' or 'threshold_recover'
    }
))
```

---

### 3. HealthMonitor (app/health_monitor.py)

#### Location 3.1: On critical health check failure
```python
# In HealthMonitor._run_all_checks() or on critical result

event_store.record(Event(
    ts=time.time(),
    event_type="health_check_failed",
    component=result.name,  # "api", "data_freshness", "reconciliation", etc.
    severity="CRITICAL" if result.status == "critical" else "WARN",
    data={
        'check_name': result.name,
        'message': result.message,
        'value': result.value
    }
))
```

---

### 4. DataFeed (market/datafeed.py)

#### Location 4.1: API error during data fetch
```python
# In DataFeed._fetch_candles() on exception

event_store.record(Event(
    ts=time.time(),
    event_type="datafeed_error",
    component="datafeed",
    severity="ERROR",
    data={
        'symbols': symbols,
        'timeframe': timeframe,
        'error_type': type(e).__name__,
        'error_msg': str(e)[:200],
        'retry_attempt': retry_count
    }
))
```

#### Location 4.2: Silent data failure (no new candles)
```python
# In DataFeed when candle age exceeds threshold

event_store.record(Event(
    ts=time.time(),
    event_type="data_stale",
    component="datafeed",
    severity="WARN",
    data={
        'last_candle_age_sec': elapsed_seconds,
        'threshold_sec': 120,
        'symbols_affected': list_of_symbols
    }
))
```

---

### 5. BithumbClient (market/bithumb_api.py)

#### Location 5.1: API call timeout
```python
# In BithumbClient API methods on timeout

event_store.record(Event(
    ts=time.time(),
    event_type="api_timeout",
    component="bithumb_api",
    severity="WARN",
    data={
        'endpoint': method_name,
        'timeout_sec': timeout_configured,
        'attempt': retry_count
    }
))
```

#### Location 5.2: API HTTP error (429, 500, etc.)
```python
# In BithumbClient on HTTP error response

event_store.record(Event(
    ts=time.time(),
    event_type="api_error",
    component="bithumb_api",
    severity="ERROR",
    data={
        'endpoint': method_name,
        'http_status': response.status,
        'error_code': response_json.get('code'),
        'error_msg': response_json.get('message')[:200]
    }
))
```

---

### 6. ApprovalWorkflow (app/approval_workflow.py)

#### Location 6.1: Config change proposed
```python
# In ApprovalWorkflow.propose_change()

event_store.record(Event(
    ts=time.time(),
    event_type="config_change_proposed",
    component="approval_workflow",
    severity="INFO",
    data={
        'param_name': param_name,
        'old_value': old_value,
        'new_value': new_value,
        'reason': reason,
        'approval_state': 'pending'
    }
))
```

#### Location 6.2: Config change approved/rejected
```python
# In ApprovalWorkflow on approval decision

event_store.record(Event(
    ts=time.time(),
    event_type="config_change_approved" if approved else "config_change_rejected",
    component="approval_workflow",
    severity="WARN",
    data={
        'param_name': param_name,
        'decision': 'approved' or 'rejected',
        'reason': approval_reason
    }
))
```

---

### 7. PoolManager (strategy/pool_manager.py)

#### Location 7.1: Pool allocation failure
```python
# In PoolManager.allocate() when allocation fails

event_store.record(Event(
    ts=time.time(),
    event_type="pool_allocation_failed",
    component="pool_manager",
    severity="WARN",
    data={
        'pool': pool_name,
        'requested_size': requested_krw,
        'available_size': available_krw,
        'reason': 'insufficient_capital' or 'tier_limit'
    }
))
```

---

### 8. Strategy/GuardAgent (strategy/guard_agent.py)

#### Location 8.1: Validation failure
```python
# In GuardAgent.validate_*() when validation fails

event_store.record(Event(
    ts=time.time(),
    event_type="validation_failed",
    component="guard_agent",
    severity="WARN",
    data={
        'validation_type': 'remediation' or 'config' or 'order',
        'entity': entity_being_validated,
        'reason': validation_failure_reason[:200]
    }
))
```

---

## Testing Instrumentation

### Manual Test: Generate Events
```bash
cd /home/bythejune/projects/bithumb-bot-v2

# Python script to manually record an event
python3 << 'EOF'
from app.event_store import Event, get_event_store
import time

event_store = get_event_store()

# Test event
event_store.record(Event(
    ts=time.time(),
    event_type="test_order_placed",
    component="test",
    severity="INFO",
    data={'test': 'value', 'amount': 100000}
))

# Verify it was recorded
recent = event_store.query_recent(event_type="test_order_placed")
print(f"✓ Recorded {len(recent)} test event(s)")
for e in recent:
    print(f"  - {e.event_type} ({e.severity}): {e.data}")
EOF
```

### Verify in Database
```bash
# Query events directly from DB
sqlite3 data/journal.db << 'EOF'
SELECT ts, event_type, severity, data
FROM system_events
ORDER BY ts DESC
LIMIT 10;
EOF
```

### Integration Test
```bash
# Run unit tests
pytest tests/test_event_store.py -v

# Or create a test file
cat > tests/test_event_store.py << 'EOF'
import time
from app.event_store import Event, EventStore


def test_event_store_record_and_query(tmp_path):
    """EventStore에 이벤트를 기록하고 조회할 수 있는지 확인."""
    store = EventStore(str(tmp_path / "test.db"))

    # Record event
    event = Event(
        ts=time.time(),
        event_type="test_event",
        component="test",
        severity="INFO",
        data={"key": "value"}
    )
    store.record(event)

    # Query and verify
    results = store.query_recent(event_type="test_event")
    assert len(results) > 0
    assert results[0].event_type == "test_event"
    assert results[0].data["key"] == "value"

    store.close()
EOF

pytest tests/test_event_store.py::test_event_store_record_and_query -v
```

---

## Deployment Checklist

### Code Changes
- [ ] Import `get_event_store()` in all 8 components
- [ ] Add event logging in all 8 locations above
- [ ] Verify imports work (no circular dependencies)
- [ ] Run `pytest tests/test_event_store.py -v`

### Integration Testing (in PAPER mode)
- [ ] Run bot for 1 cycle
- [ ] Trigger at least one order placement
- [ ] Verify event appears in `data/journal.db`
- [ ] Query events with Discord bot status command
- [ ] Verify HealthMonitor logs health checks

### Monitoring
- [ ] Event table size (should be <10MB for 7 days)
- [ ] Query performance (index usage)
- [ ] Cleanup task running daily

### Documentation
- [ ] Update CLAUDE.md if paths changed
- [ ] Document event types in README or wiki
- [ ] Add EventStore to architecture diagram

---

## Event Types Reference

| Event Type | Severity | Component | Purpose |
|------------|----------|-----------|---------|
| order_placed | INFO | order_manager | Track successful orders |
| order_rejected | ERROR | order_manager | Diagnose placement failures |
| order_cancelled | INFO | order_manager | Track cancellations |
| trading_halted | CRITICAL | risk_gate | Circuit breaker trigger |
| trading_resumed | WARN | risk_gate | Recovery from halt |
| health_check_failed | CRITICAL/WARN | health_monitor | System health issues |
| datafeed_error | ERROR | datafeed | Data fetch failures |
| data_stale | WARN | datafeed | Silent data failure detection |
| api_timeout | WARN | bithumb_api | API latency issues |
| api_error | ERROR | bithumb_api | HTTP errors, auth failures |
| config_change_proposed | INFO | approval_workflow | Parameter change requests |
| config_change_approved | WARN | approval_workflow | Approved changes |
| pool_allocation_failed | WARN | pool_manager | Capacity issues |
| validation_failed | WARN | guard_agent | Validation failures |

---

## Common Issues & Fixes

### Issue: Circular import when importing get_event_store()
**Fix:** Import inside function if needed:
```python
def place_order(...):
    from app.event_store import get_event_store
    event_store = get_event_store()
    event_store.record(...)
```

### Issue: Events not being recorded to DB
**Fix:** Verify `data/` directory exists and is writable:
```bash
mkdir -p data/
ls -la data/journal.db
```

### Issue: Event log grows too large
**Fix:** Run cleanup task daily:
```python
# In main.py startup or scheduler
async def cleanup_events():
    event_store = get_event_store()
    deleted = event_store.cleanup_old_events(days=7)
    logger.info(f"Cleaned up {deleted} old events")

# Schedule as background task
asyncio.create_task(cleanup_events())
```

---

## Next Steps (When Complete)

Once Phase 1 instrumentation is complete:

1. **Test 24h in PAPER mode** with event logging active
2. **Move to Phase 2:** Claude CLI diagnosis integration
3. **Then Phase 3:** Remediation executor with tiered actions

Phase 1 is the foundation—everything else depends on accurate event logging.

---

**Status:** Ready for implementation
**Estimated Time:** 2-3 days (one integration per day + testing)
