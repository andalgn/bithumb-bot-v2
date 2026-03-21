# 자율 연구 엔진 (AutoResearcher) 설계서

**작성일**: 2026-03-21
**목표**: autoresearch 패턴을 벤치마킹하여 DeepSeek LLM이 매매 전략을 자율적으로 실험·개선하는 시스템 구축

## 핵심 아이디어

Karpathy의 autoresearch는 "LLM이 train.py를 수정 → 학습 → 평가 → 개선이면 유지, 아니면 롤백 → 반복"하는 자율 루프.

이 매매봇에 적용:
```
DeepSeek이 실험 가설 생성
  → 파라미터/가중치 수정
  → 백테스트 실행
  → OOS 평가
  → 개선이면 유지, 아니면 롤백
  → 결과 기록
  → 다음 실험 → 반복
```

## 현재 인프라 vs 필요한 것

| 항목 | 이미 있음 | 새로 필요 |
|------|----------|----------|
| 백테스트 엔진 | `ParameterOptimizer` | - |
| DeepSeek API 호출 | `ReviewEngine._call_deepseek()` | 실험 전용 프롬프트 |
| 파라미터 그리드 | `param_grid.py` | LLM이 자유롭게 설정 |
| config 백업/적용 | `BacktestDaemon._apply_optimized_params()` | - |
| 실험 기록 | 없음 | `data/research_log.tsv` |
| 연구 방향 설정 | 없음 | `research_program.md` |
| 자율 실험 루프 | 없음 | `AutoResearcher` 클래스 |

## 아키텍처

### autoresearch 매핑

| autoresearch | 이 프로젝트 |
|---|---|
| `program.md` (사람이 방향 설정) | `research_program.md` |
| `train.py` (에이전트가 수정) | config.yaml의 `strategy_params` + rule_engine 가중치 |
| `uv run train.py` (실행) | `ParameterOptimizer.replay_with_params()` (백테스트) |
| `val_bpb` (평가 지표) | OOS Profit Factor |
| `results.tsv` (기록) | `data/research_log.tsv` |
| git commit/revert | config 백업/복원 |

### 실험 범위 (수정 가능한 것)

LLM이 수정할 수 있는 파라미터를 **안전한 범위로 제한**:

```yaml
# LLM이 제안할 수 있는 파라미터와 허용 범위
researchable_params:
  trend_follow:
    sl_mult: [1.0, 5.0]      # ATR 배수
    tp_rr: [1.0, 5.0]        # Risk:Reward 비율
    cutoff_full: [60, 90]    # 진입 점수 컷오프
  # 전략 점수 가중치 (rule_engine의 각 지표 배점)
  score_weights:
    trend_align: [0, 40]     # 1H 추세 일치
    macd: [0, 35]            # MACD 상태
    volume: [0, 30]          # 거래량
    rsi_pullback: [0, 25]    # RSI 위치
    supertrend: [0, 20]      # SuperTrend
```

**수정 불가능한 것**: 수수료 모델, 데이터 수집 로직, 리스크 게이트, 주문 실행.

### 실험 루프

```
while not stopped:
    1. research_program.md 읽기 (연구 방향)
    2. 최근 실험 이력(research_log.tsv) 읽기
    3. DeepSeek에 다음 실험 제안 요청
       - "이전 실험 결과를 보고, 다음에 시도할 변경을 JSON으로 제안해"
    4. 제안된 파라미터로 백테스트 실행 (ParameterOptimizer)
    5. OOS 결과 평가
       - PF, Sharpe, MDD, 거래 수 측정
    6. 판정:
       - 현재 baseline보다 개선 → config에 적용 + 새 baseline
       - 개선 아님 → 폐기
    7. 결과를 research_log.tsv에 기록
    8. 다음 실험으로
```

### 핵심 컴포넌트

#### 1. `research_program.md` (사람이 편집)

```markdown
# 연구 프로그램

## 현재 목표
Strategy A(추세추종)의 승률과 Profit Factor를 개선한다.

## 제약 조건
- MDD 15% 초과 금지
- 거래 수 30건 이상 유지
- 한 번에 파라미터 1~2개만 변경

## 연구 방향
- SL/TP 비율의 최적 조합 탐색
- 점수 가중치 조정 (현재 MACD 25점이 적절한지)
- cutoff 임계값 세밀 조정
- 국면별 차별화된 파라미터 검토

## 금지 사항
- 수수료/슬리피지 모델 수정 금지
- 전략 B/C/D 재활성화 시도 금지 (데이터 충분할 때까지)
```

#### 2. `AutoResearcher` 클래스

```python
class AutoResearcher:
    """자율 연구 엔진. autoresearch 패턴."""

    def __init__(
        self,
        store: MarketStore,
        config: AppConfig,
        deepseek_api_key: str,
        max_experiments: int = 10,  # 세션당 최대 실험 수
    ):
        ...

    async def run_session(self) -> list[ExperimentResult]:
        """실험 세션을 실행한다. max_experiments만큼 반복."""
        ...

    async def _propose_experiment(
        self, history: list[ExperimentResult],
    ) -> dict:
        """DeepSeek에 다음 실험을 제안받는다."""
        ...

    def _run_backtest(self, params: dict) -> BacktestMetrics:
        """파라미터로 백테스트를 실행한다."""
        ...

    def _evaluate(
        self, result: BacktestMetrics, baseline: BacktestMetrics,
    ) -> bool:
        """결과가 baseline보다 개선되었는지 판정한다."""
        ...

    def _log_result(self, experiment: ExperimentResult) -> None:
        """결과를 research_log.tsv에 기록한다."""
        ...
```

