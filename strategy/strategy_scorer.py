"""StrategyScorer — 전략 점수 계산.

5종 전략(trend_follow, mean_reversion, breakout, scalping, dca)의
점수를 계산하고 국면별 허용 전략만 반환한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.data_types import Strategy
from strategy.indicators import IndicatorPack

# ─── 전략별 기본 가중치 ───
DEFAULT_WEIGHTS: dict[str, dict[str, float]] = {
    "trend_follow": {
        "trend_align": 30,
        "macd": 25,
        "volume": 20,
        "rsi_pullback": 15,
        "supertrend": 10,
    },
}


# ─── 점수 결과 ───
@dataclass
class ScoreResult:
    """전략 점수 결과."""

    strategy: Strategy
    score: float
    detail: dict[str, float] = field(default_factory=dict)


class StrategyScorer:
    """전략 점수 계산 담당."""

    def __init__(self, strategy_params: dict | None = None) -> None:
        """초기화.

        Args:
            strategy_params: 전략별 SL/TP 파라미터 (가중치 오버라이드 포함).
        """
        self._strategy_params = strategy_params or {}

    def get_weights(self, strategy: str) -> dict[str, float]:
        """전략의 점수 가중치를 반환한다. config에 w_ 접두사 항목이 있으면 사용."""
        defaults = DEFAULT_WEIGHTS.get(strategy, {}).copy()
        sp = self._strategy_params.get(strategy, {})
        for key in defaults:
            config_key = f"w_{key}"
            if config_key in sp:
                defaults[key] = float(sp[config_key])
        return defaults

    def score_strategy_a(
        self,
        ind_15m: IndicatorPack,
        ind_1h: IndicatorPack,
        candles_15m: list | None = None,
    ) -> ScoreResult:
        """전략 A 추세추종 점수를 계산한다."""
        detail: dict[str, float] = {}
        score = 0.0
        w = self.get_weights("trend_follow")

        # 1H 추세 일치: 15M 방향과 1H EMA 방향 일치
        ema20_1h = _last_valid(ind_1h.ema20)
        ema50_1h = _last_valid(ind_1h.ema50)
        ema20_15m = _last_valid(ind_15m.ema20)
        ema50_15m = _last_valid(ind_15m.ema50)
        if ema20_1h > ema50_1h and ema20_15m > ema50_15m:
            detail["trend_align"] = w["trend_align"]
            score += w["trend_align"]
        elif ema20_1h > ema50_1h:
            detail["trend_align"] = w["trend_align"] * 0.5
            score += w["trend_align"] * 0.5
        else:
            detail["trend_align"] = 0.0

        # MACD 상태: 골든크로스 + 히스토그램 양수
        if ind_15m.macd:
            macd_line = _last_valid(ind_15m.macd.macd_line)
            signal_line = _last_valid(ind_15m.macd.signal_line)
            histogram = _last_valid(ind_15m.macd.histogram)
            if macd_line > signal_line and histogram > 0:
                detail["macd"] = w["macd"]
                score += w["macd"]
            elif macd_line > signal_line:
                detail["macd"] = w["macd"] * 0.5
                score += w["macd"] * 0.5
            else:
                detail["macd"] = 0.0
        else:
            detail["macd"] = 0.0

        # 거래량: 20봉 평균의 1.5배 이상 (실제 캔들 volume)
        if candles_15m:
            detail["volume"] = _score_volume_direct(
                candles_15m,
                threshold=1.5,
                max_pts=w["volume"],
            )
        else:
            detail["volume"] = _score_volume(
                ind_15m,
                threshold=1.5,
                max_pts=w["volume"],
            )
        score += detail["volume"]

        # RSI 위치: 40~60 범위 (풀백 구간)
        rsi = _last_valid(ind_15m.rsi)
        if 40 <= rsi <= 60:
            detail["rsi_pullback"] = w["rsi_pullback"]
            score += w["rsi_pullback"]
        elif 35 <= rsi <= 65:
            detail["rsi_pullback"] = w["rsi_pullback"] * 0.5
            score += w["rsi_pullback"] * 0.5
        else:
            detail["rsi_pullback"] = 0.0

        # SuperTrend: BULLISH 상태
        if ind_15m.supertrend and len(ind_15m.supertrend.direction) > 0:
            if ind_15m.supertrend.direction[-1] == 1:
                detail["supertrend"] = w["supertrend"]
                score += w["supertrend"]
            else:
                detail["supertrend"] = 0.0
        else:
            detail["supertrend"] = 0.0

        return ScoreResult(strategy=Strategy.TREND_FOLLOW, score=score, detail=detail)

    def score_strategy_b(
        self,
        ind_15m: IndicatorPack,
        candles_15m: list | None = None,
    ) -> ScoreResult:
        """전략 B 반전포착 점수를 계산한다."""
        detail: dict[str, float] = {}
        score = 0.0

        # RSI 반등 (30점): RSI 35 이하에서 40 이상으로 복귀
        rsi_arr = ind_15m.rsi
        valid_rsi = rsi_arr[~np.isnan(rsi_arr)]
        if len(valid_rsi) >= 3:
            prev_rsi = valid_rsi[-3]
            curr_rsi = valid_rsi[-1]
            if prev_rsi <= 35 and curr_rsi >= 40:
                detail["rsi_bounce"] = 30.0
                score += 30.0
            elif curr_rsi <= 40:
                detail["rsi_bounce"] = 15.0
                score += 15.0
            else:
                detail["rsi_bounce"] = 0.0
        else:
            detail["rsi_bounce"] = 0.0

        # BB 위치 (25점): 하단밴드 이탈 후 복귀 (실제 close vs BB lower)
        if ind_15m.bb and candles_15m and len(candles_15m) >= 5:
            lower = ind_15m.bb.lower
            n = min(len(candles_15m), len(lower))
            if n >= 5:
                closes = np.array([c.close for c in candles_15m[-n:]])
                bb_lower = lower[-n:]
                # 최근 5봉 내 close < BB lower 이탈 확인
                valid_mask = ~np.isnan(bb_lower[-5:])
                if np.any(valid_mask):
                    was_below = (
                        bool(
                            np.any(
                                closes[-5:-1][valid_mask[:-1]] < bb_lower[-5:-1][valid_mask[:-1]]
                            )
                        )
                        if np.any(valid_mask[:-1])
                        else False
                    )
                    curr_above = not np.isnan(bb_lower[-1]) and closes[-1] >= bb_lower[-1]
                    if was_below and curr_above:
                        detail["bb_position"] = 25.0
                        score += 25.0
                    elif was_below:
                        detail["bb_position"] = 12.0
                        score += 12.0
                    else:
                        detail["bb_position"] = 0.0
                else:
                    detail["bb_position"] = 0.0
            else:
                detail["bb_position"] = 0.0
        else:
            detail["bb_position"] = 0.0

        # 거래량 급증 (25점): 20봉 평균의 2배 이상
        detail["volume"] = _score_volume(ind_15m, threshold=2.0, max_pts=25.0)
        score += detail["volume"]

        # Z-score (20점): -2.0 이하
        zscore = _last_valid(ind_15m.zscore)
        if zscore <= -2.0:
            detail["zscore"] = 20.0
            score += 20.0
        elif zscore <= -1.5:
            detail["zscore"] = 10.0
            score += 10.0
        else:
            detail["zscore"] = 0.0

        return ScoreResult(strategy=Strategy.MEAN_REVERSION, score=score, detail=detail)

    def score_strategy_c(
        self, ind_15m: IndicatorPack, ind_1h: IndicatorPack, candles_15m: list
    ) -> ScoreResult:
        """전략 C 브레이크아웃 점수를 계산한다."""
        detail: dict[str, float] = {}
        score = 0.0

        # 돌파 확인 (35점): 20봉 고점 돌파 + 1봉 확인봉
        if len(candles_15m) >= 22:
            highs = np.array([c.high for c in candles_15m])
            close_curr = candles_15m[-1].close
            high_20 = float(np.max(highs[-22:-2]))  # 2봉 전까지의 20봉 고점
            close_prev = candles_15m[-2].close

            if close_prev > high_20 and close_curr > high_20:
                detail["breakout"] = 35.0
                score += 35.0
            elif close_curr > high_20:
                detail["breakout"] = 18.0
                score += 18.0
            else:
                detail["breakout"] = 0.0
        else:
            detail["breakout"] = 0.0

        # 거래량 (30점): 돌파봉 거래량 > 평균 2배 (실제 캔들 volume)
        detail["volume"] = _score_volume_direct(
            candles_15m,
            threshold=2.0,
            max_pts=30.0,
        )
        score += detail["volume"]

        # ATR 확대 (20점): 현재 ATR > 14봉 ATR 평균 × 1.3
        atr_now = _last_valid(ind_15m.atr)
        valid_atr = ind_15m.atr[~np.isnan(ind_15m.atr)]
        atr_avg = float(np.mean(valid_atr[-14:])) if len(valid_atr) >= 14 else atr_now
        if atr_avg > 0 and atr_now > atr_avg * 1.3:
            detail["atr_expand"] = 20.0
            score += 20.0
        elif atr_avg > 0 and atr_now > atr_avg:
            detail["atr_expand"] = 10.0
            score += 10.0
        else:
            detail["atr_expand"] = 0.0

        # 1H 추세 (15점): 돌파 방향과 1H EMA 방향 일치
        ema20_1h = _last_valid(ind_1h.ema20)
        ema50_1h = _last_valid(ind_1h.ema50)
        if ema20_1h > ema50_1h:
            detail["trend_1h"] = 15.0
            score += 15.0
        else:
            detail["trend_1h"] = 0.0

        # BB 스퀴즈 선행 확인 (+15/+7pt): 스퀴즈 후 확장 패턴
        # ADX 패널티 적용 전에 계산 — ADX < 20(추세 부재) 환경에서는 보너스 제외
        adx_val = _last_valid(ind_1h.adx.adx) if ind_1h.adx else 0.0
        if adx_val >= 20 and ind_15m.bb and len(ind_15m.bb.upper) >= 22 and len(ind_15m.bb.lower) >= 22:
            upper = ind_15m.bb.upper
            lower = ind_15m.bb.lower
            bandwidth = upper - lower
            valid_bw = bandwidth[~np.isnan(bandwidth)]
            if len(valid_bw) >= 22:
                bw_min_recent = float(np.min(valid_bw[-5:-1]))   # 직전 완성봉 포함 4봉 최솟값
                bw_min_20 = float(np.min(valid_bw[-22:-1]))      # 20봉 최솟값
                bw_prev = float(valid_bw[-2])
                bw_curr = float(valid_bw[-1])
                was_squeezed = bw_min_recent <= bw_min_20 * 1.15
                is_expanding = bw_prev > 0 and bw_curr > bw_prev * 1.20
                if was_squeezed and is_expanding:
                    detail["bb_squeeze"] = 15.0
                    score += 15.0
                elif is_expanding:
                    detail["bb_squeeze"] = 7.0
                    score += 7.0
                else:
                    detail["bb_squeeze"] = 0.0
            else:
                detail["bb_squeeze"] = 0.0
        else:
            detail["bb_squeeze"] = 0.0

        # ADX 필터: ADX < 20이면 추세 부재 → 가짜 돌파 위험 (점수 50% 감소)
        if adx_val < 20:
            detail["adx_filter"] = -score * 0.5
            score *= 0.5

        return ScoreResult(strategy=Strategy.BREAKOUT, score=score, detail=detail)

    def score_strategy_d(
        self, ind_15m: IndicatorPack, ind_1h: IndicatorPack, snap: object
    ) -> ScoreResult:
        """전략 D 스캘핑 점수를 계산한다."""
        detail: dict[str, float] = {}
        score = 0.0

        # RSI 바운스 (30점): 15M RSI 30이하에서 반등 시작
        rsi_arr = ind_15m.rsi
        valid_rsi = rsi_arr[~np.isnan(rsi_arr)]
        if len(valid_rsi) >= 2:
            prev_rsi = valid_rsi[-2]
            curr_rsi = valid_rsi[-1]
            if prev_rsi <= 30 and curr_rsi > prev_rsi:
                detail["rsi_bounce"] = 30.0
                score += 30.0
            elif curr_rsi <= 35:
                detail["rsi_bounce"] = 15.0
                score += 15.0
            else:
                detail["rsi_bounce"] = 0.0
        else:
            detail["rsi_bounce"] = 0.0

        # 1H 추세 일치 (30점): 상위 TF 추세 방향과 일치
        ema20_1h = _last_valid(ind_1h.ema20)
        ema50_1h = _last_valid(ind_1h.ema50)
        if ema20_1h > ema50_1h:
            detail["trend_1h"] = 30.0
            score += 30.0
        else:
            detail["trend_1h"] = 0.0

        # 스프레드 (20점): Bid-Ask 스프레드 < 0.15%
        if snap.orderbook and snap.orderbook.spread_pct < 0.0015:
            detail["spread"] = 20.0
            score += 20.0
        elif snap.orderbook and snap.orderbook.spread_pct < 0.003:
            detail["spread"] = 10.0
            score += 10.0
        else:
            detail["spread"] = 0.0

        # 거래량 (20점): 현재 거래량 > 평균 1.5배
        detail["volume"] = _score_volume(ind_15m, threshold=1.5, max_pts=20.0)
        score += detail["volume"]

        return ScoreResult(strategy=Strategy.SCALPING, score=score, detail=detail)

    def score_strategy_e(
        self,
        ind_1h: IndicatorPack,
        symbol: str,
        current_price: float = 0.0,
    ) -> ScoreResult:
        """전략 E DCA 매집 점수를 계산한다.

        Tier 1 코인(BTC, ETH)만 대상. CRISIS/WEAK_DOWN 국면.
        """
        detail: dict[str, float] = {}
        score = 0.0

        # DCA 대상 확인 (30점): BTC 또는 ETH만 허용
        dca_eligible = symbol in ("BTC", "ETH")
        if dca_eligible:
            detail["tier1"] = 30.0
            score += 30.0
        else:
            detail["tier1"] = 0.0
            return ScoreResult(strategy=Strategy.DCA, score=0, detail=detail)

        # RSI 위치 (25점): RSI < 35 (과매도 매집 적기)
        rsi = _last_valid(ind_1h.rsi)
        if rsi < 30:
            detail["rsi_oversold"] = 25.0
            score += 25.0
        elif rsi < 35:
            detail["rsi_oversold"] = 15.0
            score += 15.0
        else:
            detail["rsi_oversold"] = 0.0

        # 장기 EMA 관계 (25점): 가격이 EMA200 이하 (저평가)
        ema200 = _last_valid(ind_1h.ema200)
        if ema200 > 0:
            close = current_price if current_price > 0 else _last_valid(ind_1h.ema20)
            if close > 0 and close < ema200 * 0.95:
                detail["below_ema200"] = 25.0
                score += 25.0
            elif close > 0 and close < ema200:
                detail["below_ema200"] = 12.0
                score += 12.0
            else:
                detail["below_ema200"] = 0.0
        else:
            detail["below_ema200"] = 0.0

        # Z-score (20점): -1.5 이하
        zscore = _last_valid(ind_1h.zscore)
        if zscore <= -2.0:
            detail["zscore"] = 20.0
            score += 20.0
        elif zscore <= -1.5:
            detail["zscore"] = 10.0
            score += 10.0
        else:
            detail["zscore"] = 0.0

        return ScoreResult(strategy=Strategy.DCA, score=score, detail=detail)


# ─── 모듈 수준 유틸 함수 ───

def _last_valid(arr: np.ndarray) -> float:
    """배열에서 마지막 유효값을 반환한다."""
    valid = arr[~np.isnan(arr)]
    return float(valid[-1]) if len(valid) > 0 else float("nan")


def _score_volume(ind: IndicatorPack, threshold: float, max_pts: float) -> float:
    """거래량 점수를 계산한다 (OBV 증분 기반 간접)."""
    obv = ind.obv
    if len(obv) < 20:
        return 0.0
    # OBV 변화율로 거래량 급증 판단
    obv_diff = obv[-1] - obv[-2] if len(obv) >= 2 else 0
    avg_diff = float(np.mean(np.abs(np.diff(obv[-20:])))) if len(obv) >= 20 else 1
    if avg_diff > 0 and abs(obv_diff) > avg_diff * threshold:
        return max_pts
    if avg_diff > 0 and abs(obv_diff) > avg_diff:
        return max_pts * 0.5
    return 0.0


def _score_volume_direct(candles: list, threshold: float, max_pts: float) -> float:
    """실제 캔들 거래량을 직접 비교하여 점수를 계산한다.

    마지막 완성봉(-2)을 기준으로 평가한다.
    """
    if len(candles) < 22:
        return 0.0
    volumes = np.array([c.volume for c in candles])
    avg_vol = float(np.mean(volumes[-22:-2]))
    curr_vol = float(volumes[-2])  # 마지막 완성봉
    if avg_vol > 0 and curr_vol > avg_vol * threshold:
        return max_pts
    if avg_vol > 0 and curr_vol > avg_vol:
        return max_pts * 0.5
    return 0.0
