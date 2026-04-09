"""
Interview Coach - LLM Adapter
Provides real LLM integration via Anthropic/OpenAI APIs
Falls back to demo mode when API keys are not configured
"""
import os
from typing import AsyncGenerator, Optional
from adapters.interfaces import LLMAdapter


class DemoLLMAdapter(LLMAdapter):
    """
    Demo LLM adapter that returns mock responses.
    Used when no API keys are configured.
    """
    
    async def generate(self, messages: list[dict], config: dict) -> str:
        """Generate a mock response"""
        # Extract the last user message for context
        last_message = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_message = msg.get("content", "")[:100]
                break
        
        return f"[Demo Mode] Based on your question about '{last_message}...', here's a mock response. Configure ANTHROPIC_API_KEY or OPENAI_API_KEY for real LLM responses."
    
    async def stream(self, messages: list[dict], config: dict) -> AsyncGenerator[str, None]:
        """Stream a mock response"""
        response = await self.generate(messages, config)
        # Simulate streaming by yielding words
        words = response.split()
        for i, word in enumerate(words):
            yield word + (" " if i < len(words) - 1 else "")
    
    async def count_tokens(self, text: str) -> int:
        """Approximate token count"""
        # Rough approximation: 1 token ≈ 4 characters
        return len(text) // 4


class AnthropicLLMAdapter(LLMAdapter):
    """
    Real LLM adapter using Anthropic Claude API.
    Requires ANTHROPIC_API_KEY environment variable.
    """
    
    def __init__(self, model: str = "claude-sonnet-4-20250514"):
        self.model = model
        self.api_key = os.getenv("ANTHROPIC_API_KEY")
        self._client = None
    
    def _get_client(self):
        """Lazy-load Anthropic client"""
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.AsyncAnthropic(api_key=self.api_key)
            except ImportError:
                raise RuntimeError("anthropic package not installed. Run: pip install anthropic")
        return self._client
    
    async def generate(self, messages: list[dict], config: dict) -> str:
        """Generate response using Claude"""
        client = self._get_client()
        
        # Extract system message if present
        system = None
        chat_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                system = msg.get("content", "")
            else:
                chat_messages.append(msg)
        
        response = await client.messages.create(
            model=self.model,
            max_tokens=config.get("max_tokens", 1024),
            temperature=config.get("temperature", 0.7),
            system=system,
            messages=chat_messages,
        )
        
        return response.content[0].text
    
    async def stream(self, messages: list[dict], config: dict) -> AsyncGenerator[str, None]:
        """Stream response using Claude"""
        client = self._get_client()
        
        # Extract system message if present
        system = None
        chat_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                system = msg.get("content", "")
            else:
                chat_messages.append(msg)
        
        async with client.messages.stream(
            model=self.model,
            max_tokens=config.get("max_tokens", 1024),
            temperature=config.get("temperature", 0.7),
            system=system,
            messages=chat_messages,
        ) as stream:
            async for text in stream.text_stream:
                yield text
    
    async def count_tokens(self, text: str) -> int:
        """Count tokens using Anthropic's tokenizer"""
        # Approximate: Claude uses ~3.5 chars per token
        return len(text) // 3.5


class OpenAILLMAdapter(LLMAdapter):
    """
    Real LLM adapter using OpenAI API.
    Requires OPENAI_API_KEY environment variable.
    """
    
    def __init__(self, model: str = "gpt-4o"):
        self.model = model
        self.api_key = os.getenv("OPENAI_API_KEY")
        self._client = None


