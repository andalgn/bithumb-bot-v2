# Self-Healing Trading Bot Implementation Status

**Date:** March 31, 2026
**Status:** READY TO IMPLEMENT (Foundation Complete)

---

## Current State Analysis

### What's Already in Place ✅

The bithumb-bot-v2 codebase already has **substantial infrastructure** for self-healing:

#### 1. HealthMonitor (app/health_monitor.py) - COMPLETE
- **9 concurrent health checks running every 15 minutes:**
  1. Heartbeat detection (main loop responsiveness)
  2. Event loop lag measurement (asyncio health)
  3. API connectivity & latency
  4. Data freshness (prevents silent failures)
  5. Position reconciliation (bot vs exchange balance)
  6. System resources (CPU, memory, disk, WAL file)
  7. Trading metrics (consecutive losses, daily drawdown)
  8. Discord webhook connectivity
  9. Pipeline conversion rates (signal → sizing → execution)

- **Alert management:**
  - Critical/warning severity levels
  - Cooldown suppression (prevents alert spam)
  - Correlation-based suppression (avoid cascading alerts)
  - Integration with Journal for historical tracking

- **Auto-fix triggering:**
  - Monitors win rate per strategy
  - Triggers auto-fix script when performance drops below 30%
  - 7-day cooldown per strategy

#### 2. Journal (app/journal.py) - COMPREHENSIVE
- **Multiple event tables with WAL mode:**
  - `trades` (21-field trade records)
  - `signals` (signal generation tracking)
  - `executions` (order execution log)
  - `risk_events` (risk gate triggers)
  - `shadow_trades` (paper trading)
  - `health_checks` (historical health scores)
  - `pipeline_events` (signal-to-execution pipeline tracing)
  - `reflections` (post-trade analysis)

- **Methods for querying:**
  - `record_health_check()` — logs health check results
  - `record_pipeline_event()` — traces signal flow
  - `record_risk_event()` — logs risk triggers
  - `get_pipeline_stats()` — conversion rate analysis
  - Automatic cleanup (90-day retention for events, 1-year for trades)

#### 3. State Management
- `StateStore` (app/state_store.py) — SQLite key-value store for bot state
- `ExperimentStore` (strategy/experiment_store.py) — logs parameter changes
- `MarketStore` (market/market_store.py) — persists market data

#### 4. Risk & Execution
- `RiskGate` (risk/risk_gate.py) — circuit breaker implementation
- `OrderManager` (execution/order_manager.py) — FSM-based order lifecycle
- `PartialExitManager` (execution/partial_exit.py) — exit logic
- `Reconciler` (execution/reconciler.py) — exchange balance verification

#### 5. Strategy Evolution
- `EvolutionOrchestrator` (strategy/evolution_orchestrator.py) — 7-stage self-learning loop
- `GuardAgent` (strategy/guard_agent.py) — validates strategy changes
- `ReviewEngine` (strategy/review_engine.py) — daily/weekly/monthly performance review

---

## What Needs to Be Added

### Phase 1: EventStore (Days 1-3)
**Priority: HIGH | Effort: MEDIUM | Risk: NONE**

#### Missing: Unified event audit trail
- Journal focuses on trades/signals/executions
- HealthMonitor generates alerts but needs structured logging
- Need centralized EventStore for ALL system events

**Create:** `app/event_store.py`
```python
class Event:
    """Immutable system event."""
    ts: float           # Timestamp
    event_type: str     # "order_placed", "health_check_failed", "api_error", etc.
    component: str      # "order_manager", "price_feed", "risk_gate", etc.
    severity: str       # "INFO", "WARN", "ERROR", "CRITICAL"
    data: dict          # Context-specific payload

class EventStore:
    """Immutable audit trail using SQLite + WAL."""
    def record(event: Event) -> None
    def query_recent(event_type: str = "", minutes: int = 60) -> List[Event]
    def get_errors_since(minutes: int) -> List[Event]
    def cleanup_old_events(days: int = 7) -> int
```

**Integration points:**
- OrderManager.place_order() → record("order_placed")
- OrderManager on rejection → record("order_rejected")
- HealthMonitor._on_critical() → record("health_check_failed")
- RiskGate.check() → record("trading_halted") when triggered
- ApprovalWorkflow.suggest_change() → record("config_change_proposed")

**Why this matters:**
- Provides immutable audit trail (regulatory requirement for Korean fintech)
- Enables crash recovery by replaying events
- Foundation for Claude diagnosis (structured error context)

