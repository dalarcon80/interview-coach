"""
Interview Coach — config.providers

Loader for `config/providers.yaml`. Produces a typed in-memory registry:

    registry.stt["primary"].provider == "deepgram"

Env var overrides (per README comment in providers.yaml):
    PROVIDER_<KIND>_<ALIAS>_<FIELD>
    e.g. PROVIDER_LLM_MAIN_MODEL=claude-opus-4
         PROVIDER_STT_PRIMARY_PROVIDER=whisper_local

Field case is insensitive, aliases and kinds are uppercased for env lookup.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_PROVIDERS_YAML_ENV = "INTERVIEW_COACH_PROVIDERS_YAML"
_DEFAULT_PROVIDERS_YAML = Path("config") / "providers.yaml"


# =============================================================================
# Dataclasses
# =============================================================================
@dataclass
class ProviderEntry:
    alias: str
    provider: str
    model: str
    config: dict[str, Any] = field(default_factory=dict)
    dimensions: int | None = None  # embedding-specific


@dataclass
class ProviderRegistry:
    stt: dict[str, ProviderEntry] = field(default_factory=dict)
    llm: dict[str, ProviderEntry] = field(default_factory=dict)
    embedding: dict[str, ProviderEntry] = field(default_factory=dict)

    def for_kind(self, kind: str) -> dict[str, ProviderEntry]:
        return getattr(self, kind)


# =============================================================================
# Loader
# =============================================================================
def _resolve_yaml_path() -> Path:
    override = os.environ.get(_PROVIDERS_YAML_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    # Relative to repo root — the caller typically runs from python-core/
    # so we search both locations.
    candidates = [
        _DEFAULT_PROVIDERS_YAML,
        Path("..") / _DEFAULT_PROVIDERS_YAML,
        Path(__file__).resolve().parent.parent.parent / _DEFAULT_PROVIDERS_YAML,
    ]
    for c in candidates:
        if c.exists():
            return c
    return _DEFAULT_PROVIDERS_YAML


def _apply_env_overrides(kind: str, alias: str, entry: ProviderEntry) -> None:
    prefix = f"PROVIDER_{kind.upper()}_{alias.upper()}_"
    for env_name, env_val in os.environ.items():
        if not env_name.startswith(prefix):
            continue
        field_name = env_name[len(prefix) :].lower()
        if field_name in {"alias", "provider", "model"}:
            setattr(entry, field_name, env_val)
        elif field_name == "dimensions":
            try:
                entry.dimensions = int(env_val)
            except ValueError:
                logger.warning("[providers] invalid int for %s=%s", env_name, env_val)
        else:
            # Assume config.<field>
            entry.config[field_name] = _parse_scalar(env_val)


def _parse_scalar(value: str) -> Any:
    lv = value.lower()
    if lv in {"true", "yes", "on"}:
        return True
    if lv in {"false", "no", "off"}:
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def _entry_from_dict(alias: str, data: dict[str, Any]) -> ProviderEntry:
    return ProviderEntry(
        alias=str(data.get("alias", alias)),
        provider=str(data.get("provider", "")),
        model=str(data.get("model", "")),
        config=dict(data.get("config", {})),
        dimensions=data.get("dimensions"),
    )


@lru_cache(maxsize=1)
def load_registry() -> ProviderRegistry:
    """Load providers.yaml once, cached.

    Call `load_registry.cache_clear()` to force a reload (useful in tests).
    """
    path = _resolve_yaml_path()
    if not path.exists():
        logger.warning("[providers] %s not found; returning empty registry", path)
        return ProviderRegistry()

    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    registry = ProviderRegistry()
    providers = raw.get("providers", {})
    for kind in ("stt", "llm", "embedding"):
        kind_entries: dict[str, ProviderEntry] = {}
        for alias, entry_data in (providers.get(kind) or {}).items():
            if not isinstance(entry_data, dict):
                continue
            entry = _entry_from_dict(alias, entry_data)
            _apply_env_overrides(kind, alias, entry)
            kind_entries[alias] = entry
        setattr(registry, kind, kind_entries)

    logger.info(
        "[providers] loaded from %s — stt=%d llm=%d embedding=%d",
        path,
        len(registry.stt),
        len(registry.llm),
        len(registry.embedding),
    )
    return registry


def reload_registry() -> ProviderRegistry:
    """Force a fresh read, useful for tests and for /api/admin/reload-config."""
    load_registry.cache_clear()
    return load_registry()
