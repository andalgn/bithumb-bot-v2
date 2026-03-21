# 백테스트 전략 최적화 설계서

**작성일**: 2026-03-21
**목표**: 전략 파라미터 최적화 + 전략 로직 개선 + end-to-end 파이프라인 검증을 통해 매매 수익성 확보

## 현재 상태

### 기존 인프라
- 백테스터, 2단계 옵티마이저(Entry 캐싱 → SL/TP 리플레이), Walk-Forward/Monte Carlo/Sensitivity 클래스 구현 완료
- 파라미터 그리드 325개 조합 정의, `optimize.py` 스크립트 존재
- Walk-Forward/MC/Sensitivity 데몬 통합 미완성 (스텁 상태)
- SensitivityAnalyzer는 근사치 방식 (PnL에 delta×0.5 적용) → `ParameterOptimizer.replay_with_params()` 기반으로 재작성 필요
- WalkForward 클래스는 30일/4구간 하드코딩 → 설정 가능한 구간 수/데이터 범위로 리팩토링 필요
- MonteCarloResult에 P10 필드 없음 → 추가 필요
- 수수료 모델: 0.25%/side + 슬리피지 0.1%/side = round-trip 0.70% (`backtesting/optimizer.py` FEE_RATE 기준)

### 핵심 문제
- 실제 시장 데이터 없음 (`market_data.db` 비어있음)
- BithumbClient에 프록시 미적용 → 데이터 다운로드/LIVE 매매 불가
- 전략 A/B/C/D 모두 적자 (DCA만 수익)
- 최적화 결과: A(PF 0.20), B(PF 0.12), C(PF 0.87), D(PF 0.03), E(PF 1.67)

---

## 전체 파이프라인

```
Phase 1: 인프라 준비 + 데이터 수집
Phase 2: 1차 파라미터 최적화 (325조합, IS/OOS)
Phase 3: 결과 분석 + 전략 로직 개선
Phase 4: 2차 최적화 (fine grid + 포트폴리오)
Phase 5: 강건성 검증 (WF + MC + Sensitivity)
Phase 6: 최종 적용 + 리포트

※ Phase 5 검증 실패 시 Phase 3로 복귀하여 사이클 반복
```

각 Phase는 이전 Phase 결과에 의존하므로 순차 진행.

---

## Phase 1: 인프라 준비 + 데이터 수집

### Step 1: 프록시 인프라 적용

**변경 대상:**
- `configs/config.yaml` — `proxy: "http://127.0.0.1:1081"` 항목 추가
- `app/config.py` — proxy 설정 로딩
- `market/bithumb_api.py` — aiohttp 세션 생성 시 proxy 적용 (모든 API 호출에 자동 적용)
- `scripts/download_and_backtest.py`, `scripts/optimize.py` — proxy 경유

**설계 원칙:**
- config.yaml에서 관리, 빈 문자열이면 프록시 미사용 (직접 연결)
- BithumbClient의 `_public_request()`, `_private_request()` 호출 시 `proxy=` 파라미터 전달 (aiohttp는 per-request 방식)
- 환경변수 `HTTPS_PROXY` fallback 지원

### Step 2: 데이터 수집

- 10개 코인 × 15M/1H 캔들 최대치 수집 (빗썸 API 허용 범위, ~6개월)
- 빗썸 공개 API `GET /public/candlestick/{coin}_KRW/{interval}` 호출
- API rate limit 준수 (0.15초 간격)
- 결과를 `data/market_data.db`에 저장

**예상 데이터량:**
- 1H × 6개월 ≈ 4,320봉 × 10코인 = ~43,200행
- 15M × 6개월 ≈ 17,280봉 × 10코인 = ~172,800행
- 합계: ~216,000행

---

## Phase 2: 1차 파라미터 최적화

### 옵티마이저 방식

기존 `backtesting/optimizer.py`의 2단계 방식 사용:

1. **Entry 캐싱** — RuleEngine으로 전체 데이터 스캔, 진입 신호 + ATR + 96봉(24h) lookahead 캐싱 (전략당 1회)
2. **SL/TP 리플레이** — 캐싱된 진입점에 파라미터 조합별 SL/TP 적용, PnL 계산 (조합당 수ms)

### 파라미터 그리드 (325개 조합)

| 전략 | 파라미터 | 조합 수 |
|------|---------|--------|
| A 추세 | sl_mult × tp_rr × cutoff | 120 |
| B 평균회귀 | sl_mult × tp_rr × cutoff | 80 |
| C 돌파 | sl_mult × tp_rr × cutoff | 100 |
| D 스캘핑 | sl_pct × tp_pct | 25 |

