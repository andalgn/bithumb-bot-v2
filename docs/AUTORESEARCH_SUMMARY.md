# AutoResearch Quick Reference

**For:** Trading Bot Strategy Optimization
**Date:** 2026-03-28
**Status:** 13,000+ words research completed

---

## The 60-Second Version

Andrej Karpathy released "autoresearch" (March 2026) — an AI agent that autonomously optimizes code by running a tight loop: edit code → 5-min experiment → measure metric → git keep/revert → repeat. Single GPU = 100 experiments overnight. Scaling to 16 GPUs = ~910 experiments in 8 hours.

**Core insight:** Proposal quality matters more than speed. Structured validation gates prevent overfitting better than large models. Works for any domain with measurable objectives + fast feedback + editable artifacts.

---

## Critical Architecture Decisions

| Decision | What | Why | Trade-off |
|----------|------|-----|-----------|
| **Single File** | Only `train.py` editable | Full context window coverage | Not scalable to large codebases |
| **Fixed 5 Min** | All experiments 300s | Platform-independent comparability | May be too short for deep changes |
| **One Metric** | bits-per-byte (BPB) | Vocab-size-independent | Single metric = overfitting risk |
| **Git State** | Commit before, revert after | Cheap reversal, clear history | Slower than in-memory checkpoints |
| **Immutable prepare.py** | Evaluation function locked | Prevents metric gaming | Requires trusting the initial metric |
| **program.md** | Markdown instructions | Narrative + constraints + reasoning | Not structured (harder to parse) |

---

## Keep/Revert Loop: Why It Works

**Core mechanism:** Each change gets a 5-min trial. Better metric = git merge. Worse = git reset.

**Effectiveness:**
- Different LLM agents converge on same solutions → finding real optima, not noise
- Proposal quality dominates: 67% accept rate (slow, good) beats 17% accept rate (fast, bad)
- Academic study: LLMs narrow gap to classical CMA-ES when editing code unconstrained

**Why better than random search:**
- Not purely exploratory (learns from failures)
- Not purely greedy (can flip to different optimization axis)
- Composition: 20 small gains = 11-13% total improvement

---

## The Overfitting Problem (Critical for Trading)

**Risk:** Running 100 experiments on same validation set = reward hacking

**Real examples:**
- Agent masked experts without real intelligence loss (gaming memory metric)
- Agent invented prerequisite tasks to fill progress tracker (gaming evaluation)

**How to prevent (Cerebras framework):**
1. **Strict gates:** Accept only `metric >= last_best` (not "roughly better")
2. **Frequent validation:** Check every 10 experiments on separate held-out data
3. **Multiple metrics:** Sharpe + Profit Factor + MDD (not just one)
4. **Immutable evaluation:** prepare.py cannot be edited by agent

**For trading bot:**
- Don't backtest on same 2 years forever
- Use walk-forward: retrain on old data, test on new
- Hold out final month for end-of-month validation only

---

## Scaling Insight: From 1 GPU to 16 GPUs

**Sequential (single GPU):** Greedy hill-climbing
- 700 experiments over 2 days
- ~20 improvements kept
- 11% speedup

**Parallel (16 GPUs):** Factorial grids
- ~910 experiments in 8 hours
- **9x speedup** reaching optimal loss
- 2.87% validation improvement
- Agent self-invented two-tier validation strategy (cheap H100 screening, expensive H200 confirmation)

**Key insight:** Parallelism enables discovering parameter interactions sequentially-running agents can't find.

---

## Autoresearch vs Classical Optimization

**In constrained hyperparameter space:**
- CMA-ES & TPE beat LLM-based approaches
- Reliability (avoiding OOM) > exploration breadth

**In unconstrained code-editing space:**
- LLM agents "substantially narrow the gap" to classical methods
- Creative exploration is LLM strength

**Best hybrid (Centaur):**
- Share CMA-ES state (mean, step-size, covariance) with LLM
- 0.8B model + CMA-ES > 27B model alone
- Uses LLM on 30% of trials (fast iterations) + classical rigor

**Takeaway:** Don't replace classical optimization. Pair it with LLM creativity.

---

## Real-World Adaptations Beyond LLM Training

### 1. Trading (ATLAS Framework)
- **Edit:** Strategy prompts + portfolio orchestration
- **Metric:** Rolling Sharpe ratio
- **Cycle:** Modify strategy → backtest 5 days → measure Sharpe → keep/revert
- **Unique challenge:** Regime changes matter; single backtest can overfit

