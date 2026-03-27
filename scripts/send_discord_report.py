"""Discord 웹훅으로 리포트를 전송하는 스크립트.

표준 입력에서 텍스트를 읽어 1900자 단위로 나눠 Discord 웹훅에 POST한다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _load_dotenv(env_path: Path) -> None:
    """프로젝트 루트의 .env 파일을 환경 변수에 로드한다."""
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv  # type: ignore[import]
        load_dotenv(dotenv_path=env_path, override=False)
    except ImportError:
        # python-dotenv가 없으면 직접 파싱한다
        with env_path.open() as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value


def _split_chunks(text: str, max_len: int = 1900) -> list[str]:
    """텍스트를 max_len 이하의 청크로 분할한다 (개행 기준, 단어 중간 분리 없음)."""
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in text.splitlines(keepends=True):
        # 단일 라인이 max_len을 초과하면 강제로 잘라낸다
        while len(line) > max_len:
            space_left = max_len - current_len
            if space_left > 0:
                current.append(line[:space_left])
                chunks.append("".join(current))
                current = []
                current_len = 0
                line = line[space_left:]
            else:
                if current:
                    chunks.append("".join(current))
                current = []
                current_len = 0

        if current_len + len(line) > max_len:
            chunks.append("".join(current))
            current = [line]
            current_len = len(line)
        else:
            current.append(line)
            current_len += len(line)

    if current:
        chunks.append("".join(current))

    return [c for c in chunks if c.strip()]


def _send_webhook(url: str, content: str) -> None:
    """Discord 웹훅에 메시지를 POST한다."""
    import httpx  # httpx는 requirements.txt에 포함돼 있다

    proxy_url = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    proxies = {"http://": proxy_url, "https://": proxy_url} if proxy_url else None

    with httpx.Client(proxies=proxies, timeout=30) as client:
        resp = client.post(url, json={"content": content})
        resp.raise_for_status()


def main() -> int:
    """메인 진입점. 성공 시 0, 실패 시 1을 반환한다."""
    # 프로젝트 루트 .env 로드
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    _load_dotenv(project_root / ".env")

    webhook_url = os.environ.get("DISCORD_WEBHOOK_REPORT") or os.environ.get(
        "DISCORD_WEBHOOK_SYSTEM"
    )
    if not webhook_url:
        print(
            "warning: DISCORD_WEBHOOK_REPORT and DISCORD_WEBHOOK_SYSTEM are not set. "
            "skipping send.",
            file=sys.stderr,
        )
        # 크론 메일 스팸 방지를 위해 0 반환
        return 0

    text = sys.stdin.read()
    if not text.strip():
        print("warning: no input received, nothing to send.", file=sys.stderr)
        return 0

    chunks = _split_chunks(text, max_len=1900)
    if not chunks:
        print("warning: input was whitespace only, nothing to send.", file=sys.stderr)
        return 0

    try:
        for chunk in chunks:
            _send_webhook(webhook_url, chunk)
        print(f"sent {len(chunks)} chunks")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
