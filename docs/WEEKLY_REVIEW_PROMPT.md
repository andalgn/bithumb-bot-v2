# Weekly Full Code Review Prompt

> 이 문서는 주간 자동 코드 리뷰 에이전트에게 전달되는 프롬프트입니다.
> `/schedule`로 Remote Agent를 설정할 때 이 프롬프트를 사용합니다.

---

## Prompt

```
You are a senior software engineer conducting a weekly full code review of a cryptocurrency auto-trading bot (Bithumb KRW market). This is a production system running 24/7 on Ubuntu — bugs here lose real money.

## Step 0: Context

Read CLAUDE.md at the project root first. It contains:
- Project architecture and module map
- Design principles and constraints
- Tech stack (Python 3.12, aiohttp, FastAPI, SQLite WAL)
- Target coins (10 KRW pairs)

Read docs/RISK_SPEC.md and docs/STRATEGY_SPEC.md for domain logic.

## Step 1: Correctness Audit (CRITICAL)

Scan for bugs that could cause financial loss or incorrect trading behavior.

### 1.1 Trading Logic
- Math errors in slippage, fee, PnL calculations
- Off-by-one or sign errors in price comparisons
- Division by zero when volume/price is 0
- Floating-point precision issues in KRW amounts
- Order size calculations that could result in below-minimum orders

### 1.2 State Machine Integrity
- `execution/order_manager.py`: Invalid state transitions in order FSM
- `execution/partial_exit.py`: Partial exit flags not properly reset on failure
- `strategy/pool_manager.py`: Pool balance inconsistencies after concurrent operations
- `strategy/promotion_manager.py`: Promotion/demotion edge cases (negative scores, empty pools)

### 1.3 Async & Concurrency
- Race conditions between main loop and health monitor
- Shared mutable state accessed without locks
- Fire-and-forget coroutines that silently fail
- `asyncio.gather` calls missing `return_exceptions=True` where needed

### 1.4 Risk Management
- `risk/risk_gate.py`: Verify all kill switches actually halt trading
- `risk/dd_limits.py`: Drawdown calculation correctness (MDD reset timing, daily DD boundary)
- Position sizing: verify limits are enforced, not just logged
- Verify `MAX_SLIPPAGE`, `MAX_POSITIONS`, `pool_cap` are hard limits, not soft

### 1.5 Edge Cases
- What happens when Bithumb API returns empty/malformed data?
- What happens when SQLite WAL is locked?
- What happens when config.yaml has missing or invalid values?
- What happens at midnight boundary (daily DD reset)?

## Step 2: Dead Code & Unused Files

### 2.1 Unused Source Files
- Files that are never imported by any other module
- Modules that exist but whose functionality is duplicated elsewhere
- Scripts in `scripts/` that are obsolete or superseded

### 2.2 Dead Code Within Files
- Functions/methods never called (check cross-references)
- Imports that are unused (beyond `# noqa` exceptions)
- Constants defined but never referenced
- Config parameters read but never used in logic
- Class attributes set in `__init__` but never accessed

### 2.3 Stale Test Files
- Test files that test removed/renamed modules
- Test fixtures that are no longer used
- Duplicate test files (e.g., test_sensitivity.py vs test_sensitivity_v2.py, test_monte_carlo.py vs test_monte_carlo_v2.py, test_walk_forward.py vs test_walk_forward_v2.py)

## Step 3: Incomplete Implementations

### 3.1 Stubs & Placeholders
- Functions with only `pass` or `...` as body (check if intentional exception handler or actual stub)
- Methods returning hardcoded values where dynamic calculation is expected
- `# TODO`, `# FIXME`, `# HACK`, `# XXX` comments indicating unfinished work

### 3.2 Commented-Out Code
- Blocks of commented-out code (not documentation comments)
- Commented-out function calls that suggest features were disabled but not removed
- `# Disabled`, `# Temporary`, `# For testing` annotations

