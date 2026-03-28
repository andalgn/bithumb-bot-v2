# Autonomous Improvement Implementation Guide

Quick reference for integrating autonomous improvement into Bithumb bot.

---

## 1. File Structure Changes

```
strategy/
├── auto_researcher.py          [NEW] Daily hypothesis generation
├── guard_agent.py              [NEW] Safety validation
├── darwin_engine.py            [ENHANCE] Add autonomous_evolution_loop
├── self_reflection.py          [ENHANCE] Add agent context injection
└── (existing files)

app/
├── approval_workflow.py        [NEW] Multi-level change approval
├── metrics_stream.py           [NEW] Real-time metric collection
├── journal.py                  [ENHANCE] Add failure_class, reflection fields
└── (existing files)

scripts/
├── auto_research.py            [NEW] Entry point for /loop
├── autonomous_evolution.py     [NEW] Cloud task for nightly Darwin
└── weekly_review.py            [NEW] Sunday human review

.claude/scheduled_tasks.yaml   [NEW] Cloud task definitions
```

---

## 2. Core Integration Points

### 2.1 Enhance Trade Journal

**File:** `app/journal.py`

```python
# BEFORE: Just tracking basic trade metrics
class Trade:
    entry_price: float
    exit_price: float
    pnl: float

# AFTER: Add feedback context
class Trade:
    # Basic (existing)
    entry_price: float
    exit_price: float
    pnl: float

    # NEW: Context for agent feedback
    regime_at_entry: str  # From regime_classifier
    correlation_cluster: str  # From correlation_monitor
    momentum_rank: int  # From momentum_ranker (1-10)

    # NEW: Failure classification (by trade_tagger)
    failure_class: Optional[str]
    root_cause: Optional[str]  # LLM analysis
    reflection: Optional[str]  # Agent insights

# Add to main.py:
async def post_trade_analysis():
    """After each trade closes, run reflection."""
    trade = await journal.get_last_closed_trade()

    # Get failure classification
    trade.failure_class = await trade_tagger.classify(trade)

    # Generate reflection (TradingGroup pattern)
    similar_past = await journal.find_similar_trades(
        regime=trade.regime_at_entry,
        signal_type=trade.signal_type,
        limit=5
    )
    reflection = await claude.call(f"""
    This trade was classified as: {trade.failure_class}

    Similar past trades in same regime:
    {similar_past}

    What pattern should we adjust to prevent this?
    """)
    trade.reflection = reflection

    await journal.update_trade(trade)
```

### 2.2 Real-Time Metrics Stream

**File:** `app/metrics_stream.py` (NEW)

```python
class MetricsCollector:
    """Collects hourly metrics for agent analysis."""

    def __init__(self, state_store):
        self.state_store = state_store

    async def collect_hourly(self):
        """Called by scheduler every hour."""
        equity = await self.get_equity()
        pnl_today = equity - self.session_start_equity

        metrics = {
            "timestamp": datetime.utcnow(),
            "equity": equity,
            "pnl_today": pnl_today,
            "drawdown": self.calculate_drawdown(),
            "positions": await self.count_positions(),
            "regime": regime_classifier.current,
        }

        await self.state_store.metrics.append(metrics)

        # In app/main.py scheduler loop:
        if cycle_count % 4 == 0:  # Every 60 minutes
            await MetricsCollector(state_store).collect_hourly()
```

### 2.3 AutoResearcher Entry Point

**File:** `scripts/auto_research.py` (NEW)

```python
#!/usr/bin/env python3
"""
Entry point for autonomous research loop.
Called via: /loop 15m python scripts/auto_research.py
"""

import asyncio
from app.config import Config
from strategy.auto_researcher import AutoResearcher
from market.datafeed import DataFeed
from app.notify import notify_discord

async def main():
    config = Config.load("configs/config.yaml")
    researcher = AutoResearcher(config)

    try:
        # Step 1: Analyze yesterday's trades
        yesterday = await researcher.daily_analysis_loop()
        print(f"Analysis complete. Generated {len(yesterday.hypotheses)} hypotheses.")

        # Step 2: Propose best improvements
        for hypothesis in yesterday.hypotheses[:3]:  # Top 3
            print(f"Hypothesis: {hypothesis.name}")
            print(f"Sharpe improvement: +{hypothesis.validation.sharpe_improvement:.3f}")

    except Exception as e:
        await notify_discord(f"❌ Auto-researcher error: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
```

### 2.4 Cloud Task Configuration

**File:** `.claude/scheduled_tasks.yaml` (NEW)

