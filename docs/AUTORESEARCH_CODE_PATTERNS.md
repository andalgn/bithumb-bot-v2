# AutoResearch Code Patterns & Implementation Guide

**For:** Bithumb Trading Bot Integration
**Context:** Three-file minimal autoresearch pattern adapted for strategy optimization

---

## Pattern 1: The Immutable Evaluation Function

### Why This Pattern Works

The evaluation function (in `prepare.py`) is the **ground truth** that prevents agents from cheating. It cannot be edited, modified, or circumvented.

```python
# backtest_prepare.py — LOCKED, IMMUTABLE
# No agent touches this file ever

import numpy as np
from datetime import datetime, timedelta

# Fixed constants
TIME_BUDGET = 60  # seconds per backtest
VALIDATION_START = datetime(2025, 1, 1)
VALIDATION_END = datetime(2025, 2, 1)
TEST_COIN_UNIVERSE = ["BTC", "ETH", "XRP", "SOL", "RENDER", "VIRTUAL", "EIGEN", "ONDO", "TAO", "LDO"]

# Fixed data source
MARKET_DATA_PATH = "data/market_data_cached_2_years.parquet"

def load_market_data():
    """Load and cache 2 years of OHLCV data.

    Deterministic: Always returns same data in same order.
    Non-negotiable: Agent cannot request different coins/dates.
    """
    import pandas as pd
    df = pd.read_parquet(MARKET_DATA_PATH)
    # Filter to coins and validation period only
    df = df[
        (df['coin'].isin(TEST_COIN_UNIVERSE)) &
        (df['timestamp'] >= VALIDATION_START) &
        (df['timestamp'] < VALIDATION_END)
    ]
    return df

def evaluate_sharpe(trades_list: list) -> float:
    """Compute Sharpe ratio from trade list.

    This is the ONLY metric the optimization loop sees.
    Agent cannot change this function.

    Args:
        trades_list: List of dicts with keys ['entry_price', 'exit_price', 'entry_time', 'exit_time']

    Returns:
        Sharpe ratio (higher is better)
    """
    if not trades_list:
        return -999.0  # No trades = fail

    # Compute daily returns
    daily_returns = {}
    for trade in trades_list:
        pnl = trade['exit_price'] - trade['entry_price']
        pnl_pct = pnl / trade['entry_price']

        date_key = trade['exit_time'].date()
        if date_key not in daily_returns:
            daily_returns[date_key] = []
        daily_returns[date_key].append(pnl_pct)

    # Aggregate to daily
    daily_pnl = [sum(pnls) for pnls in daily_returns.values()]

    if len(daily_pnl) < 2:
        return -999.0  # Not enough data

    # Sharpe = mean / std * sqrt(252)
    mean_return = np.mean(daily_pnl)
    std_return = np.std(daily_pnl)

    if std_return == 0:
        return 0.0

    sharpe = (mean_return / std_return) * np.sqrt(252)
    return sharpe

def evaluate_mdd(trades_list: list) -> float:
    """Maximum drawdown - used as constraint, not primary metric.

    Args:
        trades_list: List of trades

    Returns:
        MDD as percentage (e.g., -0.15 for -15%)
    """
    if not trades_list:
        return 0.0

    cumulative_pnl = 0.0
    peak_pnl = 0.0
    max_dd = 0.0

    for trade in sorted(trades_list, key=lambda t: t['exit_time']):
        pnl = trade['exit_price'] - trade['entry_price']
        cumulative_pnl += pnl

        if cumulative_pnl > peak_pnl:
            peak_pnl = cumulative_pnl

        drawdown = (cumulative_pnl - peak_pnl) / peak_pnl if peak_pnl > 0 else 0.0
        max_dd = min(max_dd, drawdown)

    return max_dd

def evaluate_profit_factor(trades_list: list) -> float:
    """Profit factor = gross wins / gross losses.

    Used as constraint: must be > 1.5
    """
    if not trades_list:
        return 0.0

    gross_wins = 0.0
    gross_losses = 0.0

    for trade in trades_list:
        pnl = (trade['exit_price'] - trade['entry_price']) * trade.get('quantity', 1)
        if pnl > 0:
            gross_wins += pnl
        else:
            gross_losses += abs(pnl)

    if gross_losses == 0:
        return 999.0  # All winning trades

    return gross_wins / gross_losses
```

