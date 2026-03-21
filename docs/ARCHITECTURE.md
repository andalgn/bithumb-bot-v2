# 아키텍처 명세

## 오케스트레이터 패턴

```
main.py (오케스트레이터, ~200줄)
  ├── MarketAnalyzer       ← 데이터 수집 + 지표 계산 + Tier 분류
  │   └── MarketStore      ← 5M/15M/1H 캔들 + 호가창 장기 축적
  ├── SignalGenerator      ← 국면 분류 + 전략별 점수제 신호 생성
  ├── CorrelationMonitor   ← 코인 간 상관관계 (20일 롤링)
  ├── RiskGate             ← 통합 리스크 게이트웨이 (모든 주문 필수 경유)
  ├── PoolManager          ← 3풀 자금 배분 + Pool 기반 사이징
  ├── ExecutionEngine      ← 주문 + 부분청산 + 트레일링
  ├── PromotionManager     ← 승격 판정 + 보호기간 + 강등
  ├── DarwinEngine         ← Shadow 20~30개 + 주간 토너먼트
  ├── ReviewEngine         ← 일일 규칙 리뷰 + 주간 DeepSeek 분석
  └── BacktestDaemon       ← Walk-Forward + Monte Carlo + 민감도 (백그라운드)
```

## 15분 주기 메인 루프

```
[매 15분 사이클]

1. MarketAnalyzer
   Bithumb API → DataFeed (TTL 60초)
   → MarketSnapshot (15M/1H 캔들 + 현재가 + 호가창)
   → Indicators (RSI, MACD, ATR, SuperTrend, OBV, BB, ADX, EMA20/50/200)
   → CoinProfiler: Tier 자동 분류 (매일 00:00 갱신)

2. SignalGenerator
   → classify_regime(): 5단계 국면 판정 (1H 캔들 기준)
   → 보조 플래그: RANGE_VOLATILE, DOWN_ACCEL
   → 히스테리시스 적용 (3봉 확인, 6봉 재전환 금지)
   → 전략별 점수 계산 (A/B/C/D/E 독립 점수표, A/E 활성, B/C/D 비활성)

3. RiskGate (Layer 3)
   → P0~P10 우선순위 체크
   → Expected Edge > 0 확인
   → 호가 잔량 필터 (Tier별 차등)
   → DD Kill Switch, 격리, 쿨다운

4. PoolManager + PositionManager
   → Pool 기반 사이징 (Active: 잔액×3%, Core: 잔액×10%)
   → 2단계: 기회 × defense[0.3~1.0]

5. ExecutionEngine
   → 주문 생성/체결/취소/재시도
   → 부분 청산 + 트레일링 스톱

6. PromotionManager (매 사이클)
   → Active 포지션 승격 조건 확인
   → Core 보호기간/강등/추가매수

7. DarwinEngine (매 사이클, 경량)
   → Shadow: "이 파라미터였으면 진입했을까?" 기록

8. Journal + Telegram
   → 거래 기록 (Trade Schema 21필드)
   → 알림 발송
```

## 빗썸 API 참조

빗썸 REST API를 사용하여 시장 데이터 조회 및 주문 실행.

### 인증
- HMAC-SHA512 서명 방식
- API Key + Secret Key 사용
- 요청마다 nonce(timestamp) 포함
- Content-Type: application/x-www-form-urlencoded

### 주요 엔드포인트
```
[Public API - 인증 불필요]
GET /public/ticker/{coin}_KRW          현재가 정보
GET /public/orderbook/{coin}_KRW       호가창
GET /public/candlestick/{coin}_KRW/{interval}  캔들 데이터
  interval: 1m, 3m, 5m, 10m, 15m, 30m, 1h, 6h, 12h, 24h

[Private API - 인증 필요]
POST /info/balance                     잔고 조회
POST /info/orders                      주문 내역
POST /info/order_detail                주문 상세
POST /trade/place                      주문 실행
  - order_currency, payment_currency, units, price, type(bid/ask)
POST /trade/cancel                     주문 취소
POST /trade/market_buy                 시장가 매수
POST /trade/market_sell                시장가 매도
```

### 주요 제약
- API 호출 제한: 초당 15회 (Public), 초당 10회 (Private)
- 최소 주문금액: 5,000 KRW
- 캔들 데이터: 최근 1,000개까지 조회 가능
- 주문 타임아웃: 자체 관리 필요 (거래소 타임아웃 없음)

