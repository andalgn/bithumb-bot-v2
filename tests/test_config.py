"""설정 로딩 테스트.

config.yaml 로딩, 기본값, 환경변수 오버라이드를 테스트한다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import (
    AppConfig,
    ScoreCutoffConfig,
    ScoreCutoffGroup,
    SizingConfig,
    load_config,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """load_dotenv를 무력화하여 .env 파일이 테스트에 영향을 주지 않게 한다."""
    monkeypatch.setattr("app.config.load_dotenv", lambda *_a, **_kw: None)
    monkeypatch.delenv("RUN_MODE", raising=False)
    monkeypatch.delenv("BITHUMB_API_KEY", raising=False)
    monkeypatch.delenv("BITHUMB_API_SECRET", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)


@pytest.fixture
def minimal_config_yaml(tmp_path: Path) -> Path:
    """최소 config.yaml 파일을 생성한다."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "run_mode: PAPER\n"
        "cycle_interval_sec: 300\n"
        "paper_test: true\n"
        "coins:\n"
        "  - BTC\n"
        "  - ETH\n",
        encoding="utf-8",
    )
    return cfg


@pytest.fixture
def full_config_yaml(tmp_path: Path) -> Path:
    """모든 섹션을 포함한 config.yaml을 생성한다."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        """\
run_mode: DRY
cycle_interval_sec: 900
paper_test: false
coins:
  - BTC
  - ETH
  - XRP

sizing:
  active_risk_pct: 0.05
  core_risk_pct: 0.12
  active_min_krw: 10000

score_cutoff:
  group1:
    full: 75
    probe_min: 60
    probe_max: 74
  group2:
    full: 80
    probe_min: 65
    probe_max: 79
  group3:
    full: 75
    probe_min: 68
    probe_max: 74
  high_bonus:
    plus10_mult: 1.20
    plus20_mult: 1.30

regime:
  ema_periods: [20, 50, 200]
  adx_period: 14

promotion:
  profit_pct: 0.015
  adx_min: 25

risk_gate:
  daily_dd_pct: 0.05
  consecutive_loss_limit: 4

execution:
  order_timeout_sec: 45
  slippage:
    tier1: 0.0006
    tier2: 0.0012
    tier3: 0.0024
  spread_limit:
    tier1: 0.0020
  orderbook_depth_mult:
    tier1: 6

telegram:
  timeout_sec: 10

bithumb:
  base_url: https://api.bithumb.com
  public_rate_limit: 20
