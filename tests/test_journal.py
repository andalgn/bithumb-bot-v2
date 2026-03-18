"""Journal 테스트."""

import pytest

from app.journal import Journal


@pytest.fixture
def journal(tmp_path) -> Journal:
    """테스트용 Journal."""
    j = Journal(db_path=str(tmp_path / "test_journal.db"))
    yield j
    j.close()


class TestJournal:
    """거래 기록 테스트."""

    def test_record_trade(self, journal: Journal) -> None:
        """거래 기록 및 조회."""
        trade_id = journal.record_trade({
            "symbol": "BTC",
            "strategy": "trend_follow",
            "tier": 1,
            "regime": "STRONG_UP",
            "pool": "active",
            "entry_price": 50000000,
            "exit_price": 51000000,
            "qty": 0.001,
            "entry_fee_krw": 125,
            "exit_fee_krw": 127.5,
            "slippage_krw": 50,
            "gross_pnl_krw": 1000,
            "net_pnl_krw": 697.5,
            "net_pnl_pct": 1.395,
            "hold_seconds": 3600,
            "promoted": False,
            "entry_score": 75.0,
            "entry_time": 1700000000000,
            "exit_time": 1700003600000,
            "exit_reason": "tp",
        })
        assert trade_id

        trades = journal.get_recent_trades(limit=10)
        assert len(trades) == 1
        assert trades[0]["symbol"] == "BTC"
        assert trades[0]["net_pnl_krw"] == 697.5

    def test_record_signal(self, journal: Journal) -> None:
        """신호 기록."""
        journal.record_signal({
            "symbol": "ETH",
            "direction": "bid",
            "strategy": "mean_reversion",
            "score": 72.5,
            "regime": "RANGE",
            "tier": 2,
            "entry_price": 3000000,
            "stop_loss": 2900000,
            "take_profit": 3200000,
            "accepted": True,
        })
        # 에러 없으면 성공

    def test_record_risk_event(self, journal: Journal) -> None:
        """리스크 이벤트 기록."""
        journal.record_risk_event(
            event_type="dd_breach",
            priority="P5",
            symbol="",
            detail="일일 DD 4.2%",
        )

    def test_consecutive_losses(self, journal: Journal) -> None:
        """연속 손실 조회."""
        for i in range(5):
            journal.record_trade({
                "trade_id": f"loss_{i}",
                "symbol": "BTC",
                "strategy": "trend_follow",
                "tier": 1,
                "regime": "STRONG_UP",
                "pool": "active",
                "net_pnl_krw": -100,
            })
        assert journal.get_consecutive_losses() == 5

        journal.record_trade({
            "trade_id": "win_1",
            "symbol": "BTC",
            "strategy": "trend_follow",
            "tier": 1,
            "regime": "STRONG_UP",
            "pool": "active",
            "net_pnl_krw": 500,
        })
        assert journal.get_consecutive_losses() == 0

    def test_21_fields(self, journal: Journal) -> None:
        """21필드 전부 기록 가능."""
        data = {
            "trade_id": "test_21",
            "symbol": "SOL",
            "strategy": "breakout",
            "tier": 3,
            "regime": "RANGE",
            "pool": "core",
            "entry_price": 200000,
            "exit_price": 210000,
            "qty": 1.5,
            "entry_fee_krw": 750,
            "exit_fee_krw": 787.5,
            "slippage_krw": 100,
            "gross_pnl_krw": 15000,
            "net_pnl_krw": 13362.5,
            "net_pnl_pct": 4.454,
            "hold_seconds": 7200,
            "promoted": True,
            "entry_score": 82.0,
            "entry_time": 1700000000000,
            "exit_time": 1700007200000,
            "exit_reason": "trailing",
        }
        journal.record_trade(data)
        trades = journal.get_recent_trades(limit=1)
        assert trades[0]["trade_id"] == "test_21"
        assert trades[0]["promoted"] == 1
        assert trades[0]["exit_reason"] == "trailing"
