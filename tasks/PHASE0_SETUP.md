# Phase 0: 환경 셋업 + 프로젝트 생성

**기간**: 2~3일 | **우선순위**: CRITICAL
**참조**: `docs/ARCHITECTURE.md`, `docs/PARAMS.md`

## 목표
Windows 미니PC에서 개발+운영 환경 구축. 프로젝트 뼈대 생성. 빗썸 API 연결 확인.

## 작업 목록

### 0.1 환경 구축
```powershell
# Python 3.11+ 설치 확인
python --version

# 프로젝트 디렉토리 생성
mkdir C:\dev\bithumb_auto_v2
cd C:\dev\bithumb_auto_v2

# 가상환경 생성
python -m venv venv
.\venv\Scripts\activate

# git 초기화
git init
```

### 0.2 프로젝트 디렉토리 구조 생성
```
bithumb_auto_v2/
├── app/
├── strategy/
├── market/
├── risk/
├── execution/
├── bot_telegram/
├── configs/
├── tests/
├── data/           ← .gitignore에 추가
├── docs/           ← 이미 있음
├── tasks/          ← 이미 있음
└── CLAUDE.md       ← 이미 있음
```
각 패키지에 `__init__.py` 생성.

### 0.3 requirements.txt
```
aiohttp>=3.9
pyjwt>=2.8
python-dotenv>=1.0
python-telegram-bot>=21.0
pydantic>=2.5
numpy>=1.26
pytest>=8.0
pytest-asyncio>=0.23
PyYAML>=6.0
fastapi>=0.109
uvicorn>=0.27
slowapi>=0.1
python-multipart>=0.0.6
ruff>=0.3
httpx>=0.27
```
```powershell
pip install -r requirements.txt
```

### 0.4 .env.example
```
BITHUMB_API_KEY=your_api_key
BITHUMB_API_SECRET=your_api_secret
BITHUMB_API_URL=https://api.bithumb.com
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
DASHBOARD_API_KEY=your_dashboard_key
DASHBOARD_SECRET_KEY=your_secret_key
DEEPSEEK_API_KEY=your_deepseek_key
RUN_MODE=DRY
```
`.env`로 복사 후 실제 키 입력.

### 0.5 .gitignore
```
venv/
data/
.env
__pycache__/
*.pyc
.ruff_cache/
*.db
```

### 0.6 app/config.py — 설정 로딩
- `dataclass` 기반
- `configs/config.yaml`에서 로딩
- `.env`에서 민감 정보 로딩
- `docs/PARAMS.md`의 모든 값이 설정 가능하도록 구조화
- 하드코딩 없음 (모든 임계값 config)

### 0.7 configs/config.yaml 기본 구조
`docs/PARAMS.md` 기반으로 작성.

### 0.8 app/notify.py — 텔레그램 알림
- aiohttp 기반 비동기 전송
- `ClientTimeout(total=5)`
- parse_mode: HTML
- 실패 시 로그만 (봇 중단 안 함)

### 0.9 최소 동작 확인
```python
# run_bot.py — 연결 테스트
# 1. config.yaml + .env 로딩
# 2. 빗썸 Public API: BTC/KRW 현재가 조회
# 3. 텔레그램 테스트 메시지 전송
# 4. "DRY 모드 준비 완료" 로그
```

### 0.10 VPN 연결 확인
```powershell
# VPN 연결 상태에서 빗썸 API 응답 시간 확인
python -c "import aiohttp, asyncio, time; ..."
# 목표: 응답 < 500ms
```

### 0.11 초기 커밋
```bash
git add .
git commit -m "feat: project setup with config and telegram"
```

## 완료 기준
- [ ] 가상환경 + 의존성 설치 완료
- [ ] config.yaml + .env 로딩 동작
- [ ] 빗썸 Public API 호출 성공 (VPN 경유)
- [ ] 텔레그램 메시지 전송 성공
- [ ] `ruff check .` 오류 없음
- [ ] 초기 커밋 완료