### 주문 상태 머신 (FSM)
```
NEW → PLACED → PARTIAL → FILLED
       ↓
 CANCEL_REQUESTED → CANCELED
                  → FAILED
                  → REJECTED
                  → EXPIRED
```

## 데이터 저장

| 파일 | 형식 | 내용 |
|------|------|------|
| `data/app_state.json` | JSON | DD 상태, Pool 잔액, 런타임 플래그 |
| `data/journal.db` | SQLite (WAL) | signals, executions, risk_events, shadow_trades, backtest_results |
| `data/market_data.db` | SQLite | 장기 시장 데이터 (5M/15M/1H 캔들 + 호가창 스냅샷) |
| `data/order_tickets.json` | JSON | 주문 티켓 (active + terminal) |
| `data/quarantine_state.json` | JSON | 격리 상태 |
| `configs/config.yaml` | YAML | 전략/리스크/실행 설정 |
| `.env` | ENV | API 키, 텔레그램 토큰 |

## 운영 모드
| 모드 | 설명 | 주문 실행 |
|------|------|----------|
| DRY | 분석만 수행 | 없음 |
| PAPER | 시뮬레이션 | 가상 체결 (즉시 체결 가정) |
| LIVE | 실제 빗썸 API | 실제 주문 |

## 모듈 구현 매트릭스

| 모듈 | 단계 | 설명 |
|------|------|------|
| `market/bithumb_api.py` | 1 | 빗썸 REST 클라이언트, HMAC 인증, 비동기 |
| `market/datafeed.py` | 1 | 캔들 수집(5M/15M/1H) + TTL 캐시 60초 |
| `market/normalizer.py` | 1 | 가격/수량 정규화, 최소주문금액 5,000원 |
| `market/market_store.py` | 1 | 장기 데이터 축적 (market_data.db) |
| `execution/order_manager.py` | 1 | FSM 기반 주문 관리, 30초 타임아웃 |
| `execution/reconciler.py` | 1 | 거래소↔로컬 상태 동기화 |
| `execution/quarantine.py` | 1 | 종목/전역 격리 |
| `risk/dd_limits.py` | 1 | DD Kill Switch |
| `risk/risk_gate.py` | 1 | 통합 리스크 게이트 P0~P10 |
| `app/main.py` | 1 | 오케스트레이터 |
| `app/config.py` | 0 | 설정 로딩 |
| `app/journal.py` | 1 | Trade Schema 21필드 |
| `app/notify.py` | 0 | 텔레그램 알림 |
| `app/storage.py` | 1 | JSON 영속화 |
| `strategy/indicators.py` | 1 | 기술적 지표 전체 |
| `strategy/rule_engine.py` | 2 | 5국면 + 5전략 + 점수제 (A/E 활성, B/C/D 비활성) |
| `strategy/coin_profiler.py` | 2 | 자동 Tier 분류 |
| `strategy/pool_manager.py` | 3 | 3풀 자금 관리 |
| `strategy/position_manager.py` | 3 | Pool 기반 사이징 |
| `strategy/promotion_manager.py` | 3 | 승격/강등 |
| `execution/partial_exit.py` | 4 | 부분 청산 |
| `strategy/darwin_engine.py` | 5 | Shadow 20~30개 + 토너먼트 |
| `strategy/review_engine.py` | 6 | 일일/주간 리뷰 |
| `strategy/correlation_monitor.py` | 2 | 코인 간 상관관계 (20일 롤링) |
| `backtesting/backtest.py` | 5 | 기본 백테스터 |
| `backtesting/walk_forward.py` | 5 | Walk-Forward 검증 (매일 자동) |
| `backtesting/monte_carlo.py` | 5 | Monte Carlo 1,000회 시뮬 (주간) |
| `backtesting/sensitivity.py` | 5 | 파라미터 민감도 분석 (주간) |
| `backtesting/daemon.py` | 5 | 백테스트 검증 데몬 |
| `backtesting/optimizer.py` | 5 | 파라미터 최적화 엔진 |
| `backtesting/param_grid.py` | 5 | 파라미터 그리드 정의 |
| `strategy/auto_researcher.py` | 6 | 자율 연구 엔진 (DeepSeek 기반) |
| `app/live_gate.py` | 7 | LIVE 승인 자동 검증 |

## 대상 코인 (10개)
BTC/KRW, ETH/KRW, XRP/KRW, SOL/KRW, RENDER/KRW,
VIRTUAL/KRW, EIGEN/KRW, ONDO/KRW, TAO/KRW, LDO/KRW