```yaml
version: "1"

tasks:
  - id: "nightly_parameter_optimization"
    schedule: "0 2 * * *"  # 2am UTC = 11am KST
    enabled: true

    prompt: |
      You are the Bithumb autonomous strategy optimizer.

      Your job is to improve trading parameters daily.

      Step 1: Download latest metrics
      - Get last 7 days of trades from data/bot.db
      - Get current regime (bull/bear/range)
      - Get current equity and drawdown

      Step 2: Analyze performance
      - Calculate hit rate, profit factor, Sharpe
      - Identify failure patterns (from trade_class)
      - Find regime-specific issues

      Step 3: Generate parameter hypotheses
      - Propose 3 parameter changes that address failures
      - Each hypothesis should have clear rationale
      - Examples: "Add RSI filter to reduce range trades"
                  "Increase ATR multiplier in trending markets"

      Step 4: Validate hypotheses
      - For each, run 7-day backtest (out-of-sample data)
      - Calculate Sharpe improvement
      - Check for overfitting

      Step 5: Propose changes
      - Only propose if Sharpe improvement > +5%
      - Use guardrails.yaml constraints
      - Store in data/candidate_params.json

      Step 6: Report to Discord
      - List proposed changes with validation results
      - Risk assessment for each
      - Request human approval if needed

      GUARDRAILS:
      - Max position size: 60%
      - Max leverage: 1.0x
      - Max DD allowed: 20%
      - Only modify: momentum_weight, rsi_threshold, atr_multiplier
      - Never modify: strategy logic, order execution

    cloud_config:
      timeout_seconds: 1800  # 30 minutes max
      memory_mb: 512

  - id: "weekly_human_review"
    schedule: "0 9 * * 0"  # Sunday 9am UTC = 5pm KST
    enabled: true

    prompt: |
      Generate weekly review of autonomous improvements.

      Tasks:
      1. Fetch all parameter changes from last 7 days
      2. Calculate live performance of each (if deployed)
      3. Identify winners and losers
      4. Suggest reversions for underperforming changes
      5. Report to Discord with:
         - Summary of changes
         - Performance impact
         - Recommendations
```

### 2.5 Darwin Engine Autonomous Mode

**File:** `strategy/darwin_engine.py` (ENHANCE)

```python
class DarwinEngine:
    """Existing class + new autonomous_loop method."""

    async def autonomous_evolution_loop(self):
        """
        Daily evolution without human intervention.
        Called via Cloud task.
        """

        # Get baseline
        current_params = await self.load_current_params()
        baseline_result = await self.evaluate_params(current_params, days=7)

        # Create mutation population
        population = []
        for _ in range(20):
            mutant = self.create_mutant(
                center=current_params,
                mutation_std=0.05  # Small perturbations
            )
            if self.guard_agent.validate_params(mutant):
                population.append(mutant)

        # Evaluate population (parallel)
        tasks = [self.evaluate_params(p, days=7) for p in population]
        results = await asyncio.gather(*tasks)

        # Select top performer
        best_idx = np.argmax([r.sharpe_ratio for r in results])
        best_params = population[best_idx]
        best_result = results[best_idx]

        # Check improvement
        improvement = best_result.sharpe_ratio - baseline_result.sharpe_ratio

        if improvement > 0.2:
            # Significant: auto-approve
            await self.store_params(best_params, auto_approved=True)
            await notify_discord(
                f"✅ Darwin improved Sharpe by +{improvement:.3f}"
            )
        elif improvement > 0.05:
            # Moderate: request approval
            await self.queue_for_approval(best_params, improvement)
            await notify_discord(
                f"⚖️ Darwin found +{improvement:.3f} improvement (pending review)"
            )
```

### 2.6 Guard Agent

**File:** `strategy/guard_agent.py` (NEW)

```python
class GuardAgent:
    """Validates agent-generated parameters."""

    def __init__(self, config: Config):
        self.config = config
        self.safe_params = [
            "momentum_weight",
            "rsi_threshold",
            "atr_multiplier",
            "position_size",
        ]
        self.dangerous_params = [
            "entry_signal",  # Core logic
            "exit_signal",   # Core logic
            "order_execution",  # Risky
        ]

    def validate_params(self, params: dict) -> bool:
        """Check safety constraints."""

        # Check 1: Only safe parameters
        for key in params.keys():
            if key not in self.safe_params:
                logger.warning(f"Unsafe parameter: {key}")
                return False

        # Check 2: Value bounds
        bounds = {
            "momentum_weight": (0.0, 1.0),
            "rsi_threshold": (30, 80),
            "atr_multiplier": (1.0, 4.0),
            "position_size": (0.1, 0.6),
        }

        for key, (min_val, max_val) in bounds.items():
            if key in params:
                val = params[key]
                if not (min_val <= val <= max_val):
                    logger.warning(f"{key} out of bounds: {val}")
                    return False

        return True

    def validate_code(self, code: str) -> bool:
        """Prevent dangerous code modifications."""

        forbidden = [
            "order_manager.",
            "risk_gate.",
            "partial_exit.",
            "def entry_signal",
            "def exit_signal",
        ]

        for pattern in forbidden:
            if pattern in code:
                logger.error(f"Forbidden pattern: {pattern}")
                return False

        return True
```

