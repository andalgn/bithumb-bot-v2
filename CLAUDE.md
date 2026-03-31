# Bithumb Auto Trading Bot v2

## 프로젝트 개요
빗썸 KRW 마켓 암호화폐 24시간 자동매매 봇.
처음부터 새로 만드는 프로젝트. PRD v1.3 기반.

## 운영 환경
- **개발/운영 머신**: Ubuntu Server 미니PC (Ryzen 7 4700U 8코어, 8GB RAM)
- **네트워크**: VPN 24시간 연결 (한국 서버 경유)
- **24시간 무중단 운영** (systemd 서비스 등록)
- **IDE**: VS Code + Claude Code CLI
- **GCP 대비 이점**: 8코어 CPU 여유로 백테스트/Shadow 병렬 실행, 디스크 여유로 장기 데이터 축적

## 핵심 목표
1. **수익성 강화** — Expectancy > 0, Profit Factor > 1.5
2. **안전성 강화** — MDD < 15%, 일일 DD < 4%
3. **자금 활용률 향상** — 50~60%
4. **자가 학습** — 경량 Darwinian + 주간 Claude 리뷰
5. **24시간 무중단 자동매매**

## 기술 스택
- Python 3.12+ / aiohttp / FastAPI / SQLite (WAL)
- 빗썸 API (KRW 마켓, REST + 비동기)
- discord.py (알림 Webhook + 슬래시 커맨드)
- Claude CLI (파이프 모드) — LLM 추론 (DeepSeek 대체)
- React + TypeScript (대시보드, 선택)

## 개발 규칙
- 언어: 한국어 응답, 영어 커밋 메시지 (Conventional Commits)
- 린터: ruff
- 포매터: ruff format
- 테스트: pytest + pytest-asyncio
- 타입 힌트: 전체 적용
- docstring: 모든 public 함수에 한국어로
- pre-review: 실제 버그와 보안 이슈만 집중

### 아키텍처 원칙
- config.yaml 변경은 반드시 ApprovalWorkflow 경유 (직접 쓰기 금지)
- Darwin Shadow에 LLM 추론 추가 금지 (경량 파라미터 평가기 유지)
- Full Autonomy 전환 시에도 GuardAgent 검증 병목은 유지
- 파라미터 제안 경로: EvolutionOrchestrator → ApprovalWorkflow 단일 채널
- ReviewEngine은 관측/보고 전용 (파라미터 변경 제안 금지)

## 프로젝트 구조

