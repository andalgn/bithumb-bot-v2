# Strategy Optimization Backtesting Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 현재 손실 중인 전략 A/B/C/D를 체계적 파라미터 최적화로 개선하고, Walk-Forward 검증으로 과적합을 방지한다.

**Architecture:** Grid Search → Walk-Forward 검증 → 최적 파라미터 적용의 3단계 파이프라인. 전략별 독립 최적화 후 통합 백테스트로 검증. 모든 최적화는 Out-of-Sample 데이터에서 검증되어야 하며, In-Sample 성과만으로 파라미터를 채택하지 않는다.

**Tech Stack:** Python 3.11+, numpy, SQLite (market_data.db)

**Task 순서:** Task 1(Grid 정의) → Task 5(SL/TP 외부화) → Task 2(Optimizer) → Task 3(WF 검증) → Task 4(실행 스크립트) → Task 6(통합 검증)

---

## 현재 상태 (Baseline)

최근 백테스트 (31일, 10개 코인):

| 전략 | 거래 | 승률 | PF | Expectancy | PnL |
|------|------|------|-----|------------|-----|
| A 추세추종 | 139 | 35.3% | 0.20 | -16,464 | -2,288K |
| B 반전포착 | 47 | 31.9% | 0.12 | -2,211 | -104K |
| C 브레이크아웃 | 79 | 25.3% | 0.87 | -4,136 | -327K |
| D 스캘핑 | 12 | 41.7% | 0.03 | -129,061 | -1,549K |
| **E DCA** | **10** | **60.0%** | **1.67** | **506,505** | **+5,065K** |
| **합계** | **287** | **33.1%** | — | — | **+797K** |

**핵심 문제**: DCA만 수익, 나머지 4개 전략 모두 손실. 총 PnL이 +80만이지만 DCA 제거 시 -430만.

## 최적화 대상 파라미터

| 전략 | 파라미터 | 현재값 | 탐색 범위 | 단위 |
|------|----------|--------|-----------|------|
| **공통** | score_cutoff_full | 75/80 | 65~90 | 5 step |
| **공통** | score_cutoff_probe | 60/65 | 50~80 | 5 step |
| **A** | sl_mult (ATR배수) | tier_based | 1.0~3.0 | 0.5 step |
| **A** | tp_rr (R:R 비율) | 2.5 | 1.5~4.0 | 0.5 step |
| **B** | sl_mult | 1.5 | 1.0~2.5 | 0.5 step |
| **B** | tp_rr | 2.0 | 1.2~3.0 | 0.4 step |
| **C** | sl_mult | 2.0 | 1.5~3.5 | 0.5 step |
| **C** | tp_rr | 3.0 | 2.0~5.0 | 0.5 step |
| **D** | sl_pct | 0.8% | 0.5~1.5% | 0.25 step |
| **D** | tp_pct | 1.5% | 1.0~3.0% | 0.5 step |
| **공통** | max_sl_pct (T1) | 1.5% | 1.0~2.5% | 0.5 step |

---

## File Structure

### 신규 생성
| 파일 | 역할 |
|------|------|
| `scripts/optimize.py` | 메인 최적화 스크립트 (Grid Search + WF 검증 + 결과 리포트) |
| `backtesting/optimizer.py` | ParameterOptimizer 클래스 (Grid Search 엔진) |
| `backtesting/param_grid.py` | 파라미터 그리드 정의 + 조합 생성 |
| `tests/test_optimizer.py` | 최적화 엔진 테스트 |

### 수정
| 파일 | 변경 |
|------|------|
| `scripts/download_and_backtest.py` | 최적화 결과 파라미터로 재실행 가능하도록 파라미터 주입 지원 |
| `strategy/rule_engine.py` | SL/TP 계산에서 외부 파라미터 오버라이드 지원 |
| `configs/config.yaml` | 최적화 결과 파라미터 반영 |

---

## Task 1: 파라미터 그리드 정의

**Files:**
- Create: `backtesting/param_grid.py`
- Test: `tests/test_optimizer.py`

- [ ] **Step 1: 파라미터 그리드 데이터 구조 정의**

