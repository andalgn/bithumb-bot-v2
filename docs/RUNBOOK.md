# Runbook

<!-- AUTO-GENERATED: DO NOT EDIT SECTIONS BETWEEN THESE MARKERS MANUALLY -->

운영 중인 Bithumb Auto Trading Bot v2 관리를 위한 운영 매뉴얼.

## 배포 절차

### 최초 설치

```bash
git clone <repo-url>
cd bithumb-bot-v2
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# .env 파일에 실제 키 입력
sudo bash scripts/install_service_ubuntu.sh
```

### 코드 업데이트 후 재시작

```bash
cd /home/bythejune/projects/bithumb-bot-v2
git pull
source venv/bin/activate
pip install -r requirements.txt   # 의존성 변경 시
sudo systemctl restart bithumb-bot
sudo systemctl status bithumb-bot
```

### 설정(config.yaml) 변경 후 재시작

```bash
# config.yaml 편집 후
sudo systemctl restart bithumb-bot
```

일부 파라미터는 **핫 리로드** 지원 — `docs/PARAMS.md` 참조.

---

## 봇 상태 확인

```bash
# 서비스 상태
sudo systemctl status bithumb-bot

# 실시간 로그 스트리밍
sudo journalctl -u bithumb-bot -f

# 최근 100줄
sudo journalctl -u bithumb-bot -n 100

# 오늘 로그
sudo journalctl -u bithumb-bot --since today

# 에러만 필터
sudo journalctl -u bithumb-bot -p err
```

---

## 모니터링

### HealthMonitor

봇 내부 HealthMonitor가 900초(15분)마다 자동 점검:

| 항목 | 경고 | 위험 |
|------|------|------|
| 하트비트 | 20분 무응답 | 30분 무응답 |
| API 연속 실패 | — | 3회 연속 |
| 데이터 최신성 | 20분 경과 | 40분 경과 |
| 메모리 사용률 | 70% 이상 | — |
| 디스크 사용률 | — | 90% 이상 |
| 일일 손실 | 2% 이상 | 3% 이상 |

알림 쿨다운: 위험 30분 / 경고 120분

### VPN 상태

```bash
systemctl status xray
# 또는 연결 테스트
curl -x http://127.0.0.1:1081 https://api.bithumb.com/public/ticker/BTC_KRW
```

### 프록시 연결 테스트

```bash
curl -x http://127.0.0.1:1081 https://discord.com
```

---

## 운영 모드 전환

### PAPER → LIVE 전환

1. `docs/LIVE_GATE.md` 체크리스트 전부 통과 확인
2. `configs/config.yaml` 에서 `run_mode: LIVE` 설정
3. `sudo systemctl restart bithumb-bot`
4. Discord LIVE_GATE 채널에서 승인 알림 확인

### LIVE → PAPER/DRY 긴급 전환

```bash
# config.yaml 편집: run_mode: PAPER
sudo systemctl restart bithumb-bot
```

---

## 일반적인 문제 해결

### 봇이 시작되지 않음

```bash
sudo journalctl -u bithumb-bot -n 50 -p err
# ImportError → pip install -r requirements.txt
# .env 누락 → cp .env.example .env && .env 파일 편집
# 포트 충돌 → sudo ss -tlnp | grep <port>
```

### Discord 알림이 안 옴

```bash
# 1. VPN 확인
systemctl status xray
# 2. 프록시 테스트
curl -x http://127.0.0.1:1081 https://discord.com
# 3. 웹훅 URL 확인
grep DISCORD_WEBHOOK .env
```

### API 인증 오류 (빗썸)

```bash
# API 키/시크릿 확인
grep BITHUMB_API .env
# 봇 재시작 (쿼런틴 6000초 적용됨)
sudo systemctl restart bithumb-bot
```

### 메모리 사용량 급증

```bash
# 메모리 현황
free -h
ps aux --sort=-%mem | head -5
# systemd 제한: MemoryMax=2G — 초과 시 자동 재시작됨
```

### WAL 파일 비정상 증가

```bash
# WAL 크기 확인
ls -lh /home/bythejune/projects/bithumb-bot-v2/data/*.db-wal 2>/dev/null
# 봇 재시작 시 WAL 자동 체크포인트됨
sudo systemctl restart bithumb-bot
```

### 드로우다운 킬스위치 발동

봇이 거래를 중단한 경우 (`risk_gate` 발동):

```bash
sudo journalctl -u bithumb-bot -n 200 | grep -i "kill\|dd_limit\|drawdown"
# 해소 후 봇 재시작
sudo systemctl restart bithumb-bot
```

---

## 롤백 절차

```bash
# 이전 커밋으로 롤백
git log --oneline -10
git checkout <commit-hash>
sudo systemctl restart bithumb-bot

# 최신으로 복구
git checkout main
sudo systemctl restart bithumb-bot
```

---

## 백업 / 데이터 관리

```bash
# DB 백업
cp /home/bythejune/projects/bithumb-bot-v2/data/bot.db \
   /home/bythejune/backups/bot-$(date +%Y%m%d).db

# 오래된 백테스트 데이터 정리 (30일 이상)
find /home/bythejune/projects/bithumb-bot-v2/data -name "*.db" -mtime +30
```

---

## systemd 서비스 파일 수정 후 반영

```bash
sudo cp scripts/bithumb-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart bithumb-bot
```

서비스 제한:
- `MemoryMax=2G`
- `CPUQuota=80%`
- `WatchdogSec=600` (10분 내 하트비트 없으면 재시작)
- `Restart=always`, `RestartSec=10`

<!-- END AUTO-GENERATED -->
