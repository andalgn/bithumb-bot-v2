"""GuardAgent — 진화 변경의 구조적 검증 모듈.

모든 파라미터 변경을 실행 전에 코드 레벨에서 검증한다.
프롬프트 기반 제약은 신뢰할 수 없으므로(에이전트 우회 실 사례),
구조적 가드레일로 강제한다.

사용:
    guard = GuardAgent()
    result = guard.validate(current_params, proposed_params)
    if not result.is_valid:
        print(result.violations)
    print(result.risk_level)  # "low" | "medium" | "high"
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

from strategy.strategy_params import PARAM_BOUNDS, EvolvableParams

logger = logging.getLogger(__name__)

# ── 위험도 가중치 ──────────────────────────────────────────
# 리스크/사이징 파라미터 변경은 전략 가중치 변경보다 위험하다.
# 카테고리별 가중치: 변경 1건당 risk_score에 더해지는 기본값.

_RISK_WEIGHTS: dict[str, float] = {
    # 전략 가중치 (낮은 위험)
    "tf_w_trend_align": 0.03,
    "tf_w_macd": 0.03,
    "tf_w_volume": 0.03,
    "tf_w_rsi_pullback": 0.03,
    "tf_w_supertrend": 0.03,
    # 전략 SL/TP (중간 위험)
    "tf_sl_mult": 0.06,
    "tf_tp_rr": 0.06,
    "tf_cutoff": 0.05,
    "mr_sl_mult": 0.06,
    "mr_tp_rr": 0.06,
    "bo_sl_mult": 0.06,
    "bo_tp_rr": 0.06,
    "dca_sl_pct": 0.06,
    "dca_tp_pct": 0.06,
    # 리스크 임계값 (높은 위험)
    "daily_dd_pct": 0.12,
    "weekly_dd_pct": 0.12,
    "consecutive_loss_limit": 0.10,
    "cooldown_min": 0.08,
    "max_exposure_pct": 0.15,
    # 사이징 (높은 위험)
    "active_risk_pct": 0.12,
    "pool_cap_pct": 0.10,
    "defense_mult_min": 0.08,
    "defense_mult_max": 0.08,
    "vol_target_mult_min": 0.06,
    "vol_target_mult_max": 0.06,
    # 국면/필터 (중간 위험)
    "regime_adx_strong": 0.07,
    "regime_atr_spike_mult": 0.07,
    "l1_volume_ratio": 0.05,
    "l1_momentum_burst_pct": 0.05,
    # 승격 (중간 위험)
    "promotion_profit_pct": 0.07,
    "promotion_hold_bars": 0.05,
    "promotion_adx_min": 0.05,
}

# 위험도 레벨 경계값
_LOW_THRESHOLD = 0.2
_HIGH_THRESHOLD = 0.6


@dataclass(frozen=True)
class GuardResult:
    """GuardAgent 검증 결과."""

    is_valid: bool
    risk_score: float
    risk_level: str  # "low" | "medium" | "high"
    violations: list[str] = field(default_factory=list)
    changes: dict[str, tuple[float, float]] = field(default_factory=dict)
    change_count: int = 0


class GuardAgent:
    """진화 변경의 구조적 검증기.

    3단계 검증:
    1. 범위 검증 (PARAM_BOUNDS)
    2. 논리적 정합성 (교차 필드)
    3. 하드 제약 (절대 위반 불가)

    + 위험도 점수 계산.
    """

    def validate(
        self,
        current: EvolvableParams,
        proposed: EvolvableParams,
    ) -> GuardResult:
        """변경을 검증하고 위험도를 계산한다.

        Args:
            current: 현재 파라미터.
            proposed: 제안된 파라미터.

        Returns:
            검증 결과 (is_valid, risk_score, violations 등).
        """
        violations: list[str] = []
        changes = current.diff(proposed)

        if not changes:
            return GuardResult(
                is_valid=True,
                risk_score=0.0,
                risk_level="low",
                changes={},
                change_count=0,
            )

        # 1단계: 범위 검증
        violations.extend(self._check_bounds(proposed))

        # 2단계: 논리적 정합성
        violations.extend(self._check_logic(proposed))

        # 3단계: 하드 제약
        violations.extend(self._check_hard_constraints(proposed))

        # 위험도 점수 계산
        risk_score = self._calculate_risk_score(changes)
        risk_level = self._score_to_level(risk_score)

        is_valid = len(violations) == 0

        if not is_valid:
            logger.warning(
                "GuardAgent 거부: %d건 위반 — %s",
                len(violations),
                "; ".join(violations),
            )
        else:
            logger.info(
                "GuardAgent 통과: %d건 변경, risk=%s (%.2f)",
                len(changes),
                risk_level,
                risk_score,
            )

        return GuardResult(
            is_valid=is_valid,
            risk_score=round(risk_score, 3),
            risk_level=risk_level,
            violations=violations,
            changes=changes,
            change_count=len(changes),
        )

    def _check_bounds(self, proposed: EvolvableParams) -> list[str]:
        """MIN/MAX 범위 위반 검사."""
        return proposed.validate()

    def _check_logic(self, proposed: EvolvableParams) -> list[str]:
        """논리적 정합성 검사.

        validate()에서 이미 min<max, daily<weekly 체크하므로
        여기서는 추가적인 교차 필드 검증을 수행한다.
        """
        violations: list[str] = []

        # 전략 가중치 합계 제한 (0이면 전략 무력화, 150 초과면 과도)
        w_sum = (
            proposed.tf_w_trend_align
            + proposed.tf_w_macd
            + proposed.tf_w_volume
            + proposed.tf_w_rsi_pullback
            + proposed.tf_w_supertrend
        )
        if w_sum < 30:
            violations.append(f"TREND_FOLLOW 가중치 합계({w_sum:.0f})가 30 미만 — 전략 무력화 위험")
        if w_sum > 150:
            violations.append(f"TREND_FOLLOW 가중치 합계({w_sum:.0f})가 150 초과 — 과도한 점수")

        # DCA: SL이 TP보다 작으면 비정상 (SL은 더 넓어야 함)
        if proposed.dca_sl_pct < proposed.dca_tp_pct:
            violations.append(
                f"DCA sl_pct({proposed.dca_sl_pct}) < tp_pct({proposed.dca_tp_pct}) — "
                "SL이 TP보다 좁으면 손실 확률 증가"
            )

        return violations

    def _check_hard_constraints(self, proposed: EvolvableParams) -> list[str]:
        """절대 위반 불가 제약 (defense-in-depth).

        PARAM_BOUNDS와 일부 중복되지만 의도적이다.
        PARAM_BOUNDS가 우회되더라도(직접 생성 등) 이 체크가 최후 방어선.
        """
        violations: list[str] = []

        # 일간 DD 6% 초과 금지
        if proposed.daily_dd_pct > 0.06:
            violations.append(f"daily_dd_pct({proposed.daily_dd_pct}) > 0.06 — 하드 리밋 초과")

        # 최대 노출 95% 초과 금지
        if proposed.max_exposure_pct > 0.95:
            violations.append(
                f"max_exposure_pct({proposed.max_exposure_pct}) > 0.95 — 하드 리밋 초과"
            )

        # 연속 손실 한도 2 미만 금지 (최소 2회는 허용해야 운영 가능)
        if proposed.consecutive_loss_limit < 2:
            violations.append(
                f"consecutive_loss_limit({proposed.consecutive_loss_limit}) < 2 — 하드 리밋 미달"
            )

        # active_risk 12% 초과 금지
        if proposed.active_risk_pct > 0.12:
            violations.append(
                f"active_risk_pct({proposed.active_risk_pct}) > 0.12 — 하드 리밋 초과"
            )

        # 쿨다운 30분 미만 금지
        if proposed.cooldown_min < 30:
            violations.append(f"cooldown_min({proposed.cooldown_min}) < 30 — 하드 리밋 미달")

        return violations

    def _calculate_risk_score(self, changes: dict[str, tuple[float, float]]) -> float:
        """변경 크기 + 영향도 기반 위험도 점수 (0.0~1.0).

        각 변경된 파라미터에 대해:
        - 카테고리 가중치 (리스크 > 사이징 > 전략)
        - 변경 크기 비율 (범위 대비 몇 % 변경했는지)
        를 곱해서 합산한다.
        """
        score = 0.0

        for param_name, (old_val, new_val) in changes.items():
            # NaN/Inf 방어
            if any(
                isinstance(v, float) and (math.isnan(v) or math.isinf(v))
                for v in (old_val, new_val)
            ):
                logger.warning("NaN/Inf 값 감지 — %s: %s→%s", param_name, old_val, new_val)
                score += 0.5  # 위험한 변경으로 간주
                continue

            # 카테고리 기본 가중치
            base_weight = _RISK_WEIGHTS.get(param_name, 0.05)

            # 변경 크기 비율 (범위 대비)
            bounds = PARAM_BOUNDS.get(param_name)
            if bounds:
                lo, hi = bounds
                param_range = hi - lo
                if param_range > 0:
                    change_ratio = abs(new_val - old_val) / param_range
                else:
                    change_ratio = 1.0
            else:
                change_ratio = 0.5

            # 파라미터별 기여도 = 기본 가중치 × (1 + 변경 비율)
            # 작은 변경: ~base_weight, 큰 변경: ~2×base_weight
            contribution = base_weight * (1.0 + change_ratio)
            score += contribution

        return min(score, 1.0)

    @staticmethod
    def _score_to_level(score: float) -> str:
        """점수를 레벨로 변환한다."""
        if score < _LOW_THRESHOLD:
            return "low"
        if score < _HIGH_THRESHOLD:
            return "medium"
        return "high"
