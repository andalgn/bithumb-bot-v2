# Phase 3: 3풀 구조 + Pool 사이징 + 승격

**기간**: 3~4주 | **우선순위**: HIGH
**참조**: `docs/SIZING_SPEC.md`, `docs/PROMOTION_SPEC.md`

## 목표
3풀 자금 배분 + Pool 기반 2단계 사이징 + 승격/강등 시스템 구현.

## 작업 목록

### 3.1 strategy/pool_manager.py (새로 작성)
- Core(60%) / Active(30%) / Reserve(10%) 관리
- Pool 잔액 실시간 추적 (포지션 진입/청산/승격/강등 시 업데이트)
- Pool 간 자금 이동 인터페이스
- storage.py에 Pool 상태 영속화
- 메서드:
  - `get_available(pool) -> float` — 가용 잔액
  - `allocate(pool, amount) -> bool` — 자금 할당
  - `release(pool, amount)` — 자금 반환
  - `transfer(from_pool, to_pool, amount)` — 승격/강등 시

### 3.2 strategy/position_manager.py (새로 작성)
**Pool 기반 2단계 사이징** (SIZING_SPEC.md 그대로):

```python
# Active Pool
base = active_balance * 0.03
opportunity = base * tier_mult * score_mult * vol_target_mult
defense = clamp(regime_mult * dd_mult * loss_streak_mult, 0.3, 1.0)
final = min(opportunity * defense, active_balance * 0.25)

# 상관관계 축소 (correlation_monitor 연동)
corr = correlation_monitor.check(symbol, active_positions)
if corr == "SKIP": final = 0       # 상관 > 0.85
elif corr == "HALF": final *= 0.5  # 상관 0.70~0.85

if final < 5000: final = 0

# Core Pool
base = core_balance * 0.10
opportunity = base * tier_mult * vol_target_mult
defense = clamp(regime_mult * dd_mult * loss_streak_mult, 0.3, 1.0)
final = min(opportunity * defense, core_balance * 0.25)
if final < 10000: final = 0
```

- 변동성 타기팅: `vol_target_mult = target_vol / realized_20d_vol` clamp [0.5, 1.5]
- defense_mult 최소 0.3 보장
- 연속 5패 차단은 RiskGate에서 처리 (여기서는 2연패 ×0.7, 3연패 ×0.5까지)

### 3.3 strategy/promotion_manager.py (새로 작성)
**승격 (Active → Core):**
- 조건: +1.2% AND 2봉 유지 + 1H EMA20위 + ADX>20 + STRONG/WEAK_UP + Tier 1/2
- 실행: Pool 이관 + 손절선 확대 (1H ATR×2.5, 단 Active 손절의 2배 이내)

**보호기간:**
- 2봉(2시간) — 손절선 이탈 시 즉시 전량 청산

**Core 정상 운영:**
- 청산: 1H 캔들 기준만 (1H 양봉 지속 시 보유)
- 부분 청산: +3%→30%, +6%→30%, 나머지 트레일링

**강등 (Core → Active):**
- 1H EMA20 하향 이탈 OR 국면 악화 → Active 복귀
- 재승격 전 6봉 검증

**추가매수:**
- 조건: 4봉 경과 + 재평가 55점+ + 수익+2% + VWAP위 + Pool 25% 미만
- 포지션당 1회 제한
- 금액: Tier 1 Core의 15%, Tier 2 Core의 8%

### 3.4 main.py 통합
- `run_cycle()`에 PoolManager, PositionManager, PromotionManager 연결
- 매 사이클: 신호→사이징→실행→승격확인→강등확인

### 3.5 테스트
- `tests/test_pool_manager.py` — 할당/반환/이관 정합성
- `tests/test_position_manager.py` — 시나리오별 사이징 (SIZING_SPEC.md 예시)
- `tests/test_promotion.py` — 승격→보호→정상→강등→재승격 전체 흐름

## 완료 기준
- [ ] 3풀 배분 + Pool 잔액 추적 동작
- [ ] Pool 기반 사이징 시나리오 테스트 통과 (SIZING_SPEC.md 5절 예시)
- [ ] 승격→보호→Core정상→강등 전체 흐름 동작
- [ ] 추가매수 5대 조건 + VWAP 검증
- [ ] PAPER 7일, 자금 활용률 30%+ 확인
