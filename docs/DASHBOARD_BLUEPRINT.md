# Bithumb Bot v2 - Dashboard Blueprint

**작성일:** 2026-03-28
**목적:** 트레이딩 봇의 모든 데이터를 전문적으로 시각화하는 대시보드 설계 및 구현 보고서

---

## 1. Executive Summary

### 1.1 목표
봇의 **모든 운영 데이터**를 한눈에 보여주는 전문 트레이딩 대시보드 구축.
시스템 건강, 전략/지표, 의사결정 흐름, 거래내역, 포지션, 리스크, 자율연구, 백테스팅, Darwin 진화 등
봇이 생산하는 모든 정보를 실시간으로 모니터링.

### 1.2 권장 기술 스택

| 구분 | 기술 | 근거 |
|------|------|------|
| **Backend API** | FastAPI (기존 봇과 동일) | 비동기, WebSocket 네이티브, 봇 프로세스와 데이터 공유 |
| **Frontend** | React 18 + TypeScript | CLAUDE.md에 명시된 대시보드 스택, 최대 커스터마이징 |
| **차트** | TradingView lightweight-charts (가격) + Recharts (지표) | 전문 트레이딩 급 성능, 45KB 번들 |
| **UI 프레임워크** | Tailwind CSS + shadcn/ui | 현대적 디자인 시스템, 다크모드 기본 |
| **실시간 통신** | WebSocket (주문/포지션) + SSE (가격) + Polling (헬스) | 데이터 특성별 최적 프로토콜 |
| **배포** | systemd 서비스 (봇과 동일 머신) | 24시간 무중단, 브라우저 접속 |

### 1.3 대안 비교

| 옵션 | 장점 | 단점 | 판정 |
|------|------|------|------|
| **FastAPI + React** | 최대 커스터마이징, 전문 UI, lightweight-charts | JS/TS 필요 (Claude Code 생성 가능) | **채택** |
| **Dash (Plotly)** | Python만으로 구현, 빠른 개발 | UI 커스터마이징 제한, 콜백 패턴 복잡 | 대안 (빠른 프로토타입) |
| **NiceGUI** | 모던 Python-first | 금융 대시보드 사례 부족 | 보류 |
| **Streamlit** | 최소 코드 | 실시간 부적합 (전체 리런) | 부적합 |
| **Electron/Tauri** | 네이티브 데스크탑 | 불필요한 복잡도, 서버사이드 봇에 부적합 | 부적합 |

---

## 2. 데이터 소스 인벤토리

봇이 생산하는 **모든 데이터**를 대시보드에서 활용할 수 있다.

### 2.1 데이터베이스 (SQLite)

#### `data/bot.db` — 상태 저장소
| 테이블 | 스키마 | 용도 |
|--------|--------|------|
| `app_state` | key, value(JSON), updated_at | 포트폴리오, 포지션, 풀 배분, 설정 |

#### `data/journal.db` — 거래 기록 (9개 테이블)
| 테이블 | 주요 필드 | 보존 | 대시보드 용도 |
|--------|-----------|------|---------------|
| `trades` | trade_id, symbol, strategy, tier, regime, pool, entry/exit_price, net_pnl_krw/pct, hold_seconds, exit_reason, tag (21필드) | 365일 | 거래내역, P&L 분석, 전략 성과 |
| `signals` | symbol, direction, strategy, score, regime, tier, accepted, reject_reason | 90일 | 시그널 품질 분석, 의사결정 근거 |
| `executions` | trade_id, ticket_id, side, price, filled_price, status | 90일 | 체결 품질, 슬리피지 분석 |
| `risk_events` | event_type, priority, symbol, detail | 90일 | 리스크 게이트 트리거 이력 |
| `shadow_trades` | shadow_id, strategy, params_json, signal_score | 90일 | Darwin 가상 거래 |
| `backtest_results` | test_type, verdict, details | 90일 | 백테스트 결과 |
| `feedback` | trade_id, feedback_type, content | 90일 | 거래 피드백 |
| `health_checks` | score, verdict, results_json, alerts_json | 90일 | 시스템 건강 이력 |
| `reflections` | trade_id, tag, reflection_text, lesson | 90일 | 자가 반성, 학습 |

#### `data/market_data.db` — 시장 데이터
| 테이블 | 주요 필드 | 보존 | 대시보드 용도 |
|--------|-----------|------|---------------|
| `candles` | symbol, interval(5m/15m/1h), OHLCV | 5m=180일, 15m/1h=영구 | 캔들차트, 기술지표 |
| `orderbook_snapshots` | symbol, bids/asks(JSON), spread_pct | 90일 | 유동성 분석 |

#### `data/experiment_history.db` — 실험 기록
| 테이블 | 주요 필드 | 대시보드 용도 |
|--------|-----------|---------------|
| `experiments` | source, strategy, params, pf, mdd, verdict | 자율연구 결과 |
| `shadow_trades` | virtual_pnl, signal_score | Darwin 진화 추적 |
| `param_changes` | old/new_params, status(monitoring/accepted/reverted) | 파라미터 변경 이력 |

### 2.2 런타임 데이터 (메모리)

