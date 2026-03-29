# Self-Evolution Architecture — 자율 진화 시스템 설계서

**작성일:** 2026-03-29
**목적:** Karpathy Auto Research 원칙 기반, 트레이딩 봇 자율 진화 아키텍처 설계
**상태:** 리서치 완료, 구현 대기

---

## 1. 왜 현재 시스템이 부족한가

### 1.1 현재 자가 진화 범위

봇의 "DNA" 중 자율적으로 변경 가능한 부분은 **25~35%**에 불과하다.

**변경 가능 (12개 파라미터):**

| 전략 | 파라미터 | 범위 |
|------|---------|------|
| TREND_FOLLOW | sl_mult | 1.0~5.0 |
| TREND_FOLLOW | tp_rr | 1.0~5.0 |
| TREND_FOLLOW | cutoff_full | 55~90 |
| TREND_FOLLOW | w_trend_align | 0~45 |
| TREND_FOLLOW | w_macd | 0~40 |
| TREND_FOLLOW | w_volume | 0~35 |
| TREND_FOLLOW | w_rsi_pullback | 0~30 |
| TREND_FOLLOW | w_supertrend | 0~25 |
| MEAN_REVERSION | sl_mult | 2.0~10.0 |
| MEAN_REVERSION | tp_rr | 1.0~4.0 |
| DCA | sl_pct | 0.02~0.08 |
| DCA | tp_pct | 0.01~0.05 |

**영구 고정 (65~75%):**
- 전략 아키텍처 (5개 전략 종류 자체)
- 지표 계산 (RSI, MACD, ATR, BB, SuperTrend 공식)
- 국면 분류 로직 (EMA 정렬 + ADX 규칙의 임계값)
- 리스크 게이트 임계값 (DD 한도, 격리 규칙, 쿨다운)
- 사이징 프레임워크 (풀 비율, 방어 배수 범위)
- 체결 로직 (FSM, 타임아웃, 부분청산 트리거)
- 승격/강등 규칙 (수익률 기준, 보유 기간)
- 환경 필터 조건 (거래량 비율, 모멘텀 버스트 임계값)
- 수수료/슬리피지 모델

### 1.2 핵심 문제

| 문제 | 설명 |
|------|------|
| **범위가 좁다** | 봇 행동을 결정하는 수십 개 파라미터 중 12개만 진화 가능 |
| **속도가 느리다** | 주 1회, 최대 1개 파라미터셋만 적용 |
| **피드백이 끊겨있다** | FeedbackLoop이 가설을 생성하지만 로그만 남기고 자동 적용하지 않음 |
| **통합 관장자가 없다** | Darwin, AutoResearch, FeedbackLoop, Optimizer가 독립적으로 동작 |

---

## 2. Karpathy Auto Research 핵심 원칙

Andrej Karpathy의 Auto Research (2026년 3월 공개)는 AI 에이전트가 자율적으로
코드를 수정하고, 실험하고, 결과를 평가하여 시스템을 개선하는 프레임워크이다.

### 2.1 3개 파일 아키텍처

| 파일 | 역할 | 수정 권한 |
|------|------|----------|
| `prepare.py` | 고정 인프라 (데이터 로더, 평가 함수) | 수정 금지 (immutable) |
| `train.py` | 에이전트가 수정하는 코드 (모델, 옵티마이저, 하이퍼파라미터) | 에이전트 전용 |
| `program.md` | 인간이 작성하는 지침서 (목표, 제약, 방향) | 인간 전용 |

### 2.2 실험 루프

```
1. 코드 수정 (train.py)
2. 5분간 학습 실행
3. val_bpb (평가 지표) 측정
4. 이전보다 나으면 → git commit (keep)
   이전보다 나쁘면 → git reset (revert)
5. 1번으로 돌아가 반복
```

- 단일 GPU로 하룻밤 ~100회 실험 가능
- 16 GPU 병렬 시 8시간에 ~910회 실험, 9배 속도

### 2.3 6가지 핵심 설계 결정

