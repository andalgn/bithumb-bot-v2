# Complete Remaining Gaps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 전수조사에서 발견된 14개 미구현/불완전 항목을 모두 완성하여 LIVE 전환 준비 상태로 만든다.

**Architecture:** 3개 독립 영역으로 분류. (A) 기존 코드 빠진 로직 보완, (B) 텔레그램 양방향 명령 시스템, (C) LIVE 게이트 자동 검증. 각 Task는 독립 커밋 가능.

**Tech Stack:** Python 3.11+, aiohttp, SQLite, pytest

**의도적 Deferral (이 계획에서 제외):**
- **P3 api_server.py**: CLAUDE.md에 "React + TypeScript (대시보드, **선택**)"으로 명시. 텔레그램 명령어로 핵심 기능 커버 후 LIVE 안정화 이후 구현.
- **P8 Sensitivity 실제 재실행**: 현재 근사 방식이 PF/WR 차이를 감지하기에 충분. PAPER 28일 운영 데이터 축적 후 정밀도 필요 시 개선.
- **P10 ReviewEngine 백테스트 검증**: 현재 Sharpe 기반 판정이 초기 단계에서 충분. LIVE 전환 후 실제 데이터로 검증 로직 고도화.
- **P7 test_scoring.py**: test_rule_engine.py에 이미 45건의 점수/컷오프 테스트 포함. 별도 파일 분리는 YAGNI — Task 9에서 추가 점수 edge case만 보강.

**Task 의존성:**
```
Task 1 (--mode) ─── 독립
Task 2 (CRISIS) ─── 독립
Task 3 (Darwin) ─── 독립
Task 4 (월간/테이블) ─ 독립
Task 5 (텔레그램) ─── 독립
Task 6 (LIVE gate) ── depends on Task 4 (backtest_results 테이블)
Task 7 (risk 축소) ── depends on Task 5 (텔레그램 /resume, /restore_params)
Task 8 (systemd) ─── 독립
Task 9 (테스트) ───── 독립
Task 10 (통합검증) ── depends on Task 1-9 전부
```

---

## File Structure

### 신규 생성 파일
| 파일 | 역할 |
|------|------|
| `bot_telegram/handlers.py` | 텔레그램 명령어 핸들러 (/status, /positions, /balance, /pause, /resume, /close, /regime, /pnl, /restore_params) |
| `app/live_gate.py` | LIVE 승인 자동 검증 (9개 조건 체크) |
| `scripts/install_service_ubuntu.sh` | Ubuntu systemd 서비스 등록 스크립트 |
| `tests/test_telegram_handlers.py` | 텔레그램 핸들러 테스트 |
| `tests/test_live_gate.py` | LIVE 게이트 검증 테스트 |
| `tests/test_datafeed.py` | DataFeed 단위 테스트 |
| `tests/test_config.py` | AppConfig 로딩 테스트 |

### 수정 파일
| 파일 | 변경 내용 |
|------|-----------|
| `run_bot.py` | --mode 인자 실제 적용 + asyncio.get_event_loop() 수정 |
| `app/main.py` | CRISIS 전량청산, 월간 리뷰 트리거, 텔레그램 봇 통합, LIVE risk_pct 축소 |
| `strategy/darwin_engine.py` | shadow_trades를 journal.db에 기록 |
| `app/journal.py` | backtest_results 테이블 추가 |
| `requirements.txt` | python-telegram-bot 추가 |

---

## Task 1: run_bot.py --mode 인자 적용 + event_loop 수정

**Files:**
- Modify: `run_bot.py`
- Test: 수동 검증 (`python run_bot.py --mode PAPER --once`)

- [ ] **Step 1:** `run_bot.py`에서 `args.mode`를 `run_bot()` 함수에 전달하고, config 로딩 후 오버라이드하도록 수정

```python
async def run_bot(once: bool = False, mode_override: str | None = None) -> None:
    config = load_config()
    if mode_override:
        config.run_mode = mode_override
    bot = TradingBot(config)
    ...
```

`main()`:
```python
asyncio.run(run_bot(once=args.once, mode_override=args.mode))
```

- [ ] **Step 2:** `asyncio.get_event_loop()` (줄 40) → `asyncio.get_running_loop()` 수정

