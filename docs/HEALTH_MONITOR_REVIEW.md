# HealthMonitor 계획 검토 보고서

> HEALTH_MONITOR_PLAN.md v2에 대한 3가지 검토 사항.
> 작성일: 2026-03-26

---

## 질문 1: 우분투 서버에서 Claude Desktop 사용 가능한가?

### 결론: 불가능. 대안 있음.

Claude Desktop 앱은 GUI가 필요하며 headless 우분투 서버에서 실행할 수 없다.
따라서 HEALTH_MONITOR_PLAN.md의 "Claude Desktop 스케줄 태스크" 방식은 사용 불가.

### 대안 비교

| 방식 | headless 서버 | 지속성 | 로컬 파일 접근 | 최소 주기 |
|------|:---:|:---:|:---:|:---:|
| Claude Desktop 스케줄 | **X** | O | O | 1분 |
| Cloud 스케줄 (`/schedule`) | O | O | **X** (fresh clone) | 1시간 |
| `cron` + `claude -p` | **O** | **O** | **O** | 1분 |
| `/loop` (세션 내) | O | X (세션 종료 시 소멸) | O | 1분 |

### 추천: `cron` + `claude -p`

**가장 적합한 방식.** 이유:

1. **headless 서버 완전 호환**: `-p` (print) 플래그로 TTY 없이 실행
2. **로컬 파일 직접 접근**: journal.db, health_checks, 로그 모두 읽기 가능
3. **cron이 스케줄 관리**: 봇 재시작과 독립, 서버 재부팅 후에도 유지
4. **권한 제어 가능**: `--allowedTools "Read,Grep,Glob,Bash(python3 *)"` 로 최소 권한

**구현 예시:**

```bash
# /etc/cron.d/bithumb-bot-report
# 매일 00:00 UTC (09:00 KST) 일일 리포트
0 0 * * * bythejune cd /home/bythejune/projects/bithumb-bot-v2 && \
  claude -p "$(cat scripts/daily_report_prompt.txt)" \
  --model sonnet \
  --allowedTools "Read,Grep,Glob,Bash(python3 *)" \
  --output-format text \
  2>/dev/null | python3 scripts/send_discord_report.py
```

**daily_report_prompt.txt 예시:**

```
journal.db의 health_checks, trades 테이블과 최근 로그를 분석하여
일일 봇 리포트를 생성하라.

포함 항목:
1. 건강 점수 24h 추이
2. 거래 요약 (건수, 승률, PF, DD)
3. 전략별 성과 (7일 rolling)
4. 포지션 정합성 상태
5. 시스템 리소스 추이
6. 이상 패턴 분석 및 제안

출력은 디스코드 마크다운 형식으로.
```

### HEALTH_MONITOR_PLAN.md 수정 필요 사항

- Layer 2의 "Claude Desktop 스케줄 태스크" → `cron + claude -p` 로 교체
- `/schedule` (cloud) → 보조 옵션 (로컬 파일 불필요한 작업에 사용 가능)

---

## 질문 2: Claude Max 구독에서 Sonnet 사용 시 사용량 영향

### 결론: 영향 미미. 걱정 불필요.

### Max 구독 사용량 구조

| 구독 | 5시간 윈도우 메시지 수 | 일일 추정 용량 | 월 가격 |
|------|:---:|:---:|:---:|
| Pro | ~40-45 | ~100-200 | $20 |
| Max 5x | ~225 | ~500-1,000 | $100 |
| Max 20x | ~900 | ~2,000+ | $200 |

- Claude Code와 claude.ai는 **동일 사용량 버킷** 공유
- 사용량은 "메시지" 단위 (1 프롬프트+응답 = 1 메시지, 단 복잡한 멀티툴은 더 소비)
- 5시간 rolling window + 별도 주간 한도 존재

### 일일 리포트의 예상 소비량

```
입력: ~50KB (health_checks + trades + 로그 요약)
     = ~12,000 토큰

출력: ~2,000 토큰 (리포트 텍스트)

소비: 약 1~3 메시지 분량
```

| 구독 | 일일 용량 | 리포트 소비 | 비율 |
|------|:---:|:---:|:---:|
| Max 5x | ~500 | ~2 | **0.4%** |
| Max 20x | ~2,000 | ~2 | **0.1%** |

### 주간 전략 리뷰 추가 시

```
주 1회 Opus 심층 분석:
  입력: ~100KB = ~25,000 토큰
  출력: ~5,000 토큰
  소비: 약 3~5 메시지

월간 총 추가 소비: 일일 리포트 30건 + 주간 4건 = ~80 메시지
Max 5x 월간 용량 대비: ~1~2% 이하
```

