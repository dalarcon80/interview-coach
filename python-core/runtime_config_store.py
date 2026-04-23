from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

_PROFILE_ENV = "INTERVIEW_COACH_PROFILE"
_RUNTIME_CONFIG_ENV = "INTERVIEW_COACH_RUNTIME_CONFIG_PATH"
_XDG_CONFIG_ENV = "XDG_CONFIG_HOME"
_DEFAULT_CONFIG_DIR = "interview-coach"
_DEFAULT_CONFIG_FILENAME = "runtime_config.json"
_PROFILES_DIRNAME = "profiles"
_DEFAULT_PROFILE = "default"
_LEGACY_CONFIG_PATH = Path(__file__).with_name(_DEFAULT_CONFIG_FILENAME)


def _has_runtime_credentials(data: dict[str, Any]) -> bool:
    llm = data.get("llm") if isinstance(data.get("llm"), dict) else {}
    stt = data.get("stt") if isinstance(data.get("stt"), dict) else {}
    llm_api_key = str(llm.get("api_key", "")).strip()
    stt_api_key = str(stt.get("api_key", "")).strip()
    return bool(llm_api_key or stt_api_key)


def sanitize_execution_profile(value: str | None) -> str:
    cleaned = re.sub(r"[^a-z0-9._-]+", "-", str(value or "").strip().lower()).strip("._-")
    return cleaned or _DEFAULT_PROFILE


def get_execution_profile() -> str:
    return sanitize_execution_profile(os.environ.get(_PROFILE_ENV, ""))


def _get_config_base_dir() -> Path:
    xdg_config_home = os.environ.get(_XDG_CONFIG_ENV, "").strip()
    return Path(xdg_config_home).expanduser() if xdg_config_home else Path.home() / ".config"


def get_runtime_profile_dir() -> Path:
    override = os.environ.get(_RUNTIME_CONFIG_ENV, "").strip()
    if override:
        return Path(override).expanduser().parent

    base_dir = _get_config_base_dir() / _DEFAULT_CONFIG_DIR
    profile = get_execution_profile()
    if profile == _DEFAULT_PROFILE:
        return base_dir
    return base_dir / _PROFILES_DIRNAME / profile


def get_runtime_config_path() -> Path:
    override = os.environ.get(_RUNTIME_CONFIG_ENV, "").strip()
    if override:
        return Path(override).expanduser()

    return get_runtime_profile_dir() / _DEFAULT_CONFIG_FILENAME


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


def load_runtime_config_payload() -> dict[str, Any] | None:
    path = get_runtime_config_path()
    candidate_paths = [path]
    if path != _LEGACY_CONFIG_PATH:
        candidate_paths.append(_LEGACY_CONFIG_PATH)

    for candidate_path in candidate_paths:
        if not candidate_path.exists():
            continue
        try:
            with candidate_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                continue
            if candidate_path == _LEGACY_CONFIG_PATH and candidate_path != path:
                if not _has_runtime_credentials(data):
                    print(
                        "[RuntimeConfig] Skipping legacy migration because the legacy payload "
                        "does not contain runtime credentials."
                    )
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
            return data
        except Exception as exc:
            print(f"[RuntimeConfig] Could not load config from {candidate_path}: {exc}")
    return None


def save_runtime_config_payload(data: dict[str, Any]) -> Path:
    path = get_runtime_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return path
