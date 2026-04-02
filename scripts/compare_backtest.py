"""현재 설정 vs 완화 설정 A/B 백테스트 비교.

A: 현재 config.yaml 설정 (baseline)
B: probe_min 하향 + spread_limit tier3 완화
"""

from __future__ import annotations

import logging
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import ExecutionConfig, ScoreCutoffConfig, ScoreCutoffGroup, load_config
from market.market_store import MarketStore
from scripts.download_and_backtest import BacktestTrade, StrategyStats, run_backtest
from strategy.coin_profiler import CoinProfiler
from strategy.rule_engine import RuleEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logging.getLogger("strategy.rule_engine").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def make_engine(config, score_cutoff=None, execution=None) -> tuple[RuleEngine, CoinProfiler]:
    """RuleEngine + CoinProfiler 생성."""
    profiler = CoinProfiler(tier1_atr_max=0.009, tier3_atr_min=0.014)
    engine = RuleEngine(
        profiler=profiler,
        score_cutoff=score_cutoff or config.score_cutoff,
        regime_config=config.regime,
        execution_config=execution or config.execution,
        strategy_params=config.strategy_params,
    )
    return engine, profiler


def summarize(
    label: str,
    all_trades: list[BacktestTrade],
    stats: dict[str, StrategyStats],
) -> list[str]:
    """결과를 텍스트로 요약."""
    lines = [f"\n{'=' * 50}", f"  {label}", f"{'=' * 50}"]

    total = len(all_trades)
    wins = sum(1 for t in all_trades if t.pnl > 0)
    pnl = sum(t.pnl for t in all_trades)
    wr = wins / total * 100 if total > 0 else 0

    lines.append(f"  총 거래: {total}건 | 승률: {wr:.1f}% | 총 PnL: {pnl:,.0f}원")
    lines.append("")

    strat_names = {
        "trend_follow": "A 추세추종",
        "mean_reversion": "B 반전포착",
        "breakout": "C 브레이크아웃",
        "scalping": "D 스캘핑",
        "dca": "E DCA",
    }

    lines.append(f"  {'전략':<14} {'건수':>5} {'승률':>7} {'PF':>6} {'MDD':>7} {'PnL':>12}")
    lines.append(f"  {'-' * 55}")

    for key in ["trend_follow", "mean_reversion", "breakout", "scalping", "dca"]:
        s = stats.get(key)
        name = strat_names.get(key, key)
        if not s or s.trades == 0:
            lines.append(f"  {name:<14} {'—':>5}")
            continue
        lines.append(
            f"  {name:<14} {s.trades:>5} {s.win_rate * 100:>6.1f}% {s.profit_factor:>6.2f}"
            f" {s.max_drawdown * 100:>6.1f}% {s.total_pnl:>11,.0f}원"
        )

    # 코인별 요약
    lines.append("")
    coin_data: dict[str, list[BacktestTrade]] = defaultdict(list)
    for t in all_trades:
        coin_data[t.symbol].append(t)

    lines.append(f"  {'코인':<8} {'건수':>5} {'승률':>7} {'PnL':>12}")
    lines.append(f"  {'-' * 35}")
    for sym in sorted(coin_data.keys()):
        trades = coin_data[sym]
        w = sum(1 for t in trades if t.pnl > 0)
        p = sum(t.pnl for t in trades)
        lines.append(f"  {sym:<8} {len(trades):>5} {w / len(trades) * 100:>6.1f}% {p:>11,.0f}원")

    return lines


