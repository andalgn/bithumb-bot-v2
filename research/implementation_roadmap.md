# 자금 활용률 개선 구현 로드맵

## 요약
현재 930,000 KRW 자본에서 4.1% 활용률 → **50-60% 목표**

**총 소요 기간**: 4주
**투자 대비**: 3~5시간의 코드 작업 (Phase A) → 3배 신호 증대, 10배 활용률 증대

---

## Phase A: 신호 3배 증대 (1주)

### 목표
- 신호: 2개/일 → 6-8개/일 (3배)
- 활용률: 4% → 12-15%
- 추가 코드 작업: 3-4시간

### 작업 목록

#### Task 1: Strategy D (Scalping) 활성화 (30분)
**파일**: `strategy/rule_engine.py`

**현재 상태**:
- Scalping 전략 구현됨 (줄 300-310)
- 하지만 REGIME_STRATEGY_MAP에 없어서 신호 생성 안 됨

**작업**:
```python
# 줄 40-50 근처 (REGIME_STRATEGY_MAP 정의)

# 현재:
REGIME_STRATEGY_MAP = {
    Regime.UP:          [Strategy.TREND_FOLLOW, Strategy.BREAKOUT],
    Regime.DOWN:        [Strategy.MEAN_REVERSION, Strategy.DCA],
    Regime.CRISIS:      [Strategy.DCA],
    Regime.RANGE:       [Strategy.MEAN_REVERSION],
    Regime.WEAK_UP:     [Strategy.TREND_FOLLOW],
}

# 변경:
REGIME_STRATEGY_MAP = {
    Regime.UP:          [Strategy.TREND_FOLLOW, Strategy.BREAKOUT, Strategy.SCALPING],
    Regime.DOWN:        [Strategy.MEAN_REVERSION, Strategy.DCA, Strategy.SCALPING],
    Regime.CRISIS:      [Strategy.DCA, Strategy.SCALPING],
    Regime.RANGE:       [Strategy.MEAN_REVERSION, Strategy.SCALPING],
    Regime.WEAK_UP:     [Strategy.TREND_FOLLOW, Strategy.SCALPING],
}
```

**예상 신호 추가**: +3-5개/일

**검증**:
- rule_engine_test.py에서 SCALPING이 모든 국면에 포함되는지 확인
- Paper 테스트에서 5-10분 포지션이 생성되는지 모니터링

---

#### Task 2: Mean Reversion 다단계 RSI (90분)
**파일**: `strategy/strategy_scorer.py`

**현재 상태**:
```python
def score_strategy_b(self, ind_15m, candles_15m=None):
    # RSI < 30 또는 > 70만 신호 생성
    # 신호 빈도: 1-2개/일
```

**작업 상세**:
```python
# strategy_scorer.py 줄 150-180 (score_strategy_b 함수)

# 기존 코드 제거:
# if rsi < 30 or rsi > 70:
#     return ScoreResult(score=65.0, ...)
# return ScoreResult(score=0.0, ...)

# 새 코드:
def score_strategy_b(self, ind_15m, candles_15m=None):
    """반전포착 점수 — 다단계 RSI"""

    rsi = self._last_valid(ind_15m.rsi)
    if rsi <= 0 or np.isnan(rsi):
        return ScoreResult(strategy=Strategy.MEAN_REVERSION, score=0.0)

    # Strength 1: 극단값 (RSI < 20 또는 > 80)
    if rsi < 20 or rsi > 80:
        return ScoreResult(
            strategy=Strategy.MEAN_REVERSION,
            score=75.0,  # FULL
            detail=f"RSI {rsi:.1f} 극단값",
        )

    # Strength 2: 강한 신호 (RSI < 30 또는 > 70)
    if rsi < 30 or rsi > 70:
        return ScoreResult(
            strategy=Strategy.MEAN_REVERSION,
            score=65.0,  # PROBE
            detail=f"RSI {rsi:.1f} 강한 신호",
        )

    # Strength 3: 약한 신호 (RSI < 40 또는 > 60)
    if rsi < 40 or rsi > 60:
        return ScoreResult(
            strategy=Strategy.MEAN_REVERSION,
            score=50.0,  # 낮음 (컷오프로 일부 제외)
            detail=f"RSI {rsi:.1f} 약한 신호",
        )

    return ScoreResult(
        strategy=Strategy.MEAN_REVERSION,
        score=0.0,
        detail=f"RSI {rsi:.1f} 정상",
    )
```

