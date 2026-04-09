#!/bin/bash
# Interview Coach - Bootstrap Script for macOS
# Sets up the development environment for macOS (Tier 1 target)

set -euo pipefail

echo "=========================================="
echo "Interview Coach - macOS Bootstrap"
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

macos_is_12_3_plus() {
    local version="$1"
    local major="${version%%.*}"
    local rest="${version#*.}"
    local minor="${rest%%.*}"
    if [ "$major" -gt 12 ]; then
        return 0
    fi
    if [ "$major" -eq 12 ] && [ "$minor" -ge 3 ]; then
        return 0
    fi
    return 1
}

# 1. Check architecture
ARCH=$(uname -m)
if [ "$ARCH" = "arm64" ]; then
    echo -e "${BLUE}▶ Architecture${NC}"
    echo -e "  ${GREEN}✓${NC} Apple Silicon (arm64)"
else
    echo -e "${BLUE}▶ Architecture${NC}"
    echo -e "  ${YELLOW}!${NC} Intel Mac detected ($ARCH). Supported, but Apple Silicon is Tier 1 target."
fi

# 2. Check Homebrew
echo -e "${BLUE}▶ Checking Homebrew...${NC}"
if command -v brew >/dev/null 2>&1; then
    echo -e "  ${GREEN}✓${NC} Homebrew installed"
else
    echo -e "  ${YELLOW}!${NC} Homebrew not found. Installing..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

# 3. Check Python 3.11+
echo -e "${BLUE}▶ Checking Python 3.11+...${NC}"
if command -v python3 >/dev/null 2>&1; then
    PYTHON_VERSION=$(python3 --version | awk '{print $2}')
    if python_is_311_plus; then
        echo -e "  ${GREEN}✓${NC} Python ${PYTHON_VERSION}"
    else
        echo -e "  ${YELLOW}!${NC} Python ${PYTHON_VERSION} found, upgrading to 3.11+ via Homebrew..."
        brew install python@3.11
    fi
else
    echo -e "  ${YELLOW}!${NC} Python not found. Installing python@3.11..."
    brew install python@3.11
fi

# 4. Check Node.js/npm (required) and Bun (optional)
echo -e "${BLUE}▶ Checking Node.js/npm and Bun...${NC}"
if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
    echo -e "  ${GREEN}✓${NC} Node.js $(node --version)"
    echo -e "  ${GREEN}✓${NC} npm $(npm --version)"
else
    echo -e "  ${YELLOW}!${NC} Node.js/npm not found. Installing node..."
    brew install node
fi

if command -v bun >/dev/null 2>&1; then
    echo -e "  ${GREEN}✓${NC} Bun $(bun --version)"
else
    echo -e "  ${YELLOW}!${NC} Bun not found (optional). Install with: curl -fsSL https://bun.sh/install | bash"
fi

# 5. Check Rust/Cargo (required for Tauri desktop dev)
echo -e "${BLUE}▶ Checking Rust/Cargo...${NC}"
if command -v rustc >/dev/null 2>&1 && command -v cargo >/dev/null 2>&1; then
    echo -e "  ${GREEN}✓${NC} Rust $(rustc --version)"
    echo -e "  ${GREEN}✓${NC} Cargo $(cargo --version)"
else
    echo -e "  ${YELLOW}!${NC} Rust toolchain not found. Installing via rustup..."
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
    if [ -f "$HOME/.cargo/env" ]; then
        # shellcheck disable=SC1090
        source "$HOME/.cargo/env"
    fi
fi

# 6. ScreenCaptureKit + Swift/Xcode prerequisites
echo -e "${BLUE}▶ Checking ScreenCaptureKit and Swift prerequisites...${NC}"
MACOS_VERSION=$(sw_vers -productVersion 2>/dev/null || echo "0.0")
if macos_is_12_3_plus "$MACOS_VERSION"; then
    echo -e "  ${GREEN}✓${NC} macOS ${MACOS_VERSION} (ScreenCaptureKit baseline satisfied)"
else
    echo -e "  ${YELLOW}!${NC} macOS ${MACOS_VERSION} detected. ScreenCaptureKit requires macOS 12.3+"
fi

if xcode-select -p >/dev/null 2>&1; then
    echo -e "  ${GREEN}✓${NC} Xcode Command Line Tools installed"
else
    echo -e "  ${YELLOW}!${NC} Xcode Command Line Tools missing. Run: xcode-select --install"
fi

if command -v swift >/dev/null 2>&1; then
    echo -e "  ${GREEN}✓${NC} Swift toolchain available: $(swift --version | head -n 1)"
else
    echo -e "  ${YELLOW}!${NC} Swift toolchain missing. Install Xcode or Command Line Tools for Tauri dev builds."
fi

if [ -f "tauri-app/src-tauri/src/audio/macos_capture.rs" ] && grep -q "screencapturekit" tauri-app/src-tauri/Cargo.toml 2>/dev/null; then
    echo -e "  ${GREEN}✓${NC} ScreenCaptureKit crate wiring present"
else
    echo -e "  ${YELLOW}!${NC} ScreenCaptureKit wiring appears incomplete"
fi

# 7. Install Python dependencies
echo -e "${BLUE}▶ Installing Python dependencies...${NC}"
cd "$(dirname "$0")/.."
if [ -f "python-core/pyproject.toml" ]; then
    cd python-core
    python3 -m pip install --upgrade pip >/dev/null 2>&1 || true
    python3 -m pip install -e .
    cd ..
    echo -e "  ${GREEN}✓${NC} Python dependencies installed"
fi

# 8. Install Node dependencies
echo -e "${BLUE}▶ Installing Node dependencies...${NC}"
if [ -f "package.json" ]; then
    if command -v bun >/dev/null 2>&1; then
        bun install
    else
        npm install
    fi
    echo -e "  ${GREEN}✓${NC} Node dependencies installed"
fi

# 9. Check Docker (optional but recommended for pgvector)
echo -e "${BLUE}▶ Checking Docker (recommended for PostgreSQL + pgvector)...${NC}"
if command -v docker >/dev/null 2>&1; then
    if docker info >/dev/null 2>&1; then
        echo -e "  ${GREEN}✓${NC} Docker installed and running"
    else
        echo -e "  ${YELLOW}!${NC} Docker installed but not running"
    fi
else
    echo -e "  ${YELLOW}!${NC} Docker not found. Install Docker Desktop for PostgreSQL + pgvector."
fi

# 10. Summary
echo ""
echo -e "${BLUE}=========================================="
echo "Bootstrap Complete"
echo -e "==========================================${NC}"
echo ""
echo "Platform truth:"
echo "  - macOS Web UI + Backend: functional"
echo "  - macOS Audio + Desktop: partial (IPC bridge pending)"
echo ""
echo "Notes:"
echo "  - Swift toolchain/runtime is required for Tauri development on macOS."
echo "  - Grant Screen Recording + Microphone permissions when running desktop audio capture."
echo ""
echo "Next steps:"
echo "  1. Run health check:    bash scripts/doctor_macos.sh"
echo "  2. Start backend:       cd python-core && python main.py"
echo "  3. Start web preview:   bun dev"
echo "  4. Start Tauri app:     cd tauri-app && npm run tauri dev"
echo ""
echo "For PostgreSQL + pgvector:"
echo "  docker compose up -d"
echo ""
