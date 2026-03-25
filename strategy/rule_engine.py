"""전략 엔진 — 5국면 분류 + 전략 A/B/C/D 점수제 + Layer 1 환경 필터.

STRATEGY_SPEC.md 기반 구현.
국면: CRISIS / STRONG_UP / WEAK_UP / WEAK_DOWN / RANGE (판정 우선순위순).
전략: A(추세추종), B(반전포착), C(브레이크아웃), D(스캘핑), E(DCA).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

import numpy as np

from app.data_types import (
    MarketSnapshot,
    OrderSide,
    Regime,
    Signal,
    Strategy,
    Tier,
)
from strategy.coin_profiler import CoinProfiler, TierParams
from strategy.environment_filter import EnvironmentFilter
from strategy.indicators import IndicatorPack, compute_indicators
from strategy.regime_classifier import AuxFlags as AuxFlags  # re-export for backward compat
from strategy.regime_classifier import RegimeClassifier
from strategy.regime_classifier import RegimeState as RegimeState  # re-export for backward compat
from strategy.strategy_scorer import ScoreResult as ScoreResult  # re-export for backward compat
from strategy.strategy_scorer import StrategyScorer

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

# ─── 국면별 전략 허용 매핑 ───
REGIME_STRATEGY_MAP: dict[Regime, list[Strategy]] = {
    Regime.STRONG_UP: [Strategy.TREND_FOLLOW, Strategy.MEAN_REVERSION],  # A+B (심야 Tier3은 L1에서 차단)
    Regime.WEAK_UP: [Strategy.MEAN_REVERSION],  # B
    Regime.RANGE: [Strategy.MEAN_REVERSION],  # B
    Regime.WEAK_DOWN: [Strategy.MEAN_REVERSION, Strategy.DCA],  # B + E
    Regime.CRISIS: [Strategy.DCA],
}

# 국면별 포지션 배수
REGIME_POSITION_MULT: dict[Regime, float] = {
    Regime.STRONG_UP: 1.5,
    Regime.WEAK_UP: 1.0,
    Regime.RANGE: 1.0,
    Regime.WEAK_DOWN: 0.6,
    Regime.CRISIS: 0.0,
}

# 전략 → 점수 그룹 매핑
STRATEGY_GROUP: dict[Strategy, int] = {
    Strategy.TREND_FOLLOW: 1,
    Strategy.MEAN_REVERSION: 1,
    Strategy.BREAKOUT: 2,
    Strategy.SCALPING: 2,
    Strategy.DCA: 3,
}

# ─── 컷오프 판정 ───
class SizeDecision:
    """Full / Probe / HOLD 판정."""

    FULL = "FULL"
    PROBE = "PROBE"
    HOLD = "HOLD"


_NON_PARAM_KEYS = {"regime_override", "enabled"}


def _merge_strategy_params(
    sp: dict,
    tier: int,
    regime: str,
) -> dict:
    """전략 파라미터를 base < tier < regime 우선순위로 병합한다."""
    tier_key = f"tier{tier}"
    tier_sp = sp.get(tier_key, {})
    regime_sp = sp.get("regime_override", {}).get(regime, {})
    # regime_override, enabled, tier 키 자체는 결과에서 제외
    base = {k: v for k, v in sp.items() if k not in _NON_PARAM_KEYS and not k.startswith("tier")}
    return {**base, **tier_sp, **regime_sp}


class RuleEngine:
    """전략 엔진 — 5국면 + 전략 점수 + Layer 1."""

    def __init__(
        self,
        profiler: CoinProfiler | None = None,
        score_cutoff: object | None = None,
        regime_config: object | None = None,
        execution_config: object | None = None,
        strategy_params: dict | None = None,
    ) -> None:
        """초기화.

        Args:
            profiler: 코인 프로파일러.
            score_cutoff: ScoreCutoffConfig.
            regime_config: RegimeConfig.
            execution_config: ExecutionConfig.
            strategy_params: 전략별 SL/TP 파라미터.
        """
        self._profiler = profiler or CoinProfiler()
        self._score_cutoff = score_cutoff
        self._regime_config = regime_config
        self._exec_config = execution_config
        self._strategy_params = strategy_params or {}
        self._regime_classifier = RegimeClassifier()
        self._environment_filter = EnvironmentFilter()
        self._strategy_scorer = StrategyScorer(strategy_params=self._strategy_params)

    def _get_regime_state(self, symbol: str) -> RegimeState:
        """코인별 국면 상태를 가져온다."""
        return self._regime_classifier.get_state(symbol)

    def _get_weights(self, strategy: str) -> dict[str, float]:
        """전략의 점수 가중치를 반환한다. StrategyScorer에 위임한다."""
        return self._strategy_scorer._get_weights(strategy)

    # ═══════════════════════════════════════════
    # 국면 분류
    # ═══════════════════════════════════════════

    def classify_regime(
        self, symbol: str, ind_1h: IndicatorPack, candles_1h_close: np.ndarray
    ) -> tuple[Regime, AuxFlags]:
        """1H 지표 기반 국면을 판정한다 (히스테리시스 적용).

        Args:
            symbol: 코인 심볼.
            ind_1h: 1H 지표 패키지.
            candles_1h_close: 1H 종가 배열.

        Returns:
            (Regime, AuxFlags) 튜플.
        """
        return self._regime_classifier.classify(symbol, ind_1h, candles_1h_close)  # type: ignore[return-value]

    def _raw_classify(self, ind: IndicatorPack, close: np.ndarray) -> Regime:
        """히스테리시스 없이 순수 국면을 판정한다."""
        return self._regime_classifier.raw_classify(ind, close)

    def _detect_aux_flags(self, ind: IndicatorPack, close: np.ndarray) -> AuxFlags:
        """보조 플래그를 감지한다."""
        return self._regime_classifier.detect_aux_flags(ind, close)

    # ═══════════════════════════════════════════
    # Layer 1: 환경 필터
    # ═══════════════════════════════════════════

    def _check_layer1(
        self,
        regime: Regime,
        snap: MarketSnapshot,
        ind_15m: IndicatorPack,
        tier_params: TierParams,
    ) -> tuple[bool, str]:
        """Layer 1 환경 필터를 적용한다.

        Returns:
            (통과 여부, 거부 사유).
        """
        return self._environment_filter.check(regime, snap, ind_15m, tier_params)

    # ═══════════════════════════════════════════
    # 전략 점수 계산 (Layer 2)
    # ═══════════════════════════════════════════

    def _score_strategy_a(
        self,
        ind_15m: IndicatorPack,
        ind_1h: IndicatorPack,
        candles_15m: list | None = None,
    ) -> ScoreResult:
        """전략 A 추세추종 점수를 계산한다. StrategyScorer에 위임한다."""
        return self._strategy_scorer.score_strategy_a(ind_15m, ind_1h, candles_15m)

    def _score_strategy_b(
        self,
        ind_15m: IndicatorPack,
        candles_15m: list | None = None,
    ) -> ScoreResult:
        """전략 B 반전포착 점수를 계산한다. StrategyScorer에 위임한다."""
        return self._strategy_scorer.score_strategy_b(ind_15m, candles_15m)

    def _score_strategy_c(
        self, ind_15m: IndicatorPack, ind_1h: IndicatorPack, candles_15m: list
    ) -> ScoreResult:
        """전략 C 브레이크아웃 점수를 계산한다. StrategyScorer에 위임한다."""
        return self._strategy_scorer.score_strategy_c(ind_15m, ind_1h, candles_15m)

    def _score_strategy_d(
        self, ind_15m: IndicatorPack, ind_1h: IndicatorPack, snap: MarketSnapshot
    ) -> ScoreResult:
        """전략 D 스캘핑 점수를 계산한다. StrategyScorer에 위임한다."""
        return self._strategy_scorer.score_strategy_d(ind_15m, ind_1h, snap)

    def _score_strategy_e(
        self,
        ind_1h: IndicatorPack,
        symbol: str,
        current_price: float = 0.0,
    ) -> ScoreResult:
        """전략 E DCA 매집 점수를 계산한다. StrategyScorer에 위임한다."""
        return self._strategy_scorer.score_strategy_e(ind_1h, symbol, current_price)

    def _score_volume(self, ind: IndicatorPack, threshold: float, max_pts: float) -> float:
        """거래량 점수를 계산한다 (OBV 증분 기반 간접). StrategyScorer 모듈 함수에 위임한다."""
        from strategy.strategy_scorer import _score_volume as _sv
        return _sv(ind, threshold, max_pts)

    @staticmethod
    def _score_volume_direct(candles: list, threshold: float, max_pts: float) -> float:
        """실제 캔들 거래량을 직접 비교하여 점수를 계산한다. StrategyScorer 모듈 함수에 위임한다."""
        from strategy.strategy_scorer import _score_volume_direct as _svd
        return _svd(candles, threshold, max_pts)

    # ═══════════════════════════════════════════
    # 컷오프 판정
    # ═══════════════════════════════════════════

    def _decide_size(self, strategy: Strategy, score: float) -> str:
        """3그룹 컷오프 판정."""
        group = STRATEGY_GROUP.get(strategy, 1)

        if self._score_cutoff:
            if group == 1:
                g = self._score_cutoff.group1
            elif group == 2:
                g = self._score_cutoff.group2
            else:
                g = self._score_cutoff.group3
            full = g.full
            probe_min = g.probe_min
        else:
            # 기본값 (config.yaml과 동일)
            if group == 1:
                full, probe_min = 75, 60
            elif group == 2:
                full, probe_min = 80, 65
            else:
                full, probe_min = 75, 68

        if score >= full:
            return SizeDecision.FULL
        if score >= probe_min:
            return SizeDecision.PROBE
        return SizeDecision.HOLD

    # ═══════════════════════════════════════════
    # 메인 신호 생성
    # ═══════════════════════════════════════════

    def generate_signals(
        self,
        snapshots: dict[str, MarketSnapshot],
        paper_test: bool = False,
    ) -> list[Signal]:
        """스냅샷에서 매매 신호를 생성한다.

        Args:
            snapshots: 코인별 MarketSnapshot.
            paper_test: True이면 임시 RSI 테스트 전략 사용.

        Returns:
            Signal 리스트.
        """
        if paper_test:
            return self._generate_test_signals(snapshots)

        signals: list[Signal] = []

        for symbol, snap in snapshots.items():
            if not snap.candles_15m or len(snap.candles_15m) < 30:
                continue
            if not snap.candles_1h or len(snap.candles_1h) < 30:
                continue

            # 지표 계산 (15M + 1H 이중)
            ind_15m = compute_indicators(snap.candles_15m)
            ind_1h = compute_indicators(snap.candles_1h)
            close_1h = np.array([c.close for c in snap.candles_1h], dtype=np.float64)

            # 국면 분류
            regime, aux = self.classify_regime(symbol, ind_1h, close_1h)

            # Tier 확인
            tier_params = self._profiler.get_tier(symbol)

            # 국면/Tier 로깅 (4사이클마다)
            rsi_15m = self._last_valid(ind_15m.rsi)
            logger.debug(
                "%s 국면=%s Tier=%d RSI=%.1f 가격=%.0f%s%s",
                symbol,
                regime.value,
                tier_params.tier.value,
                rsi_15m,
                snap.current_price,
                " [RV]" if aux.range_volatile else "",
                " [DA]" if aux.down_accel else "",
            )

            # 해당 국면에서 허용되는 전략들
            allowed = REGIME_STRATEGY_MAP.get(regime, [])

            # Layer 1 환경 필터 (CRISIS에서 DCA만 예외 허용)
            l1_pass, l1_reason = self._check_layer1(regime, snap, ind_15m, tier_params)
            if not l1_pass:
                if regime == Regime.CRISIS and Strategy.DCA in allowed:
                    allowed = [Strategy.DCA]
                else:
                    logger.debug("%s L1 거부: %s", symbol, l1_reason)
                    continue
            best_signal = self._evaluate_strategies(
                symbol,
                snap,
                regime,
                aux,
                tier_params,
                allowed,
                ind_15m,
                ind_1h,
            )
            if best_signal:
                signals.append(best_signal)

        return signals

    def _evaluate_strategies(
        self,
        symbol: str,
        snap: MarketSnapshot,
        regime: Regime,
        aux: AuxFlags,
        tier_params: TierParams,
        allowed: list[Strategy],
        ind_15m: IndicatorPack,
        ind_1h: IndicatorPack,
    ) -> Signal | None:
        """허용된 전략들의 점수를 계산하고 최고점 신호를 반환한다."""
        results: list[ScoreResult] = []

        # 대형 코인(BTC) 보수적 점수 조정 배수
        large_cap_penalty = 0.75 if symbol == "BTC" else 1.0

        for strat in allowed:
            if strat == Strategy.TREND_FOLLOW:
                sr = self._score_strategy_a(ind_15m, ind_1h, snap.candles_15m)
                # WEAK_UP이면 보수적 (점수 0.8배)
                if regime == Regime.WEAK_UP:
                    sr = ScoreResult(
                        strategy=sr.strategy,
                        score=sr.score * 0.8,
                        detail=sr.detail,
                    )
                # BTC는 추세추종 점수 0.75배 (높은 컷오프 요구)
                if large_cap_penalty < 1.0:
                    sr = ScoreResult(
                        strategy=sr.strategy,
                        score=sr.score * large_cap_penalty,
                        detail=sr.detail,
                    )
                results.append(sr)

            elif strat == Strategy.MEAN_REVERSION:
                # BTC는 반전포착 제외 (백테스트 0% 승률)
                if symbol == "BTC":
                    continue
                sr = self._score_strategy_b(ind_15m, snap.candles_15m)
                # DOWN_ACCEL이면 점수 0.4배
                if aux.down_accel:
                    sr = ScoreResult(
                        strategy=sr.strategy,
                        score=sr.score * 0.4,
                        detail=sr.detail,
                    )
                # RANGE_VOLATILE이면 half
                if aux.range_volatile and regime == Regime.RANGE:
                    sr = ScoreResult(
                        strategy=sr.strategy,
                        score=sr.score * 0.5,
                        detail=sr.detail,
                    )
                results.append(sr)

            elif strat == Strategy.BREAKOUT:
                # RANGE_VOLATILE + Tier3이면 스킵
                if aux.range_volatile and tier_params.tier == Tier.TIER3:
                    continue
                sr = self._score_strategy_c(ind_15m, ind_1h, snap.candles_15m)
                # BTC 보수적 조정
                if large_cap_penalty < 1.0:
                    sr = ScoreResult(
                        strategy=sr.strategy,
                        score=sr.score * large_cap_penalty,
                        detail=sr.detail,
                    )
                results.append(sr)

            elif strat == Strategy.SCALPING:
                sr = self._score_strategy_d(ind_15m, ind_1h, snap)
                results.append(sr)

            elif strat == Strategy.DCA:
                sr = self._score_strategy_e(ind_1h, symbol, snap.current_price)
                results.append(sr)

        if not results:
            return None

        # 전략별 점수 로깅
        for sr in results:
            logger.debug(
                "%s 전략=%s 점수=%.0f %s",
                symbol,
                sr.strategy.value,
                sr.score,
                sr.detail,
            )

        # 최고 점수 선택
        best = max(results, key=lambda r: r.score)
        decision = self._decide_size(best.strategy, best.score)
        if decision == SizeDecision.HOLD:
            logger.debug(
                "%s HOLD: %s %.0f점 (컷오프 미달)",
                symbol,
                best.strategy.value,
                best.score,
            )
            return None

        # SL/TP 계산
        price = snap.current_price
        if price <= 0:
            return None

        atr_val = self._last_valid(ind_15m.atr)
        if np.isnan(atr_val) or atr_val <= 0:
            atr_val = price * 0.02

        sl_mult = tier_params.atr_stop_mult

        # Tier별 SL 최대 비율 상한
        max_sl_pct = {Tier.TIER1: 0.030, Tier.TIER2: 0.050, Tier.TIER3: 0.080}
        sp = self._strategy_params.get(best.strategy.value, {})
        merged_sp = _merge_strategy_params(sp, tier=tier_params.tier.value, regime=regime.value)
        sl_cap = price * max_sl_pct.get(tier_params.tier, 0.025)

        if best.strategy == Strategy.SCALPING:
            stop_loss = price * (1 - merged_sp.get("sl_pct", 0.008))
            take_profit = price * (1 + merged_sp.get("tp_pct", 0.015))
        elif best.strategy == Strategy.DCA:
            stop_loss = price * (1 - merged_sp.get("sl_pct", 0.03))
            take_profit = price * (1 + merged_sp.get("tp_pct", 0.05))
        else:
            sl_m = merged_sp.get("sl_mult", sl_mult)
            tp_r = merged_sp.get("tp_rr", 2.5)
            sl_dist = min(atr_val * sl_m, sl_cap)
            stop_loss = price - sl_dist
            take_profit = price + sl_dist * tp_r

        return Signal(
            symbol=symbol,
            direction=OrderSide.BUY,
            strategy=best.strategy,
            score=best.score,
            regime=regime,
            tier=tier_params.tier,
            entry_price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            timestamp=int(time.time() * 1000),
        )

    # ─── 유틸 ───

    @staticmethod
    def _last_valid(arr: np.ndarray) -> float:
        """배열에서 마지막 유효값을 반환한다."""
        return RegimeClassifier._last_valid(arr)

    def get_regime(self, symbol: str) -> Regime:
        """코인의 현재 국면을 반환한다."""
        state = self._regime_classifier.get_state(symbol)
        return state.current if state else Regime.RANGE

    # ═══════════════════════════════════════════
    # PAPER 테스트용 간단 RSI 전략
    # ═══════════════════════════════════════════

    def _generate_test_signals(
        self,
        snapshots: dict[str, MarketSnapshot],
    ) -> list[Signal]:
        """PAPER 테스트용 RSI 기반 간단 시그널을 생성한다.

        RSI < 45이면 매수 시그널. SL -0.3%, TP +0.5%.
        최대 3개 시그널만 반환 (가장 낮은 RSI 순).
        """
        candidates: list[tuple[float, Signal]] = []

        for symbol, snap in snapshots.items():
            if not snap.candles_15m or len(snap.candles_15m) < 30:
                continue
            price = snap.current_price
            if price <= 0:
                continue

            ind_15m = compute_indicators(snap.candles_15m)
            rsi = self._last_valid(ind_15m.rsi)
            if rsi <= 0 or np.isnan(rsi):
                continue

            if rsi < 45:
                atr = self._last_valid(ind_15m.atr)
                if atr <= 0 or np.isnan(atr):
                    atr = price * 0.01

                tier = self._profiler.get_tier(symbol).tier
                signal = Signal(
                    symbol=symbol,
                    direction=OrderSide.BUY,
                    strategy=Strategy.MEAN_REVERSION,
                    score=75.0,
                    regime=Regime.RANGE,
                    tier=tier,
                    entry_price=price,
                    stop_loss=price * 0.997,  # -0.3%
                    take_profit=price * 1.005,  # +0.5%
                    timestamp=int(time.time() * 1000),
                )
                candidates.append((rsi, signal))
                logger.info(
                    "[TEST] %s RSI=%.1f 가격=%.0f → 시그널 후보",
                    symbol,
                    rsi,
                    price,
                )

        # RSI 낮은 순으로 최대 3개
        candidates.sort(key=lambda x: x[0])
        return [sig for _, sig in candidates[:3]]

    # ═══════════════════════════════════════════
    # Public accessors (Phase 2 리팩토링용)
    # ═══════════════════════════════════════════

    @property
    def strategy_params(self) -> dict:
        """현재 전략 파라미터를 반환한다."""
        return self._strategy_params

    def get_regime_state(self, symbol: str) -> "RegimeState":
        """코인별 국면 상태를 반환한다. 없으면 초기화하여 반환한다."""
        return self._get_regime_state(symbol)

    @property
    def regime_states(self) -> dict:
        """전체 국면 상태 dict를 반환한다."""
        return self._regime_classifier.states

    @property
    def _regime_states(self) -> dict:
        """_regime_states 하위 호환 프로퍼티 — regime_classifier.states를 반환한다."""
        return self._regime_classifier.states

    def decide_size_public(self, strategy: "Strategy", score: float) -> str:
        """사이즈 결정을 public으로 위임한다."""
        return self._decide_size(strategy, score)
