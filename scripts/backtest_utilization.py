"""자금 활용률 개선 백테스트 — 3가지 개선안 비교.

1. 포지션 사이징 전환: 많은 소액 → 적은 적정액
2. RSI 필터 3단계 완화: 극값 → 범위 기반
3. Scalping 활성화: 거래 빈도 증대

각 개선안을 개별 + 조합으로 테스트하여 최적 설정을 찾는다.
"""
# ruff: noqa: E402
from __future__ import annotations

import asyncio
import copy
import logging
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np

from app.config import load_config
from app.data_types import Candle, MarketSnapshot, Strategy
from market.market_store import MarketStore
from strategy.coin_profiler import CoinProfiler
from strategy.rule_engine import RuleEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
logging.getLogger("strategy.rule_engine").setLevel(logging.WARNING)
logging.getLogger("strategy.coin_profiler").setLevel(logging.WARNING)

FEE_RATE = 0.0025
SLIPPAGE_RATE = 0.001
INITIAL_CAPITAL = 930_000


@dataclass
class Result:
    label: str
    trades: int = 0
    wins: int = 0
    total_pnl: float = 0.0
    gross_wins: float = 0.0
    gross_losses: float = 0.0
    max_drawdown: float = 0.0
    strategies: dict = field(default_factory=dict)

    @property
    def win_rate(self) -> float:
        return self.wins / self.trades if self.trades > 0 else 0

    @property
    def profit_factor(self) -> float:
        return self.gross_wins / self.gross_losses if self.gross_losses > 0 else 10.0

    @property
    def daily_trades(self) -> float:
        return self.trades / 40 if self.trades > 0 else 0  # ~40일 데이터


def run_backtest(
    store: MarketStore,
    coins: list[str],
    engine: RuleEngine,
    profiler: CoinProfiler,
    label: str,
    max_concurrent: int = 5,
    position_size_krw: float = 50_000,
) -> Result:
    """포트폴리오 시뮬레이션 백테스트."""
    result = Result(label=label)
    candles_1h_map: dict[str, list[Candle]] = {}
    for coin in coins:
        c = store.get_candles(coin, "1h", limit=10000)
        if c:
            candles_1h_map[coin] = c
    profiler.classify_all(candles_1h_map)

    positions: dict[str, dict] = {}  # symbol -> {entry, sl, tp, strategy}
    equity = float(INITIAL_CAPITAL)
    peak_equity = equity
    max_dd = 0.0
    strat_stats: dict[str, dict] = defaultdict(lambda: {"count": 0, "wins": 0, "pnl": 0.0})

    for coin in coins:
        c15 = store.get_candles(coin, "15m", limit=10000)
        c1h = store.get_candles(coin, "1h", limit=10000)
        if len(c15) < 200 or len(c1h) < 50:
            continue

        window = 200
        step = 4

        for i in range(window, len(c15) - step, step):
            s15 = c15[i - window: i]
            ts = s15[-1].timestamp
            price = s15[-1].close
            s1h = [c for c in c1h if c.timestamp <= ts]
            if len(s1h) < 50:
                continue
            s1h = s1h[-200:]

            # 포지션 체크
            if coin in positions:
                pos = positions[coin]
                future = c15[i: i + step]
                hit_sl = any(c.low <= pos["sl"] for c in future)
                hit_tp = any(c.high >= pos["tp"] for c in future)

                if hit_sl or hit_tp:
                    ep = pos["sl"] if hit_sl else pos["tp"]
                    ea = pos["entry"] * (1 + SLIPPAGE_RATE)
                    xa = ep * (1 - SLIPPAGE_RATE)
                    fee = ea * FEE_RATE + xa * FEE_RATE
                    pnl_pct = (xa - ea - fee) / ea
                    pnl_krw = position_size_krw * pnl_pct

                    result.trades += 1
                    result.total_pnl += pnl_krw
                    if pnl_krw > 0:
                        result.wins += 1
                        result.gross_wins += pnl_krw
                    else:
                        result.gross_losses += abs(pnl_krw)

                    strat_stats[pos["strategy"]]["count"] += 1
                    strat_stats[pos["strategy"]]["pnl"] += pnl_krw
                    if pnl_krw > 0:
                        strat_stats[pos["strategy"]]["wins"] += 1

                    equity += pnl_krw
                    peak_equity = max(peak_equity, equity)
                    dd = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0
                    max_dd = max(max_dd, dd)

                    del positions[coin]
                continue

            # 진입
            if len(positions) >= max_concurrent:
                continue

            snap = MarketSnapshot(
                symbol=coin, current_price=price,
                candles_15m=s15, candles_1h=s1h,
            )
            signals = engine.generate_signals({coin: snap})
            if signals:
                sig = signals[0]
                positions[coin] = {
                    "entry": sig.entry_price,
                    "sl": sig.stop_loss,
                    "tp": sig.take_profit,
                    "strategy": sig.strategy.value,
                }

    result.max_drawdown = max_dd
    result.strategies = dict(strat_stats)
    return result