### 2.7 Approval Workflow

**File:** `app/approval_workflow.py` (NEW)

```python
class ApprovalWorkflow:
    """Queue + approve agent-generated changes."""

    def __init__(self, state_store, discord_client):
        self.state_store = state_store
        self.discord = discord_client

    async def propose_change(
        self,
        hypothesis: str,
        new_params: dict,
        validation: dict,
    ) -> bool:
        """
        Propose change. Returns True if approved, False if rejected.
        """

        # Calculate risk
        risk = self._assess_risk(new_params, validation)

        if risk < 0.3:  # Low risk
            await self._deploy(new_params)
            return True
        elif risk < 0.6:  # Medium risk
            # Queue for approval
            change_id = str(uuid.uuid4())[:8]
            await self.state_store.approval_queue.append({
                "change_id": change_id,
                "hypothesis": hypothesis,
                "params": new_params,
                "validation": validation,
                "created_at": datetime.utcnow(),
            })

            # Notify
            await self.discord.send_approval_prompt(
                change_id, hypothesis, validation
            )

            # Wait for approval (24h timeout)
            approval = await self.wait_approval(change_id, timeout=86400)
            if approval:
                await self._deploy(new_params)
                return True
            else:
                return False

        else:  # High risk
            await self.discord.send(
                f"🚫 Rejected (too risky): {hypothesis} (risk={risk:.1%})"
            )
            return False

    def _assess_risk(self, new_params, validation) -> float:
        """Risk score 0-1."""
        param_deviation = np.mean([
            abs(new_params.get(k) - self.config.baseline_params.get(k))
            / (self.config.baseline_params.get(k) or 1)
            for k in new_params.keys()
        ])
        data_risk = max(0, (7 - validation.get("days_tested", 0)) / 7)
        stability = 1.0 - validation.get("oos_stability", 0.5)
        mdd_risk = max(0, (validation.get("max_dd") - 0.15) / 0.15)

        return 0.25 * param_deviation + 0.25 * data_risk + 0.25 * stability + 0.25 * mdd_risk
```

---

## 3. Discord Integration

### 3.1 Discord Commands

**In `bot_discord/bot.py`:**

```python
@bot.command()
async def approve(ctx, change_id: str):
    """Approve a pending parameter change."""
    await approval_workflow.approve(change_id)
    await ctx.send(f"✅ Approved: {change_id}")

@bot.command()
async def reject(ctx, change_id: str):
    """Reject a pending change."""
    await approval_workflow.reject(change_id)
    await ctx.send(f"❌ Rejected: {change_id}")

@bot.command()
async def agent_status(ctx):
    """Show autonomous agent status."""
    queue = await state_store.approval_queue.fetch_all()
    await ctx.send(f"Pending approvals: {len(queue)}")

@bot.command()
async def pause_agent(ctx):
    """Pause autonomous improvements."""
    config.autonomous_mode = False
    await ctx.send("⏸️ Agent paused")

@bot.command()
async def resume_agent(ctx):
    """Resume autonomous improvements."""
    config.autonomous_mode = True
    await ctx.send("▶️ Agent resumed")
```

### 3.2 Discord Notifications

```python
async def notify_improvement(hypothesis: str, sharpe_gain: float):
    """Post improvement to Discord."""
    await webhook.send(f"""
    📊 Parameter Optimization

    Hypothesis: {hypothesis}
    Sharpe Improvement: +{sharpe_gain:.3f}
    Status: Waiting for approval

    Use: `/approve <change_id>`
    """)

async def notify_deployed(new_params: dict):
    """Post deployment notification."""
    await webhook.send(f"""
    ✅ Parameters deployed

    Changes:
    {json.dumps(new_params, indent=2)}

    Live in: Shadow mode (24h) → Paper (3d) → Live (50% size)
    """)
```

---

## 4. Testing & Validation

### 4.1 Unit Test for GuardAgent

```python
# tests/test_guard_agent.py

def test_guard_agent_rejects_dangerous_params():
    guard = GuardAgent(config)

    # Dangerous: out of bounds
    assert not guard.validate_params({"rsi_threshold": 100})  # Should be 30-80

    # Safe: in bounds
    assert guard.validate_params({"rsi_threshold": 70})

    # Dangerous: core logic modification
    assert not guard.validate_code("def entry_signal(): pass")

def test_guard_agent_accepts_safe_changes():
    guard = GuardAgent(config)

    safe_params = {
        "momentum_weight": 0.5,
        "rsi_threshold": 65,
        "atr_multiplier": 2.0,
    }

    assert guard.validate_params(safe_params)
```