**예상 신호 추가**: +2-3개/일

**검증**:
- test_strategy_scorer.py에서 RSI 값별 점수 확인
- 특히 RSI 35-45, 55-65 범위에서 점수 50.0 반환 확인
- Paper 테스트에서 신호 빈도 모니터링

---

#### Task 3: Layer 1 필터 점수 기반 조정 (90분)
**파일**: `strategy/environment_filter.py`

**현재 상태**:
```python
def check(self, regime, snap, ind_15m, tier_params):
    # 고정 임계값만 사용
    if current_vol < avg_vol * 0.4:
        return False  # 거래량 필터
```

**작업 상세**:

먼저 생성_signals()에서 점수를 전달하도록 수정:

```python
# rule_engine.py _check_layer1() 호출 부분 (줄 380 근처)

# 현재:
l1_pass, l1_reason = self._check_layer1(regime, snap, ind_15m, tier_params)

# 변경: 점수를 전달하기 위해 먼저 전략 평가
# (또는 대안: 신호 생성 후 필터링)
# 대안이 더 깔끔하므로 추천: 점수별 필터링은 Signal 생성 후

# Signal을 생성한 후 점수 기반 필터링:
def generate_signals(self, snapshots, paper_test=False):
    signals = []
    for symbol, snap in snapshots.items():
        # ... 기존 로직
        signal = Signal(...)

        # L1 필터를 신호 생성 후 적용 (점수 기반)
        l1_pass, l1_reason = self._check_layer1(
            regime, snap, ind_15m, tier_params,
            score=best.score  # 신규: 점수 전달
        )
        if not l1_pass:
            continue

        signals.append(signal)
    return signals
```

다음으로 environment_filter.py 수정:

```python
# strategy/environment_filter.py 줄 18-67 (check 함수)

def check(
    self,
    regime: Regime,
    snap: MarketSnapshot,
    ind: IndicatorPack,
    tier_params: TierParams,
    score: float = 0.0,  # 신규: 신호 점수
) -> tuple[bool, str]:
    """L1 환경 필터 (점수 기반 동적 조정)"""

    # 1. 국면 != CRISIS
    if regime == Regime.CRISIS:
        return False, "L1: CRISIS 국면"

    # 2. 거래량 필터 (점수에 따라 동적 조정)
    if snap.candles_15m and len(snap.candles_15m) >= 22:
        volumes = np.array([c.volume for c in snap.candles_15m])
        avg_vol = float(np.mean(volumes[-22:-2]))
        current_vol = float(volumes[-2])

        # 점수 기반 임계값 조정
        if score >= 70:
            threshold = 0.25  # 0.4 → 0.25 (완화)
        elif score < 45:
            threshold = 0.5   # 0.4 → 0.5 (강화)
        else:
            threshold = 0.4   # 기본값

        if avg_vol > 0 and current_vol < avg_vol * threshold:
            return False, f"L1: 거래량 부족 ({current_vol:.0f} < {avg_vol * threshold:.0f})"

    # 3. 스프레드 필터 (점수에 따라 동적 조정)
    if snap.orderbook:
        spread = snap.orderbook.spread_pct

        # 점수 기반 배수 조정
        if score >= 70:
            spread_mult = 2.5   # 2.0 → 2.5 (완화)
        elif score < 45:
            spread_mult = 1.5   # 2.0 → 1.5 (강화)
        else:
            spread_mult = 2.0   # 기본값

        if spread > tier_params.spread_limit * spread_mult:
            return False, f"L1: 스프레드 초과 ({spread:.4f} > {tier_params.spread_limit * spread_mult})"

    # 4. 1H 급변동 (유지)
    if snap.candles_1h and len(snap.candles_1h) >= 2:
        c = snap.candles_1h[-2]
        if c.open > 0 and abs(c.close / c.open - 1) >= 0.015:
            return False, f"L1: 1H 급변동"

    return True, ""
```

