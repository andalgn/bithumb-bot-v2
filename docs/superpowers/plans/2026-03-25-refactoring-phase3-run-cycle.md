# Refactoring Phase 3: run_cycle Decomposition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **선행 조건:** Phase 2 완료 (`strategy/rule_engine.py` ≤ 150줄, `app/main.py`에서 `_rule_engine._*` 직접 접근 0개) 후 진행.

**Goal:** 585줄 `run_cycle()` 단일 메서드를 6개 focused 메서드로 분리하고, 메서드 간 데이터를 `MarketData` 데이터클래스로 전달한다.

**Architecture:** `MarketData` 데이터클래스를 `app/cycle_data.py`에 신설. `run_cycle()`은 6개 위임 호출만 남긴다. 각 메서드는 독립 단위 테스트 가능. 봇 외부 인터페이스(`generate_signals`, Pool, DD 등) 무변경.

> **설계 노트 1:** `_finalize_cycle()`은 `await` 호출(daily review, notifier)이 있으므로 `async def`로 정의한다. spec 의사코드는 단순화를 위해 `def`로 표기했으나 실제 구현은 async가 필요하다.
>
> **설계 노트 2:** `_execute_entries(signals, data)`는 `data.snapshots[symbol].orderbook`과 `data.snapshots[symbol].candles_1h`가 필요하므로 `data` 파라미터를 추가한다. spec 의사코드는 의존성을 단순화했다.

**Tech Stack:** Python 3.12+, dataclasses, 기존 `app/` 모듈, pytest

---

## 파일 맵

| 동작 | 경로 | 역할 |
|------|------|------|
| 생성 | `app/cycle_data.py` | `MarketData` 데이터클래스 (사이클 내 공유 데이터) |
| 수정 | `app/main.py` | `run_cycle()` 분해 → 6개 메서드 + 오케스트레이터 |
| 생성 | `tests/test_cycle_data.py` | MarketData 타입 검증 |

---

## Task 1: MarketData 데이터클래스 작성

**Files:**
- Create: `app/cycle_data.py`
- Create: `tests/test_cycle_data.py`

- [ ] **Step 1: `app/cycle_data.py` 작성**

```python
"""사이클 내 공유 데이터 컨테이너.

run_cycle() 분해 후 각 메서드 간 데이터 전달에 사용한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.data_types import Regime


@dataclass
class MarketData:
    """한 사이클에서 수집·계산된 시장 데이터."""

    snapshots: dict = field(default_factory=dict)
    """symbol → MarketSnapshot"""

    current_prices: dict[str, float] = field(default_factory=dict)
    """symbol → 현재가"""

    indicators_1h: dict = field(default_factory=dict)
    """symbol → IndicatorPack (1H)"""

    regimes: dict[str, Regime] = field(default_factory=dict)
    """symbol → Regime"""
```

- [ ] **Step 2: 타입 검증 테스트 작성**

```python
# tests/test_cycle_data.py
from app.cycle_data import MarketData
from app.data_types import Regime


def test_market_data_defaults():
    data = MarketData()
    assert data.snapshots == {}
    assert data.current_prices == {}
    assert data.indicators_1h == {}
    assert data.regimes == {}


def test_market_data_populated():
    data = MarketData(
        current_prices={"BTC": 100_000_000.0},
        regimes={"BTC": Regime.STRONG_UP},
    )
    assert data.current_prices["BTC"] == 100_000_000.0
    assert data.regimes["BTC"] == Regime.STRONG_UP
```

- [ ] **Step 3: 테스트 통과 확인**

```bash
pytest tests/test_cycle_data.py -v
```
Expected: 2케이스 PASS

- [ ] **Step 4: Commit**

```bash
git add app/cycle_data.py tests/test_cycle_data.py
git commit -m "refactor: add MarketData dataclass for run_cycle decomposition (Phase 3)"
```

---

## Task 2: `_fetch_market_data()` 추출

**Files:**
- Modify: `app/main.py`

현재 `run_cycle()` 내 시장 데이터 수집 블록 (line 434~494 + reconcile/risk 초기화):

- [ ] **Step 1: `TradingBot`에 `_fetch_market_data()` 메서드 추출**

`run_cycle()` 상단 (snapshots 수집 → market_store 저장 → profiler/correlation 갱신 → 상태 동기화 → equity 계산·리스크 갱신) 블록을 새 메서드로 이동:

```python
async def _fetch_market_data(self) -> MarketData:
    """시장 데이터 수집, 저장, 리스크 상태 갱신 후 MarketData를 반환한다.

    수행 작업:
    - 10코인 캔들/오더북/현재가 수집
    - MarketStore에 저장 (5m/15m/1h/orderbook)
    - 코인 프로파일러·상관관계 24시간마다 갱신
    - 거래소↔로컬 주문 동기화
    - equity 계산 → DDLimits, PoolManager, RiskGate 갱신
    """
    from app.cycle_data import MarketData
    from strategy.indicators import compute_indicators

    snapshots = await self._datafeed.get_all_snapshots()
    valid_count = sum(1 for s in snapshots.values() if s.current_price > 0)
    total_count = len(self._coins)
    logger.info("시장 데이터 수집 완료: %d/%d 코인", valid_count, total_count)

    # 네트워크 장애 감지
    if valid_count < total_count // 2:
        self._consecutive_data_failures += 1
        if (
            self._consecutive_data_failures >= self._data_failure_alert_threshold
            and not self._data_failure_alerted
        ):
            self._data_failure_alerted = True
            failed_coins = [
                s for s in self._coins if snapshots.get(s) and snapshots[s].current_price <= 0
            ]
            await self._notifier.send(
                f"<b>⚠ 네트워크 장애 감지</b>\n"
                f"연속 {self._consecutive_data_failures}회 데이터 수집 실패\n"
                f"수집 성공: {valid_count}/{total_count}\n"
                f"실패 코인: {', '.join(failed_coins[:5])}"
                f"{'...' if len(failed_coins) > 5 else ''}\n"
                f"VPN 연결 상태를 확인하세요.",
                channel="system",
            )
    else:
        if self._data_failure_alerted:
            await self._notifier.send(
                f"<b>✅ 네트워크 복구</b>\n"
                f"데이터 수집 정상화: {valid_count}/{total_count}\n"
                f"장애 지속: {self._consecutive_data_failures}사이클 "
                f"(약 {self._consecutive_data_failures * self._cycle_interval // 60}분)",
                channel="system",
            )
        self._consecutive_data_failures = 0
        self._data_failure_alerted = False

    # 장기 데이터 축적
    for symbol, snap in snapshots.items():
        if snap.candles_5m:
            self._market_store.store_candles(symbol, "5m", snap.candles_5m[-5:])
        if snap.candles_15m:
            self._market_store.store_candles(symbol, "15m", snap.candles_15m[-2:])
        if snap.candles_1h:
            self._market_store.store_candles(symbol, "1h", snap.candles_1h[-2:])
        if snap.orderbook:
            self._market_store.store_orderbook(symbol, snap.orderbook)

    # 코인 프로파일러·상관관계 갱신 (24시간마다)
    if self._profiler.needs_update():
        candles_1h_map = {
            sym: snap.candles_1h for sym, snap in snapshots.items() if snap.candles_1h
        }
        self._profiler.classify_all(candles_1h_map)
    if self._correlation.needs_update():
        candles_1h_map = {
            sym: snap.candles_1h for sym, snap in snapshots.items() if snap.candles_1h
        }
        self._correlation.update(candles_1h_map)

    # 상태 동기화
    recon_result = await self._reconciler.reconcile(self._coins)
    if recon_result["synced"] > 0:
        logger.info("주문 동기화: %d건", recon_result["synced"])

    # 리스크 상태 갱신
    current_prices = {sym: snap.current_price for sym, snap in snapshots.items()}
    if self._run_mode == RunMode.LIVE:
        try:
            bal = await self._client.get_balance("ALL")
            krw_available = float(bal.get("available_krw", 0))
            krw_locked = float(bal.get("locked_krw", 0))
            position_value = sum(
                current_prices.get(sym, pos.entry_price) * pos.qty
                for sym, pos in self._positions.items()
            )
            equity = krw_available + krw_locked + position_value
        except Exception:
            logger.debug("잔고 조회 실패 — Pool 장부 사용")
            equity = (
                self._pool_manager.get_balance(Pool.CORE)
                + self._pool_manager.get_balance(Pool.ACTIVE)
                + self._pool_manager.get_balance(Pool.RESERVE)
            )
    else:
        equity = (
            self._pool_manager.get_balance(Pool.CORE)
            + self._pool_manager.get_balance(Pool.ACTIVE)
            + self._pool_manager.get_balance(Pool.RESERVE)
        )
    self._dd_limits.update_equity(equity)
    self._pool_manager.update_equity(equity)
    self._risk_gate.update_state(self._pool_manager.total_exposure, equity)

    # 지표 계산
    indicators_1h: dict = {}
    regimes: dict[str, Regime] = {}
    for symbol, snap in snapshots.items():
        if snap.candles_1h and len(snap.candles_1h) >= 30:
            indicators_1h[symbol] = compute_indicators(snap.candles_1h)
            regimes[symbol] = self._rule_engine.get_regime(symbol)

    return MarketData(
        snapshots=snapshots,
        current_prices=current_prices,
        indicators_1h=indicators_1h,
        regimes=regimes,
    )
```

