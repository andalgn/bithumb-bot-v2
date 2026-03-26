"""Darwinian 자가 학습 엔진.

Shadow 20~30개 병렬 추적 + 주간 토너먼트 + 챔피언 교체.
DARWINIAN_SPEC.md 기반.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import logging
import math
import random
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.data_types import MarketSnapshot, Regime, Signal, Strategy, Tier

if TYPE_CHECKING:
    from app.journal import Journal
    from strategy.coin_profiler import CoinProfiler
    from strategy.experiment_store import ExperimentStore

logger = logging.getLogger(__name__)

# 수수료 + 슬리피지 보정
FEE_PCT = 0.005
SLIPPAGE_BY_TIER: dict[Tier, float] = {
    Tier.TIER1: 0.0005,
    Tier.TIER2: 0.001,
    Tier.TIER3: 0.002,
}
SHADOW_DISCOUNT = 0.85  # Shadow net_pnl × 0.85 vs Live

# 돌연변이 범위: (delta, min, max)
MUTATION_RANGES: dict[str, tuple[float, float, float]] = {
    "mr_sl_mult": (0.5, 2.0, 10.0),
    "mr_tp_rr": (0.3, 1.0, 4.0),
    "dca_sl_pct": (0.005, 0.02, 0.08),
    "dca_tp_pct": (0.005, 0.01, 0.05),
    "cutoff": (3.0, 55.0, 90.0),
}

# Composite Score 가중치 (합 = 1.0)
COMPOSITE_WEIGHTS = {
    "expectancy": 0.25,
    "profit_factor": 0.15,
    "mdd": 0.15,
    "sharpe": 0.15,
    "sortino": 0.10,
    "calmar": 0.10,
    "consec_loss": 0.05,
    "exec_quality": 0.05,
}


@dataclass
class ShadowParams:
    """Shadow 파라미터 세트 — strategy_params와 동일 구조."""

    shadow_id: str = ""
    group: str = "conservative"  # conservative/moderate/innovative
    mr_sl_mult: float = 7.0  # mean_reversion SL multiplier (2.0~10.0)
    mr_tp_rr: float = 1.5  # mean_reversion TP risk-reward (1.0~4.0)
    dca_sl_pct: float = 0.05  # dca SL percent (0.02~0.08)
    dca_tp_pct: float = 0.03  # dca TP percent (0.01~0.05)
    cutoff: float = 72.0  # entry score cutoff (55~90)


@dataclass
class ShadowTrade:
    """Shadow 가상 거래."""

    shadow_id: str
    symbol: str
    strategy: str
    would_enter: bool
    signal_score: float
    virtual_pnl: float = 0.0
    timestamp: int = 0


@dataclass
class ShadowPerformance:
    """Shadow 성과 통계."""

    shadow_id: str
    trade_count: int = 0
    total_pnl: float = 0.0
    win_count: int = 0
    total_wins_pnl: float = 0.0
    total_losses_pnl: float = 0.0
    max_drawdown: float = 0.0
    peak_equity: float = 1_000_000.0
    current_equity: float = 1_000_000.0
    sortino_ratio: float = 0.0        # 하방 변동성 대비 수익률
    calmar_ratio: float = 0.0         # MDD 대비 연간 수익률
    max_consecutive_loss: int = 0     # 최대 연속 손실 횟수

    @property
    def expectancy(self) -> float:
        """Expectancy를 반환한다."""
        if self.trade_count == 0:
            return 0.0
        return self.total_pnl / self.trade_count

    @property
    def win_rate(self) -> float:
        """승률을 반환한다."""
        if self.trade_count == 0:
            return 0.0
        return self.win_count / self.trade_count

    @property
    def profit_factor(self) -> float:
        """Profit Factor를 반환한다."""
        if self.trade_count == 0:
            return 0.0
        if self.total_losses_pnl == 0:
            return 10.0 if self.total_wins_pnl > 0 else 0.0
        return self.total_wins_pnl / abs(self.total_losses_pnl)


@dataclass
class CompositeScore:
    """Composite Score."""

    shadow_id: str
    score: float = 0.0
    expectancy: float = 0.0
    profit_factor: float = 0.0
    mdd: float = 0.0
    sharpe: float = 0.0
    sortino: float = 0.0
    calmar: float = 0.0
    consec_loss_penalty: float = 0.0
    exec_quality: float = 0.0


class DarwinEngine:
    """Darwinian 자가 학습 엔진."""

    def __init__(
        self,
        population_size: int = 20,
        champion_params: ShadowParams | None = None,
        journal: Journal | None = None,
        profiler: CoinProfiler | None = None,
        experiment_store: ExperimentStore | None = None,
    ) -> None:
        """초기화.

        Args:
            population_size: Shadow 개수 (20~30).
            champion_params: 챔피언 파라미터. None이면 기본값.
            journal: 거래 기록 저장소. Shadow 거래 기록용.
            profiler: 코인 프로파일러. Tier별 슬리피지 적용용.
            experiment_store: 실험 저장소. Shadow 거래 영속화용.
        """
        self._pop_size = population_size
        self._champion = champion_params or ShadowParams(shadow_id="champion")
        self._journal = journal
        self._profiler = profiler
        self._experiment_store = experiment_store
        self._shadows: list[ShadowParams] = []
        self._performances: dict[str, ShadowPerformance] = {}
        self._trades: list[ShadowTrade] = []
        # Shadow별 가상 오픈 포지션: {shadow_id: {symbol: entry_price}}
        self._open_positions: dict[str, dict[str, float]] = {}
        self._last_tournament: float = 0.0
        self._last_champion_change: float = 0.0
        self._champion_cooldown_days = 14
        self._initialize_population()
        self._restore_shadow_trades()

    def _initialize_population(self) -> None:
        """초기 Shadow 인구를 생성한다."""
        self._shadows = []
        for i in range(self._pop_size):
            sid = str(uuid.uuid4())[:8]
            if i < 7:
                group = "conservative"
                params = self._mutate(self._champion, variation=0.10, group=group)
            elif i < 15:
                group = "moderate"
                params = self._mutate(self._champion, variation=0.20, group=group)
            else:
                group = "innovative"
                params = self._mutate(self._champion, variation=0.40, group=group)

            params.shadow_id = sid
            params.group = group
            self._shadows.append(params)
            self._performances[sid] = ShadowPerformance(shadow_id=sid)

        self._performances["champion"] = ShadowPerformance(shadow_id="champion")
        logger.info("Darwin 인구 초기화: %d shadows", len(self._shadows))

    def _restore_shadow_trades(self) -> None:
        """ExperimentStore에서 Shadow 거래를 복원한다."""
        if not self._experiment_store:
            return
        restored = 0
        all_ids = [s.shadow_id for s in self._shadows] + ["champion"]
        for sid in all_ids:
            rows = self._experiment_store.get_shadow_trades(sid, days=30)
            for row in rows:
                trade = ShadowTrade(
                    shadow_id=row["shadow_id"],
                    symbol=row["symbol"],
                    strategy=row["strategy"],
                    would_enter=bool(row["would_enter"]),
                    signal_score=row["signal_score"],
                    virtual_pnl=row["virtual_pnl"],
                    timestamp=row["timestamp"] * 1000,  # s -> ms
                )
                self._trades.append(trade)
                restored += 1
        if restored:
            logger.info("Shadow 거래 복원: %d건", restored)

    def _mutate(self, base: ShadowParams, variation: float, group: str) -> ShadowParams:
        """파라미터를 돌연변이시킨다."""
        params = copy.copy(base)
        params.group = group

        for name, (max_delta, lo, hi) in MUTATION_RANGES.items():
            base_val = getattr(base, name, None)
            if base_val is None:
                continue
            multiplier = min(variation / 0.10, 2.0)  # 최대 2배로 제한
            delta = random.uniform(-max_delta, max_delta) * multiplier
            setattr(params, name, max(lo, min(hi, base_val + delta)))

        return params

    def _crossover(self, parent_a: ShadowParams, parent_b: ShadowParams) -> ShadowParams:
        """두 부모의 파라미터를 균등 교차하여 자식을 생성한다.

        Args:
            parent_a: 첫 번째 부모 파라미터. 비수치 필드(shadow_id, group)의 기준.
            parent_b: 두 번째 부모 파라미터.

        Returns:
            각 수치 파라미터가 두 부모 중 하나에서 균등 확률로 선택된 자식 ShadowParams.
        """
        child = copy.copy(parent_a)
        numeric_fields = set(MUTATION_RANGES.keys())
        for field in dataclasses.fields(ShadowParams):
            if field.name in numeric_fields:
                val = getattr(parent_a, field.name) if random.random() < 0.5 else getattr(parent_b, field.name)
                setattr(child, field.name, val)
        return child

    def record_cycle(
        self,
        snapshots: dict[str, MarketSnapshot],
        live_signals: list[Signal],
        live_sl_mult: float = 7.0,
    ) -> int:
        """매 사이클마다 Shadow들의 '진입했을까?' 를 기록한다.

        Args:
            snapshots: 시장 스냅샷.
            live_signals: 챔피언이 생성한 실제 신호.
            live_sl_mult: 현재 config의 mean_reversion.sl_mult.

        Returns:
            기록된 Shadow trade 수.
        """
        count = 0
        now = int(time.time() * 1000)

        for shadow in self._shadows:
            sid = shadow.shadow_id
            if sid not in self._open_positions:
                self._open_positions[sid] = {}
            open_pos = self._open_positions[sid]

            # 1. 기존 오픈 포지션 평가 (SL/TP 기반 exit)
            for sym in list(open_pos.keys()):
                snap = snapshots.get(sym)
                if not snap or snap.current_price <= 0:
                    continue
                entry, sl, tp = open_pos[sym]
                price = snap.current_price

                # SL/TP 도달 여부 확인 (0이면 미설정 → 무시)
                hit_sl = sl > 0 and price <= sl
                hit_tp = tp > 0 and price >= tp
                if not hit_sl and not hit_tp:
                    continue  # 보유 유지

                exit_price = sl if hit_sl else tp
                raw_pnl = (exit_price - entry) / entry
                # 코인의 실제 Tier에 따른 슬리피지 적용
                coin_tier = Tier.TIER2  # 기본값
                if self._profiler:
                    coin_tier = self._profiler.get_tier(sym).tier
                slippage = SLIPPAGE_BY_TIER.get(coin_tier, 0.001)
                virtual_pnl = raw_pnl - (FEE_PCT + slippage * 2)

                perf = self._performances[sid]
                perf.trade_count += 1
                perf.total_pnl += virtual_pnl
                if virtual_pnl > 0:
                    perf.win_count += 1
                    perf.total_wins_pnl += virtual_pnl
                else:
                    perf.total_losses_pnl += abs(virtual_pnl)

                # MDD 추적
                perf.current_equity += virtual_pnl * perf.peak_equity
                if perf.current_equity > perf.peak_equity:
                    perf.peak_equity = perf.current_equity
                if perf.peak_equity > 0:
                    dd = (perf.peak_equity - perf.current_equity) / perf.peak_equity
                    if dd > perf.max_drawdown:
                        perf.max_drawdown = dd

                # 파생 지표 (Sortino, Calmar, 연속 손실) 업데이트
                self._update_derived_metrics(perf, sid)

                del open_pos[sym]

            # 2. 새 시그널 평가 → 가상 진입
            for signal in live_signals:
                would_enter = signal.score >= shadow.cutoff

                trade = ShadowTrade(
                    shadow_id=sid,
                    symbol=signal.symbol,
                    strategy=signal.strategy.value,
                    would_enter=would_enter,
                    signal_score=signal.score,
                    virtual_pnl=0.0,
                    timestamp=now,
                )
                self._trades.append(trade)

                # Shadow 거래를 DB에 영속화
                if self._experiment_store:
                    self._experiment_store.record_shadow_trade(
                        shadow_id=sid,
                        symbol=signal.symbol,
                        strategy=signal.strategy.value,
                        would_enter=would_enter,
                        signal_score=signal.score,
                        virtual_pnl=0.0,
                    )

                if would_enter and signal.entry_price > 0:
                    sl, tp = self._compute_shadow_sl_tp(shadow, signal, live_sl_mult)
                    open_pos[signal.symbol] = (
                        signal.entry_price,
                        sl,
                        tp,
                    )
                    if self._journal:
                        self._journal.record_shadow_trade(
                            {
                                "shadow_id": trade.shadow_id,
                                "symbol": trade.symbol,
                                "strategy": trade.strategy,
                                "params_json": json.dumps(dataclasses.asdict(shadow)),
                                "would_enter": 1,
                                "signal_score": trade.signal_score,
                            }
                        )

                count += 1

        # 오래된 trades 정리 (최근 10,000건만)
        if len(self._trades) > 10_000:
            self._trades = self._trades[-10_000:]

        return count

    def run_tournament(self, market_regime: Regime | None = None) -> list[CompositeScore]:
        """주간 토너먼트를 실행한다.

        Args:
            market_regime: 현재 시장 국면 (동적 변이율 결정용).

        Returns:
            Composite Score 랭킹.
        """
        # 30일 롤링 윈도우: 오래된 trades 제거
        cutoff_ms = int((time.time() - 30 * 86400) * 1000)
        self._trades = [t for t in self._trades if t.timestamp >= cutoff_ms]

        scores: list[CompositeScore] = []

        for shadow in self._shadows:
            perf = self._performances.get(shadow.shadow_id)
            if perf is None or perf.trade_count < 30:
                continue

            cs = self._calc_composite_score(shadow.shadow_id, perf)
            scores.append(cs)

        scores.sort(key=lambda s: s.score, reverse=True)

        # 상위 70% 생존, 하위 30% 멸종
        survive_count = max(1, int(len(scores) * 0.7))
        survivors = scores[:survive_count]
        survivor_ids = {s.shadow_id for s in survivors}

        new_shadows = []
        for shadow in self._shadows:
            if shadow.shadow_id in survivor_ids:
                new_shadows.append(shadow)

        # 동적 변이율
        mutation_rate = self._get_mutation_rate(market_regime)

        # 부족분을 생존 Shadow에서 교차(50%) 또는 변이(50%)로 생성
        survivor_pool = new_shadows[:survive_count] if new_shadows else [self._champion]
        while len(new_shadows) < self._pop_size:
            if len(survivor_pool) >= 2 and random.random() < 0.5:
                # 교차: 두 부모를 선택한 뒤 uniform crossover → 소폭 변이
                p_a, p_b = random.sample(survivor_pool, 2)
                child = self._crossover(p_a, p_b)
                child = self._mutate(child, variation=mutation_rate * 0.5, group="moderate")
            else:
                # 변이: 단일 부모 변이
                parent = random.choice(survivor_pool)
                child = self._mutate(parent, variation=mutation_rate, group="moderate")
            child.shadow_id = str(uuid.uuid4())[:8]
            new_shadows.append(child)
            self._performances[child.shadow_id] = ShadowPerformance(shadow_id=child.shadow_id)

        self._shadows = new_shadows
        self._last_tournament = time.time()

        # 강제 다양성 확보
        diversity_mutations = self._enforce_diversity()

        logger.info(
            "토너먼트 완료: 생존=%d, 새생성=%d, 다양성변이=%d",
            len(survivor_ids),
            self._pop_size - len(survivor_ids),
            diversity_mutations,
        )
        return scores

    def _get_mutation_rate(self, market_regime: Regime | None) -> float:
        """시장 국면에 따른 변이율을 반환한다."""
        if market_regime is None:
            return 0.2
        if market_regime == Regime.CRISIS:
            return 0.4
        if market_regime == Regime.WEAK_DOWN:
            return 0.2
        return 0.1  # RANGE, WEAK_UP, STRONG_UP

    def _enforce_diversity(self) -> int:
        """Shadow 간 다양성을 강제한다.

        정규화된 유클리드 거리가 0.1 미만인 쌍이 있으면 하나를 강제 변이.

        Returns:
            강제 변이 적용 횟수.
        """
        param_names = list(MUTATION_RANGES.keys())
        mutation_count = 0

        for i in range(len(self._shadows)):
            for j in range(i + 1, len(self._shadows)):
                s1 = self._shadows[i]
                s2 = self._shadows[j]

                # 정규화된 유클리드 거리 계산
                dist_sq = 0.0
                for name in param_names:
                    _, lo, hi = MUTATION_RANGES[name]
                    span = hi - lo
                    if span <= 0:
                        continue
                    v1 = (getattr(s1, name) - lo) / span
                    v2 = (getattr(s2, name) - lo) / span
                    dist_sq += (v1 - v2) ** 2

                dist = math.sqrt(dist_sq / len(param_names))

                if dist < 0.1:
                    # j번째 Shadow를 강제 변이
                    mutated = self._mutate(s2, variation=0.3, group=s2.group)
                    mutated.shadow_id = s2.shadow_id
                    mutated.group = s2.group
                    self._shadows[j] = mutated
                    mutation_count += 1

        return mutation_count

    def check_champion_replacement(self) -> ShadowParams | None:
        """챔피언 교체 가능 여부를 확인한다.

        Returns:
            교체할 Shadow 파라미터 또는 None.
        """
        # 쿨다운 확인
        days_since = (time.time() - self._last_champion_change) / 86400
        if days_since < self._champion_cooldown_days:
            return None

        champ_perf = self._performances.get("champion")
        if champ_perf is None or champ_perf.trade_count < 30:
            return None

        champ_score = self._calc_composite_score("champion", champ_perf)

        best_shadow = None
        best_score = champ_score.score

        for shadow in self._shadows:
            perf = self._performances.get(shadow.shadow_id)
            if perf is None or perf.trade_count < 30:
                continue

            cs = self._calc_composite_score(shadow.shadow_id, perf)

            # Shadow PnL × 0.85 보정
            adjusted_pnl = perf.total_pnl * SHADOW_DISCOUNT
            if adjusted_pnl <= champ_perf.total_pnl:
                continue

            if cs.score > best_score:
                best_score = cs.score
                best_shadow = shadow

        if best_shadow:
            logger.info(
                "챔피언 교체 후보: %s (score=%.3f > %.3f)",
                best_shadow.shadow_id,
                best_score,
                champ_score.score,
            )
        return best_shadow

    def replace_champion(self, new_params: ShadowParams) -> None:
        """챔피언을 교체한다."""
        old_id = self._champion.shadow_id
        self._champion = copy.copy(new_params)
        self._champion.shadow_id = "champion"
        self._last_champion_change = time.time()
        self._performances["champion"] = ShadowPerformance(shadow_id="champion")
        logger.info("챔피언 교체 완료: %s -> %s", old_id, new_params.shadow_id)

    @staticmethod
    def _compute_shadow_sl_tp(
        shadow: ShadowParams,
        signal: Signal,
        live_sl_mult: float = 7.0,
    ) -> tuple[float, float]:
        """Shadow 파라미터 기반으로 SL/TP를 계산한다.

        Args:
            shadow: Shadow 파라미터.
            signal: 매매 신호.
            live_sl_mult: 현재 config의 mean_reversion.sl_mult.

        Returns:
            (stop_loss, take_profit) 튜플.
        """
        entry = signal.entry_price
        if signal.strategy == Strategy.DCA:
            sl = entry * (1.0 - shadow.dca_sl_pct)
            tp = entry * (1.0 + shadow.dca_tp_pct)
        else:
            # ATR 기반 전략 (MEAN_REVERSION, TREND_FOLLOW, BREAKOUT, SCALPING)
            # live signal의 SL 거리를 ATR 추정치로 사용
            if signal.stop_loss > 0:
                live_atr_est = abs(entry - signal.stop_loss)
            else:
                live_atr_est = entry * 0.02  # fallback 2%
            # ATR 1단위 = live_atr_est / live_sl_mult
            atr_unit = live_atr_est / live_sl_mult
            sl = entry - atr_unit * shadow.mr_sl_mult
            risk = entry - sl
            tp = entry + risk * shadow.mr_tp_rr
        return sl, tp

    def champion_to_strategy_params(self) -> dict:
        """챔피언 파라미터를 strategy_params 형식으로 변환한다.

        Note: cutoff는 score_cutoff 시스템과 형식이 달라 변환하지 않는다.
        score_cutoff는 group별 full/probe_min/probe_max 구조이므로
        단일 cutoff 값으로는 매핑할 수 없다.
        """
        c = self._champion
        return {
            "mean_reversion": {"sl_mult": c.mr_sl_mult, "tp_rr": c.mr_tp_rr},
            "dca": {"sl_pct": c.dca_sl_pct, "tp_pct": c.dca_tp_pct},
        }

    def _update_derived_metrics(self, perf: ShadowPerformance, shadow_id: str) -> None:
        """Sortino ratio, Calmar ratio, 최대 연속 손실 횟수를 업데이트한다.

        Shadow별 가상 거래 PnL 이력에서 하방 변동성·연속 손실을 계산한다.

        Args:
            perf: 업데이트할 ShadowPerformance 객체.
            shadow_id: 해당 Shadow의 ID.
        """
        # 해당 Shadow의 완결 거래 PnL 목록 수집 (virtual_pnl != 0)
        closed_pnls = [
            t.virtual_pnl
            for t in self._trades
            if t.shadow_id == shadow_id and t.virtual_pnl != 0.0
        ]
        n = len(closed_pnls)
        if n < 2:
            return

        mean_r = sum(closed_pnls) / n

        # Sortino ratio: 하방 변동성 (음의 수익률만)
        neg_returns = [r for r in closed_pnls if r < 0]
        if neg_returns:
            downside_var = sum(r**2 for r in neg_returns) / n  # 전체 n 기준
            downside_dev = math.sqrt(downside_var)
            perf.sortino_ratio = mean_r / downside_dev if downside_dev > 0 else 0.0
        else:
            # 손실이 없으면 Sortino 최대값으로 처리
            perf.sortino_ratio = 3.0

        # Calmar ratio: 연간 수익률 / MDD
        # 연간화 계수: 1거래당 평균 15분봉 1개 기준 → 연 35040개 (15분 × 4 × 24 × 365)
        annualized_return = mean_r * 35040
        if perf.max_drawdown > 0:
            perf.calmar_ratio = annualized_return / perf.max_drawdown
        else:
            perf.calmar_ratio = annualized_return  # MDD 0이면 그대로

        # 최대 연속 손실 횟수
        max_streak = 0
        cur_streak = 0
        for pnl in closed_pnls:
            if pnl < 0:
                cur_streak += 1
                if cur_streak > max_streak:
                    max_streak = cur_streak
            else:
                cur_streak = 0
        perf.max_consecutive_loss = max_streak

    def _calc_composite_score(self, shadow_id: str, perf: ShadowPerformance) -> CompositeScore:
        """Composite Score를 계산한다 (8지표)."""
        # 정규화 (0~1 범위로)
        exp_norm = min(1.0, max(0.0, perf.expectancy / 0.02 + 0.5))
        pf_norm = min(1.0, max(0.0, (perf.profit_factor - 0.5) / 3.0))
        mdd_norm = min(1.0, max(0.0, 1.0 - perf.max_drawdown / 0.20))
        # 간이 Sharpe (표준편차 대신 고정값 사용). Composite Score에서 expectancy와 중복되나,
        # 정밀 Sharpe 계산은 개별 거래 PnL 이력이 필요하므로 현재 구조에서는 근사치 사용.
        sharpe = perf.expectancy / 0.02 if perf.trade_count > 5 else 0
        sharpe_norm = min(1.0, max(0.0, (sharpe + 1) / 4))
        # Sortino: 2.0 이상이면 1.0, 0 이하면 0.0 (Sharpe와 동일 패턴)
        sortino_norm = min(1.0, max(0.0, (perf.sortino_ratio + 1) / 4))
        # Calmar: 1.0 이상이면 1.0, 0 이하면 0.0
        calmar_norm = min(1.0, max(0.0, perf.calmar_ratio / 1.0))
        # 연속 손실 패널티: 5회 이상이면 0, 0회면 1.0
        consec_penalty = max(0.0, 1.0 - perf.max_consecutive_loss / 5.0)
        exec_norm = 0.5  # 기본값 (실제 체결 품질은 LIVE에서)

        score = (
            COMPOSITE_WEIGHTS["expectancy"] * exp_norm
            + COMPOSITE_WEIGHTS["profit_factor"] * pf_norm
            + COMPOSITE_WEIGHTS["mdd"] * mdd_norm
            + COMPOSITE_WEIGHTS["sharpe"] * sharpe_norm
            + COMPOSITE_WEIGHTS["sortino"] * sortino_norm
            + COMPOSITE_WEIGHTS["calmar"] * calmar_norm
            + COMPOSITE_WEIGHTS["consec_loss"] * consec_penalty
            + COMPOSITE_WEIGHTS["exec_quality"] * exec_norm
        )

        return CompositeScore(
            shadow_id=shadow_id,
            score=score,
            expectancy=perf.expectancy,
            profit_factor=perf.profit_factor,
            mdd=perf.max_drawdown,
            sharpe=sharpe,
            sortino=perf.sortino_ratio,
            calmar=perf.calmar_ratio,
            consec_loss_penalty=consec_penalty,
            exec_quality=exec_norm,
        )

    @property
    def champion(self) -> ShadowParams:
        """현재 챔피언을 반환한다."""
        return self._champion

    @property
    def shadow_count(self) -> int:
        """Shadow 수를 반환한다."""
        return len(self._shadows)

    @property
    def performances(self) -> dict[str, ShadowPerformance]:
        """전체 성과를 반환한다."""
        return self._performances.copy()

    def get_top_shadows(self, n: int = 3) -> list[tuple[str, ShadowPerformance]]:
        """상위 N개 Shadow를 반환한다."""
        ranked = sorted(
            self._performances.items(),
            key=lambda x: x[1].total_pnl,
            reverse=True,
        )
        return ranked[:n]
