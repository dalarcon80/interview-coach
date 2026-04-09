"""
Interview Coach - Mock Adapters
For demo and testing purposes
"""
import random
import time
from typing import AsyncGenerator
from adapters.interfaces import STTAdapter, LLMAdapter, EmbeddingAdapter, TranscriptionEvent


class MockLLMAdapter(LLMAdapter):
    """Mock LLM adapter for demo purposes"""
    
    def __init__(self):
        self.call_count = 0
    
    async def generate(self, messages: list[dict], config: dict) -> str:
        """Generate a mock response"""
        self.call_count += 1
        
        # Simulate latency
        await asyncio.sleep(random.uniform(0.1, 0.3))
        
        # Get the question from messages
        question = ""
        for msg in messages:
            if msg.get("role") == "user":
                question = msg.get("content", "")
                break
        
        # Generate contextual mock response
        if "bullets" in question.lower() or "bullets" in str(messages):
            return self._generate_mock_bullets(question)
        else:
            return self._generate_mock_response(question)
    
    def _generate_mock_bullets(self, question: str) -> str:
        """Generate mock bullet points"""
        bullets = [
            "• Mi experiencia liderando equipos técnicos de hasta 8 personas",
            "• Implementé un pipeline CI/CD que redujo el tiempo de deployment en un 60%",
            "• Arquitecturé una solución de microservicios que maneja 10M+ requests/día",
        ]
        return "\n".join(bullets)
    
    def _generate_mock_response(self, question: str) -> str:
        """Generate a mock full response"""
        return """En mi rol como Senior Engineer en mi empresa anterior, lideré la migración de un sistema monolítico a una arquitectura de microservicios. 

Trabajé con un equipo de 5 ingenieros para diseñar e implementar la nueva arquitectura. Utilizamos Kubernetes para orquestación y redujimos el tiempo de deployment de 2 horas a solo 15 minutos, un improvement del 87%.

Este proyecto resultó en una mejora del 40% en la disponibilidad del sistema y nos permitió escalar horizontalmente durante picos de tráfico."""


class MockEmbeddingAdapter(EmbeddingAdapter):
    """Mock embedding adapter"""
    
    def __init__(self, dimensions: int = 1536):
        self.dimensions = dimensions
    
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate mock embeddings"""
        await asyncio.sleep(0.01)
        return [self._generate_vector() for _ in texts]
    
    async def embed_single(self, text: str) -> list[float]:
        """Generate mock embedding for single text"""
        await asyncio.sleep(0.01)
        return self._generate_vector()
    
    def get_dimensions(self) -> int:
        return self.dimensions
    
    def _generate_vector(self) -> list[float]:
        """Generate a random normalized vector"""
        vector = [random.gauss(0, 1) for _ in range(self.dimensions)]
        magnitude = sum(x * x for x in vector) ** 0.5
        return [x / magnitude for x in vector]


class MockSTTAdapter(STTAdapter):
    """Mock STT adapter for demo purposes"""
    
    def __init__(self):
        self.connected = False
    
    async def connect(self, config: dict) -> None:
        self.connected = True
    
    async def stream_audio(
        self, 
        audio_chunks: AsyncGenerator[bytes, None]
    ) -> AsyncGenerator[TranscriptionEvent, None]:
        """Mock transcription stream"""
        # Simulate transcription of pre-defined text
        mock_texts = [
            "¿Puedes contarme",
            " sobre tu experiencia",
            " liderando equipos técnicos?",
        ]
        
        for text in mock_texts:
            await asyncio.sleep(0.5)
            yield TranscriptionEvent(
                text=text,
                is_final=False,
                confidence=0.9,
                language="es",
            )
        
        # Final
        yield TranscriptionEvent(
            text="¿Puedes contarme sobre tu experiencia liderando equipos técnicos?",
            is_final=True,
            confidence=0.95,
            language="es",
        )
    
    async def disconnect(self) -> None:
        self.connected = False


# Import asyncio for sleep
import asyncio
