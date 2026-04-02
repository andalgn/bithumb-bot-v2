"""진화 가능 파라미터 단일 관리 모듈.

Karpathy Auto Research의 'train.py'에 해당 — 에이전트가 수정하는 유일한 파일.
모든 진화 가능 파라미터를 하나의 dataclass에 집중하고,
코드 레벨에서 MIN/MAX 범위를 강제한다.

사용:
    params = EvolvableParams.from_config(app_config)
    changes = params.diff(proposed_params)
    violations = proposed_params.validate()
"""

from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass, fields
from typing import Any

logger = logging.getLogger(__name__)


# ── 파라미터 범위 정의 ─────────────────────────────────────
# (min, max) 튜플. 모든 파라미터는 이 범위 안에서만 진화 가능.
# 이 딕셔너리가 구조적 안전장치 — 프롬프트가 아닌 코드로 강제.

PARAM_BOUNDS: dict[str, tuple[float, float]] = {
    # ── 전략: TREND_FOLLOW ──
    "tf_sl_mult": (1.0, 8.0),
    "tf_tp_rr": (1.0, 5.0),
    "tf_cutoff": (55, 90),
    "tf_w_trend_align": (0.0, 45.0),
    "tf_w_macd": (0.0, 40.0),
    "tf_w_volume": (0.0, 35.0),
    "tf_w_rsi_pullback": (0.0, 30.0),
    "tf_w_supertrend": (0.0, 25.0),
    # ── 전략: MEAN_REVERSION ──
    "mr_sl_mult": (2.0, 10.0),
    "mr_tp_rr": (1.0, 4.0),
    # ── 전략: BREAKOUT ──
    "bo_sl_mult": (1.0, 5.0),
    "bo_tp_rr": (1.5, 5.0),
    # ── 전략: DCA ──
    "dca_sl_pct": (0.02, 0.08),
    "dca_tp_pct": (0.01, 0.05),
    # ── 리스크 ──
    "daily_dd_pct": (0.02, 0.06),
    "weekly_dd_pct": (0.04, 0.10),
    "consecutive_loss_limit": (2, 7),
    "cooldown_min": (30, 120),
    "max_exposure_pct": (0.70, 0.95),
    # ── 사이징 ──
    "active_risk_pct": (0.03, 0.12),
    "pool_cap_pct": (0.15, 0.35),
    "defense_mult_min": (0.1, 0.5),
    "defense_mult_max": (0.7, 1.0),
    "vol_target_mult_min": (0.5, 1.0),
    "vol_target_mult_max": (1.0, 2.0),
    # ── 국면 판정 ──
    "regime_adx_strong": (18, 35),
    "regime_atr_spike_mult": (1.3, 3.0),
    # ── 환경 필터 ──
    "l1_volume_ratio": (0.5, 1.0),
    "l1_momentum_burst_pct": (0.01, 0.03),
    # ── 승격 ──
    "promotion_profit_pct": (0.008, 0.025),
    "promotion_hold_bars": (1, 5),
    "promotion_adx_min": (15, 30),
}

# int 의미론 필드 — apply_changes()에서 자동 반올림 + to_config_patches()에서 int 변환
INT_FIELDS: set[str] = {
    "tf_cutoff",
    "consecutive_loss_limit",
    "cooldown_min",
    "regime_adx_strong",
    "promotion_hold_bars",
    "promotion_adx_min",
}


