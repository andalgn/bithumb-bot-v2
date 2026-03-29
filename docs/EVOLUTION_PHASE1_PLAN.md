# Evolution Phase 1 — 구현 계획서 (최종)

**작성일:** 2026-03-29
**기반 문서:** `SELF_EVOLUTION_ARCHITECTURE.md` + `deep-research-report.md` 검토 반영
**목표:** 인간 감독 하의 자율 진화 루프 — 실험은 자동, 적용은 인간 승인
**예상 기간:** 1~2주

---

## 1. 검토 보고서 반영 사항

외부 심층 검토(deep-research-report.md)에서 수용한 7가지 개선을 이 계획에 통합했다.

### 수용 (구현에 반영)

| # | 지적 | 반영 방법 |
|---|------|----------|
| 1 | Composite Fitness가 리워드 해킹에 취약 | **하드 제약 우선 필터** — MDD>15%, 거래수<20, WR<30% 이면 fitness 계산 전에 탈락 |
| 2 | 수백 번 실험의 선택 편향 | **Deflated Sharpe Ratio** 보정 — 실험 횟수를 고려한 통계적 유의성 검증 |
| 3 | 시장 전환기에 자동 진화가 역효과 | **드리프트 감지 → 진화 자동 중단** — 성과 급락 시 마지막 안정 버전으로 롤백 |
| 4 | held-out OOS 데이터 격리 | **최근 1개월 OOS 고정** — 실험에서 절대 사용 금지, 최종 검증 전용 |
| 5 | 자전거래 방지 (빗썸 2026-03 공지) | 별도 작업으로 분리 (Phase 1과 병렬 진행) |
| 6 | client_order_id 멱등성 | 별도 작업으로 분리 (Phase 1과 병렬 진행) |
| 7 | 주문별 결정 로그 강화 | journal 필드 추가로 반영 |

### 반박 (적용하지 않음)

| 지적 | 이유 |
|------|------|
| 4~6명 팀, 0.8~3.0억 예산 | 1인 개발, 미니PC, 개인 거래 프로젝트 |
| PostgreSQL + ClickHouse + Kafka 스택 | 10코인/15분 주기에 SQLite WAL 충분 |
| Prometheus + Grafana + Loki 모니터링 | HealthMonitor + Discord 알림 충분 |
| Vault/KMS 시크릿 관리 | .env + 파일 권한 600 + VPN 뒤 홈서버 |
| CPCV (Combinatorial Purged CV) | Walk-Forward + Monte Carlo로 충분 |
| FinRL/DRL 기반 실행 | 규칙 기반 전략, GPU 없음, 아키텍처 비호환 |
| "OMS/보안을 먼저 완성하라" | 이미 LIVE 운영 중 (Phase 0~7 완료) |

---

## 2. 구현 대상 파일

### 신규 생성 (4개)

| 파일 | 목적 | 규모 |
|------|------|------|
| `strategy/strategy_params.py` | 모든 진화 가능 파라미터 집중 + 범위 강제 | ~400줄 |
| `strategy/guard_agent.py` | 변경 검증 + 위험도 점수 + 하드 제약 | ~300줄 |
| `strategy/evolution_orchestrator.py` | 7단계 루프 엔진 | ~700줄 |
| `app/approval_workflow.py` | 승인 관리 + config 원자 업데이트 | ~250줄 |

### 기존 수정 (6개)

| 파일 | 변경 | 영향도 |
|------|------|--------|
| `app/main.py` | EvolutionOrchestrator 비동기 태스크 추가 | 낮음 |
| `app/config.py` | EvolutionConfig 추가 | 낮음 |
| `bot_discord/bot.py` | `/approve`, `/reject`, `/pending` 명령 추가 | 낮음 |
| `strategy/experiment_store.py` | risk_score, validation_result, change_id 필드 추가 | 낮음 |
| `research_program.md` | Phase 1 진화 범위 + 금지 영역 명세 | 낮음 |
| `configs/config.yaml` | `evolution` 섹션 추가 | 낮음 |

