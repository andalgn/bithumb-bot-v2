#!/usr/bin/env bash
# 빗썸봇 정기 감사 — DeepSeek 분석 + Discord 전송
set -euo pipefail
cd /home/bythejune/projects/bithumb-bot-v2
LOG=/tmp/audit_bot.log
echo "$(date '+%Y-%m-%d %H:%M:%S') 감사 시작" >> "$LOG"
/home/bythejune/projects/bithumb-bot-v2/venv/bin/python scripts/audit_bot.py >> "$LOG" 2>&1
echo "$(date '+%Y-%m-%d %H:%M:%S') 감사 완료" >> "$LOG"