- [ ] **Step 2: `run_cycle()`에서 해당 블록을 `_fetch_market_data()` 호출로 교체**

```python
async def run_cycle(self) -> None:
    """한 사이클을 실행한다."""
    self._check_config_reload()
    self._cycle_count += 1
    cycle_start = time.time()
    logger.info("=" * 40)
    logger.info("사이클 #%d 시작 [%s]", self._cycle_count, self._run_mode.value)

    data = await self._fetch_market_data()

    # (아직 나머지 블록은 이 자리에 그대로 유지)
    ...
```

- [ ] **Step 3: import OK 확인**

```bash
python -c "from app.main import TradingBot; print('import OK')"
```
Expected: `import OK`

- [ ] **Step 4: Commit**

```bash
git add app/main.py app/cycle_data.py
git commit -m "refactor: extract _fetch_market_data() from run_cycle (Phase 3)"
```

---

## Task 3: `_evaluate_signals()` 추출

**Files:**
- Modify: `app/main.py`

현재 `run_cycle()` 내 승격/강등 + 신호 생성 + Darwin shadow 블록:

- [ ] **Step 1: `_evaluate_signals()` 메서드 추출**

```python
def _evaluate_signals(self, data: MarketData) -> list:
    """국면 판정 기반 승격/강등 체크 + 전략 신호 생성 + Darwin shadow 기록.

    Args:
        data: _fetch_market_data()가 반환한 시장 데이터.

    Returns:
        Signal 리스트.
    """
    from app.cycle_data import MarketData

    current_prices = data.current_prices
    indicators_1h = data.indicators_1h
    regimes = data.regimes
    snapshots = data.snapshots

    # 국면/Tier 요약 로깅 (4사이클마다)
    if self._cycle_count % 4 == 1 and regimes:
        regime_summary: dict[str, list] = {}
        for sym, reg in regimes.items():
            regime_summary.setdefault(reg.value, []).append(sym)
        tier_summary: dict[str, list] = {}
        for sym in self._coins:
            t = self._profiler.get_tier(sym)
            tier_summary.setdefault(f"T{t.tier.value}", []).append(sym)
        logger.info("국면: %s", {k: v for k, v in regime_summary.items()})
        logger.info("Tier: %s", {k: v for k, v in tier_summary.items()})

    # Core 포지션 강등 체크
    demoted = self._promotion_manager.update_core_positions(
        current_prices,
        indicators_1h,
        regimes,
    )
    for sym in demoted:
        if sym in self._positions:
            self._positions[sym].pool = Pool.ACTIVE
            self._positions[sym].promoted = False

    # Active 포지션 승격 체크
    for symbol, pos in list(self._positions.items()):
        if pos.pool != Pool.ACTIVE or pos.promoted:
            continue
        ind_1h = indicators_1h.get(symbol)
        regime = regimes.get(symbol, Regime.RANGE)
        if ind_1h and self._promotion_manager.check_promotion(
            pos, current_prices.get(symbol, 0), ind_1h, regime
        ):
            core_pos = self._promotion_manager.promote(pos, ind_1h)
            if core_pos:
                self._positions[symbol] = core_pos.position

    # 신호 생성
    if self._paused:
        logger.info("봇 일시 중지 중 — 신규 진입 스킵")
        signals = []
    else:
        signals = self._rule_engine.generate_signals(
            snapshots,
            paper_test=self._paper_test,
        )

    if signals:
        for sig in signals:
            logger.info(
                "시그널: %s %s [%s] %.0f점 | 진입=%.0f SL=%.0f TP=%.0f",
                sig.direction.value,
                sig.symbol,
                sig.strategy.value,
                sig.score,
                sig.entry_price,
                sig.stop_loss,
                sig.take_profit,
            )
    elif self._cycle_count % 4 == 0:
        logger.info("시그널 없음 (조건 미충족)")

    # Darwin Shadow 기록
    sl_mult = self._rule_engine.strategy_params.get("mean_reversion", {}).get("sl_mult", 7.0)
    shadow_count = self._darwin.record_cycle(snapshots, signals, live_sl_mult=sl_mult)
    if shadow_count > 0 and self._cycle_count % 12 == 0:
        logger.info("Darwin Shadow 기록: %d건", shadow_count)

    return signals
```

- [ ] **Step 2: `run_cycle()`에서 해당 블록을 `_evaluate_signals(data)` 호출로 교체**

- [ ] **Step 3: import OK + snapshot 테스트 통과**