def main() -> None:
    """A/B 비교 백테스트 실행."""
    config = load_config()
    store = MarketStore(db_path="data/market_data.db")
    coins = config.coins

    results: dict[str, tuple[list[BacktestTrade], dict[str, StrategyStats]]] = {}

    # ── A: 현재 설정 (baseline) ──
    logger.info("=" * 50)
    logger.info("[A] 현재 설정으로 백테스트 시작")
    engine_a, prof_a = make_engine(config)
    t0 = time.time()
    trades_a, stats_a = run_backtest(store, coins, engine_a, prof_a)
    logger.info("[A] 완료: %d건, %.1f초", len(trades_a), time.time() - t0)
    results["A"] = (trades_a, stats_a)

    # ── B: probe_min 55 + spread tier3 0.005 ──
    logger.info("=" * 50)
    logger.info("[B] 완화 설정으로 백테스트 시작")
    score_b = ScoreCutoffConfig(
        group1=ScoreCutoffGroup(full=75, probe_min=55, probe_max=74),
        group2=ScoreCutoffGroup(full=80, probe_min=60, probe_max=79),
        group3=ScoreCutoffGroup(full=75, probe_min=63, probe_max=74),
        plus10_mult=config.score_cutoff.plus10_mult,
        plus20_mult=config.score_cutoff.plus20_mult,
    )
    exec_b = ExecutionConfig(
        order_timeout_sec=config.execution.order_timeout_sec,
        retry_count=config.execution.retry_count,
        retry_base_ms=config.execution.retry_base_ms,
        price_deviation_pct=config.execution.price_deviation_pct,
        slippage_tier1=config.execution.slippage_tier1,
        slippage_tier2=config.execution.slippage_tier2,
        slippage_tier3=config.execution.slippage_tier3,
        spread_limit_tier1=config.execution.spread_limit_tier1,
        spread_limit_tier2=config.execution.spread_limit_tier2,
        spread_limit_tier3=0.005,  # 0.0035 → 0.005
        orderbook_depth_mult_tier1=config.execution.orderbook_depth_mult_tier1,
        orderbook_depth_mult_tier2=config.execution.orderbook_depth_mult_tier2,
        orderbook_depth_mult_tier3=config.execution.orderbook_depth_mult_tier3,
    )
    engine_b, prof_b = make_engine(config, score_cutoff=score_b, execution=exec_b)
    t0 = time.time()
    trades_b, stats_b = run_backtest(store, coins, engine_b, prof_b)
    logger.info("[B] 완료: %d건, %.1f초", len(trades_b), time.time() - t0)
    results["B"] = (trades_b, stats_b)

    # ── 비교 출력 ──
    output = []
    output.append("\n" + "=" * 60)
    output.append("  A/B 백테스트 비교 결과")
    output.append("=" * 60)
    output.append("")
    output.append("  [A] 현재 설정")
    output.append("      group1.probe_min=60, spread_tier3=0.0035")
    output.append("  [B] 완화 설정")
    output.append("      group1.probe_min=55, spread_tier3=0.005")

    for label, (trades, stats) in [
        ("[A] 현재 설정 (baseline)", results["A"]),
        ("[B] 완화 설정 (probe↓ + spread↑)", results["B"]),
    ]:
        output.extend(summarize(label, trades, stats))

    # 델타 요약
    ta, sa = results["A"]
    tb, sb = results["B"]
    output.append(f"\n{'=' * 50}")
    output.append("  변화량 (B - A)")
    output.append(f"{'=' * 50}")
    output.append(f"  거래 수: {len(ta)} → {len(tb)} ({len(tb) - len(ta):+d})")
    pnl_a = sum(t.pnl for t in ta)
    pnl_b = sum(t.pnl for t in tb)
    output.append(f"  총 PnL: {pnl_a:,.0f} → {pnl_b:,.0f} ({pnl_b - pnl_a:+,.0f}원)")
    wr_a = sum(1 for t in ta if t.pnl > 0) / len(ta) * 100 if ta else 0
    wr_b = sum(1 for t in tb if t.pnl > 0) / len(tb) * 100 if tb else 0
    output.append(f"  승률: {wr_a:.1f}% → {wr_b:.1f}% ({wr_b - wr_a:+.1f}%p)")

    text = "\n".join(output)
    sys.stdout.buffer.write((text + "\n").encode("utf-8"))

    store.close()


if __name__ == "__main__":
    main()
