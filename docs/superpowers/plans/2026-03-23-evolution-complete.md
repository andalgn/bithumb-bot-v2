# Evolution Complete Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 매매봇의 5개 피드백 루프를 모두 연결하여 자기 진화 시스템 완성.

**Architecture:** 모든 진화 경로(Darwin, Auto-Optimize, Auto-Research, Daily/Weekly Review)가 config.yaml을 통해 rule_engine에 파라미터를 전달. 핫 리로드(구현 완료)가 변경을 자동 반영. 안전장치(자동 롤백, 점진적 적용, 실패 기억)가 보호.

**Tech Stack:** Python 3.12+, SQLite, aiohttp, PyJWT, DeepSeek API

**Spec:** `docs/superpowers/specs/2026-03-23-evolution-complete-design.md`

**Dev worktree:** `/home/bythejune/projects/bithumb-bot-v2-dev/` (branch: feature/evolution-complete)

**Note:** `app/config.py`는 수정 불필요. `strategy_params`는 이미 plain dict로 로드되므로 `regime_override` 같은 중첩 dict도 자동 파싱됨.

---

### Task 1: 실패 기억 DB + 파라미터 변경 로그

**Files:**
- Create: `strategy/experiment_store.py`
- Create: `tests/test_experiment_store.py`

공통 인프라를 먼저 구축. 다른 태스크들이 이 모듈을 사용.

- [ ] **Step 1: Write tests**

```python
# tests/test_experiment_store.py
"""ExperimentStore 테스트."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from strategy.experiment_store import ExperimentStore


class TestExperimentStore:
    """실험 기록 저장 테스트."""

    def test_record_and_query(self, tmp_path: Path) -> None:
        store = ExperimentStore(db_path=str(tmp_path / "exp.db"))
        store.record(
            source="darwin",
            strategy="mean_reversion",
            params={"sl_mult": 7.0},
            pf=1.2,
            mdd=0.08,
            trades=35,
            verdict="keep",
        )
        results = store.get_history("mean_reversion", limit=10)
        assert len(results) == 1
        assert results[0]["verdict"] == "keep"

    def test_count_failures(self, tmp_path: Path) -> None:
        store = ExperimentStore(db_path=str(tmp_path / "exp.db"))
        for i in range(4):
            store.record(
                source="auto_research",
                strategy="mean_reversion",
                params={"sl_mult": 8.0 + i * 0.1},
                pf=0.8,
                mdd=0.12,
                trades=30,
                verdict="revert",
            )
        count = store.count_similar_failures(
            strategy="mean_reversion",
            param_key="sl_mult",
            direction="increase",
        )
        assert count >= 3

    def test_param_change_log(self, tmp_path: Path) -> None:
        store = ExperimentStore(db_path=str(tmp_path / "exp.db"))
        store.log_param_change(
            source="darwin",
            strategy="mean_reversion",
            old_params={"sl_mult": 5.0},
            new_params={"sl_mult": 6.2},
            backup_path="configs/config.yaml.bak.20260323",
            baseline_pf=1.15,
        )
        active = store.get_active_changes()
        assert len(active) == 1
        assert active[0]["status"] == "monitoring"

    def test_rollback_change(self, tmp_path: Path) -> None:
        store = ExperimentStore(db_path=str(tmp_path / "exp.db"))
        store.log_param_change(
            source="darwin",
            strategy="mean_reversion",
            old_params={"sl_mult": 5.0},
            new_params={"sl_mult": 6.2},
            backup_path="configs/config.yaml.bak.20260323",
            baseline_pf=1.15,
        )
        active = store.get_active_changes()
        store.update_change_status(active[0]["id"], "rolled_back")
        updated = store.get_active_changes()
        assert len(updated) == 0
```

- [ ] **Step 2: Implement ExperimentStore**

