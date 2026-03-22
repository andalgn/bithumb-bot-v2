"""90일 캔들 데이터 다운로드 + 전략 파이프라인 백테스트.

1. 빗썸 API에서 10개 코인의 15M/1H 캔들 데이터 다운로드
2. market_data.db에 저장
3. 전체 전략 파이프라인으로 백테스트 실행
4. 전략별 성과 지표 계산 (승률, Expectancy, MDD, Profit Factor)
5. 텔레그램으로 결과 전송
"""
# ruff: noqa: E402

from __future__ import annotations

import asyncio
import logging
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# 프로젝트 루트 추가
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import load_config
from app.data_types import Candle, MarketSnapshot, Regime, Strategy, parse_raw_candles
from app.notify import TelegramNotifier
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


# ═══════════════════════════════════════════
# 1. 데이터 다운로드
# ═══════════════════════════════════════════


async def download_candles(
    client: BithumbClient,
    store: MarketStore,
    coins: list[str],
) -> dict[str, dict[str, int]]:
    """빗썸 API에서 캔들 데이터를 다운로드한다."""
    result: dict[str, dict[str, int]] = {}

    for coin in coins:
        result[coin] = {}
        for interval in ["15m", "1h"]:
            try:
                raw = await client.get_candlestick(coin, interval)
                candles = parse_raw_candles(raw)

                stored = store.store_candles(coin, interval, candles)
                result[coin][interval] = len(candles)
                logger.info(
                    "%s %s: %d봉 다운로드 → %d건 저장",
                    coin,
                    interval,
                    len(candles),
                    stored,
                )
            except Exception:
                logger.exception("%s %s 다운로드 실패", coin, interval)
                result[coin][interval] = 0

            await asyncio.sleep(0.15)

    return result


# ═══════════════════════════════════════════
# 2. 백테스트 엔진
# ═══════════════════════════════════════════


@dataclass
class BacktestTrade:
    """백테스트 거래 기록."""

    symbol: str
    strategy: Strategy
    regime: Regime
    entry_price: float
    exit_price: float
    entry_idx: int
    exit_idx: int
    stop_loss: float
    take_profit: float
    pnl: float = 0.0
    pnl_pct: float = 0.0
    hold_bars: int = 0


@dataclass
class StrategyStats:
    """전략별 통계."""

    trades: int = 0
    wins: int = 0
    total_pnl: float = 0.0
    gross_wins: float = 0.0
    gross_losses: float = 0.0
    max_drawdown: float = 0.0
    equity_curve: list[float] = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        """승률."""
        return self.wins / self.trades if self.trades > 0 else 0.0

    @property
    def expectancy(self) -> float:
        """Expectancy (거래당 평균 수익)."""
        return self.total_pnl / self.trades if self.trades > 0 else 0.0

    @property
    def profit_factor(self) -> float:
        """Profit Factor."""
        if self.gross_losses > 0:
            return self.gross_wins / self.gross_losses
        return 10.0


FEE_RATE = 0.0025  # 편도 0.25%
SLIPPAGE_RATE = 0.001  # 편도 0.1%