---

### Phase 2: Claude CLI Diagnosis (Days 4-8)
**Priority: HIGH | Effort: MEDIUM | Risk: LOW (info-only)**

#### Missing: LLM-powered root cause analysis
- Currently: alerts only
- Needed: automatic diagnosis of *why* errors happen

**Create:** `app/llm_client.py` + `app/diagnosis_analyzer.py`

```python
class ClaudeDiagnoser:
    """Claude CLI wrapper for error diagnosis."""
    async def diagnose_error_pattern(
        self,
        recent_errors: List[Event],
        context: dict  # bot state, positions, etc.
    ) -> DiagnosisResult:
        """Return root cause + recommended action."""
        # 1. Format error context into structured prompt
        # 2. Call Claude via subprocess:
        #    echo <prompt> | claude --pipe > diagnosis.txt
        # 3. Parse output
        return DiagnosisResult(
            root_cause="positionIdx mismatch in Hedge mode",
            action="restart with position mode re-detection",
            confidence=0.85,
            raw=<claude_output>
        )

class DiagnosisAnalyzer:
    """Parse Claude output into structured format."""
    @staticmethod
    def parse_diagnosis(raw_text: str) -> DiagnosisResult:
        # Extract: root_cause, action, confidence
        # Pattern match action to remediation tier
```

**Integration points:**
- In main.py: when error count > 3 in 1 hour, trigger diagnosis
- HealthMonitor: on critical alert, enrich with diagnosis before Discord notify
- GuardAgent: use diagnosis to validate proposed fix

**Good diagnosis prompts:**
```
Error: order_rejected
Exchange: Bithumb
Error Code: 10001
Message: position idx not match position mode

Context:
- Mode: Hedge (from API check)
- Bot sends positionIdx: 0
- Expected in Hedge: 1 (short) or 2 (long)

Hypothesis: positionIdx mismatch
Requirements:
1. Detect position mode from Bithumb API on startup
2. Store in config
3. Derive correct positionIdx from (side + mode)
4. Add retry logic for ErrCode 10001

Question: What code changes fix this?
```

**Why this matters:**
- Diagnosis takes <30 seconds (Claude CLI is fast)
- Identifies patterns that simple thresholds miss
- Operator gets explanation, not just "error 10001"

---

### Phase 3: Tiered Remediation (Days 9-15)
**Priority: HIGH | Effort: MEDIUM | Risk: MEDIUM (auto-restart only)**

#### Missing: Safe autonomous recovery
- GuardAgent exists but focuses on config validation
- Need: tier-based remediation executor with cooldowns

**Create:** `app/remediation_executor.py`

```python
class RemediationAction(Enum):
    RESTART = "restart"          # Tier 1: auto-execute (with cooldown)
    RELOAD_CONFIG = "reload"     # Tier 2: validated execution
    HALT_TRADING = "halt"        # Tier 3: human-only
    INVESTIGATE = "investigate"  # Tier 1: just log for review

class RemediationExecutor:
    """Execute bounded autonomous recovery actions."""

    async def execute(
        self,
        action: RemediationAction,
        reason: str,
        diagnosis: Optional[DiagnosisResult] = None
    ) -> ExecutionResult:
        """Execute action with guardrails."""

        # Tier 1 actions (auto-execute)
        if action == RemediationAction.RESTART:
            if await self._check_cooldown("restart", 5 * 60):  # 5-min cooldown
                await self._restart_bot()
                return ExecutionResult(status="success")
            else:
                return ExecutionResult(status="cooldown_active")

        # Tier 2 actions (validated)
        if action == RemediationAction.RELOAD_CONFIG:
            if not await guard_agent.validate_reload(new_config):
                return ExecutionResult(status="validation_failed")
            # ... execute reload

        # Tier 3 actions (human-only)
        if action == RemediationAction.HALT_TRADING:
            await notify_error(
                f"🚨 Manual review required\n"
                f"Action: {action}\n"
                f"Reason: {reason}\n"
                f"Approve with: /approve halt"
            )
            return ExecutionResult(status="awaiting_approval")
```

**Integration with HealthMonitor:**
```python
# In HealthMonitor._run_all_checks():
if any(r.status == "critical" for r in results):
    # Get diagnosis
    diagnosis = await diagnoser.diagnose_error_pattern(...)

    # Classify and execute
    action = guard_agent.classify_remediation(diagnosis)
    result = await executor.execute(action, diagnosis=diagnosis)

    # Notify
    await notifier.notify_remediation(action, result)
```