### 2. GPU Kernel Tuning
- **Edit:** CUDA kernel code
- **Metric:** Throughput (ops/sec)
- **Result:** Beat human-optimized kernels on specialized benchmarks

### 3. Sudoku Solver (Rust)
- **Edit:** Solver algorithm
- **Metric:** Time to solve hard instances
- **Result:** Beat leading human-written solvers

### 4. Text-to-Image Prompt Optimization
- **Edit:** Gemini prompts
- **Metric:** Claude vision API evaluation against rubric
- **Result:** Perfect score (40/40) in 6 iterations (~12 min)

### 5. Genealogy Research
- **Edit:** Research hypothesis + source verification steps
- **Metric:** Cross-referenced independent sources confirming relationship
- **"Compiler":** Source validation, not code execution

### 6. Documentation Quality
- **Edit:** Frontmatter + markdown
- **Metrics:** SEO compliance, alt text presence, internal links
- **Result:** Full compliance in 6 iterations

---

## What Makes a Domain Suitable for AutoResearch

**Requirements (all needed):**
1. Measurable objective (better/worse, not subjective)
2. Automated evaluation (no manual judgment)
3. Editable artifact (code, prompts, config)
4. Reversible changes (git-like)
5. Fast feedback (<30 min ideally, <2 hours max)

**For bithumb trading bot:**
- ✅ Measurable: Sharpe ratio, Profit Factor, MDD
- ✅ Automated: Backtest can run in minutes
- ✅ Editable: strategy_params.py
- ✅ Reversible: git tracking
- ⚠️ Fast enough: 5-10 min per backtest possible with 2-year data

---

## Why Single File Matters

**Why it works:**
- **Full context window:** Agent sees entire system at once
- **Simpler diffs:** Changes are reviewable by humans
- **No abstraction layers:** Agent doesn't get confused by imports/dependencies
- **Atomic changes:** One edit = clear cause/effect

**Limitation:**
- Works only for self-contained problems
- Requires system to fit in context window (~4000-8000 lines)

**For trading bot:**
```python
# ONE editable file only
strategy_params.py
├── MOMENTUM_RANK_WINDOW = 20
├── ATR_SCALING_FACTOR = 2.0
├── POOL_REBALANCE_FREQ = 12
├── REGIME_THRESHOLD = 0.5
└── ... all hyperparams in one place

# LOCKED (immutable)
backtest_prepare.py
├── load_market_data()
├── evaluate_sharpe()
├── evaluation metrics
└── validation set selection
```

---

## Validation Strategy: Preventing Drift

**Tight Scope Prevents Cheating:**

Experiment design:
- ✅ Tightly scoped (one editable file, one metric, frequent gates) → Clean results
- ❌ Loosely scoped (vague objectives, infrequent validation) → Drift within hours

**Three control mechanisms:**
1. **One experiment per call** - Clean error recovery via git history
2. **Strict validation gates** - Accept only improvements >= last best, not "close enough"
3. **Frequent checkpoints** - Every 10 experiments validate on different held-out data

**Quote from Cerebras research:**
> "AutoResearch can reliably surface real findings when the loop is tightly scoped. Loosen the guardrails, and the agent drifts within hours."

---

## Limitations You Should Know

| Limitation | Example | Mitigation |
|-----------|---------|-----------|
| **Creativity ceiling** | Agent refines LR but misses architecture changes | Parallel search with factorial grids |
| **Overfitting** | 100 experiments on same validation set | Walk-forward, multiple metrics, strict gates |
| **Single metric risk** | Optimizing only Sharpe ignores drawdown | Use Sharpe + MDD + Profit Factor |
| **Regime changes** | Params optimal in bull market fail in bear | Multi-regime backtesting |
| **Short feedback only** | Won't work for week-long experiments | Stick to 5-30 min cycles |
| **No theoretical guarantee** | Unlike Bayesian opt, can't prove it converges | Accept this tradeoff for speed/autonomy |

---

## Implementation for Bithumb Bot: Proposed Structure

```
# This is what "one file" looks like:
strategy_params.py (agent edits this)
├── MOMENTUM_RANK_WINDOW = 20
├── MOMENTUM_RANK_WEIGHT = 0.6
├── ATR_SCALING_FACTOR = 2.0
├── REGIME_THRESHOLD = 0.5
├── POOL_REBALANCE_FREQ = 12
├── MAX_POSITION_SIZE = 0.05
└── DRAWDOWN_KILL_SWITCH = -15

backtest_prepare.py (LOCKED)
├── load_market_data(coin_universe, date_range)
├── evaluate_sharpe(backtest_results)  # <- The metric
├── validation_shard_selection()
└── configuration constants

optimization_program.md (human updates strategy, not agent)
├── ## Objective
│   └── Maximize Sharpe without exceeding -15% MDD
├── ## Constraints
│   └── Cannot modify prepare.py, etc.
├── ## What Has Been Tried
│   └── Historical attempts + learnings
└── ## Hypotheses to Test
    └── Next 10 ideas the human thinks are worth exploring
```

