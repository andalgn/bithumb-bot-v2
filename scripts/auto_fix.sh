#!/usr/bin/env bash
# auto_fix.sh — 전략 자동 분석 및 파라미터/코드 수정 파이프라인
#
# 사용법:
#   bash scripts/auto_fix.sh <STRATEGY> <REASON>
#
# 예시:
#   bash scripts/auto_fix.sh breakout win_rate_25%_below_30pct
#
# 요구사항:
#   - CLAUDE CLI: /home/bythejune/.local/bin/claude
#   - python3 scripts/send_discord_report.py (DISCORD_WEBHOOK_REPORT 또는 DISCORD_WEBHOOK_SYSTEM)
#   - sudo systemctl restart bithumb-bot (sudoers에 NOPASSWD 등록 필요)

set -euo pipefail

# 예기치 않은 종료 시 안전 복구: main 복귀 + 수정된 파일 롤백
trap 'cd "${PROJECT_ROOT}" && git checkout main 2>/dev/null || true; git checkout -- configs/config.yaml 2>/dev/null || true' EXIT

# ─── 상수 ──────────────────────────────────────────────────────────────────────
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${PROJECT_ROOT}/data"
SCRIPT_DIR="${PROJECT_ROOT}/scripts"
CLAUDE_BIN="/home/bythejune/.local/bin/claude"
PYTHON_BIN="${PROJECT_ROOT}/venv/bin/python3"  # httpx 등 의존성이 venv에 설치됨
export PATH="/home/bythejune/.local/bin:$PATH"  # claude CLI PATH