| 데이터 | 소스 모듈 | 주기 | 대시보드 용도 |
|--------|-----------|------|---------------|
| 현재 포지션 | `Position` (data_types) | 실시간 | 포지션 현황 |
| 풀 상태 | `PoolManager` | 5분 | 자금 배분 |
| 국면 분류 | `RuleEngine` (RegimeClassifier) | 15분 | 시장 국면 표시 |
| 헬스 점수 | `HealthMonitor` (8개 체크) | 15분 | 시스템 상태 |
| DD 상태 | `DDLimits` | 실시간 | 드로다운 게이지 |
| 리스크 게이트 | `RiskGate` (10개 체크) | 매 진입 시 | 리스크 상태 |
| 코인 유니버스 | `CoinUniverse` | 1시간 | 활성 코인 목록 |
| 모멘텀 순위 | `MomentumRanker` | 15분 | 코인 랭킹 |
| 티어 분류 | `CoinProfiler` | 일간 | 코인 특성 |
| Shadow 인구 | `DarwinEngine` | 주간 | 진화 상태 |
| 주문 상태 | `OrderManager` (FSM) | 실시간 | 주문 추적 |

### 2.3 핵심 데이터 타입

```
RunMode:    DRY | PAPER | LIVE
Regime:     STRONG_UP | WEAK_UP | RANGE | WEAK_DOWN | CRISIS
Tier:       TIER1 | TIER2 | TIER3
Strategy:   TREND_FOLLOW | MEAN_REVERSION | BREAKOUT | SCALPING | DCA
Pool:       ACTIVE | CORE | RESERVE
OrderStatus: NEW → PLACED → PARTIAL → FILLED/CANCELED/FAILED/EXPIRED
ExitReason: TP | SL | TRAILING | TIME | REGIME | MANUAL | CRISIS | DEMOTION
TradeTag:   winner | regime_mismatch | timing_error | sizing_error | signal_quality | external
```

---

## 3. 대시보드 구조 설계

