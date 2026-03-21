# BacktestDaemon 자동화 완성 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** BacktestDaemon이 config.yaml 설정을 읽고, 캔들 데이터를 자동 수집하며, 주간 파라미터 최적화를 실행하여 config.yaml에 자동 반영하는 end-to-end 자동화 완성

**Architecture:** BacktestDaemon 생성자에 BacktestConfig + MarketStore + BithumbClient를 주입. config.yaml의 `backtest` 섹션을 BacktestConfig dataclass로 파싱. 데이터 수집/최적화/적용을 daemon 스케줄에 추가. 최적화 결과가 기준 충족 시 config.yaml 백업 후 자동 반영.

**Tech Stack:** Python 3.12, dataclass, asyncio, yaml, SQLite WAL

**Spec:** 이전 탐색에서 확인한 4가지 미구현 항목

---

## 파일 구조

| 파일 | 변경 유형 | 역할 |
|------|----------|------|
| `app/config.py` | Modify | `BacktestConfig` dataclass 추가, `load_config()`에 파싱 추가 |
| `backtesting/daemon.py` | Modify | config 기반 스케줄, 데이터 수집, 자동 최적화, config 자동 반영 |
| `app/main.py` | Modify | BacktestDaemon 생성 시 config + store + client 전달 |
| `tests/test_daemon_config.py` | Create | BacktestConfig 파싱 + daemon 설정 주입 테스트 |
| `tests/test_daemon_auto_optimize.py` | Create | 자동 최적화 + config 반영 테스트 |

---

## Task 1: BacktestConfig dataclass + config.yaml 파싱

**Files:**
- Modify: `app/config.py`
- Create: `tests/test_daemon_config.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/test_daemon_config.py
"""BacktestConfig 파싱 테스트."""
from app.config import load_config


def test_config_has_backtest():
    """config에 backtest 필드가 있다."""
    config = load_config()
    assert hasattr(config, "backtest")


def test_backtest_wf_fields():
    """backtest.wf 필드가 config.yaml 값을 반영한다."""
    config = load_config()
    bt = config.backtest
    assert bt.wf_time == "00:30"
    assert bt.wf_data_days == 30
    assert bt.wf_segments == 4


def test_backtest_mc_fields():
    """backtest.mc 필드가 config.yaml 값을 반영한다."""
    config = load_config()
    bt = config.backtest
    assert bt.mc_time == "01:00"
    assert bt.mc_day == "sunday"
    assert bt.mc_iterations == 1000


def test_backtest_sens_fields():
    """backtest.sensitivity 필드가 config.yaml 값을 반영한다."""
    config = load_config()
    bt = config.backtest
    assert bt.sens_variation_pct == 0.1
    assert bt.sens_steps == 5
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_daemon_config.py -v`
Expected: FAIL — `AttributeError: 'AppConfig' has no attribute 'backtest'`

- [ ] **Step 3: BacktestConfig dataclass 구현**

`app/config.py`에 추가 (PromotionConfig 아래):

```python
@dataclass(frozen=True)
class BacktestConfig:
    """백테스트 데몬 설정."""

    wf_time: str = "00:30"
    wf_data_days: int = 30
    wf_slide_days: int = 7
    wf_segments: int = 4
    wf_overfit_diff_pct: float = 0.5
    mc_time: str = "01:00"
    mc_day: str = "sunday"
    mc_iterations: int = 1000
    mc_danger_mdd_pct: float = 0.2
    sens_time: str = "01:30"
    sens_variation_pct: float = 0.1
    sens_steps: int = 5
    sens_robust_cv: float = 0.1
    sens_warning_cv: float = 0.3
    auto_optimize_enabled: bool = True
    auto_optimize_day: str = "sunday"
    auto_optimize_time: str = "02:00"
    auto_apply_min_pf: float = 1.0
    auto_apply_min_trades: int = 30
    data_collect_time: str = "00:00"
```

`AppConfig`에 필드 추가:
```python
backtest: BacktestConfig = field(default_factory=BacktestConfig)
```

`load_config()`의 `return AppConfig(...)`에 추가:
```python
backtest=_build_backtest(raw.get("backtest", {})),
```