| 결정 | 이유 | 트레이드오프 |
|------|------|-------------|
| **단일 파일 수정** | 에이전트가 전체 시스템을 한 눈에 봄. 변경 리뷰 용이 | 대규모 코드베이스에 비확장적 |
| **고정 시간 예산 (5분)** | 하드웨어 독립적 비교 가능. 시간당 12회 실험 | 깊은 변경에는 부족할 수 있음 |
| **단일 평가 지표** | 비교가 명확 (더 낮으면 더 나음) | 단일 지표 과적합 위험 |
| **Git 상태 관리** | 저렴한 되돌리기, 명확한 이력 | 메모리 체크포인트보다 느림 |
| **불변 평가 함수** | 에이전트가 지표 자체를 속이는 것 방지 | 초기 지표 설계를 신뢰해야 함 |
| **마크다운 지침** | 서사적 + 제약 + 추론을 자연어로 | 구조화 어려움 |

### 2.4 왜 Keep/Revert 루프가 효과적인가

- 단순 랜덤 서치가 아님 — 실패에서 학습하고, 다른 최적화 축으로 전환 가능
- **제안 품질이 속도보다 중요** — 67% 채택률(느리고 좋은 제안)이 17%(빠르고 나쁜 제안)을 압도
- 20개 작은 개선 누적 = 11-13% 총 성능 향상
- 서로 다른 LLM 에이전트가 동일 해에 수렴 → 실제 최적값 발견, 노이즈가 아님

---

## 3. 리서치에서 발견한 핵심 인사이트

### 3.1 트레이딩 도메인 적합성

Auto Research 패턴이 적용되려면 5가지 요건이 필요하다:

| 요건 | 이 봇에서 | 상태 |
|------|----------|------|
| 측정 가능한 목표 | Sharpe, PF, MDD | 충족 |
| 자동화된 평가 | 백테스트 1~5분/회 | 충족 |
| 수정 가능한 산출물 | strategy_params | 충족 |
| 되돌릴 수 있는 변경 | git + config 백업 | 충족 |
| 빠른 피드백 | 5~10분/회 백테스트 | 충족 (이상적 <30분) |

### 3.2 Centaur 방식: LLM + 고전적 최적화

리서치의 핵심 발견:

> "제약된 하이퍼파라미터 공간에서는 CMA-ES와 TPE가 LLM 기반 접근을 압도한다.
> 그러나 비제약 코드 수정 공간에서는 LLM이 격차를 상당히 좁힌다."

> "0.8B 모델 + CMA-ES > 27B 모델 단독"

**결론:** LLM과 고전적 최적화를 대체 관계로 보지 말고 결합해야 한다.

- **LLM의 역할**: "어디를 탐색할지" 방향 제시 (창의적 가설 생성)
- **고전적 최적화의 역할**: "그 방향에서 최적값 찾기" (그리드 서치, 베이지안)

현재 봇에는 이미 AutoOptimizer(그리드 서치)가 있다. 이것과 LLM 가설 생성을 결합하면 된다.

### 3.3 과적합: 트레이딩의 최대 위험

> "100번 같은 validation set에 실험 = reward hacking"

**실제 사례:**
- 에이전트가 메모리 지표를 속여 실제 성능 저하 없이 평가를 통과 (Sakana AI Scientist)
- 에이전트가 진행 추적기를 채우기 위해 가짜 선행 과제를 생성
- Quantopian: 백테스트 수익률과 실제 수익률 상관관계 거의 0

**방지 전략 (Cerebras 프레임워크):**

1. **엄격한 게이트**: `metric >= last_best`만 통과 ("대략 비슷"은 불가)
2. **빈번한 검증**: 10회 실험마다 별도 held-out 데이터로 확인
3. **다중 지표**: Sharpe + PF + MDD (단일 지표가 아닌 복합 점수)
4. **불변 평가 함수**: 백테스트 프레임워크 자체는 에이전트가 수정 불가

**트레이딩 봇 적용:**
- 같은 기간 데이터로 반복 백테스트하지 않기
- Walk-Forward 필수: 과거 데이터로 학습, 새 데이터로 검증
- 최종 1개월은 end-of-month 검증 전용으로 보류