**예상 신호 통과율 개선**: 70% → 85% (추가 신호 +15%)

**검증**:
- test_environment_filter.py에서 점수별 임계값 확인
- 특히 score=75와 score=35일 때 다른 결과 확인

---

#### Task 4: 통합 테스트 및 검증 (60분)
**파일**: `tests/`

**작업**:
```bash
# 1. 기존 테스트 통과 확인
pytest tests/test_rule_engine.py -v
pytest tests/test_strategy_scorer.py -v
pytest tests/test_environment_filter.py -v

# 2. 신규 기능 테스트
# test_rule_engine.py에 추가:
def test_scalping_all_regimes():
    """Scalping 전략이 모든 국면에서 활성화되는지 확인"""
    for regime in Regime:
        assert Strategy.SCALPING in REGIME_STRATEGY_MAP[regime]

def test_mean_reversion_multi_level_rsi():
    """Mean Reversion이 다단계 RSI를 적용하는지 확인"""
    scorer = StrategyScorer()

    # RSI < 20: 75점
    ind = create_mock_indicators(rsi=15)
    result = scorer.score_strategy_b(ind)
    assert result.score == 75.0

    # RSI < 30: 65점
    ind = create_mock_indicators(rsi=25)
    result = scorer.score_strategy_b(ind)
    assert result.score == 65.0

    # RSI < 40: 50점
    ind = create_mock_indicators(rsi=35)
    result = scorer.score_strategy_b(ind)
    assert result.score == 50.0

def test_layer1_score_based_filtering():
    """L1 필터가 점수 기반으로 동작하는지 확인"""
    ef = EnvironmentFilter()

    # 높은 신호(75점)는 필터 통과 확률 높음
    # 낮은 신호(35점)는 필터 통과 확률 낮음
    # ...
```

**검증 기준**:
- 모든 기존 테스트 통과
- 신규 테스트 추가 및 통과
- Coverage 80% 이상 유지

---

### Phase A 완료 기준

```
□ REGIME_STRATEGY_MAP에 SCALPING 추가
□ strategy_scorer.py mean_reversion 다단계 RSI 구현
□ environment_filter.py 점수 기반 동적 조정 구현
□ 모든 테스트 통과
□ Paper 테스트로 신호 빈도 확인 (6-8개/일)
□ 활용률 12-15% 달성
```

---

## Phase B: 4시간 타임프레임 추가 (2주)

### 목표
- 추가 신호: +1-2개/일
- 활용률: 15% → 25-35%
- 소요 시간: 2-3일

### Task 1: 4H 캔들 수집 (2시간)
**파일**: `market/datafeed.py`

**현재 상태**:
```python
# 수집: 5M, 15M, 1H
# 필요: 4H 추가
```

**작업**:
```python
# market/datafeed.py (캔들 다운로드 부분)

async def fetch_candles(self, symbol: str, interval: str, limit: int = 200):
    """기존 로직 유지"""
    # 5M, 15M, 1H은 기존 구현

    # 신규: 4H 지원
    if interval == "4h":
        # Bithumb API: 240분 = 4시간
        endpoint = f"{symbol}_KRW/candles_240"
        response = await self._call(endpoint, limit)
        return response

    # ...기존 코드
```

**구현 옵션**:
1. **Option A (추천)**: 4H는 1H에서 캔들 4개를 합쳐서 계산
   ```python
   candles_4h = aggregate_candles(candles_1h, 4)
   ```

2. **Option B**: Bithumb API에서 직접 가져오기
   ```python
   candles_4h = await fetch_candles(symbol, "4h")
   ```

Option A가 더 효율적 (API 호출 감소)

---

### Task 2: MarketSnapshot에 4H 필드 추가 (30분)
**파일**: `app/data_types.py`

**작업**:
```python
@dataclass
class MarketSnapshot:
    """현재 상태: candles_15m, candles_1h"""

    # 신규 추가:
    candles_4h: list[Candle] | None = None
```

---

