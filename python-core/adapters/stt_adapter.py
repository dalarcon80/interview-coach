"""
Interview Coach - STT Adapter Implementation
Streaming Speech-to-Text with Deepgram and mock fallback
"""
import os
import asyncio
import json
import contextlib
from time import perf_counter
from typing import AsyncGenerator, Optional

import websockets

from adapters.interfaces import STTAdapter, TranscriptionEvent
from adapters.provider_registry import get_registry, ProviderConfig
from runtime_config_store import load_runtime_config_payload
from runtime_flags import audio_pipeline_tracing_enabled


class MockSTTAdapter(STTAdapter):
    """
    Mock STT adapter for testing and development.
    Returns mock transcription events.
    """
    
    def __init__(self):
        self._connected = False
        self._session_id: str = "unknown"
        self._lifecycle_started_at: Optional[float] = None
    
    async def connect(self, config: dict, session_id: Optional[str] = None) -> None:
        if session_id:
            self._session_id = str(session_id)
        self._connected = True

    async def open_stream(self, session_id: Optional[str] = None) -> None:
        if session_id:
            self._session_id = str(session_id)
        if self._lifecycle_started_at is not None:
            return
        self._lifecycle_started_at = perf_counter()
        print(f"[STT][LIFECYCLE] stream_open session_id={self._session_id}")
    
    async def stream_audio(
        self,
        audio_chunks: AsyncGenerator[bytes, None],
        session_id: Optional[str] = None,
    ) -> AsyncGenerator[TranscriptionEvent, None]:
        """Mock streaming - returns simulated transcription"""
        if not self._connected:
            raise RuntimeError("STT adapter not connected")

        await self.open_stream(session_id=session_id)
        
        # Simulate transcription events
        mock_texts = [
            ("Hello, this is a", False),
            ("Hello, this is a test", False),
            ("Hello, this is a test transcription.", True),
        ]
        
        for text, is_final in mock_texts:
            yield TranscriptionEvent(
                text=text,
                is_final=is_final,
                confidence=0.95,
                language="en",
                speaker="unknown",
            )
            await asyncio.sleep(0.1)
    
    async def close_stream(self, session_id: Optional[str] = None) -> None:
        if session_id:
            self._session_id = str(session_id)
        if self._lifecycle_started_at is None:
            return
        duration_ms = None
        if self._lifecycle_started_at is not None:
            duration_ms = int((perf_counter() - self._lifecycle_started_at) * 1000)
        print(
            "[STT][LIFECYCLE] stream_close "
            f"session_id={self._session_id} "
            f"duration_ms={duration_ms if duration_ms is not None else 'unknown'}"
        )
        self._lifecycle_started_at = None

    async def disconnect(self, session_id: Optional[str] = None) -> None:
        if self._lifecycle_started_at is not None:
            await self.close_stream(session_id=session_id)
        self._connected = False


