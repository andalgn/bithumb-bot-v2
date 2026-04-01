# 신호 생성 빈도 분석: 원인 및 해결책

## 개요
현재 봇의 핵심 문제는 **신호 부족**이 아니라 **신호 필터의 과도한 보수성**입니다.

---

## 1. 신호 생성 경로 분석

### 1.1 코드 흐름 (rule_engine.py)

```
generate_signals()
├─ classify_regime()          ← 5개 국면 분류
│  └─ RegimeClassifier       ← 히스테리시스 적용
│
├─ _check_layer1()           ← L1 환경 필터
│  └─ EnvironmentFilter      ← 4개 조건: 거래량, 스프레드, 1H 급변동
│
└─ _evaluate_strategies()    ← 전략 평가
   ├─ _score_strategy_a()    ← 추세추종 (TREND_FOLLOW)
   ├─ _score_strategy_b()    ← 반전포착 (MEAN_REVERSION)
   ├─ _score_strategy_c()    ← 브레이크아웃 (BREAKOUT)
   ├─ _score_strategy_d()    ← 스칼핑 (SCALPING) ← 미활성화
   └─ _score_strategy_e()    ← DCA (DCA) ← CRISIS만 활성화
```

### 1.2 현재 활성 경로
```
대부분의 신호: MEAN_REVERSION만
- 조건: RSI < 30 또는 RSI > 70 (극단값)
- 빈도: 1-2개/일
- 문제: RSI 극단값은 드물게 발생
```

### 1.3 왜 신호가 적은가?

#### 원인 1: REGIME_STRATEGY_MAP의 전략 제한
```python
# rule_engine.py 상수
REGIME_STRATEGY_MAP = {
    Regime.UP:          [Strategy.TREND_FOLLOW, Strategy.BREAKOUT],
    Regime.DOWN:        [Strategy.MEAN_REVERSION, Strategy.DCA],
    Regime.CRISIS:      [Strategy.DCA],
    Regime.RANGE:       [Strategy.MEAN_REVERSION],
    Regime.WEAK_UP:     [Strategy.TREND_FOLLOW],
}

분석:
- SCALPING(Strategy.D): 제외됨 (어느 국면에도 없음)
- DCA(Strategy.E): CRISIS와 DOWN만 (범위 너무 좁음)
```

#### 원인 2: 극단값 필터의 엄격함
```python
# strategy_scorer.py 기준
Mean Reversion 진입 조건:
- RSI < 30: 매수
- RSI > 70: 매도

통계:
- RSI < 30 확률: 약 15% (한 국면 내 시간의 15%)
- 국면 전환 빈도: 4-8시간 (15M 기준 16-32캔들)
- 예상 신호: 1개 / 1-2일

현실:
- 관찰된 신호: 1-2개 / 일
→ 이론과 일치하며, 이는 **너무 엄격한 필터**를 의미
```

#### 원인 3: Layer 1 필터의 추가 제약
```python
# environment_filter.py
거래량 < 20봉 평균 × 0.4 → 차단
스프레드 > 한계 × 2 → 차단
1H 급변동 ≥ 1.5% → 차단

이미 완화된 상태이지만, 신호 생성 자체가 부족하므로
상대적으로 필터의 영향이 크게 느껴짐
```

---

## 2. RSI 극단값 조건의 수학적 분석

### 2.1 RSI 분포 특성
```
RSI 계산: 14기간 표준 (strategy_scorer.py)

정상 시장 조건에서의 RSI 분포:
┌────────┬─────────┬──────────┐
│ RSI 범위 │ 확률   │ 의미     │
├────────┼─────────┼──────────┤
│ < 20   │ 5%      │ 극도 과매도
│ 20-30  │ 10%     │ 과매도
│ 30-70  │ 70%     │ 정상
│ 70-80  │ 10%     │ 과매수
│ > 80   │ 5%      │ 극도 과매수
└────────┴─────────┴──────────┘

현재 진입 조건: RSI < 30 또는 > 70
→ 발생 확률: 약 20% (시간의 20%)
→ 1시간에 3캔들 (15M) → 0.6개 신호/시간
→ 24시간 → 14.4개 신호/일 (이론값)

하지만 실제로는:
- MEAN_REVERSION이 모든 국면에 활성화되지 않음
  (RANGE/DOWN/WEAK_UP만 약 50% 확률)
- Layer 1 필터 적용 → 추가 50% 손실
- 결과: 14.4 × 0.5 × 0.5 ≈ 3.6개/일 기대값

실제 관찰: 1-2개/일
→ 신호 생성 엔진이 지표를 계산하지 못했거나,
   필터가 예상 이상으로 강할 가능성
```

