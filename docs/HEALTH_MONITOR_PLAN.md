# Orchestrator & HealthMonitor 구현 계획 v2

> 봇 운영 전반을 자동 감시하는 3계층 오케스트레이터 시스템.
> 웹 리서치 기반 벤치마킹 + 실 구현 설계.
> 작성일: 2026-03-26

---

## 1. 리서치 요약

### 1.1 벤치마킹 대상

| 프로젝트 | 핵심 패턴 | 적용 포인트 |
|----------|-----------|------------|
| **Freqtrade** | sd_notify watchdog, `/health` API, Telegram 일일 리포트 | systemd watchdog, 일일 digest |
| **Hummingbot** | Clock 기반 틱 오케스트레이션, 주문 추적 선행 등록, WebSocket+REST 이중화 | 주문 상태 추적 강화 |
| **Evolutionary Crypto Bot** | cron 기반 계층 스케줄링, 72h shadow 검증, 매 틱 잔고 확인 | 재시작 시 cold start 복구 |
| **Superalgos** | Task Manager 패턴, 코인별 독립 태스크, 포트폴리오 감시 봇 | 코인 장애 격리 |
| **Knight Capital 사후분석** | kill switch 부재 → $440M 손실, 실시간 포지션 감시 필수 | 포지션 정합성 최우선 |

### 1.2 핵심 교훈

1. **프로세스 alive ≠ 트레이딩 정상**: Freqtrade #7299에서 HTTP는 응답했지만 트레이딩 루프는 멈춤. → 심장박동은 **메인 루프 완료** 기준이어야 함.
2. **거래소가 진실의 원천**: 로컬 상태는 캐시일 뿐. 주기적 정합성 확인 필수.
3. **자동 복구 vs 인간 개입 구분**: API 타임아웃은 자동, 포지션 drift는 일시정지 후 알림.
4. **LLM은 일일 분석에 적합, 실시간 감시에 부적합**: 속도와 비용 문제로 실시간은 Python, 심층 분석은 Claude.

### 1.3 참고 출처

