# 백테스트 전략 최적화 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 프록시 인프라 적용 → 시장 데이터 수집 → 전략 파라미터 최적화 → 로직 개선 → 강건성 검증까지 end-to-end 백테스트 파이프라인 완성

**Architecture:** BithumbClient에 프록시 지원 추가 후 10개 코인 캔들 데이터 최대 수집. 기존 2단계 옵티마이저(Entry 캐싱 → SL/TP 리플레이)로 1차 최적화, 결과 분석 후 전략 로직 개선, 2차 fine-tuning, Walk-Forward/Monte Carlo/Sensitivity 강건성 검증.

**Tech Stack:** Python 3.12, aiohttp (proxy), SQLite WAL, pytest, ruff

**Spec:** `docs/superpowers/specs/2026-03-21-backtest-optimization-design.md`

---

## 파일 구조

| 파일 | 변경 유형 | 역할 |
|------|----------|------|
| `configs/config.yaml` | Modify | proxy 설정 항목 추가 |
| `app/config.py` | Modify | proxy 필드 로딩 |
| `market/bithumb_api.py` | Modify | aiohttp 요청에 proxy 전달 |
| `scripts/download_and_backtest.py` | Modify | 프록시 경유 다운로드 |
| `scripts/optimize.py` | Modify | 프록시 경유 |
| `backtesting/walk_forward.py` | Modify | 설정 가능한 구간 수/데이터 범위 |
| `backtesting/monte_carlo.py` | Modify | P10 필드 추가 |
| `backtesting/sensitivity.py` | Modify | replay_with_params 기반 재작성 |
| `backtesting/daemon.py` | Modify (별도 계획) | 스텁 메서드 완성 — 이 계획에서는 검증 도구를 직접 호출; daemon 통합은 LIVE 준비 시 별도 진행 |
| `tests/test_proxy_config.py` | Create | 프록시 설정 테스트 |
| `tests/test_walk_forward_v2.py` | Create | 리팩토링된 WF 테스트 |
| `tests/test_monte_carlo_v2.py` | Create | P10 추가 MC 테스트 |
| `tests/test_sensitivity_v2.py` | Create | 리플레이 기반 Sensitivity 테스트 |

---

## Task 1: 프록시 설정을 config.yaml + Config에 추가

**Files:**
- Modify: `configs/config.yaml`
- Modify: `app/config.py`
- Create: `tests/test_proxy_config.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/test_proxy_config.py
"""프록시 설정 로딩 테스트."""
from app.config import load_config


def test_load_config_has_proxy():
    """config.yaml에서 proxy 필드를 로딩한다."""
    config = load_config()
    assert hasattr(config, "proxy")
    assert isinstance(config.proxy, str)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_proxy_config.py -v`
Expected: FAIL — `AttributeError: 'AppConfig' has no attribute 'proxy'`

- [ ] **Step 3: config.yaml에 proxy 항목 추가**

`configs/config.yaml` 최상위에 추가:
```yaml
proxy: "http://127.0.0.1:1081"
```

- [ ] **Step 4: AppConfig에 proxy 필드 추가**

`app/config.py`의 `AppConfig` dataclass (line 163)에 필드 추가:
```python
proxy: str = ""
```

`load_config()` (line 284-307)의 `return AppConfig(...)` 블록 안에 proxy 로딩 추가:
```python
proxy=raw.get("proxy", "") or os.environ.get("HTTPS_PROXY", ""),
```

`os` import가 없으면 파일 상단에 `import os` 추가.

- [ ] **Step 5: 테스트 통과 확인**

Run: `pytest tests/test_proxy_config.py -v`
Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add configs/config.yaml app/config.py tests/test_proxy_config.py
git commit -m "feat: add proxy config field for HTTP proxy support"
```

---

## Task 2: BithumbClient에 프록시 적용

**Files:**
- Modify: `market/bithumb_api.py`

- [ ] **Step 1: 테스트 추가**

```python
# tests/test_proxy_config.py에 추가
from market.bithumb_api import BithumbClient


