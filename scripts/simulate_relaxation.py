"""파라미터 완화 시뮬레이션 — 4개 시나리오 비교 백테스트.

L1 필터, 점수 cutoff, 사이징, 포지션 상한을 시나리오별로 변경하고
거래 수, 승률, PF, MDD, 총 PnL, 자금활용률을 비교한다.
"""
# ruff: noqa: E402

from __future__ import annotations

import asyncio
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
from app.data_types import Candle, MarketSnapshot, Strategy, parse_raw_candles
from market.bithumb_api import BithumbClient
from market.market_store import MarketStore
from strategy.coin_profiler import CoinProfiler, TierParams
from strategy.rule_engine import RuleEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)
# 백테스트 중 과도한 로그 억제
logging.getLogger("strategy.rule_engine").setLevel(logging.WARNING)
logging.getLogger("strategy.coin_profiler").setLevel(logging.WARNING)

KST = timezone(timedelta(hours=9))

FEE_RATE = 0.0025  # 편도 0.25%
SLIPPAGE_RATE = 0.001  # 편도 0.1%
INITIAL_CAPITAL = 930_000  # 93만원


# ═══════════════════════════════════════════
# 데이터 타입
# ═══════════════════════════════════════════


@dataclass
class ScenarioConfig:
    """시나리오 파라미터."""

    name: str
    # L1 필터
    volume_ratio: float = 0.8  # 거래량 비율 (현재봉 >= 평균 × ratio)
    spread_limit_mult: float = 1.0  # 스프레드 한도 배수
    night_policy: str = "block"  # "block" | "reduce_50" | "reduce_30"
    # 점수 cutoff
    probe_min_delta: int = 0  # probe_min에서 빼는 값
    full_delta: int = 0  # full cutoff에서 빼는 값
    # 사이징
    active_risk_pct: float = 0.07
    pool_cap_pct: float = 0.25
    # 포지션 상한
    max_active_positions: int = 5
    max_core_positions: int = 3


@dataclass
class SimTrade:
    """시뮬레이션 거래."""

    symbol: str
    strategy: str
    regime: str
    entry_price: float
    exit_price: float
    entry_ts: int  # milliseconds
    exit_ts: int
    stop_loss: float
    take_profit: float
    size_krw: float = 0.0
    pnl_krw: float = 0.0
    pnl_pct: float = 0.0
    hold_bars: int = 0


@dataclass
class SimPosition:
    """시뮬레이션 포지션."""

    symbol: str
    strategy: str
    entry_price: float
    entry_ts: int
    entry_idx: int
    stop_loss: float
    take_profit: float
    size_krw: float
    regime: str = ""


@dataclass
class SimResult:
    """시나리오 결과."""

    scenario: str
    trades: list[SimTrade] = field(default_factory=list)
    total_pnl: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    sharpe: float = 0.0
    trade_count: int = 0
    avg_daily_trades: float = 0.0
    capital_utilization: float = 0.0
    final_equity: float = INITIAL_CAPITAL
    max_concurrent: int = 0


# ═══════════════════════════════════════════
# 시나리오 정의
# ═══════════════════════════════════════════

SCENARIOS = [
    ScenarioConfig(
        name="A_현행",
        volume_ratio=0.8,
        spread_limit_mult=1.0,
        night_policy="block",
        probe_min_delta=0,
        full_delta=0,
        active_risk_pct=0.07,
        pool_cap_pct=0.25,
        max_active_positions=5,
        max_core_positions=3,
    ),
    ScenarioConfig(
        name="B_보수적",
        volume_ratio=0.6,
        spread_limit_mult=1.5,
        night_policy="reduce_50",
        probe_min_delta=5,
        full_delta=5,
        active_risk_pct=0.10,
        pool_cap_pct=0.30,
        max_active_positions=6,
        max_core_positions=4,
    ),
    ScenarioConfig(
        name="C_균형",
        volume_ratio=0.5,
        spread_limit_mult=2.0,
        night_policy="reduce_50",
        probe_min_delta=10,
        full_delta=10,
        active_risk_pct=0.12,
        pool_cap_pct=0.35,
        max_active_positions=7,
        max_core_positions=5,
    ),
    ScenarioConfig(
        name="D_적극",
        volume_ratio=0.4,
        spread_limit_mult=2.0,
        night_policy="reduce_30",
        probe_min_delta=15,
        full_delta=15,
        active_risk_pct=0.15,
        pool_cap_pct=0.40,
        max_active_positions=8,
        max_core_positions=5,
    ),
]