### 4.2 Integration Test for Approval Workflow

```python
# tests/test_approval_workflow.py

@pytest.mark.asyncio
async def test_approval_workflow_auto_approves_low_risk():
    workflow = ApprovalWorkflow(state_store, discord_client)

    result = await workflow.propose_change(
        hypothesis="Add RSI filter",
        new_params={"rsi_threshold": 70},
        validation={"sharpe_improvement": 0.3, "days_tested": 7},
    )

    assert result is True  # Auto-approved (low risk)

@pytest.mark.asyncio
async def test_approval_workflow_queues_medium_risk():
    workflow = ApprovalWorkflow(state_store, discord_client)

    result = await workflow.propose_change(
        hypothesis="Change momentum weight",
        new_params={"momentum_weight": 0.8},
        validation={"sharpe_improvement": 0.1, "days_tested": 3},
    )

    # Should queue, not auto-approve
    queue = await state_store.approval_queue.fetch_all()
    assert len(queue) > 0
```

---

## 5. Deployment Checklist

Before going live with autonomous improvement:

- [ ] Enhanced Trade Journal (with failure_class, reflection fields)
- [ ] MetricsCollector running (hourly metrics to database)
- [ ] AutoResearcher implemented (daily hypothesis generation)
- [ ] GuardAgent implemented (parameter validation)
- [ ] ApprovalWorkflow implemented (multi-level approval)
- [ ] DarwinEngine autonomous_loop implemented
- [ ] Cloud task configured (.claude/scheduled_tasks.yaml)
- [ ] Discord commands registered (/approve, /reject, /agent-status, etc.)
- [ ] Tests passing (unit + integration)
- [ ] Manual 1-week shadow test (agent proposes changes, human approves only)
- [ ] Discord alerts configured for errors/changes
- [ ] Weekly review script implemented
- [ ] Rollback procedure tested (can quickly revert bad params)

---

## 6. Monitoring & Alerting

### 6.1 Key Metrics to Dashboard

```python
# In app/main.py or dashboard

agent_metrics = {
    "hypotheses_generated_today": int,
    "improvements_proposed": int,
    "auto_approved": int,
    "pending_approval": int,
    "total_sharpe_improvement": float,
    "rollback_rate": float,
    "latest_change": {
        "hypothesis": str,
        "status": str,  # "approved", "pending", "reverted"
        "sharpe_gain": float,
    }
}

# Alert conditions
if rollback_rate > 0.2:
    await notify_discord("⚠️ High rollback rate, consider tightening guardrails")

if pending_approval > 5:
    await notify_discord("📋 5+ pending approvals awaiting human review")

if total_sharpe_improvement < -0.1:
    await notify_discord("❌ Agent's changes are hurting performance, pausing")
```

---

## 7. Quick Start (5-step)

1. **Copy template files:**
   - `strategy/guard_agent.py`
   - `strategy/auto_researcher.py`
   - `app/approval_workflow.py`
   - `scripts/auto_research.py`

2. **Enhance existing files:**
   - `app/journal.py`: Add failure_class, reflection fields
   - `app/main.py`: Call MetricsCollector hourly
   - `bot_discord/bot.py`: Register approval commands

3. **Create Cloud task:**
   - Copy `.claude/scheduled_tasks.yaml` (sample provided above)
   - Test with `/schedule nightly_parameter_optimization`

4. **Test locally:**
   - Run `python scripts/auto_research.py` manually
   - Verify hypothesis generation
   - Check guardrail validation

5. **Deploy:**
   - Enable Cloud task
   - Monitor Discord for proposals
   - Manual approval for 1-2 weeks
   - Then enable auto-approval for low-risk

---

## 8. Cost Estimate

| Phase | Duration | Cost/week | API Calls |
|-------|----------|-----------|-----------|
| Development (/loop) | 2-4 weeks | $10-20 | ~1000 |
| Supervised (manual approval) | 2-4 weeks | $30-50 | ~2000 |
| Full autonomous (Cloud) | Ongoing | $50-100 | ~5000 |

Total first month: ~$150-250
Ongoing: ~$200-400/month

---

## Summary

Key files to create/modify:

1. `strategy/auto_researcher.py` → Daily hypothesis generation
2. `strategy/guard_agent.py` → Safety validation
3. `app/approval_workflow.py` → Multi-level approval
4. `.claude/scheduled_tasks.yaml` → Cloud task config
5. `bot_discord/bot.py` → Approval commands
6. `scripts/auto_research.py` → /loop entry point

Expected outcome: +20-50% Sharpe improvement by month 3, stabilizing at +5-10% long-term.