```python
# strategy/experiment_store.py
"""실험 기록 + 파라미터 변경 로그 저장소."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp INTEGER NOT NULL,
    source TEXT NOT NULL,
    strategy TEXT NOT NULL,
    params TEXT NOT NULL,
    old_params TEXT,
    pf REAL NOT NULL,
    mdd REAL NOT NULL,
    trades INTEGER NOT NULL,
    verdict TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS param_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp INTEGER NOT NULL,
    source TEXT NOT NULL,
    strategy TEXT NOT NULL,
    old_params TEXT NOT NULL,
    new_params TEXT NOT NULL,
    backup_path TEXT NOT NULL,
    monitoring_until INTEGER NOT NULL,
    baseline_pf REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'monitoring'
);
"""

MONITORING_DAYS = 7


class ExperimentStore:
    """실험 기록 + 파라미터 변경 추적 저장소."""

    def __init__(self, db_path: str = "data/experiment_history.db") -> None:
        """초기화."""
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def record(
        self,
        source: str,
        strategy: str,
        params: dict,
        pf: float,
        mdd: float,
        trades: int,
        verdict: str,
    ) -> None:
        """실험 결과를 기록한다."""
        self._conn.execute(
            "INSERT INTO experiments (timestamp, source, strategy, params, pf, mdd, trades, verdict) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (int(time.time()), source, strategy, json.dumps(params), pf, mdd, trades, verdict),
        )
        self._conn.commit()

    def get_history(self, strategy: str, limit: int = 50) -> list[dict]:
        """전략별 실험 이력을 조회한다."""
        rows = self._conn.execute(
            "SELECT * FROM experiments WHERE strategy = ? ORDER BY timestamp DESC LIMIT ?",
            (strategy, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def count_similar_failures(
        self, strategy: str, param_key: str, direction: str,
    ) -> int:
        """유사한 방향의 실패 횟수를 조회한다.

        Args:
            strategy: 전략 이름.
            param_key: 파라미터 키 (예: "sl_mult").
            direction: "increase" 또는 "decrease".
        """
        rows = self._conn.execute(
            "SELECT params, old_params FROM experiments "
            "WHERE strategy = ? AND verdict IN ('revert', 'rolled_back')",
            (strategy,),
        ).fetchall()
        count = 0
        for row in rows:
            params = json.loads(row["params"])
            if param_key not in params:
                continue
            # old_params가 없으면 방향 판단 불가 → 카운트
            old_raw = row["old_params"] if "old_params" in row.keys() else None
            if old_raw is None:
                count += 1
                continue
            old_params = json.loads(old_raw)
            old_val = old_params.get(param_key, 0)
            new_val = params[param_key]
            if direction == "increase" and new_val > old_val:
                count += 1
            elif direction == "decrease" and new_val < old_val:
                count += 1
        return count

    def log_param_change(
        self,
        source: str,
        strategy: str,
        old_params: dict,
        new_params: dict,
        backup_path: str,
        baseline_pf: float,
    ) -> None:
        """파라미터 변경을 로그한다."""
        now = int(time.time())
        self._conn.execute(
            "INSERT INTO param_changes "
            "(timestamp, source, strategy, old_params, new_params, backup_path, monitoring_until, baseline_pf, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'monitoring')",
            (
                now, source, strategy,
                json.dumps(old_params), json.dumps(new_params),
                backup_path, now + MONITORING_DAYS * 86400,
                baseline_pf,
            ),
        )
        self._conn.commit()

    def get_active_changes(self) -> list[dict]:
        """모니터링 중인 변경 건을 조회한다."""
        rows = self._conn.execute(
            "SELECT * FROM param_changes WHERE status = 'monitoring'",
        ).fetchall()
        return [dict(r) for r in rows]

    def update_change_status(self, change_id: int, status: str) -> None:
        """변경 건의 상태를 업데이트한다."""
        self._conn.execute(
            "UPDATE param_changes SET status = ? WHERE id = ?",
            (status, change_id),
        )
        self._conn.commit()

    def close(self) -> None:
        """연결을 닫는다."""
        self._conn.close()
```

- [ ] **Step 3: Run tests**

Run: `cd /home/bythejune/projects/bithumb-bot-v2-dev && pytest tests/test_experiment_store.py -v`
Expected: All PASS