---

## 3. 단계별 구현 계획

### Step 1: strategy_params.py (1일)

**모든 진화 가능 파라미터를 하나의 파일에 집중한다.**

Karpathy 원칙: "Single file to modify — Full context window coverage."

```python
@dataclass
class StrategyParams:
    # 전략 (12개 — 기존)
    tf_sl_mult: float = 2.5           # [1.0, 5.0]
    tf_tp_rr: float = 2.0             # [1.0, 5.0]
    tf_cutoff: float = 72.0           # [55, 90]
    tf_w_trend_align: float = 30.0    # [0, 45]
    tf_w_macd: float = 25.0           # [0, 40]
    tf_w_volume: float = 20.0         # [0, 35]
    tf_w_rsi_pullback: float = 15.0   # [0, 30]
    tf_w_supertrend: float = 10.0     # [0, 25]
    mr_sl_mult: float = 7.0           # [2.0, 10.0]
    mr_tp_rr: float = 1.5             # [1.0, 4.0]
    dca_sl_pct: float = 0.05          # [0.02, 0.08]
    dca_tp_pct: float = 0.03          # [0.01, 0.05]

    # 리스크 (5개 — 신규 진화 대상)
    daily_dd_pct: float = 0.04        # [0.02, 0.06]
    weekly_dd_pct: float = 0.08       # [0.04, 0.12]
    consecutive_loss_limit: int = 3   # [2, 7]
    cooldown_min: int = 60            # [30, 120]
    max_exposure_pct: float = 0.90    # [0.70, 0.95]

    # 사이징 (6개 — 신규)
    active_risk_pct: float = 0.07     # [0.03, 0.12]
    pool_cap_pct: float = 0.25        # [0.15, 0.35]
    defense_mult_min: float = 0.3     # [0.1, 0.5]
    defense_mult_max: float = 1.0     # [0.7, 1.0]
    vol_target_mult_min: float = 0.8  # [0.5, 1.0]
    vol_target_mult_max: float = 1.5  # [1.0, 2.0]

    # 국면 (2개 — 신규)
    regime_adx_strong: float = 25.0   # [18, 35]
    regime_atr_spike_mult: float = 2.0 # [1.3, 3.0]

    # 환경필터 (2개 — 신규)
    l1_volume_ratio: float = 0.8      # [0.5, 1.0]
    l1_momentum_burst_pct: float = 0.015 # [0.01, 0.03]

    # 승격 (3개 — 신규)
    promotion_profit_pct: float = 0.012  # [0.008, 0.02]
    promotion_hold_bars: int = 2         # [1, 5]
    promotion_adx_min: float = 20.0      # [15, 30]
```

**핵심 메서드:**
- `PARAM_BOUNDS: dict[str, tuple[min, max]]` — 모든 파라미터의 범위 (코드 상수)
- `validate() -> list[str]` — 범위 위반 목록 반환
- `load_from_config(path) -> StrategyParams` — config.yaml에서 초기 로드
- `diff(other) -> dict[str, tuple[old, new]]` — 두 params 간 차이
- `to_dict() / from_dict()` — 직렬화

**후방 호환성:** config.yaml의 `strategy_params` 섹션은 유지. strategy_params.py가 로드되면 그 값이 우선. 전환 기간 후 config.yaml에서 제거.

**테스트:**
- 모든 기본값이 범위 내인지 확인
- 범위 위반 시 validate()가 정확히 감지하는지
- config.yaml → StrategyParams 로드 정확성

---

### Step 2: guard_agent.py (1일)

**모든 변경을 실행 전에 구조적으로 검증한다.**

검토 보고서 수용: "프롬프트 기반 제약은 신뢰할 수 없다. 코드 레벨 구조적 제약 필수."

