# Bithumb Bot v2 — 전면 리팩토링 설계

**작성일**: 2026-03-25
**방식**: Strangler Fig (단계별 교체, 봇 운영 유지)
**배경**: 코드 품질 평가 결과 종합 점수 6.5/10. 실제 자금 운용 봇으로서 God-class, 1000줄+ 메서드, 테스트 불가 구조가 실제 위험 요소.

---

## 목표

- 각 클래스가 하나의 책임만 가짐 (SRP)
- 핵심 로직을 단위 테스트 가능하게
- 봇을 멈추지 않고 단계별 교체
- 각 단계가 독립적으로 배포·검증·롤백 가능

---

## 현재 vs 목표 구조

### 현재 문제

| 파일 | 줄수 | 문제 |
|------|------|------|
| `app/main.py` (TradingBot) | 1,359줄 | 8가지 이상 책임 |
| `strategy/rule_engine.py` (RuleEngine) | 2,000줄+ | 국면판정+점수계산+L1필터+사이즈결정 혼재 |
| `run_cycle()` 메서드 | 585줄 | 단일 메서드, 테스트 불가 |
| 상태 저장 | 5가지 방식 | JSON × 2 + SQLite × 3 혼재 |
| `except Exception` | 전체 36개 (12개 파일) | 오류 원인 추적 불가 |

### 상태 저장 전체 목록 (5가지)

| 파일 | 담당 모듈 | 내용 |
|------|----------|------|
| `data/app_state.json` | `app/storage.py` | 런타임 상태 (포지션, Pool, DD, 국면) |
| `data/order_tickets.json` | `execution/order_manager.py` | 주문 FSM 티켓 (인플라이트 주문 포함) |
| `data/journal.db` | `app/journal.py` | 거래 기록, 신호 |
| `data/market_data.db` | `market/market_store.py` | 캔들, 오더북 스냅샷 |
| `data/experiment_history.db` | `strategy/experiment_store.py` | 실험, 파라미터 변경 이력 |

### 목표 구조

```
TradingBot (오케스트레이터, 흐름 제어만)
  │
  ├── [strategy/]
  │   ├── RegimeClassifier    ← 국면 판정만
  │   ├── EnvironmentFilter   ← L1 환경 필터만
  │   ├── StrategyScorer      ← 전략 점수 계산만
  │   ├── SizeDecider         ← 사이즈 결정만
  │   └── RuleEngine          ← 위 4개 조합 파사드 (기존 인터페이스 유지)
  │
  ├── [app/]
  │   ├── protocols.py        ← Protocol 인터페이스 + StrategyInputProvider
  │   ├── cycle_runner.py     ← run_cycle 분해 (6개 메서드)
  │   ├── state_store.py      ← 통일된 SQLite 상태 저장
  │   └── errors.py           ← 커스텀 예외 계층
  │
  └── [tests/]
      ├── unit/               ← 각 컴포넌트 독립 테스트
      │   ├── fixtures/       ← 고정 캔들 시퀀스 + IndicatorPack 픽스처
      └── integration/        ← Mock 기반 통합 테스트
```

---

## 5단계 실행 계획

### Phase 1 — 테스트 인프라 구축
**봇 영향: 없음**

**목표**: 이후 모든 리팩토링의 안전망 확보

**작업**:

1. **Protocol 인터페이스 정의** (`app/protocols.py`)
   ```python
   class MarketDataProvider(Protocol):
       async def get_candles(self, symbol: str, interval: str, limit: int) -> list[Candle]: ...

   class OrderExecutor(Protocol):
       async def place_order(self, symbol: str, side: str, qty: float, price: float) -> Order: ...

   class NotificationSender(Protocol):
       async def send(self, text: str, channel: str) -> bool: ...

   class StrategyInputProvider(Protocol):
       """RuleEngine 테스트용 — 고정된 IndicatorPack 제공."""
       def get_indicators_15m(self, symbol: str) -> IndicatorPack: ...
       def get_indicators_1h(self, symbol: str) -> IndicatorPack: ...
       def get_snapshot(self, symbol: str) -> MarketSnapshot: ...
   ```

2. **고정 픽스처 작성** (`tests/unit/fixtures/`)
   - 국면별 고정 캔들 시퀀스: CRISIS / STRONG_UP / WEAK_UP / WEAK_DOWN / RANGE 각 1개
   - 각 시퀀스에서 계산된 `IndicatorPack` 저장 (JSON 스냅샷)
   - `FrozenStrategyInput`: `StrategyInputProvider` 구현체, 픽스처 반환

