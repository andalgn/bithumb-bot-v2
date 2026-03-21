# AutoResearcher 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** DeepSeek LLM이 매매 전략 파라미터를 자율적으로 실험·개선하는 autoresearch 패턴 구현

**Architecture:** `AutoResearcher` 클래스가 DeepSeek API로 실험 가설을 생성하고, `ParameterOptimizer`로 백테스트를 실행하여 평가. 개선이면 config에 적용, 아니면 폐기. `research_program.md`로 방향 설정, `research_log.tsv`로 이력 관리.

**Tech Stack:** Python 3.12, httpx (DeepSeek API), ParameterOptimizer (기존), yaml, dataclass

**Spec:** `docs/superpowers/specs/2026-03-21-auto-researcher-design.md`

---

## 파일 구조

| 파일 | 변경 유형 | 역할 |
|------|----------|------|
| `strategy/rule_engine.py` | Modify | 점수 가중치를 `strategy_params`에서 읽도록 수정 |
| `strategy/auto_researcher.py` | Create | 자율 연구 엔진 (DeepSeek 호출 + 백테스트 + 평가) |
| `research_program.md` | Create | 연구 방향 설정 (사람이 편집) |
| `configs/config.yaml` | Modify | 점수 가중치 + auto_research 설정 추가 |
| `app/config.py` | Modify | AutoResearchConfig dataclass 추가 |
| `backtesting/daemon.py` | Modify | AutoResearcher 통합 |
| `tests/test_auto_researcher.py` | Create | 자율 연구 엔진 테스트 |
| `tests/test_score_weights.py` | Create | 점수 가중치 외부화 테스트 |

---

## Task 1: 전략 A 점수 가중치를 config에서 읽기

**Files:**
- Modify: `strategy/rule_engine.py`
- Modify: `configs/config.yaml`
- Create: `tests/test_score_weights.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/test_score_weights.py
"""점수 가중치 외부화 테스트."""
from strategy.rule_engine import RuleEngine


def test_default_weights():
    """strategy_params 없으면 기본 가중치를 사용한다."""
    engine = RuleEngine()
    weights = engine._get_weights("trend_follow")
    assert weights["trend_align"] == 30
    assert weights["macd"] == 25
    assert weights["volume"] == 20
    assert weights["rsi_pullback"] == 15
    assert weights["supertrend"] == 10


def test_custom_weights():
    """strategy_params에서 가중치를 읽는다."""
    params = {
        "trend_follow": {
            "sl_mult": 3.0,
            "tp_rr": 2.0,
            "w_trend_align": 35,
            "w_macd": 30,
        },
    }
    engine = RuleEngine(strategy_params=params)
    weights = engine._get_weights("trend_follow")
    assert weights["trend_align"] == 35
    assert weights["macd"] == 30
    # 미지정 항목은 기본값
    assert weights["volume"] == 20
    assert weights["rsi_pullback"] == 15
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_score_weights.py -v`
Expected: FAIL — `_get_weights` 없음

- [ ] **Step 3: RuleEngine에 _get_weights 메서드 + _score_strategy_a 수정**

`strategy/rule_engine.py`에 추가:

```python
# 기본 점수 가중치
DEFAULT_WEIGHTS: dict[str, dict[str, float]] = {
    "trend_follow": {
        "trend_align": 30, "macd": 25, "volume": 20,
        "rsi_pullback": 15, "supertrend": 10,
    },
}

class RuleEngine:
    def _get_weights(self, strategy: str) -> dict[str, float]:
        """전략의 점수 가중치를 반환한다. config에 w_ 접두사 항목이 있으면 사용."""
        defaults = DEFAULT_WEIGHTS.get(strategy, {}).copy()
        sp = self._strategy_params.get(strategy, {})
        for key, default_val in defaults.items():
            config_key = f"w_{key}"
            if config_key in sp:
                defaults[key] = float(sp[config_key])
        return defaults
```

`_score_strategy_a`의 하드코딩 점수를 가중치로 교체:

```python
def _score_strategy_a(self, ind_15m, ind_1h, candles_15m=None):
    detail: dict[str, float] = {}
    score = 0.0
    w = self._get_weights("trend_follow")

    # 1H 추세 일치
    ...
    if ema20_1h > ema50_1h and ema20_15m > ema50_15m:
        detail["trend_align"] = w["trend_align"]
        score += w["trend_align"]
    elif ema20_1h > ema50_1h:
        detail["trend_align"] = w["trend_align"] * 0.5
        score += w["trend_align"] * 0.5
    ...
    # MACD (동일 패턴으로 w["macd"] 사용)
    # volume → w["volume"]
    # rsi_pullback → w["rsi_pullback"]
    # supertrend → w["supertrend"]
```

