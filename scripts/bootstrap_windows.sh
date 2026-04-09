#!/bin/bash
# Interview Coach - Bootstrap Script for Windows (WSL/Git Bash)
# Sets up the development environment for Windows

set -euo pipefail

echo "=========================================="
echo "Interview Coach - Windows Bootstrap"
echo "=========================================="
echo ""

# Colors (may not work in all Windows terminals)
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Check if running in WSL
if grep -qi microsoft /proc/version 2>/dev/null; then
    echo -e "${GREEN}Running in WSL2 (recommended Windows path)${NC}"
    echo ""

    # Use Linux bootstrap for WSL
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    bash "$SCRIPT_DIR/bootstrap_linux.sh"
    exit $?
fi

# Native Windows (Git Bash/CMD)
echo -e "${YELLOW}Native Windows support in this phase:${NC}"
echo "  - Web UI: functional"
echo "  - Backend: functional"
echo "  - Audio capture: stub (V1.5 target)"
echo "  - Desktop app: stub (V1.5 target)"
echo ""
echo -e "${YELLOW}Recommendation: use WSL2 for the most reliable workflow.${NC}"
echo ""

# 1. Check Python 3.11+
echo -e "${BLUE}▶ Checking Python 3.11+...${NC}"
if command -v python >/dev/null 2>&1 || command -v python3 >/dev/null 2>&1; then
    PYVER=$(python --version 2>&1 || python3 --version 2>&1)
    echo -e "  ${GREEN}✓${NC} $PYVER"
else
    echo -e "  ${RED}✗${NC} Python not found. Install Python 3.11+: https://www.python.org/downloads/"
fi

# 2. Check Node.js/npm and Bun
echo -e "${BLUE}▶ Checking Node.js/npm and Bun...${NC}"
if command -v node >/dev/null 2>&1; then
    echo -e "  ${GREEN}✓${NC} Node.js $(node --version)"
else
    echo -e "  ${RED}✗${NC} Node.js not found. Install Node.js 18+: https://nodejs.org/"
fi

if command -v npm >/dev/null 2>&1; then
    echo -e "  ${GREEN}✓${NC} npm $(npm --version)"
else
    echo -e "  ${YELLOW}!${NC} npm not found (comes with Node.js in standard installs)"
fi

if command -v bun >/dev/null 2>&1; then
    echo -e "  ${GREEN}✓${NC} Bun $(bun --version)"
else
    echo -e "  ${YELLOW}!${NC} Bun not found (optional). Install from: https://bun.sh/"
fi

# 3. Rust/Cargo (not required for current Windows support level)
echo -e "${BLUE}▶ Checking Rust/Cargo (optional in current Windows phase)...${NC}"
if command -v rustc >/dev/null 2>&1 && command -v cargo >/dev/null 2>&1; then
    echo -e "  ${GREEN}✓${NC} Rust $(rustc --version)"
    echo -e "  ${GREEN}✓${NC} Cargo $(cargo --version)"
else
    echo -e "  ${YELLOW}!${NC} Rust/Cargo not found (desktop/audio on Windows are currently stub anyway)"
fi

# 4. Check Docker Desktop
echo -e "${BLUE}▶ Checking Docker Desktop...${NC}"
if command -v docker >/dev/null 2>&1; then
    if docker info >/dev/null 2>&1; then
        echo -e "  ${GREEN}✓${NC} Docker Desktop running"
    else
        echo -e "  ${YELLOW}!${NC} Docker installed but not running"
    fi
else
    echo -e "  ${YELLOW}!${NC} Docker Desktop not found. Install from: https://www.docker.com/products/docker-desktop"
fi

# Summary
echo ""
echo -e "${BLUE}=========================================="
echo "Windows Bootstrap Notes"
echo -e "==========================================${NC}"
echo ""
echo -e "${YELLOW}Recommendations for Windows:${NC}"
echo ""
echo "  Option 1: WSL2 (Recommended)"
echo "    - Install WSL2: wsl --install"
echo "    - Then run: bash scripts/bootstrap_linux.sh"
echo ""
echo "  Option 2: Native (current phase)"
echo "    - Install Python 3.11+, Node.js 18+, Docker Desktop"
echo "    - Backend + web preview are functional"
echo "    - Audio capture and desktop app remain stub"
echo ""
