# Trade Schema 및 성과 측정 정의

## 1. Trade Schema

모든 거래는 아래 스키마로 journal.db에 기록. 성과 측정의 유일한 데이터 원천.

| 필드 | 타입 | 설명 |
|------|------|------|
| trade_id | UUID | 거래 고유 식별자 |
| symbol | string | 코인 심볼 (e.g. BTC/KRW) |
| strategy | enum | trend_follow / mean_reversion / breakout / scalping / dca |
| tier | int | 1 / 2 / 3 (진입 시점 기준) |
| regime | enum | STRONG_UP / WEAK_UP / RANGE / WEAK_DOWN / CRISIS |
| pool | enum | core / active / reserve |
| entry_price | float | 실제 체결 평균가 (KRW) |
| exit_price | float | 실제 체결 평균가 (KRW) |
| qty | float | 체결 수량 |
| entry_fee_krw | float | 매수 수수료 (KRW) |
| exit_fee_krw | float | 매도 수수료 (KRW) |
| slippage_krw | float | 슬리피지 = |signal_price - fill_price| × qty |
| gross_pnl_krw | float | (exit_price - entry_price) × qty |
| net_pnl_krw | float | gross_pnl - entry_fee - exit_fee - slippage |
| net_pnl_pct | float | net_pnl / (entry_price × qty) × 100 |
| hold_seconds | int | 보유 시간 (초) |
| promoted | bool | 승격 여부 |
| entry_score | float | 진입 시 점수 |
| entry_time | datetime | 진입 시각 (KST) |
| exit_time | datetime | 청산 시각 (KST) |
| exit_reason | enum | tp / sl / trailing / time / regime / manual / crisis / demotion |

## 2. Realized PnL 산정

```python
gross_pnl = (exit_price - entry_price) * qty
entry_fee = entry_price * qty * 0.0025
exit_fee  = exit_price * qty * 0.0025
slippage  = abs(signal_price - fill_price) * qty
net_pnl   = gross_pnl - entry_fee - exit_fee - slippage
```

**모든 성과 측정은 net_pnl_krw 기준. gross_pnl은 참고만.**

부분청산 시: 각 트렌치별 별도 기록, 포지션 종료 시 전체 합산하여 1건으로 집계.

## 3. 전략별 최소 유효 표본 수

표본 미달 시 '데이터 부족' 플래그 → 파라미터 조정 및 Darwinian 평가 대상 제외.

| 전략 | 최소 거래 수 | 근거 |
|------|-------------|------|
| 추세추종 (A) | 30건 | 승률 40~50%, 오차 ±10% 구간 신뢰 95% |
| 반전포착 (B) | 40건 | 승률 55~65%, 오차 ±8% 구간 |
| 브레이크아웃 (C) | 25건 | 빈도 낮아 축적 느림, 최소한 |
| 스캘핑 (D) | 50건 | 소액 다빈도, 통계 안정성 필요 |
| DCA (E) | 10건 | 장기 매집, 빈도 자체가 낮음 |
| 국면별 분리 | 15건/국면 | 국면 간 성과 비교 유효성 |
| Tier별 분리 | 20건/Tier | Tier간 파라미터 차별화 근거 |

## 4. 최근 성과 vs 누적 성과 충돌 시

| 상황 | 적용 규칙 |
|------|----------|
| 최근 7일 저하 + 누적 양호 | 일일 리뷰에서 파라미터 보수적 조정 (임계값+5%) |
| 최근 7일 양호 + 누적 저하 | 조정 보류 (최근 성과가 레짐 특성일 수 있음) |
| 모두 음수 | 해당 전략 일시 정지 + 주간 DeepSeek에서 원인 분석 |
| 가중치 | 최근 7일: 60% + 누적 30일: 40% (가중이동평균) |
