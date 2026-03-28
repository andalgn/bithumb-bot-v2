# Darwin Engine & Auto-Evolution Architecture - Actionable Improvements

**For:** bithumb-bot-v2 Darwinian self-learning system
**Date:** 2026-03-28
**Status:** Research-informed implementation roadmap

---

## Current State Assessment

Your architecture already has:
- ✓ **Darwin Engine:** Multi-armed bandit variant selection
- ✓ **AutoResearcher:** Parameter variant generation
- ✓ **Feedback Loop:** Trade failure clustering
- ✓ **Promotion Manager:** Variant advancement with thresholds

**Missing / Underdeveloped:**
- [ ] Walk-forward validation (critical gap)
- [ ] Overfitting detection metrics
- [ ] Paper trading validation (14-28 days)
- [ ] Discrete retraining schedule (vs. continuous)
- [ ] Hard risk limits at execution layer

---

## Priority 1: Implement Walk-Forward Validation

**Why:** Every successful system has this. Backtest Sharpe without it = meaningless.

**Implementation:**
```python
# Pseudocode
class WalkForwardValidator:
    def __init__(self, window_size=60, step_size=10, lookback=90):
        self.window_size = window_size  # 60 days in-sample
        self.step_size = step_size      # 10 days out-of-sample
        self.lookback = lookback        # 90 days total

    def validate(self, strategy_params, price_data):
        """
        Returns realistic OOS performance estimate
        """
        results = []
        for i in range(0, len(price_data) - self.window_size, self.step_size):
            # In-sample: train on days [i : i+window_size]
            is_data = price_data[i : i + self.window_size]

            # Re-optimize parameters on IS data
            best_params = self.optimize(strategy_params, is_data)

            # Out-of-sample: test on next step_size days
            oos_data = price_data[i + self.window_size : i + self.window_size + self.step_size]
            oos_result = self.backtest(best_params, oos_data)

            results.append({
                'window': i,
                'params': best_params,
                'oos_sharpe': oos_result['sharpe'],
                'oos_mdd': oos_result['mdd'],
                'trade_count': oos_result['trades']
            })

        # Aggregate OOS results
        return {
            'avg_sharpe': mean([r['oos_sharpe'] for r in results]),
            'avg_mdd': mean([r['oos_mdd'] for r in results]),
            'total_trades': sum([r['trade_count'] for r in results]),
            'consistency': self.check_consistency(results)
        }

    def check_consistency(self, results):
        """
        Red flag if performance highly variable
        """
        sharpe_values = [r['oos_sharpe'] for r in results]
        std_dev = np.std(sharpe_values)
        mean_val = np.mean(sharpe_values)

        # High variability = unstable strategy
        return {
            'coefficient_of_variation': std_dev / mean_val,
            'is_stable': std_dev / mean_val < 0.3  # <30% variation = stable
        }
```

**Integration Point:**
- Run walk-forward on shadow variants weekly (not just single backtest)
- Only promote variants if:
  - OOS Sharpe > current live Sharpe
  - Consistency check passes (CoV < 0.3)
  - P-value < 0.05 (from existing promotion logic)
  - ≥100 OOS trades

---

## Priority 2: Overfitting Detection Metrics

**Add to Darwin Engine:**

```python
class OverfittingDetector:
    def detect_overfitting(self, in_sample_result, out_of_sample_result):
        """
        Red flags for overfitting
        """
        metrics = {}

        # 1. Overfitting Ratio (OR)
        or_value = out_of_sample_result['mse'] / in_sample_result['mse']
        metrics['or'] = or_value
        metrics['is_overfit_or'] = or_value > 1.3  # Red flag if >1.3

        # 2. Sharpe Collapse
        sharpe_collapse = (
            (in_sample_result['sharpe'] - out_of_sample_result['sharpe'])
            / in_sample_result['sharpe']
        )
        metrics['sharpe_collapse_pct'] = sharpe_collapse * 100
        metrics['is_overfit_sharpe'] = sharpe_collapse > 0.3  # >30% drop = red flag

        # 3. Parameter Sensitivity (run quick sensitivity analysis)
        sensitivity = self.check_parameter_sensitivity(in_sample_result['params'])
        metrics['high_sensitivity'] = sensitivity > 0.05  # 1% param change = 5% P&L = bad

        # 4. Sample Size Check
        metrics['trade_count'] = in_sample_result['trades']
        metrics['insufficient_sample'] = in_sample_result['trades'] < 100

        # 5. Equity Curve Smoothness (too smooth = overfitting)
        equity_curve_smoothness = self.check_equity_smoothness(in_sample_result['equity'])
        metrics['equity_too_smooth'] = equity_curve_smoothness > 0.95  # >95% smooth = suspicious

        # Overall verdict
        red_flags = sum([
            metrics.get('is_overfit_or'),
            metrics.get('is_overfit_sharpe'),
            metrics.get('high_sensitivity'),
            metrics.get('insufficient_sample'),
            metrics.get('equity_too_smooth')
        ])

        return {
            'metrics': metrics,
            'red_flag_count': red_flags,
            'verdict': 'SAFE' if red_flags == 0 else ('CAUTION' if red_flags <= 2 else 'REJECT')
        }
```

