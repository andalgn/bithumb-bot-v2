# AutoResearch Research Index

**Research Date:** March 28, 2026
**Researcher:** Claude Code
**Topic:** Andrej Karpathy's AutoResearch Project (Released March 7, 2026)
**Project Context:** Bithumb Trading Bot Strategy Optimization

---

## Documents in This Research

### 1. **AUTORESEARCH_DEEP_DIVE.md** (~13,000 words)
Comprehensive technical research on the entire autoresearch project.

**Contains:**
- Core architecture & design principles (3-file pattern)
- Keep/revert loop effectiveness analysis
- Overfitting and reward hacking research (Cerebras case studies)
- Design decisions: why 5 minutes, why single metric, why git
- Scaling insights (1 GPU → 16 GPUs, 9x speedup)
- Non-LLM adaptations (trading, GPU kernels, sudoku, genealogy, voice AI, docs)
- Community forks and implementations
- Criticisms and limitations
- Application to trading bot strategy optimization

**Best for:** Deep understanding, architectural decisions, risk analysis

---

### 2. **AUTORESEARCH_SUMMARY.md** (~3,000 words)
Quick reference guide with essential patterns and trade-offs.

**Contains:**
- 60-second overview
- Critical architecture decisions (table format)
- Keep/revert loop effectiveness summary
- Overfitting problem and prevention (Cerebras framework)
- Scaling insights
- AutoResearch vs classical optimization comparison
- Real-world domain adaptations
- Suitability checklist for new domains
- Implementation structure for trading bot
- Key metrics to watch
- Darwin + AutoResearch hybrid proposal
- Git as state machine
- Gotchas and lessons learned

**Best for:** Quick lookup, decision-making, status updates

---

### 3. **AUTORESEARCH_CODE_PATTERNS.md** (~4,000 words)
Concrete code patterns and implementation guide.

**Contains:**
- Pattern 1: Immutable evaluation function (backtest_prepare.py)
- Pattern 2: Single editable parameter file (strategy_params.py)
- Pattern 3: Program.md strategy document (human-edited)
- Pattern 4: Keep/revert experiment loop (agent pseudocode)
- Pattern 5: Git commit message format for agent learning
- Pattern 6: Multi-metric validation (preventing overfitting)
- Pattern 7: Scaling to parallel execution (16 GPUs)
- Complete loop diagram

**Best for:** Implementation, copy-paste templates, code structure

---

## Quick Navigation

### I need to understand...

**How does AutoResearch work?**
→ Start: AUTORESEARCH_SUMMARY.md "The 60-Second Version"
→ Deep: AUTORESEARCH_DEEP_DIVE.md Part 1 & 2

**Why does the keep/revert loop work?**
→ Start: AUTORESEARCH_SUMMARY.md "Keep/Revert Loop: Why It Works"
→ Deep: AUTORESEARCH_DEEP_DIVE.md Part 2 "Keep/Revert Loop Effectiveness"

**How do we prevent the bot from overfitting?**
→ Start: AUTORESEARCH_SUMMARY.md "The Overfitting Problem"
→ Deep: AUTORESEARCH_DEEP_DIVE.md Part 3 "Overfitting, Reward Hacking & Validation Design"
→ Implement: AUTORESEARCH_CODE_PATTERNS.md Pattern 6 "Multi-Metric Validation"

**Can we use this for trading strategy optimization?**
→ Start: AUTORESEARCH_SUMMARY.md "Application for Bithumb Bot"
→ Deep: AUTORESEARCH_DEEP_DIVE.md Part 10 "Application to Trading Strategy Optimization"
→ Implement: AUTORESEARCH_CODE_PATTERNS.md Pattern 1-6

**What happens when we scale from 1 GPU to 16 GPUs?**
→ Start: AUTORESEARCH_SUMMARY.md "Scaling Insight"
→ Deep: AUTORESEARCH_DEEP_DIVE.md Part 5 "Scaling to Distributed Systems"
→ Implement: AUTORESEARCH_CODE_PATTERNS.md Pattern 7 "Scaling from 1 GPU to 16 GPUs"

**What are the risks and limitations?**
→ Start: AUTORESEARCH_SUMMARY.md "Limitations You Should Know"
→ Deep: AUTORESEARCH_DEEP_DIVE.md Part 9 "Criticisms, Limitations & Open Problems"

**How do we implement this right now?**
→ Implement: AUTORESEARCH_CODE_PATTERNS.md (all patterns)
→ Reference: AUTORESEARCH_SUMMARY.md "Implementation for Bithumb Bot"

**What if we want a hybrid with Darwin engine?**
→ Strategy: AUTORESEARCH_SUMMARY.md "Darwin Engine + AutoResearch Hybrid"
→ Deep: AUTORESEARCH_DEEP_DIVE.md Part 10 "Hybrid Approach"

