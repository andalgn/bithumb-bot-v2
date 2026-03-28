# Self-Evolving Trading Systems - Quick Reference

**한국어 응답 (Korean Response Below)**

---

## One-Page Summary

### The Core Pattern (Across All Successful Systems)

```
Daily Shadow Trading (20-30 variants)
    ↓ (weekly)
Walk-Forward Validation (90-day rolling)
    ↓ (if P-value < 0.05)
Promote Best Variant
    ↓
Hard Risk Limits (Daily DD 4%, Monthly MDD 15%)
    ↓
Weekly Human + AI Review (DeepSeek/Claude)
```

**Key Finding:** No system uses continuous learning. All use discrete intervals (daily/weekly retrain from scratch).

---

## 5 Core Algorithms

| Algorithm | Use Case | Maturity | Pitfall |
|-----------|----------|----------|---------|
| **Genetic Algorithm** | Parameter evolution | ✓ Production | Local minima |
| **PPO (Reinforcement Learning)** | Autonomous adaptation | Research | Reward hacking |
| **Meta-Learning (MAML)** | Regime transfer | Research | Needs diverse training |
| **Bayesian Optimization** | Quick research | ✓ Production | Small param spaces |
| **Evolutionary Strategies (DE)** | Large search spaces | ✓ Production | Many evaluations |

**Recommendation for Bot:**
1. Use Genetic Algorithm (you have Darwin Engine)
2. Add Walk-Forward Validation (critical)
3. Experiment with PPO in shadow mode (no real capital)

---

## Validation Checklist (Before Live Trading)

- [ ] Walk-forward analysis (90-day rolling, not single backtest)
- [ ] Sharpe ratio degradation <10% from IS to OOS
- [ ] Paper trading 14-28 days (correlation >95% with backtest)
- [ ] Look-ahead bias check (code review + third-party backtest)
- [ ] Parameter sensitivity analysis (1% change should not swing P&L 10%+)
- [ ] Test on multiple coins (not just primary target)
- [ ] ≥100 trades per optimization window
- [ ] Monte Carlo simulation (1000 reshuffles)

**Red Flag:** Backtest Sharpe > 1.5 with <100 trades = likely overfitting.

---

## Safety Guardrails (Enforce at Execution Layer)

```python
# Pseudocode
def validate_order(order):
    if daily_drawdown >= 4%:
        return REJECT  # Shutdown
    if monthly_mdd >= 15%:
        return REJECT  # Shutdown
    if order.position_size > portfolio_pct(5):
        return REJECT
    if correlation_with_open_positions > 0.7:
        return REJECT
    return APPROVE
```

**Non-Negotiable Limits:**
- Max daily DD: 4% → Auto-shutdown
- Max monthly MDD: 15% → Auto-shutdown
- Max position size: 5% portfolio per trade
- Max correlation: Don't trade >2 correlated pairs

---

## Overfitting: The #1 Killer

**Real Evidence:**
- Quantopian (888 strategies): Backtest Sharpe = **zero correlation** with live returns
- Moving average: Sharpe 1.2 (in-sample) → Sharpe -0.2 (fresh data)

**Prevention (in priority order):**
1. **Walk-forward validation** (forces re-optimization weekly)
2. **Separate IS/OOS data** (never touch OOS during optimization)
3. **Simplify model** (fewer parameters = less overfitting)
4. **Test on multiple assets** (not just BTC)
5. **Ensemble methods** (average predictions = more stable)

---

## Walk-Forward in 3 Steps

```
Step 1: Train on 60 days of data
Step 2: Test on next 10 days (OUT-OF-SAMPLE)
Step 3: Shift window forward, repeat
Result: Aggregate OOS results = realistic performance
```

**Why It Works:**
- Catches overfitting that single backtest misses
- Simulates real trading (always learning from recent data)
- Forces parameter diversity (not one "perfect" set)

**Computational Cost:** 20-50 optimizations per backtest (slow but worth it).

---

## Freqtrade Warning (Critical)

> "Continual learning has high probability of overfitting/getting stuck in local minima while the market moves away from your model."

**Solution:** Retrain from scratch weekly, keep 3 versions (current + 2 fallbacks).

---

## Real-World Hedge Fund Pattern

```
Jump Trading (Profitable for 20+ years):
├─ AI inspects market microstructure (millisecond-level)
├─ Learns patterns continuously
├─ Updates strategies in real-time
└─ **But does NOT use continual learning**
    Instead: Retrains on fixed schedule (daily/weekly)
```

**Key Insight:** Profitable hedge funds update parameters on schedule, not continuously.

---

## Bayesian vs. Evolutionary Optimization