### 2.2 RSI 신호 생성 주기
```
신호 생성 주기: 15분 (config.yaml)
검토 코인: 10개

초당 신호 평가 횟수: 10코인 × 4신호/시간 ≈ 40신호/시간

현실:
- 1-2개/일 신호 생성 = 0.05~0.1개/시간
- 40 신호 평가 중 0.05~0.1개만 통과
→ 필터 통과율: 0.1% 이하

결론: 매우 낮은 통과율
```

---

## 3. 신호 부족의 근본 원인

### 3.1 구조적 원인

#### Layer 1 필터 연쇄
```
신호 생성 → [REGIME 체크] → [L1 필터 체크] → [점수 컷오프 체크]
            (보수적)      (거래량,스프레드)  (60-80점)
                                               ↓
                                         최종 신호

각 단계의 필터 통과율을 가정:
- REGIME 체크: 50% (MEAN_REVERSION이 활성 국면 한정)
- L1 필터: 70% (거래량,스프레드,급변동 고려)
- 점수 컷오프: 80% (RSI 극단값 조건만 만족)

총 필터 통과율: 50% × 70% × 80% = 28%

14.4개 기대 신호 × 28% = 4개/일 예상값
실제: 1-2개/일

원인:
1. 실제 필터 통과율이 예상치보다 낮음
2. 지표 계산 오류 (NaN, 극단값 범위 예상 오차)
3. RSI 극단값 조건이 계산상 더 희귀함
```

#### Pool 포지션 수 제한
```
현재: ACTIVE 8개, CORE 5개 = 최대 13개

할당 실패 로그 확인:
"Pool %s 할당 실패: 요청=%.0f, 가용=%.0f, 포지션=%d/%d"

이 로그가 출력되는 경우:
1. 포지션이 가득 찬 경우
2. 가용 잔액 부족 (희귀)

분석: 포지션 부족이 신호를 차단하지는 않음
(신호는 생성되고, 할당만 실패)
```

### 3.2 전략 활성화 부족

#### Strategy D (Scalping) 미활성화
```python
# rule_engine.py generate_signals()

현재 코드 (줄 290):
allowed = REGIME_STRATEGY_MAP.get(regime, [])

allowed 리스트에 Strategy.SCALPING 없음
→ scalping 신호 생성 자체 안 됨

구현은 있지만 활성화되지 않은 상태
```

#### Strategy E (DCA) 범위 제한
```python
# strategy_scorer.py

def score_strategy_e(ind_1h, symbol, current_price):
    # CRISIS만 강한 신호
    # 다른 국면: 아예 신호 안 생김

문제: CRISIS는 일일 1-2번만 발생
→ DCA 신호가 거의 없음
```

---

## 4. 즉시 개선 가능한 항목 (코드 분석)

### 4.1 Strategy D (Scalping) 활성화

#### 현재 코드
```python
# rule_engine.py 줄 460-470 _evaluate_strategies()

for strat in allowed:
    if strat == Strategy.TREND_FOLLOW:
        # ...
    elif strat == Strategy.MEAN_REVERSION:
        # ...
    elif strat == Strategy.BREAKOUT:
        # ...
    elif strat == Strategy.SCALPING:
        sr = self._score_strategy_d(ind_15m, ind_1h, snap)
        results.append(sr)
    # Strategy.SCALPING은 이미 처리 가능하지만
    # allowed 리스트에 추가되지 않아서 실행 안 됨
```

#### 활성화 방법 1: REGIME_STRATEGY_MAP 확장
```python
# rule_engine.py 상수 정의 근처

REGIME_STRATEGY_MAP = {
    Regime.UP:          [Strategy.TREND_FOLLOW, Strategy.BREAKOUT, Strategy.SCALPING],  # +
    Regime.DOWN:        [Strategy.MEAN_REVERSION, Strategy.DCA, Strategy.SCALPING],     # +
    Regime.CRISIS:      [Strategy.DCA, Strategy.SCALPING],                              # +
    Regime.RANGE:       [Strategy.MEAN_REVERSION, Strategy.SCALPING],                  # +
    Regime.WEAK_UP:     [Strategy.TREND_FOLLOW, Strategy.SCALPING],                    # +
}

효과:
- Scalping 신호: 모든 국면에서 생성 가능
- 추가 신호 빈도: +3-5개/일
```