```bash
python -c "from app.main import TradingBot; print('import OK')"
pytest tests/test_regime_snapshot.py tests/test_env_filter_snapshot.py tests/test_strategy_scorer_snapshot.py -v
```
Expected: `import OK`, 19케이스 PASS

- [ ] **Step 4: Commit**

```bash
git add app/main.py
git commit -m "refactor: extract _evaluate_signals() from run_cycle (Phase 3)"
```

---

## Task 4: `_run_darwin_cycle()` 추출

**Files:**
- Modify: `app/main.py`

현재 `run_cycle()` 내 Darwin 토너먼트 + 챔피언 교체 블록 (lines 624~673):

- [ ] **Step 1: `_run_darwin_cycle()` 메서드 추출**

```python
async def _run_darwin_cycle(self) -> None:
    """Darwin 토너먼트 + 챔피언 적용 + 파라미터 롤백.

    일요일 04:00 KST 이후 12사이클마다 토너먼트 실행.
    챔피언 교체 조건: trade_count >= 30, PF > 현행, MDD <= 15%.
    """
    import datetime as _dt

    _now_kst = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=9)))
    if not (_now_kst.weekday() == 6 and _now_kst.hour >= 4 and self._cycle_count % 12 == 0):
        return

    market_regime = self._get_market_regime()
    self._darwin.run_tournament(market_regime=market_regime)
    new_champion = self._darwin.check_champion_replacement()
    if not new_champion:
        return

    shadow_perf = self._darwin._performances.get(new_champion.shadow_id)
    if not (shadow_perf and shadow_perf.trade_count >= 30):
        return

    pf = shadow_perf.profit_factor
    mdd = shadow_perf.max_drawdown
    recent_trades = self._journal.get_trades_since(int(time.time()) - 30 * 86400)
    current_pf = (
        self._backtest_daemon._calc_pf(recent_trades) if recent_trades else 1.0
    )
    if not (pf > current_pf and mdd <= 0.15):
        return

    self._darwin.replace_champion(new_champion)
    champ_params = self._darwin.champion_to_strategy_params()
    config_path = self._config_path

    import shutil as _shutil
    backup_path = config_path.with_suffix(
        f".yaml.bak.{_now_kst.strftime('%Y%m%d_%H%M%S')}"
    )
    _shutil.copy2(config_path, backup_path)
    self._apply_champion_params(champ_params, config_path)

    old_mr = self._rule_engine.strategy_params.get("mean_reversion", {})
    old_dca = self._rule_engine.strategy_params.get("dca", {})
    self._experiment_store.log_param_change(
        source="darwin",
        strategy="mean_reversion+dca",
        old_params={"mean_reversion": old_mr, "dca": old_dca},
        new_params=champ_params,
        backup_path=str(backup_path),
        baseline_pf=current_pf,
    )
    self._pilot_remaining = 20
    self._pilot_size_mult = 0.5
    logger.info("Darwin 챔피언 실전 적용: %s", champ_params)
```

- [ ] **Step 2: `run_cycle()`에서 해당 블록을 `await self._run_darwin_cycle()` 호출로 교체**

- [ ] **Step 3: import OK 확인**

```bash
python -c "from app.main import TradingBot; print('import OK')"
```

- [ ] **Step 4: Commit**

```bash
git add app/main.py
git commit -m "refactor: extract _run_darwin_cycle() from run_cycle (Phase 3)"
```

---

## Task 5: `_execute_entries()` 추출

**Files:**
- Modify: `app/main.py`

현재 `run_cycle()` 내 신호 평가 + Pool 사이징 + 주문 실행 블록 (lines 675~866):

- [ ] **Step 1: `_execute_entries()` 메서드 추출**