```python
class GuardAgent:
    def validate(self, current: StrategyParams, proposed: StrategyParams) -> GuardResult:
        """변경을 검증하고 위험도를 계산한다."""

    def _check_bounds(self, proposed) -> list[str]:
        """MIN/MAX 범위 위반 검사."""

    def _check_logic(self, proposed) -> list[str]:
        """논리적 정합성 검사."""
        # 예: defense_mult_min < defense_mult_max
        # 예: vol_target_mult_min < vol_target_mult_max
        # 예: daily_dd < weekly_dd
        # 예: weight 합계 제한

    def _check_hard_constraints(self, proposed) -> list[str]:
        """절대 위반 불가 제약."""
        # daily_dd_pct > 0.06 이면 거부 (6% 초과 불가)
        # max_exposure_pct > 0.95 이면 거부
        # consecutive_loss_limit < 2 이면 거부

    def _calculate_risk_score(self, changes: dict) -> float:
        """변경 크기 + 영향도 기반 위험도 점수 (0.0~1.0)."""
        # 리스크/사이징 파라미터 변경은 가중치 높음
        # 전략 가중치 미세 조정은 가중치 낮음
        # 동시 변경 파라미터 수에 비례
```

**GuardResult:**
```python
@dataclass
class GuardResult:
    is_valid: bool           # 범위/논리/하드 제약 통과 여부
    risk_score: float        # 0.0~1.0
    risk_level: str          # "low" | "medium" | "high"
    violations: list[str]    # 위반 내역
    changes: dict            # {param: (old, new)} 변경 요약
```

**위험도 분류:**
- `low` (< 0.2): 전략 가중치 미세 조정 1~2개
- `medium` (0.2~0.6): 리스크/사이징 파라미터 변경 또는 3개 이상 동시 변경
- `high` (> 0.6): DD 한도/노출 한도 변경 또는 5개 이상 동시 변경

**테스트:**
- 범위 위반 감지
- 논리적 정합성 (min < max 등)
- 하드 제약 거부
- 각 위험도 레벨별 예제

---

### Step 3: approval_workflow.py (0.5일)

**변경 제안을 저장하고, 인간 승인을 관리한다.**

```python
@dataclass
class PendingChange:
    change_id: str               # UUID
    proposed_params: dict        # 제안된 파라미터
    current_params: dict         # 현재 파라미터
    changes: dict                # {param: (old, new)}
    risk_score: float
    risk_level: str
    fitness_improvement: float   # baseline 대비 개선율
    rationale: str               # 변경 근거
    experiment_count: int        # 이번 세션 실험 횟수
    created_at: str
    status: str                  # "pending" | "approved" | "rejected" | "expired"

class ApprovalWorkflow:
    def propose(self, change: PendingChange) -> str:
        """변경 제안 저장, change_id 반환."""

    def approve(self, change_id: str) -> bool:
        """승인 → config 원자 업데이트 + 백업 생성."""

    def reject(self, change_id: str) -> bool:
        """거부 → 상태 변경."""

    def list_pending(self) -> list[PendingChange]:
        """대기 중인 변경 목록."""

    def expire_old(self, hours: int = 48):
        """48시간 이상 대기한 변경 자동 만료."""
```

**저장소:** `data/pending_changes.json` (SQLite 테이블 추가도 가능하나 JSON으로 충분)

**config 원자 업데이트:**
1. `config.yaml.bak.YYYYMMDD_HHMMSS` 백업 생성
2. 파일 잠금 (fcntl)
3. YAML 파싱 → 파라미터 병합
4. 임시 파일 작성 → `os.replace()` 원자 교체

---

### Step 4: evolution_orchestrator.py (3~4일) — 핵심

**7단계 루프 + 검토 보고서 수용 사항 통합.**

```python
class EvolutionOrchestrator:
    async def run_session(self) -> EvolutionResult:
        """매일 1회 실행되는 진화 세션."""
```

#### Phase 1: Monitor

```python
async def _phase_monitor(self) -> MonitorResult:
    """최근 7일 거래 성과 수집 + baseline fitness 계산."""
    trades = await self.journal.get_recent_trades(days=7)

    # 드리프트 감지 (검토 보고서 #3 수용)
    if self._detect_drift(trades):
        await self.notifier.send("진화 중단: 시장 드리프트 감지")
        return MonitorResult(should_continue=False, reason="drift")

    baseline = self._compute_composite_fitness(trades)
    return MonitorResult(should_continue=True, baseline=baseline)
```