def run_backtest(
    store: MarketStore,
    coins: list[str],
    engine: RuleEngine,
    profiler: CoinProfiler,
) -> tuple[list[BacktestTrade], dict[str, StrategyStats]]:
    """전체 전략 파이프라인 백테스트를 실행한다."""

    all_trades: list[BacktestTrade] = []
    strategy_stats: dict[str, StrategyStats] = defaultdict(StrategyStats)

    # 1H 캔들 기반 프로파일링
    candles_1h_map: dict[str, list[Candle]] = {}
    for coin in coins:
        c = store.get_candles(coin, "1h", limit=5000)
        if c:
            candles_1h_map[coin] = c
    profiler.classify_all(candles_1h_map)

    for coin in coins:
        candles_15m = store.get_candles(coin, "15m", limit=5000)
        candles_1h = store.get_candles(coin, "1h", limit=5000)

        if len(candles_15m) < 200 or len(candles_1h) < 200:
            logger.warning(
                "%s: 데이터 부족 (15m=%d, 1h=%d)",
                coin,
                len(candles_15m),
                len(candles_1h),
            )
            continue

        logger.info(
            "%s: 백테스트 시작 (15m=%d, 1h=%d)",
            coin,
            len(candles_15m),
            len(candles_1h),
        )

        # 슬라이딩 윈도우 (15M 기준, 4봉씩 = 1시간)
        window_15m = 200
        step = 4
        position: BacktestTrade | None = None

        for i in range(window_15m, len(candles_15m) - step, step):
            slice_15m = candles_15m[i - window_15m : i]
            current_ts = slice_15m[-1].timestamp
            current_price = slice_15m[-1].close

            # 1H 캔들 동기화
            sync_1h = [c for c in candles_1h if c.timestamp <= current_ts]
            if len(sync_1h) < 50:
                continue
            sync_1h = sync_1h[-200:]

            # 포지션 보유 중이면 SL/TP 체크
            if position is not None:
                future = candles_15m[i : i + step]
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
                    position.hold_bars = i - position.entry_idx

                    all_trades.append(position)

                    key = position.strategy.value
                    stats = strategy_stats[key]
                    stats.trades += 1
                    stats.total_pnl += pnl
                    if pnl > 0:
                        stats.wins += 1
                        stats.gross_wins += pnl
                    else:
                        stats.gross_losses += abs(pnl)

                    position = None
                continue

            # 신호 생성
            snap = MarketSnapshot(
                symbol=coin,
                current_price=current_price,
                candles_15m=slice_15m,
                candles_1h=sync_1h,
            )
            signals = engine.generate_signals({coin: snap})

            if signals:
                sig = signals[0]
                position = BacktestTrade(
                    symbol=coin,
                    strategy=sig.strategy,
                    regime=sig.regime,
                    entry_price=sig.entry_price,
                    exit_price=0,
                    entry_idx=i,
                    exit_idx=0,
                    stop_loss=sig.stop_loss,
                    take_profit=sig.take_profit,
                )

    # MDD 계산 (전략별, 시간순 정렬)
    for key, stats in strategy_stats.items():
        strat_trades = sorted(
            [t for t in all_trades if t.strategy.value == key],
            key=lambda t: t.entry_idx,
        )
        if not strat_trades:
            continue
        equity = 1_000_000.0  # 기준 자본
        peak = equity
        max_dd = 0.0
        for t in strat_trades:
            equity += t.pnl
            if equity > peak:
                peak = equity
            if peak > 0:
                dd = (peak - equity) / peak
                if dd > max_dd:
                    max_dd = dd
        stats.max_drawdown = max_dd

    return all_trades, dict(strategy_stats)


# ═══════════════════════════════════════════
# 3. 결과 포맷 + 텔레그램 전송
# ═══════════════════════════════════════════


