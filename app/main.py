"""오케스트레이터 -15분 주기 메인 루프.

DRY/PAPER/LIVE 모드. 전체 사이클 try-except + 텔레그램 알림.
Phase 3: Pool 기반 사이징 + 승격/강등.
"""

from __future__ import annotations

import asyncio
import logging
import time

from app.config import AppConfig
from app.data_types import OrderSide, Pool, Position, Regime, RunMode
from app.journal import Journal
from app.notify import TelegramNotifier
from app.storage import StateStorage
from backtesting.daemon import BacktestDaemon
from execution.order_manager import OrderManager
from execution.partial_exit import ExitAction, PartialExitManager
from execution.quarantine import QuarantineManager
from execution.reconciler import Reconciler
from market.bithumb_api import BithumbClient
from market.datafeed import DataFeed
from market.market_store import MarketStore
from risk.dd_limits import DDLimits
from risk.risk_gate import RiskGate
from strategy.coin_profiler import CoinProfiler
from strategy.correlation_monitor import CorrelationMonitor
from strategy.darwin_engine import DarwinEngine
from strategy.indicators import compute_indicators
from strategy.pool_manager import PoolManager
from strategy.position_manager import PositionManager
from strategy.promotion_manager import PromotionManager
from strategy.review_engine import ReviewEngine
from strategy.rule_engine import RuleEngine