""",
        encoding="utf-8",
    )
    return cfg


# ---------------------------------------------------------------------------
# SizingConfig defaults
# ---------------------------------------------------------------------------

class TestSizingConfigDefaults:
    """SizingConfig 기본값 테스트."""

    def test_defaults(self) -> None:
        """기본 사이징 값을 확인한다."""
        s = SizingConfig()
        assert s.active_risk_pct == 0.03
        assert s.core_risk_pct == 0.10
        assert s.reserve_risk_pct == 0.05
        assert s.dca_core_pct == 0.04
        assert s.pool_cap_pct == 0.25
        assert s.active_min_krw == 5000
        assert s.core_min_krw == 10000
        assert s.vol_target_mult_min == 0.5
        assert s.vol_target_mult_max == 1.5
        assert s.defense_mult_min == 0.3
        assert s.defense_mult_max == 1.0


# ---------------------------------------------------------------------------
# ScoreCutoffGroup / ScoreCutoffConfig
# ---------------------------------------------------------------------------

class TestScoreCutoffConfig:
    """점수 컷오프 설정 테스트."""

    def test_group1_default(self) -> None:
        """group1 기본값을 확인한다."""
        g = ScoreCutoffGroup()
        assert g.full == 72
        assert g.probe_min == 55
        assert g.probe_max == 71

    def test_group2_default(self) -> None:
        """group2 기본값 (config default)을 확인한다."""
        cfg = ScoreCutoffConfig()
        assert cfg.group2.full == 78
        assert cfg.group2.probe_min == 62
        assert cfg.group2.probe_max == 77

    def test_group3_default(self) -> None:
        """group3 기본값을 확인한다."""
        cfg = ScoreCutoffConfig()
        assert cfg.group3.full == 68
        assert cfg.group3.probe_min == 53
        assert cfg.group3.probe_max == 67

    def test_bonus_multipliers(self) -> None:
        """보너스 배수 기본값을 확인한다."""
        cfg = ScoreCutoffConfig()
        assert cfg.plus10_mult == 1.15
        assert cfg.plus20_mult == 1.25


# ---------------------------------------------------------------------------
# load_config — minimal yaml
# ---------------------------------------------------------------------------

class TestLoadConfigMinimal:
    """최소 config.yaml 로딩 테스트."""

    def test_run_mode_from_env_default(
        self, minimal_config_yaml: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """RUN_MODE 환경변수가 없으면 os.getenv 기본값 DRY가 우선한다."""
        monkeypatch.delenv("RUN_MODE", raising=False)
        cfg = load_config(minimal_config_yaml)
        # secrets.run_mode="DRY" (os.getenv default) -> yaml 폴백 안 됨
        assert cfg.run_mode == "DRY"

    def test_run_mode_yaml_fallback(
        self, minimal_config_yaml: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """secrets.run_mode가 빈 문자열이면 yaml의 run_mode를 사용한다."""
        monkeypatch.setenv("RUN_MODE", "")
        cfg = load_config(minimal_config_yaml)
        assert cfg.run_mode == "PAPER"

    def test_cycle_interval(
        self, minimal_config_yaml: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """cycle_interval_sec가 올바르게 로딩된다."""
        monkeypatch.delenv("RUN_MODE", raising=False)
        cfg = load_config(minimal_config_yaml)
        assert cfg.cycle_interval_sec == 300

    def test_paper_test_true(
        self, minimal_config_yaml: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """paper_test: true가 올바르게 파싱된다."""
        monkeypatch.delenv("RUN_MODE", raising=False)
        cfg = load_config(minimal_config_yaml)
        assert cfg.paper_test is True

    def test_coins(
        self, minimal_config_yaml: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """코인 목록이 올바르게 로딩된다."""
        monkeypatch.delenv("RUN_MODE", raising=False)
        cfg = load_config(minimal_config_yaml)
        assert cfg.coins == ["BTC", "ETH"]

    def test_sizing_uses_defaults(
        self, minimal_config_yaml: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """sizing 섹션이 없으면 기본값을 사용한다."""
        monkeypatch.delenv("RUN_MODE", raising=False)
        cfg = load_config(minimal_config_yaml)
        assert cfg.sizing == SizingConfig()


# ---------------------------------------------------------------------------
# load_config — full yaml
# ---------------------------------------------------------------------------

class TestLoadConfigFull:
    """전체 config.yaml 로딩 테스트."""

    def test_sizing_override(
        self, full_config_yaml: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """sizing 값이 yaml에서 오버라이드된다."""
        monkeypatch.delenv("RUN_MODE", raising=False)
        cfg = load_config(full_config_yaml)
        assert cfg.sizing.active_risk_pct == 0.05
        assert cfg.sizing.core_risk_pct == 0.12
        assert cfg.sizing.active_min_krw == 10000

    def test_score_cutoff_from_yaml(
        self, full_config_yaml: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """score_cutoff가 yaml에서 올바르게 로딩된다."""
        monkeypatch.delenv("RUN_MODE", raising=False)
        cfg = load_config(full_config_yaml)
        assert cfg.score_cutoff.group1.full == 75
        assert cfg.score_cutoff.group2.full == 80
        assert cfg.score_cutoff.group3.probe_min == 68
        assert cfg.score_cutoff.plus10_mult == 1.20
        assert cfg.score_cutoff.plus20_mult == 1.30

    def test_promotion_override(
        self, full_config_yaml: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """promotion 값이 yaml에서 오버라이드된다."""
        monkeypatch.delenv("RUN_MODE", raising=False)
        cfg = load_config(full_config_yaml)
        assert cfg.promotion.profit_pct == 0.015
        assert cfg.promotion.adx_min == 25

    def test_execution_nested(
        self, full_config_yaml: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """execution의 중첩 구조가 올바르게 파싱된다."""
        monkeypatch.delenv("RUN_MODE", raising=False)
        cfg = load_config(full_config_yaml)
        assert cfg.execution.order_timeout_sec == 45
        assert cfg.execution.slippage_tier1 == 0.0006
        assert cfg.execution.spread_limit_tier1 == 0.0020
        assert cfg.execution.orderbook_depth_mult_tier1 == 6

    def test_bithumb_config(
        self, full_config_yaml: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """bithumb 설정이 올바르게 로딩된다."""
        monkeypatch.delenv("RUN_MODE", raising=False)
        cfg = load_config(full_config_yaml)
        assert cfg.bithumb.public_rate_limit == 20

    def test_telegram_config(
        self, full_config_yaml: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """telegram 설정이 올바르게 로딩된다."""
        monkeypatch.delenv("RUN_MODE", raising=False)
        cfg = load_config(full_config_yaml)
        assert cfg.telegram.timeout_sec == 10


# ---------------------------------------------------------------------------
# Environment variable override
# ---------------------------------------------------------------------------

class TestEnvOverride:
    """환경변수 오버라이드 테스트."""

    def test_run_mode_env_overrides_yaml(
        self, minimal_config_yaml: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """RUN_MODE 환경변수가 yaml보다 우선한다."""
        monkeypatch.setenv("RUN_MODE", "LIVE")
        cfg = load_config(minimal_config_yaml)
        assert cfg.run_mode == "LIVE"

    def test_run_mode_env_dry(
        self, minimal_config_yaml: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """RUN_MODE=DRY 환경변수 테스트."""
        monkeypatch.setenv("RUN_MODE", "DRY")
        cfg = load_config(minimal_config_yaml)
        assert cfg.run_mode == "DRY"


# ---------------------------------------------------------------------------
# paper_test flag
# ---------------------------------------------------------------------------

class TestPaperTestFlag:
    """paper_test 플래그 테스트."""

    def test_paper_test_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """paper_test: false가 올바르게 파싱된다."""
        monkeypatch.delenv("RUN_MODE", raising=False)
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            "run_mode: DRY\npaper_test: false\ncoins: []\n",
            encoding="utf-8",
        )
        cfg = load_config(cfg_file)
        assert cfg.paper_test is False

    def test_paper_test_missing_defaults_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """paper_test가 없으면 기본값 False이다."""
        monkeypatch.delenv("RUN_MODE", raising=False)
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            "run_mode: DRY\ncoins: []\n",
            encoding="utf-8",
        )
        cfg = load_config(cfg_file)
        assert cfg.paper_test is False


# ---------------------------------------------------------------------------
# Default config.yaml (프로젝트 실제 파일)
# ---------------------------------------------------------------------------

class TestDefaultConfigYaml:
    """프로젝트 기본 config.yaml 로딩 테스트."""

    def test_loads_without_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """프로젝트 기본 config.yaml을 에러 없이 로딩한다."""
        monkeypatch.delenv("RUN_MODE", raising=False)
        cfg = load_config()
        assert isinstance(cfg, AppConfig)
        assert len(cfg.coins) == 10
        assert "BTC" in cfg.coins

    def test_default_10_coins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """기본 설정에 10개 코인이 있다."""
        monkeypatch.delenv("RUN_MODE", raising=False)
        cfg = load_config()
        expected = ["BTC", "ETH", "XRP", "SOL", "RENDER",
                     "VIRTUAL", "EIGEN", "ONDO", "TAO", "LDO"]
        assert cfg.coins == expected
