# Phase 1: 인프라 구축 + 오케스트레이터 + RiskGate

**기간**: 1~2주 | **우선순위**: CRITICAL
**참조**: `docs/ARCHITECTURE.md`, `docs/RISK_SPEC.md`, `docs/TRADE_SCHEMA.md`

## 목표
빗썸 API 클라이언트부터 주문 FSM, 오케스트레이터까지 전체 인프라를 새로 구축.
이 단계 끝에 DRY/PAPER 모드에서 15분 루프가 돌아가야 함.

## 작업 목록 (순서대로)

### 1.1 market/bithumb_api.py — 빗썸 API 클라이언트
- aiohttp 기반 비동기 HTTP 클라이언트
- HMAC-SHA512 인증 구현 (API Key + Secret + nonce)
- `ClientTimeout(total=10)` 필수
- Public API: ticker, orderbook, candlestick
- Private API: balance, orders, order_detail, place, cancel, market_buy, market_sell
- Rate limiting: 초당 15회(Public), 10회(Private) 준수
- 에러 처리: HTTP 오류, 빗썸 에러코드, 타임아웃 각각 처리
- 테스트: `tests/test_bithumb_api.py` (Public API만 실제 호출)

### 1.2 market/datafeed.py — 데이터 수집
- 10개 코인의 **5M/15M/1H** 캔들 데이터 수집
- TTL 캐시 60초 (같은 사이클 내 중복 API 호출 방지)
- MarketSnapshot 구조: 현재가, 15M 캔들 200개, 1H 캔들 200개, 호가창
- 5M 캔들: 전략 D(스캘핑) 진입 타이밍용 + 장기 축적용
- 최초 실행 시 히스토리 로딩 (200봉 필요)

### 1.2.1 market/market_store.py — 장기 데이터 축적 (NEW)
- **파일**: `market/market_store.py`
- SQLite DB (`data/market_data.db`)에 시장 데이터 장기 저장
- 5M/15M/1H 캔들: 매 사이클마다 새 봉 저장
- 호가창 스냅샷: 매 사이클마다 저장 (bids/asks JSON + spread_pct)
- 정리 정책: 5M 6개월, 호가창 3개월, 15M/1H 영구
- 백테스트 및 슬리피지 모델 보정에 활용
- **지금 당장 전략에 안 써도 데이터는 Phase 1부터 축적 시작**

### 1.3 market/normalizer.py — 정규화
- 코인별 가격/수량 소수점 자리수 처리
- 최소 주문금액 5,000 KRW 검증
- tick_size 규칙 적용

### 1.4 strategy/indicators.py — 기술적 지표
모든 지표를 numpy 기반으로 구현:
- RSI (14봉, Wilder smoothing)
- MACD (12/26/9)
- ATR (14봉, Wilder smoothing)
- ADX, +DI, -DI (14봉, Wilder smoothing)
- SuperTrend (10봉, 3.0배)
- EMA (20/50/200)
- OBV (누적)
- Bollinger Bands (20봉, 2σ)
- Z-score (20봉)
- IndicatorPack dataclass로 전부 묶어서 반환
- 15M + 1H 이중 계산 지원
- 테스트: `tests/test_indicators.py` (알려진 값으로 검증)

### 1.5 execution/order_manager.py — 주문 FSM
- 상태: NEW → PLACED → PARTIAL → FILLED / CANCELED / FAILED / EXPIRED
- 주문 생성 → 빗썸 API 호출 → 30초 타임아웃 (1초 폴링)
- 부분 체결 처리
- 취소/재시도 로직 (최대 3회, 500ms × 2^n)
- 주문 티켓 관리 (메모리 1,000개, 터미널 100개)
- JSON 영속화 (`data/order_tickets.json`)
- PAPER 모드: 즉시 체결 시뮬레이션

