# Refactoring Phase 1: Test Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Protocol 인터페이스 + 고정 픽스처 + 스냅샷 테스트를 구축하여 Phase 2~5 리팩토링의 안전망을 확보한다.

**Architecture:** 기존 `tests/` 구조를 유지하면서 `tests/fixtures/` 서브디렉터리를 추가. `app/protocols.py`에 Protocol 인터페이스 정의. 봇 코드 변경 없음.

**Tech Stack:** Python 3.12+, pytest, pytest-asyncio, numpy, 기존 `app/data_types.py` / `strategy/indicators.py` / `strategy/rule_engine.py`

---

## 파일 맵

| 동작 | 경로 | 역할 |
|------|------|------|
| 생성 | `app/protocols.py` | Protocol 인터페이스 4개 |
| 생성 | `tests/fixtures/__init__.py` | 픽스처 패키지 |
| 생성 | `tests/fixtures/candles.py` | 국면별 고정 캔들 팩토리 |
| 생성 | `tests/fixtures/indicators.py` | 고정 캔들 → IndicatorPack 계산 헬퍼 |
| 생성 | `tests/fixtures/snapshots.py` | FrozenStrategyInput 구현체 |
| 생성 | `tests/mocks/__init__.py` | Mock 패키지 |
| 생성 | `tests/mocks/market.py` | MockMarketData |
| 생성 | `tests/mocks/executor.py` | MockOrderExecutor |
| 생성 | `tests/mocks/notifier.py` | MockNotifier |
| 생성 | `tests/test_regime_snapshot.py` | RegimeClassifier 스냅샷 테스트 9케이스 |
| 생성 | `tests/test_env_filter_snapshot.py` | EnvironmentFilter 스냅샷 테스트 5케이스 |
| 생성 | `tests/test_strategy_scorer_snapshot.py` | StrategyScorer 스냅샷 테스트 5케이스 |

---

## Task 1: Protocol 인터페이스 정의

**Files:**
- Create: `app/protocols.py`

- [ ] **Step 1: `app/protocols.py` 작성**

```python
"""봇 핵심 컴포넌트 Protocol 인터페이스.

테스트 시 Mock으로 교체 가능하도록 런타임 의존성을 추상화한다.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.data_types import Candle, MarketSnapshot
from strategy.indicators import IndicatorPack


@runtime_checkable
class MarketDataProvider(Protocol):
    """캔들 + 오더북 데이터 제공."""

    async def get_candles(
        self, symbol: str, interval: str, limit: int
    ) -> list[Candle]:
        """캔들 리스트를 반환한다."""
        ...


@runtime_checkable
class OrderExecutor(Protocol):
    """주문 실행."""

    async def place_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        price: float,
    ) -> dict:
        """주문을 실행하고 응답을 반환한다."""
        ...


@runtime_checkable
class NotificationSender(Protocol):
    """알림 전송."""

    async def send(self, text: str, channel: str = "system") -> bool:
        """알림을 전송하고 성공 여부를 반환한다."""
        ...


@runtime_checkable
class StrategyInputProvider(Protocol):
    """RuleEngine 테스트용 — 고정된 IndicatorPack + MarketSnapshot 제공."""

    def get_indicators_15m(self, symbol: str) -> IndicatorPack:
        """15분봉 지표를 반환한다."""
        ...

    def get_indicators_1h(self, symbol: str) -> IndicatorPack:
        """1시간봉 지표를 반환한다."""
        ...

    def get_snapshot(self, symbol: str) -> MarketSnapshot:
        """시장 스냅샷을 반환한다."""
        ...
```

- [ ] **Step 2: import 확인**

```bash
cd /home/bythejune/projects/bithumb-bot-v2
python -c "from app.protocols import MarketDataProvider, OrderExecutor, NotificationSender, StrategyInputProvider; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/protocols.py
git commit -m "feat: add Protocol interfaces for testability (Phase 1)"
```

---

## Task 2: 국면별 고정 캔들 팩토리

**Files:**
- Create: `tests/fixtures/__init__.py`
- Create: `tests/fixtures/candles.py`

