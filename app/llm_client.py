"""DeepSeek API 기반 LLM 클라이언트.

용도별 모델 분리:
- deepseek-chat: 에러 진단 등 빠른 응답 필요 시
- deepseek-reasoner: 전략 가설 생성, 성과 분석 등 깊은 추론 필요 시
"""

from __future__ import annotations

import logging
import os

import aiohttp

logger = logging.getLogger(__name__)

DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
PROXY = os.getenv("PROXY", "http://127.0.0.1:1081")

# 모델 별칭 매핑
MODEL_ALIASES: dict[str, str] = {
    "chat": "deepseek-chat",
    "reasoner": "deepseek-reasoner",
    # 하위 호환: 기존 호출에서 사용하던 Claude 모델명
    "haiku": "deepseek-chat",
    "sonnet": "deepseek-reasoner",
    "opus": "deepseek-reasoner",
}

DEFAULT_MODEL = "deepseek-chat"
DEFAULT_TIMEOUT = 60


async def call_claude(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    timeout: int = DEFAULT_TIMEOUT,
) -> str | None:
    """DeepSeek API를 통해 LLM을 호출한다.

    기존 호출처와의 호환을 위해 함수명을 유지한다.

    Args:
        prompt: LLM에 전달할 프롬프트.
        model: 모델 이름 또는 별칭 (chat, reasoner, haiku, sonnet).
        timeout: 최대 대기 시간 (초).

    Returns:
        LLM 응답 텍스트. 실패 시 None.
    """
    api_key = DEEPSEEK_API_KEY
    if not api_key:
        logger.error("DEEPSEEK_API_KEY 환경변수 미설정")
        return None

    resolved_model = MODEL_ALIASES.get(model, model)

    try:
        async with aiohttp.ClientSession() as session:
            resp = await session.post(
                DEEPSEEK_API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": resolved_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 2048,
                },
                proxy=PROXY or None,
                timeout=aiohttp.ClientTimeout(total=timeout),
            )

            data = await resp.json()

            if resp.status != 200:
                err = data.get("error", {}).get("message", str(data))
                logger.warning("DeepSeek API 오류 (HTTP %d): %s", resp.status, err[:200])
                return None

            choices = data.get("choices", [])
            if not choices:
                logger.warning("DeepSeek API 빈 응답")
                return None

            content = choices[0].get("message", {}).get("content", "").strip()
            if not content:
                logger.warning("DeepSeek API 빈 content")
                return None

            # 사용량 로깅
            usage = data.get("usage", {})
            if usage:
                logger.debug(
                    "DeepSeek [%s]: in=%d out=%d tokens",
                    resolved_model,
                    usage.get("prompt_tokens", 0),
                    usage.get("completion_tokens", 0),
                )

            return content

    except TimeoutError:
        logger.warning("DeepSeek API 타임아웃 (%d초)", timeout)
        return None
    except aiohttp.ClientError as e:
        logger.warning("DeepSeek API 연결 오류: %s", e)
        return None
    except Exception:
        logger.exception("DeepSeek API 호출 실패")
        return None
