#!/bin/bash
# Interview Coach - Bootstrap Script for Linux
# Sets up the development environment for Linux

set -euo pipefail

echo "=========================================="
echo "Interview Coach - Linux Bootstrap"
echo "=========================================="
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

python_is_311_plus() {
    python3 - <<'PY'
import sys
sys.exit(0 if sys.version_info >= (3, 11) else 1)
PY
}

# Detect distribution
if [ -f /etc/os-release ]; then
    . /etc/os-release
    DISTRO=$ID
else
    DISTRO="unknown"
fi

echo -e "Detected distribution: ${BLUE}$DISTRO${NC}"
echo ""

# 1. Check Python
echo -e "${BLUE}▶ Checking Python 3.11+...${NC}"
if command -v python3 >/dev/null 2>&1; then
    PYTHON_VERSION=$(python3 --version | awk '{print $2}')
    if python_is_311_plus; then
        echo -e "  ${GREEN}✓${NC} Python $PYTHON_VERSION"
    else
        echo -e "  ${YELLOW}!${NC} Python $PYTHON_VERSION found, need 3.11+"
        case $DISTRO in
            ubuntu|debian)
                echo "     Install suggestion: sudo apt update && sudo apt install -y python3.11 python3-pip"
                ;;
            fedora|rhel|centos)
                echo "     Install suggestion: sudo dnf install -y python3.11 python3-pip"
                ;;
            arch)
                echo "     Install suggestion: sudo pacman -S python python-pip"
                ;;
            *)
                echo "     Please install Python 3.11+ manually"
                ;;
        esac
    fi
else
    echo -e "  ${YELLOW}!${NC} Python not found"
    case $DISTRO in
        ubuntu|debian)
            echo "     Install suggestion: sudo apt update && sudo apt install -y python3.11 python3-pip"
            ;;
        fedora|rhel|centos)
            echo "     Install suggestion: sudo dnf install -y python3.11 python3-pip"
            ;;
        arch)
            echo "     Install suggestion: sudo pacman -S python python-pip"
            ;;
        *)
            echo "     Please install Python 3.11+ manually"
            ;;
    esac
fi

# 2. Check Node.js/npm and Bun
echo -e "${BLUE}▶ Checking Node.js/npm and Bun...${NC}"
if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
    echo -e "  ${GREEN}✓${NC} Node.js $(node --version)"
    echo -e "  ${GREEN}✓${NC} npm $(npm --version)"
else
    echo -e "  ${YELLOW}!${NC} Node.js/npm not found. Install Node.js 18+ via your package manager or nvm."
fi

if command -v bun >/dev/null 2>&1; then
    echo -e "  ${GREEN}✓${NC} Bun $(bun --version)"
else
    echo -e "  ${YELLOW}!${NC} Bun not found (optional). Install with: curl -fsSL https://bun.sh/install | bash"
fi

# 3. Check Rust/Cargo (desktop dev only)
echo -e "${BLUE}▶ Checking Rust/Cargo (desktop dev only)...${NC}"
if command -v rustc >/dev/null 2>&1 && command -v cargo >/dev/null 2>&1; then
    echo -e "  ${GREEN}✓${NC} Rust $(rustc --version)"
    echo -e "  ${GREEN}✓${NC} Cargo $(cargo --version)"
else
    echo -e "  ${YELLOW}!${NC} Rust/Cargo not found. Install with rustup if you need desktop builds."
fi

# 4. Install Python dependencies
echo -e "${BLUE}▶ Installing Python dependencies...${NC}"
cd "$(dirname "$0")/.."
if [ -f "python-core/pyproject.toml" ]; then
    cd python-core
    if command -v python3 >/dev/null 2>&1; then
        python3 -m pip install --upgrade pip >/dev/null 2>&1 || true
        python3 -m pip install -e . || echo -e "  ${YELLOW}!${NC} Python dependency install skipped (check Python/pip setup)"
    fi
    cd ..
    echo -e "  ${GREEN}✓${NC} Python dependency step completed"
fi

# 5. Install Node dependencies
echo -e "${BLUE}▶ Installing Node dependencies...${NC}"
if [ -f "package.json" ]; then
    if command -v bun >/dev/null 2>&1; then
        bun install
    elif command -v npm >/dev/null 2>&1; then
        npm install
    else
        echo -e "  ${YELLOW}!${NC} Skipped Node dependencies (install Node.js/npm first)"
    fi
    echo -e "  ${GREEN}✓${NC} Node dependency step completed"
fi

# 6. PostgreSQL + Docker guidance
echo -e "${BLUE}▶ Checking PostgreSQL/Docker path...${NC}"
if command -v docker >/dev/null 2>&1; then
    if docker info >/dev/null 2>&1; then
        echo -e "  ${GREEN}✓${NC} Docker installed and running (recommended for PostgreSQL + pgvector)"
    else
        echo -e "  ${YELLOW}!${NC} Docker installed but not running"
    fi
else
    echo -e "  ${YELLOW}!${NC} Docker not found. Install Docker or provision native PostgreSQL + pgvector manually."
fi

if command -v psql >/dev/null 2>&1; then
    echo -e "  ${GREEN}✓${NC} psql client available"
else
    echo -e "  ${YELLOW}!${NC} psql not found (optional if using Docker-only workflow)"
fi

# 7. Summary
echo ""
echo -e "${BLUE}=========================================="
echo "Bootstrap Complete"
echo -e "==========================================${NC}"
echo ""
echo "Platform truth:"
echo "  - Linux Web UI + Backend: functional"
echo "  - Linux Audio + Desktop: stub (V1.5 target)"
echo ""
echo "Next steps:"
echo "  1. Run health check:    bash scripts/doctor_linux.sh"
echo "  2. Start backend:       cd python-core && python main.py"
echo "  3. Start web preview:   bun dev"
echo ""
echo "For PostgreSQL + pgvector:"
echo "  docker compose up -d"
echo ""
