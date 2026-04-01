#!/usr/bin/env python3
"""정기 봇 감사 스크립트.

시스템 로그, 봇 상태, 거래소 잔고, 거래 성과를 수집해 Claude Code 분석용 프롬프트 생성.
사용: python scripts/audit_bot.py | claude -p --max-turns 3 | python scripts/send_discord_report.py

특징:
- 12시간 로그: ERROR/WARNING/CRITICAL/Exception/Traceback만 필터 (max 200줄)
- 봇 상태: app_state.json 또는 bot.db 읽기
- 거래소 잔고: BithumbClient 비동기 호출
- 거래 성과: journal.db 마지막 12시간 쿼리

출력: 구조화된 텍스트 프롬프트
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# 프로젝트 루트를 sys.path에 추가 (상대 import 작동)
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.WARNING)

# KST 타임존
KST = timezone(timedelta(hours=9))


def _collect_logs() -> str:
    """마지막 12시간 로그를 수집한다 (ERROR/WARNING/CRITICAL/Exception만).

    Returns:
        필터된 로그 문자열.
    """
    try:
        result = subprocess.run(
            [
                "journalctl",
                "-u",
                "bithumb-bot",
                "--since",
                "12 hours ago",
                "--no-pager",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        logs = result.stdout

        # ERROR, WARNING, CRITICAL, Exception, Traceback 필터
        filtered_lines: list[str] = []
        for line in logs.split("\n"):
            if any(
                keyword in line
                for keyword in ["ERROR", "WARNING", "CRITICAL", "Exception", "Traceback"]
            ):
                filtered_lines.append(line)

        # 최대 200줄
        if len(filtered_lines) > 200:
            filtered_lines = filtered_lines[-200:]

        return "\n".join(filtered_lines)
    except Exception as e:
        return f"로그 수집 실패: {e}"


def _collect_bot_state() -> dict[str, Any]:
    """봇 상태를 읽는다.

    data/app_state.json 또는 data/bot.db에서 상태 읽기.

    Returns:
        상태 딕셔너리 (positions, dust_coins, pool_manager, cycle_count, last_cycle_at, pilot 정보).
    """
    state: dict[str, Any] = {}

    # 먼저 data/bot.db 시도
    bot_db_path = project_root / "data" / "bot.db"
    if bot_db_path.exists():
        try:
            from app.state_store import StateStore

            store = StateStore(db_path=bot_db_path)
            state = {}
            for key in ["positions", "dust_coins", "pool_manager", "cycle_count", "last_cycle_at", "pilot_remaining", "pilot_size_mult"]:
                val = store.get(key)
                if val is not None:
                    state[key] = val
            store.close()
            if state:
                return state
        except Exception as e:
            logger.warning("StateStore 읽기 실패: %s", e)

    # 폴백: data/app_state.json
    json_path = project_root / "data" / "app_state.json"
    if json_path.exists():
        try:
            with open(json_path, encoding="utf-8") as f:
                state = json.load(f)
            # 필요한 필드만 추출
            return {
                k: state.get(k)
                for k in ["positions", "dust_coins", "pool_manager", "cycle_count", "last_cycle_at", "pilot_remaining", "pilot_size_mult"]
            }
        except Exception as e:
            logger.warning("app_state.json 읽기 실패: %s", e)

    return {}


async def _collect_exchange_balance() -> dict[str, Any]:
    """거래소 잔고를 조회한다 (BithumbClient 사용).

    Returns:
        coin별 잔고: {"BTC": {"available": 1.5, "locked": 0.2, "avg_buy_price": 50000}, ...}
    """
    try:
        from dotenv import load_dotenv

        load_dotenv(project_root / ".env", override=False)
    except ImportError:
        pass

    api_key = os.environ.get("BITHUMB_API_KEY", "")
    api_secret = os.environ.get("BITHUMB_API_SECRET", "")
    proxy = os.environ.get("PROXY", "http://127.0.0.1:1081")

    if not api_key or not api_secret:
        return {"error": "API 인증 정보 없음"}

    try:
        from market.bithumb_api import BithumbClient

        client = BithumbClient(
            api_key=api_key,
            api_secret=api_secret,
            base_url="https://api.bithumb.com",
            proxy=proxy or None,
        )

        try:
            balance_raw = await client.get_balance("ALL")

            # 레거시 형식 변환: available_btc, locked_btc, avg_buy_price_btc → {BTC: {...}}
            result: dict[str, Any] = {}
            processed_coins = set()

            for key, value in balance_raw.items():
                if not isinstance(value, str):
                    continue

                # available_btc, locked_btc, avg_buy_price_btc 패턴 매칭
                if key.startswith("available_"):
                    coin = key[len("available_") :].upper()
                    if coin not in processed_coins:
                        try:
                            available = float(value)
                            locked = float(balance_raw.get(f"locked_{coin.lower()}", "0") or "0")
                            avg_price = float(
                                balance_raw.get(f"avg_buy_price_{coin.lower()}", "0") or "0"
                            )

                            # 0이 아닌 잔고만 포함
                            if available > 0 or locked > 0:
                                result[coin] = {
                                    "available": available,
                                    "locked": locked,
                                    "avg_buy_price": avg_price,
                                }
                                processed_coins.add(coin)
                        except (ValueError, TypeError):
                            pass

            return result if result else {"status": "empty balance"}
        finally:
            await client.close()

    except Exception as e:
        return {"error": str(e)}


def _collect_trade_performance() -> dict[str, Any]:
    """마지막 12시간 거래 성과를 계산한다.

    journal.db의 trades 테이블에서 exit_time 기준으로 필터.

    Returns:
        {'trade_count': N, 'total_pnl_krw': X, 'wins': W, 'losses': L, 'win_rate': %, 'profit_factor': PF}
    """
    journal_path = project_root / "data" / "journal.db"
    if not journal_path.exists():
        return {"error": "journal.db 없음"}

    try:
        now_ms = int(time.time() * 1000)
        since_ms = now_ms - 12 * 3600 * 1000

        conn = sqlite3.connect(str(journal_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # 마지막 12시간 거래
        cursor.execute(
            """
            SELECT COUNT(*) as cnt,
                   SUM(CASE WHEN net_pnl_krw > 0 THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN net_pnl_krw < 0 THEN 1 ELSE 0 END) as losses,
                   SUM(CASE WHEN net_pnl_krw > 0 THEN net_pnl_krw ELSE 0 END) as total_wins,
                   SUM(CASE WHEN net_pnl_krw < 0 THEN -net_pnl_krw ELSE 0 END) as total_losses,
                   SUM(net_pnl_krw) as total_pnl
            FROM trades
            WHERE exit_time IS NOT NULL AND exit_time > ?
            """,
            (since_ms,),
        )

        row = cursor.fetchone()
        conn.close()

        if not row:
            return {"trade_count": 0, "total_pnl_krw": 0}

        cnt = row["cnt"] or 0
        wins = row["wins"] or 0
        losses = row["losses"] or 0
        total_wins = row["total_wins"] or 0
        total_losses = row["total_losses"] or 0
        total_pnl = row["total_pnl"] or 0

        win_rate = (wins / cnt * 100) if cnt > 0 else 0
        profit_factor = (total_wins / total_losses) if total_losses > 0 else (1.0 if total_wins > 0 else 0)

        return {
            "trade_count": cnt,
            "total_pnl_krw": round(total_pnl, 2),
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 1),
            "profit_factor": round(profit_factor, 2),
        }

    except Exception as e:
        return {"error": f"거래 성과 조회 실패: {e}"}


def _format_pool_summary(pool: dict) -> str:
    """Pool 상태를 요약 테이블로 포맷한다."""
    equity = pool.get("total_equity", 0)
    pools = pool.get("pools", {})
    lines = [f"- 총 자산: {equity:,.0f} KRW"]
    for name, info in pools.items():
        total = info.get("total_balance", 0)
        alloc = info.get("allocated", 0)
        count = info.get("position_count", 0)
        util = (alloc / total * 100) if total > 0 else 0
        lines.append(f"- {name}: {total:,.0f}원 (할당 {alloc:,.0f}원, {count}포지션, 활용률 {util:.1f}%)")
    return "\n".join(lines)


def _format_balance_summary(balance: dict) -> str:
    """거래소 잔고를 요약 테이블로 포맷한다."""
    lines = []
    for coin, info in balance.items():
        if coin in ("KRW", "P"):
            if coin == "KRW":
                lines.append(f"- KRW: {info.get('available', 0):,.0f}원")
            continue
        avail = info.get("available", 0)
        locked = info.get("locked", 0)
        avg_price = info.get("avg_buy_price", 0)
        total = avail + locked
        value = total * avg_price
        if value < 10:
            continue  # 10원 미만 무시
        status = "🔒" if locked > 0 else ""
        lines.append(f"- {coin}: {total:.6f}개 (≈{value:,.0f}원) {status}")
    if not lines:
        lines.append("- (유의미한 잔고 없음)")
    return "\n".join(lines)


def _aggregate_logs(logs: str) -> str:
    """반복 로그를 집계한다."""
    from collections import Counter
    lines = logs.strip().splitlines()
    if not lines or lines[0].startswith("("):
        return logs

    # 메시지 부분만 추출 (타임스탬프 제거)
    messages: list[str] = []
    for line in lines:
        # "[WARNING] app.main: 부분 청산 실패..." 패턴에서 메시지 추출
        parts = line.split("] ", 1)
        if len(parts) > 1:
            msg = parts[-1].strip()
        else:
            msg = line.strip()
        messages.append(msg)

    counts = Counter(messages)
    result_lines = []
    seen = set()
    for msg, count in counts.most_common():
        if msg in seen:
            continue
        seen.add(msg)
        if count >= 3:
            result_lines.append(f"[x{count}회] {msg}")
        else:
            result_lines.append(msg)
    return "\n".join(result_lines[:50])  # 최대 50줄


def _build_prompt(
    logs: str,
    state: dict[str, Any],
    balance: dict[str, Any],
    performance: dict[str, Any],
) -> str:
    """구조화된 감사 프롬프트를 생성한다.

    Args:
        logs: 필터된 시스템 로그.
        state: 봇 상태 (positions, pool_manager, cycle_count 등).
        balance: 거래소 잔고.
        performance: 거래 성과 (trade_count, total_pnl 등).

    Returns:
        Claude Code 분석용 프롬프트.
    """
    now = datetime.now(KST)
    timestamp_str = now.strftime("%Y-%m-%d %H:%M")

    # 마지막 주기 확인
    last_cycle_at = state.get("last_cycle_at")
    if last_cycle_at:
        cycle_time = datetime.fromtimestamp(last_cycle_at, tz=KST)
        cycle_ago = (now - cycle_time).total_seconds() / 60
    else:
        cycle_ago = None

    # 포지션 정보
    positions = state.get("positions", {})
    active_positions = len(positions) if isinstance(positions, dict) else 0

    # Dust 코인
    dust_coins = state.get("dust_coins", [])

    # Pool 정보
    pool_manager = state.get("pool_manager", {})

    # Pilot 정보
    pilot_remaining = state.get("pilot_remaining", 0)
    pilot_size_mult = state.get("pilot_size_mult", 1.0)

    prompt = f"""📊 빗썸봇 정기 감사 ({timestamp_str} KST)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## 시스템 상태

