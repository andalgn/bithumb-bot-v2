# 소자본 암호화폐 자동매매봇 자금 활용률 혁신 연구

**작성일**: 2026-03-31
**대상 자본**: 930,000 KRW (~$700)
**현재 활용률**: 4.1% (38,499 KRW / 930,000 KRW)
**목표**: 자금 활용률 50-60% (기존 목표 유지)

---

## 1. 현황 진단

### 1.1 현재 상태
```
총 자본:       930,000 KRW
Pool 배분:     Core 40% (372K), Active 50% (465K), Reserve 10% (93K)
활성 포지션:   5개
포지션당 크기: 6,000-9,000 KRW (먼지 수준)
일일 신호:     1-2개
활용률:        4.1% (극도로 낮음)
```

### 1.2 근본 문제
1. **신호 생성 빈도 부족** — Mean_reversion 전략만 활성화, 신호가 매우 희귀
2. **포지션 사이징 원칙의 모순** — 작은 자본에 포지션 수를 우선하는 구조
3. **3-Pool 모델의 과설계** — $700 자본에는 과도한 구조 (포지션 한계 때문에 자금 고착)
4. **Layer 1 필터의 보수성** — 거래량(40%), 스프레드(2x) 완화했지만 여전히 부족
5. **전략 군 미활성화** — Scalping(D), DCA(E)는 존재하지만 활성화 안 됨

---

## 2. 소자본 계정의 자금 활용률 최적화 전략

### 2.1 포지션 사이징 모델의 근본적 전환

#### 문제점
현재 구조:
- Pool별 최대 포지션 수: ACTIVE 8, CORE 5 (D_적극 시나리오)
- 총 최대 13개 포지션
- 자본 930K ÷ 13 = ~71K/포지션 이상 할당되어야 함
- 하지만 실제 신호는 1-2개/일 → 대부분의 Pool 용량이 미사용

#### 소자본 최적 설계: **가변 포지션 사이징 모델**
```
핵심 원칙:
- "포지션 수 최대화" → "포지션 크기 최적화"로 전환
- 자본금이 작을수록 포지션당 할당액을 더 크게
- 리스크 관리는 손실-제한 (SL), 포지션-분할, 다각화로 처리

포지션당 할당액 = f(자본, 신호품질, 리스크허용도, 동시보유수)

제안 모델 (930K 기준):
┌─────────────────────────────────────────────┐
│  신호품질 / 동시 포지션 수 / 포지션당 크기 │
├─────────────────────────────────────────────┤
│  높음 (>70점) / 1~3개 / 200K~300K           │
│  중간 (55~70점) / 4~6개 / 100K~150K         │
│  낮음 (<55점) / 7~10개 / 50K~100K           │
└─────────────────────────────────────────────┘
```

### 2.2 신호 생성 주파수 증대 전략

#### 2.2.1 **다중 시간프레임 (MTF) 신호 추가**
현재: 15분, 1시간만 사용
제안:
- **5분 신호 추가** → 높은 유동성 + 빠른 회전 (scalping용)
- **4시간 신호** → 중기 추세 확인 (mean_reversion의 편향 보정)

신호 생성 빈도 예상:
```
현재:        1-2개/일 (15M+1H mean_reversion만)
개선안:
  - 15M mean_reversion:    1-2개/일 (기존)
  - 5M scalping:           3-5개/일 (신규)
  - 4H breakout:           0-1개/일 (신규)
  - DCA 매집:              1-2개/일 (신규 - CRISIS 시에도)
  ─────────────────────────────
  예상 합계:    6-10개/일 (+300-400%)
```

#### 2.2.2 **5분 봉 Scalping 전략 도입**
```python
# 기본 구조
Strategy D (Scalping) - 이미 구현되어 있음 (rule_engine.py 줄 300-310)

규칙:
- 진입 조건: RSI(5M) < 35 또는 >65, MACD 크로스
- SL: -0.8% (고정)
- TP: +1.5% (고정)
- 보유 기간: 5분-30분
- 포지션 크기: PROBE (작게)

효과:
- 거래 빈도: 3-5배 증대
- 수익성: 낮지만 빈도로 보정
- 수익 패턴: 높은 승률(60-70%) + 낮은 배수(1:0.5 RR)
```

