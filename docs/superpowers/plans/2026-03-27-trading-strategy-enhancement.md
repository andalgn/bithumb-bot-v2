# Trading Strategy Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 수익성 향상을 위한 3단계 전략 강화 — ATR 기반 포지션 사이징 + 코인 간 모멘텀 랭킹 + 동적 코인 유니버스, 모두 기존 봇 운영을 중단하지 않고 feature flag로 안전하게 배포.

**Architecture:** 각 Phase는 독립적인 feature flag(`*_enabled: false`)로 배포 후 `true`로 전환. Phase 1→2→3 순서로 검증. 기존 봇은 LIVE 운영 상태 유지, 코드 변경 후 `sudo systemctl restart bithumb-bot` 으로 재시작.

**Tech Stack:** Python 3.12+, numpy, aiohttp (async), pytest, SQLite, systemd

---

## 파일 구조

| 파일 | 변경 | 역할 |
|------|------|------|
| `app/config.py` | 수정 | `SizingConfig`에 ATR 필드 추가; `CoinUniverseConfig` 신규 dataclass |
| `configs/config.yaml` | 수정 | feature flag 추가 (3개 Phase) |
| `strategy/position_manager.py` | 수정 | `_calc_atr_mult()` 추가, `calculate_size()` 시그니처 확장 |
| `app/main.py` | 수정 | `calculate_size()` 호출에 `ind_1h`/`current_price` 전달; `MomentumRanker` 적용; 코인 목록 일일 갱신 |
| `market/bithumb_api.py` | 수정 | `get_all_tickers()` 추가 |
| `strategy/momentum_ranker.py` | **신규** | 코인 간 횡단면 모멘텀 점수 계산 및 순위 결정 |
| `strategy/coin_universe.py` | **신규** | 빗썸 거래량 기준 동적 코인 유니버스 관리 |
| `tests/test_position_manager_atr.py` | **신규** | Phase 1 ATR 사이징 단위 테스트 |
| `tests/test_momentum_ranker.py` | **신규** | Phase 2 모멘텀 랭커 단위 테스트 |
| `tests/test_coin_universe.py` | **신규** | Phase 3 코인 유니버스 단위 테스트 |

---

## Task 1: ATR 기반 사이징 — config 필드 추가

**Files:**
- Modify: `app/config.py:20-33` (`SizingConfig` dataclass)
- Modify: `configs/config.yaml:16-25` (`sizing:` 섹션)

- [ ] **Step 1: `SizingConfig`에 ATR 관련 필드 3개 추가**

`app/config.py` 의 `SizingConfig` dataclass (`class SizingConfig:` 블록) 끝에 아래 3줄 추가:

```python
@dataclass(frozen=True)
class SizingConfig:
    """사이징 설정."""

    active_risk_pct: float = 0.03
    core_risk_pct: float = 0.10
    reserve_risk_pct: float = 0.05
    dca_core_pct: float = 0.04
    pool_cap_pct: float = 0.25
    active_min_krw: int = 5000
    core_min_krw: int = 10000
    vol_target_mult_min: float = 0.5
    vol_target_mult_max: float = 1.5
    defense_mult_min: float = 0.3
    defense_mult_max: float = 1.0
    atr_sizing_enabled: bool = False
    atr_target_pct: float = 0.01
```

- [ ] **Step 2: `configs/config.yaml` sizing 섹션에 ATR 플래그 추가**

`sizing:` 섹션 끝에 두 줄 추가:

```yaml
sizing:
  active_risk_pct: 0.07
  core_risk_pct: 0.1
  reserve_risk_pct: 0.05
  dca_core_pct: 0.04
  pool_cap_pct: 0.25
  active_min_krw: 5000
  core_min_krw: 10000
  vol_target_mult_min: 0.8
  vol_target_mult_max: 1.5
  defense_mult_min: 0.3
  defense_mult_max: 1.0
  atr_sizing_enabled: false
  atr_target_pct: 0.01
```

- [ ] **Step 3: 설정 로딩 테스트 실행**

```bash
cd /home/bythejune/projects/bithumb-bot-v2 && source venv/bin/activate
pytest tests/test_config.py -q
```
Expected: PASS (기존 `_build_sizing`은 `**kwargs` 방식이므로 추가 코드 없이 자동 처리)

- [ ] **Step 4: 커밋**

```bash
git add app/config.py configs/config.yaml
git commit -m "feat: add ATR sizing config fields (disabled by default)"
```

---

## Task 2: ATR 기반 사이징 — PositionManager 구현

