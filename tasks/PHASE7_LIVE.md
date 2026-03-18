# Phase 7: PAPER 28일 검증 + LIVE 승인

**기간**: 7~11주 | **우선순위**: CRITICAL
**참조**: `docs/LIVE_GATE.md`, `docs/TRADE_SCHEMA.md`

## 목표
28일 PAPER 운영으로 전체 시스템 검증 + LIVE 승인 게이트 통과.

## 작업 목록

### 7.1 Windows 24시간 운영 셋업
- `nssm`으로 봇을 Windows 서비스 등록
  ```powershell
  nssm install BithumbBot "C:\dev\bithumb_auto_v2\venv\Scripts\python.exe" "C:\dev\bithumb_auto_v2\run_bot.py"
  nssm set BithumbBot AppDirectory "C:\dev\bithumb_auto_v2"
  nssm set BithumbBot AppStdout "C:\dev\bithumb_auto_v2\data\bot_stdout.log"
  nssm set BithumbBot AppStderr "C:\dev\bithumb_auto_v2\data\bot_stderr.log"
  nssm start BithumbBot
  ```
- Windows 전원 옵션: 절전 모드 끄기
- VPN 자동 재연결 설정 확인
- 봇 crash 시 자동 재시작 (nssm 기본 동작)
- 텔레그램으로 시작/정지/재시작 알림

### 7.2 PAPER 28일 연속 운영
- Phase 0~6 모든 기능 통합 PAPER 모드
- 중단 없이 28일 연속 (중단 시 카운트 리셋)
- 일일 리뷰 + 주간 DeepSeek 정상 작동 확인
- VPN 끊김 시 자동 재연결 + 봇 복구 확인

### 7.3 자동 검증 항목 모니터링
매일 텔레그램으로 현황 전송:

| 항목 | 기준 |
|------|------|
| PAPER 일수 | ≥ 28일 연속 |
| 총 거래 수 | ≥ 120건 |
| 활성 전략 Expectancy | 모두 > 0 |
| PAPER MDD | < 8% |
| 일일 DD 최대 | < 3.5% |
| 가동률 | > 99% |
| 인증 오류 미해결 | 0건 |
| 슬리피지 모델 오차 | ±25% |
| Walk-Forward 검증 | 최근 4구간 중 3개+ 통과 |
| Monte Carlo 검증 | 하위 5% PnL > -2% |
| VPN 끊김 횟수 | 기록 (0이 이상적) |

### 7.4 미달 전략 처리
- Expectancy ≤ 0인 전략 → LIVE에서 비활성화
- Shadow 모드로 전환, 데이터 계속 축적
- **억지로 전략을 활성화하지 않음**

### 7.5 수동 체크리스트 실행
```
□ 1. 모든 주문 경로가 RiskGate를 경유하는지 코드 리뷰
□ 2. 텔레그램 Hard Stop / Soft Stop 알림 수신 테스트
□ 3. 401/403, 주문 실패, 미체결 재호가 시나리오 리허설
□ 4. 부분청산/트레일링/강등 동시 발생 시 우선순위 테스트
□ 5. Shadow/Live 성과 테이블 + journal 스키마 정합성
□ 6. Pool 간 자금 이동 (승격/강등) 정합성
□ 7. CRISIS 전량청산 → 복구 → 재개 전체 흐름 테스트
□ 8. 일일 리뷰 + 주간 DeepSeek 정상 작동 확인
□ 9. VPN 끊김 → 재연결 → 봇 자동 복구 테스트
□ 10. 미니PC 재부팅 후 봇 자동 시작 확인
```

### 7.6 LIVE 전환 절차
1. 자동 검증 9개 + 수동 체크리스트 10개 = **모두 통과**
2. 텔레그램 `/resume` 명령으로 LIVE 전환
3. **전환 후 첫 7일**: 모든 Pool risk_pct 50% 축소
4. 7일 후 `/restore_params` 명령으로 정상 파라미터 복원

### 7.7 LIVE 후 단계적 활성화
| 시점 | 활성화 |
|------|--------|
| LIVE 전환 | risk_pct 50% 축소 |
| LIVE + 7일 | 정상 risk_pct 복원 |
| LIVE + 30일 | Darwinian 챔피언 교체 활성화 가능 |
| LIVE + 60일 | 전체 안정화 확인 |

## 완료 기준
- [ ] Windows 서비스 등록 + 자동 시작/재시작 동작
- [ ] VPN 끊김 복구 테스트 통과
- [ ] PAPER 28일 연속 무장애 운영
- [ ] 자동 검증 + 수동 체크리스트 모두 통과
- [ ] LIVE 전환 완료
