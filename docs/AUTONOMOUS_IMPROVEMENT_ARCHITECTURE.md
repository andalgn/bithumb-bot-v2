# Autonomous Improvement Architecture for Bithumb Trading Bot

## 1. Overview

This document details a concrete 3-tier autonomous improvement system for the Bithumb bot, integrating feedback loops from research, code, and execution layers.

---

## 2. System Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    FEEDBACK & IMPROVEMENT                         │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│  TIER 1: OBSERVATION (Real-Time)                                │
│  ├─ Live Trade Journal → Execution Outcomes                     │
│  ├─ Hourly P&L, DD, Hit Rate, Win Rate                         │
│  ├─ Failure Classification (by trade_tagger.py)                │
│  └─ Regime State (bull/bear/range via regime_classifier.py)   │
│                                                                   │
│  TIER 2: ANALYSIS (Daily/Weekly)                                │
│  ├─ SelfReflection: "Why did this trade fail?"                │
│  ├─ DarwinEngine: Parameter mutation + selection               │
│  ├─ ReviewEngine: Multi-level synthesis (daily/weekly/monthly) │
│  └─ AutoResearcher: Hypothesis generation                      │
│                                                                   │
│  TIER 3: ACTION (Execution)                                     │
│  ├─ CodeGen: Synthesize parameter changes (safe subset only)  │
│  ├─ Guard Agent: Validate changes against constraints          │
│  ├─ Backtest: Walk-forward validation on out-of-sample         │
│  └─ Deploy: Shadow → Paper → Live (gated progression)         │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

---

## 3. Tier 1: Real-Time Observation

### 3.1 Trade Journal + Tagging

**Current System:** `app/journal.py`

**Extension for Autonomous Feedback:**

```python
# app/journal.py (enhanced)

class TradeWithContext(Trade):
    """Extended trade record with context for agent analysis."""

    # Existing fields
    entry_price: float
    exit_price: float
    size: float
    pnl: float
    pnl_pct: float

    # New fields for feedback
    regime_at_entry: str  # "bull", "bear", "range"
    correlation_cluster: str  # "high", "medium", "low"
    momentum_rank: int  # 1-10 (1=weakest, 10=strongest)
    technical_score: float  # Combined indicator score at entry

    # Execution context
    slippage: float  # Expected vs actual entry
    partial_exits: List[PartialExit]  # Trail stops, profit takes
    hold_duration_bars: int

    # Outcome classification (by trade_tagger.py)
    failure_class: Optional[str]  # "stopped_out_range", "reversal_too_fast", etc.
    root_cause: Optional[str]  # LLM-generated analysis

    # AI Agent Reflection
    reflection: Optional[str]  # "In range-bound markets, this signal fails 70% of time"
    suggested_improvement: Optional[str]  # "Add RSI overbought filter"

# Daily aggregation for agent
class DailyTradeSummary:
    date: str
    trades: List[TradeWithContext]
    daily_pnl: float
    daily_dd: float

    regime: str
    avg_technical_score: float
    hit_rate: float
    profit_factor: float

    failure_patterns: Dict[str, int]  # {"stopped_out_range": 3, ...}
    top_improvement_ideas: List[str]  # Agent suggestions
```

### 3.2 Real-Time Metrics Stream

```python
# New: app/metrics_stream.py

class MetricsStreamCollector:
    """Collects metrics every hour for agent consumption."""

    async def collect_hourly_metrics(self):
        """Called by main.py every hour."""

        equity = await self.get_equity()
        unrealized_pnl = await self.get_unrealized_pnl()
        active_positions = await self.count_active_positions()

        metrics = {
            "timestamp": datetime.utcnow(),
            "equity": equity,
            "cumulative_pnl": cumulative_pnl,
            "daily_pnl": equity - session_start_equity,
            "drawdown": self.calculate_dd(),
            "positions_open": active_positions,
            "regime": regime_classifier.current_regime,
            "market_condition": "bull" | "bear" | "range",
        }

        # Store for agent analysis
        await self.state_store.append("metrics_stream", metrics)

        # Also log to Discord for visibility
        if cumulative_pnl < -session_max_dd * 0.8:
            await notify_discord(
                f"⚠️ Drawdown Warning: {drawdown:.1f}% (threshold: {session_max_dd}%)"
            )
```