```python
async def _execute_entries(self, signals: list, data: MarketData) -> None:
    """RiskGate 통과 신호만 Pool 사이징 → 주문 실행 → 포지션 등록.

    Args:
        signals: _evaluate_signals()가 반환한 Signal 리스트.
        data: 현재 사이클 시장 데이터 (orderbook, snapshots 참조용).
    """
    for signal in signals:
        if signal.symbol in self._positions:
            continue

        active_coins = list(self._positions.keys())
        corr_result = self._correlation.check_correlation(signal.symbol, active_coins)
        if not corr_result.allowed:
            continue

        check = self._risk_gate.check(
            signal,
            orderbook=data.snapshots[signal.symbol].orderbook,
            order_krw=self._config.sizing.active_min_krw,
        )
        self._journal.record_signal(
            {
                "symbol": signal.symbol,
                "direction": signal.direction.value,
                "strategy": signal.strategy.value,
                "score": signal.score,
                "regime": signal.regime.value,
                "tier": signal.tier.value,
                "entry_price": signal.entry_price,
                "stop_loss": signal.stop_loss,
                "take_profit": signal.take_profit,
                "accepted": check.allowed,
                "reject_reason": check.reason,
            }
        )
        if not check.allowed:
            logger.info(
                "신호 거부: %s %s [%.0f점] -%s",
                signal.direction.value,
                signal.symbol,
                signal.score,
                check.reason,
            )
            continue

        # Pool 기반 사이징
        if signal.strategy == Strategy.DCA:
            dca_krw = self._position_manager.calculate_dca_size()
            if self._pilot_size_mult < 1.0:
                dca_krw = int(dca_krw * self._pilot_size_mult)
            sizing = SizingResult(
                pool=Pool.CORE,
                size_krw=dca_krw,
                detail={"dca_fixed": dca_krw},
            )
        else:
            tier_params = self._profiler.get_tier(signal.symbol)
            size_decision = self._rule_engine.decide_size_public(signal.strategy, signal.score)
            weekly_dd = self._dd_limits._calc_dd(self._dd_limits.state.weekly_base)
            sizing = self._position_manager.calculate_size(
                signal=signal,
                tier_params=tier_params,
                size_decision=size_decision,
                active_positions=active_coins,
                weekly_dd_pct=weekly_dd,
                candles_1h=data.snapshots[signal.symbol].candles_1h,
                pilot_mult=self._pilot_size_mult,
            )

        # LIVE 전환 첫 7일: risk_pct 50% 축소
        if self._live_risk_reduction and sizing.size_krw > 0:
            sizing = SizingResult(
                pool=sizing.pool,
                size_krw=sizing.size_krw * 0.5,
                detail={**sizing.detail, "live_reduction": 0.5},
            )
            if time.time() - self._live_start_time > 7 * 86400:
                self._live_risk_reduction = False
                logger.info("LIVE risk_pct 축소 자동 해제 (7일 경과)")

        if sizing.size_krw <= 0:
            logger.info(
                "사이징 0: %s %s [%.0f점] size_krw=%.0f",
                signal.direction.value,
                signal.symbol,
                signal.score,
                sizing.size_krw,
            )
            continue

        alloc_pool = sizing.pool if hasattr(sizing, "pool") else Pool.ACTIVE
        if not self._pool_manager.allocate(alloc_pool, sizing.size_krw):
            logger.info(
                "Pool 할당 실패: %s (%.0f원, Active 잔액 부족)",
                signal.symbol,
                sizing.size_krw,
            )
            continue

        if signal.direction == OrderSide.BUY and signal.entry_price > 0:
            qty = normalize_qty(signal.symbol, sizing.size_krw / signal.entry_price)
            ticket = self._order_manager.create_ticket(
                symbol=signal.symbol,
                side=signal.direction,
                price=signal.entry_price,
                qty=qty,
            )
            ticket = await self._order_manager.execute_order(ticket)

            logger.info(
                "주문 %s: %s %s %.4f @ %.0f [%s %.0f점] 사이즈=%.0f원 → %s",
                ticket.ticket_id,
                signal.direction.value,
                signal.symbol,
                qty,
                signal.entry_price,
                signal.strategy.value,
                signal.score,
                sizing.size_krw,
                ticket.status.value,
            )

            if ticket.status == OrderStatus.FILLED:
                self._risk_gate.record_entry(signal.symbol)
                actual_price = ticket.filled_price if ticket.filled_price > 0 else signal.entry_price
                self._positions[signal.symbol] = Position(
                    symbol=signal.symbol,
                    entry_price=actual_price,
                    entry_time=int(time.time() * 1000),
                    size_krw=sizing.size_krw,
                    qty=ticket.filled_qty if ticket.filled_qty > 0 else qty,
                    stop_loss=signal.stop_loss,
                    take_profit=signal.take_profit,
                    strategy=signal.strategy,
                    pool=alloc_pool,
                    tier=signal.tier,
                    regime=signal.regime,
                    entry_score=signal.score,
                    signal_price=signal.entry_price,
                )
                self._exit_manager.init_position(signal.symbol)
                if self._pilot_remaining > 0:
                    self._pilot_remaining -= 1
                    if self._pilot_remaining == 0:
                        self._pilot_size_mult = 1.0
                        logger.info("Pilot 기간 종료: 포지션 사이즈 100% 복원")

                sim_tag = "" if self._run_mode == RunMode.LIVE else f" [시뮬레이션/{self._run_mode.value}]"
                filled_qty = ticket.filled_qty if ticket.filled_qty > 0 else qty
                slippage_pct = (actual_price - signal.entry_price) / signal.entry_price * 100 if signal.entry_price > 0 else 0
                sl_pct = (signal.stop_loss - actual_price) / actual_price * 100 if actual_price > 0 else 0
                tp_pct = (signal.take_profit - actual_price) / actual_price * 100 if actual_price > 0 else 0
                pool_after = self._pool_manager.get_available(alloc_pool)
                util = self._pool_manager.utilization_pct
                await self._notifier.send(
                    f"📈 **{signal.symbol} 매수 체결{sim_tag}**\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"전략: {signal.strategy.value} | {signal.score:.0f}점\n"
                    f"국면: {signal.regime.value} | Tier {signal.tier.value}\n"
                    f"가격: {actual_price:,.0f}원"
                    f"{f' (신호가 {signal.entry_price:,.0f} → {slippage_pct:+.2f}%)' if abs(slippage_pct) > 0.001 else ''}\n"
                    f"수량: {filled_qty:.4f}개 | {sizing.size_krw:,.0f}원\n"
                    f"SL: {signal.stop_loss:,.0f} ({sl_pct:+.1f}%) | TP: {signal.take_profit:,.0f} ({tp_pct:+.1f}%)\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"Pool: {alloc_pool.value.capitalize()} → {pool_after:,.0f}원\n"
                    f"포지션: {len(self._positions)}/{len(self._coins)} | 활용률 {util * 100:.1f}%",
                    channel="trade",
                )
            else:
                self._pool_manager.release(alloc_pool, sizing.size_krw)
                logger.warning(
                    "주문 실패 → Pool 롤백: %s %.0f원",
                    signal.symbol,
                    sizing.size_krw,
                )
                await self._notifier.send(
                    f"<b>⚠ {signal.symbol} 주문 실패</b>\n"
                    f"전략: {signal.strategy.value} | {signal.score:.0f}점\n"
                    f"상태: {ticket.status.value}\n"
                    f"Pool 할당 롤백: {sizing.size_krw:,.0f}원",
                    channel="system",
                )
```

