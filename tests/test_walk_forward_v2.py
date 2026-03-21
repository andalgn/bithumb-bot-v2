"""Walk-Forward 리팩토링 테스트."""
from backtesting.walk_forward import WalkForward


def test_wf_custom_segments():
    """6구간 Walk-Forward를 생성할 수 있다."""
    wf = WalkForward(num_segments=6)
    assert wf._num_segments == 6


def test_wf_custom_data_days():
    """데이터 기간을 180일로 설정할 수 있다."""
    wf = WalkForward(data_days=180, num_segments=6)
    assert wf._data_days == 180


def test_wf_run_with_6_segments():
    """6구간으로 실행하면 6개 세그먼트 결과가 나온다."""
    trades = []
    for day in range(180):
        pnl = 100 if day % 3 == 0 else -50
        trades.append({
            "day": day,
            "strategy": "trend_follow",
            "entry_price": 1000,
            "exit_price": 1000 + pnl,
            "quantity": 1.0,
            "coin": "BTC",
        })
    wf = WalkForward(data_days=180, num_segments=6)
    result = wf.run(trades)
    assert result.total_segments == 6
    assert len(result.segments) == 6


def test_wf_verdict_75pct():
    """75% 이상 통과 시 'good' 이상 verdict."""
    trades = []
    for day in range(120):
        trades.append({
            "day": day,
            "strategy": "trend_follow",
            "entry_price": 1000,
            "exit_price": 1100,
            "quantity": 1.0,
            "coin": "BTC",
        })
    wf = WalkForward(data_days=120, num_segments=4)
    result = wf.run(trades)
    assert result.verdict in ("robust", "good")
