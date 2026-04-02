#!/bin/bash
# 뮤테이션 테스트 — 핵심 모듈의 테스트 강도 검증
#
# Usage:
#   bash scripts/run_mutation_test.sh                              # impact_model (기본)
#   bash scripts/run_mutation_test.sh strategy/position_manager.py # 지정 모듈
#
# mutmut v2 사용. 결과에서 survived 뮤턴트 = 테스트 보강 필요.

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

TARGET="${1:-market/impact_model.py}"
MODULE_NAME=$(basename "$TARGET" .py)

echo "=== Mutation Test: $TARGET ==="
echo ""

# 캐시 정리
rm -rf .mutmut-cache

# 관련 테스트 파일 자동 탐지
TEST_FILE="tests/test_${MODULE_NAME}.py"
EXTRA_TESTS=""
if [ -f tests/test_property_based.py ]; then
    EXTRA_TESTS="tests/test_property_based.py"
fi

if [ ! -f "$TEST_FILE" ]; then
    echo "WARNING: $TEST_FILE not found."
    TEST_CMD="python -m pytest tests/ -x -q --tb=no --no-header"
else
    TEST_CMD="python -m pytest $TEST_FILE $EXTRA_TESTS -x -q --tb=no --no-header"
fi

# setup.cfg 동적 생성
cat > setup.cfg << EOF
[mutmut]
paths_to_mutate = $TARGET
tests_dir = tests/
runner = $TEST_CMD
EOF

echo "Runner: $TEST_CMD"
echo ""

# 기본 테스트 통과 확인
eval "$TEST_CMD" 2>/dev/null
echo "Baseline tests passed."
echo ""

# 뮤테이션 실행
mutmut run

echo ""
echo "=== Results ==="
mutmut results

echo ""
echo "Show survived mutant details:"
echo "  mutmut show <id>"