- [ ] **Step 3:** `AppConfig`의 `frozen=False` 확인 (이미 `@dataclass`이므로 변경 가능)

- [ ] **Step 4:** `python run_bot.py --mode PAPER --once` 실행하여 로그에 `[PAPER]` 표시 확인

- [ ] **Step 5:** Commit: `fix: apply --mode CLI arg override and fix event_loop deprecation`

---

## Task 2: CRISIS 전량 청산 로직

**Files:**
- Modify: `app/main.py` (run_cycle 내 국면 체크 후)
- Test: `tests/test_rule_engine.py` (CRISIS 관련 기존 테스트 확인)

- [ ] **Step 1:** `run_cycle()`에서 국면 분류 후, CRISIS 감지 시 모든 보유 포지션 즉시 청산하는 로직 추가

```python
# 6.5 CRISIS 전량 청산
for symbol in list(self._positions.keys()):
    regime = regimes.get(symbol, Regime.RANGE)
    if regime == Regime.CRISIS:
        price = current_prices.get(symbol, 0)
        if price > 0:
            logger.warning("CRISIS 전량 청산: %s @ %.0f", symbol, price)
            await self._close_position(symbol, price, "crisis")
```

위치: 승격/강등 체크(섹션 6) 직후, 신호 생성(섹션 7) 직전

- [ ] **Step 2:** 텔레그램 알림에 CRISIS 전량 청산 사유 포함 (기존 `_close_position` 내 알림이 `exit_reason="crisis"`로 전송됨 — 확인)

- [ ] **Step 3:** `pytest tests/test_rule_engine.py -v` 실행, 기존 테스트 통과 확인

- [ ] **Step 4:** Commit: `feat: add CRISIS regime forced liquidation of all positions`

---

## Task 3: Darwin shadow_trades → journal.db 기록

**Files:**
- Modify: `strategy/darwin_engine.py` (journal 파라미터, 기록 로직)
- Modify: `app/journal.py` (record_shadow_trade 메서드 추가)
- Modify: `app/main.py` (journal 인스턴스 전달)

- [ ] **Step 1:** `app/journal.py`에 `record_shadow_trade()` 메서드 추가

```python
def record_shadow_trade(self, data: dict[str, Any]) -> None:
    now = int(time.time() * 1000)
    self._conn.execute(
        """INSERT INTO shadow_trades
           (shadow_id, symbol, strategy, params_json, would_enter, signal_score, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (data["shadow_id"], data["symbol"], data["strategy"],
         data.get("params_json", ""), data.get("would_enter", 0),
         data.get("signal_score", 0), now),
    )
    self._conn.commit()
```

- [ ] **Step 2:** `DarwinEngine.__init__`에 `journal` 파라미터 추가 (Optional)

```python
def __init__(self, population_size=20, champion_params=None, journal=None):
    ...
    self._journal = journal
```

- [ ] **Step 3:** `record_cycle()`에서 trade 생성 후 journal에 기록 (`dataclasses.asdict` 사용)

```python
import dataclasses, json
if self._journal and trade.would_enter:
    self._journal.record_shadow_trade({
        "shadow_id": trade.shadow_id,
        "symbol": trade.symbol,
        "strategy": trade.strategy,
        "params_json": json.dumps(dataclasses.asdict(shadow)),
        "would_enter": 1,
        "signal_score": trade.signal_score,
    })
```

- [ ] **Step 4:** `app/main.py`에서 `DarwinEngine` 생성 시 journal 전달

```python
self._darwin = DarwinEngine(population_size=20, journal=self._journal)
```

- [ ] **Step 5:** `pytest tests/test_darwin.py -v` 통과 확인

- [ ] **Step 6:** Commit: `feat: persist darwin shadow trades to journal.db`

---

## Task 4: 월간 리뷰 트리거 연결 + backtest_results 테이블

**Files:**
- Modify: `app/main.py` (run_cycle 내 리뷰 트리거)
- Modify: `app/journal.py` (backtest_results 테이블)

- [ ] **Step 1:** `app/journal.py`에 `backtest_results` 테이블 생성 추가

```python
CREATE TABLE IF NOT EXISTS backtest_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_type TEXT NOT NULL,
    verdict TEXT NOT NULL,
    details TEXT,
    created_at INTEGER NOT NULL
);
```