# ═══════════════════════════════════════════
# L1 필터 (파라미터화)
# ═══════════════════════════════════════════


def check_l1_filter(
    candles_15m: list[Candle],
    candles_1h: list[Candle],
    tier_params: TierParams,
    candle_ts: int,
    config: ScenarioConfig,
) -> tuple[bool, str, float]:
    """L1 환경 필터 (시뮬레이션용).

    Returns:
        (통과 여부, 거부 사유, 사이징 배수)
    """
    sizing_mult = 1.0

    # 1. 거래량 필터
    if candles_15m and len(candles_15m) >= 22:
        volumes = np.array([c.volume for c in candles_15m])
        avg_vol = float(np.mean(volumes[-22:-2]))
        current_vol = float(volumes[-2])
        if avg_vol > 0 and current_vol < avg_vol * config.volume_ratio:
            return False, "거래량 부족", 0.0

    # 2. 스프레드 필터 (캔들 기반 추정: (high-low)/close)
    if candles_15m and len(candles_15m) >= 2:
        c = candles_15m[-2]
        if c.close > 0:
            estimated_spread = (c.high - c.low) / c.close
            # 실제 스프레드는 캔들 범위보다 훨씬 작음 (10~20% 수준)
            estimated_spread *= 0.15
            limit = tier_params.spread_limit * config.spread_limit_mult
            if estimated_spread > limit:
                return False, f"스프레드 초과 ({estimated_spread:.4f})", 0.0

    # 3. 시간대 필터 (캔들 타임스탬프 기반)
    candle_dt = datetime.fromtimestamp(candle_ts / 1000, tz=KST)
    is_night = 0 <= candle_dt.hour < 6
    is_tier3 = (
        tier_params.tier.value == "TIER3"
        if hasattr(tier_params.tier, "value")
        else str(tier_params.tier) == "TIER3"
    )

    if is_night and is_tier3:
        if config.night_policy == "block":
            return False, "심야 T3 차단", 0.0
        elif config.night_policy == "reduce_50":
            sizing_mult *= 0.5
        elif config.night_policy == "reduce_30":
            sizing_mult *= 0.3

    # 4. 1H 급변동 억제
    if candles_1h and len(candles_1h) >= 2:
        c = candles_1h[-2]
        if c.open > 0 and abs(c.close / c.open - 1) >= 0.015:
            return False, "모멘텀 버스트", 0.0

    return True, "", sizing_mult


# ═══════════════════════════════════════════
# 사이징 계산 (파라미터화)
# ═══════════════════════════════════════════


SCORE_MULT = {"FULL": 1.0, "PROBE": 0.5, "HOLD": 0.0}

REGIME_DEFENSE = {
    "STRONG_UP": 1.0,
    "WEAK_UP": 0.85,
    "RANGE": 0.7,
    "WEAK_DOWN": 0.5,
    "CRISIS": 0.0,
}


def decide_size(
    strategy: Strategy,
    score: float,
    config: ScenarioConfig,
) -> str:
    """FULL/PROBE/HOLD 판정 (완화 적용)."""
    # 전략→그룹 매핑
    group_map = {
        Strategy.TREND_FOLLOW: 1,
        Strategy.MEAN_REVERSION: 2,
        Strategy.BREAKOUT: 1,
        Strategy.DCA: 3,
    }
    group = group_map.get(strategy, 1)

    defaults = {
        1: (75, 60),
        2: (80, 65),
        3: (75, 68),
    }
    full_base, probe_base = defaults[group]
    full = full_base - config.full_delta
    probe_min = probe_base - config.probe_min_delta

    if score >= full:
        return "FULL"
    if score >= probe_min:
        return "PROBE"
    return "HOLD"


