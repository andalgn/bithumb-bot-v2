# 진화 로직 완성 설계

**작성일**: 2026-03-23

## 개요

매매봇의 5개 피드백 루프를 모두 연결하여, 봇이 스스로 전략 파라미터를 진화시키는 시스템을 완성한다.

**현재 문제:**
- Darwin 챔피언: 선정되지만 실전에 적용 안 됨
- 일일 리뷰: 규칙 조정 로그만 남기고 적용 안 됨
- 주간 리뷰: DeepSeek 제안 검증만 하고 적용 안 됨
- 자율 연구: trend_follow만 실험 (실제 매매 전략 아님)
- config.yaml 변경 시 봇 재시작 필요 (최대 21시간 지연)

**목표:** 모든 피드백 루프를 연결하고, 안전장치를 갖춘 자기 진화 시스템 구축.

## 1. Config 핫 리로드 (구현 완료)

매 사이클(5분)마다 `config.yaml`의 mtime을 확인. 변경 시 `strategy_params`만 리로드.

- 리로드 대상: `strategy_params`만
- 기존 포지션 SL/TP: 불변
- 파싱 실패 시: 기존 설정 유지

## 2. Darwin 엔진 개선

### 2-1. ShadowParams 재설계

현재 `ShadowParams`는 `rsi_lower`, `rsi_upper`, `atr_mult`, `cutoff`, `tp_pct`, `sl_pct`로 구성되어 있으나, 실제 전략 파라미터(`sl_mult 2.0~10.0`, `tp_rr 1.0~4.0`)와 범위/의미가 불일치.

**변경:** `ShadowParams`를 전략 파라미터 구조에 맞게 재설계.

```python
@dataclass
class ShadowParams:
    """Shadow 파라미터 세트 — strategy_params와 동일 구조."""

    shadow_id: str = ""
    group: str = "conservative"
    # mean_reversion 파라미터
    mr_sl_mult: float = 7.0       # (2.0 ~ 10.0)
    mr_tp_rr: float = 1.5         # (1.0 ~ 4.0)
    # dca 파라미터
    dca_sl_pct: float = 0.05      # (0.02 ~ 0.08)
    dca_tp_pct: float = 0.03      # (0.01 ~ 0.05)
    # 진입 기준
    cutoff: float = 72.0          # (55 ~ 90)
```

변환 함수가 불필요해짐 — Shadow 파라미터가 곧 strategy_params.

```python
def champion_to_strategy_params(shadow: ShadowParams) -> dict:
    return {
        "mean_reversion": {
            "sl_mult": shadow.mr_sl_mult,
            "tp_rr": shadow.mr_tp_rr,
        },
        "dca": {
            "sl_pct": shadow.dca_sl_pct,
            "tp_pct": shadow.dca_tp_pct,
        },
    }
```

기존 `rsi_lower`, `rsi_upper`, `atr_mult`, `tp_pct`, `sl_pct` 필드는 제거. 변이 범위도 `PARAM_BOUNDS`와 동일하게 적용.

### 2-2. 30일 롤링 윈도우

현재 매주 토너먼트 후 Shadow 성과를 리셋하여 1주일 데이터만으로 평가.

**변경:** 리셋하지 않고 30일 롤링 윈도우로 평가.
- Shadow별 가상 거래 기록 보존 (최대 30일)
- 토너먼트 시 30일 이내 거래만으로 Composite Score 계산
- 30일 이전 거래는 자동 만료
- **영속화:** Shadow 거래 기록을 `data/shadow_trades.db`에 저장하여 봇 재시작 후에도 유지

### 2-3. 하위 멸종 + 상위 재생성

현재 하위 Shadow를 랜덤 변이.

**변경:**
- 토너먼트 결과 상위 70% → 생존
- 하위 30% → 멸종, 상위 생존자의 유전자를 기반으로 변이 재생성
- 생존자의 파라미터에 변이를 적용하여 새 Shadow 생성

### 2-4. 동적 변이율

현재 고정 변이율 (conservative 10%, moderate 20%, innovative 40%).