<!-- AUTO-GENERATED-TREE: START -->
```
bithumb_auto_v2/
├── CLAUDE.md                    ← 이 파일
├── research_program.md          ← 자율 연구 방향 설정
├── docs/                        ← PRD 기반 설계 문서
├── tasks/                       ← 단계별 작업 명세
├── app/
│   ├── approval_workflow.py        ← 승인 워크플로우 — 진화 변경의 인간 승인 관리.
│   ├── config.py                   ← 설정 로딩 모듈.
│   ├── cycle_data.py               ← 사이클 내 공유 데이터 컨테이너.
│   ├── data_types.py               ← 공통 데이터 타입 정의.
│   ├── errors.py                   ← 커스텀 예외 계층.
│   ├── event_store.py              ← 시스템 이벤트 감사 로그 (Event Sourcing).
│   ├── health_monitor.py           ← HealthMonitor — 봇 건강 감시 시스템.
│   ├── journal.py                  ← 거래 기록 모듈.
│   ├── live_gate.py                ← LIVE 승인 자동 검증 모듈.
│   ├── llm_client.py               ← Claude Code CLI 기반 LLM 클라이언트.
│   ├── main.py                     ← 오케스트레이터 -15분 주기 메인 루프.
│   ├── notify.py                   ← 디스코드 Webhook 알림 모듈.
│   ├── protocols.py                ← 봇 핵심 컴포넌트 Protocol 인터페이스.
│   ├── state_store.py              ← SQLite 기반 단일 상태 저장소.
│   └── storage.py                  ← 상태 영속화 모듈.
├── strategy/
│   ├── auto_researcher.py          ← AutoResearcher — 자율 전략 실험 엔진.
│   ├── coin_profiler.py            ← 코인 프로파일러 — 자동 Tier 분류.
│   ├── coin_universe.py            ← CoinUniverse — 빗썸 거래량 기준 동적 코인 유니버스 관리.
│   ├── correlation_monitor.py      ← 코인 간 상관관계 모니터링.
│   ├── darwin_engine.py            ← Darwinian 자가 학습 엔진.
│   ├── environment_filter.py       ← EnvironmentFilter — L1 환경 필터.
│   ├── evolution_orchestrator.py   ← EvolutionOrchestrator — 자율 진화 7단계 루프.
│   ├── experiment_store.py         ← 실험 기록 + 파라미터 변경 로그 저장소.
│   ├── feedback_loop.py            ← FeedbackLoop — 거래 실패 패턴을 집계하고 가설을 생성한다.
│   ├── guard_agent.py              ← GuardAgent — 진화 변경의 구조적 검증 모듈.
│   ├── indicators.py               ← 기술적 지표 계산 모듈.
│   ├── momentum_ranker.py          ← MomentumRanker — 코인 간 횡단면 모멘텀 점수 계산 및 순위 결정.
│   ├── pool_manager.py             ← 3풀 자금 관리 모듈.
│   ├── position_manager.py         ← Pool 기반 2단계 사이징 모듈.
│   ├── promotion_manager.py        ← 승격/강등 시스템.
│   ├── regime_classifier.py        ← 국면 분류기 — 히스테리시스 적용 국면 판정.
│   ├── review_engine.py            ← ReviewEngine - 일일/주간/월간 리뷰.
│   ├── rule_engine.py              ← 전략 엔진 — 5국면 분류 + 전략 A/B/C/D 점수제 + Layer 1 환경 필터.
│   ├── self_reflection.py          ← SelfReflection — 거래 후 자동 반성 생성 모듈.
│   ├── size_decider.py             ← SizeDecider — 포지션 사이즈 결정.
│   ├── strategy_params.py          ← 진화 가능 파라미터 단일 관리 모듈.
│   ├── strategy_scorer.py          ← StrategyScorer — 전략 점수 계산.
│   └── trade_tagger.py             ← TradeTagger — 거래 결과를 실패 유형으로 분류한다.
├── market/
│   ├── bithumb_api.py              ← 빗썸 REST API 클라이언트.
│   ├── datafeed.py                 ← 데이터 수집 모듈.
│   ├── market_store.py             ← 장기 시장 데이터 축적 모듈.
│   └── normalizer.py               ← 가격/수량 정규화 모듈.
├── risk/
│   ├── dd_limits.py                ← Drawdown Kill Switch 모듈.
│   └── risk_gate.py                ← 통합 리스크 게이트웨이 모듈.
├── execution/
│   ├── order_manager.py            ← 주문 상태 머신 (FSM) 모듈.
│   ├── partial_exit.py             ← 부분청산 + 트레일링 스톱 모듈.
│   ├── quarantine.py               ← 격리 시스템 모듈.
│   └── reconciler.py               ← 거래소-로컬 상태 동기화 모듈.
├── backtesting/
│   ├── backtest.py                 ← 기본 백테스터.
│   ├── daemon.py                   ← 백테스트 검증 데몬.
│   ├── monte_carlo.py              ← Monte Carlo 시뮬레이션.
│   ├── optimizer.py                ← 파라미터 최적화 엔진.
│   ├── param_grid.py               ← 파라미터 그리드 정의.
│   ├── sensitivity.py              ← 파라미터 민감도 분석.
│   └── walk_forward.py             ← Walk-Forward 검증.
├── bot_discord/
│   └── bot.py                      ← 디스코드 슬래시 커맨드 처리기.
└── scripts/
    ├── compare_backtest.py         ← 현재 설정 vs 완화 설정 A/B 백테스트 비교.
    ├── download_and_backtest.py    ← 90일 캔들 데이터 다운로드 + 전략 파이프라인 백테스트.
    ├── log_summary.py              ← 봇 로그 요약 스크립트.
    ├── migrate_state.py            ← 5개 상태 파일 → data/bot.db 마이그레이션.
    ├── optimize.py                 ← 전략 파라미터 최적화 실행.
    ├── optimize_strategies.py      ← 전략 파라미터 최적화 — SL/TP 그리드 서치 + 필터 완화 통합.
    ├── send_discord_report.py      ← Discord 웹훅으로 리포트를 전송하는 스크립트.
    ├── simulate_relaxation.py      ← 파라미터 완화 시뮬레이션 — 4개 시나리오 비교 백테스트.
    └── sync_claude_md.py           ← CLAUDE.md와 실제 프로젝트 구조의 동기화를 검증/갱신하는 스크립트.
├── configs/
│   └── config.yaml              ← 통합 설정
├── tests/                       ← pytest 테스트
├── data/                        ← 런타임 데이터 (git 무시)
├── requirements.txt
├── .env.example
├── .gitignore
└── run_bot.py                   ← 진입점
```
<!-- AUTO-GENERATED-TREE: END -->