def calculate_size(
    equity: float,
    active_balance: float,
    size_decision: str,
    regime: str,
    tier_mult: float,
    l1_sizing_mult: float,
    config: ScenarioConfig,
) -> float:
    """포지션 사이즈 계산 (KRW)."""
    if size_decision == "HOLD":
        return 0.0

    base = active_balance * config.active_risk_pct
    score_mult = SCORE_MULT.get(size_decision, 1.0)
    defense = REGIME_DEFENSE.get(regime, 0.7)
    defense = max(0.3, min(1.0, defense))

    size = base * tier_mult * score_mult * defense * l1_sizing_mult

    # pool_cap
    cap = active_balance * config.pool_cap_pct
    size = min(size, cap)

    # 최소 주문 금액
    if size < 5000:
        return 0.0

    return size


# ═══════════════════════════════════════════
# 포트폴리오 시뮬레이터
# ═══════════════════════════════════════════


def run_scenario(
    config: ScenarioConfig,
    store: MarketStore,
    coins: list[str],
    profiler: CoinProfiler,
    base_engine: RuleEngine,
) -> SimResult:
    """단일 시나리오 시뮬레이션."""
    result = SimResult(scenario=config.name)
    equity = float(INITIAL_CAPITAL)
    active_balance = equity * 0.5  # Active Pool 50%
    _core_balance = equity * 0.4  # Core Pool 40%  # noqa: F841
    positions: dict[str, SimPosition] = {}
    equity_history: list[float] = [equity]
    utilization_samples: list[float] = []
    max_concurrent = 0
    total_bars = 0

    # 데이터 로드
    candles_15m_map: dict[str, list[Candle]] = {}
    candles_1h_map: dict[str, list[Candle]] = {}
    for coin in coins:
        c15 = store.get_candles(coin, "15m", limit=10000)
        c1h = store.get_candles(coin, "1h", limit=5000)
        if c15 and len(c15) >= 200 and c1h and len(c1h) >= 50:
            candles_15m_map[coin] = c15
            candles_1h_map[coin] = c1h

    if not candles_15m_map:
        logger.warning("%s: 데이터 부족", config.name)
        return result

    # 1H 기반 프로파일링
    profiler.classify_all(candles_1h_map)

    # 시간 범위 결정 (공통 구간)
    min_ts = max(c[200].timestamp for c in candles_15m_map.values())
    max_ts = min(c[-1].timestamp for c in candles_15m_map.values())

    window_15m = 200
    step = 4  # 4봉 = 1시간 간격으로 평가

    # 기준 코인의 15m 인덱스로 순회
    ref_coin = coins[0]
    ref_candles = candles_15m_map.get(ref_coin, [])
    if not ref_candles:
        return result

    for i in range(window_15m, len(ref_candles) - step, step):
        current_ts = ref_candles[i].timestamp
        if current_ts < min_ts or current_ts > max_ts:
            continue

        total_bars += 1

        # 포지션 보유 중인 코인의 SL/TP 체크
        closed_symbols = []
        for sym, pos in list(positions.items()):
            coin_candles = candles_15m_map.get(sym)
            if not coin_candles:
                continue

            # 현재 ts에 해당하는 인덱스 찾기
            idx = _find_index(coin_candles, current_ts)
            if idx is None or idx + step >= len(coin_candles):
                continue

            future = coin_candles[idx : idx + step]
            hit_sl = any(c.low <= pos.stop_loss for c in future)
            hit_tp = any(c.high >= pos.take_profit for c in future)

            if hit_sl or hit_tp:
                exit_price = pos.stop_loss if hit_sl else pos.take_profit
                entry_adj = pos.entry_price * (1 + SLIPPAGE_RATE)
                exit_adj = exit_price * (1 - SLIPPAGE_RATE)
                fee = entry_adj * FEE_RATE + exit_adj * FEE_RATE
                pnl_per_unit = (exit_adj - entry_adj) - fee
                pnl_pct = pnl_per_unit / entry_adj if entry_adj > 0 else 0
                pnl_krw = pos.size_krw * pnl_pct

                trade = SimTrade(
                    symbol=sym,
                    strategy=pos.strategy,
                    regime=pos.regime,
                    entry_price=pos.entry_price,
                    exit_price=exit_price,
                    entry_ts=pos.entry_ts,
                    exit_ts=current_ts,
                    stop_loss=pos.stop_loss,
                    take_profit=pos.take_profit,
                    size_krw=pos.size_krw,
                    pnl_krw=pnl_krw,
                    pnl_pct=pnl_pct * 100,
                    hold_bars=idx - pos.entry_idx,
                )
                result.trades.append(trade)

                # 자금 복귀
                equity += pnl_krw
                active_balance += pos.size_krw + pnl_krw
                closed_symbols.append(sym)

        for sym in closed_symbols:
            del positions[sym]

        # 자금활용률 기록
        deployed = sum(p.size_krw for p in positions.values())
        util = deployed / equity if equity > 0 else 0.0
        utilization_samples.append(util)

        max_concurrent = max(max_concurrent, len(positions))
        equity_history.append(equity)

        # 신규 진입 평가 (코인별)
        active_count = len(positions)

        for coin in coins:
            if coin in positions:
                continue
            if active_count >= config.max_active_positions:
                break

            coin_15m = candles_15m_map.get(coin)
            coin_1h = candles_1h_map.get(coin)
            if not coin_15m or not coin_1h:
                continue

            idx = _find_index(coin_15m, current_ts)
            if idx is None or idx < window_15m:
                continue

            slice_15m = coin_15m[idx - window_15m : idx]
            sync_1h = [c for c in coin_1h if c.timestamp <= current_ts]
            if len(sync_1h) < 50:
                continue
            sync_1h = sync_1h[-200:]

            # Tier 확인
            tier_params = profiler.get_tier(coin)

            # L1 필터
            passed, reason, l1_mult = check_l1_filter(
                slice_15m,
                sync_1h,
                tier_params,
                current_ts,
                config,
            )
            if not passed:
                continue

            # 신호 생성
            snap = MarketSnapshot(
                symbol=coin,
                current_price=slice_15m[-1].close,
                candles_15m=slice_15m,
                candles_1h=sync_1h,
            )
            signals = base_engine.generate_signals({coin: snap})
            if not signals:
                continue

            sig = signals[0]

            # 사이즈 판정
            size_dec = decide_size(sig.strategy, sig.score, config)
            if size_dec == "HOLD":
                continue

            # 국면
            regime_str = sig.regime.value if hasattr(sig.regime, "value") else str(sig.regime)

            # 사이징
            size_krw = calculate_size(
                equity,
                active_balance,
                size_dec,
                regime_str,
                tier_params.position_mult,
                l1_mult,
                config,
            )
            if size_krw <= 0:
                continue

            # 잔액 체크
            if size_krw > active_balance * 0.95:  # 95% 이상 사용 방지
                size_krw = active_balance * 0.5

            if size_krw < 5000 or active_balance < size_krw:
                continue

            # 진입
            active_balance -= size_krw
            positions[coin] = SimPosition(
                symbol=coin,
                strategy=sig.strategy.value,
                entry_price=sig.entry_price,
                entry_ts=current_ts,
                entry_idx=idx,
                stop_loss=sig.stop_loss,
                take_profit=sig.take_profit,
                size_krw=size_krw,
                regime=regime_str,
            )
            active_count += 1

    # 미청산 포지션 강제 청산 (마지막 가격 기준)
    for sym, pos in positions.items():
        coin_15m = candles_15m_map.get(sym)
        if coin_15m:
            exit_price = coin_15m[-1].close
            pnl_pct = (exit_price - pos.entry_price) / pos.entry_price if pos.entry_price > 0 else 0
            pnl_krw = pos.size_krw * pnl_pct
            equity += pnl_krw
            result.trades.append(
                SimTrade(
                    symbol=sym,
                    strategy=pos.strategy,
                    regime=pos.regime,
                    entry_price=pos.entry_price,
                    exit_price=exit_price,
                    entry_ts=pos.entry_ts,
                    exit_ts=int(time.time() * 1000),
                    stop_loss=pos.stop_loss,
                    take_profit=pos.take_profit,
                    size_krw=pos.size_krw,
                    pnl_krw=pnl_krw,
                    pnl_pct=pnl_pct * 100,
                )
            )
    positions.clear()

    # 결과 계산
    result.trade_count = len(result.trades)
    result.final_equity = equity
    result.max_concurrent = max_concurrent

    if result.trades:
        wins = [t for t in result.trades if t.pnl_krw > 0]
        losses = [t for t in result.trades if t.pnl_krw <= 0]
        result.total_pnl = sum(t.pnl_krw for t in result.trades)
        result.win_rate = len(wins) / len(result.trades) if result.trades else 0.0

        gross_wins = sum(t.pnl_krw for t in wins)
        gross_losses = abs(sum(t.pnl_krw for t in losses))
        result.profit_factor = gross_wins / gross_losses if gross_losses > 0 else 10.0

        # MDD
        peak = INITIAL_CAPITAL
        max_dd = 0.0
        eq = INITIAL_CAPITAL
        for t in sorted(result.trades, key=lambda x: x.entry_ts):
            eq += t.pnl_krw
            peak = max(peak, eq)
            dd = (peak - eq) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)
        result.max_drawdown = max_dd

        # Sharpe (일간 수익률 기반)
        daily_pnls = _calc_daily_pnls(result.trades)
        if daily_pnls and len(daily_pnls) > 1:
            mean_r = np.mean(daily_pnls)
            std_r = np.std(daily_pnls, ddof=1)
            result.sharpe = float(mean_r / std_r * math.sqrt(252)) if std_r > 0 else 0.0

        # 일평균 거래 수
        if result.trades:
            first_ts = min(t.entry_ts for t in result.trades)
            last_ts = max(t.exit_ts for t in result.trades)
            days = max((last_ts - first_ts) / 1000 / 86400, 1)
            result.avg_daily_trades = result.trade_count / days

    # 평균 자금활용률
    result.capital_utilization = float(np.mean(utilization_samples)) if utilization_samples else 0.0

    return result


