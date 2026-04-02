"""봇 로그 요약 스크립트.

최근 N시간의 bot.log를 파싱하여 핵심 지표를 요약 출력.
/loop 10m python3 scripts/log_summary.py 형태로 주기적 모니터링 가능.

사용법:
  python3 scripts/log_summary.py           # 최근 1시간
  python3 scripts/log_summary.py --hours 6 # 최근 6시간
  python3 scripts/log_summary.py --all     # 전체 로그
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = ROOT / "data" / "bot.log"
JOURNAL_PATH = ROOT / "data" / "journal.db"


def parse_log_lines(hours: int | None = 1) -> list[str]:
    """로그 파일에서 최근 N시간 라인을 추출한다."""
    if not LOG_PATH.exists():
        return []

    lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").strip().split("\n")
    if hours is None:
        return lines

    cutoff = datetime.now() - timedelta(hours=hours)
    filtered = []
    for line in lines:
        # 타임스탬프 파싱: 2026-03-22 00:31:09,857
        match = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
        if match:
            try:
                ts = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
                if ts >= cutoff:
                    filtered.append(line)
            except ValueError:
                pass
        elif filtered:
            # 타임스탬프 없는 줄은 이전 로그의 연속 (traceback 등)
            filtered.append(line)

    return filtered


def analyze_lines(lines: list[str]) -> dict:
    """로그 라인을 분석하여 요약 통계를 반환한다."""
    stats: dict = {
        "total_lines": len(lines),
        "cycles": 0,
        "errors": 0,
        "warnings": 0,
        "signals": 0,
        "trades_opened": 0,
        "trades_closed": 0,
        "regimes": Counter(),
        "error_messages": [],
        "first_ts": "",
        "last_ts": "",
    }

    for line in lines:
        # 타임스탬프 추출
        ts_match = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
        if ts_match:
            ts = ts_match.group(1)
            if not stats["first_ts"]:
                stats["first_ts"] = ts
            stats["last_ts"] = ts

        # 레벨 카운트
        if "[ERROR]" in line:
            stats["errors"] += 1
            # 에러 메시지 수집 (최근 5건)
            msg = line.split("[ERROR]")[-1].strip()[:80] if "[ERROR]" in line else ""
            if msg and len(stats["error_messages"]) < 5:
                stats["error_messages"].append(msg)
        if "[WARNING]" in line:
            stats["warnings"] += 1

        # 사이클 완료
        if "사이클 #" in line and "완료" in line:
            stats["cycles"] += 1

        # 신호 생성
        if "신호 생성" in line or "generate_signals" in line:
            stats["signals"] += 1

        # 거래
        if "포지션 진입" in line or "매수 체결" in line:
            stats["trades_opened"] += 1
        if "포지션 종료" in line or "매도 체결" in line or "청산" in line:
            stats["trades_closed"] += 1

        # 국면
        regime_match = re.search(r"국면=(\w+)", line)
        if regime_match:
            stats["regimes"][regime_match.group(1)] += 1

    return stats


def get_journal_summary() -> dict:
    """journal.db에서 최근 거래 요약을 가져온다."""
    summary: dict = {
        "total_trades": 0,
        "today_trades": 0,
        "today_pnl": 0.0,
        "total_pnl": 0.0,
        "active_positions": 0,
    }

    if not JOURNAL_PATH.exists():
        return summary

    try:
        import sqlite3

        conn = sqlite3.connect(str(JOURNAL_PATH))
        conn.row_factory = sqlite3.Row

        # 전체 거래 수
        row = conn.execute("SELECT COUNT(*) FROM trades").fetchone()
        summary["total_trades"] = row[0] if row else 0

        # 전체 PnL
        row = conn.execute("SELECT COALESCE(SUM(net_pnl_krw), 0) FROM trades").fetchone()
        summary["total_pnl"] = row[0] if row else 0

        # 오늘 거래
        today_start = int(datetime.now().replace(hour=0, minute=0, second=0).timestamp() * 1000)
        row = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(net_pnl_krw), 0) FROM trades WHERE exit_time >= ?",
            (today_start,),
        ).fetchone()
        if row:
            summary["today_trades"] = row[0]
            summary["today_pnl"] = row[1]

        # 미종료 포지션 (exit_time이 없거나 0)
        row = conn.execute(
            "SELECT COUNT(*) FROM trades WHERE exit_time IS NULL OR exit_time = 0"
        ).fetchone()
        summary["active_positions"] = row[0] if row else 0

        conn.close()
    except Exception:
        pass

    return summary


def format_summary(stats: dict, journal: dict, hours: int | None) -> str:
    """요약을 포맷한다."""
    period = f"최근 {hours}시간" if hours else "전체"
    lines = [
        f"{'=' * 50}",
        f"  봇 모니터링 요약 ({period})",
        f"  {stats['first_ts']} ~ {stats['last_ts']}",
        f"{'=' * 50}",
    ]

    # 사이클 & 신호
    lines.append(f"\n[사이클] {stats['cycles']}회 완료")
    lines.append(f"[신호]   {stats['signals']}건 생성")

    # 거래
    lines.append("\n[거래]")
    lines.append(f"  진입: {stats['trades_opened']}건 | 종료: {stats['trades_closed']}건")
    if journal["total_trades"] > 0:
        lines.append(f"  오늘: {journal['today_trades']}건, PnL {journal['today_pnl']:,.0f}원")
        lines.append(f"  누적: {journal['total_trades']}건, PnL {journal['total_pnl']:,.0f}원")
    lines.append(f"  활성 포지션: {journal['active_positions']}건")

    # 국면 분포
    if stats["regimes"]:
        lines.append("\n[국면 분포]")
        total = sum(stats["regimes"].values())
        for regime, count in stats["regimes"].most_common():
            pct = count / total * 100
            bar = "█" * int(pct / 5)
            lines.append(f"  {regime:12s} {count:4d} ({pct:4.1f}%) {bar}")

    # 에러/경고
    lines.append("\n[상태]")
    if stats["errors"] > 0:
        lines.append(f"  에러: {stats['errors']}건")
        for msg in stats["error_messages"]:
            lines.append(f"    - {msg}")
    else:
        lines.append("  에러: 없음")
    lines.append(f"  경고: {stats['warnings']}건")
    lines.append(f"  로그: {stats['total_lines']}줄")

    lines.append(f"{'=' * 50}")
    return "\n".join(lines)


def main() -> None:
    """메인 실행."""
    parser = argparse.ArgumentParser(description="봇 로그 요약")
    parser.add_argument("--hours", type=int, default=1, help="최근 N시간 (기본: 1)")
    parser.add_argument("--all", action="store_true", help="전체 로그")
    args = parser.parse_args()

    hours = None if args.all else args.hours

    if not LOG_PATH.exists():
        print(f"로그 파일 없음: {LOG_PATH}")
        print("봇이 아직 실행되지 않았습니다.")
        return

    lines = parse_log_lines(hours)
    stats = analyze_lines(lines)
    journal = get_journal_summary()
    print(format_summary(stats, journal, hours))


if __name__ == "__main__":
    main()