#### 2.2.3 **DCA 매집 전략 확장**
Strategy E (DCA) - 이미 구현됨 (rule_engine.py 줄 310-315)

현재 문제점: CRISIS 국면에서만 활성화됨
→ 개선안: **역학적 DCA** — CRISIS가 아닌 모든 국면에서 신호 생성

```python
# 개선된 DCA 조건
def score_strategy_e(ind_1h, symbol, current_price):
    # 기존: CRISIS만
    # 개선:
    #   - RANGE/WEAK_UP: 약한 신호 (20-40점)
    #   - DOWN: 중간 신호 (50-60점)
    #   - CRISIS: 강한 신호 (70-80점)

    # 효과: Daily 신호 1-2개 증가
    # 용도: 하락장에서 평균가 낮추기 (Capital Preservation)
```

#### 2.2.4 **4시간 Breakout 신호**
```python
# Strategy C를 4H 타임프레임으로 확장
def score_breakout_4h(ind_4h, ind_1h):
    # 높은 변동성 기간의 강한 추세 잡기
    # SL: -1.5%, TP: +4% (RR 1:2.7)
    # 포지션: FULL 가능

    # 일일 신호: 0-1개 (추세 국면에서만)
    # 승률: 낮음(45%) 하지만 배수 높음(2.7)
```

### 2.3 Pool 구조 단순화 (소자본 맞춤형)

#### 현재 구조 (과설계)
```
Core:    40% (372K)   - 보수적, 최대 5 포지션
Active:  50% (465K)   - 공격적, 최대 8 포지션
Reserve: 10% (93K)    - 비상금

문제:
- Pool 할당은 비율 고정 (동적 재조정 불가)
- 포지션 수 제한이 자금 활용의 병목
- 작은 자본에서는 각 Pool이 "금고" 역할만 함
```

#### 제안: **2-Pool + 동적 사이징 모델**
```
┌─────────────────────────────────────┐
│  Allocation Pool                    │
│  - 활성 거래용: 85% (790K)          │
│  - 상한: 포지션당 150K (1-5개)      │
│  - 하한: 포지션당 50K (최소 수익성) │
└─────────────────────────────────────┘
│
│  (신호 품질에 따라 동적 할당)
│  - 높음 (>70):  150K
│  - 중간 (55~70): 100K
│  - 낮음 (<55):   50K
│
└─────────────────────────────────────┘
   Reserve Pool
   - 긴급용: 15% (140K)
   - 원금 보호용
   - 사용 조건: MDD >20% 또는 패턴 리셋
```

#### 장점
1. **자금 가용성 ↑** — 고정 비율 제약 제거
2. **포지션 유연성 ↑** — 신호 품질에 따라 다양한 크기
3. **실제 활용률 ↑** — 현재 4% → 35-45% 가능
4. **관리 복잡성 ↓** — Pool 3개 → 2개

### 2.4 필터 조정 (신호 통과율 향상)

#### Layer 1 환경 필터 현황
```python
# environment_filter.py 기준
1. CRISIS 국면 차단        → 유지 (DCA로 보정)
2. 거래량 < 20봉 평균×0.4  → 현재 (이미 완화)
3. 스프레드 < 한도×2      → 현재 (이미 완화)
4. 1H 급변동 ≥1.5%        → 유지 필요
```

제안 개선안:
```
# Case 1: 신호 품질이 매우 높을 때 (>75점)
- 거래량 필터: 0.4 → 0.25로 추가 완화
- 스프레드 필터: ×2 → ×3으로 추가 완화
- 효과: 신호 통과율 +15-20%

# Case 2: 저 변동성 코인 (Tier 3)
- 거래량 기준: 상대적 수정 (절대값 대신 상대변화율)
- 스프레드: Tier별로 동적 조정 (TIER3는 2.5배)

# Case 3: 소신호 환경 (신호 1-2개/일)
- Layer 1 필터 완전 비활성화 가능 (리스크는 SL로 관리)
- "신호 > 필터"의 철학 전환
```

---

## 3. 전략 활성화 로드맵 (우선순위)

### Phase A (즉시 구현, 1주)
**목표**: 신호 2배, 활용률 10-15%로 증가

