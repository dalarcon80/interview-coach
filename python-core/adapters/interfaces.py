"""
Interview Coach - Provider Interfaces
Abstract base classes for STT, LLM, and Embedding providers
"""
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Optional
from pydantic import BaseModel, Field


class TranscriptionEvent(BaseModel):
    """A transcription event from the STT provider"""
    text: str
    is_final: bool = False
    confidence: float = 0.9
    language: str = "es"
    speaker: Optional[str] = None  # "interviewer" | "candidate"
    utterance_complete: bool = False
    event_type: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


class STTAdapter(ABC):
    """Abstract interface for Speech-to-Text providers"""
    
    @abstractmethod
    async def connect(self, config: dict, session_id: Optional[str] = None) -> None:
        """Establish connection to the STT service"""
        pass

    @abstractmethod
    async def open_stream(self, session_id: Optional[str] = None) -> None:
        """Open per-session streaming resources"""
        pass
    
    @abstractmethod
    async def stream_audio(
        self,
        audio_chunks: AsyncGenerator[bytes, None],
        session_id: Optional[str] = None,
    ) -> AsyncGenerator[TranscriptionEvent, None]:
        """Stream audio and receive transcription events"""
        pass

    @abstractmethod
    async def close_stream(self, session_id: Optional[str] = None) -> None:
        """Close per-session streaming resources"""
        pass
    
    @abstractmethod
    async def disconnect(self, session_id: Optional[str] = None) -> None:
        """Disconnect from the STT service"""
        pass


class LLMAdapter(ABC):
    """Abstract interface for Large Language Model providers"""
    
    @abstractmethod
    async def generate(
        self, 
        messages: list[dict], 
        config: dict
    ) -> str:
        """Generate a complete response"""
        pass
    
    @abstractmethod
    async def stream(
        self, 
        messages: list[dict], 
        config: dict
    ) -> AsyncGenerator[str, None]:
        """Stream response tokens"""
        pass
    
    @abstractmethod
    async def count_tokens(self, text: str) -> int:
        """Count tokens in text"""
        pass


class EmbeddingAdapter(ABC):
    """Abstract interface for Embedding providers"""
    
    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts"""
        pass
    
    @abstractmethod
    async def embed_single(self, text: str) -> list[float]:
        """Generate embedding for a single text"""
        pass
    
    @abstractmethod
    def get_dimensions(self) -> int:
        """Get the dimensionality of embeddings"""
        pass