def test_bithumb_client_accepts_proxy():
    """BithumbClient가 proxy 파라미터를 받는다."""
    client = BithumbClient(
        api_key="test",
        api_secret="test",
        proxy="http://127.0.0.1:1081",
    )
    assert client._proxy == "http://127.0.0.1:1081"


def test_bithumb_client_proxy_default_empty():
    """proxy 미지정 시 빈 문자열."""
    client = BithumbClient(api_key="test", api_secret="test")
    assert client._proxy == ""
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_proxy_config.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'proxy'`

- [ ] **Step 3: BithumbClient 생성자에 proxy 추가**

`market/bithumb_api.py` line 36 `__init__`에 `proxy: str = ""` 파라미터 추가.
`self._proxy = proxy` 저장.

- [ ] **Step 4: _public_request, _private_request에 proxy 전달**

`_public_request()` (line 118)의 `session.get()` 호출에:
```python
proxy=self._proxy or None
```

`_private_request()` (line 151)의 `session.post()` 호출에:
```python
proxy=self._proxy or None
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `pytest tests/test_proxy_config.py -v`
Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add market/bithumb_api.py tests/test_proxy_config.py
git commit -m "feat: add proxy support to BithumbClient"
```

---

## Task 3: 스크립트에 프록시 전달

**Files:**
- Modify: `scripts/download_and_backtest.py`
- Modify: `scripts/optimize.py`

- [ ] **Step 1: download_and_backtest.py 수정**

BithumbClient 생성 부분 (line 391-395)에 proxy 추가:
```python
client = BithumbClient(
    api_key=config.secrets.bithumb_api_key,
    api_secret=config.secrets.bithumb_api_secret,
    base_url=config.secrets.bithumb_api_url or config.bithumb.base_url,
    proxy=config.proxy,
)
```

- [ ] **Step 2: optimize.py 수정**

BithumbClient 생성 부분 (line 189-193)에 proxy 추가:
```python
client = BithumbClient(
    api_key=config.secrets.bithumb_api_key,
    api_secret=config.secrets.bithumb_api_secret,
    base_url=config.secrets.bithumb_api_url or config.bithumb.base_url,
    proxy=config.proxy,
)
```

- [ ] **Step 3: import 확인 (smoke test)**

```bash
python3 -c "from scripts.download_and_backtest import *; print('OK')"
python3 -c "from scripts.optimize import *; print('OK')"
```
Expected: 오류 없이 OK 출력

- [ ] **Step 4: ruff 검사**

Run: `ruff check scripts/download_and_backtest.py scripts/optimize.py`
Expected: 오류 없음

- [ ] **Step 5: 커밋**

```bash
git add scripts/download_and_backtest.py scripts/optimize.py
git commit -m "feat: pass proxy config to BithumbClient in scripts"
```

---

## Task 4: 프록시 경유 빗썸 API 연결 테스트

**Files:** 없음 (수동 테스트)

- [ ] **Step 1: 빗썸 현재가 조회 테스트**

```bash
cd /home/bythejune/projects/bithumb-bot-v2
source venv/bin/activate
python3 -c "
import asyncio
from app.config import load_config
from market.bithumb_api import BithumbClient

async def test():
    config = load_config()
    client = BithumbClient(
        api_key=config.secrets.bithumb_api_key,
        api_secret=config.secrets.bithumb_api_secret,
        proxy=config.proxy,
    )
    ticker = await client.get_ticker('BTC')
    print(f'BTC: {ticker}')
    await client.close()

