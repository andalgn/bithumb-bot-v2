"""AutoResearcher 테스트."""

from __future__ import annotations

from unittest.mock import MagicMock

from strategy.auto_researcher import AutoResearcher, ExperimentResult


def _make_researcher() -> AutoResearcher:
    """테스트용 AutoResearcher를 생성한다 (의존성 없이)."""
    obj = AutoResearcher.__new__(AutoResearcher)
    obj._min_pf = 1.0
    obj._min_trades = 20
    obj._max_mdd = 0.15
    return obj


def _make_opt_result(
    profit_factor: float = 1.5,
    sharpe: float = 1.0,
    trades: int = 50,
    max_drawdown: float = 0.10,
) -> MagicMock:
    """테스트용 OptResult mock을 생성한다."""
    m = MagicMock()
    m.profit_factor = profit_factor
    m.sharpe = sharpe
    m.trades = trades
    m.max_drawdown = max_drawdown
    return m


# ═══════════════════════════════════════════
# _evaluate 테스트
# ═══════════════════════════════════════════


class TestEvaluate:
    """_evaluate 메서드 테스트."""

    def test_evaluate_improved(self) -> None:
        """PF 개선 + MDD/trades 충족 → True."""
        ar = _make_researcher()
        baseline = _make_opt_result(profit_factor=1.5, trades=50, max_drawdown=0.10)
        result = _make_opt_result(profit_factor=2.0, trades=50, max_drawdown=0.10)
        assert ar._evaluate(result, baseline) is True

    def test_evaluate_worse(self) -> None:
        """PF 하락 → False."""
        ar = _make_researcher()
        baseline = _make_opt_result(profit_factor=2.0)
        result = _make_opt_result(profit_factor=1.5)
        assert ar._evaluate(result, baseline) is False

    def test_evaluate_mdd_exceeded(self) -> None:
        """MDD > 15% → False (PF가 좋아도)."""
        ar = _make_researcher()
        baseline = _make_opt_result(profit_factor=1.5)
        result = _make_opt_result(profit_factor=3.0, max_drawdown=0.20)
        assert ar._evaluate(result, baseline) is False

    def test_evaluate_too_few_trades(self) -> None:
        """trades < 20 → False."""
        ar = _make_researcher()
        baseline = _make_opt_result(profit_factor=1.5)
        result = _make_opt_result(profit_factor=2.0, trades=10)
        assert ar._evaluate(result, baseline) is False


# ═══════════════════════════════════════════
# _parse_proposal 테스트
# ═══════════════════════════════════════════


class TestParseProposal:
    """_parse_proposal 메서드 테스트."""

    def test_parse_proposal_json_block(self) -> None:
        """```json ... ``` 형식 파싱."""
        ar = _make_researcher()
        content = (
            "제안합니다:\n"
            "```json\n"
            '{"params": {"sl_mult": 2.5}, "hypothesis": "SL 조정", '
            '"expected_impact": "손실 감소"}\n'
            "```\n"
            "이상입니다."
        )
        result = ar._parse_proposal(content)
        assert result is not None
        assert result["params"]["sl_mult"] == 2.5
        assert result["hypothesis"] == "SL 조정"

    def test_parse_proposal_raw_json(self) -> None:
        """raw JSON 형식 파싱."""
        ar = _make_researcher()
        content = (
            '{"params": {"tp_rr": 3.0}, "hypothesis": "TP 확대", '
            '"expected_impact": "수익 증가"}'
        )
        result = ar._parse_proposal(content)
        assert result is not None
        assert result["params"]["tp_rr"] == 3.0


# ═══════════════════════════════════════════
# _validate_bounds 테스트
# ═══════════════════════════════════════════


class TestValidateBounds:
    """_validate_bounds 메서드 테스트."""

    def test_validate_bounds_ok(self) -> None:
        """범위 내 파라미터 → True."""
        ar = _make_researcher()
        params = {"sl_mult": 2.5, "tp_rr": 3.0, "w_trend_align": 30}
        assert ar._validate_bounds("trend_follow", params) is True

    def test_validate_bounds_exceeded(self) -> None:
        """범위 초과 파라미터 → False."""
        ar = _make_researcher()
        params = {"sl_mult": 10.0}  # max 5.0
        assert ar._validate_bounds("trend_follow", params) is False


# ═══════════════════════════════════════════
# _log_result 테스트
# ═══════════════════════════════════════════


class TestLogResult:
    """_log_result 메서드 테스트."""

    def test_log_result_creates_tsv(self, tmp_path: object) -> None:
        """TSV 파일 생성 + 헤더 + 데이터 행."""
        from pathlib import Path

        log_file = Path(str(tmp_path)) / "test_log.tsv"
        ar = _make_researcher()
        ar._log_path = log_file

        exp = ExperimentResult(
            experiment_id="abc123",
            strategy="trend_follow",
            params_changed={"sl_mult": 2.5},
            baseline_pf=1.5,
            result_pf=2.0,
            baseline_sharpe=1.0,
            result_sharpe=1.5,
            trades=50,
            mdd=0.10,
            verdict="KEEP",
            description="SL 테스트",
        )
        ar._log_result(exp)

        assert log_file.exists()
        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2  # 헤더 + 1행
        assert lines[0].startswith("experiment_id")
        assert "abc123" in lines[1]
        assert "KEEP" in lines[1]

        # 2번째 기록 추가 시 헤더 안 붙음
        ar._log_result(exp)
        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 3
