# Refactoring Phase 2: RuleEngine Decomposition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **선행 조건:** Phase 1 완료 (`pytest tests/test_regime_snapshot.py tests/test_env_filter_snapshot.py tests/test_strategy_scorer_snapshot.py` 전체 통과) 후 진행.

**Goal:** 2,000줄 RuleEngine God-class를 4개 독립 클래스로 분리하고, 기존 인터페이스를 유지하는 파사드를 남겨 봇 코드 변경 없이 교체한다.

**Architecture:** Strangler Fig + Facade 패턴. `main.py`가 `RuleEngine`을 직접 접근하는 내부 속성 8곳을 먼저 public accessor로 교체 → 그 후 내부를 분리. 기존 `generate_signals()` 인터페이스는 그대로 유지.

**Tech Stack:** Python 3.12+, 기존 `strategy/` 모듈, pytest

---

## 파일 맵

| 동작 | 경로 | 역할 |
|------|------|------|
| 생성 | `strategy/regime_classifier.py` | 국면 판정 + 히스테리시스 |
| 생성 | `strategy/environment_filter.py` | L1 환경 필터 |
| 생성 | `strategy/strategy_scorer.py` | 전략 점수 계산 5종 |
| 생성 | `strategy/size_decider.py` | 사이즈 결정 |
| 수정 | `strategy/rule_engine.py` | public accessor 추가 → 파사드로 축소 |
| 수정 | `app/main.py` | `_rule_engine._*` 8곳 → accessor 경유로 교체 |

---

## Task 1: main.py의 private 접근 현황 파악

**Files:**
- Read: `app/main.py`

- [ ] **Step 1: private 접근 위치 확인**

```bash
grep -n "_rule_engine\._" /home/bythejune/projects/bithumb-bot-v2/app/main.py
```
Expected: `_strategy_params`, `_regime_states`, `_decide_size`, `_get_regime_state` 등 8곳

- [ ] **Step 2: 각 접근의 context 파악**

```bash
grep -n -B2 -A2 "_rule_engine\._" /home/bythejune/projects/bithumb-bot-v2/app/main.py
```

결과를 메모해두고 다음 Task에서 accessor 설계에 반영한다.

---

## Task 2: RuleEngine에 public accessor 추가

**Files:**
- Modify: `strategy/rule_engine.py`

- [ ] **Step 1: 기존 private 속성 확인**

```bash
grep -n "self\._strategy_params\|self\._regime_states\|self\._decide_size\|self\._get_regime" \
  /home/bythejune/projects/bithumb-bot-v2/strategy/rule_engine.py | head -20
```

- [ ] **Step 2: `RuleEngine` 클래스에 accessor 메서드 추가**

`strategy/rule_engine.py`의 `RuleEngine` 클래스 마지막 부분에 추가:

```python
# ═══════════════════════════════════════════
# Public accessors (Phase 2 리팩토링용)
# ═══════════════════════════════════════════

@property
def strategy_params(self) -> dict:
    """현재 전략 파라미터를 반환한다."""
    return self._strategy_params

def get_regime_state(self, symbol: str):
    """코인별 국면 상태를 반환한다."""
    return self._regime_states.get(symbol)

@property
def regime_states(self) -> dict:
    """전체 국면 상태 dict를 반환한다."""
    return self._regime_states

def decide_size_public(self, *args, **kwargs):
    """사이즈 결정을 public으로 위임한다."""
    return self._decide_size(*args, **kwargs)
```

- [ ] **Step 3: 테스트로 accessor 동작 확인**

