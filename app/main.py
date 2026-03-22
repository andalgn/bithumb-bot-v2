"""오케스트레이터 -15분 주기 메인 루프.

DRY/PAPER/LIVE 모드. 전체 사이클 try-except + 디스코드 알림.
Phase 3: Pool 기반 사이징 + 승격/강등.
"""

from __future__ import annotations

import asyncio
import logging
import time

import numpy as np

from app.config import AppConfig
from app.data_types import OrderSide, Pool, Position, Regime, RunMode, Strategy, Tier
from app.journal import Journal
from app.notify import DiscordNotifier
from app.storage import StateStorage
from backtesting.daemon import BacktestDaemon
from bot_discord.bot import DiscordBot
from execution.order_manager import OrderManager
from execution.partial_exit import ExitAction, PartialExitManager
from execution.quarantine import QuarantineManager
from execution.reconciler import Reconciler
from market.bithumb_api import BithumbClient
from market.datafeed import DataFeed
from market.market_store import MarketStore
from market.normalizer import normalize_qty
from risk.dd_limits import DDLimits
from risk.risk_gate import RiskGate
from strategy.coin_profiler import CoinProfiler
from strategy.correlation_monitor import CorrelationMonitor
from strategy.darwin_engine import DarwinEngine
from strategy.indicators import compute_indicators
from strategy.pool_manager import PoolManager
from strategy.position_manager import PositionManager, SizingResult
from strategy.promotion_manager import PromotionManager
from strategy.review_engine import ReviewEngine
from strategy.rule_engine import RuleEngine

logger = logging.getLogger(__name__)


