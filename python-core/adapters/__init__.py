"""
Interview Coach - Adapters Package
Provider interfaces and implementations
"""
from adapters.interfaces import (
    TranscriptionEvent,
    STTAdapter,
    LLMAdapter,
    EmbeddingAdapter,
)
from adapters.llm_adapter import (
    get_llm_adapter,
    get_llm_adapter_or_demo,
    DemoLLMAdapter,
    AnthropicLLMAdapter,
    OpenAILLMAdapter,
)

__all__ = [
    "TranscriptionEvent",
    "STTAdapter",
    "LLMAdapter",
    "EmbeddingAdapter",
    "get_llm_adapter",
    "get_llm_adapter_or_demo",
    "DemoLLMAdapter",
    "AnthropicLLMAdapter",
    "OpenAILLMAdapter",
]