- [ ] **Step 4: config.yaml에 기본 가중치 추가**

```yaml
strategy_params:
  trend_follow:
    sl_mult: 3.0
    tp_rr: 2.0
    w_trend_align: 30
    w_macd: 25
    w_volume: 20
    w_rsi_pullback: 15
    w_supertrend: 10
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `pytest tests/test_score_weights.py -v`
Expected: PASS

- [ ] **Step 6: 전체 테스트 통과 확인**

Run: `pytest tests/ --ignore=tests/test_bithumb_api.py -x -q`
Expected: 전체 PASS

- [ ] **Step 7: 커밋**

```bash
git add strategy/rule_engine.py configs/config.yaml tests/test_score_weights.py
git commit -m "refactor: externalize strategy A score weights to config"
```

---

## Task 2: AutoResearcher 핵심 클래스 구현

**Files:**
- Create: `strategy/auto_researcher.py`
- Create: `tests/test_auto_researcher.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/test_auto_researcher.py
"""AutoResearcher 테스트."""
import asyncio
import json
from unittest.mock import MagicMock, AsyncMock, patch

from strategy.auto_researcher import AutoResearcher, ExperimentResult


def test_evaluate_improved():
    """PF 개선 시 KEEP 판정."""
    researcher = AutoResearcher.__new__(AutoResearcher)
    researcher._min_pf = 1.0
    researcher._min_trades = 10
    researcher._max_mdd = 0.15

    baseline = MagicMock(profit_factor=1.0, trades=50, max_drawdown=0.05)
    result = MagicMock(profit_factor=1.2, trades=55, max_drawdown=0.06)

    assert researcher._evaluate(result, baseline) is True


def test_evaluate_worse():
    """PF 하락 시 REVERT 판정."""
    researcher = AutoResearcher.__new__(AutoResearcher)
    researcher._min_pf = 1.0
    researcher._min_trades = 10
    researcher._max_mdd = 0.15

    baseline = MagicMock(profit_factor=1.2, trades=50, max_drawdown=0.05)
    result = MagicMock(profit_factor=0.8, trades=45, max_drawdown=0.06)

    assert researcher._evaluate(result, baseline) is False


def test_evaluate_mdd_exceeded():
    """MDD 15% 초과 시 무조건 REVERT."""
    researcher = AutoResearcher.__new__(AutoResearcher)
    researcher._min_pf = 1.0
    researcher._min_trades = 10
    researcher._max_mdd = 0.15

    baseline = MagicMock(profit_factor=1.0, trades=50, max_drawdown=0.05)
    result = MagicMock(profit_factor=2.0, trades=50, max_drawdown=0.20)

    assert researcher._evaluate(result, baseline) is False


def test_evaluate_too_few_trades():
    """거래 수 부족 시 REVERT."""
    researcher = AutoResearcher.__new__(AutoResearcher)
    researcher._min_pf = 1.0
    researcher._min_trades = 20
    researcher._max_mdd = 0.15

    baseline = MagicMock(profit_factor=1.0, trades=50, max_drawdown=0.05)
    result = MagicMock(profit_factor=2.0, trades=5, max_drawdown=0.03)

    assert researcher._evaluate(result, baseline) is False


def test_parse_experiment_proposal():
    """DeepSeek JSON 응답 파싱."""
    researcher = AutoResearcher.__new__(AutoResearcher)
    content = '''Here is my proposal:
```json
{"params": {"sl_mult": 2.5, "tp_rr": 1.8}, "hypothesis": "SL 축소", "expected_impact": "PF 5% 개선"}
```'''
    result = researcher._parse_proposal(content)
    assert result["params"]["sl_mult"] == 2.5
    assert "hypothesis" in result


