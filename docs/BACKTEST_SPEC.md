# 백테스트 및 검증 강화 명세

## 1. 개요
미니PC의 8코어 CPU 여유를 활용하여, 기본 백테스트 외에 3가지 고급 검증을 **백그라운드 스레드**에서 상시 실행. 파라미터 품질을 근본적으로 다른 수준으로 검증.

```
메모리 예산:
  봇 메인:         ~200MB
  백테스트 데몬:    ~400MB (Walk-Forward + Monte Carlo + 민감도)
  Shadow 20~30개:  ~150MB
  기타:            ~250MB
  합계:            ~1GB (8GB 중, 충분히 여유)
```

## 2. Walk-Forward 검증 (매일 자동)

### 개념
과거 데이터를 여러 구간으로 나눠 순차적으로 "훈련→검증"을 반복.
모든 구간에서 수익이 나야 견고한 파라미터.

### 구현
```
30일 데이터를 7일 단위로 슬라이딩:

구간 1: [1~14일 훈련] → [15~21일 검증]
구간 2: [8~21일 훈련] → [22~28일 검증]
구간 3: [15~28일 훈련] → [29~35일 검증]  ← 미래 데이터면 제외
...

각 구간에서:
  1. 훈련 기간의 최적 파라미터 탐색
  2. 검증 기간에서 성과 측정
  3. Sharpe, Expectancy, MDD 기록
```

### 판정 기준
| 결과 | 판정 | 조치 |
|------|------|------|
| 4개 구간 중 4개 수익 | 견고 | 파라미터 유지 |
| 4개 구간 중 3개 수익 | 양호 | 주의 관찰 |
| 4개 구간 중 2개 이하 수익 | 불안정 | 파라미터 조정 필요 경고 |
| 훈련 성과 vs 검증 성과 차이 > 50% | 과적합 | 해당 파라미터 폐기 |

### 실행 주기
- 매일 00:30 KST (일일 리뷰 직후)
- 별도 스레드에서 실행, 메인 루프에 영향 없음
- 결과를 journal.db `backtest_results` 테이블에 저장
- 텔레그램 요약: "WF 검증: 4/4 통과 ✓" 또는 "WF 검증: 2/4 — 경고 ⚠"

## 3. Monte Carlo 시뮬레이션 (주간)

### 개념
실제 거래 결과의 순서를 랜덤으로 섞어서 1,000번 시뮬레이션.
"이 성과가 운이 아닌 실력인가?"를 검증.

### 구현
```python
# 최근 30일 거래 결과 (net_pnl 리스트)
trades = get_recent_trades(days=30)

results = []
for i in range(1000):
    shuffled = random.shuffle(trades.copy())
    equity_curve = cumulative_sum(shuffled)
    results.append({
        "final_pnl": equity_curve[-1],
        "max_drawdown": calc_mdd(equity_curve),
        "sharpe": calc_sharpe(shuffled),
    })

# 통계
percentile_5 = sorted([r["final_pnl"] for r in results])[50]   # 하위 5%
percentile_95 = sorted([r["final_pnl"] for r in results])[950]  # 상위 95%
worst_mdd = max([r["max_drawdown"] for r in results])
```

### 판정 기준
| 지표 | 기준 | 의미 |
|------|------|------|
| 하위 5% PnL | > 0 | 95% 확률로 수익 |
| 하위 5% PnL | < 0이지만 > -3% | 약간 위험하지만 허용 |
| 하위 5% PnL | < -3% | 운에 의존하는 전략, 경고 |
| 최악 MDD | < 15% | 허용 범위 |
| 최악 MDD | > 20% | 리스크 과다, 사이징 축소 필요 |

### 실행 주기
- 매주 일요일 01:00 KST (주간 리뷰와 함께)
- 1,000회 시뮬레이션 소요시간: ~30초 (8코어)
- 텔레그램 리포트에 포함

## 4. 파라미터 민감도 분석 (주간)

### 개념
현재 파라미터를 ±10% 범위에서 변화시켜 성과 변화를 측정.
"이 파라미터가 조금만 바뀌어도 성과가 크게 변하면 불안정하다."

### 구현
```python
# 현재 파라미터
current_params = {
    "rsi_lower": 52, "rsi_upper": 70,
    "atr_mult": 2.0, "cutoff": 72, ...
}

# 각 파라미터를 ±10% 변화
for param_name, base_value in current_params.items():
    results = []
    for delta in [-0.10, -0.05, 0, +0.05, +0.10]:
        test_params = current_params.copy()
        test_params[param_name] = base_value * (1 + delta)
        perf = backtest(test_params, days=30)
        results.append(perf.sharpe)

    sensitivity = std(results) / mean(results)  # 변동계수
    # sensitivity > 0.3이면 "민감" → 주의
    # sensitivity < 0.1이면 "견고" → 안심
```