def format_results(
    all_trades: list[BacktestTrade],
    strategy_stats: dict[str, StrategyStats],
    download_info: dict[str, dict[str, int]],
) -> str:
    """결과를 텔레그램 메시지로 포맷한다."""
    lines = ["<b>[BackTest] 백테스트 결과</b>"]
    lines.append("")

    total_15m = sum(v.get("15m", 0) for v in download_info.values())
    total_1h = sum(v.get("1h", 0) for v in download_info.values())
    lines.append(f"데이터: {len(download_info)}개 코인")
    lines.append(f"15M {total_15m:,}봉 / 1H {total_1h:,}봉")
    lines.append("")

    total_trades = len(all_trades)
    if total_trades > 0:
        total_wins = sum(1 for t in all_trades if t.pnl > 0)
        total_pnl = sum(t.pnl for t in all_trades)
        wr = total_wins / total_trades * 100
        lines.append(f"<b>전체: {total_trades}건, 승률 {wr:.1f}%</b>")
        lines.append(f"총 PnL: {total_pnl:,.0f}원")
    else:
        lines.append("<b>거래 없음</b>")
    lines.append("")

    lines.append("<b>── 전략별 성과 ──</b>")
    strat_names = {
        "trend_follow": "A 추세추종",
        "mean_reversion": "B 반전포착",
        "breakout": "C 브레이크아웃",
        "scalping": "D 스캘핑",
        "dca": "E DCA",
    }

    for key in ["trend_follow", "mean_reversion", "breakout", "scalping", "dca"]:
        stats = strategy_stats.get(key)
        name = strat_names.get(key, key)
        if not stats or stats.trades == 0:
            lines.append(f"\n{name}: 거래 없음")
            continue

        lines.append(f"\n<b>{name}</b> ({stats.trades}건)")
        lines.append(f"  승률: {stats.win_rate * 100:.1f}%")
        lines.append(f"  Expectancy: {stats.expectancy:,.0f}원")
        lines.append(f"  PF: {stats.profit_factor:.2f}")
        lines.append(f"  MDD: {stats.max_drawdown * 100:.1f}%")
        lines.append(f"  총 PnL: {stats.total_pnl:,.0f}원")

    # BTC 전략별 상세
    btc_trades = [t for t in all_trades if t.symbol == "BTC"]
    if btc_trades:
        lines.append("")
        lines.append("<b>── BTC 전략별 상세 ──</b>")
        btc_by_strat: dict[str, list[BacktestTrade]] = defaultdict(list)
        for t in btc_trades:
            btc_by_strat[t.strategy.value].append(t)
        for skey, trades in sorted(btc_by_strat.items()):
            ws = sum(1 for t in trades if t.pnl > 0)
            pnl = sum(t.pnl for t in trades)
            avg_win = sum(t.pnl for t in trades if t.pnl > 0) / ws if ws > 0 else 0
            ls = len(trades) - ws
            avg_loss = sum(t.pnl for t in trades if t.pnl <= 0) / ls if ls > 0 else 0
            name = strat_names.get(skey, skey)
            lines.append(
                f"  {name}: {len(trades)}건 {ws}W/{ls}L PnL={pnl:,.0f}",
            )
            lines.append(
                f"    avg_win={avg_win:,.0f} avg_loss={avg_loss:,.0f}",
            )

    lines.append("")
    lines.append("<b>── 코인별 ──</b>")
    coin_pnl: dict[str, list[float]] = defaultdict(list)
    for t in all_trades:
        coin_pnl[t.symbol].append(t.pnl)
    for sym in sorted(coin_pnl.keys()):
        pnls = coin_pnl[sym]
        wins = sum(1 for p in pnls if p > 0)
        total = sum(pnls)
        lines.append(
            f"  {sym}: {len(pnls)}건 {wins}/{len(pnls)} PnL={total:,.0f}",
        )

    return "\n".join(lines)


# ═══════════════════════════════════════════
# 메인
# ═══════════════════════════════════════════


async def main() -> None:
    """메인 실행."""
    config = load_config()
    coins = config.coins
    logger.info("대상 코인: %s", coins)

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
    notifier = TelegramNotifier(
        token=config.secrets.telegram_bot_token,
        chat_id=config.secrets.telegram_chat_id,
    )

    try:
        # 1. 데이터 다운로드
        logger.info("=" * 50)
        logger.info("1단계: 캔들 데이터 다운로드")
        download_info = await download_candles(client, store, coins)

        total_candles = sum(v for coin_data in download_info.values() for v in coin_data.values())
        logger.info("다운로드 완료: 총 %d봉", total_candles)

        # 2. 백테스트
        logger.info("=" * 50)
        logger.info("2단계: 전략 파이프라인 백테스트")

        profiler = CoinProfiler(
            tier1_atr_max=0.03,
            tier3_atr_min=0.07,
        )
        engine = RuleEngine(
            profiler=profiler,
            score_cutoff=config.score_cutoff,
            regime_config=config.regime,
            execution_config=config.execution,
            strategy_params=config.strategy_params,
        )

        # rule_engine DEBUG 로그 끄기 (백테스트 중 너무 많음)
        logging.getLogger("strategy.rule_engine").setLevel(logging.WARNING)

        start_time = time.time()
        all_trades, strategy_stats = run_backtest(
            store,
            coins,
            engine,
            profiler,
        )
        elapsed = time.time() - start_time
        logger.info(
            "백테스트 완료: %d건 거래, %.1f초",
            len(all_trades),
            elapsed,
        )

        # 3. 결과
        msg = format_results(all_trades, strategy_stats, download_info)
        plain = msg.replace("<b>", "").replace("</b>", "")
        # 터미널 인코딩 문제 회피 (UTF-8 강제)
        sys.stdout.buffer.write(("\n" + plain + "\n").encode("utf-8"))

        # 4. 텔레그램 전송
        logger.info("=" * 50)
        logger.info("3단계: 텔레그램 전송")
        ok = await notifier.send(msg)
        if ok:
            logger.info("텔레그램 전송 성공")
        else:
            logger.warning("텔레그램 전송 실패")

    finally:
        await client.close()
        await notifier.close()
        store.close()


if __name__ == "__main__":
    asyncio.run(main())