def make_engine(
    config,
    profiler: CoinProfiler,
    *,
    rsi_multi_level: bool = False,
    scalping_enabled: bool = False,
    strategy_params_override: dict | None = None,
) -> RuleEngine:
    """파라미터를 조정한 RuleEngine을 생성한다."""
    sp = copy.deepcopy(config.strategy_params)
    if strategy_params_override:
        for k, v in strategy_params_override.items():
            if k in sp:
                sp[k].update(v)

    if scalping_enabled and "scalping" in sp:
        sp["scalping"]["enabled"] = True

    engine = RuleEngine(
        profiler=profiler,
        score_cutoff=config.score_cutoff,
        regime_config=config.regime,
        execution_config=config.execution,
        strategy_params=sp,
    )

    # RSI 다단계 필터 적용 (원본 scorer 패치)
    if rsi_multi_level:
        _patch_rsi_multi_level(engine)

    # Scalping 국면 매핑 추가
    if scalping_enabled:
        _patch_scalping_regime(engine)

    return engine


def _patch_rsi_multi_level(engine: RuleEngine) -> None:
    """RSI 필터를 3단계로 패치한다. strategy_scorer.score_strategy_b를 래핑."""
    scorer = engine._strategy_scorer
    original_fn = scorer.score_strategy_b

    def patched_score_b(ind_15m, candles_15m):
        from strategy.strategy_scorer import ScoreResult
        result = original_fn(ind_15m, candles_15m)
        # RSI 범위 확장
        rsi_arr = ind_15m.rsi
        valid = rsi_arr[~np.isnan(rsi_arr)]
        if len(valid) >= 2 and result.detail.get("rsi_bounce", 0) < 15:
            curr = valid[-1]
            bonus = 0.0
            if curr < 30 or curr > 70:
                bonus = 30.0
            elif 30 <= curr < 35 or 65 < curr <= 70:
                bonus = 21.0
            elif 35 <= curr < 40 or 60 < curr <= 65:
                bonus = 12.0
            old_bounce = result.detail.get("rsi_bounce", 0)
            if bonus > old_bounce:
                diff = bonus - old_bounce
                result = ScoreResult(
                    strategy=result.strategy,
                    score=result.score + diff,
                    detail={**result.detail, "rsi_bounce": bonus},
                )
        return result

    scorer.score_strategy_b = patched_score_b


def _patch_scalping_regime(engine: RuleEngine) -> None:
    """SCALPING을 STRONG_UP/WEAK_UP/RANGE 국면에 추가한다."""
    from app.data_types import Regime
    from strategy.rule_engine import REGIME_STRATEGY_MAP

    for regime in [Regime.STRONG_UP, Regime.WEAK_UP, Regime.RANGE]:
        if Strategy.SCALPING not in REGIME_STRATEGY_MAP[regime]:
            REGIME_STRATEGY_MAP[regime].append(Strategy.SCALPING)