def _on_daemon_done(task: asyncio.Task) -> None:
    """BacktestDaemon 태스크 종료 콜백."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc:
        logger.error("BacktestDaemon 비정상 종료: %s", exc, exc_info=exc)


class TradingBot:
    """자동매매 봇 오케스트레이터."""

    def __init__(self, config: AppConfig) -> None:
        """초기화.

        Args:
            config: 애플리케이션 설정.
        """
        self._config = config
        self._run_mode = RunMode(config.run_mode)
        self._coins = config.coins
        self._cycle_interval = config.cycle_interval_sec
        self._running = False
        self._cycle_count = 0
        self._paper_test = config.paper_test

        # 컴포넌트 초기화
        self._client = BithumbClient(
            api_key=config.secrets.bithumb_api_key,
            api_secret=config.secrets.bithumb_api_secret,
            base_url=config.secrets.bithumb_api_url or config.bithumb.base_url,
            public_rate_limit=config.bithumb.public_rate_limit,
            private_rate_limit=config.bithumb.private_rate_limit,
            proxy=config.proxy,
            verify_ssl=not bool(config.proxy),
        )

        self._notifier = DiscordNotifier(
            webhooks=config.secrets.discord_webhooks,
            proxy=config.proxy,
            timeout_sec=config.discord.timeout_sec,
        )

        self._datafeed = DataFeed(self._client, self._coins)
        self._market_store = MarketStore(db_path="data/market_data.db")
        self._journal = Journal(db_path="data/journal.db")
        self._storage = StateStorage(path="data/app_state.json")

        self._quarantine = QuarantineManager(
            coin_fail_limit=config.risk_gate.coin_quarantine_failures,
            coin_quarantine_sec=config.risk_gate.coin_quarantine_sec,
            global_fail_limit=config.risk_gate.global_quarantine_failures,
            global_quarantine_sec=config.risk_gate.global_quarantine_sec,
            auth_quarantine_sec=config.risk_gate.auth_error_quarantine_sec,
        )

        self._dd_limits = DDLimits(
            daily_pct=config.risk_gate.daily_dd_pct,
            weekly_pct=config.risk_gate.weekly_dd_pct,
            monthly_pct=config.risk_gate.monthly_dd_pct,
            total_pct=config.risk_gate.total_dd_pct,
        )

        self._risk_gate = RiskGate(
            dd_limits=self._dd_limits,
            quarantine=self._quarantine,
            max_exposure_pct=config.risk_gate.max_exposure_pct,
            consecutive_loss_limit=config.risk_gate.consecutive_loss_limit,
            cooldown_min=config.risk_gate.cooldown_min,
            notifier=self._notifier,
        )

        self._order_manager = OrderManager(
            client=self._client,
            run_mode=self._run_mode,
            timeout_sec=config.execution.order_timeout_sec,
            max_retries=config.execution.retry_count,
        )

        self._reconciler = Reconciler(
            client=self._client,
            order_manager=self._order_manager,
            run_mode=self._run_mode,
        )

        self._profiler = CoinProfiler(tier1_atr_max=0.009, tier3_atr_min=0.014)

        self._correlation = CorrelationMonitor(
            skip_threshold=0.85,
            reduce_threshold_min=0.70,
            reduce_threshold_max=0.85,
            reduce_mult=0.5,
        )

        self._rule_engine = RuleEngine(
            profiler=self._profiler,
            score_cutoff=config.score_cutoff,
            regime_config=config.regime,
            execution_config=config.execution,
            strategy_params=config.strategy_params,
        )

        # Phase 3: Pool + Position + Promotion
        # PAPER/DRY 모드 기본 초기 자본. LIVE 전환 시 실제 잔고로 대체됨.
        # _restore_state()에서 저장된 값을 로드하므로 첫 실행에만 적용.
        initial_equity = 1_000_000
        self._pool_manager = PoolManager(initial_equity)

        self._position_manager = PositionManager(
            pool_manager=self._pool_manager,
            correlation=self._correlation,
            sizing_config=config.sizing,
        )

        self._promotion_manager = PromotionManager(
            pool_manager=self._pool_manager,
            profit_pct=config.promotion.profit_pct,
            profit_hold_bars=config.promotion.profit_hold_bars,
            adx_min=config.promotion.adx_min,
            protection_bars=config.promotion.protection_bars,
            dca_wait_bars=config.promotion.dca_wait_bars,
            dca_rescore_min=config.promotion.dca_rescore_min,
            dca_profit_min=config.promotion.dca_profit_min,
            dca_max_per_position=config.promotion.dca_max_per_position,
            re_promotion_verify_bars=config.promotion.re_promotion_verify_bars,
        )

        # Phase 4: 부분청산 + 트레일링
        self._exit_manager = PartialExitManager()

        # Phase 5: Darwin + BacktestDaemon
        self._darwin = DarwinEngine(population_size=20, journal=self._journal)
        self._backtest_daemon = BacktestDaemon(
            journal=self._journal,
            notifier=self._notifier,
            config=config.backtest,
            store=self._market_store,
            client=self._client,
            coins=config.coins,
            deepseek_api_key=config.secrets.deepseek_api_key,
        )

        # Phase 6: ReviewEngine
        self._review_engine = ReviewEngine(
            journal=self._journal,
            notifier=self._notifier,
            deepseek_api_key=config.secrets.deepseek_api_key,
        )
        self._review_engine._risk_gate = self._risk_gate

        # 포지션 관리
        self._positions: dict[str, Position] = {}

        # 일시 중지 / 시작 시간
        self._paused = False
        self._bot_start_time = time.time()
        self._paper_start_time: float = 0.0

        # LIVE 전환 risk_pct 50% 축소
        self._live_risk_reduction = False
        self._live_start_time: float = 0.0

        # 네트워크 장애 추적
        self._consecutive_data_failures = 0
        self._data_failure_alert_threshold = 2  # 연속 2회 실패 시 알림
        self._data_failure_alerted = False

        # 상태 복원
        self._restore_state()

    def _restore_state(self) -> None:
        """저장된 상태를 복원한다."""
        dd_state = self._storage.get("dd_limits")
        if dd_state:
            self._dd_limits.load_state(dd_state)

        rg_state = self._storage.get("risk_gate")
        if rg_state:
            self._risk_gate.load_state(rg_state)

        pool_state = self._storage.get("pool_manager")
        if pool_state:
            self._pool_manager.load_state(pool_state)

        if self._dd_limits.state.total_base == 0:
            initial = self._storage.get("initial_equity", 1_000_000)
            self._dd_limits.initialize(initial)
            logger.info("DD 초기 자산: %s원", f"{initial:,.0f}")

        # 포지션 복원
        positions_data = self._storage.get("positions", {})
        for sym, pdata in positions_data.items():
            try:
                self._positions[sym] = Position(
                    symbol=pdata["symbol"],
                    entry_price=pdata["entry_price"],
                    entry_time=pdata["entry_time"],
                    size_krw=pdata["size_krw"],
                    qty=pdata["qty"],
                    stop_loss=pdata["stop_loss"],
                    take_profit=pdata["take_profit"],
                    strategy=Strategy(pdata["strategy"]),
                    pool=Pool(pdata["pool"]),
                    tier=Tier(pdata["tier"]),
                    regime=Regime(pdata.get("regime", "RANGE")),
                    promoted=pdata.get("promoted", False),
                    entry_score=pdata.get("entry_score", 0),
                    signal_price=pdata.get("signal_price", 0),
                )
                self._exit_manager.init_position(sym)
                logger.info(
                    "포지션 복원: %s %.6f @ %.0f (SL=%.0f TP=%.0f)",
                    sym,
                    pdata["qty"],
                    pdata["entry_price"],
                    pdata["stop_loss"],
                    pdata["take_profit"],
                )
            except (KeyError, ValueError, TypeError):
                logger.exception("포지션 복원 실패: %s (스킵)", sym)

        # RegimeState 복원
        regime_data = self._storage.get("regime_states", {})
        for sym, rd in regime_data.items():
            try:
                rs = self._rule_engine._get_regime_state(sym)
                rs.current = Regime(rd["current"])
                rs.pending = Regime(rd["pending"]) if rd.get("pending") else None
                rs.confirm_count = rd.get("confirm_count", 0)
                rs.cooldown_remaining = rd.get("cooldown_remaining", 0)
                rs.crisis_release_count = rd.get("crisis_release_count", 0)
            except (KeyError, ValueError):
                pass

        # 승격 상태 복원
        promo_state = self._storage.get("promotion_state")
        if promo_state:
            self._promotion_manager.from_state(promo_state, self._positions)

        # PositionManager 연속 손실 복원
        self._position_manager._consecutive_losses = self._storage.get(
            "pm_consecutive_losses",
            0,
        )

        # LIVE risk_pct 축소 상태 복원
        self._live_risk_reduction = self._storage.get("live_risk_reduction", False)
        self._live_start_time = self._storage.get("live_start_time", 0.0)

        # pause 상태 복원
        self._paused = self._storage.get("paused", False)

        # PAPER 모드 시작 시간 복원 (없으면 현재 시간으로 초기화)
        stored_paper_start = self._storage.get("paper_start_time", 0.0)
        if stored_paper_start > 0:
            self._paper_start_time = stored_paper_start
        elif self._run_mode == RunMode.PAPER:
            self._paper_start_time = time.time()

    def _save_state(self) -> None:
        """현재 상태를 저장한다."""
        self._storage.set("dd_limits", self._dd_limits.dump_state())
        self._storage.set("risk_gate", self._risk_gate.dump_state())
        self._storage.set("pool_manager", self._pool_manager.dump_state())
        self._storage.set("cycle_count", self._cycle_count)
        self._storage.set("last_cycle_at", int(time.time()))

        # 포지션 영속화
        positions_data = {}
        for sym, pos in self._positions.items():
            positions_data[sym] = {
                "symbol": pos.symbol,
                "entry_price": pos.entry_price,
                "entry_time": pos.entry_time,
                "size_krw": pos.size_krw,
                "qty": pos.qty,
                "stop_loss": pos.stop_loss,
                "take_profit": pos.take_profit,
                "strategy": pos.strategy.value,
                "pool": pos.pool.value,
                "tier": pos.tier.value,
                "regime": pos.regime.value,
                "promoted": pos.promoted,
                "entry_score": pos.entry_score,
                "signal_price": pos.signal_price,
            }
        self._storage.set("positions", positions_data)

        # RegimeState 영속화
        regime_data = {}
        for sym, rs in self._rule_engine._regime_states.items():
            regime_data[sym] = {
                "current": rs.current.value,
                "pending": rs.pending.value if rs.pending else None,
                "confirm_count": rs.confirm_count,
                "cooldown_remaining": rs.cooldown_remaining,
                "crisis_release_count": rs.crisis_release_count,
            }
        self._storage.set("regime_states", regime_data)

        # PositionManager 연속 손실 카운터 영속화
        self._storage.set(
            "pm_consecutive_losses",
            self._position_manager._consecutive_losses,
        )

        # 승격 상태 영속화
        self._storage.set("promotion_state", self._promotion_manager.to_state())

        # LIVE risk_pct 축소 + pause + paper_start_time 영속화
        self._storage.set("live_risk_reduction", self._live_risk_reduction)
        self._storage.set("live_start_time", self._live_start_time)
        self._storage.set("paused", self._paused)
        self._storage.set("paper_start_time", self._paper_start_time)

        self._storage.save()

    async def run_cycle(self) -> None:
        """한 사이클을 실행한다."""
        self._cycle_count += 1
        cycle_start = time.time()
        logger.info("=" * 40)
        logger.info("사이클 #%d 시작 [%s]", self._cycle_count, self._run_mode.value)

        # 1. 시장 데이터 수집
        snapshots = await self._datafeed.get_all_snapshots()
        valid_count = sum(1 for s in snapshots.values() if s.current_price > 0)
        total_count = len(self._coins)
        logger.info("시장 데이터 수집 완료: %d/%d 코인", valid_count, total_count)

        # 네트워크 장애 감지 및 알림
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

        # 2. 장기 데이터 축적
        for symbol, snap in snapshots.items():
            if snap.candles_5m:
                self._market_store.store_candles(symbol, "5m", snap.candles_5m[-5:])
            if snap.candles_15m:
                self._market_store.store_candles(symbol, "15m", snap.candles_15m[-2:])
            if snap.candles_1h:
                self._market_store.store_candles(symbol, "1h", snap.candles_1h[-2:])
            if snap.orderbook:
                self._market_store.store_orderbook(symbol, snap.orderbook)

        # 3. 코인 프로파일러/상관관계 갱신 (24시간마다)
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

        # 4. 상태 동기화
        recon_result = await self._reconciler.reconcile(self._coins)
        if recon_result["synced"] > 0:
            logger.info("주문 동기화: %d건", recon_result["synced"])

        # 5. 리스크 상태 업데이트 (Pool 합계를 실제 equity로 사용)
        equity = (
            self._pool_manager.get_balance(Pool.CORE)
            + self._pool_manager.get_balance(Pool.ACTIVE)
            + self._pool_manager.get_balance(Pool.RESERVE)
        )
        self._dd_limits.update_equity(equity)
        self._pool_manager.update_equity(equity)
        self._risk_gate.update_state(self._pool_manager.total_exposure, equity)

        # 6. 승격/강등 확인 (기존 포지션)
        indicators_1h: dict[str, object] = {}
        regimes: dict[str, Regime] = {}
        current_prices: dict[str, float] = {}

        for symbol, snap in snapshots.items():
            current_prices[symbol] = snap.current_price
            if snap.candles_1h and len(snap.candles_1h) >= 30:
                ind_1h = compute_indicators(snap.candles_1h)
                indicators_1h[symbol] = ind_1h
                regimes[symbol] = self._rule_engine.get_regime(symbol)

        # 국면/Tier 요약 로깅 (4사이클마다)
        if self._cycle_count % 4 == 1 and regimes:
            regime_summary = {}
            for sym, reg in regimes.items():
                regime_summary.setdefault(reg.value, []).append(sym)
            tier_summary = {}
            for sym in self._coins:
                t = self._profiler.get_tier(sym)
                tier_summary.setdefault(f"T{t.tier.value}", []).append(sym)
            logger.info("국면: %s", {k: v for k, v in regime_summary.items()})
            logger.info("Tier: %s", {k: v for k, v in tier_summary.items()})

        # Core 포지션 업데이트 (강등 체크)
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

        # 6.5 CRISIS 전량 청산 (개별 실패 시 다음 사이클 재시도)
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

        # 7. 신호 생성
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

        # 7.5 Darwin Shadow 기록
        shadow_count = self._darwin.record_cycle(snapshots, signals)
        if shadow_count > 0 and self._cycle_count % 12 == 0:
            logger.info("Darwin Shadow 기록: %d건", shadow_count)

        # 8. 신호 평가 + Pool 사이징 + 주문
        for signal in signals:
            # 이미 포지션 있으면 스킵
            if signal.symbol in self._positions:
                continue

            # 상관관계 확인
            active_coins = list(self._positions.keys())
            corr_result = self._correlation.check_correlation(signal.symbol, active_coins)
            if not corr_result.allowed:
                continue

            # 리스크 체크
            check = self._risk_gate.check(
                signal,
                orderbook=snapshots[signal.symbol].orderbook,
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

            # Pool 기반 사이징 (DCA는 고정 사이징)
            if signal.strategy == Strategy.DCA:
                dca_krw = self._position_manager.calculate_dca_size()
                sizing = SizingResult(
                    pool=Pool.CORE,
                    size_krw=dca_krw,
                    detail={"dca_fixed": dca_krw},
                )
            else:
                tier_params = self._profiler.get_tier(signal.symbol)
                size_decision = self._rule_engine._decide_size(signal.strategy, signal.score)
                weekly_dd = self._dd_limits._calc_dd(self._dd_limits.state.weekly_base)
                sizing = self._position_manager.calculate_size(
                    signal=signal,
                    tier_params=tier_params,
                    size_decision=size_decision,
                    active_positions=active_coins,
                    weekly_dd_pct=weekly_dd,
                    candles_1h=snapshots[signal.symbol].candles_1h,
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

            # Pool 할당
            alloc_pool = sizing.pool if hasattr(sizing, "pool") else Pool.ACTIVE
            if not self._pool_manager.allocate(alloc_pool, sizing.size_krw):
                logger.info(
                    "Pool 할당 실패: %s (%.0f원, Active 잔액 부족)",
                    signal.symbol,
                    sizing.size_krw,
                )
                continue

            # 주문
            if signal.direction == OrderSide.BUY and signal.entry_price > 0:
                qty = normalize_qty(signal.symbol, sizing.size_krw / signal.entry_price)
                ticket = self._order_manager.create_ticket(
                    symbol=signal.symbol,
                    side=signal.direction,
                    price=signal.entry_price,
                    qty=qty,
                )
                ticket = await self._order_manager.execute_order(ticket)
                self._risk_gate.record_entry(signal.symbol)

                # 포지션 기록
                self._positions[signal.symbol] = Position(
                    symbol=signal.symbol,
                    entry_price=signal.entry_price,
                    entry_time=int(time.time() * 1000),
                    size_krw=sizing.size_krw,
                    qty=qty,
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

                # 체결 알림
                await self._notifier.send(
                    f"<b>📈 {signal.symbol} 매수 체결</b>\n"
                    f"전략: {signal.strategy.value} | {signal.score:.0f}점\n"
                    f"가격: {signal.entry_price:,.0f}원\n"
                    f"수량: {qty:.6f} | {sizing.size_krw:,.0f}원\n"
                    f"SL: {signal.stop_loss:,.0f} | TP: {signal.take_profit:,.0f}\n"
                    f"상태: {ticket.status.value}",
                    channel="trade",
                )

        # 9. 포지션 관리: 부분청산/트레일링/시간 제한
        now_ms = int(time.time() * 1000)
        for symbol in list(self._positions.keys()):
            # CRISIS 청산 실패한 포지션은 일반 exit 스킵 (exit_reason 왜곡 방지)
            if symbol in crisis_failed:
                continue
            pos = self._positions[symbol]
            price = current_prices.get(symbol, 0)
            if price <= 0:
                continue

            # ATR, BB 중간선 가져오기
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

            # 시간 제한 체크 (스캘핑)
            time_exit = self._exit_manager.check_time_exit(pos, now_ms)
            if time_exit.action != ExitAction.NONE:
                logger.info("시간 제한 청산: %s", symbol)
                await self._close_position(symbol, price, time_exit.reason.value)
                continue

            # 부분청산/트레일링/손절 통합 평가
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

        # 10. 로그: 활용률
        util = self._pool_manager.utilization_pct
        if self._cycle_count % 4 == 0:
            logger.info(
                "자금 활용률: %.1f%% | 포지션: %d개",
                util * 100,
                len(self._positions),
            )

        # 11. 일일/주간 리뷰 트리거 (KST 00:00~00:15 사이에)
        from datetime import datetime, timedelta
        from datetime import timezone as tz

        now_kst = datetime.now(tz(timedelta(hours=9)))
        if now_kst.hour == 0 and now_kst.minute < 15:
            await self._review_engine.run_daily_review(
                active_positions=len(self._positions),
                utilization_pct=util,
            )

            # DB 정리 (일 1회)
            self._journal.cleanup()
            self._market_store.cleanup()

            # LIVE 게이트 자동 검증 (PAPER 모드에서만)
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
                    strategy_expectancy={},  # 일일 리뷰에서 계산
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
            if now_kst.weekday() == 6:  # 일요일
                shadow_top3 = self._darwin.get_top_shadows(3)
                bd = self._backtest_daemon
                await self._review_engine.run_weekly_review(
                    shadow_top3=shadow_top3,
                    wf_verdict=bd.wf_result.verdict if bd.wf_result else "",
                    mc_p5=bd.mc_result.pnl_percentile_5 if bd.mc_result else 0,
                    mc_mdd=bd.mc_result.worst_mdd if bd.mc_result else 0,
                )

            # 월 1일 00:00~00:15 KST: 월간 심층 리뷰
            if now_kst.day == 1 and now_kst.hour == 0 and now_kst.minute < 15:
                await self._review_engine.run_monthly_review()

        # 12. 상태 저장
        self._save_state()

        elapsed = time.time() - cycle_start
        logger.info("사이클 #%d 완료 (%.1f초)", self._cycle_count, elapsed)

    async def _partial_close_position(
        self,
        symbol: str,
        exit_price: float,
        ratio: float,
        exit_reason: str,
    ) -> None:
        """포지션을 부분 청산한다."""
        pos = self._positions.get(symbol)
        if pos is None or ratio <= 0:
            return

        exit_qty = pos.qty * ratio
        exit_krw = pos.size_krw * ratio

        # 부분 매도 주문
        if self._run_mode == RunMode.LIVE:
            ticket = self._order_manager.create_ticket(
                symbol=symbol,
                side=OrderSide.SELL,
                price=exit_price,
                qty=exit_qty,
            )
            await self._order_manager.execute_order(ticket)

        # PnL 계산 (부분) — 진입·청산 양쪽 수수료 차감
        gross = (exit_price - pos.entry_price) * exit_qty
        entry_fee = pos.entry_price * exit_qty * 0.0025
        exit_fee = exit_price * exit_qty * 0.0025
        fee = entry_fee + exit_fee
        net = gross - fee
        self._exit_manager.add_fee(symbol, fee)

        # 포지션 차감
        pos.qty -= exit_qty
        pos.size_krw -= exit_krw

        # Pool 부분 반환
        self._pool_manager.release(pos.pool, exit_krw, pnl=net)

        # Journal 기록
        self._journal.record_execution(
            {
                "trade_id": "",
                "ticket_id": "",
                "symbol": symbol,
                "side": "ask",
                "price": exit_price,
                "qty": exit_qty,
                "filled_price": exit_price,
                "filled_qty": exit_qty,
                "status": "FILLED",
                "error_msg": f"partial_{exit_reason}_{ratio:.0%}",
            }
        )

        logger.info(
            "부분 청산: %s %.0f%% qty=%.6f @ %.0f PnL=%.0f (%s)",
            symbol,
            ratio * 100,
            exit_qty,
            exit_price,
            net,
            exit_reason,
        )

        # 남은 수량이 최소 주문금액 미만이면 전량 청산
        if pos.qty * exit_price < 5000:
            await self._close_position(symbol, exit_price, exit_reason)

    async def _close_position(self, symbol: str, exit_price: float, exit_reason: str) -> None:
        """포지션을 청산한다.

        NOTE: 부분 청산(_partial_close_position)이 선행된 경우 pos.qty와
        pos.size_krw는 이미 차감된 상태이며, cum_fee에 부분 청산 시 지불한
        수수료(진입+청산 양쪽)가 누적되어 있다.
        """
        pos = self._positions.pop(symbol, None)
        if pos is None:
            return

        # LIVE 모드: 실제 매도 주문
        if self._run_mode == RunMode.LIVE:
            ticket = self._order_manager.create_ticket(
                symbol=symbol,
                side=OrderSide.SELL,
                price=exit_price,
                qty=pos.qty,
            )
            ticket = await self._order_manager.execute_order(ticket)
            if ticket.filled_price > 0:
                exit_price = ticket.filled_price

        # PnL 계산
        gross_pnl = (exit_price - pos.entry_price) * pos.qty
        fee = pos.entry_price * pos.qty * 0.0025 + exit_price * pos.qty * 0.0025
        cum_fee = self._exit_manager.get_cumulative_fee(symbol)
        net_pnl = gross_pnl - fee  # 잔여 포지션만, 부분 청산 수수료는 이미 반영됨
        total_fee = fee + cum_fee  # 저널 기록용 전체 수수료

        # Pool 반환
        self._pool_manager.release(pos.pool, pos.size_krw, pnl=net_pnl)
        self._risk_gate.record_trade_result(is_loss=net_pnl < 0)
        self._position_manager.record_trade_result(is_loss=net_pnl < 0)

        # Journal 기록
        hold_sec = (int(time.time() * 1000) - pos.entry_time) // 1000
        self._journal.record_trade(
            {
                "symbol": symbol,
                "strategy": pos.strategy.value,
                "tier": pos.tier.value,
                "regime": pos.regime.value,
                "pool": pos.pool.value,
                "entry_price": pos.entry_price,
                "exit_price": exit_price,
                "qty": pos.qty,
                "entry_fee_krw": total_fee / 2,  # 근사 배분 (저널용)
                "exit_fee_krw": total_fee / 2,
                "gross_pnl_krw": gross_pnl,
                "net_pnl_krw": net_pnl,
                # net_pnl_pct: 퍼센트 값 (예: 2.5% → 2.5). live_gate에서는 비율(0.025)로 비교.
                "net_pnl_pct": net_pnl / pos.size_krw * 100 if pos.size_krw > 0 else 0,
                "hold_seconds": hold_sec,
                "promoted": pos.promoted,
                "entry_score": pos.entry_score,
                "entry_time": pos.entry_time,
                "exit_time": int(time.time() * 1000),
                "exit_reason": exit_reason,
            }
        )

        # 청산 후 정리
        self._exit_manager.remove_position(symbol)

        logger.info(
            "청산 완료: %s PnL=%.0f원 (%s)",
            symbol,
            net_pnl,
            exit_reason,
        )

        # 청산 알림 (실패해도 청산 로직에 영향 없음)
        try:
            pnl_pct = net_pnl / pos.size_krw * 100 if pos.size_krw > 0 else 0
            pnl_emoji = "+" if net_pnl >= 0 else "-"
            await self._notifier.send(
                f"<b>[{pnl_emoji}] {symbol} 청산</b>\n"
                f"사유: {exit_reason}\n"
                f"진입: {pos.entry_price:,.0f} → 청산: {exit_price:,.0f}\n"
                f"PnL: {net_pnl:,.0f}원 ({pnl_pct:+.2f}%)\n"
                f"보유: {hold_sec // 60}분",
                channel="trade",
            )
        except Exception:
            logger.exception("청산 알림 전송 실패: %s", symbol)

    async def run(self) -> None:
        """메인 루프를 시작한다."""
        self._running = True
        logger.info(
            "봇 시작 -모드: %s, 코인: %d개, 사이클: %d초",
            self._run_mode.value,
            len(self._coins),
            self._cycle_interval,
        )

        await self._notifier.send(
            f"<b>봇 시작</b>\n"
            f"모드: {self._run_mode.value}\n"
            f"코인: {len(self._coins)}개\n"
            f"사이클: {self._cycle_interval}초",
            channel="system",
        )

        # 디스코드 명령어 봇 시작
        guild_id_str = self._config.secrets.discord_guild_id
        if self._config.secrets.discord_bot_token and guild_id_str:
            self._discord_bot = DiscordBot(
                token=self._config.secrets.discord_bot_token,
                bot=self,
                guild_id=int(guild_id_str),
                proxy=self._config.proxy,
                admin_role=self._config.discord.admin_role,
            )
            self._discord_task = asyncio.create_task(self._discord_bot.start())
        else:
            logger.warning("디스코드 봇 토큰/guild_id 미설정 — 명령어 비활성화")

        # BacktestDaemon 백그라운드 시작
        self._daemon_task = asyncio.create_task(self._backtest_daemon.run())
        self._daemon_task.add_done_callback(_on_daemon_done)

        while self._running:
            try:
                await self.run_cycle()
            except Exception:
                logger.exception("사이클 실행 중 오류")
                await self._notifier.send(
                    f"<b>사이클 #{self._cycle_count} 오류</b>\n상세 내용은 로그 확인",
                    channel="system",
                )

            if self._running:
                await asyncio.sleep(self._cycle_interval)

    async def stop(self) -> None:
        """봇을 중지한다."""
        self._running = False
        if hasattr(self, "_discord_bot"):
            await self._discord_bot.stop()
        if hasattr(self, "_discord_task"):
            self._discord_task.cancel()
            try:
                await self._discord_task
            except asyncio.CancelledError:
                pass
        if hasattr(self, "_daemon_task"):
            self._daemon_task.cancel()
            try:
                await self._daemon_task
            except asyncio.CancelledError:
                pass
        await self._backtest_daemon.stop()
        self._save_state()
        await self._client.close()
        self._market_store.close()
        self._journal.close()
        logger.info("봇 종료")
        await self._notifier.send("<b>봇 종료</b>", channel="system")
        await self._notifier.close()

    async def run_once(self) -> None:
        """사이클을 1회 실행하고 종료한다 (테스트용)."""
        try:
            await self.run_cycle()
        finally:
            await self._client.close()
            self._market_store.close()
            self._journal.close()
            await self._notifier.close()