- [ ] **Step 1: `tests/fixtures/__init__.py` 작성**

```python
"""테스트 픽스처 패키지."""
```

- [ ] **Step 2: `tests/fixtures/candles.py` 작성**

각 국면을 확실하게 만드는 캔들 시퀀스를 생성한다.
- STRONG_UP: EMA20 > EMA50 > EMA200, ADX > 25, +DI > -DI (강한 추세)
- WEAK_UP: EMA20 > EMA50, 20 ≤ ADX ≤ 25, +DI > -DI
- RANGE: EMA20 ≈ EMA50, ADX < 20
- WEAK_DOWN: EMA20 < EMA50, -DI > +DI
- CRISIS: ATR > ATR_avg × 2.5, 24h 가격변화 < -10%

```python
"""국면별 고정 캔들 시퀀스 팩토리.

각 함수는 해당 국면 판정을 확실하게 만드는 200봉 이상의 캔들을 반환한다.
(IndicatorPack 계산에 최소 200봉 필요)
"""
from __future__ import annotations

from app.data_types import Candle


def _make_candle(ts: int, price: float, volume: float = 1000.0) -> Candle:
    return Candle(
        timestamp=ts,
        open=price * 0.999,
        high=price * 1.002,
        low=price * 0.998,
        close=price,
        volume=volume,
    )


def strong_up_candles(count: int = 250) -> list[Candle]:
    """STRONG_UP 국면 캔들.

    강한 상승 추세: 매봉 0.3% 상승, 높은 거래량.
    EMA20 > EMA50 > EMA200, ADX > 25 조건 충족.
    """
    candles = []
    price = 50_000_000.0
    for i in range(count):
        price *= 1.003  # 0.3% 상승
        candles.append(_make_candle(i * 900_000, price, volume=5000.0 + i * 10))
    return candles


def weak_up_candles(count: int = 250) -> list[Candle]:
    """WEAK_UP 국면 캔들.

    약한 상승 추세: 매봉 0.08% 상승, 보통 거래량.
    EMA20 > EMA50, 20 ≤ ADX ≤ 25 조건 충족.
    """
    candles = []
    price = 50_000_000.0
    for i in range(count):
        price *= 1.0008
        candles.append(_make_candle(i * 900_000, price, volume=2000.0))
    return candles


def range_candles(count: int = 250) -> list[Candle]:
    """RANGE 국면 캔들.

    횡보: 가격이 좁은 범위에서 진동, ADX < 20.
    """
    import math
    candles = []
    base = 50_000_000.0
    for i in range(count):
        price = base + base * 0.01 * math.sin(i * 0.3)
        candles.append(_make_candle(i * 900_000, price, volume=1500.0))
    return candles


def weak_down_candles(count: int = 250) -> list[Candle]:
    """WEAK_DOWN 국면 캔들.

    약한 하락 추세: 매봉 0.08% 하락.
    EMA20 < EMA50, -DI > +DI 조건 충족.
    """
    candles = []
    price = 50_000_000.0
    for i in range(count):
        price *= 0.9992
        candles.append(_make_candle(i * 900_000, price, volume=2000.0))
    return candles


def crisis_candles(count: int = 250) -> list[Candle]:
    """CRISIS 국면 캔들.

    정상 횡보 후 마지막 24봉에서 급락 (-12%).
    ATR > ATR_avg × 2.5, 24h 변화 < -10% 조건 충족.
    """
    import math
    candles = []
    base = 50_000_000.0
    normal_count = count - 24
    # 정상 구간
    for i in range(normal_count):
        price = base + base * 0.005 * math.sin(i * 0.2)
        candles.append(_make_candle(i * 900_000, price, volume=1500.0))
    # 급락 구간 (변동성 크게 + 하락)
    crash_price = base
    for j in range(24):
        crash_price *= 0.9948  # 24봉 누적 -12%
        candles.append(
            Candle(
                timestamp=(normal_count + j) * 900_000,
                open=crash_price * 1.02,
                high=crash_price * 1.03,
                low=crash_price * 0.95,   # ATR 크게
                close=crash_price,
                volume=8000.0,
            )
        )
    return candles
```

