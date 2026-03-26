"""EnvironmentFilter — L1 환경 필터.

거래 진입 전 시장 환경이 적합한지 판정한다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

from app.data_types import MarketSnapshot, Regime, Tier
from strategy.coin_profiler import TierParams
from strategy.indicators import IndicatorPack

KST = timezone(timedelta(hours=9))


class EnvironmentFilter:
    """L1 환경 필터 담당."""

    def __init__(self) -> None:
        """초기화."""

    def check(
        self,
        regime: Regime,
        snap: MarketSnapshot,
        ind: IndicatorPack,
        tier_params: TierParams,
    ) -> tuple[bool, str]:
        """L1 필터를 적용한다.

        Returns:
            (통과 여부, 거부 사유) 튜플.
        """
        # 1. 국면 != CRISIS
        if regime == Regime.CRISIS:
            return False, "L1: CRISIS 국면"

        # 2. 거래량 >= 20봉 평균 × 0.8 (마지막 완성봉 기준)
        if snap.candles_15m and len(snap.candles_15m) >= 22:
            volumes = np.array([c.volume for c in snap.candles_15m])
            # 마지막 봉은 미완성일 수 있으므로 -2번째 사용
            avg_vol = float(np.mean(volumes[-22:-2]))
            current_vol = float(volumes[-2])
            if avg_vol > 0 and current_vol < avg_vol * 0.8:
                return False, f"L1: 거래량 부족 ({current_vol:.0f} < {avg_vol * 0.8:.0f})"

        # 3. 스프레드 < Tier별 한도
        if snap.orderbook:
            spread = snap.orderbook.spread_pct
            if spread > tier_params.spread_limit:
                return False, f"L1: 스프레드 초과 ({spread:.4f} > {tier_params.spread_limit})"

        # 4. 시간대 필터 (00:00~06:00 KST → Tier 3 스킵)
        now_kst = datetime.now(KST)
        if 0 <= now_kst.hour < 6 and tier_params.tier == Tier.TIER3:
            return False, "L1: 심야 시간대 Tier 3 거래 중단"

        # 5. 1H 급변동 억제: 직전 완성 1H 봉 변동 ≥ 1.5% → 급등/급락 직후 진입 차단
        if snap.candles_1h and len(snap.candles_1h) >= 2:
            c = snap.candles_1h[-2]  # 마지막 완성봉
            if c.open > 0 and abs(c.close / c.open - 1) >= 0.015:
                return False, f"L1: 1H 모멘텀 버스트 ({abs(c.close / c.open - 1):.2%})"

        return True, ""
