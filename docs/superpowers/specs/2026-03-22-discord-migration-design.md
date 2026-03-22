# 텔레그램 → 디스코드 마이그레이션 설계

**작성일**: 2026-03-22

## 개요

텔레그램 기반 알림/명령어 시스템을 디스코드로 완전 교체한다.
- **알림**: Discord Webhook (채널별 분리, 단방향)
- **명령어**: discord.py Bot (슬래시 커맨드 14개)
- 텔레그램 코드는 전량 삭제 (git history에서 복원 가능)

## 아키텍처

```
TradingBot (main.py)
  ├── DiscordNotifier.send(text, channel="trade")
  │     └── HTTP POST → Discord Webhook URL (#거래)
  │     └── HTML → Discord Markdown 변환은 send() 내부에서 자동 수행
  │
  └── DiscordBot (별도 asyncio task)
        └── discord.py Client + CommandTree
              ├── /status, /positions, /pnl, ...
              └── /golive, /close, /pause, /resume (admin 전용)
```

- **DiscordNotifier**: Webhook URL로 단방향 POST. Bot과 독립 동작
- **DiscordBot**: discord.py로 long-lived 연결. 슬래시 커맨드 수신/응답만 담당
- 두 컴포넌트 모두 프록시(`http://127.0.0.1:1081`) 경유
- discord.py의 `proxy` 파라미터(2.0+)를 사용하여 Bot 연결도 프록시 경유

Webhook과 Bot을 분리하는 이유: Bot 프로세스 장애 시에도 알림(Webhook)은 정상 전달.

## Notifier Protocol

모듈 간 결합도를 낮추기 위해 Protocol 정의:

```python
from typing import Protocol

class Notifier(Protocol):
    async def send(self, text: str, channel: str = "system") -> bool: ...
    async def close(self) -> None: ...
```

`ReviewEngine`, `BacktestDaemon`, `scripts/*.py` 등 모든 소비자는 `Notifier` 타입으로 참조.
`DiscordNotifier`가 이 Protocol을 구현.

## 모듈 구조

### 삭제
- `bot_telegram/handlers.py`
- `bot_telegram/` 디렉토리
- `app/notify.py` 내 `TelegramNotifier`
- `app/config.py` 내 `TelegramConfig`

### 신규/변경
```
app/
├── notify.py              ← Notifier Protocol + DiscordNotifier (Webhook 기반)
├── config.py              ← DiscordConfig (TelegramConfig 대체)
bot_discord/
├── __init__.py
└── bot.py                 ← DiscordBot (슬래시 커맨드 14개)
```

## DiscordNotifier 상세

### 채널 매핑
```python
CHANNEL_TRADE = "trade"        # 매수/매도 체결, PnL
CHANNEL_REPORT = "report"      # 일일/주간/월간 리뷰
CHANNEL_BACKTEST = "backtest"  # WF, MC, 최적화, 자율연구
CHANNEL_SYSTEM = "system"      # 봇 시작/종료, 에러, 네트워크
CHANNEL_COMMAND = "command"    # 명령어 응답
CHANNEL_LIVEGATE = "livegate"  # LIVE 전환 검증 결과
```

### 호출 사이트별 채널 배정

| 파일 | 라인 | 메시지 | 채널 |
|------|------|--------|------|
| `main.py` | 387 | 네트워크 장애 감지 | `system` |
| `main.py` | 397 | 네트워크 복구 | `system` |
| `main.py` | 677 | 매수 체결 | `trade` |
| `main.py` | 807 | LiveGate 리포트 | `livegate` |
| `main.py` | 974 | 포지션 청산 + PnL | `trade` |
| `main.py` | 994 | 봇 시작 | `system` |
| `main.py` | 1022 | 사이클 오류 | `system` |
| `main.py` | 1052 | 봇 종료 | `system` |
| `review_engine.py` | 287 | 일일 리뷰 | `report` |
| `review_engine.py` | 586 | 주간 리뷰 | `report` |
| `review_engine.py` | 608 | 월간 리뷰 | `report` |
| `daemon.py` | 239 | Walk-Forward 결과 | `backtest` |
| `daemon.py` | 372 | Monte Carlo 결과 | `backtest` |
| `daemon.py` | 417 | 민감도 분석 결과 | `backtest` |
| `daemon.py` | 499 | AutoResearcher/최적화 결과 | `backtest` |
| `scripts/optimize.py` | 252 | 최적화 결과 | `backtest` |
| `scripts/download_and_backtest.py` | 443 | 백테스트 결과 | `backtest` |