**How do other people use AutoResearch (not LLM training)?**
→ Examples: AUTORESEARCH_SUMMARY.md "Real-World Adaptations Beyond LLM Training"
→ Deep: AUTORESEARCH_DEEP_DIVE.md Part 6 "Adaptations Beyond LLM Training"
→ Comprehensive: AUTORESEARCH_DEEP_DIVE.md Part 7 "Community Forks & Implementations"

---

## Key Insights Summary

### 1. Core Mechanism
- Agent edits one file (strategy_params.py)
- Runs time-boxed experiment (60 seconds for trading)
- Measures metric (Sharpe ratio)
- Keeps change if improvement, reverts if worse
- Repeats 100 times overnight

### 2. Why It Works
- Tight scope prevents gaming
- Frequent feedback enables learning
- Git history enables reversals
- Single metric forces focus
- Immutable evaluation prevents cheating

### 3. Key Risk: Overfitting
- Solution: Multiple metrics (Sharpe + MDD + Profit Factor)
- Solution: Frequent checkpoints every 10 experiments
- Solution: Hold-out validation month never seen by agent
- Solution: Walk-forward testing monthly
- Tight evaluation gates prevent drift

### 4. Scaling Strategy
- Single GPU: Greedy hill-climbing
- Multi-GPU: Factorial grids test parameter interactions
- Result: 9x speedup reaching optimal loss
- Agent self-discovers hardware optimization strategies

### 5. Comparison to Alternatives
- Grid search: Exhaustive but curse of dimensionality
- Random search: Broad but inefficient
- Bayesian optimization: Efficient but bounded search space
- **AutoResearch:** Creative exploration in unbounded code space
- **Centaur (hybrid):** Classical optimizer state + LLM creativity = best results

### 6. Lessons from Failures
- Loose evaluation gates → agent drifts within hours
- Single metric → reward hacking
- Infrequent validation → explores tangents
- Unreversible changes → expensive mistakes
- Long feedback loops → < 10 nightly iterations

### 7. What Transfers to Trading
- ✅ Measurable metric (Sharpe ratio)
- ✅ Automated evaluation (backtest)
- ✅ Editable artifact (strategy parameters)
- ✅ Reversible changes (git tracking)
- ⚠️ Fast feedback needed (60-second backtest possible)

### 8. What's Different in Trading
- ❌ Longer feedback loops than LLM training (minutes vs seconds)
- ❌ Overfitting risk higher (backtest != live trading)
- ❌ Regime changes break learned parameters
- ❌ Data quality issues can be exploited
- ❌ Execution assumptions differ (slippage, fills, rejections)

---

## Recommended Next Steps

### Phase 0: Decision (This Week)
- [ ] Read AUTORESEARCH_SUMMARY.md
- [ ] Decide: proceed with implementation?
- [ ] Risk assessment: acceptable overfitting risk?

### Phase 1: Prototype (Week 1-2)
- [ ] Implement backtest_prepare.py (immutable)
- [ ] Implement strategy_params.py (editable)
- [ ] Implement optimization_program.md (human-driven)
- [ ] Write basic keep/revert loop
- [ ] Test with 10 manual experiments

### Phase 2: Automation (Week 2-3)
- [ ] Connect to agent (Claude Code skill)
- [ ] Set up nightly orchestration
- [ ] Implement multi-metric gating (6 constraints)
- [ ] Add out-of-sample checkpoints
- [ ] Run 50 overnight experiments

### Phase 3: Validation (Week 3-4)
- [ ] Walk-forward testing on 3 months unseen data
- [ ] Compare optimized vs baseline parameters
- [ ] Paper trading simulation
- [ ] Risk analysis: max drawdown, consecutive losses

### Phase 4: Integration (Week 4+)
- [ ] Integrate with Darwin engine (weekly hypotheses)
- [ ] Set up scaling infrastructure (16 GPUs optional)
- [ ] Monitor for drift and overfitting
- [ ] Monthly review and recalibration

---

## Critical Decisions Pending

### 1. Feedback Loop Speed
- **Current:** 60 seconds per backtest on 2-year data
- **Question:** Fast enough for 100 nightly experiments?
- **Impact:** Slower = fewer experiments = less learning

### 2. Metric Selection
- **Current:** Sharpe ratio primary
- **Question:** Add Profit Factor constraint? MDD hard limit? Consecutive loss constraint?
- **Impact:** More constraints = prevents bad optimization, but may be too strict

### 3. Overfitting Defense
- **Current:** Monthly walk-forward validation
- **Question:** More frequent (weekly)? Or less (quarterly)?
- **Impact:** More frequent = longer development cycle but safer

