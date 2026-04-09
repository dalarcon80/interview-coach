#!/bin/bash
# v1.0-Fases1-2 Backup Commands
# Run from project root: /Users/dalarcon/projects/dev/interview-coach

# Create backup directory if not exists
mkdir -p backup/v1.0

# Copy frontend files
cp tauri-app/src/App.tsx backup/v1.0/

# Copy Python backend files (Fases 1-2)
cp python-core/api/server.py backup/v1.0/
cp python-core/conversation/tracker.py backup/v1.0/
cp python-core/storage/session_repo.py backup/v1.0/
cp python-core/pipeline/silence_detector.py backup/v1.0/

# Copy config files
cp python-core/runtime_config.json backup/v1.0/

# Copy Rust files
cp tauri-app/src-tauri/src/audio/router.rs backup/v1.0/

echo "v1.0-Fases1-2 backup complete in backup/v1.0/"

# ============================================
# ROLLBACK COMMANDS - Copy-paste ready
# ============================================

# Rollback Scenario 1: Frontend
rollback_frontend() {
    cp backup/v1.0/App.tsx tauri-app/src/App.tsx
    echo "Frontend rollback complete - refresh Tauri app"
}

# Rollback Scenario 2: Config
rollback_config() {
    cp backup/v1.0/runtime_config.json python-core/runtime_config.json
    echo "Config rollback complete - restart backend"
}

# Rollback Scenario 3: Rust Router
rollback_rust() {
    cp backup/v1.0/router.rs tauri-app/src-tauri/src/audio/router.rs
    echo "Rust rollback complete - rebuild Tauri"
}

# Rollback Scenario 4: Python Backend (Fases 1-2)
rollback_python() {
    cp backup/v1.0/server.py python-core/api/server.py
    cp backup/v1.0/tracker.py python-core/conversation/tracker.py
    cp backup/v1.0/session_repo.py python-core/storage/session_repo.py
    rm -f python-core/pipeline/silence_detector.py
    echo "Python rollback complete - restart backend"
}

# Rollback Scenario 5: Complete Rollback
rollback_all() {
    cp backup/v1.0/App.tsx tauri-app/src/App.tsx
    cp backup/v1.0/server.py python-core/api/server.py
    cp backup/v1.0/tracker.py python-core/conversation/tracker.py
    cp backup/v1.0/session_repo.py python-core/storage/session_repo.py
    rm -f python-core/pipeline/silence_detector.py
    cp backup/v1.0/runtime_config.json python-core/runtime_config.json
    cp backup/v1.0/router.rs tauri-app/src-tauri/src/audio/router.rs
    echo "Complete rollback complete - restart all services"
}
