#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTION="${1:-status}"
RAW_PROFILE="${2:-${INTERVIEW_COACH_PROFILE:-default}}"
BACKEND_PORT="${INTERVIEW_COACH_BACKEND_PORT:-8000}"
FRONTEND_PORT="${INTERVIEW_COACH_FRONTEND_PORT:-5174}"

sanitize_profile() {
  local value
  value="$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9._-]+/-/g; s/^[._-]+//; s/[._-]+$//')"
  if [[ -z "$value" ]]; then
    value="default"
  fi
  printf '%s' "$value"
}

PROFILE="$(sanitize_profile "$RAW_PROFILE")"
PROFILE_ROOT="$ROOT_DIR/.runtime/profiles/$PROFILE"
LOG_DIR="$PROFILE_ROOT/logs"
PID_DIR="$PROFILE_ROOT/pids"
PY_CACHE_DIR="$PROFILE_ROOT/pycache"
TAURI_TARGET_DIR="$PROFILE_ROOT/tauri-target"
RUNTIME_CONFIG_PATH="$PROFILE_ROOT/runtime_config.json"
BACKEND_LOG="$LOG_DIR/backend.log"
TAURI_LOG="$LOG_DIR/tauri.log"
BACKEND_PID_FILE="$PID_DIR/backend.pid"
TAURI_PID_FILE="$PID_DIR/tauri.pid"

mkdir -p "$LOG_DIR" "$PID_DIR" "$PY_CACHE_DIR" "$TAURI_TARGET_DIR"

is_port_busy() {
  lsof -ti "tcp:$1" >/dev/null 2>&1
}

read_pid() {
  local pid_file="$1"
  if [[ -f "$pid_file" ]]; then
    tr -d ' \n' <"$pid_file"
  fi
}

spawn_detached() {
  local log_file="$1"
  shift

  INTERVIEW_COACH_SPAWN_LOG_FILE="$log_file" \
  INTERVIEW_COACH_SPAWN_CWD="$ROOT_DIR" \
  python3 - "$@" <<'PY'
import os
import subprocess
import sys
from pathlib import Path

log_path = Path(os.environ["INTERVIEW_COACH_SPAWN_LOG_FILE"])
log_path.parent.mkdir(parents=True, exist_ok=True)
cwd = os.environ["INTERVIEW_COACH_SPAWN_CWD"]

with log_path.open("ab") as handle:
    process = subprocess.Popen(
        sys.argv[1:],
        cwd=cwd,
        env=os.environ.copy(),
        stdin=subprocess.DEVNULL,
        stdout=handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        close_fds=True,
    )

print(process.pid)
PY
}

print_status() {
  local commit branch checksum
  commit="$(git -C "$ROOT_DIR" rev-parse HEAD)"
  branch="$(git -C "$ROOT_DIR" rev-parse --abbrev-ref HEAD)"
  checksum="missing"
  if [[ -f "$RUNTIME_CONFIG_PATH" ]]; then
    checksum="$(shasum -a 256 "$RUNTIME_CONFIG_PATH" | awk '{print $1}')"
  fi

  cat <<EOF
profile=$PROFILE
branch=$branch
commit=$commit
backend_port=$BACKEND_PORT
frontend_port=$FRONTEND_PORT
runtime_config_path=$RUNTIME_CONFIG_PATH
runtime_config_sha256=$checksum
pycache_dir=$PY_CACHE_DIR
tauri_target_dir=$TAURI_TARGET_DIR
backend_pid=$(read_pid "$BACKEND_PID_FILE")
tauri_pid=$(read_pid "$TAURI_PID_FILE")
backend_port_busy=$(is_port_busy "$BACKEND_PORT" && echo yes || echo no)
frontend_port_busy=$(is_port_busy "$FRONTEND_PORT" && echo yes || echo no)
backend_log=$BACKEND_LOG
tauri_log=$TAURI_LOG
EOF
}

stop_pid_file() {
  local pid_file="$1"
  local pid
  pid="$(read_pid "$pid_file")"
  if [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1; then
    kill "$pid" >/dev/null 2>&1 || true
    sleep 1
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill -9 "$pid" >/dev/null 2>&1 || true
    fi
  fi
  rm -f "$pid_file"
}

start_stack() {
  stop_pid_file "$BACKEND_PID_FILE"
  stop_pid_file "$TAURI_PID_FILE"

  if is_port_busy "$BACKEND_PORT"; then
    echo "backend port $BACKEND_PORT is busy; stop the conflicting process first" >&2
    exit 1
  fi

  if is_port_busy "$FRONTEND_PORT"; then
    echo "frontend port $FRONTEND_PORT is busy; stop the conflicting process first" >&2
    exit 1
  fi

  local backend_pid
  backend_pid="$(
    INTERVIEW_COACH_PROFILE="$PROFILE" \
    VITE_INTERVIEW_COACH_PROFILE="$PROFILE" \
    INTERVIEW_COACH_RUNTIME_CONFIG_PATH="$RUNTIME_CONFIG_PATH" \
    PYTHONPYCACHEPREFIX="$PY_CACHE_DIR" \
    CARGO_TARGET_DIR="$TAURI_TARGET_DIR" \
    INTERVIEW_COACH_TRACE_AUDIO_PIPELINE="${INTERVIEW_COACH_TRACE_AUDIO_PIPELINE:-0}" \
    INTERVIEW_COACH_TRACE_CAPTIONS="${INTERVIEW_COACH_TRACE_CAPTIONS:-0}" \
    PYTHONPATH=python-core \
    spawn_detached "$BACKEND_LOG" "$ROOT_DIR/.venv/bin/python" -m uvicorn api.server:app --app-dir python-core --host 127.0.0.1 --port "$BACKEND_PORT"
  )"
  printf '%s\n' "$backend_pid" >"$BACKEND_PID_FILE"

  local tauri_pid
  tauri_pid="$(
    INTERVIEW_COACH_PROFILE="$PROFILE" \
    VITE_INTERVIEW_COACH_PROFILE="$PROFILE" \
    INTERVIEW_COACH_RUNTIME_CONFIG_PATH="$RUNTIME_CONFIG_PATH" \
    PYTHONPYCACHEPREFIX="$PY_CACHE_DIR" \
    CARGO_TARGET_DIR="$TAURI_TARGET_DIR" \
    INTERVIEW_COACH_TRACE_AUDIO_PIPELINE="${INTERVIEW_COACH_TRACE_AUDIO_PIPELINE:-0}" \
    INTERVIEW_COACH_TRACE_CAPTIONS="${INTERVIEW_COACH_TRACE_CAPTIONS:-0}" \
    spawn_detached "$TAURI_LOG" npm run tauri:dev
  )"
  printf '%s\n' "$tauri_pid" >"$TAURI_PID_FILE"

  print_status
}

case "$ACTION" in
  start)
    start_stack
    ;;
  stop)
    stop_pid_file "$BACKEND_PID_FILE"
    stop_pid_file "$TAURI_PID_FILE"
    print_status
    ;;
  status)
    print_status
    ;;
  *)
    echo "usage: $0 {start|stop|status} [profile]" >&2
    exit 1
    ;;
esac
