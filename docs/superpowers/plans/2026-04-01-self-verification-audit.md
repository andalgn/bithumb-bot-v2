# 자가검증 + 정기 감사 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 매도 주문 후 거래소 잔고를 즉시 검증하고, 일 2회 Claude Code 감사로 구조적 문제를 사전 탐지한다.

**Architecture:** (1) `_verify_sell_execution()` 메서드로 매도 직후 거래소 잔고 교차검증, 불일치 시 포지션 복원. (2) HealthMonitor에 자금 활용률/잔고 정합성 체크 추가. (3) `scripts/audit_bot.py`가 데이터를 수집하고 `claude -p`에 파이프하여 종합 감사, 결과를 Discord 전송.

**Tech Stack:** Python 3.12, asyncio, aiohttp, Bithumb REST API, claude CLI, cron

---

## 파일 구조

| 파일 | 역할 | 변경 유형 |
|------|------|-----------|
| `app/main.py` | `_verify_sell_execution()` 추가, `_close_position`/`_partial_close_position`에서 호출 | 수정 |
| `app/health_monitor.py` | Check 10 (자금 활용률), Check 11 (잔고↔포지션 교차검증) | 수정 |
| `scripts/audit_bot.py` | 봇 데이터 수집 + Claude 프롬프트 생성 | 신규 |
| `configs/config.yaml` | 활용률 임계값 설정 추가 | 수정 |
| `tests/test_verify_sell.py` | `_verify_sell_execution` 단위 테스트 | 신규 |
| `tests/test_health_checks.py` | Check 10/11 단위 테스트 | 수정 |

---

### Task 1: _verify_sell_execution 메서드 구현

**Files:**
- Modify: `app/main.py`
- Create: `tests/test_verify_sell.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/test_verify_sell.py
"""매도 후 거래소 잔고 재검증 테스트."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest


@dataclass
class FakePosition:
    symbol: str
    entry_price: float
    qty: float
    size_krw: float
    pool: str = "active"
    strategy: str = "mean_reversion"
    tier: str = "1"
    regime: str = "RANGE"
    promoted: bool = False
    entry_score: float = 50.0
    signal_price: float = 0.0
    entry_time: int = 0
    stop_loss: float = 0.0
    take_profit: float = 0.0


def _make_bot_with_balance(balance_response: dict):
    """거래소 잔고 응답을 시뮬레이션하는 봇 목업을 생성한다."""
    from app.main import TradingBot

    bot = object.__new__(TradingBot)
    bot._client = AsyncMock()
    bot._client.get_balance = AsyncMock(return_value=balance_response)
    bot._notifier = AsyncMock()
    bot._notifier.send = AsyncMock()
    bot._positions = {}
    bot._dust_coins = {}
    bot._pool_manager = MagicMock()
    bot._run_mode = MagicMock()
    bot._run_mode.value = "LIVE"
    return bot


@pytest.mark.asyncio
async def test_verify_sell_balance_matches():
    """매도 후 거래소 잔고가 기대와 일치하면 True를 반환한다."""
    bot = _make_bot_with_balance({"available_eth": "0.0000", "locked_eth": "0"})
    result = await bot._verify_sell_execution(
        symbol="ETH",
        sold_qty=0.0025,
        pre_sell_qty=0.0025,
        position_backup=None,
    )
    assert result is True


@pytest.mark.asyncio
async def test_verify_sell_coins_remain():
    """매도했는데 거래소에 코인이 남아있으면 False + 포지션 복원."""
    pos = FakePosition(symbol="ETH", entry_price=3113000, qty=0.0025, size_krw=7782)
    bot = _make_bot_with_balance({"available_eth": "0.0025", "locked_eth": "0"})
    bot._positions = {}

    result = await bot._verify_sell_execution(
        symbol="ETH",
        sold_qty=0.0025,
        pre_sell_qty=0.0025,
        position_backup=pos,
    )
    assert result is False
    assert "ETH" in bot._positions  # 포지션 복원됨
    bot._notifier.send.assert_called()  # Discord 경고 전송됨


@pytest.mark.asyncio
async def test_verify_sell_partial_remain():
    """부분 매도 후 잔량이 기대보다 많으면 False."""
    pos = FakePosition(symbol="RENDER", entry_price=2564, qty=3.674, size_krw=9420)
    bot = _make_bot_with_balance({"available_render": "3.674", "locked_render": "0"})

    result = await bot._verify_sell_execution(
        symbol="RENDER",
        sold_qty=1.83,
        pre_sell_qty=3.674,
        position_backup=pos,
    )
    assert result is False


@pytest.mark.asyncio
async def test_verify_sell_api_error_returns_true():
    """API 오류 시 검증을 건너뛰고 True를 반환한다 (메인 루프 보호)."""
    bot = _make_bot_with_balance({})
    bot._client.get_balance = AsyncMock(side_effect=Exception("timeout"))

    result = await bot._verify_sell_execution(
        symbol="ETH",
        sold_qty=0.0025,
        pre_sell_qty=0.0025,
        position_backup=None,
    )
    assert result is True  # 검증 실패해도 메인 루프 차단 안 함
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_verify_sell.py -v`
Expected: FAIL — `_verify_sell_execution` 메서드 없음

