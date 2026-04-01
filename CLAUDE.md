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
4. **자가 학습** — 경량 Darwinian + 주간 DeepSeek 리뷰
5. **24시간 무중단 자동매매**

## 기술 스택
- Python 3.12+ / aiohttp / FastAPI / SQLite (WAL)
- 빗썸 API (KRW 마켓, REST + 비동기)
- discord.py (알림 Webhook + 슬래시 커맨드)
- DeepSeek API (deepseek-chat / deepseek-reasoner)
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
│   ├── llm_client.py               ← Anthropic Claude API 기반 LLM 클라이언트.
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
│   ├── spread_profiler.py          ← SpreadProfiler — 코인별 동적 스프레드 임계값 관리.
│   ├── strategy_params.py          ← 진화 가능 파라미터 단일 관리 모듈.
│   ├── strategy_scorer.py          ← StrategyScorer — 전략 점수 계산.
│   └── trade_tagger.py             ← TradeTagger — 거래 결과를 실패 유형으로 분류한다.
├── market/
│   ├── bithumb_api.py              ← 빗썸 REST API 클라이언트.
│   ├── datafeed.py                 ← 데이터 수집 모듈.
│   ├── impact_model.py             ← Square-Root Impact 거래비용 모델.
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
    ├── audit_bot.py                ← 정기 봇 감사 스크립트.
    ├── backtest_utilization.py     ← 자금 활용률 개선 백테스트 — 3가지 개선안 비교.
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

# DeepSeek API
DEEPSEEK_API_KEY=sk-xxxx  # systemd 서비스 필수

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

## 최근 변경사항 (2026-04-01)

### 최신 커밋 (3개 — 전략 최적화 + 필터 완화 + 진화 확장)

| 커밋 | 날짜 | 설명 |
|------|------|------|
| `cd6b3cf` | 2026-04-01 | feat: expand evolution search space and improve report format |
| `0965a84` | 2026-03-31 | feat: relax filters + DeepSeek LLM + fix review reports |
| `0a318e0` | 2026-03-31 | feat: optimize strategy params + add auto-diagnosis system |

### 1. 전략 파라미터 최적화 (0a318e0)

**목표**: SL/TP 비율 최적화로 손익률 개선

| 전략 | 변경 | 효과 | 가설 |
|------|------|------|------|
| mean_reversion | tp_rr 1.5 → 2.5 | PF 0.97 → 1.83 (+89%) | 높은 수익 배수로 큰 이익 건 포착 |
| DCA | tp_pct 0.03 → 0.05 | PF 1.07 → 2.17 (+103%) | 강한 추세에서 더 높은 익절 |
| trend_follow | **비활성화** | PF < 1 (모든 SL/TP) | 현 강도로 수익성 미달, 코드 유지만 |

**파일**: `configs/config.yaml` (strategies 섹션)

**명령어**:
```bash
python scripts/optimize_strategies.py  # 전체 그리드 재최적화 (5시간)
```

### 2. 필터 완화 + DeepSeek LLM (0965a84)

**시나리오**: D_적극 (공격적 필터 완화) — 백테스트 PF 1.30

#### 환경 필터 (L1) 완화
| 파라미터 | 기존 | 완화 | 목적 |
|---------|------|------|------|
| volume_ratio (L1) | 0.8 | 0.4 | 저유동성 코인도 진입 |
| spread_x | 1x | 2x | 스프레드 넓은 코인 허용 |
| night_t3_block | BLOCK | 30% 사이징 | 야간 T3도 제한적 진입 |
| probe_min_cutoff | -10 | -15 | 약한 신호도 허용 |
| full_min_cutoff | -10 | -15 | 약한 신호도 허용 |

#### 포지션 정책
| 파라미터 | 기존 | 완화 |
|---------|------|------|
| active_positions | 5 | 8 |
| core_positions | 3 | 5 |
| active_risk | 7% | 15% |
| pool_cap | 25% | 40% |

**파일**: `configs/config.yaml` (environment_filter, sizing)

**테스트**:
```bash
python scripts/simulate_relaxation.py  # D_적극 vs D_중도 vs D_보수 A/B 비교
```

#### LLM 백엔드 전환
- **기존**: Claude CLI 파이프 모드 (claude -p)
- **신규**: DeepSeek API (systemd 호환성)

**모델 라우팅**:
- `deepseek-chat`: 에러 진단 (HealthMonitor T2 진단)
- `deepseek-reasoner`: 가설 생성, 주간 리뷰 (깊은 추론)