### Task 3: 4H 지표 계산 (15분)
**파일**: `strategy/indicators.py`

**현재 상태**:
```python
def compute_indicators(candles: list[Candle]) -> IndicatorPack:
    """15M/1H 공용 함수"""
    # 이미 일반화됨
```

**작업**: 기존 함수 재사용 (변경 불필요)
```python
ind_4h = compute_indicators(snap.candles_4h)
```

---

### Task 4: 4H Breakout 신호 추가 (2시간)
**파일**: `strategy/rule_engine.py`, `strategy/strategy_scorer.py`

**작업**:
```python
# rule_engine.py generate_signals()

# 4H 지표 계산 추가
if snap.candles_4h and len(snap.candles_4h) >= 30:
    ind_4h_4h = compute_indicators(snap.candles_4h)
    close_4h = np.array([c.close for c in snap.candles_4h])

    # Breakout 신호 평가 (4H 기준)
    sr_4h = self._score_breakout_4h(ind_4h_4h, close_4h)
    if sr_4h.score > 45:
        results.append(sr_4h)

# strategy_scorer.py에 신규 함수:
def score_breakout_4h(self, ind_4h, close_4h):
    """4시간 Breakout 신호"""
    # 1H Breakout과 유사하지만, 4H 기준
    # 강도: 기존 Breakout의 1.2배 (더 강한 추세 확인)
    # SL: -1.5%, TP: +4% (RR 1:2.7)
    # 일일 신호: 0-1개
```

**예상 신호**: +0-1개/일

---

### Phase B 완료 기준

```
□ 4H 캔들 수집 구현
□ MarketSnapshot.candles_4h 추가
□ 4H 지표 계산 통합
□ 4H Breakout 신호 로직 구현
□ 테스트 및 Paper 검증
□ 활용률 25-35% 달성
```

---

## Phase C: Pool 재설계 (3주)

### 목표
- 포지션당 크기: 7K → 80-150K (10배)
- 동시 포지션: 5 → 10-15개
- 활용률: 35% → 50-60%
- 소요 시간: 1주

### Task 1: 2-Pool 모델 설계 (2시간)
**파일**: `strategy/pool_manager.py`

**현재 상태**:
```python
DEFAULT_RATIOS = {
    Pool.CORE: 0.40,    # 보수적
    Pool.ACTIVE: 0.50,  # 공격적
    Pool.RESERVE: 0.10,
}
MAX_POSITIONS = {
    Pool.CORE: 5,
    Pool.ACTIVE: 8,
    Pool.RESERVE: 1,
}
```

**변경**:
```python
# 2-Pool 모델
DEFAULT_RATIOS = {
    Pool.ALLOCATION: 0.85,  # 활성 거래용
    Pool.RESERVE: 0.15,      # 긴급용
}

MAX_POSITIONS = {
    Pool.ALLOCATION: 20,  # 상한 (동적 사이징으로 보정)
    Pool.RESERVE: 0,
}

# 추가: 동적 사이징 함수
def calculate_position_size(score: float, total_equity: float) -> float:
    """신호 점수에 따른 포지션 크기"""
    if score >= 75:
        return total_equity * 0.85 / 5  # 150K (큰 포지션, 적게)
    elif score >= 60:
        return total_equity * 0.85 / 8  # 100K (중간)
    else:
        return total_equity * 0.85 / 15  # 50K (작은 포지션, 많이)
```

---

### Task 2: Size Decider 확장 (2시간)
**파일**: `strategy/size_decider.py`

**현재 상태**:
```python
def decide(self, strategy, score) -> str:
    """FULL / PROBE / HOLD 반환"""
    # 컷오프만 처리
```

**확장**:
```python
def calculate_size(self, score: float, available: float) -> float:
    """신호 점수에 따른 포지션 크기 계산"""

    if score >= 75:
        return available * 0.20  # 활용 가능 자금의 20%
    elif score >= 60:
        return available * 0.12  # 12%
    elif score >= 45:
        return available * 0.06  # 6%
    else:
        return 0.0  # HOLD
```

---

### Task 3: Position Manager 통합 (2시간)
**파일**: `strategy/position_manager.py`