**드리프트 감지 로직:**
- 최근 7일 fitness vs 이전 30일 평균 비교
- fitness가 30일 평균 대비 25% 이상 하락 → 드리프트
- 연속 3일 fitness 하락 추세 → 드리프트
- 드리프트 시: 진화 중단 + Discord 알림 + 마지막 안정 config 기록

#### Phase 2: Diagnose

```python
async def _phase_diagnose(self, baseline: MonitorResult) -> list[str]:
    """약한 영역 파악 → 이번 세션의 탐색 영역 선정."""
    patterns = await self.feedback_loop.get_failure_patterns(days=7)

    weak_areas = []
    if baseline.profit_factor < 1.3:
        weak_areas.append("strategy_weights")
    if baseline.mdd > 0.10:
        weak_areas.append("risk_thresholds")
    if baseline.win_rate < 0.45:
        weak_areas.append("entry_cutoff")
    if patterns and patterns[0].tag == "sizing_error":
        weak_areas.append("sizing_params")

    return weak_areas[:2]  # 세션당 최대 2개 영역
```

#### Phase 3: Hypothesize (Centaur)

```python
async def _phase_hypothesize(self, weak_areas: list[str]) -> list[ParamCandidate]:
    """LLM 방향 제시 + AutoOptimizer 그리드 탐색."""

    # 1. LLM (DeepSeek) — "어디를 탐색할지"
    hypotheses = await self.feedback_loop.generate_hypotheses()
    # → [{param: "tf_sl_mult", direction: "increase", range: (2.0, 3.5), reason: "..."}]

    # 2. AutoOptimizer — "그 방향에서 최적값 찾기"
    candidates = []
    for hyp in hypotheses[:3]:  # 가설 최대 3개
        grid = self._build_focused_grid(hyp)  # 가설 범위 내 그리드
        results = await self._run_grid_search(grid)
        candidates.extend(results)

    return candidates
```

#### Phase 4: Experiment

```python
async def _phase_experiment(self, candidates: list[ParamCandidate]) -> list[ExperimentResult]:
    """각 후보로 백테스트 실행 (5~10회)."""
    results = []
    for candidate in candidates[:self.max_experiments]:
        # strategy_params 수정
        test_params = self.current_params.apply(candidate.changes)

        # 하드 제약 사전 필터 (검토 보고서 #1 수용)
        if not self._pass_hard_constraints(test_params):
            results.append(ExperimentResult(candidate, fitness=0, rejected="hard_constraint"))
            continue

        # 백테스트 실행 (기존 backtest.py 재사용)
        bt_result = await self.backtester.run(test_params, days=90)

        # 하드 제약 결과 필터 (fitness 계산 전)
        if bt_result.trades < 20:
            results.append(ExperimentResult(candidate, fitness=0, rejected="min_trades"))
            continue
        if bt_result.max_drawdown > 0.15:
            results.append(ExperimentResult(candidate, fitness=0, rejected="mdd_limit"))
            continue
        if bt_result.win_rate < 0.30:
            results.append(ExperimentResult(candidate, fitness=0, rejected="min_winrate"))
            continue

        fitness = self._compute_composite_fitness(bt_result)
        results.append(ExperimentResult(candidate, fitness=fitness))

    return results
```

#### Phase 5: Validate (과적합 방지 강화)