헬퍼 함수:
```python
def _build_backtest(raw: dict) -> BacktestConfig:
    """backtest 섹션을 파싱한다."""
    wf = raw.get("walk_forward", {})
    mc = raw.get("monte_carlo", {})
    sens = raw.get("sensitivity", {})
    opt = raw.get("auto_optimize", {})
    return BacktestConfig(
        wf_time=wf.get("time", "00:30"),
        wf_data_days=wf.get("data_days", 30),
        wf_slide_days=wf.get("slide_days", 7),
        wf_segments=wf.get("segments", 4),
        wf_overfit_diff_pct=wf.get("overfit_diff_pct", 0.5),
        mc_time=mc.get("time", "01:00"),
        mc_day=mc.get("day", "sunday"),
        mc_iterations=mc.get("iterations", 1000),
        mc_danger_mdd_pct=mc.get("danger_mdd_pct", 0.2),
        sens_time=sens.get("time", "01:30"),
        sens_variation_pct=sens.get("variation_pct", 0.1),
        sens_steps=sens.get("steps", 5),
        sens_robust_cv=sens.get("robust_cv", 0.1),
        sens_warning_cv=sens.get("warning_cv", 0.3),
        auto_optimize_enabled=opt.get("enabled", True),
        auto_optimize_day=opt.get("day", "sunday"),
        auto_optimize_time=opt.get("time", "02:00"),
        auto_apply_min_pf=opt.get("min_pf", 1.0),
        auto_apply_min_trades=opt.get("min_trades", 30),
        data_collect_time=raw.get("data_collect_time", "00:00"),
    )
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_daemon_config.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add app/config.py tests/test_daemon_config.py
git commit -m "feat: add BacktestConfig dataclass for daemon settings"
```

---

## Task 2: BacktestDaemon에 config 기반 스케줄 적용

**Files:**
- Modify: `backtesting/daemon.py`
- Modify: `app/main.py`

- [ ] **Step 1: 테스트 추가**

```python
# tests/test_daemon_config.py에 추가
from backtesting.daemon import BacktestDaemon
from app.config import BacktestConfig
from unittest.mock import MagicMock


def test_daemon_uses_config_wf_segments():
    """데몬이 config의 wf_segments를 사용한다."""
    bt_config = BacktestConfig(wf_segments=6, wf_data_days=180)
    journal = MagicMock()
    daemon = BacktestDaemon(journal=journal, config=bt_config)
    assert daemon._walk_forward._num_segments == 6


def test_daemon_uses_config_mc_iterations():
    """데몬이 config의 mc_iterations를 사용한다."""
    bt_config = BacktestConfig(mc_iterations=500)
    journal = MagicMock()
    daemon = BacktestDaemon(journal=journal, config=bt_config)
    assert daemon._monte_carlo._iterations == 500


def test_daemon_uses_config_sens_steps():
    """데몬이 config의 sens_steps를 사용한다."""
    bt_config = BacktestConfig(sens_steps=3, sens_variation_pct=0.2)
    journal = MagicMock()
    daemon = BacktestDaemon(journal=journal, config=bt_config)
    assert daemon._sensitivity._steps == 3
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_daemon_config.py::test_daemon_uses_config_wf_segments -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'config'`

- [ ] **Step 3: BacktestDaemon 생성자에 config 주입**

`backtesting/daemon.py` 수정:

```python
from app.config import BacktestConfig  # import 추가

class BacktestDaemon:
    def __init__(
        self,
        journal: Journal,
        notifier: TelegramNotifier | None = None,
        config: BacktestConfig | None = None,
    ) -> None:
        self._journal = journal
        self._notifier = notifier
        self._config = config or BacktestConfig()
        c = self._config

        self._walk_forward = WalkForward(
            data_days=c.wf_data_days,
            slide_days=c.wf_slide_days,
            num_segments=c.wf_segments,
            overfit_threshold=c.wf_overfit_diff_pct,
        )
        self._monte_carlo = MonteCarlo(
            iterations=c.mc_iterations,
            danger_mdd_pct=c.mc_danger_mdd_pct,
        )
        self._sensitivity = SensitivityAnalyzer(
            variation_pct=c.sens_variation_pct,
            steps=c.sens_steps,
        )
        # ... 나머지 초기화 (기존과 동일)
```

스케줄 루프에서 하드코딩 → config 값 사용:

```python
async def run(self) -> None:
    self._running = True
    logger.info("BacktestDaemon 시작")
    wf_hour, wf_min = self._parse_time(self._config.wf_time)
    mc_hour, mc_min = self._parse_time(self._config.mc_time)
    sens_hour, sens_min = self._parse_time(self._config.sens_time)
    mc_weekday = self._parse_weekday(self._config.mc_day)

    while self._running:
        try:
            now = datetime.now(KST)
            date_key = now.strftime("%Y-%m-%d")
            week_key = f"{date_key}-w"

            if now.hour == wf_hour and now.minute >= wf_min and self._last_wf != date_key:
                self._last_wf = date_key
                await self._run_walk_forward()

            if now.weekday() == mc_weekday:
                if now.hour == mc_hour and now.minute >= mc_min and self._last_mc != week_key:
                    self._last_mc = week_key
                    await self._run_monte_carlo()

                if now.hour == sens_hour and now.minute >= sens_min and self._last_sens != week_key:
                    self._last_sens = week_key
                    await self._run_sensitivity()
                    await self._send_weekly_report()

        except Exception:
            logger.exception("BacktestDaemon 오류")
        await asyncio.sleep(60)

@staticmethod
def _parse_time(time_str: str) -> tuple[int, int]:
    """'HH:MM' → (hour, minute)."""
    parts = time_str.split(":")
    return int(parts[0]), int(parts[1])

@staticmethod
def _parse_weekday(day_str: str) -> int:
    """요일 문자열 → weekday (0=월, 6=일)."""
    mapping = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,
    }
    return mapping.get(day_str.lower(), 6)
```

- [ ] **Step 4: main.py에서 config 전달**

`app/main.py` line 173-175 수정:

```python
self._backtest_daemon = BacktestDaemon(
    journal=self._journal,
    notifier=self._notifier,
    config=config.backtest,
)
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `pytest tests/test_daemon_config.py -v`
Expected: PASS

- [ ] **Step 6: 기존 테스트 통과 확인**

Run: `pytest tests/ --ignore=tests/test_bithumb_api.py -x -q`
Expected: 전체 PASS

- [ ] **Step 7: 커밋**

```bash
git add backtesting/daemon.py app/main.py tests/test_daemon_config.py
git commit -m "refactor: BacktestDaemon reads schedule from config instead of hardcoded"
```

---

## Task 3: 데이터 자동 수집 기능 추가

**Files:**
- Modify: `backtesting/daemon.py`
- Modify: `app/main.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/test_daemon_config.py에 추가
import asyncio


def test_daemon_accepts_store_and_client():
    """데몬이 MarketStore와 BithumbClient를 받는다."""
    journal = MagicMock()
    store = MagicMock()
    client = MagicMock()
    daemon = BacktestDaemon(
        journal=journal, store=store, client=client,
        coins=["BTC", "ETH"],
    )
    assert daemon._store is store
    assert daemon._client is client
    assert daemon._coins == ["BTC", "ETH"]


def test_daemon_without_store_skips_collect():
    """store 없으면 데이터 수집을 건너뛴다."""
    journal = MagicMock()
    daemon = BacktestDaemon(journal=journal)
    # _collect_candles가 존재하고, store 없으면 early return
    result = asyncio.get_event_loop().run_until_complete(
        daemon._collect_candles()
    )
    assert result == 0
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_daemon_config.py::test_daemon_accepts_store_and_client -v`
Expected: FAIL

- [ ] **Step 3: 데이터 수집 구현**

`backtesting/daemon.py`에 추가:

생성자에 store/client/coins 파라미터 추가:
```python
def __init__(
    self,
    journal: Journal,
    notifier: TelegramNotifier | None = None,
    config: BacktestConfig | None = None,
    store: "MarketStore | None" = None,
    client: "BithumbClient | None" = None,
    coins: list[str] | None = None,
) -> None:
    # ... 기존 초기화 ...
    self._store = store
    self._client = client
    self._coins = coins or []
    self._last_collect: str = ""
```

`_collect_candles` 메서드:
```python
async def _collect_candles(self) -> int:
    """최신 캔들 데이터를 수집한다. 수집한 봉 수를 반환."""
    if not self._store or not self._client:
        return 0

    from app.data_types import Candle

    total = 0
    for coin in self._coins:
        for interval in ["15m", "1h"]:
            try:
                raw = await self._client.get_candlestick(coin, interval)
                candles = []
                for item in raw:
                    try:
                        candles.append(Candle(
                            timestamp=int(item[0]),
                            open=float(item[1]),
                            close=float(item[2]),
                            high=float(item[3]),
                            low=float(item[4]),
                            volume=float(item[5]),
                        ))
                    except (IndexError, ValueError, TypeError):
                        continue
                stored = self._store.store_candles(coin, interval, candles)
                total += stored
            except Exception:
                logger.exception("캔들 수집 실패: %s %s", coin, interval)
            await asyncio.sleep(0.15)

    logger.info("캔들 데이터 수집 완료: %d건", total)
    return total
