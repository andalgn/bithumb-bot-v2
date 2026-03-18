# Bithumb Auto Trading Bot v2

## 프로젝트 개요
빗썸 KRW 마켓 암호화폐 24시간 자동매매 봇.
처음부터 새로 만드는 프로젝트. PRD v1.3 기반.

## 운영 환경
- **개발/운영 머신**: Windows 10 미니PC (Ryzen 7 4700U 8코어, 8GB RAM)
- **네트워크**: VPN 24시간 연결 (한국 서버 경유)
- **24시간 무중단 운영** (nssm Windows 서비스 등록)
- **IDE**: VS Code + Claude Code CLI
- **GCP 대비 이점**: 8코어 CPU 여유로 백테스트/Shadow 병렬 실행, 디스크 여유로 장기 데이터 축적

## 핵심 목표
1. **수익성 강화** — Expectancy > 0, Profit Factor > 1.5
2. **안전성 강화** — MDD < 15%, 일일 DD < 4%
3. **자금 활용률 향상** — 50~60%
4. **자가 학습** — 경량 Darwinian + 주간 DeepSeek 리뷰
5. **24시간 무중단 자동매매**

## 기술 스택
- Python 3.11+ / aiohttp / FastAPI / SQLite (WAL)
- 빗썸 API (KRW 마켓, REST + 비동기)
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

```
bithumb_auto_v2/
├── CLAUDE.md                    ← 이 파일
├── docs/                        ← PRD 기반 설계 문서
├── tasks/                       ← 단계별 작업 명세
├── app/
│   ├── main.py                  ← 오케스트레이터 (~200줄)
│   ├── config.py                ← dataclass 기반 설정 로딩
│   ├── data_types.py            ← 공통 데이터 타입 (Candle, Position 등)
│   ├── journal.py               ← SQLite 거래 기록 (Trade Schema)
│   ├── notify.py                ← 텔레그램 알림
│   ├── storage.py               ← JSON 상태 영속화
│   └── api_server.py            ← FastAPI 대시보드 백엔드
├── strategy/
│   ├── rule_engine.py           ← 국면 5단계 + 5전략 + 점수제
│   ├── indicators.py            ← 기술적 지표 (RSI, MACD, ATR, ADX, EMA, BB, OBV, SuperTrend)
│   ├── pool_manager.py          ← 3풀 자금 관리
│   ├── position_manager.py      ← Pool 기반 2단계 사이징
│   ├── coin_profiler.py         ← 자동 Tier 분류
│   ├── promotion_manager.py     ← 승격/강등 관리
│   ├── darwin_engine.py         ← Shadow 20~30개 + 토너먼트
│   ├── review_engine.py         ← 일일/주간 리뷰
│   └── correlation_monitor.py   ← 코인 간 상관관계 모니터링 (NEW)
├── market/
│   ├── bithumb_api.py           ← 빗썸 REST API 클라이언트 (비동기)
│   ├── datafeed.py              ← 데이터 수집 (5M/15M/1H) + TTL 캐시
│   ├── normalizer.py            ← 가격/수량 정규화 + 최소주문금액
│   └── market_store.py          ← 장기 데이터 축적 (market_data.db) (NEW)
├── risk/
│   ├── risk_gate.py             ← 통합 리스크 게이트웨이
│   └── dd_limits.py             ← Drawdown Kill Switch
├── execution/
│   ├── order_manager.py         ← 주문 상태 머신 (FSM)
│   ├── reconciler.py            ← 거래소-로컬 동기화
│   ├── quarantine.py            ← 격리 시스템
│   └── partial_exit.py          ← 부분 청산
├── backtesting/
│   ├── backtest.py              ← 기본 백테스터
│   ├── walk_forward.py          ← Walk-Forward 검증 (NEW)
│   ├── monte_carlo.py           ← Monte Carlo 시뮬레이션 (NEW)
│   └── sensitivity.py           ← 파라미터 민감도 분석 (NEW)
├── bot_telegram/
│   └── handlers.py              ← 텔레그램 명령어 핸들러
├── configs/
│   └── config.yaml              ← 통합 설정
├── tests/
│   ├── test_rule_engine.py
│   ├── test_risk_gate.py
│   ├── test_pool_manager.py
│   ├── test_sizing.py
│   ├── test_promotion.py
│   └── ...
├── data/                        ← 런타임 데이터 (git 무시)
│   ├── app_state.json
│   ├── journal.db
│   ├── market_data.db           ← 장기 시장 데이터 축적 (5M/15M/1H + 호가창)
│   └── ...
├── requirements.txt
├── .env.example
├── .gitignore
└── run_bot.py                   ← 진입점
```

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
| `docs/BACKTEST_SPEC.md` | Walk-Forward + Monte Carlo + 민감도 분석 | 백테스트 작업 시 |
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

## Windows 24시간 운영 참고
- `nssm`(Non-Sucking Service Manager)으로 Windows 서비스 등록
- 또는 `pm2` (Node.js 기반 프로세스 매니저, Python 지원)
- 전원 옵션: 절전 모드 끄기, 자동 재시작 설정
- VPN 자동 재연결 설정 필수
- 봇 crash 시 자동 재시작 + 텔레그램 알림
