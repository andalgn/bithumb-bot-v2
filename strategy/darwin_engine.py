"""Darwinian 자가 학습 엔진.

Shadow 20~30개 병렬 추적 + 주간 토너먼트 + 챔피언 교체.
DARWINIAN_SPEC.md 기반.
"""

from __future__ import annotations

import copy
import logging
import random
import time
import uuid
from dataclasses import dataclass

from app.data_types import MarketSnapshot, Signal, Tier

logger = logging.getLogger(__name__)

# 수수료 + 슬리피지 보정
FEE_PCT = 0.005
SLIPPAGE_BY_TIER: dict[Tier, float] = {
    Tier.TIER1: 0.0005,
    Tier.TIER2: 0.001,
    Tier.TIER3: 0.002,
}
SHADOW_DISCOUNT = 0.85  # Shadow net_pnl × 0.85 vs Live

# 돌연변이 범위
MUTATION_RANGES: dict[str, float] = {
    "rsi_lower": 3.0,
    "rsi_upper": 3.0,
    "atr_mult": 0.3,
    "cutoff": 5.0,
    "tp_pct": 0.005,
    "sl_pct": 0.005,
}

# Composite Score 가중치
COMPOSITE_WEIGHTS = {
    "expectancy": 0.30,
    "profit_factor": 0.20,
    "mdd": 0.20,
    "sharpe": 0.20,
    "exec_quality": 0.10,
}


@dataclass
class ShadowParams:
    """Shadow 파라미터 세트."""

    shadow_id: str = ""
    group: str = "conservative"  # conservative/moderate/innovative
    rsi_lower: float = 30.0
    rsi_upper: float = 70.0
    atr_mult: float = 2.0
    cutoff: float = 72.0
    tp_pct: float = 0.03
    sl_pct: float = 0.02


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
    max_drawdown: float = 0.0
    peak_equity: float = 0.0
    current_equity: float = 0.0

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
        """Profit Factor를 반환한다 (근사)."""
        if self.trade_count == 0:
            return 0.0
        if self.win_rate <= 0:
            return 0.0
        avg_win = self.total_pnl / max(self.win_count, 1) if self.total_pnl > 0 else 0
        avg_loss = abs(self.total_pnl) / max(self.trade_count - self.win_count, 1)
        if avg_loss <= 0:
            return 10.0
        loss_count = self.trade_count - self.win_count
        if loss_count <= 0:
            return 10.0
        return abs(avg_win * self.win_count) / abs(avg_loss * loss_count)


@dataclass
class CompositeScore:
    """Composite Score."""

    shadow_id: str
    score: float = 0.0
    expectancy: float = 0.0
    profit_factor: float = 0.0
    mdd: float = 0.0
    sharpe: float = 0.0
    exec_quality: float = 0.0