- [ ] **Step 2: `run_cycle()`에서 해당 블록을 `await self._execute_entries(signals, data)` 호출로 교체**

> **주의**: CRISIS 전량 청산 블록(crisis_failed)은 `_manage_open_positions()`로 이동 예정이므로 아직 run_cycle()에 남겨둔다.

- [ ] **Step 3: import OK + snapshot 테스트 통과**

```bash
python -c "from app.main import TradingBot; print('import OK')"
pytest tests/test_regime_snapshot.py tests/test_env_filter_snapshot.py tests/test_strategy_scorer_snapshot.py -v
```

- [ ] **Step 4: Commit**

```bash
git add app/main.py
git commit -m "refactor: extract _execute_entries() from run_cycle (Phase 3)"
```

---

## Task 6: `_manage_open_positions()` 추출

**Files:**
- Modify: `app/main.py`

현재 `run_cycle()` 내 CRISIS 청산 + 트레일링/부분청산 블록:

- [ ] **Step 1: `_manage_open_positions()` 메서드 추출**

```python
async def _manage_open_positions(self, data: MarketData) -> None:
    """CRISIS 긴급 청산 + 트레일링 스톱/부분청산/시간 제한 청산.

    Args:
        data: 현재 사이클 시장 데이터 (current_prices, indicators_1h 참조).
    """
    import numpy as np
    from execution.partial_exit import ExitAction

    current_prices = data.current_prices
    indicators_1h = data.indicators_1h
    regimes = data.regimes

    # CRISIS 전량 청산 (개별 실패 시 다음 사이클 재시도)
    crisis_failed: set[str] = set()
    for symbol in list(self._positions.keys()):
        regime = regimes.get(symbol, Regime.RANGE)
        if regime == Regime.CRISIS:
            price = current_prices.get(symbol, 0)
            if price > 0:
                try:
                    logger.warning("CRISIS 전량 청산: %s @ %.0f", symbol, price)
                    await self._close_position(symbol, price, "crisis")
                except Exception:
                    logger.exception("CRISIS 청산 실패 (다음 사이클 재시도): %s", symbol)
                    crisis_failed.add(symbol)

    # 트레일링 스톱, 부분청산, 시간 제한 청산
    now_ms = int(time.time() * 1000)
    for symbol in list(self._positions.keys()):
        if symbol in crisis_failed:
            continue
        pos = self._positions[symbol]
        price = current_prices.get(symbol, 0)
        if price <= 0:
            continue

        atr_val = 0.0
        bb_mid = 0.0
        ind = indicators_1h.get(symbol)
        if ind and hasattr(ind, "atr") and len(ind.atr) > 0:
            valid_atr = ind.atr[~np.isnan(ind.atr)]
            atr_val = float(valid_atr[-1]) if len(valid_atr) > 0 else 0
        if ind and hasattr(ind, "bb") and ind.bb is not None:
            bb_arr = ind.bb.middle
            valid_bb = bb_arr[~np.isnan(bb_arr)]
            bb_mid = float(valid_bb[-1]) if len(valid_bb) > 0 else 0

        is_core = self._promotion_manager.is_core(symbol)
        core_sl = 0.0
        cp = self._promotion_manager.get_core_position(symbol)
        if cp:
            core_sl = cp.core_stop_loss

        time_exit = self._exit_manager.check_time_exit(pos, now_ms)
        if time_exit.action != ExitAction.NONE:
            logger.info("시간 제한 청산: %s", symbol)
            await self._close_position(symbol, price, time_exit.reason.value)
            continue

        decision = self._exit_manager.evaluate(
            position=pos,
            current_price=price,
            atr_value=atr_val,
            bb_middle=bb_mid,
            is_core=is_core,
            core_stop_loss=core_sl,
        )
        if decision.action == ExitAction.NONE:
            continue
        if decision.exit_ratio >= 1.0:
            logger.info(
                "전량 청산: %s [%s] @ %.0f",
                symbol,
                decision.action.value,
                price,
            )
            await self._close_position(symbol, price, decision.reason.value)
        else:
            await self._partial_close_position(
                symbol,
                price,
                decision.exit_ratio,
                decision.reason.value,
            )
```