- [ ] **Step 4: Lint + Commit**

```bash
cd /home/bythejune/projects/bithumb-bot-v2-dev
ruff check strategy/experiment_store.py tests/test_experiment_store.py
ruff format strategy/experiment_store.py tests/test_experiment_store.py
git add strategy/experiment_store.py tests/test_experiment_store.py
git commit -m "feat: add ExperimentStore — experiment history + param change tracking"
```

---

### Task 2: 국면별 파라미터 (regime_override)

**Files:**
- Modify: `strategy/rule_engine.py` — generate_signals() 내 파라미터 병합 로직
- Create: `tests/test_regime_override.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_regime_override.py
"""국면별 파라미터 오버라이드 테스트."""

from __future__ import annotations


class TestRegimeOverride:
    """regime_override 병합 테스트."""

    def test_base_only(self) -> None:
        """regime_override 없으면 기본값 사용."""
        from strategy.rule_engine import _merge_strategy_params
        sp = {"sl_mult": 7.0, "tp_rr": 1.5}
        result = _merge_strategy_params(sp, tier=1, regime="RANGE")
        assert result["sl_mult"] == 7.0

    def test_regime_overrides_base(self) -> None:
        """regime_override가 기본값을 덮어쓴다."""
        from strategy.rule_engine import _merge_strategy_params
        sp = {
            "sl_mult": 7.0, "tp_rr": 1.5,
            "regime_override": {
                "WEAK_DOWN": {"sl_mult": 8.0, "tp_rr": 1.2},
            },
        }
        result = _merge_strategy_params(sp, tier=1, regime="WEAK_DOWN")
        assert result["sl_mult"] == 8.0
        assert result["tp_rr"] == 1.2

    def test_regime_overrides_tier(self) -> None:
        """regime_override가 tier보다 우선한다."""
        from strategy.rule_engine import _merge_strategy_params
        sp = {
            "sl_mult": 7.0,
            "tier1": {"sl_mult": 6.0},
            "regime_override": {
                "WEAK_DOWN": {"sl_mult": 8.0},
            },
        }
        result = _merge_strategy_params(sp, tier=1, regime="WEAK_DOWN")
        assert result["sl_mult"] == 8.0

    def test_no_matching_regime(self) -> None:
        """매칭 국면 없으면 base+tier 사용."""
        from strategy.rule_engine import _merge_strategy_params
        sp = {
            "sl_mult": 7.0,
            "regime_override": {"CRISIS": {"sl_mult": 10.0}},
        }
        result = _merge_strategy_params(sp, tier=1, regime="RANGE")
        assert result["sl_mult"] == 7.0
```

- [ ] **Step 2: Implement `_merge_strategy_params` helper function**

`strategy/rule_engine.py`에 헬퍼 함수 추가:

```python
def _merge_strategy_params(
    sp: dict, tier: int, regime: str,
) -> dict:
    """전략 파라미터를 base < tier < regime 우선순위로 병합한다."""
    tier_key = f"tier{tier}"
    tier_sp = sp.get(tier_key, {})
    regime_sp = sp.get("regime_override", {}).get(regime, {})
    # regime_override, tier 키 자체는 결과에서 제외
    base = {k: v for k, v in sp.items() if k != "regime_override" and not k.startswith("tier")}
    return {**base, **tier_sp, **regime_sp}
```

`generate_signals()` 내에서 기존 `merged_sp = {**sp, **tier_sp}` 로직을 `_merge_strategy_params()` 호출로 교체. 호출 시 `regime` 인자는 `regime.value` (문자열, 예: `"WEAK_DOWN"`)로 전달:

```python
merged_sp = _merge_strategy_params(sp, tier=tier_params.tier.value, regime=regime.value)
```

- [ ] **Step 3: Run tests + Commit**

```bash
cd /home/bythejune/projects/bithumb-bot-v2-dev
pytest tests/test_regime_override.py -v
ruff check strategy/rule_engine.py tests/test_regime_override.py
ruff format strategy/rule_engine.py tests/test_regime_override.py
git add strategy/rule_engine.py tests/test_regime_override.py
git commit -m "feat: add regime_override parameter merging (base < tier < regime)"
```