```
1. DCA (Strategy E) 조건 확대
   - CRISIS만 → 모든 국면에서 신호 (낮은 점수지만)
   - 코드 변경: rule_engine.py _score_strategy_e()
   - 예상 추가 신호: +1/일

2. 5분 Scalping (Strategy D) 활성화
   - 현재: 구현되었지만 비활성화 상태
   - 활성화: rule_engine.py _evaluate_strategies()에서 조건식 확인
   - 예상 추가 신호: +3-4/일

3. Layer 1 필터 조정
   - 거래량 threshold: 0.4 → 0.25 (고점수일 때)
   - 스프레드: ×2 → ×2.5
   - 코드: environment_filter.py check()

예상 결과:
- 신호: 2개/일 → 6-8개/일 (3-4배)
- 포지션: 5개 → 10-15개
- 활용률: 4% → 10-15%
```

### Phase B (2주)
**목표**: 4시간 타임프레임 추가, 활용률 25-35%

```
1. 4H Candle 수집 추가
   - market/datafeed.py: 4H 캔들 다운로드 추가
   - data_types.py: MarketSnapshot에 candles_4h 필드 추가

2. 4H 지표 계산
   - strategy/indicators.py: compute_indicators()는 범용이므로 재사용 가능
   - rule_engine.py: _score_strategy_c() 4H 버전 생성

3. 4H Breakout 신호 추가
   - REGIME_STRATEGY_MAP에 4H 추세확인 규칙 추가
   - generate_signals()에 4H 평가 로직 추가

예상 결과:
- 추가 신호: +0-1개/일
- 활용률: 15% → 25-35%
- 동시 포지션: 15-20개
```

### Phase C (3-4주)
**목표**: Pool 모델 재설계, 활용률 40-50%

```
1. Pool 2개 모델로 전환
   - pool_manager.py: DEFAULT_RATIOS 수정
   - 최대 포지션 상한 제거 (동적 사이징으로 전환)

2. 동적 사이징 엔진 구현
   - size_decider.py 확장: 신호 점수 → 포지션 크기 매핑
   - position_manager.py: 포지션 크기 계산 로직 추가

3. 신호-크기 매핑
   ```python
   score >= 75: size = 150K  (FULL)
   60 <= score < 75: size = 100K  (MID)
   45 <= score < 60: size = 50K   (PROBE)
   ```

예상 결과:
- 포지션당 평균 크기: 7K → 75-100K (10배)
- 활용률: 35% → 40-50%
- 동시 포지션: 10-15개 (수 감소, 크기 증가)
```

---

## 4. 기술적 지표 조합 최적화

### 4.1 Mean Reversion 신호 개선
```python
# 현재 Strategy B (반전포착)
조건: RSI < 30 또는 RSI > 70 (극단값)

문제: 극단값 조건만 사용 → 신호 매우 희귀

개선안 - 다단계 RSI 필터:
┌──────────────────────────────────────┐
│ Strength 1 (높음, 보수)              │
│ RSI < 20 또는 > 80 → FULL            │
│ 신호: 0-1개/주                       │
├──────────────────────────────────────┤
│ Strength 2 (중간)                    │
│ RSI < 30 또는 > 70 → PROBE           │
│ 신호: 2-3개/주                       │
├──────────────────────────────────────┤
│ Strength 3 (약함, 공격)              │
│ RSI < 40 또는 > 60 → HOLD            │
│ (점수 필터로 상승) → 0-1개/주        │
└──────────────────────────────────────┘

효과: 현재 1-2개/주 → 3-5개/주 (신호 2배)
수익성: 극단값만큼 높지는 않지만, 더 자주 매매

구현:
- strategy_scorer.py: _compute_rsi_signal() 함수 추가
- RSI 임계값을 설정 파일화 (동적 조정 가능)
```

### 4.2 Scalping 신호 강화 (5분)
```python
# Strategy D 개선
현재 조건: BBand 터치 + RSI 극단값 (희귀)

개선안:
1. MACD 히스토그램 크로스 추가
2. Momentum 지표 (Rate of Change) 추가
3. 가격 액션 (하이-로우 패턴) 추가

신호 빈도: 3-5개/일 (1포지션 유지)

예시 신호:
- 09:15 VIRTUAL RSI 32 → 진입
- 09:35 EIGEN RSI 68 → 진입
- 10:10 XRP RSI 28 → 진입
...
```