### Key Properties

1. **Read-only:** No agent modifies this
2. **Deterministic:** Same input = same output
3. **Fast:** Completes in milliseconds
4. **Clear boundaries:** Takes trades list, returns metric
5. **Version-locked:** Change only when you understand implications

---

## Pattern 2: The Single Editable Parameter File

### Unconstrained Search Space

Everything the agent can modify lives in ONE file:

```python
# strategy_params.py — EDITABLE BY AGENT ONLY
# Agent can change any number/value here
# Must maintain valid Python syntax

# ============================================================================
# STRATEGY PARAMETERS — Agent optimizes these
# ============================================================================

# Momentum ranking (which coins to trade)
MOMENTUM_RANK_WINDOW = 20  # bars to lookback for momentum
MOMENTUM_RANK_WEIGHT = 0.6  # 0.0-1.0, influence on coin selection

# Regime classification (bullish/bearish/sideways)
REGIME_THRESHOLD = 0.5  # crossover threshold for regime detector
REGIME_LOOKBACK = 100  # bars for regime calculation

# Position sizing
ATR_SCALING_FACTOR = 2.0  # ATR multiple for position size
BASE_POSITION_PCT = 0.05  # 5% per position
MAX_POSITION_SIZE = 0.08  # never exceed 8%
MIN_POSITION_SIZE = 0.01  # minimum 1%

# Pool rebalancing
POOL_REBALANCE_FREQ = 12  # hours between rebalance
CORRELATION_CUTOFF = 0.7  # max allowed correlation

# Entry signal (indicators)
RSI_OVERSOLD = 30  # entry if RSI < this
RSI_OVERBOUGHT = 70  # avoid entry if RSI > this
ATR_MIN_THRESHOLD = 0.02  # minimum volatility required

# Exit logic
TAKE_PROFIT_ATR_MULT = 2.5  # exit target = entry + ATR * this
STOP_LOSS_ATR_MULT = 1.0  # stop loss = entry - ATR * this
TRAILING_STOP_PERCENT = 0.03  # trail profit by 3%

# Risk gates
MAX_DAILY_LOSS_PCT = -0.04  # kill switch if down 4% in day
DRAWDOWN_KILL_SWITCH = -0.15  # stop trading if DD > -15%
MAX_CONCURRENT_POSITIONS = 5  # never open > 5 positions

# ============================================================================
# Agent can edit ANY of the above.
# Agent cannot add new parameters (would break prepare.py).
# Agent cannot change default_coin_universe (that's a constant).
# ============================================================================

# DO NOT EDIT BELOW (for reference, from prepare.py)
DEFAULT_COIN_UNIVERSE = ["BTC", "ETH", "XRP", "SOL", "RENDER", "VIRTUAL", "EIGEN", "ONDO", "TAO", "LDO"]
```

### Constraints Built Into The System

```python
# backtest_prepare.py also imports from strategy_params
# and validates constraints

from strategy_params import *

def validate_parameters():
    """Ensure parameters are reasonable.

    This runs before backtest. If it fails, experiment is rejected.
    """
    assert 0 <= MOMENTUM_RANK_WEIGHT <= 1.0, "MOMENTUM_RANK_WEIGHT must be 0-1"
    assert MOMENTUM_RANK_WINDOW >= 5, "MOMENTUM_RANK_WINDOW must be >= 5"
    assert 0 < ATR_SCALING_FACTOR <= 10.0, "ATR_SCALING_FACTOR out of bounds"
    assert 0 < BASE_POSITION_PCT <= 0.5, "BASE_POSITION_PCT too large"
    assert MAX_POSITION_SIZE <= 0.25, "MAX_POSITION_SIZE cannot exceed 25%"
    assert DRAWDOWN_KILL_SWITCH >= -0.50, "DRAWDOWN_KILL_SWITCH too loose"
    assert MAX_CONCURRENT_POSITIONS >= 1 and MAX_CONCURRENT_POSITIONS <= 10, "Position limit invalid"
    # ... more validation ...
```

