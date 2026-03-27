#!/usr/bin/env bash
# daily_report.sh — 일일 리포트 생성 및 Discord 전송 스크립트
# cron에서 호출: bash /home/bythejune/projects/bithumb-bot-v2/scripts/daily_report.sh

set -euo pipefail

PROJECT_ROOT="/home/bythejune/projects/bithumb-bot-v2"
LOG_FILE="/tmp/daily_report_last.log"
CLAUDE_LOG="/tmp/daily_report_claude.log"

cd "$PROJECT_ROOT"

# 가상환경 활성화
source venv/bin/activate

# claude CLI PATH 추가 (cron의 기본 PATH에는 없음)
export PATH="/home/bythejune/.local/bin:$PATH"

TIMESTAMP="$(date '+%Y-%m-%d %H:%M:%S')"
echo "[$TIMESTAMP] daily_report.sh started" | tee "$LOG_FILE"

# Claude로 리포트 생성 (출력 없으면 빈 문자열, 에러는 무시)
REPORT="$(claude -p "$(cat scripts/daily_report_prompt.txt)" \
    --model sonnet \
    --allowedTools "Read,Grep,Glob,Bash(python3 *)" \
    --output-format text \
    2>"${CLAUDE_LOG}" || true)"

if [ -z "$REPORT" ]; then
    echo "[$TIMESTAMP] warning: claude -p produced no output" | tee -a "$LOG_FILE"
    exit 0
fi

# Discord로 전송
SEND_RESULT="$(echo "$REPORT" | python3 scripts/send_discord_report.py 2>&1 || true)"
echo "[$TIMESTAMP] send result: $SEND_RESULT" | tee -a "$LOG_FILE"

echo "[$TIMESTAMP] daily_report.sh finished" | tee -a "$LOG_FILE"