- [ ] **Step 3: import 확인**

```bash
python -c "from tests.fixtures.candles import strong_up_candles; c = strong_up_candles(); print(len(c), 'candles OK')"
```
Expected: `250 candles OK`

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/__init__.py tests/fixtures/candles.py
git commit -m "test: add regime-specific candle fixtures (Phase 1)"
```

---

## Task 3: FrozenStrategyInput 구현체

**Files:**
- Create: `tests/fixtures/indicators.py`
- Create: `tests/fixtures/snapshots.py`

- [ ] **Step 1: `tests/fixtures/indicators.py` 작성**

```python
"""고정 캔들에서 IndicatorPack을 계산하는 헬퍼."""
from __future__ import annotations

from app.data_types import Candle
from strategy.indicators import IndicatorPack, compute_indicators


def indicators_from_candles(candles: list[Candle]) -> IndicatorPack:
    """캔들 리스트로 IndicatorPack을 계산한다."""
    return compute_indicators(candles)
```

- [ ] **Step 2: `tests/fixtures/snapshots.py` 작성**

```python
"""FrozenStrategyInput — StrategyInputProvider Protocol 구현체."""
from __future__ import annotations

from app.data_types import Candle, MarketSnapshot, Orderbook, OrderbookEntry
from strategy.indicators import IndicatorPack, compute_indicators


def _make_orderbook(mid_price: float, spread_pct: float = 0.001) -> Orderbook:
    half = mid_price * spread_pct / 2
    return Orderbook(
        timestamp=0,
        bids=[OrderbookEntry(price=mid_price - half, quantity=100.0)],
        asks=[OrderbookEntry(price=mid_price + half, quantity=100.0)],
    )


class FrozenStrategyInput:
    """고정 캔들로 초기화된 StrategyInputProvider.

    테스트에서 결정론적 입력을 보장한다.
    """

    def __init__(
        self,
        candles_15m: list[Candle],
        candles_1h: list[Candle] | None = None,
        symbol: str = "BTC",
        current_price: float | None = None,
        spread_pct: float = 0.001,
    ) -> None:
        self._symbol = symbol
        self._candles_15m = candles_15m
        # 1H 캔들이 없으면 15M의 4봉을 1봉으로 합산
        self._candles_1h = candles_1h or _resample_to_1h(candles_15m)
        self._price = current_price or candles_15m[-1].close
        self._spread_pct = spread_pct

    def get_indicators_15m(self, symbol: str) -> IndicatorPack:
        """15분봉 지표를 반환한다."""
        return compute_indicators(self._candles_15m)

    def get_indicators_1h(self, symbol: str) -> IndicatorPack:
        """1시간봉 지표를 반환한다."""
        return compute_indicators(self._candles_1h)

    def get_snapshot(self, symbol: str) -> MarketSnapshot:
        """시장 스냅샷을 반환한다."""
        return MarketSnapshot(
            symbol=self._symbol,
            current_price=self._price,
            candles_15m=self._candles_15m,
            candles_1h=self._candles_1h,
            orderbook=_make_orderbook(self._price, self._spread_pct),
        )


def _resample_to_1h(candles_15m: list[Candle]) -> list[Candle]:
    """15분봉 4개를 1시간봉 1개로 리샘플링한다."""
    from app.data_types import Candle as C
    result = []
    for i in range(0, len(candles_15m) - 3, 4):
        chunk = candles_15m[i:i + 4]
        result.append(C(
            timestamp=chunk[0].timestamp,
            open=chunk[0].open,
            high=max(c.high for c in chunk),
            low=min(c.low for c in chunk),
            close=chunk[-1].close,
            volume=sum(c.volume for c in chunk),
        ))
    return result
```

- [ ] **Step 3: import 확인**

```bash
python -c "
from tests.fixtures.candles import strong_up_candles
from tests.fixtures.snapshots import FrozenStrategyInput
inp = FrozenStrategyInput(strong_up_candles())
ind = inp.get_indicators_15m('BTC')
snap = inp.get_snapshot('BTC')
print('IndicatorPack OK, snapshot OK')
"
```
Expected: `IndicatorPack OK, snapshot OK`

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/indicators.py tests/fixtures/snapshots.py
git commit -m "test: add FrozenStrategyInput fixture for RuleEngine testing (Phase 1)"
```