---

## Pattern 3: The Program.md Strategy Document

### Human-Edited, Agent-Readable Directions

```markdown
# Bithumb Trading Strategy Optimization

## Objective
Maximize Sharpe ratio while maintaining:
- Maximum drawdown: NO WORSE than -15%
- Profit factor: >= 1.5
- Consecutive losing days: < 5

## Success Criteria
- **Primary:** Rolling 30-day Sharpe > 1.0
- **Constraint 1:** MDD >= -15% (red line)
- **Constraint 2:** Profit Factor >= 1.5
- **Constraint 3:** Must hold for 2+ weeks out-of-sample

## Constraints (Do NOT modify)
- Cannot edit `backtest_prepare.py`
- Cannot add new Python imports
- Cannot modify `DEFAULT_COIN_UNIVERSE`
- Cannot run backtests longer than 60 seconds
- Must maintain valid Python syntax

## What Has Been Tried (Lessons Learned)

### Attempt 1-5: Learning Rate Tuning
- Tried MOMENTUM_RANK_WEIGHT: 0.5 → 0.9
- Result: +0.02 Sharpe improvement (marginal)
- Insight: Coin selection less important than entry/exit logic

### Attempt 6-15: Regime Threshold Exploration
- Tried REGIME_THRESHOLD: 0.3 → 0.8
- Result: Best at 0.5, symmetric around center
- Insight: Bull/bear detection needs tuning per coin pairs

### Attempt 16-25: ATR Scaling
- Tried ATR_SCALING_FACTOR: 1.0 → 3.5
- Result: 2.0 optimal, diminishing returns above 2.2
- Insight: Too large positions → drawdown hits constraint quickly

### Attempt 26-35: Exit Logic
- Tried TAKE_PROFIT_ATR_MULT: 2.0 → 4.0
- Result: 2.5 is sweet spot; larger targets = fewer wins
- Insight: Exit timing matters more than entry selection

## Current Hypotheses (Worth Exploring)

### Hypothesis 1: Regime-Aware Positioning
**Idea:** Use different position sizes in bull vs bear regimes
**Why:** Current code uses same max size always; could be too aggressive in bear

**To test:**
```python
# Pseudo-code for agent
if REGIME == BULL:
    MAX_POSITION_SIZE = 0.08
elif REGIME == BEAR:
    MAX_POSITION_SIZE = 0.04  # smaller in bear
```

### Hypothesis 2: Adaptive ATR Thresholds
**Idea:** Entry signal depends on regime volatility
**Why:** RSI_OVERSOLD = 30 always; but 30 RSI in low volatility different than high volatility

**To test:**
```python
# Adaptive threshold
if current_volatility < historical_volatility * 0.5:
    RSI_OVERSOLD = 25  # more lenient in low vol
else:
    RSI_OVERSOLD = 35  # more strict in high vol
```

### Hypothesis 3: Pool Rebalance Frequency
**Idea:** Rebalance more often in volatile periods
**Why:** Current POOL_REBALANCE_FREQ = 12h always; maybe should adapt

**To test:**
Try: 6h, 8h, 12h, 24h cycles and measure Sharpe

### Hypothesis 4: Multi-Timeframe Confirmation
**Idea:** Require signal on multiple timeframes before entry
**Why:** Single 15M signal = noise; 15M + 1H confirmation = more robust

## Search Strategy Going Forward

**Phase 1 (Iterations 1-30):** Fine-tune entry/exit parameters
- RSI thresholds
- ATR multiples
- Take profit targets

**Phase 2 (Iterations 31-60):** Regime adaptation
- Different parameters for bull/bear/sideways
- Measure Sharpe in each regime separately

**Phase 3 (Iterations 61-100):** Risk management
- Drawdown limits
- Consecutive loss handling
- Position size decay on losses

**Phase 4 (Beyond 100):** Validation
- Out-of-sample testing on held-out month
- Walk-forward backtesting
- Live paper trading comparison

## Important Notes

- Experiments run in 60 seconds max
- Each experiment is ONE change only
- If Sharpe goes down OR MDD hits -15%+: revert
- If profitable but new MDD worse: evaluate tradeoff
- Log what you tried and why
```