- [Orchestration Framework for Financial Agents (arXiv)](https://arxiv.org/html/2512.02227v1)
- [Freqtrade Health Check Issue #7299](https://github.com/freqtrade/freqtrade/issues/7299)
- [Hummingbot Architecture](https://hummingbot.org/blog/hummingbot-architecture---part-1/)
- [Evolutionary Crypto Bot (Medium)](https://medium.com/@clturner23/evolutionary-crypto-trading-bot-from-openai-prompts-to-self-learning-ensemble-4091f758afb1)
- [10 Notorious Trading Bot Failures](https://london-post.co.uk/10-notorious-cases-of-trading-bot-failures/)
- [Azure Circuit Breaker Pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/circuit-breaker)
- [aiobreaker (async circuit breaker)](https://aiobreaker.netlify.app/)
- [sdnotify (systemd watchdog)](https://pypi.org/project/sdnotify/)

---

## 2. 아키텍처

```
┌──────────────────────────────────────────────────────┐
│                   Orchestrator                       │
│                                                      │
│  Layer 3: systemd Watchdog (외부, 프로세스 레벨)      │
│    └─ WatchdogSec=300 → 행(hang) 시 자동 재시작      │
│                                                      │
│  Layer 1: HealthMonitor (내부, 15분 주기)             │
│    ├─ 8개 점검 → 건강 점수 (0~100)                   │
│    ├─ AlertManager → 디스코드 (CRITICAL/WARNING)      │
│    ├─ health_checks 테이블 → 이력 저장               │
│    └─ CycleResult → 매 사이클 구조화된 결과 기록      │
│                                                      │
│  Layer 2: Claude 스케줄 에이전트 (매일 09:00 KST)     │
│    ├─ health_checks + journal.db 심층 분석            │
│    ├─ 느린 열화(drift) 감지                          │
│    └─ 종합 일일 리포트 → 디스코드                     │
│                                                      │
│  [신규] 자동 복구 엔진                               │
│    ├─ Circuit Breaker (API 호출)                     │
│    ├─ Graceful Degradation (데이터 부족 시 HOLD)      │
│    └─ Cold Start Recovery (재시작 시 상태 복원)        │
└──────────────────────────────────────────────────────┘
```

**역할 분담:**

| 계층 | 주기 | 역할 | 비용 |
|------|------|------|------|
| Layer 3 (systemd) | 실시간 | 프로세스 생사 감시, 자동 재시작 | 0원 |
| Layer 1 (Python) | 15분 | 실시간 탐지 + 즉시 알림 | 0원 |
| Layer 2 (Claude) | 1일 | 심층 분석 + 트렌드 감지 + 리포트 | API 크레딧 |
| 자동 복구 | 이벤트 | 장애 자동 대응 | 0원 |

---

## 3. Layer 1: HealthMonitor (Python)

### 3.1 파일 구조

```
app/
  health_monitor.py      ← HealthMonitor + AlertManager + CheckResult
  main.py                ← heartbeat 기록 + HealthMonitor task 등록
```

### 3.2 점검 항목 (8개)

#### 점검 1: 메인 루프 심장박동

```
방법: main.py 매 사이클 끝에서 health_monitor.record_heartbeat() 호출
      HealthMonitor가 last_heartbeat_ts 경과시간 확인
WARNING: 20분 미갱신 (cycle_interval 15분의 1.3배)
CRITICAL: 30분 미갱신 (2배)
참고: Freqtrade의 /health 엔드포인트 방식과 동일한 원리
      "프로세스 alive ≠ 루프 정상" — 루프 완료 기준으로 판정
```

#### 점검 2: 이벤트 루프 지연

```
방법: asyncio.sleep(1.0) 후 실제 경과시간 측정
      lag = actual_elapsed - 1.0
WARNING: lag > 3초 (이벤트 루프 과부하)
CRITICAL: lag > 10초 (사실상 멈춤)
참고: Hummingbot의 Clock 기반 틱 정밀도 개념 차용
```

#### 점검 3: API 연결

```
방법: 빗썸 ticker API 1회 호출, 응답시간 측정
      연속 실패 카운트 추적
WARNING: 응답 > 2초
CRITICAL: 연속 3회 실패
자동 복구: Circuit Breaker가 OPEN → 60초 후 HALF-OPEN으로 재시도
참고: aiobreaker 라이브러리 사용 (async native)
```

#### 점검 4: 데이터 신선도

```
방법: 마지막 수집된 15M 캔들의 timestamp vs 현재시각
WARNING: 20분 경과 (정상: 15분 이내)
CRITICAL: 40분 경과
자동 복구: 데이터 40분 이상 오래됨 → HOLD 모드 (신규 진입 차단)
참고: Evolutionary Bot의 "stale data → skip signals" 패턴
```

#### 점검 5: 포지션 정합성 (핵심)

```
방법: (1시간마다 1회, 매 사이클은 아님 — API 부담 경감)
      1. 거래소 잔고 조회 (balance API)
      2. 봇 positions dict와 비교
      3. 코인별 수량 차이 계산

      자동 해결: 차이 < 0.1% (거래소 수수료 반올림 등 dust)
      WARNING: 차이 > 5%
      CRITICAL: 포지션 누락(봇에는 없는데 거래소에 있음) 또는 초과

      CRITICAL 발생 시:
      → 신규 진입 일시 차단
      → 디스코드 알림 (구체적 수량 명시)
      → 인간 개입 대기

참고: Knight Capital 사례 — 포지션 감시 없이 45분에 $440M 손실
      Block3 Finance — "거래소가 진실의 원천, 로컬은 캐시"
```

#### 점검 6: 시스템 리소스

```
방법: psutil로 CPU/메모리/디스크 조회
      + SQLite WAL 파일 크기 확인 (비정상 성장 감지)
WARNING: 메모리 > 70%, WAL > 100MB
CRITICAL: 디스크 > 90%
참고: SQLite WAL 파일이 무한 성장하면 DB 잠금 위험
      (Freqtrade #7299의 근본 원인이 DB 관련이었음)
```

#### 점검 7: 거래 지표

```
방법: journal.db trades 테이블에서 최근 거래 조회
      - 연속 손실 횟수
      - 일일 실현 손익 (DD 계산)
      - 최근 20건 rolling PF
WARNING: 연속 2패, 일일 DD > 2%
CRITICAL: 일일 DD > 3% (config의 daily DD limit)
참고: 거래 부족 시 (< 20건) "insufficient_data"로 별도 처리
      (WF 검증에서 이미 적용한 패턴)
```

#### 점검 8: 디스코드 연결

```
방법: webhook URL로 테스트 POST (빈 메시지 아닌 health ping)
WARNING: —
CRITICAL: 전송 실패
주기: 4시간마다 1회 (매 15분은 과도)
참고: 프록시 경유 필수 (127.0.0.1:1081)
```

### 3.3 건강 점수 (Health Score)

```
0~100점, 가중 합산:

항목                    배점    ok    warn    critical
──────────────────────────────────────────────────────
메인 루프 심장박동        20     20     10        0
API 연결                20     20     10        0
데이터 신선도            15     15      7        0
포지션 정합성            15     15      7        0
이벤트 루프 지연          10     10      5        0
거래 지표                10     10      5        0
시스템 리소스             5      5      2        0
디스코드 연결             5      5      2        0

판정:
  80~100  Healthy   정상 운영
  50~79   Degraded  주의 필요 (디스코드 WARNING)
  <50     Critical  즉시 조치 (디스코드 CRITICAL)
```

### 3.4 AlertManager 상세

```python
알림 정책:

1. 쿨다운 (동일 이슈 반복 억제)
   CRITICAL: 30분
   WARNING:  2시간

2. 배치 (WARNING은 묶어서 전송)
   15분 동안 쌓인 WARNING을 1개 메시지로 묶음
   CRITICAL은 즉시 개별 전송

3. 에스컬레이션 (WARNING → CRITICAL 자동 승격)
   동일 항목 WARNING 3회 연속 → CRITICAL로 승격

4. 상관 억제 (cascade alert 방지)
   "API 연결 실패" 발생 시:
     → "데이터 신선도" 경보 억제
     → "거래 지표" 경보 억제
     → 근본 원인 1건만 알림

5. 회복 알림
   CRITICAL 해소 시 "✅ 정상 복귀: {항목}" 전송
   → 사용자가 "아직 문제인가?" 확인할 필요 없음
```

### 3.5 데이터 저장

```sql
-- journal.db에 추가
CREATE TABLE IF NOT EXISTS health_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    score INTEGER NOT NULL,
    verdict TEXT NOT NULL,        -- "healthy" / "degraded" / "critical"
    results_json TEXT NOT NULL,   -- 8개 점검별 상세 (JSON array)
    alerts_json TEXT DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 보관 정책: 90일 초과 시 HealthMonitor가 자동 정리
-- 예상 데이터량: 96건/일 × 90일 = 8,640건 (< 1MB)
```

---

## 4. 자동 복구 엔진 (신규)

리서치에서 가장 일관되게 강조된 패턴. 기존 봇에 없는 부분.

### 4.1 Circuit Breaker (API 호출)

```
라이브러리: aiobreaker (async native)

적용 대상: bithumb_api.py의 모든 API 호출

상태 전이:
  CLOSED (정상) → 연속 5회 실패 → OPEN (차단)
  OPEN → 60초 경과 → HALF-OPEN (1회 시도)
  HALF-OPEN → 성공 → CLOSED
  HALF-OPEN → 실패 → OPEN (다시 60초 대기)

예외 구분:
  차단 대상: ConnectionError, TimeoutError, HTTP 5xx
  통과 대상: InsufficientBalanceError, APIAuthError (봇 로직 문제)

효과:
  - API 장애 시 무한 재시도 방지
  - 거래소 rate limit ban 예방
  - 복구 시 자동 재개
```

### 4.2 Graceful Degradation 모드

```
조건에 따라 봇의 운영 모드를 자동 전환:

FULL      (정상)       → 모든 기능 활성
HOLD      (데이터 부족) → 신규 진입 차단, 기존 포지션 유지
EXIT_ONLY (DD 위험)    → 청산만 허용
HALT      (심각)       → 모든 거래 중단

전환 조건:
  FULL → HOLD:     데이터 신선도 CRITICAL 또는 API Circuit OPEN
  FULL → EXIT_ONLY: 일일 DD > 3%
  FULL → HALT:      포지션 정합성 CRITICAL 또는 건강 점수 < 30
  * → FULL:         해당 조건 해소 시 자동 복귀

참고: Evolutionary Bot의 "stale data → skip signals" 패턴
```

### 4.3 Cold Start Recovery (재시작 복구)

```
봇 시작 시 실행 순서:

1. SQLite 상태 복원 (기존 로직)
2. [신규] 거래소 잔고 조회 → 로컬 포지션과 정합성 확인
3. [신규] 불일치 발견 시:
   a. 로그에 상세 기록
   b. 디스코드 알림
   c. HOLD 모드로 시작 (자동 매매 차단)
   d. 인간 확인 후 FULL 전환
4. 정합성 정상 → FULL 모드로 시작
5. 데이터 캐시 검증 → 부족한 캔들 보충 수집

참고: Evolutionary Bot의 "wakes up, checks for holes, requests just
      the pieces it needs" 패턴
```

---

## 5. Layer 2: Claude 스케줄 에이전트

### 5.1 실행 방식

```
Claude Code Desktop 스케줄 태스크 (매일 09:00 KST = 00:00 UTC)
→ 로컬 파일 직접 접근 가능
→ 봇 재시작 후에도 유지됨
```

### 5.2 분석 항목

| # | 분석 | 데이터 소스 | Python으로 못 하는 이유 |
|---|------|-----------|---------------------|
| 1 | 건강 점수 추이 해석 | health_checks | 단순 숫자가 아닌 맥락 판단 필요 |
| 2 | 전략별 성과 트렌드 | trades | "전략 C가 왜 안 되는가" 분석 |
| 3 | 반복 패턴 식별 | trades + signals | "같은 코인이 매번 SL" 패턴 인식 |
| 4 | 리소스 증가 추세 | health_checks | 선형 외삽 → 고갈 시점 예측 |
| 5 | 종합 제안 | 전체 | 여러 신호 종합한 판단 |

### 5.3 느린 열화(Slow Drift) 감지

```
Python이 탐지하기 어려운 "서서히 나빠지는" 현상:

1. 7일 rolling Sharpe vs 30일 rolling Sharpe
   → 7일이 30일보다 1σ 이상 낮으면 열화 신호

2. 전략별 승률 추이
   → 최근 20건 승률이 과거 평균에서 2σ 이상 하락

3. 평균 수익/손실 비율 압축
   → 승리 건당 수익은 줄고, 손실 건당 금액은 유지/증가

4. 거래 빈도 변화
   → 신호는 많은데 진입이 줄어듦 = 필터가 너무 엄격해짐
   → 진입은 많은데 수익이 줄어듦 = 시장 적합도 하락

이런 분석은 맥락 이해가 필요하므로 Claude 에이전트가 적합.
```

### 5.4 일일 리포트 형식

```
═══ 일일 봇 리포트 — 2026-03-27 ═══

📊 건강 점수: 92/100 (Healthy)
   24h 추이: 88 → 92 → 95 → 92 (안정)

💰 거래 요약 (24h)
  • 거래: 8건 (5승 3패) — 승률 62.5%
  • 수익: +45,230원 (+0.45%)
  • Profit Factor: 1.82
  • 최대 DD: 1.2% (한도 4.0%)

📈 전략 추이 (7일 rolling)
  • trend_follow: Sharpe 1.42 (↑), 승률 71%
  • breakout: Sharpe 0.8 (↓), 승률 33% ⚠️
  • dca: 미발동 (조건 미충족)

🔄 포지션 정합성
  • 마지막 점검: 08:45 — 정상
  • 보유: XRP, RENDER, TAO, VIRTUAL (4종)

⚠️ 알림 요약 (24h)
  • WARNING: 2건 (API 지연)
  • CRITICAL: 0건

🔧 시스템
  • 업타임: 48h (재시작 없음)
  • 메모리: 85MB (안정)
  • WAL 크기: 2.1MB
  • 디스크: 23GB / 98GB (25%)

💡 분석 & 제안
  • breakout 전략 최근 6건 중 4패 — 파라미터 리뷰 권장
  • API 지연 03:14, 14:22 — 프록시 상태 안정적, 일시적 현상
  • 전체적으로 양호한 운영 상태
```

---

## 6. Layer 3: systemd Watchdog

### 6.1 설정

```ini
# scripts/bithumb-bot.service
[Service]
Type=notify
WatchdogSec=300          # 5분 (15분 사이클의 1/3)
Restart=always
RestartSec=10

# 재시작 시 디스코드 알림 (ExecStartPre에서 처리)
```

### 6.2 코드

```python
# app/main.py — 매 사이클 끝
import sdnotify
_sd = sdnotify.SystemdNotifier()

# 사이클 완료 시:
_sd.notify("WATCHDOG=1")
_sd.notify(f"STATUS=Cycle {cycle_count}, {len(positions)} positions, score={health_score}")
```

`systemctl status bithumb-bot` 출력에 실시간 상태가 표시됨:
```
● bithumb-bot.service - Bithumb Auto Trading Bot v2
   Status: "Cycle 142, 4 positions, score=92"
```

### 6.3 의존성

```
pip install sdnotify     # 경량 (순수 Python, C 의존성 없음)
```

---

## 7. 구현 순서 (우선순위 기반)

리서치 결과 **영향도 × 구현 난이도**로 정렬:

| 순서 | 내용 | 파일 | 난이도 | 영향 |
|------|------|------|--------|------|
| **1** | systemd watchdog (sd_notify) | `service`, `main.py` | 낮음 | 높음 |
| **2** | CheckResult + HealthMonitor 골격 | `app/health_monitor.py` | 중간 | 높음 |
| **3** | 점검 1~4 (심장박동, 루프지연, API, 데이터) | `app/health_monitor.py` | 중간 | 높음 |
| **4** | AlertManager (쿨다운, 배치, 상관억제) | `app/health_monitor.py` | 중간 | 높음 |
| **5** | 점검 5: 포지션 정합성 | `app/health_monitor.py` | 중간 | 최고 |
| **6** | 점검 6~8 (리소스, 지표, 디스코드) | `app/health_monitor.py` | 낮음 | 중간 |
| **7** | health_checks 테이블 + 건강 점수 | `app/journal.py` | 낮음 | 중간 |
| **8** | main.py 통합 | `app/main.py` | 중간 | 높음 |
| **9** | Graceful Degradation (HOLD/EXIT_ONLY) | `app/main.py` | 중간 | 높음 |
| **10** | Cold Start Recovery | `app/main.py` | 중간 | 높음 |
| **11** | Circuit Breaker (API) | `market/bithumb_api.py` | 낮음 | 중간 |
| **12** | 테스트 | `tests/test_health_monitor.py` | 중간 | — |
| **13** | Claude 스케줄 에이전트 등록 | `/schedule` | 낮음 | 중간 |

**Phase A (핵심)**: 순서 1~8 — HealthMonitor + systemd watchdog
**Phase B (자동 복구)**: 순서 9~11 — Degradation + Cold Start + Circuit Breaker
**Phase C (AI 분석)**: 순서 12~13 — 테스트 + Claude 에이전트

---

## 8. 설정 (config.yaml 추가)

```yaml
health_monitor:
  enabled: true
  interval_sec: 900                   # 15분
  reconciliation_interval_sec: 3600   # 정합성 점검: 1시간
  discord_check_interval_sec: 14400   # 디스코드 점검: 4시간

  # 심장박동
  heartbeat_warn_sec: 1200            # 20분
  heartbeat_critical_sec: 1800        # 30분

  # API
  api_timeout_sec: 5
  api_consecutive_fail_critical: 3

  # 데이터
  data_freshness_warn_min: 20
  data_freshness_critical_min: 40

  # 시스템
  memory_warn_pct: 70
  disk_critical_pct: 90
  wal_warn_mb: 100

  # 거래 지표
  daily_dd_warn_pct: 2.0
  daily_dd_critical_pct: 3.0

  # 알림
  alert_cooldown_critical_min: 30
  alert_cooldown_warning_min: 120
  alert_batch_interval_sec: 900       # WARNING 배치 주기

  # 보관
  retention_days: 90

  # Graceful Degradation
  degradation:
    hold_on_stale_data: true
    hold_on_api_circuit_open: true
    exit_only_on_daily_dd: true
    halt_on_reconciliation_critical: true
```

---

## 9. 기대 효과

| 영역 | 현재 (수동) | 도입 후 (자동) |
|------|-----------|--------------|
| 프로세스 행 | 수시간 후 발견 | systemd가 5분 내 재시작 |
| 디스코드 끊김 | 우연히 발견 | 4시간 내 CRITICAL 알림 |
| 포지션 불일치 | 수동 확인 | 1시간 내 탐지 + 매매 일시 차단 |
| API 장애 | 로그 확인 | Circuit Breaker 자동 차단/복구 |
| 데이터 오래됨 | 모름 | HOLD 모드 자동 전환 |
| 전략 성과 열화 | 감으로 판단 | Claude 일일 리포트에서 데이터 기반 감지 |
| 재시작 후 상태 | 수동 확인 | Cold Start Recovery 자동 정합성 |
| 일일 현황 | 여러 곳 확인 | 디스코드 1개 메시지로 종합 리포트 |

---

## 10. 리스크 & 주의사항

1. **HealthMonitor 자체 장애**: 모니터가 죽으면 감시 공백 발생.
   → 대책: systemd watchdog이 최후 안전망 역할. HealthMonitor 예외는 전부 catch.

2. **알림 채널 단일 장애점**: 디스코드가 유일한 알림 채널.
   → 대책: CRITICAL은 `systemctl status`에도 기록 (sd_notify STATUS).
   필요 시 이메일/SMS 보조 채널 추가 가능.

3. **포지션 정합성 오탐**: 거래소 API 지연으로 잠시 불일치 보일 수 있음.
   → 대책: 2회 연속 불일치 시에만 CRITICAL. 1회는 WARNING.

4. **Circuit Breaker 과민 반응**: 일시적 API 지연에 너무 빨리 차단.
   → 대책: failure_threshold=5, recovery_timeout=60 (보수적 설정).

5. **Claude 에이전트 비용**: 매일 1회 → 월 30회.
   → 대책: Haiku 모델 사용 가능, 또는 Python 스크립트로 기본 리포트 생성 후
   주 1회만 Claude 심층 분석.
