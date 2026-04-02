"""SelfReflection — 거래 후 자동 반성 생성 모듈."""

from __future__ import annotations

import logging
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.journal import Journal

logger = logging.getLogger(__name__)

# 태그별 반성 템플릿
_REFLECTION_TEMPLATES: dict[str, tuple[str, str]] = {
    "regime_mismatch": (
        "{strategy} 전략으로 {entry_regime} 국면에서 진입했으나 {exit_regime} 국면으로 전환되어 손실 발생.",
        "국면 전환 속도가 빠를 때는 진입 전 추가 확인 필요. {strategy} 전략의 국면 민감도 검토.",
    ),
    "timing_error": (
        "{strategy} 전략 방향 예측은 맞았으나 SL이 먼저 도달. {entry_regime} 국면에서 변동성 과소평가.",
        "SL 폭을 ATR 기반으로 조정하거나 진입 시점을 더 보수적으로 설정할 것.",
    ),
    "sizing_error": (
        "{strategy} 전략 손실이 수수료보다 작음. {entry_regime} 국면에서 포지션 크기 부적절.",
        "최소 기대 수익이 수수료의 2배 이상이 되도록 포지션 크기 조정 필요.",
    ),
    "signal_quality": (
        "{strategy} 전략 신호 품질 불량. {entry_regime} 국면에서 진입 조건 미흡.",
        "{strategy} 전략의 진입 점수 컷오프를 높이거나 확인 지표 추가 검토.",
    ),
    "external": (
        "외부 요인(API/거래소)으로 인한 비정상 청산. 전략 자체 문제 아님.",
        "외부 오류 발생 시 재진입 대기 로직 강화 필요.",
    ),
    "winner": (
        "{strategy} 전략이 {entry_regime} 국면에서 수익 달성.",
        "{strategy} 전략의 {entry_regime} 국면 진입 조건 유지.",
    ),
}


def generate_reflection(
    trade: dict,
    entry_regime: str,
    exit_regime: str,
    tag: str,
) -> tuple[str, str]:
    """거래 결과로부터 반성문과 교훈을 생성한다.

    Args:
        trade: 거래 dict (strategy, net_pnl_krw 등 포함)
        entry_regime: 진입 국면
        exit_regime: 청산 국면
        tag: TradeTagger가 분류한 태그

    Returns:
        (reflection_text, lesson) 튜플
    """
    strategy = trade.get("strategy") or trade.get("signal_type") or "unknown"
    template = _REFLECTION_TEMPLATES.get(tag, _REFLECTION_TEMPLATES["signal_quality"])
    fmt = {"strategy": strategy, "entry_regime": entry_regime, "exit_regime": exit_regime}
    reflection_text = template[0].format(**fmt)
    lesson = template[1].format(**fmt)
    return reflection_text, lesson


class ReflectionStore:
    """거래 반성을 생성하고 저장한다."""

    def __init__(self, journal: Journal) -> None:
        """초기화."""
        self._journal = journal

    def record_trade_reflection(
        self,
        trade: dict,
        entry_regime: str,
        exit_regime: str,
        tag: str,
    ) -> None:
        """거래 종료 시 반성을 생성하고 저장한다."""
        reflection_text, lesson = generate_reflection(trade, entry_regime, exit_regime, tag)
        trade_id = str(trade.get("id") or trade.get("trade_id") or "")
        strategy = trade.get("strategy") or trade.get("signal_type") or "unknown"
        self._journal.record_reflection(
            trade_id=trade_id,
            strategy=strategy,
            regime_entry=entry_regime,
            regime_exit=exit_regime,
            tag=tag,
            reflection_text=reflection_text,
            lesson=lesson,
        )
        logger.debug("반성 기록: [%s] %s", tag, lesson)

    def get_weekly_synthesis(self, days: int = 7) -> list[str]:
        """최근 N일 반성에서 빈도 높은 교훈 Top 5를 반환한다.

        Args:
            days: 분석 기간 (일)

        Returns:
            교훈 문자열 목록 (빈도순, 최대 5개)
        """
        reflections = self._journal.get_recent_reflections(limit=200)
        cutoff = datetime.now(UTC) - timedelta(days=days)
        lessons: list[str] = []
        for r in reflections:
            created_at = r.get("created_at", "")
            if not created_at:
                continue
            try:
                dt = datetime.fromisoformat(created_at)
                # created_at이 timezone-naive이면 UTC로 간주
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                if dt < cutoff:
                    continue
            except ValueError:
                continue
            lesson = r.get("lesson", "")
            if lesson:
                lessons.append(lesson)

        counter = Counter(lessons)
        top5 = [lesson for lesson, _ in counter.most_common(5)]
        return top5