**변경:** 시장 국면에 따라 변이율 조정.

**국면 집계 방법:** 10개 코인의 `regime_states`에서 최빈값(mode)을 "시장 국면"으로 사용.

```python
from collections import Counter

def get_market_regime(regime_states: dict[str, RegimeState]) -> Regime:
    """10개 코인의 국면 최빈값을 시장 국면으로 반환한다."""
    counts = Counter(rs.current for rs in regime_states.values())
    return counts.most_common(1)[0][0]
```

국면별 변이율:
- 안정 시장 (RANGE, WEAK_UP, STRONG_UP): 변이율 10%
- 하락 시장 (WEAK_DOWN): 변이율 20%
- 급변 시장 (CRISIS): 변이율 40%

**의존성 주입:** `DarwinEngine.run_tournament(market_regime: Regime)`으로 국면 정보를 전달. `main.py`에서 호출 시 `get_market_regime()` 결과를 인자로 전달.

### 2-5. 강제 다양성

Shadow 간 파라미터 유사도를 **정규화 유클리드 거리**로 측정. 각 파라미터를 범위로 정규화(0~1)한 뒤 거리 계산. 거리 < 0.1인 Shadow 쌍이 있으면 한쪽을 강제 변이. 전체 Shadow가 하나의 전략으로 수렴하는 것 방지.

### 2-6. 챔피언 교체 조건 강화

- 최소 거래수: 10 → **30**
- 기존 Composite Score 비교 + shadow_discount 유지

## 3. 챔피언 → 실전 적용

### 3-1. 적용 검증 게이트

챔피언 교체 시 3단계 검증:

| 단계 | 조건 | 이유 |
|------|------|------|
| 1 | 거래수 ≥ 30 | 통계적 유의성 |
| 2 | PF > 현재 config PF | 개선 확인 |
| 3 | MDD ≤ 15% | 과도한 리스크 방지 |

3단계 모두 통과 시 config.yaml에 쓰기. 핫 리로드로 다음 사이클에 반영.

### 3-2. Auto-Optimize와의 관계

- Darwin 챔피언이 config에 쓰면 핫 리로드로 즉시 반영
- Auto-Optimize(일요일 02:00) 실행 시, 결과가 **현재 config PF보다 나을 때만** 덮어씀
- 현재 `_run_auto_optimize()`는 `auto_apply_min_pf` 기준만 사용 → **현재 config PF와 비교하는 로직으로 변경**
- 결과적으로 항상 더 나은 쪽이 유지됨

### 3-3. 알림

챔피언 교체 + 실전 적용 시 `#시스템` 채널로 알림.

## 4. 자율 연구 대상 확장

### 4-1. PARAM_BOUNDS 확장

```python
PARAM_BOUNDS = {
    "trend_follow": {
        "sl_mult": (1.0, 5.0),
        "tp_rr": (1.0, 5.0),
        "cutoff_full": (55, 90),
        "w_trend_align": (0, 45),
        "w_macd": (0, 40),
        "w_volume": (0, 35),
        "w_rsi_pullback": (0, 30),
        "w_supertrend": (0, 25),
    },
    "mean_reversion": {
        "sl_mult": (2.0, 10.0),
        "tp_rr": (1.0, 4.0),
    },
    "dca": {
        "sl_pct": (0.02, 0.08),
        "tp_pct": (0.01, 0.05),
    },
}
```

### 4-2. DeepSeek 프롬프트 개선

제공 데이터:
- 최근 30일 거래 성과 (전략별 PF, 승률, 거래수)
- 현재 시장 국면 분포 (WEAK_DOWN 80%, RANGE 20% 등)
- Darwin 챔피언 파라미터 vs 현재 config 비교
- 과거 실패 실험 이력 (experiment_history.db에서 조회)

### 4-3. 실험 대상 전략 선택

해당 주에 실제 매매에 사용된 전략만 실험. 사용하지 않는 전략은 건너뜀.

## 5. 리뷰 피드백 루프 연결

