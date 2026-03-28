# Dashboard Design Review Report

**검수일:** 2026-03-28 (2차 검수 완료)
**대상:** Stitch MCP 생성 6개 페이지 vs DASHBOARD_BLUEPRINT.md + 실제 코드베이스 + configs/config.yaml
**Stitch 프로젝트 ID:** 6115074138076030650
**검수 라운드:** 1차 (11건 발견, 수정) → 2차 (10건 추가 발견, 수정)

---

## 1. 정확하게 반영된 항목 (통과)

| 항목 | 소스 코드 위치 | 판정 |
|------|--------------|------|
| Health Monitor 8개 체크 이름 및 가중치 (총 100점) | `app/health_monitor.py:52-61` | 정확 |
| Pool 3종 (ACTIVE 50%, CORE 40%, RESERVE 10%) | `strategy/pool_manager.py` | 정확 |
| Regime 5단계 | `strategy/regime_classifier.py` | 정확 |
| TREND_FOLLOW Score 5축 (30+25+20+15+10=100) | `strategy/strategy_scorer.py` | 정확 |
| CompositeScore 8축 | `strategy/darwin_engine.py` | 정확 |
| Shadow 3그룹 (conservative/moderate/innovative) | `strategy/darwin_engine.py:185-196` | 정확 |
| Trade Tag 6종 | `strategy/trade_tagger.py:6-13` | 정확 |
| Journal 9개 테이블 | `app/journal.py` | 정확 |
| Self-Reflection 필드 | `strategy/self_reflection.py` | 정확 |
| DD Limits 4단계 (4%/8%/12%/20%) | `risk/dd_limits.py` | 정확 |
| Pool 포지션 한도 (ACTIVE 5, CORE 3, RESERVE 1) | `strategy/pool_manager.py` | 정확 |

---

## 2. 수정 완료된 불일치 항목

### CRITICAL

| ID | 페이지 | 문제 | 디자인 값 | 코드 실제 값 | 수정 내용 |
|----|--------|------|----------|------------|----------|
| C1 | P6 System | Health 게이지 임계값 | 0-40 red, 40-70 amber, 70-100 green | healthy ≥ 80, degraded 50-79, critical < 50 | 0-50 red, 50-80 amber, 80-100 green으로 수정 |
| C2 | P3 Strategy | Coin Profiler atr_stop_mult 값 반전 | TIER1=1.5, TIER3=2.5 | TIER1=2.5, TIER3=1.5 | 코드 값으로 수정. TIER1이 가장 넓은 스탑 |
| C3 | P4 Risk | Correlation을 RiskGate 독립 항목으로 표시 | 13개 게이트 | RiskGate 12개 (P1-P10+EDGE+OB). Correlation은 별도 모듈 | Correlation을 "별도 필터" 영역으로 분리, RiskGate는 12개로 수정 |

### MEDIUM

| ID | 페이지 | 문제 | 수정 내용 |
|----|--------|------|----------|
| M1 | P3 Strategy | Momentum Heatmap "Volume" 컬럼 | "Vol Ratio" (변동성 비율)로 변경 |
| M2 | P3 Strategy | TIER1 spread_limit 0.15% | 0.18%로 수정 |
| M3 | P3 Strategy | ATR 범위 부정확 | TIER1 <0.9%, TIER2 0.9-1.4%, TIER3 ≥1.4%로 수정 |
| M4 | P5 Evolution | 실험 상태 "accepted" | "keep"으로 변경 |
| M5 | P4 Risk | Spread가 독립 항목 | OB 필터에 통합 표시 |
| M6 | P4 Risk | P10 Cooldown 누락 | P10 Cooldown (60분) 항목 추가 |
| M7 | P3 Strategy | Decision Flow L1 라벨 부정확 | 실제 체크명으로 변경: regime/volume/spread/time(Tier3)/momentum_burst |

### MINOR (허용 가능)

| ID | 설명 |
|----|------|
| m1 | Trade 테이블: 23개 필드 중 주요 항목만 표시 — UI 밀도상 합리적 |
| m2 | 전략별 Score 축 개수 상이 (TREND 5개, MEAN_REV 4개 등) — 동적 렌더링 필요 |
| m3 | Backtest Schedule 시간은 config 의존 — 하드코딩 아닌 동적 표시 |

### 임의 데이터

| ID | 항목 | 수정 |
|----|------|------|
| A1 | Page 1 헤더 "RUN_MODE: AGGRESSIVE" | RunMode는 DRY/PAPER/LIVE만 존재. "LIVE"로 수정 |

---

## 3. 코드 참조 맵 (구현 시 데이터 바인딩)