asyncio.run(test())
"
```

Expected: BTC 현재가 정상 출력

- [ ] **Step 2: 기존 테스트 전체 통과 확인**

Run: `pytest tests/ -v --timeout=30`
Expected: 기존 테스트 모두 PASS (프록시 추가가 기존 동작에 영향 없음)

---

## Task 5: 시장 데이터 수집

**Files:** 없음 (스크립트 실행)

- [ ] **Step 1: 데이터 다운로드 실행**

```bash
cd /home/bythejune/projects/bithumb-bot-v2
source venv/bin/activate
python3 scripts/download_and_backtest.py
```

Expected: 10개 코인 × 15M/1H 캔들 다운로드 → `data/market_data.db` 생성

- [ ] **Step 2: 데이터 검증**

```bash
python3 -c "
from market.market_store import MarketStore
store = MarketStore()
for coin in ['BTC','ETH','XRP','SOL','RENDER','VIRTUAL','EIGEN','ONDO','TAO','LDO']:
    candles_1h = store.get_candles(coin, '1h', limit=10000)
    candles_15m = store.get_candles(coin, '15m', limit=50000)
    print(f'{coin:8s}  1H: {len(candles_1h):>5}봉  15M: {len(candles_15m):>6}봉')
store.close()
"
```

Expected: 각 코인별 수천~수만 봉 확인

---

## Task 6: Walk-Forward 리팩토링 (설정 가능한 구간 수)

**Files:**
- Modify: `backtesting/walk_forward.py`
- Create: `tests/test_walk_forward_v2.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/test_walk_forward_v2.py
"""Walk-Forward 리팩토링 테스트."""
from backtesting.walk_forward import WalkForward


def test_wf_custom_segments():
    """6구간 Walk-Forward를 생성할 수 있다."""
    wf = WalkForward(num_segments=6)
    assert wf._num_segments == 6


def test_wf_custom_data_days():
    """데이터 기간을 180일로 설정할 수 있다."""
    wf = WalkForward(data_days=180, num_segments=6)
    assert wf._data_days == 180


def test_wf_run_with_6_segments():
    """6구간으로 실행하면 6개 세그먼트 결과가 나온다."""
    # 180일 데이터, 6구간 시뮬레이션
    trades = []
    for day in range(180):
        pnl = 100 if day % 3 == 0 else -50
        trades.append({
            "day": day,
            "strategy": "trend_follow",
            "entry_price": 1000,
            "exit_price": 1000 + pnl,
            "quantity": 1.0,
            "coin": "BTC",
        })
    wf = WalkForward(data_days=180, num_segments=6)
    result = wf.run(trades)
    assert result.total_segments == 6
    assert len(result.segments) == 6


def test_wf_verdict_75pct():
    """75% 이상 통과 시 'good' 이상 verdict."""
    trades = []
    for day in range(120):
        trades.append({
            "day": day,
            "strategy": "trend_follow",
            "entry_price": 1000,
            "exit_price": 1100,
            "quantity": 1.0,
            "coin": "BTC",
        })
    wf = WalkForward(data_days=120, num_segments=4)
    result = wf.run(trades)
    assert result.verdict in ("robust", "good")
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_walk_forward_v2.py -v`
Expected: FAIL — 현재 WF가 30일/4구간 하드코딩

- [ ] **Step 3: WalkForward verdict 로직 리팩토링**

현재 생성자는 이미 `num_segments`, `data_days`를 받지만, verdict 로직 (lines 131-136)이 `pass_count >= 4`, `>= 3`으로 하드코딩되어 있음. 이를 비율 기반으로 수정:

```python
# 기존 (하드코딩):
if pass_count >= 4: verdict = "robust"
elif pass_count >= 3: verdict = "good"

# 변경 (비율 기반):
ratio = pass_count / total_segments
if ratio >= 1.0: verdict = "robust"
elif ratio >= 0.75: verdict = "good"
elif ratio >= 0.5: verdict = "warning"
else: verdict = "poor"
```

또한 구간 분할 로직이 동적 `num_segments`에 맞게 동작하는지 확인하고, 필요시 수정.

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_walk_forward_v2.py -v`
Expected: PASS

- [ ] **Step 5: 기존 WF 테스트도 통과 확인**

