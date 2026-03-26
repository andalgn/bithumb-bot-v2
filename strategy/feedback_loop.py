"""FeedbackLoop — 거래 실패 패턴을 집계하고 가설을 생성한다."""
from __future__ import annotations

import json
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

    def __init__(
        self,
        journal: Journal,
        deepseek_api_key: str = "",
        deepseek_base_url: str = "https://api.deepseek.com/v1",
    ) -> None:
        """초기화.

        Args:
            journal: 거래 기록.
            deepseek_api_key: DeepSeek API 키.
            deepseek_base_url: DeepSeek API URL.
        """
        self._journal = journal
        self._deepseek_key = deepseek_api_key
        self._deepseek_url = deepseek_base_url

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

    async def generate_hypotheses(
        self,
        patterns: list[FailurePattern],
        current_params: dict,
    ) -> list[dict]:
        """실패 패턴 기반으로 DeepSeek에게 파라미터 수정 가설을 요청한다.

        Args:
            patterns: 분석할 실패 패턴 목록.
            current_params: 현재 전략 파라미터.

        Returns:
            파라미터 수정 제안 목록. 각 항목: {
                "rationale": str,       # 가설 근거
                "mr_sl_mult": float,    # 수정 제안값 (없으면 current 유지)
                "mr_tp_rr": float,
                "dca_sl_pct": float,
                "dca_tp_pct": float,
                "cutoff": float,
            }
        """
        if not patterns or not self._deepseek_key:
            return []

        try:
            import httpx
        except ImportError:
            logger.warning("httpx 미설치, DeepSeek 가설 생성 건너뜀")
            return []

        top3 = patterns[:3]
        pattern_summary = "\n".join(
            f"- 태그={p.tag}, 전략={p.strategy}, 국면={p.regime},"
            f" 횟수={p.count}, 평균손실={p.avg_loss_krw:.0f}원"
            for p in top3
        )

        prompt = (
            "당신은 암호화폐 거래 전략 최적화 전문가입니다.\n\n"
            "최근 7일 거래 실패 패턴:\n"
            f"{pattern_summary}\n\n"
            "현재 파라미터:\n"
            f"{json.dumps(current_params, ensure_ascii=False)}\n\n"
            "각 패턴에 대해 구체적인 파라미터 수정 가설을 제시하세요.\n"
            "JSON 배열로만 응답하세요:\n"
            '[{"rationale": "...", "mr_sl_mult": 1.8, "mr_tp_rr": 2.5,'
            ' "dca_sl_pct": 0.03, "dca_tp_pct": 0.04, "cutoff": 70.0}, ...]'
        )

        _param_keys = ("mr_sl_mult", "mr_tp_rr", "dca_sl_pct", "dca_tp_pct", "cutoff")

        try:
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
                        "max_tokens": 800,
                        "temperature": 0.3,
                    },
                )
                if resp.status_code != 200:
                    logger.warning("DeepSeek API 오류: %d", resp.status_code)
                    return []

                data = resp.json()
                content = data["choices"][0]["message"]["content"]

        except Exception:  # noqa: BLE001 — DeepSeek API 호출 실패, 의도적 광역 포착
            logger.exception("DeepSeek 가설 생성 API 호출 실패")
            return []

        # JSON 파싱
        raw_list: list[dict] = []
        try:
            start = content.find("[")
            end = content.rfind("]") + 1
            if start >= 0 and end > start:
                raw_list = json.loads(content[start:end])
        except (json.JSONDecodeError, IndexError):
            logger.warning("DeepSeek 가설 응답 파싱 실패")
            return []

        if not isinstance(raw_list, list):
            return []

        # 검증 + 누락 파라미터 채우기
        hypotheses: list[dict] = []
        for item in raw_list:
            if not isinstance(item, dict) or "rationale" not in item:
                continue
            hyp: dict = {"rationale": item["rationale"]}
            for key in _param_keys:
                default_val = current_params.get(key, 0.0)
                val = item.get(key, default_val)
                hyp[key] = val
            hypotheses.append(hyp)

        return hypotheses[:3]
