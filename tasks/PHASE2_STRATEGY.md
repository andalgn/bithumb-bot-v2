# Phase 2: 전략 코어 구현

**기간**: 2~3주 | **우선순위**: HIGH
**참조**: `docs/STRATEGY_SPEC.md`, `docs/PARAMS.md`

## 목표
국면 5단계 + 전략 5종 + 전략별 점수제 + MTF 확인 + 코인 프로파일러 구현.

## 작업 목록

### 2.1 strategy/coin_profiler.py (새로 작성)
- 매일 00:00 KST 자동 실행
- 최근 14일 ATR%, 거래대금, BTC 상관계수 계산
- Tier 1/2/3 자동 분류 (ATR% <3% / 3~7% / >7%)
- Tier별 파라미터 세트 반환 (RSI 범위, ATR 손절 배수, 포지션 배수)
- config.yaml에서 임계값 로딩 (하드코딩 없음)

### 2.2 strategy/rule_engine.py (새로 작성)
**국면 분류:**
- 5단계 판정 수식 (STRATEGY_SPEC.md 2.2절 코드 그대로 구현)
- 입력: 1H 캔들 기준 EMA 20/50/200, ADX 14, +DI/-DI, ATR 14
- 히스테리시스: 3봉 확인 + 6봉 재전환 금지 + CRISIS 즉시/6봉 해제
- 보조 플래그: RANGE_VOLATILE (2봉), DOWN_ACCEL

**전략별 점수 계산:**
- 전략 A/B/C/D 독립 점수표 (STRATEGY_SPEC.md 4.2~4.5절)
- 각 전략이 0~100점 반환
- 3그룹 컷오프: A/B ≥72 Full / 55~71 Probe | C/D ≥78 / 62~77 | E ≥68 / 53~67

**Layer 1 환경 필터:**
- 국면 ≠ CRISIS
- 거래량 ≥ 20봉 평균 × 0.8
- 스프레드 < Tier별 한도 (T1:0.18%, T2:0.25%, T3:0.35%)
- 시간대 필터 (00:00~06:00 KST → Tier 3 스킵)

**국면별 전략 허용 매핑:**
- STRONG_UP → A + D
- WEAK_UP → A 보수적
- RANGE → B + C
- WEAK_DOWN → B만 (DOWN_ACCEL 시 ×0.4)
- CRISIS → 전량 청산

### 2.3 indicators.py 확장 (Phase 0에서 복사한 것에 추가)
- `calc_adx(highs, lows, closes, period=14)` → ADX, +DI, -DI
- `ema(data, period=200)` → EMA200 추가
- 모든 지표를 15M + 1H 이중 계산 지원
- `get_indicators()` → 확장된 IndicatorPack 반환

### 2.4 Layer 3 Expected Edge 필터 (RiskGate 확장)
- `risk_gate.py`에 Expected Edge 계산 추가
- `expected_edge = expectancy - (fee + slippage + failure_penalty)`
- ≤ 0이면 거부
- 호가 잔량 필터 구현 (Tier별: T1 5배, T2 3배, T3 2배)

### 2.5 strategy/correlation_monitor.py (NEW)
- **파일**: `strategy/correlation_monitor.py`
- 매일 00:00 KST: 10개 코인 간 20일 롤링 수익률 상관관계 매트릭스 계산
- 진입 전 확인 메서드: `check_correlation(new_coin, active_positions)`
  - 상관계수 > 0.85 → 진입 스킵
  - 상관계수 0.70~0.85 → 포지션 크기 50% 축소
  - 상관계수 < 0.70 → 정상
- Layer 3에서 RiskGate와 함께 호출
- 주간 리포트에 상관관계 요약 포함
- 테스트: `tests/test_correlation.py`

### 2.6 테스트
- `tests/test_rule_engine.py`:
  - 각 국면 진입 조건 5개 케이스
  - 히스테리시스 전환/재전환 금지 테스트
  - CRISIS 즉시 진입 / 6봉 해제 테스트
  - 보조 플래그 (RANGE_VOLATILE, DOWN_ACCEL) 테스트
- `tests/test_scoring.py`:
  - 전략별 만점/0점/경계값 테스트
  - 3그룹 컷오프 Full/Probe/HOLD 판정

## 완료 기준
- [ ] 5단계 국면 + 히스테리시스 동작
- [ ] 4개 전략 점수표 + 3그룹 컷오프 동작
- [ ] 코인 프로파일러 Tier 자동 분류 동작
- [ ] Expected Edge + 호가 잔량 필터 동작
- [ ] PAPER 7일, 진입 빈도 및 신호 품질 확인
- [ ] `pytest tests/` 전체 통과