Run: `pytest tests/ -k walk_forward -v`
Expected: 기존 + 새 테스트 모두 PASS

- [ ] **Step 6: 커밋**

```bash
git add backtesting/walk_forward.py tests/test_walk_forward_v2.py
git commit -m "refactor: make WalkForward segment count and data range configurable"
```

---

## Task 7: Monte Carlo에 P10 추가

**Files:**
- Modify: `backtesting/monte_carlo.py`
- Create: `tests/test_monte_carlo_v2.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/test_monte_carlo_v2.py
"""Monte Carlo P10 추가 테스트."""
from backtesting.monte_carlo import MonteCarlo, MonteCarloResult


def test_mc_result_has_p10():
    """MonteCarloResult에 pnl_percentile_10 필드가 있다."""
    mc = MonteCarlo(iterations=100)
    pnl_list = [100, -50, 200, -30, 150, -80, 120, -40, 90, -60] * 10
    result = mc.run(pnl_list, initial_equity=10_000_000)
    assert hasattr(result, "pnl_percentile_10")
    assert isinstance(result.pnl_percentile_10, float)


def test_mc_verdict_uses_p10():
    """P10 > 0 AND P5 > -2% 기준으로 verdict 판단."""
    mc = MonteCarlo(iterations=100)
    # 대부분 수익인 PnL → safe
    pnl_list = [100_000] * 80 + [-50_000] * 20
    result = mc.run(pnl_list, initial_equity=10_000_000)
    assert result.verdict == "safe"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_monte_carlo_v2.py -v`
Expected: FAIL — `pnl_percentile_10` 필드 없음

- [ ] **Step 3: MonteCarloResult에 P10 추가**

`backtesting/monte_carlo.py`의 `MonteCarloResult` dataclass에:
```python
pnl_percentile_10: float
```

`run()` 메서드에서 P10 계산 추가:
```python
pnl_percentile_10=sorted_pnls[int(n * 0.10)],
```

verdict 로직 업데이트 (기존 P5 > 0 → 강화):
- "safe": P10 > 0 AND P5 > -2% of initial_equity
- "caution": P5 > -3% of initial_equity
- "danger": else

**주의:** 기존 MC 테스트가 있다면 verdict 기준 변경으로 실패할 수 있음. `pytest tests/ -k monte_carlo`로 기존 테스트 확인 후 함께 업데이트.

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_monte_carlo_v2.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add backtesting/monte_carlo.py tests/test_monte_carlo_v2.py
git commit -m "feat: add P10 percentile to Monte Carlo and update verdict logic"
```

---

## Task 8: Sensitivity 분석기를 replay_with_params 기반으로 재작성

**Files:**
- Modify: `backtesting/sensitivity.py`
- Create: `tests/test_sensitivity_v2.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/test_sensitivity_v2.py
"""Sensitivity 분석기 재작성 테스트."""
from unittest.mock import MagicMock, patch
from backtesting.sensitivity import SensitivityAnalyzer


def test_sensitivity_calls_replay():
    """Sensitivity가 근사치가 아닌 replay_with_params를 호출한다."""
    analyzer = SensitivityAnalyzer()
    # replay를 실제로 호출하는지 검증
    mock_optimizer = MagicMock()
    mock_optimizer.replay_with_params.return_value = MagicMock(
        sharpe=1.5, profit_factor=1.8, trades=50, win_rate=0.55,
        expectancy=100, max_drawdown=0.05, total_pnl=5000,
    )
    result = analyzer.run_with_optimizer(
        optimizer=mock_optimizer,
        base_params={"sl_mult": 2.0, "tp_rr": 3.0},
        strategy_name="trend_follow",
        entries=[],  # mock이니까 빈 리스트
    )
    assert mock_optimizer.replay_with_params.call_count >= 5  # steps=5


