# DEVLOG

## 2026-03-18

### Phase 0: 환경 셋업 + 프로젝트 생성
- Python 3.14.3 환경 확인
- 가상환경 생성 + 의존성 설치 완료 (requirements.txt)
- 프로젝트 디렉토리 구조 생성 (app/, strategy/, market/, risk/, execution/, bot_telegram/, configs/, tests/, data/, backtesting/)
- 각 패키지 `__init__.py` 생성
- `.env.example`, `.gitignore` 생성
- `configs/config.yaml` — PARAMS.md 기반 전체 파라미터 설정
- `app/config.py` — dataclass 기반 설정 로딩 (config.yaml + .env)
- `app/notify.py` — aiohttp 비동기 텔레그램 알림
- `app/data_types.py` — 공통 데이터 타입 (Candle, Ticker, Regime, Tier 등)
- `run_bot.py` — 진입점 + 연결 테스트
- 빗썸 Public API 연결 성공: BTC/KRW 106,561,000원 (응답 1750ms)
- `ruff check .` — 오류 없음
- git init 완료 (커밋은 git user 설정 후 진행 필요)

## 2026-03-19

### Phase 1: 인프라 구축 + 오케스트레이터 + RiskGate
- `app/data_types.py` 확장 — Position, Signal, MarketSnapshot, OrderTicket, Orderbook 등 추가
- `market/bithumb_api.py` — HMAC-SHA512 인증 + 비동기 aiohttp + Rate Limiting
- `market/normalizer.py` — 코인별 tick_size, 수량 소수점, 최소주문금액 5,000원 검증
- `market/datafeed.py` — 10개 코인 5M/15M/1H 캔들 수집 + TTL 캐시 60초
- `market/market_store.py` — SQLite 장기 데이터 축적 (5M 6개월, 15M/1H 영구, 호가창 3개월)
- `strategy/indicators.py` — numpy 기반 9개 지표 (RSI, MACD, ATR, ADX, SuperTrend, EMA, OBV, BB, Z-score)
- `execution/order_manager.py` — 주문 FSM (NEW→PLACED→PARTIAL→FILLED/CANCELED/FAILED/EXPIRED), PAPER 즉시 체결
- `execution/reconciler.py` — 거래소↔로컬 상태 동기화
- `execution/quarantine.py` — 종목(3회→120초)/전역(8회→60초)/인증(1회→600초) 격리 + JSON 영속화
- `risk/dd_limits.py` — DD Kill Switch (일4%/주8%/월12%/총20%), SELL 비차단, 00:00 KST 리셋
- `risk/risk_gate.py` — P0~P10 통합 리스크 게이트 (DD, 익스포저, 격리, 연속손실, 쿨다운)
- `app/journal.py` — SQLite WAL, 21필드 Trade Schema, 5테이블, 90일 자동 정리
- `app/storage.py` — app_state.json 상태 영속화 + 재시작 복원
- `strategy/rule_engine.py` — 임시 RSI 스텁 (Phase 2에서 교체)
- `app/main.py` — 오케스트레이터 15분 루프 (DRY/PAPER/LIVE)
- `run_bot.py` — CLI 진입점 + Windows 서비스 준비
- 테스트 8개 파일, 64개 테스트 전체 통과
- `ruff check .` 오류 없음
- DRY 모드 사이클 1회 실행 성공: 10/10 코인 수집, 7건 신호 → 주문 시뮬레이션 체결 (2.3초)

### Phase 2: 전략 코어 구현
- `strategy/coin_profiler.py` — ATR% 기반 Tier 1/2/3 자동 분류 (매일 갱신)
- `strategy/rule_engine.py` — 전면 재작성:
  - 5단계 국면 분류 (CRISIS/STRONG_UP/WEAK_UP/WEAK_DOWN/RANGE)
  - 히스테리시스 (3봉 확인 + 6봉 재전환 금지 + CRISIS 즉시/6봉 해제)
  - 보조 플래그 (RANGE_VOLATILE, DOWN_ACCEL)
  - 전략 A/B/C/D 독립 점수표 (각 0~100점)
  - 3그룹 컷오프 (Full/Probe/HOLD)
  - Layer 1 환경 필터 (거래량, 스프레드, 시간대)
  - 국면별 전략 허용 매핑 + 보조 플래그 제한
- `risk/risk_gate.py` 확장:
  - Expected Edge 필터 (expectancy - fee - slippage - penalty)
  - 호가 잔량 필터 (Tier별 best 3 levels × 배수)
  - 스프레드 한도 확인
- `strategy/correlation_monitor.py` — 20일 롤링 상관관계 매트릭스
  - 진입 전 필터: >0.85 스킵, 0.70~0.85 50% 축소
- `app/main.py` 통합: coin_profiler + correlation_monitor + 전략 엔진 연결
- 테스트 11개 파일, 93개 테스트 전체 통과
- `ruff check .` 오류 없음
- DRY 모드 Phase 2 실행 성공: Tier 분류 + 국면 판정 + 전략 점수 → TAO mean_reversion 72점 체결 (2.6초)

### Phase 3: 3풀 구조 + Pool 사이징 + 승격
- `strategy/pool_manager.py` — Core(60%)/Active(30%)/Reserve(10%) 3풀 관리
  - 잔액 추적, 할당/반환/이관 인터페이스, 동시 포지션 제한
  - 자산 변동 시 미할당분 비율 재배분, 상태 영속화