**Files:**
- Modify: `strategy/position_manager.py:73-158` (`calculate_size`, `_calc_vol_target_mult`)
- Create: `tests/test_position_manager_atr.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_position_manager_atr.py
"""ATR 기반 포지션 사이징 단위 테스트."""
from __future__ import annotations

import numpy as np
import pytest

from app.config import SizingConfig
from app.data_types import Pool, Regime, Signal
from strategy.coin_profiler import TierParams, Tier
from strategy.correlation_monitor import CorrelationMonitor
from strategy.indicators import IndicatorPack
from strategy.pool_manager import PoolManager
from strategy.position_manager import PositionManager
from strategy.rule_engine import SizeDecision


def _make_pm(atr_sizing_enabled: bool = False, atr_target_pct: float = 0.01) -> PositionManager:
    pool = PoolManager.__new__(PoolManager)
    pool._balances = {Pool.ACTIVE: 1_000_000.0, Pool.CORE: 500_000.0, Pool.RESERVE: 200_000.0}
    pool._lock = __import__("threading").Lock()
    corr = CorrelationMonitor.__new__(CorrelationMonitor)
    corr._matrix = {}
    corr._skip_threshold = 0.85
    corr._reduce_threshold_min = 0.70
    corr._reduce_threshold_max = 0.85
    corr._reduce_mult = 0.5
    cfg = SizingConfig(
        active_risk_pct=0.07,
        atr_sizing_enabled=atr_sizing_enabled,
        atr_target_pct=atr_target_pct,
    )
    return PositionManager(pool, corr, cfg)


def _make_signal() -> Signal:
    return Signal(
        symbol="BTC",
        strategy="trend_follow",
        score=80,
        entry_price=50_000_000.0,
        stop_loss=48_000_000.0,
        take_profit=54_000_000.0,
        regime=Regime.STRONG_UP,
    )


def _make_tier() -> TierParams:
    return TierParams(
        tier=Tier.TIER1,
        atr_pct=0.005,
        position_mult=1.0,
        rsi_min=35,
        rsi_max=65,
        atr_stop_mult=2.5,
        spread_limit=0.0018,
    )


def _make_ind(atr_val: float) -> IndicatorPack:
    atr_arr = np.full(100, atr_val)
    return IndicatorPack(atr=atr_arr)


def test_atr_sizing_disabled_uses_vol_target():
    """ATR 사이징 비활성화 시 기존 vol_target_mult 방식 사용."""
    pm = _make_pm(atr_sizing_enabled=False)
    result = pm.calculate_size(
        signal=_make_signal(),
        tier_params=_make_tier(),
        size_decision=SizeDecision.FULL,
        active_positions=[],
        ind_1h=_make_ind(500_000.0),
        current_price=50_000_000.0,
    )
    assert result.size_krw > 0
    assert "vol_target_mult" in result.detail


def test_atr_sizing_enabled_uses_atr_mult():
    """ATR 사이징 활성화 시 atr_mult 키가 detail에 존재."""
    pm = _make_pm(atr_sizing_enabled=True, atr_target_pct=0.01)
    # ATR = 500_000 KRW, price = 50_000_000 → atr_pct = 0.01 → mult = 1.0
    result = pm.calculate_size(
        signal=_make_signal(),
        tier_params=_make_tier(),
        size_decision=SizeDecision.FULL,
        active_positions=[],
        ind_1h=_make_ind(500_000.0),
        current_price=50_000_000.0,
    )
    assert result.size_krw > 0
    assert "atr_mult" in result.detail
    assert abs(result.detail["atr_mult"] - 1.0) < 0.01


def test_atr_sizing_high_volatility_reduces_size():
    """ATR 높을 때 포지션 축소."""
    pm = _make_pm(atr_sizing_enabled=True, atr_target_pct=0.01)
    # ATR = 1_000_000 KRW, price = 50_000_000 → atr_pct = 0.02 → mult = 0.5 (clamped to vol_target_mult_min=0.5)
    result = pm.calculate_size(
        signal=_make_signal(),
        tier_params=_make_tier(),
        size_decision=SizeDecision.FULL,
        active_positions=[],
        ind_1h=_make_ind(1_000_000.0),
        current_price=50_000_000.0,
    )
    assert result.detail.get("atr_mult", 1.0) <= 0.6


def test_atr_sizing_no_ind_falls_back():
    """ind_1h 없을 때 vol_target_mult fallback."""
    pm = _make_pm(atr_sizing_enabled=True)
    result = pm.calculate_size(
        signal=_make_signal(),
        tier_params=_make_tier(),
        size_decision=SizeDecision.FULL,
        active_positions=[],
        ind_1h=None,
        current_price=0.0,
    )
    assert result.size_krw > 0
    assert "vol_target_mult" in result.detail
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
pytest tests/test_position_manager_atr.py -q
```
Expected: FAIL (`calculate_size()` does not accept `ind_1h` or `current_price` params yet)

- [ ] **Step 3: `PositionManager` 수정 — `_calc_atr_mult` 추가 및 `calculate_size` 시그니처 확장**

`strategy/position_manager.py` 에서 `calculate_size` 메서드 시그니처와 내부 로직을 수정한다.