---

## 4. Tier 2: Daily Analysis & Hypothesis Generation

### 4.1 AutoResearcher Module (Enhanced)

**File:** `strategy/auto_researcher.py`

```python
class AutoResearcher:
    """
    Autonomous strategy researcher.
    Runs daily: analyze yesterday, hypothesize improvements.
    """

    def __init__(self, config: Config, claude_client: AsyncClaudeClient):
        self.config = config
        self.claude = claude_client
        self.state_store = StateStore()

    async def daily_analysis_loop(self):
        """
        Called via Cloud task every 2am UTC.

        1. Fetch yesterday's trades + metrics
        2. Run TradingGroup-style reflection
        3. Generate hypotheses
        4. Propose parameter changes
        5. Report to Discord
        """

        # Step 1: Gather observations
        yesterday_trades = await self.state_store.get_trades_for_date(
            date=date.today() - timedelta(days=1)
        )
        yesterday_summary = DailyTradeSummary.from_trades(yesterday_trades)

        # Step 2: Reflection (TradingGroup pattern)
        reflection_result = await self.reflect_on_trades(yesterday_summary)
        # Example output:
        # {
        #   "failure_patterns": ["stopped_out_in_range": 3, "reversal_too_fast": 2],
        #   "successful_patterns": ["strong_trend_momentum": 5],
        #   "regime_analysis": "Yesterday was range-bound, strategy struggled",
        #   "root_causes": [
        #     "RSI overbought filter missing on short entries",
        #     "ATR-based stop too tight in low-vol regime"
        #   ]
        # }

        # Step 3: Hypothesis generation (Claude)
        hypotheses = await self.generate_hypotheses(reflection_result)
        # [
        #   {"name": "rsi_overbought_filter", "description": "..."},
        #   {"name": "atr_regime_adjustment", "description": "..."},
        # ]

        # Step 4: Parameter synthesis for each hypothesis
        for hypothesis in hypotheses:
            new_params = await self.synthesize_parameters(hypothesis)

            # Step 5: Quick validation (7-day backtest)
            validation = await self.validate_parameters(
                new_params,
                lookback_days=7,
                out_of_sample=True  # Use data agent hasn't seen
            )

            # Step 6: Filter & report
            if validation.sharpe_improvement > 0.05:
                await self.report_hypothesis_to_discord(
                    hypothesis, validation, new_params
                )
                # Store for weekly human review
                await self.state_store.store_candidate_params(
                    date=date.today(),
                    hypothesis=hypothesis,
                    params=new_params,
                    validation=validation
                )

    async def reflect_on_trades(self, summary: DailyTradeSummary) -> dict:
        """TradingGroup-style reflection."""

        prompt = f"""
        You are a trading strategist analyzing yesterday's performance.

        Yesterday's Summary:
        - Total trades: {len(summary.trades)}
        - Profit factor: {summary.profit_factor:.2f}
        - Hit rate: {summary.hit_rate:.1%}
        - Daily P&L: ${summary.daily_pnl:,.0f}
        - Market regime: {summary.regime}

        Failed Trades:
        {self._format_failed_trades(summary)}

        Successful Trades:
        {self._format_successful_trades(summary)}

        Questions to Answer:
        1. What market conditions were we in? Did our strategy match?
        2. Which signal types failed most? Why?
        3. Were there pattern/technical breaks?
        4. What ONE filter/indicator could have prevented most losses?
        5. What worked well? Should we emphasize it more?

        Respond with:
        - Key patterns observed
        - Root causes for failures
        - Specific improvement hypotheses (actionable)
        """

        response = await self.claude.call(prompt)
        return self._parse_reflection(response)

    async def generate_hypotheses(self, reflection: dict) -> List[dict]:
        """Convert reflection insights into parameter hypotheses."""

        # Example: reflection says "RSI overbought"
        # Hypothesis: "Add RSI threshold filter"
        # Parameters: RSI_THRESHOLD=70, RSI_WEIGHT=0.2

        prompt = f"""
        Based on this reflection:
        {json.dumps(reflection, indent=2)}

        Generate 3-5 specific parameter change hypotheses.

        For each hypothesis, provide:
        1. Name: "hypothesis_name"
        2. Rationale: Why this should work
        3. Parameters to change:
           - param_name: [current_value → proposed_value]
        4. Expected improvement: Which failure pattern does it address?

        Format as JSON array.
        """

        response = await self.claude.call(prompt)
        return json.loads(response)

    async def validate_parameters(
        self,
        new_params: dict,
        lookback_days: int = 7,
        out_of_sample: bool = True
    ) -> BacktestResult:
        """Quick validation of proposed parameters."""

        # Get historical data (avoiding look-ahead bias)
        if out_of_sample:
            # Use data agent hasn't yet analyzed
            cutoff_date = date.today() - timedelta(days=lookback_days+1)
            historical_data = await self.fetch_data(
                start_date=cutoff_date - timedelta(days=lookback_days),
                end_date=cutoff_date  # Past data only
            )
        else:
            # Use most recent N days
            historical_data = await self.fetch_recent_data(days=lookback_days)

        # Run backtest with new parameters
        strategy = StrategyEngine(self.config)
        strategy.params.update(new_params)

        result = await strategy.backtest(
            data=historical_data,
            progress_callback=None  # Silent mode
        )

        return result


class TradingGroupReflectionEngine:
    """
    Implements TradingGroup's self-reflection mechanism.

    Key insight: Each agent (forecast, style, decision) maintains
    its own recent context of successes/failures, injecting insights
    into its next decision.
    """

    async def reflect_stock_forecasting_agent(self):
        """Stock Forecasting Agent reflection."""

        # Fetch recent predictions
        recent_preds = await self.db.fetch_predictions(limit=50)
        accurate = [p for p in recent_preds if p.outcome == "CORRECT"]
        failed = [p for p in recent_preds if p.outcome == "FAILED"]

        # Summarize patterns
        patterns = await self.claude.call(f"""
        Recent accurate predictions: {self._format_trades(accurate)}
        Recent failed predictions: {self._format_trades(failed)}

        What patterns distinguish successful from failed predictions?
        Focus on:
        - Market regime differences
        - Indicator combinations that worked/failed
        - Time-of-day patterns
        - Volatility regimes

        Return a JSON object with key insights to inject into next forecast.
        """)

        # Inject into context for next decision
        await self.state_store.set_agent_context("stock_forecasting", patterns)
```

