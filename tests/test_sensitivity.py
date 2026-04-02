"""파라미터 민감도 분석 테스트."""

import pytest

from backtesting.sensitivity import SensitivityAnalyzer


@pytest.fixture
def analyzer() -> SensitivityAnalyzer:
    """테스트용 SensitivityAnalyzer."""
    return SensitivityAnalyzer(variation_pct=0.10, steps=5)


def _make_trades(count: int = 30) -> list[dict]:
    """테스트용 거래."""
    return [
        {"entry_price": 50_000_000, "exit_price": 50_500_000, "qty": 0.001} for _ in range(count)
    ]


class TestSensitivity:
    """민감도 분석 테스트."""

    def test_empty(self, analyzer: SensitivityAnalyzer) -> None:
        """빈 데이터."""
        result = analyzer.run({}, [])
        assert len(result.params) == 0

    def test_basic_analysis(self, analyzer: SensitivityAnalyzer) -> None:
        """기본 분석."""
        params = {"rsi_lower": 30.0, "atr_mult": 2.0}
        trades = _make_trades()
        result = analyzer.run(params, trades)
        assert len(result.params) == 2
        for p in result.params:
            assert p.cv >= 0
            assert p.verdict in ("robust", "normal", "sensitive", "danger")

    def test_cv_categories(self, analyzer: SensitivityAnalyzer) -> None:
        """CV 판정 카테고리."""
        params = {"cutoff": 72.0}
        trades = _make_trades()
        result = analyzer.run(params, trades)
        assert result.robust_count + result.sensitive_count <= len(result.params)

    def test_values_and_sharpes_populated(self, analyzer: SensitivityAnalyzer) -> None:
        """테스트 값/Sharpe 리스트 채워짐."""
        params = {"rsi_lower": 30.0}
        trades = _make_trades()
        result = analyzer.run(params, trades)
        for p in result.params:
            assert len(p.values) == 5
            assert len(p.sharpes) == 5