```bash
python -c "
from app.config import load_config
from strategy.rule_engine import RuleEngine
engine = RuleEngine(load_config())
print('strategy_params:', type(engine.strategy_params))
print('regime_states:', type(engine.regime_states))
print('OK')
"
```
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add strategy/rule_engine.py
git commit -m "refactor: add public accessors to RuleEngine for safe split preparation (Phase 2)"
```

---

## Task 3: main.py의 private 접근 → accessor로 교체

**Files:**
- Modify: `app/main.py`

- [ ] **Step 1: 각 private 접근을 accessor로 교체**

Task 1에서 파악한 8곳을 교체:
- `self._rule_engine._strategy_params` → `self._rule_engine.strategy_params`
- `self._rule_engine._regime_states` → `self._rule_engine.regime_states`
- `self._rule_engine._get_regime_state(sym)` → `self._rule_engine.get_regime_state(sym)`
- `self._rule_engine._decide_size(...)` → `self._rule_engine.decide_size_public(...)`

- [ ] **Step 2: private 접근이 0개인지 확인**

```bash
grep -n "_rule_engine\._" /home/bythejune/projects/bithumb-bot-v2/app/main.py
```
Expected: 출력 없음

- [ ] **Step 3: 스냅샷 테스트 통과 확인**

```bash
pytest tests/test_regime_snapshot.py tests/test_env_filter_snapshot.py tests/test_strategy_scorer_snapshot.py -v
```
Expected: 전체 통과

- [ ] **Step 4: 봇 재시작 없이 import 확인**

```bash
python -c "from app.main import TradingBot; print('import OK')"
```
Expected: `import OK`

- [ ] **Step 5: Commit** ← 이 시점이 Phase 2 완전 롤백 포인트

```bash
git add app/main.py
git commit -m "refactor: replace private RuleEngine accesses with public accessors (Phase 2)"
```

---

## Task 4: RegimeClassifier 분리

**Files:**
- Create: `strategy/regime_classifier.py`

- [ ] **Step 1: `strategy/regime_classifier.py` 작성**

`rule_engine.py`에서 `_raw_classify`, `_detect_aux_flags`, 히스테리시스 로직을 추출:

```python
"""RegimeClassifier — 국면 판정 + 히스테리시스.

1H 지표를 기반으로 5종 국면을 분류하고 히스테리시스를 적용한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.data_types import Regime
from app.config import AppConfig
from strategy.indicators import IndicatorPack

# rule_engine.py에서 RegimeState dataclass와 분류 로직을 이 파일로 이동
# (rule_engine.py에서 import하여 사용하면 됨)


class RegimeClassifier:
    """국면 판정 담당."""

    def __init__(self, config: AppConfig) -> None:
        # rule_engine.py의 _regime_states, _raw_classify, _detect_aux_flags 이동
        ...

    def classify(self, symbol: str, ind_1h: IndicatorPack) -> Regime:
        """히스테리시스 적용 최종 국면을 반환한다."""
        ...

    def raw_classify(self, ind_1h: IndicatorPack) -> Regime:
        """히스테리시스 없는 원시 국면을 반환한다."""
        # rule_engine._raw_classify 내용 이동
        ...

    def get_state(self, symbol: str):
        """코인별 국면 상태를 반환한다."""
        ...

    @property
    def states(self) -> dict:
        """전체 국면 상태를 반환한다."""
        ...
```

> **구현 지침**: `rule_engine.py`의 `_raw_classify` (약 50줄)와 `_detect_aux_flags`, 히스테리시스 블록을 그대로 이동. 로직 수정 금지.

- [ ] **Step 2: 스냅샷 테스트 통과 확인 (RuleEngine 파사드가 RegimeClassifier 위임 후)**

```bash
pytest tests/test_regime_snapshot.py -v
```
Expected: 9케이스 전체 통과

- [ ] **Step 3: Commit**

```bash
git add strategy/regime_classifier.py strategy/rule_engine.py
git commit -m "refactor: extract RegimeClassifier from RuleEngine (Phase 2)"
```

---

## Task 5: EnvironmentFilter 분리

**Files:**
- Create: `strategy/environment_filter.py`

- [ ] **Step 1: `strategy/environment_filter.py` 작성**

`rule_engine.py`의 `_check_layer1` 메서드를 이동:

```python
"""EnvironmentFilter — L1 환경 필터.

거래 진입 전 시장 환경이 적합한지 판정한다.
"""
from __future__ import annotations

from app.data_types import MarketSnapshot, Regime
from app.config import AppConfig
from strategy.coin_profiler import TierParams
from strategy.indicators import IndicatorPack


class EnvironmentFilter:
    """L1 환경 필터 담당."""

    def __init__(self, config: AppConfig) -> None:
        ...

    def check(
        self,
        regime: Regime,
        snap: MarketSnapshot,
        ind_15m: IndicatorPack,
        tier_params: TierParams,
    ) -> tuple[bool, str]:
        """L1 필터를 적용한다. (통과 여부, 거부 사유) 반환."""
        # rule_engine._check_layer1 내용 이동
        ...
```

- [ ] **Step 2: 스냅샷 테스트 통과 확인**

```bash
pytest tests/test_env_filter_snapshot.py -v
```
Expected: 5케이스 전체 통과

- [ ] **Step 3: Commit**

```bash
git add strategy/environment_filter.py strategy/rule_engine.py
git commit -m "refactor: extract EnvironmentFilter from RuleEngine (Phase 2)"
```

---

## Task 6: StrategyScorer 분리

**Files:**
- Create: `strategy/strategy_scorer.py`

- [ ] **Step 1: `strategy/strategy_scorer.py` 작성**

`rule_engine.py`의 `_score_strategy_a~e`, `_evaluate_strategies`, `_get_weights` 이동:

```python
"""StrategyScorer — 전략 점수 계산.