def test_log_result_creates_tsv(tmp_path):
    """실험 결과를 TSV에 기록한다."""
    log_path = tmp_path / "research_log.tsv"
    researcher = AutoResearcher.__new__(AutoResearcher)
    researcher._log_path = log_path

    exp = ExperimentResult(
        experiment_id="exp_001",
        strategy="trend_follow",
        params_changed={"sl_mult": 2.5},
        baseline_pf=1.0,
        result_pf=1.2,
        baseline_sharpe=0.8,
        result_sharpe=1.0,
        trades=50,
        mdd=0.05,
        verdict="KEEP",
        description="SL 축소 실험",
    )
    researcher._log_result(exp)

    lines = log_path.read_text().strip().split("\n")
    assert len(lines) == 2  # header + 1 row
    assert "exp_001" in lines[1]
    assert "KEEP" in lines[1]
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_auto_researcher.py -v`
Expected: FAIL — `cannot import name 'AutoResearcher'`

- [ ] **Step 3: AutoResearcher 구현**

```python
# strategy/auto_researcher.py
"""자율 연구 엔진 — autoresearch 패턴.

DeepSeek LLM이 실험 가설을 생성하고, 백테스트로 검증.
개선이면 유지, 아니면 롤백. research_program.md로 방향 설정.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from backtesting.optimizer import OptResult

logger = logging.getLogger(__name__)

RESEARCH_PROGRAM_PATH = Path("research_program.md")
LOG_PATH = Path("data/research_log.tsv")

# 파라미터 허용 범위
PARAM_BOUNDS: dict[str, dict[str, tuple[float, float]]] = {
    "trend_follow": {
        "sl_mult": (1.0, 5.0),
        "tp_rr": (1.0, 5.0),
        "cutoff_full": (55, 90),
        "w_trend_align": (0, 45),
        "w_macd": (0, 40),
        "w_volume": (0, 35),
        "w_rsi_pullback": (0, 30),
        "w_supertrend": (0, 25),
    },
}


@dataclass
class ExperimentResult:
    """실험 결과."""

    experiment_id: str = ""
    strategy: str = ""
    params_changed: dict = field(default_factory=dict)
    baseline_pf: float = 0.0
    result_pf: float = 0.0
    baseline_sharpe: float = 0.0
    result_sharpe: float = 0.0
    trades: int = 0
    mdd: float = 0.0
    verdict: str = ""  # KEEP / REVERT
    description: str = ""


class AutoResearcher:
    """자율 연구 엔진."""

    def __init__(
        self,
        store: object,
        coins: list[str],
        deepseek_api_key: str,
        deepseek_base_url: str = "https://api.deepseek.com/v1",
        max_experiments: int = 10,
        max_consecutive_failures: int = 5,
        log_path: Path | None = None,
    ) -> None:
        """초기화."""
        self._store = store
        self._coins = coins
        self._deepseek_key = deepseek_api_key
        self._deepseek_url = deepseek_base_url
        self._max_experiments = max_experiments
        self._max_failures = max_consecutive_failures
        self._log_path = log_path or LOG_PATH
        self._min_pf = 1.0
        self._min_trades = 20
        self._max_mdd = 0.15

    async def run_session(self) -> list[ExperimentResult]:
        """실험 세션을 실행한다."""
        from app.config import load_config
        from backtesting.optimizer import ParameterOptimizer

        config = load_config()
        results: list[ExperimentResult] = []

        # 데이터 로딩
        candles_15m, candles_1h = self._load_candles()
        if not any(len(v) > 200 for v in candles_15m.values()):
            logger.warning("AutoResearcher: 데이터 부족")
            return results

        # rule_engine 로그 억제
        import logging as _logging
        _logging.getLogger("strategy.rule_engine").setLevel(_logging.WARNING)
        _logging.getLogger("backtesting.optimizer").setLevel(_logging.WARNING)

        strategy = "trend_follow"  # 현재 활성 전략
        current_params = config.strategy_params.get(strategy, {})

        # baseline 계산
        optimizer = ParameterOptimizer(self._coins, config)
        baseline = optimizer.run_single(
            strategy, current_params, candles_15m, candles_1h,
        )
        logger.info(
            "Baseline: PF=%.2f Sharpe=%.2f Trades=%d",
            baseline.profit_factor, baseline.sharpe, baseline.trades,
        )

        # 실험 이력 로드
        history = self._load_history()
        consecutive_failures = 0

        for i in range(self._max_experiments):
            exp_id = f"exp_{int(time.time())}_{i:03d}"

            # 연속 실패 제한
            if consecutive_failures >= self._max_failures:
                logger.info("연속 %d회 실패, 세션 중단", self._max_failures)
                break

            # DeepSeek에 실험 제안 요청
            proposal = await self._propose_experiment(
                strategy, current_params, baseline, history,
            )
            if not proposal or "params" not in proposal:
                logger.warning("실험 제안 파싱 실패, 건너뜀")
                consecutive_failures += 1
                continue

            # 파라미터 범위 검증
            proposed_params = {**current_params, **proposal["params"]}
            if not self._validate_bounds(strategy, proposed_params):
                logger.warning("범위 초과 파라미터, 건너뜀")
                consecutive_failures += 1
                continue

            # 백테스트 실행 (entry 캐시 재사용)
            optimizer._entry_cache = {}
            result = optimizer.run_single(
                strategy, proposed_params, candles_15m, candles_1h,
            )

            # 평가
            keep = self._evaluate(result, baseline)
            verdict = "KEEP" if keep else "REVERT"

            exp = ExperimentResult(
                experiment_id=exp_id,
                strategy=strategy,
                params_changed=proposal["params"],
                baseline_pf=baseline.profit_factor,
                result_pf=result.profit_factor,
                baseline_sharpe=baseline.sharpe,
                result_sharpe=result.sharpe,
                trades=result.trades,
                mdd=result.max_drawdown,
                verdict=verdict,
                description=proposal.get("hypothesis", ""),
            )
            results.append(exp)
            history.append(exp)
            self._log_result(exp)

            logger.info(
                "[%s] %s: PF %.2f→%.2f %s | %s",
                exp_id, verdict,
                baseline.profit_factor, result.profit_factor,
                proposal["params"],
                proposal.get("hypothesis", ""),
            )

            if keep:
                current_params = proposed_params
                baseline = result
                consecutive_failures = 0
            else:
                consecutive_failures += 1

        return results

    def _load_candles(self) -> tuple[dict, dict]:
        """시장 데이터를 로드한다."""
        candles_15m: dict[str, list] = {}
        candles_1h: dict[str, list] = {}
        for coin in self._coins:
            candles_15m[coin] = self._store.get_candles(coin, "15m", limit=5000)
            candles_1h[coin] = self._store.get_candles(coin, "1h", limit=5000)
        return candles_15m, candles_1h

    async def _propose_experiment(
        self,
        strategy: str,
        current_params: dict,
        baseline: OptResult,
        history: list[ExperimentResult],
    ) -> dict | None:
        """DeepSeek에 다음 실험을 제안받는다."""
        try:
            import httpx
        except ImportError:
            logger.warning("httpx 미설치")
            return None

        program = ""
        if RESEARCH_PROGRAM_PATH.exists():
            program = RESEARCH_PROGRAM_PATH.read_text(encoding="utf-8")

        # 최근 10건 이력
        recent = history[-10:] if history else []
        history_text = "\n".join(
            f"  {e.experiment_id}: {e.params_changed} → PF {e.baseline_pf:.2f}→{e.result_pf:.2f} [{e.verdict}] {e.description}"
            for e in recent
        ) if recent else "  (이력 없음)"

        bounds_text = json.dumps(
            PARAM_BOUNDS.get(strategy, {}), indent=2,
        )

        prompt = f"""당신은 암호화폐 매매 전략 연구자입니다.