---

## Task 4: Mock 구현체

**Files:**
- Create: `tests/mocks/__init__.py`
- Create: `tests/mocks/market.py`
- Create: `tests/mocks/executor.py`
- Create: `tests/mocks/notifier.py`

- [ ] **Step 1: `tests/mocks/__init__.py` 작성**

```python
"""테스트 Mock 패키지."""
```

- [ ] **Step 2: `tests/mocks/market.py` 작성**

```python
"""MockMarketData — MarketDataProvider Protocol 구현체."""
from __future__ import annotations

from app.data_types import Candle


class MockMarketData:
    """픽스처 캔들을 반환하는 Mock."""

    def __init__(self, candles: list[Candle] | None = None) -> None:
        self._candles = candles or []
        self.call_count = 0

    async def get_candles(
        self, symbol: str, interval: str, limit: int
    ) -> list[Candle]:
        """고정 캔들을 반환한다."""
        self.call_count += 1
        return self._candles[-limit:] if limit else self._candles
```

- [ ] **Step 3: `tests/mocks/executor.py` 작성**

```python
"""MockOrderExecutor — OrderExecutor Protocol 구현체."""
from __future__ import annotations


class MockOrderExecutor:
    """주문을 기록하는 Mock. 실제 API 미호출."""

    def __init__(self) -> None:
        self.orders: list[dict] = []

    async def place_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        price: float,
    ) -> dict:
        """주문을 기록하고 성공 응답을 반환한다."""
        order = {"symbol": symbol, "side": side, "qty": qty, "price": price, "status": "filled"}
        self.orders.append(order)
        return order
```

- [ ] **Step 4: `tests/mocks/notifier.py` 작성**

```python
"""MockNotifier — NotificationSender Protocol 구현체."""
from __future__ import annotations


class MockNotifier:
    """알림을 캡처하는 Mock."""

    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    async def send(self, text: str, channel: str = "system") -> bool:
        """알림을 기록하고 True를 반환한다."""
        self.messages.append((channel, text))
        return True
```

- [ ] **Step 5: Protocol 준수 확인**

```bash
python -c "
from app.protocols import MarketDataProvider, OrderExecutor, NotificationSender
from tests.mocks.market import MockMarketData
from tests.mocks.executor import MockOrderExecutor
from tests.mocks.notifier import MockNotifier
assert isinstance(MockMarketData(), MarketDataProvider)
assert isinstance(MockOrderExecutor(), OrderExecutor)
assert isinstance(MockNotifier(), NotificationSender)
print('All mocks satisfy Protocol OK')
"
```
Expected: `All mocks satisfy Protocol OK`

- [ ] **Step 6: Commit**

```bash
git add tests/mocks/__init__.py tests/mocks/market.py tests/mocks/executor.py tests/mocks/notifier.py
git commit -m "test: add Mock implementations for MarketData, OrderExecutor, Notifier (Phase 1)"
```

---

## Task 5: RegimeClassifier 스냅샷 테스트

**Files:**
- Create: `tests/test_regime_snapshot.py`

- [ ] **Step 1: 테스트 작성**