### 봇 운영 상태
- 마지막 사이클: {cycle_ago:.1f}분 전 (15분 주기 예상)
- 활성 포지션: {active_positions}개
- Pilot 남은 횟수: {pilot_remaining}회
- Pilot 사이징 배수: {pilot_size_mult:.2f}x
- 사이클 누적: {state.get('cycle_count', 'N/A')}회

### 자금 현황
{_format_pool_summary(pool_manager)}

### 거래 성과 (최근 12시간)
- 거래: {performance.get('trade_count', 0)}건
- PnL: {performance.get('total_pnl_krw', 0):,.0f} KRW
- 승률: {performance.get('win_rate', 0):.1f}%
- 손익률: {performance.get('profit_factor', 0):.2f}
- 승: {performance.get('wins', 0)}건 / 패: {performance.get('losses', 0)}건

### 거래소 잔고 (0초과만)
{_format_balance_summary(balance)}

### ⚠️ 이상 신호 및 체크리스트

체크할 항목:
1. **봇 활성 여부**: 마지막 사이클이 {cycle_ago:.1f}분 전 — 정상이면 < 20분, 비정상이면 > 30분
2. **거래소 잔고 vs 봇 포지션 불일치**: {active_positions}개 포지션과 거래소 잔고 대조
3. **반복 에러 패턴**: 아래 로그에서 동일 에러가 3회 이상 발생?
4. **거래 빈도**: 12시간에 {performance.get('trade_count', 0)}건 — 비정상적으로 많거나 적음?
5. **손익률**: {performance.get('profit_factor', 0):.2f} — 목표 > 1.5
6. **Dust 포지션**: {len(dust_coins)}개 — 정리 필요?
7. **활성 자금**: Pool 자금 활용률 확인
8. **미체결 주문**: 거래소 미체결 주문 확인 (> 2시간 경고)
9. **일일 DD**: 최근 일일 낙폭 점검
10. **API 연결**: 최근 API 오류 있는지 확인