### 5-1. 일일 리뷰 → config 적용

현재 `_apply_rules()` 메서드는 조정을 로그에만 기록하고 config에 쓰지 않음.

**변경:** 새 메서드 `_apply_and_verify_rules()`를 추가.

```
일일 리뷰 규칙 발동 (예: 승률 < 40%)
    ↓
조정 사항 결정 (예: cutoff +5%)
    ↓
_apply_and_verify_rules():
    백테스트로 검증 (최근 7일 데이터)
    ↓
    PF 유지/개선 → _apply_optimized_params()로 config.yaml 적용
    PF 악화 → 적용 안 함, 로그만
```

기존 `_apply_rules()`의 로그/cooldown 로직은 유지. 새 메서드가 백테스트 검증 + config 쓰기를 담당.

### 5-2. 주간 리뷰 DeepSeek 제안 → 적용

현재 `_validate_suggestions()` 메서드는 구조 검증만 하고 적용하지 않음.

**변경:** 새 메서드 `_apply_verified_suggestions()`를 추가.

```
DeepSeek 제안 수신
    ↓
_validate_suggestions(): 기존 구조 검증 (유지)
    ↓
_apply_verified_suggestions():
    검증 통과한 제안으로 백테스트 실행 (최근 30일)
    ↓
    PF 개선 + MDD ≤ 15% → _apply_optimized_params()로 config.yaml 적용
    미달 → 적용 안 함
```

### 5-3. 공통 적용 기준

모든 자동 적용 경로에 동일한 게이트:

| 조건 | 기준 |
|------|------|
| PF | ≥ 현재 config PF |
| MDD | ≤ 15% |
| 거래수 | ≥ 30 (백테스트 기준) |

## 6. 안전장치

### 6-1. 자동 롤백

파라미터 변경 후 7일간 모니터링. 성과 악화 시 자동 복귀.

```json
// data/param_change_log.json
{
    "timestamp": 1774269163,
    "source": "darwin",
    "strategy": "mean_reversion",
    "old_params": {"sl_mult": 5.0, "tp_rr": 1.5},
    "new_params": {"sl_mult": 6.2, "tp_rr": 1.8},
    "backup_path": "configs/config.yaml.bak.20260323_030000",
    "monitoring_until": 1774873963,
    "baseline_pf": 1.15,
    "status": "monitoring"
}
```

롤백 조건:
- 변경 후 거래수 ≥ 10 && PF < baseline_pf × 0.9 → **자동 롤백**
- 변경 후 거래수 ≥ 20 && PF ≥ baseline_pf → **confirmed**
- 7일 경과 && 거래수 < 10 → **confirmed** (데이터 부족, 유지)

**롤백 체크 위치:** `app/main.py`에서 포지션 청산 후(거래 완료 시점) 체크. 거래 기반 판단이므로 시간 기반 daemon보다 main loop가 적합.

롤백 시 `#시스템` 채널 알림.

### 6-2. 점진적 적용

새 파라미터 적용 시 첫 20건은 포지션 사이즈 50%로 제한.

- 파라미터 변경 시 `pilot_remaining = 20`, `pilot_size_mult = 0.5` 설정
- `position_manager`가 사이징 시 multiplier 적용
- 20건 소진 후 자동으로 1.0 복귀
- 롤백 발생 시 즉시 pilot 해제
- **영속화:** `app/storage.py`의 `StateStorage`에 pilot 상태 저장하여 봇 재시작 후에도 유지

### 6-3. 실패 기억

실패한 파라미터 조합을 `data/experiment_history.db`에 기록. 기존 `data/research_log.tsv`와 통합하여 하나의 저장소로 관리.

```sql
CREATE TABLE experiments (
    id INTEGER PRIMARY KEY,
    timestamp INTEGER,
    source TEXT,
    strategy TEXT,
    params TEXT,
    pf REAL,
    mdd REAL,
    trades INTEGER,
    verdict TEXT
);
```

