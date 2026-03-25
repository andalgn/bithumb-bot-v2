# Refactoring Phase 5: Exception Handling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **선행 조건:** Phase 4 완료 후 진행.

**Goal:** `app/`, `execution/`, `market/`에서 `except Exception` 36개 → 최상위 catch-all 1개 + 구체적 핸들러로 교체한다.

**Architecture:** `app/errors.py`에 커스텀 예외 계층 신설. 각 모듈에서 `except Exception`을 구체적 예외 타입 + 복구 동작으로 교체. 최상위 `run()` 루프의 catch-all 1개는 유지 (의도적).

**Tech Stack:** Python 3.12+, 기존 `app/`, `execution/`, `market/` 모듈, pytest

---

## 파일 맵

| 동작 | 경로 | `except Exception` 수 → 목표 |
|------|------|-------------------------------|
| 생성 | `app/errors.py` | 커스텀 예외 계층 정의 |
| 수정 | `app/main.py` | 7개 → 최상위 1개 유지, 나머지 구체화 |
| 수정 | `execution/order_manager.py` | 6개 → 구체적 핸들러 |
| 수정 | `execution/reconciler.py` | 2개 → 구체적 핸들러 |
| 수정 | `market/datafeed.py` | 4개 → 구체적 핸들러 |
| 생성 | `tests/test_errors.py` | 커스텀 예외 계층 + 복구 동작 검증 |

> **대상 외**: `strategy/`, `bot_discord/`, `backtesting/`, `scripts/`의 17개는 별도 후속 PR.

---

## Task 1: `app/errors.py` 작성

**Files:**
- Create: `app/errors.py`
- Create: `tests/test_errors.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_errors.py
import pytest

from app.errors import (
    APIAuthError,
    BotError,
    DataFetchError,
    InsufficientBalanceError,
    OrderTimeoutError,
    PositionLimitExceededError,
)


def test_exception_hierarchy():
    """모든 커스텀 예외가 BotError를 상속한다."""
    assert issubclass(InsufficientBalanceError, BotError)
    assert issubclass(OrderTimeoutError, BotError)
    assert issubclass(DataFetchError, BotError)
    assert issubclass(PositionLimitExceededError, BotError)
    assert issubclass(APIAuthError, BotError)


def test_bot_error_is_exception():
    assert issubclass(BotError, Exception)


def test_data_fetch_error_carries_symbol():
    err = DataFetchError("BTC", "캔들 조회 실패")
    assert "BTC" in str(err)
    assert err.symbol == "BTC"
    assert err.reason == "캔들 조회 실패"


def test_order_timeout_error_carries_ticket_id():
    err = OrderTimeoutError("ticket-123", "30초 초과")
    assert "ticket-123" in str(err)
    assert err.ticket_id == "ticket-123"


def test_api_auth_error():
    err = APIAuthError("API 키 만료")
    assert isinstance(err, BotError)
    assert "API 키 만료" in str(err)


def test_data_fetch_error_caught_as_bot_error():
    """DataFetchError가 BotError로 catch 가능하다 (복구 핸들러 설계 검증)."""
    with pytest.raises(BotError) as exc_info:
        raise DataFetchError("ETH", "타임아웃")
    assert exc_info.value.symbol == "ETH"


def test_api_auth_error_caught_separately_from_data_fetch():
    """APIAuthError와 DataFetchError는 별도 처리 가능하다."""
    errors = []
    for exc in [DataFetchError("BTC", ""), APIAuthError("키 만료")]:
        try:
            raise exc
        except APIAuthError:
            errors.append("auth")
        except DataFetchError:
            errors.append("data")
    assert errors == ["data", "auth"]
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

```bash
pytest tests/test_errors.py -v
```
Expected: `ModuleNotFoundError: No module named 'app.errors'`

- [ ] **Step 3: `app/errors.py` 작성**

```python
"""커스텀 예외 계층.

BotError를 최상위로, 원인별 구체적 예외 타입을 정의한다.
각 예외 타입에 따른 복구 동작:
  - InsufficientBalanceError: 주문 취소 + Discord 알림
  - OrderTimeoutError: 취소 후 다음 사이클 재시도
  - DataFetchError: 캐시 사용 또는 사이클 스킵
  - PositionLimitExceededError: 진입 거부 (로그만)
  - APIAuthError: 봇 일시정지 + Discord 알림
"""
from __future__ import annotations


