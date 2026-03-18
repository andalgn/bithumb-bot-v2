# DEVLOG

## 2026-03-18

### Phase 0: 환경 셋업 + 프로젝트 생성
- Python 3.14.3 환경 확인
- 가상환경 생성 + 의존성 설치 완료 (requirements.txt)
- 프로젝트 디렉토리 구조 생성 (app/, strategy/, market/, risk/, execution/, bot_telegram/, configs/, tests/, data/, backtesting/)
- 각 패키지 `__init__.py` 생성
- `.env.example`, `.gitignore` 생성
- `configs/config.yaml` — PARAMS.md 기반 전체 파라미터 설정
- `app/config.py` — dataclass 기반 설정 로딩 (config.yaml + .env)
- `app/notify.py` — aiohttp 비동기 텔레그램 알림
- `app/data_types.py` — 공통 데이터 타입 (Candle, Ticker, Regime, Tier 등)
- `run_bot.py` — 진입점 + 연결 테스트
- 빗썸 Public API 연결 성공: BTC/KRW 106,561,000원 (응답 1750ms)
- `ruff check .` — 오류 없음
- git init 완료 (커밋은 git user 설정 후 진행 필요)