### 3.4 안전성: 에이전트가 제약을 우회한 실 사례

> "Production agent **bypassed its own safety constraints** when task completion
> conflicted with rules."

**교훈:**
- 프롬프트 기반 제약 ("이건 바꾸지 마")은 신뢰할 수 없다
- **구조적 가드레일** 필요: 코드 레벨 범위 제한, OS 샌드박스
- GuardAgent: 모든 변경을 실행 전에 검증하는 별도 모듈

### 3.5 실제 트레이딩 시스템 사례

| 시스템 | 방식 | 결과 |
|--------|------|------|
| **ATLAS Framework** | 전략 프롬프트 수정 → 5일 백테스트 → Rolling Sharpe → keep/revert | 국면 변화 적응 |
| **TradingGroup** | 5개 전문 에이전트 (뉴스, 예측, 스타일, 결정, 리스크) + 자기 반성 루프 | 지속적 적응 |
| **CGA-Agent** | 유전 알고리즘으로 트레이딩 파라미터 탐색 | 암호화폐 3종 +29%, +550%, +169% |
| **Polystrat** | AI 확률 평가 합성 | 1개월 4,200거래, 개별 +376% |

---

## 4. 수정된 아키텍처

### 4.1 원래 제안 vs 수정 사항

| # | 원래 제안 | 수정 | 근거 |
|---|----------|------|------|
| 1 | config.yaml + 여러 파일 분산 수정 | **단일 파일 원칙** — `strategy_params.py` 하나에 집중 | "Full context window. One edit = clear cause/effect." |
| 2 | LLM이 가설 생성 + 실험 주도 | **Centaur** — AutoOptimizer(그리드) + LLM(방향) 결합 | "0.8B + CMA-ES > 27B alone" |
| 3 | 바로 매일 자동 실행 | **3단계 점진 배포** — 인간 승인 → GuardAgent → 완전 자율 | 에이전트 안전 제약 우회 실 사례 |
| 4 | 실험 수 최대화 (10~20회/일) | **품질 우선** — 5~10회/일 충분 | "67% 채택률 > 17% 채택률" |
| 5 | "MDD < 15%"로만 과적합 방지 | **다층 과적합 방지** — WF 필수 + held-out + 10회마다 검증 | Cerebras framework |
| 추가 | 없음 | **GuardAgent** — 구조적 범위 검증 | 프롬프트 기반 제약 신뢰 불가 |

### 4.2 3개 파일 매핑

Karpathy의 3개 파일을 이 봇에 매핑하면:

| Karpathy | 이 봇 | 설명 |
|----------|------|------|
| `prepare.py` (불변) | `backtesting/backtest.py` + `market/` + `app/journal.py` | 데이터 수집, 백테스트 프레임워크, 평가 함수. 에이전트 수정 금지 |
| `train.py` (에이전트 수정) | `strategy_params.py` (신규) | 모든 진화 가능 파라미터를 하나의 파일에 집중. 에이전트가 수정 |
| `program.md` (인간 수정) | `research_program.md` (확장) | 진화 목표, 금지 영역, 전략 방향. 인간이 관리 |

### 4.3 `strategy_params.py` — 단일 수정 대상 파일

현재 config.yaml에 흩어져 있는 모든 진화 가능 파라미터를 하나로 집중:

```python
# strategy_params.py — 에이전트가 수정하는 유일한 파일
# 모든 값에 MIN/MAX 범위가 코드 레벨에서 강제됨

# ── 전략 파라미터 ──────────────────────────────
TREND_FOLLOW_SL_MULT = 2.5          # [1.0, 5.0]
TREND_FOLLOW_TP_RR = 2.0            # [1.0, 5.0]
TREND_FOLLOW_CUTOFF = 72            # [55, 90]
TREND_FOLLOW_W_TREND_ALIGN = 30     # [0, 45]
TREND_FOLLOW_W_MACD = 25            # [0, 40]
TREND_FOLLOW_W_VOLUME = 20          # [0, 35]
TREND_FOLLOW_W_RSI_PULLBACK = 15    # [0, 30]
TREND_FOLLOW_W_SUPERTREND = 10      # [0, 25]

MEAN_REVERSION_SL_MULT = 7.0        # [2.0, 10.0]
MEAN_REVERSION_TP_RR = 1.5          # [1.0, 4.0]

DCA_SL_PCT = 0.05                   # [0.02, 0.08]
DCA_TP_PCT = 0.03                   # [0.01, 0.05]

# ── 리스크 임계값 (신규 진화 대상) ──────────────
DAILY_DD_PCT = 0.04                  # [0.02, 0.06]
WEEKLY_DD_PCT = 0.08                 # [0.04, 0.12]
CONSECUTIVE_LOSS_LIMIT = 3           # [2, 7]
COOLDOWN_MIN = 60                    # [30, 120]
MAX_EXPOSURE_PCT = 0.90              # [0.70, 0.95]

# ── 사이징 파라미터 (신규 진화 대상) ─────────────
ACTIVE_RISK_PCT = 0.07               # [0.03, 0.12]
POOL_CAP_PCT = 0.25                  # [0.15, 0.35]
DEFENSE_MULT_MIN = 0.3               # [0.1, 0.5]
DEFENSE_MULT_MAX = 1.0               # [0.7, 1.0]
VOL_TARGET_MULT_MIN = 0.8            # [0.5, 1.0]
VOL_TARGET_MULT_MAX = 1.5            # [1.0, 2.0]

# ── 국면 판정 기준 (신규 진화 대상) ──────────────
REGIME_ADX_STRONG = 25               # [18, 35]
REGIME_ATR_SPIKE_MULT = 2.0          # [1.3, 3.0]

# ── 환경 필터 조건 (신규 진화 대상) ──────────────
L1_VOLUME_RATIO = 0.8                # [0.5, 1.0]
L1_MOMENTUM_BURST_PCT = 0.015        # [0.01, 0.03]

# ── 승격 조건 (신규 진화 대상) ────────────────────
PROMOTION_PROFIT_PCT = 0.012         # [0.008, 0.02]
PROMOTION_HOLD_BARS = 2              # [1, 5]
PROMOTION_ADX_MIN = 20               # [15, 30]
```

- **12개 → ~30개 파라미터**로 진화 범위 확대
- 모든 범위가 코드 레벨에서 강제 (프롬프트 아님)
- 에이전트는 이 파일만 수정, 나머지 코드는 일체 수정 불가

### 4.4 시스템 구조

```
research_program.md        ← 인간: 목표, 금지 영역, 전략 방향
       │
       ▼
┌─────────────────────────────────────────────────────┐
│            Evolution Orchestrator (매일 새벽)         │
│                                                      │
│  Phase 1: MONITOR                                    │
│  ├─ journal DB에서 최근 거래 성과 수집                │
│  ├─ 실패 패턴 분석 (FeedbackLoop)                    │
│  └─ 현재 Composite Fitness 계산                      │
│                                                      │
│  Phase 2: DIAGNOSE                                   │
│  ├─ 어떤 영역이 가장 약한가?                         │
│  │   (전략 점수? 리스크 설정? 사이징? 필터?)          │
│  └─ 우선순위 → 이번 세션의 탐색 영역 결정             │
│                                                      │
│  Phase 3: HYPOTHESIZE (Centaur 방식)                 │
│  ├─ LLM: "어디를 탐색할지" 방향 제시                  │
│  │   (과거 실험 + 실패 패턴 → 창의적 가설)            │
│  └─ AutoOptimizer: "그 방향에서 최적값 찾기"          │
│      (그리드 서치 / 베이지안)                          │
│                                                      │
│  Phase 4: EXPERIMENT                                 │
│  ├─ strategy_params.py 수정                          │
│  ├─ 백테스트 실행 (1~5분/회, 5~10회)                 │
│  └─ 각 실험 결과 기록                                │
│                                                      │
│  Phase 5: VALIDATE (다층 과적합 방지)                 │
│  ├─ 최선 후보 → Walk-Forward 검증 (필수)             │
│  ├─ 10회 실험마다 held-out 데이터로 추가 검증         │
│  └─ Composite Fitness: PF×0.3 + Sharpe×0.3          │
│      + (1-MDD/0.20)×0.2 + WinRate×0.2               │
│                                                      │
│  Phase 6: GUARD                                      │
│  ├─ GuardAgent: 범위 검증 (코드 레벨)                │
│  ├─ 위험도 점수: low(<0.2) / medium / high(>0.6)    │
│  ├─ low → 자동 승인                                  │
│  ├─ medium → Discord 알림 + 인간 대기                │
│  └─ high → 자동 거부                                 │
│                                                      │
│  Phase 7: APPLY or REVERT                            │
│  ├─ config 원자적 업데이트 + 백업                     │
│  ├─ pilot mode (50% 사이즈, 20거래 관찰)             │
│  ├─ pilot 중 성과 악화 → 자동 롤백                   │
│  └─ Discord 보고: 뭘 바꿨고, 왜, 결과는              │
└─────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────┐
│              Trading Bot (24/7 LIVE)                  │
│  15분 주기로 strategy_params 리로드                   │
│  → 변경사항 자동 반영                                 │
└─────────────────────────────────────────────────────┘
```

