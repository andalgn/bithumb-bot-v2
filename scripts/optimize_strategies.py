"""전략 파라미터 최적화 — SL/TP 그리드 서치 + 필터 완화 통합.

각 전략의 SL/TP 파라미터를 그리드 서치하고,
최적 전략 파라미터 + 필터 완화를 조합하여 최종 추천 설정을 출력한다.
"""
# ruff: noqa: E402

from __future__ import annotations

import asyncio
import copy
import logging
import math
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np

from app.config import load_config
from app.data_types import Candle, MarketSnapshot, Regime, Strategy, OrderSide, parse_raw_candles
from market.bithumb_api import BithumbClient
from market.market_store import MarketStore
from strategy.coin_profiler import CoinProfiler
from strategy.rule_engine import RuleEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)
logging.getLogger("strategy.rule_engine").setLevel(logging.WARNING)
logging.getLogger("strategy.coin_profiler").setLevel(logging.WARNING)

KST = timezone(timedelta(hours=9))
FEE_RATE = 0.0025
SLIPPAGE_RATE = 0.001


# ═══════════════════════════════════════════
# 데이터 타입
# ═══════════════════════════════════════════


@dataclass
class BacktestResult:
    """백테스트 결과."""

    label: str
    trades: int = 0
    wins: int = 0
    total_pnl: float = 0.0
    gross_wins: float = 0.0
    gross_losses: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    params: dict = field(default_factory=dict)


@dataclass
class Trade:
    """거래 기록."""

    symbol: str
    strategy: str
    entry_price: float
    exit_price: float
    entry_idx: int
    exit_idx: int
    stop_loss: float
    take_profit: float
    pnl: float = 0.0
    pnl_pct: float = 0.0


# ═══════════════════════════════════════════
# 파라미터 그리드 정의
# ═══════════════════════════════════════════

# 전략별 SL/TP 그리드
GRIDS = {
    "trend_follow": {
        "sl_mult": [1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0],
        "tp_rr": [1.5, 2.0, 2.5, 3.0, 3.5, 4.0],
    },
    "mean_reversion": {
        "sl_mult": [1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 7.0],
        "tp_rr": [1.0, 1.5, 2.0, 2.5, 3.0],
    },
    "dca": {
        "sl_pct": [0.02, 0.03, 0.04, 0.05, 0.06, 0.08],
        "tp_pct": [0.02, 0.03, 0.04, 0.05, 0.06, 0.08],
    },
    "breakout": {
        "sl_mult": [1.0, 1.5, 2.0, 2.5, 3.0],
        "tp_rr": [2.0, 2.5, 3.0, 3.5, 4.0, 5.0],
    },
}


# ═══════════════════════════════════════════
# 백테스트 엔진 (단일 전략 + 파라미터 변경)
# ═══════════════════════════════════════════


