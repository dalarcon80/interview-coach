#!/bin/bash
# Interview Coach - Doctor Script for Windows (Git Bash/WSL)
# Diagnoses common issues with the development environment

set -euo pipefail

echo "=========================================="
echo "Interview Coach - Windows Doctor"
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

# Check if running in WSL
if grep -qi microsoft /proc/version 2>/dev/null; then
    echo -e "${GREEN}Running in WSL2 (recommended Windows workflow)${NC}"
    echo ""

    # Run Linux doctor for WSL
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    bash "$SCRIPT_DIR/doctor_linux.sh"
    exit $?
fi

# Native Windows checks
echo -e "${BLUE}▶ Windows Version${NC}"
if command -v cmd.exe >/dev/null 2>&1; then
    VER=$(cmd.exe /c "ver" 2>/dev/null | head -1)
    if [ -n "$VER" ]; then
        check_pass "$VER"
    else
        check_warn "Unable to detect Windows version from this shell"
    fi
else
    check_warn "cmd.exe unavailable from current shell"
fi

# Python
echo -e "${BLUE}▶ Python 3.11+${NC}"
if command -v python >/dev/null 2>&1 || command -v python3 >/dev/null 2>&1; then
    PYVER=$(python --version 2>&1 || python3 --version 2>&1)
    check_pass "$PYVER"
else
    check_fail "Python not found"
fi

# Node.js/npm and Bun
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

# Docker Desktop
echo -e "${BLUE}▶ Docker Desktop${NC}"
if command -v docker >/dev/null 2>&1; then
    if docker info >/dev/null 2>&1; then
        check_pass "Docker Desktop running"
    else
        check_warn "Docker installed but not running"
    fi
else
    check_warn "Docker Desktop not found (recommended for PostgreSQL + pgvector)"
fi

# Windows support truth
echo -e "${BLUE}▶ Windows support truth${NC}"
check_warn "Audio capture is stub on Windows (WASAPI path is V1.5 target)"
check_warn "Desktop app is stub for product use on Windows in current phase"

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
echo "  - Windows Web UI + Backend: functional"
echo "  - Windows Audio + Desktop: stub"
echo ""

echo -e "${YELLOW}Windows workflow notes:${NC}"
echo "  - Preferred: WSL2 + scripts/bootstrap_linux.sh + scripts/doctor_linux.sh"
echo "  - Native: web preview/backend only for current phase"

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