`calculate_size` 메서드의 파라미터 목록 끝에 두 개 추가:
```python
    def calculate_size(
        self,
        signal: Signal,
        tier_params: TierParams,
        size_decision: str,
        active_positions: list[str],
        weekly_dd_pct: float = 0.0,
        candles_1h: list[Candle] | None = None,
        pilot_mult: float = 1.0,
        ind_1h: object | None = None,
        current_price: float = 0.0,
    ) -> SizingResult:
```

그리고 `_calc_vol_target_mult` 호출 부분(line 113-114)을 아래로 교체:
```python
        if self._cfg.atr_sizing_enabled:
            sizing_mult = self._calc_atr_mult(ind_1h, current_price)
            detail["atr_mult"] = sizing_mult
        else:
            sizing_mult = self._calc_vol_target_mult(candles_1h)
            detail["vol_target_mult"] = sizing_mult

        opportunity = base * tier_mult * score_mult * sizing_mult
```

그리고 클래스 끝에 `_calc_atr_mult` 메서드 추가 (`_calc_vol_target_mult` 바로 뒤):
```python
    def _calc_atr_mult(self, ind_1h: object | None, current_price: float) -> float:
        """ATR 기반 사이징 배수를 계산한다.

        atr_target_pct / 실제_ATR_pct 로 배수를 구한다.
        목표 변동성(atr_target_pct=1%)보다 ATR이 크면 포지션 축소, 작으면 확대.
        """
        if ind_1h is None or current_price <= 0:
            return 1.0
        atr = getattr(ind_1h, "atr", np.array([]))
        if len(atr) == 0:
            return 1.0
        valid = atr[~np.isnan(atr)]
        if len(valid) == 0:
            return 1.0
        atr_pct = float(valid[-1]) / current_price
        if atr_pct <= 0:
            return 1.0
        mult = self._cfg.atr_target_pct / atr_pct
        return max(self._cfg.vol_target_mult_min, min(self._cfg.vol_target_mult_max, mult))
```

`calculate_core_size`의 `_calc_vol_target_mult` 호출도 동일하게 업데이트:
```python
        if self._cfg.atr_sizing_enabled:
            sizing_mult = self._calc_atr_mult(ind_1h, 0.0)
            detail["atr_mult"] = sizing_mult
        else:
            sizing_mult = self._calc_vol_target_mult(candles_1h)
            detail["vol_target_mult"] = sizing_mult

        opportunity = base * tier_mult * sizing_mult
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
pytest tests/test_position_manager_atr.py -q
```
Expected: 4 passed

- [ ] **Step 5: `main.py` 의 `calculate_size` 호출에 `ind_1h`와 `current_price` 추가**

`app/main.py` 에서 `calculate_size` 호출 부분(약 line 815-820):
```python
                size_result = self._position_manager.calculate_size(
                    signal=signal,
                    tier_params=tier_params,
                    size_decision=size_decision,
                    active_positions=active_coins,
                    weekly_dd_pct=weekly_dd,
                    candles_1h=data.snapshots[signal.symbol].candles_1h,
                    pilot_mult=self._pilot_size_mult,
                    ind_1h=data.indicators_1h.get(signal.symbol),
                    current_price=data.current_prices.get(signal.symbol, 0.0),
                )
```

- [ ] **Step 6: 전체 테스트 통과 확인**

```bash
pytest tests/ -q --ignore=tests/test_bithumb_api.py
```
Expected: all pass

- [ ] **Step 7: 커밋**

```bash
git add strategy/position_manager.py app/main.py tests/test_position_manager_atr.py
git commit -m "feat: add ATR-based position sizing (feature flag atr_sizing_enabled)"
```

---

## Task 3: ATR 사이징 LIVE 검증 및 활성화

**Files:**
- Modify: `configs/config.yaml` (sizing 섹션)

이 Task는 코드 변경 없이 config만 수정한다. **봇을 충분히 관찰한 뒤 (최소 1일)** 활성화한다.

- [ ] **Step 1: ATR 사이징 활성화**

```yaml
# configs/config.yaml
sizing:
  ...
  atr_sizing_enabled: true   # false → true
  atr_target_pct: 0.01
```

- [ ] **Step 2: 봇 재시작**

```bash
sudo systemctl restart bithumb-bot
sudo journalctl -u bithumb-bot -f -n 50
```
Expected: 로그에 `atr_mult` 값이 포함된 사이징 detail 출력

- [ ] **Step 3: 커밋**

```bash
git add configs/config.yaml
git commit -m "feat: enable ATR-based position sizing in LIVE"
```

---

## Task 4: 횡단면 모멘텀 랭커 구현

