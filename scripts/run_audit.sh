#!/usr/bin/env bash
# 빗썸봇 정기 감사 실행 스크립트
# cron에서 호출: 06:00, 18:00 KST
set -euo pipefail

cd /home/bythejune/projects/bithumb-bot-v2
LOG=/tmp/audit_bot.log
PROMPT=/tmp/audit_prompt.txt
RESULT=/tmp/audit_result.txt

echo "$(date '+%Y-%m-%d %H:%M:%S') 감사 시작" >> "$LOG"

# 1. 데이터 수집 + 프롬프트 생성
/home/bythejune/projects/bithumb-bot-v2/venv/bin/python scripts/audit_bot.py > "$PROMPT" 2>>"$LOG"
if [ ! -s "$PROMPT" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') 프롬프트 생성 실패" >> "$LOG"
    exit 1
fi

# 2. Claude 분석
/home/bythejune/.local/bin/claude -p --max-turns 3 < "$PROMPT" > "$RESULT" 2>>"$LOG"
if [ ! -s "$RESULT" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') Claude 분석 결과 없음" >> "$LOG"
    exit 1
fi

# 3. Discord 전송
/home/bythejune/projects/bithumb-bot-v2/venv/bin/python scripts/send_discord_report.py < "$RESULT" 2>>"$LOG"

echo "$(date '+%Y-%m-%d %H:%M:%S') 감사 완료" >> "$LOG"