```python
"""파라미터 그리드 정의.

전략별 최적화 대상 파라미터와 탐색 범위.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from itertools import product

@dataclass
class ParamRange:
    """파라미터 탐색 범위."""
    name: str
    values: list[float]

@dataclass
class StrategyParamGrid:
    """전략별 파라미터 그리드."""
    strategy: str
    params: list[ParamRange] = field(default_factory=list)

    def combinations(self) -> list[dict[str, float]]:
        """모든 파라미터 조합을 생성한다."""
        if not self.params:
            return [{}]
        names = [p.name for p in self.params]
        values = [p.values for p in self.params]
        return [dict(zip(names, combo)) for combo in product(*values)]

def build_grids() -> dict[str, StrategyParamGrid]:
    """전략별 파라미터 그리드를 생성한다."""
    grids = {}

    # 전략 A: 추세추종
    grids["trend_follow"] = StrategyParamGrid(
        strategy="trend_follow",
        params=[
            ParamRange("sl_mult", [1.0, 1.5, 2.0, 2.5, 3.0]),
            ParamRange("tp_rr", [1.5, 2.0, 2.5, 3.0, 3.5, 4.0]),
            ParamRange("cutoff_full", [70, 75, 80, 85]),
        ],
    )

    # 전략 B: 반전포착
    grids["mean_reversion"] = StrategyParamGrid(
        strategy="mean_reversion",
        params=[
            ParamRange("sl_mult", [1.0, 1.5, 2.0, 2.5]),
            ParamRange("tp_rr", [1.2, 1.6, 2.0, 2.4, 3.0]),
            ParamRange("cutoff_full", [70, 75, 80, 85]),
        ],
    )

    # 전략 C: 브레이크아웃
    grids["breakout"] = StrategyParamGrid(
        strategy="breakout",
        params=[
            ParamRange("sl_mult", [1.5, 2.0, 2.5, 3.0, 3.5]),
            ParamRange("tp_rr", [2.0, 2.5, 3.0, 4.0, 5.0]),
            ParamRange("cutoff_full", [75, 80, 85, 90]),
        ],
    )

    # 전략 D: 스캘핑
    grids["scalping"] = StrategyParamGrid(
        strategy="scalping",
        params=[
            ParamRange("sl_pct", [0.005, 0.008, 0.010, 0.012, 0.015]),
            ParamRange("tp_pct", [0.010, 0.015, 0.020, 0.025, 0.030]),
        ],
    )

    return grids
```

- [ ] **Step 2: 테스트 작성 — 그리드 조합 수 검증**

```python
def test_grid_combination_count():
    grids = build_grids()
    a = grids["trend_follow"]
    assert len(a.combinations()) == 5 * 6 * 4  # 120

def test_grid_keys():
    grids = build_grids()
    combo = grids["trend_follow"].combinations()[0]
    assert "sl_mult" in combo
    assert "tp_rr" in combo
    assert "cutoff_full" in combo
```

- [ ] **Step 3:** `ruff check` + `pytest` 통과 확인
- [ ] **Step 4:** Commit: `feat: add parameter grid definition for strategy optimization`

---

## Task 2: 파라미터 오버라이드 백테스트 엔진

**Files:**
- Create: `backtesting/optimizer.py`
- Modify: `scripts/download_and_backtest.py` (run_backtest에 param 주입 지원)

- [ ] **Step 1: optimizer.py — 단일 파라미터셋으로 백테스트 실행**

```python
"""파라미터 최적화 엔진.

Grid Search + Walk-Forward 검증.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from market.market_store import MarketStore
from strategy.coin_profiler import CoinProfiler
from strategy.rule_engine import RuleEngine
from app.data_types import Candle, MarketSnapshot, Strategy
from strategy.indicators import compute_indicators
import numpy as np

logger = logging.getLogger(__name__)

FEE_RATE = 0.0025
SLIPPAGE_RATE = 0.001

@dataclass
class OptResult:
    """단일 최적화 실행 결과."""
    params: dict[str, float]
    strategy: str
    trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    max_drawdown: float = 0.0
    sharpe: float = 0.0
    total_pnl: float = 0.0


class ParameterOptimizer:
    """전략 파라미터 최적화기."""

    def __init__(self, store: MarketStore, coins: list[str]) -> None:
        self._store = store
        self._coins = coins

    def run_single(
        self,
        strategy: str,
        params: dict[str, float],
        candles_15m: dict[str, list[Candle]],
        candles_1h: dict[str, list[Candle]],
    ) -> OptResult:
        """단일 파라미터셋으로 특정 전략만 백테스트한다."""
        # 전략별 SL/TP 파라미터를 오버라이드하여 시그널 평가
        trades = []
        for coin in self._coins:
            c15 = candles_15m.get(coin, [])
            c1h = candles_1h.get(coin, [])
            if len(c15) < 200 or len(c1h) < 200:
                continue
            coin_trades = self._backtest_coin(
                coin, strategy, params, c15, c1h,
            )
            trades.extend(coin_trades)

        return self._calc_stats(strategy, params, trades)
```