3. **스냅샷 테스트 작성** (최소 기준)
   - `RegimeClassifier`: 국면별 5케이스 + 히스테리시스 3케이스 + CRISIS 즉시 전환 1케이스
   - `StrategyScorer`: 전략별 점수 계산 5케이스 (trend_follow, mean_reversion, dca, breakout, scalping)
   - `EnvironmentFilter`: 거부 케이스 4개 (CRISIS, 거래량 부족, 스프레드 초과, 심야 Tier3) + 통과 1개

4. **Mock 구현체 작성** (`tests/mocks/`)
   - `MockMarketData`, `MockOrderExecutor`, `MockNotifier`

**완료 기준**: `pytest tests/` 통과, 커버리지 측정 기준선 확보

---

### Phase 2 — RuleEngine 분해
**봇 영향: 재시작 1회**

**목표**: 2,000줄 God-class를 4개 독립 클래스로 분리

**선행 작업 — public accessor 추가 (분리 전)**:

`main.py`에서 `RuleEngine` 내부를 직접 접근하는 8곳을 먼저 public accessor로 교체:
```python
# RuleEngine에 추가 (분리 전)
@property
def strategy_params(self) -> dict: ...
def get_regime_state(self, symbol: str) -> RegimeState: ...
@property
def regime_states(self) -> dict[str, RegimeState]: ...
def decide_size(self, ...) -> SizeDecision: ...
```
→ `main.py`의 `_rule_engine._*` 직접 접근 8곳을 accessor 경유로 교체 후 테스트 통과 확인. 이 시점에서 Phase 2 롤백 = `git revert` 한 번으로 완전 복구.

**분리 대상**:

| 신규 클래스 | 파일 | 담당 |
|------------|------|------|
| `RegimeClassifier` | `strategy/regime_classifier.py` | `_raw_classify`, `_detect_aux_flags`, 히스테리시스 |
| `EnvironmentFilter` | `strategy/environment_filter.py` | `_check_layer1` |
| `StrategyScorer` | `strategy/strategy_scorer.py` | `_score_strategy_a~e`, `_evaluate_strategies` |
| `SizeDecider` | `strategy/size_decider.py` | `_decide_size`, `_get_size_bucket` |

**기존 호환성 유지**:
```python
# strategy/rule_engine.py — 파사드로만 남김
class RuleEngine:
    def __init__(self, config):
        self._classifier = RegimeClassifier(config)
        self._filter = EnvironmentFilter(config)
        self._scorer = StrategyScorer(config)
        self._sizer = SizeDecider(config)

    def generate_signals(self, snaps, indicators):
        # 4개 컴포넌트 조합, 기존 인터페이스 그대로
        ...
```

**완료 기준**:
- Phase 1 스냅샷 테스트 전체 통과
- `RuleEngine` 파일 ≤ 150줄
- 봇 재시작 후 사이클 정상 실행 확인

---

### Phase 3 — run_cycle 분해
**봇 영향: 재시작 1회**

**목표**: 585줄 단일 메서드 → 6개 focused 메서드

```python
async def run_cycle(self) -> None:
    """메인 사이클 오케스트레이터. 각 단계 위임만. ~20줄"""
    data = await self._fetch_market_data()
    signals = self._evaluate_signals(data)
    await self._manage_open_positions(data)
    await self._run_darwin_cycle()
    await self._execute_entries(signals)
    self._finalize_cycle(data)

async def _fetch_market_data(self) -> MarketData:
    """10개 코인 캔들 + 오더북 수집. ~80줄"""

def _evaluate_signals(self, data: MarketData) -> list[Signal]:
    """국면 판정 + 전략 점수 + 진입 후보 생성. ~60줄"""

async def _manage_open_positions(self, data: MarketData) -> None:
    """트레일링 스톱, 부분청산, 강제청산 + 네트워크 장애 알림. ~100줄"""

async def _run_darwin_cycle(self) -> None:
    """Darwin 토너먼트 + 챔피언 교체 + 파라미터 롤백. ~60줄 (기존 618~673줄)"""

async def _execute_entries(self, signals: list[Signal]) -> None:
    """RiskGate 통과 신호만 주문 실행 + CRISIS 청산. ~80줄"""

def _finalize_cycle(self, data: MarketData) -> None:
    """상태 저장, 로그, Pool 업데이트, 파일럿 카운터. ~50줄"""
```

**완료 기준**:
- `run_cycle()` ≤ 25줄
- 각 메서드 독립 단위 테스트 가능
- 봇 재시작 후 사이클 로그 정상

---

### Phase 4 — 상태 저장 통일
**봇 영향: 데이터 마이그레이션 필요**

**목표**: 5가지 저장 방식 → SQLite 단일 DB