### 4.2 DarwinEngine Integration

**File:** `strategy/darwin_engine.py`

The existing DarwinEngine already implements:
- Fitness evaluation (Sharpe, Profit Factor, MDD)
- Parameter mutation (Gaussian perturbation)
- Selection (tournament)

**Enhancement for autonomous improvement:**

```python
class DarwinEngine:
    """Enhanced with autonomous mode."""

    async def autonomous_evolution_loop(self):
        """
        Called daily via Cloud task.

        Evolves parameters without human intervention, using
        safety guardrails to prevent dangerous changes.
        """

        # Step 1: Get current best parameters
        current_best = await self.state_store.get_best_params()

        # Step 2: Create population around current best
        population = self.initialize_population(
            center=current_best,
            mutation_std=0.1  # Small perturbations (conservative)
        )

        # Step 3: Evaluate population (walk-forward validation)
        fitness_scores = []
        for params in population:
            # GUARD: Check parameter bounds
            if not self.guard_agent.validate_params(params):
                fitness_scores.append(-float('inf'))  # Reject invalid params
                continue

            # Backtest
            result = await self.backtest_params(params, lookback_days=30)
            fitness_scores.append(result.sharpe_ratio)

        # Step 4: Select top performers
        top_indices = np.argsort(fitness_scores)[-self.elite_size:]
        elite_params = [population[i] for i in top_indices]
        elite_scores = [fitness_scores[i] for i in top_indices]

        # Step 5: Auto-approve if significant improvement
        improvement = elite_scores[0] - current_best.sharpe_ratio

        if improvement > 0.2:  # Significant improvement (0.2 Sharpe points)
            # Auto-approve: low risk, high evidence
            await self.deploy_params(elite_params[0], auto_approve=True)
            await notify_discord(
                f"🧬 Darwin improved Sharpe by {improvement:.3f} "
                f"(new: {elite_scores[0]:.2f})"
            )
        elif improvement > 0.05:  # Moderate improvement
            # Flag for human review
            await self.state_store.queue_for_review(
                params=elite_params[0],
                improvement=improvement,
                new_sharpe=elite_scores[0]
            )
            await notify_discord(
                f"⚖️ Darwin found +{improvement:.3f} improvement (pending review)"
            )
        else:
            # No meaningful improvement
            pass
```