핵심: `_backtest_coin()`에서 `RuleEngine.generate_signals()`를 호출하되, SL/TP를 params로 오버라이드.

- [ ] **Step 2: _backtest_coin — 슬라이딩 윈도우 시뮬레이션**

기존 `download_and_backtest.py`의 `run_backtest` 로직을 재사용하되, 특정 전략만 필터링하고 SL/TP를 params로 계산.

```python
    def _backtest_coin(
        self, coin, strategy, params, candles_15m, candles_1h,
    ) -> list[dict]:
        """코인별 백테스트 실행."""
        window = 200
        step = 4
        trades = []
        position = None

        for i in range(window, len(candles_15m) - step, step):
            slice_15m = candles_15m[i - window: i]
            current_ts = slice_15m[-1].timestamp
            current_price = slice_15m[-1].close

            sync_1h = [c for c in candles_1h if c.timestamp <= current_ts]
            if len(sync_1h) < 50:
                continue
            sync_1h = sync_1h[-200:]

            # 포지션 보유 중 → SL/TP 체크
            if position is not None:
                future = candles_15m[i: i + step]
                hit_sl = any(c.low <= position["sl"] for c in future)
                hit_tp = any(c.high >= position["tp"] for c in future)
                if hit_sl or hit_tp:
                    exit_p = position["sl"] if hit_sl else position["tp"]
                    pnl = self._calc_pnl(position["entry"], exit_p)
                    trades.append({"pnl": pnl, "entry": position["entry"], "exit": exit_p})
                    position = None
                continue

            # 시그널 생성 + 전략 필터
            ind_15m = compute_indicators(slice_15m)
            ind_1h = compute_indicators(sync_1h)
            # ... 전략별 점수 계산, cutoff 체크 ...
            # SL/TP를 params에서 가져와 계산
            sl, tp = self._calc_sl_tp(strategy, params, current_price, ind_15m)
            if sl > 0 and tp > 0:
                position = {"entry": current_price, "sl": sl, "tp": tp}

        return trades
```

- [ ] **Step 3: _calc_sl_tp — 전략별 SL/TP 계산 (파라미터 기반)**

```python
    def _calc_sl_tp(self, strategy, params, price, ind_15m):
        atr = self._last_valid(ind_15m.atr)
        if atr <= 0:
            atr = price * 0.02

        if strategy == "scalping":
            sl = price * (1 - params.get("sl_pct", 0.008))
            tp = price * (1 + params.get("tp_pct", 0.015))
        else:
            sl_mult = params.get("sl_mult", 2.0)
            tp_rr = params.get("tp_rr", 2.5)
            sl_dist = min(atr * sl_mult, price * 0.015)  # SL cap
            sl = price - sl_dist
            tp = price + sl_dist * tp_rr

        return sl, tp
```

- [ ] **Step 4:** 테스트 + lint 통과 확인
- [ ] **Step 5:** Commit: `feat: add parameter optimizer with per-strategy backtesting`

---

## Task 3: Walk-Forward 기반 Grid Search

**Files:**
- Modify: `backtesting/optimizer.py` (optimize 메서드 추가)

- [ ] **Step 1: Grid Search + Walk-Forward 통합**

