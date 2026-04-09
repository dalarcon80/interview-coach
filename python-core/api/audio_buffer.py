"""
Interview Coach - Audio Buffer for Realtime STT

Handles buffering of incoming audio chunks and triggers STT processing.
"""
import asyncio
import base64
from collections import deque
from dataclasses import dataclass, field
from typing import Optional
import numpy as np


@dataclass
class AudioBuffer:
    """
    Accumulates audio chunks and triggers transcription when:
    - Buffer exceeds max_size bytes
    - Silence is detected for threshold duration
    """
    max_size_bytes: int = 16000 * 2 * 2  # ~2 seconds of 16kHz 16-bit mono
    silence_threshold: float = 0.01  # RMS amplitude threshold for silence
    min_buffer_ms: int = 500  # Minimum buffer before triggering (500ms)
    
    _buffer: deque = field(default_factory=deque)
    _sample_rate: int = 16000
    _channels: int = 1
    _last_audio_ms: float = 0
    
    def add_chunk(self, audio_base64: str, timestamp_ms: int) -> Optional[bytes]:
        """
        Add an audio chunk to the buffer.
        Returns audio bytes if buffer should be flushed, None otherwise.
        """
        try:
            audio_bytes = base64.b64decode(audio_base64)
        except Exception:
            return None
        
        self._buffer.append(audio_bytes)
        self._last_audio_ms = timestamp_ms
        
        # Check if we should flush
        total_size = sum(len(chunk) for chunk in self._buffer)
        
        # Flush if buffer exceeds max size
        if total_size >= self.max_size_bytes:
            return self._flush()
        
        # Flush if enough time has passed (at least min_buffer_ms)
        if timestamp_ms >= self.min_buffer_ms and len(self._buffer) > 0:
            # Check for silence in recent chunks
            if self._is_silent_recent():
                return self._flush()
        
        return None
    
    def _is_silent_recent(self) -> bool:
        """Check if recent audio is mostly silence."""
        if not self._buffer:
            return False
        
        # Check last 2 chunks (roughly 200ms)
        recent_chunks = list(self._buffer)[-2:]
        for chunk in recent_chunks:
            # Convert to numpy array and calculate RMS
            try:
                samples = np.frombuffer(chunk, dtype=np.int16)
                if len(samples) > 0:
                    rms = np.sqrt(np.mean(samples.astype(np.float32) ** 2))
                    if rms > self.silence_threshold * 32768:
                        return False
            except Exception:
                continue
        
        return True
    
    def _flush(self) -> Optional[bytes]:
        """Flush the buffer and return combined audio."""
        if not self._buffer:
            return None
        
        combined = b''.join(self._buffer)
        self._buffer.clear()
        return combined
    
    def reset(self):
        """Clear the buffer."""
        self._buffer.clear()
    
    @property
    def is_empty(self) -> bool:
        return len(self._buffer) == 0
    
    @property
    def size_bytes(self) -> int:
        return sum(len(chunk) for chunk in self._buffer)


class SessionAudioManager:
    """
    Manages audio buffers for multiple WebSocket sessions.
    """
    
    def __init__(self):
        self._buffers: dict[str, AudioBuffer] = {}
    
    def get_buffer(self, session_id: str) -> AudioBuffer:
        """Get or create buffer for a session."""
        if session_id not in self._buffers:
            self._buffers[session_id] = AudioBuffer()
        return self._buffers[session_id]
    
    def remove_buffer(self, session_id: str):
        """Remove buffer for a session."""
        if session_id in self._buffers:
            del self._buffers[session_id]
    
    def has_session(self, session_id: str) -> bool:
        """Check if session has a buffer."""
        return session_id in self._buffers


# Global session audio manager
_session_audio_manager: Optional[SessionAudioManager] = None


def get_session_audio_manager() -> SessionAudioManager:
    """Get the global session audio manager."""
    global _session_audio_manager
    if _session_audio_manager is None:
        _session_audio_manager = SessionAudioManager()
    return _session_audio_manager
