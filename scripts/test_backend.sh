#!/bin/bash
# Interview Coach - Backend Test Script
# Run tests for the Python/FastAPI backend

set -e

echo "=========================================="
echo "Interview Coach - Backend Test Suite"
echo "=========================================="

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Change to project root
cd "$(dirname "$0")/.."

# Check Python
if ! command -v python &> /dev/null; then
    echo -e "${RED}Python not found. Please install Python 3.11+${NC}"
    exit 1
fi

echo ""
echo "Running tests..."
echo ""

# Run pytest with verbose output
python -m pytest tests/ -v \
    --tb=short \
    --ignore=tests/fixtures \
    -x

# Capture exit code
EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}=========================================="
    echo -e "All tests passed!"
    echo -e "==========================================${NC}"
else
    echo -e "${RED}=========================================="
    echo -e "Some tests failed. Exit code: $EXIT_CODE"
    echo -e "==========================================${NC}"
fi

exit $EXIT_CODE