```python
    def optimize(
        self,
        strategy: str,
        grid: list[dict[str, float]],
        candles_15m: dict[str, list[Candle]],
        candles_1h: dict[str, list[Candle]],
        in_sample_ratio: float = 0.7,
    ) -> list[OptResult]:
        """Grid Search를 실행하고 Walk-Forward 검증한다.

        데이터를 70% In-Sample / 30% Out-of-Sample로 분할.
        In-Sample에서 최적 파라미터 탐색 → Out-of-Sample에서 검증.
        """
        results = []

        # 데이터 분할 (시간 기준, 모든 코인 누적)
        is_15m, oos_15m, is_1h, oos_1h = {}, {}, {}, {}
        for coin in self._coins:
            c15 = candles_15m.get(coin, [])
            if not c15:
                continue
            split_idx = int(len(c15) * in_sample_ratio)
            is_15m[coin] = c15[:split_idx]
            oos_15m[coin] = c15[split_idx - 200:]  # 200봉 워밍업 포함
            c1h = candles_1h.get(coin, [])
            ts_cutoff = c15[split_idx - 1].timestamp if split_idx > 0 else 0
            is_1h[coin] = [c for c in c1h if c.timestamp <= ts_cutoff]
            oos_1h[coin] = c1h

        # Phase 1: In-Sample Grid Search
        logger.info("Grid Search 시작: %s (%d 조합)", strategy, len(grid))
        is_results = []
        for params in grid:
            r = self.run_single(strategy, params, is_15m, is_1h)
            is_results.append(r)

        # 상위 5개 선별 (Profit Factor 기준)
        is_results.sort(key=lambda r: r.profit_factor, reverse=True)
        top5 = is_results[:5]

        # Phase 2: Out-of-Sample 검증
        logger.info("OOS 검증: 상위 %d개", len(top5))
        for r in top5:
            oos = self.run_single(strategy, r.params, oos_15m, oos_1h)
            oos.params = r.params  # 파라미터 보존
            results.append(oos)

        # OOS 거래 수 부족 경고
        for oos_r in results:
            if oos_r.trades < 10:
                logger.warning(
                    "OOS 거래 수 부족 (통계적 유의성 없음): %s %d건",
                    strategy, oos_r.trades,
                )

        # 과적합 감지: IS vs OOS Sharpe 차이 > 50%
        for is_r, oos_r in zip(top5, results):
            if is_r.sharpe > 0:
                diff = abs(is_r.sharpe - oos_r.sharpe) / is_r.sharpe
                if diff > 0.5:
                    logger.warning(
                        "과적합 감지: %s %s (IS=%.2f, OOS=%.2f, diff=%.0f%%)",
                        strategy, oos_r.params, is_r.sharpe, oos_r.sharpe, diff * 100,
                    )

        return results
```

- [ ] **Step 2: 테스트 — 과적합 감지 로직**

```python
def test_overfit_detection():
    # IS Sharpe=2.0, OOS Sharpe=0.5 → diff=75% → 과적합
    ...
```

- [ ] **Step 3:** Commit: `feat: add walk-forward grid search with overfit detection`

---

## Task 4: 최적화 실행 스크립트

**Files:**
- Create: `scripts/optimize.py`

- [ ] **Step 1: 메인 스크립트 — 데이터 로딩 + Grid Search + 리포트**

```python
"""전략 파라미터 최적화.

사용법: python scripts/optimize.py [--strategy trend_follow]
전략을 지정하지 않으면 A/B/C/D 전부 최적화.
"""
import argparse, asyncio, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import load_config
from backtesting.optimizer import ParameterOptimizer
from backtesting.param_grid import build_grids
from market.bithumb_api import BithumbClient
from market.market_store import MarketStore

async def main():
    config = load_config()
    store = MarketStore(db_path="data/market_data.db")

    # 1. 데이터 다운로드 (이미 있으면 스킵)
    client = BithumbClient(...)
    # ... download if needed ...

    # 2. 데이터 로딩
    candles_15m = {}
    candles_1h = {}
    for coin in config.coins:
        candles_15m[coin] = store.get_candles(coin, "15m", limit=5000)
        candles_1h[coin] = store.get_candles(coin, "1h", limit=5000)

    # 3. Grid Search
    optimizer = ParameterOptimizer(store, config.coins)
    grids = build_grids()

    all_results = {}
    for strategy, grid in grids.items():
        combos = grid.combinations()
        results = optimizer.optimize(strategy, combos, candles_15m, candles_1h)
        all_results[strategy] = results

    # 4. 결과 리포트
    print_report(all_results)

    # 5. 최적 파라미터 YAML 출력
    print_optimal_yaml(all_results)

    store.close()
```

- [ ] **Step 2: 리포트 포맷**

```
전략 A 추세추종:
  Baseline: PF=0.20, WR=35.3%, Exp=-16K
  최적 (OOS): PF=1.45, WR=42%, Exp=+12K
  파라미터: sl_mult=1.5, tp_rr=3.0, cutoff=80
  과적합: IS PF=1.8 → OOS PF=1.45 (차이 19%, OK)
```

- [ ] **Step 3: config.yaml 자동 업데이트 옵션 (--apply)**

```python
if args.apply:
    # config.yaml의 해당 파라미터를 최적값으로 업데이트
    update_config_yaml(optimal_params)
```

- [ ] **Step 4:** Commit: `feat: add optimization script with report and auto-apply`

---

## Task 5: 전략별 SL/TP 파라미터 외부화

**Files:**
- Modify: `strategy/rule_engine.py` (SL/TP 하드코딩 → config 기반)
- Modify: `configs/config.yaml` (전략별 SL/TP 파라미터 섹션)
- Modify: `app/config.py` (StrategySlTpConfig dataclass)

- [ ] **Step 1: config.yaml에 전략별 SL/TP 파라미터 추가**