logger = logging.getLogger(__name__)


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

        # 컴포넌트 초기화
        self._client = BithumbClient(
            api_key=config.secrets.bithumb_api_key,
            api_secret=config.secrets.bithumb_api_secret,
            base_url=config.secrets.bithumb_api_url or config.bithumb.base_url,
            public_rate_limit=config.bithumb.public_rate_limit,
            private_rate_limit=config.bithumb.private_rate_limit,
        )

        self._notifier = TelegramNotifier(
            token=config.secrets.telegram_bot_token,
            chat_id=config.secrets.telegram_chat_id,
            timeout_sec=config.telegram.timeout_sec,
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

        self._profiler = CoinProfiler(tier1_atr_max=0.03, tier3_atr_min=0.07)

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
        )

        # Phase 3: Pool + Position + Promotion
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
        self._darwin = DarwinEngine(population_size=20)
        self._backtest_daemon = BacktestDaemon(
            journal=self._journal, notifier=self._notifier,
        )

        # Phase 6: ReviewEngine
        self._review_engine = ReviewEngine(
            journal=self._journal,
            notifier=self._notifier,
            deepseek_api_key=config.secrets.deepseek_api_key,
        )

        # 포지션 관리
        self._positions: dict[str, Position] = {}

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

    def _save_state(self) -> None:
        """현재 상태를 저장한다."""
        self._storage.set("dd_limits", self._dd_limits.dump_state())
        self._storage.set("risk_gate", self._risk_gate.dump_state())
        self._storage.set("pool_manager", self._pool_manager.dump_state())
        self._storage.set("cycle_count", self._cycle_count)
        self._storage.set("last_cycle_at", int(time.time()))
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
        logger.info("시장 데이터 수집 완료: %d/%d 코인", valid_count, len(self._coins))

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
                sym: snap.candles_1h
                for sym, snap in snapshots.items()
                if snap.candles_1h
            }
            self._profiler.classify_all(candles_1h_map)

        if self._correlation.needs_update():
            candles_1h_map = {
                sym: snap.candles_1h
                for sym, snap in snapshots.items()
                if snap.candles_1h
            }
            self._correlation.update(candles_1h_map)

        # 4. 상태 동기화
        recon_result = await self._reconciler.reconcile(self._coins)
        if recon_result["synced"] > 0:
            logger.info("주문 동기화: %d건", recon_result["synced"])

        # 5. 리스크 상태 업데이트
        equity = self._dd_limits.state.current_equity
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

        # Core 포지션 업데이트 (강등 체크)
        demoted = self._promotion_manager.update_core_positions(
            current_prices, indicators_1h, regimes,
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

        # 7. 신호 생성
        signals = self._rule_engine.generate_signals(snapshots)

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
            corr_result = self._correlation.check_correlation(
                signal.symbol, active_coins
            )
            if not corr_result.allowed:
                continue

            # 리스크 체크
            check = self._risk_gate.check(
                signal,
                orderbook=snapshots[signal.symbol].orderbook,
                order_krw=self._config.sizing.active_min_krw,
            )

            self._journal.record_signal({
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
            })

            if not check.allowed:
                logger.info(
                    "신호 거부: %s %s [%.0f점] -%s",
                    signal.direction.value, signal.symbol,
                    signal.score, check.reason,
                )
                continue

            # Pool 기반 사이징
            tier_params = self._profiler.get_tier(signal.symbol)
            size_decision = self._rule_engine._decide_size(
                signal.strategy, signal.score
            )
            weekly_dd = self._dd_limits._calc_dd(self._dd_limits.state.weekly_base)
            sizing = self._position_manager.calculate_size(
                signal=signal,
                tier_params=tier_params,
                size_decision=size_decision,
                active_positions=active_coins,
                weekly_dd_pct=weekly_dd,
                candles_1h=snapshots[signal.symbol].candles_1h,
            )

            if sizing.size_krw <= 0:
                continue

            # Pool 할당
            if not self._pool_manager.allocate(Pool.ACTIVE, sizing.size_krw):
                continue

            # 주문
            if signal.direction == OrderSide.BUY and signal.entry_price > 0:
                qty = sizing.size_krw / signal.entry_price
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
                    pool=Pool.ACTIVE,
                    tier=signal.tier,
                    regime=signal.regime,
                    entry_score=signal.score,
                    signal_price=signal.entry_price,
                )
                self._exit_manager.init_position(signal.symbol)

                logger.info(
                    "주문 %s: %s %s %.4f @ %.0f [%s %.0f점] "
                    "사이즈=%.0f원 → %s",
                    ticket.ticket_id, signal.direction.value,
                    signal.symbol, qty, signal.entry_price,
                    signal.strategy.value, signal.score,
                    sizing.size_krw, ticket.status.value,
                )

        # 9. 포지션 관리: 부분청산/트레일링/시간 제한
        now_ms = int(time.time() * 1000)
        for symbol in list(self._positions.keys()):
            pos = self._positions[symbol]
            price = current_prices.get(symbol, 0)
            if price <= 0:
                continue

            # ATR, BB 중간선 가져오기
            atr_val = 0.0
            bb_mid = 0.0
            ind = indicators_1h.get(symbol)
            if ind and hasattr(ind, "atr") and len(ind.atr) > 0:
                valid_atr = ind.atr[~__import__("numpy").isnan(ind.atr)]
                atr_val = float(valid_atr[-1]) if len(valid_atr) > 0 else 0
            if ind and hasattr(ind, "bb") and ind.bb is not None:
                bb_arr = ind.bb.middle
                valid_bb = bb_arr[~__import__("numpy").isnan(bb_arr)]
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
                self._close_position(symbol, price, time_exit.reason.value)
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
                    symbol, decision.action.value, price,
                )
                self._close_position(symbol, price, decision.reason.value)
            else:
                logger.info(
                    "부분 청산: %s %.0f%% [%s] @ %.0f",
                    symbol, decision.exit_ratio * 100,
                    decision.detail, price,
                )

        # 10. 로그: 활용률
        util = self._pool_manager.utilization_pct
        if self._cycle_count % 4 == 0:
            logger.info(
                "자금 활용률: %.1f%% | 포지션: %d개",
                util * 100, len(self._positions),
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
            if now_kst.weekday() == 6:  # 일요일
                shadow_top3 = self._darwin.get_top_shadows(3)
                bd = self._backtest_daemon
                await self._review_engine.run_weekly_review(
                    shadow_top3=shadow_top3,
                    wf_verdict=bd.wf_result.verdict if bd.wf_result else "",
                    mc_p5=bd.mc_result.pnl_percentile_5 if bd.mc_result else 0,
                    mc_mdd=bd.mc_result.worst_mdd if bd.mc_result else 0,
                )

        # 12. 상태 저장
        self._save_state()

        elapsed = time.time() - cycle_start
        logger.info("사이클 #%d 완료 (%.1f초)", self._cycle_count, elapsed)

    def _close_position(
        self, symbol: str, exit_price: float, exit_reason: str
    ) -> None:
        """포지션을 청산한다."""
        pos = self._positions.pop(symbol, None)
        if pos is None:
            return

        # PnL 계산
        gross_pnl = (exit_price - pos.entry_price) * pos.qty
        fee = pos.entry_price * pos.qty * 0.0025 + exit_price * pos.qty * 0.0025
        cum_fee = self._exit_manager.get_cumulative_fee(symbol)
        net_pnl = gross_pnl - fee - cum_fee

        # Pool 반환
        self._pool_manager.release(pos.pool, pos.size_krw, pnl=net_pnl)
        self._risk_gate.record_trade_result(is_loss=net_pnl < 0)
        self._position_manager.record_trade_result(is_loss=net_pnl < 0)

        # Journal 기록
        hold_sec = (int(time.time() * 1000) - pos.entry_time) // 1000
        self._journal.record_trade({
            "symbol": symbol,
            "strategy": pos.strategy.value,
            "tier": pos.tier.value,
            "regime": pos.regime.value,
            "pool": pos.pool.value,
            "entry_price": pos.entry_price,
            "exit_price": exit_price,
            "qty": pos.qty,
            "entry_fee_krw": pos.entry_price * pos.qty * 0.0025,
            "exit_fee_krw": exit_price * pos.qty * 0.0025,
            "gross_pnl_krw": gross_pnl,
            "net_pnl_krw": net_pnl,
            "net_pnl_pct": net_pnl / pos.size_krw * 100 if pos.size_krw > 0 else 0,
            "hold_seconds": hold_sec,
            "promoted": pos.promoted,
            "entry_score": pos.entry_score,
            "entry_time": pos.entry_time,
            "exit_time": int(time.time() * 1000),
            "exit_reason": exit_reason,
        })

        # 청산 후 정리
        self._exit_manager.remove_position(symbol)

        logger.info(
            "청산 완료: %s PnL=%.0f원 (%s)",
            symbol, net_pnl, exit_reason,
        )

    async def run(self) -> None:
        """메인 루프를 시작한다."""
        self._running = True
        logger.info(
            "봇 시작 -모드: %s, 코인: %d개, 사이클: %d초",
            self._run_mode.value, len(self._coins), self._cycle_interval,
        )

        await self._notifier.send(
            f"<b>봇 시작</b>\n"
            f"모드: {self._run_mode.value}\n"
            f"코인: {len(self._coins)}개\n"
            f"사이클: {self._cycle_interval}초"
        )

        # BacktestDaemon 백그라운드 시작
        asyncio.create_task(self._backtest_daemon.run())

        while self._running:
            try:
                await self.run_cycle()
            except Exception:
                logger.exception("사이클 실행 중 오류")
                await self._notifier.send(
                    f"<b>사이클 #{self._cycle_count} 오류</b>\n"
                    f"상세 내용은 로그 확인"
                )

            if self._running:
                await asyncio.sleep(self._cycle_interval)

    async def stop(self) -> None:
        """봇을 중지한다."""
        self._running = False
        await self._backtest_daemon.stop()
        self._save_state()
        await self._client.close()
        self._market_store.close()
        self._journal.close()
        logger.info("봇 종료")
        await self._notifier.send("<b>봇 종료</b>")

    async def run_once(self) -> None:
        """사이클을 1회 실행하고 종료한다 (테스트용)."""
        try:
            await self.run_cycle()
        finally:
            await self._client.close()
            self._market_store.close()
            self._journal.close()
