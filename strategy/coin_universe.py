"""CoinUniverse — 빗썸 거래량 기준 동적 코인 유니버스 관리 + Phase 1 Hard Cutoffs.

Phase 1 Hard Cutoffs (극저가 코인 제외):
1. VOLUME FILTER: 7일 이동평균 거래량 > 100M KRW (1시간 캔들 기반)
2. SPREAD FILTER: bid/ask 스프레드 < 0.5%
3. TICK-PRICE FILTER: tick_size / price < 1% (극저가 코인 제외) ← CRITICAL
4. EXCLUDE LIST: 스테이블코인, KRW 등

daily refresh로 상위 top_n 코인을 선정하고 hard cutoff로 필터링한 후,
base_coins(안전망)와 합집합으로 최종 목록 결정.

예상 결과:
- Before: 20개 (10 KRW 코인 다수 포함, 스프레드 1% 이상)
- After: 12-15개 (모두 1% 이상의 최소호가 비율, 스프레드 < 0.5%)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from market.normalizer import get_tick_size as _get_tick_size

if TYPE_CHECKING:
    from market.bithumb_api import BithumbClient

logger = logging.getLogger(__name__)

_EXCLUDE: frozenset[str] = frozenset(
    {
        "USDT",
        "USDC",
        "BUSD",
        "DAI",
        "TUSD",
        "USDP",
        "GUSD",
        "KRW",
        "KRWC",
    }
)


class CoinUniverse:
    """빗썸 거래량 기반 동적 코인 유니버스 관리자.

    Phase 1: Hard Cutoffs (tick, spread, volume)
    Phase 2: Tradeability Score 기반 순위 선정
    """

    # Phase 1 Hard Cutoff 임계값
    MIN_7D_ROLLING_VOLUME_KRW = 100_000_000  # 100M KRW
    MAX_SPREAD_RATIO = 0.005  # 0.5%
    MAX_TICK_PRICE_RATIO = 0.01  # 1%

    def __init__(
        self,
        client: BithumbClient,
        top_n: int = 20,
        base_coins: list[str] | None = None,
        max_universe: int = 15,
    ) -> None:
        """초기화.

        Args:
            client: 빗썸 API 클라이언트.
            top_n: 거래량 기준 상위 선정 수 (필터 전).
            base_coins: 항상 포함할 안전망 코인 목록.
            max_universe: 최종 유니버스 최대 크기 (Phase 2 점수 기반 선정).
        """
        self._client = client
        self._top_n = top_n
        self._max_universe = max_universe
        self._base_coins: list[str] = list(base_coins or [])
        self._current: list[str] = list(base_coins or [])
        self._filtered_out: dict[str, str] = {}  # 필터링된 코인 + 사유
        self._scores: dict[str, float] = {}  # Phase 2 트레이더빌리티 점수

    @property
    def coins(self) -> list[str]:
        """현재 코인 목록을 반환한다."""
        return list(self._current)

    @property
    def filtered_out(self) -> dict[str, str]:
        """필터링된 코인 목록 + 사유를 반환한다.

        Returns:
            {코인: 필터링 사유} 딕셔너리.
        """
        return dict(self._filtered_out)

    @property
    def scores(self) -> dict[str, float]:
        """코인별 트레이더빌리티 점수를 반환한다.

        Returns:
            {코인: 점수(0~100)} 딕셔너리.
        """
        return dict(self._scores)

    def _compute_7d_rolling_volume_from_candles(self, candles: list[list]) -> float:
        """캔들 데이터에서 7일 거래대금을 계산한다.

        Args:
            candles: 1시간 캔들 리스트.

        Returns:
            7일 거래대금 (KRW). 데이터 부족 시 0.0.
        """
        if not candles:
            return 0.0
        try:
            recent = candles[-168:] if len(candles) >= 168 else candles
            return sum(float(c[2]) * float(c[5]) for c in recent if len(c) >= 6)
        except Exception as e:
            logger.warning("7d 거래량 계산 실패: %s", e)
            return 0.0

    def _compute_volatility(self, candles: list[list]) -> float:
        """1시간 캔들에서 7일 수익률 표준편차를 계산한다.

        Args:
            candles: 1시간 캔들 리스트.

        Returns:
            일일 변동성 (표준편차). 데이터 부족 시 0.0.
        """
        if not candles or len(candles) < 24:
            return 0.0
        recent = candles[-168:] if len(candles) >= 168 else candles
        closes = [float(c[2]) for c in recent if len(c) >= 6 and float(c[2]) > 0]
        if len(closes) < 24:
            return 0.0
        returns = [(closes[i] / closes[i - 1]) - 1 for i in range(1, len(closes))]
        if not returns:
            return 0.0
        import statistics

        hourly_std = statistics.stdev(returns)
        # 시간 → 일일 변동성 (√24)
        import math

        return hourly_std * math.sqrt(24)

    def _compute_volume_consistency(self, candles: list[list]) -> float:
        """거래량 일관성을 계산한다 (1 - CV, 변동계수가 낮을수록 일관적).

        Args:
            candles: 1시간 캔들 리스트.

        Returns:
            일관성 점수 (0~1). 1에 가까울수록 일관적.
        """
        if not candles or len(candles) < 24:
            return 0.0
        recent = candles[-168:] if len(candles) >= 168 else candles
        volumes = [float(c[5]) for c in recent if len(c) >= 6]
        if len(volumes) < 24:
            return 0.0
        import statistics

        mean_vol = statistics.mean(volumes)
        if mean_vol <= 0:
            return 0.0
        cv = statistics.stdev(volumes) / mean_vol  # 변동계수
        return max(0.0, min(1.0, 1.0 - cv))

    def _passes_hard_cutoffs(
        self, coin: str, ticker: dict, rolling_vol: float
    ) -> tuple[bool, str | None]:
        """Hard cutoff을 통과하는지 검사한다.

        Args:
            coin: 코인 심볼.
            ticker: 빗썸 ticker 딕셔너리.
            rolling_vol: 7일 이동평균 거래량 (KRW).

        Returns:
            (통과 여부, 실패 사유). 통과 시 (True, None).
        """
        # 1. SPREAD FILTER
        try:
            bid = float(ticker.get("bid", 0))
            ask = float(ticker.get("ask", 0))
            if bid > 0 and ask > 0:
                spread_ratio = 1 - (bid / ask)
                if spread_ratio > self.MAX_SPREAD_RATIO:
                    return False, f"spread {spread_ratio:.4f} > {self.MAX_SPREAD_RATIO}"
        except (TypeError, ValueError):
            return False, "invalid bid/ask"

        # 2. TICK-PRICE FILTER (극저가 코인 제외) ← CRITICAL
        # get_ticker() 응답에서 "closing_price"를 사용
        try:
            price = float(ticker.get("closing_price", 0))
            if price <= 0:
                return False, "price <= 0"
            tick = _get_tick_size(price)
            tick_ratio = tick / price
            if tick_ratio > self.MAX_TICK_PRICE_RATIO:
                return False, f"tick_ratio {tick_ratio:.4f} > {self.MAX_TICK_PRICE_RATIO}"
        except (TypeError, ValueError):
            return False, "invalid price"

        # 3. VOLUME FILTER (7일 이동평균)
        if rolling_vol < self.MIN_7D_ROLLING_VOLUME_KRW:
            return False, f"vol_7d {rolling_vol:.0f} < {self.MIN_7D_ROLLING_VOLUME_KRW}"

        # All cutoffs passed
        return True, None

    async def refresh(self) -> list[str]:
        """빗썸 API에서 전체 티커를 조회해 코인 목록을 갱신한다 (hard cutoff 적용).

        Returns:
            갱신된 코인 목록.
        """
        all_tickers = await self._client.get_all_tickers()
        if not all_tickers:
            logger.warning("get_all_tickers 빈 응답 — base_coins 유지")
            self._current = list(self._base_coins)
            self._filtered_out = {}
            return list(self._base_coins)

        # Step 1: 거래량 기준 상위 top_n 선정 (24h 기준, 필터 전)
        volumes: list[tuple[str, float]] = []
        for sym, info in all_tickers.items():
            if sym in _EXCLUDE:
                continue
            try:
                vol = float(info.get("acc_trade_value_24H", 0))
            except (TypeError, ValueError):
                vol = 0.0
            volumes.append((sym, vol))

        volumes.sort(key=lambda x: x[1], reverse=True)
        candidates = [sym for sym, _ in volumes[: self._top_n]]

        logger.info("코인 유니버스 상위 %d개 후보: %s", len(candidates), candidates)

        # Step 2: Hard cutoff 적용
        self._filtered_out = {}
        passed_coins: list[tuple[str, float]] = []

        ticker_cache: dict[str, dict] = {}
        candles_cache: dict[str, list[list]] = {}

        for coin in candidates:
            try:
                ticker = await self._client.get_ticker(coin)
            except Exception as e:
                logger.debug("개별 티커 조회 실패 (%s): %s", coin, e)
                self._filtered_out[coin] = f"ticker_fetch_error: {e}"
                continue

            try:
                candles = await self._client.get_candlestick(coin, "1h")
            except Exception:
                candles = []

            ticker_cache[coin] = ticker
            candles_cache[coin] = candles

            rolling_vol = self._compute_7d_rolling_volume_from_candles(candles)

            passes, reason = self._passes_hard_cutoffs(coin, ticker, rolling_vol)
            if not passes:
                self._filtered_out[coin] = reason or "unknown"
                logger.debug("코인 제외 (%s): %s", coin, reason)
            else:
                vol_24h = float(all_tickers.get(coin, {}).get("acc_trade_value_24H", 0))
                passed_coins.append((coin, vol_24h))

        # Step 3: Phase 2 — 트레이더빌리티 점수 계산 및 순위 선정
        scored_coins: list[tuple[str, float, float]] = []  # (coin, score, vol_24h)
        self._scores = {}

        for coin, vol_24h in passed_coins:
            ticker = ticker_cache.get(coin, {})
            candles = candles_cache.get(coin, [])

            bid = float(ticker.get("bid", 0))
            ask = float(ticker.get("ask", 0))
            price = float(ticker.get("closing_price", 0))

            spread = (1 - bid / ask) if (bid > 0 and ask > 0) else 0.005
            tick = _get_tick_size(price) if price > 0 else 1.0
            tick_r = (tick / price) if price > 0 else 0.01

            rolling_vol = self._compute_7d_rolling_volume_from_candles(candles)
            volatility = self._compute_volatility(candles) if candles else 0.03
            consistency = self._compute_volume_consistency(candles) if candles else 0.5

            score = compute_tradeability_score(
                vol_7d=rolling_vol,
                spread_ratio=spread,
                tick_ratio=tick_r,
                volatility=volatility,
                vol_consistency=consistency,
            )
            scored_coins.append((coin, score, vol_24h))
            self._scores[coin] = score

        # 점수 기준 내림차순 정렬
        scored_coins.sort(key=lambda x: x[1], reverse=True)

        # 상위 max_universe개 선정
        top_scored = [(c, s, v) for c, s, v in scored_coins[: self._max_universe]]
        top_set = {c for c, _, _ in top_scored}

        # 점수 밖으로 밀린 코인 기록
        for coin, score, _ in scored_coins[self._max_universe :]:
            self._filtered_out[coin] = (
                f"score_rank ({score:.1f}점, 상위 {self._max_universe}개 미포함)"
            )

        # Step 4: base_coins 안전망 추가
        base_not_in_top = [c for c in self._base_coins if c not in top_set]

        result = [c for c, _, _ in top_scored] + base_not_in_top

        self._current = result

        # 점수 로그
        score_str = ", ".join(f"{c}({s:.1f})" for c, s, _ in scored_coins)
        logger.info(
            "코인 유니버스 갱신: %d개 최종 (top%d 중 %d 통과 → 점수 상위 %d, base %d)",
            len(result),
            len(candidates),
            len(passed_coins),
            len(top_scored),
            len(base_not_in_top),
        )
        logger.info("트레이더빌리티 점수: %s", score_str)

        if self._filtered_out:
            excluded_str = ", ".join(
                f"{coin}({reason})" for coin, reason in self._filtered_out.items()
            )
            logger.info("제외된 코인: %s", excluded_str)

        return result


def compute_tradeability_score(
    vol_7d: float,
    spread_ratio: float,
    tick_ratio: float,
    volatility: float,
    vol_consistency: float,
) -> float:
    """복합 트레이더빌리티 점수를 계산한다.

    각 지표를 0~1로 정규화한 후 가중 합산.
    높을수록 매매하기 좋은 코인.

    Args:
        vol_7d: 7일 평균 거래대금 (KRW).
        spread_ratio: 호가 스프레드 비율 (0~1).
        tick_ratio: tick_size / price 비율 (0~1).
        volatility: 7일 수익률 표준편차 (0~1).
        vol_consistency: 거래량 일관성 (0~1, 높을수록 일관적).

    Returns:
        트레이더빌리티 점수 (0~100).
    """
    # 거래량 점수: log 스케일, 1억~1000억 범위를 0~1로
    import math

    vol_score = max(0.0, min(1.0, (math.log10(max(vol_7d, 1)) - 8) / 3))

    # 스프레드 점수: 낮을수록 좋음 (0.5% → 1.0, 0% → 1.0)
    spread_score = max(0.0, 1.0 - (spread_ratio / 0.005))

    # Tick 비율 점수: 낮을수록 좋음 (1% → 0.0, 0% → 1.0)
    tick_score = max(0.0, 1.0 - (tick_ratio / 0.01))

    # 변동성 점수: mean_reversion에 적당한 변동성이 좋음
    # 최적 구간: 2~5% (너무 낮으면 기회 없음, 너무 높으면 위험)
    if volatility <= 0:
        vol_score_adj = 0.0
    elif volatility < 0.02:
        vol_score_adj = volatility / 0.02  # 0~2%: 선형 증가
    elif volatility <= 0.05:
        vol_score_adj = 1.0  # 2~5%: 최적
    else:
        vol_score_adj = max(0.0, 1.0 - (volatility - 0.05) / 0.10)  # 5%~15%: 감소

    # 가중 합산
    W_VOL = 0.30
    W_SPREAD = 0.25
    W_TICK = 0.15
    W_VOLATILITY = 0.15
    W_CONSISTENCY = 0.15

    score = (
        W_VOL * vol_score
        + W_SPREAD * spread_score
        + W_TICK * tick_score
        + W_VOLATILITY * vol_score_adj
        + W_CONSISTENCY * vol_consistency
    )

    return round(score * 100, 1)