- [ ] **Step 3: _verify_sell_execution 구현**

`app/main.py`에 `_cleanup_dust` 메서드 바로 앞에 추가:

```python
async def _verify_sell_execution(
    self,
    symbol: str,
    sold_qty: float,
    pre_sell_qty: float,
    position_backup: "Position | None",
) -> bool:
    """매도 후 거래소 잔고를 검증한다.

    Args:
        symbol: 코인 심볼.
        sold_qty: 매도한 수량.
        pre_sell_qty: 매도 전 보유 수량.
        position_backup: 불일치 시 복원할 포지션 (전량 청산 시).

    Returns:
        True면 검증 통과, False면 불일치 감지.
    """
    if self._run_mode != RunMode.LIVE:
        return True

    try:
        balance = await self._client.get_balance()
    except Exception:
        logger.warning("매도 검증 실패 (API 오류) — 검증 스킵: %s", symbol)
        return True

    key = symbol.lower()
    actual_available = float(balance.get(f"available_{key}", 0))
    actual_locked = float(balance.get(f"locked_{key}", 0))
    actual_total = actual_available + actual_locked

    expected_remaining = pre_sell_qty - sold_qty
    if expected_remaining < 0:
        expected_remaining = 0

    # 허용 오차 0.1%
    tolerance = pre_sell_qty * 0.001
    diff = actual_total - expected_remaining

    if abs(diff) <= tolerance:
        return True

    if diff > tolerance:
        # 거래소에 코인이 더 많음 → 매도 안 됨
        logger.error(
            "매도 검증 실패: %s 거래소=%.6f 기대=%.6f (차이=+%.6f) — 매도 미체결",
            symbol, actual_total, expected_remaining, diff,
        )
        # 포지션 복원
        if position_backup is not None and symbol not in self._positions:
            self._positions[symbol] = position_backup
            self._pool_manager.reclaim(position_backup.pool, position_backup.size_krw)
            logger.info("포지션 복원: %s %.6f개", symbol, position_backup.qty)

        await self._notifier.send(
            f"⚠️ **매도 검증 실패: {symbol}**\n"
            f"거래소 잔고: {actual_total:.6f}\n"
            f"기대 잔량: {expected_remaining:.6f}\n"
            f"→ 매도가 실제로 체결되지 않음. 포지션 복원됨.",
            channel="system",
        )
        return False

    # diff < -tolerance: 거래소에 코인이 더 적음 (더 팔림)
    logger.warning(
        "매도 검증 이상: %s 거래소=%.6f 기대=%.6f (차이=%.6f)",
        symbol, actual_total, expected_remaining, diff,
    )
    await self._notifier.send(
        f"⚠️ **매도 검증 이상: {symbol}**\n"
        f"거래소 잔고: {actual_total:.6f}\n"
        f"기대 잔량: {expected_remaining:.6f}\n"
        f"→ 예상보다 더 많이 매도됨. 확인 필요.",
        channel="system",
    )
    return False
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_verify_sell.py -v`
Expected: 4 passed

- [ ] **Step 5: 커밋**

```bash
git add app/main.py tests/test_verify_sell.py
git commit -m "feat: add _verify_sell_execution for post-sell balance verification"
```