def test_sensitivity_cv_calculation():
    """CV가 올바르게 계산된다."""
    analyzer = SensitivityAnalyzer(steps=3)
    mock_optimizer = MagicMock()
    # 동일한 결과 → CV ≈ 0 → robust
    mock_optimizer.replay_with_params.return_value = MagicMock(
        sharpe=1.5, profit_factor=1.8, trades=50, win_rate=0.55,
        expectancy=100, max_drawdown=0.05, total_pnl=5000,
    )
    result = analyzer.run_with_optimizer(
        optimizer=mock_optimizer,
        base_params={"sl_mult": 2.0},
        strategy_name="trend_follow",
        entries=[],
    )
    assert len(result.params) == 1
    assert result.params[0].cv < 0.01  # 동일 결과이므로 CV ≈ 0
    assert result.params[0].verdict == "robust"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_sensitivity_v2.py -v`
Expected: FAIL — `run_with_optimizer` 메서드 없음

- [ ] **Step 3: SensitivityAnalyzer에 run_with_optimizer 메서드 추가**

`backtesting/sensitivity.py`에 새 메서드 추가:

```python
def run_with_optimizer(
    self,
    optimizer: "ParameterOptimizer",
    base_params: dict,
    strategy_name: str,
    entries: list,
) -> SensitivityResult:
    """replay_with_params 기반 실제 민감도 분석."""
    param_results = []
    for param_name, base_value in base_params.items():
        variations = np.linspace(
            base_value * (1 - self._variation_pct),
            base_value * (1 + self._variation_pct),
            self._steps,
        )
        sharpes = []
        for v in variations:
            test_params = {**base_params, param_name: v}
            result = optimizer.replay_with_params(
                strategy_name=strategy_name,
                params=test_params,
                entries=entries,
            )
            sharpes.append(result.sharpe)

        mean_s = np.mean(sharpes)
        cv = np.std(sharpes) / mean_s if mean_s != 0 else float("inf")
        verdict = self._cv_verdict(cv)
        param_results.append(ParamSensitivity(
            name=param_name,
            base_value=base_value,
            cv=cv,
            verdict=verdict,
            values=list(variations),
            sharpes=sharpes,
        ))

    return SensitivityResult(
        params=param_results,
        sensitive_count=sum(1 for p in param_results if p.verdict in ("sensitive", "danger")),
        robust_count=sum(1 for p in param_results if p.verdict == "robust"),
    )
```

기존 `run()` 메서드는 하위 호환성을 위해 유지 (deprecated 표시).

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_sensitivity_v2.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add backtesting/sensitivity.py tests/test_sensitivity_v2.py
git commit -m "feat: add replay-based sensitivity analysis (replaces approximation)"
```

---

## Task 9: 1차 파라미터 최적화 실행

**Files:** 없음 (기존 optimize.py 실행)

- [ ] **Step 1: 최적화 실행**

```bash
cd /home/bythejune/projects/bithumb-bot-v2
source venv/bin/activate
python3 scripts/optimize.py 2>&1 | tee data/optimization_round1.log
```

Expected: 4개 전략(A/B/C/D) × 그리드 조합 → IS/OOS 결과 출력

- [ ] **Step 2: 결과 분석**

결과에서 확인할 항목:
- 전략별 OOS 최적 파라미터
- OOS PF > 1.0 달성 여부
- OOS 트레이드 수 ≥ 30 여부
- IS vs OOS Sharpe 괴리 (과적합 경고)

- [ ] **Step 3: 결과 저장**

```bash
mkdir -p data/optimization_results
cp data/optimization_round1.log data/optimization_results/
```

---

## Task 10: 1차 결과 분석 + 전략 로직 개선

**Files:** Phase 3 — 1차 결과에 따라 결정

이 Task는 Task 9 결과에 따라 내용이 달라짐. Task 9 완료 후 구체적인 sub-task로 분해하여 진행. Strategy E (DCA)도 필요 시 sl_pct/tp_pct 검토. 다음 판단 기준으로 진행:

- [ ] **Step 1: 전략별 진단**