- `strategy/position_manager.py` — Pool 기반 2단계 사이징
  - 1단계: base × tier_mult × score_mult × vol_target_mult
  - 2단계: regime_mult × dd_mult × loss_streak_mult, clamp [0.3, 1.0]
  - 변동성 타기팅, 상관관계 축소, 25% 상한 가드레일
  - DCA 고정 사이징 (Core × 4%), 추가매수 사이징
- `strategy/promotion_manager.py` — 승격/강등 시스템
  - Active→Core 승격: +1.2% AND 2봉 유지 + EMA20위 + ADX>20
  - 보호기간 2봉: 손절 이탈 시 즉시 청산
  - Core 정상: 1H 기준, 부분청산 (+3%→30%, +6%→30%, 나머지 트레일링)
  - 강등: EMA20 이탈/국면 악화 → Active 복귀, 6봉 재승격 검증
  - 추가매수: 5대 조건 + VWAP 위 + Pool 25% 미만 + 1회 제한
- `app/main.py` 통합: Pool/Position/Promotion 연결
  - 사이클 흐름: 시장수집→프로파일링→동기화→승격/강등→신호→사이징→주문
  - Pool 상태 영속화, 자금 활용률 로깅
- 테스트 14개 파일, 130개 테스트 전체 통과
- `ruff check .` 오류 없음
- DRY 모드 Phase 3 실행 성공: Pool 초기화 + 사이징 적용 + 쿨다운 필터 (2.8초)

### Phase 4: 부분청산 + 트레일링 + 체결 정책
- `execution/partial_exit.py` - 부분청산 + 트레일링 스톱 통합 모듈
  - 전략 A: +3%→30%, +6%→30%, 나머지 트레일링
  - 전략 B: BB 중간선→50%, 나머지 트레일링
  - 전략 C: 트레일링 ATR x3.0 (부분청산 없음)
  - 전략 D: 고정 TP 1.5% + SL 0.8% + 시간 제한 2시간
  - 트레일링: +3% 활성화, 콜백 1%, ATR 기반 (Tier별 배수)
  - 청산 우선순위: 손절 > 트레일링 > 부분청산 > TP
  - 수수료 누적 추적 + 트렌치별 기록
- `execution/order_manager.py` 체결 정책 강화
  - 지정가→시장가 전환 (30초 타임아웃 후)
  - 가격 이탈 체크 (±0.3% 초과 시 주문 포기)
  - 부분체결 처리 (잔량 x 현재가 < 5,000원이면 취소)
- `app/main.py` 포지션 관리 통합
  - 매 사이클 부분청산/트레일링/시간제한 평가
  - _close_position: PnL 계산, Pool 반환, Journal 기록
- 테스트 15개 파일, 146개 테스트 전체 통과
- `ruff check .` 오류 없음
- DRY 모드 Phase 4 실행 성공 (2.7초)

### Phase 5: Darwinian + 고급 백테스트 검증
- `strategy/darwin_engine.py` - Shadow 20~30개 병렬 추적
  - 3그룹 Population (±10% 미세 / ±20% 탐색 / 혁신적)
  - 매 사이클 "진입했을까?" 기록 + 가상 PnL (체결비용 보정)
  - 주간 토너먼트: Composite Score 랭킹, 상위 5개 생존
  - 챔피언 교체: 월 1회, 3윈도우 검증, 14일 쿨다운
  - 돌연변이 범위 제한 (RSI ±3, ATR ±0.3 등)
- `backtesting/backtest.py` - 기본 백테스터 (수수료+슬리피지 반영, Sharpe/MDD/PF)
- `backtesting/walk_forward.py` - Walk-Forward (30일 4구간, 4/4=견고, 과적합 감지)
- `backtesting/monte_carlo.py` - Monte Carlo 1,000회 (P5/P50/P95, 최악 MDD)
- `backtesting/sensitivity.py` - 민감도 분석 (±10% 5단계, CV 판정)
- `backtesting/daemon.py` - 검증 데몬 (별도 태스크)
  - Walk-Forward: 매일 00:30 KST
  - Monte Carlo + 민감도: 매주 일요일 01:00~01:30 KST
  - 주간 통합 검증 리포트 텔레그램 전송
- `app/main.py` 통합: Darwin 매 사이클 기록, BacktestDaemon 백그라운드
- 테스트 19개 파일, 169개 테스트 전체 통과
- `ruff check .` 오류 없음
- DRY 모드 Phase 5 실행 성공: Darwin 20 shadows 초기화 + 정상 (2.7초)

### Phase 6: ReviewEngine + DeepSeek 주간 분석
- `strategy/review_engine.py` - 일일/주간/월간 리뷰 엔진
  - 일일 리뷰 (00:00 KST, LLM 없음):
    - SQL 집계: 전략/국면/종목/Tier별 승률 + Expectancy
    - 규칙 기반 조정: 승률 < 40% 시 임계값 +5%, 종목 3연속 손절 시 24h 쿨다운
    - 텔레그램 일일 요약 (거래 건수, PnL, 활용률, 승격, 조정)
  - 주간 DeepSeek 분석 (일요일 00:00):
    - 데이터 패키지 자동 생성 (전략통계 + Shadow + WF + MC + 민감도 + 상관관계)
    - httpx로 DeepSeek-chat API 호출, JSON 파싱
    - 제안별 백테스트 검증 -> 통과분만 적용
    - 텔레그램 주간 리포트
  - 월간 심층 (월 1회): deepseek-reasoner 호출 (전략 재평가)
- `app/main.py` 통합: 매 사이클 KST 00:00~00:15에 일일/주간 리뷰 트리거
- 테스트 20개 파일, 181개 테스트 전체 통과
- `ruff check .` 오류 없음
- DRY 모드 Phase 6 실행 성공 (2.7초)
