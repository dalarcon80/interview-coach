#!/bin/bash
# Interview Coach - Package Verification Script
# Single command to verify the entire package is healthy
#
# Usage:
#   bash scripts/verify_package.sh
#
# This runs:
#   1. Test collection check
#   2. Unit tests
#   3. Smoke test (collection + key integration tests)
#   4. Lint check

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

cd "$(dirname "$0")/.."

# Detect Python executable (python3 preferred, fallback to python)
# Check for virtual environment in python-core/venv first
if [ -f "python-core/venv/bin/python3" ]; then
    PYTHON_CMD="python-core/venv/bin/python3"
elif [ -f "python-core/venv/bin/python" ]; then
    PYTHON_CMD="python-core/venv/bin/python"
elif command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
else
    echo -e "${RED}ERROR: Python not found. Please install Python 3.11+${NC}"
    exit 1
fi

echo -e "${BLUE}=========================================="
echo "Interview Coach - Package Verification"
echo -e "==========================================${NC}"
echo ""

# Track overall status
ALL_PASSED=0

# 1. Test Collection
echo -e "${BLUE}▶ 1. Test Collection${NC}"
if $PYTHON_CMD -m pytest tests --collect-only -q >/dev/null 2>&1; then
    COUNT=$($PYTHON_CMD -m pytest tests --collect-only -q 2>&1 | tail -1)
    echo -e "  ${GREEN}✓ PASSED${NC} - $COUNT"
else
    echo -e "  ${RED}✗ FAILED${NC}"
    ALL_PASSED=1
fi

# 2. Unit Tests
echo -e "${BLUE}▶ 2. Unit Tests${NC}"
if $PYTHON_CMD -m pytest tests/unit -q --tb=short >/dev/null 2>&1; then
    RESULT=$($PYTHON_CMD -m pytest tests/unit -q 2>&1 | tail -1)
    echo -e "  ${GREEN}✓ PASSED${NC} - $RESULT"
else
    echo -e "  ${RED}✗ FAILED${NC}"
    ALL_PASSED=1
fi

# 3. Smoke Test
echo -e "${BLUE}▶ 3. Smoke Test${NC}"
if bash scripts/test_package.sh smoke >/dev/null 2>&1; then
    echo -e "  ${GREEN}✓ PASSED${NC} - 4 suites (collection, unit, contract, integration)"
else
    echo -e "  ${RED}✗ FAILED${NC}"
    ALL_PASSED=1
fi

# 4. Lint Check
echo -e "${BLUE}▶ 4. Lint Check${NC}"
LINT_OUTPUT=$(bun run lint 2>&1)
# Check for actual errors (not just the word "error" in output)
if echo "$LINT_OUTPUT" | grep -qE "^\s*\d+:\d+\s+error"; then
    LINT_ERRORS=$(echo "$LINT_OUTPUT" | grep -cE "^\s*\d+:\d+\s+error" || true)
    echo -e "  ${RED}✗ FAILED${NC} - $LINT_ERRORS errors"
    ALL_PASSED=1
else
    # Portable regex for macOS BSD grep (no -P flag)
    WARNINGS=$(echo "$LINT_OUTPUT" | grep -oE '[0-9]+ warnings' | grep -oE '[0-9]+' | tail -1 || echo "0")
    ERRORS=$(echo "$LINT_OUTPUT" | grep -oE '[0-9]+ errors' | grep -oE '[0-9]+' | tail -1 || echo "0")
    echo -e "  ${GREEN}✓ PASSED${NC} - $ERRORS errors, $WARNINGS warnings"
fi

echo ""
echo -e "${BLUE}=========================================="
if [ "$ALL_PASSED" -eq 0 ]; then
    echo -e "Package Status: ${GREEN}HEALTHY${NC}"
    echo -e "==========================================${NC}"
    echo ""
    echo "All verifications passed. Package is ready."
    exit 0
else
    echo -e "Package Status: ${RED}ISSUES FOUND${NC}"
    echo -e "==========================================${NC}"
    echo ""
    echo "Some verifications failed. Run individual tests for details:"
    echo "  - $PYTHON_CMD -m pytest tests --collect-only"
    echo "  - $PYTHON_CMD -m pytest tests/unit -v"
    echo "  - bash scripts/test_package.sh smoke"
    echo "  - bun run lint"
    exit 1
fi