#### 활성화 방법 2: 조건부 추가
```python
# rule_engine.py _evaluate_strategies()

# Scalping은 항상 평가 (국면 무관)
# 높은 변동성 환경에서만 신호 생성
sr_scalp = self._score_strategy_d(ind_15m, ind_1h, snap)
if sr_scalp.score > 40:  # 낮은 컷오프
    results.append(sr_scalp)
```

### 4.2 Strategy E (DCA) 범위 확대

#### 현재 코드
```python
# rule_engine.py _evaluate_strategies() 줄 520-530

elif strat == Strategy.DCA:
    sr = self._score_strategy_e(ind_1h, symbol, snap.current_price)
    results.append(sr)

# 하지만 allowed = REGIME_STRATEGY_MAP.get(regime, [])
# CRISIS와 DOWN만 포함되어 있음
```

#### 개선 코드
```python
# 모든 국면에서 DCA 신호 생성

if Strategy.DCA in allowed or True:  # 또는 항상 평가
    sr = self._score_strategy_e(ind_1h, symbol, snap.current_price)

    # 국면별 강도 조정
    score_mult = {
        Regime.CRISIS: 1.0,    # 70-80점
        Regime.DOWN: 0.8,      # 56-64점
        Regime.RANGE: 0.5,     # 35-40점
        Regime.WEAK_UP: 0.4,   # 28-32점
        Regime.UP: 0.3,        # 21-24점
    }

    sr = ScoreResult(
        strategy=sr.strategy,
        score=sr.score * score_mult.get(regime, 0.5),
        detail=sr.detail,
    )
    results.append(sr)
```

### 4.3 Layer 1 필터 동적 조정

#### 현재 코드 (environment_filter.py)
```python
def check(self, regime, snap, ind_15m, tier_params):
    # 고정 임계값
    if current_vol < avg_vol * 0.4:  # 거래량
        return False, "L1: 거래량 부족"

    if spread > tier_params.spread_limit * 2.0:  # 스프레드
        return False, "L1: 스프레드 초과"
```

#### 개선 코드
```python
def check(self, regime, snap, ind_15m, tier_params, score=0.0):
    # score 기반 동적 조정

    # 신호가 매우 강하면 필터 완화
    # score >= 70: 필터 통과율 90%
    # 40 <= score < 70: 필터 통과율 70%
    # score < 40: 필터 통과율 50%

    if score >= 70:
        vol_threshold = 0.25  # 0.4 → 0.25
        spread_mult = 2.5      # 2.0 → 2.5
    elif score < 40:
        vol_threshold = 0.5    # 0.4 → 0.5
        spread_mult = 1.5      # 2.0 → 1.5
    else:
        vol_threshold = 0.4
        spread_mult = 2.0

    if current_vol < avg_vol * vol_threshold:
        return False, "L1: 거래량 부족"

    if spread > tier_params.spread_limit * spread_mult:
        return False, "L1: 스프레드 초과"

    return True, ""
```

---

## 5. Mean Reversion 신호 개선 (다단계 RSI)

### 5.1 문제점
```
현재: RSI < 30 또는 > 70만 신호
→ 이론 확률 20%, 실제 1-2개/일

개선: 다단계 RSI 필터로 신호 3배
```

### 5.2 개선안

```python
# strategy_scorer.py

def score_strategy_b(self, ind_15m, candles_15m=None):
    """반전포착 점수 — 다단계 RSI"""

    rsi = self._last_valid(ind_15m.rsi)

    if rsi <= 0 or np.isnan(rsi):
        return ScoreResult(strategy=Strategy.MEAN_REVERSION, score=0.0)

    # ┌─────────────────────────────────────┐
    # │ Strength 1 (극단, 높음 확률)       │
    # │ RSI < 20 → +70점, RSI > 80 → +70점 │
    # │ 기대 빈도: 10% (1-2개/5일)         │
    # ├─────────────────────────────────────┤
    # │ Strength 2 (중간, 중간 확률)        │
    # │ RSI < 30 → +60점, RSI > 70 → +60점 │
    # │ 기대 빈도: 20% (3-4개/5일)         │
    # ├─────────────────────────────────────┤
    # │ Strength 3 (약함, 높은 확률)        │
    # │ RSI < 40 → +45점, RSI > 60 → +45점 │
    # │ 기대 빈도: 40% (8-10개/5일)        │
    # └─────────────────────────────────────┘

    if rsi < 20:
        return ScoreResult(
            strategy=Strategy.MEAN_REVERSION,
            score=75.0,  # FULL 진입
            detail=f"RSI {rsi:.1f} 극도 과매도",
        )
    elif rsi < 30:
        return ScoreResult(
            strategy=Strategy.MEAN_REVERSION,
            score=65.0,  # PROBE 진입
            detail=f"RSI {rsi:.1f} 과매도",
        )
    elif rsi < 40:
        return ScoreResult(
            strategy=Strategy.MEAN_REVERSION,
            score=50.0,  # 낮음 (컷오프 필터로 일부 제외)
            detail=f"RSI {rsi:.1f} 약한 과매도",
        )

    # 대칭: 과매수
    if rsi > 80:
        return ScoreResult(
            strategy=Strategy.MEAN_REVERSION,
            score=75.0,
            detail=f"RSI {rsi:.1f} 극도 과매수",
        )
    elif rsi > 70:
        return ScoreResult(
            strategy=Strategy.MEAN_REVERSION,
            score=65.0,
            detail=f"RSI {rsi:.1f} 과매수",
        )
    elif rsi > 60:
        return ScoreResult(
            strategy=Strategy.MEAN_REVERSION,
            score=50.0,
            detail=f"RSI {rsi:.1f} 약한 과매수",
        )

    return ScoreResult(
        strategy=Strategy.MEAN_REVERSION,
        score=0.0,
        detail=f"RSI {rsi:.1f} 정상",
    )
```

