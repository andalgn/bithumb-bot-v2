"""Claude Code CLI 기반 LLM 클라이언트.

claude -p (파이프 모드)를 사용하여 Claude Max 구독 내에서 LLM 호출.
API 키 불필요 — CLI 인증 사용.
"""

from __future__ import annotations

import asyncio
import logging
import shutil

logger = logging.getLogger(__name__)

# claude CLI 절대 경로 (systemd 환경에서 PATH 누락 대비)
_CLAUDE_PATH: str | None = shutil.which("claude") or "/home/bythejune/.local/bin/claude"

# 기본 설정
DEFAULT_MODEL = "sonnet"
DEFAULT_TIMEOUT = 60  # 초


async def call_claude(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    timeout: int = DEFAULT_TIMEOUT,
) -> str | None:
    """Claude Code CLI를 통해 LLM을 호출한다.

    stdin으로 프롬프트를 전달하고, stdout에서 응답을 받는다.
    Claude Max 구독 사용량으로 처리되며 API 키가 불필요하다.

    Args:
        prompt: LLM에 전달할 프롬프트.
        model: 사용할 모델 (sonnet, opus, haiku).
        timeout: 최대 대기 시간 (초).

    Returns:
        LLM 응답 텍스트. 실패 시 None.
    """
    if not _CLAUDE_PATH:
        logger.error("claude CLI를 찾을 수 없음")
        return None

    try:
        proc = await asyncio.create_subprocess_exec(
            _CLAUDE_PATH,
            "-p",
            "--model", model,
            "--output-format", "text",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=prompt.encode("utf-8")),
            timeout=timeout,
        )

        if proc.returncode != 0:
            err_msg = stderr.decode("utf-8", errors="replace").strip()
            logger.warning(
                "claude CLI 오류 (exit=%d): %s",
                proc.returncode, err_msg[:200],
            )
            return None

        result = stdout.decode("utf-8").strip()
        if not result:
            logger.warning("claude CLI 빈 응답")
            return None

        return result

    except asyncio.TimeoutError:
        logger.warning("claude CLI 타임아웃 (%d초)", timeout)
        if proc.returncode is None:
            proc.kill()
        return None
    except FileNotFoundError:
        logger.error("claude CLI 실행 파일 없음: %s", _CLAUDE_PATH)
        return None
    except Exception:
        logger.exception("claude CLI 호출 실패")
        return None
