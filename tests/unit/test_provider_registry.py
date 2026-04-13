"""
Interview Coach - Unit Tests for Provider Registry
Tests for alias resolution and environment variable overrides
"""
import os
import pytest
from pathlib import Path
from unittest.mock import patch

from adapters.provider_registry import (
    ProviderRegistryService,
    get_registry,
)
from contracts.models import ProviderConfig, ProviderType


class TestProviderRegistryService:
    """Test ProviderRegistryService class"""
    
    def test_registry_initialization(self):
        """Test registry initializes with default config"""
        # Use a non-existent config path to trigger defaults
        registry = ProviderRegistryService(config_path="nonexistent_config.yaml")
        
        assert registry._registry is not None
        assert "primary" in registry._registry.stt
        assert "main" in registry._registry.llm
        assert "primary" in registry._registry.embedding
    
    def test_resolve_llm_config(self):
        """Test resolving LLM configuration"""
        registry = ProviderRegistryService(config_path="nonexistent_config.yaml")
        
        config = registry.resolve(ProviderType.LLM, "main")
        
        assert config.alias == "llm_main"
        assert config.provider == "anthropic"
        assert config.model == "claude-sonnet-4-20250514"
    
    def test_resolve_stt_config(self):
        """Test resolving STT configuration"""
        registry = ProviderRegistryService(config_path="nonexistent_config.yaml")
        
        config = registry.resolve(ProviderType.STT, "primary")
        
        assert config.alias == "stt_primary"
        assert config.provider == "deepgram"
        assert config.model == "nova-3"
    
    def test_resolve_embedding_config(self):
        """Test resolving embedding configuration"""
        registry = ProviderRegistryService(config_path="nonexistent_config.yaml")
        
        config = registry.resolve(ProviderType.EMBEDDING, "primary")
        
        assert config.alias == "embedding_primary"
        assert config.provider == "openai"
        assert config.model == "text-embedding-3-small"
    
    def test_resolve_unknown_alias_raises_error(self):
        """Test resolving unknown alias raises ValueError"""
        registry = ProviderRegistryService(config_path="nonexistent_config.yaml")
        
        with pytest.raises(ValueError, match="Unknown alias"):
            registry.resolve(ProviderType.LLM, "nonexistent")
    
    def test_get_llm_config_shortcut(self):
        """Test get_llm_config shortcut method"""
        registry = ProviderRegistryService(config_path="nonexistent_config.yaml")
        
        config = registry.get_llm_config("main")
        
        assert config.alias == "llm_main"
    
    def test_get_stt_config_shortcut(self):
        """Test get_stt_config shortcut method"""
        registry = ProviderRegistryService(config_path="nonexistent_config.yaml")
        
        config = registry.get_stt_config("primary")
        
        assert config.alias == "stt_primary"
    
    def test_get_embedding_config_shortcut(self):
        """Test get_embedding_config shortcut method"""
        registry = ProviderRegistryService(config_path="nonexistent_config.yaml")
        
        config = registry.get_embedding_config("primary")
        
        assert config.alias == "embedding_primary"


class TestProviderRegistryEnvOverrides:
    """Test environment variable overrides"""
    
    def test_model_override(self):
        """Test model override via environment variable"""
        with patch.dict(os.environ, {"PROVIDER_LLM_MAIN_MODEL": "claude-opus-4-20250514"}):
            registry = ProviderRegistryService(config_path="nonexistent_config.yaml")
            
            config = registry.resolve(ProviderType.LLM, "main")
            
            assert config.model == "claude-opus-4-20250514"
    
    def test_provider_override(self):
        """Test provider override via environment variable"""
        with patch.dict(os.environ, {"PROVIDER_STT_PRIMARY_PROVIDER": "whisper_local"}):
            registry = ProviderRegistryService(config_path="nonexistent_config.yaml")
            
            config = registry.resolve(ProviderType.STT, "primary")
            
            assert config.provider == "whisper_local"


class TestGlobalRegistry:
    """Test global registry functions"""
    
    def test_get_registry_singleton(self):
        """Test get_registry returns singleton"""
        # Reset the global registry
        import adapters.provider_registry as pr
        pr._registry = None
        
        registry1 = get_registry()
        registry2 = get_registry()
        
        assert registry1 is registry2


class TestProviderConfigFromFile:
    """Test loading provider config from actual file"""
    
    def test_load_from_providers_yaml(self):
        """Test loading configuration from providers.yaml"""
        registry = ProviderRegistryService(config_path="config/providers.yaml")
        
        assert registry._registry is not None
        
        # Check LLM config
        llm_config = registry.get_llm_config("main")
        assert llm_config.provider == "ollama"

        fast_llm_config = registry.get_llm_config("fast")
        assert fast_llm_config.provider == "anthropic"
        assert fast_llm_config.model == "claude-haiku-4-5-20251001"
        
        # Check STT config
        stt_config = registry.get_stt_config("primary")
        assert stt_config.provider == "deepgram"
        
        # Check embedding config
        embedding_config = registry.get_embedding_config("primary")
        assert embedding_config.provider == "openai"

    def test_default_config_resolves_from_python_core_cwd(self, monkeypatch):
        """Test default providers.yaml resolution is independent of process cwd."""
        repo_root = Path(__file__).resolve().parents[2]
        monkeypatch.chdir(repo_root / "python-core")

        registry = ProviderRegistryService()

        assert Path(registry.config_path).resolve() == repo_root / "config" / "providers.yaml"
        fast_llm_config = registry.get_llm_config("fast")
        assert fast_llm_config.provider == "anthropic"
        assert fast_llm_config.model == "claude-haiku-4-5-20251001"