### Key Points

1. **Narrative style** — Not a YAML config, but strategy document
2. **Hypothesis sections** — Give agent ideas to test (or it generates own)
3. **Lessons learned** — Agent can read what failed before, avoid retrying
4. **Search strategy** — Structure the phases so agent doesn't wander
5. **Success criteria** — Crystal clear what "winning" means

---

## Pattern 4: The Keep/Revert Experiment Loop

### Pseudocode for the Agent's Main Loop

```python
# This is what the agent executes repeatedly (100 times overnight)

while num_iterations < 100:
    # ========================================================================
    # STEP 1: Understand current state
    # ========================================================================
    current_best_sharpe = read_last_committed_metric()
    git_log = get_git_history()  # last 10 commits
    program_md = read("optimization_program.md")  # human guidance
    current_params = read("strategy_params.py")  # as Python dict

    # ========================================================================
    # STEP 2: Form a hypothesis
    # ========================================================================
    hypothesis = form_hypothesis(
        current_params,           # what's currently set
        git_log,                  # what was tried before
        program_md,               # human guidance
        current_best_sharpe       # how close to goal
    )
    # Example hypothesis:
    # {
    #   'param': 'ATR_SCALING_FACTOR',
    #   'old_value': 2.0,
    #   'new_value': 2.1,
    #   'reasoning': 'Small increase to capture more trades without hitting MDD'
    # }

    # ========================================================================
    # STEP 3: Modify code (ONE change only)
    # ========================================================================
    modify_file(
        "strategy_params.py",
        find=f"{hypothesis['param']} = {hypothesis['old_value']}",
        replace=f"{hypothesis['param']} = {hypothesis['new_value']}"
    )

    # Validate syntax
    try:
        compile(open("strategy_params.py").read(), "strategy_params.py", "exec")
    except SyntaxError:
        undo_change()
        continue  # try next hypothesis

    # ========================================================================
    # STEP 4: Commit change BEFORE testing
    # ========================================================================
    git_commit(
        message=f"experiment: {hypothesis['param']} {hypothesis['old_value']} -> {hypothesis['new_value']}\n"
                f"Reasoning: {hypothesis['reasoning']}"
    )

    # ========================================================================
    # STEP 5: Run backtest (time-boxed to 60 seconds)
    # ========================================================================
    start_time = time.time()
    result = run_backtest()  # calls prepare.py
    elapsed = time.time() - start_time

    if elapsed > 60:
        # Backtest took too long
        git_reset_hard()
        continue

    if result.has_error:
        # Backtest crashed
        git_reset_hard()
        continue

    # ========================================================================
    # STEP 6: Evaluate metric
    # ========================================================================
    new_sharpe = result.sharpe
    new_mdd = result.mdd
    new_profit_factor = result.profit_factor

    # ========================================================================
    # STEP 7: DECIDE: Keep or Revert
    # ========================================================================
    improvement = (
        new_sharpe >= current_best_sharpe  # Sharpe not worse
        and new_mdd >= -0.15               # MDD constraint respected
        and new_profit_factor >= 1.5       # Min profitability
    )

    if improvement:
        # KEEP: advance the branch
        log(f"✓ KEEP: {hypothesis['param']} -> {hypothesis['new_value']} "
            f"(Sharpe: {current_best_sharpe:.2f} -> {new_sharpe:.2f})")
        current_best_sharpe = new_sharpe
        # Don't reset; current commit stays
    else:
        # REVERT: undo the change
        log(f"✗ REVERT: {hypothesis['param']} -> {hypothesis['new_value']} "
            f"(Sharpe would be {new_sharpe:.2f}, MDD {new_mdd:.2f}, PF {new_profit_factor:.2f})")
        git_reset_hard()

    num_iterations += 1

# ============================================================================
# END OF NIGHT
# ============================================================================
final_sharpe = read_last_committed_metric()
git_log_summary = get_git_log_summary()
notify_user(
    f"AutoResearch complete. {num_iterations} experiments. "
    f"Best Sharpe: {final_sharpe:.2f}\n\n{git_log_summary}"
)
```