### 1.6 execution/reconciler.py — 상태 동기화
- 매 사이클: 거래소 주문 상태 ↔ 로컬 상태 비교
- 미지의 주문 감지 → manual_intervention 플래그
- FAILED/CANCEL_REQUESTED 복구

### 1.7 execution/quarantine.py — 격리
- 종목 격리: 3회 실패 → 120초
- 전역 격리: 8회 실패 → 60초
- 인증 오류: 1회 → 600초
- 300초 비활성 후 카운트 리셋
- JSON 영속화 (`data/quarantine_state.json`)

### 1.8 risk/dd_limits.py — DD Kill Switch
- 일일 4%, 주간 8%, 월간 12%, 총 20%
- SELL은 차단하지 않음
- 매일 00:00 KST 일일 기준 리셋

### 1.9 risk/risk_gate.py — 통합 리스크 게이트
- P0~P10 우선순위 체계 (`docs/RISK_SPEC.md`)
- Hard Stop / Soft Stop 구분
- `check(signal) -> bool` — 모든 주문 필수 경유
- DD Kill Switch 호출
- 격리/쿨다운 확인
- Expected Edge 필터 (표본 미달 시 edge=0)
- 호가 잔량 필터 스텁 (Tier별 차등)
- 총 익스포저 90% 확인
- 연속 손실 5회 차단
- 텔레그램 알림 연동

### 1.10 app/journal.py — 거래 기록
- `docs/TRADE_SCHEMA.md`의 21필드 전체
- 테이블: signals, executions, risk_events, feedback, shadow_trades
- SQLite WAL 모드
- 90일 자동 정리

### 1.11 app/storage.py — 상태 영속화
- `data/app_state.json` 읽기/쓰기
- DD 상태, Pool 잔액, 포지션, 런타임 플래그
- 재시작 시 상태 복원

### 1.12 app/data_types.py — 공통 타입
```python
@dataclass
class Candle: timestamp, open, high, low, close, volume
@dataclass
class Position: symbol, entry_price, entry_time, size_krw, stop_loss, take_profit, strategy, pool, tier, ...
@dataclass
class Signal: symbol, direction, strategy, score, regime, tier, ...
@dataclass
class MarketSnapshot: symbol, current_price, candles_15m, candles_1h, orderbook
```

### 1.13 app/main.py — 오케스트레이터
```python
class TradingBot:
    async def run_cycle(self):
        snapshots = await self.market_analyzer.get_snapshots()
        signals = self.signal_generator.generate(snapshots)  # Phase 2에서 본격
        for signal in signals:
            if not self.risk_gate.check(signal):
                continue
            size = self.position_sizer.calculate(signal)  # Phase 3에서 Pool 기반
            if size > 0:
                await self.execution_engine.execute(signal, size)
        await self.manage_positions(snapshots)
        self.storage.save_state()
```
- 15분 주기 asyncio 스케줄러
- DRY/PAPER/LIVE 모드
- 사이클 전체 try-except + 텔레그램 알림

### 1.14 임시 전략 (Phase 2까지 사용)
- rule_engine.py 스텁: 단순 RSI BUY/SELL
- 루프 동작 확인용, Phase 2에서 교체

### 1.15 run_bot.py 진입점 + Windows 서비스 준비
- `nssm` 또는 `pm2`로 Windows 서비스 등록 가능한 구조

## 완료 기준
- [ ] 빗썸 API: 10개 코인 현재가 + 캔들 조회 성공
- [ ] 지표 계산: RSI, MACD, ATR, ADX 등 정상
- [ ] 주문 FSM: PAPER 모드 가상 체결 동작
- [ ] RiskGate: P0~P10 각 조건 차단/통과 테스트
- [ ] journal.db: 21필드 기록 + 조회 동작
- [ ] 15분 루프 정상 동작 (DRY → PAPER)
- [ ] `pytest tests/` 전체 통과
- [ ] 24시간 연속 DRY 운영 성공 (크래시 없음)