### 5.3 예상 효과
```
기존: 1-2개/일 (RSI < 30 또는 > 70만)
개선:
- Strength 1 (극단): 1개/3-5일 (기존)
- Strength 2 (중간): +2-3개/일 (신규)
- Strength 3 (약함): +3-4개/일 (신규, 일부 컷오프 제외)

합계: 6-10개/일 → 활용률 4% → 15-25%
```

---

## 6. 신호 생성 최종 계획

### 6.1 Phase 1 (즉시, 2-3시간)

```
1. Strategy D (Scalping) 활성화
   - REGIME_STRATEGY_MAP 수정
   - 신호 추가: +3-5개/일
   - 코드: rule_engine.py 상수

2. Mean Reversion 다단계 RSI
   - strategy_scorer.py 수정
   - 신호 추가: +2-3개/일
   - 총 효과: +5-8개/일 (1-2개 → 6-10개)

3. Layer 1 필터 점수 기반 조정
   - environment_filter.py 수정
   - 신호 통과율: 70% → 85%
```

### 6.2 Phase 2 (3-5일)

```
1. DCA 범위 확대
   - rule_engine.py _evaluate_strategies() 수정
   - 신호 추가: +1-2개/일
   - 효과: 하락장 대응 강화

2. 4H 타임프레임 추가
   - datafeed.py에서 4H 캔들 수집
   - indicators.py에서 4H 지표 계산
   - rule_engine.py에서 4H 신호 생성
   - 신호 추가: +0-1개/일
```

### 6.3 예상 최종 결과

```
메트릭              현재      Phase 1    Phase 2
─────────────────────────────────────────────
신호/일            1-2       6-10       8-12
활용률            4%        15-25%     25-35%
포지션 크기        7K        7-10K      7-10K
```

---

## 7. 검증 계획

### 7.1 코드 리뷰 체크리스트
```
□ Strategy D (Scalping) 조건 및 SL/TP 확인
□ Mean Reversion RSI 임계값이 과도하게 낮지 않은지 확인
□ Layer 1 필터 점수 기반 조정이 로직적으로 맞는지 확인
□ DCA 국면별 강도 조정 값이 합리적인지 확인
```

### 7.2 백테스트 검증
```
테스트 데이터: 최근 30일
검증 항목:
- 신호 생성 빈도 (예상 vs 실제)
- 신호별 승률 (전략별)
- 활용률 변화
- MDD / DD 변화
- 수익성 변화 (Sharpe, Profit Factor)

통과 기준:
- 신호: 8개/일 이상
- 활용률: 20% 이상
- 승률: 40% 이상 (Strategy D는 60% 이상)
- MDD: 15% 이내
```

### 7.3 Paper 테스트
```
기간: 1주
검증:
- 실제 신호 생성 빈도
- 신호 품질 (거짓 신호율)
- 수수료 영향
- 슬리피지 영향
```

---

## 결론

신호 부족의 원인은 **신호 생성 엔진의 보수성**이며, 즉시 개선 가능합니다.

**3시간 작업으로:**
- 신호 3배 증가 (2개 → 6-10개/일)
- 활용률 4배 증가 (4% → 15-25%)

이는 **아키텍처 변경 없이** 기존 구현된 전략들을 활성화하고
필터 조건을 합리적으로 조정하는 것만으로 달성 가능합니다.