### Key Properties

1. **Atomic:** One change per iteration
2. **Reversible:** git reset --hard always available
3. **Measurable:** Exact metric evaluation each time
4. **Logged:** Every attempt in git history
5. **Bounded:** Tight time constraint (60 seconds per backtest)

---

## Pattern 5: Git Commit Message Format

### Structured Logging for Agent Learning

```bash
# Good: Clear, parseable by agent in next iteration
git commit -m "experiment: ATR_SCALING_FACTOR 2.0 -> 2.1
Target: Increase position sizing without hitting MDD limit
Result: Sharpe 0.92 (no improvement), reverted"

# Bad: Too vague
git commit -m "tried something"

# Good: Shows reasoning
git commit -m "experiment: MOMENTUM_RANK_WEIGHT 0.6 -> 0.7
Hypothesis: Higher weight on momentum would catch trend starts earlier
Result: Sharpe 0.89 -> 0.91 (+0.02), kept
Note: Also reduced consecutive losses from 4 to 3 days"

# Good: Shows constraint interaction
git commit -m "experiment: MAX_POSITION_SIZE 0.08 -> 0.10
Hypothesis: Larger positions = higher returns
Result: Sharpe improved to 0.95 BUT MDD hit -16.2% (constraint violated)
Decision: Reverted to stay within -15% MDD limit"
```

### Commit Message Parsing Pattern

```python
def parse_commit_message(msg: str) -> dict:
    """Agent reads its own commit history.

    Format:
    experiment: PARAM old_val -> new_val
    Hypothesis: ...
    Result: ...
    """
    lines = msg.split('\n')

    # Line 0: "experiment: PARAM old_val -> new_val"
    # Extract param name, old/new values

    # Remaining: free-form text, but with key sections:
    # "Hypothesis:" - what was expected
    # "Result:" - what actually happened

    return {
        'param': ...,
        'old_value': ...,
        'new_value': ...,
        'hypothesis': ...,
        'result': ...,
        'outcome': 'kept' or 'reverted'
    }
```

---

## Pattern 6: Multi-Metric Validation (Preventing Overfitting)

### Gating Logic with Multiple Constraints

```python
def should_keep_experiment(
    new_sharpe: float,
    new_mdd: float,
    new_profit_factor: float,
    new_consecutive_losses: int,
    last_best_sharpe: float,
    experiment_number: int
) -> bool:
    """Strict gating logic to prevent overfitting.

    Args:
        new_sharpe: Sharpe ratio from this experiment
        new_mdd: Maximum drawdown
        new_profit_factor: Gross wins / gross losses
        new_consecutive_losses: Longest losing streak
        last_best_sharpe: Best Sharpe seen so far
        experiment_number: Which iteration (1-100)

    Returns:
        True = keep change, False = revert
    """

    # GATE 1: Must not regress on Sharpe
    if new_sharpe < last_best_sharpe:
        reason = f"Sharpe {new_sharpe:.2f} < {last_best_sharpe:.2f}"
        return False, reason

    # GATE 2: Must respect MDD constraint (hard limit)
    if new_mdd < -0.15:
        reason = f"MDD {new_mdd:.2f} violates -15% limit"
        return False, reason

    # GATE 3: Must maintain profitability
    if new_profit_factor < 1.5:
        reason = f"Profit Factor {new_profit_factor:.2f} < 1.5"
        return False, reason

    # GATE 4: Consecutive losses (soft, informational)
    if new_consecutive_losses > 5:
        log.warning(f"High consecutive losses: {new_consecutive_losses} days")
        # Don't reject, just warn

    # GATE 5: Frequent checkpoints (every 10 experiments)
    if experiment_number % 10 == 0:
        out_of_sample_sharpe = validate_on_holdout_month()
        if out_of_sample_sharpe < 0.5:
            reason = f"Out-of-sample Sharpe only {out_of_sample_sharpe:.2f} (overfitting?)"
            return False, reason

    return True, "All gates passed"
```