class WhisperLocalSTTAdapter(STTAdapter):
    """
    Local Whisper STT adapter using faster-whisper.
    Works offline without external API, optimized for Apple Silicon (M1-M5).
    """
    
    def __init__(self, model_size: str = "small"):
        self._model_size = model_size
        self._model = None
        self._connected = False
        self._session_id: str = "unknown"
        self._lifecycle_started_at: Optional[float] = None
        self._stream_started_at: Optional[float] = None
    
    async def connect(self, config: dict, session_id: Optional[str] = None) -> None:
        """Load Whisper model (CPU with int8 for speed)"""
        if session_id:
            self._session_id = str(session_id)
        
        try:
            from faster_whisper import WhisperModel
            # Use int8 for speed, CPU (Metal GPU will be used automatically on Apple Silicon)
            self._model = WhisperModel(
                self._model_size,
                device="cpu",
                compute_type="int8"
            )
            self._connected = True
            print(f"[STT][WhisperLocal] Model '{self._model_size}' loaded successfully")
        except ImportError:
            print("[STT][WhisperLocal] ERROR: faster-whisper not installed. Run: pip install faster-whisper")
            raise RuntimeError("faster-whisper not installed. Install with: pip install faster-whisper")
        except Exception as e:
            print(f"[STT][WhisperLocal] ERROR loading model: {e}")
            raise
    
    async def open_stream(self, session_id: Optional[str] = None) -> None:
        if session_id:
            self._session_id = str(session_id)
        if self._lifecycle_started_at is not None:
            return
        self._lifecycle_started_at = perf_counter()
        self._stream_started_at = perf_counter()
        print(f"[STT][WhisperLocal][LIFECYCLE] stream_open session_id={self._session_id}")
    
    async def stream_audio(
        self,
        audio_chunks: AsyncGenerator[bytes, None],
        session_id: Optional[str] = None,
    ) -> AsyncGenerator[TranscriptionEvent, None]:
        """Stream audio through local Whisper model with time-based processing"""
        if not self._connected:
            raise RuntimeError("WhisperLocal STT adapter not connected")
        
        if session_id:
            self._session_id = str(session_id)
        
        await self.open_stream(session_id=session_id)
        
        # Buffer for accumulating audio
        audio_buffer = b""
        sample_rate = 16000  # Whisper expects 16kHz
        
        # Time-based processing: process every N seconds
        # Partial: every 1 second for real-time display  
        # Final: every 4 seconds for coach (consolidated)
        partial_interval_samples = sample_rate * 1  # 1 second
        final_interval_samples = sample_rate * 4    # 4 seconds
        
        async for chunk in audio_chunks:
            audio_buffer += chunk
            
            current_samples = len(audio_buffer) // 2  # 2 bytes per sample
            
            # Process for partial display every 1 second
            if current_samples >= partial_interval_samples:
                try:
                    import numpy as np
                    audio_np = np.frombuffer(audio_buffer, dtype=np.int16).astype(np.float32) / 32768.0
                    
                    segments, info = self._model.transcribe(
                        audio_np,
                        beam_size=1,
                        vad_filter=False,
                    )
                    
                    # Get all text
                    text_parts = []
                    for segment in segments:
                        text = segment.text.strip()
                        if text:
                            text_parts.append(text)
                    
                    consolidated_text = " ".join(text_parts).strip()
                    
                    if consolidated_text:
                        # Determine final vs partial based on buffer size
                        is_final = current_samples >= final_interval_samples
                        
                        yield TranscriptionEvent(
                            text=consolidated_text,
                            is_final=is_final,
                            confidence=info.language_probability,
                            language=info.language or "en",
                            speaker="interviewer",
                        )
                    
                    # Keep overlap for continuity - 0.3 seconds
                    overlap_samples = sample_rate * 0.3
                    overlap_bytes = int(overlap_samples * 2)
                    if len(audio_buffer) > overlap_bytes:
                        audio_buffer = audio_buffer[-overlap_bytes:]
                    else:
                        audio_buffer = b""
                    
                except Exception as e:
                    print(f"[STT][WhisperLocal] Transcription error: {e}")
                    # Clear buffer on error to avoid stuck state
                    audio_buffer = b""
                    continue
        
        # Process remaining buffer as final when session ends
        if audio_buffer and (len(audio_buffer) // 2) >= sample_rate * 0.5:
            try:
                import numpy as np
                audio_np = np.frombuffer(audio_buffer, dtype=np.int16).astype(np.float32) / 32768.0
                
                segments, info = self._model.transcribe(
                    audio_np,
                    beam_size=1,
                    vad_filter=False,
                )
                
                text_parts = []
                for segment in segments:
                    text = segment.text.strip()
                    if text:
                        text_parts.append(text)
                
                consolidated_text = " ".join(text_parts).strip()
                
                if consolidated_text:
                    yield TranscriptionEvent(
                        text=consolidated_text,
                        is_final=True,
                        confidence=info.language_probability,
                        language=info.language or "en",
                        speaker="interviewer",
                    )
            except Exception as e:
                print(f"[STT][WhisperLocal] Final transcription error: {e}")
    
    async def close_stream(self, session_id: Optional[str] = None) -> None:
        if session_id:
            self._session_id = str(session_id)
        if self._lifecycle_started_at is None:
            return
        duration_ms = None
        if self._stream_started_at is not None:
            duration_ms = int((perf_counter() - self._stream_started_at) * 1000)
        print(
            "[STT][WhisperLocal][LIFECYCLE] stream_close "
            f"session_id={self._session_id} "
            f"duration_ms={duration_ms if duration_ms is not None else 'unknown'}"
        )
        self._lifecycle_started_at = None
        self._stream_started_at = None
    
    async def disconnect(self, session_id: Optional[str] = None) -> None:
        if self._lifecycle_started_at is not None:
            await self.close_stream(session_id=session_id)
        self._model = None
        self._connected = False


class DeepgramSTTAdapter(STTAdapter):
    """
    Deepgram STT adapter for streaming transcription.
    Uses Nova-3 multilingual model with code-switching support.
    """
    
    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or os.getenv("DEEPGRAM_API_KEY")
        self._connected = False
        self._config: dict = {}
        self._websocket = None
        self._ws_url: Optional[str] = None
        self._ws_headers: list[tuple[str, str]] = []
        self._language = "multi"
        self._diarize = True
        self._smart_format = True
        self._utterance_end_ms = 2500
        self._deepgram_request_id: Optional[str] = None
        self._first_event_type: Optional[str] = None
        self._first_partial_logged = False
        self._final_logged = False
        self._utterance_end_logged = False
        self._session_id: str = "unknown"
        self._keepalive_count: int = 0
        self._finalize_sent_at_ms: Optional[int] = None
        self._close_stream_sent_at_ms: Optional[int] = None
        self._stream_started_at: Optional[float] = None
        self._received_utterance_complete: bool = False
        self._close_sent: bool = False
        self._downstream_completed: bool = False
        self._terminal_failure: bool = False
        self._terminal_failure_reason: Optional[str] = None
        self._active_session_id: Optional[str] = None
        self._lifecycle_started_at: Optional[float] = None

    def set_session_context(self, session_id: str) -> None:
        """Attach app session context for correlation logs."""
        self._session_id = str(session_id or "unknown")

    def _elapsed_ms(self) -> int:
        if self._stream_started_at is None:
            return 0
        return int((perf_counter() - self._stream_started_at) * 1000)

    def _reset_stream_state(self) -> None:
        self._deepgram_request_id = None
        self._first_event_type = None
        self._first_partial_logged = False
        self._final_logged = False
        self._utterance_end_logged = False
        self._keepalive_count = 0
        self._finalize_sent_at_ms = None
        self._close_stream_sent_at_ms = None
        self._stream_started_at = None
        self._received_utterance_complete = False
        self._close_sent = False
        self._downstream_completed = False
        self._terminal_failure = False
        self._terminal_failure_reason = None

    def mark_downstream_complete(self) -> None:
        """Signal that transcript -> analysis -> suggestion completed."""
        if self._downstream_completed:
            return
        self._downstream_completed = True
        print(
            "[STT][Deepgram] "
            f"session_id={self._session_id} downstream_complete_ms={self._elapsed_ms()}"
        )

    def mark_terminal_failure(self, reason: str) -> None:
        """Signal terminal failure so stream close is allowed without suggestion."""
        self._terminal_failure = True
        self._terminal_failure_reason = str(reason or "unknown")
        print(
            "[STT][Deepgram] "
            f"session_id={self._session_id} terminal_failure reason={self._terminal_failure_reason} "
            f"timestamp_ms={self._elapsed_ms()}"
        )
    
    async def connect(self, config: dict, session_id: Optional[str] = None) -> None:
        """
        Connect to Deepgram streaming API.
        
        Config options:
        - language: "multi" for multilingual, "en", "es", etc.
        - diarize: bool (speaker diarization)
        - smart_format: bool (punctuation, formatting)
        - utterance_end_ms: int (silence threshold for utterance end)
        """
        if not self._api_key:
            raise ValueError("DEEPGRAM_API_KEY not configured")

        if session_id:
            self.set_session_context(session_id)
        
        self._config = config or {}
        self._language = str(self._config.get("language", "multi"))
        self._diarize = bool(self._config.get("diarize", True))
        self._smart_format = bool(self._config.get("smart_format", True))
        self._utterance_end_ms = int(self._config.get("utterance_end_ms", 1500))
        # DUAL_STT_PHASE4: Add endpointing for faster speech boundary detection
        self._endpointing_ms = int(self._config.get("endpointing_ms", 400))

        # L2-STT-07 stabilization baseline:
        # - Single websocket path only: /v1/listen
        # - Single model only: nova-3
        # - Raw audio contract: linear16/16kHz/mono must match payload
        query_parts = [
            "encoding=linear16",
            "sample_rate=16000",
            "channels=1",
            "model=nova-3",
            f"diarize={'true' if self._diarize else 'false'}",
            f"smart_format={'true' if self._smart_format else 'false'}",
            "utterances=true",
            "punctuate=true",
            f"utterance_end_ms={self._utterance_end_ms}",
            f"endpointing={self._endpointing_ms}",  # DUAL_STT_PHASE4: Faster speech-to-silence detection
            "interim_results=true",
            "multichannel=true",  # Enable multichannel for better speaker separation
            "numerals=true",  # Better number formatting
        ]
        if self._language and self._language != "multi":
            query_parts.append(f"language={self._language}")

        self._ws_url = f"wss://api.deepgram.com/v1/listen?{'&'.join(query_parts)}"
        self._ws_headers = [("Authorization", f"Token {self._api_key}")]
        print(
            "[STT][Deepgram] connect "
            f"session_id={self._session_id} "
            "endpoint=/v1/listen model=nova-3 encoding=linear16 sample_rate=16000 channels=1"
        )

        # Keep connect lightweight/truthful (validate configuration + auth presence).
        # Persistent websocket is opened in stream_audio() for the active stream.
        self._connected = True

    async def open_stream(self, session_id: Optional[str] = None) -> None:
        if session_id:
            self.set_session_context(session_id)

        target_session_id = self._session_id

        if not self._connected:
            raise RuntimeError("STT adapter not connected")

        if self._active_session_id and self._active_session_id != self._session_id:
            print(
                "[STT][LIFECYCLE] stream_open_replace "
                f"session_id={self._session_id} previous_session_id={self._active_session_id}"
            )
            await self.close_stream(self._active_session_id)
            self.set_session_context(target_session_id)

        if self._lifecycle_started_at is not None and self._active_session_id == self._session_id:
            return

        self._active_session_id = self._session_id
        self._lifecycle_started_at = perf_counter()
        self._reset_stream_state()
        print(f"[STT][LIFECYCLE] stream_open session_id={self._session_id}")

    async def _ensure_websocket(self):
        """Ensure websocket exists and is open for streaming session reuse."""
        if self._websocket and not getattr(self._websocket, "closed", False):
            return self._websocket

        if not self._ws_url:
            raise RuntimeError("Deepgram websocket URL is not initialized. Call connect() first.")

        self._websocket = await websockets.connect(
            self._ws_url,
            additional_headers=self._ws_headers,
            ping_interval=20,
            ping_timeout=20,
            max_size=10 * 1024 * 1024,
        )
        return self._websocket

    async def _recv_messages_until_close(self, ws):
        """Receive Deepgram websocket messages until close/utterance end."""
        while True:
            raw = await ws.recv()
            if isinstance(raw, bytes):
                continue
            payload = json.loads(raw)
            event_type = str(payload.get("type", "")).lower()
            if event_type in {"close", "closed"}:
                break
            yield payload

    def _handle_provider_event_logs(self, payload: dict) -> None:
        """Log first Deepgram event/request correlation + key lifecycle events."""
        event_type_raw = str(payload.get("type", "")) or "Unknown"
        event_type = event_type_raw.strip() or "Unknown"

        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        request_id = (
            payload.get("request_id")
            or payload.get("requestId")
            or metadata.get("request_id")
            or metadata.get("requestId")
        )

        if request_id and request_id != self._deepgram_request_id:
            self._deepgram_request_id = str(request_id)
            print(
                "[STT][Deepgram] "
                f"session_id={self._session_id} request_id={self._deepgram_request_id}"
            )

        if self._first_event_type is None:
            self._first_event_type = event_type
            print(
                "[STT][Deepgram] "
                f"session_id={self._session_id} "
                f"first_event_type={self._first_event_type} "
                f"request_id={self._deepgram_request_id or 'unknown'}"
            )
    
    async def stream_audio(
        self,
        audio_chunks: AsyncGenerator[bytes, None],
        session_id: Optional[str] = None,
    ) -> AsyncGenerator[TranscriptionEvent, None]:
        """
        Stream audio to Deepgram and yield transcription events.
        
        Audio should be:
        - PCM 16-bit signed little-endian
        - 16kHz sample rate
        - Mono channel
        """
        if session_id:
            self.set_session_context(session_id)

        if not self._connected:
            raise RuntimeError("STT adapter not connected")

        captured_audio = bytearray()

        ws = None
        send_completed = False
        finalized = False
        close_allowed = False
        receive_done = False

        try:
            if self._lifecycle_started_at is None:
                await self.open_stream(self._session_id)

            self._reset_stream_state()
            self._stream_started_at = perf_counter()

            ws = await self._ensure_websocket()

            def _now_ms() -> int:
                if self._stream_started_at is None:
                    return 0
                return int((perf_counter() - self._stream_started_at) * 1000)

            last_audio_sent_at_ms: Optional[int] = None
            first_audio_sent_at_ms: Optional[int] = None
            last_keepalive_sent_at_ms: Optional[int] = None

            async def _send_audio_task():
                nonlocal send_completed, last_audio_sent_at_ms, first_audio_sent_at_ms
                async for chunk in audio_chunks:
                    if not chunk:
                        continue
                    captured_audio.extend(chunk)
                    now_ms = _now_ms()
                    interval_ms = (
                        0 if last_audio_sent_at_ms is None else max(0, now_ms - last_audio_sent_at_ms)
                    )
                    await ws.send(chunk)
                    last_audio_sent_at_ms = now_ms

                    if first_audio_sent_at_ms is None:
                        first_audio_sent_at_ms = now_ms
                        if audio_pipeline_tracing_enabled():
                            if first_audio_sent_at_ms > 500:
                                print(
                                    "[STT][Deepgram] "
                                    f"session_id={self._session_id} first_audio_delay_ms={first_audio_sent_at_ms} "
                                    "warning=initial_audio_delay_exceeded"
                                )
                            else:
                                print(
                                    "[STT][Deepgram] "
                                    f"session_id={self._session_id} first_audio_delay_ms={first_audio_sent_at_ms}"
                                )

                    cadence_drift_ms = interval_ms - 100 if interval_ms else 0
                    if audio_pipeline_tracing_enabled():
                        if interval_ms > 200:
                            print(
                                "[STT][Deepgram] "
                                f"session_id={self._session_id} audio_gap_ms={interval_ms} "
                                "warning=cadence_gap_exceeded"
                            )
                        print(
                            "[STT][Deepgram] "
                            f"session_id={self._session_id} audio_sent_ms={now_ms} "
                            f"interval_ms={interval_ms} drift_ms={cadence_drift_ms} bytes={len(chunk)}"
                        )
                send_completed = True

            async def _keepalive_task():
                nonlocal finalized, last_keepalive_sent_at_ms
                while not receive_done:
                    await asyncio.sleep(0.5)
                    if receive_done:
                        break
                    now_ms = _now_ms()
                    idle_ms = now_ms if last_audio_sent_at_ms is None else max(0, now_ms - last_audio_sent_at_ms)
                    if idle_ms < 1000:
                        continue
                    if last_keepalive_sent_at_ms is not None and now_ms - last_keepalive_sent_at_ms < 1000:
                        continue
                    try:
                        await ws.send(json.dumps({"type": "KeepAlive"}))
                        self._keepalive_count += 1
                        last_keepalive_sent_at_ms = now_ms
                        if audio_pipeline_tracing_enabled():
                            print(
                                "[STT][Deepgram] "
                                f"session_id={self._session_id} keepalive_count={self._keepalive_count} "
                                f"timestamp_ms={now_ms} idle_ms={idle_ms}"
                            )
                    except Exception:
                        break

            async def _send_finalize_once():
                nonlocal finalized
                if finalized:
                    return
                with contextlib.suppress(Exception):
                    await ws.send(json.dumps({"type": "Finalize"}))
                finalized = True
                self._finalize_sent_at_ms = _now_ms()
                print(
                    "[STT][Deepgram] "
                    f"session_id={self._session_id} finalize_sent_ms={self._finalize_sent_at_ms}"
                )

            async def _send_close_stream_once():
                if self._close_sent:
                    return
                with contextlib.suppress(Exception):
                    await ws.send(json.dumps({"type": "CloseStream"}))
                self._close_sent = True
                self._close_stream_sent_at_ms = _now_ms()
                print(
                    "[STT][Deepgram] "
                    f"session_id={self._session_id} close_stream_sent_ms={self._close_stream_sent_at_ms}"
                )

            send_task = asyncio.create_task(_send_audio_task())
            keepalive_task = asyncio.create_task(_keepalive_task())
            idle_after_send_ticks = 0
            finalize_idle_ticks = 0

            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    inactivity_ms = None
                    if last_audio_sent_at_ms is not None:
                        inactivity_ms = _now_ms() - last_audio_sent_at_ms

                    # L2-STT-09: Use longer finalize timeout (3500ms) to match the
                    # increased utterance_end_ms (2500ms) plus buffer for network latency.
                    should_finalize_on_idle = (
                        not finalized
                        and len(captured_audio) > 0
                        and inactivity_ms is not None
                        and inactivity_ms >= 3500
                    )

                    if should_finalize_on_idle:
                        await _send_finalize_once()
                    elif send_task.done() and send_completed and not finalized:
                        await _send_finalize_once()

                    if finalized:
                        finalize_idle_ticks += 1

                    if send_task.done() and send_completed:
                        idle_after_send_ticks += 1
                        # L2-STT-09: Only break on terminal failure, not on downstream_complete.
                        # The stream must stay open for the entire session. The session manager
                        # (SessionSTTStreamManager) will call close_stream when the session ends.
                        if self._terminal_failure and idle_after_send_ticks >= 2:
                            await _send_close_stream_once()
                            break
                        # L2-STT-09: Reset state after utterance completion to handle next utterance
                        if close_allowed and self._downstream_completed:
                            # Reset for next utterance in the same session
                            finalized = False
                            close_allowed = False
                            self._close_sent = False
                            self._downstream_completed = False
                            self._received_utterance_complete = False
                            self._finalize_sent_at_ms = None
                            self._close_stream_sent_at_ms = None
                            idle_after_send_ticks = 0
                            finalize_idle_ticks = 0
                            print(
                                "[STT][Deepgram] "
                                f"session_id={self._session_id} "
                                "utterance_complete_reset_for_next"
                            )

                    # L2-STT-08 hardening: if provider emits no utterance-end/final
                    # after Finalize, close stream after bounded idle time to avoid
                    # indefinite keepalive loops and teardown timeouts.
                    # Increased from 10 to 30 ticks (15 seconds) for session stability.
                    if finalized and finalize_idle_ticks >= 30 and not close_allowed:
                        print(
                            "[STT][Deepgram] "
                            f"session_id={self._session_id} "
                            f"finalize_idle_timeout_ticks={finalize_idle_ticks} "
                            "warning=long_idle_but_session_continues"
                        )
                        # Don't mark as terminal failure - just allow the stream to close
                        # This prevents premature disconnects during natural pauses
                        close_allowed = True
                        # Yield a silent completion event instead of an error
                        yield TranscriptionEvent(
                            text="",
                            is_final=True,
                            confidence=0.0,
                            language="en",
                            speaker="unknown",
                            utterance_complete=True,
                            event_type="utterance_end",
                            metadata={
                                "request_id": self._deepgram_request_id,
                                "keepalive_count": self._keepalive_count,
                                "finalize_sent_ms": self._finalize_sent_at_ms,
                                "close_stream_sent_ms": self._close_stream_sent_at_ms,
                                "event_timestamp_ms": _now_ms(),
                                "idle_timeout": True,
                            },
                        )
                    continue

                if isinstance(raw, bytes):
                    continue

                idle_after_send_ticks = 0
                finalize_idle_ticks = 0
                payload = json.loads(raw)
                self._handle_provider_event_logs(payload)
                event_type = str(payload.get("type", "")).lower()

                if event_type in {"close", "closed"}:
                    break

                # Expected Nova-3 /v1/listen events in this stabilization task:
                # Metadata, Results, SpeechStarted, UtteranceEnd
                if event_type in {"metadata"}:
                    continue
                if event_type in {"speechstarted"}:
                    print(
                        "[STT][Deepgram] "
                        f"session_id={self._session_id} "
                        f"speech_started request_id={self._deepgram_request_id or 'unknown'}"
                    )
                    continue
                if event_type in {"utteranceend"}:
                    if not self._utterance_end_logged:
                        self._utterance_end_logged = True
                        print(
                            "[STT][Deepgram] "
                            f"session_id={self._session_id} "
                            f"utterance_end request_id={self._deepgram_request_id or 'unknown'}"
                        )
                    self._received_utterance_complete = True
                    close_allowed = True
                    continue
                if event_type in {"error", "warning"}:
                    message = payload.get("description") or payload.get("message") or str(payload)
                    close_allowed = True
                    self.mark_terminal_failure(f"provider_{event_type}")
                    yield TranscriptionEvent(
                        text=f"[STT Error: {message}]",
                        is_final=True,
                        confidence=0.0,
                        language="en",
                        speaker="unknown",
                        utterance_complete=True,
                        event_type=event_type,
                        metadata={
                            "request_id": self._deepgram_request_id,
                            "keepalive_count": self._keepalive_count,
                            "finalize_sent_ms": self._finalize_sent_at_ms,
                            "close_stream_sent_ms": self._close_stream_sent_at_ms,
                            "event_timestamp_ms": _now_ms(),
                            "terminal_failure": self._terminal_failure_reason,
                        },
                    )
                    continue

                if event_type not in {"results", ""}:
                    continue

                channel = payload.get("channel") or payload.get("results", {}).get("channel") or {}
                alternatives = channel.get("alternatives", [])
                if not alternatives:
                    continue

                best = alternatives[0]
                text = (best.get("transcript") or "").strip()
                if not text:
                    continue

                is_final = bool(payload.get("is_final") or payload.get("speech_final"))
                speech_final = bool(payload.get("speech_final"))
                confidence = float(best.get("confidence") or 0.0)
                detected_language = (
                    best.get("detected_language")
                    or payload.get("metadata", {}).get("language")
                    or "en"
                )

                speaker = self._map_speaker_from_payload(payload, best)

                if not is_final and not self._first_partial_logged:
                    self._first_partial_logged = True
                    print(
                        "[STT][Deepgram] "
                        f"session_id={self._session_id} "
                        f"first_partial request_id={self._deepgram_request_id or 'unknown'} "
                        f"text='{text[:120]}'"
                    )
                if is_final and not self._final_logged:
                    self._final_logged = True
                    print(
                        "[STT][Deepgram] "
                        f"session_id={self._session_id} "
                        f"final_transcript request_id={self._deepgram_request_id or 'unknown'} "
                        f"text='{text[:120]}'"
                    )

                utterance_complete = bool(speech_final or self._received_utterance_complete)
                if finalized and is_final:
                    utterance_complete = True
                if utterance_complete:
                    close_allowed = True
                    self._received_utterance_complete = True

                yield TranscriptionEvent(
                    text=text,
                    is_final=is_final,
                    confidence=confidence,
                    language=detected_language,
                    speaker=speaker,
                    utterance_complete=utterance_complete,
                    event_type="results",
                    metadata={
                        "request_id": self._deepgram_request_id,
                        "speech_final": speech_final,
                        "keepalive_count": self._keepalive_count,
                        "finalize_sent_ms": self._finalize_sent_at_ms,
                        "close_stream_sent_ms": self._close_stream_sent_at_ms,
                        "event_timestamp_ms": _now_ms(),
                        "terminal_failure": self._terminal_failure_reason,
                    },
                )

            receive_done = True
            with contextlib.suppress(Exception):
                await send_task
            with contextlib.suppress(Exception):
                await keepalive_task
            # L2-STT-09: Keep stream open for entire session; only close on explicit
            # session end or terminal failure. The stream lifecycle is now managed
            # by the session manager (SessionSTTStreamManager) rather than per-utterance.
            if self._terminal_failure:
                await _send_close_stream_once()

        except Exception as e:
            # Temporary smoke fallback (request-per-buffer) is preserved explicitly
            # but is NOT the primary architecture path.
            self.mark_terminal_failure(f"stream_exception:{e.__class__.__name__}")
            if not captured_audio:
                async for chunk in audio_chunks:
                    if chunk:
                        captured_audio.extend(chunk)

            yielded = False
            async for fallback_event in self._rest_fallback_stream(bytes(captured_audio)):
                yielded = True
                yield fallback_event

            if not yielded:
                yield TranscriptionEvent(
                    text=f"[STT Error: {e}]",
                    is_final=True,
                    confidence=0.0,
                    language="en",
                    speaker="unknown",
                    utterance_complete=True,
                    event_type="error",
                )
        finally:
            receive_done = True
            if ws is not None:
                with contextlib.suppress(Exception):
                    await ws.close()
            self._websocket = None

    def _map_speaker_from_payload(self, payload: dict, best_alternative: dict) -> str:
        """Truthful speaker mapping from diarization data when available."""
        # Try to get speaker from the top-level of the payload first (Nova-3 format)
        results = payload.get("results", {})
        
        # Check for utterances array (most reliable for diarization)
        utterances = payload.get("utterances") or results.get("utterances") or []
        if isinstance(utterances, list) and utterances:
            # Get the first utterance's speaker
            first_utterance = utterances[0]
            if isinstance(first_utterance, dict):
                speaker_id = first_utterance.get("speaker")
                if isinstance(speaker_id, int):
                    # Speaker 0 is typically the first speaker (interviewer in our convention)
                    # Speaker 1 is the second speaker (candidate)
                    return "interviewer" if speaker_id == 0 else "candidate"
                elif isinstance(speaker_id, str):
                    speaker_str = speaker_id.lower().strip()
                    if speaker_str in ("0", "speaker_0", "speaker 0"):
                        return "interviewer"
                    elif speaker_str in ("1", "speaker_1", "speaker 1"):
                        return "candidate"
        
        # Check channel data (multichannel mode)
        channels = results.get("channels", [])
        if isinstance(channels, list) and len(channels) > 0:
            # In multichannel, channel 0 is interviewer, channel 1 is candidate
            channel_data = payload.get("channel") or channels[0]
            if isinstance(channel_data, dict):
                # Check if this came from a specific channel
                channel_index = payload.get("channel_index")
                if isinstance(channel_index, int):
                    return "interviewer" if channel_index == 0 else "candidate"

        # Fallback to words array
        words = best_alternative.get("words", [])
        if isinstance(words, list) and words:
            speaker_votes = {}
            for word in words:
                if isinstance(word, dict):
                    speaker_id = word.get("speaker")
                    if isinstance(speaker_id, int):
                        speaker_votes[speaker_id] = speaker_votes.get(speaker_id, 0) + 1
            if speaker_votes:
                # Majority vote from words
                majority_speaker = max(speaker_votes, key=speaker_votes.get)
                return "interviewer" if majority_speaker == 0 else "candidate"

        return "unknown"

    async def _rest_fallback_stream(
        self,
        audio_payload: bytes,
    ) -> AsyncGenerator[TranscriptionEvent, None]:
        """Temporary smoke fallback using request-per-buffer Deepgram REST."""
        try:
            import httpx
        except Exception:
            return

        if not audio_payload:
            return

        request_params = {
            "model": "nova-3",
            "smart_format": "true" if self._smart_format else "false",
            "diarize": "true" if self._diarize else "false",
            "utterances": "true",
            "punctuate": "true",
            "encoding": "linear16",
            "sample_rate": "16000",
            "channels": "1",
            "utterance_end_ms": str(self._utterance_end_ms),
        }
        if self._language and self._language != "multi":
            request_params["language"] = self._language

        headers = {
            "Authorization": f"Token {self._api_key}",
            "Content-Type": "audio/raw",
        }

        url = "https://api.deepgram.com/v1/listen"

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0)) as client:
                response = await client.post(
                    url,
                    params=request_params,
                    headers=headers,
                    content=audio_payload,
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as e:
            yield TranscriptionEvent(
                text=f"[STT Error: {e}]",
                is_final=True,
                confidence=0.0,
                language="en",
                speaker="unknown",
            )
            return

        channels = payload.get("results", {}).get("channels", [])
        if not channels:
            return
        alternatives = channels[0].get("alternatives", [])
        if not alternatives:
            return

        best = alternatives[0]
        text = (best.get("transcript") or "").strip()
        if not text:
            return

        confidence = float(best.get("confidence") or 0.0)
        detected_language = (
            best.get("detected_language")
            or payload.get("results", {}).get("language")
            or "en"
        )
        speaker = self._map_speaker_from_payload(payload, best)

        yield TranscriptionEvent(
            text=text,
            is_final=True,
            confidence=confidence,
            language=detected_language,
            speaker=speaker,
        )
    
    async def disconnect(self, session_id: Optional[str] = None) -> None:
        """Disconnect from Deepgram"""
        if session_id:
            self.set_session_context(session_id)
        if self._lifecycle_started_at is not None:
            await self.close_stream(session_id)
        if self._websocket:
            await self._websocket.close()
        self._connected = False
        self._websocket = None
        self._ws_url = None
        self._ws_headers = []
        self._active_session_id = None
        self._lifecycle_started_at = None

    async def close_stream(self, session_id: Optional[str] = None) -> None:
        if session_id:
            self.set_session_context(session_id)
        if self._lifecycle_started_at is None and self._websocket is None:
            self._active_session_id = None
            return
        duration_ms = None
        if self._lifecycle_started_at is not None:
            duration_ms = int((perf_counter() - self._lifecycle_started_at) * 1000)
        print(
            "[STT][LIFECYCLE] stream_close "
            f"session_id={self._session_id} "
            f"duration_ms={duration_ms if duration_ms is not None else 'unknown'}"
        )
        if self._websocket:
            with contextlib.suppress(Exception):
                await self._websocket.close()
        self._websocket = None
        self._active_session_id = None
        self._lifecycle_started_at = None
        self._reset_stream_state()


class STTAdapterFactory:
    """Factory for creating STT adapters"""
    
    @staticmethod
    def _get_runtime_config() -> Optional[dict]:
        """Get runtime config from the shared local settings store."""
        try:
            return load_runtime_config_payload()
        except Exception as e:
            print(f"[STTAdapter] Could not load runtime config: {e}")
        return None

    @staticmethod
    def create(config: Optional[ProviderConfig] = None, api_key: Optional[str] = None) -> STTAdapter:
        """Create an STT adapter based on configuration"""
        print("[STTAdapter] Factory.create() called")
        
        # Check runtime config first
        runtime_config = STTAdapterFactory._get_runtime_config()
        
        if runtime_config and runtime_config.get("stt"):
            stt_config = runtime_config["stt"]
            local_enabled = stt_config.get("local_enabled", False)
            provider = stt_config.get("provider", "deepgram")
            enabled = stt_config.get("enabled", False)
            has_api_key = bool(stt_config.get("api_key"))
            
            print(f"[STTAdapter] Runtime config loaded: provider={provider}, local_enabled={local_enabled}, enabled={enabled}, has_api_key={has_api_key}")
            
            # If local Whisper is enabled, use it
            if local_enabled:
                print("[STTAdapter] Using WhisperLocal (local_enabled=True)")
                return WhisperLocalSTTAdapter(model_size=stt_config.get("local_model", "small"))
            
            # Otherwise use Deepgram if configured
            if enabled and has_api_key:
                api_key = stt_config["api_key"]
                print(f"[STTAdapter] Using Deepgram")
                return DeepgramSTTAdapter(api_key=api_key)
        
        # Fallback to Deepgram
        print("[STTAdapter] No runtime config, using default Deepgram")
        return DeepgramSTTAdapter()


# Global adapter instance
_stt_adapter: Optional[STTAdapter] = None


async def get_stt_adapter() -> STTAdapter:
    """Get or create the global STT adapter"""
    global _stt_adapter
    if _stt_adapter is None:
        _stt_adapter = STTAdapterFactory.create()
        await _stt_adapter.connect({})
    return _stt_adapter


async def reset_stt_adapter():
    """Reset the global STT adapter"""
    global _stt_adapter
    if _stt_adapter:
        await _stt_adapter.disconnect()
    _stt_adapter = None