@dataclass(frozen=True)
class EvolvableParams:
    """진화 가능한 모든 파라미터.

    총 ~32개 파라미터. 각 필드는 PARAM_BOUNDS의 키와 1:1 대응.
    frozen=True — 직접 변경 불가. 반드시 apply_changes()를 사용.
    """

    # ── 전략: TREND_FOLLOW ──────────────────────────────
    tf_sl_mult: float = 5.0
    tf_tp_rr: float = 1.5
    tf_cutoff: int = 75
    tf_w_trend_align: float = 30.0
    tf_w_macd: float = 25.0
    tf_w_volume: float = 20.0
    tf_w_rsi_pullback: float = 15.0
    tf_w_supertrend: float = 10.0

    # ── 전략: MEAN_REVERSION ────────────────────────────
    mr_sl_mult: float = 7.0
    mr_tp_rr: float = 1.5

    # ── 전략: BREAKOUT ──────────────────────────────────
    bo_sl_mult: float = 2.0
    bo_tp_rr: float = 3.0

    # ── 전략: DCA ───────────────────────────────────────
    dca_sl_pct: float = 0.05
    dca_tp_pct: float = 0.03

    # ── 리스크 임계값 ───────────────────────────────────
    daily_dd_pct: float = 0.04
    weekly_dd_pct: float = 0.08
    consecutive_loss_limit: int = 3
    cooldown_min: int = 60
    max_exposure_pct: float = 0.90

    # ── 사이징 ──────────────────────────────────────────
    active_risk_pct: float = 0.07
    pool_cap_pct: float = 0.25
    defense_mult_min: float = 0.3
    defense_mult_max: float = 1.0
    vol_target_mult_min: float = 0.8
    vol_target_mult_max: float = 1.5

    # ── 국면 판정 ───────────────────────────────────────
    regime_adx_strong: int = 25
    regime_atr_spike_mult: float = 2.5

    # ── 환경 필터 ───────────────────────────────────────
    l1_volume_ratio: float = 0.8
    l1_momentum_burst_pct: float = 0.015

    # ── 승격 조건 ───────────────────────────────────────
    promotion_profit_pct: float = 0.012
    promotion_hold_bars: int = 2
    promotion_adx_min: int = 20

    # ── 유틸리티 메서드 ─────────────────────────────────

    def __post_init__(self) -> None:
        """NaN/Inf 값은 즉시 거부한다 (구조적 안전장치)."""
        for f in fields(self):
            value = getattr(self, f.name)
            if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
                raise ValueError(f"{f.name}={value} — NaN/Inf 값 불허")

    def validate(self) -> list[str]:
        """모든 파라미터의 범위를 검증한다.

        Returns:
            위반 내역 목록. 빈 리스트면 모두 통과.
        """
        violations: list[str] = []
        for f in fields(self):
            name = f.name
            value = getattr(self, name)

            # NaN/Inf 체크 (float 필드만)
            if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
                violations.append(f"{name}={value} — NaN/Inf 값 불허")
                continue

            bounds = PARAM_BOUNDS.get(name)
            if bounds is None:
                continue
            lo, hi = bounds
            if value < lo or value > hi:
                violations.append(f"{name}={value} 범위 위반 [{lo}, {hi}]")

        # 논리적 정합성
        if self.defense_mult_min >= self.defense_mult_max:
            violations.append(
                f"defense_mult_min({self.defense_mult_min}) >= "
                f"defense_mult_max({self.defense_mult_max})"
            )
        if self.vol_target_mult_min >= self.vol_target_mult_max:
            violations.append(
                f"vol_target_mult_min({self.vol_target_mult_min}) >= "
                f"vol_target_mult_max({self.vol_target_mult_max})"
            )
        if self.daily_dd_pct >= self.weekly_dd_pct:
            violations.append(
                f"daily_dd_pct({self.daily_dd_pct}) >= weekly_dd_pct({self.weekly_dd_pct})"
            )
        return violations

    def diff(self, other: EvolvableParams) -> dict[str, tuple[float, float]]:
        """두 파라미터 세트 간 차이를 반환한다.

        Returns:
            {param_name: (old_value, new_value)} 변경된 항목만.
        """
        changes: dict[str, tuple[float, float]] = {}
        for f in fields(self):
            old_val = getattr(self, f.name)
            new_val = getattr(other, f.name)
            if old_val != new_val:
                changes[f.name] = (old_val, new_val)
        return changes

    def apply_changes(self, changes: dict[str, float]) -> EvolvableParams:
        """변경사항을 적용한 새 인스턴스를 반환한다.

        범위 클램핑 + int 반올림 + 교차 필드 검증을 적용한다.

        Args:
            changes: {param_name: new_value}

        Returns:
            변경이 적용된 새 EvolvableParams.

        Raises:
            ValueError: 교차 필드 제약 위반 시.
        """
        data = asdict(self)
        for key, value in changes.items():
            if key not in data:
                logger.warning("알 수 없는 파라미터 무시: %s", key)
                continue
            bounds = PARAM_BOUNDS.get(key)
            if bounds:
                lo, hi = bounds
                value = max(lo, min(hi, value))
            if key in INT_FIELDS:
                value = int(round(value))
            data[key] = value
        new_params = EvolvableParams(**data)
        violations = new_params.validate()
        if violations:
            raise ValueError(f"교차 필드 제약 위반: {violations}")
        return new_params

    def to_dict(self) -> dict[str, float]:
        """딕셔너리로 변환한다."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvolvableParams:
        """딕셔너리에서 생성한다.

        알 수 없는 키는 무시한다.
        """
        valid_keys = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)

    @classmethod
    def from_config(cls, config: Any) -> EvolvableParams:
        """AppConfig에서 현재 값을 로드한다.

        config.yaml의 여러 섹션에 흩어진 파라미터를
        하나의 EvolvableParams로 통합한다.

        Args:
            config: AppConfig 인스턴스.

        Returns:
            현재 설정값 기반 EvolvableParams.
        """
        sp = config.strategy_params  # raw dict

        # 전략 파라미터 (base/default 값)
        tf = sp.get("trend_follow", {})
        mr = sp.get("mean_reversion", {})
        bo = sp.get("breakout", {})
        dca = sp.get("dca", {})

        return cls(
            # TREND_FOLLOW
            tf_sl_mult=tf.get("sl_mult", 5.0),
            tf_tp_rr=tf.get("tp_rr", 1.5),
            tf_cutoff=int(
                config.score_cutoff.group1.full if hasattr(config, "score_cutoff") else 75
            ),
            tf_w_trend_align=tf.get("w_trend_align", 30.0),
            tf_w_macd=tf.get("w_macd", 25.0),
            tf_w_volume=tf.get("w_volume", 20.0),
            tf_w_rsi_pullback=tf.get("w_rsi_pullback", 15.0),
            tf_w_supertrend=tf.get("w_supertrend", 10.0),
            # MEAN_REVERSION
            mr_sl_mult=mr.get("sl_mult", 7.0),
            mr_tp_rr=mr.get("tp_rr", 1.5),
            # BREAKOUT
            bo_sl_mult=bo.get("sl_mult", 2.0),
            bo_tp_rr=bo.get("tp_rr", 3.0),
            # DCA
            dca_sl_pct=dca.get("sl_pct", 0.05),
            dca_tp_pct=dca.get("tp_pct", 0.03),
            # 리스크
            daily_dd_pct=config.risk_gate.daily_dd_pct,
            weekly_dd_pct=config.risk_gate.weekly_dd_pct,
            consecutive_loss_limit=int(config.risk_gate.consecutive_loss_limit),
            cooldown_min=int(config.risk_gate.cooldown_min),
            max_exposure_pct=config.risk_gate.max_exposure_pct,
            # 사이징
            active_risk_pct=config.sizing.active_risk_pct,
            pool_cap_pct=config.sizing.pool_cap_pct,
            defense_mult_min=config.sizing.defense_mult_min,
            defense_mult_max=config.sizing.defense_mult_max,
            vol_target_mult_min=config.sizing.vol_target_mult_min,
            vol_target_mult_max=config.sizing.vol_target_mult_max,
            # 국면
            regime_adx_strong=int(config.regime.strong_up_adx),
            regime_atr_spike_mult=config.regime.crisis_atr_mult,
            # 환경 필터 (현재 하드코딩 → 여기서 관리)
            l1_volume_ratio=0.8,
            l1_momentum_burst_pct=0.015,
            # 승격
            promotion_profit_pct=config.promotion.profit_pct,
            promotion_hold_bars=int(config.promotion.profit_hold_bars),
            promotion_adx_min=int(config.promotion.adx_min),
        )

    def to_config_patches(self, current: EvolvableParams) -> dict[str, Any]:
        """변경된 파라미터를 config.yaml 구조로 변환한다.

        config.yaml의 원래 섹션 구조(strategy_params, risk_gate, sizing 등)에
        맞춰 패치 딕셔너리를 반환한다.

        Args:
            current: 변경 전 파라미터 (비교 기준).

        Returns:
            config.yaml 섹션별 패치 딕셔너리.
            예: {"strategy_params": {"trend_follow": {"sl_mult": 3.0}},
                 "risk_gate": {"daily_dd_pct": 0.035}}
        """
        changes = current.diff(self)
        if not changes:
            return {}

        patches: dict[str, Any] = {}

        # 매핑: evolvable param name → config.yaml 경로
        _MAPPING: dict[str, tuple[str, ...]] = {
            # TREND_FOLLOW
            "tf_sl_mult": ("strategy_params", "trend_follow", "sl_mult"),
            "tf_tp_rr": ("strategy_params", "trend_follow", "tp_rr"),
            "tf_cutoff": ("score_cutoff", "group1", "full"),
            "tf_w_trend_align": ("strategy_params", "trend_follow", "w_trend_align"),
            "tf_w_macd": ("strategy_params", "trend_follow", "w_macd"),
            "tf_w_volume": ("strategy_params", "trend_follow", "w_volume"),
            "tf_w_rsi_pullback": ("strategy_params", "trend_follow", "w_rsi_pullback"),
            "tf_w_supertrend": ("strategy_params", "trend_follow", "w_supertrend"),
            # MEAN_REVERSION
            "mr_sl_mult": ("strategy_params", "mean_reversion", "sl_mult"),
            "mr_tp_rr": ("strategy_params", "mean_reversion", "tp_rr"),
            # BREAKOUT
            "bo_sl_mult": ("strategy_params", "breakout", "sl_mult"),
            "bo_tp_rr": ("strategy_params", "breakout", "tp_rr"),
            # DCA
            "dca_sl_pct": ("strategy_params", "dca", "sl_pct"),
            "dca_tp_pct": ("strategy_params", "dca", "tp_pct"),
            # 리스크
            "daily_dd_pct": ("risk_gate", "daily_dd_pct"),
            "weekly_dd_pct": ("risk_gate", "weekly_dd_pct"),
            "consecutive_loss_limit": ("risk_gate", "consecutive_loss_limit"),
            "cooldown_min": ("risk_gate", "cooldown_min"),
            "max_exposure_pct": ("risk_gate", "max_exposure_pct"),
            # 사이징
            "active_risk_pct": ("sizing", "active_risk_pct"),
            "pool_cap_pct": ("sizing", "pool_cap_pct"),
            "defense_mult_min": ("sizing", "defense_mult_min"),
            "defense_mult_max": ("sizing", "defense_mult_max"),
            "vol_target_mult_min": ("sizing", "vol_target_mult_min"),
            "vol_target_mult_max": ("sizing", "vol_target_mult_max"),
            # 국면
            "regime_adx_strong": ("regime", "strong_up_adx"),
            "regime_atr_spike_mult": ("regime", "crisis_atr_mult"),
            # 승격
            "promotion_profit_pct": ("promotion", "profit_pct"),
            "promotion_hold_bars": ("promotion", "profit_hold_bars"),
            "promotion_adx_min": ("promotion", "adx_min"),
        }

        for param_name in changes:
            path = _MAPPING.get(param_name)
            if path is None:
                # l1_volume_ratio, l1_momentum_burst_pct 등
                # 현재 config.yaml에 없는 파라미터 → 별도 처리
                continue

            new_value = getattr(self, param_name)

            # int 의미론 필드는 int로 변환
            if param_name in INT_FIELDS:
                new_value = int(new_value)

            # 중첩 딕셔너리 구성
            d = patches
            for key in path[:-1]:
                d = d.setdefault(key, {})
            d[path[-1]] = new_value

        return patches

    def clone(self) -> EvolvableParams:
        """깊은 복사본을 반환한다."""
        return EvolvableParams(**asdict(self))

    def summary(self) -> str:
        """파라미터 요약 문자열을 반환한다."""
        lines = ["=== EvolvableParams ==="]
        for f in fields(self):
            name = f.name
            value = getattr(self, name)
            bounds = PARAM_BOUNDS.get(name, (None, None))
            lines.append(f"  {name}: {value}  [{bounds[0]}, {bounds[1]}]")
        return "\n".join(lines)
