"""국면 분류기 — 히스테리시스 적용 국면 판정.

RuleEngine에서 분리된 국면 분류 전담 클래스.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.data_types import Regime
from strategy.indicators import IndicatorPack


@dataclass
class AuxFlags:
    """보조 플래그."""

    range_volatile: bool = False
    down_accel: bool = False


@dataclass
class RegimeState:
    """코인별 국면 상태 (히스테리시스)."""

    current: Regime = Regime.RANGE
    pending: Regime | None = None
    confirm_count: int = 0
    cooldown_remaining: int = 0
    crisis_release_count: int = 0


class RegimeClassifier:
    """히스테리시스 적용 국면 분류기."""

    def __init__(self) -> None:
        """초기화."""
        self._regime_states: dict[str, RegimeState] = {}

    def _get_state(self, symbol: str) -> RegimeState:
        """코인별 국면 상태를 가져온다."""
        if symbol not in self._regime_states:
            self._regime_states[symbol] = RegimeState()
        return self._regime_states[symbol]

    def classify(
        self, symbol: str, ind: IndicatorPack, close: np.ndarray
    ) -> tuple[Regime, AuxFlags]:
        """히스테리시스 적용 최종 국면을 반환한다.

        Args:
            symbol: 코인 심볼.
            ind: 1H 지표 패키지.
            close: 1H 종가 배열.

        Returns:
            (Regime, AuxFlags) 튜플.
        """
        state = self._get_state(symbol)
        raw_regime = self.raw_classify(ind, close)
        aux = self.detect_aux_flags(ind, close)

        # CRISIS 즉시 진입
        if raw_regime == Regime.CRISIS:
            state.current = Regime.CRISIS
            state.pending = None
            state.confirm_count = 0
            state.cooldown_remaining = 0
            state.crisis_release_count = 0
            return state.current, aux

        # CRISIS 해제: 6봉 연속 정상 확인
        if state.current == Regime.CRISIS:
            if raw_regime != Regime.CRISIS:
                state.crisis_release_count += 1
                if state.crisis_release_count >= 6:
                    state.current = raw_regime
                    state.crisis_release_count = 0
                    state.cooldown_remaining = 6
            else:
                state.crisis_release_count = 0
            return state.current, aux

        # 쿨다운 중이면 전환 안 함
        if state.cooldown_remaining > 0:
            state.cooldown_remaining -= 1
            return state.current, aux

        # 같은 국면이면 리셋
        if raw_regime == state.current:
            state.pending = None
            state.confirm_count = 0
            return state.current, aux

        # 히스테리시스: 3봉 확인
        if raw_regime == state.pending:
            state.confirm_count += 1
            if state.confirm_count >= 3:
                state.current = raw_regime
                state.pending = None
                state.confirm_count = 0
                state.cooldown_remaining = 6  # 재전환 금지
        else:
            state.pending = raw_regime
            state.confirm_count = 1

        return state.current, aux

    def raw_classify(self, ind: IndicatorPack, close: np.ndarray) -> Regime:
        """히스테리시스 없는 원시 국면을 반환한다.

        Args:
            ind: 지표 패키지.
            close: 종가 배열.

        Returns:
            Regime 국면.
        """
        n = len(close)
        if n < 25:
            return Regime.RANGE

        # 필요 지표 최신값
        adx_val = self._last_valid(ind.adx.adx) if ind.adx else 0.0
        plus_di = self._last_valid(ind.adx.plus_di) if ind.adx else 0.0
        minus_di = self._last_valid(ind.adx.minus_di) if ind.adx else 0.0
        ema20 = self._last_valid(ind.ema20)
        ema50 = self._last_valid(ind.ema50)
        ema200 = self._last_valid(ind.ema200)
        atr_now = self._last_valid(ind.atr)

        # ATR 20일 평균 (480봉 = 20일 × 24봉)
        valid_atr = ind.atr[~np.isnan(ind.atr)]
        atr_20d_avg = float(np.mean(valid_atr[-480:])) if len(valid_atr) > 0 else atr_now

        # 24H 가격변동률
        if n >= 24:
            price_change_24h = (close[-1] - close[-24]) / close[-24]
        else:
            price_change_24h = 0.0

        # 1. CRISIS
        if atr_20d_avg > 0 and atr_now > atr_20d_avg * 2.5 and price_change_24h < -0.10:
            return Regime.CRISIS

        # 2. STRONG_UP
        if ema20 > ema50 > ema200 and adx_val > 25 and plus_di > minus_di:
            return Regime.STRONG_UP

        # 3. WEAK_UP
        if ema20 > ema50 and 20 <= adx_val <= 25 and plus_di > minus_di:
            return Regime.WEAK_UP

        # 4. WEAK_DOWN
        if ema20 < ema50 and minus_di > plus_di:
            return Regime.WEAK_DOWN

        # 5. RANGE
        return Regime.RANGE

    def detect_aux_flags(self, ind: IndicatorPack, close: np.ndarray) -> AuxFlags:
        """보조 플래그를 감지한다."""
        adx_val = self._last_valid(ind.adx.adx) if ind.adx else 0.0
        plus_di = self._last_valid(ind.adx.plus_di) if ind.adx else 0.0
        minus_di = self._last_valid(ind.adx.minus_di) if ind.adx else 0.0
        ema20 = self._last_valid(ind.ema20)
        ema50 = self._last_valid(ind.ema50)
        ema200 = self._last_valid(ind.ema200)
        atr_now = self._last_valid(ind.atr)

        valid_atr = ind.atr[~np.isnan(ind.atr)]
        atr_20d_avg = float(np.mean(valid_atr[-480:])) if len(valid_atr) > 0 else atr_now

        range_volatile = adx_val < 20 and atr_20d_avg > 0 and atr_now > atr_20d_avg * 1.2
        down_accel = ema20 < ema50 < ema200 and adx_val > 22 and minus_di > plus_di

        return AuxFlags(range_volatile=range_volatile, down_accel=down_accel)

    def get_state(self, symbol: str) -> RegimeState:
        """코인별 국면 상태를 반환한다. 없으면 초기화하여 반환한다.

        Args:
            symbol: 코인 심볼.

        Returns:
            RegimeState (없으면 새로 생성).
        """
        return self._get_state(symbol)

    @property
    def states(self) -> dict:
        """전체 국면 상태를 반환한다."""
        return self._regime_states

    @staticmethod
    def _last_valid(arr: np.ndarray) -> float:
        """배열에서 마지막 유효값을 반환한다."""
        if arr is None or len(arr) == 0:
            return 0.0
        for i in range(len(arr) - 1, -1, -1):
            if not np.isnan(arr[i]):
                return float(arr[i])
        return 0.0