자율 연구/Darwin이 새 파라미터를 제안할 때:
- 과거 실패 기록 조회
- 유사한 방향의 변경이 3회 이상 실패했으면 건너뜀
- DeepSeek 프롬프트에 실패 이력 포함

## 7. 국면별 파라미터 분리

config.yaml에 국면별 오버라이드 추가:

```yaml
strategy_params:
  mean_reversion:
    sl_mult: 7.0      # 기본값
    tp_rr: 1.5
    regime_override:
      RANGE:
        sl_mult: 5.0
        tp_rr: 2.0
      WEAK_DOWN:
        sl_mult: 8.0
        tp_rr: 1.2
  dca:
    sl_pct: 0.05
    tp_pct: 0.03
    regime_override:
      WEAK_DOWN:
        sl_pct: 0.06
        tp_pct: 0.025
```

`rule_engine`이 시그널 생성 시 파라미터 병합 우선순위: **base < tier < regime** (regime이 최우선).

```python
# rule_engine.py generate_signals() 내 파라미터 병합
sp = self._strategy_params.get(strategy_name, {})
tier_sp = sp.get(f"tier{tier}", {})
regime_sp = sp.get("regime_override", {}).get(regime.value, {})
merged_sp = {**sp, **tier_sp, **regime_sp}  # regime이 최우선
```

Darwin/Auto-Optimize/Auto-Research도 국면별로 독립 진화.

## 변경 파일 목록

| 파일 | 변경 |
|------|------|
| `strategy/darwin_engine.py` | ShadowParams 재설계, 30일 롤링 윈도우(+영속화), 하위 멸종, 동적 변이율(market_regime 인자), 강제 다양성, champion_to_strategy_params() |
| `strategy/auto_researcher.py` | PARAM_BOUNDS 확장 (mean_reversion, dca), 프롬프트 개선, 실패 이력 조회 |
| `strategy/review_engine.py` | `_apply_and_verify_rules()` 신규 — 일일 리뷰 백테스트 검증 + config 적용. `_apply_verified_suggestions()` 신규 — 주간 리뷰 제안 백테스트 검증 + config 적용 |
| `strategy/rule_engine.py` | 국면별 regime_override 파라미터 병합 (base < tier < regime) |
| `strategy/position_manager.py` | pilot_size_mult 적용 |
| `backtesting/daemon.py` | auto_optimize: 현재 config PF와 비교 로직 추가 |
| `app/main.py` | Darwin 챔피언 적용 연결 (get_market_regime → run_tournament → champion_to_strategy_params → config 쓰기), 롤백 체크 (청산 후) |
| `app/config.py` | regime_override 파싱 지원 |
| `app/storage.py` | pilot 상태 영속화 |
| `configs/config.yaml` | regime_override 섹션 추가 |
| `data/param_change_log.json` | **신규** — 파라미터 변경 이력 + 롤백 모니터링 |
| `data/experiment_history.db` | **신규** — 실패 기억 DB (research_log.tsv 통합) |
| `data/shadow_trades.db` | **신규** — Shadow 거래 기록 영속화 |

## 피드백 루프 완성 후 데이터 흐름

```
매매 → 성과 측정 (journal)
  ↓
일일 리뷰 → _apply_and_verify_rules() → 백테스트 검증 → config 적용
주간 리뷰 → DeepSeek 제안 → _apply_verified_suggestions() → 백테스트 검증 → config 적용
Auto-Optimize → 그리드 탐색 → 백테스트 → config PF 비교 → config 적용
Auto-Research → DeepSeek 실험 → 백테스트 → config 적용
Darwin → 가상 매매 경쟁 → 챔피언 선정 → 3단계 검증 → config 적용
  ↓
핫 리로드 → rule_engine 파라미터 갱신 (regime_override 포함)
  ↓
다음 사이클 매매에 반영 (점진적 적용: 첫 20건 50% 사이즈)
  ↓
자동 롤백 모니터링 (7일, 청산 시 체크)
  ↓
성과 악화 → 롤백 / 성과 유지 → confirmed
  ↓
실패 기억 DB에 기록 → 향후 동일 방향 변경 방지
```