| Aspect | Bayesian | Evolutionary |
|--------|----------|-------------|
| Evaluations needed | 10-100 | 100-1000 |
| Parameter space | Small (<10) | Large |
| Discrete params | Weak | Strong |
| Time to result | Fast | Slow |

**For Crypto Trading:** Trend-following = Evolutionary, Mean-reversion = Bayesian.

---

## Paper Trading Reality Gaps

**These only show up in paper trading, NOT backtest:**
- Execution latency (order delay)
- Slippage (actual fill vs. expected price)
- Partial fills (can't fill full size)
- Order rejection (circuit breakers)
- Funding rate costs
- Exchange downtime

**Minimum Duration:** 14-28 days before live trading.

---

## Common Backtest Pitfalls

| Pitfall | Detection | Fix |
|---------|-----------|-----|
| Look-ahead bias | Paper ≠ Backtest | Code review, third-party backtest |
| Overfitting | IS Sharpe >> OOS | Walk-forward validation |
| Insufficient data | <100 trades | Increase sample size |
| Data leakage | Used OOS data for features | Regenerate features IS-only |
| Wrong timestamp | Off-by-one | Use strict timestamp order |

---

## Metrics Dashboard (Minimal Viable)

**Daily:**
- Current Sharpe (rolling 20 trades)
- Daily Drawdown (current session)
- Win Rate (current week)

**Weekly:**
- Walk-forward validation score
- Shadow variant count
- Best variant vs. current

**Monthly:**
- Archive best configuration
- Prune underperformers
- Update hypothesis backlog

---

## Implementation Road Map

**Phase 1 (Now):**
- Walk-forward validator
- Shadow trading 20 variants
- Bayesian optimization

**Phase 2 (Month 2):**
- Trade failure clustering
- Auto-hypothesis generation
- Weekly DeepSeek review

**Phase 3 (Month 3):**
- PPO agent (shadow mode)
- Actor-critic structure

**Phase 4 (Month 4+):**
- Meta-learning (MAML)
- Automatic regime detection

---

## Research Sources (Top References)

**Must-Read:**
- [Walk-Forward Analysis](https://www.interactivebrokers.com/campus/ibkr-quant-news/the-future-of-backtesting-a-deep-dive-into-walk-forward-analysis/)
- [How to Avoid Overfitting](https://quantlane.com/blog/avoid-overfitting-trading-strategies/)
- [Freqtrade FreqAI Docs](https://www.freqtrade.io/en/stable/freqai/)
- [Bayesian vs. Evolutionary](https://www.mdpi.com/2227-7390/14/5/761)

**Deep Dive:**
- [arXiv: Self-Rewarding Deep RL](https://www.mdpi.com/2227-7390/12/24/4020)
- [arXiv: Meta-Learning for Trading](https://www.scirp.org/pdf/jdaip_2020052215031097.pdf)
- [Genetic Algorithms for Trading](https://arxiv.org/html/2510.07943v1)

---

## Bottom Line

1. **Walk-forward validation is non-negotiable.** Backtest Sharpe without it = meaningless.

2. **Overfitting kills 80% of strategies.** Prevention requires discipline: separate IS/OOS, simplify, test broadly.

3. **Discrete retraining > continuous learning.** Hedge funds retrain weekly from scratch, not continuously.

4. **Hard risk limits at execution layer.** Even perfect AI can fail; gate every trade.

5. **Shadow trading catches reality.** 14-28 days of paper trading reveals gaps backtest misses.

6. **Ensemble > single algorithm.** Multiple RL agents, genetic variants, multiple models = more stable.

7. **Weekly human review required.** Autonomous systems drift. Schedule AI + human review weekly.

---

## Korean Translation (한국어 번역)

### 한줄 요약

**성공한 모든 시스템의 핵심:** 매일 그림자 매매(20-30 변형) → 매주 워크포워드 검증 → 최고 변형 승격 → 강건한 위험 제한 → 매주 인간+AI 리뷰.

**핵심 발견:** 연속학습 사용하는 시스템 없음. 모두 이산적 간격(일일/주간 처음부터 재학습) 사용.

### 5가지 핵심 알고리즘

| 알고리즘 | 용도 | 성숙도 | 주의점 |
|---------|------|--------|--------|
| **유전알고리즘** | 파라미터 진화 | ✓ 프로덕션 | 국소 최소값 |
| **PPO (강화학습)** | 자율 적응 | 연구 | 보상 해킹 |
| **메타러닝** | 체제 전이 | 연구 | 다양한 학습 필요 |
| **베이지안 최적화** | 빠른 연구 | ✓ 프로덕션 | 작은 파라미터 공간 |
| **진화 전략** | 큰 탐색 공간 | ✓ 프로덕션 | 많은 평가 필요 |

### 라이브 거래 전 검증 체크리스트

- [ ] 워크포워드 분석 (90일 롤링, 단일 백테스트 아님)
- [ ] 샤프 비율 감소 IS→OOS <10%
- [ ] 페이퍼 거래 14-28일 (백테스트와 상관계수 >95%)
- [ ] 룩어헤드 바이어스 확인 (코드 리뷰 + 제3자 백테스트)
- [ ] 파라미터 민감도 분석 (1% 변화가 P&L 10% 이상 변동 금지)
- [ ] 여러 코인에서 테스트 (메인 타겟만 아님)
- [ ] 최적화 윈도우당 ≥100 거래
- [ ] 몬테카를로 시뮬레이션 (1000회 재샘플)

### 오버피팅: #1 위험 요소

**실증 증거:**
- Quantopian (888 전략): 백테스트 샤프 = **라이브 수익과 무관**
- 이동평균: 샤프 1.2 (표본 내) → 샤프 -0.2 (신규 데이터)

**방지 (우선순위):**
1. **워크포워드 검증** (매주 재최적화 강제)
2. **IS/OOS 데이터 분리** (최적화 중 OOS 건드리지 않기)
3. **모델 단순화** (파라미터 적을수록 오버피팅 적음)
4. **여러 자산에서 테스트** (BTC만 아님)
5. **앙상블 메서드** (평균 = 더 안정적)

### 안전 가드레일 (실행 계층에서 강제)

**절대 수정 불가 제한:**
- 일일 DD 최대: 4% → 자동 종료
- 월간 MDD 최대: 15% → 자동 종료
- 최대 포지션 크기: 거래당 포트폴리오 5%
- 최대 상관계수: 2개 이상 상관된 쌍 거래 금지

### Freqtrade 경고 (중요)

> "연속학습은 오버피팅/국소 최소값 위험이 높으며, 시장이 모델에서 벗어날 때 성능 저하."

**해결책:** 매주 처음부터 재학습, 3개 버전 유지 (현재 + 2개 폴백).

### 워크포워드 분석 (3단계)

```
1단계: 60일 데이터로 학습
2단계: 다음 10일에서 테스트 (표본 외)
3단계: 윈도우 앞으로 이동, 반복
결과: OOS 결과 집계 = 현실적 성능
```

**작동 원리:**
- 단일 백테스트로 놓치는 오버피팅 탐지
- 실제 거래 시뮬레이션 (항상 최근 데이터 학습)
- 파라미터 다양성 강제 ("완벽한" 세트 하나 아님)

### 페이퍼 거래의 현실 차이 (백테스트에만 없는 것)

- 실행 지연 (주문 지연)
- 슬리페이지 (예상 가격과 실제 체결 가격)
- 부분 체결 (전체 주문 체결 불가)
- 주문 거부 (서킷 브레이커)
- 펀딩 레이트 비용
- 거래소 다운타임

**최소 기간:** 라이브 거래 전 14-28일.

### 구현 로드맵

**Phase 1 (지금):**
- 워크포워드 검증기
- 20개 변형 그림자 거래
- 베이지안 최적화

**Phase 2 (2개월):**
- 거래 실패 클러스터링
- 자동 가설 생성
- 주간 DeepSeek 리뷰

**Phase 3 (3개월):**
- PPO 에이전트 (그림자 모드)
- Actor-Critic 구조

**Phase 4 (4개월+):**
- 메타러닝 (MAML)
- 자동 체제 감지

### 핵심 결론

1. **워크포워드 검증은 필수.** 검증 없는 백테스트 샤프 = 무의미.

2. **오버피팅이 80% 전략 살점.** 방지는 규율 필요: IS/OOS 분리, 단순화, 광범위 테스트.

3. **이산 재학습 > 연속 학습.** 헤지펀드는 연속이 아닌 주간 처음부터 재학습.

4. **실행 계층의 강건한 위험 제한.** 완벽한 AI도 실패 가능; 모든 거래 제어.

5. **그림자 거래가 현실 차이 탐지.** 14-28일 페이퍼 거래로 백테스트 놓친 것 발견.

6. **앙상블 > 단일 알고리즘.** 여러 RL 에이전트, 유전 변형, 모델 결합 = 더 안정적.

7. **주간 인간 리뷰 필수.** 자율 시스템은 드리프트. 주간 AI + 인간 리뷰 스케줄 필요.

---

**마지막 업데이트:** 2026-03-28
**상태:** 구현 준비 완료