### Out-of-Sample Checkpoint Pattern

```python
def validate_on_holdout_month():
    """Every 10 experiments, validate on held-out month.

    This is the VALIDATION SET the agent never trains on.
    """

    from backtest_prepare import VALIDATION_START, VALIDATION_END
    from backtest_prepare import evaluate_sharpe

    # Load separate data (never seen by agent)
    validation_data = load_data(
        start=VALIDATION_START,
        end=VALIDATION_END
    )

    # Run strategy with current params
    trades = backtest(validation_data)

    # Compute Sharpe on this held-out data
    validation_sharpe = evaluate_sharpe(trades)

    return validation_sharpe
```

---

## Pattern 7: Scaling from 1 GPU to 16 GPUs

### Parallel Factorial Grids (Not Sequential Hill-Climbing)

```python
# When you have multiple GPUs, DON'T do sequential optimization
# Instead, test multiple hypotheses in parallel

def generate_experiment_wave(
    base_params: dict,
    focus_area: str,
    num_gpus: int = 16
) -> list:
    """Generate N experiments to run in parallel.

    With 16 GPUs, you can test factorial grids:
    3 values of ATR × 4 values of momentum weight × 2 values of regime threshold = 24 experiments
    """

    experiments = []

    if focus_area == "position_sizing":
        for atr_scaling in [1.8, 2.0, 2.2]:
            for base_pos_pct in [0.04, 0.05, 0.06, 0.07]:
                params = base_params.copy()
                params['ATR_SCALING_FACTOR'] = atr_scaling
                params['BASE_POSITION_PCT'] = base_pos_pct
                experiments.append(params)

    elif focus_area == "regime_awareness":
        for regime_threshold in [0.3, 0.5, 0.7]:
            for regime_window in [50, 100, 150]:
                params = base_params.copy()
                params['REGIME_THRESHOLD'] = regime_threshold
                params['REGIME_LOOKBACK'] = regime_window
                experiments.append(params)

    return experiments[:num_gpus]  # Take only as many as GPUs available

# Agent orchestrates:
# 1. Generate 16 parameter sets (covering interactions)
# 2. Launch on 16 GPUs in parallel
# 3. Wait 60 seconds for all to finish
# 4. Evaluate all 16 results
# 5. Decide which interactions work
# 6. Advance with best configuration
```

### Key Insight from SkyPilot Scaling

> "With parallel exploration, the agent can run full factorial grids — test 3 values of weight decay × 4 values of learning rate = 12 experiments in a single 5-minute wave. This enables discovery of parameter interactions that sequential search would miss."

---

## Summary: The Complete Loop

```
┌─────────────────────────────────────────────────────────┐
│ Human-Driven (Once Per Week)                            │
│                                                          │
│ 1. Edit optimization_program.md                         │
│ 2. Add new hypotheses                                   │
│ 3. Review previous week's discoveries                   │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│ AutoResearch Loop (Nightly, 100 Iterations)             │
│                                                          │
│ 1. Read program.md + git log + current params           │
│ 2. Form hypothesis (one parameter change)               │
│ 3. Modify strategy_params.py                            │
│ 4. Git commit (before testing)                          │
│ 5. Backtest in 60 seconds                               │
│ 6. Evaluate: Sharpe ↑ AND MDD ≥ -15% AND PF ≥ 1.5?     │
│ 7. If YES: keep / If NO: git reset                      │
│ 8. Loop 100 times overnight                             │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│ Weekly Validation                                       │
│                                                          │
│ 1. Every 10 experiments: validate on holdout month      │
│ 2. Monthly: full walk-forward on unseen data            │
│ 3. Compare vs. control/baseline parameters              │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│ Darwin Engine Integration                               │
│                                                          │
│ 1. Analyze week's trade failures                        │
│ 2. Generate new hypotheses for next program.md          │
│ 3. Feed into next week's AutoResearch                   │
└─────────────────────────────────────────────────────────┘
```

This pattern scales from 1 GPU overnight to 16 GPUs in 8 hours, with the agent automatically discovering parameter interactions and hardware optimization strategies.