### Page 1: Overview
| 컴포넌트 | 데이터 소스 |
|----------|-----------|
| KPI Cards | `journal.trades` 집계 + `DDLimits` 실시간 |
| Equity Curve | `trades.net_pnl_krw` 누적 |
| Pool Allocation | `PoolManager.get_balance()` |
| Active Positions | `StateStorage` 현재 포지션 |
| Activity Feed | `journal.signals` + `trades` + `risk_events` |

### Page 2: Trading
| 컴포넌트 | 데이터 소스 |
|----------|-----------|
| Candlestick | `market_store.candles` + `indicators.py` |
| Signal Log | `journal.signals` (symbol, direction, strategy, score, regime, tier, accepted, reject_reason) |
| Trade History | `journal.trades` (23 필드) |
| Reflections | `journal.reflections` (trade_id, tag, reflection_text, lesson) |
| Execution Quality | `journal.executions` |

### Page 3: Strategy & Intelligence
| 컴포넌트 | 데이터 소스 |
|----------|-----------|
| Regime | `RegimeClassifier` — CRISIS/STRONG_UP/WEAK_UP/WEAK_DOWN/RANGE |
| Strategy Performance | `journal.trades` GROUP BY strategy |
| Score Breakdown | `StrategyScorer.score_strategy_*()` — 전략별 축 수 다름 |
| Momentum Heatmap | `MomentumRanker.rank()` — ret_7d(0.4), ret_3d(0.3), vol_ratio(-0.2), rsi(0.1) |
| Coin Profiler | `CoinProfiler.classify()` — TIER1(<0.9%), TIER2(0.9-1.4%), TIER3(≥1.4%) |
| Decision Flow | L1: `EnvironmentFilter` (5체크) → RiskGate (12체크) → Sizing → Order |

### Page 4: Risk & Capital
| 컴포넌트 | 데이터 소스 |
|----------|-----------|
| DD Gauges | `DDLimits` (daily 4%, weekly 8%, monthly 12%, total 20%) |
| Risk Gate | `RiskGate` 12개 (P1-P10 + EDGE + OB) |
| Pool Distribution | `PoolManager` (total_balance, allocated, position_count, available) |
| Risk Events | `journal.risk_events` |
| Correlation Matrix | `CorrelationMonitor` (별도 모듈, RiskGate 밖) |

### Page 5: Evolution & Research
| 컴포넌트 | 데이터 소스 |
|----------|-----------|
| Darwin Status | `DarwinEngine` (population, generation, champion) |
| Shadow Scatter | `ShadowParams` + `CompositeScore` (8축) |
| Experiment Timeline | `experiment_store.experiments` (verdict: keep/revert) |
| Param Changes | `experiment_store.param_changes` (status: monitoring/keep/revert/rolled_back) |
| Feedback Loop | `FeedbackLoop.get_failure_patterns()` + `journal.reflections` |

### Page 6: System
| 컴포넌트 | 데이터 소스 |
|----------|-----------|
| Health Gauge | `HealthMonitor` — healthy(≥80), degraded(50-79), critical(<50) |
| Health Checks | 8개 CheckResult (name, status, message, value) |
| System Resources | `psutil` (CPU, Memory, Disk) |
| Services | `systemctl status` |
| Config | `config.yaml` |
| Logs | `journalctl -u bithumb-bot` |

---

## 4. 구현 시 주의사항

1. **Score Breakdown 레이더 차트**: 전략별 축 수가 다름
   - TREND_FOLLOW: 5축 (trend_align, macd, volume, rsi_pullback, supertrend)
   - MEAN_REVERSION: 4축 (rsi_bounce, bb_position, volume, zscore)
   - BREAKOUT: 5+1축 (breakout, volume, atr_expand, trend_1h, bb_squeeze + adx_filter 패널티)
   - SCALPING: 4축 (rsi_bounce, trend_1h, spread, volume)
   - DCA: 4축 (tier1, rsi_oversold, below_ema200, zscore)

2. **Correlation**: RiskGate 항목이 아닌 `CorrelationMonitor` 별도 호출
   - ≥0.85: 진입 차단
   - 0.70-0.85: 사이즈 50% 축소
   - <0.70: 정상

3. **L1 환경 필터 5개 체크**: regime, volume, spread, time(Tier3 심야), 1H momentum burst

4. **RiskGate 12개**: P1(인증격리), P2(총DD), P3(월DD), P4(주DD), P5(일DD), P6(총익스포저 90%), P7(전역격리), P8(종목격리), P9(연속손실 **3**회, config override), P10(쿨다운 60분), EDGE(기대수익), OB(호가잔량+스프레드)

---

## 5. 2차 검수 추가 발견 및 수정 (2026-03-28)

### CRITICAL (2차)