---

## 5. Tier 3: Safe Execution & Deployment

### 5.1 GuardAgent: Parameter Validation

**File:** `strategy/guard_agent.py` (NEW)

```python
class GuardAgent:
    """
    Safety validation layer for autonomous code changes.

    Ensures agent-generated parameters stay within safe bounds
    and don't violate risk constraints.
    """

    def __init__(self, config: Config):
        self.config = config
        self.bounds = {
            "max_position_size": 0.6,  # 60% of equity
            "max_leverage": 1.0,  # No margin
            "min_sharpe_baseline": 0.5,  # Don't go backward
            "max_dd_allowed": 0.15,  # 15% max drawdown
            "atr_multiplier_range": (1.0, 4.0),  # Stop loss range
            "momentum_weight_range": (0.0, 1.0),  # Indicator weights
            "rsi_threshold_range": (30, 80),  # Overbought/sold levels
        }

    def validate_params(self, params: dict) -> bool:
        """Check if parameters are within safe bounds."""

        checks = [
            ("position_size", params.get("position_size", 0.5) <= self.bounds["max_position_size"]),
            ("leverage", params.get("leverage", 1.0) <= self.bounds["max_leverage"]),
            ("atr_mult", self._in_range(
                params.get("atr_multiplier", 2.0),
                self.bounds["atr_multiplier_range"]
            )),
            ("rsi_thresh", self._in_range(
                params.get("rsi_threshold", 70),
                self.bounds["rsi_threshold_range"]
            )),
        ]

        for check_name, result in checks:
            if not result:
                logger.warning(f"GuardAgent: {check_name} out of bounds")
                return False

        return True

    def validate_strategy_logic(self, code: str) -> bool:
        """
        Prevent agent from modifying strategy logic.

        Safe changes:
        - Parameter values in config.yaml
        - Weights/thresholds

        Forbidden changes:
        - core algorithm modifications
        - order execution logic
        - risk gate calculations
        """

        forbidden_patterns = [
            r"def (entry_signal|exit_signal|position_sizing)",  # Core logic
            r"order_manager\.",  # Execution
            r"risk_gate\.",  # Risk controls
            r"open_positions = \d+",  # Hardcoded values
        ]

        for pattern in forbidden_patterns:
            if re.search(pattern, code):
                logger.error(f"GuardAgent: Forbidden modification detected: {pattern}")
                return False

        return True
```

### 5.2 Proposal & Approval Workflow

**File:** `app/approval_workflow.py` (NEW)