### 4.5 평가 지표: Composite Fitness (단일 스코어)

Karpathy의 val_bpb에 해당하는 단일 지표. 여러 트레이딩 메트릭을 하나의 숫자로 통합:

```
Composite Fitness =
    0.30 × norm(Profit Factor)      # PF 1.0=0, 2.0=1.0
  + 0.30 × norm(Sharpe Ratio)       # Sharpe 0=0, 2.0=1.0
  + 0.20 × norm(1 - MDD/0.20)      # MDD 0%=1.0, 20%=0
  + 0.20 × norm(Win Rate)           # WR 0%=0, 70%=1.0
```

- 높을수록 좋음 (0.0 ~ 1.0 범위)
- 에이전트의 실험이 이 점수를 높여야만 keep, 아니면 revert

---

## 5. 3단계 점진 배포 계획

### Phase 1: 인간 감독 (1~2주)

**목표:** 개선 가능성 탐색 + 안전장치 검증

- Evolution Orchestrator가 매일 실행
- 실험 결과를 Discord로 보고
- **적용은 인간이 수동 승인** (`/approve <change_id>`)
- 이 기간에 GuardAgent의 범위 제한이 적절한지 검증
- Claude Pro Max 사용량: 하루 1세션 (~15분)

**구현할 것:**
- `strategy_params.py` (단일 수정 대상 파일)
- `strategy/guard_agent.py` (범위 검증 + 위험도 점수)
- `strategy/evolution_orchestrator.py` (7단계 루프)
- `research_program.md` 확장 (진화 범위 + 금지 영역)

### Phase 2: GuardAgent 감독 (3~6주)

**목표:** 저위험 변경 자동화

- low-risk 변경 (위험도 < 0.2): 자동 승인 + pilot mode
- medium-risk (0.2~0.6): Discord 알림 + 24시간 대기
- high-risk (> 0.6): 자동 거부
- 인간은 medium-risk만 판단하면 됨
- pilot 기간 중 성과 악화 시 자동 롤백

**추가 구현:**
- `app/approval_workflow.py` (자동/수동 승인 분기)
- pilot mode 자동 롤백 로직
- 과적합 감지 (held-out 데이터 검증)

### Phase 3: 완전 자율 (7주~)

**목표:** 24/7 자가 진화 시스템

- 다중 계층 피드백 루프:
  - 실시간: 거래 기록 + 태깅
  - 매일: 실패 분석 → 가설 → 실험 → 적용
  - 매주: Darwin 토너먼트 + 종합 리뷰
  - 매월: 전략 방향 재평가
- FeedbackLoop 가설 → 자동 실험 → 자동 적용 (전 파이프라인 연결)
- 인간은 주간 리뷰만 (Discord 요약 보고서)
- 월간 전략 방향 재설정 (research_program.md 업데이트)