class OllamaLLMAdapter(LLMAdapter):
    """
    Real LLM adapter using Ollama for local execution.
    Connects to a local Ollama server (default: http://localhost:11434).
    Does not require API keys - runs locally.
    """
    
    def __init__(self, model: str = "llama3.2", base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url
        self._client = None
    
    def _get_client(self):
        """Lazy-load Ollama client"""
        if self._client is None:
            try:
                import httpx
                self._client = httpx.AsyncClient(base_url=self.base_url, timeout=120.0)
            except ImportError:
                raise RuntimeError("httpx package not installed. Run: pip install httpx")
        return self._client
    
    async def generate(self, messages: list[dict], config: dict) -> str:
        """Generate response using Ollama"""
        client = self._get_client()
        
        # Convert messages to Ollama format
        ollama_messages = []
        for msg in messages:
            if msg.get("role") != "system":
                ollama_messages.append({
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", "")
                })
            else:
                # Prepend system message as first message
                ollama_messages.insert(0, {
                    "role": "system",
                    "content": msg.get("content", "")
                })
        
        response = await client.post(
            "/api/chat",
            json={
                "model": self.model,
                "messages": ollama_messages,
                "stream": False,
                "options": {
                    "temperature": config.get("temperature", 0.7),
                    "num_predict": config.get("max_tokens", 1024),
                }
            }
        )
        response.raise_for_status()
        data = response.json()
        return data.get("message", {}).get("content", "")
    
    async def stream(self, messages: list[dict], config: dict) -> AsyncGenerator[str, None]:
        """Stream response using Ollama"""
        client = self._get_client()
        
        # Convert messages to Ollama format
        ollama_messages = []
        for msg in messages:
            if msg.get("role") != "system":
                ollama_messages.append({
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", "")
                })
            else:
                ollama_messages.insert(0, {
                    "role": "system",
                    "content": msg.get("content", "")
                })
        
        async with client.stream(
            "POST",
            "/api/chat",
            json={
                "model": self.model,
                "messages": ollama_messages,
                "stream": True,
                "options": {
                    "temperature": config.get("temperature", 0.7),
                    "num_predict": config.get("max_tokens", 1024),
                }
            }
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.strip():
                    try:
                        import json
                        data = json.loads(line)
                        if "message" in data and "content" in data["message"]:
                            content = data["message"]["content"]
                            if content:
                                yield content
                    except json.JSONDecodeError:
                        continue
    
    async def count_tokens(self, text: str) -> int:
        """Approximate token count for Ollama models"""
        # Rough approximation: ~3.5 chars per token
        return len(text) // 3.5
    
    def _get_client(self):
        """Lazy-load OpenAI client"""
        if self._client is None:
            try:
                from openai import AsyncOpenAI
                self._client = AsyncOpenAI(api_key=self.api_key)
            except ImportError:
                raise RuntimeError("openai package not installed. Run: pip install openai")
        return self._client
    
    async def generate(self, messages: list[dict], config: dict) -> str:
        """Generate response using GPT"""
        client = self._get_client()
        
        response = await client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=config.get("max_tokens", 1024),
            temperature=config.get("temperature", 0.7),
        )
        
        return response.choices[0].message.content
    
    async def stream(self, messages: list[dict], config: dict) -> AsyncGenerator[str, None]:
        """Stream response using GPT"""
        client = self._get_client()
        
        stream = await client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=config.get("max_tokens", 1024),
            temperature=config.get("temperature", 0.7),
            stream=True,
        )
        
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    
    async def count_tokens(self, text: str) -> int:
        """Count tokens using tiktoken if available"""
        try:
            import tiktoken
            encoder = tiktoken.encoding_for_model(self.model)
            return len(encoder.encode(text))
        except ImportError:
            # Approximate: GPT uses ~4 chars per token
            return len(text) // 4


def _resolve_llm_provider_config(alias: str = "main") -> tuple[Optional[str], Optional[str]]:
    """Resolve LLM provider/model from provider registry configuration."""
    try:
        from adapters.provider_registry import get_registry

        cfg = get_registry().get_llm_config(alias=alias)
        provider = (cfg.provider or "").strip().lower() or None
        model = (cfg.model or "").strip() or None
        return provider, model
    except Exception as e:
        print(f"[LLMAdapter] Could not resolve provider config for alias '{alias}': {e}")
        return None, None


def _get_runtime_config() -> Optional[dict]:
    """Get runtime config from server if available."""
    try:
        from pathlib import Path
        import json
        config_path = Path(__file__).parent.parent / "runtime_config.json"
        if config_path.exists():
            with open(config_path, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"[LLMAdapter] Could not load runtime config: {e}")
    return None