명시되지 않은 호출은 기본값 `channel="system"`으로 전송.

### HTML → Discord Markdown 변환

`send()` 내부에서 자동 수행. 호출자는 기존 HTML 포맷 그대로 전달 가능.

```
<b>텍스트</b> → **텍스트**
<i>텍스트</i> → *텍스트*
<code>텍스트</code> → `텍스트`
&amp; → &, &lt; → <, &gt; → >
기타 HTML 태그 → 제거
```

### Discord Markdown Escape

Discord 특수문자(`*`, `_`, `~`, `|`, `` ` ``)를 이스케이프하는 `escape()` 정적 메서드 제공.
기존 `TelegramNotifier.escape()` (HTML 이스케이프) 대체.

### 인터페이스
```python
class DiscordNotifier:
    def __init__(self, webhooks: dict[str, str], proxy: str = "", timeout_sec: int = 5):
        ...

    async def send(self, text: str, channel: str = "system") -> bool:
        """메시지를 지정 채널의 Webhook으로 전송. HTML→Markdown 자동 변환."""

    @staticmethod
    def escape(text: str) -> str:
        """Discord Markdown 특수문자를 이스케이프한다."""

    async def close(self) -> None:
        """aiohttp 세션 종료."""
```

- 메시지 2000자 초과 시 분할 전송
- 기존 TelegramNotifier와 동일한 재시도/세션 관리 패턴
- Discord Webhook rate limit: 채널당 30req/60s. 초과 시 429 응답의 `Retry-After` 헤더를 존중하여 대기
- 프록시 지원

## DiscordBot 상세

### 슬래시 커맨드

| 커맨드 | 설명 | 권한 |
|--------|------|------|
| `/status` | 봇 상태 (모드, 사이클, 업타임) | 모두 |
| `/positions` | 보유 포지션 목록 | 모두 |
| `/pnl` | 오늘/이번 주 실현 PnL | 모두 |
| `/regime` | 현재 국면 분류 | 모두 |
| `/risk` | RiskGate 상태 | 모두 |
| `/shadows` | Darwinian 상위 그림자 | 모두 |
| `/pool` | 3풀 자금 현황 | 모두 |
| `/balance` | Pool별 잔액 | 모두 |
| `/pause` | 매매 일시정지 | admin |
| `/resume` | 매매 재개 | admin |
| `/golive` | LIVE 모드 전환 (LiveGate 검증) | admin |
| `/close` | 수동 청산 (`/close symbol:BTC`) | admin |
| `/restore_params` | LIVE risk_pct 정상화 | admin |
| `/help` | 명령어 목록 | 모두 |

### 구조
```python
class DiscordBot:
    def __init__(self, token: str, bot: TradingBot, guild_id: int, proxy: str = "", admin_role: str = "admin"):
        self._client = discord.Client(intents=discord.Intents.default(), proxy=proxy)
        self._tree = app_commands.CommandTree(self._client)
        self._bot = bot
        self._guild = discord.Object(id=guild_id)
        self._admin_role = admin_role

    async def start(self) -> None:
        """Bot 실행 (asyncio task로 호출)."""
```

### 권한 & 보안
- 슬래시 커맨드는 지정된 guild에서만 등록
- `/pause`, `/resume`, `/golive`, `/close`, `/restore_params`는 `admin_role` 역할 보유자만 실행 가능
- 권한 미달 시 ephemeral 메시지로 거부 응답

### 명령어 응답 포맷
- 기존 텔레그램 핸들러의 HTML 포맷 → Discord Markdown으로 변환
- 응답은 slash command interaction의 `response.send_message()`로 전송 (Webhook 불사용)

## Config & 환경변수

### config.yaml
```yaml
# telegram 섹션 삭제, 아래 추가:
discord:
  bot_guild_id: ""    # .env에서 로드
  admin_role: "admin"
  timeout_sec: 5
```

Webhook URL은 secrets이므로 `.env`에서만 관리. `config.yaml`에 webhooks 섹션 없음.

### .env
```
# TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 삭제
DISCORD_BOT_TOKEN=your_discord_bot_token
DISCORD_WEBHOOK_TRADE=https://discord.com/api/webhooks/...
DISCORD_WEBHOOK_REPORT=https://discord.com/api/webhooks/...
DISCORD_WEBHOOK_BACKTEST=https://discord.com/api/webhooks/...
DISCORD_WEBHOOK_SYSTEM=https://discord.com/api/webhooks/...
DISCORD_WEBHOOK_COMMAND=https://discord.com/api/webhooks/...
DISCORD_WEBHOOK_LIVEGATE=https://discord.com/api/webhooks/...
DISCORD_GUILD_ID=your_guild_id
```

### config.py
```python
@dataclass(frozen=True)
class DiscordConfig:
    """디스코드 설정."""
    bot_guild_id: str = ""
    admin_role: str = "admin"
    timeout_sec: int = 5

# EnvSecrets:
# telegram_bot_token, telegram_chat_id 삭제
# 추가:
discord_bot_token: str = ""
discord_webhooks: dict[str, str] = field(default_factory=dict)
discord_guild_id: str = ""

# AppConfig:
# telegram: TelegramConfig → discord: DiscordConfig 교체
```

### 의존성
- `requirements.txt`에 `discord.py` 추가

## 에러 처리

- **Webhook 실패**: 로그만 남기고 봇 중단 안 함. 3회 연속 실패 시 세션 재생성
- **Webhook rate limit**: 429 응답 시 `Retry-After` 헤더만큼 대기 후 재시도
- **Bot 연결 끊김**: discord.py 내장 자동 재연결 (`reconnect=True`)
- **메시지 2000자 초과**: 분할 전송
- **Webhook URL 미설정**: 해당 채널 건너뛰기 + 경고 로그

## 테스트

- `tests/test_notify.py` — DiscordNotifier 단위 테스트
  - HTML→Markdown 변환
  - Discord Markdown escape
  - 채널별 Webhook URL 선택
  - 2000자 분할
  - 프록시 전달
  - 실패 시 세션 재생성
  - rate limit (429) 처리
- `tests/test_discord_bot.py` — DiscordBot 단위 테스트
  - 슬래시 커맨드 등록
  - admin 권한 체크
  - 응답 포맷

## 변경 파일 목록

| 파일 | 변경 |
|------|------|
| `app/notify.py` | `TelegramNotifier` → `Notifier` Protocol + `DiscordNotifier` |
| `app/config.py` | `TelegramConfig` → `DiscordConfig`, `EnvSecrets` 수정 |
| `configs/config.yaml` | `telegram` → `discord` 섹션 |
| `.env.example` | 텔레그램 → 디스코드 환경변수 |
| `app/main.py` | notifier 교체 + channel 지정 + DiscordBot task |
| `strategy/review_engine.py` | import 변경 (`TelegramNotifier` → `Notifier`), send()에 channel="report" |
| `backtesting/daemon.py` | import 변경 (`TelegramNotifier` → `Notifier`), send()에 channel="backtest" |
| `scripts/optimize.py` | import 변경, send()에 channel="backtest" |
| `scripts/download_and_backtest.py` | import 변경, send()에 channel="backtest" |
| `bot_discord/__init__.py` | **신규** |
| `bot_discord/bot.py` | **신규** — 슬래시 커맨드 14개 |
| `bot_telegram/` | **디렉토리 삭제** |
| `requirements.txt` | `discord.py` 추가 |
| `tests/test_notify.py` | 테스트 갱신 |
| `tests/test_discord_bot.py` | **신규** |
| `CLAUDE.md` | 프로젝트 구조 갱신 (`bot_telegram/` → `bot_discord/`) |
