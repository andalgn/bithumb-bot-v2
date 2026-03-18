# Pool 기반 2단계 사이징 명세

## 1. 3풀 자금 구조

| Pool | 비율 | 용도 | risk_pct | 동시 포지션 | 하한 |
|------|------|------|---------|------------|------|
| Core | 60% | 승격된 중장기 추세 + DCA | 잔액 × 10% | 최대 3건 + DCA 별도 | 10,000원 |
| Active | 30% | 15M 단기 전략 | 잔액 × 3% | 최대 5건 | 5,000원 |
| Reserve | 10% | CRISIS 전용 현금 | 잔액 × 5% | Tier 1만 | 5,000원 |

**핵심**: 총자산 기준이 아닌 **Pool 잔액 기준**으로 사이징.

## 2. Active Pool 사이징

```python
# ─── 1단계: 기회 사이즈 ───
base = active_balance * 0.03  # Active 잔액의 3%

opportunity_size = base * tier_mult * score_mult * vol_target_mult

# tier_mult:  T1=1.5, T2=1.0, T3=0.6
# score_mult: Probe=0.4, Full=1.0, High(+10)=1.15, High(+20)=1.25
# vol_target_mult: target_vol / realized_20d_vol, clamp [0.5, 1.5]

# ─── 2단계: 방어 조정 ───
defense = regime_mult * dd_mult * loss_streak_mult
defense = max(0.3, min(1.0, defense))  # clamp [0.3, 1.0]

# regime_mult: STRONG=1.5, WEAK_UP=1.0, RANGE=1.0, WEAK_DOWN=0.6, CRISIS=0
# dd_mult: 주간DD>4%=0.7, 주간DD>6%=0.5, else=1.0
# loss_streak_mult: 2연패=0.7, 3연패=0.5, else=1.0

# ─── 최종 ───
final_size = opportunity_size * defense

# 가드레일
final_size = min(final_size, active_balance * 0.25)  # Pool의 25% 상한
if final_size < 5000:
    final_size = 0  # 주문 안 함
```

## 3. Core Pool 사이징

```python
base = core_balance * 0.10  # Core 잔액의 10%

opportunity_size = base * tier_mult * vol_target_mult
# tier_mult: T1=1.5, T2=1.0 (Tier 3은 승격 불가이므로 없음)
# vol_target_mult: clamp [0.5, 1.5]

defense = regime_mult * dd_mult * loss_streak_mult
defense = max(0.3, min(1.0, defense))

final_size = opportunity_size * defense
final_size = min(final_size, core_balance * 0.25)  # Pool의 25% 상한
if final_size < 10000:
    final_size = 0

# DCA 별도: core_balance * 0.04 (고정, 방어 조정 미적용)
```

## 4. Reserve Pool 사이징

```python
# CRISIS에서만 사용, Tier 1 한정
reserve_size = reserve_balance * 0.05  # 고정
```

## 5. 시나리오별 계산 예시 (총자산 100만원)

```
Pool 배분: Core 600,000 / Active 300,000 / Reserve 100,000

── Active: BTC(T1), STRONG_UP, 점수 80점(Full), 정상 ──
base = 300,000 × 0.03 = 9,000
opportunity = 9,000 × 1.5(T1) × 1.0(Full) × 1.1(vol) = 14,850
defense = 1.5(STRONG) × 1.0 × 1.0 = 1.5 → clamp → 1.0
final = 14,850 × 1.0 = 14,850원 ✓

── Active: ETH(T1), WEAK_UP, 점수 62점(Probe), 정상 ──
base = 9,000
opportunity = 9,000 × 1.5 × 0.4(Probe) × 1.0 = 5,400
defense = 1.0 × 1.0 × 1.0 = 1.0
final = 5,400원 ✓

── Active: SOL(T2), WEAK_UP, 점수 76점(Full), 2연패 ──
base = 9,000
opportunity = 9,000 × 1.0 × 1.0 × 1.0 = 9,000
defense = 1.0 × 1.0 × 0.7 = 0.7
final = 9,000 × 0.7 = 6,300원 ✓

── Core: BTC 승격 포지션 ──
base = 600,000 × 0.10 = 60,000
opportunity = 60,000 × 1.5(T1) × 1.0 = 90,000
defense = 1.0
final = 90,000원 ✓
추가매수: 60,000 × 1.5 × 0.5 = 45,000원 → 총 135,000원 (Core의 22.5%)
```

## 6. 역할 분리 원칙

```
"거래할까 말까?" → RiskGate (DD Kill, 격리, 연속5패 차단)
"한다면 얼마나?" → Pool Sizer (기회 평가 × 방어 조정)
"이 코인이 겹치나?" → Correlation Monitor (상관관계 필터)
```

연속 5패 차단은 사이징(×0)이 아닌 RiskGate Hard/Soft Stop에서 처리.
사이징에서는 2연패(×0.7), 3연패(×0.5)까지만 적용.
defense_mult 최소 0.3 보장 — 0에 수렴하는 것은 RiskGate 역할.

**상관관계 축소 (사이징 마지막 단계에서 적용):**
- 보유 중 코인과 상관계수 > 0.85 → 진입 스킵 (size=0)
- 상관계수 0.70~0.85 → size × 0.5
- 상관계수 < 0.70 → 정상

## 7. 자금 활용률 추정

| 시나리오 | Core 사용 | Active 사용 | 총 활용률 |
|---------|----------|------------|----------|
| 초기 (1주차) | ~10% | ~10% | ~20% |
| 안정화 (2~3주) | ~35% | ~8% | ~43% |
| 상승장 | ~50% | ~12% | ~62% |
| 하락장 | DCA만 ~10% | ~3% | ~13% + Reserve |