class BotError(Exception):
    """모든 봇 예외의 최상위 클래스."""


class InsufficientBalanceError(BotError):
    """잔고 부족으로 주문 불가.

    복구: 주문 취소 + 알림.
    """

    def __init__(self, symbol: str, required: float, available: float) -> None:
        super().__init__(
            f"{symbol}: 잔고 부족 (필요={required:,.0f}원, 가용={available:,.0f}원)"
        )
        self.symbol = symbol
        self.required = required
        self.available = available


class OrderTimeoutError(BotError):
    """주문이 제한 시간 내 체결되지 않음.

    복구: 취소 후 다음 사이클 재시도.
    """

    def __init__(self, ticket_id: str, reason: str = "") -> None:
        super().__init__(f"주문 타임아웃: {ticket_id}" + (f" — {reason}" if reason else ""))
        self.ticket_id = ticket_id


class DataFetchError(BotError):
    """시장 데이터 조회 실패.

    복구: 캐시된 데이터 사용 또는 해당 코인 사이클 스킵.
    """

    def __init__(self, symbol: str, reason: str = "") -> None:
        super().__init__(f"{symbol}: 데이터 조회 실패" + (f" — {reason}" if reason else ""))
        self.symbol = symbol
        self.reason = reason


class PositionLimitExceededError(BotError):
    """포지션 한도 초과로 진입 불가.

    복구: 진입 거부 (로그만).
    """

    def __init__(self, symbol: str, current: int, limit: int) -> None:
        super().__init__(f"{symbol}: 포지션 한도 초과 ({current}/{limit})")
        self.symbol = symbol
        self.current = current
        self.limit = limit


class APIAuthError(BotError):
    """API 인증 실패.

    복구: 봇 일시정지 + Discord 알림.
    """

    def __init__(self, reason: str = "") -> None:
        super().__init__(f"API 인증 실패" + (f": {reason}" if reason else ""))
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
pytest tests/test_errors.py -v
```
Expected: 5케이스 전체 PASS

- [ ] **Step 5: Commit**

```bash
git add app/errors.py tests/test_errors.py
git commit -m "feat: add BotError custom exception hierarchy (Phase 5)"
```

---

## Task 2: `market/datafeed.py` 4개 교체

**Files:**
- Modify: `market/datafeed.py`

현재 `except Exception` 4개 위치:
1. `캔들 조회 실패` (line ~132)
2. `현재가 조회 실패` (line ~155)
3. `호가창 조회 실패` (line ~178)
4. `스냅샷 수집 실패` (line ~231)

- [ ] **Step 1: datafeed.py에 DataFetchError import 추가 + 4곳 교체**

각 위치에서:
```python
# Before
except Exception:
    logger.exception("캔들 조회 실패: %s %s", coin, interval)
    return []

# After
except Exception as exc:
    raise DataFetchError(coin, f"{interval} 캔들 조회: {exc}") from exc
```

스냅샷 집계 부분은 DataFetchError를 catch하여 graceful degradation 유지:
```python
# _get_snapshot 내부: DataFetchError는 re-raise
# get_all_snapshots 내부:
except DataFetchError as exc:
    logger.warning("데이터 조회 실패: %s — %s", coin, exc)
    results[coin] = MarketSnapshot(symbol=coin, current_price=0.0)
```

- [ ] **Step 2: import OK + 테스트 통과**

```bash
python -c "from market.datafeed import DataFeed; print('import OK')"
pytest tests/ -v --tb=short 2>&1 | tail -20
```
Expected: `import OK`, 전체 PASS

- [ ] **Step 3: Commit**

```bash
git add market/datafeed.py
git commit -m "refactor: replace except Exception in datafeed.py with DataFetchError (Phase 5)"
```

---

## Task 3: `execution/reconciler.py` 2개 교체

**Files:**
- Modify: `execution/reconciler.py`

현재 `except Exception` 2개:
1. `동기화 실패: ticket.symbol/ticket.ticket_id` (line ~89)
2. `orders 조회 실패는 무시` (line ~112)

- [ ] **Step 1: reconciler.py 교체**

```python
# 1번: 동기화 실패 — OrderTimeoutError로 교체
except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
    logger.debug("동기화 실패: %s/%s — %s", ticket.symbol, ticket.ticket_id, exc)

# 2번: orders 조회 실패 — DataFetchError catch
except DataFetchError as exc:
    logger.debug("미체결 주문 조회 실패: %s — %s", coin, exc)
