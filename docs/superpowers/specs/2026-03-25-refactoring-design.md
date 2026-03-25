# Bithumb Bot v2 — 전면 리팩토링 설계

**작성일**: 2026-03-25
**방식**: Strangler Fig (단계별 교체, 봇 운영 유지)
**배경**: 코드 품질 평가 결과 종합 점수 6.5/10. 실제 자금 운용 봇으로서 God-class, 1000줄+ 메서드, 테스트 불가 구조가 실제 위험 요소.

---

## 목표

- 각 클래스가 하나의 책임만 가짐 (SRP)
- 핵심 로직을 단위 테스트 가능하게
- 봇을 멈추지 않고 단계별 교체
- 각 단계가 독립적으로 배포·검증 가능

---

## 현재 vs 목표 구조

### 현재 문제

| 파일 | 줄수 | 문제 |
|------|------|------|
| `app/main.py` (TradingBot) | 1,359줄 | 8가지 이상 책임 |
| `strategy/rule_engine.py` (RuleEngine) | 2,000줄+ | 국면판정+점수계산+L1필터+사이즈결정 혼재 |
| `run_cycle()` 메서드 | 934줄 | 단일 메서드, 테스트 불가 |
| 상태 저장 | 4가지 방식 | JSON × 1 + SQLite × 3 혼재 |
| 예외 처리 | `except Exception` × 7 | 오류 원인 추적 불가 |

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
  │   ├── cycle_runner.py     ← run_cycle 분해 (5개 메서드)
  │   ├── state_store.py      ← 통일된 SQLite 상태 저장
  │   └── errors.py           ← 커스텀 예외 계층
  │
  └── [tests/]
      ├── unit/               ← 각 컴포넌트 독립 테스트
      └── integration/        ← Mock 기반 통합 테스트
```

---

## 5단계 실행 계획

### Phase 1 — 테스트 인프라 구축
**봇 영향: 없음**

**목표**: 이후 모든 리팩토링의 안전망 확보

**작업**:
1. Protocol 인터페이스 정의
   ```python
   # app/protocols.py
   class MarketDataProvider(Protocol):
       async def get_candles(self, symbol: str, interval: str, limit: int) -> list[Candle]: ...

   class OrderExecutor(Protocol):
       async def place_order(self, symbol: str, side: str, qty: float, price: float) -> Order: ...

   class NotificationSender(Protocol):
       async def send(self, text: str, channel: str) -> bool: ...
   ```

2. Mock 구현체 작성 (`tests/mocks/`)
   - `MockMarketData`: 캔들 데이터 픽스처 반환
   - `MockOrderExecutor`: 주문 기록만, 실제 API 미호출
   - `MockNotifier`: 알림 캡처

3. 핵심 로직 기존 동작 스냅샷 테스트 작성
   - RegimeClassifier 입력/출력 케이스 20개
   - StrategyScorer 각 전략별 점수 케이스
   - L1 필터 거부/통과 케이스

**완료 기준**: `pytest tests/` 통과, 커버리지 측정 기준선 확보

---

### Phase 2 — RuleEngine 분해
**봇 영향: 재시작 1회**

**목표**: 2,000줄 God-class를 4개 독립 클래스로 분리

**분리 대상**:

| 신규 클래스 | 파일 | 담당 메서드 |
|------------|------|------------|
| `RegimeClassifier` | `strategy/regime_classifier.py` | `_raw_classify`, `_detect_aux_flags`, 히스테리시스 |
| `EnvironmentFilter` | `strategy/environment_filter.py` | `_check_layer1` |
| `StrategyScorer` | `strategy/strategy_scorer.py` | `_score_strategy_a~e`, `_evaluate_strategies` |
| `SizeDecider` | `strategy/size_decider.py` | `_decide_size`, `_get_size_bucket` |

**기존 호환성 유지 방법**:
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

`TradingBot`은 `RuleEngine`만 참조 → 호출부 변경 없음.

**완료 기준**:
- Phase 1 스냅샷 테스트 전체 통과
- 봇 재시작 후 사이클 정상 실행 확인

---

### Phase 3 — run_cycle 분해
**봇 영향: 재시작 1회**

**목표**: 934줄 단일 메서드 → 5개 focused 메서드

```python
async def run_cycle(self) -> None:
    """메인 사이클 오케스트레이터. 각 단계 위임만."""
    data = await self._fetch_market_data()
    signals = self._evaluate_signals(data)
    await self._manage_open_positions(data)
    await self._execute_entries(signals)
    self._finalize_cycle(data)