---

### Task 2: _close_position에 검증 통합

**Files:**
- Modify: `app/main.py` — `_close_position` 메서드

- [ ] **Step 1: _close_position 수정**

`_close_position`에서 주문 성공 후, `self._positions.pop(symbol, None)` 직전에 검증을 삽입한다.

변경 전 (현재 코드):
```python
            if ticket.filled_price > 0:
                exit_price = ticket.filled_price

        self._positions.pop(symbol, None)
```

변경 후:
```python
            if ticket.filled_price > 0:
                exit_price = ticket.filled_price

            # 매도 후 거래소 잔고 재검증
            pos_backup_for_verify = Position(
                symbol=pos.symbol, entry_price=pos.entry_price,
                entry_time=pos.entry_time, size_krw=pos.size_krw,
                qty=pos.qty, stop_loss=pos.stop_loss, take_profit=pos.take_profit,
                strategy=pos.strategy, pool=pos.pool, tier=pos.tier,
                regime=pos.regime, promoted=pos.promoted,
                entry_score=pos.entry_score, signal_price=pos.signal_price,
            )
            verified = await self._verify_sell_execution(
                symbol=symbol,
                sold_qty=pos.qty,
                pre_sell_qty=pos.qty,
                position_backup=pos_backup_for_verify,
            )
            if not verified:
                return

        self._positions.pop(symbol, None)
```

- [ ] **Step 2: 재시작 후 로그 확인**

Run: `sudo systemctl restart bithumb-bot && sleep 10 && sudo journalctl -u bithumb-bot -n 5 --no-pager`
Expected: 정상 시작, 에러 없음

- [ ] **Step 3: 커밋**

```bash
git add app/main.py
git commit -m "feat: integrate sell verification into _close_position"
```

---

### Task 3: _partial_close_position에 검증 통합

**Files:**
- Modify: `app/main.py` — `_partial_close_position` 메서드

- [ ] **Step 1: _partial_close_position 수정**

부분 매도 성공 후(PnL 계산 직전), 검증을 삽입한다.

변경 전:
```python
        # PnL 계산 (부분) — 진입·청산 양쪽 수수료 차감
        gross = (exit_price - pos.entry_price) * exit_qty
```

변경 후:
```python
        # 부분 매도 후 거래소 잔고 재검증
        verified = await self._verify_sell_execution(
            symbol=symbol,
            sold_qty=exit_qty,
            pre_sell_qty=pos.qty + exit_qty,  # 차감 전 원래 수량
            position_backup=None,  # 부분 청산이므로 전체 복원 불필요
        )
        if not verified:
            return

        # PnL 계산 (부분) — 진입·청산 양쪽 수수료 차감
        gross = (exit_price - pos.entry_price) * exit_qty
```

주의: `_partial_close_position`에서는 아직 `pos.qty`를 차감하지 않은 상태이므로, `pre_sell_qty = pos.qty`가 맞다. 그러나 이 시점에서 exit_qty는 이미 계산되었고 pos.qty는 아직 원래값이므로 `pre_sell_qty=pos.qty`를 사용한다.

- [ ] **Step 2: 문법 검증**

Run: `python3 -c "import py_compile; py_compile.compile('app/main.py', doraise=True)"`
Expected: 에러 없음

- [ ] **Step 3: 커밋**

```bash
git add app/main.py
git commit -m "feat: integrate sell verification into _partial_close_position"
```

---

### Task 4: PoolManager.reclaim 메서드 확인/추가

**Files:**
- Modify: `strategy/pool_manager.py`

`_verify_sell_execution`에서 포지션 복원 시 Pool에서 반환된 자금을 다시 회수해야 한다. `PoolManager.reclaim(pool, amount)` 메서드가 필요하다.

- [ ] **Step 1: reclaim 존재 여부 확인**

Run: `grep -n "def reclaim" strategy/pool_manager.py`

- 있으면 Step 3으로 건너뜀
- 없으면 Step 2 진행

- [ ] **Step 2: reclaim 구현**

`strategy/pool_manager.py`의 `release` 메서드 아래에 추가:

```python
def reclaim(self, pool: Pool, amount: float) -> None:
    """반환된 자금을 다시 할당 상태로 되돌린다 (포지션 복원 시 사용).

    Args:
        pool: 풀 종류.
        amount: 회수할 금액(KRW).
    """
    if pool == Pool.ACTIVE:
        self._active_available -= amount
    elif pool == Pool.CORE:
        self._core_available -= amount
    elif pool == Pool.RESERVE:
        self._reserve_available -= amount
```

- [ ] **Step 3: 커밋**

```bash
git add strategy/pool_manager.py
git commit -m "feat: add PoolManager.reclaim for position restoration"
```

---

### Task 5: HealthMonitor Check 10 — 자금 활용률

**Files:**
- Modify: `app/health_monitor.py`
- Modify: `configs/config.yaml`

- [ ] **Step 1: config.yaml에 설정 추가**

`health_monitor` 섹션 끝에 추가:

```yaml
  utilization_warn_pct: 10       # 활용률 이 이하면 WARNING
  utilization_warn_duration_h: 6  # 이 시간 지속 시 경고
```

- [ ] **Step 2: SCORE_WEIGHTS 확장**

`app/health_monitor.py`의 `SCORE_WEIGHTS`에 추가 (기존 가중치에서 pipeline을 5로 줄여 합계 유지):

```python
SCORE_WEIGHTS: dict[str, int] = {
    "heartbeat": 20,
    "event_loop": 10,
    "api": 20,
    "data_freshness": 15,
    "reconciliation": 10,    # 15 → 10
    "system_resources": 5,
    "trading_metrics": 10,
    "discord": 5,
    "pipeline": 5,           # 10 → 5
    "utilization": 5,        # NEW
    "balance_check": 5,      # NEW (Task 6)
}
```

- [ ] **Step 3: _check_utilization 구현**

```python
def _check_utilization(self) -> CheckResult:
    """자금 활용률을 점검한다."""
    if not self._get_positions:
        return CheckResult(name="utilization", status="ok", message="활용률 점검 미설정")

    try:
        positions = self._get_positions()
        total_position_krw = sum(
            (p.get("size_krw", 0) if isinstance(p, dict) else getattr(p, "size_krw", 0))
            for p in positions.values()
        )
        total_equity = getattr(self, "_total_equity", 1_000_000)
        util_pct = (total_position_krw / total_equity * 100) if total_equity > 0 else 0

        warn_pct = getattr(self._config, "utilization_warn_pct", 10)
        warn_hours = getattr(self._config, "utilization_warn_duration_h", 6)

        if util_pct < warn_pct:
            if not hasattr(self, "_low_util_since"):
                self._low_util_since = time.time()
            elapsed_h = (time.time() - self._low_util_since) / 3600
            if elapsed_h >= warn_hours:
                return CheckResult(
                    name="utilization", status="warn",
                    message=f"활용률 {util_pct:.1f}% < {warn_pct}% ({elapsed_h:.1f}시간 지속)",
                )
        else:
            self._low_util_since = 0

        return CheckResult(
            name="utilization", status="ok",
            message=f"활용률 {util_pct:.1f}%",
        )
    except Exception as e:
        return CheckResult(name="utilization", status="ok", message=f"활용률 점검 실패: {e}")
```

- [ ] **Step 4: _run_all_checks에 등록**

```python
async def _run_all_checks(self) -> list[CheckResult]:
    return [
        # ... 기존 9개 ...
        self._check_pipeline_health(),
        self._check_utilization(),          # NEW
    ]
```

- [ ] **Step 5: 커밋**

```bash
git add app/health_monitor.py configs/config.yaml
git commit -m "feat: add HealthMonitor Check 10 — capital utilization alert"
```

---

### Task 6: HealthMonitor Check 11 — 거래소↔봇 잔고 정합성

**Files:**
- Modify: `app/health_monitor.py`

- [ ] **Step 1: _check_balance_integrity 구현**

기존 `_check_reconciliation`은 주문 상태 동기화용이다. 새 체크는 **잔고 vs 포지션** 비교에 집중한다.