except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
    logger.debug("미체결 주문 조회 실패: %s — %s", coin, exc)
```

> **구체 예외 타입 확인**: `bithumb_api.py`에서 어떤 예외를 올리는지 확인 후 교체. API 예외가 `BotError` 계층이 아닌 경우 `(aiohttp.ClientError, asyncio.TimeoutError, BotError)` 묶음으로 처리.

- [ ] **Step 2: import OK + 테스트 통과**

```bash
python -c "from execution.reconciler import Reconciler; print('import OK')"
pytest tests/ -v --tb=short 2>&1 | tail -20
```

- [ ] **Step 3: Commit**

```bash
git add execution/reconciler.py
git commit -m "refactor: replace except Exception in reconciler.py with specific handlers (Phase 5)"
```

---

## Task 4: `execution/order_manager.py` 6개 교체

**Files:**
- Modify: `execution/order_manager.py`

현재 `except Exception` 6개:
1. `주문 티켓 로딩 실패` (line ~92) — JSON 파싱 실패
2. `상태 저장 실패` (line ~121) — atomic write 실패
3. `주문 폴링 오류 (재시도 중)` (line ~353)
4. `주문 취소 실패 (이미 체결된 경우)` (line ~364)
5. line ~384 — EXPIRED 처리
6. `주문 취소 실패` (line ~414)

- [ ] **Step 1: order_manager.py 6곳 교체**

```python
# 1. 티켓 로딩 — OSError/json.JSONDecodeError
except (OSError, json.JSONDecodeError) as exc:
    logger.exception("주문 티켓 로딩 실패: %s", exc)

# 2. 저장 실패 — OSError
except OSError as exc:
    try:
        os.unlink(tmp_path)
    except OSError:
        pass
    logger.exception("주문 상태 저장 실패: %s", exc)

# 3. 폴링 오류 — aiohttp/asyncio 네트워크 예외
except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
    logger.debug("주문 폴링 오류 (재시도 중): %s", exc)

# 4. 취소 실패 (이미 체결) — API 예외
except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
    logger.debug("주문 취소 실패 (이미 체결된 경우): %s", exc)

# 5. EXPIRED 처리 — 광범위 catch 유지 (상태 보호 필수)
except Exception as exc:  # noqa: BLE001 — 상태 보호용
    logger.warning("주문 처리 중 예외 → EXPIRED: %s", exc)
    ticket.status = OrderStatus.EXPIRED

# 6. 취소 실패 — OrderTimeoutError 발생
except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
    raise OrderTimeoutError(ticket.ticket_id, str(exc)) from exc
```

> **#5 주의**: EXPIRED 처리 블록은 상태 보호가 필수이므로 `except Exception` + `# noqa: BLE001` 주석을 달아 의도적으로 유지.

- [ ] **Step 2: `except Exception` 잔여 건수 확인**