**Strategy E (DCA)**: 고정 4%/거래, CRISIS/WEAK_DOWN 전용. 이미 PF 1.67로 수익 중이며 파라미터가 단순하므로 그리드 최적화 대상에서 제외. Phase 3에서 필요 시 sl_pct/tp_pct 범위만 검토.

### IS/OOS 분할

- 데이터를 시간순 70:30으로 분할
- IS에서 그리드 탐색 → 전략별 상위 5개 파라미터 선정
- OOS에서 상위 5개 검증
- IS vs OOS Sharpe 괴리 > 50%면 과적합으로 기각

### 성공 기준 (1차)

- 전략별 OOS Expectancy > 0
- OOS Profit Factor > 1.0
- OOS 최소 트레이드 30건 이상
- **트레이드 부족 시 fallback**: OOS 30건 미만이면 IS/OOS 비율을 60:40으로 조정하거나, 최소 20건 + 통계적 신뢰도 경고 부착

### 산출물

- 전략별 최적 파라미터 + 성과 지표
- Baseline 대비 개선율
- 과적합 경고 목록

---

## Phase 3: 결과 분석 + 전략 로직 개선

### 진단 기준

1차 최적화 결과를 기반으로 전략별 진단:

- **파라미터로 해결됨** — OOS PF > 1.0 달성 → Phase 4에서 fine-tuning만
- **구조적 문제** — 최적 파라미터로도 OOS PF < 0.8 → 로직 개선 필요
- **트레이드 부족** — OOS 30건 미만 → 진입 조건이 너무 보수적

### 개선 가능 영역 (제한 없음)

| 영역 | 예시 | 적용 단위 |
|------|------|----------|
| 점수 가중치 | A전략 MACD 25→35, Volume 20→10 | 전략별 |
| 진입 cutoff | Full 75→70, Probe 60→55 | 전략별 |
| 청산 로직 | 부분청산 비율, 트레일링 ATR 배수 | 전략별 |
| 국면 배수 | STRONG_UP ×1.5→×1.2 | 전체 |
| 국면 전환 조건 | ADX 임계값, EMA 조합 | 전체 |
| 타임아웃 | D전략 2시간→4시간 | 전략별 |
| 전략 비활성화 | 구조적으로 안 되는 전략 OFF | 전략별 |

### 프로세스

1. 1차 결과 리포트 생성 (전략별 승률, PF, MDD, 트레이드 분포)
2. 적자 전략의 트레이드를 개별 분석 — 어디서 손실이 집중되는지 (국면별, 코인별, 시간대별)
3. 가설 수립 → 로직 수정 → 국소 백테스트로 빠르게 검증
4. 개선된 로직으로 Phase 4 진행

**주의: Entry 캐시 무효화** — Phase 3에서 전략 로직(점수 가중치, 진입 조건 등)을 변경하면, Phase 2에서 생성한 entry cache가 무효화됨. 로직 변경 후에는 반드시 `ParameterOptimizer.scan_entries()`를 재실행하여 새로운 캐시를 생성해야 함.

### 핵심 원칙

- **데이터 기반 판단** — 감이 아니라 1차 결과 숫자로 결정
- **한 번에 하나씩** — 여러 변수를 동시에 바꾸면 뭐가 효과인지 모름
- **구제불능이면 끈다** — 모든 전략이 수익일 필요 없음, 전체 포트폴리오 수익이면 됨

---

## Phase 4: 2차 최적화

### 1차와의 차이점

- **확장된 탐색 공간** — Phase 3에서 개선한 로직 기반, 점수 가중치·청산 비율 등 새 파라미터 포함
- **적응형 그리드** — 1차에서 유망했던 영역 주변을 세밀하게 탐색 (coarse → fine)
- **전략 간 조합 평가** — 개별 전략 최적화 후 포트폴리오 레벨에서 전략 조합 시뮬레이션

### 2단계 그리드 전략

```
1차: 넓은 범위 탐색 (step 큰 간격)
     └→ 상위 5개 영역 식별

2차: 상위 영역 ±1~2 step 범위로 fine grid
     └→ 최종 최적 파라미터 도출
```

### 포트폴리오 시뮬레이션