**목표 스키마** (`data/bot.db`):
```sql
-- 런타임 상태: 키-값 쌍 (유연성 + crash-safety 모두 확보)
CREATE TABLE app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,   -- JSON 직렬화
    updated_at INTEGER NOT NULL
);

-- 나머지는 기존 스키마 그대로 이관
CREATE TABLE trades (...);          -- journal.db에서 이관
CREATE TABLE candles (...);         -- market_data.db에서 이관
CREATE TABLE experiments (...);     -- experiment_history.db에서 이관
CREATE TABLE order_tickets (...);   -- order_tickets.json에서 이관
```

> `app_state`는 JSON 컬럼 1개가 아니라 **키-값 행 단위**로 저장 (예: key=`positions`, key=`pool_balances`, key=`dd_state`). 각 키가 독립 행이므로 WAL 모드에서 부분 쓰기 시 해당 키만 롤백됨.

**마이그레이션 절차** (`scripts/migrate_state.py`):

```
1. [Dry-run] 기존 파일 읽기 → 변환 결과 출력 (쓰기 없음)
   - order_tickets.json에 PLACED/WAIT 상태 티켓 있으면 경고 출력 후 중단
     (인플라이트 주문이 있는 상태에서 마이그레이션 금지)

2. [Backup] 기존 파일 전체를 data/backup_YYYYMMDD_HHMMSS/ 로 복사

3. [Write] bot.db 생성 + 데이터 이관

4. [Verify] bot.db에서 읽어 원본과 diff 비교, 불일치 시 중단

5. [Commit flag] bot.db에 migration_complete = true 기록
   → 봇 시작 시 이 플래그 확인, 없으면 구 방식으로 fallback

6. [Restart] 봇 재시작
```

**롤백 절차** (명시):
```bash
# 1. 봇 중지
sudo systemctl stop bithumb-bot

# 2. bot.db 삭제 (또는 이름 변경)
mv data/bot.db data/bot.db.failed

# 3. 백업 복원
cp data/backup_YYYYMMDD_HHMMSS/* data/

# 4. 봇 재시작 (구 방식으로 자동 fallback)
sudo systemctl start bithumb-bot
```

**완료 기준**:
- 마이그레이션 후 봇 재시작 시 상태 정상 복원 (포지션, Pool, DD 확인)
- 구 파일 백업 보관
- 72시간 모니터링 후 구 파일 삭제

---

### Phase 5 — 예외 처리 체계화
**봇 영향: 재시작 1회**

**목표**: `except Exception` 36개 → 최상위 catch-all 1개 + 구체적 핸들러

**커스텀 예외 계층** (`app/errors.py`):
```python
class BotError(Exception): ...
class InsufficientBalanceError(BotError): ...  # 주문 취소, 알림
class OrderTimeoutError(BotError): ...          # 취소 후 재시도
class DataFetchError(BotError): ...             # 캐시 사용 또는 사이클 스킵
class PositionLimitExceededError(BotError): ... # 진입 거부
class APIAuthError(BotError): ...               # 봇 일시정지 + 알림
```

**파일별 교체 범위**:

| 파일 | `except Exception` 수 | 우선순위 |
|------|----------------------|---------|
| `app/main.py` | 7개 | Phase 5 포함 |
| `execution/order_manager.py` | 6개 | Phase 5 포함 |
| `execution/reconciler.py` | 2개 | Phase 5 포함 |
| `market/datafeed.py` | 4개 | Phase 5 포함 |
| `strategy/`, `bot_discord/`, 기타 | 17개 | Phase 5 후속 (별도 PR) |

**완료 기준 (Phase 5)**:
- `app/`, `execution/`, `market/` 내 `except Exception` = 0
- 각 예외 타입 단위 테스트 (복구 동작 검증)
- 나머지 17개는 후속 작업으로 분리

---

## 불변 원칙

1. **봇은 각 단계 완료 시 재시작 한 번만** — 중간에 두 번 재시작 없음
2. **이전 단계 테스트 통과 확인 후 다음 단계 진행**
3. **Phase 4는 인플라이트 주문 0개일 때만 실행** (dry-run에서 검증)
4. **각 단계는 `git revert` 한 번으로 롤백 가능** (Phase 2는 accessor 추가 선행 필수)
5. **Phase 4 롤백은 위의 명시된 절차 그대로 실행**

---

## 완료 기준 (전체)

- [ ] `pytest tests/` 통과, 핵심 로직 커버리지 ≥ 70%
- [ ] 어떤 단일 클래스도 500줄 초과하지 않음
- [ ] `run_cycle()` ≤ 25줄
- [ ] `app/`, `execution/`, `market/`에서 `except Exception` = 0
- [ ] 상태 저장 단일 DB (`data/bot.db`)
- [ ] 봇 연속 24시간 무중단 운영 확인 (각 단계 후)
