"""파라미터 최적화 엔진.

Grid Search + Walk-Forward IS/OOS 검증.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

from app.data_types import Candle, MarketSnapshot
from strategy.coin_profiler import CoinProfiler
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
    is_oos: bool = False  # True = Out-of-Sample result


class ParameterOptimizer:
    """전략 파라미터 최적화기."""

    def __init__(self, coins: list[str], config: object | None = None) -> None:
        """초기화.

        Args:
            coins: 대상 코인 목록.
            config: AppConfig 인스턴스 (선택).
        """
        self._coins = coins
        self._config = config
        self._profiler = CoinProfiler(tier1_atr_max=0.03, tier3_atr_min=0.07)

    def run_single(
        self,
        strategy_name: str,
        params: dict[str, float],
        candles_15m: dict[str, list[Candle]],
        candles_1h: dict[str, list[Candle]],
    ) -> OptResult:
        """단일 파라미터셋으로 특정 전략만 백테스트.

        Args:
            strategy_name: 전략 이름 (예: "trend_follow").
            params: SL/TP 파라미터 딕셔너리.
            candles_15m: 코인별 15분 캔들.
            candles_1h: 코인별 1시간 캔들.

        Returns:
            OptResult 통계 결과.
        """
        # Build engine with param overrides
        strategy_params = {strategy_name: params}
        # Use cutoff from params if provided, else default
        cutoff_full = params.get("cutoff_full")

        # Classify coins
        if candles_1h:
            self._profiler.classify_all(candles_1h)

        engine = RuleEngine(
            profiler=self._profiler,
            score_cutoff=self._config.score_cutoff if self._config else None,
            regime_config=self._config.regime if self._config else None,
            execution_config=self._config.execution if self._config else None,
            strategy_params=strategy_params,
        )

        all_pnls: list[float] = []
        for coin in self._coins:
            c15 = candles_15m.get(coin, [])
            c1h = candles_1h.get(coin, [])
            if len(c15) < 250 or len(c1h) < 50:
                continue
            pnls = self._backtest_coin(
                engine, coin, strategy_name, params, c15, c1h, cutoff_full,
            )
            all_pnls.extend(pnls)

        return self._calc_stats(strategy_name, params, all_pnls)

    def _backtest_coin(
        self,
        engine: RuleEngine,
        coin: str,
        strategy_name: str,
        params: dict[str, float],
        candles_15m: list[Candle],
        candles_1h: list[Candle],
        cutoff_override: float | None = None,
    ) -> list[float]:
        """코인별 슬라이딩 윈도우 백테스트를 실행한다.

        Args:
            engine: RuleEngine 인스턴스.
            coin: 코인 심볼.
            strategy_name: 전략 이름.
            params: 파라미터 딕셔너리.
            candles_15m: 15분 캔들 리스트.
            candles_1h: 1시간 캔들 리스트.
            cutoff_override: 점수 컷오프 오버라이드.

        Returns:
            PnL 비율 리스트.
        """
        window = 200
        step = 4
        position: dict[str, float] | None = None
        pnls: list[float] = []

        for i in range(window, len(candles_15m) - step, step):
            slice_15m = candles_15m[i - window: i]
            current_ts = slice_15m[-1].timestamp
            current_price = slice_15m[-1].close

            sync_1h = [c for c in candles_1h if c.timestamp <= current_ts]
            if len(sync_1h) < 50:
                continue
            sync_1h = sync_1h[-200:]

            # Position check
            if position is not None:
                future = candles_15m[i: i + step]
                hit_sl = any(c.low <= position["sl"] for c in future)
                hit_tp = any(c.high >= position["tp"] for c in future)
                if hit_sl or hit_tp:
                    exit_p = position["sl"] if hit_sl else position["tp"]
                    pnl = self._calc_trade_pnl(position["entry"], exit_p)
                    pnls.append(pnl)
                    position = None
                continue

            # Generate signals
            snap = MarketSnapshot(
                symbol=coin,
                current_price=current_price,
                candles_15m=slice_15m,
                candles_1h=sync_1h,
            )
            signals = engine.generate_signals({coin: snap})

            # Filter by target strategy
            for sig in signals:
                if sig.strategy.value != strategy_name:
                    continue
                # Apply cutoff override if set
                if cutoff_override and sig.score < cutoff_override:
                    continue
                position = {
                    "entry": sig.entry_price,
                    "sl": sig.stop_loss,
                    "tp": sig.take_profit,
                }
                break

        return pnls

    @staticmethod
    def _calc_trade_pnl(entry: float, exit_price: float) -> float:
        """수수료+슬리피지 포함 PnL 비율을 계산한다.

        Args:
            entry: 진입가.
            exit_price: 청산가.

        Returns:
            PnL 비율 (소수).
        """
        entry_adj = entry * (1 + SLIPPAGE_RATE)
        exit_adj = exit_price * (1 - SLIPPAGE_RATE)
        gross = (exit_adj - entry_adj) / entry_adj
        fee = FEE_RATE * 2  # 매수+매도
        return gross - fee

    @staticmethod
    def _calc_stats(
        strategy: str, params: dict[str, float], pnls: list[float],
    ) -> OptResult:
        """PnL 리스트에서 통계를 계산한다.

        Args:
            strategy: 전략 이름.
            params: 파라미터 딕셔너리.
            pnls: PnL 비율 리스트.

        Returns:
            OptResult 통계 결과.
        """
        n = len(pnls)
        if n == 0:
            return OptResult(params=params, strategy=strategy)

        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        total = sum(pnls)
        wr = len(wins) / n
        pf = sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else 10.0
        exp = total / n

        # Sharpe
        arr = np.array(pnls)
        std = float(np.std(arr))
        sharpe = float(np.mean(arr) / std * np.sqrt(252)) if std > 0 else 0.0

        # MDD
        equity = np.cumsum(pnls)
        peak = np.maximum.accumulate(equity)
        dd = peak - equity
        mdd = float(np.max(dd / (peak + 1e-10))) if len(dd) > 0 else 0.0

        return OptResult(
            params=params,
            strategy=strategy,
            trades=n,
            win_rate=wr,
            profit_factor=pf,
            expectancy=exp,
            max_drawdown=mdd,
            sharpe=sharpe,
            total_pnl=total,
        )

    def optimize(
        self,
        strategy: str,
        grid: list[dict[str, float]],
        candles_15m: dict[str, list[Candle]],
        candles_1h: dict[str, list[Candle]],
        in_sample_ratio: float = 0.7,
        top_n: int = 5,
    ) -> list[OptResult]:
        """Grid Search + Walk-Forward OOS 검증을 실행한다.

        Args:
            strategy: 전략 이름.
            grid: 파라미터 조합 리스트.
            candles_15m: 코인별 15분 캔들.
            candles_1h: 코인별 1시간 캔들.
            in_sample_ratio: IS 데이터 비율 (기본 0.7).
            top_n: OOS 검증 대상 상위 N개 (기본 5).

        Returns:
            OOS 검증 결과 리스트.
        """
        # Data split (all coins)
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

        # Phase 1: In-Sample Grid Search
        logger.info("[%s] Grid Search: %d 조합", strategy, len(grid))
        is_results: list[OptResult] = []
        for idx, params in enumerate(grid):
            r = self.run_single(strategy, params, is_15m, is_1h)
            is_results.append(r)
            if (idx + 1) % 50 == 0:
                logger.info("[%s] %d/%d 완료", strategy, idx + 1, len(grid))

        # Top N by Profit Factor
        is_results.sort(key=lambda r: r.profit_factor, reverse=True)
        top = is_results[:top_n]

        # Phase 2: Out-of-Sample validation
        logger.info("[%s] OOS 검증: 상위 %d개", strategy, len(top))
        oos_results: list[OptResult] = []
        for is_r in top:
            oos_r = self.run_single(strategy, is_r.params, oos_15m, oos_1h)
            oos_r.is_oos = True
            oos_results.append(oos_r)

            # OOS trade count warning
            if oos_r.trades < 10:
                logger.warning(
                    "[%s] OOS 거래 %d건 — 통계적 유의성 부족",
                    strategy, oos_r.trades,
                )

            # Overfit detection
            if is_r.sharpe > 0:
                diff = abs(is_r.sharpe - oos_r.sharpe) / is_r.sharpe
                if diff > 0.5:
                    logger.warning(
                        "[%s] 과적합 감지: IS=%.2f → OOS=%.2f (차이 %.0f%%)",
                        strategy, is_r.sharpe, oos_r.sharpe, diff * 100,
                    )

        return oos_results
