"""승격/강등 시스템.

Active → Core 승격, 보호기간, Core 정상 운영, 강등, 추가매수.
PROMOTION_SPEC.md 기반.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

import numpy as np

from app.data_types import Candle, Pool, Position, Regime, Tier
from strategy.indicators import IndicatorPack
from strategy.pool_manager import PoolManager

logger = logging.getLogger(__name__)


class CorePhase(str, Enum):
    """Core 포지션 단계."""

    PROTECTION = "protection"  # 보호기간 (2봉)
    NORMAL = "normal"  # 정상 운영
    DEMOTED = "demoted"  # 강등됨


@dataclass
class CorePosition:
    """Core 포지션 상태."""

    symbol: str
    position: Position
    phase: CorePhase = CorePhase.PROTECTION
    protection_bars: int = 0  # 보호기간 경과 봉 수
    bars_since_promotion: int = 0  # 승격 후 경과 봉 수
    original_stop_loss: float = 0.0  # Active 시절 손절가
    core_stop_loss: float = 0.0  # Core 확대 손절가
    additional_buy_done: bool = False  # 추가매수 완료 여부
    demotion_bar_count: int = 0  # 강등 후 재승격 검증 봉 수
    partial_exit_1: bool = False  # +3% 부분청산 완료
    partial_exit_2: bool = False  # +6% 부분청산 완료


class PromotionManager:
    """승격/강등 관리자."""

    def __init__(
        self,
        pool_manager: PoolManager,
        profit_pct: float = 0.012,
        profit_hold_bars: int = 2,
        adx_min: int = 20,
        protection_bars: int = 2,
        dca_wait_bars: int = 4,
        dca_rescore_min: int = 55,
        dca_profit_min: float = 0.02,
        dca_max_per_position: int = 1,
        re_promotion_verify_bars: int = 6,
    ) -> None:
        """초기화.

        Args:
            pool_manager: 풀 관리자.
            profit_pct: 승격 수익 조건.
            profit_hold_bars: 수익 유지 봉 수.
            adx_min: 승격 ADX 최소값.
            protection_bars: 보호기간 봉 수.
            dca_wait_bars: 추가매수 대기 봉 수.
            dca_rescore_min: 추가매수 최소 점수.
            dca_profit_min: 추가매수 최소 수익률.
            dca_max_per_position: 포지션당 추가매수 최대 횟수.
            re_promotion_verify_bars: 강등 후 재승격 검증 봉 수.
        """
        self._pool = pool_manager
        self._profit_pct = profit_pct
        self._profit_hold_bars = profit_hold_bars
        self._adx_min = adx_min
        self._protection_bars = protection_bars
        self._dca_wait_bars = dca_wait_bars
        self._dca_rescore_min = dca_rescore_min
        self._dca_profit_min = dca_profit_min
        self._dca_max = dca_max_per_position
        self._re_promo_bars = re_promotion_verify_bars

        # Core 포지션 추적
        self._core_positions: dict[str, CorePosition] = {}
        # 강등된 코인의 재승격 대기 카운터
        self._demotion_cooldown: dict[str, int] = {}
        # 수익 유지 카운터 (승격 전)
        self._profit_hold_count: dict[str, int] = {}

    def check_promotion(
        self,
        position: Position,
        current_price: float,
        ind_1h: IndicatorPack,
        regime: Regime,
    ) -> bool:
        """승격 조건을 확인한다.

        Args:
            position: Active 포지션.
            current_price: 현재 가격.
            ind_1h: 1H 지표.
            regime: 현재 국면.

        Returns:
            승격 가능 여부.
        """
        symbol = position.symbol

        # Tier 3 승격 불가
        if position.tier == Tier.TIER3:
            return False

        # STRONG_UP/WEAK_UP에서만 승격
        if regime not in (Regime.STRONG_UP, Regime.WEAK_UP):
            return False

        # 강등 후 재승격 쿨다운
        if symbol in self._demotion_cooldown:
            if self._demotion_cooldown[symbol] < self._re_promo_bars:
                self._demotion_cooldown[symbol] += 1
                return False
            else:
                del self._demotion_cooldown[symbol]

        # 수익 +1.2% 이상
        if position.entry_price <= 0:
            return False
        pnl_pct = (current_price - position.entry_price) / position.entry_price
        if pnl_pct < self._profit_pct:
            self._profit_hold_count.pop(symbol, None)
            return False

        # 2봉 유지
        self._profit_hold_count.setdefault(symbol, 0)
        self._profit_hold_count[symbol] += 1
        if self._profit_hold_count[symbol] < self._profit_hold_bars:
            return False

        # ADX > 20
        if ind_1h.adx:
            adx_val = self._last_valid(ind_1h.adx.adx)
            if adx_val < self._adx_min:
                return False

        # 1H EMA20 위
        ema20 = self._last_valid(ind_1h.ema20)
        if current_price < ema20:
            return False

        return True

    def promote(
        self,
        position: Position,
        ind_1h: IndicatorPack,
    ) -> CorePosition | None:
        """포지션을 승격한다 (Active → Core).

        Args:
            position: Active 포지션.
            ind_1h: 1H 지표.

        Returns:
            CorePosition 또는 None.
        """
        # Pool 이관
        success = self._pool.transfer(Pool.ACTIVE, Pool.CORE, position.size_krw)
        if not success:
            return None

        # Core 손절선 계산: 1H ATR × 2.5, Active 손절폭의 2배 이내
        atr_1h = self._last_valid(ind_1h.atr)
        if atr_1h <= 0:
            atr_1h = position.entry_price * 0.02

        original_sl_width = abs(position.entry_price - position.stop_loss)
        core_sl_width = min(atr_1h * 2.5, original_sl_width * 2)
        core_stop_loss = position.entry_price - core_sl_width

        position.pool = Pool.CORE
        position.promoted = True

        core_pos = CorePosition(
            symbol=position.symbol,
            position=position,
            phase=CorePhase.PROTECTION,
            protection_bars=0,
            bars_since_promotion=0,
            original_stop_loss=position.stop_loss,
            core_stop_loss=core_stop_loss,
        )

        self._core_positions[position.symbol] = core_pos
        self._profit_hold_count.pop(position.symbol, None)

        logger.info(
            "승격: %s Active→Core, SL: %.0f→%.0f",
            position.symbol, position.stop_loss, core_stop_loss,
        )
        position.stop_loss = core_stop_loss
        return core_pos

    def update_core_positions(
        self,
        current_prices: dict[str, float],
        indicators_1h: dict[str, IndicatorPack],
        regimes: dict[str, Regime],
    ) -> list[str]:
        """Core 포지션들을 업데이트한다.

        Args:
            current_prices: 코인별 현재 가격.
            indicators_1h: 코인별 1H 지표.
            regimes: 코인별 국면.

        Returns:
            강등된 코인 심볼 리스트.
        """
        demoted: list[str] = []

        for symbol in list(self._core_positions.keys()):
            cp = self._core_positions[symbol]
            price = current_prices.get(symbol, 0)
            if price <= 0:
                continue

            cp.bars_since_promotion += 1

            # 보호기간
            if cp.phase == CorePhase.PROTECTION:
                cp.protection_bars += 1
                # 손절선 이탈 → 즉시 청산
                if price < cp.core_stop_loss:
                    logger.warning("보호기간 손절: %s @ %.0f < SL %.0f",
                                   symbol, price, cp.core_stop_loss)
                    demoted.append(symbol)
                    continue
                # 보호기간 종료
                if cp.protection_bars >= self._protection_bars:
                    cp.phase = CorePhase.NORMAL
                    logger.info("보호기간 종료 → Core 정상: %s", symbol)

            elif cp.phase == CorePhase.NORMAL:
                ind = indicators_1h.get(symbol)
                regime = regimes.get(symbol, Regime.RANGE)

                # 강등 체크: EMA20 이탈 또는 국면 악화
                if ind:
                    ema20 = self._last_valid(ind.ema20)
                    if price < ema20:
                        logger.info("강등 (EMA20 이탈): %s", symbol)
                        demoted.append(symbol)
                        continue

                if regime not in (Regime.STRONG_UP, Regime.WEAK_UP):
                    logger.info("강등 (국면 악화→%s): %s", regime.value, symbol)
                    demoted.append(symbol)
                    continue

                # 손절선 이탈
                if price < cp.core_stop_loss:
                    logger.warning("Core 손절: %s @ %.0f < SL %.0f",
                                   symbol, price, cp.core_stop_loss)
                    demoted.append(symbol)
                    continue

        # 강등 처리
        for symbol in demoted:
            self._demote(symbol)

        return demoted

    def _demote(self, symbol: str) -> None:
        """포지션을 강등한다 (Core → Active)."""
        cp = self._core_positions.pop(symbol, None)
        if cp is None:
            return

        pos = cp.position
        self._pool.transfer(Pool.CORE, Pool.ACTIVE, pos.size_krw)
        pos.pool = Pool.ACTIVE
        pos.stop_loss = cp.original_stop_loss

        self._demotion_cooldown[symbol] = 0
        logger.info("강등 완료: %s Core→Active, SL 복원: %.0f", symbol, pos.stop_loss)

    def check_additional_buy(
        self,
        symbol: str,
        current_price: float,
        rescore: float,
        candles_15m: list[Candle],
    ) -> bool:
        """추가매수 조건을 확인한다.

        Args:
            symbol: 코인 심볼.
            current_price: 현재 가격.
            rescore: 재평가 점수.
            candles_15m: 15M 캔들 (VWAP 계산용).

        Returns:
            추가매수 가능 여부.
        """
        cp = self._core_positions.get(symbol)
        if cp is None or cp.phase != CorePhase.NORMAL:
            return False

        # 이미 추가매수 완료
        if cp.additional_buy_done:
            return False

        # 4봉 경과
        if cp.bars_since_promotion < self._dca_wait_bars:
            return False

        # 재평가 점수 >= 55
        if rescore < self._dca_rescore_min:
            return False

        # 수익 >= +2%
        pos = cp.position
        if pos.entry_price <= 0:
            return False
        pnl_pct = (current_price - pos.entry_price) / pos.entry_price
        if pnl_pct < self._dca_profit_min:
            return False

        # VWAP 위에서 집행 (최근 4봉 VWAP)
        if candles_15m and len(candles_15m) >= 4:
            recent = candles_15m[-4:]
            total_pv = sum(c.close * c.volume for c in recent)
            total_vol = sum(c.volume for c in recent)
            if total_vol > 0:
                vwap = total_pv / total_vol
                if current_price < vwap:
                    return False

        # Pool 25% 미만
        core_balance = self._pool.get_balance(Pool.CORE)
        if pos.size_krw >= core_balance * 0.25:
            return False

        return True

    def mark_additional_buy(self, symbol: str) -> None:
        """추가매수 완료를 기록한다."""
        cp = self._core_positions.get(symbol)
        if cp:
            cp.additional_buy_done = True

    def check_partial_exit(
        self, symbol: str, current_price: float
    ) -> float:
        """부분 청산 비율을 확인한다.

        Args:
            symbol: 코인 심볼.
            current_price: 현재 가격.

        Returns:
            청산할 비율 (0.0 = 없음, 0.3 = 30%).
        """
        cp = self._core_positions.get(symbol)
        if cp is None or cp.phase != CorePhase.NORMAL:
            return 0.0

        pos = cp.position
        if pos.entry_price <= 0:
            return 0.0

        pnl_pct = (current_price - pos.entry_price) / pos.entry_price

        # +6% → 30% (2차)
        if pnl_pct >= 0.06 and not cp.partial_exit_2:
            cp.partial_exit_2 = True
            return 0.3

        # +3% → 30% (1차)
        if pnl_pct >= 0.03 and not cp.partial_exit_1:
            cp.partial_exit_1 = True
            return 0.3

        return 0.0

    def get_core_position(self, symbol: str) -> CorePosition | None:
        """Core 포지션을 조회한다."""
        return self._core_positions.get(symbol)

    def is_core(self, symbol: str) -> bool:
        """Core 포지션인지 확인한다."""
        return symbol in self._core_positions

    @property
    def core_positions(self) -> dict[str, CorePosition]:
        """전체 Core 포지션을 반환한다."""
        return self._core_positions.copy()

    def to_state(self) -> dict:
        """상태를 직렬화한다."""
        core_data = {}
        for k, cp in self._core_positions.items():
            core_data[k] = {
                "symbol": cp.symbol,
                "phase": cp.phase.value,
                "protection_bars": cp.protection_bars,
                "bars_since_promotion": cp.bars_since_promotion,
                "original_stop_loss": cp.original_stop_loss,
                "core_stop_loss": cp.core_stop_loss,
                "additional_buy_done": cp.additional_buy_done,
                "demotion_bar_count": cp.demotion_bar_count,
                "partial_exit_1": cp.partial_exit_1,
                "partial_exit_2": cp.partial_exit_2,
            }
        return {
            "core_positions": core_data,
            "demotion_cooldown": dict(self._demotion_cooldown),
            "profit_hold_count": dict(self._profit_hold_count),
        }

    def from_state(self, state: dict, positions: dict[str, Position]) -> None:
        """상태를 복원한다.

        Args:
            state: to_state()로 직렬화된 상태.
            positions: 심볼→Position 매핑 (포지션 참조 복원용).
        """
        for k, v in state.get("core_positions", {}).items():
            pos = positions.get(k)
            if pos is None:
                logger.warning("Core 포지션 복원 스킵 (포지션 없음): %s", k)
                continue
            self._core_positions[k] = CorePosition(
                symbol=v["symbol"],
                position=pos,
                phase=CorePhase(v.get("phase", "protection")),
                protection_bars=v.get("protection_bars", 0),
                bars_since_promotion=v.get("bars_since_promotion", 0),
                original_stop_loss=v.get("original_stop_loss", 0.0),
                core_stop_loss=v.get("core_stop_loss", 0.0),
                additional_buy_done=v.get("additional_buy_done", False),
                demotion_bar_count=v.get("demotion_bar_count", 0),
                partial_exit_1=v.get("partial_exit_1", False),
                partial_exit_2=v.get("partial_exit_2", False),
            )
        self._demotion_cooldown = state.get("demotion_cooldown", {})
        self._profit_hold_count = state.get("profit_hold_count", {})

    @staticmethod
    def _last_valid(arr: np.ndarray) -> float:
        """배열에서 마지막 유효값을 반환한다."""
        if arr is None or len(arr) == 0:
            return 0.0
        for i in range(len(arr) - 1, -1, -1):
            if not np.isnan(arr[i]):
                return float(arr[i])
        return 0.0