def run_backtest(
    store: MarketStore,
    coins: list[str],
    engine: RuleEngine,
    profiler: CoinProfiler,
    target_strategy: str | None = None,
) -> BacktestResult:
    """전체 백테스트 실행."""

    all_trades: list[Trade] = []
    candles_1h_map: dict[str, list[Candle]] = {}
    for coin in coins:
        c = store.get_candles(coin, "1h", limit=10000)
        if c:
            candles_1h_map[coin] = c
    profiler.classify_all(candles_1h_map)

    for coin in coins:
        candles_15m = store.get_candles(coin, "15m", limit=10000)
        candles_1h = store.get_candles(coin, "1h", limit=10000)

        if len(candles_15m) < 200 or len(candles_1h) < 50:
            continue

        window = 200
        step = 4
        position: Trade | None = None

        for i in range(window, len(candles_15m) - step, step):
            slice_15m = candles_15m[i - window: i]
            current_ts = slice_15m[-1].timestamp
            current_price = slice_15m[-1].close

            sync_1h = [c for c in candles_1h if c.timestamp <= current_ts]
            if len(sync_1h) < 50:
                continue
            sync_1h = sync_1h[-200:]

            # 포지션 체크
            if position is not None:
                future = candles_15m[i: i + step]
                hit_sl = any(c.low <= position.stop_loss for c in future)
                hit_tp = any(c.high >= position.take_profit for c in future)

                if hit_sl or hit_tp:
                    exit_price = position.stop_loss if hit_sl else position.take_profit
                    entry_adj = position.entry_price * (1 + SLIPPAGE_RATE)
                    exit_adj = exit_price * (1 - SLIPPAGE_RATE)
                    fee = entry_adj * FEE_RATE + exit_adj * FEE_RATE
                    pnl = (exit_adj - entry_adj) - fee
                    pnl_pct = pnl / entry_adj * 100 if entry_adj > 0 else 0

                    position.exit_price = exit_price
                    position.exit_idx = i
                    position.pnl = pnl
                    position.pnl_pct = pnl_pct
                    all_trades.append(position)
                    position = None
                continue

            # 신호
            snap = MarketSnapshot(
                symbol=coin,
                current_price=current_price,
                candles_15m=slice_15m,
                candles_1h=sync_1h,
            )
            signals = engine.generate_signals({coin: snap})
            if not signals:
                continue

            sig = signals[0]

            # 타겟 전략 필터
            if target_strategy and sig.strategy.value != target_strategy:
                continue

            position = Trade(
                symbol=coin,
                strategy=sig.strategy.value,
                entry_price=sig.entry_price,
                exit_price=0,
                entry_idx=i,
                exit_idx=0,
                stop_loss=sig.stop_loss,
                take_profit=sig.take_profit,
            )

    # 결과 계산
    result = BacktestResult(label="")
    result.trades = len(all_trades)
    if not all_trades:
        return result

    wins = [t for t in all_trades if t.pnl > 0]
    losses = [t for t in all_trades if t.pnl <= 0]
    result.wins = len(wins)
    result.total_pnl = sum(t.pnl for t in all_trades)
    result.gross_wins = sum(t.pnl for t in wins)
    result.gross_losses = abs(sum(t.pnl for t in losses))
    result.win_rate = len(wins) / len(all_trades) if all_trades else 0
    result.profit_factor = result.gross_wins / result.gross_losses if result.gross_losses > 0 else 10.0
    result.expectancy = result.total_pnl / len(all_trades) if all_trades else 0
    result.avg_win = result.gross_wins / len(wins) if wins else 0
    result.avg_loss = -result.gross_losses / len(losses) if losses else 0

    # MDD
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in sorted(all_trades, key=lambda x: x.entry_idx):
        equity += t.pnl
        peak = max(peak, equity)
        dd = (peak - equity) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)
    result.max_drawdown = max_dd

    return result


# ═══════════════════════════════════════════
# 전략별 그리드 서치
# ═══════════════════════════════════════════


def optimize_strategy(
    strategy_name: str,
    store: MarketStore,
    coins: list[str],
    base_config: object,
) -> list[BacktestResult]:
    """단일 전략의 SL/TP 그리드 서치."""
    grid = GRIDS.get(strategy_name, {})
    if not grid:
        return []

    results: list[BacktestResult] = []
    profiler = CoinProfiler(tier1_atr_max=0.009, tier3_atr_min=0.014)

    if strategy_name == "dca":
        sl_values = grid["sl_pct"]
        tp_values = grid["tp_pct"]
        param_keys = ("sl_pct", "tp_pct")
    else:
        sl_values = grid["sl_mult"]
        tp_values = grid["tp_rr"]
        param_keys = ("sl_mult", "tp_rr")

    total = len(sl_values) * len(tp_values)
    count = 0

    for sl_val in sl_values:
        for tp_val in tp_values:
            count += 1

            # DCA에서 tp <= sl 은 건너뛰기 (손익비 역전 방지)
            if strategy_name == "dca" and tp_val <= sl_val * 0.8:
                continue

            # 전략 파라미터 복제 + 수정
            sp = copy.deepcopy(base_config.strategy_params)
            strat_sp = sp.get(strategy_name, {})

            if strategy_name == "dca":
                strat_sp["sl_pct"] = sl_val
                strat_sp["tp_pct"] = tp_val
                # regime_override도 같은 비율 적용
                for _regime, override in strat_sp.get("regime_override", {}).items():
                    override["sl_pct"] = sl_val
                    override["tp_pct"] = tp_val
            else:
                strat_sp["sl_mult"] = sl_val
                strat_sp["tp_rr"] = tp_val
                # Tier별 파라미터도 동일 적용
                for tier_key in ("tier1", "tier2", "tier3"):
                    if tier_key in strat_sp:
                        strat_sp[tier_key]["sl_mult"] = sl_val
                        strat_sp[tier_key]["tp_rr"] = tp_val
                # regime_override
                for _regime, override in strat_sp.get("regime_override", {}).items():
                    override["sl_mult"] = sl_val
                    override["tp_rr"] = tp_val

            sp[strategy_name] = strat_sp

            engine = RuleEngine(
                profiler=profiler,
                score_cutoff=base_config.score_cutoff,
                regime_config=base_config.regime,
                execution_config=base_config.execution,
                strategy_params=sp,
            )

            result = run_backtest(store, coins, engine, profiler, target_strategy=strategy_name)
            result.label = f"{strategy_name} {param_keys[0]}={sl_val} {param_keys[1]}={tp_val}"
            result.params = {param_keys[0]: sl_val, param_keys[1]: tp_val}

            results.append(result)

            if count % 10 == 0:
                logger.info("  [%s] %d/%d 완료", strategy_name, count, total)

    return results