**환경 변수**:
```bash
DEEPSEEK_API_KEY=sk-xxxx
```

**파일**: `app/llm_client.py`

### 3. 자동 진단 시스템 (0a318e0)

**계층별 대응**:
- **T1 (일시적)**: 로그만 기록
- **T2 (경고)**: DeepSeek 진단 + Discord 보고 + 근본 원인 + 수정 제안
- **T3 (위험)**: 즉시 경고 + 진단

**특징**:
- 30분 cooldown (진단 폭주 방지)
- 10분 startup grace (초기 false alarm 억제)
- 비동기 & non-blocking (메인 루프 영향 없음)

**파일**: `app/health_monitor.py` (Check 10 추가, startup grace)

### 4. 진화 루프 확장 (cd6b3cf)

**확장 범위**:
- max_experiments: 10 → 50 (병목 해제)
- LLM 가설: 3 → 5 (더 다양한 아이디어)
- **전략 그리드**: 6 → 21 후보 (SL/TP + DCA params)
- **컷오프 그리드**: 4 → 8 후보
- **리스크 그리드**: 2 → 11 후보 (dd, cooldown, consecutive_loss)
- **사이징 그리드**: 2 → 13 후보 (risk, cap, defense)
- **국면 그리드**: NEW 6 후보 (volume_ratio, adx)
- **총 후보**: ~3-9 → 최대 64 (cap 50)

**탐색 전략**:
- 모든 영역 항상 탐색 (약한 영역만 X)
- 구조화된 리포트 (evolution/daily/monthly 일관성)

**파일**: `strategy/evolution_orchestrator.py` (StrategyGridBuilder 확장)

### 5. 추가 변경사항

#### HealthMonitor Check 10개
| Check | 기능 | 임계값 |
|-------|------|--------|
| 1 | API 연결 | 3회 연속 실패 → WARNING |
| 2 | 주문 상태 | 미체결 > 2h → CRITICAL |
| 3 | 포지션 드리프트 | 거래소 vs 로컬 δ > 5% → WARNING |
| 4 | Pilot 표본 | < 5 → WARNING |
| 5 | 데이터 신선도 | > 5m gap → WARNING |
| 6 | MDD | > 15% → CRITICAL |
| 7 | 일일 DD | > 4% → WARNING |
| 8 | 거래 부진 | 12h 거래 0 → WARNING |
| 9 | 파이프라인 funnel | 신호 vs 거래 비율 이상 → WARNING |
| 10 | Pilot 신뢰도 | < 30 samples → WARNING |

#### Review Report 개선
- **월간 리뷰**: _last_monthly 플래그로 중복 제거
- **일일/주간 리뷰**: 구조화된 섹션 (result/progress/interpretation)
- **일관성**: 모든 7개 진화 세션 결과도 동일 포맷

#### 버그 수정
- ExperimentStore.get_history() `source` 파라미터 누락
- 주문 가격 정규화 (entry_price vs tick-aligned)
- MIN_ORDER_KRW 경계값 반올림 오류

### systemd 환경 변수 추가

**파일**: `scripts/bithumb-bot.service`

```ini
Environment=PYTHONUNBUFFERED=1
Environment=CLAUDECODE=1
Environment=DEEPSEEK_API_KEY=sk-xxxx
```

## 운영 체크리스트

### 주간 작업
- [ ] 월요일: 이전 주 performance review (ReviewEngine 자동)
- [ ] 월요일: 진화 루프 실행 (EvolutionOrchestrator Sunday 자동)
- [ ] 매일: HealthMonitor 경고 확인 (Discord DISCORD_WEBHOOK_SYSTEM)
- [ ] 금요일: 주간 리포트 검토 + 수동 승인 필요 시

### 수익성 모니터링
- **목표**: PF > 1.5, Expectancy > 0, MDD < 15%
- **위험**: PF < 1.0 → 전략 재검토
- **개선**: 기존 파라미터 → 그리드 탐색 → 상위 5개 후보 → ApprovalWorkflow 승인

### 안전성 모니터링
- **일일 DD > 4%** → HealthMonitor Check 7 경고
- **MDD > 15%** → HealthMonitor Check 6 경고 (CRITICAL)
- **미체결 주문 > 2시간** → HealthMonitor Check 2 경고 (CRITICAL)

## 문서 동기화

**스크립트**: `python scripts/sync_claude_md.py`
- 프로젝트 구조와 CLAUDE.md 일치 확인
- 실제 파일 목록과 문서 비교
- 오래된 모듈 감지

**주기**: 월 1회 이상 또는 구조 변경 시
