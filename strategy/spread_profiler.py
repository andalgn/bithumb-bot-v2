"""SpreadProfiler — 코인별 동적 스프레드 임계값 관리.

과거 N일간 호가 스프레드 데이터를 기반으로 코인별 동적 임계값을 산출한다.
공식: threshold = percentile(90, spreads) × safety_mult
"""

from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path

from app.data_types import Tier

logger = logging.getLogger(__name__)

# Tier별 기본값 (데이터 부족 시 폴백)
DEFAULT_SPREAD_LIMIT: dict[Tier, float] = {
    Tier.TIER1: 0.0018,
    Tier.TIER2: 0.0045,
    Tier.TIER3: 0.0070,
}

# 동적 임계값 설정
LOOKBACK_DAYS = 7
PERCENTILE = 90
SAFETY_MULT = 1.5
MIN_SAMPLES = 20  # 최소 샘플 수
CACHE_TTL_SEC = 3600  # 캐시 유효 시간 (1시간)


class SpreadProfiler:
    """코인별 동적 스프레드 임계값을 관리한다."""

    def __init__(self, db_path: str | Path = "data/market_data.db") -> None:
        """초기화.

        Args:
            db_path: MarketStore의 SQLite DB 경로.
        """
        self._db_path = Path(db_path)
        self._cache: dict[str, float] = {}
        self._last_refresh: float = 0.0

    def get_threshold(self, symbol: str, tier: Tier) -> float:
        """코인의 동적 스프레드 임계값을 반환한다.

        캐시가 유효하면 캐시에서, 아니면 DB에서 계산한다.
        데이터 부족 시 Tier별 기본값을 반환한다.

        Args:
            symbol: 코인 심볼.
            tier: 코인 Tier.

        Returns:
            스프레드 임계값 (비율).
        """
        self._maybe_refresh()

        if symbol in self._cache:
            return self._cache[symbol]

        return DEFAULT_SPREAD_LIMIT.get(tier, 0.0070)

    def refresh(self) -> int:
        """모든 코인의 임계값을 DB에서 재계산한다.

        Returns:
            계산된 코인 수.
        """
        if not self._db_path.exists():
            return 0

        try:
            conn = sqlite3.connect(str(self._db_path))
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.Error:
            logger.warning("SpreadProfiler DB 연결 실패: %s", self._db_path)
            return 0

        try:
            cutoff_ms = int((time.time() - LOOKBACK_DAYS * 86400) * 1000)

            rows = conn.execute(
                """SELECT symbol, spread_pct
                   FROM orderbook_snapshots
                   WHERE created_at >= ?
                   ORDER BY symbol""",
                (cutoff_ms,),
            ).fetchall()

            # 코인별 그룹핑
            spreads_by_coin: dict[str, list[float]] = {}
            for symbol, spread in rows:
                if spread > 0:
                    spreads_by_coin.setdefault(symbol, []).append(spread)

            new_cache: dict[str, float] = {}
            for symbol, spreads in spreads_by_coin.items():
                if len(spreads) < MIN_SAMPLES:
                    continue

                spreads.sort()
                idx = int(len(spreads) * PERCENTILE / 100)
                idx = min(idx, len(spreads) - 1)
                p90 = spreads[idx]
                threshold = p90 * SAFETY_MULT
                new_cache[symbol] = threshold

            self._cache = new_cache
            self._last_refresh = time.time()

            if new_cache:
                logger.info(
                    "SpreadProfiler 갱신: %d개 코인 (예: %s)",
                    len(new_cache),
                    ", ".join(f"{s}={v:.4f}" for s, v in sorted(new_cache.items())[:3]),
                )

            return len(new_cache)

        except sqlite3.Error:
            logger.warning("SpreadProfiler 쿼리 실패")
            return 0
        finally:
            conn.close()

    def _maybe_refresh(self) -> None:
        """캐시 TTL이 지났으면 갱신한다."""
        if time.time() - self._last_refresh > CACHE_TTL_SEC:
            self.refresh()

    def get_all_thresholds(self) -> dict[str, float]:
        """캐시된 모든 코인의 임계값을 반환한다."""
        self._maybe_refresh()
        return dict(self._cache)