#### 3. `data/research_log.tsv` (실험 이력)

```
timestamp	experiment_id	strategy	params_changed	baseline_pf	result_pf	baseline_sharpe	result_sharpe	trades	mdd	verdict	description
2026-03-21T15:30	exp_001	trend_follow	sl_mult=2.5	1.13	1.25	0.8	1.1	145	0.06	KEEP	SL 3.0→2.5 축소
2026-03-21T15:37	exp_002	trend_follow	tp_rr=1.8	1.25	1.10	1.1	0.7	148	0.08	REVERT	TP 2.0→1.8 축소, PF 하락
```

#### 4. DeepSeek 프롬프트 설계

```
당신은 암호화폐 매매 전략 연구자입니다.

## 연구 프로그램
{research_program.md 내용}

## 현재 전략 파라미터
{config.yaml의 strategy_params}

## 현재 Baseline 성과
PF={pf}, Sharpe={sharpe}, MDD={mdd}, 거래={trades}건

## 최근 실험 이력
{research_log.tsv 최근 10건}

## 수정 가능한 파라미터와 허용 범위
{researchable_params}

## 지시사항
위 데이터를 분석하고, 다음 실험으로 시도할 파라미터 변경을 제안하세요.
- 이전에 실패한 방향은 피하세요
- 한 번에 1~2개 파라미터만 변경
- JSON 형식으로 응답: {"params": {"sl_mult": 2.5}, "hypothesis": "...", "expected_impact": "..."}
```

### 안전장치

| 안전장치 | 설명 |
|---------|------|
| 파라미터 범위 제한 | 각 파라미터에 [min, max] hard limit |
| 세션당 실험 수 제한 | `max_experiments` (기본 10회) |
| MDD 게이트 | 결과 MDD > 15%면 무조건 REVERT |
| 거래 수 최소 | OOS 거래 20건 미만이면 판정 보류 |
| config 백업 | 매 적용 전 `.bak` 생성 |
| 연속 실패 제한 | 5연속 REVERT면 세션 중단 |
| 읽기 전용 파일 | rule_engine.py 코드 직접 수정 불가 (파라미터만) |

### BacktestDaemon 통합

기존 daemon의 자동 최적화 슬롯에 AutoResearcher 연결:

```python
# backtesting/daemon.py의 run() 루프에서
if (c.auto_optimize_enabled
        and now.weekday() == opt_weekday
        and now.hour == opt_h ...):
    # 기존 그리드서치 대신 AutoResearcher 실행
    researcher = AutoResearcher(
        store=self._store,
        config=load_config(),
        deepseek_api_key=self._deepseek_key,
        max_experiments=10,
    )
    results = await researcher.run_session()
```

### 전략 점수 가중치 동적 조정

현재 rule_engine.py의 점수 가중치는 코드에 하드코딩:
```python
detail["trend_align"] = 30.0  # 하드코딩
detail["macd"] = 25.0         # 하드코딩
```

이를 config에서 읽도록 수정하면 LLM이 가중치도 실험 가능:
```yaml
strategy_params:
  trend_follow:
    sl_mult: 3.0
    tp_rr: 2.0
    # 점수 가중치 (NEW)
    w_trend_align: 30
    w_macd: 25
    w_volume: 20
    w_rsi_pullback: 15
    w_supertrend: 10
```

이렇게 하면 LLM이 "MACD 가중치를 25→35로 올려보자"같은 실험 가능.
코드 수정 없이 파라미터만으로 전략 행동을 변경할 수 있어 **안전**.

### 비용 추정

| 항목 | 추정 |
|------|------|
| 실험당 DeepSeek 호출 | Input ~15K + Output ~2K 토큰 |
| 실험당 백테스트 시간 | ~30초 (replay만, scan 캐시 활용) |
| 주 1회 세션 (10회 실험) | ~$0.06, ~5분 |
| 야간 세션 (50회 실험) | ~$0.30, ~25분 |
| 월간 총 비용 | **$1~5** |

### 산출물

1. `strategy/auto_researcher.py` — 자율 연구 엔진
2. `research_program.md` — 연구 방향 (사람이 편집)
3. `data/research_log.tsv` — 실험 이력
4. `configs/config.yaml` 확장 — 점수 가중치 외부화 + researchable_params
5. `backtesting/daemon.py` 수정 — AutoResearcher 통합
6. `strategy/rule_engine.py` 수정 — 점수 가중치를 config에서 읽기

### 검증 기준

| 기준 | 목표 |
|------|------|
| 자율 실행 | 사람 개입 없이 10회 실험 완료 |
| 안전성 | 실패 실험이 config에 반영되지 않음 |
| 기록 완전성 | 모든 실험이 research_log.tsv에 기록 |
| 개선 탐지 | PF 개선 시 자동 적용 확인 |
| 비용 | 세션당 $0.10 이내 |
