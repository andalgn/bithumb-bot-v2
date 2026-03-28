docs/DASHBOARD_BLUEPRINT.md 파일을 읽고, 이 기획서에 나온 트레이딩 봇 대시보드를 Stitch MCP로 디자인해줘.

## 프로젝트 개요
빗썸 KRW 마켓 암호화폐 24시간 자동매매 봇의 전문 모니터링 대시보드.
상업 제품 수준의 완성도로 디자인해야 한다.

## 디자인 시스템
- 다크 모드 기본 (배경 #0f1117, 카드 #1a1d29)
- 수익: #22c55e (green), 손실: #ef4444 (red), 경고: #f59e0b, 액센트: #3b82f6
- 좌측 사이드바 네비게이션 + 상단 KPI 바 + 메인 콘텐츠 영역
- 데스크탑 1920×1080 기준, 정보 밀도 높은 전문 트레이딩 터미널 스타일
- 폰트: Inter 또는 시스템 sans-serif, 숫자는 tabular-nums (고정폭)

## 6개 페이지를 각각 디자인해줘

### Page 1: Overview (메인 대시보드)
- 상단 KPI 카드 행: 총 자산(₩), 일일 P&L(₩/%), 주간 P&L, 승률(%), Profit Factor, MDD(%)
- 좌측: Equity Curve 라인 차트 (30일/90일/전체 토글)
- 우측: Pool Allocation 도넛 차트 (ACTIVE 50% / CORE 40% / RESERVE 10%)
- 중앙: Active Positions 테이블 (Symbol, Strategy, Pool, Entry₩, Current₩, P&L%, Duration, SL/TP)
- 하단: Recent Activity Feed (시간순 이벤트 — 진입, 청산, 리스크 거부 등)

### Page 2: Trading (거래 상세)
- 좌측 상단: 캔들스틱 차트 (TradingView 스타일, EMA 오버레이, 진입/청산 마커, RSI 서브차트)
- 우측 상단: Signal Log (시그널 이력 — score, regime, accepted/rejected, reject_reason)
- 중앙: Trade History 테이블 (21개 필드, 행 클릭 시 상세 패널 확장)
  - 확장 패널: 진입 시그널 score breakdown, 사이징 계산 과정, 자가반성(reflection + lesson)
- 하단: Execution Quality 메트릭 (평균 슬리피지, 체결 성공률, 평균 체결 시간)

### Page 3: Strategy & Intelligence (전략 및 지표)
- 상단: Market Regime 표시기 (5단계 가로 바: STRONG_UP/WEAK_UP/RANGE/WEAK_DOWN/CRISIS, 현재 국면 하이라이트, 전환 이력 타임라인)
- 좌측: Strategy Performance 비교 테이블 (전략별 Trades/WR%/PF/Expectancy/Sharpe)
- 우측: Score Breakdown 레이더 차트 (선택 전략의 5개 가중치 항목)
- 좌측 하단: Momentum Heatmap (코인×지표 매트릭스, 색상 강도로 순위 표시)
- 우측 하단: Coin Profiler (티어 분류 카드 — TIER1/2/3, ATR%, 파라미터 차이)
- 하단: Decision Flow 다이어그램 (시그널생성→환경필터→리스크게이트→사이징→주문, 각 단계 통과율)

### Page 4: Risk & Capital (리스크 및 자금)
- 상단: Drawdown Gauge 4개 (원형/반원 게이지 — Daily 3.2%/4%, Weekly/Monthly/Total)
- 좌측: Risk Gate Status (10개 게이트 항목별 상태 표시등 — OK/WARNING/BLOCKED)
- 우측: Pool Distribution 3개 카드 (ACTIVE/CORE/RESERVE — 잔고, 사용중, 포지션 수, 가용)
- 중앙: Risk Event Timeline (시간순 리스크 이벤트 — priority, 설명)
- 하단: Correlation Matrix 히트맵 (코인 간 상관계수, 동시 진입 경고)

### Page 5: Evolution & Research (진화 및 자율연구)
- 상단: Darwin Engine 상태 바 (Population, Generation, Champion ID, 다음 승격까지 남은 일수)
- 좌측: Shadow Population 산점도 (x=PF, y=MDD, size=CompositeScore, color=group)
- 우측: Composite Score 레이더 차트 (8개 축: expectancy, PF, MDD, sharpe, sortino, calmar, consec_loss, exec_quality)
- 중앙: Shadow Performance 테이블 (ID, Group, Trades, WR%, PF, MDD%, Score, LIVE와 비교)
- 실험 타임라인 (●KEEP / ○REVERT / ◆MONITORING 점 그래프)
- Parameter Change History 테이블
- Backtest Schedule 카드 (WF/MC/Sensitivity/Optimize/Research — 다음 실행 시각, 마지막 결과)
- Feedback Loop: Top Failure Patterns 바 차트 + 최근 자가반성 교훈

### Page 6: System (시스템 건강)
- 상단: Health Score 큰 게이지 (0-100, HEALTHY/DEGRADED/CRITICAL 색상)
- 좌측: 8개 Health Check 항목 (heartbeat, event_loop, api, data_freshness, reconciliation, system_resources, trading_metrics, discord — 가중치와 점수)
- 우측: Health Score History 24시간 라인 차트
- System Resources 바 (CPU%, Memory, Disk, Uptime)
- Service Status (bithumb-bot, xray VPN, dashboard — 상태 표시등)
- Configuration Overview (run_mode, cycle, coins, sizing, risk, darwin 주요 설정)
- 하단: Live Log Stream (실시간 로그 스크롤, 레벨별 색상)

## 디자인 품질 요구사항
- Bloomberg Terminal, TradingView, Binance Pro 수준의 전문성
- 일관된 그리드 시스템, 카드 간격, 타이포그래피
- 의미있는 데이터 시각화 (숫자만 나열하지 말고 차트/게이지/히트맵 활용)
- 샘플 데이터를 넣어서 실제 운영 중인 것처럼 보이게
