# 텔레그램 → 디스코드 알림 마이그레이션 계획

**작성일**: 2026-03-22

## Context

현재 봇의 모든 알림이 텔레그램 단일 채팅방으로 전송됨. 디스코드로 변경하여 메시지 유형별로 채널을 분리하려는 목적.

## 현재 알림 현황

총 **8가지 유형**, 6개 파일에서 `notifier.send()` 호출:

| 유형 | 발생 위치 | 빈도 | 내용 |
|------|----------|------|------|
| 거래 알림 | `app/main.py` | 매매 시 | 매수 체결, 포지션 종료, PnL |
| 시스템 알림 | `app/main.py` | 이벤트 시 | 봇 시작/종료, 사이클 에러, 네트워크 장애 |
| 일일 리포트 | `strategy/review_engine.py` | 매일 | 거래 집계, PnL, 조정 사항 |
| 주간 리포트 | `strategy/review_engine.py` | 매주 | 전략 성과, DeepSeek 제안 |
| 월간 리포트 | `strategy/review_engine.py` | 매월 | 30일 종합 |
| 백테스트 | `backtesting/daemon.py` | 매일/주간 | WF, MC, 민감도, 자동최적화 |
| 자율 연구 | `backtesting/daemon.py` | 주간 | AutoResearcher 결과 |
| 명령 응답 | `bot_telegram/handlers.py` | 수동 | /status, /pnl 등 11개 명령 |

## 디스코드 채널 구조

```
📁 빗썸봇
├── #거래         ← 매수/매도 체결, PnL
├── #리포트       ← 일일/주간/월간 리뷰
├── #백테스트     ← WF, MC, 최적화, 자율연구
├── #시스템       ← 봇 시작/종료, 에러, 네트워크
├── #명령         ← /status, /pnl 등 명령어 응답
└── #라이브게이트  ← LIVE 전환 검증 결과
```

## 구현 방식: Discord Webhook

**Discord Bot vs Webhook:**
- Bot: 명령어 수신/응답 가능, 복잡한 셋업
- **Webhook: 채널별 URL로 메시지 전송만, 심플** ← 추천

Webhook이 적합한 이유:
- 대부분 알림이 **봇→사람** 단방향
- 명령어는 디스코드 슬래시 커맨드로 별도 구현 가능 (Phase 2)
- 채널별 Webhook URL만 config에 추가하면 됨

## 수정 대상 파일

| 파일 | 변경 |
|------|------|
| `app/notify.py` | `DiscordNotifier` 클래스 추가 (채널별 webhook) |
| `app/config.py` | `DiscordConfig` dataclass 추가 |
| `configs/config.yaml` | discord 설정 섹션 추가 |
| `app/main.py` | TelegramNotifier → DiscordNotifier 교체, 메시지별 채널 지정 |
| `strategy/review_engine.py` | notifier 호출 시 채널 지정 |
| `backtesting/daemon.py` | notifier 호출 시 채널 지정 |
| `bot_telegram/handlers.py` | 디스코드 슬래시 커맨드로 교체 (또는 Phase 2) |
| `.env.example` | 디스코드 webhook URL 추가 |

## 핵심 설계

### DiscordNotifier 클래스

```python
class DiscordNotifier:
    """디스코드 Webhook 기반 알림."""

    CHANNEL_TRADE = "trade"
    CHANNEL_REPORT = "report"
    CHANNEL_BACKTEST = "backtest"
    CHANNEL_SYSTEM = "system"
    CHANNEL_COMMAND = "command"
    CHANNEL_LIVEGATE = "livegate"

    def __init__(self, webhooks: dict[str, str], proxy: str = ""):
        # webhooks: {"trade": "https://discord.com/api/webhooks/...", ...}
        self._webhooks = webhooks
        self._proxy = proxy

    async def send(self, text: str, channel: str = "system") -> bool:
        # HTML → Discord Markdown 변환
        # webhook URL로 POST
```

### config.yaml 추가

```yaml
discord:
  webhooks:
    trade: ""      # .env에서 로드
    report: ""
    backtest: ""
    system: ""
    command: ""
    livegate: ""
```

### HTML → Discord Markdown 변환

```
<b>텍스트</b> → **텍스트**
<i>텍스트</i> → *텍스트*
<code>텍스트</code> → `텍스트`
기타 HTML 태그 → 제거
```

### 호출 변경 예시

```python
# 현재 (텔레그램)
await self._notifier.send("<b>매수 체결</b> BTC 0.001 @ 100,000,000")

# 변경 (디스코드)
await self._notifier.send("**매수 체결** BTC 0.001 @ 100,000,000", channel="trade")
```

## 단계별 진행

### Phase 1: DiscordNotifier + 채널별 전송 (이번에 구현)
- DiscordNotifier 클래스 생성
- 기존 notifier.send() 호출에 channel 파라미터 추가
- HTML→Markdown 변환
- 텔레그램 코드는 유지 (폴백/전환 가능)

### Phase 2: 디스코드 슬래시 커맨드 (향후)
- /status, /pnl 등 명령어를 디스코드 슬래시 커맨드로 구현
- discord.py 라이브러리 사용
- 현재 TelegramHandler 대체

## 검증

1. 디스코드 서버 생성 + 채널별 Webhook URL 발급
2. DiscordNotifier 단위 테스트
3. 봇 시작 시 "봇 시작" 메시지가 #시스템 채널에 도착
4. 기존 텔레그램 알림과 동일한 내용이 적절한 채널로 전달되는지 확인