### 3.1 전체 레이아웃

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Header Bar                                                              │
│ [Bot Status] [Run Mode] [Equity ₩] [Daily P&L] [Health Score] [Clock]  │
├────────┬────────────────────────────────────────────────────────────────┤
│        │                                                                │
│  Side  │  Main Content Area (탭 기반)                                   │
│  Nav   │                                                                │
│        │  ┌──────────────────────────────────────────────────────────┐  │
│  📊    │  │ 현재 선택된 페이지 콘텐츠                                 │  │
│  Over  │  │                                                          │  │
│  view  │  │                                                          │  │
│        │  │                                                          │  │
│  📈    │  │                                                          │  │
│  Trad  │  │                                                          │  │
│  ing   │  │                                                          │  │
│        │  │                                                          │  │
│  🧠    │  │                                                          │  │
│  Strat │  │                                                          │  │
│  egy   │  │                                                          │  │
│        │  │                                                          │  │
│  ⚠️    │  │                                                          │  │
│  Risk  │  │                                                          │  │
│        │  │                                                          │  │
│  🧬    │  │                                                          │  │
│  Evol  │  │                                                          │  │
│  ution │  │                                                          │  │
│        │  │                                                          │  │
│  🔧    │  │                                                          │  │
│  Syst  │  │                                                          │  │
│  em    │  └──────────────────────────────────────────────────────────┘  │
│        │                                                                │
└────────┴────────────────────────────────────────────────────────────────┘
```

### 3.2 페이지 구성 (6개 페이지)

---

#### Page 1: Overview (메인 대시보드)
> 봇의 현재 상태를 한눈에 파악

```
┌──────────────────────────────────────────────────────────────┐
│ KPI Cards Row                                                │
│ [총 자산 ₩] [일일 P&L] [주간 P&L] [승률] [PF] [MDD %]       │
├──────────────────────────┬───────────────────────────────────┤
│ Equity Curve (Line)      │ Pool Allocation (Donut)           │
│ - 실시간 자산 추이         │ - ACTIVE/CORE/RESERVE 비율       │
│ - 30일 / 90일 / 전체      │ - 각 풀 잔고 + 사용률             │
├──────────────────────────┴───────────────────────────────────┤
│ Active Positions Table                                       │
│ Symbol | Strategy | Pool | Entry₩ | Current₩ | P&L% |       │
│        | Regime   | Tier | Size₩  | Duration | SL/TP |       │
├──────────────────────────────────────────────────────────────┤
│ Recent Activity Feed (최근 10건)                              │
│ [14:30] BTC 매수 진입 - TREND_FOLLOW, Score: 78, STRONG_UP   │
│ [14:15] ETH 매도 청산 - TP 도달, +2.3%, 4시간 보유            │
│ [14:00] Risk Gate: SOL 진입 거부 - 일일 DD 3.5% (한도 4%)     │
└──────────────────────────────────────────────────────────────┘
```

**데이터 소스:**
- KPI: `journal.trades` 집계 + `DDLimits` 실시간
- Equity Curve: `trades.net_pnl_krw` 누적
- Pool: `PoolManager.get_balance()`
- Positions: `StateStorage` 현재 포지션
- Activity: `journal.signals` + `journal.trades` + `journal.risk_events` 최신

---

#### Page 2: Trading (거래 상세)
> 거래내역, 시그널, 체결 품질 분석

```
┌──────────────────────────────────────────────────────────────┐
│ Filters: [Period ▾] [Symbol ▾] [Strategy ▾] [Pool ▾]        │
├──────────────────────────┬───────────────────────────────────┤
│ Price Chart              │ Signal Log (시그널 이력)           │
│ - Lightweight-Charts     │ - 생성된 모든 시그널               │
│ - 캔들스틱 (5m/15m/1h)    │ - Score, Regime, Tier             │
│ - EMA 20/50/200 오버레이  │ - 수락/거부 + 거부 사유            │
│ - 진입/청산 마커           │ - 의사결정 근거 추적               │
│ - 볼린저밴드, RSI 서브차트 │                                   │
├──────────────────────────┴───────────────────────────────────┤
│ Trade History Table (완료 거래)                               │
│ ID | Symbol | Strategy | Entry Time | Exit Time | Hold |     │
│    | Entry₩ | Exit₩ | Gross P&L | Fees | Net P&L | Reason | │
│    | Regime | Tier | Pool | Score | Tag | Promoted |         │
│ ─────────────────────────────────────────────────────────── │
│ 클릭 시 거래 상세 패널 확장:                                   │
│   - 진입 시그널 상세 (score breakdown)                        │
│   - 사이징 계산 과정 (opportunity → defense 단계)              │
│   - 리스크 게이트 통과 내역                                    │
│   - 자가반성 (reflection_text + lesson)                       │
│   - 체결 상세 (슬리피지, 재시도 횟수)                          │
├──────────────────────────────────────────────────────────────┤
│ Execution Quality                                            │
│ - 평균 슬리피지 (bps)                                         │
│ - 체결 성공률                                                 │
│ - 평균 체결 시간                                              │
└──────────────────────────────────────────────────────────────┘
```

**데이터 소스:**
- Chart: `market_store.candles` + `indicators.py` 계산
- Signals: `journal.signals`
- Trades: `journal.trades` (21필드 전체)
- Reflections: `journal.reflections`
- Executions: `journal.executions`
- Sizing detail: `PositionManager.compute()` 결과 (SizingResult.detail)

---

#### Page 3: Strategy & Intelligence (전략 및 지표)
> 전략 성과, 국면 분류, 모멘텀, 의사결정 구조

```
┌──────────────────────────────────────────────────────────────┐
│ Market Regime Panel                                          │
│ ┌─────────┬─────────┬─────────┬─────────┬─────────┐         │
│ │STRONG_UP│ WEAK_UP │  RANGE  │WEAK_DOWN│ CRISIS  │         │
│ │   ●     │         │         │         │         │ ← 현재   │
│ └─────────┴─────────┴─────────┴─────────┴─────────┘         │
│ 국면 전환 이력 (타임라인): RANGE → STRONG_UP (3시간 전)        │
│ 근거: EMA20>50>200 정렬, ADX=32 (≥25), BTC +4.2% 24h       │
├──────────────────────────┬───────────────────────────────────┤
│ Strategy Performance     │ Score Breakdown                   │
│ (전략별 성과 비교)        │ (선택 전략의 점수 구성)            │
│                          │                                   │
│ Strategy  | Trades | WR% │ TREND_FOLLOW Score: 78/100        │
│ TREND_FOL | 45     | 62% │ ├─ trend_align: 28/30 (93%)      │
│ MEAN_REV  | 32     | 48% │ ├─ macd:        20/25 (80%)      │
│ DCA       | 12     | 75% │ ├─ volume:      15/20 (75%)      │
│ BREAKOUT  | 8      | 38% │ ├─ rsi_pullback: 10/15 (67%)     │
│                          │ └─ supertrend:   5/10  (50%)     │
│ PF / Expect / Sharpe     │                                   │
├──────────────────────────┼───────────────────────────────────┤
│ Momentum Heatmap         │ Coin Profiler                     │
│ (코인 간 모멘텀 순위)     │ (티어 분류 현황)                   │
│                          │                                   │
│      7D   3D   Vol  RSI  │ BTC:  TIER1 (ATR 0.8%)           │
│ BTC  ██   ██   ░░   ██   │ ETH:  TIER2 (ATR 1.1%)           │
│ ETH  ██   ░░   ██   ░░   │ SOL:  TIER3 (ATR 1.8%)           │
│ SOL  ░░   ██   ██   ██   │                                   │
│ XRP  ░░   ░░   ░░   ██   │ → 티어별 파라미터 차이 표시        │
│                          │   (spread_limit, atr_stop_mult)   │
├──────────────────────────┴───────────────────────────────────┤
│ Decision Flow Diagram (의사결정 흐름도)                        │
│                                                              │
│ 시그널 생성 → L1 환경 필터 → 리스크 게이트 → 사이징 → 주문    │
│     ↓            ↓              ↓            ↓         ↓     │
│  score=78    spread OK      DD 3.5%<4%   ₩500K    PLACED    │
│  TREND_FOL   depth OK      corr OK      defense   FILLED    │
│  STRONG_UP   edge OK       streak OK    ×0.8               │
│                                                              │
│ 각 단계별 통과/거부 비율 통계                                  │
└──────────────────────────────────────────────────────────────┘
```

**데이터 소스:**
- Regime: `RegimeClassifier` 결과 + `rule_engine.py` 로직
- Strategy Performance: `journal.trades` GROUP BY strategy
- Score Breakdown: `StrategyScorer.score_strategy_*()` 결과
- Momentum: `MomentumRanker.rank()` 결과
- Coin Profiler: `CoinProfiler.classify()` 결과
- Decision Flow: `signals` (생성) + `risk_events` (게이트) + `executions` (체결)

---

#### Page 4: Risk & Capital (리스크 및 자금)
> 드로다운, 리스크 게이트, 자금 배분

```
┌──────────────────────────────────────────────────────────────┐
│ Drawdown Gauges (원형 게이지 4개)                             │
│ ┌──────────┬──────────┬──────────┬──────────┐                │
│ │ Daily DD │Weekly DD │Monthly DD│ Total DD │                │
│ │  3.2%    │  5.1%    │  7.3%    │  12.4%   │                │
│ │  /4.0%   │  /8.0%   │  /12.0%  │  /20.0%  │                │
│ │  [■■■░]  │  [■■░░]  │  [■■░░]  │  [■■░░░] │                │
│ └──────────┴──────────┴──────────┴──────────┘                │
├──────────────────────────┬───────────────────────────────────┤
│ Risk Gate Status         │ Pool Distribution                 │
│ (10개 게이트 상태)        │ (3풀 상세 현황)                    │
│                          │                                   │
│ Gate           Status    │ ACTIVE (50%)                      │
│ ─────────────────────── │ ├─ 잔고: ₩5,000,000              │
│ Auth Quarant.  ● OK     │ ├─ 사용중: ₩3,200,000 (64%)      │
│ Global Quara.  ● OK     │ ├─ 포지션: 3/5                    │
│ Coin Quarant.  ● OK     │ └─ 가용: ₩1,800,000              │
│ Consec. Loss   ● OK     │                                   │
│ Daily DD       ⚠ 80%    │ CORE (40%)                        │
│ Weekly DD      ● OK     │ ├─ 잔고: ₩4,000,000              │
│ Monthly DD     ● OK     │ ├─ 사용중: ₩2,500,000 (63%)      │
│ Total DD       ● OK     │ ├─ 포지션: 2/3                    │
│ Max Exposure   ● OK     │ └─ 가용: ₩1,500,000              │
│ Expectancy     ⚠ LOW    │                                   │
│ OB Depth       ● OK     │ RESERVE (10%)                     │
│ Spread         ● OK     │ ├─ 잔고: ₩1,000,000              │
│ Correlation    ● OK     │ └─ 포지션: 0/1                    │
├──────────────────────────┴───────────────────────────────────┤
│ Risk Event Timeline (리스크 이벤트 타임라인)                   │
│ [14:30] P5 Daily DD 3.2% - ETH 진입 size_mult=0.7 적용      │
│ [13:45] P3 Coin Quarantine - SOL API timeout (120s 격리)     │
│ [12:00] P4 Consec. Loss Reset - 연패 카운터 0으로 리셋        │
├──────────────────────────────────────────────────────────────┤
│ Correlation Matrix (상관관계 히트맵)                           │
│         BTC   ETH   SOL   XRP                                │
│ BTC     1.0   0.87  0.72  0.65                               │
│ ETH     0.87  1.0   0.78  0.61                               │
│ SOL     0.72  0.78  1.0   0.54                               │
│ XRP     0.65  0.61  0.54  1.0                                │
│ → 상관도 높은 동시 진입 경고                                   │
└──────────────────────────────────────────────────────────────┘
```

**데이터 소스:**
- DD: `DDLimits` (daily/weekly/monthly/total_base, current_equity)
- Risk Gate: `RiskGate` 10개 체크 결과
- Pool: `PoolManager` (total_balance, allocated, position_count)
- Risk Events: `journal.risk_events`
- Correlation: `CorrelationMonitor`

---

#### Page 5: Evolution & Research (진화 및 자율연구)
> Darwin 엔진, 자율연구, 백테스팅, 피드백 루프

```
┌──────────────────────────────────────────────────────────────┐
│ Darwin Engine Status                                         │
│ Population: 25/30 | Generation: 14 | Last Tournament: 3일 전 │
│ Champion: shadow-07 (CompositeScore: 0.82)                   │
│ Next Promotion Window: 11일 후 (14일 쿨다운)                  │
├──────────────────────────┬───────────────────────────────────┤
│ Shadow Population        │ Composite Score Breakdown         │
│ (Scatter Plot)           │ (Radar Chart - 선택 Shadow)       │
│                          │                                   │
│ x=Profit Factor          │      Expectancy                   │
│ y=Max Drawdown           │         ●                         │
│ size=CompositeScore      │    PF ● ─── ● MDD                │
│ color=group              │        │                          │
│                          │   Sharpe● ─ ● Sortino             │
│ ● Conservative (blue)    │        │                          │
│ ● Moderate (green)       │   Calmar● ─ ● ConsecLoss         │
│ ● Innovative (orange)    │      ExecQuality                  │
│                          │                                   │
│ 호버: 파라미터 상세       │ shadow-07 vs Live 비교            │
├──────────────────────────┴───────────────────────────────────┤
│ Shadow Performance Table                                     │
│ ID    | Group    | Trades | WR%  | PF   | MDD%  | Score     │
│ sh-07 | moderate |   142  | 61%  | 1.82 | 8.3%  | 0.82 ★   │
│ sh-12 | conserv  |   128  | 58%  | 1.65 | 6.1%  | 0.79     │
│ sh-03 | innovat  |   165  | 55%  | 1.91 | 11.2% | 0.74     │
│ (LIVE)| ─        |   201  | 57%  | 1.58 | 9.5%  | 0.71     │
├──────────────────────────────────────────────────────────────┤
│ Auto Research Results                                        │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │ Experiment Timeline (최근 30일)                           │ │
│ │ ● KEEP (green) ○ REVERT (red) ◆ MONITORING (yellow)     │ │
│ │                                                          │ │
│ │ 03/15 ──●──○──●──○──○──●──○──●──◆── 03/28              │ │
│ │                                                          │ │
│ │ 성공률: 37.5% (6/16)                                     │ │
│ │ 최근 실험: mean_reversion sl_mult 3.0→3.5 (MONITORING)   │ │
│ └──────────────────────────────────────────────────────────┘ │
├──────────────────────────────────────────────────────────────┤
│ Parameter Change History (파라미터 변경 이력)                  │
│ Date     | Source      | Strategy   | Change         | Status│
│ 03/27    | auto_optim  | trend_fol  | cutoff 65→70   | accepted│
│ 03/25    | auto_resrch | mean_rev   | sl_mult 3→3.5  | monitoring│
│ 03/22    | darwin      | dca        | tp_pct 3%→2.5% | reverted│
├──────────────────────────────────────────────────────────────┤
│ Backtest Schedule & Results                                  │
│ ┌────────────────────────────────────────┐                   │
│ │ Walk-Forward: 매주 일 03:00 | 마지막: robust (4/4 pass)  │ │
│ │ Monte Carlo:  매주 일 03:00 | 마지막: safe (P5>0, MDD<15%)│ │
│ │ Sensitivity:  매주 일 03:00 | 마지막: robust (CV<0.15)   │ │
│ │ Auto-Optimize: 매주 일 04:00| 마지막: 2 params accepted  │ │
│ │ Auto-Research: 매주 일 05:00| 마지막: 1/3 experiments kept│ │
│ └────────────────────────────────────────┘                   │
├──────────────────────────────────────────────────────────────┤
│ Feedback Loop (실패 패턴 분석)                                │
│ Top Failure Patterns (30일):                                 │
│ 1. regime_mismatch (38%) — 진입 국면 ≠ 청산 국면             │
│ 2. timing_error (25%) — SL 적중 후 방향 전환                 │
│ 3. signal_quality (20%) — 방향 오판                          │
│                                                              │
│ 자가반성 최근 교훈:                                           │
│ "RANGE 국면에서 TREND_FOLLOW 진입은 score≥80일 때만 유효"     │
└──────────────────────────────────────────────────────────────┘
```

**데이터 소스:**
- Darwin: `DarwinEngine` (ShadowParams, ShadowPerformance, CompositeScore)
- Research: `experiment_store.experiments`
- Param Changes: `experiment_store.param_changes`
- Backtest: `journal.backtest_results` + `BacktestDaemon` 스케줄
- Feedback: `FeedbackLoop.get_failure_patterns()` + `journal.reflections`

---

#### Page 6: System (시스템 건강)
> 헬스 모니터, 인프라, 로그, 설정

```
┌──────────────────────────────────────────────────────────────┐
│ Health Score Gauge: 87/100 [■■■■■■■■░░] HEALTHY              │
├──────────────────────────┬───────────────────────────────────┤
│ Health Check Details     │ Health Score History              │
│ (8개 체크 항목)           │ (24시간 라인 차트)                │
│                          │                                   │
│ Check          W   Score │  100├─────────────────────       │
│ heartbeat      20  20/20 │   80├──●──●──●──●──●───●──       │
│ event_loop     10  10/10 │   60├─────────────────────       │
│ api            20  18/20 │   40├─────────────────────       │
│ data_freshness 15  12/15 │     └──────────────────────      │
│ reconciliation 15  15/15 │     0h    6h    12h   18h  24h   │
│ system_res      5   5/5  │                                   │
│ trading_met    10   7/10 │ Alerts (최근 알림)                 │
│ discord         5   0/5  │ [WARN] Discord webhook timeout   │
│                          │ [INFO] Daily DD reset at 00:00   │
├──────────────────────────┴───────────────────────────────────┤
│ System Resources                                             │
│ CPU: 23% [■■░░░░░░░░] | Memory: 4.2/8 GB [■■■■■░░░░░]     │
│ Disk: 12/128 GB [■░░░░░░░░░] | Uptime: 14d 7h 23m          │
├──────────────────────────────────────────────────────────────┤
│ Service Status                                               │
│ bithumb-bot:    ● active (running) | PID 12345 | 14d uptime │
│ xray (VPN):     ● active (running) | proxy OK               │
│ dashboard:      ● active (running) | port 8080               │
├──────────────────────────────────────────────────────────────┤
│ Configuration Overview                                       │
│ Run Mode: LIVE | Cycle: 300s | Coins: 10 (dynamic)          │
│ Sizing: active_risk=5% | pool_cap=25% | atr_sizing=ON       │
│ Risk: daily_dd=4% | weekly_dd=8% | max_exposure=90%         │
│ Darwin: population=25 | champion_cooldown=14d                │
│ Backtest: WF=Sun 03:00 | MC=Sun 03:00 | Optimize=Sun 04:00 │
├──────────────────────────────────────────────────────────────┤
│ Live Log Stream (실시간 로그)                                 │
│ 14:30:12 [INFO] Cycle #1847 started                          │
│ 14:30:13 [INFO] Fetching candles for 10 coins...             │
│ 14:30:15 [INFO] Regime: BTC=STRONG_UP, ETH=WEAK_UP          │
│ 14:30:16 [INFO] Signal: BTC TREND_FOLLOW score=78 ACCEPTED  │
│ 14:30:17 [INFO] Order PLACED: BTC BUY ₩500,000 @ 87,500,000│
└──────────────────────────────────────────────────────────────┘
```

**데이터 소스:**
- Health: `HealthMonitor` (8개 CheckResult) + `journal.health_checks`
- System: `psutil` (CPU, Memory, Disk)
- Services: `systemctl status` 결과
- Config: `config.yaml` 파싱
- Logs: `journalctl -u bithumb-bot` 스트리밍

---

## 4. 기술 아키텍처

### 4.1 시스템 아키텍처

```
┌─────────────────────────────────────────────────────┐
│                  Ubuntu Mini-PC                      │
│                                                      │
│  ┌──────────────┐    ┌───────────────────────────┐  │
│  │  Trading Bot  │    │   Dashboard Service       │  │
│  │  (systemd)    │    │   (systemd)               │  │
│  │               │    │                           │  │
│  │  main.py      │───▶│  FastAPI Backend          │  │
│  │  ├─ strategy  │    │  ├─ REST API (/api/*)     │  │
│  │  ├─ risk      │    │  ├─ WebSocket (/ws/*)     │  │
│  │  ├─ execution │    │  └─ SSE (/stream/*)       │  │
│  │  └─ darwin    │    │                           │  │
│  │               │    │  Static Files (React)     │  │
│  │  SQLite DBs ──┼───▶│  ├─ index.html            │  │
│  │  ├─ bot.db    │    │  ├─ bundle.js             │  │
│  │  ├─ journal   │    │  └─ assets/               │  │
│  │  ├─ market    │    │                           │  │
│  │  └─ experiment│    │  Port: 8080               │  │
│  └──────────────┘    └───────────────────────────┘  │
│                                                      │
│  Access: http://192.168.10.3:8080                    │
│  Remote: SSH tunnel or VPN                           │
└─────────────────────────────────────────────────────┘
```

### 4.2 데이터 통신 패턴

```
브라우저 (React)
    │
    ├── WebSocket /ws/live ──────── 실시간 데이터 (1초 간격)
    │   └─ 포지션, P&L, 주문 상태, 국면, 헬스 점수
    │
    ├── SSE /stream/prices ──────── 가격 스트림 (0.5초 간격)
    │   └─ 현재가, 변동률, 거래량
    │
    ├── REST GET /api/trades ────── 거래 이력 (온디맨드)
    ├── REST GET /api/signals ───── 시그널 이력 (온디맨드)
    ├── REST GET /api/candles ───── 캔들 데이터 (온디맨드)
    ├── REST GET /api/darwin ────── Darwin 상태 (온디맨드)
    ├── REST GET /api/research ──── 실험 이력 (온디맨드)
    ├── REST GET /api/config ────── 설정 조회 (온디맨드)
    └── REST GET /api/health ────── 헬스 상세 (10초 폴링)
```

### 4.3 Backend API 설계

```python
# app/dashboard/api.py

# === 실시간 ===
@router.websocket("/ws/live")
# → { positions, equity, pnl, regime, health_score, dd_state, pool_state }

@router.get("/stream/prices")  # SSE
# → { symbol, price, change_pct, volume } × N coins

# === 거래 ===
@router.get("/api/trades")        # ?days=30&strategy=&symbol=
@router.get("/api/trades/{id}")   # 거래 상세 + reflection + execution
@router.get("/api/signals")       # ?days=7&accepted=true
@router.get("/api/executions")    # 체결 이력

# === 전략 ===
@router.get("/api/regime")        # 현재 국면 + 전환 이력
@router.get("/api/strategy/performance")  # 전략별 집계
@router.get("/api/momentum")      # 모멘텀 순위
@router.get("/api/tiers")         # 코인 티어 분류

# === 리스크 ===
@router.get("/api/risk/state")    # DD + 리스크 게이트 상태
@router.get("/api/risk/events")   # 리스크 이벤트 이력
@router.get("/api/correlation")   # 상관관계 매트릭스
@router.get("/api/pools")         # 풀 상태

# === 진화 ===
@router.get("/api/darwin/population")   # Shadow 인구 현황
@router.get("/api/darwin/tournament")   # 최근 토너먼트 결과
@router.get("/api/research/experiments")  # 실험 이력
@router.get("/api/research/params")     # 파라미터 변경 이력

# === 시장 ===
@router.get("/api/candles/{symbol}")  # ?interval=15m&limit=200
@router.get("/api/orderbook/{symbol}")

# === 시스템 ===
@router.get("/api/health")       # 헬스 체크 상세
@router.get("/api/health/history")  # 헬스 점수 이력
@router.get("/api/system")       # CPU, 메모리, 디스크, 서비스 상태
@router.get("/api/config")       # 현재 설정
@router.get("/api/logs")         # 최근 로그 (N줄)
```

### 4.4 Frontend 구조

```
dashboard/
├── package.json
├── tsconfig.json
├── tailwind.config.ts
├── vite.config.ts
├── index.html
└── src/
    ├── main.tsx                    ← 진입점
    ├── App.tsx                     ← 라우터 + 레이아웃
    ├── api/
    │   ├── client.ts               ← API 클라이언트 (fetch wrapper)
    │   ├── websocket.ts            ← WebSocket 연결 관리
    │   └── sse.ts                  ← SSE 가격 스트림
    ├── hooks/
    │   ├── useLiveData.ts          ← WebSocket 데이터 훅
    │   ├── usePrices.ts            ← SSE 가격 훅
    │   ├── useTrades.ts            ← 거래 이력 훅
    │   └── useHealth.ts            ← 헬스 폴링 훅
    ├── pages/
    │   ├── OverviewPage.tsx        ← Page 1: 메인 대시보드
    │   ├── TradingPage.tsx         ← Page 2: 거래 상세
    │   ├── StrategyPage.tsx        ← Page 3: 전략 & 지표
    │   ├── RiskPage.tsx            ← Page 4: 리스크 & 자금
    │   ├── EvolutionPage.tsx       ← Page 5: 진화 & 연구
    │   └── SystemPage.tsx          ← Page 6: 시스템
    ├── components/
    │   ├── layout/
    │   │   ├── Header.tsx          ← 상단 바 (KPI)
    │   │   ├── Sidebar.tsx         ← 좌측 네비게이션
    │   │   └── Layout.tsx          ← 전체 레이아웃
    │   ├── charts/
    │   │   ├── CandlestickChart.tsx ← lightweight-charts 래퍼
    │   │   ├── EquityCurve.tsx      ← Recharts 라인
    │   │   ├── DrawdownGauge.tsx    ← 원형 게이지
    │   │   ├── MomentumHeatmap.tsx  ← 히트맵
    │   │   ├── RadarChart.tsx       ← 스코어 레이더
    │   │   └── CorrelationMatrix.tsx
    │   ├── tables/
    │   │   ├── PositionsTable.tsx   ← 활성 포지션
    │   │   ├── TradeHistory.tsx     ← 거래 내역
    │   │   ├── SignalLog.tsx        ← 시그널 로그
    │   │   └── ShadowTable.tsx      ← Darwin Shadow 목록
    │   ├── cards/
    │   │   ├── KpiCard.tsx         ← 단일 KPI 카드
    │   │   ├── RegimeIndicator.tsx  ← 국면 표시기
    │   │   ├── RiskGateStatus.tsx   ← 리스크 게이트
    │   │   └── PoolCard.tsx        ← 풀 상태 카드
    │   └── common/
    │       ├── StatusBadge.tsx
    │       ├── Sparkline.tsx
    │       └── TimeAgo.tsx
    ├── types/
    │   └── index.ts                ← TypeScript 타입 (Python data_types 미러)
    └── styles/
        └── globals.css             ← Tailwind + 커스텀 스타일
```

### 4.5 디자인 시스템

**다크 모드 기본** (트레이딩 대시보드 표준):
```
배경:           #0f1117 (거의 검정)
카드 배경:       #1a1d29
사이드바:        #141722
텍스트 (기본):   #e2e8f0
텍스트 (보조):   #94a3b8
수익 (양수):     #22c55e (green-500)
손실 (음수):     #ef4444 (red-500)
경고:           #f59e0b (amber-500)
위험:           #dc2626 (red-600)
강조 (액센트):   #3b82f6 (blue-500)
국면 색상:
  STRONG_UP:    #22c55e
  WEAK_UP:      #86efac
  RANGE:        #94a3b8
  WEAK_DOWN:    #fca5a5
  CRISIS:       #dc2626
```

---

## 5. 구현 계획

### 5.1 프로젝트 구조 (최종)

```
bithumb-bot-v2/
├── app/                         ← 기존 봇 코드
│   ├── main.py
│   ├── ...
│   └── dashboard_api.py         ← NEW: FastAPI 대시보드 API
├── dashboard/                   ← NEW: React 프론트엔드
│   ├── package.json
│   ├── src/
│   └── dist/                    ← 빌드 결과물
├── scripts/
│   └── bithumb-dashboard.service ← NEW: systemd 서비스
└── ...
```

### 5.2 단계별 구현

#### Phase 1: API 레이어 (1주)
- `app/dashboard_api.py` 생성
- FastAPI 라우터로 REST + WebSocket + SSE 엔드포인트 구현
- SQLite 직접 쿼리 (journal.db, market_data.db, experiment_history.db)
- 봇 런타임 데이터 접근 (SharedState 패턴 또는 별도 프로세스 DB 읽기)

#### Phase 2: 프론트엔드 기반 (1주)
- React + TypeScript + Vite 프로젝트 생성
- Tailwind CSS + shadcn/ui 설정
- 레이아웃 (Header + Sidebar + Main) 구현
- WebSocket/SSE 훅 구현
- 라우팅 (6개 페이지)

#### Phase 3: Overview 페이지 (1주)
- KPI 카드 (자산, P&L, 승률, PF, MDD)
- Equity Curve (Recharts)
- Pool Allocation (Donut Chart)
- Active Positions Table
- Recent Activity Feed

#### Phase 4: Trading 페이지 (1주)
- 캔들스틱 차트 (lightweight-charts)
- 기술지표 오버레이 (EMA, BB, RSI)
- 진입/청산 마커
- Trade History 테이블 (확장 가능)
- Signal Log
- 거래 상세 패널 (reflection, execution, sizing)

#### Phase 5: Strategy + Risk 페이지 (1주)
- Regime Indicator + 전환 타임라인
- Strategy Performance 비교 테이블
- Score Breakdown (Radar Chart)
- Momentum Heatmap
- Drawdown Gauges
- Risk Gate Status 패널
- Pool Distribution 카드

#### Phase 6: Evolution + System 페이지 (1주)
- Darwin Population Scatter Plot
- Shadow Performance Table
- Composite Score Radar
- Experiment Timeline
- Parameter Change History
- Health Score Gauge + History
- System Resources
- Config Overview
- Live Log Stream

#### Phase 7: 통합 및 배포 (1주)
- 프론트엔드 빌드 → FastAPI static files 서빙
- systemd 서비스 등록
- 프록시 설정 (필요시 Nginx)
- 성능 튜닝 (캐싱, 쿼리 최적화)
- 에러 핸들링 및 재연결 로직

### 5.3 총 소요: 약 7주

---

## 6. 핵심 기술 결정 사항

### 6.1 봇-대시보드 데이터 공유 방식

**옵션 A: 동일 프로세스** (권장)
- 대시보드 API를 봇의 FastAPI 앱에 라우터로 추가
- 봇의 런타임 객체(PoolManager, DDLimits 등)에 직접 접근
- 장점: 실시간 데이터 즉시 접근, 추가 IPC 불필요
- 단점: 봇 재시작 시 대시보드도 재시작

**옵션 B: 별도 프로세스** (대안)
- 대시보드를 독립 FastAPI 서비스로 실행
- SQLite DB만 공유 (WAL 모드로 동시 읽기 가능)
- 런타임 데이터는 봇이 주기적으로 DB에 기록
- 장점: 봇과 독립 운영
- 단점: 실시간성 약간 저하 (DB 기록 주기에 의존)

**권장: 옵션 A** — 봇이 15분 주기로 돌아가므로 대시보드를 같은 프로세스에 넣어도
CPU 부담이 미미하고, 실시간 데이터 접근이 훨씬 편리.

### 6.2 차트 라이브러리 선택

| 용도 | 라이브러리 | 근거 |
|------|-----------|------|
| 캔들스틱 (가격) | **lightweight-charts** | 45KB, TradingView급 성능, 실시간 스트리밍 |
| 지표/P&L/Equity | **Recharts** | 100KB, React 네이티브, 깔끔한 API |
| 히트맵/상관관계 | **Recharts** 또는 커스텀 | 별도 라이브러리 없이 가능 |
| 게이지 (DD) | 커스텀 SVG 또는 **Recharts** RadialBar | 간단한 구현 |

### 6.3 인증

초기 버전: 인증 없음 (로컬 네트워크 전용, `192.168.10.3:8080`)
향후: 간단한 Bearer token 또는 Basic Auth 추가 가능

---

## 7. 참고 자료

### 오픈소스 프로젝트 (우선순위)
1. **[ashwinder-bot/stock-market-dashboard](https://github.com/ashwinder-bot/stock-market-dashboard)** — FastAPI+React+SQLite, 가장 유사한 구조
2. **[nMaroulis/sibyl](https://github.com/nMaroulis/sibyl)** — AI+트레이딩 엔진 통합 패턴
3. **[sivakirlampalli/ai-trading-dashboard](https://github.com/sivakirlampalli/ai-trading-dashboard)** — FastAPI+React+TailwindCSS
4. **[ustropo/websocket-example](https://github.com/ustropo/websocket-example)** — FastAPI WebSocket+Recharts
5. **[tradingview/lightweight-charts](https://github.com/tradingview/lightweight-charts)** — 캔들스틱 차트

### 상세 조사 문서 (docs/ 디렉토리)
- `TRADING_DASHBOARD_RESEARCH.md` — 프레임워크 비교, 차트 라이브러리, 실시간 패턴 상세
- `DASHBOARD_DECISION_MATRIX.md` — 기술 선택 의사결정 매트릭스
- `DASHBOARD_GITHUB_REFERENCES.md` — 40+ GitHub 프로젝트 카탈로그
- `DASHBOARD_QUICK_START.md` — 빠른 시작 가이드 (Dash 대안 포함)

### 공식 문서
- [FastAPI WebSocket](https://fastapi.tiangolo.com/advanced/websockets/)
- [lightweight-charts API](https://tradingview.github.io/lightweight-charts/)
- [Recharts](https://recharts.org/)
- [Tailwind CSS](https://tailwindcss.com/)
- [shadcn/ui](https://ui.shadcn.com/)

---

## 8. 요약

| 항목 | 결정 |
|------|------|
| **프레임워크** | FastAPI (backend) + React + TypeScript (frontend) |
| **차트** | lightweight-charts (가격) + Recharts (지표) |
| **UI** | Tailwind CSS + shadcn/ui, 다크모드 기본 |
| **실시간** | WebSocket + SSE + Polling 하이브리드 |
| **페이지** | 6개 (Overview, Trading, Strategy, Risk, Evolution, System) |
| **배포** | 동일 머신 systemd 서비스, 브라우저 접속 |
| **일정** | 약 7주 (Phase 1~7) |
| **비용** | $0 (전체 오픈소스) |

봇이 생산하는 **9개 DB 테이블, 15+ 런타임 모듈, 100+ 메트릭**을
6개 페이지에 체계적으로 배치하여 전문 트레이딩 터미널 수준의 대시보드를 구현한다.
