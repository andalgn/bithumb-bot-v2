"""설정 로딩 모듈.

config.yaml + .env에서 설정을 로딩하여 dataclass로 제공한다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

# 프로젝트 루트
PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class SizingConfig:
    """사이징 설정."""

    active_risk_pct: float = 0.03
    core_risk_pct: float = 0.10
    reserve_risk_pct: float = 0.05
    dca_core_pct: float = 0.04
    pool_cap_pct: float = 0.25
    active_min_krw: int = 5000
    core_min_krw: int = 10000
    vol_target_mult_min: float = 0.5
    vol_target_mult_max: float = 1.5
    defense_mult_min: float = 0.3
    defense_mult_max: float = 1.0
    atr_sizing_enabled: bool = False
    atr_target_pct: float = 0.01


@dataclass(frozen=True)
class ScoreCutoffGroup:
    """점수 컷오프 그룹."""

    full: int = 72
    probe_min: int = 55
    probe_max: int = 71


@dataclass(frozen=True)
class ScoreCutoffConfig:
    """점수 컷오프 설정."""

    group1: ScoreCutoffGroup = field(default_factory=lambda: ScoreCutoffGroup())
    group2: ScoreCutoffGroup = field(
        default_factory=lambda: ScoreCutoffGroup(full=78, probe_min=62, probe_max=77)
    )
    group3: ScoreCutoffGroup = field(
        default_factory=lambda: ScoreCutoffGroup(full=68, probe_min=53, probe_max=67)
    )
    plus10_mult: float = 1.15
    plus20_mult: float = 1.25


@dataclass(frozen=True)
class RegimeConfig:
    """국면 분류 설정."""

    ema_periods: list[int] = field(default_factory=lambda: [20, 50, 200])
    adx_period: int = 14
    strong_up_adx: int = 25
    weak_up_adx: int = 20
    crisis_atr_mult: float = 2.5
    crisis_24h_drop: float = -0.10
    transition_confirm_bars: int = 3
    transition_cooldown_bars: int = 6
    crisis_release_bars: int = 6
    aux_flag_confirm_bars: int = 2


@dataclass(frozen=True)
class PromotionConfig:
    """승격 설정."""

    profit_pct: float = 0.012
    profit_hold_bars: int = 2
    adx_min: int = 20
    protection_bars: int = 2
    dca_wait_bars: int = 4
    dca_rescore_min: int = 55
    dca_profit_min: float = 0.02
    dca_max_per_position: int = 1
    re_promotion_verify_bars: int = 6


@dataclass(frozen=True)
class BacktestConfig:
    """백테스트 데몬 설정."""

    wf_time: str = "00:30"
    wf_data_days: int = 30
    wf_slide_days: int = 7
    wf_segments: int = 4
    wf_overfit_diff_pct: float = 0.5
    mc_time: str = "01:00"
    mc_day: str = "sunday"
    mc_iterations: int = 1000
    mc_danger_mdd_pct: float = 0.2
    sens_time: str = "01:30"
    sens_variation_pct: float = 0.1
    sens_steps: int = 5
    sens_robust_cv: float = 0.1
    sens_warning_cv: float = 0.3
    auto_optimize_enabled: bool = True
    auto_optimize_day: str = "sunday"
    auto_optimize_time: str = "02:00"
    auto_apply_min_pf: float = 1.0
    auto_apply_min_trades: int = 30
    data_collect_time: str = "00:00"
    auto_research_enabled: bool = True
    auto_research_day: str = "sunday"
    auto_research_time: str = "03:00"
    auto_research_max_experiments: int = 10
    auto_research_max_failures: int = 5


@dataclass(frozen=True)
class RiskGateConfig:
    """리스크 게이트 설정."""

    daily_dd_pct: float = 0.04
    weekly_dd_pct: float = 0.08
    monthly_dd_pct: float = 0.12
    total_dd_pct: float = 0.20
    max_exposure_pct: float = 0.90
    coin_quarantine_failures: int = 3
    coin_quarantine_sec: int = 120
    global_quarantine_failures: int = 8
    global_quarantine_sec: int = 60
    auth_error_quarantine_sec: int = 600
    consecutive_loss_limit: int = 3
    cooldown_min: int = 60


@dataclass(frozen=True)
class ExecutionConfig:
    """체결 설정."""

    order_timeout_sec: int = 30
    retry_count: int = 3
    retry_base_ms: int = 500
    price_deviation_pct: float = 0.003
    slippage_tier1: float = 0.0005
    slippage_tier2: float = 0.0010
    slippage_tier3: float = 0.0020
    spread_limit_tier1: float = 0.0018
    spread_limit_tier2: float = 0.0025
    spread_limit_tier3: float = 0.0035
    orderbook_depth_mult_tier1: int = 5
    orderbook_depth_mult_tier2: int = 3
    orderbook_depth_mult_tier3: int = 2


@dataclass(frozen=True)
class DiscordConfig:
    """디스코드 설정."""

    bot_guild_id: str = ""
    admin_role: str = "admin"
    timeout_sec: int = 5


@dataclass(frozen=True)
class BithumbConfig:
    """빗썸 API 설정."""

    base_url: str = "https://api.bithumb.com"
    public_rate_limit: int = 15
    private_rate_limit: int = 10
    min_order_krw: int = 5000
    max_candle_count: int = 1000


@dataclass(frozen=True)
class EnvSecrets:
    """환경 변수에서 로딩하는 민감 정보."""

    bithumb_api_key: str = ""
    bithumb_api_secret: str = ""
    bithumb_api_url: str = "https://api.bithumb.com"
    discord_bot_token: str = ""
    discord_webhooks: dict[str, str] = field(default_factory=dict)
    discord_guild_id: str = ""
    dashboard_api_key: str = ""
    dashboard_secret_key: str = ""
    deepseek_api_key: str = ""
    run_mode: str = "DRY"


@dataclass(frozen=True)
class HealthMonitorConfig:
    """헬스 모니터 설정."""

    enabled: bool = True
    interval_sec: int = 900
    reconciliation_interval_sec: int = 3600
    discord_check_interval_sec: int = 14400
    heartbeat_warn_sec: int = 1200
    heartbeat_critical_sec: int = 1800
    api_timeout_sec: int = 5
    api_consecutive_fail_critical: int = 3
    data_freshness_warn_min: int = 20
    data_freshness_critical_min: int = 40
    memory_warn_pct: int = 70
    disk_critical_pct: int = 90
    wal_warn_mb: int = 100
    daily_dd_warn_pct: float = 2.0
    daily_dd_critical_pct: float = 3.0
    alert_cooldown_critical_min: int = 30
    alert_cooldown_warning_min: int = 120
    retention_days: int = 90
    auto_fix_win_rate_threshold: float = 0.30
    auto_fix_min_trades: int = 10


@dataclass(frozen=True)
class MomentumRankingConfig:
    """모멘텀 랭킹 설정."""

    enabled: bool = False
    top_n: int = 10


@dataclass(frozen=True)
class CoinUniverseConfig:
    """동적 코인 유니버스 설정."""

    enabled: bool = False
    top_n: int = 20
    refresh_hour: int = 0


@dataclass
class AppConfig:
    """애플리케이션 전체 설정."""

    run_mode: str = "DRY"
    cycle_interval_sec: int = 900
    paper_test: bool = False
    coins: list[str] = field(default_factory=list)
    sizing: SizingConfig = field(default_factory=SizingConfig)
    score_cutoff: ScoreCutoffConfig = field(default_factory=ScoreCutoffConfig)
    regime: RegimeConfig = field(default_factory=RegimeConfig)
    promotion: PromotionConfig = field(default_factory=PromotionConfig)
    risk_gate: RiskGateConfig = field(default_factory=RiskGateConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    discord: DiscordConfig = field(default_factory=DiscordConfig)
    bithumb: BithumbConfig = field(default_factory=BithumbConfig)
    secrets: EnvSecrets = field(default_factory=EnvSecrets)
    strategy_params: dict = field(default_factory=dict)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    proxy: str = ""
    health_monitor: HealthMonitorConfig = field(default_factory=HealthMonitorConfig)
    momentum_ranking: MomentumRankingConfig = field(default_factory=MomentumRankingConfig)
    coin_universe: CoinUniverseConfig = field(default_factory=CoinUniverseConfig)


def _load_env() -> EnvSecrets:
    """환경 변수에서 민감 정보를 로딩한다."""
    env_path = PROJECT_ROOT / ".env"
    load_dotenv(env_path)
    return EnvSecrets(
        bithumb_api_key=os.getenv("BITHUMB_API_KEY", ""),
        bithumb_api_secret=os.getenv("BITHUMB_API_SECRET", ""),
        bithumb_api_url=os.getenv("BITHUMB_API_URL", "https://api.bithumb.com"),
        discord_bot_token=os.getenv("DISCORD_BOT_TOKEN", ""),
        discord_webhooks={
            "trade": os.getenv("DISCORD_WEBHOOK_TRADE", ""),
            "report": os.getenv("DISCORD_WEBHOOK_REPORT", ""),
            "backtest": os.getenv("DISCORD_WEBHOOK_BACKTEST", ""),
            "system": os.getenv("DISCORD_WEBHOOK_SYSTEM", ""),
            "command": os.getenv("DISCORD_WEBHOOK_COMMAND", ""),
            "livegate": os.getenv("DISCORD_WEBHOOK_LIVEGATE", ""),
        },
        discord_guild_id=os.getenv("DISCORD_GUILD_ID", ""),
        dashboard_api_key=os.getenv("DASHBOARD_API_KEY", ""),
        dashboard_secret_key=os.getenv("DASHBOARD_SECRET_KEY", ""),
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        run_mode=os.getenv("RUN_MODE", "DRY"),
    )


def _build_sizing(raw: dict) -> SizingConfig:
    """사이징 설정을 빌드한다."""
    if not raw:
        return SizingConfig()
    return SizingConfig(**{k: v for k, v in raw.items() if v is not None})


def _build_score_cutoff(raw: dict) -> ScoreCutoffConfig:
    """점수 컷오프 설정을 빌드한다."""
    if not raw:
        return ScoreCutoffConfig()
    g1 = ScoreCutoffGroup(**raw["group1"]) if "group1" in raw else ScoreCutoffGroup()
    g2 = (
        ScoreCutoffGroup(**raw["group2"])
        if "group2" in raw
        else ScoreCutoffGroup(full=78, probe_min=62, probe_max=77)
    )
    g3 = (
        ScoreCutoffGroup(**raw["group3"])
        if "group3" in raw
        else ScoreCutoffGroup(full=68, probe_min=53, probe_max=67)
    )
    bonus = raw.get("high_bonus", {})
    return ScoreCutoffConfig(
        group1=g1,
        group2=g2,
        group3=g3,
        plus10_mult=bonus.get("plus10_mult", 1.15),
        plus20_mult=bonus.get("plus20_mult", 1.25),
    )


def _build_regime(raw: dict) -> RegimeConfig:
    """국면 분류 설정을 빌드한다."""
    if not raw:
        return RegimeConfig()
    return RegimeConfig(**{k: v for k, v in raw.items() if v is not None})


def _build_execution(raw: dict) -> ExecutionConfig:
    """체결 설정을 빌드한다."""
    if not raw:
        return ExecutionConfig()
    slip = raw.get("slippage", {})
    spread = raw.get("spread_limit", {})
    depth = raw.get("orderbook_depth_mult", {})
    return ExecutionConfig(
        order_timeout_sec=raw.get("order_timeout_sec", 30),
        retry_count=raw.get("retry_count", 3),
        retry_base_ms=raw.get("retry_base_ms", 500),
        price_deviation_pct=raw.get("price_deviation_pct", 0.003),
        slippage_tier1=slip.get("tier1", 0.0005),
        slippage_tier2=slip.get("tier2", 0.0010),
        slippage_tier3=slip.get("tier3", 0.0020),
        spread_limit_tier1=spread.get("tier1", 0.0018),
        spread_limit_tier2=spread.get("tier2", 0.0025),
        spread_limit_tier3=spread.get("tier3", 0.0035),
        orderbook_depth_mult_tier1=depth.get("tier1", 5),
        orderbook_depth_mult_tier2=depth.get("tier2", 3),
        orderbook_depth_mult_tier3=depth.get("tier3", 2),
    )


def load_config(
    config_path: Path | None = None,
) -> AppConfig:
    """config.yaml + .env를 로딩하여 AppConfig를 반환한다.

    Args:
        config_path: config.yaml 경로. None이면 기본 경로 사용.

    Returns:
        완성된 AppConfig 인스턴스.
    """
    if config_path is None:
        config_path = PROJECT_ROOT / "configs" / "config.yaml"

    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    secrets = _load_env()

    # run_mode: .env가 우선, config.yaml이 폴백
    run_mode = secrets.run_mode or raw.get("run_mode", "DRY")

    return AppConfig(
        run_mode=run_mode,
        cycle_interval_sec=raw.get("cycle_interval_sec", 900),
        paper_test=raw.get("paper_test", False),
        coins=raw.get("coins", []),
        sizing=_build_sizing(raw.get("sizing", {})),
        score_cutoff=_build_score_cutoff(raw.get("score_cutoff", {})),
        regime=_build_regime(raw.get("regime", {})),
        promotion=PromotionConfig(
            **{k: v for k, v in raw.get("promotion", {}).items() if v is not None}
        ),
        risk_gate=RiskGateConfig(
            **{k: v for k, v in raw.get("risk_gate", {}).items() if v is not None}
        ),
        execution=_build_execution(raw.get("execution", {})),
        discord=DiscordConfig(
            bot_guild_id=secrets.discord_guild_id,
            admin_role=raw.get("discord", {}).get("admin_role", "admin"),
            timeout_sec=raw.get("discord", {}).get("timeout_sec", 5),
        ),
        bithumb=BithumbConfig(**{k: v for k, v in raw.get("bithumb", {}).items() if v is not None}),
        secrets=secrets,
        strategy_params=raw.get("strategy_params", {}),
        backtest=_build_backtest(raw.get("backtest", {})),
        proxy=raw.get("proxy", "") or os.environ.get("HTTPS_PROXY", ""),
        health_monitor=_build_health_monitor(raw.get("health_monitor", {})),
        momentum_ranking=_build_momentum_ranking(raw.get("momentum_ranking", {})),
        coin_universe=_build_coin_universe(raw.get("coin_universe", {})),
    )


def _build_health_monitor(raw: dict) -> HealthMonitorConfig:
    """health_monitor 섹션을 파싱한다."""
    if not raw:
        return HealthMonitorConfig()
    fields = HealthMonitorConfig.__dataclass_fields__
    return HealthMonitorConfig(**{k: v for k, v in raw.items() if k in fields and v is not None})


def _build_momentum_ranking(raw: dict) -> MomentumRankingConfig:
    """momentum_ranking 섹션을 파싱한다."""
    if not raw:
        return MomentumRankingConfig()
    fields = MomentumRankingConfig.__dataclass_fields__
    cfg = MomentumRankingConfig(**{k: v for k, v in raw.items() if k in fields and v is not None})
    # top_n=0이면 모든 신호가 차단되므로 최소 1 보장
    if cfg.top_n < 1:
        cfg = MomentumRankingConfig(enabled=cfg.enabled, top_n=1)
    return cfg


def _build_coin_universe(raw: dict) -> CoinUniverseConfig:
    """coin_universe 섹션을 파싱한다."""
    if not raw:
        return CoinUniverseConfig()
    fields = CoinUniverseConfig.__dataclass_fields__
    return CoinUniverseConfig(**{k: v for k, v in raw.items() if k in fields and v is not None})


def _build_backtest(raw: dict) -> BacktestConfig:
    """backtest 섹션을 파싱한다."""
    wf = raw.get("walk_forward", {})
    mc = raw.get("monte_carlo", {})
    sens = raw.get("sensitivity", {})
    opt = raw.get("auto_optimize", {})
    research = raw.get("auto_research", {})
    return BacktestConfig(
        wf_time=str(wf.get("time", "00:30")),
        wf_data_days=wf.get("data_days", 30),
        wf_slide_days=wf.get("slide_days", 7),
        wf_segments=wf.get("segments", 4),
        wf_overfit_diff_pct=wf.get("overfit_diff_pct", 0.5),
        mc_time=str(mc.get("time", "01:00")),
        mc_day=mc.get("day", "sunday"),
        mc_iterations=mc.get("iterations", 1000),
        mc_danger_mdd_pct=mc.get("danger_mdd_pct", 0.2),
        sens_time=str(sens.get("time", "01:30")),
        sens_variation_pct=sens.get("variation_pct", 0.1),
        sens_steps=sens.get("steps", 5),
        sens_robust_cv=sens.get("robust_cv", 0.1),
        sens_warning_cv=sens.get("warning_cv", 0.3),
        auto_optimize_enabled=opt.get("enabled", True),
        auto_optimize_day=opt.get("day", "sunday"),
        auto_optimize_time=str(opt.get("time", "02:00")),
        auto_apply_min_pf=opt.get("min_pf", 1.0),
        auto_apply_min_trades=opt.get("min_trades", 30),
        data_collect_time=str(raw.get("data_collect_time", "00:00")),
        auto_research_enabled=research.get("enabled", True),
        auto_research_day=research.get("day", "sunday"),
        auto_research_time=str(research.get("time", "03:00")),
        auto_research_max_experiments=research.get("max_experiments", 10),
        auto_research_max_failures=research.get("max_consecutive_failures", 5),
    )