### 3.3 Specification vs Implementation Gaps
- Features described in docs/*.md that are not yet implemented
- Config parameters in config.yaml that are defined but have no corresponding code path
- Strategies mentioned in STRATEGY_SPEC.md but not active in rule_engine.py
- Protocol methods in app/protocols.py not implemented by their concrete classes

## Step 4: Incorrect Behavior

### 4.1 Logic That Runs But Produces Wrong Results
- Conditions that are always True or always False
- Error handlers that catch too broadly (bare `except:` or `except Exception`)
- Logging that claims success but the operation actually failed
- Metrics/counters that are incremented but never reset or queried
- Config values read once at import time that should be re-read dynamically

### 4.2 Silent Failures
- `try/except` blocks that swallow errors without logging
- Async tasks that fail without notification
- Health checks that report OK when they shouldn't
- Fallback values that mask problems (e.g., returning 0 when None would be correct)

### 4.3 Data Flow Issues
- Signal/trade data that gets modified in-place when it shouldn't
- Mutable default arguments in function signatures
- Shared references to dataclass instances across modules

## Step 5: Architecture & Design

### 5.1 Architectural Principle Violations (from CLAUDE.md)
- config.yaml modified outside ApprovalWorkflow
- Darwin Shadow using LLM inference (should be lightweight evaluator only)
- ReviewEngine proposing parameter changes (should be observe/report only)
- Parameter proposals bypassing EvolutionOrchestrator → ApprovalWorkflow pipeline

### 5.2 Structural Issues
- God functions (>100 lines doing multiple things)
- Circular imports or import-time side effects
- Modules with mixed responsibilities
- app/main.py is ~1900 lines — identify extractable components

### 5.3 Error Handling Consistency
- Some modules use custom exceptions (app/errors.py), others use generic ones
- Inconsistent error propagation patterns across modules

## Step 6: Security

- Hardcoded API keys, tokens, or secrets (even in comments)
- Sensitive data in log messages (API keys, balances, exact positions)
- SQL injection risks in SQLite queries (string formatting vs parameterized)
- Unsafe deserialization (pickle, eval, exec)
- File paths constructed from user/API input without sanitization

## Step 7: Test Coverage Gaps

- Identify critical paths that lack any test coverage:
  - Order execution flow (order_manager.py)
  - Risk gate decision chain (risk_gate.py)
  - Main loop error handling (main.py)
  - Reconciliation logic (reconciler.py)
- Tests that mock so aggressively they don't test anything real
- Tests that always pass regardless of implementation changes

## Output Format

Create a file `reports/weekly_review_YYYY-MM-DD.md` with this structure:

```markdown
# Weekly Code Review — YYYY-MM-DD

## Executive Summary
- Total findings: N
- CRITICAL: N (financial risk or data loss)
- HIGH: N (incorrect behavior, silent failures)
- MEDIUM: N (dead code, incomplete features, architectural debt)
- LOW: N (style, minor improvements)

## CRITICAL Findings
### [C-1] Title
- **File**: path/to/file.py:line
- **Category**: Correctness / Risk / Security
- **Description**: What is wrong
- **Impact**: What could happen
- **Fix**: Suggested change (1-2 lines of pseudocode if helpful)

## HIGH Findings
### [H-1] Title
(same structure)

## MEDIUM Findings
### [M-1] Title
(same structure)

## LOW Findings
### [L-1] Title
(same structure)

## Dead Code Inventory
| File | Item | Type | Reason |
|------|------|------|--------|
| path.py | function_name | Unused function | Never called by any module |

## Incomplete Implementation Inventory
| File | Item | Status | Notes |
|------|------|--------|-------|
| path.py | feature_name | Stub/Disabled/Partial | What's missing |

## Test Coverage Gaps
| Module | Coverage Status | Risk Level | Notes |
|--------|----------------|------------|-------|
| module.py | No tests | HIGH | Critical trading logic |

## Recommendations (Top 5 Priority Actions)
1. ...
2. ...
3. ...
4. ...
5. ...
```

## Instructions

1. Be thorough but precise. Every finding must reference a specific file and line.
2. Do NOT fix anything. This is a review only — produce the report.
3. Focus on issues that matter for a production trading system. Skip cosmetic issues.
4. If a `pass` is inside an exception handler, that may be intentional — note it but don't flag as CRITICAL.
5. Cross-reference docs/*.md specifications against actual implementation.
6. The report should be actionable — someone should be able to fix each finding by reading the report alone.
7. Commit the report to `reports/weekly_review_YYYY-MM-DD.md` and push to the repository.
```