# ═══════════════════════════════════════════
# 필터 완화 + 최적 전략 통합 백테스트
# ═══════════════════════════════════════════


def run_integrated_test(
    store: MarketStore,
    coins: list[str],
    base_config: object,
    best_params: dict[str, dict],
) -> BacktestResult:
    """최적 전략 파라미터로 전체 통합 백테스트."""
    profiler = CoinProfiler(tier1_atr_max=0.009, tier3_atr_min=0.014)

    sp = copy.deepcopy(base_config.strategy_params)
    for strat_name, params in best_params.items():
        strat_sp = sp.get(strat_name, {})
        for key, val in params.items():
            strat_sp[key] = val
            # Tier별/regime별에도 반영
            for tier_key in ("tier1", "tier2", "tier3"):
                if tier_key in strat_sp:
                    strat_sp[tier_key][key] = val
            for _regime, override in strat_sp.get("regime_override", {}).items():
                override[key] = val
        sp[strat_name] = strat_sp

    engine = RuleEngine(
        profiler=profiler,
        score_cutoff=base_config.score_cutoff,
        regime_config=base_config.regime,
        execution_config=base_config.execution,
        strategy_params=sp,
    )

    result = run_backtest(store, coins, engine, profiler)
    result.label = "통합 (최적 파라미터)"
    return result


# ═══════════════════════════════════════════
# 결과 출력
# ═══════════════════════════════════════════


def print_top_results(strategy_name: str, results: list[BacktestResult], top_n: int = 10) -> None:
    """상위 N개 결과 출력."""
    # PF > 0.5이고 거래 10건 이상인 것만 필터
    valid = [r for r in results if r.trades >= 10 and r.profit_factor > 0.5]
    if not valid:
        print(f"\n  [{strategy_name}] 유효한 결과 없음 (거래 10건 이상 필요)")
        return

    # PF 기준 정렬
    valid.sort(key=lambda r: r.profit_factor, reverse=True)
    top = valid[:top_n]

    print(f"\n{'='*90}")
    print(f"  [{strategy_name}] 상위 {min(top_n, len(top))}개 파라미터 조합")
    print(f"{'='*90}")

    header = f"{'파라미터':<35} {'거래':>5} {'승률':>7} {'PF':>7} {'MDD':>7} {'Expect':>10} {'총PnL':>12}"
    print(header)
    print("-" * 90)

    for r in top:
        print(
            f"{r.label:<35} {r.trades:>5} {r.win_rate*100:>6.1f}% {r.profit_factor:>6.2f} "
            f"{r.max_drawdown*100:>6.1f}% {r.expectancy:>+10,.0f} {r.total_pnl:>+12,.0f}"
        )

    # 추천 (PF > 1.0이고 거래 20건 이상)
    profitable = [r for r in valid if r.profit_factor > 1.0 and r.trades >= 20]
    if profitable:
        best = max(profitable, key=lambda r: r.profit_factor * math.sqrt(r.trades))
        print(f"\n  ★ 추천: {best.label}")
        print(f"    PF={best.profit_factor:.2f}, WR={best.win_rate*100:.1f}%, "
              f"{best.trades}건, PnL={best.total_pnl:+,.0f}")
    else:
        # PF가 가장 높은 것이라도 표시
        best = max(valid, key=lambda r: r.profit_factor)
        print(f"\n  ⚠ PF > 1.0 + 20건 이상 조합 없음. 최선: {best.label}")
        print(f"    PF={best.profit_factor:.2f}, WR={best.win_rate*100:.1f}%, "
              f"{best.trades}건")


