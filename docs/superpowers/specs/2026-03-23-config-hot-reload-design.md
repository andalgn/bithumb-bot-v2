# Config 핫 리로드 설계

**작성일**: 2026-03-23

## 개요

봇 재시작 없이 `config.yaml`의 전략 파라미터 변경을 자동 반영한다.
매 사이클(5분)마다 파일 수정 시각을 확인하여, 변경 시 `strategy_params`만 리로드한다.

## 동기

Auto-Optimize, Auto-Research, Darwin 챔피언 등이 `config.yaml`을 수정해도
봇이 재시작하기 전까지 반영되지 않는 문제. 최대 21시간 지연 발생.

## 설계

### 동작 방식

1. `TradingBot.__init__`에서 config 파일의 초기 mtime 기록
2. `run_cycle()` 시작 시 `_check_config_reload()` 호출
3. mtime이 변경되었으면:
   - `load_config()` 호출
   - `self._rule_engine._strategy_params` 교체
   - mtime 갱신
   - 로그 기록 + `#시스템` 채널 알림
4. 파싱 실패 시 기존 설정 유지, 에러 로그만 남김

### 리로드 대상

| 항목 | 리로드 | 이유 |
|------|--------|------|
| `strategy_params` | ✅ | 전략 파라미터 — 핵심 리로드 대상 |
| 기존 포지션 SL/TP | ❌ | 진입 시점 조건 기반이므로 변경하면 위험 |
| sizing/risk_gate/dd_limits | ❌ | 런타임 상태와 충돌 위험 |
| pool_manager | ❌ | 할당 상태가 꼬일 수 있음 |

### 구현

```python
# app/main.py TradingBot 클래스에 추가

def __init__(self, config: AppConfig) -> None:
    ...
    self._config_path = PROJECT_ROOT / "configs" / "config.yaml"
    self._config_mtime: float = self._config_path.stat().st_mtime

def _check_config_reload(self) -> None:
    """config.yaml 변경 시 strategy_params를 리로드한다."""
    try:
        mtime = self._config_path.stat().st_mtime
    except OSError:
        return
    if mtime <= self._config_mtime:
        return
    try:
        new_config = load_config(self._config_path)
        self._rule_engine._strategy_params = new_config.strategy_params
        self._config_mtime = mtime
        logger.info("config 핫 리로드 완료: strategy_params 갱신")
    except Exception:
        logger.exception("config 리로드 실패 — 기존 설정 유지")
```

`run_cycle()` 시작 부분에서 호출:
```python
async def run_cycle(self) -> None:
    self._check_config_reload()
    ...
```

### 에러 처리

- config 파일 없음 → `OSError` → 무시, 기존 설정 유지
- YAML 파싱 실패 → `Exception` → 로그 남기고 기존 설정 유지
- 부분 업데이트 없음 — 파싱 성공 시에만 전체 교체

### 변경 파일

| 파일 | 변경 |
|------|------|
| `app/main.py` | `_config_path`, `_config_mtime` 속성 추가, `_check_config_reload()` 메서드 추가, `run_cycle()` 시작에 호출 추가 |
| `tests/test_config_reload.py` | **신규** — 핫 리로드 단위 테스트 |

### 테스트

- config.yaml mtime 변경 시 strategy_params 갱신 확인
- mtime 미변경 시 리로드 안 함 확인
- YAML 파싱 실패 시 기존 설정 유지 확인
- 기존 포지션 SL/TP 불변 확인