class DarwinEngine:
    """Darwinian 자가 학습 엔진."""

    def __init__(
        self,
        population_size: int = 20,
        champion_params: ShadowParams | None = None,
    ) -> None:
        """초기화.

        Args:
            population_size: Shadow 개수 (20~30).
            champion_params: 챔피언 파라미터. None이면 기본값.
        """
        self._pop_size = population_size
        self._champion = champion_params or ShadowParams(shadow_id="champion")
        self._shadows: list[ShadowParams] = []
        self._performances: dict[str, ShadowPerformance] = {}
        self._trades: list[ShadowTrade] = []
        # Shadow별 가상 오픈 포지션: {shadow_id: {symbol: entry_price}}
        self._open_positions: dict[str, dict[str, float]] = {}
        self._last_tournament: float = 0.0
        self._last_champion_change: float = 0.0
        self._champion_cooldown_days = 14
        self._initialize_population()

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

    def _mutate(
        self, base: ShadowParams, variation: float, group: str
    ) -> ShadowParams:
        """파라미터를 돌연변이시킨다."""
        params = copy.copy(base)
        params.group = group

        for name, max_delta in MUTATION_RANGES.items():
            base_val = getattr(base, name, None)
            if base_val is None:
                continue
            delta = random.uniform(-max_delta, max_delta) * (variation / 0.10)
            setattr(params, name, base_val + delta)

        # 범위 클램핑
        params.rsi_lower = max(15, min(45, params.rsi_lower))
        params.rsi_upper = max(55, min(85, params.rsi_upper))
        params.atr_mult = max(0.5, min(5.0, params.atr_mult))
        params.cutoff = max(40, min(95, params.cutoff))
        params.tp_pct = max(0.005, min(0.10, params.tp_pct))
        params.sl_pct = max(0.005, min(0.05, params.sl_pct))

        return params

    def record_cycle(
        self,
        snapshots: dict[str, MarketSnapshot],
        live_signals: list[Signal],
    ) -> int:
        """매 사이클마다 Shadow들의 '진입했을까?' 를 기록한다.

        Args:
            snapshots: 시장 스냅샷.
            live_signals: 챔피언이 생성한 실제 신호.

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

            # 1. 기존 오픈 포지션 평가 (이전 사이클 진입분)
            for sym in list(open_pos.keys()):
                snap = snapshots.get(sym)
                if not snap or snap.current_price <= 0:
                    continue
                entry = open_pos[sym]
                raw_pnl = (snap.current_price - entry) / entry
                slippage = SLIPPAGE_BY_TIER.get(Tier.TIER1, 0.001)
                virtual_pnl = raw_pnl - (FEE_PCT + slippage * 2)

                perf = self._performances[sid]
                perf.trade_count += 1
                perf.total_pnl += virtual_pnl
                if virtual_pnl > 0:
                    perf.win_count += 1
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

                if would_enter and signal.entry_price > 0:
                    open_pos[signal.symbol] = signal.entry_price

                count += 1

        # 오래된 trades 정리 (최근 10,000건만)
        if len(self._trades) > 10_000:
            self._trades = self._trades[-10_000:]

        return count

    def run_tournament(self, top_survive: int = 5) -> list[CompositeScore]:
        """주간 토너먼트를 실행한다.

        Args:
            top_survive: 생존 수.

        Returns:
            Composite Score 랭킹.
        """
        scores: list[CompositeScore] = []

        for shadow in self._shadows:
            perf = self._performances.get(shadow.shadow_id)
            if perf is None or perf.trade_count < 5:
                continue

            cs = self._calc_composite_score(shadow.shadow_id, perf)
            scores.append(cs)

        scores.sort(key=lambda s: s.score, reverse=True)

        # 상위 생존, 하위 변이
        survivors = scores[:top_survive]
        survivor_ids = {s.shadow_id for s in survivors}

        new_shadows = []
        for shadow in self._shadows:
            if shadow.shadow_id in survivor_ids:
                new_shadows.append(shadow)

        # 부족분을 상위 Shadow에서 변이 생성
        while len(new_shadows) < self._pop_size:
            parent = random.choice(new_shadows[:top_survive]) if new_shadows else self._champion
            child = self._mutate(parent, variation=0.15, group="moderate")
            child.shadow_id = str(uuid.uuid4())[:8]
            new_shadows.append(child)
            self._performances[child.shadow_id] = ShadowPerformance(
                shadow_id=child.shadow_id
            )

        self._shadows = new_shadows
        self._last_tournament = time.time()

        logger.info(
            "토너먼트 완료: 생존=%d, 새생성=%d",
            len(survivor_ids), self._pop_size - len(survivor_ids),
        )
        return scores

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
        if champ_perf is None or champ_perf.trade_count < 10:
            return None

        champ_score = self._calc_composite_score("champion", champ_perf)

        best_shadow = None
        best_score = champ_score.score

        for shadow in self._shadows:
            perf = self._performances.get(shadow.shadow_id)
            if perf is None or perf.trade_count < 10:
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
                best_shadow.shadow_id, best_score, champ_score.score,
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

    def _calc_composite_score(
        self, shadow_id: str, perf: ShadowPerformance
    ) -> CompositeScore:
        """Composite Score를 계산한다."""
        # 정규화 (0~1 범위로)
        exp_norm = min(1.0, max(0.0, perf.expectancy / 0.02 + 0.5))
        pf_norm = min(1.0, max(0.0, (perf.profit_factor - 0.5) / 3.0))
        mdd_norm = min(1.0, max(0.0, 1.0 - perf.max_drawdown / 0.20))
        # Sharpe 근사
        sharpe = perf.expectancy / 0.02 if perf.trade_count > 5 else 0
        sharpe_norm = min(1.0, max(0.0, (sharpe + 1) / 4))
        exec_norm = 0.5  # 기본값 (실제 체결 품질은 LIVE에서)

        score = (
            COMPOSITE_WEIGHTS["expectancy"] * exp_norm
            + COMPOSITE_WEIGHTS["profit_factor"] * pf_norm
            + COMPOSITE_WEIGHTS["mdd"] * mdd_norm
            + COMPOSITE_WEIGHTS["sharpe"] * sharpe_norm
            + COMPOSITE_WEIGHTS["exec_quality"] * exec_norm
        )

        return CompositeScore(
            shadow_id=shadow_id,
            score=score,
            expectancy=perf.expectancy,
            profit_factor=perf.profit_factor,
            mdd=perf.max_drawdown,
            sharpe=sharpe,
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
