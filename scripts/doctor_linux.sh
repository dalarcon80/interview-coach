#!/bin/bash
# Interview Coach - Doctor Script for Linux
# Diagnoses common issues with the development environment

set -euo pipefail

echo "=========================================="
echo "Interview Coach - Linux Doctor"
echo "=========================================="
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PASS=0
FAIL=0
WARN=0

check_pass() { echo -e "  ${GREEN}✓${NC} $1"; PASS=$((PASS + 1)); }
check_fail() { echo -e "  ${RED}✗${NC} $1"; FAIL=$((FAIL + 1)); }
check_warn() { echo -e "  ${YELLOW}!${NC} $1"; WARN=$((WARN + 1)); }

python_is_311_plus() {
    python3 - <<'PY'
import sys
sys.exit(0 if sys.version_info >= (3, 11) else 1)
PY
}

# 1. Distribution
echo -e "${BLUE}▶ Distribution${NC}"
if [ -f /etc/os-release ]; then
    . /etc/os-release
    check_pass "$PRETTY_NAME"
else
    check_warn "Unknown distribution"
fi

# 2. Python
echo -e "${BLUE}▶ Python 3.11+${NC}"
if command -v python3 >/dev/null 2>&1; then
    PYVER=$(python3 --version 2>&1 | awk '{print $2}')
    if python_is_311_plus; then
        check_pass "Python $PYVER"
    else
        check_fail "Python $PYVER - Need 3.11+"
    fi
else
    check_fail "Python not found"
fi

# 3. Node.js/npm and Bun
echo -e "${BLUE}▶ Node.js/npm and Bun${NC}"
if command -v node >/dev/null 2>&1; then
    check_pass "Node.js $(node --version)"
else
    check_fail "Node.js not found"
fi

if command -v npm >/dev/null 2>&1; then
    check_pass "npm $(npm --version)"
else
    check_fail "npm not found"
fi

if command -v bun >/dev/null 2>&1; then
    check_pass "Bun $(bun --version)"
else
    check_warn "Bun not found (optional; npm is supported)"
fi

# 4. Rust/Cargo (optional for current Linux support level)
echo -e "${BLUE}▶ Rust/Cargo (optional for Linux desktop work)${NC}"
if command -v rustc >/dev/null 2>&1; then
    check_pass "Rust $(rustc --version)"
else
    check_warn "Rust not found - Linux desktop path is currently stub"
fi

if command -v cargo >/dev/null 2>&1; then
    check_pass "Cargo $(cargo --version)"
else
    check_warn "Cargo not found - Linux desktop path is currently stub"
fi

# 5. Docker + PostgreSQL path
echo -e "${BLUE}▶ Docker / PostgreSQL path${NC}"
if command -v docker >/dev/null 2>&1; then
    if docker info >/dev/null 2>&1; then
        check_pass "Docker running (recommended for PostgreSQL + pgvector)"
    else
        check_warn "Docker installed but not running"
    fi
else
    check_warn "Docker not found - Use Docker or provision native PostgreSQL + pgvector"
fi

if command -v psql >/dev/null 2>&1; then
    check_pass "psql client available"
else
    check_warn "psql client not found (optional when using Docker-only workflow)"
fi

# 6. API Keys
echo -e "${BLUE}▶ LLM API Keys (optional)${NC}"
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
    check_pass "ANTHROPIC_API_KEY configured"
elif [ -n "${OPENAI_API_KEY:-}" ]; then
    check_pass "OPENAI_API_KEY configured"
else
    check_warn "No LLM API keys - Demo mode only"
fi

# 7. Project dependencies
echo -e "${BLUE}▶ Project dependencies${NC}"
cd "$(dirname "$0")/.."

if [ -d "node_modules" ]; then
    check_pass "node_modules present"
else
    check_warn "node_modules missing - Run: bun install (or npm install)"
fi

if [ -f "python-core/pyproject.toml" ]; then
    check_pass "python-core project present"
else
    check_fail "python-core project missing"
fi

# 8. Linux support truth
echo -e "${BLUE}▶ Linux support truth${NC}"
check_warn "Audio capture is stub on Linux (PipeWire path is V1.5 target)"
check_warn "Desktop app is stub for product use on Linux in current phase"

# Summary
echo ""
echo -e "${BLUE}=========================================="
echo "Diagnosis Summary"
echo -e "==========================================${NC}"
echo ""
echo -e "  ${GREEN}Passed:${NC}  $PASS"
echo -e "  ${YELLOW}Warnings:${NC} $WARN"
echo -e "  ${RED}Failed:${NC}  $FAIL"
echo ""
echo "Platform truth reminder:"
echo "  - Linux Web UI + Backend: functional"
echo "  - Linux Audio + Desktop: stub"
echo ""

if [ "$FAIL" -eq 0 ]; then
    echo -e "${GREEN}✓ Environment is viable for current Linux support level.${NC}"
    echo ""
    echo "Next steps:"
    echo "  - Start backend:     cd python-core && python main.py"
    echo "  - Start web preview: bun dev"
    echo "  - For pgvector:      docker compose up -d"
else
    echo -e "${RED}✗ Some required items are missing. Fix failures before proceeding.${NC}"
    exit 1
fi
