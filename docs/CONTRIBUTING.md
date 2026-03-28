# Contributing Guide

<!-- AUTO-GENERATED: DO NOT EDIT SECTIONS BETWEEN THESE MARKERS MANUALLY -->

## Prerequisites

- Python 3.12+
- Ubuntu 24.04 (권장)
- VPN 연결 (Xray/VLESS+Reality, 한국 서버 경유)
- HTTP 프록시: `http://127.0.0.1:1081`

## 개발 환경 설정

```bash
# 1. 저장소 클론
git clone <repo-url>
cd bithumb-bot-v2

# 2. 가상환경 생성 및 활성화
python3 -m venv venv
source venv/bin/activate

# 3. 의존성 설치
pip install -r requirements.txt

# 4. 환경변수 설정
cp .env.example .env
# .env 파일에 실제 키 값 입력

# 5. (선택) 시스템 서비스 등록
sudo bash scripts/install_service_ubuntu.sh
```

## 환경변수 레퍼런스

<!-- AUTO-GENERATED: ENV_VARS -->

| 변수 | 필수 | 설명 |
|------|------|------|
| `BITHUMB_API_KEY` | 필수 | 빗썸 API 키 |
| `BITHUMB_API_SECRET` | 필수 | 빗썸 API 시크릿 |
| `BITHUMB_API_URL` | 필수 | 빗썸 API 엔드포인트 (기본: `https://api.bithumb.com`) |
| `DISCORD_BOT_TOKEN` | 필수 | Discord 봇 토큰 |
| `DISCORD_WEBHOOK_TRADE` | 필수 | 거래 알림 웹훅 URL |
| `DISCORD_WEBHOOK_REPORT` | 필수 | 리포트 웹훅 URL |
| `DISCORD_WEBHOOK_BACKTEST` | 선택 | 백테스트 결과 웹훅 URL |
| `DISCORD_WEBHOOK_SYSTEM` | 필수 | 시스템 알림 웹훅 URL |
| `DISCORD_WEBHOOK_COMMAND` | 선택 | 슬래시 커맨드 웹훅 URL |
| `DISCORD_WEBHOOK_LIVEGATE` | 선택 | LIVE 승인 웹훅 URL |
| `DISCORD_GUILD_ID` | 필수 | Discord 서버 ID |
| `DASHBOARD_API_KEY` | 선택 | 대시보드 API 키 |
| `DASHBOARD_SECRET_KEY` | 선택 | 대시보드 시크릿 |
| `DEEPSEEK_API_KEY` | 선택 | DeepSeek API 키 (주간 리뷰용) |
| `RUN_MODE` | 선택 | 실행 모드: `DRY` / `PAPER` / `LIVE` (기본: `DRY`) |

<!-- END AUTO-GENERATED: ENV_VARS -->

## 사용 가능한 스크립트

<!-- AUTO-GENERATED: SCRIPTS -->

| 스크립트 | 설명 |
|---------|------|
| `python run_bot.py` | 봇 메인 진입점 (직접 실행) |
| `python scripts/download_and_backtest.py` | 90일 캔들 데이터 다운로드 + 전략 파이프라인 백테스트 |
| `python scripts/log_summary.py` | 봇 로그 요약 |
| `python scripts/migrate_state.py` | 5개 상태 파일 → `data/bot.db` 마이그레이션 |
| `python scripts/optimize.py` | 전략 파라미터 최적화 실행 |
| `python scripts/send_discord_report.py` | Discord 웹훅으로 리포트 전송 |
| `python scripts/sync_claude_md.py` | CLAUDE.md와 실제 프로젝트 구조 동기화 검증 |
| `bash scripts/install_service_ubuntu.sh` | systemd 서비스 등록 (sudo 필요) |
| `bash scripts/daily_report.sh` | 일일 리포트 생성 및 Discord 전송 |
| `bash scripts/auto_fix.sh` | 자동 수정 스크립트 |

<!-- END AUTO-GENERATED: SCRIPTS -->

## 의존성

<!-- AUTO-GENERATED: DEPENDENCIES -->

| 패키지 | 버전 | 용도 |
|--------|------|------|
| `aiohttp` | >=3.9 | 비동기 HTTP 클라이언트 (빗썸 API, 프록시) |
| `pyjwt` | >=2.8 | 빗썸 API JWT 인증 |
| `python-dotenv` | >=1.0 | 환경변수 로딩 |
| `discord.py` | >=2.4 | Discord 봇/웹훅 알림 |
| `pydantic` | >=2.5 | 데이터 검증 및 설정 |
| `numpy` | >=1.26 | 수치 계산 (지표, 통계) |
| `pytest` | >=8.0 | 테스트 프레임워크 |
| `pytest-asyncio` | >=0.23 | 비동기 테스트 지원 |
| `PyYAML` | >=6.0 | config.yaml 파싱 |
| `fastapi` | >=0.109 | 대시보드 API 서버 |
| `uvicorn` | >=0.27 | ASGI 서버 |
| `slowapi` | >=0.1 | FastAPI rate limiting |
| `ruff` | >=0.3 | 린터 + 포매터 |
| `httpx` | >=0.27 | HTTP 클라이언트 (동기) |
| `sdnotify` | ==0.3.2 | systemd watchdog 알림 |

<!-- END AUTO-GENERATED: DEPENDENCIES -->

## 테스트

```bash
# 전체 테스트 실행
pytest

# 커버리지 포함
pytest --cov=app --cov=strategy --cov=market --cov=risk --cov=execution --cov-report=term-missing

# 특정 모듈 테스트
pytest tests/test_rule_engine.py -v
```

테스트 목표: **80%+ 커버리지**

## 코드 스타일

```bash
# 린트 검사
ruff check .

# 자동 수정
ruff check --fix .

# 포맷
ruff format .
```

설정: `pyproject.toml` — line-length=100, Python 3.11+

## 개발 워크플로

1. **플랜 먼저** — 복잡한 기능은 `docs/superpowers/plans/` 아래 계획 문서 작성
2. **TDD** — 테스트 먼저 작성 (RED → GREEN → REFACTOR)
3. **코드 리뷰** — 코드 작성 직후 리뷰
4. **커밋** — Conventional Commits 형식 (영어)

## 커밋 형식

```
<type>: <description>

<optional body>
```

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`

## PR 체크리스트

- [ ] 테스트 통과 (`pytest`)
- [ ] 린트 통과 (`ruff check .`)
- [ ] 타입 힌트 적용
- [ ] public 함수 docstring (한국어)
- [ ] PAPER 모드에서 검증 (기능 변경 시)
- [ ] 환경변수 변경 시 `.env.example` 업데이트
- [ ] config 변경 시 `docs/PARAMS.md` 업데이트

<!-- END AUTO-GENERATED -->