## 문서 구조
작업 전 반드시 해당 spec 파일을 읽을 것:

| 파일 | 내용 | 언제 참조 |
|------|------|-----------|
| `docs/PRD_OVERVIEW.md` | 1페이지 전체 요약 | 항상 |
| `docs/ARCHITECTURE.md` | 모듈 구조 + 데이터 흐름 + 빗썸 API | 모듈 생성 시 |
| `docs/STRATEGY_SPEC.md` | 전략 5종 + 점수체계 + 국면분류 | 전략 작업 시 |
| `docs/SIZING_SPEC.md` | Pool 기반 2단계 사이징 수식 | 사이징 작업 시 |
| `docs/RISK_SPEC.md` | RiskGate 상태전이 + 체결비용 | 리스크/주문 작업 시 |
| `docs/PROMOTION_SPEC.md` | 승격 시스템 전체 규칙 | 승격/Core 작업 시 |
| `docs/DARWINIAN_SPEC.md` | Darwinian + Composite Score + 검증 강화 | Darwinian 작업 시 |
| `docs/BACKTEST_SPEC.md` | Walk-Forward + Monte Carlo + 민감도 분석 + Auto-Optimize + Auto-Research | 백테스트 작업 시 |
| `docs/TRADE_SCHEMA.md` | Trade Schema + 성과측정 | journal/성과 작업 시 |
| `docs/LIVE_GATE.md` | LIVE 승인 체크리스트 | LIVE 전환 전 |
| `docs/PARAMS.md` | 즉시 반영 파라미터 전체 | config 작업 시 |

## 구현 로드맵
**반드시 순서대로 진행. 각 단계 완료 시 PAPER 모드에서 검증.**

| 단계 | 기간 | 파일 | 핵심 |
|------|------|------|------|
| 0 | 2~3일 | `tasks/PHASE0_SETUP.md` | 환경 셋업 + 프로젝트 생성 + 빗썸 API 연결 |
| 1 | 1~2주 | `tasks/PHASE1_INFRA.md` | 시장 데이터(5M/15M/1H) + 주문 FSM + 오케스트레이터 + RiskGate |
| 2 | 2~3주 | `tasks/PHASE2_STRATEGY.md` | 국면 5단계 + 점수제 + MTF + 코인 프로파일러 + 상관관계 |
| 3 | 3~4주 | `tasks/PHASE3_POOL.md` | 3풀 + Pool 사이징 + 승격 + 상관관계 필터 |
| 4 | 4~5주 | `tasks/PHASE4_EXECUTION.md` | 부분청산 + 트레일링 + 체결정책 |
| 5 | 5~6주 | `tasks/PHASE5_DARWIN.md` | Shadow 20~30개 + Walk-Forward + Monte Carlo + 민감도 분석 |
| 6 | 6~7주 | `tasks/PHASE6_REVIEW.md` | ReviewEngine + DeepSeek + 검증 리포트 |
| 7 | 7~11주 | `tasks/PHASE7_LIVE.md` | PAPER 28일 + LIVE 승인 |