- [ ] **Step 2:** `app/main.py`의 일일/주간 리뷰 블록에 월간 리뷰 트리거 추가

```python
# 월 1일 00:00~00:15 KST
if now_kst.day == 1 and now_kst.hour == 0 and now_kst.minute < 15:
    await self._review_engine.run_monthly_review()
```

- [ ] **Step 3:** `pytest tests/ -v` 전체 통과 확인

- [ ] **Step 4:** Commit: `feat: add monthly review trigger and backtest_results table`

---

## Task 5: 텔레그램 명령어 핸들러 구현

**Files:**
- Create: `bot_telegram/handlers.py`
- Modify: `app/main.py` (핸들러 통합)
- Modify: `requirements.txt` (python-telegram-bot 추가)
- Create: `tests/test_telegram_handlers.py`

- [ ] **Step 1:** `requirements.txt`에 `python-telegram-bot>=21.0` 추가 후 `pip install -r requirements.txt`

- [ ] **Step 2:** `bot_telegram/handlers.py` 구현 — aiohttp polling 기반 (python-telegram-bot 없이도 가능, 의존성 최소화)

핵심 명령어:
```
/status   - 봇 상태 (모드, 사이클, 가동시간, 포지션 수)
/positions - 보유 포지션 상세 (심볼, 진입가, 현재가, PnL)
/balance  - Pool별 잔액 (Core/Active/Reserve)
/regime   - 코인별 국면 분류
/pnl      - 오늘/이번 주 PnL 요약
/pause    - 봇 일시 중지 (신규 진입 차단)
/resume   - 봇 재개 (또는 LIVE 전환)
/close <코인> - 특정 코인 수동 청산
/restore_params - LIVE 전환 후 risk_pct 복원
```

- [ ] **Step 3:** `app/main.py`에 텔레그램 핸들러 시작/종료 코드 추가

```python
# __init__ 내
self._telegram_handler = TelegramHandler(
    token=config.secrets.telegram_bot_token,
    chat_id=config.secrets.telegram_chat_id,
    bot=self,
)

# run() 내
asyncio.create_task(self._telegram_handler.start_polling())

# stop() 내
await self._telegram_handler.stop()
```

- [ ] **Step 4:** `tests/test_telegram_handlers.py` 작성 — 명령어별 응답 포맷 테스트

- [ ] **Step 5:** `pytest tests/ -v` 전체 통과 확인

- [ ] **Step 6:** Commit: `feat: implement telegram command handlers (/status, /positions, /balance, etc.)`

---

## Task 6: LIVE 게이트 자동 검증

**Depends on:** Task 4 (backtest_results 테이블)

**Files:**
- Create: `app/live_gate.py`
- Create: `tests/test_live_gate.py`
- Modify: `app/main.py` (일일 리뷰에서 호출)

- [ ] **Step 1:** `tests/test_live_gate.py` 작성 — 9개 조건별 pass/fail 테스트

```python
def test_paper_days_check():
    gate = LiveGate(min_paper_days=28)
    assert gate.check_paper_days(27) == False
    assert gate.check_paper_days(28) == True

def test_all_pass():
    gate = LiveGate(...)
    result = gate.evaluate(stats)
    assert result.approved == True
```

- [ ] **Step 2:** `app/live_gate.py` 구현

```python
@dataclass
class LiveGateResult:
    approved: bool
    checks: dict[str, bool]
    failures: list[str]

class LiveGate:
    def evaluate(self, journal, dd_limits, backtest_daemon, ...) -> LiveGateResult:
        # 9개 조건 체크
```

조건: PAPER 일수 ≥28, 거래 ≥120, Expectancy>0, MDD<8%, 일일DD<3.5%, 가동률>99%, 인증오류 0, 슬리피지 오차 ±25%, WF 3/4, MC P5>-2%

- [ ] **Step 3:** `app/main.py`의 일일 리뷰 블록에서 `LiveGate.evaluate()` 호출, 결과 텔레그램 전송

- [ ] **Step 4:** `pytest tests/test_live_gate.py -v` 통과 확인

- [ ] **Step 5:** Commit: `feat: implement LIVE gate auto-verification (9 conditions)`

---