# ─── 인수 검증 ─────────────────────────────────────────────────────────────────
if [[ $# -lt 2 ]]; then
    echo "[auto_fix] ERROR: usage: $0 <STRATEGY> <REASON>" >&2
    exit 1
fi

STRATEGY="$1"
REASON="$2"

# 입력값 검증 — 알파벳/숫자/밑줄/하이픈만 허용 (경로 탐색 및 인젝션 방지)
if ! [[ "${STRATEGY}" =~ ^[a-zA-Z0-9_-]+$ ]]; then
    echo "[auto_fix] ERROR: STRATEGY에 허용되지 않는 문자 포함: '${STRATEGY}'" >&2
    exit 1
fi
if ! [[ "${REASON}" =~ ^[a-zA-Z0-9_%.-]+$ ]]; then
    echo "[auto_fix] ERROR: REASON에 허용되지 않는 문자 포함: '${REASON}'" >&2
    exit 1
fi

log() {
    echo "[auto_fix][$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

send_discord() {
    local msg="$1"
    echo "$msg" | "${PYTHON_BIN}" "${SCRIPT_DIR}/send_discord_report.py" || true
}

log "시작: STRATEGY=${STRATEGY} REASON=${REASON}"

# ─── 빈도 제한 (7일 이내 중복 실행 방지) ──────────────────────────────────────
TS_FILE="${DATA_DIR}/last_auto_fix_${STRATEGY}.ts"

if [[ -f "${TS_FILE}" ]]; then
    LAST_RUN=$(cat "${TS_FILE}" 2>/dev/null || echo "0")
    NOW=$(date +%s)
    DIFF=$(( NOW - ${LAST_RUN:-0} ))
    if (( DIFF < 604800 )); then  # 7일 = 604800초
        log "빈도 제한: 마지막 실행 후 ${DIFF}초 경과 (최소 604800초 필요). 종료."
        exit 0
    fi
fi

# ─── Phase 1: Opus 분석 (읽기 전용) ────────────────────────────────────────────
log "Phase 1: Opus 분석 시작"

OPUS_PROMPT="당신은 암호화폐 자동매매 봇의 전략 분석가입니다.

전략 '${STRATEGY}'이(가) 다음 이유로 성능 저하를 보이고 있습니다: ${REASON}

다음 단계로 분석하세요:
1. data/journal.db 파일의 최근 30일 거래 데이터를 읽어 strategy='${STRATEGY}' 거래만 분석하세요.
   (journal.db가 없으면 configs/config.yaml의 strategy_params 섹션만 분석하세요.)
2. configs/config.yaml 파일의 strategy_params.${STRATEGY} 섹션을 읽으세요.
3. strategy/rule_engine.py 파일을 읽어 ${STRATEGY} 전략 로직을 파악하세요.
4. 왜 승률이 30% 이하로 떨어졌는지 분석하세요.
5. 개선 방안을 JSON 형식으로만 출력하세요 (다른 텍스트 없이 순수 JSON만).

출력 형식 (반드시 이 형식 그대로):
{\"changes\": [{\"file\": \"configs/config.yaml\", \"type\": \"param\", \"description\": \"설명\"}], \"rationale\": \"분석 근거\"}

type은 반드시 'param' 또는 'code' 중 하나여야 합니다.
configs/config.yaml만 수정하는 경우 type='param', 코드 파일을 수정해야 하는 경우 type='code'.
보수적으로 판단하세요 — param 변경으로 해결 가능하면 type='param'을 사용하세요."

PLAN=$("${CLAUDE_BIN}" -p "${OPUS_PROMPT}" \
    --model opus \
    --allowedTools "Read,Grep,Glob" \
    --output-format json \
    2>/dev/null | "${PYTHON_BIN}" -c "
import sys, json
try:
    data = json.load(sys.stdin)
    # claude -p --output-format json 의 result 필드 추출
    if isinstance(data, dict) and 'result' in data:
        print(data['result'])
    else:
        print(json.dumps(data))
except Exception:
    pass
" || echo "")

log "Opus 분석 완료. PLAN 길이: ${#PLAN}"

# PLAN이 비어있거나 유효하지 않으면 종료
if [[ -z "${PLAN}" ]]; then
    log "PLAN이 비어있음. 자동 수정 건너뜀."
    send_discord "⚠️ auto-fix 분석 실패: ${STRATEGY} — Opus가 유효한 계획을 반환하지 않았습니다."
    exit 0
fi

# PLAN에서 JSON 파싱 가능한지 확인
PLAN_VALID=$(echo "${PLAN}" | "${PYTHON_BIN}" -c "
import sys, json
try:
    text = sys.stdin.read().strip()
    # JSON 블록만 추출 (```json ... ``` 또는 순수 JSON)
    import re
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        obj = json.loads(m.group())
        print(json.dumps(obj))
    else:
        print('')
except Exception:
    print('')
" || echo "")

if [[ -z "${PLAN_VALID}" ]]; then
    log "PLAN JSON 파싱 실패. 자동 수정 건너뜀."
    send_discord "⚠️ auto-fix 파싱 실패: ${STRATEGY} — 계획 JSON을 파싱할 수 없습니다."
    exit 0
fi

PLAN="${PLAN_VALID}"
log "PLAN 파싱 성공: ${PLAN:0:200}..."

# ─── code 변경 포함 여부 판단 ───────────────────────────────────────────────────
HAS_CODE=$(echo "${PLAN}" | "${PYTHON_BIN}" -c "
import sys, json
try:
    obj = json.loads(sys.stdin.read())
    changes = obj.get('changes', [])
    has_code = any(c.get('type') == 'code' for c in changes)
    print('yes' if has_code else 'no')
except Exception:
    print('no')
" || echo "no")

log "코드 변경 포함 여부: ${HAS_CODE}"

cd "${PROJECT_ROOT}"

# ─── 경로 A: param-only (configs/config.yaml만 수정) ────────────────────────────
if [[ "${HAS_CODE}" == "no" ]]; then
    log "경로 A: param-only 수정 시작"

    SONNET_PROMPT="다음 계획을 구현하라:

${PLAN}

규칙:
- configs/config.yaml 파일만 수정하라.
- strategy_params.${STRATEGY} 섹션의 파라미터만 변경하라.
- 다른 섹션이나 파일은 절대 수정하지 마라.
- 변경 사항이 합리적인지 확인하라 (극단적인 값 금지).
- 수정 완료 후 아무것도 출력하지 않아도 된다."

    "${CLAUDE_BIN}" -p "${SONNET_PROMPT}" \
        --model sonnet \
        --allowedTools "Read,Edit" \
        2>/dev/null || true

    log "Sonnet 수정 완료. pytest 실행 중..."

    # pytest 실행
    if "${PYTHON_BIN}" -m pytest tests/ -q --ignore=tests/test_bithumb_api.py 2>&1 | tail -5; then
        log "테스트 통과. 타임스탬프 기록 및 알림 전송."
        mkdir -p "${DATA_DIR}"
        date +%s > "${TS_FILE}"
        send_discord "⚙️ 자동 파라미터 조정: ${STRATEGY} — ${REASON}"
        sudo systemctl restart bithumb-bot 2>/dev/null || true
        log "봇 재시작 완료."
    else
        log "테스트 실패. configs/config.yaml 롤백."
        git checkout -- configs/config.yaml || true
        send_discord "❌ auto-fix 테스트 실패: ${STRATEGY} — ${REASON} (config.yaml 롤백됨)"
    fi

# ─── 경로 B: code 변경 포함 (브랜치 생성 + PR) ──────────────────────────────────
else
    log "경로 B: code 변경 포함. 브랜치 생성."

    BRANCH_NAME="auto-fix/${STRATEGY}-$(date +%Y%m%d)"

    # 기존 브랜치가 있으면 삭제 후 재생성
    git branch -D "${BRANCH_NAME}" 2>/dev/null || true
    git checkout -b "${BRANCH_NAME}"

    SONNET_PROMPT="다음 계획을 구현하라:

${PLAN}

규칙:
- 계획에 명시된 파일만 수정하라.
- 극단적이거나 위험한 변경은 하지 마라.
- 수정 후 반드시 pytest로 테스트하라."

    "${CLAUDE_BIN}" -p "${SONNET_PROMPT}" \
        --model sonnet \
        --allowedTools "Read,Edit,Bash(python3 -m pytest *)" \
        2>/dev/null || true

    log "Sonnet 수정 완료. pytest 최종 확인 중..."

    if "${PYTHON_BIN}" -m pytest tests/ -q --ignore=tests/test_bithumb_api.py 2>&1 | tail -5; then
        log "테스트 통과. 커밋 생성."
        git add -A
        git commit -m "fix: auto-optimize ${STRATEGY} — ${REASON}" || true
        mkdir -p "${DATA_DIR}"
        date +%s > "${TS_FILE}"
        send_discord "🔀 auto-fix 브랜치 생성됨 (인간 리뷰 필요): ${BRANCH_NAME} — ${STRATEGY} / ${REASON}"
        git checkout main
        log "브랜치 ${BRANCH_NAME} 생성 완료. main으로 복귀."
    else
        log "테스트 실패. 변경사항 롤백."
        git checkout -- . || true
        git checkout main
        git branch -D "${BRANCH_NAME}" 2>/dev/null || true
        send_discord "❌ auto-fix 테스트 실패 (코드 변경): ${STRATEGY} — ${REASON} (변경사항 롤백됨)"
    fi
fi

log "완료: STRATEGY=${STRATEGY} REASON=${REASON}"
