"""SpreadProfiler 단위 테스트."""

from __future__ import annotations

import sqlite3
import time

import pytest

from app.data_types import Tier
from strategy.spread_profiler import (
    DEFAULT_SPREAD_LIMIT,
    MIN_SAMPLES,
    SAFETY_MULT,
    SpreadProfiler,
)


@pytest.fixture
def db_path(tmp_path):
    """테스트용 DB를 생성한다."""
    path = tmp_path / "test_market.db"
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE orderbook_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            bids TEXT NOT NULL,
            asks TEXT NOT NULL,
            spread_pct REAL NOT NULL,
            created_at INTEGER NOT NULL
        );
    """)
    conn.commit()
    conn.close()
    return path


def _insert_spreads(db_path, symbol: str, spreads: list[float], days_ago: float = 0) -> None:
    """스프레드 데이터를 삽입한다."""
    conn = sqlite3.connect(str(db_path))
    base_ms = int((time.time() - days_ago * 86400) * 1000)
    for i, spread in enumerate(spreads):
        conn.execute(
            """INSERT INTO orderbook_snapshots
               (symbol, timestamp, bids, asks, spread_pct, created_at)
               VALUES (?, ?, '[]', '[]', ?, ?)""",
            (symbol, base_ms + i, spread, base_ms + i),
        )
    conn.commit()
    conn.close()


class TestGetThreshold:
    """get_threshold 테스트."""

    def test_no_data_returns_tier_default(self, db_path) -> None:
        """데이터 없으면 Tier별 기본값 반환."""
        sp = SpreadProfiler(db_path=db_path)
        assert sp.get_threshold("BTC", Tier.TIER1) == DEFAULT_SPREAD_LIMIT[Tier.TIER1]
        assert sp.get_threshold("LDO", Tier.TIER2) == DEFAULT_SPREAD_LIMIT[Tier.TIER2]
        assert sp.get_threshold("RENDER", Tier.TIER3) == DEFAULT_SPREAD_LIMIT[Tier.TIER3]

    def test_insufficient_samples_returns_default(self, db_path) -> None:
        """샘플 부족 시 기본값 반환."""
        _insert_spreads(db_path, "BTC", [0.001] * (MIN_SAMPLES - 1))
        sp = SpreadProfiler(db_path=db_path)
        assert sp.get_threshold("BTC", Tier.TIER1) == DEFAULT_SPREAD_LIMIT[Tier.TIER1]

    def test_dynamic_threshold_calculated(self, db_path) -> None:
        """충분한 데이터로 동적 임계값 계산."""
        # 100개 샘플: 대부분 0.002, 상위 10%는 0.005
        spreads = [0.002] * 90 + [0.005] * 10
        _insert_spreads(db_path, "LDO", spreads)
        sp = SpreadProfiler(db_path=db_path)

        threshold = sp.get_threshold("LDO", Tier.TIER2)
        # 90분위 = 0.005, × 1.5 = 0.0075
        assert threshold == pytest.approx(0.005 * SAFETY_MULT)

    def test_old_data_excluded(self, db_path) -> None:
        """LOOKBACK_DAYS 이전 데이터는 제외."""
        # 오래된 데이터 (8일 전)
        _insert_spreads(db_path, "BTC", [0.01] * 50, days_ago=8)
        # 최근 데이터 (1일 전)
        _insert_spreads(db_path, "BTC", [0.001] * 50, days_ago=1)

        sp = SpreadProfiler(db_path=db_path)
        threshold = sp.get_threshold("BTC", Tier.TIER1)
        # 최근 데이터만 사용: 90분위 ≈ 0.001 × 1.5 = 0.0015
        assert threshold < 0.005  # 오래된 0.01 기반이면 0.015가 됨

    def test_per_coin_different_thresholds(self, db_path) -> None:
        """코인별로 다른 임계값."""
        _insert_spreads(db_path, "BTC", [0.001] * 50)
        _insert_spreads(db_path, "LDO", [0.004] * 50)
        sp = SpreadProfiler(db_path=db_path)

        btc_t = sp.get_threshold("BTC", Tier.TIER1)
        ldo_t = sp.get_threshold("LDO", Tier.TIER2)
        assert ldo_t > btc_t


class TestRefresh:
    """refresh 테스트."""

    def test_refresh_returns_coin_count(self, db_path) -> None:
        """갱신 후 코인 수 반환."""
        _insert_spreads(db_path, "BTC", [0.001] * 30)
        _insert_spreads(db_path, "ETH", [0.002] * 30)
        sp = SpreadProfiler(db_path=db_path)
        count = sp.refresh()
        assert count == 2

    def test_get_all_thresholds(self, db_path) -> None:
        """모든 코인 임계값 반환."""
        _insert_spreads(db_path, "BTC", [0.001] * 30)
        _insert_spreads(db_path, "ETH", [0.002] * 30)
        sp = SpreadProfiler(db_path=db_path)
        sp.refresh()
        all_t = sp.get_all_thresholds()
        assert "BTC" in all_t
        assert "ETH" in all_t

    def test_nonexistent_db_returns_zero(self) -> None:
        """DB 없으면 0 반환."""
        sp = SpreadProfiler(db_path="/tmp/nonexistent_xyz.db")
        count = sp.refresh()
        assert count == 0

    def test_zero_spread_excluded(self, db_path) -> None:
        """spread=0인 데이터는 제외."""
        _insert_spreads(db_path, "BTC", [0.0] * 10 + [0.001] * 30)
        sp = SpreadProfiler(db_path=db_path)
        sp.refresh()
        threshold = sp.get_threshold("BTC", Tier.TIER1)
        assert threshold > 0