**Action:**
- Add to promotion logic: Reject if `verdict == 'REJECT'`
- Alert if `verdict == 'CAUTION'` (human review)
- Auto-approve if `verdict == 'SAFE'`

---

## Priority 3: Paper Trading Validation Gate

**Implementation:**
```python
class PaperTradingValidator:
    def __init__(self, min_duration=14, correlation_threshold=0.95):
        self.min_duration = min_duration  # days
        self.correlation_threshold = correlation_threshold
        self.shadow_trades = []

    def validate_before_promotion(self, variant_id, days_in_paper):
        """
        Can only promote to live after sufficient paper trading
        """
        if days_in_paper < self.min_duration:
            return {
                'status': 'BLOCKED',
                'reason': f'Insufficient paper trading ({days_in_paper}/{self.min_duration} days)',
                'ready_date': datetime.now() + timedelta(days=self.min_duration - days_in_paper)
            }

        # Correlation check: paper trading vs backtest
        paper_trades = self.get_paper_trades(variant_id)
        backtest_trades = self.get_backtest_trades(variant_id)

        if len(paper_trades) < 10:
            return {
                'status': 'BLOCKED',
                'reason': f'Too few paper trades ({len(paper_trades)} < 10)',
                'ready_date': datetime.now() + timedelta(days=7)
            }

        correlation = self.calculate_trade_correlation(paper_trades, backtest_trades)

        if correlation < self.correlation_threshold:
            return {
                'status': 'CAUTION',
                'reason': f'Low correlation between paper & backtest ({correlation:.2f})',
                'diagnostic': 'Likely look-ahead bias in backtest or slippage model mismatch',
                'correlation': correlation
            }

        return {
            'status': 'APPROVED',
            'reason': f'Paper trading validated (correlation: {correlation:.2f})',
            'ready_for_live': True
        }

    def calculate_trade_correlation(self, paper_trades, backtest_trades):
        """
        Compare actual (paper) vs expected (backtest) trade results
        """
        # Match trades by entry time
        paired_trades = self.pair_trades(paper_trades, backtest_trades)

        if not paired_trades:
            return 0.0

        paper_returns = [t['paper']['return'] for t in paired_trades]
        backtest_returns = [t['backtest']['return'] for t in paired_trades]

        return np.corrcoef(paper_returns, backtest_returns)[0, 1]
```

**Action:**
- Block promotion until min 14 days paper trading
- Check correlation before live trading
- Alert if correlation < 95%

---

## Priority 4: Discrete Retraining Schedule (Not Continuous)

**Key Finding from Research:** Freqtrade warns against continual learning. Hedge funds retrain from scratch on fixed schedule.

