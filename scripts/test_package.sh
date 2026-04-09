#!/bin/bash
# Interview Coach - Package Smoke Test Runner
# Validates that the package is internally consistent and verifiable
#
# Usage:
#   ./scripts/test_package.sh          # Run smoke tests
#   ./scripts/test_package.sh quick    # Quick validation (unit only)
#   ./scripts/test_package.sh full     # Full validation (all tests)

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Change to project root
cd "$(dirname "$0")/.."

MODE="${1:-smoke}"

echo -e "${BLUE}=========================================="
echo "Interview Coach - Package Smoke Test"
echo "Mode: $MODE"
echo -e "==========================================${NC}"
echo ""

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

# Check prerequisites
echo -e "${YELLOW}Checking prerequisites...${NC}"

echo -e "  ${GREEN}✓${NC} Python found: $($PYTHON_CMD --version)"

if ! $PYTHON_CMD -c "import pytest" 2>/dev/null; then
    echo -e "${RED}ERROR: pytest not found. Install with: pip install pytest pytest-asyncio${NC}"
    exit 1
fi
echo -e "  ${GREEN}✓${NC} pytest found"

echo ""

# Track results
PASSED=0
FAILED=0

# Function to run tests and track result
run_test() {
    local name="$1"
    local args="$2"

    echo -e "${BLUE}▶ $name${NC}"
    if $PYTHON_CMD -m pytest $args --tb=short -q 2>&1; then
        echo -e "  ${GREEN}✓ PASSED${NC}"
        ((PASSED++))
    else
        echo -e "  ${RED}✗ FAILED${NC}"
        ((FAILED++))
    fi
}

case "$MODE" in
    quick)
        echo -e "${YELLOW}Running QUICK validation (unit tests only)${NC}"
        echo ""
        run_test "Unit Tests" "tests/unit"
        ;;

    smoke)
        echo -e "${YELLOW}Running SMOKE validation${NC}"
        echo ""

        # 1. Test collection
        echo -e "${BLUE}▶ Test Collection${NC}"
        if $PYTHON_CMD -m pytest tests --collect-only -q >/dev/null 2>&1; then
            echo -e "  ${GREEN}✓ PASSED${NC} (all tests collect)"
            ((PASSED++))
        else
            echo -e "  ${RED}✗ FAILED${NC} (collection errors)"
            ((FAILED++))
        fi

        # 2. Unit tests
        run_test "Unit Tests" "tests/unit"

        # 3. WS Contract test
        run_test "WebSocket Contract" "tests/integration/test_frontend_backend_ws_contract.py"

        # 4. UI Component integration
        run_test "UI Component Integration" "tests/integration/test_realtime_ui_component_integration.py"
        ;;

    full)
        echo -e "${YELLOW}Running FULL validation${NC}"
        echo ""
        run_test "All Tests" "tests"
        ;;

    *)
        echo -e "${RED}Unknown mode: $MODE${NC}"
        echo "Usage: $0 [quick|smoke|full]"
        exit 1
        ;;
esac

echo ""
echo -e "${BLUE}=========================================="
echo "Results: ${GREEN}$PASSED passed${NC}, ${RED}$FAILED failed${NC}"
echo -e "==========================================${NC}"

if [ $FAILED -gt 0 ]; then
    echo ""
    echo -e "${YELLOW}Note: Some tests may fail due to missing dependencies:${NC}"
    echo "  - asyncpg: Required for database integration tests"
    echo "  - PostgreSQL: Required for real database tests"
    echo "  - API keys: Required for LLM integration tests"
    echo ""
    echo "Run 'pytest tests --collect-only' to verify all tests can be collected."
    exit 1
fi

exit 0