```python
async def _phase_validate(self, best: ExperimentResult) -> ValidationResult:
    """다층 과적합 방지 검증."""

    # 1. Walk-Forward 검증 (필수)
    wf_result = await self.walk_forward.run(best.params, segments=4)
    if not wf_result.is_robust:
        return ValidationResult(passed=False, reason="walk_forward_failed")

    # 2. Held-out OOS 검증 (검토 보고서 #4 수용)
    # 최근 1개월 데이터는 실험에서 사용 금지, 여기서만 검증
    oos_result = await self.backtester.run(best.params, oos_only=True)
    if oos_result.profit_factor < 1.0:
        return ValidationResult(passed=False, reason="oos_negative")

    # 3. IS/OOS 괴리 체크
    is_oos_ratio = best.fitness / self._compute_fitness(oos_result)
    if is_oos_ratio > 1.5:  # IS가 OOS보다 50% 이상 좋으면 과적합
        return ValidationResult(passed=False, reason="overfitting_detected")

    # 4. Deflated Sharpe Ratio (검토 보고서 #2 수용)
    dsr = self._deflated_sharpe(
        sharpe=oos_result.sharpe,
        num_experiments=self.session_experiment_count,
        skew=oos_result.return_skewness,
        kurtosis=oos_result.return_kurtosis,
    )
    if dsr < 0.05:  # 5% 유의수준
        return ValidationResult(passed=False, reason="dsr_not_significant")

    return ValidationResult(passed=True, oos_fitness=oos_fitness, dsr=dsr)
```

**Deflated Sharpe Ratio 공식:**
```
DSR = Φ(  (SR_obs - SR_0) × √(n-1)  /  √(1 - γ₃·SR_obs + (γ₄-1)/4 · SR_obs²)  )

SR_obs: 관측된 Sharpe Ratio
SR_0: 실험 횟수 기반 기대 최대값 (E[max(SR)] ≈ √(2·ln(N)) × σ_SR)
n: 거래 수
γ₃: 수익률 왜도 (skewness)
γ₄: 수익률 첨도 (kurtosis)
```

#### Phase 6: Guard

```python
async def _phase_guard(self, validated: ValidationResult) -> GuardResult:
    """GuardAgent 구조적 검증."""
    guard_result = self.guard_agent.validate(self.current_params, validated.params)

    if not guard_result.is_valid:
        await self.notifier.send(f"GuardAgent 거부: {guard_result.violations}")
        return guard_result

    return guard_result
```

#### Phase 7: Apply / Revert

```python
async def _phase_apply(self, guard_result: GuardResult, validation: ValidationResult):
    """Phase 1에서는 모두 pending → Discord 알림 → 인간 승인 대기."""

    change = PendingChange(
        change_id=uuid4().hex[:8],
        proposed_params=validation.params.to_dict(),
        current_params=self.current_params.to_dict(),
        changes=guard_result.changes,
        risk_score=guard_result.risk_score,
        risk_level=guard_result.risk_level,
        fitness_improvement=validation.oos_fitness - self.baseline_fitness,
        rationale=validation.rationale,
        experiment_count=self.session_experiment_count,
    )

    change_id = self.approval_workflow.propose(change)

    # Discord 보고
    msg = self._format_evolution_report(change)
    await self.notifier.send(msg)
    await self.notifier.send(f"승인: `/approve {change_id}` | 거부: `/reject {change_id}`")
```

**Discord 보고 포맷:**
```
━━━ Evolution Report ━━━
세션: 2026-03-29 00:30 KST
실험: 8회 (3 keep, 5 revert)
베이스라인 fitness: 0.62
최선 후보 fitness: 0.68 (+9.7%)

변경 내용:
  tf_sl_mult: 2.5 → 2.8
  tf_w_trend_align: 30 → 33

검증:
  Walk-Forward: 4/4 통과
  OOS PF: 1.42
  IS/OOS 괴리: 1.18 (OK)
  DSR p-value: 0.03 (유의)

위험도: low (0.15)
━━━━━━━━━━━━━━━━━━━━
/approve abc12345 | /reject abc12345
```

---

### Step 5: 통합 + Discord 명령 (1일)

#### app/main.py 수정

```python
# TradingBot.__init__() 에 추가
self._evolution = EvolutionOrchestrator(
    journal=self._journal,
    notifier=self._notifier,
    market_store=self._market_store,
    feedback_loop=self._feedback_loop,
    guard_agent=GuardAgent(),
    approval_workflow=ApprovalWorkflow(state_store=self._state_store),
    backtester=self._backtester,
    walk_forward=self._walk_forward,
    config=config.evolution,
)

# _schedule_tasks() 에 추가
if config.evolution.enabled:
    asyncio.create_task(self._run_evolution_daemon())
```