**Implementation:**
```python
class DiscreteRetrain Engine:
    def __init__(self):
        self.retrain_schedule = 'weekly'  # Sunday 2am UTC
        self.versions = {
            'current': {...},      # Live trading
            'previous': {...},      # Fallback 1
            'previous_prev': {...}  # Fallback 2
        }

    def should_retrain(self):
        """Check if it's time for scheduled retrain"""
        now = datetime.utcnow()
        # Trigger every Sunday at 2am UTC
        return (now.weekday() == 6 and now.hour == 2)

    def retrain_from_scratch(self):
        """
        Full retraining pipeline (not continual learning)
        """
        # 1. Gather latest 90 days of data
        market_data = self.gather_market_data(days=90)

        # 2. Generate 20-30 parameter variants
        variants = self.auto_researcher.generate_variants(count=30)

        # 3. Walk-forward validation on each
        for variant in variants:
            wf_result = self.walk_forward_validator.validate(variant, market_data)
            variant['wf_score'] = wf_result['avg_sharpe']
            variant['is_stable'] = wf_result['consistency']['is_stable']

        # 4. Rank and select top 3
        top_variants = sorted(variants, key=lambda v: v['wf_score'], desc=True)[:3]

        # 5. Rollout (keep current if top variant not significantly better)
        best_variant = top_variants[0]
        current_variant = self.versions['current']

        # Statistical test: Is new variant significantly better?
        is_significant = self.t_test(
            best_variant['wf_score'],
            current_variant['last_wf_score']
        )

        if is_significant and best_variant['is_stable']:
            # Promotion path
            self.versions['previous_prev'] = self.versions['previous']
            self.versions['previous'] = self.versions['current']
            self.versions['current'] = best_variant
            self.notify('Variant promoted to live trading', variant=best_variant)
        else:
            self.notify('No improvement, keeping current', variant=current_variant)

        return {
            'retrained': True,
            'new_best': best_variant,
            'was_promoted': is_significant and best_variant['is_stable']
        }

    def fallback_to_previous(self):
        """
        If current variant degrades, auto-fallback
        """
        if self.detect_performance_degradation():
            self.versions['current'] = self.versions['previous']
            self.notify('Fallback to previous version (performance degradation)')
```

**Schedule:**
- Weekly retrain: Sunday 2am UTC
- Do NOT retrain continuously
- Keep 3 versions with auto-fallback

---

## Priority 5: Risk Limits at Execution Layer

**Critical:** Even perfect AI can fail. Enforce hard stops before order submission.

```python
class ExecutionGate:
    def __init__(self):
        self.daily_dd_limit = 0.04  # 4%
        self.monthly_mdd_limit = 0.15  # 15%
        self.max_position_pct = 0.05  # 5% per position
        self.max_correlation = 0.70

    def validate_order(self, order):
        """
        Final gate before order submission
        Returns: (approved: bool, reason: str)
        """
        checks = {}

        # Check 1: Daily Drawdown
        daily_dd = self.calculate_daily_drawdown()
        checks['daily_dd'] = {
            'value': daily_dd,
            'passes': daily_dd < self.daily_dd_limit,
            'status': 'OK' if daily_dd < self.daily_dd_limit else 'CRITICAL - AUTO SHUTDOWN'
        }
        if daily_dd >= self.daily_dd_limit:
            return False, f'Daily DD limit exceeded: {daily_dd:.2%} >= {self.daily_dd_limit:.2%}'

        # Check 2: Monthly MDD
        monthly_mdd = self.calculate_monthly_mdd()
        checks['monthly_mdd'] = {
            'value': monthly_mdd,
            'passes': monthly_mdd < self.monthly_mdd_limit,
            'status': 'OK' if monthly_mdd < self.monthly_mdd_limit else 'CRITICAL - AUTO SHUTDOWN'
        }
        if monthly_mdd >= self.monthly_mdd_limit:
            return False, f'Monthly MDD limit exceeded: {monthly_mdd:.2%} >= {self.monthly_mdd_limit:.2%}'

        # Check 3: Position Size
        position_pct = order['amount'] / self.portfolio_value
        checks['position_size'] = {
            'value': position_pct,
            'passes': position_pct <= self.max_position_pct,
            'status': 'OK' if position_pct <= self.max_position_pct else 'REJECT'
        }
        if position_pct > self.max_position_pct:
            return False, f'Position too large: {position_pct:.2%} > {self.max_position_pct:.2%}'

        # Check 4: Correlation
        new_correlation = self.calculate_new_correlation(order['coin'])
        checks['correlation'] = {
            'value': new_correlation,
            'passes': new_correlation <= self.max_correlation,
            'status': 'OK' if new_correlation <= self.max_correlation else 'REJECT'
        }
        if new_correlation > self.max_correlation:
            return False, f'Correlation with open positions too high: {new_correlation:.2f}'

        # All checks passed
        return True, 'Order approved by execution gate'
```

**Integration:**
```python
# In order_manager.py or equivalent
def submit_order(self, order):
    # First: Validate at execution gate
    approved, reason = self.execution_gate.validate_order(order)

    if not approved:
        self.logger.warning(f'Order rejected: {reason}')
        self.notify_discord(f'⛔ Order rejected: {reason}')
        return None  # Don't submit

    # Second: Submit to exchange
    return self.exchange_api.submit(order)
```

---