def print_current_vs_best(
    strategy_name: str,
    current: BacktestResult,
    best: BacktestResult | None,
) -> None:
    """현행 vs 최적 비교."""
    if not best:
        return
    print(f"\n  [{strategy_name}] 현행 vs 최적 비교:")
    print(f"    {'':>20} {'현행':>12} {'최적':>12} {'변화':>12}")
    print(f"    {'거래 수':>20} {current.trades:>12} {best.trades:>12}")
    print(f"    {'승률':>20} {current.win_rate*100:>11.1f}% {best.win_rate*100:>11.1f}% {(best.win_rate-current.win_rate)*100:>+11.1f}%")
    print(f"    {'PF':>20} {current.profit_factor:>12.2f} {best.profit_factor:>12.2f} {best.profit_factor-current.profit_factor:>+12.2f}")
    print(f"    {'MDD':>20} {current.max_drawdown*100:>11.1f}% {best.max_drawdown*100:>11.1f}%")
    print(f"    {'총 PnL':>20} {current.total_pnl:>+12,.0f} {best.total_pnl:>+12,.0f} {best.total_pnl-current.total_pnl:>+12,.0f}")


# ═══════════════════════════════════════════
# 데이터 다운로드
# ═══════════════════════════════════════════


async def download_fresh_data(coins: list[str], config: object) -> None:
    """최신 데이터 다운로드."""
    client = BithumbClient(
        api_key=config.secrets.bithumb_api_key,
        api_secret=config.secrets.bithumb_api_secret,
        base_url=config.secrets.bithumb_api_url or config.bithumb.base_url,
        proxy=config.proxy,
        verify_ssl=not bool(config.proxy),
        public_rate_limit=config.bithumb.public_rate_limit,
        private_rate_limit=config.bithumb.private_rate_limit,
    )
    store = MarketStore(db_path="data/market_data.db")
    try:
        for coin in coins:
            for interval in ["15m", "1h"]:
                try:
                    raw = await client.get_candlestick(coin, interval)
                    candles = parse_raw_candles(raw)
                    stored = store.store_candles(coin, interval, candles)
                    logger.info("%s %s: %d봉 → %d건 저장", coin, interval, len(candles), stored)
                except Exception:
                    logger.exception("%s %s 다운로드 실패", coin, interval)
                await asyncio.sleep(0.2)
    finally:
        await client.close()
        store.close()


# ═══════════════════════════════════════════
# 메인
# ═══════════════════════════════════════════


