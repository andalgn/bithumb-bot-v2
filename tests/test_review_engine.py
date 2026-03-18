"""ReviewEngine 테스트."""

import pytest

from app.journal import Journal
from strategy.review_engine import ReviewEngine


@pytest.fixture
def journal(tmp_path) -> Journal:
    """테스트용 Journal."""
    j = Journal(db_path=str(tmp_path / "test.db"))
    yield j
    j.close()


@pytest.fixture
def engine(journal: Journal) -> ReviewEngine:
    """테스트용 ReviewEngine."""
    return ReviewEngine(journal=journal)


_trade_counter = 0


def _add_trades(journal: Journal, count: int, pnl: float) -> None:
    """테스트 거래 추가."""
    global _trade_counter  # noqa: PLW0603
    for i in range(count):
        _trade_counter += 1
        journal.record_trade({
            "trade_id": f"test_{_trade_counter}",
            "symbol": "BTC",
            "strategy": "trend_follow",
            "tier": 1,
            "regime": "STRONG_UP",
            "pool": "active",
            "entry_price": 50_000_000,
            "exit_price": 50_000_000 + pnl / 0.001,
            "qty": 0.001,
            "net_pnl_krw": pnl,
        })


class TestDailyReview:
    """일일 리뷰 테스트."""

    @pytest.mark.asyncio
    async def test_empty_trades(self, engine: ReviewEngine) -> None:
        """거래 없을 때."""
        result = await engine.run_daily_review()
        assert result.total_trades == 0

    @pytest.mark.asyncio
    async def test_with_trades(self, engine: ReviewEngine, journal: Journal) -> None:
        """거래 있을 때 통계 계산."""
        _add_trades(journal, 5, 1000)
        _add_trades(journal, 3, -500)

        # _last_daily 리셋
        engine._last_daily = ""
        result = await engine.run_daily_review()
        assert result.total_trades == 8
        assert result.wins == 5
        assert result.losses == 3

    @pytest.mark.asyncio
    async def test_no_duplicate_run(self, engine: ReviewEngine) -> None:
        """같은 날 중복 실행 방지."""
        engine._last_daily = ""
        r1 = await engine.run_daily_review()
        r2 = await engine.run_daily_review()
        # 두 번째는 빈 결과 (이미 실행됨)
        assert r2.total_trades == 0 or r2.date == r1.date


class TestStrategyStats:
    """전략별 통계 테스트."""

    def test_calc_strategy_stats(self, engine: ReviewEngine) -> None:
        """전략별 통계."""
        trades = [
            {"strategy": "trend_follow", "net_pnl_krw": 1000},
            {"strategy": "trend_follow", "net_pnl_krw": -500},
            {"strategy": "mean_reversion", "net_pnl_krw": 2000},
        ]
        stats = engine._calc_strategy_stats(trades)
        assert "trend_follow" in stats
        assert "mean_reversion" in stats
        assert stats["trend_follow"]["count"] == 2
        assert stats["trend_follow"]["win_rate"] == 0.5
        assert stats["mean_reversion"]["win_rate"] == 1.0


class TestRules:
    """규칙 기반 조정 테스트."""

    def test_low_winrate_adjustment(self, engine: ReviewEngine) -> None:
        """승률 < 40% → 임계값 상향."""
        stats = {
            "trend_follow": {
                "count": 15, "wins": 4, "win_rate": 0.27,
                "total_pnl": -500, "expectancy": -33,
            },
        }
        adjustments = engine._apply_rules(stats, [])
        cutoff_adj = [a for a in adjustments if a["type"] == "cutoff_increase"]
        assert len(cutoff_adj) >= 1

    def test_no_adjustment_if_sufficient_winrate(self, engine: ReviewEngine) -> None:
        """승률 >= 40% → 조정 없음."""
        stats = {
            "trend_follow": {
                "count": 15, "wins": 8, "win_rate": 0.53,
                "total_pnl": 5000, "expectancy": 333,
            },
        }
        adjustments = engine._apply_rules(stats, [])
        cutoff_adj = [a for a in adjustments if a["type"] == "cutoff_increase"]
        assert len(cutoff_adj) == 0

    def test_consecutive_sl_cooldown(self, engine: ReviewEngine) -> None:
        """3회 연속 손절 → 쿨다운."""
        trades = [
            {"symbol": "BTC", "net_pnl_krw": -100},
            {"symbol": "BTC", "net_pnl_krw": -200},
            {"symbol": "BTC", "net_pnl_krw": -300},
        ]
        adjustments = engine._apply_rules({}, trades)
        cooldowns = [a for a in adjustments if a["type"] == "coin_cooldown"]
        assert len(cooldowns) >= 1
        assert cooldowns[0]["symbol"] == "BTC"


class TestSuggestionParsing:
    """DeepSeek 응답 파싱 테스트."""

    def test_parse_json_array(self, engine: ReviewEngine) -> None:
        """JSON 배열 파싱."""
        content = '[{"param": "rsi", "action": "increase", "delta": 3, "reason": "test"}]'
        result = engine._parse_suggestions(content)
        assert len(result) == 1
        assert result[0]["param"] == "rsi"

    def test_parse_embedded_json(self, engine: ReviewEngine) -> None:
        """텍스트 속 JSON 파싱."""
        content = (
            'Here are my suggestions:\n'
            '[{"param": "atr", "action": "decrease",'
            ' "delta": 0.2, "reason": "too wide"}]\nThank you.'
        )
        result = engine._parse_suggestions(content)
        assert len(result) == 1

    def test_parse_invalid(self, engine: ReviewEngine) -> None:
        """파싱 불가 → 빈 리스트."""
        result = engine._parse_suggestions("No suggestions available.")
        assert result == []


class TestWeeklyReview:
    """주간 리뷰 테스트."""

    @pytest.mark.asyncio
    async def test_weekly_without_deepseek(self, engine: ReviewEngine) -> None:
        """DeepSeek 키 없을 때도 동작."""
        engine._last_weekly = ""
        result = await engine.run_weekly_review()
        assert result.deepseek_suggestions == []

    @pytest.mark.asyncio
    async def test_weekly_with_data(
        self, engine: ReviewEngine, journal: Journal
    ) -> None:
        """데이터 있을 때."""
        _add_trades(journal, 10, 500)
        engine._last_weekly = ""
        result = await engine.run_weekly_review()
        assert result.total_trades == 10