---

### Task 3: ShadowParams 재설계

**Files:**
- Modify: `strategy/darwin_engine.py` — ShadowParams, _mutate(), _initialize_population(), record_cycle()
- Modify: `tests/test_darwin.py` (있으면 업데이트)

- [ ] **Step 1: Redesign ShadowParams dataclass**

`strategy/darwin_engine.py`의 `ShadowParams` (lines 56-68) 교체:

```python
@dataclass
class ShadowParams:
    """Shadow 파라미터 세트 — strategy_params와 동일 구조."""

    shadow_id: str = ""
    group: str = "conservative"
    # mean_reversion 파라미터
    mr_sl_mult: float = 7.0
    mr_tp_rr: float = 1.5
    # dca 파라미터
    dca_sl_pct: float = 0.05
    dca_tp_pct: float = 0.03
    # 진입 기준
    cutoff: float = 72.0
```

- [ ] **Step 2: Update MUTATION_RANGES**

기존 MUTATION_RANGES (lines 37-44) 교체:

```python
MUTATION_RANGES: dict[str, tuple[float, float, float]] = {
    # (delta, min, max)
    "mr_sl_mult": (0.5, 2.0, 10.0),
    "mr_tp_rr": (0.3, 1.0, 4.0),
    "dca_sl_pct": (0.005, 0.02, 0.08),
    "dca_tp_pct": (0.005, 0.01, 0.05),
    "cutoff": (3.0, 55.0, 90.0),
}
```

- [ ] **Step 3: Update _mutate() method**

`_mutate()` (lines 189-210)을 새 필드에 맞게 수정. 기존 `rsi_lower`, `rsi_upper`, `atr_mult`, `tp_pct`, `sl_pct` 참조를 모두 새 필드로 교체.

- [ ] **Step 4: Update record_cycle()**

`record_cycle()` (lines 212-317)에서 Shadow의 가상 매매 판단 시:
- 기존: `shadow.cutoff`로 진입 판단, `shadow.sl_pct`/`shadow.tp_pct`로 SL/TP 설정
- 변경: `shadow.cutoff`로 진입 판단, 전략별로 `shadow.mr_sl_mult`/`shadow.mr_tp_rr` 또는 `shadow.dca_sl_pct`/`shadow.dca_tp_pct` 사용

- [ ] **Step 5: Add champion_to_strategy_params()**

```python
def champion_to_strategy_params(self) -> dict:
    """챔피언 파라미터를 strategy_params 형식으로 변환한다."""
    c = self._champion
    return {
        "mean_reversion": {
            "sl_mult": c.mr_sl_mult,
            "tp_rr": c.mr_tp_rr,
        },
        "dca": {
            "sl_pct": c.dca_sl_pct,
            "tp_pct": c.dca_tp_pct,
        },
    }
```

- [ ] **Step 6: Run tests + Commit**

```bash
cd /home/bythejune/projects/bithumb-bot-v2-dev
pytest tests/test_darwin.py -v
ruff check strategy/darwin_engine.py
ruff format strategy/darwin_engine.py
git add strategy/darwin_engine.py
git commit -m "feat: redesign ShadowParams to match strategy_params structure"
```

---

### Task 4: Darwin 30일 롤링 윈도우 + 하위 멸종 + 동적 변이 + 강제 다양성

**Files:**
- Modify: `strategy/darwin_engine.py` — run_tournament(), _initialize_population()
- Modify: `tests/test_darwin.py`

- [ ] **Step 1: 30일 롤링 윈도우**

`run_tournament()` (lines 319-365) 수정:
- 토너먼트 시작 시 각 Shadow의 30일 이전 거래 제거
- 성과 리셋 삭제
- 최소 거래수: 5 → 30

- [ ] **Step 2: 하위 30% 멸종**

`run_tournament()` 내 생존/멸종 로직:
```python
# 상위 70% 생존
survive_count = max(1, int(len(ranked) * 0.7))
survivors = ranked[:survive_count]
# 하위 30% 멸종 → 상위 생존자 기반 재생성
extinct_count = len(self._shadows) - survive_count
```