#### app/config.py — EvolutionConfig

```python
@dataclass(frozen=True)
class EvolutionConfig:
    enabled: bool = False
    run_time: str = "00:30"              # 매일 실행 시간 (KST)
    max_experiments: int = 10
    held_out_days: int = 30              # OOS 격리 기간
    dsr_significance: float = 0.05      # DSR 유의수준
    is_oos_max_ratio: float = 1.5       # IS/OOS 괴리 한도
    drift_threshold: float = 0.25       # fitness 하락률 한도
```

#### bot_discord/bot.py — 슬래시 커맨드

```python
@bot.tree.command(name="approve")
async def approve_change(interaction, change_id: str):
    """진화 변경 승인."""

@bot.tree.command(name="reject")
async def reject_change(interaction, change_id: str):
    """진화 변경 거부."""

@bot.tree.command(name="pending")
async def list_pending(interaction):
    """대기 중인 변경 목록."""
```

#### configs/config.yaml 추가

```yaml
evolution:
  enabled: false   # Phase 1: 수동 활성화
  run_time: "00:30"
  max_experiments: 10
  held_out_days: 30
  dsr_significance: 0.05
  is_oos_max_ratio: 1.5
  drift_threshold: 0.25
```

---

### Step 6: research_program.md 확장 (0.5일)

```markdown
# Phase 1 진화 범위

## 진화 가능 (30개 파라미터)
- 전략: 12개 (SL/TP, 가중치, cutoff)
- 리스크: 5개 (DD 한도, 격리, 쿨다운, 노출)
- 사이징: 6개 (risk_pct, pool_cap, defense, vol_target)
- 국면: 2개 (ADX 임계값, ATR spike 배수)
- 환경필터: 2개 (거래량 비율, 모멘텀 버스트)
- 승격: 3개 (수익률, 보유 기간, ADX)

## 금지 영역 (절대 수정 불가)
- 지표 공식 (RSI, MACD, ATR, BB, SuperTrend 계산)
- 주문 FSM (체결 로직, 타임아웃, 재시도)
- 국면 5종류 자체 (STRONG_UP/WEAK_UP/RANGE/WEAK_DOWN/CRISIS)
- 수수료/슬리피지 모델
- 데이터 수집/정규화 로직
- 백테스트 평가 함수 (불변, Karpathy의 prepare.py에 해당)

## 하드 제약 (fitness 계산 전 탈락)
- MDD > 15% → 즉시 탈락
- 거래 수 < 20 → 즉시 탈락
- Win Rate < 30% → 즉시 탈락
- IS/OOS 괴리 > 1.5 → 과적합 판정

## 평가 지표
Composite Fitness = 0.30×norm(PF) + 0.30×norm(Sharpe) + 0.20×norm(1-MDD/0.20) + 0.20×norm(WR)
+ Deflated Sharpe Ratio 유의성 검증 (p < 0.05)
```

---

### Step 7: 테스트 (1~2일)

#### 단위 테스트

| 파일 | 대상 | 목표 |
|------|------|------|
| `tests/test_strategy_params.py` | 범위 검증, 직렬화, config 로드 | 85%+ |
| `tests/test_guard_agent.py` | 위험도 점수, 하드 제약, 논리 검증 | 85%+ |
| `tests/test_evolution_orchestrator.py` | 각 Phase별 로직 (Mock 사용) | 70%+ |

#### 통합 테스트

- `scripts/test_evolution.py` — 과거 데이터로 7단계 루프 시뮬레이션
- 체크리스트:
  - [ ] Monitor: baseline fitness 계산
  - [ ] Diagnose: 약한 영역 식별
  - [ ] Hypothesize: 가설 생성 (DeepSeek Mock 가능)
  - [ ] Experiment: 백테스트 실행 + 하드 제약 필터링
  - [ ] Validate: Walk-Forward + OOS + DSR
  - [ ] Guard: 위험도 점수
  - [ ] Apply: Discord 메시지 포맷 확인