## 대상 코인 (10개)
BTC/KRW, ETH/KRW, XRP/KRW, SOL/KRW, RENDER/KRW,
VIRTUAL/KRW, EIGEN/KRW, ONDO/KRW, TAO/KRW, LDO/KRW

## 실행 가이드

### 스크립트 사용법

<!-- AUTO-GENERATED: Scripts Reference -->

| 스크립트 | 용도 | 사용법 |
|---------|------|--------|
| `python scripts/download_and_backtest.py` | 90일 캔들 다운로드 + 전략 백테스트 | `python scripts/download_and_backtest.py` |
| `python scripts/optimize_strategies.py` | SL/TP 파라미터 그리드 서치 + 최적 설정 제안 | `python scripts/optimize_strategies.py` |
| `python scripts/simulate_relaxation.py` | 4개 완화 시나리오 비교 백테스트 | `python scripts/simulate_relaxation.py` |
| `python scripts/optimize.py` | 전략 파라미터 최적화 (출력 전용) | `python scripts/optimize.py` |
| `python scripts/compare_backtest.py` | 현재 vs 완화 A/B 백테스트 비교 | `python scripts/compare_backtest.py` |
| `python scripts/log_summary.py` | 봇 로그 자동 요약 | `python scripts/log_summary.py` |
| `python scripts/send_discord_report.py` | Discord 웹훅으로 리포트 전송 | `python scripts/send_discord_report.py` |
| `bash scripts/auto_fix.sh` | 코드 린팅 + 포매팅 (ruff) | `bash scripts/auto_fix.sh` |
| `bash scripts/daily_report.sh` | 일일 보고서 생성 (Claude 프롬프트) | `bash scripts/daily_report.sh` |
| `bash scripts/fix_discord_proxy.sh` | Discord 플러그인 프록시 패치 | `bash scripts/fix_discord_proxy.sh` |

### 환경 변수

`.env.example`에서 필요한 환경 변수:

```bash
# Bithumb API
BITHUMB_API_KEY=your_api_key
BITHUMB_API_SECRET=your_api_secret
BITHUMB_API_URL=https://api.bithumb.com

# Discord 알림 (6개 웹훅)
DISCORD_WEBHOOK_TRADE=https://discord.com/api/webhooks/...      # 거래 알림
DISCORD_WEBHOOK_REPORT=https://discord.com/api/webhooks/...    # 일일/주간 보고서
DISCORD_WEBHOOK_BACKTEST=https://discord.com/api/webhooks/...  # 백테스트 결과
DISCORD_WEBHOOK_SYSTEM=https://discord.com/api/webhooks/...    # 시스템 상태
DISCORD_WEBHOOK_COMMAND=https://discord.com/api/webhooks/...   # 커맨드 응답
DISCORD_WEBHOOK_LIVEGATE=https://discord.com/api/webhooks/...  # LIVE 승인

# Discord 봇 (슬래시 커맨드)
DISCORD_BOT_TOKEN=your_discord_bot_token
DISCORD_GUILD_ID=your_guild_id

# 대시보드 (선택)
DASHBOARD_API_KEY=your_dashboard_key
DASHBOARD_SECRET_KEY=your_secret_key

# 운영 모드
RUN_MODE=DRY  # DRY|PAPER|LIVE
```