def _find_index(candles: list[Candle], target_ts: int) -> int | None:
    """타임스탬프에 가장 가까운 인덱스를 찾는다."""
    # 이진 탐색
    lo, hi = 0, len(candles) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if candles[mid].timestamp < target_ts:
            lo = mid + 1
        elif candles[mid].timestamp > target_ts:
            hi = mid - 1
        else:
            return mid
    # 가장 가까운 이전 인덱스
    return hi if hi >= 0 else None


def _calc_daily_pnls(trades: list[SimTrade]) -> list[float]:
    """거래를 일별로 묶어 일간 PnL 리스트를 반환한다."""
    if not trades:
        return []
    daily: dict[str, float] = defaultdict(float)
    for t in trades:
        day = datetime.fromtimestamp(t.exit_ts / 1000, tz=KST).strftime("%Y-%m-%d")
        daily[day] += t.pnl_krw
    return list(daily.values())


# ═══════════════════════════════════════════
# 데이터 다운로드
# ═══════════════════════════════════════════


async def download_fresh_data(coins: list[str], config: object) -> None:
    """최신 캔들 데이터를 다운로드한다."""
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
# 결과 출력
# ═══════════════════════════════════════════


def print_results(results: list[SimResult]) -> None:
    """비교 테이블을 출력한다."""
    print("\n" + "=" * 80)
    print("  파라미터 완화 시뮬레이션 결과 비교")
    print(f"  자본금: {INITIAL_CAPITAL:,}원 | 데이터: ~40일")
    print("=" * 80)

    # 헤더
    names = [r.scenario for r in results]
    header = f"{'지표':<20}" + "".join(f"{n:>14}" for n in names)
    print(header)
    print("-" * (20 + 14 * len(names)))

    # 행
    def row(label: str, values: list[str]) -> None:
        print(f"{label:<20}" + "".join(f"{v:>14}" for v in values))

    row("총 거래 수", [str(r.trade_count) for r in results])
    row("일평균 거래", [f"{r.avg_daily_trades:.1f}" for r in results])
    row("승률", [f"{r.win_rate * 100:.1f}%" for r in results])
    row("Profit Factor", [f"{r.profit_factor:.2f}" for r in results])
    row("Sharpe Ratio", [f"{r.sharpe:.2f}" for r in results])
    row("MDD", [f"{r.max_drawdown * 100:.1f}%" for r in results])
    row("총 PnL", [f"{r.total_pnl:,.0f}원" for r in results])
    row("최종 자산", [f"{r.final_equity:,.0f}원" for r in results])
    row("수익률", [f"{(r.final_equity / INITIAL_CAPITAL - 1) * 100:.1f}%" for r in results])
    row("자금활용률", [f"{r.capital_utilization * 100:.1f}%" for r in results])
    row("최대 동시포지션", [str(r.max_concurrent) for r in results])

    print("-" * (20 + 14 * len(names)))

    # 최적 판정 (PnL > 0이고 MDD < 15%인 것 중 PnL 최대)
    valid = [r for r in results if r.total_pnl > 0 and r.max_drawdown < 0.15]
    if valid:
        best = max(valid, key=lambda r: r.total_pnl)
        print(f"\n★ 추천 시나리오: {best.scenario}")
        print(
            f"  사유: PnL {best.total_pnl:,.0f}원, MDD {best.max_drawdown * 100:.1f}%, "
            f"PF {best.profit_factor:.2f}, 자금활용률 {best.capital_utilization * 100:.1f}%"
        )
    else:
        print("\n⚠ 모든 시나리오가 MDD > 15% 또는 PnL <= 0. 추가 조정 필요.")

    # 전략별 세부
    print("\n" + "=" * 80)
    print("  전략별 세부 (각 시나리오)")
    print("=" * 80)

    for r in results:
        print(f"\n  [{r.scenario}]")
        strat_trades: dict[str, list[SimTrade]] = defaultdict(list)
        for t in r.trades:
            strat_trades[t.strategy].append(t)

        if not strat_trades:
            print("    거래 없음")
            continue

        for strat in sorted(strat_trades.keys()):
            trades = strat_trades[strat]
            wins = sum(1 for t in trades if t.pnl_krw > 0)
            total_pnl = sum(t.pnl_krw for t in trades)
            gr_w = sum(t.pnl_krw for t in trades if t.pnl_krw > 0)
            gr_l = abs(sum(t.pnl_krw for t in trades if t.pnl_krw <= 0))
            pf = gr_w / gr_l if gr_l > 0 else 10.0
            wr = wins / len(trades) * 100 if trades else 0
            print(
                f"    {strat:<18} {len(trades):>3}건 WR={wr:>5.1f}% PF={pf:>5.2f} PnL={total_pnl:>+10,.0f}원"
            )

    # 코인별
    print("\n" + "=" * 80)
    print("  코인별 세부 (추천 시나리오)")
    print("=" * 80)

    target = best if valid else results[-1]
    coin_trades: dict[str, list[SimTrade]] = defaultdict(list)
    for t in target.trades:
        coin_trades[t.symbol].append(t)

    for sym in sorted(coin_trades.keys()):
        trades = coin_trades[sym]
        wins = sum(1 for t in trades if t.pnl_krw > 0)
        total_pnl = sum(t.pnl_krw for t in trades)
        print(
            f"  {sym:<10} {len(trades):>3}건 {wins}W/{len(trades) - wins}L PnL={total_pnl:>+10,.0f}원"
        )