- [ ] **Step 3: 동적 변이율**

`run_tournament()` 시그니처에 `market_regime` 파라미터 추가 (기존 `top_survive` 제거, 70% 생존으로 대체):
`run_tournament(self, market_regime: Regime | None = None) -> list[CompositeScore]`

`Regime` import 추가: `from app.data_types import Regime` (기존 import에 추가)

```python
def _get_mutation_rate(self, market_regime: Regime | None) -> float:
    """시장 국면에 따른 변이율을 반환한다."""
    if market_regime is None:
        return 0.2
    if market_regime == Regime.CRISIS:
        return 0.4
    if market_regime == Regime.WEAK_DOWN:
        return 0.2
    return 0.1  # RANGE, WEAK_UP, STRONG_UP
```

- [ ] **Step 4: 강제 다양성**

`_enforce_diversity()` 메서드 추가:
```python
def _enforce_diversity(self) -> int:
    """유사 Shadow를 강제 변이시킨다. 변이된 수를 반환한다."""
    # 정규화 유클리드 거리 계산
    # 거리 < 0.1인 쌍 → 한쪽 강제 변이
```

- [ ] **Step 5: get_market_regime 헬퍼 추가**

`app/main.py`에 추가:
```python
def _get_market_regime(self) -> Regime | None:
    """10개 코인의 국면 최빈값을 반환한다."""
    from collections import Counter
    states = self._rule_engine._regime_states
    if not states:
        return None
    counts = Counter(rs.current for rs in states.values())
    return counts.most_common(1)[0][0]
```

- [ ] **Step 6: 챔피언 교체 조건 강화**

`check_champion_replacement()` (lines 367-410):
- 최소 거래수: 10 → 30

- [ ] **Step 7: Run tests + Commit**

```bash
cd /home/bythejune/projects/bithumb-bot-v2-dev
pytest tests/test_darwin.py -v
ruff check strategy/darwin_engine.py
git add strategy/darwin_engine.py
git commit -m "feat: Darwin 30-day rolling window, extinction, dynamic mutation, diversity"
```

---

### Task 5: 챔피언 → 실전 적용 + 자동 롤백

**Files:**
- Modify: `app/main.py` — Darwin 챔피언 적용, 롤백 체크
- Modify: `app/journal.py` — `get_trades_since()` 메서드 추가
- Modify: `backtesting/daemon.py` — auto_optimize PF 비교 로직

- [ ] **Step 1: Darwin 챔피언 적용 로직 in main.py**

`run()` 메서드에서 토너먼트 + 챔피언 적용 로직 추가. 주간 토너먼트 시점(기존 Darwin shadow_top3 로직 근처):

```python
# 토너먼트 실행 (주간)
market_regime = self._get_market_regime()
self._darwin.run_tournament(market_regime=market_regime)

# 챔피언 교체 확인
new_champion = self._darwin.check_champion_replacement()
if new_champion:
    champ_params = self._darwin.champion_to_strategy_params()
    champ_perf = self._darwin.get_champion_performance()
    # 3단계 검증
    if (
        champ_perf.trade_count >= 30
        and champ_perf.profit_factor > current_config_pf
        and champ_perf.max_drawdown <= 0.15
    ):
        # config.yaml에 쓰기
        self._backtest_daemon._apply_optimized_params(
            "mean_reversion", champ_params["mean_reversion"], config_path,
        )
        self._backtest_daemon._apply_optimized_params(
            "dca", champ_params["dca"], config_path,
        )
        # 롤백 모니터링 등록
        self._experiment_store.log_param_change(...)
        # 점진적 적용 활성화
        self._pilot_remaining = 20
        self._pilot_size_mult = 0.5
```

- [ ] **Step 2: Journal에 get_trades_since() 추가**

`app/journal.py`에 메서드 추가:

```python
def get_trades_since(self, timestamp_sec: int) -> list[dict]:
    """지정 시각 이후의 거래를 조회한다.

    Args:
        timestamp_sec: 유닉스 타임스탬프 (초).

    Returns:
        거래 목록.
    """
    timestamp_ms = timestamp_sec * 1000
    rows = self._conn.execute(
        "SELECT * FROM trades WHERE exit_time >= ?",
        (timestamp_ms,),
    ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 3: main.py에 _calc_pf() 헬퍼 추가**

```python
@staticmethod
def _calc_pf(trades: list[dict]) -> float:
    """거래 목록에서 Profit Factor를 계산한다."""
    gross_profit = sum(t.get("net_pnl_krw", 0) for t in trades if (t.get("net_pnl_krw") or 0) > 0)
    gross_loss = abs(sum(t.get("net_pnl_krw", 0) for t in trades if (t.get("net_pnl_krw") or 0) < 0))
    if gross_loss == 0:
        return 99.0 if gross_profit > 0 else 0.0
    return gross_profit / gross_loss
```

- [ ] **Step 4: 롤백 체크 in _close_position()**

`_close_position()` 끝부분에 롤백 체크 추가:

```python
# 롤백 모니터링 체크
await self._check_rollback()
```

`_check_rollback`은 **async** 메서드로 정의:

```python
async def _check_rollback(self) -> None:
    """파라미터 변경 모니터링 + 자동 롤백."""
    active = self._experiment_store.get_active_changes()
    for change in active:
        change_time = change["timestamp"]
        trades = self._journal.get_trades_since(change_time)
        if len(trades) >= 20:
            pf = self._calc_pf(trades)
            if pf >= change["baseline_pf"]:
                self._experiment_store.update_change_status(change["id"], "confirmed")
            else:
                await self._rollback_params(change, pf)
        elif len(trades) >= 10:
            pf = self._calc_pf(trades)
            if pf < change["baseline_pf"] * 0.9:
                await self._rollback_params(change, pf)
        elif int(time.time()) > change["monitoring_until"]:
            self._experiment_store.update_change_status(change["id"], "confirmed")

async def _rollback_params(self, change: dict, current_pf: float) -> None:
    """파라미터를 이전 값으로 롤백한다."""
    import shutil
    self._experiment_store.update_change_status(change["id"], "rolled_back")
    backup = Path(change["backup_path"])
    if backup.exists():
        shutil.copy2(backup, self._config_path)
    self._pilot_remaining = 0
    self._pilot_size_mult = 1.0
    await self._notifier.send(
        f"<b>⚠ 파라미터 자동 롤백</b>\n"
        f"source: {change['source']} | strategy: {change['strategy']}\n"
        f"변경 후 PF: {current_pf:.2f} (기준: {change['baseline_pf']:.2f})",
        channel="system",
    )
```

- [ ] **Step 3: Auto-Optimize PF 비교**

`backtesting/daemon.py`의 `_run_auto_optimize()` 수정:
- 기존: `if result.profit_factor >= self._config.auto_apply_min_pf`
- 변경: 현재 config의 전략 PF와 비교하여 더 나은 경우만 적용

- [ ] **Step 4: Commit**

```bash
cd /home/bythejune/projects/bithumb-bot-v2-dev
ruff check app/main.py backtesting/daemon.py
git add app/main.py backtesting/daemon.py
git commit -m "feat: connect Darwin champion to live trading + auto-rollback"
```

---

### Task 6: 점진적 적용 (Pilot)

**Files:**
- Modify: `strategy/position_manager.py` — pilot_size_mult 적용
- Modify: `app/main.py` — pilot 상태 관리
- Modify: `app/storage.py` — pilot 상태 영속화

- [ ] **Step 1: position_manager에 pilot 지원 추가**

`calculate_size()` 메서드에 `pilot_mult` 파라미터 추가:

```python
def calculate_size(
    self, signal, tier_params, size_decision, active_positions,
    weekly_dd_pct=0.0, candles_1h=None,
    pilot_mult: float = 1.0,  # 신규
) -> SizingResult:
    ...
    final_size = size_krw * pilot_mult  # 최종 사이즈에 적용
