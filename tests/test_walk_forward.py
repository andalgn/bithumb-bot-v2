"""Walk-Forward 검증 테스트."""

import pytest

from backtesting.walk_forward import WalkForward


@pytest.fixture
def wf() -> WalkForward:
    """테스트용 WalkForward."""
    return WalkForward(data_days=30, slide_days=7, num_segments=4)


def _make_trades(count: int, profitable: bool = True) -> list[dict]:
    """테스트용 거래 생성."""
    trades = []
    for i in range(count):
        entry = 50_000_000
        exit_p = entry * (1.01 if profitable else 0.99)
        trades.append({
            "entry_price": entry,
            "exit_price": exit_p,
            "qty": 0.001,
            "day": i % 30,
        })
    return trades


class TestWalkForward:
    """Walk-Forward 테스트."""

    def test_empty_trades(self, wf: WalkForward) -> None:
        """빈 거래 → warning."""
        result = wf.run([])
        assert result.verdict == "warning"

    def test_profitable_trades(self, wf: WalkForward) -> None:
        """수익 거래들 → 3개 이상 구간 통과."""
        trades = _make_trades(100, profitable=True)
        result = wf.run(trades)
        assert result.pass_count >= 3
        assert result.verdict in ("robust", "good", "overfit")

    def test_losing_trades(self, wf: WalkForward) -> None:
        """손실 거래들 → warning."""
        trades = _make_trades(100, profitable=False)
        result = wf.run(trades)
        assert result.pass_count <= 2

    def test_segments_count(self, wf: WalkForward) -> None:
        """4개 구간."""
        trades = _make_trades(50)
        result = wf.run(trades)
        assert result.total_segments == 4
        assert len(result.segments) == 4
