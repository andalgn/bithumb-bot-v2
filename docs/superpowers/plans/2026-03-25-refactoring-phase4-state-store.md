# Refactoring Phase 4: State Storage Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **선행 조건:** Phase 3 완료 후 진행. **Phase 4는 인플라이트 주문 0개일 때만 실행** (dry-run에서 검증).

**Goal:** 5가지 상태 저장 방식(JSON ×2 + SQLite ×3)을 `data/bot.db` 단일 SQLite DB로 통일한다.

**Architecture:** `app/state_store.py`에 SQLite 기반 키-값 저장소를 신설. 기존 `StateStorage`, `OrderManager`, `Journal`, `MarketStore`, `ExperimentStore`는 `migration_complete` 플래그를 확인 후 신규 DB로 위임. `scripts/migrate_state.py`가 dry-run → backup → write → verify → flag 순서로 마이그레이션한다.

**Tech Stack:** Python 3.12+, sqlite3, WAL 모드, pytest

---

## 파일 맵

| 동작 | 경로 | 역할 |
|------|------|------|
| 생성 | `app/state_store.py` | SQLite 기반 단일 상태 저장소 |
| 생성 | `scripts/migrate_state.py` | 5개 소스 → bot.db 마이그레이션 |
| 수정 | `app/storage.py` | `StateStorage` → `StateStore` 위임 (플래그 확인) |
| 수정 | `app/main.py` | `_storage` 초기화 시 `StateStore` 사용 |
| 생성 | `tests/test_state_store.py` | StateStore 단위 테스트 |

> **Phase 4 마이그레이션 범위**: `app_state.json` + `order_tickets.json` 만 bot.db로 이관한다.
> `journal.db`, `market_data.db`, `experiment_history.db`는 별도 테이블로 이관 가능하지만, 이 3개 DB는 현재 정상 동작 중이고 기존 SQLite 파일을 그대로 유지하는 것이 안전하다. 완전한 단일 DB 통합은 이후 별도 PR로 진행한다.
>
> **수정 제외**: `Journal`, `MarketStore`, `ExperimentStore`, `OrderManager` — 이 파일들은 Phase 4에서 변경하지 않는다.

---

## Task 1: `app/state_store.py` 작성

**Files:**
- Create: `app/state_store.py`
- Create: `tests/test_state_store.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_state_store.py
import json
import tempfile
from pathlib import Path

import pytest

from app.state_store import StateStore


@pytest.fixture
def store(tmp_path):
    return StateStore(db_path=str(tmp_path / "test.db"))


def test_set_and_get(store):
    store.set("positions", {"BTC": {"qty": 1.0}})
    val = store.get("positions")
    assert val == {"BTC": {"qty": 1.0}}


def test_get_missing_returns_default(store):
    assert store.get("nonexistent") is None
    assert store.get("nonexistent", default={}) == {}


def test_update_existing_key(store):
    store.set("pool", {"core": 1000})
    store.set("pool", {"core": 2000})
    assert store.get("pool") == {"core": 2000}


def test_migration_complete_flag(store):
    assert store.is_migration_complete() is False
    store.set_migration_complete()
    assert store.is_migration_complete() is True


def test_all_keys(store):
    store.set("a", 1)
    store.set("b", 2)
    keys = store.all_keys()
    assert set(keys) >= {"a", "b"}
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

```bash
pytest tests/test_state_store.py -v
```
Expected: `ModuleNotFoundError: No module named 'app.state_store'`

- [ ] **Step 3: `app/state_store.py` 작성**

```python
"""SQLite 기반 단일 상태 저장소.

WAL 모드. 키-값 행 단위 저장으로 부분 롤백 지원.
migration_complete 플래그로 구 방식 fallback 제어.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at INTEGER NOT NULL
);
"""

_MIGRATION_KEY = "__migration_complete__"