### 결론

**Max 구독에서 일일 Sonnet 리포트는 사용량에 사실상 영향 없음.**
대화형 코딩 세션 1회 (수백 메시지)와 비교하면 무시할 수준.

---

## 질문 3: 전략 열화 감지 시 자동 수정 가능한가?

### 결론: 기술적으로 가능. 단, 안전장치 필수.

### 가능한 파이프라인

```
[HealthMonitor 감지]
  → 전략 C 승률 30% 미만 (7일 rolling, 최소 10건)
  → 자동 트리거

[Phase 1: Opus 분석 + 계획]
  claude -p "전략 breakout 최근 성과 분석 + 개선 계획 수립" \
    --model opus \
    --allowedTools "Read,Grep,Glob" \     ← 읽기만 허용
    --output-format json \
    > /tmp/fix-plan.json

[Phase 2: Sonnet 구현]
  claude -p "이 계획을 구현하라: $(cat /tmp/fix-plan.json)" \
    --model sonnet \
    --allowedTools "Read,Edit,Bash(python -m pytest *)" \
    --output-format json

[Phase 3: 검증]
  pytest 전체 통과 확인
  → 실패 시 변경 사항 revert

[Phase 4: 배포 결정]
  ┌─ 자동 배포 (테스트 통과 + 파라미터 변경만) ← config.yaml 수정
  │
  └─ PR 생성 + 디스코드 알림 (코드 변경 시) ← 인간 리뷰
```

### Claude Code 제공 기능

| 기능 | 용도 | 안전성 |
|------|------|--------|
| `claude -p` | headless 실행, 스크립트에서 호출 | 안전 |
| `--allowedTools` | 도구별 권한 제한 | 안전 |
| `--model opus/sonnet` | 모델 선택 | 안전 |
| `--output-format json` | 구조화된 출력 | 안전 |
| `--continue` / `--resume` | 세션 이어서 실행 | 안전 |
| `--dangerously-skip-permissions` | 모든 권한 확인 생략 | **위험 — 사용 금지** |

### 안전장치 (필수)

```
1. 읽기/쓰기 분리
   - Opus (분석): Read, Grep, Glob만 허용
   - Sonnet (구현): Read, Edit, Bash(pytest)만 허용
   - 절대 금지: Bash(python run_bot.py), Bash(curl),
     Bash(systemctl), .env 파일 수정

2. 변경 범위 제한
   - 파라미터 변경만 자동 적용 (config.yaml)
   - 전략 코드 변경은 별도 브랜치 + PR → 인간 리뷰

3. 테스트 게이트
   - pytest 전체 통과 필수
   - 실패 시 자동 revert (git checkout -- .)

4. 빈도 제한
   - 자동 수정은 주 1회까지
   - 같은 전략에 대해 연속 수정 금지 (최소 7일 간격)

5. 디스코드 알림
   - 자동 수정 시작/완료/실패 모두 알림
   - 변경 내용 요약 포함

6. hooks 가드레일
   - PreToolUse 훅으로 위험 파일 수정 차단
     (.env, bithumb_api.py, main.py 등)
```

### 자동 수정 대상 vs 인간 리뷰 대상

| 구분 | 자동 적용 가능 | 인간 리뷰 필요 |
|------|:---:|:---:|
| config.yaml 파라미터 조정 (SL/TP/가중치) | O | |
| 지표 임계값 변경 | O | |
| 전략 로직 변경 (점수 계산 등) | | O |
| 새 필터/조건 추가 | | O |
| 모듈 구조 변경 | | O |
| 리스크 설정 변경 | | O |

### 구현 방법

