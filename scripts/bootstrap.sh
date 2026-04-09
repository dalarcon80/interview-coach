#!/bin/bash
# Interview Coach - Bootstrap Script
# Sets up the development environment
# Architecture v3.2.1 Compliant

set -e  # Exit on any real error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Interview Coach - Bootstrap${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# ===========================================
# Tier 1: Environment Checks
# ===========================================

echo -e "${YELLOW}[Tier 1] Checking prerequisites...${NC}"

# Check OS
OS="$(uname -s)"
case "$OS" in
    Darwin*)
        echo -e "  ${GREEN}✓${NC} macOS detected"
        MACOS_VERSION=$(sw_vers -productVersion)
        echo -e "    Version: $MACOS_VERSION"
        ;;
    Linux*)
        echo -e "  ${YELLOW}!${NC} Linux detected (V1.5 support)"
        ;;
    *)
        echo -e "  ${RED}✗${NC} Unsupported OS: $OS"
        echo "    V1 is macOS-first. Windows/Linux support planned for V1.5"
        exit 1
        ;;
esac

# Check required directories
echo ""
echo -e "${YELLOW}[Tier 1] Verifying directory structure...${NC}"

REQUIRED_DIRS=(
    "tauri-app"
    "python-core"
    "config"
    "scripts"
    "tests"
)

for dir in "${REQUIRED_DIRS[@]}"; do
    if [ -d "$dir" ]; then
        echo -e "  ${GREEN}✓${NC} $dir/"
    else
        echo -e "  ${RED}✗${NC} $dir/ - missing"
        exit 1
    fi
done

# Check .env file
echo ""
echo -e "${YELLOW}[Tier 1] Checking environment configuration...${NC}"

if [ -f ".env" ]; then
    echo -e "  ${GREEN}✓${NC} .env file exists"
else
    echo -e "  ${YELLOW}!${NC} .env file not found"
    if [ -f ".env.example" ]; then
        echo -e "    Creating .env from .env.example..."
        cp .env.example .env
        echo -e "  ${GREEN}✓${NC} .env created - please fill in your API keys"
    else
        echo -e "  ${RED}✗${NC} .env.example not found"
        exit 1
    fi
fi

# ===========================================
# Tier 2: Infrastructure Setup
# ===========================================

echo ""
echo -e "${YELLOW}[Tier 2] Setting up infrastructure...${NC}"

# Check Docker
echo ""
echo -e "${YELLOW}[Tier 2] Checking Docker...${NC}"

if command -v docker &> /dev/null; then
    DOCKER_VERSION=$(docker --version)
    echo -e "  ${GREEN}✓${NC} Docker installed: $DOCKER_VERSION"
    
    # Check if Docker is running
    if docker info &> /dev/null; then
        echo -e "  ${GREEN}✓${NC} Docker daemon running"
        
        # Start PostgreSQL
        echo ""
        echo -e "${YELLOW}[Tier 2] Starting PostgreSQL + pgvector...${NC}"
        docker compose up -d
        
        # Wait for PostgreSQL to be healthy
        echo -e "  Waiting for PostgreSQL to be ready..."
        for i in {1..30}; do
            if docker compose exec -T postgres pg_isready -U interview_coach -d interview_coach &> /dev/null; then
                echo -e "  ${GREEN}✓${NC} PostgreSQL is ready"
                break
            fi
            if [ $i -eq 30 ]; then
                echo -e "  ${RED}✗${NC} PostgreSQL failed to start within 30 seconds"
                exit 1
            fi
            sleep 1
        done
    else
        echo -e "  ${RED}✗${NC} Docker daemon not running"
        echo "    Please start Docker Desktop and re-run this script"
        exit 1
    fi
else
    echo -e "  ${RED}✗${NC} Docker not installed"
    echo "    Please install Docker Desktop and re-run this script"
    exit 1
fi

# ===========================================
# Tier 3: Dependencies
# ===========================================

echo ""
echo -e "${YELLOW}[Tier 3] Installing dependencies...${NC}"

# Python dependencies
echo ""
echo -e "${YELLOW}[Tier 3] Python dependencies...${NC}"

if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version)
    echo -e "  ${GREEN}✓${NC} $PYTHON_VERSION"
    
    if [ -f "python-core/pyproject.toml" ]; then
        echo -e "  Installing Python dependencies..."
        cd python-core
        pip install -e . 2>&1 | while read line; do
            if [[ "$line" == *"error"* ]] || [[ "$line" == *"Error"* ]]; then
                echo -e "  ${RED}✗${NC} $line"
            fi
        done
        cd ..
        echo -e "  ${GREEN}✓${NC} Python dependencies installed"
    else
        echo -e "  ${YELLOW}!${NC} python-core/pyproject.toml not found"
    fi
else
    echo -e "  ${RED}✗${NC} Python 3 not installed"
    exit 1
fi

# Node.js dependencies for Tauri
echo ""
echo -e "${YELLOW}[Tier 3] Node.js dependencies...${NC}"

if command -v node &> /dev/null; then
    NODE_VERSION=$(node --version)
    echo -e "  ${GREEN}✓${NC} Node.js $NODE_VERSION"
    
    if [ -d "tauri-app" ]; then
        echo -e "  Installing Tauri dependencies..."
        cd tauri-app
        npm install
        cd ..
        echo -e "  ${GREEN}✓${NC} Tauri dependencies installed"
    fi
else
    echo -e "  ${RED}✗${NC} Node.js not installed"
    exit 1
fi

# ===========================================
# Final Verification
# ===========================================

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Bootstrap Complete!${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo "Next steps:"
echo "  1. Edit .env with your API keys"
echo "  2. Run: ./scripts/doctor.sh"
echo "  3. Start the backend: cd python-core && uvicorn api.server:app --reload"
echo ""