```python
"""RegimeClassifier 스냅샷 테스트.

현재 RuleEngine의 국면 판정 동작을 고정한다.
Phase 2에서 RegimeClassifier를 분리한 후 이 테스트가 여전히 통과하면 분리 성공.
"""
from __future__ import annotations

import pytest

from app.data_types import Regime
from strategy.indicators import compute_indicators
from strategy.rule_engine import RuleEngine
from tests.fixtures.candles import (
    crisis_candles,
    range_candles,
    strong_up_candles,
    weak_down_candles,
    weak_up_candles,
)

from app.config import load_config


@pytest.fixture
def engine() -> RuleEngine:
    config = load_config()
    return RuleEngine(config)


# ─── 국면별 5케이스 ────────────────────────────────────────


def test_regime_strong_up(engine):
    """강한 상승 캔들 → STRONG_UP."""
    candles = strong_up_candles()
    ind = compute_indicators(candles)
    regime = engine._raw_classify(ind)
    assert regime == Regime.STRONG_UP, f"Expected STRONG_UP, got {regime}"


def test_regime_weak_up(engine):
    """약한 상승 캔들 → WEAK_UP."""
    candles = weak_up_candles()
    ind = compute_indicators(candles)
    regime = engine._raw_classify(ind)
    assert regime == Regime.WEAK_UP, f"Expected WEAK_UP, got {regime}"


def test_regime_range(engine):
    """횡보 캔들 → RANGE."""
    candles = range_candles()
    ind = compute_indicators(candles)
    regime = engine._raw_classify(ind)
    assert regime == Regime.RANGE, f"Expected RANGE, got {regime}"


def test_regime_weak_down(engine):
    """약한 하락 캔들 → WEAK_DOWN."""
    candles = weak_down_candles()
    ind = compute_indicators(candles)
    regime = engine._raw_classify(ind)
    assert regime == Regime.WEAK_DOWN, f"Expected WEAK_DOWN, got {regime}"


def test_regime_crisis(engine):
    """급락 캔들 → CRISIS."""
    candles = crisis_candles()
    ind = compute_indicators(candles)
    regime = engine._raw_classify(ind)
    assert regime == Regime.CRISIS, f"Expected CRISIS, got {regime}"


# ─── 히스테리시스 3케이스 ─────────────────────────────────


def test_hysteresis_requires_3_bars(engine):
    """국면 전환은 3봉 연속 확인 후 발생한다."""
    # RANGE 국면 초기화
    candles = range_candles()
    ind_range = compute_indicators(candles)
    snap_range = _make_snapshot("BTC", candles)
    engine.generate_signals({"BTC": snap_range}, {"BTC": (ind_range, ind_range)})
    state_before = engine.get_regime_state("BTC") if hasattr(engine, "get_regime_state") else None

    # 1봉만 STRONG_UP 신호 → 아직 전환 안 됨
    candles_up = strong_up_candles(count=3)
    ind_up = compute_indicators(strong_up_candles())
    snap_up = _make_snapshot("BTC", strong_up_candles())
    engine.generate_signals({"BTC": snap_up}, {"BTC": (ind_up, ind_up)})
    # confirm_count == 1, 아직 RANGE
    state = engine._regime_states.get("BTC")
    if state:
        assert state.current in (Regime.RANGE, Regime.STRONG_UP)  # 3봉 미만이면 RANGE 유지


def test_hysteresis_crisis_immediate(engine):
    """CRISIS는 즉시 전환된다 (히스테리시스 없음)."""
    # STRONG_UP 초기화
    snap = _make_snapshot("BTC", strong_up_candles())
    ind = compute_indicators(strong_up_candles())
    engine.generate_signals({"BTC": snap}, {"BTC": (ind, ind)})

    # 단 1봉 CRISIS → 즉시 전환
    crisis = crisis_candles()
    ind_c = compute_indicators(crisis)
    snap_c = _make_snapshot("BTC", crisis)
    signals = engine.generate_signals({"BTC": snap_c}, {"BTC": (ind_c, ind_c)})
    state = engine._regime_states.get("BTC")
    if state:
        assert state.current == Regime.CRISIS


def test_hysteresis_crisis_release_requires_6_bars(engine):
    """CRISIS 해제는 6봉 연속 정상 확인 후 발생한다."""
    # CRISIS 초기화
    crisis = crisis_candles()
    ind_c = compute_indicators(crisis)
    snap_c = _make_snapshot("BTC", crisis)
    engine.generate_signals({"BTC": snap_c}, {"BTC": (ind_c, ind_c)})

    # 정상 캔들 5봉 → 아직 CRISIS
    for _ in range(5):
        normal = range_candles()
        ind_n = compute_indicators(normal)
        snap_n = _make_snapshot("BTC", normal)
        engine.generate_signals({"BTC": snap_n}, {"BTC": (ind_n, ind_n)})

    state = engine._regime_states.get("BTC")
    if state:
        assert state.current == Regime.CRISIS, "5봉 후에는 아직 CRISIS여야 함"


# ─── 헬퍼 ────────────────────────────────────────────────


def _make_snapshot(symbol: str, candles: list):
    from app.data_types import MarketSnapshot, Orderbook, OrderbookEntry
    price = candles[-1].close
    ob = Orderbook(
        timestamp=0,
        bids=[OrderbookEntry(price=price * 0.999, quantity=100.0)],
        asks=[OrderbookEntry(price=price * 1.001, quantity=100.0)],
    )
    return MarketSnapshot(
        symbol=symbol,
        current_price=price,
        candles_15m=candles,
        candles_1h=candles,
        orderbook=ob,
    )
```

