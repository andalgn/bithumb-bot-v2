#!/bin/bash
# Bithumb Bot v2 — Ubuntu systemd 서비스 등록
# 사용법: sudo bash scripts/install_service_ubuntu.sh

set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_FILE="$PROJECT_DIR/scripts/bithumb-bot.service"
USER=$(whoami)

echo "프로젝트: $PROJECT_DIR"
echo "사용자: $USER"

# 서비스 파일에서 경로/사용자 치환
sed -e "s|/home/bythejune/projects/bithumb-bot-v2|$PROJECT_DIR|g" \
    -e "s|User=bythejune|User=$USER|g" \
    -e "s|Group=bythejune|Group=$USER|g" \
    "$SERVICE_FILE" > /tmp/bithumb-bot.service

# 서비스 설치
sudo cp /tmp/bithumb-bot.service /etc/systemd/system/bithumb-bot.service
sudo systemctl daemon-reload
sudo systemctl enable bithumb-bot
sudo systemctl start bithumb-bot

echo ""
echo "설치 완료. 상태 확인:"
sudo systemctl status bithumb-bot --no-pager

echo ""
echo "유용한 명령어:"
echo "  sudo systemctl status bithumb-bot    # 상태"
echo "  sudo systemctl restart bithumb-bot   # 재시작"
echo "  sudo systemctl stop bithumb-bot      # 중지"
echo "  sudo journalctl -u bithumb-bot -f    # 실시간 로그"