**Files:**
- Create: `strategy/momentum_ranker.py`
- Create: `tests/test_momentum_ranker.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_momentum_ranker.py
"""MomentumRanker 단위 테스트."""
from __future__ import annotations

import time
import pytest
from app.data_types import Candle
from strategy.momentum_ranker import MomentumRanker


def _make_candles(n: int, base_price: float, drift: float = 0.0) -> list[Candle]:
    """n개의 1H 캔들을 생성한다. drift > 0이면 상승 추세."""
    now_ms = int(time.time() * 1000)
    candles = []
    price = base_price
    for i in range(n):
        ts = now_ms - (n - i) * 3600 * 1000
        close = price * (1 + drift)
        candles.append(Candle(timestamp=ts, open=price, high=close * 1.001, low=price * 0.999, close=close, volume=1000.0))
        price = close
    return candles


def test_rank_returns_all_coins():
    """모든 코인이 순위에 포함된다."""
    ranker = MomentumRanker()
    candles_map = {
        "BTC": _make_candles(200, 50_000_000),
        "ETH": _make_candles(200, 3_000_000),
        "SOL": _make_candles(200, 200_000),
    }
    ranked = ranker.rank(candles_map)
    assert set(ranked) == {"BTC", "ETH", "SOL"}
    assert len(ranked) == 3


def test_rank_strong_uptrend_coin_first():
    """강한 상승 코인이 1위."""
    ranker = MomentumRanker()
    candles_map = {
        "RISING": _make_candles(200, 100_000, drift=0.003),   # 강한 상승
        "FLAT":   _make_candles(200, 100_000, drift=0.0),     # 횡보
        "FALLING": _make_candles(200, 100_000, drift=-0.003), # 하락
    }
    ranked = ranker.rank(candles_map)
    assert ranked[0] == "RISING"
    assert ranked[-1] == "FALLING"


def test_rank_insufficient_candles_last():
    """캔들 부족 코인은 꼴찌."""
    ranker = MomentumRanker()
    candles_map = {
        "GOOD": _make_candles(200, 50_000_000, drift=0.001),
        "SHORT": _make_candles(10, 50_000_000),  # 캔들 부족
    }
    ranked = ranker.rank(candles_map)
    assert ranked[-1] == "SHORT"


def test_rank_single_coin():
    """코인 1개일 때 그대로 반환."""
    ranker = MomentumRanker()
    candles_map = {"BTC": _make_candles(200, 50_000_000)}
    ranked = ranker.rank(candles_map)
    assert ranked == ["BTC"]
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
pytest tests/test_momentum_ranker.py -q
```
Expected: FAIL (모듈 없음)

- [ ] **Step 3: `strategy/momentum_ranker.py` 구현**

```python
"""MomentumRanker — 코인 간 횡단면 모멘텀 점수 계산 및 순위 결정.

점수 = 0.4 × 7일수익률_z + 0.3 × 3일수익률_z - 0.2 × 변동성비율_z + 0.1 × RSI_z
캔들 부족 코인은 최하위 배치.
"""

from __future__ import annotations

import numpy as np

from app.data_types import Candle


class MomentumRanker:
    """코인 간 횡단면 모멘텀 기반 순위 결정기."""

    # 1H 캔들 기준 기간 (1H bar 수)
    BARS_7D = 168
    BARS_3D = 72
    BARS_1D = 24
    MIN_BARS = 80  # 최소 필요 캔들 수

    def rank(self, candles_map: dict[str, list[Candle]]) -> list[str]:
        """코인을 모멘텀 점수 순서로 정렬하여 반환한다.

        Args:
            candles_map: {심볼: 1H 캔들 리스트} 딕셔너리.

        Returns:
            모멘텀 점수 내림차순 코인 목록. 캔들 부족 코인은 뒤로.
        """
        scores: dict[str, float] = {}
        insufficient: list[str] = []

        for symbol, candles in candles_map.items():
            if len(candles) < self.MIN_BARS:
                insufficient.append(symbol)
                continue
            scores[symbol] = self._compute_raw_score(candles)

        if not scores:
            return list(candles_map.keys())

        # z-score 정규화가 아닌 raw score 기반 정렬
        # (coins 수가 적으면 z-score 정규화가 불안정하므로 raw score 직접 사용)
        ranked = sorted(scores.keys(), key=lambda s: scores[s], reverse=True)
        return ranked + insufficient

    def _compute_raw_score(self, candles: list[Candle]) -> float:
        """개별 코인의 모멘텀 raw 점수를 계산한다."""
        closes = np.array([c.close for c in candles], dtype=np.float64)
        n = len(closes)

        # 7일 수익률
        idx_7d = max(0, n - self.BARS_7D - 1)
        ret_7d = (closes[-1] - closes[idx_7d]) / closes[idx_7d] if closes[idx_7d] > 0 else 0.0

        # 3일 수익률
        idx_3d = max(0, n - self.BARS_3D - 1)
        ret_3d = (closes[-1] - closes[idx_3d]) / closes[idx_3d] if closes[idx_3d] > 0 else 0.0

        # 변동성 비율 (최근 24H / 이전 7일): 낮을수록 유리 (안정적 상승 선호)
        recent = closes[-self.BARS_1D:] if n >= self.BARS_1D else closes
        historical = closes[-self.BARS_7D:-self.BARS_1D] if n >= self.BARS_7D else closes[:-self.BARS_1D]
        vol_recent = float(np.std(recent)) if len(recent) > 1 else 0.0
        vol_hist = float(np.std(historical)) if len(historical) > 1 else 1.0
        vol_ratio = vol_recent / vol_hist if vol_hist > 0 else 1.0

        # RSI 근사: 마지막 14봉의 평균 상승/하락
        rsi_score = self._approx_rsi(closes[-14:]) if n >= 14 else 50.0

        # 종합 점수 (높을수록 좋음, vol_ratio는 낮을수록 좋으므로 부호 반전)
        score = 0.4 * ret_7d + 0.3 * ret_3d - 0.2 * (vol_ratio - 1.0) + 0.1 * (rsi_score - 50) / 50
        return float(score)

    def _approx_rsi(self, closes: np.ndarray) -> float:
        """RSI 근사값을 계산한다 (0~100)."""
        if len(closes) < 2:
            return 50.0
        diffs = np.diff(closes)
        gains = diffs[diffs > 0].mean() if (diffs > 0).any() else 0.0
        losses = -diffs[diffs < 0].mean() if (diffs < 0).any() else 0.0
        if losses == 0:
            return 100.0
        rs = gains / losses
        return float(100 - 100 / (1 + rs))
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
pytest tests/test_momentum_ranker.py -q
```
Expected: 4 passed