## Priority 6: Weekly Review + Hypothesis Generation

**Current State:** Auto-review via code (good)
**Missing:** Human + AI review loop

**Add to weekly schedule:**
```python
class WeeklyReviewEngine:
    def __init__(self):
        self.deepseek_api = ...  # DeepSeek API
        self.discord_webhook = ...

    async def run_weekly_review(self):
        """
        Every Sunday after retrain
        """
        # 1. Gather metrics for the week
        metrics = self.gather_weekly_metrics()

        # 2. Identify regime shifts
        regime_analysis = self.analyze_regime_shift(metrics)

        # 3. Generate hypotheses via DeepSeek
        hypothesis_prompt = f"""
        Trading bot performance metrics (last 7 days):
        - Sharpe ratio: {metrics['sharpe']:.2f}
        - Win rate: {metrics['win_rate']:.1%}
        - MDD: {metrics['mdd']:.2%}
        - Trade count: {metrics['trade_count']}

        Market regime: {regime_analysis['current_regime']}
        Regime shift detected: {regime_analysis['shift_detected']}

        Suggest 3-5 parameter adjustment hypotheses to improve performance.
        Focus on: Entry criteria, exit criteria, position sizing, coin selection.
        """

        hypotheses = await self.deepseek_api.generate_text(hypothesis_prompt)

        # 4. Parse hypotheses and queue for testing
        parsed = self.parse_hypotheses(hypotheses)
        for hypo in parsed:
            self.auto_researcher.add_hypothesis(hypo)

        # 5. Send to Discord
        await self.discord_webhook.send(
            f"📊 Weekly Review Complete\n"
            f"Sharpe: {metrics['sharpe']:.2f}\n"
            f"Regime: {regime_analysis['current_regime']}\n"
            f"Generated {len(parsed)} hypotheses for testing\n"
            f"\nTop hypothesis: {parsed[0]['description']}"
        )

        return {
            'metrics': metrics,
            'regime': regime_analysis,
            'hypotheses': parsed
        }
```

---

## Implementation Checklist

**Week 1:** Foundation
- [ ] Implement `WalkForwardValidator`
- [ ] Integrate into promotion logic
- [ ] Test on historical data (non-live)

**Week 2:** Safety & Detection
- [ ] Implement `OverfittingDetector`
- [ ] Implement `ExecutionGate` with risk limits
- [ ] Deploy execution gate to live trading

**Week 3:** Paper Trading Gate
- [ ] Implement `PaperTradingValidator`
- [ ] Add to promotion workflow
- [ ] Test with real paper trading (14+ days)

**Week 4:** Discrete Retraining
- [ ] Refactor to `DiscreteRetrainEngine` (from continuous)
- [ ] Schedule weekly retrain (Sunday 2am UTC)
- [ ] Test version management + fallback

**Week 5:** Weekly Review Loop
- [ ] Implement `WeeklyReviewEngine`
- [ ] Integrate DeepSeek API
- [ ] Test hypothesis generation + queueing

---

## Risk Assessment

| Change | Risk Level | Mitigation |
|--------|-----------|-----------|
| Walk-forward validation | Low | Runs on shadow variants first, no live impact |
| Execution gate (risk limits) | Low | Only rejects unsafe orders, improves safety |
| Paper trading gate | Low | Just blocks promotion until validation |
| Discrete retraining | **Medium** | Could miss fast-moving improvements; mitigate with daily small updates |
| Weekly review loop | Low | Just generates suggestions, requires human approval |

---

## Success Metrics (6 Weeks)

- ✓ Walk-forward validation deployed and active
- ✓ Zero manual intervention needed for risk management (auto-gates work)
- ✓ All new variants validated via paper trading before live
- ✓ Weekly hypotheses generated and tested
- ✓ Sharpe ratio stable or improving
- ✓ Overfitting detected early (before live impact)

---

## Open Questions for Team

1. **Continuous vs. Discrete:** Current system uses continuous learning. How much improvement per day is "acceptable" vs. overshooting into noise?
2. **Hypothesis Testing:** Should auto-researcher generate hypotheses, or let DeepSeek suggest them?
3. **Regime Detection:** How to automatically detect regime shifts? Volatility-based? Correlation-based?
4. **Fallback Strategy:** What if all 3 versions perform poorly? Fall back to known-good version from history?

---

**Status:** Ready for implementation discussion
**Next Step:** Prioritize which to implement first based on team capacity