async def main() -> None:
    """메인."""
    config = load_config()
    coins = config.coins
    strategies = ["trend_follow", "mean_reversion", "dca", "breakout"]

    logger.info("전략 파라미터 최적화 시작: %d개 코인, %d개 전략", len(coins), len(strategies))

    # 1. 데이터
    logger.info("=" * 50)
    logger.info("1단계: 데이터 다운로드")
    await download_fresh_data(coins, config)

    store = MarketStore(db_path="data/market_data.db")

    # 2. 현행 파라미터 기준선
    logger.info("=" * 50)
    logger.info("2단계: 현행 파라미터 기준선 백테스트")

    profiler = CoinProfiler(tier1_atr_max=0.009, tier3_atr_min=0.014)
    current_engine = RuleEngine(
        profiler=profiler,
        score_cutoff=config.score_cutoff,
        regime_config=config.regime,
        execution_config=config.execution,
        strategy_params=config.strategy_params,
    )

    current_results: dict[str, BacktestResult] = {}
    for strat in strategies:
        r = run_backtest(store, coins, current_engine, profiler, target_strategy=strat)
        r.label = f"{strat} (현행)"
        current_results[strat] = r
        logger.info("  %s 현행: %d건, PF=%.2f, WR=%.1f%%", strat, r.trades, r.profit_factor, r.win_rate*100)

    # 전체 통합 현행
    current_all = run_backtest(store, coins, current_engine, profiler)
    current_all.label = "전체 (현행)"
    logger.info("  전체 현행: %d건, PF=%.2f, WR=%.1f%%", current_all.trades, current_all.profit_factor, current_all.win_rate*100)

    # 3. 전략별 그리드 서치
    logger.info("=" * 50)
    logger.info("3단계: 전략별 SL/TP 그리드 서치")

    best_params: dict[str, dict] = {}
    best_results: dict[str, BacktestResult | None] = {}

    for strat in strategies:
        logger.info("  [%s] 그리드 서치 시작...", strat)
        start = time.time()
        results = optimize_strategy(strat, store, coins, config)
        elapsed = time.time() - start
        logger.info("  [%s] %d개 조합 테스트, %.1f초", strat, len(results), elapsed)

        print_top_results(strat, results)

        # 최적 파라미터 선택
        valid = [r for r in results if r.trades >= 10 and r.profit_factor > 0.5]
        if valid:
            # PF × sqrt(trades)로 안정성 고려
            profitable = [r for r in valid if r.profit_factor >= 1.0]
            if profitable:
                best = max(profitable, key=lambda r: r.profit_factor * math.sqrt(r.trades))
            else:
                best = max(valid, key=lambda r: r.profit_factor)
            best_params[strat] = best.params
            best_results[strat] = best
        else:
            best_results[strat] = None

    # 4. 현행 vs 최적 비교
    print("\n" + "=" * 90)
    print("  현행 vs 최적 비교")
    print("=" * 90)

    for strat in strategies:
        print_current_vs_best(strat, current_results[strat], best_results.get(strat))

    # 5. 통합 백테스트 (최적 파라미터)
    if best_params:
        logger.info("=" * 50)
        logger.info("4단계: 최적 파라미터 통합 백테스트")

        integrated = run_integrated_test(store, coins, config, best_params)
        logger.info("  통합: %d건, PF=%.2f, WR=%.1f%%", integrated.trades, integrated.profit_factor, integrated.win_rate*100)

        print("\n" + "=" * 90)
        print("  통합 결과: 현행 전체 vs 최적 전체")
        print("=" * 90)
        print(f"    {'':>20} {'현행':>12} {'최적':>12}")
        print(f"    {'거래 수':>20} {current_all.trades:>12} {integrated.trades:>12}")
        print(f"    {'승률':>20} {current_all.win_rate*100:>11.1f}% {integrated.win_rate*100:>11.1f}%")
        print(f"    {'PF':>20} {current_all.profit_factor:>12.2f} {integrated.profit_factor:>12.2f}")
        print(f"    {'MDD':>20} {current_all.max_drawdown*100:>11.1f}% {integrated.max_drawdown*100:>11.1f}%")
        print(f"    {'Expectancy':>20} {current_all.expectancy:>+12,.0f} {integrated.expectancy:>+12,.0f}")
        print(f"    {'총 PnL':>20} {current_all.total_pnl:>+12,.0f} {integrated.total_pnl:>+12,.0f}")

    # 6. 최종 추천 설정 출력
    print("\n" + "=" * 90)
    print("  최종 추천 config.yaml 변경사항")
    print("=" * 90)

    for strat, params in best_params.items():
        print(f"\n  {strat}:")
        for key, val in params.items():
            current_sp = config.strategy_params.get(strat, {})
            old_val = current_sp.get(key, "?")
            print(f"    {key}: {old_val} → {val}")

    store.close()


if __name__ == "__main__":
    asyncio.run(main())