- [ ] **Step 5: `configs/config.yaml`에 모멘텀 랭킹 플래그 추가**

파일 끝(health_monitor 섹션 뒤)에 추가:
```yaml
momentum_ranking:
  enabled: false
  top_n: 10
```

- [ ] **Step 6: `app/config.py`에 `MomentumRankingConfig` 추가**

`AppConfig` 바로 위에 신규 dataclass:
```python
@dataclass(frozen=True)
class MomentumRankingConfig:
    """모멘텀 랭킹 설정."""

    enabled: bool = False
    top_n: int = 10
```

`AppConfig`에 필드 추가:
```python
    momentum_ranking: MomentumRankingConfig = field(default_factory=MomentumRankingConfig)
```

`load_config` 함수에서 momentum_ranking 파싱 추가 (기존 `_load_config` 함수 내부에서 다른 섹션과 동일한 패턴으로):
```python
    raw_mr = raw.get("momentum_ranking", {})
    momentum_ranking = MomentumRankingConfig(**{k: v for k, v in raw_mr.items() if v is not None}) if raw_mr else MomentumRankingConfig()
```

`AppConfig(...)` 생성자 호출에 `momentum_ranking=momentum_ranking` 추가.

- [ ] **Step 7: `app/main.py`에 `MomentumRanker` 통합**

1. import 추가:
```python
from strategy.momentum_ranker import MomentumRanker
```

2. `__init__` 에서 인스턴스 생성 (다른 컴포넌트 초기화 블록 근처):
```python
        self._momentum_ranker = MomentumRanker()
```

3. `_evaluate_signals` 메서드 내부에서 코인 목록을 신호 생성 전에 정렬:
```python
        # 모멘텀 랭킹 적용 (enabled 시 상위 top_n 코인 우선 처리)
        mr_cfg = self._config.momentum_ranking
        coins_to_process = self._coins
        if mr_cfg.enabled and data.snapshots:
            candles_map = {
                sym: data.snapshots[sym].candles_1h
                for sym in self._coins
                if data.snapshots.get(sym) and data.snapshots[sym].candles_1h
            }
            if candles_map:
                ranked = self._momentum_ranker.rank(candles_map)
                coins_to_process = ranked[: mr_cfg.top_n]
```

4. 기존 신호 생성 루프에서 `self._coins` 대신 `coins_to_process` 사용:
```python
        for symbol in coins_to_process:
            snap = data.snapshots.get(symbol)
            ...
```
(기존 루프가 `data.snapshots.items()` 또는 `self._coins`를 사용하는 부분을 찾아 교체)

- [ ] **Step 8: 전체 테스트 통과 확인**

```bash
pytest tests/ -q --ignore=tests/test_bithumb_api.py
```
Expected: all pass

- [ ] **Step 9: 커밋**

```bash
git add strategy/momentum_ranker.py tests/test_momentum_ranker.py app/config.py app/main.py configs/config.yaml
git commit -m "feat: add cross-sectional momentum ranker (feature flag momentum_ranking.enabled)"
```

---

## Task 5: 동적 코인 유니버스 — API 추가

**Files:**
- Modify: `market/bithumb_api.py`

