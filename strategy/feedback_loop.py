"""FeedbackLoop — 거래 실패 패턴을 집계하고 가설을 생성한다."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.journal import Journal

logger = logging.getLogger(__name__)

_EXCLUDED_TAGS = {"winner", "untagged"}
DAY_MS = 86400 * 1000


@dataclass
class FailurePattern:
    """반복되는 거래 실패 패턴."""

    tag: str               # TradeTag 값
    strategy: str          # 전략명 (rule_engine strategy)
    regime: str            # 국면
    count: int             # 발생 횟수
    avg_loss_krw: float    # 평균 손실 (원)
    total_loss_krw: float  # 총 손실 (원)


class FeedbackLoop:
    """거래 결과를 분석하여 반복 패턴을 찾는다."""

    def __init__(self, journal: Journal) -> None:
        """초기화."""
        self._journal = journal

    def get_failure_patterns(self, days: int = 7) -> list[FailurePattern]:
        """최근 N일 거래에서 상위 3개 실패 패턴을 반환한다.

        Args:
            days: 분석 대상 기간 (일)

        Returns:
            FailurePattern 목록 (count 내림차순, 최대 3개)
        """
        trades = self._journal.get_recent_trades(limit=200)

        cutoff_ms = int(time.time() * 1000) - days * DAY_MS

        # 기간 필터 + 실패 태그 필터
        failed = [
            t for t in trades
            if (t.get("exit_time") or 0) >= cutoff_ms
            and t.get("tag", "untagged") not in _EXCLUDED_TAGS
        ]

        # (tag, strategy, regime) 기준으로 그룹핑
        groups: dict[tuple[str, str, str], list[float]] = {}
        for t in failed:
            key = (
                t.get("tag", "unknown"),
                t.get("strategy", "unknown") or "unknown",
                t.get("regime", "unknown") or "unknown",
            )
            pnl: float = t.get("net_pnl_krw", 0) or 0
            groups.setdefault(key, []).append(pnl)

        patterns: list[FailurePattern] = []
        for (tag, strategy, regime), pnl_list in groups.items():
            count = len(pnl_list)
            total_loss = sum(pnl_list)
            avg_loss = total_loss / count if count else 0.0
            patterns.append(
                FailurePattern(
                    tag=tag,
                    strategy=strategy,
                    regime=regime,
                    count=count,
                    avg_loss_krw=avg_loss,
                    total_loss_krw=total_loss,
                )
            )

        patterns.sort(key=lambda p: p.count, reverse=True)
        return patterns[:3]
