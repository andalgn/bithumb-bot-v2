# Phase 6: ReviewEngine + DeepSeek 주간 분석

**기간**: 6~7주 | **우선순위**: MEDIUM
**참조**: `docs/TRADE_SCHEMA.md`, `docs/DARWINIAN_SPEC.md`

## 작업 목록

### 6.1 strategy/review_engine.py (새로 작성)

**일일 규칙 리뷰 (LLM 없음):**
- 매일 00:00 KST `asyncio.create_task()`로 실행
- journal.db SQL 쿼리로 거래 집계
- 전략/국면/종목/Tier별 승률 + Expectancy 계산
- 규칙 기반 조정:
  - 승률 < 40% (표본 충족 시) → 해당 조합 임계값 +5%
  - 종목 3회 연속 손절 → 24시간 쿨다운
  - 주간 MDD > 6% → dd_mult 강화
- 조정분 14일 백테스트 → Sharpe 악화 시 롤백
- 텔레그램 일일 요약

**주간 DeepSeek 분석 (일요일 00:00):**
- 데이터 패키지 자동 생성:
  - 7일 거래 요약 (전략/국면/Tier/시간대별)
  - Darwinian 토너먼트 결과 (Shadow 20~30개 랭킹)
  - 파라미터 변경 이력 + 특이 이벤트
  - **Walk-Forward 판정 결과 (4구간 통과 여부)**
  - **Monte Carlo 하위5% PnL + 최악 MDD**
  - **민감도 분석 — 민감 파라미터 목록**
  - **상관관계 매트릭스 요약 (0.7 이상 쌍)**
- `httpx`로 DeepSeek-chat API 호출 (~3,000 tokens)
- JSON 응답 파싱 → 제안 리스트
- 제안별 백테스트 실행 → 통과분만 적용
- 텔레그램 주간 리포트

**월간 DeepSeek 심층 (월 1회):**
- deepseek-reasoner 호출
- 전략 체계 재평가 + 코인 유니버스 검토

### 6.2 텔레그램 리포트 포맷
```
📊 일일 리뷰 (2026-XX-XX)
━━━━━━━━━━━━━━━━━━
거래: 5건 (승3/패2)
Net PnL: +12,340원 (+1.2%)
활성 포지션: 3건 (Core 1, Active 2)
자금 활용률: 42%
승격: BTC (Active→Core)
조정: XRP 임계값 +5% (승률 35%)
━━━━━━━━━━━━━━━━━━

📊 주간 리뷰 (2026-XX-XX)
━━━━━━━━━━━━━━━━━━
총 거래: 28건 | 승률 54%
Net PnL: +45,200원 (+4.5%)
최고 전략: A(추세) Exp +2.1%
최저 전략: D(스캘핑) Exp -0.3% → 임계값 상향
Shadow 추천: 파라미터B (Sharpe +18%)
DeepSeek 제안: 2건 적용, 1건 기각
━━━━━━━━━━━━━━━━━━
```

### 6.3 테스트
- 일일 리뷰 SQL 쿼리 정확성
- 규칙 기반 조정 + 롤백 동작
- DeepSeek API 호출 + JSON 파싱 (mock 테스트)

## 완료 기준
- [ ] 일일 리뷰 00:00 자동 실행 + 텔레그램
- [ ] 주간 DeepSeek 호출 + 파싱 + 백테스트 검증
- [ ] 파라미터 자동 조정 + 롤백
- [ ] PAPER 7일 운영
