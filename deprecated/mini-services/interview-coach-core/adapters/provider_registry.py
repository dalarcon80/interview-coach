"""
Interview Coach - Provider Registry
Resolves aliases to actual provider configurations
Supports environment variable overrides
"""
import os
import yaml
from pathlib import Path
from typing import Optional, Any
from contracts.models import ProviderConfig, ProviderRegistry, ProviderType


class ProviderRegistryService:
    """
    Manages provider resolution via aliases.
    Allows environment variable overrides.
    
    Example:
        PROVIDER_LLM_MAIN_MODEL=claude-opus-4-20250514
    """
    
    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or "config/providers.yaml"
        self._registry: Optional[ProviderRegistry] = None
        self._load_config()
    
    def _load_config(self) -> None:
        """Load providers.yaml configuration"""
        config_file = Path(self.config_path)
        
        if config_file.exists():
            with open(config_file, "r") as f:
                data = yaml.safe_load(f) or {}
            
            self._registry = ProviderRegistry(
                stt=self._parse_providers(data.get("stt", {})),
                llm=self._parse_providers(data.get("llm", {})),
                embedding=self._parse_providers(data.get("embedding", {})),
            )
        else:
            # Default configuration
            self._registry = self._create_default_registry()
    
    def _parse_providers(self, data: dict) -> dict[str, ProviderConfig]:
        """Parse provider configurations from YAML data"""
        result = {}
        for key, value in data.items():
            if isinstance(value, dict):
                config = ProviderConfig(
                    alias=value.get("alias", key),
                    provider=value.get("provider", "unknown"),
                    model=value.get("model", ""),
                    config=value.get("config", {}),
                )
                result[key] = config
        return result
    
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
                provider=provider_env,
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