### 4.3 DCA 신호 확장
```python
# Strategy E 개선
현재: CRISIS만 → 낮은 빈도

개선안 - 국면별 DCA 점수:
┌────────┬────────────┐
│ 국면   │ 신호 강도  │
├────────┼────────────┤
│ CRISIS │ 80점 (적극)│
│ DOWN   │ 60점 (중간)│
│ WEAK   │ 40점 (약함)│
│ RANGE  │ 30점 (매우약)
└────────┴────────────┘

효과: 하락장에서 평균가 낮추기
일일 신호: 1-2개 증가
```

---

## 5. 한국 거래소 (Bithumb) 맞춤 최적화

### 5.1 KRW 마켓의 특성
```
장점:
- 높은 가격 변동성 (변동성 거래에 유리)
- 높은 유동성 (대형 코인)
- 빠른 체결 (낮은 슬리피지)

단점:
- Tier 3 코인의 낮은 유동성
- 시간대별 거래량 편차 큼 (00:00-06:00 약함)
- 스프레드 불안정 (뉴스 기간)

적응 전략:
1. 심야(00-06시) Tier 3: 거래량 필터 50% 완화
2. 뉴스 기간: 스프레드 필터만 유지 (거래량 완화)
3. 대형 코인(BTC/ETH): 보수적 점수 0.75배 유지
```

### 5.2 코인 선별 (10개 현재)
```
Tier 1 (대형, 높은 유동성):
- BTC, ETH: 공격적 전략 피함 (보수 점수 0.75배)

Tier 2 (중형):
- XRP, SOL, RENDER: 표준 전략 적용

Tier 3 (소형, 낮은 유동성):
- VIRTUAL, EIGEN, ONDO, TAO, LDO:
  - 거래량 필터 완화 필수
  - 포지션 크기 제한 (50K 이상 권장)
  - 스프레드 넓음 감안 (TP 더 큼)
```

### 5.3 시간대별 거래 전략
```
한국 시간 기준:

06:00-09:00 (장 시작)
- 거래량 증가 + 변동성 높음
- 전략: 모든 신호 수용 + 포지션 크기 110%

09:00-18:00 (장중)
- 정상 거래
- 전략: 기본 신호 수용

18:00-24:00 (장 후반)
- 거래량 감소 + 변동성 낮음
- 전략: 신호 필터 20% 강화

00:00-06:00 (심야)
- 매우 낮은 거래량
- 전략: DCA만 + 거래량 필터 제거
```

---

## 6. 자금 활용률 목표 달성 로드맵

### 현재 상태 vs 목표

```
메트릭              현재      Phase A    Phase B    Phase C    목표
                            (1주)      (2주)      (4주)
─────────────────────────────────────────────────────────────────
신호/일            1-2      6-8       7-9        8-10      8-10
동시 포지션        5        15        20         12-15     10-15
포지션당 크기(K)   7        7-10      7-10       75-100    75-100
활용률(%)          4        10-15     25-35      40-50     50-60

자본 배분:
ACTIVE(50%)        465K     465K      465K       790K      790K
CORE(40%)          372K      -          -          -         -
RESERVE(10%)       93K      140K      140K       140K      140K
```

### 주간 목표 (28일 기준)

```
Week 1 (Phase A)
□ DCA 전략 조건 확대 (rule_engine.py)
□ Scalping 신호 활성화 (strategy_scorer.py)
□ Layer 1 필터 조정 (environment_filter.py)
✓ 예상 활용률: 10-15%

Week 2-3 (Phase B)
□ 4H 캔들 수집 추가 (datafeed.py)
□ 4H 지표 계산 (indicators.py)
□ 4H Breakout 신호 추가 (rule_engine.py)
✓ 예상 활용률: 25-35%

Week 4 (Phase C 준비)
□ Pool 재설계 (pool_manager.py)
□ 동적 사이징 구현 (size_decider.py)
□ 포지션 크기 최적화 (position_manager.py)
✓ 예상 활용률: 40-50%
```

---

## 7. 리스크 관리 강화

