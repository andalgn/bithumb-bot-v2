# Phase 5: Darwinian 20~30 Shadow + 고급 백테스트 검증

**기간**: 5~6주 | **우선순위**: MEDIUM
**참조**: `docs/DARWINIAN_SPEC.md`, `docs/BACKTEST_SPEC.md`

## 목표
미니PC 8코어 활용: Shadow 20~30개 병렬 추적 + Walk-Forward / Monte Carlo / 민감도 분석을 백그라운드에서 상시 실행.

## 작업 목록

### 5.1 strategy/darwin_engine.py — 확장 Darwinian

**Population 관리 (20~30개):**
- Champion 1 + Shadow 19~29
- 초기 생성: Champion ±돌연변이로 3그룹
  - Shadow 1~7: Champion ±10% (미세 조정)
  - Shadow 8~15: ±20% (탐색적)
  - Shadow 16~20+: 완전히 다른 조합 (혁신적)
- Shadow 1개당 ~5MB, 20개 = ~100MB

**Shadow 기록 (매 사이클):**
- 각 Shadow 파라미터로 "진입했을까?" 판단
- 가상 PnL 추적 + 체결비용 보정 (Tier별 슬리피지 + 수수료 0.5%)
- journal.db shadow_trades 테이블에 기록

**주간 토너먼트 (매주 일요일 00:00):**
- Composite Score 랭킹 (Exp 30% + PF 20% + MDD 20% + Sharpe 20% + ExQ 10%)
- 상위 5개 생존, 하위 변이
- 표본 미달 Shadow 제외

**돌연변이:** RSI ±3, ATR배수 ±0.3, 임계값 ±5%, TP/SL ±0.5%

**챔피언 교체 (월 1회, LIVE+30일까지 로그만):**
- Shadow net_pnl × 0.85 vs Live net_pnl
- 3개 윈도우 (14일 + 14일 + 30일) 모두 우위
- 교체 후 14일 쿨다운, 레짐 전환 후 48시간 동결

### 5.2 backtesting/backtest.py — 기본 백테스터
- market_data.db 축적 데이터로 실데이터 리플레이
- 수수료 + 슬리피지 반영
- 전략별/국면별/Tier별 성과 분리
- 결과: Sharpe, Expectancy, MDD, PF, 승률

### 5.3 backtesting/walk_forward.py — Walk-Forward 검증
- **매일 00:30 KST** 백그라운드 스레드에서 자동 실행
- 30일 데이터 7일 슬라이딩 (4개 구간)
- 각 구간: 훈련→검증 성과 측정
- 판정: 4/4=견고, 3/4=양호, 2/4이하=경고
- 훈련 vs 검증 차이 > 50%이면 과적합
- journal.db backtest_results 테이블에 저장

### 5.4 backtesting/monte_carlo.py — Monte Carlo 시뮬레이션
- **매주 일요일 01:00 KST** 실행
- 최근 30일 거래를 1,000번 랜덤 셔플
- 하위 5% PnL, 최악 MDD, Sharpe 분포 산출
- 하위5% PnL > 0 = "95% 확률로 수익"
- 최악 MDD > 20%이면 사이징 축소 경고
- 소요: ~30초 (8코어 병렬)

### 5.5 backtesting/sensitivity.py — 파라미터 민감도 분석
- **매주 일요일 01:30 KST** 실행
- 현재 파라미터 ±10% (5단계) 변이
- 변동계수(CV): <0.1 견고, 0.1~0.3 보통, >0.3 민감(경고)
- 민감 파라미터 → 주간 DeepSeek에 전달
- ~50회 백테스트, 소요 ~2분

### 5.6 검증 데몬 통합
```python
class BacktestDaemon:
    """별도 스레드, 메인 루프에 영향 없음"""
    async def run(self):
        while True:
            now = get_kst_now()
            if now.hour == 0 and now.minute == 30:
                await self.walk_forward.run()
            if now.weekday() == 6 and now.hour == 1:
                await self.monte_carlo.run()
                await self.sensitivity.run()
            await asyncio.sleep(60)
```

### 5.7 텔레그램 통합 검증 리포트
```
📊 주간 검증 (2026-XX-XX)
━━━━━━━━━━━━━━━━━━
[Walk-Forward] 4/4 통과 ✓
[Monte Carlo]  하위5%: +1.2%, 최악MDD: 11.3%
[민감도]       RSI:견고 ATR:보통 컷오프:민감⚠
[Shadow]       Top3: B(+18%), D(+12%), A(+8%)
[데이터]       5M: 42,000봉, 호가창: 8,400건
━━━━━━━━━━━━━━━━━━
```

### 5.8 테스트
- `tests/test_darwin.py` — Shadow PnL 정확성
- `tests/test_walk_forward.py` — 4구간 판정
- `tests/test_monte_carlo.py` — 분포 계산
- `tests/test_sensitivity.py` — CV 판정
- 메모리 모니터링 (~500MB 이내)

## 완료 기준
- [ ] Shadow 20~30개 병렬 추적 동작
- [ ] Walk-Forward 매일 자동 + 판정 정상
- [ ] Monte Carlo 주간 자동 + 분포 산출
- [ ] 민감도 분석 주간 자동 + CV 판정
- [ ] 통합 검증 리포트 텔레그램 전송
- [ ] 메인 루프 성능에 영향 없음
- [ ] PAPER 7일 운영
