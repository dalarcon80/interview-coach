"""
Interview Coach — config.runtime

Single source of truth for runtime configuration per ADR-004.

Precedence (highest wins):
1. `$INTERVIEW_COACH_RUNTIME_CONFIG_PATH` explicit override.
2. `$XDG_CONFIG_HOME/interview-coach/profiles/<profile>/runtime_config.json`
   when `INTERVIEW_COACH_PROFILE` is set and != 'default'.
3. `$XDG_CONFIG_HOME/interview-coach/runtime_config.json` (default profile).
4. `~/.config/interview-coach/...` (when XDG_CONFIG_HOME is empty).

The legacy `python-core/runtime_config.json` **is no longer consulted**.
Migration to this model happened in F1-T12 (file removed from repo) and
F2-T9 (this module). If a user still has a local copy, run
`scripts/setup_secrets.sh` (F2-T19) once to migrate.

Secrets are NOT stored in this file going forward (ADR-004). The
`api_key` field remains in the Pydantic model only for backward
compatibility during the F2-T18/T20 cutover; once migrated, api_key is
sourced from the secret_store at request time.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PROFILE_ENV = "INTERVIEW_COACH_PROFILE"
_RUNTIME_CONFIG_ENV = "INTERVIEW_COACH_RUNTIME_CONFIG_PATH"
_XDG_CONFIG_ENV = "XDG_CONFIG_HOME"
_DEFAULT_CONFIG_DIR = "interview-coach"
_DEFAULT_CONFIG_FILENAME = "runtime_config.json"
_PROFILES_DIRNAME = "profiles"
_DEFAULT_PROFILE = "default"


# =============================================================================
# Profile
# =============================================================================
def sanitize_execution_profile(value: str | None) -> str:
    cleaned = re.sub(r"[^a-z0-9._-]+", "-", str(value or "").strip().lower()).strip("._-")
    return cleaned or _DEFAULT_PROFILE


def get_execution_profile() -> str:
    return sanitize_execution_profile(os.environ.get(_PROFILE_ENV, ""))


# =============================================================================
# Paths
# =============================================================================
def _get_config_base_dir() -> Path:
    xdg = os.environ.get(_XDG_CONFIG_ENV, "").strip()
    return Path(xdg).expanduser() if xdg else Path.home() / ".config"


def get_runtime_profile_dir() -> Path:
    override = os.environ.get(_RUNTIME_CONFIG_ENV, "").strip()
    if override:
        return Path(override).expanduser().parent

    base = _get_config_base_dir() / _DEFAULT_CONFIG_DIR
    profile = get_execution_profile()
    if profile == _DEFAULT_PROFILE:
        return base
    return base / _PROFILES_DIRNAME / profile


def get_runtime_config_path() -> Path:
    override = os.environ.get(_RUNTIME_CONFIG_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    return get_runtime_profile_dir() / _DEFAULT_CONFIG_FILENAME


# =============================================================================
# Load / Save
# =============================================================================
def load_runtime_config_payload() -> dict[str, Any] | None:
    path = get_runtime_config_path()
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        return data
    except Exception as exc:  # noqa: BLE001
        logger.warning("[config.runtime] could not load %s: %s", path, exc)
        return None


def save_runtime_config_payload(data: dict[str, Any]) -> Path:
    """Atomic write to the configured path.

    Writes to a temp file in the same dir, then renames — avoids half-written
    JSON if the process is killed mid-write.
    """
    path = get_runtime_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmpname = tempfile.mkstemp(dir=str(path.parent), prefix=".rc-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmpname, path)
    except Exception:
        try:
            os.unlink(tmpname)
        except FileNotFoundError:
            pass
        raise

    # Tight perms — avoids accidentally world-readable api_keys during the
    # transition to secret_store (F2-T18).
    try:
        os.chmod(path, 0o600)
    except PermissionError:
        pass

    return path


# =============================================================================
# Checksum / Metadata
# =============================================================================
def get_runtime_config_checksum(data: dict[str, Any] | None = None) -> str | None:
    payload = data if data is not None else load_runtime_config_payload()
    if not isinstance(payload, dict):
        return None
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def get_runtime_config_metadata() -> dict[str, Any]:
    path = get_runtime_config_path()
    payload = load_runtime_config_payload()
    return {
        "profile": get_execution_profile(),
        "config_path": str(path),
        "config_exists": path.exists(),
        "config_sha256": get_runtime_config_checksum(payload),
    }