**현재 상태**:
```python
def suggest_order(...):
    # 포지션 크기 계산 로직
```

**변경**:
```python
def suggest_order(self, signal: Signal, pool_mgr: PoolManager) -> Order | None:
    # 1. 신호 점수에 따른 크기 계산
    size = self.size_decider.calculate_size(
        signal.score,
        pool_mgr.get_available(Pool.ALLOCATION)
    )

    # 2. Pool에서 자금 할당
    if pool_mgr.allocate(Pool.ALLOCATION, size):
        return Order(size=size, ...)
    else:
        return None
```

---

### Task 4: 테스트 및 검증 (3시간)

**작업**:
```bash
# 1. 단위 테스트
pytest tests/test_pool_manager.py
pytest tests/test_size_decider.py
pytest tests/test_position_manager.py

# 2. 통합 테스트
# 신호 점수별 포지션 크기 검증
def test_dynamic_position_sizing():
    pm = PositionManager()
    pool = PoolManager(930000)

    # 높은 신호
    size_high = pm.size_decider.calculate_size(80, pool.get_available(Pool.ALLOCATION))
    assert size_high > size_med > size_low

    # 중간 신호
    size_med = pm.size_decider.calculate_size(60, pool.get_available(Pool.ALLOCATION))

    # 낮은 신호
    size_low = pm.size_decider.calculate_size(40, pool.get_available(Pool.ALLOCATION))

# 3. Paper 테스트 (1주)
# 동적 사이징이 실제로 작동하는지 확인
```

---

### Phase C 완료 기준

```
□ 2-Pool 모델 구현
□ 동적 사이징 함수 구현
□ Position Manager 통합
□ 모든 테스트 통과
□ Paper 테스트로 포지션 크기 확인
□ 활용률 50-60% 달성
□ 일일 수익성 모니터링 (최소 Sharpe 0.5)
```

---

## 전체 타임라인

```
Week 1 (Phase A)
├─ Mon-Tue: Task 1-2 (Strategy D + Mean Reversion)
├─ Wed: Task 3 (Layer 1 필터)
├─ Thu-Fri: Task 4 (테스트 + Paper)
└─ Expected: 신호 6-8개/일, 활용률 12-15%

Week 2-3 (Phase B)
├─ Mon: Task 1-2 (4H 캔들 + MarketSnapshot)
├─ Tue-Wed: Task 3-4 (4H Breakout)
├─ Thu-Fri: 테스트 + Paper
└─ Expected: 신호 8-10개/일, 활용률 25-35%

Week 4 (Phase C 준비)
├─ Mon-Wed: Task 1-3 (Pool 재설계)
├─ Thu-Fri: Task 4 (테스트)
└─ Expected: 포지션당 크기 10배, 활용률 40-50%

Week 5+ (Phase C 본격화)
├─ Paper 테스트 1주
├─ 모니터링 및 튜닝
└─ LIVE 전환 준비
```

---

## 리스크 및 대응

### Risk 1: 신호 품질 저하
**원인**: 필터 완화로 거짓 신호 증가
**대응**:
- Phase A 이후 Paper 테스트에서 신호 품질 검증
- 승률이 35% 이하면 Task 3 (필터) 조정
- 컷오프 강화 (50점 → 55점) 옵션 준비

### Risk 2: 포지션 관리 복잡성 증가
**원인**: 동시 포지션 수 증가 (5 → 15개)
**대응**:
- Order Manager FSM은 이미 구현됨
- Risk Gate (MDD, DD) 자동화 확인
- Manual intervention 절차 문서화

### Risk 3: 수수료 부담 증가
**원인**: 거래 빈도 3배 증가
**대응**:
- Bithumb API 수수료 0.1% 적용
- 월간 거래비용 = 930K × 3배 빈도 × 0.1% = 약 2.8K/월
- 수익 시뮬레이션에서 거래비용 차감 후 재평가
- 필요시 포지션당 최소 크기 제한 추가

### Risk 4: 보유 기간 단축
**원인**: Scalping 신호로 5-30분 포지션 증가
**대응**:
- 이미 partial_exit.py에서 처리
- 15분 이내 청산 로직 확인
- Slippage 영향 모니터링

