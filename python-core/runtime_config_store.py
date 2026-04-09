from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_RUNTIME_CONFIG_ENV = "INTERVIEW_COACH_RUNTIME_CONFIG_PATH"
_XDG_CONFIG_ENV = "XDG_CONFIG_HOME"
_DEFAULT_CONFIG_DIR = "interview-coach"
_DEFAULT_CONFIG_FILENAME = "runtime_config.json"
_LEGACY_CONFIG_PATH = Path(__file__).with_name(_DEFAULT_CONFIG_FILENAME)


def get_runtime_config_path() -> Path:
    override = os.environ.get(_RUNTIME_CONFIG_ENV, "").strip()
    if override:
        return Path(override).expanduser()

    xdg_config_home = os.environ.get(_XDG_CONFIG_ENV, "").strip()
    base_dir = Path(xdg_config_home).expanduser() if xdg_config_home else Path.home() / ".config"
    return base_dir / _DEFAULT_CONFIG_DIR / _DEFAULT_CONFIG_FILENAME


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