```python
class ApprovalWorkflow:
    """
    Multi-level approval system for agent-generated changes.

    Level 1: Auto-approve (low risk, high confidence)
    Level 2: Discord notification (human review, 24h window)
    Level 3: Manual approval required (high risk)
    """

    async def propose_change(
        self,
        hypothesis: str,
        new_params: dict,
        validation: BacktestResult,
        change_type: str = "parameter_tune"  # or "strategy_logic"
    ) -> bool:
        """
        Propose a change. Returns True if approved, False if rejected.
        """

        # Calculate risk score
        risk_score = self._calculate_risk_score(
            new_params=new_params,
            change_type=change_type,
            validation=validation
        )

        if risk_score < 0.2:  # Low risk
            # Auto-approve
            await self._deploy_change(new_params)
            await notify_discord(
                f"✅ Agent auto-approved: {hypothesis}\n"
                f"Sharpe improvement: +{validation.sharpe_improvement:.3f}"
            )
            return True

        elif risk_score < 0.6:  # Medium risk
            # Queue for human review, wait 24h
            change_id = str(uuid.uuid4())
            await self.state_store.queue_for_review(
                change_id=change_id,
                hypothesis=hypothesis,
                new_params=new_params,
                validation=validation,
                risk_score=risk_score
            )
            await notify_discord(
                f"⚠️ Pending approval (24h window): {hypothesis}\n"
                f"Risk score: {risk_score:.1%}\n"
                f"To approve: `/approve {change_id}`"
            )

            # Wait for approval
            approval = await self.wait_for_approval(change_id, timeout_hours=24)
            if approval:
                await self._deploy_change(new_params)
                return True
            else:
                await notify_discord(f"❌ Approval denied/timeout: {change_id}")
                return False

        else:  # High risk
            # Reject automatically
            await notify_discord(
                f"🚫 Rejected (too risky): {hypothesis}\n"
                f"Risk score: {risk_score:.1%}"
            )
            return False

    def _calculate_risk_score(
        self,
        new_params: dict,
        change_type: str,
        validation: BacktestResult
    ) -> float:
        """
        Scores risk on 0-1 scale.

        Factors:
        - Parameter deviation from baseline (0.3 weight)
        - Validation dataset size (0.2 weight)
        - Out-of-sample stability (0.3 weight)
        - Max drawdown increase (0.2 weight)
        """

        baseline = self.config.get_baseline_params()

        # Factor 1: Parameter deviation
        param_deviation = np.mean([
            abs(new_params.get(k, v) - v) / (v or 1)
            for k, v in baseline.items()
            if k in new_params
        ])
        param_risk = min(param_deviation, 1.0)  # Cap at 1.0

        # Factor 2: Validation data size (more data = lower risk)
        validation_size_risk = max(0, (7 - validation.days_tested) / 7)

        # Factor 3: Out-of-sample stability
        stability_risk = 1.0 - validation.oos_stability_score

        # Factor 4: Max drawdown
        mdd_increase = max(0, validation.max_dd - self.config.max_dd)
        mdd_risk = min(mdd_increase / self.config.max_dd, 1.0)

        # Weighted combination
        risk_score = (
            0.3 * param_risk +
            0.2 * validation_size_risk +
            0.3 * stability_risk +
            0.2 * mdd_risk
        )

        return risk_score
```

### 5.3 Deployment Pipeline

