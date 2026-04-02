"""MomentumRanker 단위 테스트."""

from __future__ import annotations

import time

from app.data_types import Candle
from strategy.momentum_ranker import MomentumRanker


def _make_candles(n: int, base_price: float, drift: float = 0.0) -> list[Candle]:
    """n개의 1H 캔들을 생성한다. drift > 0이면 상승 추세."""
    now_ms = int(time.time() * 1000)
    candles = []
    price = base_price
    for i in range(n):
        ts = now_ms - (n - i) * 3600 * 1000
        close = price * (1 + drift)
        candles.append(
            Candle(
                timestamp=ts,
                open=price,
                high=close * 1.001,
                low=price * 0.999,
                close=close,
                volume=1000.0,
            )
        )
        price = close
    return candles


def test_rank_returns_all_coins():
    """모든 코인이 순위에 포함된다."""
    ranker = MomentumRanker()
    candles_map = {
        "BTC": _make_candles(200, 50_000_000),
        "ETH": _make_candles(200, 3_000_000),
        "SOL": _make_candles(200, 200_000),
    }
    ranked = ranker.rank(candles_map)
    assert set(ranked) == {"BTC", "ETH", "SOL"}
    assert len(ranked) == 3


def test_rank_strong_uptrend_coin_first():
    """강한 상승 코인이 1위."""
    ranker = MomentumRanker()
    candles_map = {
        "RISING": _make_candles(200, 100_000, drift=0.003),
        "FLAT": _make_candles(200, 100_000, drift=0.0),
        "FALLING": _make_candles(200, 100_000, drift=-0.003),
    }
    ranked = ranker.rank(candles_map)
    assert ranked[0] == "RISING"
    assert ranked[-1] == "FALLING"


def test_rank_insufficient_candles_last():
    """캔들 부족 코인은 꼴찌."""
    ranker = MomentumRanker()
    candles_map = {
        "GOOD": _make_candles(200, 50_000_000, drift=0.001),
        "SHORT": _make_candles(10, 50_000_000),
    }
    ranked = ranker.rank(candles_map)
    assert ranked[-1] == "SHORT"


def test_rank_single_coin():
    """코인 1개일 때 그대로 반환."""
    ranker = MomentumRanker()
    candles_map = {"BTC": _make_candles(200, 50_000_000)}
    ranked = ranker.rank(candles_map)
    assert ranked == ["BTC"]
