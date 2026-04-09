#!/bin/bash
# Interview Coach - Doctor Script for macOS
# Diagnoses common issues with the development environment

set -euo pipefail

echo "=========================================="
echo "Interview Coach - macOS Doctor"
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

# 1. Architecture
echo -e "${BLUE}▶ Architecture${NC}"
ARCH=$(uname -m)
if [ "$ARCH" = "arm64" ]; then
    check_pass "Apple Silicon (arm64) - Tier 1 target"
else
    check_warn "Intel Mac ($ARCH) - Supported but not Tier 1 target"
fi

# 2. macOS Version + ScreenCaptureKit baseline
echo -e "${BLUE}▶ macOS Version / ScreenCaptureKit baseline${NC}"
MACOS_VERSION=$(sw_vers -productVersion 2>/dev/null || echo "0.0")
if macos_is_12_3_plus "$MACOS_VERSION"; then
    check_pass "macOS $MACOS_VERSION (ScreenCaptureKit baseline satisfied: 12.3+)"
else
    check_fail "macOS $MACOS_VERSION (ScreenCaptureKit requires 12.3+)"
fi

# 3. Python
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

# 4. Node.js/npm and Bun
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

# 5. Rust/Cargo
echo -e "${BLUE}▶ Rust/Cargo (for Tauri)${NC}"
if command -v rustc >/dev/null 2>&1; then
    check_pass "Rust $(rustc --version)"
else
    check_fail "Rust not found - Required for Tauri desktop"
fi

if command -v cargo >/dev/null 2>&1; then
    check_pass "Cargo $(cargo --version)"
else
    check_fail "Cargo not found - Install with Rust"
fi

# 6. Swift / Xcode CLT prerequisites
echo -e "${BLUE}▶ Swift / Xcode prerequisites${NC}"
if xcode-select -p >/dev/null 2>&1; then
    check_pass "Xcode Command Line Tools installed"
else
    check_fail "Xcode Command Line Tools missing (run: xcode-select --install)"
fi

if command -v swift >/dev/null 2>&1; then
    check_pass "Swift toolchain available"
else
    check_fail "Swift toolchain not found (required for Tauri/macOS build toolchain)"
fi

# 7. Docker / PostgreSQL path
echo -e "${BLUE}▶ Docker / PostgreSQL path${NC}"
if command -v docker >/dev/null 2>&1; then
    if docker info >/dev/null 2>&1; then
        check_pass "Docker running (recommended for PostgreSQL + pgvector)"
    else
        check_warn "Docker installed but not running"
    fi
else
    check_warn "Docker not found (recommended for PostgreSQL + pgvector)"
fi

if command -v psql >/dev/null 2>&1; then
    check_pass "psql client available"
else
    check_warn "psql client not found (optional when using Docker-only workflow)"
fi

# 8. API Keys
echo -e "${BLUE}▶ LLM API Keys (optional)${NC}"
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
    check_pass "ANTHROPIC_API_KEY configured"
elif [ -n "${OPENAI_API_KEY:-}" ]; then
    check_pass "OPENAI_API_KEY configured"
else
    check_warn "No LLM API keys - Demo mode only"
fi

# 9. Project dependencies
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

# 10. ScreenCaptureKit integration truth
echo -e "${BLUE}▶ ScreenCaptureKit integration${NC}"
if [ -f "tauri-app/src-tauri/src/audio/macos_capture.rs" ]; then
    check_pass "macOS capture source file present"
else
    check_fail "macOS capture source file missing"
fi

if grep -q "screencapturekit" tauri-app/src-tauri/Cargo.toml 2>/dev/null; then
    check_pass "screencapturekit crate referenced in Cargo.toml"
else
    check_fail "screencapturekit crate not found in Cargo.toml"
fi

if grep -q "audio/router" tauri-app/src-tauri/src/main.rs 2>/dev/null || grep -q "mod audio" tauri-app/src-tauri/src/main.rs 2>/dev/null; then
    check_warn "Desktop audio path still partial - IPC bridge/wiring should be verified manually"
else
    check_warn "Desktop audio path is partial - IPC bridge pending"
fi

# 11. Audio permission guidance
echo -e "${BLUE}▶ Audio permission guidance${NC}"
if command -v tccutil >/dev/null 2>&1; then
    check_pass "tccutil available"
    echo "    Grant permissions in System Settings > Privacy & Security:"
    echo "      - Screen Recording"
    echo "      - Microphone"
else
    check_warn "tccutil not found; verify Screen Recording + Microphone permissions manually"
fi

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
echo "  - macOS Web UI + Backend: functional"
echo "  - macOS Audio + Desktop: partial (IPC bridge pending)"
echo ""

if [ "$FAIL" -eq 0 ]; then
    echo -e "${GREEN}✓ Environment is viable for current macOS support level.${NC}"
    echo ""
    echo "Next steps:"
    echo "  - Start backend:     cd python-core && python main.py"
    echo "  - Start web preview: bun dev"
    echo "  - Start Tauri app:   cd tauri-app && npm run tauri dev"
else
    echo -e "${RED}✗ Some required items are missing. Resolve failures before proceeding.${NC}"
    exit 1
fi
