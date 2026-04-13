"""
Interview Coach - Provider Registry
Resolves aliases to actual provider configurations
Supports environment variable overrides
"""
import os
import yaml
from pathlib import Path
from typing import Optional
from contracts.models import ProviderConfig, ProviderRegistry, ProviderType


DEFAULT_CONFIG_PATH = "config/providers.yaml"


class ProviderRegistryService:
    """
    Manages provider resolution via aliases.
    Allows environment variable overrides.
    
    Example:
        PROVIDER_LLM_MAIN_MODEL=claude-opus-4-20250514
    """
    
    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or DEFAULT_CONFIG_PATH
        self._registry: Optional[ProviderRegistry] = None
        self._load_config()
    
    def _load_config(self) -> None:
        """Load providers.yaml configuration"""
        config_file = self._resolve_config_file(self.config_path)
        
        if config_file.exists():
            self.config_path = str(config_file)
            with open(config_file, "r") as f:
                data = yaml.safe_load(f) or {}
            
            # Handle providers: root key in YAML
            providers_data = data.get("providers", data)
            
            self._registry = ProviderRegistry(
                stt=self._parse_providers(providers_data.get("stt", {})),
                llm=self._parse_providers(providers_data.get("llm", {})),
                embedding=self._parse_providers(providers_data.get("embedding", {})),
            )
        else:
            # Default configuration
            self._registry = self._create_default_registry()

    def _resolve_config_file(self, config_path: str) -> Path:
        """Resolve the default providers file from the repo root, independent of cwd."""
        config_file = Path(config_path).expanduser()
        if config_file.exists() or config_file.is_absolute():
            return config_file

        if config_file.as_posix() != DEFAULT_CONFIG_PATH:
            return config_file

        search_roots: list[Path] = []
        cwd = Path.cwd().resolve()
        search_roots.extend([cwd, *cwd.parents])
        module_path = Path(__file__).resolve()
        search_roots.extend([module_path.parent, *module_path.parents])

        seen: set[Path] = set()
        for root in search_roots:
            if root in seen:
                continue
            seen.add(root)
            candidate = root / config_file
            if candidate.exists():
                return candidate
        return config_file
    
    def _parse_providers(self, data: dict) -> dict[str, ProviderConfig]:
        """Parse provider configurations from YAML data"""
        result = {}
        for key, value in data.items():
            if isinstance(value, dict):
                config_payload = dict(value.get("config", {}) or {})
                # Preserve non-standard top-level keys (e.g. embedding dimensions)
                for extra_key, extra_value in value.items():
                    if extra_key not in {"alias", "provider", "model", "config"}:
                        config_payload[extra_key] = extra_value

                config = ProviderConfig(
                    alias=value.get("alias", key),
                    provider=self._normalize_provider_name(value.get("provider", "unknown")),
                    model=value.get("model", ""),
                    config=config_payload,
                )
                result[key] = config
        return result

    @staticmethod
    def _normalize_provider_name(provider: str) -> str:
        """Normalize provider aliases to canonical names."""
        normalized = (provider or "").strip().lower()
        if normalized in {"anthropic", "claude", "claude3", "claude-3", "claude-sonnet"}:
            return "anthropic"
        if normalized in {"openai", "gpt", "chatgpt", "gpt4", "gpt-4", "gpt4o", "gpt-4o"}:
            return "openai"
        if normalized in {"ollama", "local", "llama", "llama3"}:
            return "ollama"
        return normalized or "unknown"
    
    def _create_default_registry(self) -> ProviderRegistry:
        """Create default provider registry"""
        return ProviderRegistry(
            stt={
                "primary": ProviderConfig(
                    alias="stt_primary",
                    provider="deepgram",
                    model="nova-3",
                    config={
                        "language": "multi",
                        "diarize": True,
                        "smart_format": True,
                        "utterance_end_ms": 1500,
                    }
                ),
                "fallback": ProviderConfig(
                    alias="stt_fallback",
                    provider="whisper_local",
                    model="medium",
                    config={}
                )
            },
            llm={
                "main": ProviderConfig(
                    alias="llm_main",
                    provider="anthropic",
                    model="claude-sonnet-4-20250514",
                    config={
                        "temperature": 0.3,
                        "max_tokens": 300,
                        "stream": True,
                    }
                ),
                "fast": ProviderConfig(
                    alias="llm_fast",
                    provider="anthropic",
                    model="claude-haiku-4-5-20251001",
                    config={
                        "temperature": 0.2,
                        "max_tokens": 150,
                        "stream": False,
                    }
                )
            },
            embedding={
                "primary": ProviderConfig(
                    alias="embedding_primary",
                    provider="openai",
                    model="text-embedding-3-small",
                    config={"dimensions": 1536}
                )
            }
        )
    
    def resolve(self, provider_type: ProviderType, alias: str) -> ProviderConfig:
        """
        Resolve an alias to a provider configuration.
        Applies environment variable overrides.
        
        Env var format: PROVIDER_{TYPE}_{ALIAS}_{FIELD}
        Example: PROVIDER_LLM_MAIN_MODEL=claude-opus-4-20250514
        """
        if self._registry is None:
            raise RuntimeError("Provider registry not initialized")
        
        registry_map = {
            ProviderType.STT: self._registry.stt,
            ProviderType.LLM: self._registry.llm,
            ProviderType.EMBEDDING: self._registry.embedding,
        }
        
        providers = registry_map.get(provider_type, {})
        config = providers.get(alias)
        
        if config is None:
            raise ValueError(f"Unknown alias: {provider_type.value}/{alias}")
        
        # Apply environment variable overrides
        config = self._apply_env_overrides(provider_type, alias, config)
        
        return config
    
    def _apply_env_overrides(
        self, 
        provider_type: ProviderType, 
        alias: str, 
        config: ProviderConfig
    ) -> ProviderConfig:
        """Apply environment variable overrides to configuration"""
        prefix = f"PROVIDER_{provider_type.value.upper()}_{alias.upper()}_"
        
        # Check for model override
        model_env = os.getenv(f"{prefix}MODEL")
        if model_env:
            config = ProviderConfig(
                alias=config.alias,
                provider=config.provider,
                model=model_env,
                config=config.config,
            )
        
        # Check for provider override
        provider_env = os.getenv(f"{prefix}PROVIDER")
        if provider_env:
            config = ProviderConfig(
                alias=config.alias,
                provider=self._normalize_provider_name(provider_env),
                model=config.model,
                config=config.config,
            )
        
        return config
    
    def get_llm_config(self, alias: str = "main") -> ProviderConfig:
        """Get LLM provider configuration"""
        return self.resolve(ProviderType.LLM, alias)
    
    def get_stt_config(self, alias: str = "primary") -> ProviderConfig:
        """Get STT provider configuration"""
        return self.resolve(ProviderType.STT, alias)
    
    def get_embedding_config(self, alias: str = "primary") -> ProviderConfig:
        """Get Embedding provider configuration"""
        return self.resolve(ProviderType.EMBEDDING, alias)


# Global instance
_registry: Optional[ProviderRegistryService] = None


def get_registry() -> ProviderRegistryService:
    """Get or create the global provider registry"""
    global _registry
    if _registry is None:
        _registry = ProviderRegistryService()
    return _registry