## Ubuntu 24시간 운영 참고
- `systemd` 서비스로 등록 (`scripts/bithumb-bot.service`)
- 설치: `sudo bash scripts/install_service_ubuntu.sh`
- 관리: `sudo systemctl {start|stop|restart|status} bithumb-bot`
- 로그: `sudo journalctl -u bithumb-bot -f`
- VPN 자동 재연결 설정 필수
- 봇 crash 시 자동 재시작 (Restart=always) + 디스코드 알림

### 봇 프로세스 관리 (필수)
**봇은 systemd 서비스로 운영 중. `nohup`이나 직접 `python run_bot.py`로 실행하지 않는다.**

```bash
# 재시작 (코드 변경 후)
sudo systemctl restart bithumb-bot

# 중지
sudo systemctl stop bithumb-bot

# 상태 확인
sudo systemctl status bithumb-bot

# 실시간 로그
sudo journalctl -u bithumb-bot -f

# 최근 로그 N줄
sudo journalctl -u bithumb-bot -n 100

# 서비스 파일 수정 후 반영
sudo cp scripts/bithumb-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart bithumb-bot
```

## 최근 변경사항 (2026-03-31)

### 주요 커밋

| 커밋 | 설명 |
|------|------|
| `5c264f3` | feat: trade pipeline observability — event sourcing + watchdog 추가 |
| `bdb640c` | fix: pilot sizing deadlock + pool allocation leak 해결 |
| `149a838` | refactor: DeepSeek API → Claude CLI 파이프 모드로 대체 |
| `6f36150` | fix: MAS 리팩터 코드 리뷰 반영 |
| `1863c5a` | refactor: config.yaml 쓰기 경로 ApprovalWorkflow 통일 |

### 신기능

#### 1. 파이프라인 이벤트 소싱 (Event Sourcing)
- **파일**: `app/journal.py`, `app/health_monitor.py`
- **내용**: 
  - `pipeline_events` 테이블로 전체 신호-거래 추적 (trace_id)
  - 각 파이프라인 단계별 이벤트 기록 (corr_rejected, risk_rejected, sizing_done, order_filled)
  - HealthMonitor Check 9: 4시간 funnel로 deadlock 감지

#### 2. Claude CLI 파이프 모드
- **파일**: `app/llm_client.py`
- **대체**: DeepSeek API → `claude -p` stdin pipe
- **영향**:
  - `strategy/feedback_loop.py` — generate_hypotheses()
  - `strategy/review_engine.py` — weekly insights
  - `strategy/auto_researcher.py` — experiment proposals
- **이점**: API 키 불필요, Claude Max 구독 활용, 네트워크 호출 최소화

#### 3. Pilot 사이징 Deadlock 수정
- **파일**: `strategy/position_manager.py`, `strategy/pool_manager.py`
- **문제**: Pilot 모드에서 size_mult=0.5 적용 시 최소값 이하로 떨어져 0 거래 발생
- **해결**:
  - min_krw 체크를 pilot 적용 전에 수행
  - pilot 중 최소값 floor 설정
  - PoolManager.reconcile() — 할당/카운트 드리프트 정정

#### 4. 새로운 최적화 스크립트
- **`optimize_strategies.py`**: SL/TP 그리드 서치 + 필터 완화 통합
- **`simulate_relaxation.py`**: 4개 완화 시나리오 A/B 백테스트 비교

### 아키텍처 원칙 강화

1. **ApprovalWorkflow 단일 채널**: 모든 config.yaml 변경은 반드시 ApprovalWorkflow 경유
2. **ReviewEngine 관측 전용**: 파라미터 제안 금지 (EvolutionOrchestrator만 제안)
3. **파이프라인 추적성**: 모든 거래의 신호-거래 경로를 trace_id로 추적 가능

### 환경 변수 추가
- 파일: `.env.example`
- 신규: 모든 Discord 웹훅이 명시적으로 정의됨 (6개 채널)
- 기존: RUN_MODE (DRY|PAPER|LIVE)