### 판정 기준
| 민감도 (CV) | 판정 | 의미 |
|------------|------|------|
| < 0.1 | 견고 | 파라미터 변화에 안정적 |
| 0.1 ~ 0.3 | 보통 | 정상 범위 |
| > 0.3 | 민감 | 약간만 바뀌어도 성과 급변, 과적합 가능 |
| > 0.5 | 위험 | 해당 파라미터에 과의존, 전략 재검토 필요 |

### 실행 주기
- 매주 일요일 01:30 KST
- 파라미터 10개 × 5개 변이 × 30일 백테스트 = ~50회 백테스트
- 소요시간: ~2분 (8코어 병렬)

## 5. 장기 시장 데이터 축적

### 수집 대상
| 데이터 | 주기 | 저장 위치 | 연간 크기 |
|--------|------|----------|----------|
| 5M 캔들 | 매 5분 | market_data.db | ~200MB |
| 15M 캔들 | 매 15분 | market_data.db | ~70MB |
| 1H 캔들 | 매 1시간 | market_data.db | ~20MB |
| 호가창 스냅샷 | 매 15분 (사이클마다) | market_data.db | ~500MB |
| 체결가 vs 신호가 | 매 거래 | journal.db | ~10MB |

### 활용
- **지금**: 5M 캔들로 스캘핑(전략 D) 진입 타이밍 정밀화
- **3개월 후**: 실제 데이터 리플레이 백테스트 (시뮬레이션이 아닌 실데이터)
- **6개월 후**: 슬리피지 모델을 실측 기반으로 정밀 보정
- **1년 후**: 시간대/국면/Tier별 패턴 분석의 신뢰도 극대화

### DB 스키마 (market_data.db)
```sql
CREATE TABLE candles (
    symbol TEXT,
    interval TEXT,  -- '5m', '15m', '1h'
    timestamp INTEGER,
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    PRIMARY KEY (symbol, interval, timestamp)
);

CREATE TABLE orderbook_snapshots (
    symbol TEXT,
    timestamp INTEGER,
    bids TEXT,  -- JSON: [[price, qty], ...]
    asks TEXT,  -- JSON: [[price, qty], ...]
    spread_pct REAL,
    PRIMARY KEY (symbol, timestamp)
);
```

### 정리 정책
- 5M 캔들: 6개월 보관 후 자동 삭제
- 15M/1H 캔들: 영구 보관
- 호가창 스냅샷: 3개월 보관 후 자동 삭제

## 6. 상관관계 모니터링

### 개념
10개 코인 간 수익률 상관관계를 실시간 추적.
높은 상관관계 코인을 동시 보유하면 분산 효과가 사라짐.

### 구현
```python
# 매 사이클: 20일 롤링 상관관계 매트릭스 계산
returns = {}
for coin in target_coins:
    returns[coin] = calc_daily_returns(coin, days=20)

corr_matrix = calc_correlation_matrix(returns)  # 10×10

# 진입 전 확인
def check_correlation(new_coin, active_positions):
    for pos in active_positions:
        corr = corr_matrix[new_coin][pos.symbol]
        if corr > 0.85:
            return "SKIP"      # 진입 스킵
        elif corr > 0.70:
            return "HALF"      # 포지션 크기 50% 축소
    return "OK"
```

### 적용
| 상관계수 | 조치 |
|---------|------|
| > 0.85 | 진입 스킵 (이미 비슷한 코인 보유 중) |
| 0.70 ~ 0.85 | 포지션 크기 50% 축소 |
| < 0.70 | 정상 진입 |

### 실행
- 상관관계 매트릭스: 매일 00:00 재계산 (20일 롤링)
- 진입 시 확인: 매 사이클 Layer 3에서 체크
- 텔레그램: 주간 리포트에 상관관계 히트맵 요약 포함

## 7. 통합 검증 리포트 (주간)

주간 DeepSeek 분석에 아래 검증 결과를 함께 패키징:

```
📊 주간 검증 리포트
━━━━━━━━━━━━━━━━━━
[Walk-Forward] 4/4 통과 ✓ (모든 구간 수익)
[Monte Carlo]  하위5% PnL: +1.2%, 최악MDD: 11.3%
[민감도]       RSI: 견고(0.08), ATR배수: 보통(0.21), 컷오프: 민감(0.35)⚠
[상관관계]     BTC-ETH: 0.82, 기타 모두 <0.7
[데이터 축적]  5M: 42,000봉, 호가창: 8,400건
━━━━━━━━━━━━━━━━━━
```