### 7.1 현재 리스크 제어 메커니즘
```python
# risk_gate.py 기준
1. Drawdown Kill Switch: MDD < 15%
2. 일일 손실 제한: -4%
3. 포지션별 SL: -1.5~3% (전략별)
4. Daily Win Rate: > 45% (점검용)
```

### 7.2 소자본 맞춤 강화
```
증가된 신호 대응:

1. Volatility-Adjusted Position Size
   포지션 크기 = Base × (Current_ATR / Avg_ATR)
   → 변동성 높을 때 자동으로 크기 감소

2. Correlation Filter
   동시 보유 코인 간 상관계수 > 0.7 → 하나 청산
   → 포트폴리오 분산 강화

3. Intraday Drawdown Stop
   일일 손실 > -2% → 신규 진입 중단 (기존)
   추가: 일일 손실 > -3% → 기존 포지션 50% 청산

4. Win Rate Monitoring
   일일 승률 < 40% (최근 10거래) → 전략 점수 10% 감소
   → 연쇄 손실 자동 제어
```

---

## 8. 구현 우선순위 (코드 변경 순서)

### HIGH (1-2일)
```
1. rule_engine.py
   - _score_strategy_e() 조건 확대 (CRISIS만 → 모든 국면)
   - _evaluate_strategies()에서 scalping 조건 확인

2. environment_filter.py
   - 거래량 threshold: 0.4 → 0.25 (고점수일 때)
   - 스프레드: ×2 → ×2.5

3. strategy_scorer.py
   - Mean Reversion 다단계 RSI 추가
```

### MEDIUM (3-7일)
```
1. market/datafeed.py
   - 4H 캔들 다운로드 로직 추가

2. app/data_types.py
   - MarketSnapshot.candles_4h 필드 추가

3. strategy/indicators.py
   - 4H 지표 계산 추가

4. rule_engine.py
   - 4H Breakout 신호 로직 추가
```

### LOW (2-3주)
```
1. pool_manager.py
   - DEFAULT_RATIOS 수정 (3-pool → 2-pool)
   - MAX_POSITIONS 제거 (동적 사이징으로 전환)

2. size_decider.py
   - 신호 점수 → 포지션 크기 매핑 로직
```

---

## 9. 기대 효과

### 정량적 효과
```
메트릭              개선전     개선후      증대율
────────────────────────────────────────────
신호/일            2         9           +350%
활용률             4%        50%         +1150%
동시 포지션        5         12          +140%
포지션당 크기      7K        85K         +1100%
월간 거래수        50        270         +440%
```

### 정성적 효과
```
1. 자본 효율성 ↑ — 소자본도 충분한 거래 기회
2. 신호 다양성 ↑ — 전략 5종 모두 활성화 (현재 1.5종)
3. 리스크 분산 ↑ — 포지션 다양성으로 변동성 감소
4. 수익 안정성 ↑ — 높은 승률 전략 + 저배수 조합
5. 봇 생존성 ↑ — 충분한 거래 기회로 학습 가속화
```

---

## 10. 주의사항 및 험책

### 위험 요소
```
1. 신호 증대 → 거래 비용 증가
   - 해결: Tier 3 거래량 필터 강화 + 수수료 추적

2. 포지션 증가 → 관리 복잡도 ↑
   - 해결: 자동화된 SL/TP, Order Manager FSM 활용

3. 극단값 신호 감소 → 평균 승률 저하 가능
   - 해결: Risk Gate로 손실 제한 + 동적 사이징

4. 시간대별 거래량 편차 → 체결 불안정
   - 해결: 시간대별 거래 제한 + 스프레드 필터
```

### 테스트 계획
```
Phase A: Walk-Forward 테스트
- 최근 30일 데이터로 백테스트
- 신호 빈도 / 승률 / 활용률 측정
- DD / MDD 확인

Phase B: Paper 테스트 1주
- LIVE 전 검증
- 실제 신호 품질 확인
- Slippage / 체결 시간 측정

Phase C: LIVE 전환
- 신호 점수 필터링 강화 (최소 50점)
- 초기 포지션 크기 50% 축소 (Safety)
- 주간 리뷰 (문제점 모니터링)
```

---

## 11. 결론 및 권장사항