- [ ] **Step 1: `BithumbClient`에 `get_all_tickers()` 메서드 추가**

빗썸 Public API `GET /public/ticker/ALL_KRW` 를 호출해 전체 KRW 마켓 현재가 및 거래량을 반환한다.
기존 `get_ticker(coin)` 메서드 바로 뒤에 추가:

```python
    async def get_all_tickers(self) -> dict[str, dict]:
        """전체 KRW 마켓 현재가 및 거래량을 조회한다.

        Returns:
            {심볼: {acc_trade_value_24H: 거래대금, closing_price: 현재가, ...}} 딕셔너리.
            오류 시 빈 딕셔너리 반환.
        """
        url = f"{self._base_url}/public/ticker/ALL_KRW"
        try:
            data = await self._public_get(url)
            # 응답: {"status": "0000", "data": {"BTC": {...}, "ETH": {...}, "date": "..."}}
            raw = data.get("data", {})
            return {k: v for k, v in raw.items() if k != "date" and isinstance(v, dict)}
        except Exception:
            logger.exception("get_all_tickers 실패")
            return {}
```

(참고: `_public_get`이 없으면 `get_ticker`에서 사용하는 내부 HTTP GET 헬퍼와 동일한 방식으로 호출)

- [ ] **Step 2: 기존 테스트가 깨지지 않는지 확인**

```bash
pytest tests/test_config.py tests/test_coin_profiler.py -q
```
Expected: all pass

- [ ] **Step 3: 커밋**

```bash
git add market/bithumb_api.py
git commit -m "feat: add get_all_tickers() to BithumbClient for dynamic coin universe"
```

---

## Task 6: 동적 코인 유니버스 — CoinUniverse 구현

**Files:**
- Create: `strategy/coin_universe.py`
- Create: `tests/test_coin_universe.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_coin_universe.py
"""CoinUniverse 단위 테스트."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
import pytest

from strategy.coin_universe import CoinUniverse


def _make_ticker_data(coins: list[tuple[str, float]]) -> dict:
    """(심볼, 거래대금) 목록으로 티커 데이터 생성."""
    return {sym: {"acc_trade_value_24H": str(vol)} for sym, vol in coins}


@pytest.mark.asyncio
async def test_refresh_returns_top_n_by_volume():
    """거래대금 기준 상위 N개 코인을 반환한다."""
    client = MagicMock()
    client.get_all_tickers = AsyncMock(return_value=_make_ticker_data([
        ("BTC", 1_000_000_000),
        ("ETH", 800_000_000),
        ("XRP", 500_000_000),
        ("SOL", 300_000_000),
        ("DOGE", 100_000_000),
    ]))
    universe = CoinUniverse(client, top_n=3, base_coins=[])
    result = await universe.refresh()
    assert result[:3] == ["BTC", "ETH", "XRP"]
    assert len(result) == 3


@pytest.mark.asyncio
async def test_refresh_includes_base_coins():
    """base_coins는 거래량과 무관하게 포함된다."""
    client = MagicMock()
    client.get_all_tickers = AsyncMock(return_value=_make_ticker_data([
        ("BTC", 1_000_000_000),
        ("ETH", 800_000_000),
        ("XRP", 500_000_000),
    ]))
    universe = CoinUniverse(client, top_n=2, base_coins=["RENDER", "SOL"])
    result = await universe.refresh()
    assert "RENDER" in result
    assert "SOL" in result
    assert "BTC" in result  # top_n 포함


@pytest.mark.asyncio
async def test_refresh_api_failure_returns_base_coins():
    """API 실패 시 base_coins 반환."""
    client = MagicMock()
    client.get_all_tickers = AsyncMock(return_value={})
    universe = CoinUniverse(client, top_n=5, base_coins=["BTC", "ETH"])
    result = await universe.refresh()
    assert set(result) == {"BTC", "ETH"}


@pytest.mark.asyncio
async def test_refresh_excludes_stable_coins():
    """스테이블코인(USDT, USDC 등) 제외."""
    client = MagicMock()
    client.get_all_tickers = AsyncMock(return_value=_make_ticker_data([
        ("BTC", 1_000_000_000),
        ("USDT", 999_000_000),
        ("USDC", 888_000_000),
        ("ETH", 800_000_000),
    ]))
    universe = CoinUniverse(client, top_n=3, base_coins=[])
    result = await universe.refresh()
    assert "USDT" not in result
    assert "USDC" not in result
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
pytest tests/test_coin_universe.py -q
```
Expected: FAIL (모듈 없음)

- [ ] **Step 3: `strategy/coin_universe.py` 구현**