```bash
# scripts/auto_fix.sh — HealthMonitor가 트리거

#!/bin/bash
set -euo pipefail

STRATEGY="$1"          # e.g. "breakout"
REASON="$2"            # e.g. "win_rate_below_30"
BOT_DIR="/home/bythejune/projects/bithumb-bot-v2"
cd "$BOT_DIR"

# 빈도 제한: 마지막 수정 후 7일 이내면 중단
LAST_FIX=$(cat data/last_auto_fix_${STRATEGY}.ts 2>/dev/null || echo 0)
NOW=$(date +%s)
if (( NOW - LAST_FIX < 604800 )); then
    echo "빈도 제한: ${STRATEGY} 마지막 수정 후 7일 미경과"
    exit 0
fi

# Phase 1: Opus 분석
PLAN=$(claude -p "
journal.db의 trades 테이블에서 전략 '${STRATEGY}'의 최근 성과를 분석하라.
문제: ${REASON}
configs/config.yaml과 strategy/ 코드를 읽고 개선 계획을 JSON으로 출력하라.
형식: {\"changes\": [{\"file\": \"...\", \"type\": \"param|code\", \"description\": \"...\"}]}
" --model opus --allowedTools "Read,Grep,Glob" --output-format json 2>/dev/null)

# 파라미터 변경만 있는지 확인
CODE_CHANGES=$(echo "$PLAN" | python3 -c "
import sys, json
data = json.load(sys.stdin)
code = [c for c in data.get('result',{}).get('changes',[]) if c.get('type')=='code']
print(len(code))
" 2>/dev/null || echo "1")

if [ "$CODE_CHANGES" != "0" ]; then
    # 코드 변경 포함 → 브랜치 + PR (인간 리뷰)
    git checkout -b "auto-fix/${STRATEGY}-$(date +%Y%m%d)"
    claude -p "이 계획을 구현하라: $PLAN" \
        --model sonnet \
        --allowedTools "Read,Edit,Bash(python -m pytest *)" \
        2>/dev/null

    if python -m pytest tests/ -q --ignore=tests/test_bithumb_api.py; then
        git add -A && git commit -m "fix: auto-optimize ${STRATEGY} — ${REASON}"
        # 디스코드 알림: PR 리뷰 요청
        python3 scripts/notify.py "자동 수정 완료: ${STRATEGY}\n브랜치: auto-fix/${STRATEGY}-$(date +%Y%m%d)\n인간 리뷰 필요"
    else
        git checkout -- .
        git checkout main
        python3 scripts/notify.py "자동 수정 실패: ${STRATEGY} — 테스트 미통과"
    fi
else
    # 파라미터만 변경 → 직접 적용
    claude -p "이 계획을 구현하라: $PLAN" \
        --model sonnet \
        --allowedTools "Read,Edit" \
        2>/dev/null

    if python -m pytest tests/ -q --ignore=tests/test_bithumb_api.py; then
        echo "$NOW" > "data/last_auto_fix_${STRATEGY}.ts"
        sudo systemctl restart bithumb-bot
        python3 scripts/notify.py "자동 파라미터 조정 완료: ${STRATEGY}\n사유: ${REASON}"
    else
        git checkout -- .
        python3 scripts/notify.py "자동 수정 실패: ${STRATEGY} — 테스트 미통과"
    fi
fi
```

---

## 종합: HEALTH_MONITOR_PLAN.md 수정 사항

| 항목 | 기존 | 수정 |
|------|------|------|
| Layer 2 실행 방식 | Claude Desktop 스케줄 태스크 | `cron + claude -p` |
| Layer 2 모델 | 미지정 | 일일: Sonnet, 주간: Opus |
| 자동 수정 기능 | 없음 | 신규 Layer 4 추가 |
| 비용 영향 | 미검토 | Max 구독 대비 1~2% (무시 가능) |

### 수정된 아키텍처

```
Layer 1: HealthMonitor (Python, 15분마다)           ← 변경 없음
Layer 2: cron + claude -p (매일 09:00 KST)          ← Desktop → cron 변경
Layer 3: systemd Watchdog (프로세스 외부)             ← 변경 없음
Layer 4: 자동 수정 파이프라인 (이벤트 트리거)          ← 신규
  ├─ Opus 분석 + 계획 (Read only)
  ├─ Sonnet 구현 (Edit + pytest)
  ├─ 파라미터만 → 자동 적용
  └─ 코드 변경 → 브랜치 + 인간 리뷰
```

---

## 참고 출처

- [Claude Code Scheduled Tasks](https://code.claude.com/docs/en/scheduled-tasks) — Desktop vs Cloud 차이
- [Claude Code Headless Mode](https://code.claude.com/docs/en/headless) — `-p` 플래그, CI/CD 활용
- [Claude Code Permissions](https://code.claude.com/docs/en/permissions) — `--allowedTools`, auto mode
- [Claude Code Auto Mode](https://www.anthropic.com/engineering/claude-code-auto-mode) — 자동 승인 안전 분류기
- [Agent SDK Overview](https://platform.claude.com/docs/en/agent-sdk/overview) — 프로그래밍 방식 제어
- [Claude Max Plan Limits](https://intuitionlabs.ai/articles/claude-max-plan-pricing-usage-limits) — Max 5x/20x 용량
- [Claude Code Rate Limits](https://portkey.ai/blog/claude-code-limits/) — 사용량 측정 방식
- [Claude Code + Cron Guide](https://smartscope.blog/en/generative-ai/claude/claude-code-cron-schedule-automation-complete-guide-2025/) — cron 자동화