async def main() -> None:
    config = load_config()
    coins = config.coins
    store = MarketStore(db_path="data/market_data.db")
    profiler = CoinProfiler(tier1_atr_max=0.009, tier3_atr_min=0.014)

    scenarios = []

    # A: 현행 (baseline)
    logger.info("A: 현행 baseline")
    eng_a = make_engine(config, profiler)
    r_a = run_backtest(store, coins, eng_a, profiler,
                       "A_현행", max_concurrent=8, position_size_krw=50_000)
    scenarios.append(r_a)

    # B: 포지션 크기 증가 (3슬롯 × 150K)
    logger.info("B: 적은 포지션 × 큰 금액")
    eng_b = make_engine(config, profiler)
    r_b = run_backtest(store, coins, eng_b, profiler,
                       "B_대형포지션", max_concurrent=3, position_size_krw=150_000)
    scenarios.append(r_b)

    # C: RSI 3단계 완화
    logger.info("C: RSI 다단계")
    eng_c = make_engine(config, profiler, rsi_multi_level=True)
    r_c = run_backtest(store, coins, eng_c, profiler,
                       "C_RSI확장", max_concurrent=8, position_size_krw=50_000)
    scenarios.append(r_c)

    # D: Scalping 활성화
    logger.info("D: Scalping 활성화")
    eng_d = make_engine(config, profiler, scalping_enabled=True)
    r_d = run_backtest(store, coins, eng_d, profiler,
                       "D_스캘핑", max_concurrent=8, position_size_krw=50_000)
    scenarios.append(r_d)

    # E: RSI확장 + Scalping (신호 최대화)
    logger.info("E: RSI + Scalping")
    eng_e = make_engine(config, profiler, rsi_multi_level=True, scalping_enabled=True)
    r_e = run_backtest(store, coins, eng_e, profiler,
                       "E_신호최대", max_concurrent=8, position_size_krw=50_000)
    scenarios.append(r_e)

    # F: 최적 조합 (RSI+Scalping + 적정 포지션)
    logger.info("F: 최적 조합")
    eng_f = make_engine(config, profiler, rsi_multi_level=True, scalping_enabled=True)
    r_f = run_backtest(store, coins, eng_f, profiler,
                       "F_최적조합", max_concurrent=5, position_size_krw=100_000)
    scenarios.append(r_f)

    store.close()

    # 결과 출력
    print("\n" + "=" * 100)
    print("  자금 활용률 개선 백테스트 결과 (40일 데이터)")
    print("=" * 100)

    header = f"{'시나리오':<16} {'거래':>5} {'일평균':>6} {'승률':>7} {'PF':>7} {'MDD':>7} {'총PnL':>12} {'포지션':>8}"
    print(header)
    print("-" * 100)

    for r in scenarios:
        pos_info = r.label.split("_")[1] if "_" in r.label else ""
        print(
            f"{r.label:<16} {r.trades:>5} {r.daily_trades:>6.1f} "
            f"{r.win_rate*100:>6.1f}% {r.profit_factor:>6.2f} "
            f"{r.max_drawdown*100:>6.1f}% {r.total_pnl:>+12,.0f}"
        )

    # 전략별 세부
    print("\n" + "=" * 100)
    print("  전략별 세부")
    print("=" * 100)

    for r in scenarios:
        if not r.strategies:
            print(f"\n  [{r.label}] 거래 없음")
            continue
        print(f"\n  [{r.label}]")
        for strat, s in sorted(r.strategies.items()):
            wr = s["wins"] / s["count"] * 100 if s["count"] > 0 else 0
            print(f"    {strat:<18} {s['count']:>3}건 WR={wr:>5.1f}% PnL={s['pnl']:>+10,.0f}")

    # 추천
    print("\n" + "=" * 100)
    valid = [r for r in scenarios if r.trades >= 20 and r.profit_factor > 1.0]
    if valid:
        best = max(valid, key=lambda r: r.total_pnl)
        print(f"  ★ 추천: {best.label}")
        print(f"    거래 {best.trades}건, PF {best.profit_factor:.2f}, "
              f"PnL {best.total_pnl:+,.0f}, 일평균 {best.daily_trades:.1f}건")
    else:
        # PnL 최대 기준
        best = max(scenarios, key=lambda r: r.total_pnl)
        print(f"  ⚠ PF>1 + 20건 이상 없음. 최선: {best.label}")
        print(f"    거래 {best.trades}건, PF {best.profit_factor:.2f}, PnL {best.total_pnl:+,.0f}")
    print("=" * 100)


if __name__ == "__main__":
    asyncio.run(main())