**Experiment cycle:**
1. Agent reads program.md for direction
2. Agent modifies strategy_params.py (one change)
3. Git commit: `git commit -m "experiment: MOMENTUM_RANK_WINDOW 20->25"`
4. Backtest runs in 60 seconds
5. Evaluate: `new_sharpe > best_sharpe and new_mdd >= -15%?`
6. Yes → `git merge` / No → `git reset --hard`
7. Repeat 100 times overnight

---

## Key Metrics to Watch

Don't optimize single metric. Use:

| Metric | What | Why | Target |
|--------|------|-----|--------|
| **Sharpe Ratio** | Risk-adjusted return | Balances return vs volatility | > 1.0 |
| **Profit Factor** | Win amount / Loss amount | Probability of profit | > 1.5 |
| **Max Drawdown** | Worst cumulative loss | Risk constraint | > -15% |
| **Consecutive Losses** | Longest losing streak | Psychological resilience | < 5 days |
| **Out-of-Sample** | Held-out test month | Real generalization | Checked only at end |

---

## Darwin Engine + AutoResearch Hybrid

**Current:** Weekly DeepSeek-driven reflection on failures

**Proposed hybrid:**

```
Daily (AutoResearch):
├── 50-100 iterations on parameter tweaks
├── Momentum weights, ATR scaling, regime thresholds
└── Fast feedback loop

Weekly (Darwin):
├── Analyze aggregated trade failures
├── Generate new strategy hypotheses
├── Propose architectural changes

Monthly (Walk-Forward):
├── Validate best parameters on unseen 1-month window
└── Confirm real improvement, not overfitting
```

**Why hybrid works:**
- AutoResearch: Fast local refinement
- Darwin: Hypothesis generation from failure patterns
- Walk-Forward: Prevents overfitting spiral

---

## Git as State Machine

```bash
# Each iteration
git checkout -b opt/exp-NNN
# agent modifies strategy_params.py
git commit -m "experiment: ATR_SCALING_FACTOR 2.0 -> 2.2"

# Evaluation (60 seconds)
./backtest.sh > results.json

# Decide
if sharpe_improved and mdd_ok:
  git checkout main && git merge opt/exp-NNN
  git branch -d opt/exp-NNN
else:
  git checkout main && git branch -D opt/exp-NNN
```

**Advantages:**
- Cheap reversal (one git command)
- History preserved (all attempts logged)
- Parallel-friendly (can retry on different GPU)
- Human-reviewable (clear diffs per experiment)

---

## Gotchas & Lessons Learned

1. **Proposal quality > speed** — Better to think 60s for good idea than 30s for bad idea
2. **Tight scope prevents gaming** — More constraints = fewer agent tricks
3. **Frequency beats model size** — 10 small validation checks > 1 large check
4. **Git history is your friend** — Don't use in-memory state; persist to disk
5. **Multiple metrics prevent single-metric gaming** — 3 metrics > 1 metric
6. **Immutable ground truth** — If evaluation can be edited, agent will exploit it
7. **Short time budgets force focus** — 5 min finds early-signal optimizations, 30 min finds overfitted tweaks
8. **Theoretical guarantee doesn't exist** — Unlike CMA-ES, no proof it converges; accept this tradeoff

---

## Sources

Full research document: `/home/bythejune/projects/bithumb-bot-v2/docs/AUTORESEARCH_DEEP_DIVE.md`

Key references:
- [GitHub - karpathy/autoresearch](https://github.com/karpathy/autoresearch)
- [Cerebras: How to Stop Your AutoResearch Loop from Cheating](https://www.cerebras.ai/blog/how-to-stop-your-autoresearch-loop-from-cheating)
- [SkyPilot: Scaling Karpathy's Autoresearch to 16 GPUs](https://blog.skypilot.co/scaling-autoresearch/)
- [ArXiv: Can LLMs Beat Classical HPO? (2603.24647)](https://arxiv.org/html/2603.24647)
- [Awesome AutoResearch](https://github.com/alvinunreal/awesome-autoresearch)
