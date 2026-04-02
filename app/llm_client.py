"""Anthropic Claude API 기반 LLM 클라이언트.

용도별 모델 분리:
- Haiku 4.5: 실시간 진단, 피드백 가설 등 빠른 응답
- Sonnet 4.6: 정기 감사, 주간 리뷰, 자율 연구 등 깊은 분석
"""

from __future__ import annotations

import logging
import os

import aiohttp

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
PROXY = os.getenv("PROXY", "http://127.0.0.1:1081")

# 모델 별칭 매핑
MODEL_ALIASES: dict[str, str] = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-20250514",
    "opus": "claude-opus-4-1-20250805",
    # 하위 호환: DeepSeek 별칭
    "chat": "claude-haiku-4-5-20251001",
    "reasoner": "claude-sonnet-4-20250514",
}

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_TIMEOUT = 60


async def call_claude(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    timeout: int = DEFAULT_TIMEOUT,
) -> str | None:
    """Anthropic Claude API를 통해 LLM을 호출한다.

    Args:
        prompt: LLM에 전달할 프롬프트.
        model: 모델 이름 또는 별칭 (haiku, sonnet, opus).
        timeout: 최대 대기 시간 (초).

    Returns:
        LLM 응답 텍스트. 실패 시 None.
    """
    api_key = ANTHROPIC_API_KEY
    if not api_key:
        logger.error("ANTHROPIC_API_KEY 환경변수 미설정")
        return None

    resolved_model = MODEL_ALIASES.get(model, model)

    try:
        async with aiohttp.ClientSession() as session:
            resp = await session.post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": resolved_model,
                    "max_tokens": 2048,
                    "messages": [{"role": "user", "content": prompt}],
                },
                proxy=PROXY or None,
                timeout=aiohttp.ClientTimeout(total=timeout),
            )

            data = await resp.json()

            if resp.status != 200:
                err = data.get("error", {}).get("message", str(data))
                logger.warning("Claude API 오류 (HTTP %d): %s", resp.status, err[:200])
                return None

            content_blocks = data.get("content", [])
            if not content_blocks:
                logger.warning("Claude API 빈 응답")
                return None

            # text 블록 추출
            text_parts = [
                block.get("text", "") for block in content_blocks if block.get("type") == "text"
            ]
            content = "\n".join(text_parts).strip()
            if not content:
                logger.warning("Claude API 빈 content")
                return None

            # 사용량 로깅
            usage = data.get("usage", {})
            if usage:
                logger.debug(
                    "Claude [%s]: in=%d out=%d tokens",
                    resolved_model,
                    usage.get("input_tokens", 0),
                    usage.get("output_tokens", 0),
                )

            return content

    except TimeoutError:
        logger.warning("Claude API 타임아웃 (%d초)", timeout)
        return None
    except aiohttp.ClientError as e:
        logger.warning("Claude API 연결 오류: %s", e)
        return None
    except Exception:
        logger.exception("Claude API 호출 실패")
        return None
