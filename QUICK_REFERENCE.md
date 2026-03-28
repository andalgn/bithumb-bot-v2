# Autonomous Code Improvement - Quick Reference Card

**Print this or bookmark for quick access during implementation.**

---

## 3-Phase Implementation Plan

| Phase | Duration | Key Action | Cost/week | Command |
|-------|----------|-----------|-----------|---------|
| 1: Dev | Weeks 1-2 | `/loop 15m` test | $10-20 | `/loop 15m python scripts/auto_research.py` |
| 2: Supervised | Weeks 3-6 | Human approval gate | $30-50 | Cloud task + Discord /approve |
| 3: Autonomous | Weeks 7+ | Auto-deploy + TradingGroup | $50-100 | DarwinEngine + feedback loops |

---

## 5 Core Files to Create

| File | Lines | Purpose | Status |
|------|-------|---------|--------|
| `strategy/guard_agent.py` | 200 | Safety validation | NEW |
| `strategy/auto_researcher.py` | 500 | Hypothesis generation | NEW |
| `app/approval_workflow.py` | 300 | Multi-level approval | NEW |
| `scripts/auto_research.py` | 50 | `/loop` entry point | NEW |
| `.claude/scheduled_tasks.yaml` | 100 | Cloud task config | NEW |

---

## Safety Checklist (Must Complete Before Live)

### Code Safety
- [ ] Strategy logic frozen (no rewrites)
- [ ] Parameter bounds in code (not prompt)
- [ ] Guardrails structural (OS-level)
- [ ] Resource limits on agent execution

### Financial Safety
- [ ] Position size ≤ 60% of equity
- [ ] Drawdown kill switch active
- [ ] Daily loss limit: 4% max
- [ ] Leverage: 1.0x max

### Operational Safety
- [ ] All changes git-logged
- [ ] Automated rollback on P&L < -X%
- [ ] Discord alerts on every action
- [ ] Weekly human review
- [ ] Shadow + paper before live

---

## Key Metrics (Track Daily)

```
Autonomous Agent Health:
- Hypothesis quality: % generating +5% improvement
- Validation stability: In-sample ≈ out-of-sample?
- Auto-approval rate: 20-40%?
- Rollback rate: <10%?
- Sharpe gain: +0.2-0.5/month?

Safety:
- Constraint violations: 0?
- Max DD from changes: <+5%?
- Parameter drift: <20%?
- Changes logged: 100%?
```

---

## Expected Timeline

```
Week 1-2: "Can we improve?"
  ├─ Implement Phase 1
  └─ Answer: Yes/No (usually yes!)

Week 3-6: "Can we do it safely?"
  ├─ Implement Phase 2
  └─ Answer: Yes (with guardrails)

Week 7+: "How much can we improve?"
  ├─ Implement Phase 3
  └─ Answer: +20-50% in month 3, then +5-10% long-term

Month 6: Stabilization
  └─ Diminishing returns kick in
```

---

## Claude Code Commands (Available Now)

```bash
# Phase 1: Development loop
/loop 15m python scripts/auto_research.py     # Run every 15m
/loop 30m hypothesis test                      # Every 30m
/loop daily full optimization                  # Daily

# Or with Cloud (persistent):
/schedule nightly_parameter_optimization at 2am UTC

# Management:
/cancel loop_id_xyz                            # Stop a loop
what scheduled tasks do I have?                # List active
remind me at 9am to review changes             # One-shot alert
```

---

## Discord Approval Commands

```
/approve <change_id>          # Approve pending change
/reject <change_id>           # Reject pending change
/rollback <change_id>         # Revert deployed change
/pause-agent                  # Pause autonomous improvements
/resume-agent                 # Resume autonomous improvements
/agent-status                 # Current state + queue
/weekly-review                # Force weekly report
/monthly-review               # Force strategic review
```

---

## GuardAgent Bounds (Copy & Paste)

```python
self.bounds = {
    "max_position_size": 0.6,          # 60% of equity
    "max_leverage": 1.0,               # No margin
    "atr_multiplier_range": (1.0, 4.0),
    "rsi_threshold_range": (30, 80),
    "momentum_weight_range": (0.0, 1.0),
    "max_daily_loss": -0.04,           # 4% max loss
    "max_drawdown": 0.15,              # 15% max DD
}
```

---

## Approval Risk Scoring

```
Risk = 0.3 * param_deviation
     + 0.2 * data_size_risk
     + 0.3 * stability_risk
     + 0.2 * mdd_risk

Auto-approve if risk < 0.2
Queue if 0.2 ≤ risk < 0.6
Reject if risk ≥ 0.6
```

---

## Deployment Stages

```
Proposed Change
    ↓ (Approval workflow)
    ├─ Risk Score ≤ 0.2? → Auto-approve → Deploy
    ├─ 0.2 < Risk < 0.6? → Queue for human review
    └─ Risk ≥ 0.6? → Auto-reject

Auto-Approved Change
    ↓
    Stage 1: Shadow (24h)
    ├─ Paper trades, no orders executed
    ├─ Check: Sharpe improvement > 0?
    └─ Continue or abort

    Stage 2: Paper (72h)
    ├─ Real orders on paper account
    ├─ Check: Sharpe improvement > -5%?
    └─ Continue or abort

    Stage 3: Live 50% (168h / 7 days)
    ├─ Real orders, real money, 50% position sizing
    ├─ Check: Sharpe improvement > 0%?
    └─ Success or rollback

    Stage 4: Full Deployment
    ├─ Scale to 100% position sizing
    └─ Monitor indefinitely
```

---

## TradingGroup Reflection (Key Pattern)