```

- [ ] **Step 2: main.py에서 pilot 상태 전달**

주문 시 `pilot_mult`를 position_manager에 전달:

```python
sizing = self._position_manager.calculate_size(
    ...,
    pilot_mult=self._pilot_size_mult,
)
```

- [ ] **Step 3: pilot 상태 영속화**

`app/main.py`의 `_save_state()` 메서드 (line 324)에 pilot 상태 추가:
```python
"pilot_remaining": self._pilot_remaining,
"pilot_size_mult": self._pilot_size_mult,
```

`_restore_state()` 메서드 (line 235)에서 복원:
```python
self._pilot_remaining = state.get("pilot_remaining", 0)
self._pilot_size_mult = state.get("pilot_size_mult", 1.0)
```

- [ ] **Step 4: Commit**

```bash
cd /home/bythejune/projects/bithumb-bot-v2-dev
ruff check strategy/position_manager.py app/main.py app/storage.py
git add strategy/position_manager.py app/main.py app/storage.py
git commit -m "feat: add pilot sizing (50% for first 20 trades after param change)"
```

---

### Task 7: 자율 연구 대상 확장

**Files:**
- Modify: `strategy/auto_researcher.py` — PARAM_BOUNDS, 프롬프트 개선

- [ ] **Step 1: PARAM_BOUNDS 확장**

`PARAM_BOUNDS` (lines 21-32) 수정:

```python
PARAM_BOUNDS: dict[str, dict[str, tuple[float, float]]] = {
    "trend_follow": {
        "sl_mult": (1.0, 5.0),
        "tp_rr": (1.0, 5.0),
        "cutoff_full": (55, 90),
        "w_trend_align": (0, 45),
        "w_macd": (0, 40),
        "w_volume": (0, 35),
        "w_rsi_pullback": (0, 30),
        "w_supertrend": (0, 25),
    },
    "mean_reversion": {
        "sl_mult": (2.0, 10.0),
        "tp_rr": (1.0, 4.0),
    },
    "dca": {
        "sl_pct": (0.02, 0.08),
        "tp_pct": (0.01, 0.05),
    },
}
```

- [ ] **Step 2: DeepSeek 프롬프트에 실패 이력 + 국면 정보 추가**

`_propose_experiment()` 메서드의 프롬프트에 추가 데이터:
- 실패 실험 이력 (ExperimentStore에서 조회)
- 최근 국면 분포

- [ ] **Step 3: run_session()에서 실제 매매 전략만 실험**

현재 `"trend_follow"`만 실험 → journal에서 최근 7일 거래의 전략 분포를 조회하여, 사용된 전략만 실험 대상에 포함.

- [ ] **Step 4: 실험 결과를 ExperimentStore에 기록**

`run_session()` 내에서 각 실험 결과를 `experiment_store.record()` 호출로 저장.

- [ ] **Step 5: Commit**

```bash
cd /home/bythejune/projects/bithumb-bot-v2-dev
ruff check strategy/auto_researcher.py
git add strategy/auto_researcher.py
git commit -m "feat: expand auto-research to mean_reversion/dca + failure memory"
```

---

### Task 8: 일일 리뷰 피드백 루프 연결

**Files:**
- Modify: `strategy/review_engine.py` — `_apply_and_verify_rules()` 추가

- [ ] **Step 1: `_apply_and_verify_rules()` 메서드 추가**

```python
async def _apply_and_verify_rules(
    self, adjustments: list[dict],
) -> list[dict]:
    """조정 사항을 백테스트로 검증 후 config에 적용한다."""
    applied = []
    for adj in adjustments:
        # 백테스트 실행 (최근 7일)
        # PF 비교
        # 개선 시 _apply_optimized_params()로 config 쓰기
        # experiment_store에 기록
    return applied