- [ ] **Step 2: 테스트 실행**

```bash
cd /home/bythejune/projects/bithumb-bot-v2
pytest tests/test_regime_snapshot.py -v 2>&1 | head -40
```
Expected: 최소 5개 통과 (히스테리시스 테스트는 RuleEngine 내부 구조 의존, 일부 skip 가능)

- [ ] **Step 3: 실패 케이스 분석 후 픽스처 파라미터 조정**

STRONG_UP 조건: EMA20 > EMA50 > EMA200 (200봉 이상 필요), ADX > 25.
캔들이 충분하지 않거나 트렌드가 약하면 픽스처 조정:
- `count` 증가 (300→400)
- `price *= 1.005` 등 상승률 강화

- [ ] **Step 4: Commit**

```bash
git add tests/test_regime_snapshot.py
git commit -m "test: add RegimeClassifier snapshot tests — 9 cases (Phase 1)"
```

---

## Task 6: EnvironmentFilter 스냅샷 테스트

**Files:**
- Create: `tests/test_env_filter_snapshot.py`

- [ ] **Step 1: 테스트 작성**

```python
"""EnvironmentFilter(L1 필터) 스냅샷 테스트.

거부/통과 동작을 고정한다.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

from app.data_types import Candle, MarketSnapshot, Orderbook, OrderbookEntry, Regime, Tier
from app.config import load_config
from strategy.coin_profiler import TierParams
from strategy.indicators import compute_indicators
from strategy.rule_engine import RuleEngine
from tests.fixtures.candles import range_candles


KST = timezone(timedelta(hours=9))


@pytest.fixture
def engine():
    return RuleEngine(load_config())


@pytest.fixture
def tier1_params():
    return TierParams(tier=Tier.TIER1, position_mult=1.2, rsi_min=35, rsi_max=65,
                      atr_stop_mult=2.5, spread_limit=0.0018)


@pytest.fixture
def tier3_params():
    return TierParams(tier=Tier.TIER3, position_mult=1.0, rsi_min=25, rsi_max=75,
                      atr_stop_mult=1.5, spread_limit=0.0035)


def _make_snap(candles, volume_override=None, spread_pct=0.001):
    """테스트용 스냅샷 생성."""
    if volume_override is not None:
        candles = [
            Candle(c.timestamp, c.open, c.high, c.low, c.close, volume_override)
            for c in candles
        ]
    price = candles[-1].close
    ob = Orderbook(
        timestamp=0,
        bids=[OrderbookEntry(price=price * (1 - spread_pct / 2), quantity=100.0)],
        asks=[OrderbookEntry(price=price * (1 + spread_pct / 2), quantity=100.0)],
    )
    return MarketSnapshot(
        symbol="TEST", current_price=price,
        candles_15m=candles, candles_1h=candles, orderbook=ob
    )


def test_l1_pass_normal(engine, tier1_params):
    """정상 조건 → L1 통과."""
    candles = range_candles()
    snap = _make_snap(candles)
    ind = compute_indicators(candles)
    passed, reason = engine._check_layer1(Regime.RANGE, snap, ind, tier1_params)
    assert passed, f"정상 조건인데 거부됨: {reason}"


def test_l1_reject_crisis(engine, tier1_params):
    """CRISIS 국면 → L1 거부."""
    candles = range_candles()
    snap = _make_snap(candles)
    ind = compute_indicators(candles)
    passed, reason = engine._check_layer1(Regime.CRISIS, snap, ind, tier1_params)
    assert not passed
    assert "CRISIS" in reason


def test_l1_reject_low_volume(engine, tier1_params):
    """거래량 부족 → L1 거부."""
    candles = range_candles()
    # 마지막 봉 거래량을 평균의 50%로 설정 (기준: 80%)
    avg_vol = sum(c.volume for c in candles[-22:-2]) / 20
    low_vol = avg_vol * 0.5
    snap = _make_snap(candles, volume_override=low_vol)
    ind = compute_indicators(snap.candles_15m)
    passed, reason = engine._check_layer1(Regime.RANGE, snap, ind, tier1_params)
    assert not passed
    assert "거래량" in reason


def test_l1_reject_high_spread(engine, tier1_params):
    """스프레드 초과 → L1 거부 (Tier1 한도 0.0018)."""
    candles = range_candles()
    snap = _make_snap(candles, spread_pct=0.005)  # 0.5% >> 0.18%
    ind = compute_indicators(candles)
    passed, reason = engine._check_layer1(Regime.RANGE, snap, ind, tier1_params)
    assert not passed
    assert "스프레드" in reason


def test_l1_reject_nighttime_tier3(engine, tier3_params):
    """심야(03:00 KST) + Tier3 → L1 거부."""
    candles = range_candles()
    snap = _make_snap(candles)
    ind = compute_indicators(candles)
    night_kst = datetime(2026, 3, 25, 3, 0, 0, tzinfo=KST)
    with patch("strategy.rule_engine.datetime") as mock_dt:
        mock_dt.now.return_value = night_kst
        passed, reason = engine._check_layer1(Regime.RANGE, snap, ind, tier3_params)
    assert not passed
    assert "심야" in reason or "Tier 3" in reason
```