| 결과 | 판단 | 조치 |
|------|------|------|
| OOS PF > 1.0 | 파라미터로 해결됨 | Phase 4에서 fine-tuning |
| OOS PF 0.5~1.0 | 부분 개선 필요 | 점수 가중치/cutoff 조정 |
| OOS PF < 0.5 | 구조적 문제 | 로직 전면 재검토 또는 비활성화 |
| OOS 트레이드 < 30 | 데이터 부족 | IS/OOS 비율 60:40으로 조정 |

- [ ] **Step 2: 손실 패턴 분석**

적자 전략의 트레이드를 분석:
- 국면별 손실 분포 (어떤 국면에서 손실 집중?)
- 코인별 손실 분포 (특정 코인에서만 실패?)
- 시간대별 패턴 (특정 시간대에 허위 신호?)
- SL/TP hit 비율 (타임아웃 많으면 TP가 너무 높음)

- [ ] **Step 3: 로직 수정 (데이터 기반)**

결과에 따라 한 번에 하나씩 수정:
- 점수 가중치 조정
- cutoff 임계값 변경
- 청산 로직 수정
- 국면 배수 조정
- 전략 비활성화

**주의:** 로직 변경 시 Entry 캐시가 무효화됨 → `scan_entries()` 재실행 필요

- [ ] **Step 4: 국소 백테스트로 개선 효과 확인**

변경한 전략만 빠르게 백테스트하여 개선 확인.

- [ ] **Step 5: 커밋**

변경한 파일만 개별 지정하여 stage (data/ 파일이나 로그 혼입 방지):
```bash
git add strategy/rule_engine.py strategy/indicators.py configs/config.yaml
git commit -m "refactor: strategy logic improvements based on round 1 analysis"
```

---

## Task 11: 2차 최적화 (fine grid + 포트폴리오)

**Files:** 없음 (optimize.py 재실행 또는 확장)

- [ ] **Step 1: fine grid 생성**

1차 최적화 상위 5개 영역 주변으로 세밀한 그리드:
- 각 파라미터 ±1~2 step 범위
- step 간격을 1차의 절반으로

- [ ] **Step 2: 2차 최적화 실행**

```bash
python3 scripts/optimize.py 2>&1 | tee data/optimization_round2.log
```

- [ ] **Step 3: 포트폴리오 시뮬레이션**

개별 전략 최적 파라미터로 동시 실행 시:
- 전략 충돌 (같은 코인 동시 진입) 확인
- 전체 포트폴리오 수익 곡선
- 성공 기준: 포트폴리오 OOS PF > 1.5, MDD < 15%

- [ ] **Step 4: 결과 저장 + 커밋**

```bash
cp data/optimization_round2.log data/optimization_results/
git add data/optimization_results/optimization_round2.log
git commit -m "feat: round 2 optimization results (fine grid + portfolio)"
```

---

## Task 12: Walk-Forward 강건성 검증

**Files:** 없음 (리팩토링된 WF 실행)

- [ ] **Step 1: 최적 파라미터로 Walk-Forward 실행**

```python
# 6~8구간 Walk-Forward
from backtesting.walk_forward import WalkForward

wf = WalkForward(data_days=DATA_DAYS, num_segments=NUM_SEGMENTS)
result = wf.run(trades)
print(f"Verdict: {result.verdict}")
print(f"Pass: {result.pass_count}/{result.total_segments}")
for seg in result.segments:
    print(f"  Segment {seg.segment}: test_pnl={seg.test_pnl:,.0f} {'✓' if seg.profitable else '✗'}")
```

- [ ] **Step 2: 통과 기준 확인**

- 75% 이상 구간에서 OOS PF > 1.0
- 구간별 성과 편차 검토

---

## Task 13: Monte Carlo 강건성 검증

**Files:** 없음 (실행)

- [ ] **Step 1: Monte Carlo 실행**