---

## 성공 지표

### 정량적 지표
```
메트릭              기준        기대값      Red Flag
─────────────────────────────────────────────────
신호/일            1-2         8-10        < 5
활용률             4%          50%         < 30%
포지션당 크기      7K          80K         < 50K
동시 포지션        5           12          < 8
월간 거래수        50          300         < 150
```

### 정성적 지표
```
Phase A 완료:
✓ REGIME_STRATEGY_MAP에 SCALPING 추가됨
✓ Mean Reversion 다단계 RSI 작동함
✓ L1 필터 점수 기반 조정 작동함
✓ Paper 테스트에서 신호 3배 확인

Phase B 완료:
✓ 4H 캔들 수집 및 지표 계산 됨
✓ 4H Breakout 신호 생성 확인
✓ 추가 신호 1-2개/일 확인

Phase C 완료:
✓ 2-Pool 모델 배포 됨
✓ 동적 사이징 작동 확인
✓ 활용률 50% 이상 달성
✓ Sharpe 0.5 이상 유지
```

---

## 실행 체크리스트

### Phase A (1주)
- [ ] 코드 수정 완료 (4시간)
- [ ] 단위 테스트 작성 및 통과 (2시간)
- [ ] Paper 테스트 실행 (1주)
- [ ] 신호 빈도 검증 (6-8개/일 확인)
- [ ] 활용률 계산 (12-15% 확인)
- [ ] Code Review 완료
- [ ] 피드백 반영

### Phase B (2주)
- [ ] 4H 캔들 수집 구현 (2시간)
- [ ] 4H Breakout 신호 구현 (2시간)
- [ ] 통합 테스트 (2시간)
- [ ] Paper 테스트 (1주)
- [ ] 신호 빈도 재검증
- [ ] 활용률 확인 (25-35%)

### Phase C (3주)
- [ ] Pool 재설계 (2시간)
- [ ] 동적 사이징 구현 (2시간)
- [ ] 통합 테스트 (2시간)
- [ ] Paper 테스트 (2주)
- [ ] 포지션 크기 확인 (80K+)
- [ ] 활용률 확인 (50%+)
- [ ] Risk Management 최종 검증

### LIVE 전환
- [ ] 신호 점수 필터 강화 (minimum 50점)
- [ ] 초기 포지션 크기 50% 축소 (Safety)
- [ ] 일일 리뷰 (1주)
- [ ] 주간 리뷰 자동화 (ReviewEngine)
- [ ] 월간 리뷰 (DeepSeek)

---

## 예상 결과

```
현재 상태:
- 신호: 1-2개/일
- 활용률: 4.1%
- 포지션당 크기: 7K
- 동시 포지션: 5개

4주 후:
- 신호: 8-10개/일 (4-5배)
- 활용률: 50%+ (12배)
- 포지션당 크기: 80-100K (12배)
- 동시 포지션: 10-15개 (2배)

월간 거래:
- 현재: 50거래/월
- 개선: 250-300거래/월 (5배)

자본 효율:
- 930K 자본으로 충분한 거래 빈도 확보
- 신호당 평균 체류 시간: 4시간 (개선 전 8시간)
- 일일 자금 회전율: 50-60% (기존 4%)
```

---

## 주요 참고사항

1. **코드 변경은 최소화**
   - 기존 구현된 전략들의 활성화가 주
   - 새로운 알고리즘 추가는 최소

2. **테스트 우선**
   - 각 단계마다 Paper 테스트 필수
   - Red Flag 감지 즉시 조정

3. **점진적 전환**
   - Phase A만 적용해도 자금 활용률 3배
   - Phase B 없이도 충분한 신호 빈도 가능
   - Phase C는 선택적 (포지션 크기 최적화)

4. **모니터링**
   - 일일: 신호 생성 빈도, 승률
   - 주간: 활용률, MDD, Sharpe
   - 월간: DeepSeek 리뷰

---

**이 로드맵은 살아있는 문서입니다.**
실제 구현 과정에서 발견되는 이슈나 개선 사항은 반영됩니다.