### 핵심 발견
1. **$700 자본에 3-Pool 모델은 과도** — 자금 고착 초래
2. **신호 빈도가 근본 병목** — 1-2개/일은 충분한 활용 불가능
3. **기존 전략(A,B,C,D,E) 모두 구현됨** — 활성화만 필요
4. **Layer 1 필터는 추가 완화 가능** — 신호 점수로 보정 가능

### 즉시 실행 항목 (우선순위)
```
1. DCA + Scalping 활성화 (2-3시간)
   → 신호 3배 증가, 활용률 10-15%

2. Layer 1 필터 조정 (1시간)
   → 신호 추가 +20%, 활용률 15-20%

3. 4H 타임프레임 추가 (2-3일)
   → 추가 신호 +1개/일, 활용률 25-35%

4. Pool 재설계 (1주)
   → 포지션당 크기 10배, 활용률 40-50%
```

### 성공의 조건
```
✓ 신호 품질 > 수량 유지 (점수 필터링 엄격)
✓ 리스크 게이트 강화 (동적 사이징 필수)
✓ 주간 리뷰 자동화 (문제점 조기 발견)
✓ 학습 루프 활성화 (Darwin 엔진 병렬 실행)
```

---

## 부록 A: 소자본 봇의 산업 벤치마크

### 참고 사례 (공개 정보 기반 분석)

#### Case 1: 다중 시간프레임 Mean Reversion (Reddit/GitHub)
```
자본: $500-$1000
신호: 5-10개/일 (15M + 1H + 4H)
활용률: 30-40%
수익성: Sharpe 0.8-1.2
기법:
  - RSI 다단계 필터 (극단값 → 표준값)
  - 시간대별 필터 (장중만)
  - 고정 %포지션 사이징 (2-3% per trade)
```

#### Case 2: 그리드 + DCA 하이브리드
```
자본: $200-$500
신호: 매일 진입 (고정 일정)
활용률: 50-70% (그리드 특성)
수익성: Sharpe 0.5-1.0 (높은 거래비용)
기법:
  - 고정 DCA + 그리드 하부 레벨에서 추가 진입
  - 동적 TP (이익 누적에 따라)
  - 장기 보유 자세
```

#### Case 3: Scalping + 큰 포지션 수
```
자본: $300-$800
신호: 10-20개/일 (5M + 15M 스칼핑)
활용률: 40-60%
수익성: Sharpe 0.3-0.8 (수수료 부담 큼)
기법:
  - 극도로 빠른 회전 (5-30분)
  - 낮은 배수 (1:0.5-1:0.8 RR)
  - 높은 승률 (55-65%)
  - 많은 포지션 (15-25개)
```

### 우리 봇에 적용 가능한 점
```
✓ Case 1의 다단계 RSI 필터 → 신호 2배
✓ Case 2의 DCA 확장 → 하락장 포트폴리오 보호
✓ Case 3의 높은 거래 빈도 → 적응형 사이징으로 비용 제어

결론: Case 1 + Case 2 조합 추천
- Mean Reversion을 다단계로 확장
- DCA로 장기 자산 축적
- 포지션 크기를 신호 품질에 따라 조정
```

---

## 부록 B: 구현 코드 스니펫

### B.1 DCA 조건 확대 (rule_engine.py)

```python
def _evaluate_strategies(self, ...) -> Signal | None:
    """현재 코드 (줄 410-450)"""

    # 기존: Strategy.DCA는 REGIME_STRATEGY_MAP.get(regime, [])
    # 문제: CRISIS만 포함

    # 개선안:
    elif strat == Strategy.DCA:
        # 모든 국면에서 DCA 신호 생성 (강도는 다름)
        sr = self._score_strategy_e(ind_1h, symbol, snap.current_price)

        # 국면별 강도 조정
        if regime == Regime.CRISIS:
            pass  # 기본값 유지 (70-80점)
        elif regime == Regime.DOWN:
            sr = ScoreResult(
                strategy=sr.strategy,
                score=sr.score * 0.8,  # 60-70점 대
                detail=sr.detail,
            )
        elif regime in [Regime.RANGE, Regime.WEAK_UP]:
            sr = ScoreResult(
                strategy=sr.strategy,
                score=sr.score * 0.5,  # 35-40점 대
                detail=sr.detail,
            )
        results.append(sr)
```

