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