- [ ] **Step 2: `run_cycle()`에서 CRISIS 청산 블록 + 포지션 관리 블록을 `await self._manage_open_positions(data)` 호출로 교체**

- [ ] **Step 3: import OK 확인**

```bash
python -c "from app.main import TradingBot; print('import OK')"
```

- [ ] **Step 4: Commit**

```bash
git add app/main.py
git commit -m "refactor: extract _manage_open_positions() from run_cycle (Phase 3)"
```

---

## Task 7: `_finalize_cycle()` 추출

**Files:**
- Modify: `app/main.py`

현재 `run_cycle()` 내 로깅 + 리뷰 트리거 + 롤백 + 상태 저장 블록 (lines 933~1011):

- [ ] **Step 1: `_finalize_cycle()` 메서드 추출**

```python
async def _finalize_cycle(self, data: MarketData) -> None:
    """활용률 로깅, 일/주/월 리뷰 트리거, 롤백 모니터링, 상태 저장.

    Args:
        data: 현재 사이클 시장 데이터 (활용률 계산용).
    """
    from datetime import datetime, timedelta
    from datetime import timezone as tz

    util = self._pool_manager.utilization_pct
    if self._cycle_count % 4 == 0:
        logger.info(
            "자금 활용률: %.1f%% | 포지션: %d개",
            util * 100,
            len(self._positions),
        )

    now_kst = datetime.now(tz(timedelta(hours=9)))
    if now_kst.hour == 0 and now_kst.minute < 15:
        await self._review_engine.run_daily_review(
            active_positions=len(self._positions),
            utilization_pct=util,
        )
        self._journal.cleanup()
        self._market_store.cleanup()

        if self._run_mode == RunMode.PAPER:
            from app.live_gate import LiveGate
            gate = LiveGate()
            paper_days = (
                int((time.time() - self._paper_start_time) / 86400)
                if self._paper_start_time
                else 0
            )
            total_trades = self._journal.get_trade_count()
            gate_result = gate.evaluate(
                paper_days=paper_days,
                total_trades=total_trades,
                strategy_expectancy={},
                mdd_pct=self._dd_limits._calc_dd(self._dd_limits.state.total_base),
                max_daily_dd_pct=self._dd_limits.get_max_daily_dd(),
                uptime_pct=0.99,
                unresolved_auth_errors=0,
                slippage_model_error_pct=0.0,
                wf_pass_count=(
                    self._backtest_daemon.wf_result.pass_count
                    if self._backtest_daemon.wf_result
                    else 0
                ),
                wf_total=4,
                mc_p5_pnl=(
                    self._backtest_daemon.mc_result.pnl_percentile_5
                    if self._backtest_daemon.mc_result
                    else 0
                ),
            )
            await self._notifier.send(gate.format_report(gate_result), channel="livegate")

        if now_kst.weekday() == 6:
            shadow_top3 = self._darwin.get_top_shadows(3)
            bd = self._backtest_daemon
            await self._review_engine.run_weekly_review(
                shadow_top3=shadow_top3,
                wf_verdict=bd.wf_result.verdict if bd.wf_result else "",
                mc_p5=bd.mc_result.pnl_percentile_5 if bd.mc_result else 0,
                mc_mdd=bd.mc_result.worst_mdd if bd.mc_result else 0,
            )

        if now_kst.day == 1 and now_kst.hour == 0 and now_kst.minute < 15:
            await self._review_engine.run_monthly_review()

    await self._check_rollback()
    self._save_state()
```