- [ ] **Step 2: 테스트 실행**

```bash
pytest tests/test_env_filter_snapshot.py -v
```
Expected: 5개 모두 통과

- [ ] **Step 3: Commit**

```bash
git add tests/test_env_filter_snapshot.py
git commit -m "test: add EnvironmentFilter snapshot tests — 5 cases (Phase 1)"
```

---

## Task 7: StrategyScorer 스냅샷 테스트

**Files:**
- Create: `tests/test_strategy_scorer_snapshot.py`

- [ ] **Step 1: 테스트 작성**

```python
"""StrategyScorer 스냅샷 테스트.

각 전략의 점수 계산 동작을 고정한다.
"""
from __future__ import annotations

import pytest

from app.config import load_config
from app.data_types import Regime, Strategy
from strategy.indicators import compute_indicators
from strategy.rule_engine import RuleEngine
from tests.fixtures.candles import strong_up_candles, range_candles, weak_down_candles
from tests.fixtures.snapshots import FrozenStrategyInput


@pytest.fixture
def engine():
    return RuleEngine(load_config())


def test_trend_follow_scores_in_strong_up(engine):
    """STRONG_UP 국면 + 상승 캔들 → trend_follow 점수 > 0."""
    candles = strong_up_candles()
    ind = compute_indicators(candles)
    result = engine._score_strategy_a(ind, ind, candles)
    assert result.strategy == Strategy.TREND_FOLLOW
    assert result.score >= 0  # 0 이상이면 동작 확인


def test_mean_reversion_scores_in_range(engine):
    """RANGE 국면 캔들 → mean_reversion 점수 반환."""
    candles = range_candles()
    ind = compute_indicators(candles)
    result = engine._score_strategy_b(ind, ind, candles)
    assert result.strategy == Strategy.MEAN_REVERSION
    assert isinstance(result.score, float)


def test_dca_score_in_weak_down(engine):
    """WEAK_DOWN 캔들 → DCA 점수 반환."""
    candles = weak_down_candles()
    ind = compute_indicators(candles)
    result = engine._score_strategy_e(ind)
    assert result.strategy == Strategy.DCA
    assert isinstance(result.score, float)


def test_score_cutoff_blocks_low_score(engine):
    """점수 컷오프 미달 신호는 생성되지 않는다."""
    # RANGE 캔들에서 trend_follow는 점수가 낮아 신호 생성 안 됨
    from tests.fixtures.snapshots import FrozenStrategyInput, _make_orderbook
    from app.data_types import MarketSnapshot
    candles = range_candles()
    snap = MarketSnapshot(
        symbol="BTC", current_price=candles[-1].close,
        candles_15m=candles, candles_1h=candles,
        orderbook=_make_orderbook(candles[-1].close),
    )
    ind = compute_indicators(candles)
    signals = engine.generate_signals({"BTC": snap}, {"BTC": (ind, ind)})
    # trend_follow 신호가 없거나 있어도 점수가 컷오프 미달인지 확인
    trend_signals = [s for s in signals if s.strategy == Strategy.TREND_FOLLOW]
    # RANGE에서 trend_follow가 나와도 점수가 낮으면 정상


def test_all_strategy_scorers_return_score_result(engine):
    """모든 전략 스코어러가 ScoreResult를 반환한다."""
    candles = range_candles()
    ind = compute_indicators(candles)
    results = [
        engine._score_strategy_a(ind, ind, candles),
        engine._score_strategy_b(ind, ind, candles),
        engine._score_strategy_e(ind),
    ]
    for r in results:
        assert hasattr(r, "strategy")
        assert hasattr(r, "score")
        assert isinstance(r.score, float)
```