```

`run()` 루프에 데이터 수집 스케줄 추가 (WF 전에):
```python
collect_hour, collect_min = self._parse_time(self._config.data_collect_time)

# 데이터 수집: 매일 00:00
if (now.hour == collect_hour and now.minute >= collect_min
        and self._last_collect != date_key):
    self._last_collect = date_key
    await self._collect_candles()
```

- [ ] **Step 4: main.py에서 store/client/coins 전달**

```python
self._backtest_daemon = BacktestDaemon(
    journal=self._journal,
    notifier=self._notifier,
    config=config.backtest,
    store=self._market_store,
    client=self._client,
    coins=config.coins,
)
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `pytest tests/test_daemon_config.py -v`
Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add backtesting/daemon.py app/main.py tests/test_daemon_config.py
git commit -m "feat: add automatic candle data collection to BacktestDaemon"
```

---

## Task 4: 자동 파라미터 최적화 + config 반영

**Files:**
- Modify: `backtesting/daemon.py`
- Modify: `configs/config.yaml`
- Create: `tests/test_daemon_auto_optimize.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/test_daemon_auto_optimize.py
"""자동 최적화 + config 반영 테스트."""
import asyncio
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import yaml

from app.config import BacktestConfig
from backtesting.daemon import BacktestDaemon


def test_auto_optimize_disabled():
    """auto_optimize_enabled=False면 최적화를 건너뛴다."""
    config = BacktestConfig(auto_optimize_enabled=False)
    journal = MagicMock()
    daemon = BacktestDaemon(journal=journal, config=config)
    result = asyncio.get_event_loop().run_until_complete(
        daemon._run_auto_optimize()
    )
    assert result is None


def test_auto_optimize_no_store():
    """store 없으면 최적화를 건너뛴다."""
    journal = MagicMock()
    daemon = BacktestDaemon(journal=journal)
    result = asyncio.get_event_loop().run_until_complete(
        daemon._run_auto_optimize()
    )
    assert result is None


def test_apply_params_creates_backup():
    """config 적용 시 백업 파일이 생성된다."""
    config = BacktestConfig(auto_apply_min_pf=1.0, auto_apply_min_trades=5)
    journal = MagicMock()
    daemon = BacktestDaemon(journal=journal, config=config)

    # 임시 config.yaml 생성
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False,
    ) as f:
        yaml.dump({"strategy_params": {"trend_follow": {"sl_mult": 1.0}}}, f)
        tmp_path = Path(f.name)

    try:
        # 적용
        daemon._apply_optimized_params(
            strategy="trend_follow",
            params={"sl_mult": 3.0, "tp_rr": 2.0},
            config_path=tmp_path,
        )
        # 백업 확인
        backups = list(tmp_path.parent.glob("*.yaml.bak.*"))
        assert len(backups) >= 1

        # 값 반영 확인
        with open(tmp_path) as f:
            updated = yaml.safe_load(f)
        assert updated["strategy_params"]["trend_follow"]["sl_mult"] == 3.0
    finally:
        tmp_path.unlink(missing_ok=True)
        for b in tmp_path.parent.glob("*.yaml.bak.*"):
            b.unlink(missing_ok=True)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_daemon_auto_optimize.py -v`
Expected: FAIL — `_run_auto_optimize` 없음

- [ ] **Step 3: 자동 최적화 구현**

`backtesting/daemon.py`에 추가:

생성자에 `_last_optimize: str = ""` 추가.

```python
async def _run_auto_optimize(self) -> dict | None:
    """자동 파라미터 최적화를 실행한다."""
    if not self._config.auto_optimize_enabled:
        return None
    if not self._store or not self._client:
        return None

    logger.info("자동 파라미터 최적화 시작")

    from app.config import load_config
    from backtesting.optimizer import ParameterOptimizer
    from backtesting.param_grid import build_grids

    config = load_config()
    coins = self._coins

    # 데이터 로딩
    candles_15m: dict[str, list] = {}
    candles_1h: dict[str, list] = {}
    for coin in coins:
        candles_15m[coin] = self._store.get_candles(coin, "15m", limit=5000)
        candles_1h[coin] = self._store.get_candles(coin, "1h", limit=5000)

    if not any(len(v) > 200 for v in candles_15m.values()):
        logger.warning("자동 최적화: 데이터 부족, 건너뜀")
        return None

    optimizer = ParameterOptimizer(coins, config)
    grids = build_grids()
    results: dict[str, dict] = {}

    for strategy, grid in grids.items():
        combos = grid.combinations()
        oos_list = optimizer.optimize(
            strategy, combos, candles_15m, candles_1h,
        )
        if not oos_list:
            continue
        best = max(oos_list, key=lambda r: r.profit_factor)
        results[strategy] = {
            "params": best.params,
            "pf": best.profit_factor,
            "trades": best.trades,
            "wr": best.win_rate,
        }
        logger.info(
            "최적화 %s: PF=%.2f WR=%.0f%% (%d건)",
            strategy, best.profit_factor, best.win_rate * 100, best.trades,
        )

    # 기준 충족 시 자동 적용
    from pathlib import Path
    config_path = Path("configs/config.yaml")
    applied = []
    for strategy, r in results.items():
        if (r["pf"] >= self._config.auto_apply_min_pf
                and r["trades"] >= self._config.auto_apply_min_trades):
            self._apply_optimized_params(strategy, r["params"], config_path)
            applied.append(f"{strategy}: PF={r['pf']:.2f}")

    # 텔레그램 알림
    if self._notifier:
        lines = ["<b>자동 최적화 완료</b>"]
        for s, r in results.items():
            lines.append(f"  {s}: PF={r['pf']:.2f} ({r['trades']}건)")
        if applied:
            lines.append(f"\n<b>자동 적용:</b> {', '.join(applied)}")
        else:
            lines.append("\n기준 미달 — 적용 없음")
        await self._notifier.send("\n".join(lines))

    self.optimize_result = results
    return results