---

### Step 8: PAPER 검증 (3~5일)

- `evolution.enabled: true` 설정
- 매일 00:30에 루프 실행 관찰
- 최소 3회 완전 루프 확인
- 체크리스트:
  - [ ] 루프 정시 시작/종료 (30분 이내)
  - [ ] 모든 Phase 로그 수집
  - [ ] Discord 알림 정상 수신
  - [ ] `/approve` 명령 동작 확인
  - [ ] config 원자 업데이트 + 백업 생성
  - [ ] 승인된 변경이 다음 사이클에 반영
  - [ ] 드리프트 감지 로직 동작 확인 (인위적 트리거)

---

### Step 9: LIVE 배포 (1주 모니터링)

- PAPER 검증 통과 후 LIVE에서 활성화
- 첫 주: 매일 Discord 보고 확인 + 수동 판단
- 문제 발생 시: `evolution.enabled: false`로 즉시 비활성화
- 성공 기준:
  - [ ] 1주간 봇 안정 운영 (크래시 0건)
  - [ ] 최소 3개 변경 제안 수신
  - [ ] fitness 악화 없음 (기존 대비)

---

## 4. 임계 경로 + 일정

```
Day 1:  strategy_params.py
Day 2:  guard_agent.py + approval_workflow.py
Day 3-6: evolution_orchestrator.py (7단계 루프)
Day 5:  main.py 통합 + config.py + Discord 명령 (병렬)
Day 6:  research_program.md 확장 (병렬)
Day 7-8: 테스트 작성 + 통합 테스트
Day 9-13: PAPER 검증
Day 14+: LIVE 배포
```

**총: ~2주 (개발 8일 + PAPER 5일)**

---

## 5. 위험 및 완화

| 위험 | 확률 | 영향 | 완화 |
|------|------|------|------|
| LLM 가설 품질 저하 | 중 | 중 | Walk-Forward + DSR + 하드 제약이 나쁜 제안 필터링 |
| 과적합 (백테스트 맞춤) | 높 | 높 | held-out OOS + IS/OOS 괴리 체크 + DSR |
| config 손상 | 낮 | 높 | 원자 업데이트 + 타임스탬프 백업 + 롤백 |
| 드리프트 중 잘못된 진화 | 중 | 높 | 드리프트 감지 → 자동 중단 |
| 백테스트 시간 초과 | 낮 | 낮 | max_experiments 10 + 타임아웃 설정 |
| Discord 알림 실패 | 낮 | 중 | 재시도 + pending 상태 영속화 |

---

## 6. Phase 2 전환 조건

Phase 1이 3~6주 안정 운영되면 Phase 2로 전환:

- low-risk (< 0.2): 자동 승인 + pilot mode (50% 사이즈, 20거래)
- medium-risk: Discord 알림만 (승인 선택)
- high-risk: 자동 거부
- pilot 중 fitness 하락 → 자동 롤백

Phase 2 전환 조건:
- [ ] Phase 1에서 최소 10개 변경 승인/적용
- [ ] 적용된 변경 중 롤백 필요했던 건 0건
- [ ] 전체 fitness 유지 또는 개선
- [ ] GuardAgent 위험도 점수의 정확성 검증 (low가 실제로 안전했는가)

---

## 7. 별도 병렬 작업 (진화와 독립)

검토 보고서에서 수용했으나 진화 시스템과 독립적인 LIVE 운영 개선:

| 작업 | 설명 | 우선순위 |
|------|------|---------|
| 자전거래 방지 | 기존 미체결과 교차하는 신규 주문 차단 | 높음 |
| `client_order_id` 도입 | 빗썸 API 멱등성 활용 | 중간 |
| 주문별 결정 로그 | journal에 피처 스냅샷 + 리스크 게이트 결과 저장 | 낮음 |