```python
"""CoinUniverse — 빗썸 거래량 기준 동적 코인 유니버스 관리.

daily refresh로 상위 top_n 코인을 선정하고 base_coins(안전망)와 합집합으로 최종 목록을 결정한다.
스테이블코인 및 원화(KRW) 자동 제외.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from market.bithumb_api import BithumbClient

logger = logging.getLogger(__name__)

# 제외할 심볼 (스테이블코인 + 원화)
_EXCLUDE: frozenset[str] = frozenset({
    "USDT", "USDC", "BUSD", "DAI", "TUSD", "USDP", "GUSD",
    "KRW", "KRWC",
})


class CoinUniverse:
    """빗썸 거래량 기준 동적 코인 유니버스 관리자."""

    def __init__(
        self,
        client: "BithumbClient",
        top_n: int = 20,
        base_coins: list[str] | None = None,
    ) -> None:
        """초기화.

        Args:
            client: 빗썸 API 클라이언트.
            top_n: 거래량 기준 상위 선정 수.
            base_coins: 항상 포함할 안전망 코인 목록.
        """
        self._client = client
        self._top_n = top_n
        self._base_coins: list[str] = list(base_coins or [])
        self._current: list[str] = list(base_coins or [])

    @property
    def coins(self) -> list[str]:
        """현재 코인 목록을 반환한다."""
        return list(self._current)

    async def refresh(self) -> list[str]:
        """빗썸 API에서 전체 티커를 조회해 코인 목록을 갱신한다.

        Returns:
            갱신된 코인 목록.
        """
        all_tickers = await self._client.get_all_tickers()
        if not all_tickers:
            logger.warning("get_all_tickers 빈 응답 — base_coins 유지")
            return list(self._base_coins)

        # 거래대금 파싱 및 필터링
        volumes: list[tuple[str, float]] = []
        for sym, info in all_tickers.items():
            if sym in _EXCLUDE:
                continue
            try:
                vol = float(info.get("acc_trade_value_24H", 0))
            except (TypeError, ValueError):
                vol = 0.0
            volumes.append((sym, vol))

        # 거래대금 내림차순 정렬
        volumes.sort(key=lambda x: x[1], reverse=True)
        top_coins = [sym for sym, _ in volumes[: self._top_n]]

        # base_coins 합집합 (순서 유지: top_coins 먼저, 나머지 base_coins 뒤)
        seen: set[str] = set(top_coins)
        extra = [c for c in self._base_coins if c not in seen]
        result = top_coins + extra

        self._current = result
        logger.info("코인 유니버스 갱신: %d개 (top%d + base%d)", len(result), len(top_coins), len(extra))
        return result
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
pytest tests/test_coin_universe.py -q
```
Expected: 4 passed

- [ ] **Step 5: 커밋**

```bash
git add strategy/coin_universe.py tests/test_coin_universe.py
git commit -m "feat: add CoinUniverse for dynamic top-N coin selection by volume"
```

---

## Task 7: 동적 코인 유니버스 — config 및 main.py 통합

**Files:**
- Modify: `app/config.py`
- Modify: `configs/config.yaml`
- Modify: `app/main.py`

- [ ] **Step 1: `CoinUniverseConfig` dataclass를 `app/config.py`에 추가**

`MomentumRankingConfig` 바로 뒤에:

```python
@dataclass(frozen=True)
class CoinUniverseConfig:
    """동적 코인 유니버스 설정."""

    enabled: bool = False
    top_n: int = 20
    refresh_hour: int = 0  # KST 기준 갱신 시각 (0시)
```

`AppConfig`에 필드 추가:
```python
    coin_universe: CoinUniverseConfig = field(default_factory=CoinUniverseConfig)
```

`load_config`에서 파싱:
```python
    raw_cu = raw.get("coin_universe", {})
    coin_universe = CoinUniverseConfig(**{k: v for k, v in raw_cu.items() if v is not None}) if raw_cu else CoinUniverseConfig()
```

- [ ] **Step 2: `configs/config.yaml` 에 `coin_universe:` 섹션 추가**

파일 끝에 추가:
```yaml
coin_universe:
  enabled: false
  top_n: 20
  refresh_hour: 0
```

- [ ] **Step 3: `app/main.py`에 `CoinUniverse` 통합**

1. import:
```python
from strategy.coin_universe import CoinUniverse
```

2. `__init__`에서 초기화:
```python
        self._coin_universe = CoinUniverse(
            client=self._client,
            top_n=config.coin_universe.top_n,
            base_coins=list(config.coins),
        )
        self._last_universe_refresh_hour: int = -1
```

3. `_run_cycle` 메서드(또는 메인 루프) 시작 부분에 daily refresh 로직 추가:

```python
        # 동적 코인 유니버스 갱신 (enabled + 갱신 시각 도달 시)
        if self._config.coin_universe.enabled:
            import datetime
            now_kst = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
            if now_kst.hour == self._config.coin_universe.refresh_hour and \
               self._last_universe_refresh_hour != now_kst.hour:
                new_coins = await self._coin_universe.refresh()
                if new_coins:
                    self._coins = new_coins
                    self._datafeed._coins = new_coins
                    self._last_universe_refresh_hour = now_kst.hour
                    logger.info("코인 유니버스 갱신 완료: %s", new_coins)
```