| ID | 페이지 | 디자인 표시 | 실제 값 | 근거 |
|----|--------|-----------|--------|------|
| C4 | P5 Evolution | Backtest: WF Sun 03:00, MC Sun 03:00, Sens Sun 03:00, Opt Sun 04:00, Research Sun 05:00 | WF **Daily 00:30**, MC **Sun 01:00**, Sens **Sun 01:30**, Opt **Sun 02:00**, Research **Sun 03:00** | `configs/config.yaml` backtest 섹션. 5개 시간 전부 틀렸고 WF는 매일 실행 |
| C5 | P6 System | Config: `active_risk=5%` | `active_risk_pct: 0.07` = **7%** | `configs/config.yaml` sizing 섹션 |
| C6 | P4 Risk | Consecutive Loss: `streak: 1/5` | `consecutive_loss_limit: 3` (config가 코드 기본값 5를 override) | `configs/config.yaml` risk_gate 섹션 |
| C7 | P5 Evolution | Composite Score 레이더 8축 동일 가중 | Config에 **5개 가중치**만: expectancy 0.3, PF 0.2, MDD 0.2, sharpe 0.2, exec_quality 0.1. sortino/calmar/consec_loss는 0 가중 | `configs/config.yaml` darwinian.composite_weights |

### MEDIUM (2차)

| ID | 페이지 | 디자인 표시 | 실제 값 | 수정 |
|----|--------|-----------|--------|------|
| M8 | P4 Risk | "P5 Daily DD 3.2% — size_mult=0.7" | `dd_mult`는 **WEEKLY** DD 기반 (>6%→0.5, 4-6%→0.7) | "P5 Weekly DD 5.1% — dd_mult=0.7"로 수정 |
| M9 | P6 System | `darwin: population=25` | `shadow_count_min: 20, max: 30`. 범위 표시 필요 | "population=20-30"으로 수정 |
| M10 | P2 Trading | "21개 필드" 표기 | 실제 `trades` 테이블 **23**개 컬럼 | 문서 오류 (Blueprint 자체 문제) |
| M11 | P2 Trading | Signal Log에 score/regime/tier만 | Signal 스키마에 entry_price, stop_loss, take_profit도 존재 | 구현 시 선택 표시 가능 |
| M12 | P6 System | health_checks 날짜 형식 가정 | `health_checks.created_at`과 `reflections.created_at`은 **TEXT** (datetime), 나머지 테이블은 **INTEGER** (ms) | 대시보드 쿼리 시 타입 분기 필요 |
| M13 | P4 Risk | Risk Event "size_mult" 표기 | `size_mult`는 `RiskGate`가 아닌 `PositionManager._calc_dd_mult()`에서 계산 | 소스 모듈 혼동 방지 위해 "dd_mult"로 용어 변경 |

### 2차 Stitch 수정 완료

| 페이지 | 수정 ID | 수정 내용 | 새 스크린 ID |
|--------|---------|----------|-------------|
| P5 Evolution | C4 | Backtest 스케줄 5개 시간 전부 수정 (WF Daily 00:30 등) | `2399a79b` |
| P5 Evolution | C7 | Composite Score 레이더에 "config: 5 weighted" 표시, 비활성 축 dimmed | `2399a79b` |
| P4 Risk | C6 | Consecutive Loss 3/3으로 수정 | `8b4f621d` |
| P4 Risk | M8+M13 | Risk Event "Weekly DD 5.1% — dd_mult=0.7"로 수정 | `8b4f621d` |
| P6 System | C5 | active_risk=7%로 수정 | `146ca0b1` |
| P6 System | M9 | population=20-30 범위 표시 | `146ca0b1` |

### 잔여 사항 (구현 시 참고, 디자인 수정 불필요)

| ID | 내용 | 비고 |
|----|------|------|
| m4 | `health_checks.created_at` TEXT vs INTEGER 타입 혼재 | 대시보드 DB 쿼리 레이어에서 처리 |
| m5 | Signal 상세에 entry_price/SL/TP 추가 가능 | 프론트엔드 확장 시 반영 |
| m6 | Trade 테이블 23개 필드 중 표시 컬럼 선택 | UI 밀도상 합리적 |
| m7 | OrderStatus에 CANCEL_REQUESTED 상태 존재 | 주문 추적 UI에서만 관련 |
| m8 | Sizing flow: opportunity→defense(regime×dd×loss_streak)→cap→corr→pilot→final | P2 확장 패널에 반영 필요 |

## 6. 최종 완성도

| 등급 | 1차 | 2차 | 누적 발견 | 수정 완료 | 미수정 |
|------|-----|-----|----------|----------|--------|
| CRITICAL | 3 | 4 | **7** | 7 | 0 |
| MEDIUM | 7 | 6 | **13** | 11 | 2 (m10-m11, 디자인 아닌 구현 이슈) |
| MINOR | 3+1 | 5 | **9** | 0 | 9 (허용 가능) |