def _apply_optimized_params(
    self,
    strategy: str,
    params: dict[str, float],
    config_path: "Path",
) -> None:
    """최적 파라미터를 config.yaml에 백업 후 적용한다."""
    import shutil
    from datetime import datetime

    # 백업
    backup_path = config_path.with_suffix(
        f".yaml.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    shutil.copy2(config_path, backup_path)
    logger.info("config 백업: %s", backup_path)

    # 업데이트
    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    sp = raw.setdefault("strategy_params", {})
    if strategy not in sp:
        sp[strategy] = {}
    for k, v in params.items():
        if k == "cutoff_full":
            continue
        sp[strategy][k] = round(v, 4)

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(raw, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    logger.info("config 업데이트: %s → %s", strategy, params)
```

`import yaml` 추가 (파일 상단).

`run()` 루프에 자동 최적화 스케줄 추가:
```python
if self._config.auto_optimize_enabled:
    opt_hour, opt_min = self._parse_time(self._config.auto_optimize_time)
    opt_weekday = self._parse_weekday(self._config.auto_optimize_day)
    if (now.weekday() == opt_weekday
            and now.hour == opt_hour
            and now.minute >= opt_min
            and self._last_optimize != week_key):
        self._last_optimize = week_key
        await self._run_auto_optimize()
```

- [ ] **Step 4: config.yaml에 auto_optimize 섹션 추가**

`configs/config.yaml`의 `backtest:` 아래에 추가:
```yaml
  auto_optimize:
    enabled: true
    day: sunday
    time: "02:00"
    min_pf: 1.0
    min_trades: 30
  data_collect_time: "00:00"
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `pytest tests/test_daemon_auto_optimize.py -v`
Expected: PASS

- [ ] **Step 6: 전체 테스트 통과 확인**

Run: `pytest tests/ --ignore=tests/test_bithumb_api.py -x -q`
Expected: 전체 PASS

- [ ] **Step 7: 커밋**

```bash
git add backtesting/daemon.py configs/config.yaml tests/test_daemon_auto_optimize.py
git commit -m "feat: add auto parameter optimization with config auto-apply to BacktestDaemon"
```

---

## 의존성 그래프

```
Task 1 (BacktestConfig dataclass)
  └→ Task 2 (daemon config 주입)
       └→ Task 3 (데이터 자동 수집)
            └→ Task 4 (자동 최적화 + config 반영)
```

모든 Task는 순차 의존.
