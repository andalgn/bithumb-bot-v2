# 자가검증 + 정기 감사 설계

## 배경

봇이 주문 실행 후 실제 체결 여부를 검증하지 않아, 거래소에 코인이 남아있는데 "청산 완료"로 처리하는 버그가 발생했다. 또한 자금 활용률 저하, 필터 과다 차단 등 구조적 문제를 사용자가 직접 발견하기 전까지 봇이 인지하지 못했다.

## 기능 1: 주문 후 거래소 잔고 재검증

### 목적
매도 주문 실행 직후 거래소 잔고를 조회하여, 주문이 실제로 체결되었는지 검증한다.

### 구현 위치
`app/main.py` — 새 메서드 `_verify_sell_execution()`

### 흐름
```
매도 주문 실행 완료
  → get_balance(coin) 호출
  → expected_remaining = 기존 qty - 매도 qty
  → actual = 거래소 available + locked
  → 비교 (허용 오차 0.1%)
  ├─ 일치 → 정상 진행
  ├─ actual > expected (안 팔림)
  │   → 포지션 복원 (positions에 다시 추가)
  │   → Pool 반환 취소
  │   → Discord SYSTEM 경고
  └─ actual < expected (더 팔림)
      → 포지션 qty/size_krw 조정
      → Discord SYSTEM 경고
```

### 호출 지점
- `_close_position()`: 매도 주문 성공(FILLED/PARTIAL) 후
- `_partial_close_position()`: 부분 매도 성공 후

### 제약
- LIVE 모드에서만 동작
- API 호출 1회 추가 (get_balance는 전체 잔고 반환, 특정 코인만 확인)

### 메서드 시그니처
```python
async def _verify_sell_execution(
    self,
    symbol: str,
    sold_qty: float,
    pre_sell_qty: float,
    position_backup: Position | None,
) -> bool:
    """매도 후 거래소 잔고를 검증한다.

    Returns:
        True면 검증 통과, False면 불일치 감지 (포지션 복원됨).
    """
```

### HealthMonitor 확장

**Check 10: 자금 활용률**
- 매 15분 체크
- 활용률 < 10%가 6시간 이상 지속 시 WARNING
- 활용률 = (포지션 총 가치) / (전체 자산) × 100

**Check 11: 거래소↔봇 잔고 정합성**
- 1시간 주기 (기존 reconciliation_interval_sec 활용)
- 모든 보유 포지션에 대해 거래소 잔고와 비교
- 불일치 발견 시 CRITICAL + Discord 알림
- 봇에 없는 거래소 잔고 발견 시 더스트로 자동 등록

## 기능 2: 정기 Claude Code 감사

### 목적
일 2회 `claude -p`로 봇 상태를 종합 감사하여 구조적 문제를 사전에 탐지한다.

### 실행 주기
- 매일 06:00, 18:00 KST (cron)

### 스크립트
`scripts/audit_bot.py`

### 데이터 수집 (Python)
1. **봇 로그**: `journalctl -u bithumb-bot --since "12 hours ago"` — 에러/경고만 필터
2. **거래소 잔고**: Bithumb API `get_balance()` — 0 초과 코인만
3. **봇 포지션**: `data/app_state.json`의 positions + dust_coins
4. **거래 성과**: `data/journal.db` — 최근 12시간 거래 요약 (PF, 승률, 평균 PnL)
5. **자금 활용률**: Pool 상태에서 계산
6. **더스트 현황**: dust_coins 목록 + 현재가 기준 가치

### Claude 프롬프트 구조
```
[시스템 컨텍스트]
빗썸 자동매매 봇 정기 감사. 아래 데이터를 분석하여 문제를 찾고 개선안을 제시하라.

[점검 항목]
1. 거래소 잔고 vs 봇 포지션 불일치 여부
2. 반복되는 에러/경고 패턴 (같은 에러 N회 이상)
3. 매매 빈도 — 기대 대비 너무 적으면 원인 분석
4. 수익성 — PF, 승률, Expectancy 추세
5. 자금 활용률 — 유휴 자금 비율
6. 더스트 잔고 — 정리 가능 여부
7. 코드 레벨 구조적 문제 (로그 패턴에서 추론)

[출력 형식]
## 🔴 CRITICAL (즉시 조치)
## 🟡 WARNING (주의 필요)
## 💡 SUGGESTION (개선 제안)

각 항목: 문제 설명 + 근거 데이터 + 구체적 조치안
```

### 실행 방식
```bash
python3 scripts/audit_bot.py | claude -p --max-turns 3 | python3 scripts/send_discord_report.py
```

1. `audit_bot.py`: 데이터 수집 + 프롬프트 생성 → stdout
2. `claude -p`: 분석 → stdout
3. `send_discord_report.py`: Discord SYSTEM 채널 전송

### cron 등록
```cron
CRON_TZ=Asia/Seoul
0 6 * * * cd /home/bythejune/projects/bithumb-bot-v2 && /home/bythejune/projects/bithumb-bot-v2/venv/bin/python scripts/audit_bot.py 2>/tmp/audit_bot.log | claude -p --max-turns 3 2>>/tmp/audit_bot.log | /home/bythejune/projects/bithumb-bot-v2/venv/bin/python scripts/send_discord_report.py 2>>/tmp/audit_bot.log
0 18 * * * cd /home/bythejune/projects/bithumb-bot-v2 && /home/bythejune/projects/bithumb-bot-v2/venv/bin/python scripts/audit_bot.py 2>/tmp/audit_bot.log | claude -p --max-turns 3 2>>/tmp/audit_bot.log | /home/bythejune/projects/bithumb-bot-v2/venv/bin/python scripts/send_discord_report.py 2>>/tmp/audit_bot.log
```

### 비용 제어
- `--max-turns 3`: Claude 실행 범위 제한
- 데이터 수집은 Python (토큰 소비 없음)
- 에러/경고 로그만 필터 (전체 로그 전송 X)

## 변경 파일 목록

| 파일 | 변경 |
|------|------|
| `app/main.py` | `_verify_sell_execution()` 추가, `_close_position`/`_partial_close_position`에서 호출 |
| `app/health_monitor.py` | Check 10 (자금 활용률), Check 11 (잔고 정합성) 추가 |
| `scripts/audit_bot.py` | 신규 — 데이터 수집 + 프롬프트 생성 |
| `scripts/send_discord_report.py` | 기존 — 감사 보고서 전송에 재활용 |
| crontab | 06:00, 18:00 감사 스케줄 추가 |

## 테스트

- `_verify_sell_execution`: 잔고 일치/불일치 시나리오 단위 테스트
- `audit_bot.py`: 수동 실행 후 Discord 메시지 확인
- HealthMonitor Check 10/11: PAPER 모드에서 로그 확인