def get_llm_adapter(alias: str = "main") -> Optional[LLMAdapter]:
    """
    Get the appropriate LLM adapter based on runtime config or environment.
    
    Priority:
    1. Runtime config (if enabled and valid)
    2. Environment variables (ANTHROPIC_API_KEY / OPENAI_API_KEY)
    3. None (caller should handle explicit error)
    
    Returns None if no valid configuration is found.
    """
    # Check runtime config first
    runtime_config = _get_runtime_config()
    if runtime_config and runtime_config.get("llm"):
        llm_config = runtime_config["llm"]
        if llm_config.get("enabled", False) and llm_config.get("api_key"):
            provider = llm_config.get("provider", "anthropic")
            model = llm_config.get("model", "claude-sonnet-4-20250514")
            api_key = llm_config["api_key"]

            # Check if runtime config key looks like a placeholder/test key
            # More comprehensive check for various placeholder patterns
            is_placeholder_key = (
                api_key.startswith("sk-test-") or
                api_key.startswith("sk-test-key") or
                api_key == "test-deepgram-key" or
                len(api_key) < 20 or  # Real keys are longer
                "test" in api_key.lower() or
                "placeholder" in api_key.lower()
            )

            print(f"[LLMAdapter] Runtime config found: provider={provider}, model={model}")
            print(f"[LLMAdapter] Runtime key check: length={len(api_key)}, is_placeholder={is_placeholder_key}")

            # Use env var if available and runtime config key is placeholder
            if provider == "anthropic":
                env_key = os.getenv("ANTHROPIC_API_KEY")
                final_key = env_key if is_placeholder_key else api_key
                print(f"[LLMAdapter] Env key present: {bool(env_key)}, Using env fallback: {is_placeholder_key}")
                if final_key:
                    adapter = AnthropicLLMAdapter(model=model)
                    adapter.api_key = final_key
                    source = "env" if is_placeholder_key else "runtime_config"
                    print(f"[LLMAdapter] Runtime config: provider=anthropic model={model} (key from {source})")
                    return adapter
                else:
                    print("[LLMAdapter] Warning: No valid Anthropic API key, falling through to env check...")
                    # Fall through to env var handling below
            elif provider == "openai":
                env_key = os.getenv("OPENAI_API_KEY")
                final_key = env_key if is_placeholder_key else api_key
                print(f"[LLMAdapter] Env key present: {bool(env_key)}, Using env fallback: {is_placeholder_key}")
                if final_key:
                    adapter = OpenAILLMAdapter(model=model)
                    adapter.api_key = final_key
                    source = "env" if is_placeholder_key else "runtime_config"
                    print(f"[LLMAdapter] Runtime config: provider=openai model={model} (key from {source})")
                    return adapter
                else:
                    print("[LLMAdapter] Warning: No valid OpenAI API key, falling through to env check...")
            
            elif provider == "ollama":
                # Ollama doesn't require API key - uses local server
                ollama_base_url = llm_config.get("base_url", "http://localhost:11434")
                adapter = OllamaLLMAdapter(model=model, base_url=ollama_base_url)
                print(f"[LLMAdapter] Runtime config: provider=ollama model={model} (base_url={ollama_base_url})")
                return adapter
    
    # Fall back to environment variables
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    preferred_provider, preferred_model = _resolve_llm_provider_config(alias=alias)

    def _anthropic_adapter() -> AnthropicLLMAdapter:
        return AnthropicLLMAdapter(model=preferred_model or "claude-sonnet-4-20250514")

    def _openai_adapter() -> OpenAILLMAdapter:
        return OpenAILLMAdapter(model=preferred_model or "gpt-4o")

    if preferred_provider == "anthropic":
        if anthropic_key:
            adapter = _anthropic_adapter()
            print(f"[LLMAdapter] Selected provider=anthropic model={adapter.model} (alias={alias})")
            return adapter
        print("[LLMAdapter] Preferred provider anthropic configured but ANTHROPIC_API_KEY is missing")

    if preferred_provider == "openai":
        if openai_key:
            adapter = _openai_adapter()
            print(f"[LLMAdapter] Selected provider=openai model={adapter.model} (alias={alias})")
            return adapter
        print("[LLMAdapter] Preferred provider openai configured but OPENAI_API_KEY is missing")

    # Fallback by key availability priority
    if anthropic_key:
        adapter = _anthropic_adapter()
        print(f"[LLMAdapter] Fallback selected provider=anthropic model={adapter.model}")
        return adapter

    if openai_key:
        adapter = _openai_adapter()
        print(f"[LLMAdapter] Fallback selected provider=openai model={adapter.model}")
        return adapter
    
    # Check for Ollama - doesn't require API key
    ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    if preferred_provider == "ollama" or (not anthropic_key and not openai_key):
        # If Ollama is the preferred or no keys are available, try Ollama
        if preferred_model:
            adapter = OllamaLLMAdapter(model=preferred_model, base_url=ollama_url)
            print(f"[LLMAdapter] Fallback selected provider=ollama model={adapter.model}")
            return adapter
        else:
            # Use default model if none specified
            adapter = OllamaLLMAdapter(model="llama3.2", base_url=ollama_url)
            print(f"[LLMAdapter] Fallback selected provider=ollama model={adapter.model}")
            return adapter
    
    return None


def get_llm_adapter_or_demo(alias: str = "main") -> LLMAdapter:
    """
    Get LLM adapter, falling back to demo mode if no API keys.
    DEPRECATED: Use get_llm_adapter() instead for explicit error handling.
    """
    adapter = get_llm_adapter(alias=alias)
    if adapter is None:
        return DemoLLMAdapter()
    return adapter