```python
from backtesting.monte_carlo import MonteCarlo

mc = MonteCarlo(iterations=1000)
result = mc.run(pnl_list, initial_equity=INITIAL_EQUITY)
print(f"Verdict: {result.verdict}")
print(f"P5: {result.pnl_percentile_5:,.0f}")
print(f"P10: {result.pnl_percentile_10:,.0f}")
print(f"P50: {result.pnl_percentile_50:,.0f}")
print(f"Worst MDD: {result.worst_mdd:.2%}")
```

- [ ] **Step 2: 통과 기준 확인**

- P10 > 0 AND P5 > -2% of initial equity
- P95 MDD < 15%

---

## Task 14: Sensitivity 강건성 검증

**Files:** 없음 (실행)

- [ ] **Step 1: replay 기반 Sensitivity 실행**

```python
from backtesting.sensitivity import SensitivityAnalyzer
from backtesting.optimizer import ParameterOptimizer

optimizer = ParameterOptimizer(coins=COINS)
analyzer = SensitivityAnalyzer(variation_pct=0.20, steps=5)
result = analyzer.run_with_optimizer(
    optimizer=optimizer,
    base_params=best_params,
    strategy=strategy_name,
    entries=cached_entries,
)
for p in result.params:
    print(f"  {p.name}: CV={p.cv:.3f} → {p.verdict}")
```

- [ ] **Step 2: 통과 기준 확인**

- CV < 0.3 = 강건
- CV > 0.3인 파라미터 → 보수적 값으로 조정

---

## Task 15: 검증 실패 시 사이클 복귀

Task 12~14 중 하나라도 실패하면:

- [ ] **Step 1: 실패 원인 분석**

어떤 검증이 실패했는지, 어떤 전략/파라미터가 문제인지 파악.

- [ ] **Step 2: Task 10으로 복귀**

로직 재개선 → 2차 최적화 → 검증 반복.

- [ ] **Step 3: 구제불능 전략은 비활성화**

반복해도 검증 통과 못하는 전략은 `enabled: false` 처리.

---

## Task 16: 최종 적용 + 리포트

**Files:**
- Modify: `configs/config.yaml`
- Create: `docs/backtest-report-YYYY-MM-DD.md`

- [ ] **Step 1: 최적 파라미터 적용**

```bash
python3 scripts/optimize.py --apply
```

또는 수동으로 `configs/config.yaml`의 `strategy_params` 업데이트.

- [ ] **Step 2: 결과 리포트 작성**

```markdown
# 백테스트 최적화 결과 리포트

## 요약
| 지표 | Baseline | 최종 |
|------|---------|------|
| PF (포트폴리오) | X.XX | X.XX |
| MDD | XX% | XX% |
| 승률 | XX% | XX% |

## 전략별 상세
...

## Walk-Forward 결과
...

## Monte Carlo 결과
...

## Sensitivity 결과
...

## 권고사항
- PAPER 모드 전환 가능 여부
- 추가 개선 영역
```

- [ ] **Step 3: 커밋**

```bash
git add configs/config.yaml docs/backtest-report-*.md data/optimization_results/
git commit -m "feat: apply optimized parameters and add backtest report"
```

---

## 의존성 그래프

```
Task 1 (config proxy)
  └→ Task 2 (BithumbClient proxy)
       └→ Task 3 (스크립트 proxy)
            └→ Task 4 (연결 테스트)
                 └→ Task 5 (데이터 수집)

Task 6 (WF 리팩토링) ──────┐
Task 7 (MC P10) ───────────┤── 병렬 가능
Task 8 (Sensitivity 재작성) ┘

Task 5 + Task 6~8 완료
  └→ Task 9 (1차 최적화)
       └→ Task 10 (분석 + 로직 개선)
            └→ Task 11 (2차 최적화)
                 └→ Task 12~14 (강건성 검증, 병렬 가능)
                      └→ Task 15 (실패 시 복귀) 또는 Task 16 (최종 적용)
```