- [ ] **Step 2: `run_cycle()`에서 해당 블록을 `await self._finalize_cycle(data)` 호출로 교체**

- [ ] **Step 3: `run_cycle()` 최종 형태 확인**

최종 `run_cycle()`은 다음과 같이 ≤ 25줄이어야 한다:

```python
async def run_cycle(self) -> None:
    """한 사이클을 실행한다. 각 단계를 위임만 한다."""
    self._check_config_reload()
    self._cycle_count += 1
    cycle_start = time.time()
    logger.info("=" * 40)
    logger.info("사이클 #%d 시작 [%s]", self._cycle_count, self._run_mode.value)

    data = await self._fetch_market_data()
    signals = self._evaluate_signals(data)
    await self._manage_open_positions(data)
    await self._run_darwin_cycle()
    await self._execute_entries(signals, data)
    await self._finalize_cycle(data)

    elapsed = time.time() - cycle_start
    logger.info("사이클 #%d 완료 (%.1f초)", self._cycle_count, elapsed)
```

- [ ] **Step 4: run_cycle() 줄수 확인**

```bash
grep -n "async def run_cycle\|async def _fetch\|async def _evaluate\|async def _manage\|async def _run_darwin\|async def _execute\|async def _finalize" \
  /home/bythejune/projects/bithumb-bot-v2/app/main.py
```

- [ ] **Step 5: import OK 확인**

```bash
python -c "from app.main import TradingBot; print('import OK')"
```

- [ ] **Step 6: Commit**

```bash
git add app/main.py
git commit -m "refactor: extract _finalize_cycle() — run_cycle() now ≤ 25 lines (Phase 3)"
```

---

## Task 8: Phase 3 완료 검증

**Files:**
- Verify: `app/main.py`

- [ ] **Step 1: run_cycle() 줄수 ≤ 25줄 확인**

```python
import ast, pathlib
src = pathlib.Path("app/main.py").read_text()
tree = ast.parse(src)
for cls in ast.walk(tree):
    if isinstance(cls, ast.ClassDef) and cls.name == "TradingBot":
        for func in ast.walk(cls):
            if isinstance(func, ast.AsyncFunctionDef) and func.name == "run_cycle":
                print(f"run_cycle: {func.end_lineno - func.lineno + 1} 줄")
```

```bash
python -c "
import ast, pathlib
src = pathlib.Path('app/main.py').read_text()
tree = ast.parse(src)
for cls in ast.walk(tree):
    if isinstance(cls, ast.ClassDef) and cls.name == 'TradingBot':
        for func in ast.walk(cls):
            if isinstance(func, ast.AsyncFunctionDef) and func.name == 'run_cycle':
                print(f'run_cycle: {func.end_lineno - func.lineno + 1} 줄')
"
```
Expected: `run_cycle: N 줄` (N ≤ 25)

- [ ] **Step 2: 전체 스냅샷 테스트 통과**

```bash
pytest tests/test_regime_snapshot.py tests/test_env_filter_snapshot.py tests/test_strategy_scorer_snapshot.py tests/test_cycle_data.py -v
```
Expected: 21케이스 전체 PASS

- [ ] **Step 3: 전체 테스트 스위트 통과**

```bash
pytest tests/ -v --tb=short 2>&1 | tail -30
```
Expected: 전체 통과

- [ ] **Step 4: 봇 재시작 + 사이클 확인**

```bash
sudo systemctl restart bithumb-bot && sleep 5 && sudo journalctl -u bithumb-bot -n 10 --no-pager
```
Expected: `사이클 #1 완료` 로그 확인

- [ ] **Step 5: 최종 Commit + 태그**

```bash
git add -A
git commit -m "refactor: Phase 3 complete — run_cycle decomposed into 6 focused methods"
git tag phase3-run-cycle-split
```

---

## Phase 3 완료 기준 체크리스트

- [ ] `run_cycle()` ≤ 25줄
- [ ] 6개 추출 메서드 모두 존재 (`_fetch_market_data`, `_evaluate_signals`, `_manage_open_positions`, `_run_darwin_cycle`, `_execute_entries`, `_finalize_cycle`)
- [ ] `app/cycle_data.py` 생성 (`MarketData` 데이터클래스)
- [ ] 스냅샷 테스트 19케이스 + cycle_data 2케이스 = 21케이스 전체 PASS
- [ ] 봇 재시작 후 사이클 정상 실행

**다음 단계:** `docs/superpowers/plans/2026-03-25-refactoring-phase4-state-store.md`