```python
async def _check_balance_integrity(self) -> CheckResult:
    """거래소 잔고와 봇 포지션의 정합성을 검증한다."""
    if not self._get_positions or not self._get_exchange_balances:
        return CheckResult(name="balance_check", status="ok", message="잔고 검증 미설정")

    now = time.time()
    interval = getattr(self._config, "reconciliation_interval_sec", 3600)
    if not hasattr(self, "_last_balance_check"):
        self._last_balance_check = 0
    if now - self._last_balance_check < interval:
        return CheckResult(name="balance_check", status="ok", message="주기 미도래")
    self._last_balance_check = now

    try:
        positions = self._get_positions()
        balances = await self._get_exchange_balances()
        issues = []

        # 1) 봇 포지션에 있는데 거래소에 없는 경우
        for symbol, pos in positions.items():
            local_qty = pos.get("qty", 0) if isinstance(pos, dict) else getattr(pos, "qty", 0)
            key = symbol.lower()
            exchange_qty = float(balances.get(f"available_{key}", 0)) + float(balances.get(f"locked_{key}", 0))
            if local_qty > 0 and exchange_qty < local_qty * 0.5:
                issues.append(f"{symbol}: 봇={local_qty:.4f} 거래소={exchange_qty:.4f} (부족)")

        # 2) 거래소에 있는데 봇 포지션에 없는 경우 (더스트 후보)
        position_symbols = {s.lower() for s in positions}
        dust_candidates = []
        for k, v in balances.items():
            if not k.startswith("available_"):
                continue
            currency = k.replace("available_", "").upper()
            if currency in ("KRW", "P"):
                continue
            qty = float(v)
            if qty > 0 and currency.lower() not in position_symbols:
                avg_price_key = f"avg_buy_price_{currency.lower()}"
                avg_price = float(balances.get(avg_price_key, 0))
                if avg_price * qty > 100:  # 100원 이상만
                    dust_candidates.append(f"{currency}: {qty} (≈{avg_price * qty:.0f}원)")

        if issues:
            msg = "잔고 불일치: " + "; ".join(issues)
            if dust_candidates:
                msg += " | 미등록 잔고: " + ", ".join(dust_candidates[:5])
            return CheckResult(name="balance_check", status="critical", message=msg)

        if dust_candidates:
            return CheckResult(
                name="balance_check", status="warn",
                message=f"미등록 거래소 잔고: {', '.join(dust_candidates[:5])}",
            )

        return CheckResult(
            name="balance_check", status="ok",
            message=f"잔고 정합성 정상 ({len(positions)}종)",
        )
    except Exception as e:
        return CheckResult(name="balance_check", status="warn", message=f"잔고 검증 실패: {e}")
```

- [ ] **Step 2: _run_all_checks에 등록**

```python
async def _run_all_checks(self) -> list[CheckResult]:
    return [
        # ... 기존 + Check 10 ...
        self._check_utilization(),
        await self._check_balance_integrity(),  # NEW
    ]
```

- [ ] **Step 3: 커밋**

```bash
git add app/health_monitor.py
git commit -m "feat: add HealthMonitor Check 11 — exchange balance integrity"
```

---

### Task 7: scripts/audit_bot.py 구현

**Files:**
- Create: `scripts/audit_bot.py`

- [ ] **Step 1: 스크립트 작성**