async def _fetch_market_data(self) -> MarketData:
    """10개 코인 캔들 + 오더북 수집. ~80줄"""

def _evaluate_signals(self, data: MarketData) -> list[Signal]:
    """국면 판정 + 전략 점수 + 진입 후보 생성. ~60줄"""

async def _manage_open_positions(self, data: MarketData) -> None:
    """트레일링 스톱, 부분청산, 강제청산. ~80줄"""

async def _execute_entries(self, signals: list[Signal]) -> None:
    """RiskGate 통과 신호만 주문 실행. ~60줄"""

def _finalize_cycle(self, data: MarketData) -> None:
    """상태 저장, 로그, Pool 업데이트. ~40줄"""
```

**완료 기준**:
- 각 메서드 독립 단위 테스트 가능
- 봇 재시작 후 사이클 로그 정상

---

### Phase 4 — 상태 저장 통일
**봇 영향: 데이터 마이그레이션 필요**

**목표**: 4가지 저장 방식 → SQLite 단일 DB

**현재 → 목표**:
```
app_state.json      ─┐
journal.db          ─┤  →  data/bot.db (단일 SQLite, WAL)
market_store.db     ─┤       ├── app_state (JSON 컬럼으로 유연성 유지)
experiment_store.db ─┘       ├── trades
                              ├── candles
                              └── experiments
```

**마이그레이션 전략**:
1. `app/state_store.py` 신규 작성 (bot.db 인터페이스)
2. 기존 데이터 마이그레이션 스크립트 작성 (`scripts/migrate_state.py`)
3. 구 파일 읽기 → bot.db 쓰기 검증 → 구 파일 백업
4. TradingBot이 StateStore를 사용하도록 교체

**완료 기준**:
- 마이그레이션 후 봇 재시작 시 상태 정상 복원
- 구 DB 파일 백업 보관

---

### Phase 5 — 예외 처리 체계화
**봇 영향: 재시작 1회**

**목표**: `except Exception` 제거 → 구체적 복구 로직

```python
# app/errors.py
class BotError(Exception):
    """봇 최상위 예외."""

class InsufficientBalanceError(BotError):
    """잔고 부족 — 주문 취소, 알림."""

class OrderTimeoutError(BotError):
    """주문 타임아웃 — 취소 후 재시도."""

class DataFetchError(BotError):
    """데이터 수집 실패 — 캐시 사용 또는 사이클 스킵."""

class PositionLimitExceededError(BotError):
    """포지션 한도 초과 — 진입 거부."""

class APIAuthError(BotError):
    """API 인증 오류 — 봇 일시정지 + 알림."""
```

`except Exception` → `except DataFetchError` 등 구체적 핸들러로 교체. 각 예외별 복구 전략 명시.

**완료 기준**:
- `except Exception` 0개 (의도적인 것 제외)
- 각 예외 타입 단위 테스트

---

## 불변 원칙

1. **봇은 각 단계 완료 시마다 재시작 한 번만** — 중간에 두 번 재시작 없음
2. **이전 단계 테스트 통과 확인 후 다음 단계 진행**
3. **각 단계는 독립적으로 롤백 가능** — git revert 한 번으로 복구
4. **Phase 4(상태 마이그레이션) 전에 반드시 DB 백업**

---

## 완료 기준 (전체)

- [ ] `pytest tests/` 통과, 핵심 로직 커버리지 ≥ 70%
- [ ] 어떤 단일 클래스도 500줄 초과하지 않음
- [ ] `run_cycle()` ≤ 50줄
- [ ] `except Exception` ≤ 1개 (최상위 catch-all만)
- [ ] 상태 저장 단일 DB
- [ ] 봇 연속 24시간 무중단 운영 확인