## 연구 프로그램
{program or "(미설정)"}

## 현재 전략: {strategy}
## 현재 파라미터
{json.dumps(current_params, indent=2)}

## 현재 Baseline 성과
PF={baseline.profit_factor:.3f}, Sharpe={baseline.sharpe:.3f}, Trades={baseline.trades}, MDD={baseline.max_drawdown:.2%}

## 최근 실험 이력
{history_text}

## 수정 가능한 파라미터와 허용 범위
{bounds_text}

## 지시사항
1. 위 데이터를 분석하고, 다음 실험으로 시도할 파라미터 변경을 제안하세요.
2. 이전에 REVERT된 방향은 피하세요.
3. 한 번에 1~2개 파라미터만 변경하세요.
4. 반드시 아래 JSON 형식으로만 응답하세요:

{{"params": {{"파라미터명": 값}}, "hypothesis": "가설 설명", "expected_impact": "예상 효과"}}"""

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    f"{self._deepseek_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._deepseek_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "deepseek-chat",
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 500,
                        "temperature": 0.7,
                    },
                )
                if resp.status_code != 200:
                    logger.warning("DeepSeek API 오류: %d", resp.status_code)
                    return None

                content = resp.json()["choices"][0]["message"]["content"]
                return self._parse_proposal(content)

        except Exception:
            logger.exception("DeepSeek API 호출 실패")
            return None

    def _parse_proposal(self, content: str) -> dict | None:
        """DeepSeek 응답에서 실험 제안을 파싱한다."""
        # JSON 블록 추출
        for start_marker in ["```json", "```"]:
            if start_marker in content:
                start = content.find(start_marker) + len(start_marker)
                end = content.find("```", start)
                if end > start:
                    content = content[start:end].strip()
                    break

        # { } 찾기
        brace_start = content.find("{")
        brace_end = content.rfind("}") + 1
        if brace_start >= 0 and brace_end > brace_start:
            try:
                return json.loads(content[brace_start:brace_end])
            except json.JSONDecodeError:
                pass
        return None

    def _validate_bounds(self, strategy: str, params: dict) -> bool:
        """파라미터가 허용 범위 내인지 검증한다."""
        bounds = PARAM_BOUNDS.get(strategy, {})
        for key, value in params.items():
            if key in bounds:
                lo, hi = bounds[key]
                if not (lo <= float(value) <= hi):
                    logger.warning(
                        "범위 초과: %s=%s (허용: %.1f~%.1f)",
                        key, value, lo, hi,
                    )
                    return False
        return True

    def _evaluate(self, result: OptResult, baseline: OptResult) -> bool:
        """결과가 baseline보다 개선되었는지 판정한다."""
        # MDD 초과 → 무조건 REVERT
        if result.max_drawdown > self._max_mdd:
            return False
        # 거래 수 부족 → REVERT
        if result.trades < self._min_trades:
            return False
        # PF 개선 → KEEP
        return result.profit_factor > baseline.profit_factor

    def _load_history(self) -> list[ExperimentResult]:
        """기존 실험 이력을 로드한다."""
        if not self._log_path.exists():
            return []
        results = []
        lines = self._log_path.read_text(encoding="utf-8").strip().split("\n")
        for line in lines[1:]:  # header skip
            cols = line.split("\t")
            if len(cols) >= 11:
                results.append(ExperimentResult(
                    experiment_id=cols[1],
                    strategy=cols[2],
                    params_changed=json.loads(cols[3]) if cols[3] else {},
                    baseline_pf=float(cols[4]),
                    result_pf=float(cols[5]),
                    baseline_sharpe=float(cols[6]),
                    result_sharpe=float(cols[7]),
                    trades=int(cols[8]),
                    mdd=float(cols[9]),
                    verdict=cols[10],
                    description=cols[11] if len(cols) > 11 else "",
                ))
        return results

    def _log_result(self, exp: ExperimentResult) -> None:
        """실험 결과를 TSV에 기록한다."""
        from datetime import datetime

        self._log_path.parent.mkdir(parents=True, exist_ok=True)

        if not self._log_path.exists():
            header = (
                "timestamp\texperiment_id\tstrategy\tparams_changed\t"
                "baseline_pf\tresult_pf\tbaseline_sharpe\tresult_sharpe\t"
                "trades\tmdd\tverdict\tdescription\n"
            )
            self._log_path.write_text(header, encoding="utf-8")

        row = (
            f"{datetime.now().isoformat(timespec='seconds')}\t"
            f"{exp.experiment_id}\t{exp.strategy}\t"
            f"{json.dumps(exp.params_changed)}\t"
            f"{exp.baseline_pf:.4f}\t{exp.result_pf:.4f}\t"
            f"{exp.baseline_sharpe:.4f}\t{exp.result_sharpe:.4f}\t"
            f"{exp.trades}\t{exp.mdd:.4f}\t{exp.verdict}\t"
            f"{exp.description}\n"
        )
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(row)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_auto_researcher.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add strategy/auto_researcher.py tests/test_auto_researcher.py
git commit -m "feat: add AutoResearcher — autonomous strategy experimentation engine"
```

---

## Task 3: research_program.md 생성 + BacktestDaemon 통합

**Files:**
- Create: `research_program.md`
- Modify: `backtesting/daemon.py`
- Modify: `app/config.py`
- Modify: `configs/config.yaml`

- [ ] **Step 1: research_program.md 작성**

```markdown
# 연구 프로그램

## 현재 목표
Strategy A(추세추종)의 OOS Profit Factor를 1.2 이상으로 개선한다.

## 제약 조건
- MDD 15% 초과 금지
- OOS 거래 수 20건 이상 유지
- 한 번에 파라미터 1~2개만 변경
- 점수 가중치 합계가 100에서 크게 벗어나지 않도록

## 연구 방향
- SL/TP 비율의 최적 조합 탐색 (sl_mult와 tp_rr 미세 조정)
- 점수 가중치 재분배 (MACD vs 추세 일치 vs 거래량 비중)
- cutoff 임계값 세밀 조정 (70 ± 5 범위)

## 금지 사항
- 수수료/슬리피지 모델 수정 금지
- 전략 B/C/D 재활성화 시도 금지
```

- [ ] **Step 2: config.yaml에 auto_research 설정 추가**

```yaml
backtest:
  auto_research:
    enabled: true
    day: sunday
    time: "03:00"
    max_experiments: 10
    max_consecutive_failures: 5
```

- [ ] **Step 3: AppConfig에 auto_research 필드 추가**

`app/config.py`의 `BacktestConfig`에 추가:
```python
auto_research_enabled: bool = True
auto_research_day: str = "sunday"
auto_research_time: str = "03:00"
auto_research_max_experiments: int = 10
auto_research_max_failures: int = 5
```

`_build_backtest()`에 추가:
```python
research = raw.get("auto_research", {})
# ...
auto_research_enabled=research.get("enabled", True),
auto_research_day=research.get("day", "sunday"),
auto_research_time=str(research.get("time", "03:00")),
auto_research_max_experiments=research.get("max_experiments", 10),
auto_research_max_failures=research.get("max_consecutive_failures", 5),
```

- [ ] **Step 4: BacktestDaemon에 AutoResearcher 통합**

`backtesting/daemon.py`의 `run()` 루프에 추가:

```python
# 자율 연구: 매주
if (c.auto_research_enabled
        and now.weekday() == self._parse_weekday(c.auto_research_day)
        and now.hour == research_h
        and now.minute >= research_m
        and self._last_research != week_key):
    self._last_research = week_key
    await self._run_auto_research()
```

`_run_auto_research()` 메서드:
```python
async def _run_auto_research(self) -> None:
    """자율 연구 세션을 실행한다."""
    if not self._store:
        return
    logger.info("자율 연구 세션 시작")

    from strategy.auto_researcher import AutoResearcher

    researcher = AutoResearcher(
        store=self._store,
        coins=self._coins,
        deepseek_api_key=self._deepseek_key,
        max_experiments=self._config.auto_research_max_experiments,
        max_consecutive_failures=self._config.auto_research_max_failures,
    )
    results = await researcher.run_session()

    # KEEP된 최종 파라미터를 config에 적용
    kept = [r for r in results if r.verdict == "KEEP"]
    if kept and self._store:
        last_kept = kept[-1]
        from pathlib import Path
        config_path = Path("configs/config.yaml")
        final_params = {}
        for r in kept:
            final_params.update(r.params_changed)
        self._apply_optimized_params(
            last_kept.strategy, final_params, config_path,
        )

    # 텔레그램 리포트
    if self._notifier and results:
        total = len(results)
        keeps = len(kept)
        lines = [
            f"<b>자율 연구 완료</b> ({keeps}/{total} 개선)",
        ]
        for r in results:
            icon = "✓" if r.verdict == "KEEP" else "✗"
            lines.append(
                f"  {icon} {r.params_changed} PF {r.baseline_pf:.2f}→{r.result_pf:.2f}"
            )
        await self._notifier.send("\n".join(lines))
```

생성자에 `deepseek_api_key` 파라미터 + `_last_research` 추가.

- [ ] **Step 5: main.py에서 deepseek_api_key 전달**

```python
self._backtest_daemon = BacktestDaemon(
    journal=self._journal,
    notifier=self._notifier,
    config=config.backtest,
    store=self._market_store,
    client=self._client,
    coins=config.coins,
    deepseek_api_key=config.secrets.deepseek_api_key,
)
```

- [ ] **Step 6: 전체 테스트 통과 확인**

Run: `pytest tests/ --ignore=tests/test_bithumb_api.py -x -q`
Expected: 전체 PASS

- [ ] **Step 7: 커밋**

```bash
git add research_program.md backtesting/daemon.py app/config.py app/main.py configs/config.yaml
git commit -m "feat: integrate AutoResearcher into BacktestDaemon with weekly schedule"
```

---

## 의존성 그래프

```
Task 1 (점수 가중치 외부화)
  └→ Task 2 (AutoResearcher 핵심 구현)
       └→ Task 3 (research_program.md + daemon 통합)
```

Task 1이 선행 — LLM이 가중치를 실험하려면 config에서 읽어야 함.
Task 2는 독립 실행 가능하나, 가중치 실험은 Task 1 이후에 의미 있음.
Task 3은 Task 2에 의존.
