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
- DeepSeek API (주간 리뷰만)
- React + TypeScript (대시보드, 선택)

## 개발 규칙
- 언어: 한국어 응답, 영어 커밋 메시지 (Conventional Commits)
- 린터: ruff
- 포매터: ruff format
- 테스트: pytest + pytest-asyncio
- 타입 힌트: 전체 적용
- docstring: 모든 public 함수에 한국어로
- pre-review: 실제 버그와 보안 이슈만 집중

## 프로젝트 구조

<!-- AUTO-GENERATED-TREE: START -->
```
bithumb_auto_v2/
├── CLAUDE.md                    ← 이 파일
├── research_program.md          ← 자율 연구 방향 설정
├── docs/                        ← PRD 기반 설계 문서
├── tasks/                       ← 단계별 작업 명세
├── app/
│   ├── config.py                   ← 설정 로딩 모듈.
│   ├── data_types.py               ← 공통 데이터 타입 정의.
│   ├── journal.py                  ← 거래 기록 모듈.
│   ├── live_gate.py                ← LIVE 승인 자동 검증 모듈.
│   ├── main.py                     ← 오케스트레이터 -15분 주기 메인 루프.
│   ├── notify.py                   ← 디스코드 Webhook 알림 모듈.
│   ├── protocols.py                ← 봇 핵심 컴포넌트 Protocol 인터페이스.
│   └── storage.py                  ← 상태 영속화 모듈.
├── strategy/
│   ├── auto_researcher.py          ← AutoResearcher — 자율 전략 실험 엔진.
│   ├── coin_profiler.py            ← 코인 프로파일러 — 자동 Tier 분류.
│   ├── correlation_monitor.py      ← 코인 간 상관관계 모니터링.
│   ├── darwin_engine.py            ← Darwinian 자가 학습 엔진.
│   ├── environment_filter.py       ← EnvironmentFilter — L1 환경 필터.
│   ├── experiment_store.py         ← 실험 기록 + 파라미터 변경 로그 저장소.
│   ├── indicators.py               ← 기술적 지표 계산 모듈.
│   ├── pool_manager.py             ← 3풀 자금 관리 모듈.
│   ├── position_manager.py         ← Pool 기반 2단계 사이징 모듈.
│   ├── promotion_manager.py        ← 승격/강등 시스템.
│   ├── regime_classifier.py        ← 국면 분류기 — 히스테리시스 적용 국면 판정.
│   ├── review_engine.py            ← ReviewEngine - 일일/주간/월간 리뷰.
│   ├── rule_engine.py              ← 전략 엔진 — 5국면 분류 + 전략 A/B/C/D 점수제 + Layer 1 환경 필터.
│   ├── size_decider.py             ← SizeDecider — 포지션 사이즈 결정.
│   └── strategy_scorer.py          ← StrategyScorer — 전략 점수 계산.
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
    ├── download_and_backtest.py    ← 90일 캔들 데이터 다운로드 + 전략 파이프라인 백테스트.
    ├── log_summary.py              ← 봇 로그 요약 스크립트.
    ├── optimize.py                 ← 전략 파라미터 최적화 실행.
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
