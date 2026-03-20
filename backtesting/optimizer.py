"""파라미터 최적화 엔진.

2단계 최적화: 진입 시점 캐싱 → SL/TP 파라미터 리플레이.
Grid Search + Walk-Forward IS/OOS 검증.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

from app.data_types import Candle, MarketSnapshot
from strategy.coin_profiler import CoinProfiler
from strategy.indicators import compute_indicators
from strategy.rule_engine import RuleEngine

logger = logging.getLogger(__name__)

FEE_RATE = 0.0025
SLIPPAGE_RATE = 0.001


@dataclass
class OptResult:
    """단일 최적화 실행 결과."""

    params: dict[str, float] = field(default_factory=dict)
    strategy: str = ""
    trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    max_drawdown: float = 0.0
    sharpe: float = 0.0
    total_pnl: float = 0.0
    is_oos: bool = False


@dataclass
class EntryPoint:
    """캐싱된 진입 시점."""

    coin: str
    idx: int
    price: float
    atr: float
    score: float
    strategy: str
    candle_data: list[Candle]  # 진입 이후 캔들 (exit 판정용)


class ParameterOptimizer:
    """전략 파라미터 최적화기 (2단계 캐싱 방식)."""

    def __init__(self, coins: list[str], config: object | None = None) -> None:
        """초기화."""
        self._coins = coins
        self._config = config
        self._profiler = CoinProfiler(tier1_atr_max=0.03, tier3_atr_min=0.07)
        self._profiled = False
        self._entry_cache: dict[str, list[EntryPoint]] = {}

    def _ensure_profiled(self, candles_1h: dict[str, list[Candle]]) -> None:
        """Tier 분류를 최초 1회만 실행한다."""
        if not self._profiled and candles_1h:
            self._profiler.classify_all(candles_1h)
            self._profiled = True

    # ═══════════════════════════════════════════
    # Phase 0: 진입 시점 스캔 + 캐싱 (1회)
    # ═══════════════════════════════════════════

    def scan_entries(
        self,
        strategy_name: str,
        candles_15m: dict[str, list[Candle]],
        candles_1h: dict[str, list[Candle]],
        min_score: float = 0.0,
    ) -> list[EntryPoint]:
        """전략의 모든 진입 시점을 스캔하여 캐싱한다.

        이 함수는 전략당 1회만 호출. compute_indicators 비용을 여기서 지불.
        """
        cache_key = strategy_name
        if cache_key in self._entry_cache:
            return self._entry_cache[cache_key]

        self._ensure_profiled(candles_1h)
        engine = RuleEngine(
            profiler=self._profiler,
            score_cutoff=self._config.score_cutoff if self._config else None,
            regime_config=self._config.regime if self._config else None,
            execution_config=self._config.execution if self._config else None,
        )

        entries: list[EntryPoint] = []
        window = 200
        step = 4

        for coin in self._coins:
            c15 = candles_15m.get(coin, [])
            c1h = candles_1h.get(coin, [])
            if len(c15) < 250 or len(c1h) < 50:
                continue

            logger.info("[scan] %s %s: %d봉", strategy_name, coin, len(c15))

            for i in range(window, len(c15) - step, step):
                slice_15m = c15[i - window: i]
                current_ts = slice_15m[-1].timestamp
                current_price = slice_15m[-1].close

                sync_1h = [c for c in c1h if c.timestamp <= current_ts]
                if len(sync_1h) < 50:
                    continue
                sync_1h = sync_1h[-200:]

                snap = MarketSnapshot(
                    symbol=coin,
                    current_price=current_price,
                    candles_15m=slice_15m,
                    candles_1h=sync_1h,
                )
                signals = engine.generate_signals({coin: snap})

                for sig in signals:
                    if sig.strategy.value != strategy_name:
                        continue
                    if sig.score < min_score:
                        continue

                    # ATR 계산
                    ind = compute_indicators(slice_15m)
                    atr_arr = ind.atr[~np.isnan(ind.atr)]
                    atr_val = float(atr_arr[-1]) if len(atr_arr) > 0 else current_price * 0.02

                    # 진입 이후 캔들 저장 (최대 96봉 = 24시간)
                    future_end = min(i + 96, len(c15))
                    entries.append(EntryPoint(
                        coin=coin,
                        idx=i,
                        price=current_price,
                        atr=atr_val,
                        score=sig.score,
                        strategy=strategy_name,
                        candle_data=c15[i: future_end],
                    ))
                    break  # 1시점 1시그널

        self._entry_cache[cache_key] = entries
        logger.info(
            "[scan] %s 완료: %d개 진입 시점 캐싱", strategy_name, len(entries),
        )
        return entries

    # ═══════════════════════════════════════════
    # Phase 1: SL/TP 파라미터 리플레이 (N회, 초고속)
    # ═══════════════════════════════════════════

    def replay_with_params(
        self,
        strategy_name: str,
        params: dict[str, float],
        entries: list[EntryPoint],
    ) -> OptResult:
        """캐싱된 진입 시점에서 SL/TP만 변경하여 시뮬레이션한다."""
        cutoff = params.get("cutoff_full", 0)
        pnls: list[float] = []

        for ep in entries:
            if cutoff > 0 and ep.score < cutoff:
                continue

            sl, tp = self._calc_sl_tp(strategy_name, params, ep.price, ep.atr)
            if sl <= 0 or tp <= 0:
                continue

            # 진입 이후 캔들에서 SL/TP 도달 확인
            pnl = self._simulate_exit(ep.price, sl, tp, ep.candle_data)
            if pnl is not None:
                pnls.append(pnl)

        return self._calc_stats(strategy_name, params, pnls)

    @staticmethod
    def _calc_sl_tp(
        strategy: str, params: dict[str, float],
        price: float, atr: float,
    ) -> tuple[float, float]:
        """파라미터 기반 SL/TP를 계산한다."""
        max_sl = price * 0.025  # 기본 SL cap 2.5%

        if strategy == "scalping":
            sl = price * (1 - params.get("sl_pct", 0.008))
            tp = price * (1 + params.get("tp_pct", 0.015))
        else:
            sl_m = params.get("sl_mult", 2.0)
            tp_r = params.get("tp_rr", 2.5)
            sl_dist = min(atr * sl_m, max_sl)
            sl = price - sl_dist
            tp = price + sl_dist * tp_r

        return sl, tp

    @staticmethod
    def _simulate_exit(
        entry: float, sl: float, tp: float, future_candles: list[Candle],
    ) -> float | None:
        """진입 이후 캔들에서 SL/TP 도달 시 PnL을 반환한다."""
        for candle in future_candles:
            hit_sl = candle.low <= sl
            hit_tp = candle.high >= tp
            if hit_sl or hit_tp:
                exit_p = sl if hit_sl else tp
                entry_adj = entry * (1 + SLIPPAGE_RATE)
                exit_adj = exit_p * (1 - SLIPPAGE_RATE)
                gross = (exit_adj - entry_adj) / entry_adj
                return gross - FEE_RATE * 2
        return None  # 미도달 (타임아웃)

    # ═══════════════════════════════════════════
    # 통합 최적화 (scan + replay)
    # ═══════════════════════════════════════════

    def run_single(
        self,
        strategy_name: str,
        params: dict[str, float],
        candles_15m: dict[str, list[Candle]],
        candles_1h: dict[str, list[Candle]],
    ) -> OptResult:
        """단일 파라미터셋으로 백테스트 (캐싱 활용)."""
        entries = self.scan_entries(strategy_name, candles_15m, candles_1h)
        return self.replay_with_params(strategy_name, params, entries)

    def optimize(
        self,
        strategy: str,
        grid: list[dict[str, float]],
        candles_15m: dict[str, list[Candle]],
        candles_1h: dict[str, list[Candle]],
        in_sample_ratio: float = 0.7,
        top_n: int = 5,
    ) -> list[OptResult]:
        """Grid Search + Walk-Forward OOS 검증."""
        # 데이터 분할
        is_15m: dict[str, list[Candle]] = {}
        oos_15m: dict[str, list[Candle]] = {}
        is_1h: dict[str, list[Candle]] = {}
        oos_1h: dict[str, list[Candle]] = {}

        for coin in self._coins:
            c15 = candles_15m.get(coin, [])
            if not c15:
                continue
            split_idx = int(len(c15) * in_sample_ratio)
            is_15m[coin] = c15[:split_idx]
            oos_15m[coin] = c15[max(0, split_idx - 200):]
            c1h = candles_1h.get(coin, [])
            ts_cut = c15[split_idx - 1].timestamp if split_idx > 0 else 0
            is_1h[coin] = [c for c in c1h if c.timestamp <= ts_cut]
            oos_1h[coin] = c1h

        # Phase 0: 진입 시점 스캔 (IS + OOS 각 1회)
        self._entry_cache = {}  # 캐시 리셋
        is_entries = self.scan_entries(
            strategy, is_15m, is_1h, min_score=0,
        )
        self._entry_cache = {}
        oos_entries = self.scan_entries(
            strategy, oos_15m, oos_1h, min_score=0,
        )

        logger.info(
            "[%s] 진입 캐싱 완료: IS=%d, OOS=%d",
            strategy, len(is_entries), len(oos_entries),
        )

        # Phase 1: IS Grid Search (초고속 리플레이)
        logger.info("[%s] Grid Search: %d 조합", strategy, len(grid))
        is_results: list[OptResult] = []
        for params in grid:
            r = self.replay_with_params(strategy, params, is_entries)
            is_results.append(r)

        # Top N by PF
        is_results.sort(key=lambda r: r.profit_factor, reverse=True)
        top = is_results[:top_n]

        # Phase 2: OOS 검증 (초고속 리플레이)
        logger.info("[%s] OOS 검증: 상위 %d개", strategy, len(top))
        oos_results: list[OptResult] = []
        for is_r in top:
            oos_r = self.replay_with_params(strategy, is_r.params, oos_entries)
            oos_r.is_oos = True
            oos_results.append(oos_r)

            if oos_r.trades < 10:
                logger.warning(
                    "[%s] OOS 거래 %d건 — 통계적 유의성 부족",
                    strategy, oos_r.trades,
                )
            if is_r.sharpe > 0:
                diff = abs(is_r.sharpe - oos_r.sharpe) / is_r.sharpe
                if diff > 0.5:
                    logger.warning(
                        "[%s] 과적합: IS=%.2f → OOS=%.2f (%.0f%%)",
                        strategy, is_r.sharpe, oos_r.sharpe, diff * 100,
                    )

        return oos_results

    @staticmethod
    def _calc_stats(
        strategy: str, params: dict[str, float], pnls: list[float],
    ) -> OptResult:
        """PnL 리스트에서 통계를 계산한다."""
        n = len(pnls)
        if n == 0:
            return OptResult(params=params, strategy=strategy)

        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        total = sum(pnls)
        wr = len(wins) / n
        loss_sum = abs(sum(losses)) if losses else 0
        pf = sum(wins) / loss_sum if loss_sum > 0 else 10.0
        exp = total / n

        arr = np.array(pnls)
        std = float(np.std(arr))
        sharpe = float(np.mean(arr) / std * np.sqrt(252)) if std > 0 else 0.0

        equity = np.cumsum(pnls)
        peak = np.maximum.accumulate(equity)
        dd = peak - equity
        mdd = float(np.max(dd / (peak + 1e-10))) if len(dd) > 0 else 0.0

        return OptResult(
            params=params, strategy=strategy, trades=n,
            win_rate=wr, profit_factor=pf, expectancy=exp,
            max_drawdown=mdd, sharpe=sharpe, total_pnl=total,
        )

    @staticmethod
    def _calc_trade_pnl(entry: float, exit_price: float) -> float:
        """수수료+슬리피지 포함 PnL 비율."""
        entry_adj = entry * (1 + SLIPPAGE_RATE)
        exit_adj = exit_price * (1 - SLIPPAGE_RATE)
        gross = (exit_adj - entry_adj) / entry_adj
        return gross - FEE_RATE * 2