class StateStore:
    """SQLite 기반 키-값 상태 저장소."""

    def __init__(self, db_path: str | Path = "data/bot.db") -> None:
        """초기화.

        Args:
            db_path: bot.db 경로.
        """
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        logger.info("StateStore 초기화: %s", self._path)

    def get(self, key: str, default: Any = None) -> Any:
        """키에 해당하는 값을 반환한다.

        Args:
            key: 조회할 키.
            default: 키가 없을 때 반환할 기본값.

        Returns:
            저장된 값 (JSON 역직렬화) 또는 default.
        """
        row = self._conn.execute(
            "SELECT value FROM app_state WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return default
        return json.loads(row[0])

    def set(self, key: str, value: Any) -> None:
        """키-값 쌍을 저장한다.

        Args:
            key: 저장할 키.
            value: JSON 직렬화 가능한 값.
        """
        self._conn.execute(
            "INSERT OR REPLACE INTO app_state (key, value, updated_at) VALUES (?, ?, ?)",
            (key, json.dumps(value, ensure_ascii=False), int(time.time())),
        )
        self._conn.commit()

    def all_keys(self) -> list[str]:
        """저장된 모든 키 목록을 반환한다."""
        rows = self._conn.execute("SELECT key FROM app_state").fetchall()
        return [r[0] for r in rows]

    def is_migration_complete(self) -> bool:
        """마이그레이션 완료 여부를 반환한다."""
        return self.get(_MIGRATION_KEY) is True

    def set_migration_complete(self) -> None:
        """마이그레이션 완료 플래그를 기록한다."""
        self.set(_MIGRATION_KEY, True)

    def close(self) -> None:
        """DB 연결을 닫는다."""
        self._conn.close()

    def __del__(self) -> None:
        """GC 시 연결을 자동으로 닫는다."""
        try:
            self._conn.close()
        except Exception:
            pass
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
pytest tests/test_state_store.py -v
```
Expected: 5케이스 전체 PASS

- [ ] **Step 5: Commit**

```bash
git add app/state_store.py tests/test_state_store.py
git commit -m "feat: add StateStore (SQLite key-value store) for Phase 4 unification"
```

---

## Task 2: `scripts/migrate_state.py` 작성

**Files:**
- Create: `scripts/migrate_state.py`

- [ ] **Step 1: `scripts/migrate_state.py` 작성**

```python
#!/usr/bin/env python3
"""5개 상태 파일 → data/bot.db 마이그레이션.

사용법:
  python scripts/migrate_state.py --dry-run   # 쓰기 없음, 결과 출력만
  python scripts/migrate_state.py             # 실제 마이그레이션 실행

단계:
  1. [Guard] order_tickets.json에 PLACED/WAIT 상태 확인 → 있으면 중단
  2. [Dry-run] 변환 결과 출력
  3. [Backup] data/backup_YYYYMMDD_HHMMSS/ 로 복사
  4. [Write] bot.db 생성 + 데이터 이관
  5. [Verify] bot.db 값과 원본 diff 비교
  6. [Flag] migration_complete = True 기록
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.state_store import StateStore


DATA_DIR = Path("data")
APP_STATE_JSON = DATA_DIR / "app_state.json"
ORDER_TICKETS_JSON = DATA_DIR / "order_tickets.json"


def _check_inflight_orders() -> list[str]:
    """인플라이트 주문(PLACED/WAIT 상태) 목록을 반환한다."""
    if not ORDER_TICKETS_JSON.exists():
        return []
    try:
        tickets = json.loads(ORDER_TICKETS_JSON.read_text(encoding="utf-8"))
        inflight = [
            t.get("ticket_id", "?")
            for t in tickets
            if t.get("status") in ("PLACED", "WAIT", "placed", "wait")
        ]
        return inflight
    except Exception as e:
        print(f"[ERROR] order_tickets.json 읽기 실패: {e}")
        return []


def _read_app_state() -> dict:
    """app_state.json을 읽어 반환한다."""
    if not APP_STATE_JSON.exists():
        return {}
    try:
        return json.loads(APP_STATE_JSON.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[WARN] app_state.json 읽기 실패: {e}")
        return {}


def _read_order_tickets() -> list:
    """order_tickets.json을 읽어 반환한다."""
    if not ORDER_TICKETS_JSON.exists():
        return []
    try:
        return json.loads(ORDER_TICKETS_JSON.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[WARN] order_tickets.json 읽기 실패: {e}")
        return []


def run(dry_run: bool = True) -> None:
    """마이그레이션을 실행한다."""
    print(f"{'[DRY-RUN] ' if dry_run else ''}마이그레이션 시작")
    print(f"작업 디렉터리: {Path.cwd()}")

    # 1. 인플라이트 주문 확인
    inflight = _check_inflight_orders()
    if inflight:
        print(f"[ERROR] 인플라이트 주문 {len(inflight)}건 존재: {inflight[:5]}")
        print("       주문이 모두 완료된 후 마이그레이션하세요.")
        sys.exit(1)
    print("[OK] 인플라이트 주문 없음")

    # 2. 데이터 읽기
    app_state = _read_app_state()
    order_tickets = _read_order_tickets()

    print(f"\n[Preview] app_state.json 키 ({len(app_state)}개): {list(app_state.keys())[:10]}")
    print(f"[Preview] order_tickets.json 티켓 ({len(order_tickets)}개)")

    if dry_run:
        print("\n[DRY-RUN 완료] --dry-run 없이 실행하면 실제 마이그레이션합니다.")
        return

    # 3. 백업
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = DATA_DIR / f"backup_{ts}"
    backup_dir.mkdir(parents=True)
    for src in [APP_STATE_JSON, ORDER_TICKETS_JSON]:
        if src.exists():
            shutil.copy2(src, backup_dir / src.name)
    print(f"[Backup] {backup_dir}")

    # 4. bot.db 쓰기
    store = StateStore(db_path=DATA_DIR / "bot.db")

    # app_state 키-값 이관
    for key, value in app_state.items():
        store.set(key, value)
    print(f"[Write] app_state {len(app_state)}키 이관 완료")

    # order_tickets 이관
    store.set("order_tickets", order_tickets)
    print(f"[Write] order_tickets {len(order_tickets)}건 이관 완료")

    # 5. 검증
    failures = []
    for key, value in app_state.items():
        restored = store.get(key)
        if restored != value:
            failures.append(f"키={key}: 원본≠복원")
    restored_tickets = store.get("order_tickets", [])
    if restored_tickets != order_tickets:
        failures.append("order_tickets: 원본≠복원")

    if failures:
        print(f"[ERROR] 검증 실패 {len(failures)}건:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("[Verify] 검증 통과")

    # 6. 플래그 기록
    store.set_migration_complete()
    print("[Flag] migration_complete = True 기록")
    print("\n마이그레이션 완료. 봇을 재시작하세요.")
    print("롤백이 필요하면: docs/superpowers/specs/2026-03-25-refactoring-design.md Phase 4 롤백 절차 참조")
    store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Bithumb Bot 상태 마이그레이션")
    parser.add_argument("--dry-run", action="store_true", help="쓰기 없이 결과만 출력")
    args = parser.parse_args()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: dry-run 동작 확인**

```bash
python scripts/migrate_state.py --dry-run
```
Expected: `[DRY-RUN 완료]` 출력, 에러 없음, `data/bot.db` 미생성

- [ ] **Step 3: Commit**

```bash
git add scripts/migrate_state.py
git commit -m "feat: add migrate_state.py (dry-run → backup → write → verify → flag)"
```

---

## Task 3: `app/storage.py`에 StateStore 위임 추가

**Files:**
- Modify: `app/storage.py`

`StateStorage`가 `migration_complete` 플래그를 확인하고, 플래그가 있으면 `StateStore`로 위임한다.

- [ ] **Step 1: `StateStorage`에 StateStore 위임 로직 추가**

`app/storage.py`의 `__init__`, `load`, `save` 메서드 수정:

```python
# app/storage.py 상단에 추가
from app.state_store import StateStore

class StateStorage:
    """JSON 상태 영속화. migration_complete 이후 StateStore로 위임."""

    def __init__(self, path: str | Path = DEFAULT_STATE_PATH) -> None:
        self._path = Path(path)
        self._state: dict[str, Any] = {}
        self._store: StateStore | None = None
        self._try_init_store()
        self.load()

    def _try_init_store(self) -> None:
        """bot.db가 존재하고 migration_complete이면 StateStore를 초기화한다."""
        try:
            bot_db = Path("data/bot.db")
            if bot_db.exists():
                store = StateStore(db_path=bot_db)
                if store.is_migration_complete():
                    self._store = store
                    logger.info("StateStorage: bot.db 위임 모드")
                else:
                    store.close()
        except Exception:
            logger.debug("StateStore 초기화 실패 — JSON fallback")

    def load(self) -> dict[str, Any]:
        if self._store is not None:
            # bot.db에서 모든 키를 로딩
            for key in self._store.all_keys():
                if key.startswith("__"):
                    continue
                val = self._store.get(key)
                if val is not None:
                    self._state[key] = val
            logger.info("상태 복원 (bot.db): %d키", len(self._state))
            return self._state

        # 기존 JSON fallback
        if self._path.exists():
            try:
                with open(self._path, encoding="utf-8") as f:
                    self._state = json.load(f)
                logger.info("상태 복원: %s", self._path)
            except Exception:
                logger.exception("상태 로딩 실패, 초기화")
                self._state = {}
        return self._state

    def save(self) -> None:
        if self._store is not None:
            for key, value in self._state.items():
                self._store.set(key, value)
            return

        # 기존 JSON atomic write
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(dir=str(self._path.parent), suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._state, f, indent=2, ensure_ascii=False)
            os.replace(tmp, str(self._path))
        except Exception:
            logger.exception("상태 저장 실패")
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
```

- [ ] **Step 2: import OK 확인**

```bash
python -c "from app.storage import StateStorage; s = StateStorage(); print('load OK', list(s.state.keys())[:5])"
```
Expected: `load OK [...]` (에러 없음)

- [ ] **Step 3: 기존 전체 테스트 통과**

```bash
pytest tests/ -v --tb=short 2>&1 | tail -20
```
Expected: 전체 통과

- [ ] **Step 4: Commit**

```bash
git add app/storage.py
git commit -m "refactor: StateStorage delegates to StateStore when migration_complete flag is set"
```

---

## Task 4: 마이그레이션 실행 + 봇 재시작

> **전제**: 봇 중지 후, `order_tickets.json`에 PLACED/WAIT 상태 주문이 0개인 것을 dry-run으로 확인한다.

- [ ] **Step 1: 봇 중지 + dry-run 확인**

```bash
sudo systemctl stop bithumb-bot
python scripts/migrate_state.py --dry-run
```
Expected: 인플라이트 주문 없음, 키 목록 출력

- [ ] **Step 2: 실제 마이그레이션 실행**

```bash
python scripts/migrate_state.py
```
Expected:
```
[OK] 인플라이트 주문 없음
[Backup] data/backup_YYYYMMDD_HHMMSS
[Write] app_state N키 이관 완료
[Write] order_tickets N건 이관 완료
[Verify] 검증 통과
[Flag] migration_complete = True 기록
마이그레이션 완료.
```

- [ ] **Step 3: bot.db 내용 확인**

```bash
python -c "
from app.state_store import StateStore
s = StateStore()
print('키 목록:', s.all_keys()[:10])
print('migration_complete:', s.is_migration_complete())
"
```
Expected: 기존 app_state.json의 키들이 출력됨, `migration_complete: True`

- [ ] **Step 4: 봇 재시작 + 상태 정상 복원 확인**

```bash
sudo systemctl start bithumb-bot && sleep 5 && sudo journalctl -u bithumb-bot -n 15 --no-pager
```
Expected:
- `상태 복원 (bot.db): N키` 로그
- `사이클 #1 완료` 로그 (사이클 정상 실행)
- 포지션, Pool, DD 상태 복원 확인

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: Phase 4 state migration complete — bot.db is now primary state store"
git tag phase4-state-unification
```

---

## Task 5: 72시간 모니터링 후 구 파일 정리

> **이 Task는 Phase 4 실행 72시간 이후에 진행한다.**

- [ ] **Step 1: 72시간 후 봇 정상 운영 확인**

```bash
sudo journalctl -u bithumb-bot -n 50 --no-pager | grep -E "완료|오류|실패"
```
Expected: `사이클 #N 완료` 로그만 있고 오류 없음

- [ ] **Step 2: 구 파일 아카이브 (삭제 아님)**

```bash
mkdir -p data/legacy_YYYYMMDD
mv data/app_state.json data/legacy_YYYYMMDD/ 2>/dev/null || true
mv data/order_tickets.json data/legacy_YYYYMMDD/ 2>/dev/null || true
echo "구 파일 아카이브 완료"
```

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "chore: archive legacy JSON state files after 72h monitoring (Phase 4)"
```

---

## Phase 4 완료 기준 체크리스트

- [ ] `data/bot.db` 존재, `migration_complete = True`
- [ ] 봇 재시작 후 포지션/Pool/DD 상태 정상 복원
- [ ] `StateStorage.save()` 호출 시 bot.db에 저장됨
- [ ] dry-run이 인플라이트 주문 차단 동작
- [ ] 72시간 모니터링 후 구 파일 아카이브

**롤백 절차 (필요 시):**
```bash
# 1. 봇 중지
sudo systemctl stop bithumb-bot
# 2. bot.db 비활성화
mv data/bot.db data/bot.db.failed
# 3. 백업 복원
cp data/backup_YYYYMMDD_HHMMSS/* data/
# 4. 봇 재시작 (JSON fallback 자동 동작)
sudo systemctl start bithumb-bot
```

**다음 단계:** `docs/superpowers/plans/2026-03-25-refactoring-phase5-exceptions.md`