```python
class DeploymentPipeline:
    """
    Multi-stage deployment: Shadow → Paper → Live
    """

    async def deploy_params(self, new_params: dict, auto_approve: bool = False):
        """
        Orchestrates safe parameter deployment.
        """

        # Stage 1: Shadow (1 day)
        # Strategy trades with new params, but doesn't execute orders
        await self.start_shadow_mode(new_params, duration_hours=24)
        await notify_discord(f"🔵 Shadow mode started with new params")

        await asyncio.sleep(86400)  # 24 hours

        shadow_result = await self.get_shadow_metrics()
        if shadow_result.sharpe_improvement < 0:
            await notify_discord("❌ Shadow mode showed negative performance, aborting")
            return False

        # Stage 2: Paper Trading (3 days)
        # Strategy places real orders on paper account
        await self.start_paper_mode(new_params, duration_hours=72)
        await notify_discord(f"🟡 Paper mode started (3 days)")

        await asyncio.sleep(3 * 86400)  # 3 days

        paper_result = await self.get_paper_metrics()
        if paper_result.sharpe_improvement < -0.05:  # Allow small variance
            await notify_discord("❌ Paper mode underperformed, aborting")
            return False

        # Stage 3: Live Deployment
        # Parameters go live with reduced position size (50% of normal)
        await self.deploy_to_live(new_params, size_reduction=0.5)
        await notify_discord(
            f"🟢 Live deployment with 50% sizing\n"
            f"Shadow Sharpe: {shadow_result.sharpe:.2f}\n"
            f"Paper Sharpe: {paper_result.sharpe:.2f}"
        )

        # Monitor for 7 days at 50% size
        await self.monitor_live(duration_hours=168)

        live_result = await self.get_live_metrics()
        if live_result.sharpe_improvement > 0:
            # Scale up to 100%
            await self.scale_to_full_size(new_params)
            await notify_discord("📈 Scaling to 100% size - parameter improvement confirmed")
            return True
        else:
            # Rollback
            await self.rollback_params()
            await notify_discord("⏮️ Rolled back params due to live underperformance")
            return False
```

---

## 6. Weekly & Monthly Review Cycles

### 6.1 Weekly Human Review

**Scheduled:** Every Sunday 9am KST

```python
class WeeklyReview:
    """
    Human reviews all autonomous changes made during the week.
    """

    async def generate_weekly_report(self):
        """Called every Sunday."""

        # Fetch all changes made this week
        changes = await self.state_store.get_changes_this_week()

        report = {
            "changes_made": len(changes),
            "auto_approved": len([c for c in changes if c.auto_approved]),
            "human_approved": len([c for c in changes if c.human_approved]),
            "rejected": len([c for c in changes if c.rejected]),
            "total_sharpe_improvement": sum(c.sharpe_improvement for c in changes),
            "total_mdd_increase": sum(c.mdd_increase for c in changes),
            "details": []
        }

        for change in changes:
            report["details"].append({
                "date": change.date,
                "hypothesis": change.hypothesis,
                "params_changed": change.param_summary,
                "sharpe_change": change.sharpe_improvement,
                "status": change.status,  # auto_approved, human_approved, rejected, reverted
            })

        # Post to Discord
        await self._post_review_to_discord(report)

        # Suggest: revert any changes that didn't work out
        underperforming = [c for c in changes if c.sharpe_improvement < -0.05]
        if underperforming:
            await notify_discord(
                f"⚠️ {len(underperforming)} changes underperformed. "
                f"Suggest review and potential revert."
            )

class MonthlyStrategicReview:
    """
    Deep analysis of agent's improvement quality.
    Used to adjust guardrails for next month.
    """

    async def analyze_month(self):
        """Called 1st of month."""

        # Metrics
        autonomous_changes = await self.get_changes_this_month()
        baseline_sharpe = self.config.baseline_sharpe
        improved_sharpe = await self.get_current_sharpe()

        analysis = {
            "sharpe_improvement": improved_sharpe - baseline_sharpe,
            "num_changes": len(autonomous_changes),
            "success_rate": len([c for c in autonomous_changes if c.success]) / len(autonomous_changes),
            "avg_time_to_value": np.mean([c.time_to_value_days for c in autonomous_changes]),
            "rollback_count": len([c for c in autonomous_changes if c.reverted]),
            "rollback_rate": len([c for c in autonomous_changes if c.reverted]) / len(autonomous_changes),
        }

        # Recommendations
        recommendations = []

        if analysis["sharpe_improvement"] > 0.3:
            recommendations.append("✅ Agent performing well. Consider increasing mutation rate.")

        if analysis["rollback_rate"] > 0.2:
            recommendations.append("⚠️ High rollback rate. Tighten guardrails or reduce change aggressiveness.")

        if analysis["success_rate"] < 0.4:
            recommendations.append("❌ Low success rate. Review hypothesis generation quality.")

        # Post findings
        await notify_discord(f"""
        **Monthly Agent Performance Review**

        Sharpe Improvement: {analysis["sharpe_improvement"]:+.2f}
        Changes Made: {analysis["num_changes"]}
        Success Rate: {analysis["success_rate"]:.1%}
        Rollback Rate: {analysis["rollback_rate"]:.1%}

        Recommendations:
        {chr(10).join(f'- {r}' for r in recommendations)}
        """)
```