## Task 7: LIVE 전환 risk_pct 50% 축소 + 복원

**Depends on:** Task 5 (텔레그램 /resume, /restore_params 명령)

**Files:**
- Modify: `app/main.py` (LIVE 전환 시 사이징 조정, 상태 영속화)
- Modify: `bot_telegram/handlers.py` (/resume, /restore_params)

- [ ] **Step 1:** `app/main.py`에 `_live_risk_reduction` 플래그 추가

```python
self._live_risk_reduction = False  # LIVE 전환 후 7일간 True
self._live_start_time: float = 0
```

- [ ] **Step 2:** `/resume` 명령에서 LIVE 전환 + risk 축소 활성화

```python
async def cmd_resume(self):
    self._config.run_mode = "LIVE"
    self._run_mode = RunMode.LIVE
    self._live_risk_reduction = True
    self._live_start_time = time.time()
```

- [ ] **Step 3:** `run_cycle()`의 사이징 단계에서 축소 적용

```python
if self._live_risk_reduction:
    sizing.size_krw *= 0.5
    # 7일 경과 시 자동 해제
    if time.time() - self._live_start_time > 7 * 86400:
        self._live_risk_reduction = False
        logger.info("LIVE risk_pct 축소 자동 해제 (7일 경과)")
```

- [ ] **Step 4:** `/restore_params` 명령에서 수동 해제

- [ ] **Step 5:** `_save_state()`/`_restore_state()`에 `_live_risk_reduction`, `_live_start_time` 영속화 추가 (봇 재시작 시 축소 상태 유지)

```python
# _save_state
self._storage.set("live_risk_reduction", self._live_risk_reduction)
self._storage.set("live_start_time", self._live_start_time)

# _restore_state
self._live_risk_reduction = self._storage.get("live_risk_reduction", False)
self._live_start_time = self._storage.get("live_start_time", 0)
```

- [ ] **Step 6:** Commit: `feat: add LIVE transition risk_pct 50% reduction with auto/manual restore`

---

## Task 8: systemd 서비스 설치 스크립트

**Files:**
- Already exists: `scripts/bithumb-bot.service`, `scripts/install_service_ubuntu.sh`

- [x] **Step 1:** systemd 서비스 파일 + 설치 스크립트 작성 (완료)

```bash
# 설치
sudo bash scripts/install_service_ubuntu.sh

# 관리
sudo systemctl {start|stop|restart|status} bithumb-bot
sudo journalctl -u bithumb-bot -f
```

- [x] **Step 2:** Commit: `feat: add Ubuntu systemd service files for 24/7 operation`

---

## Task 9: 누락 테스트 파일 생성

**Files:**
- Create: `tests/test_datafeed.py`
- Create: `tests/test_config.py`

- [ ] **Step 1:** `tests/test_datafeed.py` — 캐시 TTL, 파싱, 빈 데이터 처리

```python
class TestDataFeed:
    def test_cache_hit(self): ...
    def test_cache_miss(self): ...
    def test_parse_candles_valid(self): ...
    def test_parse_candles_invalid(self): ...
    def test_get_snapshot(self): ...
```

- [ ] **Step 2:** `tests/test_config.py` — YAML 로딩, .env 오버라이드, 기본값

```python
class TestConfig:
    def test_load_default(self): ...
    def test_env_override(self): ...
    def test_paper_test_flag(self): ...
    def test_score_cutoff_groups(self): ...
```

- [ ] **Step 3:** `pytest tests/ -v` 전체 통과 확인

- [ ] **Step 4:** Commit: `test: add datafeed and config unit tests`

---

## Task 10: 최종 통합 검증 + DEVLOG 업데이트

**Files:**
- Modify: `DEVLOG.md`

- [ ] **Step 1:** `python -m ruff check .` — lint 통과
- [ ] **Step 2:** `python -m pytest tests/ -v` — 전체 통과
- [ ] **Step 3:** `python run_bot.py --once` — DRY 사이클 정상 완료
- [ ] **Step 4:** `python run_bot.py --mode PAPER --once` — PAPER 사이클 정상 완료
- [ ] **Step 5:** DEVLOG.md 업데이트
- [ ] **Step 6:** Commit: `docs: update DEVLOG with gap completion summary`