```python
#!/usr/bin/env python3
"""봇 정기 감사 — 데이터 수집 + Claude 프롬프트 생성.

사용법:
    python scripts/audit_bot.py | claude -p --max-turns 3
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

KST = timezone(timedelta(hours=9))


def _collect_logs() -> str:
    """최근 12시간 봇 로그에서 에러/경고를 수집한다."""
    try:
        result = subprocess.run(
            ["journalctl", "-u", "bithumb-bot", "--since", "12 hours ago", "--no-pager"],
            capture_output=True, text=True, timeout=30,
        )
        lines = result.stdout.splitlines()
        # ERROR, WARNING, CRITICAL만 필터
        filtered = [
            line for line in lines
            if any(kw in line for kw in ["ERROR", "WARNING", "CRITICAL", "Exception", "Traceback"])
        ]
        # 최대 200줄
        return "\n".join(filtered[-200:]) if filtered else "(에러/경고 없음)"
    except Exception as e:
        return f"(로그 수집 실패: {e})"


def _collect_bot_state() -> dict:
    """봇 상태 파일을 읽는다."""
    state_path = PROJECT_ROOT / "data" / "app_state.json"
    if not state_path.exists():
        return {"error": "app_state.json not found"}
    with state_path.open() as f:
        state = json.load(f)

    # 필요한 부분만 추출
    return {
        "positions": state.get("positions", {}),
        "dust_coins": state.get("dust_coins", {}),
        "pool_manager": state.get("pool_manager", {}),
        "cycle_count": state.get("cycle_count", 0),
        "last_cycle_at": state.get("last_cycle_at", 0),
        "pilot_remaining": state.get("pilot_remaining", 0),
        "pilot_size_mult": state.get("pilot_size_mult", 1.0),
    }


async def _collect_exchange_balance() -> dict:
    """거래소 잔고를 조회한다."""
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
    from market.bithumb_api import BithumbClient

    client = BithumbClient(
        api_key=os.environ["BITHUMB_API_KEY"],
        api_secret=os.environ["BITHUMB_API_SECRET"],
        proxy=os.environ.get("PROXY", "http://127.0.0.1:1081"),
    )
    try:
        balance = await client.get_balance()
        # 0 초과 코인만 필터
        significant = {}
        for k, v in balance.items():
            if k.startswith("available_") or k.startswith("locked_"):
                qty = float(v)
                if qty > 0:
                    significant[k] = v
            elif k.startswith("avg_buy_price_"):
                currency = k.replace("avg_buy_price_", "")
                avail = float(balance.get(f"available_{currency}", 0))
                locked = float(balance.get(f"locked_{currency}", 0))
                if avail + locked > 0:
                    significant[k] = v
        return significant
    except Exception as e:
        return {"error": str(e)}
    finally:
        await client.close()


def _collect_trade_performance() -> dict:
    """최근 12시간 거래 성과를 요약한다."""
    db_path = PROJECT_ROOT / "data" / "journal.db"
    if not db_path.exists():
        return {"error": "journal.db not found"}

    now = datetime.now(KST)
    since = int((now - timedelta(hours=12)).timestamp() * 1000)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM trades WHERE exit_time > ? ORDER BY exit_time DESC",
            (since,),
        ).fetchall()

        if not rows:
            return {"trades_12h": 0, "message": "최근 12시간 거래 없음"}

        trades = [dict(r) for r in rows]
        total_pnl = sum(t.get("net_pnl_krw", 0) for t in trades)
        wins = sum(1 for t in trades if t.get("net_pnl_krw", 0) >= 0)
        losses = len(trades) - wins
        gross_profit = sum(t["net_pnl_krw"] for t in trades if t["net_pnl_krw"] > 0)
        gross_loss = abs(sum(t["net_pnl_krw"] for t in trades if t["net_pnl_krw"] < 0))
        pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        return {
            "trades_12h": len(trades),
            "total_pnl_krw": round(total_pnl),
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / len(trades) * 100, 1) if trades else 0,
            "profit_factor": round(pf, 2),
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        conn.close()


def _build_prompt(logs: str, state: dict, balance: dict, performance: dict) -> str:
    """Claude 분석용 프롬프트를 생성한다."""
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")

    return f"""빗썸 자동매매 봇 정기 감사 보고서를 작성하라.
현재 시각: {now}

=== 점검 항목 ===
1. 거래소 잔고 vs 봇 포지션 불일치 여부 (거래소에 있는데 봇에 없는 코인, 또는 그 반대)
2. 반복되는 에러/경고 패턴 (같은 에러가 3회 이상)
3. 매매 빈도 — 12시간 동안 거래가 너무 적으면 원인 분석
4. 수익성 — PF, 승률, 총 PnL
5. 자금 활용률 — 포지션 가치 / 전체 자산
6. 더스트 잔고 — 정리 가능 여부
7. 봇이 정상 작동하는지 (마지막 사이클 시간 확인)

=== 봇 상태 ===
{json.dumps(state, indent=2, ensure_ascii=False)}

=== 거래소 잔고 ===
{json.dumps(balance, indent=2, ensure_ascii=False)}

=== 거래 성과 (12시간) ===
{json.dumps(performance, indent=2, ensure_ascii=False)}

=== 에러/경고 로그 (12시간) ===
{logs}

=== 출력 형식 ===
아래 형식으로 한국어로 작성하라. 각 항목에 문제 설명 + 근거 데이터 + 구체적 조치안을 포함.

📊 빗썸봇 정기 감사 ({now})
━━━━━━━━━━━━━━━

🔴 CRITICAL (즉시 조치)
(없으면 "없음")

🟡 WARNING (주의 필요)
(없으면 "없음")

💡 SUGGESTION (개선 제안)
(없으면 "없음")

📈 성과 요약
(12시간 거래 수, PF, 승률, PnL)
"""


async def main() -> None:
    """데이터를 수집하고 프롬프트를 stdout에 출력한다."""
    logs = _collect_logs()
    state = _collect_bot_state()
    balance = await _collect_exchange_balance()
    performance = _collect_trade_performance()
    prompt = _build_prompt(logs, state, balance, performance)
    print(prompt)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: 수동 실행 테스트**

Run: `cd /home/bythejune/projects/bithumb-bot-v2 && PROXY=http://127.0.0.1:1081 venv/bin/python scripts/audit_bot.py | head -50`
Expected: 구조화된 프롬프트 출력