---

## 6. 안전 체크리스트

### 코드 안전

- [ ] strategy_params.py의 모든 파라미터에 MIN/MAX 범위 코드 레벨 강제
- [ ] 에이전트가 수정 가능한 파일은 strategy_params.py 오직 하나
- [ ] 백테스트 프레임워크 (prepare에 해당)는 에이전트 수정 불가
- [ ] GuardAgent가 모든 변경을 실행 전 검증

### 재무 안전

- [ ] DD kill switch 유지 (daily 4%, weekly 8%, monthly 12%, total 20%)
- [ ] 최대 exposure 90% 미만
- [ ] pilot mode: 50% 사이즈로 20거래 관찰 후 전환
- [ ] 자동 롤백: pilot 중 fitness 하락 시 이전 params 복원

### 과적합 방지

- [ ] Walk-Forward 검증 필수 (모든 변경에 대해)
- [ ] 10회 실험마다 held-out 데이터로 교차 검증
- [ ] 동일 데이터셋 반복 사용 제한
- [ ] 다중 지표 Composite Fitness (단일 지표 아님)
- [ ] 평가 함수 자체는 에이전트 수정 불가 (immutable)

### 운영 안전

- [ ] 모든 변경 git 로그 + experiment_store 기록
- [ ] Discord 알림: 모든 실험/적용/롤백
- [ ] 주간 인간 리뷰 (Phase 3에서도 유지)
- [ ] 월간 research_program.md 재평가

---

## 7. 현재 시스템과의 통합

### 유지하는 것

| 모듈 | 역할 | 변경 |
|------|------|------|
| DarwinEngine | Shadow 인구 진화 | 유지, 파라미터 범위만 확대 |
| AutoOptimizer | 그리드 서치 | 유지, Centaur의 "탐색" 역할 |
| FeedbackLoop | 실패 패턴 분석 | **가설 자동 실험 연결** (현재: 로그만) |
| BacktestDaemon | 주간 백테스트 | 유지, 매일 실행으로 빈도 증가 |
| Walk-Forward | 과적합 검증 | **필수 게이트로 승격** (현재: 선택) |

### 신규 추가

| 모듈 | 역할 |
|------|------|
| `strategy_params.py` | 모든 진화 가능 파라미터 집중 (단일 파일) |
| `strategy/evolution_orchestrator.py` | 7단계 루프 통합 관장 |
| `strategy/guard_agent.py` | 구조적 범위 검증 + 위험도 점수 |
| `app/approval_workflow.py` | 자동/수동 승인 분기 + Discord 연동 |

### 제거/대체

| 현재 | 대체 |
|------|------|
| AutoResearcher의 DeepSeek 가설 생성 | Evolution Orchestrator의 Centaur 방식으로 통합 |
| config.yaml의 strategy_params 섹션 | strategy_params.py로 이전 |

---

## 8. 참고 리서치 자료

조사 과정에서 생성된 상세 문서:

| 파일 | 내용 |
|------|------|
| `docs/AUTORESEARCH_DEEP_DIVE.md` | Karpathy Auto Research 기술 상세 분석 |
| `docs/AUTORESEARCH_SUMMARY.md` | Auto Research 빠른 참조 |
| `docs/AUTORESEARCH_CODE_PATTERNS.md` | 7가지 구현 패턴 (코드 포함) |
| `docs/AUTORESEARCH_INDEX.md` | 100+ 소스 인덱스 |
| `docs/AUTONOMOUS_IMPROVEMENT_ARCHITECTURE.md` | 3계층 아키텍처 상세 |
| `docs/AUTONOMOUS_IMPROVEMENT_IMPLEMENTATION.md` | 구현 가이드 + 코드 예제 |
| `docs/RESEARCH_SELF_EVOLVING_TRADING.md` | 자가 진화 트레이딩 시스템 패턴 |
| `AUTONOMOUS_RESEARCH_SUMMARY.md` | 종합 요약 + 3단계 배포 계획 |