# ═══════════════════════════════════════════
# 메인
# ═══════════════════════════════════════════


async def main() -> None:
    """메인 실행."""
    config = load_config()
    coins = config.coins
    logger.info("시뮬레이션 시작: %d개 코인, %d개 시나리오", len(coins), len(SCENARIOS))

    # 1. 최신 데이터 다운로드
    logger.info("=" * 50)
    logger.info("1단계: 최신 캔들 데이터 다운로드")
    await download_fresh_data(coins, config)

    # 2. 시나리오별 시뮬레이션
    logger.info("=" * 50)
    logger.info("2단계: 시나리오별 시뮬레이션")

    store = MarketStore(db_path="data/market_data.db")
    profiler = CoinProfiler(
        tier1_atr_max=0.009,
        tier3_atr_min=0.014,
    )
    engine = RuleEngine(
        profiler=profiler,
        score_cutoff=config.score_cutoff,
        regime_config=config.regime,
        execution_config=config.execution,
        strategy_params=config.strategy_params,
    )

    results: list[SimResult] = []
    for scenario in SCENARIOS:
        logger.info("시나리오 %s 실행 중...", scenario.name)
        start = time.time()
        result = run_scenario(scenario, store, coins, profiler, engine)
        elapsed = time.time() - start
        logger.info(
            "  %s: %d건 거래, PnL=%+,.0f원, %.1f초",
            scenario.name,
            result.trade_count,
            result.total_pnl,
            elapsed,
        )
        results.append(result)

    store.close()

    # 3. 결과 비교
    print_results(results)


if __name__ == "__main__":
    asyncio.run(main())