**Guardrails enforced:**
- Tier 1 (restart): max 1x per 5 minutes
- Tier 2 (reload): requires GuardAgent validation
- Tier 3 (halt): requires human approval button via Discord slash command
- Circuit breaker: hard stop on MDD > 15%, daily loss > 2%

**Why this matters:**
- Bot recovers from transient errors without operator intervention
- Humans always in control of trading decisions (Tier 3 never auto-executes)
- Cooldown prevents restart loops

---

## Integration Checklist

### Phase 1: EventStore
- [ ] Create `app/event_store.py` with Event + EventStore classes
- [ ] Add `events` table to Journal schema
- [ ] Instrument OrderManager.place_order() → record event
- [ ] Instrument OrderManager error paths → record event
- [ ] Instrument RiskGate.check() → record trading_halted events
- [ ] Unit tests for record/query operations
- [ ] Manual test: verify events logged to data/journal.db

### Phase 2: Claude Diagnosis
- [ ] Create `app/llm_client.py` with ClaudeDiagnoser
- [ ] Create `app/diagnosis_analyzer.py` with parser
- [ ] Test Claude CLI invocation (with proxy)
- [ ] Design error context prompt
- [ ] Integrate into HealthMonitor (on_critical alert)
- [ ] Test with sample errors (timeout, API fail, order reject)
- [ ] Manual test: verify diagnosis output in Discord

### Phase 3: Remediation
- [ ] Create `app/remediation_executor.py` with actions + cooldown
- [ ] Extend GuardAgent.classify_remediation()
- [ ] Integrate into main.py error handler
- [ ] Test Tier 1 (restart) with cooldown
- [ ] Test Tier 2 validation (config reload)
- [ ] Add Discord slash command for Tier 3 approval
- [ ] Manual test: trigger error → diagnose → remediate flow

### Post-Implementation
- [ ] 24h+ PAPER testing before LIVE
- [ ] Monitor: error rate, diagnosis accuracy, MTTR
- [ ] Verify Discord notifications include all context
- [ ] Document runbook for manual overrides

---

## Timeline & Risk

| Phase | Days | Components | Risk |
|-------|------|-----------|------|
| **1** | 1-3  | EventStore | **NONE** (read-only observability) |
| **2** | 4-8  | Claude diagnosis | **LOW** (info-only notifications) |
| **3** | 9-15 | Remediation executor | **MEDIUM** (auto-restart w/ cooldown) |
| **Testing** | 16-20 | PAPER mode validation | Validation only |

**Total:** 3-4 weeks for full rollout

---

## Success Metrics

Track daily in Discord:

```
📊 Self-Healing Status (24h)
├─ Error Count: 5 (↓)
├─ Diagnosis Accuracy: 100% (1/1 patterns correct)
├─ Remediation Success: 100% (5/5 restarts successful)
├─ MTTR: 3 min (target <10 min)
├─ Bot Uptime: 99.8%
├─ Auto-Restarts: 1 (target <1/day)
└─ Manual Interventions: 0
```

---

## Why This Architecture Works

1. **EventStore:** Immutable audit trail enables crash recovery + regulatory compliance
2. **HealthMonitor:** Concurrent checks detect both silent failures and active errors
3. **Claude diagnosis:** RCA in <30 seconds, human-readable explanation
4. **Tiered remediation:** Auto-execute safe actions, require approval for risky ones
5. **Guardrails:** Circuit breakers + cooldowns prevent cascading failure loops

This mirrors the architecture used by:
- **Rootly** (incident response automation) — reduced MTTR by 80%
- **Freqtrade** (crypto bot) — watchdog + SQLite persistence + systemd auto-restart
- **TraceRoot** (Y Combinator S25) — self-healing observability platform

---

## Next Steps

1. **Read** this file → understand current state
2. **Create Phase 1:** EventStore (3 days)
3. **Create Phase 2:** Claude diagnosis (5 days)
4. **Create Phase 3:** Remediation executor (7 days)
5. **Test 24+ hours in PAPER mode**
6. **Deploy to LIVE**

Start with Phase 1: EventStore. It's lowest-risk and enables everything that follows.

---

**Status:** Ready for implementation
**Recommendation:** Start Phase 1 immediately (zero risk)