def get_llm_adapter_required(alias: str = "main") -> LLMAdapter:
    """
    Get LLM adapter, raising an error if no valid configuration.
    Use this when you need explicit error handling instead of silent fallback.
    """
    adapter = get_llm_adapter(alias=alias)
    if adapter is None:
        # Check runtime config for more specific error
        runtime_config = _get_runtime_config()
        if runtime_config and runtime_config.get("llm"):
            llm_config = runtime_config["llm"]
            if not llm_config.get("enabled"):
                raise ValueError("LLM is disabled in runtime configuration")
            if not llm_config.get("api_key"):
                raise ValueError("LLM API key not configured in runtime configuration")
        raise ValueError("No LLM configuration available. Set ANTHROPIC_API_KEY or OPENAI_API_KEY, or configure runtime config.")
    return adapter


# =====================
# MODEL DISCOVERY FUNCTIONS
# =====================

# Anthropic models (statically defined - these are the available models)
ANTHROPIC_MODELS = [
    {"id": "claude-sonnet-4-20250514", "name": "Claude Sonnet 4 (Latest)", "context_window": 200000},
    {"id": "claude-opus-4-20250514", "name": "Claude Opus 4", "context_window": 200000},
    {"id": "claude-3-5-sonnet-20241022", "name": "Claude 3.5 Sonnet", "context_window": 200000},
    {"id": "claude-3-5-haiku-20241022", "name": "Claude 3.5 Haiku", "context_window": 200000},
    {"id": "claude-3-haiku-20240307", "name": "Claude 3 Haiku", "context_window": 200000},
    {"id": "claude-3-sonnet-20240229", "name": "Claude 3 Sonnet", "context_window": 200000},
    {"id": "claude-3-opus-20240229", "name": "Claude 3 Opus", "context_window": 200000},
]

# OpenAI models (statically defined)
OPENAI_MODELS = [
    {"id": "gpt-4o", "name": "GPT-4o", "context_window": 128000},
    {"id": "gpt-4o-mini", "name": "GPT-4o Mini", "context_window": 128000},
    {"id": "gpt-4-turbo", "name": "GPT-4 Turbo", "context_window": 128000},
    {"id": "gpt-4", "name": "GPT-4", "context_window": 8192},
    {"id": "gpt-3.5-turbo", "name": "GPT-3.5 Turbo", "context_window": 16385},
    {"id": "o1", "name": "o1 (Reasoning)", "context_window": 128000},
    {"id": "o1-mini", "name": "o1 Mini (Reasoning)", "context_window": 128000},
]


async def list_anthropic_models() -> list[dict]:
    """List available Anthropic models"""
    return ANTHROPIC_MODELS


async def list_openai_models() -> list[dict]:
    """List available OpenAI models"""
    return OPENAI_MODELS


async def list_ollama_models(base_url: str = "http://localhost:11434") -> list[dict]:
    """
    List available Ollama models by querying the local Ollama server.
    Returns list of model info or empty list if Ollama is not available.
    """
    try:
        import httpx
        async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as client:
            response = await client.get("/api/tags")
            if response.status_code == 200:
                data = response.json()
                models = []
                for model in data.get("models", []):
                    models.append({
                        "id": model.get("name", ""),
                        "name": model.get("name", ""),
                        "size": model.get("size", 0),
                        "modified_at": model.get("modified_at", ""),
                    })
                return models
            return []
    except Exception as e:
        print(f"[LLMAdapter] Ollama not available: {e}")
        return []


async def check_ollama_available(base_url: str = "http://localhost:11434") -> bool:
    """Check if Ollama server is available"""
    try:
        import httpx
        async with httpx.AsyncClient(base_url=base_url, timeout=5.0) as client:
            response = await client.get("/api/tags")
            return response.status_code == 200
    except Exception:
        return False


# Unified model listing function
async def list_available_models(
    provider: Optional[str] = None,
    ollama_base_url: str = "http://localhost:11434"
) -> dict[str, list[dict]]:
    """
    List available models for all providers or a specific provider.
    
    Returns a dict with provider names as keys and lists of model info as values.
    """
    result = {}
    
    if provider is None or provider == "anthropic":
        result["anthropic"] = await list_anthropic_models()
    
    if provider is None or provider == "openai":
        result["openai"] = await list_openai_models()
    
    if provider is None or provider == "ollama":
        result["ollama"] = await list_ollama_models(ollama_base_url)
    
    return result
