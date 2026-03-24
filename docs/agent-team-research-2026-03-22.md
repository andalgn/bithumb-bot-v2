# 에이전트 팀 시스템 검토 결과

**작성일**: 2026-03-22

## Context

Claude Code의 에이전트 팀 기능을 매매봇에 적용할 수 있는지 검토. 팀장/검사/코딩/매매/연구 에이전트로 역할을 나누어 자율 운영하는 구조를 원함.

## 조사 결과

### 현재 가능한 것

**1. Claude Code Agent Teams (실험적 기능)**
- `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`로 활성화
- 팀원별 독립 컨텍스트 + 직접 메시지 교환 + 공유 태스크 리스트
- 한계: **세션이 활성화된 동안만 작동** (24/7 데몬 불가), 세션 종료 시 팀 해체

**2. Claude Agent SDK (Python/TypeScript)**
- 프로그래밍 방식으로 에이전트를 코드 안에서 실행
- 장기 실행 프로세스에 적합
- 한계: 아직 초기 단계, 에이전트 간 직접 통신은 직접 구현 필요

**3. Subagents (현재 이미 사용 중)**
- 포그라운드/백그라운드 실행 가능
- 한계: 서브에이전트끼리 직접 통신 불가, 메인 에이전트를 통해서만

### 사용자가 원하는 구조 vs 현실

| 원하는 것 | 현재 가능 여부 |
|-----------|---------------|
| 팀장이 팀원에게 작업 지시 | ⚠️ Agent Teams로 가능하나 세션 내에서만 |
| 24/7 자율 운영 | ❌ Claude Code 세션이 닫히면 중단 |
| 정해진 시간에 자동 실행 | ❌ 에이전트가 스스로 깨어나지 못함 |
| 텔레그램으로 나에게 보고 | ✅ 기존 TelegramNotifier로 가능 |
| 코드 수정 후 자동 적용 | ⚠️ Agent Teams에서 가능하나 세션 내 |

### 핵심 한계

**Claude Code 에이전트는 "항상 켜져있는 데몬"이 아닙니다.** 세션이 열려있는 동안만 작동하고, 세션이 닫히면 모든 에이전트가 종료됩니다. 사용자가 원하는 "24시간 자율 운영 에이전트 팀"은 현재 Claude Code만으로는 불가능합니다.

## 실현 가능한 대안

### 방안 A: 기존 봇 + 정기 Claude Code 세션 (가장 현실적)

```
매매봇 (Python, 24/7 systemd)
  ├── 매매 실행 (기존 main.py — 항상 실행)
  ├── BacktestDaemon (기존 — 항상 실행)
  ├── AutoResearcher (기존 — 주간 실행)
  └── 텔레그램 알림 (기존 — 항상 실행)

Claude Code 세션 (필요 시 수동 또는 cron으로 실행)
  ├── 일일 검사: cron으로 claude 호출 → log_summary + 이슈 분석
  ├── 코드 수정: 검사 결과 기반 수정 작업
  └── 전략 연구: 백테스트 + 최적화
```

**장점**: 매매봇은 안정적으로 24/7 실행, Claude는 필요할 때만 호출
**단점**: 에이전트 간 자율 협업이 아니라 "봇 + 도구" 구조

### 방안 B: Claude Agent SDK로 에이전트 파이프라인 구축

Python 코드에서 Claude API를 직접 호출하여 에이전트 역할을 구현:

```python
# 매일 cron으로 실행
async def daily_agent_pipeline():
    # 1. 검사 에이전트 (Claude API 호출)
    inspection = await call_claude("최근 24시간 로그를 분석하고 이슈를 보고해")

    # 2. 팀장 에이전트 (Claude API 호출)
    decision = await call_claude(f"검사 결과를 검토하고 수정 필요 여부 판단: {inspection}")

    # 3. 코딩 에이전트 (필요 시)
    if decision.needs_fix:
        fix = await call_claude(f"다음 이슈를 수정해: {decision.issues}")

    # 4. 텔레그램 보고
    await notifier.send(f"일일 보고: {decision.summary}")
```

**장점**: 24/7 자동 실행 가능, 에이전트 역할 분리 가능
**단점**: Claude API 비용, 코드 수정을 Claude API가 직접 하기 어려움 (파일 쓰기 권한 문제)

### 방안 C: Agent Teams로 인터랙티브 세션 (제한적)

Claude Code Agent Teams를 활성화하고, 필요할 때 팀 세션을 시작:

```
claude --team trading-ops
  [lead] 팀장: 전체 조율
  [inspector] 검사: 로그 분석
  [coder] 코딩: 수정 작업
```

**장점**: 에이전트 간 직접 소통 가능
**단점**: 세션 동안만 작동, 24/7 불가, 실험적 기능

## 권장안

**방안 A (기존 봇 강화)가 가장 현실적입니다.**

현재 이미 구현된 것들이 에이전트 역할의 대부분을 수행합니다:
- 매매 에이전트 → `app/main.py` (24/7 사이클)
- 연구 에이전트 → `AutoResearcher` + `BacktestDaemon`
- 검사 → `scripts/log_summary.py` + `ReviewEngine`

부족한 부분만 보강하면 됩니다:
1. **일일 종합 보고서 자동 생성 + 텔레그램 전송** (ReviewEngine 강화)
2. **이상 탐지 시 자동 알림** (임계값 기반)
3. **필요 시 Claude Code 세션을 cron으로 호출하여 분석/수정**