## 시스템 로그 (최근 12시간 ERROR/WARNING/CRITICAL)

```
{_aggregate_logs(logs) if logs else "(로그 없음 — 정상)"}
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## 분석 요청

중요: 도구(Bash, Read, Grep 등)를 사용하지 말고, 위에 제공된 데이터만으로 분석하라.

위 체크리스트를 기반으로:
1. **🔴 CRITICAL** (즉시 조치): 봇 불능, API 인증 실패, 거래소 잔고 불일치 등
2. **🟡 WARNING** (주의): 거래 부진, 손익률 악화, 에러 반복 등
3. **💡 SUGGESTION** (개선): 파라미터 조정, 전략 재검토 등

각 항목에 대해 **원인 분석** 후 **수정 제안**을 제시하라. 도구 호출 없이 바로 보고서를 출력하라.
"""

    return prompt


async def main() -> None:
    """메인 진입점."""
    try:
        # 1. 로그 수집
        logs = _collect_logs()

        # 2. 봇 상태 수집
        state = _collect_bot_state()

        # 3. 거래소 잔고 수집 (비동기)
        balance = await _collect_exchange_balance()

        # 4. 거래 성과 수집
        performance = _collect_trade_performance()

        # 5. 프롬프트 생성
        prompt = _build_prompt(logs, state, balance, performance)

        # 6. 표준 출력
        print(prompt)

    except Exception as e:
        print(f"감사 실패: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