```bash
grep -n "except Exception" /home/bythejune/projects/bithumb-bot-v2/execution/order_manager.py
```
Expected: 1줄 (`# noqa: BLE001` 주석이 달린 #5번만)

- [ ] **Step 3: import OK + 테스트 통과**

```bash
python -c "from execution.order_manager import OrderManager; print('import OK')"
pytest tests/ -v --tb=short 2>&1 | tail -20
```

- [ ] **Step 4: Commit**

```bash
git add execution/order_manager.py
git commit -m "refactor: replace except Exception in order_manager.py with specific handlers (Phase 5)"
```

---

## Task 5: `app/main.py` 7개 교체

**Files:**
- Modify: `app/main.py`

현재 `except Exception` 7개 위치:
1. `config 리로드 실패` (line ~245)
2. `잔고 조회 실패 — Pool 장부 사용` (line ~515) — Phase 3에서 `_fetch_market_data()` 내부로 이동됨
3. `CRISIS 청산 실패` (line ~591) — Phase 3에서 `_manage_open_positions()` 내부로 이동됨
4. `_apply_champion_params` 내 tmp 파일 정리 (line ~1112)
5. `롤백 파일 복원 실패` (line ~1150)
6. `청산 알림 전송 실패` (line ~1274)
7. `사이클 실행 중 오류` (line ~1316) — **최상위 catch-all, 유지**

- [ ] **Step 1: 각 위치별 교체**

```python
# 1. config 리로드 실패 — OSError/yaml 파싱 예외
import yaml  # 이미 import된 경우 생략
except (OSError, yaml.YAMLError) as exc:
    logger.exception("config 리로드 실패 — 기존 설정 유지: %s", exc)

# 2. 잔고 조회 실패 (_fetch_market_data 내부)
# APIAuthError 발생 시 봇 정지, 일반 네트워크 오류는 Pool 장부 fallback
except APIAuthError:
    logger.error("잔고 조회 API 인증 오류 — 봇 정지")
    raise
except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
    logger.debug("잔고 조회 실패 — Pool 장부 사용: %s", exc)
    equity = (...)

# 3. CRISIS 청산 실패 (_manage_open_positions 내부)
except (aiohttp.ClientError, asyncio.TimeoutError, BotError) as exc:
    logger.exception("CRISIS 청산 실패 (다음 사이클 재시도): %s — %s", symbol, exc)
    crisis_failed.add(symbol)

# 4. _apply_champion_params tmp 파일 정리
except OSError as exc:
    os.unlink(tmp_path)
    raise OSError(f"config 쓰기 실패: {exc}") from exc

# 5. 롤백 파일 복원 실패
except OSError as exc:
    logger.exception("롤백 파일 복원 실패: %s — %s", backup, exc)
    self._experiment_store.update_change_status(change["id"], "rollback_failed")

# 6. 청산 알림 전송 실패
except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
    logger.warning("청산 알림 전송 실패: %s — %s", symbol, exc)

# 7. 사이클 실행 중 오류 — 최상위 catch-all 유지 (의도적)
except Exception:  # noqa: BLE001 — top-level guard, intentional
    logger.exception("사이클 실행 중 오류")
    await self._notifier.send(...)
```

- [ ] **Step 2: `except Exception` 잔여 건수 확인**

```bash
grep -n "except Exception" /home/bythejune/projects/bithumb-bot-v2/app/main.py
```
Expected: 1줄 (`# noqa: BLE001` 최상위 catch-all만)

- [ ] **Step 3: import OK + 전체 테스트 통과**

```bash
python -c "from app.main import TradingBot; print('import OK')"
pytest tests/ -v --tb=short 2>&1 | tail -30
```
Expected: `import OK`, 전체 통과

- [ ] **Step 4: Commit**

```bash
git add app/main.py
git commit -m "refactor: replace except Exception in main.py with specific handlers (Phase 5)"
```

---

## Task 6: Phase 5 완료 검증

**Files:**
- Verify: `app/`, `execution/`, `market/`

- [ ] **Step 1: 대상 범위 `except Exception` 잔여 건수 확인**

```bash
grep -rn "except Exception" \
  /home/bythejune/projects/bithumb-bot-v2/app/ \
  /home/bythejune/projects/bithumb-bot-v2/execution/ \
  /home/bythejune/projects/bithumb-bot-v2/market/
```
Expected: **정확히 2줄** (의도적 catch-all):
1. `execution/order_manager.py`: `# noqa: BLE001 — 상태 보호용` (EXPIRED 처리)
2. `app/main.py`: `# noqa: BLE001 — top-level guard, intentional` (사이클 최상위)

- [ ] **Step 2: 전체 스냅샷 + 오류 테스트 통과**

```bash
pytest tests/ -v --tb=short 2>&1 | tail -30
```
Expected: 전체 통과

- [ ] **Step 3: 봇 재시작 + 사이클 확인**

```bash
sudo systemctl restart bithumb-bot && sleep 5 && sudo journalctl -u bithumb-bot -n 15 --no-pager
```
Expected: `사이클 #1 완료` 로그, 오류 없음

- [ ] **Step 4: 최종 Commit + 태그**

```bash
git add -A
git commit -m "refactor: Phase 5 complete — except Exception replaced with specific handlers in app/execution/market"
git tag phase5-exception-handling
```

---

## Phase 5 완료 기준 체크리스트

- [ ] `app/errors.py` 생성 (5개 커스텀 예외)
- [ ] `app/`, `execution/`, `market/`에서 `except Exception` = 의도적 catch-all (`# noqa: BLE001`)만 남음
- [ ] 각 예외 타입 단위 테스트 통과
- [ ] 전체 테스트 스위트 통과
- [ ] 봇 재시작 후 사이클 정상 실행

**후속 작업 (별도 PR):**
- `strategy/`, `bot_discord/`, `backtesting/`, `scripts/`의 나머지 17개 `except Exception` 교체