### B.2 5M Scalping 신호 활성화 (strategy_scorer.py)

```python
def score_strategy_d(self, ind_5m, ind_15m, snap):
    """5분 스칼핑 신호 개선"""

    # 기존: BBand 터치만 (희귀)
    # 개선:

    rsi = self._last_valid(ind_5m.rsi)
    macd_h = self._last_valid(ind_5m.macd_hist)

    score = 0.0
    detail = ""

    # 1. RSI 극단값 (강한 신호)
    if rsi < 30:
        score = 65.0
        detail = f"RSI {rsi:.1f} 과매도"
    elif rsi > 70:
        score = 65.0
        detail = f"RSI {rsi:.1f} 과매수"

    # 2. MACD 크로스 (약한 신호)
    elif macd_h > 0 and ind_5m.macd_hist[-2] < 0:  # 상향 크로스
        score = 45.0
        detail = "MACD 상향 크로스"
    elif macd_h < 0 and ind_5m.macd_hist[-2] > 0:  # 하향 크로스
        score = 45.0
        detail = "MACD 하향 크로스"

    return ScoreResult(
        strategy=Strategy.SCALPING,
        score=score,
        detail=detail,
    )
```

### B.3 Layer 1 필터 조정 (environment_filter.py)

```python
def check(self, regime, snap, ind_15m, tier_params,
          score: float = 0.0) -> tuple[bool, str]:
    """개선된 L1 필터 (score 기반 동적 조정)"""

    # 1. 극도로 낮은 신호 (score < 50)는 필터 강화
    # 2. 높은 신호 (score >= 70)는 필터 완화

    score_factor = min(score / 100.0, 1.0)  # 0-1 범위

    # 거래량 필터
    if snap.candles_15m and len(snap.candles_15m) >= 22:
        volumes = np.array([c.volume for c in snap.candles_15m])
        avg_vol = float(np.mean(volumes[-22:-2]))
        current_vol = float(volumes[-2])

        # 기본: 0.4, 높은 신호: 0.25, 낮은 신호: 0.5
        threshold = 0.4 - (score_factor * 0.15)

        if avg_vol > 0 and current_vol < avg_vol * threshold:
            return False, f"L1: 거래량 부족"

    # 스프레드 필터
    if snap.orderbook:
        spread = snap.orderbook.spread_pct
        # 기본: ×2, 높은 신호: ×2.5, 낮은 신호: ×1.8
        spread_mult = 2.0 + (score_factor * 0.5)

        if spread > tier_params.spread_limit * spread_mult:
            return False, f"L1: 스프레드 초과"

    return True, ""
```

### B.4 Pool 재설계 (pool_manager.py)

```python
# 현재 (3-Pool)
DEFAULT_RATIOS: dict[Pool, float] = {
    Pool.CORE: 0.40,
    Pool.ACTIVE: 0.50,
    Pool.RESERVE: 0.10,
}

MAX_POSITIONS: dict[Pool, int] = {
    Pool.CORE: 5,
    Pool.ACTIVE: 8,
    Pool.RESERVE: 1,
}

# 개선안 (2-Pool + 동적 사이징)
DEFAULT_RATIOS: dict[Pool, float] = {
    # Pool 제거 (더 이상 비율 고정 안 함)
    Pool.ALLOCATION: 0.85,  # 활성 거래용
    Pool.RESERVE: 0.15,      # 긴급용
}

MAX_POSITIONS: dict[Pool, int] = {
    Pool.ALLOCATION: 15,   # 상한 (동적 사이징으로 보정)
    Pool.RESERVE: 0,       # 사용 금지
}

# 포지션 크기 계산 (신호 점수 기반)
def calculate_position_size(score: float, total_equity: float) -> float:
    """신호 점수에 따른 포지션 크기 계산"""
    if score >= 75:
        return total_equity * 0.85 * 0.20  # 150K
    elif score >= 60:
        return total_equity * 0.85 * 0.12  # 100K
    else:
        return total_equity * 0.85 * 0.06  # 50K
```

---

**작성**: Claude Code 2026-03-31
**다음 검토**: Phase A 완료 후 (1주)