개별 전략 최적화 후, 전략 조합의 시너지/충돌 검증:
- 같은 코인에 A전략과 C전략이 동시 진입하는 경우
- 국면별 활성 전략 조합의 총 수익 곡선
- 자금 배분(Pool 사이즈)에 따른 전체 수익 변화

### 성공 기준 (2차, 강화)

- 전략별 OOS PF > 1.2
- 포트폴리오 OOS PF > 1.5
- MDD < 15%
- Expectancy > 0 (수수료·슬리피지 포함)

---

## Phase 5: 강건성 검증

### Walk-Forward 검증

- 전체 데이터를 **6~8구간**으로 분할 (데이터량에 비례)
- 각 구간: IS(학습) 70% → OOS(검증) 30%, 슬라이딩
- **통과 기준**: 전체 구간의 75% 이상에서 OOS PF > 1.0
- 구간별 성과 편차가 크면 특정 시장 국면에만 작동하는 전략 → 경고

### Monte Carlo 시뮬레이션

- 최적 파라미터의 트레이드 결과를 1,000회 무작위 셔플
- 수익 곡선 분포에서 퍼센타일 분석
- **통과 기준**: P10 > 0 AND P5 > -2%
- MDD 분포: P95 MDD < 15%

### Sensitivity 분석

- 현재 SensitivityAnalyzer는 근사치 방식 → `ParameterOptimizer.replay_with_params()` 기반으로 재작성 후 사용
- 최적 파라미터를 ±10%, ±20% 변동
- 각 변동에서 실제 SL/TP 리플레이로 PF, Expectancy 재계산
- **CV(변동계수) < 0.3** = 강건, > 0.3 = 민감 → 해당 파라미터 재검토
- 특정 파라미터가 민감하면 보수적 값으로 조정

### 기각 시 대응

검증 실패한 전략은:
1. Phase 3로 돌아가 로직 재개선
2. 또는 해당 전략 비활성화
3. 포트폴리오 레벨에서 재평가

---

## Phase 6: 최종 적용 + 리포트

### config.yaml 반영

- 검증 통과한 파라미터를 `configs/config.yaml`의 `strategy_params`에 적용
- 변경 전/후 파라미터 diff 기록
- 비활성화할 전략이 있으면 config에서 `enabled: false` 처리

### 결과 리포트 구성

```
1. 요약 — Baseline vs 최종 성과 비교표
2. 전략별 상세
   - 최적 파라미터
   - IS/OOS 성과 (PF, 승률, Expectancy, MDD)
   - Walk-Forward 구간별 결과
   - Monte Carlo P5/P10/P50 분포
   - Sensitivity CV 값
3. 포트폴리오 전체
   - 전략 조합 수익 곡선
   - 총 PF, MDD, 자금활용률
4. 결론 + 권고사항
   - PAPER 모드 전환 가능 여부 판단
   - 추가 개선이 필요한 영역
```

### 산출물

- `docs/backtest-report-YYYY-MM-DD.md` — 분석 리포트
- `configs/config.yaml` — 최적 파라미터 반영
- `data/optimization_results/` — 원시 결과 데이터 보관

---

## 검증 기준 요약

| 지표 | 1차 기준 | 최종 기준 |
|------|---------|---------|
| Expectancy | > 0 | > 0 (수수료 포함) |
| Profit Factor (전략별) | > 1.0 | > 1.2 |
| Profit Factor (포트폴리오) | — | > 1.5 |
| MDD | — | < 15% |
| Walk-Forward | — | 75% 구간 OOS PF > 1.0 |
| Monte Carlo | — | P10 > 0, P5 > -2% |
| Sensitivity CV | — | < 0.3 |
| Overfit 탐지 | IS/OOS Sharpe 괴리 < 50% | IS/OOS Sharpe 괴리 < 50% |
| 최소 트레이드 | OOS 30건/전략 | OOS 30건/전략 |

검증 기준은 1차 백테스트 결과를 보고 데이터 분포에 맞춰 조정 가능.

---

## 반복 사이클

최적화는 coarse → fine 2회로 충분. 3회 이상 같은 그리드를 세밀하게 쪼개면 과적합 위험.
단, **"분석 → 로직 개선 → 최적화 2회 → 검증" 사이클 자체**는 검증 통과할 때까지 반복.
로직이 바뀌면 탐색 공간 자체가 달라지므로 coarse → fine 2회가 다시 유효.

```
Phase 3 → Phase 4 → Phase 5
   ↑                    ↓
   └── 검증 실패 시 복귀 ──┘
```
