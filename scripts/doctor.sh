#!/bin/bash
# Interview Coach - Doctor Script
# Verifies system health (three-tier checks)
# Architecture v3.2.1 Compliant

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

ERRORS=0
WARNINGS=0

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Interview Coach - Doctor${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# ===========================================
# Tier 1: Structure
# ===========================================

echo -e "${YELLOW}[Tier 1] Structure Check${NC}"
echo "Checking files and configuration..."

# Required files
REQUIRED_FILES=(
    ".env"
    "docker-compose.yml"
    "config/providers.yaml"
    "config/status.json"
    "python-core/pyproject.toml"
    "tauri-app/package.json"
    "tauri-app/src-tauri/Cargo.toml"
)

for file in "${REQUIRED_FILES[@]}"; do
    if [ -f "$file" ]; then
        echo -e "  ${GREEN}✓${NC} $file"
    else
        echo -e "  ${RED}✗${NC} $file - missing"
        ((ERRORS++))
    fi
done

# Required directories
REQUIRED_DIRS=(
    "python-core"
    "python-core/contracts"
    "python-core/adapters"
    "python-core/api"
    "python-core/storage"
    "python-core/pipeline"
    "tests/unit"
    "tauri-app/src"
    "tauri-app/src-tauri/src"
)

for dir in "${REQUIRED_DIRS[@]}"; do
    if [ -d "$dir" ]; then
        echo -e "  ${GREEN}✓${NC} $dir/"
    else
        echo -e "  ${RED}✗${NC} $dir/ - missing"
        ((ERRORS++))
    fi
done

# Check API keys in .env
echo ""
echo "Checking API keys..."

if [ -f ".env" ]; then
    # Check for placeholder API keys
    if grep -q "your_deepgram_api_key_here" .env 2>/dev/null; then
        echo -e "  ${YELLOW}!${NC} DEEPGRAM_API_KEY not set (using placeholder)"
        ((WARNINGS++))
    else
        echo -e "  ${GREEN}✓${NC} DEEPGRAM_API_KEY configured"
    fi
    
    if grep -q "your_anthropic_api_key_here" .env 2>/dev/null; then
        echo -e "  ${YELLOW}!${NC} ANTHROPIC_API_KEY not set (using placeholder)"
        ((WARNINGS++))
    else
        echo -e "  ${GREEN}✓${NC} ANTHROPIC_API_KEY configured"
    fi
    
    if grep -q "your_openai_api_key_here" .env 2>/dev/null; then
        echo -e "  ${YELLOW}!${NC} OPENAI_API_KEY not set (using placeholder)"
        ((WARNINGS++))
    else
        echo -e "  ${GREEN}✓${NC} OPENAI_API_KEY configured"
    fi
fi

echo ""

# ===========================================
# Tier 2: Infrastructure
# ===========================================

echo -e "${YELLOW}[Tier 2] Infrastructure Check${NC}"
echo "Checking Docker and database..."

# Docker check
if command -v docker &> /dev/null; then
    echo -e "  ${GREEN}✓${NC} Docker installed"
    
    if docker info &> /dev/null 2>&1; then
        echo -e "  ${GREEN}✓${NC} Docker daemon running"
        
        # Check PostgreSQL container
        if docker ps | grep -q "interview-coach-db"; then
            echo -e "  ${GREEN}✓${NC} PostgreSQL container running"
            
            # Check pgvector extension
            if docker compose exec -T postgres psql -U interview_coach -d interview_coach -c "SELECT 1 FROM pg_extension WHERE extname = 'vector';" 2>/dev/null | grep -q "1 row"; then
                echo -e "  ${GREEN}✓${NC} pgvector extension installed"
            else
                echo -e "  ${YELLOW}!${NC} pgvector extension not found"
                ((WARNINGS++))
            fi
            
            # Check database tables
            TABLES=$(docker compose exec -T postgres psql -U interview_coach -d interview_coach -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';" 2>/dev/null | tr -d ' ')
            if [ "$TABLES" -gt 0 ] 2>/dev/null; then
                echo -e "  ${GREEN}✓${NC} Database tables exist ($TABLES tables)"
            else
                echo -e "  ${YELLOW}!${NC} No database tables found"
                ((WARNINGS++))
            fi
        else
            echo -e "  ${YELLOW}!${NC} PostgreSQL container not running"
            echo "    Run: docker compose up -d"
            ((WARNINGS++))
        fi
    else
        echo -e "  ${YELLOW}!${NC} Docker daemon not running"
        ((WARNINGS++))
    fi
else
    echo -e "  ${RED}✗${NC} Docker not installed"
    ((ERRORS++))
fi

echo ""

# ===========================================
# Tier 3: Functional
# ===========================================

echo -e "${YELLOW}[Tier 3] Functional Check${NC}"
echo "Testing Python imports and services..."

cd python-core 2>/dev/null || true

# Test Python imports
if python3 -c "from contracts.models import *; print('OK')" 2>/dev/null; then
    echo -e "  ${GREEN}✓${NC} contracts.models imports"
else
    echo -e "  ${RED}✗${NC} contracts.models import failed"
    ((ERRORS++))
fi

if python3 -c "from adapters.interfaces import *; print('OK')" 2>/dev/null; then
    echo -e "  ${GREEN}✓${NC} adapters.interfaces imports"
else
    echo -e "  ${RED}✗${NC} adapters.interfaces import failed"
    ((ERRORS++))
fi

if python3 -c "from adapters.provider_registry import get_registry; r = get_registry(); print('OK')" 2>/dev/null; then
    echo -e "  ${GREEN}✓${NC} provider_registry loads"
else
    echo -e "  ${RED}✗${NC} provider_registry failed"
    ((ERRORS++))
fi

# Test providers.yaml parsing
if python3 -c "
import yaml
with open('../config/providers.yaml') as f:
    data = yaml.safe_load(f)
    assert 'llm' in data
    assert 'main' in data['llm']
    print('OK')
" 2>/dev/null; then
    echo -e "  ${GREEN}✓${NC} providers.yaml parses correctly"
else
    echo -e "  ${RED}✗${NC} providers.yaml parsing failed"
    ((ERRORS++))
fi

cd ..

# Check Node packages
if [ -d "tauri-app/node_modules" ]; then
    echo -e "  ${GREEN}✓${NC} Tauri node_modules installed"
else
    echo -e "  ${YELLOW}!${NC} Tauri node_modules not found"
    echo "    Run: cd tauri-app && npm install"
    ((WARNINGS++))
fi

echo ""

# ===========================================
# Summary
# ===========================================

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Doctor Summary${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

if [ $ERRORS -gt 0 ]; then
    echo -e "  ${RED}Errors: $ERRORS${NC}"
else
    echo -e "  ${GREEN}Errors: 0${NC}"
fi

if [ $WARNINGS -gt 0 ]; then
    echo -e "  ${YELLOW}Warnings: $WARNINGS${NC}"
else
    echo -e "  ${GREEN}Warnings: 0${NC}"
fi

echo ""

if [ $ERRORS -gt 0 ]; then
    echo -e "${RED}❌ Doctor found errors. Fix before proceeding.${NC}"
    exit 1
elif [ $WARNINGS -gt 0 ]; then
    echo -e "${YELLOW}⚠️  Doctor passed with warnings.${NC}"
    exit 0
else
    echo -e "${GREEN}✅ Doctor passed. All systems healthy.${NC}"
    exit 0
fi