- [ ] **Step 3: Claude 파이프 테스트**

Run: `cd /home/bythejune/projects/bithumb-bot-v2 && PROXY=http://127.0.0.1:1081 venv/bin/python scripts/audit_bot.py | claude -p --max-turns 1 | head -30`
Expected: Claude 분석 결과 출력

- [ ] **Step 4: 커밋**

```bash
git add scripts/audit_bot.py
git commit -m "feat: add audit_bot.py for periodic Claude Code auditing"
```

---

### Task 8: cron 등록

**Files:**
- System crontab

- [ ] **Step 1: cron 등록**

```bash
(crontab -l 2>/dev/null; cat <<'CRON'
# 봇 정기 감사 (매일 06:00, 18:00 KST)
CRON_TZ=Asia/Seoul
0 6 * * * cd /home/bythejune/projects/bithumb-bot-v2 && /home/bythejune/projects/bithumb-bot-v2/venv/bin/python scripts/audit_bot.py 2>/tmp/audit_bot.log | claude -p --max-turns 3 2>>/tmp/audit_bot.log | /home/bythejune/projects/bithumb-bot-v2/venv/bin/python scripts/send_discord_report.py 2>>/tmp/audit_bot.log
0 18 * * * cd /home/bythejune/projects/bithumb-bot-v2 && /home/bythejune/projects/bithumb-bot-v2/venv/bin/python scripts/audit_bot.py 2>/tmp/audit_bot.log | claude -p --max-turns 3 2>>/tmp/audit_bot.log | /home/bythejune/projects/bithumb-bot-v2/venv/bin/python scripts/send_discord_report.py 2>>/tmp/audit_bot.log
CRON
) | crontab -
```

- [ ] **Step 2: cron 등록 확인**

Run: `crontab -l | grep audit`
Expected: 2개 라인 (06:00, 18:00)

- [ ] **Step 3: 전체 파이프라인 테스트**

Run: `cd /home/bythejune/projects/bithumb-bot-v2 && PROXY=http://127.0.0.1:1081 venv/bin/python scripts/audit_bot.py 2>/tmp/audit_test.log | claude -p --max-turns 3 2>>/tmp/audit_test.log | venv/bin/python scripts/send_discord_report.py 2>>/tmp/audit_test.log`
Expected: Discord SYSTEM 채널에 감사 보고서 도착

---

### Task 9: CLAUDE.md 업데이트

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: 스크립트 테이블에 audit_bot.py 추가**

`### 스크립트 사용법` 테이블에 행 추가:

```markdown
| `python scripts/audit_bot.py \| claude -p --max-turns 3` | 봇 정기 감사 (cron 06:00/18:00) | `python scripts/audit_bot.py \| claude -p --max-turns 3 \| python scripts/send_discord_report.py` |
```

- [ ] **Step 2: 커밋**

```bash
git add CLAUDE.md
git commit -m "docs: add audit_bot.py to scripts reference"
```