### 4. Agent Model
- **Current:** Claude (via API)
- **Question:** Which model size? Larger = better proposals but slower (60s budget)?
- **Impact:** Proposal quality dominates cost, not speed

### 5. Scaling Timeline
- **Current:** Single GPU implementation
- **Question:** Build for 16 GPU multi-node from start?
- **Impact:** More complex infrastructure vs potential 9x speedup

---

## Sources & References

### Original Project
- [GitHub - karpathy/autoresearch](https://github.com/karpathy/autoresearch)
- [Andrej Karpathy's Announcement (X/Twitter, March 7 2026)](https://x.com/karpathy/status/2030371219518931079)

### Key Research Papers
- [ArXiv 2603.24647: Can LLMs Beat Classical Hyperparameter Optimization?](https://arxiv.org/html/2603.24647)
- [ArXiv 2603.23420: Bilevel Autoresearch: Meta-Autoresearching Itself](https://arxiv.org/html/2603.23420)

### Implementation Guides
- [Cerebras: How to Stop Your AutoResearch Loop from Cheating](https://www.cerebras.ai/blog/how-to-stop-your-autoresearch-loop-from-cheating)
- [SkyPilot: Scaling Karpathy's Autoresearch to 16 GPUs](https://blog.skypilot.co/scaling-autoresearch/)
- [Medium: I Turned Autoresearch Into a Universal Skill](https://medium.com/@k.balu124/i-turned-andrej-karpathys-autoresearch-into-a-universal-skill-1cb3d44fc669)
- [Medium: Run Autoresearch on Google Cloud for $2/hour](https://medium.com/google-cloud/run-karpathys-autoresearch-on-a-google-serverless-stack-for-2-hour-210fc8e2a829)

### Domain Adaptations
- [GitHub: awesome-autoresearch (Curated list of implementations)](https://github.com/alvinunreal/awesome-autoresearch)
- [ATLAS Trading Agents (GitHub: chrisworsey55/atlas-gic)](https://github.com/chrisworsey55/atlas-gic)
- [autoresearch-genealogy](https://github.com/mattprusak/autoresearch-genealogy)

### Community Resources
- [DataCamp: A Guide to Andrej Karpathy's AutoResearch](https://www.datacamp.com/tutorial/guide-to-autoresearch)
- [Karpathy's Autoresearch for PMs](https://www.news.aakashg.com/p/autoresearch-guide-for-pms)
- [The New Stack: Karpathy's Autonomous Experiment Loop](https://thenewstack.io/karpathy-autonomous-experiment-loop/)
- [VentureBeat: Karpathy's AutoResearch Revolutionary Implications](https://venturebeat.com/technology/andrej-karpathys-new-open-source-autoresearch-lets-you-run-hundreds-of-ai/)

---

## Research Completion Status

**Total Words:** ~20,000
**Documents:** 4 (DEEP_DIVE + SUMMARY + CODE_PATTERNS + INDEX)
**Topics Covered:**
- ✅ GitHub repo and architecture
- ✅ Blog posts and discussions
- ✅ Community forks and adaptations
- ✅ Non-LLM use cases (trading, GPU kernels, genealogy, voice AI, docs)
- ✅ Design decisions (why single file, why fixed budget, why git)
- ✅ Keep/revert effectiveness vs random search
- ✅ Criticisms and limitations (overfitting, reward hacking, drift)
- ✅ Scaling insights (1 GPU → 16 GPUs)
- ✅ Comparison to classical optimization
- ✅ Implementation patterns and code examples
- ✅ Trading bot specific application

**Next:** Implement prototype following AUTORESEARCH_CODE_PATTERNS.md

---

## Quick Links for Different Audiences

### For Product Managers / Executives
→ Read: AUTORESEARCH_SUMMARY.md (10 minutes)
→ Key: 100 experiments overnight, 11% improvement, prevents human bias in parameter selection

### For Engineers / Implementers
→ Read: AUTORESEARCH_CODE_PATTERNS.md (30 minutes)
→ Key: 3 files, 7 code patterns, copy-paste templates, multi-metric validation

### For Architects / Decision-Makers
→ Read: AUTORESEARCH_DEEP_DIVE.md Parts 1, 3, 5, 9, 10 (1 hour)
→ Key: Risks (overfitting, reward hacking), scaling strategy, comparison to alternatives

### For Researchers / PhD Students
→ Read: AUTORESEARCH_DEEP_DIVE.md (2-3 hours)
→ Key: Complete literature review, all adaptations, all design decisions, open problems

### For Trading-Specific Questions
→ Read: AUTORESEARCH_SUMMARY.md "Application" section
→ Then: AUTORESEARCH_DEEP_DIVE.md Part 10
→ Then: AUTORESEARCH_CODE_PATTERNS.md Pattern 1-6

---

**End of Index**

---

For detailed research, see the three companion documents in this directory.