```yaml
# 전략별 SL/TP 파라미터
strategy_params:
  trend_follow:
    sl_mult: 2.0      # ATR × sl_mult
    tp_rr: 2.5         # SL 거리 × tp_rr
  mean_reversion:
    sl_mult: 1.5
    tp_rr: 2.0
  breakout:
    sl_mult: 2.0
    tp_rr: 3.0
  scalping:
    sl_pct: 0.008      # 고정 0.8%
    tp_pct: 0.015       # 고정 1.5%
  dca:
    sl_pct: 0.03        # 고정 3%
    tp_pct: 0.05        # 고정 5%
```

- [ ] **Step 2: rule_engine.py에서 하드코딩 SL/TP → config 참조**

```python
# 기존:
# stop_loss = price - atr_val * 2.0
# take_profit = price + atr_val * 2.0 * 3

# 변경:
sp = self._strategy_params.get(best.strategy.value, {})
if best.strategy == Strategy.SCALPING:
    stop_loss = price * (1 - sp.get("sl_pct", 0.008))
    take_profit = price * (1 + sp.get("tp_pct", 0.015))
elif best.strategy == Strategy.DCA:
    stop_loss = price * (1 - sp.get("sl_pct", 0.03))
    take_profit = price * (1 + sp.get("tp_pct", 0.05))
else:
    sl_m = sp.get("sl_mult", 2.0)
    tp_r = sp.get("tp_rr", 2.5)
    sl_dist = min(atr_val * sl_m, sl_cap)
    stop_loss = price - sl_dist
    take_profit = price + sl_dist * tp_r
```

- [ ] **Step 3: RuleEngine에 strategy_params 주입**

```python
class RuleEngine:
    def __init__(self, ..., strategy_params=None):
        self._strategy_params = strategy_params or {}
```

- [ ] **Step 4:** 기존 테스트 전부 통과 확인 (기본값이 현재와 동일하므로 변경 없어야 함)
- [ ] **Step 5:** Commit: `refactor: externalize strategy SL/TP params to config.yaml`

---

## Task 6: 통합 검증 + 결과 리포트

**Files:**
- 없음 (실행만)

- [ ] **Step 1:** 데이터 다운로드: `python scripts/download_and_backtest.py` (최신 데이터 확보)
- [ ] **Step 2:** Baseline 백테스트 실행 (현재 파라미터)
- [ ] **Step 3:** 최적화 실행: `python scripts/optimize.py`
- [ ] **Step 4:** 최적 파라미터 적용: `python scripts/optimize.py --apply`
- [ ] **Step 5:** 최적화 후 백테스트 실행 (새 파라미터)
- [ ] **Step 6:** Before/After 비교 리포트 작성
- [ ] **Step 7:** 텔레그램으로 결과 전송
- [ ] **Step 8:** Commit: `feat: strategy optimization results — before/after comparison`

---

## 성공 기준

| 지표 | Baseline | 목표 | 비활성화 기준 |
|------|----------|------|-------------|
| 전략 A PF | 0.20 | OOS PF > 0.7 | OOS PF < 0.5 → 비활성화 |
| 전략 B PF | 0.12 | OOS PF > 0.7 | OOS PF < 0.5 → 비활성화 |
| 전략 C PF | 0.87 | OOS PF > 1.0 | OOS PF < 0.7 → 비활성화 |
| 전략 D PF | 0.03 | OOS PF > 0.5 | OOS 거래 < 10건 → 판단 보류 |
| OOS 과적합 | N/A | IS-OOS 차이 < 50% | > 50% → 해당 파라미터 폐기 |
| OOS 거래 수 | N/A | >= 10건 | < 10건 → 통계 무의미 경고 |

**비활성화 판단 기준**: 최적화 후에도 OOS PF < 0.5인 전략은 PAPER에서 Shadow 모드로 전환. 시그널만 기록하고 실거래하지 않음. 데이터 축적 후 재평가.

## 주의사항

1. **과적합 방지**: Grid Search 결과를 In-Sample에서만 보고 채택하면 안 됨. 반드시 OOS 검증
2. **샘플 수**: 전략 D(스캘핑)는 12건뿐이라 통계적 유의성 부족. 결과 해석 주의
3. **데이터 한계**: 15M 데이터는 ~31일분만 있음. 70/30 분할 시 OOS ~9일 (전략별 5~10건). 1H 데이터(209일)로 보조 검증 권장
4. **cutoff_probe 미포함**: Grid에 cutoff_full만 포함. probe 범위는 full-10 고정으로 자동 계산