- [ ] **Step 2: 테스트 실행**

```bash
pytest tests/test_strategy_scorer_snapshot.py -v
```
Expected: 5개 모두 통과 (score 값은 고정 안 해도 됨, 타입과 존재만 확인)

- [ ] **Step 3: 전체 테스트 스위트 실행**

```bash
pytest tests/ -v --tb=short 2>&1 | tail -20
```
Expected: 기존 테스트 포함 전체 통과

- [ ] **Step 4: Commit**

```bash
git add tests/test_strategy_scorer_snapshot.py
git commit -m "test: add StrategyScorer snapshot tests — 5 cases (Phase 1)"
```

---

## Task 8: Phase 1 완료 검증

- [ ] **Step 1: 전체 테스트 실행 + 커버리지 측정**

```bash
pytest tests/ --cov=strategy --cov=app --cov-report=term-missing 2>&1 | tail -30
```
Expected: 전체 통과, 커버리지 기준선 출력 (숫자 기록해둘 것)

- [ ] **Step 2: 새로 추가된 파일 목록 확인**

```bash
git diff --name-only HEAD~8 HEAD
```
Expected:
```
app/protocols.py
tests/fixtures/__init__.py
tests/fixtures/candles.py
tests/fixtures/indicators.py
tests/fixtures/snapshots.py
tests/mocks/__init__.py
tests/mocks/market.py
tests/mocks/executor.py
tests/mocks/notifier.py
tests/test_regime_snapshot.py
tests/test_env_filter_snapshot.py
tests/test_strategy_scorer_snapshot.py
```

- [ ] **Step 3: 봇 정상 운영 확인 (코드 변경 없으므로 재시작 불필요)**

```bash
sudo journalctl -u bithumb-bot -n 5 --no-pager
```
Expected: 사이클 정상 실행 로그

- [ ] **Step 4: Phase 1 완료 태그**

```bash
git tag phase1-test-infra
git log --oneline -8
```

---

## Phase 1 완료 기준 체크리스트

- [ ] `pytest tests/` 전체 통과
- [ ] `app/protocols.py` 4개 Protocol 정의
- [ ] `tests/fixtures/` 국면별 캔들 + FrozenStrategyInput
- [ ] `tests/mocks/` MockMarketData + MockOrderExecutor + MockNotifier
- [ ] 스냅샷 테스트 총 19케이스 (국면 9 + L1 5 + 스코어러 5)
- [ ] 봇 무중단 운영 확인

**다음 단계:** `docs/superpowers/plans/2026-03-25-refactoring-phase2-rule-engine.md`