5종 전략(trend_follow, mean_reversion, breakout, scalping, dca)의
점수를 계산하고 국면별 허용 전략만 반환한다.
"""
from __future__ import annotations

from app.data_types import MarketSnapshot, Regime, Strategy
from app.config import AppConfig
from strategy.indicators import IndicatorPack


class StrategyScorer:
    """전략 점수 계산 담당."""

    def __init__(self, config: AppConfig) -> None:
        ...

    def score_all(
        self,
        regime: Regime,
        snap: MarketSnapshot,
        ind_15m: IndicatorPack,
        ind_1h: IndicatorPack,
    ) -> list:
        """허용된 전략의 ScoreResult 리스트를 반환한다."""
        # rule_engine의 _evaluate_strategies 내용 이동
        ...
```

- [ ] **Step 2: 스냅샷 테스트 통과 확인**

```bash
pytest tests/test_strategy_scorer_snapshot.py -v
```
Expected: 5케이스 전체 통과

- [ ] **Step 3: Commit**

```bash
git add strategy/strategy_scorer.py strategy/rule_engine.py
git commit -m "refactor: extract StrategyScorer from RuleEngine (Phase 2)"
```

---

## Task 7: SizeDecider 분리

**Files:**
- Create: `strategy/size_decider.py`

- [ ] **Step 1: `strategy/size_decider.py` 작성**

`rule_engine.py`의 `_decide_size`, `_get_size_bucket` 이동:

```python
"""SizeDecider — 포지션 사이즈 결정.

전략 점수와 국면을 기반으로 FULL/HALF/SKIP 버킷을 결정한다.
"""
from __future__ import annotations

from app.data_types import Regime
from app.config import AppConfig


class SizeDecider:
    """사이즈 결정 담당."""

    def __init__(self, config: AppConfig) -> None:
        ...

    def decide(self, regime: Regime, score: float, strategy: str) -> str:
        """FULL / HALF / SKIP 중 하나를 반환한다."""
        # rule_engine._decide_size 내용 이동
        ...
```

- [ ] **Step 2: Commit**

```bash
git add strategy/size_decider.py strategy/rule_engine.py
git commit -m "refactor: extract SizeDecider from RuleEngine (Phase 2)"
```

---

## Task 8: RuleEngine 파사드 완성 + 검증

**Files:**
- Modify: `strategy/rule_engine.py`

- [ ] **Step 1: RuleEngine이 4개 컴포넌트를 조합하는 파사드인지 확인**

```bash
wc -l /home/bythejune/projects/bithumb-bot-v2/strategy/rule_engine.py
```
Expected: ≤ 150줄

- [ ] **Step 2: 전체 스냅샷 테스트 통과**

```bash
pytest tests/test_regime_snapshot.py tests/test_env_filter_snapshot.py tests/test_strategy_scorer_snapshot.py -v
```
Expected: 19케이스 전체 통과

- [ ] **Step 3: 전체 테스트 스위트 통과**

```bash
pytest tests/ -v --tb=short 2>&1 | tail -20
```
Expected: 전체 통과

- [ ] **Step 4: 봇 재시작 후 사이클 확인**

```bash
sudo systemctl restart bithumb-bot && sleep 5 && sudo journalctl -u bithumb-bot -n 10 --no-pager
```
Expected: `사이클 #1 완료` 로그 확인

- [ ] **Step 5: 최종 Commit + 태그**

```bash
git add -A
git commit -m "refactor: RuleEngine decomposed into RegimeClassifier/EnvironmentFilter/StrategyScorer/SizeDecider facade (Phase 2)"
git tag phase2-rule-engine-split
```

---

## Phase 2 완료 기준 체크리스트

- [ ] `strategy/rule_engine.py` ≤ 150줄
- [ ] 4개 신규 파일 생성 (`regime_classifier.py`, `environment_filter.py`, `strategy_scorer.py`, `size_decider.py`)
- [ ] `app/main.py`에서 `_rule_engine._*` 직접 접근 0개
- [ ] Phase 1 스냅샷 테스트 19케이스 전체 통과
- [ ] 봇 재시작 후 사이클 정상 실행

**다음 단계:** `docs/superpowers/plans/2026-03-25-refactoring-phase3-run-cycle.md`
