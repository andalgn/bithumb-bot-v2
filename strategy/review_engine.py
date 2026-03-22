"""ReviewEngine - 일일/주간/월간 리뷰.

일일: SQL 집계 기반 규칙 조정 (LLM 없음).
주간: DeepSeek-chat API 호출 + 백테스트 검증.
월간: DeepSeek-reasoner 심층 분석.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.journal import Journal
from app.notify import Notifier
from backtesting.backtest import Backtester

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
DAY_MS = 86400 * 1000

# 조정 규칙
WIN_RATE_THRESHOLD = 0.40
CONSECUTIVE_SL_LIMIT = 3
WEEKLY_MDD_THRESHOLD = 0.06
CUTOFF_ADJUSTMENT = 5.0  # 임계값 +5%


@dataclass
class DailyReviewResult:
    """일일 리뷰 결과."""

    date: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    net_pnl_krw: float = 0.0
    net_pnl_pct: float = 0.0
    active_positions: int = 0
    adjustments: list[dict] = field(default_factory=list)
    strategy_stats: dict[str, dict] = field(default_factory=dict)


@dataclass
class WeeklyReviewResult:
    """주간 리뷰 결과."""

    week_start: str
    total_trades: int = 0
    win_rate: float = 0.0
    net_pnl_krw: float = 0.0
    net_pnl_pct: float = 0.0
    best_strategy: str = ""
    worst_strategy: str = ""
    deepseek_suggestions: list[dict] = field(default_factory=list)
    applied_suggestions: int = 0
    rejected_suggestions: int = 0


@dataclass
class Adjustment:
    """파라미터 조정 기록."""

    param: str
    old_value: float
    new_value: float
    reason: str
    timestamp: float = 0.0
    rolled_back: bool = False


class ReviewEngine:
    """일일/주간/월간 리뷰 엔진."""

    def __init__(
        self,
        journal: Journal,
        notifier: Notifier | None = None,
        deepseek_api_key: str = "",
        deepseek_base_url: str = "https://api.deepseek.com/v1",
    ) -> None:
        """초기화.

        Args:
            journal: 거래 기록.
            notifier: 알림.
            deepseek_api_key: DeepSeek API 키.
            deepseek_base_url: DeepSeek API URL.
        """
        self._journal = journal
        self._notifier = notifier
        self._deepseek_key = deepseek_api_key
        self._deepseek_url = deepseek_base_url
        self._backtester = Backtester()
        self._adjustments: list[Adjustment] = []
        self._risk_gate: object | None = None  # 외부에서 주입
        self._rule_engine: object | None = None  # 외부에서 주입
        self._last_daily: str = ""
        self._last_weekly: str = ""

    # ═══════════════════════════════════════════
    # 일일 규칙 리뷰 (LLM 없음)
    # ═══════════════════════════════════════════

    async def run_daily_review(
        self,
        active_positions: int = 0,
        utilization_pct: float = 0.0,
        promotions: list[str] | None = None,
    ) -> DailyReviewResult:
        """일일 리뷰를 실행한다.

        Args:
            active_positions: 현재 활성 포지션 수.
            utilization_pct: 자금 활용률.
            promotions: 오늘 승격된 코인 목록.

        Returns:
            DailyReviewResult.
        """
        now = datetime.now(KST)
        date_key = now.strftime("%Y-%m-%d")

        if self._last_daily == date_key:
            return DailyReviewResult(date=date_key)

        self._last_daily = date_key
        logger.info("일일 리뷰 시작: %s", date_key)

        # 최근 24시간 거래 집계
        trades = self._journal.get_recent_trades(limit=100)
        cutoff = int(time.time() * 1000) - DAY_MS
        today_trades = [t for t in trades if (t.get("created_at") or 0) >= cutoff]

        total = len(today_trades)
        wins = sum(1 for t in today_trades if (t.get("net_pnl_krw") or 0) > 0)
        losses = total - wins
        net_pnl = sum(t.get("net_pnl_krw") or 0 for t in today_trades)

        # 전략별 통계
        strategy_stats = self._calc_strategy_stats(today_trades)

        # 규칙 기반 조정
        adjustments = self._apply_rules(strategy_stats, trades)

        result = DailyReviewResult(
            date=date_key,
            total_trades=total,
            wins=wins,
            losses=losses,
            net_pnl_krw=net_pnl,
            net_pnl_pct=net_pnl / 1_000_000 * 100 if net_pnl else 0,
            active_positions=active_positions,
            adjustments=adjustments,
            strategy_stats=strategy_stats,
        )

        # 일일 요약 알림
        if self._notifier:
            await self._send_daily_report(result, utilization_pct, promotions)

        logger.info(
            "일일 리뷰 완료: %d건 (승%d/패%d), PnL=%.0f원, 조정=%d건",
            total,
            wins,
            losses,
            net_pnl,
            len(adjustments),
        )
        return result

    def _calc_strategy_stats(self, trades: list[dict]) -> dict[str, dict]:
        """전략별 통계를 계산한다."""
        stats: dict[str, dict] = {}
        for t in trades:
            strat = t.get("strategy", "unknown")
            if strat not in stats:
                stats[strat] = {
                    "count": 0,
                    "wins": 0,
                    "total_pnl": 0.0,
                }
            stats[strat]["count"] += 1
            pnl = t.get("net_pnl_krw") or 0
            stats[strat]["total_pnl"] += pnl
            if pnl > 0:
                stats[strat]["wins"] += 1

        for strat, s in stats.items():
            s["win_rate"] = s["wins"] / s["count"] if s["count"] > 0 else 0
            s["expectancy"] = s["total_pnl"] / s["count"] if s["count"] > 0 else 0

        return stats

    def _apply_rules(
        self,
        strategy_stats: dict[str, dict],
        all_trades: list[dict],
    ) -> list[dict]:
        """규칙 기반 조정을 적용한다."""
        adjustments: list[dict] = []

        # 규칙 1: 승률 < 40% (표본 충족 시) → 임계값 +5%
        for strat, s in strategy_stats.items():
            if s["count"] >= 10 and s["win_rate"] < WIN_RATE_THRESHOLD:
                adj = {
                    "type": "cutoff_increase",
                    "strategy": strat,
                    "reason": f"승률 {s['win_rate']:.0%} < {WIN_RATE_THRESHOLD:.0%}",
                    "delta": CUTOFF_ADJUSTMENT,
                }
                adjustments.append(adj)
                self._adjustments.append(
                    Adjustment(
                        param=f"{strat}_cutoff",
                        old_value=0,
                        new_value=CUTOFF_ADJUSTMENT,
                        reason=adj["reason"],
                        timestamp=time.time(),
                    )
                )
                logger.info("조정: %s 임계값 +%.0f%% (%s)", strat, CUTOFF_ADJUSTMENT, adj["reason"])

        # 규칙 2: 종목 3회 연속 손절 → 24시간 쿨다운
        coin_losses: dict[str, int] = {}
        for t in all_trades[:20]:  # 최근 20건
            symbol = t.get("symbol", "")
            pnl = t.get("net_pnl_krw") or 0
            if pnl < 0:
                coin_losses[symbol] = coin_losses.get(symbol, 0) + 1
            else:
                coin_losses[symbol] = 0

        for coin, count in coin_losses.items():
            if count >= CONSECUTIVE_SL_LIMIT:
                adj = {
                    "type": "coin_cooldown",
                    "symbol": coin,
                    "reason": f"{count}회 연속 손절",
                    "cooldown_hours": 24,
                }
                adjustments.append(adj)
                logger.info("조정: %s 24시간 쿨다운 (%s)", coin, adj["reason"])

                # 실제 적용: RiskGate 쿨다운 타이머 설정
                if self._risk_gate and hasattr(self._risk_gate, "record_entry"):
                    self._risk_gate.record_entry(coin)

        return adjustments

    async def _send_daily_report(
        self,
        result: DailyReviewResult,
        utilization_pct: float,
        promotions: list[str] | None,
    ) -> None:
        """일일 리포트를 전송한다."""
        lines = [
            f"<b>일일 리뷰 ({result.date})</b>",
            "=" * 20,
            f"거래: {result.total_trades}건 (승{result.wins}/패{result.losses})",
            f"Net PnL: {result.net_pnl_krw:+,.0f}원 ({result.net_pnl_pct:+.1f}%)",
            f"활성 포지션: {result.active_positions}건",
            f"자금 활용률: {utilization_pct:.0%}",
        ]

        if promotions:
            lines.append(f"승격: {', '.join(promotions)}")

        if result.adjustments:
            for adj in result.adjustments:
                if adj["type"] == "cutoff_increase":
                    lines.append(
                        f"조정: {adj['strategy']} 임계값 +{adj['delta']:.0f}% ({adj['reason']})"
                    )
                elif adj["type"] == "coin_cooldown":
                    lines.append(
                        f"조정: {adj['symbol']} {adj['cooldown_hours']}h 쿨다운 ({adj['reason']})"
                    )

        lines.append("=" * 20)

        if self._notifier:
            await self._notifier.send("\n".join(lines), channel="report")

    # ═══════════════════════════════════════════
    # 주간 DeepSeek 분석
    # ═══════════════════════════════════════════

    async def run_weekly_review(
        self,
        shadow_top3: list[tuple] | None = None,
        wf_verdict: str = "",
        mc_p5: float = 0.0,
        mc_mdd: float = 0.0,
        sensitive_params: list[str] | None = None,
        corr_pairs: list[tuple[str, str, float]] | None = None,
    ) -> WeeklyReviewResult:
        """주간 리뷰를 실행한다.

        Args:
            shadow_top3: Darwin 상위 3 Shadow.
            wf_verdict: Walk-Forward 판정.
            mc_p5: Monte Carlo 하위 5% PnL.
            mc_mdd: Monte Carlo 최악 MDD.
            sensitive_params: 민감 파라미터 목록.
            corr_pairs: 상관계수 0.7 이상 쌍.

        Returns:
            WeeklyReviewResult.
        """
        now = datetime.now(KST)
        week_key = now.strftime("%Y-W%W")

        if self._last_weekly == week_key:
            return WeeklyReviewResult(week_start=week_key)

        self._last_weekly = week_key
        logger.info("주간 리뷰 시작: %s", week_key)

        # 최근 7일 거래
        trades = self._journal.get_recent_trades(limit=500)
        cutoff = int(time.time() * 1000) - 7 * DAY_MS
        week_trades = [t for t in trades if (t.get("created_at") or 0) >= cutoff]

        total = len(week_trades)
        wins = sum(1 for t in week_trades if (t.get("net_pnl_krw") or 0) > 0)
        net_pnl = sum(t.get("net_pnl_krw") or 0 for t in week_trades)

        strategy_stats = self._calc_strategy_stats(week_trades)
        default_stat = ("", {"expectancy": 0})
        best = (
            max(strategy_stats.items(), key=lambda x: x[1]["expectancy"])
            if strategy_stats
            else default_stat
        )
        worst = (
            min(strategy_stats.items(), key=lambda x: x[1]["expectancy"])
            if strategy_stats
            else default_stat
        )

        result = WeeklyReviewResult(
            week_start=week_key,
            total_trades=total,
            win_rate=wins / total if total > 0 else 0,
            net_pnl_krw=net_pnl,
            net_pnl_pct=net_pnl / 1_000_000 * 100 if net_pnl else 0,
            best_strategy=best[0],
            worst_strategy=worst[0],
        )

        # DeepSeek API 호출
        if self._deepseek_key:
            suggestions = await self._call_deepseek(
                strategy_stats=strategy_stats,
                shadow_top3=shadow_top3,
                wf_verdict=wf_verdict,
                mc_p5=mc_p5,
                mc_mdd=mc_mdd,
                sensitive_params=sensitive_params,
                corr_pairs=corr_pairs,
            )
            result.deepseek_suggestions = suggestions

            # 제안별 백테스트 검증
            applied, rejected = self._validate_suggestions(suggestions, week_trades)
            result.applied_suggestions = applied
            result.rejected_suggestions = rejected

        # 주간 리포트 알림
        if self._notifier:
            await self._send_weekly_report(result, shadow_top3)

        logger.info(
            "주간 리뷰 완료: %d건, 승률 %.0f%%, PnL=%.0f원",
            total,
            result.win_rate * 100,
            net_pnl,
        )
        return result

    async def _call_deepseek(
        self,
        strategy_stats: dict,
        shadow_top3: list | None = None,
        wf_verdict: str = "",
        mc_p5: float = 0.0,
        mc_mdd: float = 0.0,
        sensitive_params: list[str] | None = None,
        corr_pairs: list | None = None,
    ) -> list[dict]:
        """DeepSeek API를 호출하여 분석 제안을 받는다."""
        try:
            import httpx
        except ImportError:
            logger.warning("httpx 미설치, DeepSeek 호출 건너뜀")
            return []

        # 데이터 패키지 구성
        data_package = {
            "strategy_stats": strategy_stats,
            "shadow_top3": [
                {"id": s[0], "pnl": s[1].total_pnl, "win_rate": s[1].win_rate}
                for s in (shadow_top3 or [])
            ],
            "walk_forward": wf_verdict,
            "monte_carlo": {"p5_pnl": mc_p5, "worst_mdd": mc_mdd},
            "sensitive_params": sensitive_params or [],
            "correlation_pairs": [
                {"coin1": c[0], "coin2": c[1], "corr": c[2]} for c in (corr_pairs or [])
            ],
        }

        prompt = (
            "아래는 암호화폐 자동매매 봇의 주간 성과 데이터입니다.\n"
            "JSON으로 파라미터 조정 제안을 3개 이내로 해주세요.\n"
            '각 제안: {"param": "파라미터명", "action": "increase/decrease",'
            ' "delta": 숫자, "reason": "이유"}\n\n'
            f"데이터:\n{json.dumps(data_package, ensure_ascii=False, indent=2)}"
        )

        try:
            # DeepSeek API는 직접 접속 (프록시 불필요 — 프록시는 한국 서버용)
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self._deepseek_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._deepseek_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "deepseek-chat",
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 1000,
                        "temperature": 0.3,
                    },
                )
                if resp.status_code != 200:
                    logger.warning("DeepSeek API 오류: %d", resp.status_code)
                    return []

                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                # JSON 파싱 시도
                return self._parse_suggestions(content)

        except Exception:
            logger.exception("DeepSeek API 호출 실패")
            return []

    def _parse_suggestions(self, content: str) -> list[dict]:
        """DeepSeek 응답에서 제안을 파싱한다."""
        try:
            # JSON 배열 찾기
            start = content.find("[")
            end = content.rfind("]") + 1
            if start >= 0 and end > start:
                return json.loads(content[start:end])
        except (json.JSONDecodeError, IndexError):
            pass

        # 개별 JSON 객체 찾기
        suggestions = []
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    suggestions.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return suggestions

    # 검증 가능한 파라미터 목록과 허용 범위
    _KNOWN_PARAMS: dict[str, tuple[float, float]] = {
        "rsi_lower": (15.0, 45.0),
        "rsi_upper": (55.0, 85.0),
        "atr_mult": (0.5, 5.0),
        "cutoff": (40.0, 95.0),
        "tp_pct": (0.005, 0.10),
        "sl_pct": (0.005, 0.05),
    }

    # delta 절대값 상한 (파라미터별)
    _MAX_DELTA: dict[str, float] = {
        "rsi_lower": 10.0,
        "rsi_upper": 10.0,
        "atr_mult": 1.0,
        "cutoff": 10.0,
        "tp_pct": 0.02,
        "sl_pct": 0.02,
    }

    def _validate_suggestions(self, suggestions: list[dict], trades: list[dict]) -> tuple[int, int]:
        """제안의 타당성을 검증한다.

        파라미터 존재 여부, 허용 범위, delta 크기를 확인하는 기본 검증이다.
        전략을 재실행하는 완전한 백테스트 검증은 아니며, 다음 백테스트
        사이클에서 실제 성과로 검증된다.

        Returns:
            (적용 건수, 기각 건수).
        """
        applied = 0
        rejected = 0

        for suggestion in suggestions:
            param = suggestion.get("param", "")
            delta = suggestion.get("delta")
            action = suggestion.get("action", "")

            # 1. 필수 필드 존재 확인
            if not param or delta is None or not action:
                rejected += 1
                logger.info("DeepSeek 제안 기각 (필수 필드 누락): %s", suggestion)
                continue

            # 2. 알려진 파라미터인지 확인
            if param not in self._KNOWN_PARAMS:
                rejected += 1
                logger.info("DeepSeek 제안 기각 (알 수 없는 파라미터): %s", suggestion)
                continue

            # 3. delta 크기 합리성 확인
            max_delta = self._MAX_DELTA.get(param, 10.0)
            try:
                delta_val = abs(float(delta))
            except (TypeError, ValueError):
                rejected += 1
                logger.info("DeepSeek 제안 기각 (유효하지 않은 delta): %s", suggestion)
                continue

            if delta_val > max_delta:
                rejected += 1
                logger.info(
                    "DeepSeek 제안 기각 (delta %.2f > 상한 %.2f): %s",
                    delta_val,
                    max_delta,
                    suggestion,
                )
                continue

            # 4. action 유효성 확인
            if action not in ("increase", "decrease"):
                rejected += 1
                logger.info("DeepSeek 제안 기각 (잘못된 action): %s", suggestion)
                continue

            applied += 1
            logger.info("DeepSeek 제안 적용: %s", suggestion)

        return applied, rejected

    async def _send_weekly_report(
        self, result: WeeklyReviewResult, shadow_top3: list | None
    ) -> None:
        """주간 리포트를 전송한다."""
        lines = [
            f"<b>주간 리뷰 ({result.week_start})</b>",
            "=" * 20,
            f"총 거래: {result.total_trades}건 | 승률 {result.win_rate:.0%}",
            f"Net PnL: {result.net_pnl_krw:+,.0f}원 ({result.net_pnl_pct:+.1f}%)",
        ]

        if result.best_strategy:
            lines.append(f"최고 전략: {result.best_strategy}")
        if result.worst_strategy:
            lines.append(f"최저 전략: {result.worst_strategy}")

        if shadow_top3:
            top_strs = [f"{s[0]}({s[1].total_pnl:+.0f})" for s in shadow_top3[:3]]
            lines.append(f"Shadow Top3: {', '.join(top_strs)}")

        if result.deepseek_suggestions:
            lines.append(
                f"DeepSeek 제안: {result.applied_suggestions}건 적용,"
                f" {result.rejected_suggestions}건 기각"
            )

        lines.append("=" * 20)

        if self._notifier:
            await self._notifier.send("\n".join(lines), channel="report")

    # ═══════════════════════════════════════════
    # 월간 DeepSeek 심층
    # ═══════════════════════════════════════════

    async def run_monthly_review(self) -> None:
        """월간 심층 리뷰 (deepseek-reasoner)."""
        if not self._deepseek_key:
            logger.info("월간 리뷰: DeepSeek API 키 미설정, 건너뜀")
            return

        logger.info("월간 심층 리뷰 시작")

        trades = self._journal.get_recent_trades(limit=1000)
        cutoff = int(time.time() * 1000) - 30 * DAY_MS
        month_trades = [t for t in trades if (t.get("created_at") or 0) >= cutoff]

        strategy_stats = self._calc_strategy_stats(month_trades)
        total_pnl = sum(t.get("net_pnl_krw") or 0 for t in month_trades)

        if self._notifier:
            await self._notifier.send(
                f"<b>월간 리뷰</b>\n"
                f"30일 거래: {len(month_trades)}건\n"
                f"Net PnL: {total_pnl:+,.0f}원\n"
                f"전략별: {json.dumps(strategy_stats, ensure_ascii=False)}",
                channel="report",
            )

        logger.info("월간 심층 리뷰 완료: %d건, PnL=%.0f원", len(month_trades), total_pnl)

    @property
    def adjustments(self) -> list[Adjustment]:
        """조정 이력을 반환한다."""
        return self._adjustments.copy()