```

- [ ] **Step 2: run_daily_review()에서 호출**

기존 `_apply_rules()` 호출 후 `_apply_and_verify_rules()`를 추가 호출.

- [ ] **Step 3: Commit**

```bash
cd /home/bythejune/projects/bithumb-bot-v2-dev
ruff check strategy/review_engine.py
git add strategy/review_engine.py
git commit -m "feat: connect daily review adjustments to config via backtest verification"
```

---

### Task 9: 주간 리뷰 피드백 루프 연결

**Files:**
- Modify: `strategy/review_engine.py` — `_apply_verified_suggestions()` 추가

- [ ] **Step 1: `_apply_verified_suggestions()` 메서드 추가**

```python
async def _apply_verified_suggestions(
    self, suggestions: list[dict],
) -> int:
    """DeepSeek 제안을 백테스트 검증 후 config에 적용한다."""
    applied = 0
    for suggestion in suggestions:
        # 파라미터 변경 적용
        # 백테스트 (최근 30일)
        # PF 개선 + MDD ≤ 15% → config 적용
        # experiment_store에 기록
    return applied
```

- [ ] **Step 2: run_weekly_review()에서 호출**

기존 `_validate_suggestions()` 호출 후 `_apply_verified_suggestions()`를 추가 호출.

- [ ] **Step 3: Commit**

```bash
cd /home/bythejune/projects/bithumb-bot-v2-dev
ruff check strategy/review_engine.py
git add strategy/review_engine.py
git commit -m "feat: connect weekly review DeepSeek suggestions to config via backtest"
```

---

### Task 10: Shadow 거래 영속화

**Files:**
- Modify: `strategy/darwin_engine.py` — Shadow 거래 저장/복원

- [ ] **Step 1: Shadow 거래 DB 테이블 추가**

`ExperimentStore`의 `experiment_history.db`에 shadow_trades 테이블 추가 (별도 DB 파일 불필요):

```sql
CREATE TABLE IF NOT EXISTS shadow_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shadow_id TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    would_enter INTEGER NOT NULL,
    signal_score REAL NOT NULL,
    virtual_pnl REAL NOT NULL DEFAULT 0.0
);
```

- [ ] **Step 2: record_cycle()에서 DB에 저장**

가상 거래 발생 시 DB에도 기록.

- [ ] **Step 3: 초기화 시 DB에서 30일 이내 거래 복원**

`DarwinEngine.__init__()`에서 DB로부터 거래 기록 복원.

- [ ] **Step 4: Commit**

```bash
cd /home/bythejune/projects/bithumb-bot-v2-dev
ruff check strategy/darwin_engine.py
git add strategy/darwin_engine.py
git commit -m "feat: persist shadow trades to SQLite for 30-day rolling window"
```

---

### Task 11: config.yaml 초기 regime_override 설정

**Files:**
- Modify: `configs/config.yaml`

- [ ] **Step 1: regime_override 추가**

```yaml
strategy_params:
  mean_reversion:
    sl_mult: 7.0
    tp_rr: 1.5
    regime_override:
      RANGE:
        sl_mult: 5.0
        tp_rr: 2.0
      WEAK_DOWN:
        sl_mult: 8.0
        tp_rr: 1.2
  dca:
    sl_pct: 0.05
    tp_pct: 0.03
    regime_override:
      WEAK_DOWN:
        sl_pct: 0.06
        tp_pct: 0.025
```

- [ ] **Step 2: Commit**

```bash
cd /home/bythejune/projects/bithumb-bot-v2-dev
git add configs/config.yaml
git commit -m "feat: add initial regime_override params for mean_reversion and dca"
```

---

### Task 12: 통합 테스트 + 린트

**Files:** 전체

- [ ] **Step 1: ruff check**

Run: `cd /home/bythejune/projects/bithumb-bot-v2-dev && ruff check .`

- [ ] **Step 2: ruff format**

Run: `ruff format --check .`

- [ ] **Step 3: 전체 테스트**

Run: `pytest tests/ -v --ignore=tests/test_bithumb_api.py`

- [ ] **Step 4: 필요시 수정 + Commit**

수정한 파일만 개별적으로 staging:

```bash
git add strategy/ app/ backtesting/ configs/ tests/
git commit -m "fix: resolve integration issues from evolution-complete"
```