---

## 7. Implementation Roadmap

### Phase 1: Development Loop (Weeks 1-2)
- [ ] Implement Tier 1: Enhanced journal + metrics stream
- [ ] Implement Tier 2: AutoResearcher basic (reflection + hypothesis)
- [ ] Manual parameter testing
- [ ] Use `/loop 15m python scripts/auto_research.py`

**Cost:** $10-20/week

### Phase 2: Supervised Autonomous (Weeks 3-6)
- [ ] Implement GuardAgent + validation
- [ ] Implement ApprovalWorkflow
- [ ] Auto-approve low-risk changes
- [ ] Daily synthesis + approval queue
- [ ] Use Cloud tasks: nightly optimization

**Cost:** $30-50/week

### Phase 3: Production Autonomous (Weeks 7+)
- [ ] Implement TradingGroup reflection
- [ ] Integrate DarwinEngine autonomous loop
- [ ] Multi-stage deployment (shadow → paper → live)
- [ ] Weekly human review ritual
- [ ] Monthly strategic analysis

**Cost:** $50-100/week

---

## 8. Metrics & Monitoring

### Agent Health Metrics

| Metric | Target | Frequency |
|--------|--------|-----------|
| Hypothesis quality | >70% of hypotheses → +5% improvement | Daily |
| Parameter validation stability | >85% in-sample ≈ out-of-sample | Daily |
| Auto-approval rate | 20-40% of changes | Weekly |
| Rollback rate | <10% of deployed changes | Weekly |
| Convergence speed | <10 iterations to find improvement | Daily |
| Total sharpe improvement | +0.2-0.5 per month (decreasing) | Monthly |

### Safety Metrics

| Metric | Target | Frequency |
|--------|--------|-----------|
| Constraint violations | 0 | Continuous |
| Max drawdown from agent changes | <+5% from baseline | Daily |
| Parameter drift | <20% from baseline | Weekly |
| All changes logged in git | 100% | Continuous |
| Human approval time | <24h for review queue | Daily |

---

## 9. Discord Commands for Management

```
/approve <change_id>          # Approve pending change
/reject <change_id>           # Reject pending change
/rollback <change_id>         # Revert deployed change
/pause-agent                  # Pause autonomous improvements
/resume-agent                 # Resume autonomous improvements
/agent-status                 # Show current agent state + queue
/weekly-review                # Force weekly review report
/monthly-review               # Force monthly strategic review
```

---

## 10. Conclusion

This architecture enables **safe, measurable, autonomous improvement** by:

1. **Observing:** Real-time metrics + trade classification
2. **Analyzing:** LLM-driven reflection + hypothesis generation
3. **Executing:** Guard-rail protected, multi-stage deployment
4. **Reviewing:** Weekly human oversight + monthly strategic assessment

Expected outcome: **+20-50% Sharpe improvement over 3 months**, stabilizing at +5-10% by month 6+.

Key success factor: **Measurable feedback** at every stage. If you can't quantify it, the agent can't optimize it.
