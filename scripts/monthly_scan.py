"""월간 코드 품질 스캔 — 죽은 코드 + 복잡도 분석.

Usage:
    python scripts/monthly_scan.py          # 전체 스캔
    python scripts/monthly_scan.py --quick  # 요약만
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ["app", "strategy", "market", "execution", "risk", "backtesting"]
REPORT_DIR = PROJECT_ROOT / "reports"


def run_cmd(cmd: list[str]) -> str:
    """명령 실행 후 stdout 반환."""
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)
    return result.stdout + result.stderr


def scan_dead_code() -> str:
    """vulture로 죽은 코드 탐지."""
    lines = []
    lines.append("## Dead Code (vulture, confidence >= 80%)\n")

    output = run_cmd(["vulture"] + SCAN_DIRS + ["--min-confidence", "80"])
    if not output.strip():
        lines.append("죽은 코드 없음.\n")
    else:
        lines.append("```")
        lines.append(output.strip())
        lines.append("```\n")

    count = len([line for line in output.strip().split("\n") if line.strip()])
    lines.append(f"**총 {count}건**\n")
    return "\n".join(lines)


def scan_complexity() -> str:
    """radon으로 복잡도 분석."""
    lines = []
    lines.append("## Cyclomatic Complexity (radon, grade C 이상)\n")

    output = run_cmd(["radon", "cc"] + SCAN_DIRS + ["-a", "-n", "C", "-s"])
    if not output.strip():
        lines.append("복잡도 C 이상 함수 없음.\n")
    else:
        lines.append("```")
        lines.append(output.strip())
        lines.append("```\n")

    # 평균 복잡도
    avg_output = run_cmd(["radon", "cc"] + SCAN_DIRS + ["-a", "-s"])
    for line in avg_output.strip().split("\n"):
        if "Average complexity" in line:
            lines.append(f"**{line.strip()}**\n")
            break

    return "\n".join(lines)


def scan_maintainability() -> str:
    """radon MI (Maintainability Index) 스캔."""
    lines = []
    lines.append("## Maintainability Index (radon mi, grade B 이하)\n")

    output = run_cmd(["radon", "mi"] + SCAN_DIRS + ["-n", "B", "-s"])
    if not output.strip():
        lines.append("유지보수성 B 이하 파일 없음.\n")
    else:
        lines.append("```")
        lines.append(output.strip())
        lines.append("```\n")

    return "\n".join(lines)


def scan_loc() -> str:
    """radon raw LOC 통계."""
    lines = []
    lines.append("## Lines of Code Summary\n")

    output = run_cmd(["radon", "raw"] + SCAN_DIRS + ["-s"])
    # 마지막 Summary 부분만 추출
    summary_start = output.rfind("** Total **")
    if summary_start >= 0:
        lines.append("```")
        lines.append(output[summary_start:].strip())
        lines.append("```\n")
    else:
        lines.append("LOC 통계를 가져올 수 없음.\n")

    return "\n".join(lines)


def main() -> None:
    """메인 실행."""
    quick = "--quick" in sys.argv

    today = datetime.now().strftime("%Y-%m-%d")
    report_lines = [f"# Monthly Code Quality Scan — {today}\n"]

    print(f"[scan] 월간 코드 품질 스캔 시작 ({today})")

    print("[scan] 1/4 Dead code 분석...")
    report_lines.append(scan_dead_code())

    print("[scan] 2/4 Complexity 분석...")
    report_lines.append(scan_complexity())

    if not quick:
        print("[scan] 3/4 Maintainability 분석...")
        report_lines.append(scan_maintainability())

        print("[scan] 4/4 LOC 통계...")
        report_lines.append(scan_loc())

    report = "\n".join(report_lines)

    # 리포트 저장
    REPORT_DIR.mkdir(exist_ok=True)
    report_path = REPORT_DIR / f"monthly_scan_{today}.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"[scan] 리포트 저장: {report_path}")

    # 콘솔 출력
    print("\n" + "=" * 60)
    print(report)


if __name__ == "__main__":
    main()