4. `start()` 메서드에서 봇 시작 시 초기 refresh 호출:
```python
        if self._config.coin_universe.enabled:
            initial_coins = await self._coin_universe.refresh()
            if initial_coins:
                self._coins = initial_coins
                self._datafeed._coins = initial_coins
```

- [ ] **Step 4: `DataFeed._coins` 업데이트 가능 여부 확인**

`market/datafeed.py` 에서 `self._coins` 가 인스턴스 변수인지 확인. 만약 `__init__` 에서만 할당된다면, setter 없이 직접 대입 가능 (Python attribute). 확인 후 필요하면 `DataFeed`에 `update_coins(coins: list[str])` 메서드 추가:

```python
    def update_coins(self, coins: list[str]) -> None:
        """거래 대상 코인 목록을 갱신한다."""
        self._coins = list(coins)
```

그리고 `main.py`에서 `self._datafeed._coins = ...` 대신 `self._datafeed.update_coins(new_coins)` 사용.

- [ ] **Step 5: 전체 테스트 통과 확인**

```bash
pytest tests/ -q --ignore=tests/test_bithumb_api.py
```
Expected: all pass

- [ ] **Step 6: 커밋**

```bash
git add app/config.py configs/config.yaml app/main.py market/datafeed.py
git commit -m "feat: integrate CoinUniverse into main orchestrator (feature flag coin_universe.enabled)"
```

---

## Task 8: 배포 및 검증

**Files:**
- Modify: `configs/config.yaml` (feature flag 순차 활성화)

이 Task는 봇이 LIVE로 운영 중인 상태에서 단계적으로 flag를 켠다.

- [ ] **Step 1: Phase 1 (ATR 사이징) 활성화 후 1일 관찰**

```yaml
sizing:
  atr_sizing_enabled: true
```
```bash
sudo systemctl restart bithumb-bot
sudo journalctl -u bithumb-bot -f -n 50
```
1일간 거래 detail에 `atr_mult` 정상 출력 확인. 사이징 이상 없으면 다음 Phase 진행.

- [ ] **Step 2: Phase 2 (모멘텀 랭킹) 활성화 후 3일 관찰**

```yaml
momentum_ranking:
  enabled: true
  top_n: 10
```
```bash
sudo systemctl restart bithumb-bot
```
상위 10개 코인에만 신호 생성되는지 로그 확인. 기존 10개 고정 대비 코인 구성 변화 없으면 정상.

- [ ] **Step 3: Phase 3 (동적 유니버스) 활성화 후 7일 관찰**

```yaml
coin_universe:
  enabled: true
  top_n: 20
  refresh_hour: 0
```
```bash
sudo systemctl restart bithumb-bot
```
매일 0시 KST에 코인 목록 갱신 로그 확인. 거래대금 상위 20개 코인으로 유니버스 확장 확인.

- [ ] **Step 4: 최종 커밋**

```bash
git add configs/config.yaml
git commit -m "feat: enable trading strategy enhancements in LIVE (ATR + momentum + dynamic universe)"
```

---

## Self-Review

### Spec Coverage

| 요구사항 | Task |
|---------|------|
| ATR 기반 포지션 사이징 | Task 1, 2, 3 |
| 횡단면 모멘텀 랭킹 | Task 4 |
| 동적 코인 유니버스 | Task 5, 6, 7 |
| feature flag 안전 배포 | Task 3, 8 |
| 기존 봇 운영 유지 | 모든 Task (봇 재시작만, 중단 없음) |

### Type Consistency

- `PositionManager.calculate_size()`: `ind_1h: object | None` (duck typing으로 `IndicatorPack` 의존성 없음)
- `MomentumRanker.rank()`: `dict[str, list[Candle]]` 입력, `list[str]` 출력
- `CoinUniverse.refresh()`: `async → list[str]`
- `CoinUniverseConfig.refresh_hour`: `int` (0~23)

### 주의사항

- **Task 7 Step 3**: `self._datafeed._coins`는 내부 변수 직접 접근이므로 `update_coins()` 메서드 추가를 권장. 실제 구현 시 `datafeed.py` 코드 확인 필수.
- **ATR 사이징**: `vol_target_mult_min`/`vol_target_mult_max` 값을 재사용. `config.yaml`에서 `vol_target_mult_min: 0.8` 이므로 ATR 배수 하한이 0.8. 필요 시 별도 `atr_mult_min`/`atr_mult_max` 추가 고려.
- **동적 유니버스 + 모멘텀 랭킹 동시 활성화 시**: 코인 목록 갱신 후 랭킹 적용이 동일 사이클 내에서 이뤄지는지 순서 확인 필요.