```
For each agent:
1. Fetch recent outcomes (last 50 trades/decisions)
2. Split: successful vs. failed
3. Summarize: What patterns differ?
4. Inject: Summary into next decision's context
5. Repeat: Every cycle

Example:
  Failed trades: 3x stopped out in range-bound markets
  Successful trades: 5x caught trending moves
  Pattern: "RSI > 70 → skip entry signal"
  Action: "Add RSI filter to next decision"
```

---

## Cost Calculator

**Development Phase (Week 1-2):**
- `/loop 15m`: ~500 calls/day × 2 weeks = 7,000 calls
- Cost: 7,000 × $0.0015/call ≈ $10-20

**Supervised Phase (Week 3-6):**
- Cloud task nightly: 30 calls × 4 weeks ≈ 120 calls
- Cost: 120 × $0.02/call ≈ $2-3/week × 4 = $8-12
- Plus /loop testing: $20/week
- **Total: $30-50/week**

**Full Autonomous (Week 7+):**
- Daily optimization + hourly metrics: ~1,000 calls/day
- Cost: 1,000 × $0.002/call × 30 days ≈ $60/month
- **Total: $50-100/week**

**First month budget: $150-250**
**Ongoing monthly: $200-400**

---

## When to Use Autonomous Improvement

### ✅ Good Fits
- Parameter tuning (Sharpe measurable)
- Indicator thresholds (hit rate measurable)
- Position sizing (P&L measurable)
- Trading hours filtering (profit per hour measurable)

### ❌ Bad Fits
- Strategy rewrites ("more profitable" = vague)
- Regime detection (subjective)
- Risk model changes (dangerous)
- Anything without numeric metrics

---

## Guardrail Patterns (Copy & Paste)

### Pattern 1: Bounds Check
```python
if not (1.0 <= param <= 4.0):
    return False  # Out of bounds
```

### Pattern 2: Forbidden Modifications
```python
forbidden = ["def entry_signal", "order_manager.", "risk_gate."]
if any(f in code for f in forbidden):
    return False  # Dangerous modification
```

### Pattern 3: Risk Score
```python
risk = (0.3 * param_dev + 0.2 * data_risk +
        0.3 * stability + 0.2 * mdd_risk)
if risk < 0.2:
    auto_approve()
elif risk < 0.6:
    queue_for_approval()
else:
    reject()
```

### Pattern 4: Multi-Stage Deployment
```python
await shadow_trade(new_params, 24)        # Paper
await paper_trade(new_params, 72)         # Paper
await live_trade(new_params, 168, size=0.5)  # 50% live
await full_deployment(new_params)         # 100% live
```

---

## Critical Success Factors

1. **Measurable Feedback**
   - Must have: baseline → change → validation
   - Cannot improve: subjective metrics

2. **Structural Guardrails**
   - Guardrails must be in code, not prompts
   - Agent can't bypass code constraints

3. **Multi-Stage Validation**
   - Never: deploy directly to live
   - Always: shadow → paper → live 50% → live 100%

4. **Audit Trail**
   - Every change git-logged
   - Every approval recorded
   - Rollback always possible

5. **Human Oversight**
   - Weekly review (minimum)
   - Auto-rollback on failure (automatic)
   - Manual intervention on uncertainty

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| Agent generates bad hypotheses | Reflection context incomplete | Add more trade context (regime, signals, patterns) |
| Improvements don't hold in live | Overfitting (lucky backtest) | Increase validation data, use walk-forward |
| Rollback rate >20% | Guardrails too loose | Tighten parameter bounds, reduce mutation rate |
| High approval queue | Too many medium-risk changes | Increase auto-approval threshold (0.2 → 0.3) |
| Constraint violations | Guardrails not structural | Move from prompt to code-level checks |
| Agent loop never converges | Mutation rate too high | Reduce mutation_std (0.1 → 0.05) |

---

## Recommended Reading Order

1. **5 min:** AUTONOMOUS_RESEARCH_SUMMARY.md
2. **30 min:** RESEARCH_AUTONOMOUS_AGENT_CODE_IMPROVEMENT.md sections 1-4
3. **20 min:** AUTONOMOUS_IMPROVEMENT_ARCHITECTURE.md sections 1-3
4. **15 min:** AUTONOMOUS_IMPROVEMENT_IMPLEMENTATION.md sections 1-3
5. **Start coding:** Follow IMPLEMENTATION templates

---

## Quick Commands (Ctrl+C / Cmd+C to Copy)

```bash
# Start Phase 1 development loop
/loop 15m python scripts/auto_research.py

# Create Cloud task for Phase 2
/schedule nightly_parameter_optimization at 2am UTC

# Check active loops
what scheduled tasks do I have?

# Stop all autonomous improvements
/pause-agent

# Resume autonomous improvements
/resume-agent

# Force weekly review report
/weekly-review
```

---

## Contact Points in Codebase

| Component | File | When to Modify |
|-----------|------|---|
| Trade journal | `app/journal.py` | Add failure_class, reflection |
| Metrics collection | `app/metrics_stream.py` | Add hourly metric types |
| Strategy | `strategy/rule_engine.py` | Freeze (no agent changes) |
| Hypothesis gen | `strategy/auto_researcher.py` | Tune Claude prompt |
| Safety validation | `strategy/guard_agent.py` | Adjust parameter bounds |
| Approval | `app/approval_workflow.py` | Adjust risk thresholds |
| Deployment | `execution/order_manager.py` | Add rollback trigger |
| Discord | `bot_discord/bot.py` | Add approval commands |

---

## Version
- **Research Date:** 2026-03-28
- **Status:** Ready for implementation
- **Next Review:** After Phase 1 completion

---

**Print this card. Keep it handy during implementation.**
