"""Walk-Forward 검증.

임의의 데이터 기간과 구간 수를 지원한다.
판정 (비율 기반): 100%=robust, 75%이상=good, 50%이상=warning, 미만=poor.
훈련 vs 검증 차이 > 50%이면 과적합 (overfit_detected 필드에 기록).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from backtesting.backtest import Backtester

logger = logging.getLogger(__name__)


@dataclass
class WFSegmentResult:
    """Walk-Forward 구간 결과."""

    segment: int
    train_sharpe: float = 0.0
    test_sharpe: float = 0.0
    train_pnl: float = 0.0
    test_pnl: float = 0.0
    profitable: bool = False
    overfit: bool = False


@dataclass
class WalkForwardResult:
    """Walk-Forward 전체 결과."""

    segments: list[WFSegmentResult] = field(default_factory=list)
    pass_count: int = 0
    total_segments: int = 0
    verdict: str = ""  # "robust", "good", "warning", "overfit"
    overfit_detected: bool = False


class WalkForward:
    """Walk-Forward 검증."""

    def __init__(
        self,
        data_days: int = 30,
        slide_days: int = 7,
        num_segments: int = 4,
        overfit_threshold: float = 0.50,
    ) -> None:
        """초기화.

        Args:
            data_days: 전체 데이터 기간 (일).
            slide_days: 슬라이딩 기간 (일).
            num_segments: 구간 수.
            overfit_threshold: 과적합 판정 기준 (훈련/검증 차이 비율).
        """
        self._data_days = data_days
        self._slide_days = slide_days
        self._num_segments = num_segments
        self._overfit_threshold = overfit_threshold
        self._backtester = Backtester()

    def run(self, trades: list[dict]) -> WalkForwardResult:
        """Walk-Forward 검증을 실행한다.

        Args:
            trades: 날짜순 거래 리스트. 각 항목에 "day" 키 필요 (0~data_days).

        Returns:
            WalkForwardResult.
        """
        result = WalkForwardResult(total_segments=self._num_segments)

        if not trades:
            result.verdict = "warning"
            return result

        # 최소 거래수 가드: 세그먼트당 5건 이상 필요
        min_trades = self._num_segments * 5
        if len(trades) < min_trades:
            result.verdict = "insufficient_data"
            logger.info(
                "Walk-Forward: 거래 %d건 < 최소 %d건 — 검증 보류",
                len(trades), min_trades,
            )
            return result

        for seg in range(self._num_segments):
            train_start = seg * self._slide_days
            train_end = train_start + self._data_days // 2
            test_start = train_end
            test_end = test_start + self._slide_days

            train_trades = [
                t for t in trades
                if train_start <= t.get("day", 0) < train_end
            ]
            test_trades = [
                t for t in trades
                if test_start <= t.get("day", 0) < test_end
            ]

            if not train_trades or not test_trades:
                seg_result = WFSegmentResult(segment=seg)
                result.segments.append(seg_result)
                continue

            train_result = self._backtester.run(train_trades)
            test_result = self._backtester.run(test_trades)

            profitable = test_result.total_pnl > 0

            # 과적합 판정
            overfit = False
            if train_result.sharpe > 0:
                diff = abs(train_result.sharpe - test_result.sharpe) / train_result.sharpe
                overfit = diff > self._overfit_threshold

            seg_result = WFSegmentResult(
                segment=seg,
                train_sharpe=train_result.sharpe,
                test_sharpe=test_result.sharpe,
                train_pnl=train_result.total_pnl,
                test_pnl=test_result.total_pnl,
                profitable=profitable,
                overfit=overfit,
            )
            result.segments.append(seg_result)

            if profitable:
                result.pass_count += 1
            if overfit:
                result.overfit_detected = True

        # 판정 (비율 기반)
        total = result.total_segments
        ratio = result.pass_count / total if total > 0 else 0.0
        if ratio >= 1.0:
            result.verdict = "robust"
        elif ratio >= 0.75:
            result.verdict = "good"
        elif ratio >= 0.5:
            result.verdict = "warning"
        else:
            result.verdict = "poor"

        logger.info(
            "Walk-Forward: %d/%d 통과 -> %s",
            result.pass_count, result.total_segments, result.verdict,
        )
        return result
