"""
Interview Coach - FastAPI Server
Health endpoint, WebSocket for realtime audio, and API routes

Architecture compliance:
- FastAPI backend on port 8000
- WebSocket for realtime communication
- PostgreSQL + pgvector for storage
- Provider abstraction via providers.yaml
"""
import os
import sys
import asyncio
import inspect
import uuid
import time
import json
from time import perf_counter
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime
from dataclasses import dataclass
from typing import Any, Optional, Literal, Dict

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field
import yaml

# Expose RealtimePipeline symbols at module scope for integration test patching
from pipeline.realtime_pipeline import RealtimePipeline, PipelineConfig
from pipeline.steps.turn_assembler import TurnAssembler, SpeakerTurn
from pipeline.silence_detector import SilenceDetector
from conversation.speaker_fallback import SpeakerFallbackCorrector

# Import database check function
from storage.database import check_db_connection, close_db


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    timestamp: str
    db_connected: bool
    pgvector_ready: bool
    api_keys_configured: bool
    effective_mode: Literal["real", "demo"]
    mode_source: str
    version: str
    providers_loaded: bool


class ProviderConfig(BaseModel):
    """Provider configuration"""
    alias: str
    provider: str
    model: str


class LLMConfig(BaseModel):
    """LLM runtime configuration"""
    provider: Literal["anthropic", "openai", "ollama"] = "anthropic"
    model: str = "claude-sonnet-4-20250514"
    api_key: str = ""
    enabled: bool = True
    base_url: str = "http://localhost:11434"  # For Ollama


class STTConfig(BaseModel):
    """STT runtime configuration"""
    provider: Literal["deepgram"] = "deepgram"
    model: str = "nova-3"
    api_key: str = ""
    enabled: bool = True


class LatencyConfig(BaseModel):
    """Latency configuration for real-time processing"""
    utterance_end_ms: int = 2000  # How long to wait for speech to end before processing (Deepgram)
    silence_threshold_ms: int = 500  # How long of silence to wait before considering a turn complete
    min_utterance_duration_ms: int = 300  # Minimum speech duration to process
    suggestion_cooldown_sec: int = 3  # Cooldown between suggestions


class RuntimeConfig(BaseModel):
    """Runtime configuration for providers"""
    llm: LLMConfig = LLMConfig()
    stt: STTConfig = STTConfig()
    latency: LatencyConfig = LatencyConfig()


# In-memory runtime config storage (loaded from file on startup)
_RUNTIME_CONFIG: RuntimeConfig | None = None
_RUNTIME_CONFIG_PATH = Path(__file__).parent.parent / "runtime_config.json"

# Global registry of active pipelines by session_id
# Used to access in-memory conversation history during active sessions
_active_pipelines: Dict[str, Any] = {}


def load_runtime_config() -> RuntimeConfig | None:
    """Load runtime config from file if exists"""
    global _RUNTIME_CONFIG
    try:
        if _RUNTIME_CONFIG_PATH.exists():
            with open(_RUNTIME_CONFIG_PATH, 'r') as f:
                data = json.load(f)
                _RUNTIME_CONFIG = RuntimeConfig(**data)
                print(f"[RuntimeConfig] Loaded from {_RUNTIME_CONFIG_PATH}")
                return _RUNTIME_CONFIG
    except Exception as e:
        print(f"[RuntimeConfig] Could not load config: {e}")
    return None


def save_runtime_config(config: RuntimeConfig) -> RuntimeConfig:
    """Save runtime config to file"""
    global _RUNTIME_CONFIG
    try:
        with open(_RUNTIME_CONFIG_PATH, 'w') as f:
            json.dump(config.model_dump(), f, indent=2)
        _RUNTIME_CONFIG = config
        print(f"[RuntimeConfig] Saved to {_RUNTIME_CONFIG_PATH}")
    except Exception as e:
        print(f"[RuntimeConfig] Could not save config: {e}")
    return config


def get_runtime_config() -> RuntimeConfig | None:
    """Get current runtime config"""
    global _RUNTIME_CONFIG
    if _RUNTIME_CONFIG is None:
        _RUNTIME_CONFIG = load_runtime_config()
    return _RUNTIME_CONFIG


class SuggestRequest(BaseModel):
    """Request payload for manual /api/suggest coaching path."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    question: str = ""
    questionText: Optional[str] = None
    question_text: Optional[str] = None
    session_id: Optional[str] = None
    candidate_profile: Optional[dict[str, Any]] = None
    company_info: Optional[dict[str, Any]] = None
    style_id: Optional[str] = "professional"
    language: Optional[str] = "en"
    mode: Optional[Literal["real", "demo"]] = None
    # Profile ID for filtering evidence retrieval (from reindexed profile)
    profile_id: Optional[str] = None
    # Number of history messages to consult (default: 4, validated range: 1-20)
    history_count: Optional[int] = None
    # NEW: Control de longitud de respuesta
    max_words: Optional[int] = Field(default=200, ge=50, le=500)
    # NEW: Tipo de entrevista para estructurar la respuesta
    interview_type: Optional[str] = None

    # Backward-compatible fields
    style: Optional[str] = None
    candidate: Optional[dict[str, Any]] = None
    company: Optional[dict[str, Any]] = None


# Load providers.yaml
def load_providers():
    """Load provider configuration from YAML"""
    config_path = Path(__file__).parent.parent.parent / "config" / "providers.yaml"
    try:
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"[Warning] Could not load providers.yaml: {e}")
        return None


PROVIDERS_CONFIG = load_providers()


async def check_pgvector_ready() -> bool:
    """Check database availability plus pgvector extension/schema readiness."""
    try:
        from storage.database import execute_scalar

        vector_extension = await execute_scalar(
            "SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector')"
        )
        achievements_vector = await execute_scalar(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'achievements'
                  AND column_name = 'embedding'
                  AND udt_name = 'vector'
            )
            """
        )
        document_chunks_vector = await execute_scalar(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'document_chunks'
                  AND column_name = 'embedding'
                  AND udt_name = 'vector'
            )
            """
        )
        return bool(vector_extension and achievements_vector and document_chunks_vector)
    except Exception as e:
        print(f"[Mode] pgvector readiness check failed: {e}")
        return False


async def resolve_server_mode() -> tuple[str, str, bool, bool, bool]:
    """
    Resolve effective backend mode.
    Returns: (mode, source, db_connected, pgvector_ready, api_keys_configured)
    """
    api_keys = check_api_keys_available()

    db_connected = False
    pgvector_ready = False
    try:
        db_connected = await check_db_connection()
        if db_connected:
            pgvector_ready = await check_pgvector_ready()
    except Exception as e:
        print(f"[Mode] Database readiness check failed: {e}")

    prereqs_ok = bool(api_keys and db_connected and pgvector_ready)

    env_mode_raw = str(os.getenv("INTERVIEW_COACH_MODE", "auto")).strip().lower()
    if env_mode_raw not in {"auto", "real", "demo"}:
        print(f"[Mode] Invalid INTERVIEW_COACH_MODE='{env_mode_raw}', defaulting to auto")
        env_mode_raw = "auto"

    if env_mode_raw == "demo":
        mode = "demo"
        source = "env:INTERVIEW_COACH_MODE=demo"
    elif env_mode_raw == "real":
        if prereqs_ok:
            mode = "real"
            source = "env:INTERVIEW_COACH_MODE=real"
        else:
            mode = "demo"
            source = "fallback:env_real_missing_prereqs"
            print(
                "[Mode] INTERVIEW_COACH_MODE=real requested but prerequisites missing; "
                "falling back to demo"
            )
    else:
        mode = "real" if prereqs_ok else "demo"
        source = "auto:prereqs_ok" if prereqs_ok else "auto:missing_prereqs"

    return mode, source, db_connected, pgvector_ready, api_keys


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler"""
    # Startup
    print("[Interview Coach] Starting Python/FastAPI backend...")
    print("[Interview Coach] Architecture: Tauri + Rust (audio) + Python/FastAPI (core) + React/TS (UI)")
    print("[Interview Coach] Storage: PostgreSQL + pgvector")
    
    if PROVIDERS_CONFIG:
        print(f"[Interview Coach] Providers loaded from config/providers.yaml")
    else:
        print("[Interview Coach] Warning: providers.yaml not found")
    
    # Check database connection on startup
    try:
        db_ok = await check_db_connection()
        if db_ok:
            print("[Interview Coach] Database connection: OK")
        else:
            print("[Interview Coach] Warning: Database connection failed")
    except Exception as e:
        print(f"[Interview Coach] Warning: Database check error: {e}")

    # Resolve and publish effective mode on startup
    mode, source, db_connected, pgvector_ready, api_keys = await resolve_server_mode()
    app.state.default_mode = mode
    app.state.default_mode_source = source
    print(
        "[Interview Coach] Mode resolution "
        f"effective={mode} source={source} "
        f"api_keys={api_keys} db_connected={db_connected} pgvector_ready={pgvector_ready}"
    )
    
    yield
    
    # Shutdown
    print("[Interview Coach] Shutting down...")
    await close_db()


app = FastAPI(
    title="Interview Coach - Python Backend",
    description="Real-time AI interview coaching backend (FastAPI)",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS for development (Tauri webview)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to tauri://localhost
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Health check endpoint.
    Returns 200 if service is healthy.
    Actually checks database connection.
    """
    mode, source, db_connected, pgvector_ready, api_keys = await resolve_server_mode()
    
    return HealthResponse(
        status="healthy" if db_connected else "degraded",
        timestamp=datetime.utcnow().isoformat(),
        db_connected=db_connected,
        pgvector_ready=pgvector_ready,
        api_keys_configured=api_keys,
        effective_mode=mode,
        mode_source=source,
        version="0.1.0",
        providers_loaded=PROVIDERS_CONFIG is not None,
    )


@app.get("/api/runtime-config", response_model=RuntimeConfig)
async def get_runtime_config_endpoint():
    """
    Get current runtime configuration for LLM/STT providers.
    Returns the current configuration or default if not set.
    """
    config = get_runtime_config()
    if config is None:
        # Return default config if not set
        return RuntimeConfig()
    return config


@app.put("/api/runtime-config", response_model=RuntimeConfig)
async def update_runtime_config_endpoint(config: RuntimeConfig):
    """
    Update runtime configuration for LLM/STT providers.
    This allows users to specify their own API keys and provider preferences.
    """
    return save_runtime_config(config)


# =====================
# MODEL DISCOVERY ENDPOINTS
# =====================

@app.get("/api/models")
async def list_available_models(
    provider: str | None = None,
    ollama_base_url: str | None = None
):
    """
    List available models for all providers or a specific provider.
    
    Query parameters:
    - provider: Optional filter (anthropic, openai, ollama)
    - ollama_base_url: Custom Ollama server URL (default: http://localhost:11434)
    
    Returns a dict with provider names as keys and lists of available models.
    """
    from adapters.llm_adapter import list_available_models
    
    url = ollama_base_url or "http://localhost:11434"
    models = await list_available_models(provider=provider, ollama_base_url=url)
    
    return {
        "success": True,
        "providers": models,
    }


@app.get("/api/models/{provider}")
async def list_provider_models(provider: str, ollama_base_url: str | None = None):
    """
    List available models for a specific provider.
    
    Path parameters:
    - provider: Provider name (anthropic, openai, ollama)
    
    Query parameters:
    - ollama_base_url: Custom Ollama server URL (for ollama provider)
    """
    from adapters.llm_adapter import (
        list_anthropic_models,
        list_openai_models,
        list_ollama_models,
    )
    
    provider = provider.lower()
    
    if provider == "anthropic":
        models = await list_anthropic_models()
    elif provider == "openai":
        models = await list_openai_models()
    elif provider == "ollama":
        url = ollama_base_url or "http://localhost:11434"
        models = await list_ollama_models(url)
    else:
        return {"success": False, "error": f"Unknown provider: {provider}"}
    
    return {
        "success": True,
        "provider": provider,
        "models": models,
    }


@app.get("/api/ollama/status")
async def check_ollama_status(ollama_base_url: str | None = None):
    """
    Check if Ollama server is available and running.
    """
    from adapters.llm_adapter import check_ollama_available
    
    url = ollama_base_url or "http://localhost:11434"
    available = await check_ollama_available(url)
    
    return {
        "success": True,
        "available": available,
        "base_url": url,
    }


@app.get("/api/debug/session/{session_id}")
async def debug_session(session_id: str):
    """
    Debug endpoint to check session state and conversation history.
    """
    result = {
        "session_id": session_id,
        "active_pipelines_count": len(_active_pipelines),
        "active_pipeline_ids": list(_active_pipelines.keys()),
        "pipeline_found": False,
        "tracker_info": None,
        "turns": [],
    }
    
    active_pipeline = _active_pipelines.get(session_id)
    if active_pipeline:
        result["pipeline_found"] = True
        
        if hasattr(active_pipeline, 'conversation_tracker'):
            tracker = active_pipeline.conversation_tracker
            result["tracker_info"] = {
                "has_tracker": True,
                "tracker_type": type(tracker).__name__,
            }
            
            # Try to get turns
            try:
                turns = tracker.get_last_n_turns(limit=10)
                result["turns_count"] = len(turns)
                result["turns"] = [
                    {
                        "speaker": turn.get("speaker", "unknown"),
                        "text": turn.get("text", "")[:100],
                        "timestamp": turn.get("timestamp", "N/A"),
                    }
                    for turn in turns
                ]
            except Exception as e:
                result["tracker_error"] = str(e)
        else:
            result["tracker_info"] = {"has_tracker": False}
    
    return result


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "name": "Interview Coach Python Backend",
        "version": "0.1.0",
        "architecture": "Tauri + Rust + Python/FastAPI + React/TS",
        "docs": "/docs",
        "endpoints": {
            "health": "/health",
            "providers": "/providers",
            "ws_pipeline": "/ws/pipeline",
        }
    }


@app.get("/providers")
async def list_providers():
    """List available provider configurations from providers.yaml"""
    if not PROVIDERS_CONFIG:
        return {"error": "providers.yaml not loaded"}
    
    return {
        "stt": PROVIDERS_CONFIG.get("providers", {}).get("stt", {}),
        "llm": PROVIDERS_CONFIG.get("providers", {}).get("llm", {}),
        "embedding": PROVIDERS_CONFIG.get("providers", {}).get("embedding", {}),
    }


def check_api_keys_available():
    """Check if API keys are configured for real LLM/embedding calls."""
    has_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY"))
    has_openai = bool(os.environ.get("OPENAI_API_KEY"))
    return has_anthropic or has_openai


def _normalize_mode(value: Any, default: str = "demo") -> str:
    """Normalize mode values to a JSON-safe, known mode label."""
    allowed = {"demo", "real", "fallback", "safe_fallback"}
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in allowed:
            return normalized

    if isinstance(default, str):
        fallback = default.strip().lower()
        if fallback in allowed:
            return fallback

    return "demo"


def _resolve_result_mode(result: Any, suggested_response: Any, default_mode: str = "demo") -> str:
    """Resolve mode from suggestion/result objects with safe fallback."""
    suggested_mode = getattr(suggested_response, "mode", None)
    result_mode = getattr(result, "mode", None)
    return _normalize_mode(suggested_mode, _normalize_mode(result_mode, default_mode))


def _as_serializable_list(value: Any) -> list[Any]:
    """Convert possibly mocked/typed values to a concrete list for JSON payloads."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _adapter_accepts_session_arg(method: Any) -> bool:
    try:
        params = list(inspect.signature(method).parameters.values())
    except (TypeError, ValueError):
        return False
    for param in params:
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            return True
    return len(params) >= 1


def _adapter_stream_accepts_session_arg(method: Any) -> bool:
    try:
        params = list(inspect.signature(method).parameters.values())
    except (TypeError, ValueError):
        return False
    for param in params:
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            return True
    return len(params) >= 2


async def _call_adapter_method(adapter: Any, method_name: str, session_id: Optional[str]) -> None:
    if adapter is None or not hasattr(adapter, method_name):
        return
    method = getattr(adapter, method_name)
    if _adapter_accepts_session_arg(method):
        await method(session_id)
    else:
        await method()


def _build_analysis_event(result: Any) -> Optional[dict[str, Any]]:
    """Build a serializable analysis event from pipeline result data."""
    question_analysis = getattr(result, "question_analysis", None)
    if question_analysis is None:
        return None

    primary_type_obj = getattr(question_analysis, "primary_type", None)
    question_type = getattr(primary_type_obj, "value", primary_type_obj)
    question_type_str = str(question_type or "unknown")

    sub_questions_payload: list[dict[str, str]] = []
    for sub_question in _as_serializable_list(getattr(question_analysis, "sub_questions", [])):
        priority_obj = getattr(sub_question, "priority", None)
        priority = getattr(priority_obj, "value", priority_obj)
        text = getattr(sub_question, "text", sub_question)
        sub_questions_payload.append(
            {
                "text": str(text or ""),
                "priority": str(priority or ""),
            }
        )

    return {
        "type": "analysis",
        "question_type": question_type_str,
        "is_compound": bool(getattr(question_analysis, "is_compound", False)),
        "sub_questions": sub_questions_payload,
        "key_topics": [str(topic) for topic in _as_serializable_list(getattr(question_analysis, "key_topics", []))],
        "underlying_intent": [
            str(intent)
            for intent in _as_serializable_list(getattr(question_analysis, "underlying_intent", []))
        ],
        "red_flags": [str(flag) for flag in _as_serializable_list(getattr(question_analysis, "red_flags", []))],
    }


def _extract_request_id(payload: Any) -> Optional[str]:
    if not isinstance(payload, dict):
        return None
    request_id = payload.get("request_id") or payload.get("requestId") or payload.get("requestID")
    if request_id:
        return str(request_id)
    return None


def _build_transcript_metadata(
    *,
    session_id: str,
    transcript_id: str,
    request_id: str,
    language: str,
    speaker: str,
    source: str,
) -> dict[str, str]:
    payload = {
        "session_id": str(session_id or ""),
        "transcript_id": str(transcript_id or ""),
        "request_id": str(request_id or ""),
        "language": str(language or ""),
        "speaker": str(speaker or ""),
        "source": str(source or ""),
    }
    return {key: value for key, value in payload.items() if value}


def _supports_transcript_metadata(pipeline: Any) -> bool:
    return getattr(pipeline, "supports_transcript_metadata", False) is True


async def _emit_analysis_if_missing(websocket: WebSocket, result: Any, analysis_emitted: bool) -> bool:
    """Emit analysis from result only when pipeline progress stream didn't already emit it."""
    if analysis_emitted:
        return False
    analysis_event = _build_analysis_event(result)
    if analysis_event:
        await websocket.send_json(analysis_event)
        return True
    return False


@dataclass
class InterviewerTurnCandidateState:
    """Minimal state for assembling an interviewer turn candidate."""

    text: str
    fragment_count: int = 1
    last_event_signature: Optional[str] = None


class SessionSTTStreamManager:
    """Session-scoped STT stream manager for persistent realtime audio streaming."""

    def __init__(
        self,
        websocket: WebSocket,
        pipeline: Any,
        session_id: str,
        default_mode: str,
    ):
        self._websocket = websocket
        self._pipeline = pipeline
        self._session_id = session_id
        self._default_mode = _normalize_mode(default_mode, "demo")
        self._queue: asyncio.Queue[Optional[tuple[bytes, str]]] = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None
        self._latest_source = "system"
        self._stream_started_at: Optional[float] = None
        self._first_partial_latency_ms: Optional[int] = None
        self._first_final_latency_ms: Optional[int] = None
        self._provider_errors: list[str] = []
        self._stt_adapter: Any = None
        self._transcript_emitted_at_ms: Optional[int] = None
        self._analysis_emitted_at_ms: Optional[int] = None
        self._suggestion_emitted_at_ms: Optional[int] = None
        self._teardown_started_at_ms: Optional[int] = None
        self._teardown_cancel_at_ms: Optional[int] = None
        self._downstream_in_flight: bool = False
        self._interviewer_turn_candidate: Optional[InterviewerTurnCandidateState] = None
        self._last_completed_interviewer_turn_signature: Optional[str] = None
        self._last_completed_interviewer_turn_at: Optional[float] = None
        self._completed_interviewer_turn_count: int = 0
        self._duplicate_turn_window_sec: float = 3.0
        self._last_completed_turn_signature: Optional[str] = None
        self._last_completed_turn_at: Optional[float] = None
        self._speaker_corrector = SpeakerFallbackCorrector(session_id=session_id)
        self._speaker_fallback_enabled = True
        self._fallback_turn_confidence_threshold = 0.8
        self._turn_flush_task: Optional[asyncio.Task] = None
        self._turn_flush_token: int = 0
        # Turn boundary controls to prevent rapid-fire processing
        self._min_utterance_duration_ms = 2000  # Minimum 2 seconds of speech
        self._min_utterance_words = 5  # Minimum 5 words
        self._suggestion_cooldown_sec = 5.0  # 5 second cooldown between suggestions
        self._last_suggestion_at: Optional[float] = None
        silence_threshold_ms = 2000
        try:
            silence_threshold_ms = int(getattr(self._pipeline, "config", None).silence_threshold_ms)
        except Exception:
            silence_threshold_ms = 2000
        self._turn_assembler = TurnAssembler(silence_threshold_ms=silence_threshold_ms)
        
        # Initialize SilenceDetector for auto-triggered suggestions
        # Uses relaxed constraints (500ms, 2 words) vs TurnAssembler (2000ms, 5 words)
        self._silence_detector = SilenceDetector(
            conversation_tracker=self._pipeline.conversation_tracker,
            cooldown_sec=self._suggestion_cooldown_sec,
            min_turn_duration_ms=500,  # Relaxed from 2000ms
            min_word_count=2,  # Relaxed from 5 words
            context_turn_limit=4,
        )

    @staticmethod
    def _normalize_speaker(raw_speaker: Any) -> str:
        if raw_speaker is None:
            return "unknown"
        speaker = str(raw_speaker).strip().lower()
        if not speaker:
            return "unknown"
        if speaker in {"interviewer", "candidate", "unknown", "unattributed"}:
            return speaker
        return "unknown"

    @staticmethod
    def _normalize_turn_text(text: str) -> str:
        return " ".join(str(text or "").split()).strip()

    @staticmethod
    def _merge_turn_text(current_text: str, incoming_text: str) -> str:
        if not current_text:
            return incoming_text
        if not incoming_text:
            return current_text
        if incoming_text == current_text:
            return current_text
        if incoming_text.startswith(current_text):
            return incoming_text
        if current_text.startswith(incoming_text):
            return current_text
        if incoming_text in current_text:
            return current_text
        if current_text in incoming_text:
            return incoming_text
        return incoming_text

    def _update_interviewer_turn_candidate(
        self,
        transcript_text: str,
        speaker: str,
        is_final: bool,
        utterance_complete: bool,
    ) -> Optional[str]:
        """Accumulate interviewer fragments and return completed candidate when available."""
        normalized_text = self._normalize_turn_text(transcript_text)
        if not normalized_text:
            return None

        # Candidate speech breaks interviewer accumulation; unknown/unattributed does not.
        if speaker == "candidate":
            self._interviewer_turn_candidate = None
            return None
        if speaker != "interviewer":
            return None

        incoming_signature = f"{normalized_text}|{int(is_final)}|{int(utterance_complete)}"
        state = self._interviewer_turn_candidate
        if state is None:
            state = InterviewerTurnCandidateState(
                text=normalized_text,
                fragment_count=1,
                last_event_signature=incoming_signature,
            )
            self._interviewer_turn_candidate = state
        elif state.last_event_signature != incoming_signature:
            state.text = self._merge_turn_text(state.text, normalized_text)
            state.fragment_count += 1
            state.last_event_signature = incoming_signature

        if not (is_final and utterance_complete):
            return None

        completed_text = self._interviewer_turn_candidate.text if self._interviewer_turn_candidate else normalized_text
        completed_signature = completed_text.lower()
        self._interviewer_turn_candidate = None
        now = perf_counter()

        if (
            completed_signature == self._last_completed_interviewer_turn_signature
            and self._last_completed_interviewer_turn_at is not None
            and (now - self._last_completed_interviewer_turn_at) <= self._duplicate_turn_window_sec
        ):
            print(
                "[WS][TURN] interviewer_turn_duplicate "
                f"session_id={self._session_id} text='{completed_text[:120]}'"
            )
            return None

        self._last_completed_interviewer_turn_signature = completed_signature
        self._last_completed_interviewer_turn_at = now
        self._completed_interviewer_turn_count += 1
        print(
            "[WS][TURN] interviewer_turn_candidate_complete "
            f"session_id={self._session_id} turn_index={self._completed_interviewer_turn_count} "
            f"fragments={state.fragment_count if state else 1} text='{completed_text[:120]}'"
        )
        return completed_text

    def _record_turn_event(self, turn: SpeakerTurn) -> None:
        try:
            if hasattr(self._pipeline, "conversation_tracker"):
                self._pipeline.conversation_tracker.record_turn_event(
                    speaker=turn.speaker,
                    text=turn.text,
                    utterance_count=turn.utterance_count,
                    start_time=turn.start_time,
                    end_time=turn.end_time or turn.start_time,
                    reason=turn.completion_reason or "unknown",
                    metadata={"session_id": self._session_id},
                )
        except Exception as e:
            print(f"[TURN][ASSEMBLY] tracker_log_failed session_id={self._session_id} error={e}")

    def _is_duplicate_turn(self, turn: SpeakerTurn) -> bool:
        signature = " ".join(str(turn.text or "").split()).strip().lower()
        if not signature:
            return False
        now = perf_counter()
        if (
            signature == self._last_completed_turn_signature
            and self._last_completed_turn_at is not None
            and (now - self._last_completed_turn_at) <= self._duplicate_turn_window_sec
        ):
            return True
        self._last_completed_turn_signature = signature
        self._last_completed_turn_at = now
        return False

    def _cancel_turn_flush(self) -> None:
        if self._turn_flush_task and not self._turn_flush_task.done():
            self._turn_flush_task.cancel()
        self._turn_flush_task = None

    def _schedule_turn_flush(self) -> None:
        self._cancel_turn_flush()
        self._turn_flush_token += 1
        token = self._turn_flush_token
        threshold_sec = max(self._turn_assembler.state.silence_threshold_ms / 1000, 0.0)

        async def _flush_after_pause():
            try:
                if threshold_sec:
                    await asyncio.sleep(threshold_sec)
                if token != self._turn_flush_token:
                    return
                completed = self._turn_assembler.flush_if_idle(
                    current_time=time.time(),
                    reason="pause",
                )
                if completed is None:
                    return
                self._record_turn_event(completed)
                await self._process_completed_turn(completed)
            except asyncio.CancelledError:
                return
            except Exception as e:
                print(f"[TURN][ASSEMBLY] flush_failed session_id={self._session_id} error={e}")

        self._turn_flush_task = asyncio.create_task(
            _flush_after_pause(),
            name=f"turn-flush-{self._session_id}",
        )

    def _assemble_turn(
        self,
        *,
        transcript_text: str,
        speaker: str,
        is_final: bool,
        utterance_complete: bool,
        event_time: float,
        language: str,
        provider_metadata: dict,
    ) -> Optional[SpeakerTurn]:
        provider_request_id = _extract_request_id(provider_metadata) or "unknown"
        metadata = {
            "utterance_complete": utterance_complete,
            "is_final": is_final,
            "provider_event_type": provider_metadata.get("event_type"),
            "source": self._latest_source,
            "provider_request_id": provider_request_id,
            "provider_metadata": provider_metadata,
        }

        current_turn = self._turn_assembler.get_current_turn()

        if speaker == "unknown":
            target_speaker = current_turn.speaker if current_turn is not None else "unknown"
            self._turn_assembler.process_utterance(
                transcript_text,
                target_speaker,
                event_time=event_time,
                language=language,
                metadata=metadata,
                allow_completion=False,
            )
            self._schedule_turn_flush()
            return None

        if is_final and utterance_complete:
            if current_turn is not None and current_turn.speaker == speaker:
                self._turn_assembler.process_utterance(
                    transcript_text,
                    speaker,
                    event_time=event_time,
                    language=language,
                    metadata=metadata,
                    allow_completion=False,
                )
                completed_turn = self._turn_assembler.force_complete(
                    reason="utterance_complete",
                    end_time=event_time,
                )
                self._cancel_turn_flush()
                return completed_turn

            if current_turn is None:
                # Start and immediately complete the turn since STT signaled utterance end
                self._turn_assembler.process_utterance(
                    transcript_text,
                    speaker,
                    event_time=event_time,
                    language=language,
                    metadata=metadata,
                    allow_completion=False,
                )
                completed_turn = self._turn_assembler.force_complete(
                    reason="utterance_complete",
                    end_time=event_time,
                )
                self._cancel_turn_flush()
                return completed_turn
            return None

        if not is_final:
            self._turn_assembler.process_partial(transcript_text, speaker)
            return None

        if is_final and not utterance_complete:
            completed_turn = self._turn_assembler.process_utterance(
                transcript_text,
                speaker,
                event_time=event_time,
                language=language,
                metadata=metadata,
            )
            if completed_turn is not None:
                self._cancel_turn_flush()
                return completed_turn
            self._schedule_turn_flush()

        if current_turn is None:
            self._turn_assembler.process_utterance(
                transcript_text,
                speaker,
                event_time=event_time,
                language=language,
                metadata=metadata,
                allow_completion=False,
            )
            self._schedule_turn_flush()
        return None

    def _check_turn_boundary_constraints(self, turn: SpeakerTurn) -> tuple[bool, str]:
        """
        Check if a turn meets the minimum requirements to trigger pipeline processing.
        Returns (passed, reason) tuple.
        """
        # Check minimum duration
        if turn.duration_ms < self._min_utterance_duration_ms:
            return False, f"duration_too_short ({turn.duration_ms}ms < {self._min_utterance_duration_ms}ms)"
        
        # Check minimum word count
        word_count = len(str(turn.text or "").split())
        if word_count < self._min_utterance_words:
            return False, f"word_count_too_low ({word_count} < {self._min_utterance_words})"
        
        # Check cooldown period
        if self._last_suggestion_at is not None:
            elapsed_since_last = perf_counter() - self._last_suggestion_at
            if elapsed_since_last < self._suggestion_cooldown_sec:
                return False, f"cooldown_active ({elapsed_since_last:.1f}s < {self._suggestion_cooldown_sec}s)"
        
        return True, ""

    async def _try_auto_trigger_suggestion(self, turn: SpeakerTurn) -> None:
        """
        Try to trigger an automatic suggestion using relaxed constraints.
        
        This is called when the strict constraints fail, allowing shorter
        interviewer questions to still trigger auto-suggestions.
        
        Uses SilenceDetector with:
        - min_turn_duration_ms: 500 (vs 2000 strict)
        - min_word_count: 2 (vs 5 strict)
        - cooldown_sec: 5.0
        """
        # Build turn data for SilenceDetector
        turn_data = {
            "speaker": turn.speaker,
            "duration_ms": turn.duration_ms,
            "text": turn.text or "",
        }
        
        # Check if we should trigger with relaxed constraints
        if not self._silence_detector.should_trigger_suggestion(turn_data):
            remaining_cooldown = self._silence_detector.get_remaining_cooldown()
            print(
                "[AUTO][SILENCE] skip_trigger "
                f"session_id={self._session_id} "
                f"reason=constraints_not_met "
                f"duration_ms={turn.duration_ms} "
                f"word_count={len(str(turn.text or '').split())} "
                f"remaining_cooldown={remaining_cooldown:.1f}s"
            )
            return
        
        # Record that we're about to trigger
        self._silence_detector.record_trigger()
        
        print(
            "[AUTO][SILENCE] triggering_suggestion "
            f"session_id={self._session_id} "
            f"duration_ms={turn.duration_ms} "
            f"word_count={len(str(turn.text or '').split())}"
        )
        
        # Get context from conversation history (last 4 turns)
        context = self._silence_detector.get_context_turns()
        question_text = self._silence_detector.get_primary_question_from_context()
        
        if not question_text:
            print(
                "[AUTO][SILENCE] skip_trigger "
                f"session_id={self._session_id} reason=no_question_text"
            )
            self._silence_detector.record_completion()
            return
        
        # Send progress indicator
        await self._websocket.send_json({
            "type": "analysis",
            "stage": "auto_silence",
            "context_turns": len(context),
        })
        
        try:
            # Process through pipeline with context (same as manual trigger)
            result = await self._pipeline.process_question(
                question_text,
                is_final=True,
                on_progress=lambda e: self._websocket.send_json(e),
                context=context,
            )
            
            # Emit suggestion event
            suggested_response = result.exchange.suggested_response
            suggested_metadata = getattr(suggested_response, "metadata", {}) or {}
            if not isinstance(suggested_metadata, dict):
                suggested_metadata = {}
            
            await self._websocket.send_json({
                "type": "suggestion",
                "stage": "full",
                "mode": "real",
                "source": "auto_silence",
                "trigger": "silence",
                "question": question_text,
                "context_turns": len(context),
                "full_response": result.exchange.suggested_response.full_response,
                "bullets_preview": result.exchange.suggested_response.bullets,
                "bullets": result.exchange.suggested_response.bullets,
                "key_metrics": result.exchange.suggested_response.key_metrics,
                "confidence": result.exchange.suggested_response.confidence,
                "style": result.exchange.suggested_response.style_used.value,
                "language": result.language_decision.final_language,
                "quality_passed": result.quality_result.passed,
                "quality_score": result.quality_result.score,
                "quality_issues": result.quality_result.issues,
                "latency_ms": result.total_latency_ms,
                "processing_full_response": False,
                "bullets_latency_ms": suggested_metadata.get("time_to_bullets_ms", result.total_latency_ms),
                "full_latency_ms": suggested_metadata.get("time_to_full_ms", result.total_latency_ms),
            })
            
            print(
                "[AUTO][SILENCE] suggestion_emitted "
                f"session_id={self._session_id} "
                f"latency_ms={result.total_latency_ms}"
            )
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            await self._websocket.send_json({
                "type": "error",
                "message": f"Auto-suggestion error: {str(e)}",
            })
        finally:
            self._silence_detector.record_completion()

    async def _process_completed_turn(self, turn: SpeakerTurn) -> None:
        if self._is_duplicate_turn(turn):
            print(
                "[TURN][ASSEMBLY] duplicate_turn "
                f"session_id={self._session_id} text='{(turn.text or '')[:120]}'"
            )
            return
        if turn.speaker != "interviewer":
            print(
                "[WS][TURN] skip_downstream "
                f"session_id={self._session_id} reason=non_interviewer speaker={turn.speaker}"
            )
            return
        
        # Check turn boundary constraints (minimum duration, cooldown, etc.)
        constraints_passed, constraints_reason = self._check_turn_boundary_constraints(turn)
        if not constraints_passed:
            print(
                "[WS][TURN] skip_downstream "
                f"session_id={self._session_id} reason={constraints_reason} "
                f"text='{(turn.text or '')[:60]}...'"
            )
            
            # Try auto-trigger with relaxed constraints (SilenceDetector)
            # This allows shorter interviewer questions to still trigger auto-suggestions
            await self._try_auto_trigger_suggestion(turn)
            return

        provider_request_id = "unknown"
        provider_metadata = turn.metadata.get("provider_metadata", {}) if isinstance(turn.metadata, dict) else {}
        if isinstance(provider_metadata, dict):
            provider_request_id = _extract_request_id(provider_metadata) or "unknown"
        transcript_id = str(uuid.uuid4())
        handoff_start = perf_counter()
        print(
            "[PIPELINE][HANDOFF] transcript_received "
            f"session_id={self._session_id} transcript_id={transcript_id}"
        )

        transcript_metadata = _build_transcript_metadata(
            session_id=self._session_id,
            transcript_id=transcript_id,
            request_id=provider_request_id,
            language=turn.language or "unknown",
            speaker=turn.speaker,
            source=str(turn.metadata.get("source") if isinstance(turn.metadata, dict) else self._latest_source),
        )

        analysis_emitted = False
        analysis_emitted_via_handoff = False

        async def _send_progress(event_payload: dict):
            nonlocal analysis_emitted, analysis_emitted_via_handoff
            if isinstance(event_payload, dict) and event_payload.get("type") == "analysis":
                analysis_emitted = True
                analysis_emitted_via_handoff = True
                if self._stream_started_at is not None and self._analysis_emitted_at_ms is None:
                    self._analysis_emitted_at_ms = int((perf_counter() - self._stream_started_at) * 1000)
                    print(
                        "[WS][STT] analysis_emitted "
                        f"session_id={self._session_id} "
                        f"timestamp_ms={self._analysis_emitted_at_ms}"
                    )
            await self._websocket.send_json(event_payload)

        self._downstream_in_flight = True
        try:
            print(
                "[PIPELINE][HANDOFF] pipeline_start "
                f"session_id={self._session_id} transcript_id={transcript_id} "
                f"request_id={provider_request_id}"
            )

            if self._stream_started_at is not None and self._analysis_emitted_at_ms is None:
                self._analysis_emitted_at_ms = int((perf_counter() - self._stream_started_at) * 1000)

            if _supports_transcript_metadata(self._pipeline):
                result = await self._pipeline.process_question(
                    turn.text,
                    is_final=True,
                    on_progress=_send_progress,
                    transcript_metadata=transcript_metadata,
                )
            else:
                result = await self._pipeline.process_question(
                    turn.text,
                    is_final=True,
                    on_progress=_send_progress,
                )

            analysis_emitted_via_handoff = await _emit_analysis_if_missing(
                self._websocket,
                result,
                analysis_emitted,
            ) or analysis_emitted_via_handoff

            suggested_response = result.exchange.suggested_response
            suggested_metadata = getattr(suggested_response, "metadata", {}) or {}
            if not isinstance(suggested_metadata, dict):
                suggested_metadata = {}

            actual_mode = _resolve_result_mode(result, suggested_response, self._default_mode)
            provider_used = suggested_metadata.get("provider")
            model_used = suggested_metadata.get("model")

            # Record that we generated a suggestion for cooldown purposes
            self._last_suggestion_at = perf_counter()
            
            await self._websocket.send_json({
                "type": "suggestion",
                "stage": "full",
                "mode": actual_mode,
                # P4-T1: full_response is primary; bullets are preview-only.
                "full_response": result.exchange.suggested_response.full_response,
                "bullets_preview": result.exchange.suggested_response.bullets,
                "bullets": result.exchange.suggested_response.bullets,
                "key_metrics": result.exchange.suggested_response.key_metrics,
                "confidence": result.exchange.suggested_response.confidence,
                "style": result.exchange.suggested_response.style_used.value,
                "language": result.language_decision.final_language,
                "quality_passed": result.quality_result.passed,
                "quality_score": result.quality_result.score,
                "quality_issues": result.quality_result.issues,
                "latency_ms": result.total_latency_ms,
                "processing_full_response": False,
                "bullets_latency_ms": suggested_metadata.get("time_to_bullets_ms", result.total_latency_ms),
                "full_latency_ms": suggested_metadata.get("time_to_full_ms", result.total_latency_ms),
                "provider": provider_used,
                "model": model_used,
                "transcript_id": transcript_id,
                "request_id": provider_request_id,
            })

            if self._stream_started_at is not None and self._suggestion_emitted_at_ms is None:
                self._suggestion_emitted_at_ms = int((perf_counter() - self._stream_started_at) * 1000)
                print(
                    "[WS][STT] suggestion_emitted "
                    f"session_id={self._session_id} "
                    f"timestamp_ms={self._suggestion_emitted_at_ms}"
                )

            if self._stt_adapter is not None and hasattr(self._stt_adapter, "mark_downstream_complete"):
                self._stt_adapter.mark_downstream_complete()

            handoff_latency_ms = int((perf_counter() - handoff_start) * 1000)
            print(
                "[PIPELINE][HANDOFF] pipeline_complete "
                f"session_id={self._session_id} transcript_id={transcript_id} "
                f"request_id={provider_request_id} latency_ms={handoff_latency_ms}"
            )
            if analysis_emitted_via_handoff:
                print(
                    "[PIPELINE][HANDOFF] event_sequence "
                    f"session_id={self._session_id} transcript_id={transcript_id} "
                    "sequence=transcript->analysis->suggestion"
                )
        except Exception as e:
            if self._stt_adapter is not None and hasattr(self._stt_adapter, "mark_terminal_failure"):
                self._stt_adapter.mark_terminal_failure(f"downstream_exception:{e.__class__.__name__}")
            raise
        finally:
            self._downstream_in_flight = False

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(
            self._run(),
            name=f"stt-stream-{self._session_id}",
        )

    async def enqueue_audio(self, audio_bytes: bytes, source: str) -> None:
        if not audio_bytes:
            return
        await self.start()
        await self._queue.put((audio_bytes, source or "system"))

    async def stop(self) -> None:
        if self._stream_started_at is not None:
            self._teardown_started_at_ms = int((perf_counter() - self._stream_started_at) * 1000)
            print(
                "[WS][STT] teardown_start "
                f"session_id={self._session_id} "
                f"timestamp_ms={self._teardown_started_at_ms}"
            )

        if self._task and not self._task.done():
            await self._queue.put(None)
            try:
                await asyncio.wait_for(self._task, timeout=30.0)
            except asyncio.TimeoutError:
                if self._downstream_in_flight and self._suggestion_emitted_at_ms is None:
                    print(
                        "[WS][STT] teardown_wait_downstream "
                        f"session_id={self._session_id} "
                        f"analysis_ms={self._analysis_emitted_at_ms if self._analysis_emitted_at_ms is not None else 'n/a'} "
                        f"suggestion_ms={self._suggestion_emitted_at_ms if self._suggestion_emitted_at_ms is not None else 'n/a'}"
                    )
                    try:
                        await asyncio.wait_for(self._task, timeout=45.0)
                    except asyncio.TimeoutError:
                        pass

            if self._task and not self._task.done():
                print(
                    "[WS][STT] teardown_timeout "
                    f"session_id={self._session_id} "
                    f"analysis_ms={self._analysis_emitted_at_ms if self._analysis_emitted_at_ms is not None else 'n/a'} "
                    f"suggestion_ms={self._suggestion_emitted_at_ms if self._suggestion_emitted_at_ms is not None else 'n/a'}"
                )
                if self._stream_started_at is not None:
                    self._teardown_cancel_at_ms = int((perf_counter() - self._stream_started_at) * 1000)
                    print(
                        "[WS][STT] teardown_cancel "
                        f"session_id={self._session_id} "
                        f"timestamp_ms={self._teardown_cancel_at_ms}"
                    )
                self._task.cancel()
                try:
                    await self._task
                except Exception:
                    pass

        try:
            if self._stt_adapter is not None:
                await _call_adapter_method(self._stt_adapter, "disconnect", self._session_id)
        except Exception as e:
            print(f"[WS][STT] disconnect warning session_id={self._session_id} error={e}")

        try:
            from adapters.stt_adapter import reset_stt_adapter

            await reset_stt_adapter()
        except Exception as e:
            print(f"[WS][STT] reset warning session_id={self._session_id} error={e}")
        finally:
            self._stt_adapter = None

    async def _audio_chunks(self):
        while True:
            item = await self._queue.get()
            if item is None:
                break
            audio_bytes, source = item
            self._latest_source = source or "system"
            yield audio_bytes

    async def _run(self) -> None:
        from adapters.stt_adapter import get_stt_adapter

        try:
            self._stream_started_at = perf_counter()
            print(f"[WS][STT] stream_open session_id={self._session_id}")
            stt_adapter = await get_stt_adapter()
            if hasattr(stt_adapter, "set_session_context"):
                stt_adapter.set_session_context(self._session_id)
            await _call_adapter_method(stt_adapter, "open_stream", self._session_id)
            self._stt_adapter = stt_adapter
            if _adapter_stream_accepts_session_arg(stt_adapter.stream_audio):
                event_stream = stt_adapter.stream_audio(self._audio_chunks(), self._session_id)
            else:
                event_stream = stt_adapter.stream_audio(self._audio_chunks())
            async for event in event_stream:
                # DUAL_STT_PHASE2: Split event routing
                # Display path: every event (partial + final) → live_caption for real-time display
                # Coach path: only finals + utterance_complete → transcript for turn assembly
                await self._handle_display_event(event)
                await self._handle_transcription_event(event)
        except Exception as e:
            print(f"[WS] Session STT stream error: {e}")
            await self._websocket.send_json({
                "type": "error",
                "message": f"STT stream error: {str(e)}",
            })
        finally:
            if self._stt_adapter is not None:
                try:
                    await _call_adapter_method(self._stt_adapter, "close_stream", self._session_id)
                except Exception as e:
                    print(f"[WS][STT] close_stream warning session_id={self._session_id} error={e}")
            duration_ms = None
            if self._stream_started_at is not None:
                duration_ms = int((perf_counter() - self._stream_started_at) * 1000)
            print(
                "[WS][STT] stream_close "
                f"session_id={self._session_id} "
                f"duration_ms={duration_ms if duration_ms is not None else 'unknown'} "
                f"first_partial_latency_ms={self._first_partial_latency_ms if self._first_partial_latency_ms is not None else 'n/a'} "
                f"first_final_latency_ms={self._first_final_latency_ms if self._first_final_latency_ms is not None else 'n/a'} "
                f"transcript_ms={self._transcript_emitted_at_ms if self._transcript_emitted_at_ms is not None else 'n/a'} "
                f"analysis_ms={self._analysis_emitted_at_ms if self._analysis_emitted_at_ms is not None else 'n/a'} "
                f"suggestion_ms={self._suggestion_emitted_at_ms if self._suggestion_emitted_at_ms is not None else 'n/a'} "
                f"teardown_ms={self._teardown_started_at_ms if self._teardown_started_at_ms is not None else 'n/a'} "
                f"teardown_cancel_ms={self._teardown_cancel_at_ms if self._teardown_cancel_at_ms is not None else 'n/a'} "
                f"provider_errors={len(self._provider_errors)}"
            )

    async def _handle_display_event(self, event: Any) -> None:
        """
        DUAL_STT_PHASE2: Display path handler.
        Fires on EVERY Deepgram event (partial + final) to provide real-time captions.
        Sends live_caption WS events for Zoom/Teams-like flowing captions.
        """
        transcript_text = (getattr(event, "text", "") or "").strip()
        if not transcript_text:
            return
        
        is_final = bool(getattr(event, "is_final", False))
        raw_speaker = self._normalize_speaker(getattr(event, "speaker", None))
        
        # Use speaker corrector for consistent speaker attribution in display
        decision = self._speaker_corrector.resolve(
            raw_speaker,
            transcript_text,
            event_timestamp=time.time(),
            is_final=is_final,
            utterance_complete=False,
        )
        speaker = decision.speaker
        
        event_timestamp_ms = None
        if self._stream_started_at is not None:
            event_timestamp_ms = int((perf_counter() - self._stream_started_at) * 1000)
        
        await self._websocket.send_json({
            "type": "live_caption",
            "text": transcript_text,
            "speaker": speaker,
            "is_partial": not is_final,
            "timestamp_ms": event_timestamp_ms,
            "source": self._latest_source,
        })
        
        print(
            f"[WS][DISPLAY] live_caption session_id={self._session_id} "
            f"is_partial={not is_final} speaker={speaker} text='{transcript_text[:80]}'"
        )

    async def _handle_transcription_event(self, event: Any) -> None:
        transcript_text = (getattr(event, "text", "") or "").strip()
        if not transcript_text:
            return
        
        # Skip silent utterance end events (used for session stability)
        event_type = getattr(event, "event_type", None)
        if event_type == "utterance_end" and not transcript_text:
            return

        is_final = bool(getattr(event, "is_final", False))
        utterance_complete = bool(getattr(event, "utterance_complete", False))
        confidence = float(getattr(event, "confidence", 0.0) or 0.0)
        language = str(getattr(event, "language", "en") or "en")
        raw_speaker = self._normalize_speaker(getattr(event, "speaker", None))
        provider_metadata = getattr(event, "metadata", {}) or {}
        provider_event_type = getattr(event, "event_type", None)

        event_timestamp_ms = None
        if self._stream_started_at is not None:
            event_timestamp_ms = int((perf_counter() - self._stream_started_at) * 1000)

        event_time = time.time()

        if self._stream_started_at is not None:
            latency_ms = int((perf_counter() - self._stream_started_at) * 1000)
            if not is_final and self._first_partial_latency_ms is None:
                self._first_partial_latency_ms = latency_ms
                print(
                    f"[WS][STT] first_partial session_id={self._session_id} "
                    f"latency_ms={self._first_partial_latency_ms}"
                )
            if is_final and self._first_final_latency_ms is None:
                self._first_final_latency_ms = latency_ms
                print(
                    f"[WS][STT] first_final session_id={self._session_id} "
                    f"latency_ms={self._first_final_latency_ms}"
                )

        event_timestamp = (
            (self._stream_started_at + (event_timestamp_ms / 1000))
            if self._stream_started_at is not None and event_timestamp_ms is not None
            else perf_counter()
        )

        decision = self._speaker_corrector.resolve(
            raw_speaker,
            transcript_text,
            event_timestamp=event_timestamp,
            is_final=is_final,
            utterance_complete=utterance_complete,
        )

        if decision.used_fallback:
            print(
                "[SPEAKER][FALLBACK] "
                f"session_id={self._session_id} decision={decision.speaker} "
                f"confidence={decision.confidence:.2f} reason={decision.reason}"
            )

        try:
            if hasattr(self._pipeline, "conversation_tracker"):
                self._pipeline.conversation_tracker.record_speaker_event(
                    speaker=decision.speaker,
                    confidence=decision.confidence,
                    reason=decision.reason,
                    source="stt_stream",
                    utterance_text=transcript_text,
                    metadata={
                        "raw_speaker": raw_speaker,
                        "provider_event_type": provider_event_type,
                        "utterance_complete": utterance_complete,
                        "confidence_raw": confidence,
                    },
                )
        except Exception as e:
            print(f"[SPEAKER][FALLBACK] tracker_log_failed session_id={self._session_id} error={e}")

        speaker = decision.speaker
        speaker_for_turn = speaker
        if decision.used_fallback and decision.confidence < self._fallback_turn_confidence_threshold:
            speaker_for_turn = "unknown"

        # DUAL_STT_PHASE2: Only send transcript WS event for finals
        # Display (live_caption) is handled by _handle_display_event for every event
        # Transcript is only for conversation history + turn assembly - use finals only
        if is_final:
            await self._websocket.send_json({
                "type": "transcript",
                "text": transcript_text,
                "is_final": is_final,
                "confidence": confidence,
                "language": language,
                "speaker": speaker,
                "speaker_attribution": speaker,
                "speaker_confidence": decision.confidence,
                "speaker_reason": decision.reason,
                "source": self._latest_source,
                "utterance_complete": utterance_complete,
                "provider_event_type": provider_event_type,
                "provider_metadata": provider_metadata,
                "timestamp_ms": event_timestamp_ms,
            })

            if self._stream_started_at is not None and self._transcript_emitted_at_ms is None:
                self._transcript_emitted_at_ms = int((perf_counter() - self._stream_started_at) * 1000)
                print(
                    "[WS][STT] transcript_emitted "
                    f"session_id={self._session_id} "
                    f"timestamp_ms={self._transcript_emitted_at_ms}"
                )

            print(
                "[WS] Transcript: "
                f"'{transcript_text}' (final={is_final}, utterance_complete={utterance_complete})"
            )

        assembled_turn = self._assemble_turn(
            transcript_text=transcript_text,
            speaker=speaker_for_turn,
            is_final=is_final,
            utterance_complete=utterance_complete,
            event_time=event_time,
            language=language,
            provider_metadata=provider_metadata,
        )

        # L2-STT-08: trigger downstream on is_final (indicates speaker finished).
        # utterance_complete is optional - Deepgram may not always set it.
        if not is_final:
            return

        # Keep explicit fallback/error behavior truthful: final STT error payloads are
        # surfaced as transcript text and do not trigger pipeline processing.
        if transcript_text.startswith("[STT Error:"):
            self._provider_errors.append(transcript_text)
            print(f"[WS][STT] provider_error session_id={self._session_id} detail={transcript_text}")
            if self._stt_adapter is not None and hasattr(self._stt_adapter, "mark_terminal_failure"):
                self._stt_adapter.mark_terminal_failure("provider_error_transcript")
            return

        if assembled_turn is None:
            idle_completed_turn = self._turn_assembler.flush_if_idle(
                current_time=event_time,
                reason="pause",
            )
            if idle_completed_turn is not None:
                self._record_turn_event(idle_completed_turn)
                if idle_completed_turn.speaker == "interviewer":
                    assembled_turn = idle_completed_turn

        if assembled_turn is None:
            print(
                "[WS][TURN] skip_downstream "
                f"session_id={self._session_id} reason=no_turn_ready speaker={speaker}"
            )
            return

        self._record_turn_event(assembled_turn)
        await self._process_completed_turn(assembled_turn)


@app.post("/api/suggest")
async def suggest_response(request: SuggestRequest):
    """
    Generate interview response suggestion.
    
    This is the main coaching endpoint that:
    1. Analyzes the question
    2. Retrieves relevant evidence from profile
    3. Generates response in the selected style
    4. Validates through quality gate
    
    Returns explicit 'mode' field indicating 'demo' or 'real'.
    Demo mode is used when API keys are not configured.
    """
    from pipeline.steps.language_policy import LanguagePolicy
    from pipeline.steps.question_analyzer import QuestionAnalyzer, AnalysisContext
    from pipeline.steps.retrieval_planner import RetrievalPlanner
    from pipeline.steps.evidence_retriever import EvidenceRetriever, RetrieverMode
    from pipeline.steps.response_composer import ResponseComposer, ComposerMode
    from pipeline.steps.quality_gate import QualityGate
    from contracts.models import ResponseStyle, AssembledContext
    import uuid
    
    def _as_list(value):
        if value is None:
            return []
        if isinstance(value, list):
            return [str(v) for v in value if v is not None and str(v).strip()]
        if isinstance(value, str):
            value = value.strip()
            return [value] if value else []
        return []

    request_data = request.model_dump(exclude_none=True)
    if request.model_extra:
        request_data.update(request.model_extra)

    question_text = (
        request_data.get("question")
        or request_data.get("questionText")
        or request_data.get("question_text")
        or ""
    )
    
    # HR-2: Get conversation history from active pipeline (in-memory) or database
    session_id = request_data.get("session_id")
    
    # Extract and validate history_count (default: 4, range: 1-20)
    history_count_raw = request_data.get("history_count")
    if history_count_raw is not None:
        try:
            history_count = int(history_count_raw)
            if history_count < 1:
                history_count = 1
            elif history_count > 20:
                history_count = 20
        except (ValueError, TypeError):
            history_count = 4
    else:
        history_count = 4
    
    print(f"[/api/suggest] Request received - session_id: {session_id}, "
          f"question_text provided: {bool(question_text)}, "
          f"question_length: {len(question_text)}, "
          f"history_count: {history_count}")
    
    # DEBUG: Log active pipelines state
    print(f"[/api/suggest][DEBUG] Active pipelines: {list(_active_pipelines.keys())}")
    print(f"[/api/suggest][DEBUG] Session ID received: '{session_id}'")
    print(f"[/api/suggest][DEBUG] Session ID in active pipelines: {session_id in _active_pipelines}")
    
    # HR-2: OPTION 0 - Use conversation_history from request (frontend-provided, highest priority)
    conversation_history_from_session = []
    recent_exchanges = []
    frontend_conversation_history = request_data.get("conversation_history")
    
    if frontend_conversation_history and isinstance(frontend_conversation_history, list):
        print(f"[/api/suggest] Using conversation_history from frontend: {len(frontend_conversation_history)} turns")
        conversation_history_from_session = [
            {
                "speaker": turn.get("speaker", "unknown"),
                "text": turn.get("text", ""),
            }
            for turn in frontend_conversation_history
        ]
        print(f"[/api/suggest] Loaded {len(conversation_history_from_session)} turns from frontend request")
        # Log each turn for debugging
        for i, turn in enumerate(conversation_history_from_session):
            print(f"[/api/suggest][DEBUG] Frontend turn {i}: speaker={turn['speaker']}, text='{turn['text'][:50]}...'")
    
    if session_id and not conversation_history_from_session:
        try:
            # OPTION 1: Check active pipeline's conversation_tracker (in-memory, for live sessions)
            active_pipeline = _active_pipelines.get(session_id)
            if active_pipeline and hasattr(active_pipeline, 'conversation_tracker'):
                print(f"[/api/suggest] Found active pipeline for session {session_id}")
                recent_turns = active_pipeline.conversation_tracker.get_last_n_turns(limit=history_count)
                print(f"[/api/suggest] Got {len(recent_turns)} turns from active tracker")
                
                for turn in recent_turns:
                    recent_exchanges.append({
                        'interviewer_utterance': turn.get('text', ''),
                        'candidate_response': '',  # Not available in tracker turns
                        'timestamp': turn.get('timestamp', datetime.now().isoformat())
                    })
                
                if recent_exchanges:
                    print(f"[/api/suggest] Using {len(recent_exchanges)} exchanges from in-memory tracker")
            
            # OPTION 2: Fallback to database if no active pipeline or no turns in tracker
            if not recent_exchanges:
                print(f"[/api/suggest] No active pipeline, querying database...")
                from storage.session_repo import get_session_repository
                repo = get_session_repository()
                print(f"[/api/suggest][DEBUG] Querying exchanges for session_id: {session_id}")
                recent_exchanges = await repo.get_recent_exchanges(session_id, limit=history_count)
                print(f"[/api/suggest] Got {len(recent_exchanges)} exchanges from database")
            
            # DEBUG: Log details of each exchange
            for i, ex in enumerate(recent_exchanges):
                utterance = ex.get('interviewer_utterance', 'N/A')
                print(f"[/api/suggest][DEBUG] Exchange {i}: utterance='{utterance[:50] if utterance else 'EMPTY'}...'")
            
            if recent_exchanges:
                # Format exchanges as conversation history (HR-2: last 4 messages)
                conversation_history_from_session = [
                    {
                        "speaker": "interviewer",
                        "text": exchange.get("interviewer_utterance", ""),
                    }
                    for exchange in recent_exchanges
                ]
                # Use most recent interviewer's question as question_text if not provided
                if not question_text and recent_exchanges:
                    last_exchange = recent_exchanges[-1]
                    question_text = last_exchange.get("interviewer_utterance", "")
                    print(f"[/api/suggest] Extracted question from history: '{question_text[:50]}...'")
                print(f"[/api/suggest] Loaded {len(conversation_history_from_session)} turns from session {session_id}")
        except Exception as e:
            print(f"[/api/suggest] Warning: Could not load conversation history: {e}")
    
    style_str = request_data.get("style_id") or request_data.get("style") or "professional"
    request_language = str(request_data.get("language") or "en").strip().lower() or "en"

    # Extract candidate - check both nested and top-level keys
    candidate = (
        request_data.get("candidate_profile")
        or request_data.get("candidate")
        or {}
    )
    
    # If candidate is empty, check top-level request_data for profile fields
    if not candidate or candidate == {}:
        candidate = {
            "name": request_data.get("name"),
            "current_role": request_data.get("current_role"),
            "target_role": request_data.get("target_role"),
            "years_experience": request_data.get("years_experience"),
            "skills": request_data.get("skills", []),
            "industry": request_data.get("industry"),
            "cv_text": request_data.get("cv_text"),
            "summary": request_data.get("summary"),
            "achievements": request_data.get("achievements", []),
            "education": request_data.get("education"),
            "languages": request_data.get("languages", []),
            "certifications": request_data.get("certifications", []),
        }
        # Remove None values
        candidate = {k: v for k, v in candidate.items() if v is not None}
    
    company = (
        request_data.get("company_info")
        or request_data.get("company")
        or {}
    )

    candidate_name = request_data.get("candidate_name") or request_data.get("candidateName")
    role_title = request_data.get("role") or request_data.get("role_title") or request_data.get("roleTitle")
    company_name = request_data.get("company_name") or request_data.get("companyName")

    if isinstance(candidate, str):
        candidate = {"name": candidate}
    if isinstance(company, str):
        company = {"companyName": company}

    if candidate_name and not candidate.get("name"):
        candidate["name"] = candidate_name
    if company_name and not company.get("companyName"):
        company["companyName"] = company_name
    if role_title and not company.get("roleTitle"):
        company["roleTitle"] = role_title
    
    # HR-2: Log final state before validation
    print(f"[/api/suggest] Final validation - session_id: {session_id}, "
          f"question_text empty: {not question_text}, "
          f"history_loaded: {len(conversation_history_from_session)} turns")
    
    # HR-2: Improved validation with descriptive error messages
    if not question_text:
        # Build debug info for error response
        debug_info_error = {
            "session_id": session_id,
            "history_count_requested": history_count,
            "conversation_history_found": len(conversation_history_from_session),
            "active_pipelines": list(_active_pipelines.keys()),
            "question_text": question_text[:100] if question_text else None,
        }
        
        if session_id:
            if conversation_history_from_session:
                # Session exists, history loaded, but no question text found
                return {
                    "success": False,
                    "error": "Question required - session history found but no interviewer question detected. "
                             "Please ensure the interviewer has spoken or provide a question manually.",
                    "mode": "error",
                    "debug": debug_info_error,
                }
            else:
                # Session exists but no history found
                return {
                    "success": False,
                    "error": "Question required - no conversation history found for this session. "
                             "Please start a live session first or provide a question manually.",
                    "mode": "error",
                    "debug": debug_info_error,
                }
        else:
            # No session_id and no question provided
            return {
                "success": False,
                "error": "Question required - provide a question or start a live session with session_id.",
                "mode": "error",
                "debug": debug_info_error,
            }
    
    # HR-2: Validation passed - log the question being used
    question_source = "history" if session_id and conversation_history_from_session else "request"
    print(f"[/api/suggest] Validation passed - using question from {question_source}: "
          f"'{question_text[:60]}...' (length: {len(question_text)})")
    
    # Resolve baseline mode from environment + readiness
    default_mode, default_mode_source, _, _, _ = await resolve_server_mode()

    # Check if we can use real adapters; allow explicit mode override
    request_mode = str(request_data.get("mode") or "").strip().lower()
    if request_mode == "demo":
        use_real = False
        mode_source = "request:demo"
    elif request_mode == "real":
        if default_mode == "real":
            use_real = True
            mode_source = "request:real"
        else:
            use_real = False
            mode_source = "fallback:request_real_missing_prereqs"
            print("[/api/suggest] Request mode=real but prerequisites missing; using demo")
    else:
        use_real = default_mode == "real"
        mode_source = default_mode_source
    mode = "real" if use_real else "demo"
    
    # Map style string to enum
    style_map = {
        "executive": ResponseStyle.EXECUTIVE,
        "commercial": ResponseStyle.COMMERCIAL,
        "technical": ResponseStyle.TECHNICAL,
        "mixed": ResponseStyle.MIXED,
        "professional": ResponseStyle.EXECUTIVE,
        "conversational": ResponseStyle.MIXED,
        "concise": ResponseStyle.EXECUTIVE,
        "detailed": ResponseStyle.TECHNICAL,
        "star": ResponseStyle.EXECUTIVE,
    }
    response_style = style_map.get(style_str.lower(), ResponseStyle.MIXED)
    
    candidate_summary = (
        request_data.get("candidate_summary")
        or request_data.get("candidateSummary")
        or candidate.get("summary")
        or ""
    )
    candidate_skills = _as_list(
        request_data.get("candidate_skills")
        or request_data.get("candidateSkills")
        or candidate.get("skills", [])
    )
    candidate_achievements = _as_list(
        request_data.get("candidate_achievements")
        or request_data.get("candidateAchievements")
        or candidate.get("achievements", [])
    )
    candidate_certifications = _as_list(
        request_data.get("candidate_certifications")
        or request_data.get("candidateCertifications")
        or candidate.get("certifications", [])
    )

    normalized_candidate_name = (
        candidate.get("name")
        or candidate.get("candidate_name")
        or candidate.get("candidateName")
        or ""
    )

    candidate_cv_text = candidate.get("cv_text") or candidate.get("cvText") or ""
    
    # DEBUG: Log cv_text received
    print(f"[/api/suggest] Received cv_text: {len(candidate_cv_text)} chars")
    if len(candidate_cv_text) > 0:
        print(f"[/api/suggest] cv_text preview: {candidate_cv_text[:100]}...")
    else:
        print(f"[/api/suggest] WARNING: No cv_text received!")
        print(f"[/api/suggest] candidate keys: {list(candidate.keys())}")
    
    candidate_context = {
        "name": normalized_candidate_name,
        "current_role": candidate.get("current_role") or candidate.get("currentRole") or "",
        "years_experience": candidate.get("years_experience") or candidate.get("yearsExperience") or 0,
        "skills": candidate_skills,
        "education": candidate.get("education") or "",
        "languages": _as_list(candidate.get("languages", [])),
        "certifications": candidate_certifications,
        "summary": candidate_summary,
        "achievements": candidate_achievements,
        "target_role": candidate.get("target_role") or candidate.get("targetRole") or "",
        "industry": candidate.get("industry") or "",
        "location": candidate.get("location") or "",
        "cv_text": candidate_cv_text,
    }
    
    # Debug: Log cv_text presence
    cv_text_length = len(candidate_cv_text) if candidate_cv_text else 0
    print(f"[/api/suggest] cv_text received: {cv_text_length} chars")
    if cv_text_length > 0:
        print(f"[/api/suggest] cv_text preview: {candidate_cv_text[:200]}...")

    company_industry = (
        request_data.get("company_industry")
        or request_data.get("companyIndustry")
        or company.get("industry", "")
    )
    company_description = (
        request_data.get("company_description")
        or request_data.get("companyDescription")
        or company.get("companyDescription", "")
    )
    company_requirements = _as_list(
        request_data.get("company_requirements")
        or request_data.get("companyRequirements")
        or request_data.get("roleRequirements")
        or company.get("positionRequirements", [])
        or company.get("role_requirements", [])
        or company.get("roleRequirements", [])
    )
    company_culture = (
        request_data.get("company_culture")
        or request_data.get("companyCulture")
        or company.get("companyCulture")
        or company.get("culture")
        or ""
    )
    company_values = _as_list(company.get("values", []))
    company_tech_stack = _as_list(company.get("tech_stack") or company.get("techStack") or [])
    role_responsibilities = _as_list(
        company.get("role_responsibilities")
        or company.get("roleResponsibilities")
        or []
    )
    interview_type = company.get("interview_type") or company.get("interviewType") or "mixed"
    # NEW: Extract max_words from request (company_info or direct field)
    max_words = request.max_words if request.max_words else (company.get("max_words") or 200)
    interview_focus = _as_list(company.get("interview_focus") or company.get("interviewFocus") or [])

    normalized_company_name = (
        company.get("name")
        or company.get("companyName")
        or ""
    )
    normalized_role_title = (
        company.get("role_title")
        or company.get("roleTitle")
        or company.get("positionTitle")
        or ""
    )
    normalized_job_description = (
        company.get("job_description")
        or company.get("jobDescription")
        or company.get("positionDescription")
        or company_description
    )

    company_context = {
        "name": normalized_company_name,
        "companyName": normalized_company_name,
        "industry": company_industry,
        "size": company.get("size") or "",
        "culture": company_culture,
        "companyCulture": company_culture,
        "mission": company.get("mission") or "",
        "values": company_values,
        "tech_stack": company_tech_stack,
        "techStack": company_tech_stack,
        "role_title": normalized_role_title,
        "roleTitle": normalized_role_title,
        "positionTitle": normalized_role_title,
        "role_requirements": company_requirements,
        "roleRequirements": company_requirements,
        "positionRequirements": company_requirements,
        "role_responsibilities": role_responsibilities,
        "roleResponsibilities": role_responsibilities,
        "interview_type": interview_type,
        "interviewType": interview_type,
        "interview_focus": interview_focus,
        "interviewFocus": interview_focus,
        "job_description": normalized_job_description,
        "jobDescription": normalized_job_description,
        "positionDescription": normalized_job_description,
        "company_description": company_description,
        "companyDescription": company_description,
    }

    # Build interview config
    interview_config = {
        "company_name": normalized_company_name,
        "role_title": normalized_role_title,
        "job_description": normalized_job_description,
        "company_industry": company_industry,
        "company_description": company_description,
        "company_requirements": company_requirements,
        "company_culture": company_culture,
        "response_style": response_style.value,
        "style_id": style_str,
        "language_preference": request_language,
        "interview_type": interview_type,
        "interview_focus": interview_focus,
        # NEW: Length control
        "max_words": max_words,
        # Candidate profile for evidence retrieval
        "candidate_name": normalized_candidate_name,
        "candidate_summary": candidate_summary,
        "candidate_skills": candidate_skills,
        "candidate_achievements": candidate_achievements,
        "candidate_certifications": candidate_certifications,
        # Keep full context objects for downstream pipeline usage
        "candidate": candidate_context,
        "company": company_context,
    }
    
    try:
        start_perf = perf_counter()

        # Direct manual path (no audio/STT/turn assembler)
        language_policy = LanguagePolicy(
            user_preference=request_language if request_language in {"es", "en"} else None
        )
        question_analyzer = QuestionAnalyzer(use_llm=use_real)
        retrieval_planner = RetrievalPlanner()
        evidence_retriever = EvidenceRetriever(
            mode=RetrieverMode.AUTO if use_real else RetrieverMode.DEMO,
            force_demo=not use_real,
        )
        response_composer = ResponseComposer(
            mode=ComposerMode.REAL if use_real else ComposerMode.DEMO,
            use_llm=use_real,
        )
        quality_gate = QualityGate()

        language_decision = language_policy.decide(question_text)

        analysis_context = AnalysisContext(
            role_title=interview_config.get("role_title", ""),
            company_name=interview_config.get("company_name", ""),
            job_description=interview_config.get("job_description", ""),
            company_industry=interview_config.get("company_industry", ""),
            company_description=interview_config.get("company_description", ""),
            company_requirements=interview_config.get("company_requirements", []) or [],
            company_culture=interview_config.get("company_culture", ""),
            candidate_summary=interview_config.get("candidate_summary", ""),
            candidate_skills=interview_config.get("candidate_skills", []) or [],
            candidate_achievements=interview_config.get("candidate_achievements", []) or [],
            candidate_certifications=interview_config.get("candidate_certifications", []) or [],
            conversation_history=conversation_history_from_session if conversation_history_from_session else [],
            topics_covered=[],
            metrics_used=[],
        )

        question_analysis = await question_analyzer.analyze(question_text, analysis_context)

        # Extract profile_id from request for evidence filtering
        profile_id = request_data.get("profile_id")
        
        retrieval_plan = retrieval_planner.plan(
            question_analysis,
            analysis_context.role_title,
            analysis_context.company_name,
            candidate_skills=analysis_context.candidate_skills,
            company_requirements=analysis_context.company_requirements,
            candidate_summary=analysis_context.candidate_summary,
            profile_id=profile_id,
        )
        evidence = await evidence_retriever.retrieve(retrieval_plan)

        assembled_context = AssembledContext(
            question=question_text,
            analysis=question_analysis,
            evidence=evidence,
            conversation_summary="",
            conversation_history=conversation_history_from_session,  # HR-2: Pass full conversation history
            topics_already_covered=[],
            metrics_already_used=[],
            achievements_referenced=analysis_context.candidate_achievements,
            style_config={
                "response_style": interview_config.get("response_style", "mixed"),
                "language_preference": interview_config.get("language_preference", "auto"),
                "style_id": interview_config.get("style_id", style_str),
            },
            interview_config=interview_config,
            max_words=max_words,  # NEW: Length control
        )

        # DEBUG: Build prompt for debug output
        debug_prompt = response_composer._build_prompt(assembled_context, response_style)
        debug_system_prompt = response_composer._get_system_prompt(response_style)

        generated_response = await response_composer.compose(assembled_context)
        final_response, quality_result = await quality_gate.process(
            generated_response,
            question_analysis,
            conversation_map=None,
            expected_language=language_decision.final_language,
        )

        total_latency_ms = int((perf_counter() - start_perf) * 1000)

        suggested_metadata = getattr(final_response, "metadata", {}) or {}
        if not isinstance(suggested_metadata, dict):
            suggested_metadata = {}
        
        # Determine actual mode from result (composer may still use demo/fallback)
        actual_mode = getattr(final_response, 'mode', mode)
        provider_used = suggested_metadata.get("provider")
        model_used = suggested_metadata.get("model")
        if actual_mode == "real":
            print(
                f"[/api/suggest] REAL mode verified provider={provider_used or 'unknown'} "
                f"model={model_used or 'unknown'}"
            )
        elif actual_mode == "fallback":
            print("[/api/suggest] Fallback mode used after real path failure")
        else:
            print("[/api/suggest] Demo mode used")
        
        # Build response with explicit mode
        return {
            "success": True,
            "mode": actual_mode,
            "requested_mode": request_mode or None,
            "resolved_mode": mode,
            "mode_source": mode_source,
            "suggestion_id": request_data.get("session_id") or str(uuid.uuid4()),
            "full_response": final_response.full_response,
            "bullets": final_response.bullets,
            "confidence": final_response.confidence,
            "quality_score": quality_result.score,
            "suggestion": {
                "full_response": final_response.full_response,
                "suggestedAnswer": final_response.full_response,
                "bullets": final_response.bullets,
                "key_metrics": final_response.key_metrics,
                "keyMetrics": final_response.key_metrics,
                "confidence": final_response.confidence,
                "style": final_response.style_used.value,
                "questionType": question_analysis.primary_type.value,
                "isCompound": question_analysis.is_compound,
                "subQuestions": [
                    {
                        "text": sq.text,
                        "priority": sq.priority.value,
                        "weight": sq.weight,
                    }
                    for sq in question_analysis.sub_questions
                ],
                "underlyingIntent": question_analysis.underlying_intent,
                "redFlags": question_analysis.red_flags,
                "quality_score": quality_result.score,
            },
            "language": {
                "detected": language_decision.final_language,
                "confidence": language_decision.confidence,
            },
            "quality": {
                "passed": quality_result.passed,
                "score": quality_result.score,
                "issues": quality_result.issues,
            },
            "llm": {
                "provider": provider_used,
                "model": model_used,
            },
            "latency_ms": total_latency_ms,
            "candidate": normalized_candidate_name or "Candidato",
            "company": normalized_company_name or "Empresa",
            "debug": {
                "history_count": history_count,
                "conversation_history": conversation_history_from_session,
                "question": question_text,
                "system_prompt": debug_system_prompt,
                "user_prompt": debug_prompt[:2000] + "..." if len(debug_prompt) > 2000 else debug_prompt,
            },
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "mode": "error",
            "error": f"Pipeline error: {str(e)}",
        }


async def _persist_cv_profile(
    name: str,
    resume_text: str,
    profile_data: Optional[dict] = None,
) -> Optional[str]:
    """
    Persist a CV profile to the database with embeddings.
    
    Stores:
    - user_profiles: Basic profile info
    - achievements: Each achievement with embedding and company metadata
    - document_chunks: CV sections with embeddings for retrieval
    
    Args:
        name: Candidate name
        resume_text: Raw CV text
        profile_data: Optional dict with structured profile data (achievements, companies, etc.)
    
    Returns:
        Profile ID if stored successfully
    """
    from storage.database import execute_scalar, execute_query
    from storage.embedding_utils import build_query_embedding, vector_literal
    
    try:
        # Insert base profile
        profile_id = await execute_scalar(
            """
            INSERT INTO user_profiles (name, resume_text, created_at, updated_at)
            VALUES ($1, $2, NOW(), NOW())
            RETURNING id
            """,
            name,
            resume_text,
        )
        
        if not profile_id:
            return None
        
        profile_id_str = str(profile_id)
        
        # If we have structured profile data, also store achievements and document chunks
        if profile_data:
            await _persist_cv_embeddings(
                profile_id_str,
                profile_data,
                resume_text,
            )
        
        return profile_id_str
        
    except Exception as e:
        print(f"[CV Analyzer] Failed to store CV profile: {e}")
        return None


async def _persist_cv_embeddings(
    profile_id: str,
    profile_data: dict,
    resume_text: str,
) -> None:
    """
    Store achievements and document chunks with embeddings.

    Args:
        profile_id: UUID of the user profile
        profile_data: Dict with achievements, companies, skills, etc.
        resume_text: Raw CV text for chunking
    """
    from storage.database import execute_query
    from storage.embedding_utils import build_query_embedding, vector_literal

    try:
        # Extract structured data
        achievements = profile_data.get("achievements", [])
        achievement_companies = profile_data.get("achievement_companies", {})
        all_companies = profile_data.get("all_companies", [])
        skills = profile_data.get("skills", [])
        leadership_roles = profile_data.get("leadership_roles", [])
        technical_stack = profile_data.get("technical_stack", [])
        current_role = profile_data.get("currentRole", "")
        current_company = profile_data.get("company", "")

        print(f"[CV Persist] Starting to persist profile {profile_id}")
        print(f"[CV Persist] Found {len(achievements)} achievements, companies: {all_companies}")
        
        # Store achievements with embeddings and company metadata
        stored_achievements = 0
        failed_achievements = 0
        for idx, achievement_text in enumerate(achievements):
            if not achievement_text:
                continue

            # Get company for this achievement (use index mapping)
            company = achievement_companies.get(str(idx)) or achievement_companies.get(idx)
            if not company:
                company = "Unknown"

            print(f"[CV Persist] Processing achievement {idx}: company={company}, text_preview={achievement_text[:50]}...")
            
            # Extract metrics from achievement text (simple pattern matching)
            import re
            metrics = re.findall(r"[\d,]+%?|[\d,]+(?:\s+(?:users|customers|accounts|teams|people|years|million|billion|dollars|hours))?", 
                                achievement_text.lower())
            metrics = [m.strip() for m in metrics if m.strip()] if metrics else []
            
            # Create tags including company
            tags = [company]
            if current_company and company == current_company:
                tags.append("current_company")
            
            # Generate embedding
            embedding_text = f"Achievement at {company}: {achievement_text}"
            try:
                embedding = await build_query_embedding(embedding_text)
                embedding_vec = vector_literal(embedding)
                print(f"[CV Persist] Created embedding for achievement {idx}")
            except Exception as e:
                print(f"[CV Persist] Failed to create embedding for achievement {idx}: {e}")
                embedding_vec = None
                failed_achievements += 1

            # Store achievement
            if embedding_vec:
                try:
                    await execute_query(
                        """
                        INSERT INTO achievements
                        (profile_id, title, context, action, result, metrics, tags, embedding, created_at)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
                        """,
                        profile_id,
                        achievement_text,  # title
                        company,  # context (company)
                        None,  # action
                        None,  # result
                        metrics if metrics else None,
                        tags if tags else None,
                        embedding_vec,
                    )
                    stored_achievements += 1
                    print(f"[CV Persist] Stored achievement {idx} with company={company}")
                except Exception as e:
                    print(f"[CV Persist] Failed to store achievement {idx}: {e}")
                    failed_achievements += 1
        
        # Store document chunks for retrieval
        # Chunk the resume into sections
        chunks = []
        
        # Summary chunk
        if profile_data.get("summary"):
            chunks.append({
                "section": "summary",
                "content": profile_data["summary"],
            })
        
        # Skills chunk
        if skills:
            chunks.append({
                "section": "skills",
                "content": ", ".join(skills),
            })
        
        # Technical stack chunk
        if technical_stack:
            chunks.append({
                "section": "technical_stack",
                "content": ", ".join(technical_stack),
            })
        
        # Leadership roles chunk
        if leadership_roles:
            chunks.append({
                "section": "leadership",
                "content": "; ".join(leadership_roles),
            })
        
        # Companies section - list all companies
        if all_companies:
            companies_text = "; ".join(all_companies)
            chunks.append({
                "section": "companies",
                "content": companies_text,
            })
        
        # Store each chunk with embedding
        for chunk in chunks:
            try:
                embedding = await build_query_embedding(chunk["content"])
                embedding_vec = vector_literal(embedding)
            except Exception as e:
                print(f"[CV Analyzer] Failed to create embedding for chunk: {e}")
                embedding_vec = None
            
            # Metadata including company info - must be JSON string for DB storage
            import json as _json
            metadata = _json.dumps({
                "section": chunk["section"],
                "companies": all_companies,
                "current_company": current_company,
            })
            
            if embedding_vec:
                await execute_query(
                    """
                    INSERT INTO document_chunks
                    (profile_id, source, section, content, embedding, metadata, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, NOW())
                    """,
                    profile_id,
                    "cv",
                    chunk["section"],
                    chunk["content"],
                    embedding_vec,
                    metadata,
                )
        
        print(f"[CV Persist] Completed: stored {stored_achievements} achievements, {len(chunks)} document chunks (failed: {failed_achievements})")

    except Exception as e:
        print(f"[CV Persist] Failed to store CV embeddings: {e}")
        import traceback
        traceback.print_exc()


@app.post("/api/analyze-cv")
async def analyze_cv(request: dict):
    """
    Analyze CV and extract structured profile.
    
    In REAL mode (API keys configured): Uses LLM for intelligent parsing.
    In DEMO mode (no API keys): Returns structured demo data with basic extraction.
    """
    from pipeline.steps.cv_analyzer import CVAnalyzer
    
    cv_text = request.get("cvText") or request.get("cv_text", "")
    
    if not cv_text:
        return {"success": False, "error": "CV text required"}
    
    analyzer = CVAnalyzer.from_environment()
    result = await analyzer.analyze(cv_text)

    if result.mode == "unavailable":
        return {
            "success": True,
            "mode": "demo",
            "profile": {
                "name": "",
                "email": None,
                "currentRole": "",
                "company": None,
                "summary": "",
                "yearsExperience": 0,
                "skills": [],
                "achievements": [],
                "leadershipRoles": [],
                "technicalStack": [],
                "metrics": [],
            },
            "highlights": [],
            "suggestedTalkingPoints": [],
            "confidence": 0.0,
            "error": result.error,
            "note": "Demo mode - CV real analysis unavailable without LLM API key",
        }

    if result.success:
        try:
            if await check_db_connection():
                # Build profile data dict with all fields needed for embeddings
                profile_data = {
                    "name": result.profile.name,
                    "email": result.profile.email,
                    "currentRole": result.profile.current_role,
                    "company": result.profile.company,
                    "summary": result.profile.summary,
                    "yearsExperience": result.profile.years_experience,
                    "skills": result.profile.skills,
                    "achievements": result.profile.achievements,
                    "achievement_companies": result.profile.achievement_companies,
                    "all_companies": result.profile.all_companies,
                    "leadership_roles": result.profile.leadership_roles,
                    "technical_stack": result.profile.technical_stack,
                    "metrics": result.profile.metrics,
                }
                await _persist_cv_profile(
                    result.profile.name or "Unknown",
                    cv_text,
                    profile_data,
                )
        except Exception as e:
            print(f"[CV Analyzer] Storage check failed: {e}")
    
    response = {
        "success": result.success,
        "mode": result.mode,
        "profile": {
            "name": result.profile.name,
            "email": result.profile.email,
            "currentRole": result.profile.current_role,
            "company": result.profile.company,
            "summary": result.profile.summary,
            "yearsExperience": result.profile.years_experience,
            "skills": result.profile.skills,
            "achievements": result.profile.achievements,
            "leadershipRoles": result.profile.leadership_roles,
            "technicalStack": result.profile.technical_stack,
            "metrics": result.profile.metrics,
        },
        "analysis_summary": result.analysis_summary,
        "strengths": result.strengths,
        "gaps": result.gaps,
        "recommendations": result.recommendations,
        "highlights": result.highlights,
        "suggestedTalkingPoints": result.suggested_talking_points,
        "confidence": result.confidence,
        "error": result.error,
    }

    if result.mode in {"demo", "fallback"}:
        response["note"] = (
            "Demo mode - configure ANTHROPIC_API_KEY or OPENAI_API_KEY for real LLM analysis"
        )

    return response


@app.post("/api/coach/analyze-cv")
async def analyze_cv_proxy(request: dict):
    """Alias endpoint to match /api/coach/analyze-cv clients."""
    return await analyze_cv(request)


# =============================================================================
# PROFILE REINDEX ENDPOINT - For re-indexing after profile edits
# =============================================================================

class ProfileReindexRequest(BaseModel):
    """Request to reindex a profile after edits"""
    profile_id: Optional[str] = None
    name: Optional[str] = None
    current_role: Optional[str] = None
    years_experience: Optional[int] = None
    skills: Optional[list[str]] = None
    achievements: Optional[list[str]] = None
    summary: Optional[str] = None
    cv_text: Optional[str] = None


@app.post("/api/profile/reindex")
async def reindex_profile(request: ProfileReindexRequest):
    """
    Reindex a profile to regenerate embeddings after edits.
    
    This endpoint:
    1. Finds or creates a profile by name
    2. Deletes existing embeddings (achievements + document_chunks)
    3. Regenerates embeddings with the new data
    
    Use this after editing the profile to ensure the coach uses updated context.
    """
    from storage.database import execute_scalar, execute_query
    from storage.embedding_utils import build_query_embedding, vector_literal
    import re
    
    try:
        # Validate we have data to index (achievements, cv_text, OR profile fields)
        has_profile_fields = bool(
            request.name or request.summary or request.current_role or 
            request.years_experience or (request.skills and len(request.skills) > 0)
        )
        if not request.achievements and not request.cv_text and not has_profile_fields:
            return {"success": False, "error": "No achievements, cv_text, or profile fields provided to index"}
        
        profile_name = request.name or "Unknown"
        
        # Try to find existing profile or create new one
        profile_id = None
        
        if request.profile_id:
            # Use provided profile_id
            profile_id = request.profile_id
        else:
            # Try to find by name
            existing_id = await execute_scalar(
                "SELECT id FROM user_profiles WHERE name = $1 ORDER BY created_at DESC LIMIT 1",
                profile_name
            )
            if existing_id:
                profile_id = str(existing_id)
        
        # Delete existing embeddings
        deleted_achievements = 0
        deleted_chunks = 0
        
        if profile_id:
            # Delete achievements
            result = await execute_query(
                "DELETE FROM achievements WHERE profile_id = $1 RETURNING id",
                profile_id
            )
            deleted_achievements = len(result) if result else 0
            
            # Delete document chunks
            result = await execute_query(
                "DELETE FROM document_chunks WHERE profile_id = $1 RETURNING id",
                profile_id
            )
            deleted_chunks = len(result) if result else 0
            
            # Update profile timestamp
            await execute_query(
                "UPDATE user_profiles SET updated_at = NOW() WHERE id = $1",
                profile_id
            )
        
        # If no profile exists, create one
        if not profile_id:
            new_id = await execute_scalar(
                """
                INSERT INTO user_profiles (name, resume_text, created_at, updated_at)
                VALUES ($1, $2, NOW(), NOW())
                RETURNING id
                """,
                profile_name,
                request.cv_text or ""
            )
            profile_id = str(new_id) if new_id else None
        
        if not profile_id:
            return {"success": False, "error": "Failed to create or find profile"}
        
        # Index achievements
        indexed_achievements = 0
        if request.achievements:
            for idx, achievement_text in enumerate(request.achievements):
                if not achievement_text:
                    continue
                
                # Extract metrics
                metrics = re.findall(
                    r"[\d,]+%?|[\d,]+(?:\s+(?:users|customers|accounts|teams|people|years|million|billion|dollars|hours))?",
                    achievement_text.lower()
                )
                metrics = [m.strip() for m in metrics if m.strip()]
                
                # Generate embedding
                embedding_text = f"Achievement: {achievement_text}"
                try:
                    embedding = await build_query_embedding(embedding_text)
                    embedding_vec = vector_literal(embedding)
                    
                    await execute_query(
                        """
                        INSERT INTO achievements 
                        (profile_id, title, context, action, result, metrics, tags, embedding, created_at)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
                        """,
                        profile_id,
                        achievement_text[:200] if achievement_text else "",  # title
                        request.current_role or "",  # context (store role for now)
                        "",  # action
                        "",  # result
                        metrics if metrics else None,
                        None,  # tags
                        embedding_vec,
                    )
                    indexed_achievements += 1
                except Exception as e:
                    print(f"[ProfileReindex] Failed to index achievement {idx}: {e}")
        
        # Index CV text chunks
        indexed_chunks = 0
        if request.cv_text:
            # Split CV into chunks (simple approach - paragraphs)
            paragraphs = [p.strip() for p in request.cv_text.split("\n\n") if p.strip()]
            
            for chunk_text in paragraphs:
                if len(chunk_text) < 20:  # Skip very short chunks
                    continue
                
                try:
                    embedding = await build_query_embedding(chunk_text)
                    embedding_vec = vector_literal(embedding)
                    
                    await execute_query(
                        """
                        INSERT INTO document_chunks
                        (profile_id, source, section, content, embedding, metadata, created_at)
                        VALUES ($1, $2, $3, $4, $5, $6, NOW())
                        """,
                        profile_id,
                        "cv_text",
                        "general",
                        chunk_text[:1000],  # limit content length
                        embedding_vec,
                        json.dumps({"indexed_from": "reindex"}),
                    )
                    indexed_chunks += 1
                except Exception as e:
                    print(f"[ProfileReindex] Failed to index chunk: {e}")
        
        # Index profile fields as synthetic chunks (name, summary, role, skills)
        # This ensures edited fields are searchable even without CV text
        profile_sections = []
        
        if request.name:
            profile_sections.append(f"Name: {request.name}")
        
        if request.current_role:
            profile_sections.append(f"Current Role: {request.current_role}")
        
        if request.years_experience:
            profile_sections.append(f"Experience: {request.years_experience} years")
        
        if request.summary:
            profile_sections.append(f"Summary: {request.summary}")
        
        if request.skills and len(request.skills) > 0:
            profile_sections.append(f"Skills: {', '.join(request.skills)}")
        
        if profile_sections:
            # Create a synthetic profile document
            synthetic_profile = "\n\n".join(profile_sections)
            print(f"[ProfileReindex] Indexing synthetic profile ({len(synthetic_profile)} chars)")
            
            try:
                embedding = await build_query_embedding(synthetic_profile)
                embedding_vec = vector_literal(embedding)
                
                await execute_query(
                    """
                    INSERT INTO document_chunks
                    (profile_id, source, section, content, embedding, metadata, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, NOW())
                    """,
                    profile_id,
                    "profile_fields",
                    "synthetic",
                    synthetic_profile[:2000],
                    embedding_vec,
                    json.dumps({"indexed_from": "profile_fields", "fields": ["name", "role", "experience", "summary", "skills"]}),
                )
                indexed_chunks += 1
                print(f"[ProfileReindex] Successfully indexed synthetic profile chunk")
            except Exception as e:
                print(f"[ProfileReindex] Failed to index synthetic profile: {e}")
        
        return {
            "success": True,
            "profile_id": profile_id,
            "deleted": {
                "achievements": deleted_achievements,
                "document_chunks": deleted_chunks,
            },
            "indexed": {
                "achievements": indexed_achievements,
                "document_chunks": indexed_chunks,
            },
            "message": f"Successfully reindexed profile: {indexed_achievements} achievements, {indexed_chunks} CV chunks"
        }
        
    except Exception as e:
        print(f"[ProfileReindex] Error: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


# =============================================================================
# DEBUG RETRIEVE EVIDENCE ENDPOINT - For verifying evidence retrieval
# =============================================================================

@app.post("/api/debug/retrieve-evidence")
async def debug_retrieve_evidence(request: dict):
    """
    Debug endpoint to see what evidence is retrieved for a question.
    
    This helps verify:
    - What embeddings exist in the database
    - What similarity matches are found
    - Whether the retrieval is working correctly
    
    Returns the raw evidence chunks without going through the full pipeline.
    """
    from storage.database import execute_query
    from storage.embedding_utils import build_query_embedding, vector_literal
    
    try:
        question = request.get("question", "")
        profile_id = request.get("profile_id")
        
        if not question:
            return {"success": False, "error": "Question is required"}
        
        # Build query embedding
        embedding = await build_query_embedding(question)
        embedding_vec = vector_literal(embedding)
        
        # Query achievements
        achievement_results = []
        if profile_id:
            rows = await execute_query(
                """
                SELECT id, title, context, action, result, tags,
                1 - (embedding <=> $1::vector) AS similarity
                FROM achievements
                WHERE profile_id = $2 AND embedding IS NOT NULL
                ORDER BY similarity DESC
                LIMIT 10
                """,
                embedding_vec,
                profile_id
            )
        else:
            rows = await execute_query(
                """
                SELECT id, title, context, action, result, tags, profile_id,
                1 - (embedding <=> $1::vector) AS similarity
                FROM achievements
                WHERE embedding IS NOT NULL
                ORDER BY similarity DESC
                LIMIT 10
                """,
                embedding_vec
            )
        
        for row in rows:
            # Handle asyncpg Record objects and dicts
            def safe_get(record, key, default=None):
                if hasattr(record, 'get'):
                    return record.get(key, default)
                return getattr(record, key, default) if hasattr(record, key) else default
            
            title = safe_get(row, "title", "")
            context = safe_get(row, "context", "")
            action = safe_get(row, "action", "")
            result = safe_get(row, "result", "")
            sim = safe_get(row, "similarity", 0)
            pid = safe_get(row, "profile_id")
            tags = safe_get(row, "tags")
            
            text = f"{title}"
            if context:
                text += f" at {context}"
            if action:
                text += f". {action}"
            if result:
                text += f". {result}"
                
            achievement_results.append({
                "source": "achievement",
                "text": text,
                "similarity_score": float(sim) if sim else 0.0,
                "profile_id": str(pid) if pid else None,
                "metadata": {
                    "title": title,
                    "context": context,
                    "tags": tags or [],
                }
            })
        
        # Query document chunks
        chunk_results = []
        if profile_id:
            rows = await execute_query(
                """
                SELECT id, source, section, content, metadata,
                1 - (embedding <=> $1::vector) AS similarity
                FROM document_chunks
                WHERE profile_id = $2 AND embedding IS NOT NULL
                ORDER BY similarity DESC
                LIMIT 10
                """,
                embedding_vec,
                profile_id
            )
        else:
            rows = await execute_query(
                """
                SELECT id, source, section, content, metadata, profile_id,
                1 - (embedding <=> $1::vector) AS similarity
                FROM document_chunks
                WHERE embedding IS NOT NULL
                ORDER BY similarity DESC
                LIMIT 10
                """,
                embedding_vec
            )
        
        for row in rows:
            if isinstance(row, dict):
                content = row.get("content", "")
                sim = row.get("similarity", 0)
                pid = row.get("profile_id")
                
                chunk_results.append({
                    "source": "document_chunk",
                    "text": content[:500] if content else "",  # Truncate long content
                    "similarity_score": float(sim) if sim else 0.0,
                    "profile_id": str(pid) if pid else None,
                    "metadata": {
                        "source": row.get("source"),
                        "section": row.get("section"),
                    }
                })
        
        # Combine results
        all_evidence = achievement_results + chunk_results
        all_evidence.sort(key=lambda x: x["similarity_score"], reverse=True)
        
        return {
            "success": True,
            "question": question,
            "evidence": all_evidence[:20],  # Top 20
            "total_found": len(all_evidence),
            "achievements_found": len(achievement_results),
            "chunks_found": len(chunk_results),
            "query_embedding_dim": len(embedding) if embedding else 0,
        }
        
    except Exception as e:
        print(f"[DebugRetrieveEvidence] Error: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


# Session management endpoints
class SessionCreateRequest(BaseModel):
    """Request to create a new session"""
    config_id: Optional[str] = None
    company_name: Optional[str] = None
    role_title: Optional[str] = None
    candidate_name: Optional[str] = None
    language_preference: Optional[str] = "en"
    response_style: Optional[str] = "professional"


class SessionUpdateRequest(BaseModel):
    """Request to update session state"""
    status: Optional[str] = None  # "paused", "resumed", "ended"


@app.post("/api/sessions", response_model=dict)
async def create_session(request: SessionCreateRequest):
    """
    Create a new interview session.
    
    Returns session_id that can be used with WebSocket for realtime coaching.
    """
    from storage.session_repo import get_session_repository
    
    try:
        repo = get_session_repository()
        
        # Create session in database
        config_id = request.config_id or "default"
        session_id = await repo.create_session(config_id, status="active")
        
        return {
            "success": True,
            "session_id": session_id,
            "status": "active",
            "message": "Session created. Connect to /ws/pipeline for realtime coaching.",
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "error": f"Failed to create session: {str(e)}",
        }


@app.get("/api/sessions/{session_id}", response_model=dict)
async def get_session(session_id: str):
    """
    Get session state by ID.
    """
    from storage.session_repo import get_session_repository
    
    try:
        repo = get_session_repository()
        session = await repo.get_session(session_id)
        
        if not session:
            return {
                "success": False,
                "error": "Session not found",
            }
        
        # Get exchanges for this session
        exchanges = await repo.get_exchanges(session_id)
        
        return {
            "success": True,
            "session": session,
            "exchanges": exchanges,
            "exchange_count": len(exchanges),
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "error": f"Failed to get session: {str(e)}",
        }


@app.put("/api/sessions/{session_id}", response_model=dict)
async def update_session(session_id: str, request: SessionUpdateRequest):
    """
    Update session state (pause/resume/end).
    """
    from storage.session_repo import get_session_repository
    
    try:
        repo = get_session_repository()
        
        if request.status == "ended":
            summary = {"status": "ended_via_api"}
            await repo.end_session(session_id, summary)
            return {
                "success": True,
                "session_id": session_id,
                "status": "ended",
                "message": "Session ended",
            }
        elif request.status == "paused":
            # Update status to paused (would need to extend schema)
            return {
                "success": True,
                "session_id": session_id,
                "status": "paused",
                "message": "Session paused",
            }
        elif request.status == "resumed":
            # Update status to active
            return {
                "success": True,
                "session_id": session_id,
                "status": "active",
                "message": "Session resumed",
            }
        else:
            return {
                "success": False,
                "error": f"Invalid status: {request.status}",
            }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "error": f"Failed to update session: {str(e)}",
        }


async def _process_audio_for_stt(
    audio_bytes: bytes,
    websocket: WebSocket,
    session_id: str,
    pipeline,
    source: str
):
    """
    Process buffered audio through STT adapter and emit transcript events.
    
    This function:
    1. Sends audio to STT adapter (or mock if no API key)
    2. Emits transcript events back to frontend
    3. Triggers full pipeline processing when final transcript received
    """
    from adapters.stt_adapter import get_stt_adapter
    
    try:
        # Try to get STT adapter
        stt_adapter = await get_stt_adapter()
        await _call_adapter_method(stt_adapter, "open_stream", session_id)
        
        # Create async generator for audio chunks
        async def audio_chunk_generator():
            yield audio_bytes
        
        # Stream audio through STT
        transcript_text = ""
        is_final = False
        
        if _adapter_stream_accepts_session_arg(stt_adapter.stream_audio):
            event_stream = stt_adapter.stream_audio(audio_chunk_generator(), session_id)
        else:
            event_stream = stt_adapter.stream_audio(audio_chunk_generator())
        async for event in event_stream:
            transcript_text = event.text
            is_final = event.is_final
            
            if transcript_text.strip():
                # Emit transcript event to frontend using a single server->client
                # event type. Finalization is carried in `is_final`.
                await websocket.send_json({
                    "type": "transcript",
                    "text": transcript_text,
                    "is_final": is_final,
                    "confidence": event.confidence,
                    "language": event.language,
                    "speaker": event.speaker or "unknown",
                    "source": source,
                })
                
                print(f"[WS] Transcript: '{transcript_text}' (final={is_final})")
        
        # If we got a final transcript, process through the full pipeline
        if is_final and transcript_text.strip():
            print(f"[WS] Processing final transcript through pipeline: '{transcript_text}'")
            
            analysis_emitted = False

            async def _send_progress(event_payload: dict):
                nonlocal analysis_emitted
                if isinstance(event_payload, dict) and event_payload.get("type") == "analysis":
                    analysis_emitted = True
                await websocket.send_json(event_payload)

            result = await pipeline.process_question(
                transcript_text,
                is_final=True,
                on_progress=_send_progress,
            )

            await _emit_analysis_if_missing(websocket, result, analysis_emitted)

            suggested_response = result.exchange.suggested_response
            suggested_metadata = getattr(suggested_response, "metadata", {}) or {}
            if not isinstance(suggested_metadata, dict):
                suggested_metadata = {}
            
            actual_mode = _resolve_result_mode(result, suggested_response, "demo")
            
            await websocket.send_json({
                "type": "suggestion",
                "stage": "full",
                "mode": actual_mode,
                # P4-T1: full_response is primary; bullets are preview-only.
                "full_response": result.exchange.suggested_response.full_response,
                "bullets_preview": result.exchange.suggested_response.bullets,
                "bullets": result.exchange.suggested_response.bullets,
                "key_metrics": result.exchange.suggested_response.key_metrics,
                "confidence": result.exchange.suggested_response.confidence,
                "style": result.exchange.suggested_response.style_used.value,
                "language": result.language_decision.final_language,
                "quality_passed": result.quality_result.passed,
                "quality_score": result.quality_result.score,
                "quality_issues": result.quality_result.issues,
                "latency_ms": result.total_latency_ms,
                "processing_full_response": False,
                "bullets_latency_ms": suggested_metadata.get("time_to_bullets_ms", result.total_latency_ms),
                "full_latency_ms": suggested_metadata.get("time_to_full_ms", result.total_latency_ms),
            })
            
    except Exception as e:
        print(f"[WS] STT processing error: {e}")
        # If STT fails, try a simple energy-based mock transcription
        # This provides basic functionality without Deepgram API key
        await _process_audio_mock(audio_bytes, websocket, source)
    finally:
        if "stt_adapter" in locals():
            try:
                await _call_adapter_method(stt_adapter, "close_stream", session_id)
            except Exception as e:
                print(f"[WS][STT] close_stream warning session_id={session_id} error={e}")


async def _process_audio_mock(
    audio_bytes: bytes,
    websocket: WebSocket,
    source: str
):
    """
    Simple energy-based mock transcription for demo mode.
    Detects if there's significant audio energy and emits a placeholder transcript.
    """
    import numpy as np
    
    try:
        # Convert bytes to numpy array
        samples = np.frombuffer(audio_bytes, dtype=np.int16)
        
        if len(samples) == 0:
            return
        
        # Calculate RMS energy
        rms = np.sqrt(np.mean(samples.astype(np.float32) ** 2))
        rms_normalized = rms / 32768.0
        
        # If there's significant energy, emit a partial transcript
        # In real implementation, this would trigger actual STT
        if rms_normalized > 0.01:  # Above 1% of max amplitude
            # Emit partial transcript indicating audio detected
            await websocket.send_json({
                "type": "transcript",
                "text": "[audio detected - transcription requires Deepgram API key]",
                "is_final": False,
                "confidence": 0.0,
                "language": "en",
                "speaker": "unknown",
                "source": source,
            })
            
    except Exception as e:
        print(f"[WS] Mock transcription error: {e}")


# Official WebSocket endpoint for realtime pipeline
# NOTE: This is the ONLY official realtime entrypoint.
# ws_realtime.py is deprecated and should not be used.
@app.websocket("/ws/pipeline")
async def websocket_pipeline(websocket: WebSocket):
    """
    WebSocket endpoint for full pipeline communication.
    Handles transcript events and returns suggestions through the full pipeline.
    
    Protocol:
    
    Client -> Server (transcript ready):
    {
        "type": "transcript_ready",
        "text": "Cuéntame sobre tu experiencia...",
        "is_final": true,
        "language": "es"
    }
    
    Client -> Server (start session):
    {
        "type": "start_session",
        "config": {
            "company_name": "...",
            "role_title": "...",
            "response_style": "executive"
        }
    }
    
    Server -> Client (analysis):
    {
        "type": "analysis",
        "question_type": "behavioral",
        "is_compound": true,
        "sub_questions": [...]
    }
    
    Server -> Client (suggestion):
    {
        "type": "suggestion",
        "bullets": [...],
        "full_response": "...",
        "confidence": 0.9
    }
    """
    import uuid
    import json
    
    # Declare global for pipeline registry management
    global _active_pipelines
    
    await websocket.accept()
    print("[WS] Pipeline client connected")
    
    # Initialize audio manager
    from api.audio_buffer import get_session_audio_manager
    audio_manager = get_session_audio_manager()
    
    pipeline = None
    session_id = None
    stt_stream_manager: Optional[SessionSTTStreamManager] = None
    
    try:
        # Send connected message
        await websocket.send_json({
            "type": "connected",
            "message": "Pipeline WebSocket connected. Ready for session.",
            "timestamp": datetime.utcnow().isoformat(),
        })
        
        while True:
            data = await websocket.receive_text()
            
            try:
                message = json.loads(data)
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid JSON",
                })
                continue
            
            msg_type = message.get("type", "unknown")
            
            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
            
            elif msg_type == "start_session":
                # Start a new interview session
                config = message.get("config", {})
                
                # Log the context for verification (R1.3)
                candidate_name = config.get("candidate", {}).get("name", "") or config.get("candidate_name", "")
                company_name = config.get("company", {}).get("companyName", "") or config.get("company_name", "")
                role_title = config.get("company", {}).get("positionTitle", "") or config.get("role_title", "")
                print(f"[WS] Session context: candidate={candidate_name}, company={company_name}, role={role_title}")
                
                # Resolve realtime mode from server readiness + optional session override
                default_mode, _, _, _, _ = await resolve_server_mode()
                requested_mode = str(config.get("mode") or "").strip().lower()
                if requested_mode == "demo":
                    use_real = False
                elif requested_mode == "real":
                    use_real = default_mode == "real"
                    if not use_real:
                        print("[WS] Requested real mode but prerequisites missing; falling back to demo")
                else:
                    use_real = default_mode == "real"
                mode = "real" if use_real else "demo"
                
                # Create pipeline
                pipeline = RealtimePipeline(config=PipelineConfig(
                    use_real_llm=use_real,
                    use_real_embeddings=use_real,
                ))
                
                # Use provided session_id or generate new one (for reconnection support)
                session_id = message.get("session_id") or str(uuid.uuid4())
                if message.get("session_id"):
                    print(f"[WS] Reconnecting to existing session_id={session_id}")
                else:
                    print(f"[WS] Creating new session_id={session_id}")
                
                try:
                    await pipeline.start_session(session_id, config)
                finally:
                    stt_stream_manager = None
                try:
                    from adapters.stt_adapter import get_stt_adapter

                    stt_adapter = await get_stt_adapter()
                    await _call_adapter_method(stt_adapter, "open_stream", session_id)
                except Exception as e:
                    print(f"[WS][STT] open_stream warning session_id={session_id} error={e}")
                
                # Register pipeline in global registry for /api/suggest access
                _active_pipelines[session_id] = pipeline
                print(f"[WS] Pipeline registered for session {session_id}")
                
                await websocket.send_json({
                    "type": "session_started",
                    "session_id": session_id,
                    "config": config,
                    "mode": mode,
                })
            
            elif msg_type == "audio_data":
                # Handle incoming audio data from frontend
                # Buffer audio and trigger STT transcription
                if not pipeline:
                    await websocket.send_json({
                        "type": "error",
                        "message": "No active session. Send start_session first.",
                    })
                    continue
                
                audio_base64 = message.get("audio", "")
                timestamp = message.get("timestamp", 0)
                sample_rate = message.get("sample_rate", 16000)
                channels = message.get("channels", 1)
                source = message.get("source", "system")

                print(
                    "[AUDIO][BACKEND][WS_RECV] "
                    f"session_id={session_id} timestamp_ms={timestamp} "
                    f"sample_rate={sample_rate} channels={channels} source={source} "
                    f"payload_b64_len={len(audio_base64)}"
                )
                
                if not audio_base64:
                    await websocket.send_json({
                        "type": "error",
                        "message": "No audio data provided",
                    })
                    continue

                audio_bytes = None
                
                try:
                    # DUAL_STT_PHASE1: Send audio directly to STT without AudioBuffer gating
                    # This eliminates the 2+ second delay before first transcript appears
                    # Decode base64 directly - no buffering for STT path
                    import base64
                    try:
                        audio_bytes = base64.b64decode(audio_base64)
                    except Exception as e:
                        print(f"[WS] Error decoding audio base64: {e}")
                        await websocket.send_json({
                            "type": "error",
                            "message": f"Invalid audio data: {str(e)}",
                        })
                        continue
                    
                    decoded_audio_len = len(audio_bytes) if audio_bytes else 0
                    
                    print(
                        "[AUDIO][BACKEND][DIRECT] "
                        f"session_id={session_id} timestamp_ms={timestamp} "
                        f"payload_b64_len={len(audio_base64)} decoded_audio_bytes={decoded_audio_len}"
                    )
                    
                    # Acknowledge audio data received
                    await websocket.send_json({
                        "type": "audio_received",
                        "timestamp": timestamp,
                        "bytes_received": len(audio_base64),
                        "direct_to_stt": True,
                    })
                    
                    # Always send directly to STT - no buffering delay
                    if audio_bytes:
                        if stt_stream_manager is None:
                            stt_stream_manager = SessionSTTStreamManager(
                                websocket=websocket,
                                pipeline=pipeline,
                                session_id=session_id,
                                default_mode=mode,
                            )

                        print(
                            "[AUDIO][BACKEND][STT_ENQUEUE] "
                            f"session_id={session_id} timestamp_ms={timestamp} "
                            f"source={source} decoded_audio_bytes={len(audio_bytes)}"
                        )

                        await stt_stream_manager.enqueue_audio(audio_bytes, source)
                    
                except Exception as e:
                    print(f"[WS] Error processing audio data: {e}")
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Error processing audio: {str(e)}",
                    })

                    if audio_bytes:
                        await _process_audio_mock(audio_bytes, websocket, source)
            
            elif msg_type == "transcript_ready":
                if not pipeline:
                    await websocket.send_json({
                        "type": "error",
                        "message": "No active session. Send start_session first.",
                    })
                    continue
                
                text = message.get("text", "")
                is_final = message.get("is_final", True)
                language = message.get("language") or "en"
                speaker = str(message.get("speaker") or "interviewer")
                request_id = _extract_request_id(message) or "client"
                transcript_id = str(message.get("transcript_id") or message.get("transcriptId") or uuid.uuid4())
                
                if not text:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Empty transcript",
                    })
                    continue

                if str(text).startswith("[STT Error:") or message.get("stt_error") or message.get("is_error"):
                    print(
                        "[PIPELINE][HANDOFF] transcript_error "
                        f"session_id={session_id} transcript_id={transcript_id} "
                        f"request_id={request_id}"
                    )
                    continue

                print(
                    "[PIPELINE][HANDOFF] transcript_received "
                    f"session_id={session_id} transcript_id={transcript_id}"
                )

                transcript_metadata = _build_transcript_metadata(
                    session_id=session_id or "unknown",
                    transcript_id=transcript_id,
                    request_id=request_id,
                    language=language,
                    speaker=speaker,
                    source=str(message.get("source") or "client"),
                )
                
                # Process through pipeline
                try:
                    analysis_emitted = False
                    analysis_emitted_via_handoff = False
                    handoff_start = perf_counter()

                    async def _send_progress(event_payload: dict):
                        nonlocal analysis_emitted, analysis_emitted_via_handoff
                        if isinstance(event_payload, dict) and event_payload.get("type") == "analysis":
                            analysis_emitted = True
                            analysis_emitted_via_handoff = True
                        await websocket.send_json(event_payload)

                    print(
                        "[PIPELINE][HANDOFF] pipeline_start "
                        f"session_id={session_id} transcript_id={transcript_id} "
                        f"request_id={request_id}"
                    )

                    if _supports_transcript_metadata(pipeline):
                        result = await pipeline.process_question(
                            text,
                            is_final=is_final,
                            on_progress=_send_progress,
                            transcript_metadata=transcript_metadata,
                        )
                    else:
                        result = await pipeline.process_question(
                            text,
                            is_final=is_final,
                            on_progress=_send_progress,
                        )

                    analysis_emitted_via_handoff = await _emit_analysis_if_missing(
                        websocket,
                        result,
                        analysis_emitted,
                    ) or analysis_emitted_via_handoff

                    suggested_response = result.exchange.suggested_response
                    suggested_metadata = getattr(suggested_response, "metadata", {}) or {}
                    if not isinstance(suggested_metadata, dict):
                        suggested_metadata = {}
                    
                    # Determine actual mode from result
                    actual_mode = _resolve_result_mode(result, suggested_response, mode)
                    provider_used = suggested_metadata.get("provider")
                    model_used = suggested_metadata.get("model")
                    if actual_mode == "real":
                        print(
                            f"[WS] REAL mode verified provider={provider_used or 'unknown'} "
                            f"model={model_used or 'unknown'}"
                        )
                    elif actual_mode == "fallback":
                        print("[WS] Fallback mode used after real path failure")
                    else:
                        print("[WS] Demo mode used")
                    
                    # Send suggestion with explicit mode
                    await websocket.send_json({
                        "type": "suggestion",
                        "stage": "full",
                        "mode": actual_mode,
                        # P4-T1: full_response is primary; bullets are preview-only.
                        "full_response": result.exchange.suggested_response.full_response,
                        "bullets_preview": result.exchange.suggested_response.bullets,
                        "bullets": result.exchange.suggested_response.bullets,
                        "key_metrics": result.exchange.suggested_response.key_metrics,
                        "confidence": result.exchange.suggested_response.confidence,
                        "style": result.exchange.suggested_response.style_used.value,
                        "language": result.language_decision.final_language,
                        "quality_passed": result.quality_result.passed,
                        "quality_score": result.quality_result.score,
                        "quality_issues": result.quality_result.issues,
                        "latency_ms": result.total_latency_ms,
                        "processing_full_response": False,
                        "bullets_latency_ms": suggested_metadata.get("time_to_bullets_ms", result.total_latency_ms),
                        "full_latency_ms": suggested_metadata.get("time_to_full_ms", result.total_latency_ms),
                        "provider": provider_used,
                        "model": model_used,
                        "transcript_id": transcript_id,
                        "request_id": request_id,
                    })

                    handoff_latency_ms = int((perf_counter() - handoff_start) * 1000)
                    print(
                        "[PIPELINE][HANDOFF] pipeline_complete "
                        f"session_id={session_id} transcript_id={transcript_id} "
                        f"request_id={request_id} latency_ms={handoff_latency_ms}"
                    )
                    if analysis_emitted_via_handoff:
                        print(
                            "[PIPELINE][HANDOFF] event_sequence "
                            f"session_id={session_id} transcript_id={transcript_id} "
                            "sequence=transcript->analysis->suggestion"
                        )
                    
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Pipeline error: {str(e)}",
                    })
            
            elif msg_type == "pause_session":
                if not pipeline:
                    await websocket.send_json({
                        "type": "error",
                        "message": "No active session to pause",
                    })
                else:
                    # Mark session as paused
                    if pipeline.session_state:
                        pipeline.session_state.status = "paused"
                    await websocket.send_json({
                        "type": "session_paused",
                        "session_id": session_id,
                    })
            
            elif msg_type == "resume_session":
                if not pipeline:
                    await websocket.send_json({
                        "type": "error",
                        "message": "No session to resume",
                    })
                else:
                    # Mark session as active again
                    if pipeline.session_state:
                        pipeline.session_state.status = "active"
                    await websocket.send_json({
                        "type": "session_resumed",
                        "session_id": session_id,
                    })
            
            elif msg_type == "end_session":
                if pipeline:
                    if stt_stream_manager:
                        await stt_stream_manager.stop()
                        stt_stream_manager = None
                    else:
                        try:
                            from adapters.stt_adapter import get_stt_adapter

                            stt_adapter = await get_stt_adapter()
                            await _call_adapter_method(stt_adapter, "close_stream", session_id)
                            await _call_adapter_method(stt_adapter, "disconnect", session_id)
                            from adapters.stt_adapter import reset_stt_adapter

                            await reset_stt_adapter()
                        except Exception as e:
                            print(f"[WS][STT] close_stream warning session_id={session_id} error={e}")

                    # Clean up audio buffer for this session
                    try:
                        from api.audio_buffer import get_session_audio_manager
                        audio_manager = get_session_audio_manager()
                        audio_manager.remove_buffer(session_id)
                    except Exception as e:
                        print(f"[WS] Error cleaning up audio buffer: {e}")
                    
                    summary = await pipeline.end_session()
                    
                    # Persist session to database if session_id exists
                    try:
                        from storage.session_repo import get_session_repository
                        repo = get_session_repository()
                        # Log the session end event
                        await repo.log_event(
                            session_id,
                            "session_ended",
                            {"summary": summary}
                        )
                    except Exception as db_err:
                        print(f"[WS] Could not persist session: {db_err}")
                    
                    await websocket.send_json({
                        "type": "session_ended",
                        "summary": summary,
                    })
                    
                    # Unregister pipeline from global registry
                    if session_id in _active_pipelines:
                        del _active_pipelines[session_id]
                        print(f"[WS] Pipeline unregistered for session {session_id}")
                    
                    pipeline = None
                    session_id = None
                else:
                    await websocket.send_json({
                        "type": "session_ended",
                        "summary": {},
                    })
            
            elif msg_type == "manual_question":
                # Handle manual question input (when audio isn't working)
                if not pipeline:
                    await websocket.send_json({
                        "type": "error",
                        "message": "No active session. Send start_session first.",
                    })
                    continue
                
                question = message.get("question", "")
                if not question:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Empty question",
                    })
                    continue
                
                # Process through pipeline as transcript_ready
                try:
                    analysis_emitted = False

                    async def _send_progress_manual(event_payload: dict):
                        nonlocal analysis_emitted
                        if isinstance(event_payload, dict) and event_payload.get("type") == "analysis":
                            analysis_emitted = True
                        await websocket.send_json(event_payload)

                    result = await pipeline.process_question(
                        question,
                        is_final=True,
                        on_progress=_send_progress_manual,
                    )

                    await _emit_analysis_if_missing(websocket, result, analysis_emitted)

                    suggested_response = result.exchange.suggested_response
                    suggested_metadata = getattr(suggested_response, "metadata", {}) or {}
                    if not isinstance(suggested_metadata, dict):
                        suggested_metadata = {}
                    
                    # Determine actual mode from result
                    actual_mode = _resolve_result_mode(result, suggested_response, mode)
                    
                    await websocket.send_json({
                        "type": "suggestion",
                        "stage": "full",
                        "mode": actual_mode,
                        "question": question,
                        # P4-T1: full_response is primary; bullets are preview-only.
                        "full_response": result.exchange.suggested_response.full_response,
                        "bullets_preview": result.exchange.suggested_response.bullets,
                        "bullets": result.exchange.suggested_response.bullets,
                        "key_metrics": result.exchange.suggested_response.key_metrics,
                        "confidence": result.exchange.suggested_response.confidence,
                        "style": result.exchange.suggested_response.style_used.value,
                        "language": result.language_decision.final_language,
                        "quality_passed": result.quality_result.passed,
                        "quality_score": result.quality_result.score,
                        "quality_issues": result.quality_result.issues,
                        "latency_ms": result.total_latency_ms,
                        "processing_full_response": False,
                        "bullets_latency_ms": suggested_metadata.get("time_to_bullets_ms", result.total_latency_ms),
                        "full_latency_ms": suggested_metadata.get("time_to_full_ms", result.total_latency_ms),
                    })
                    
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Manual question error: {str(e)}",
                    })
            
            elif msg_type == "request_suggestion":
                # Handle history-based suggestion request (manual or silence-triggered)
                print(f"[DEBUG][REQUEST_SUGGESTION] Handler triggered - checking pipeline...")
                if not pipeline:
                    print(f"[DEBUG][REQUEST_SUGGESTION] ERROR: No active pipeline!")
                    await websocket.send_json({
                        "type": "error",
                        "message": "No active session. Send start_session first.",
                    })
                    continue

                print(f"[DEBUG][REQUEST_SUGGESTION] Pipeline active, fetching turns...")
                # ALWAYS get last 4 turns - no speaker filter, no time filter
                # This ensures suggestions work even if last speaker was candidate
                recent_turns = pipeline.conversation_tracker.get_last_n_turns(limit=4)

                # DEBUG: Log turn history
                print(f"[DEBUG][REQUEST_SUGGESTION] Recent turns in history (no filter): count={len(recent_turns)}")
                for i, t in enumerate(recent_turns):
                    speaker = t.get('speaker', 'unknown')
                    text = t.get('text', '')[:60]
                    print(f"[DEBUG][REQUEST_SUGGESTION]   Turn {i}: speaker={speaker} text='{text}...'")

                # If no turns at all, use empty context but still process
                if not recent_turns:
                    print("[DEBUG][REQUEST_SUGGESTION] WARNING: No turns in history!")
                    recent_turns = []

                # Use the most recent turn as the primary question (regardless of speaker)
                last_turn = recent_turns[-1] if recent_turns else None

                print(f"[DEBUG][REQUEST_SUGGESTION] Selected last_turn: speaker={last_turn.get('speaker') if last_turn else None}")

                # Process through history-based pipeline (bypasses constraints)
                try:
                    from time import perf_counter

                    # Get context from recent turns (no speaker filter) - same as recent_turns
                    context = recent_turns  # Use the same list, don't fetch again

                    # Build pipeline input - use most recent turn text as the question
                    question_text = last_turn.get("text", "") if last_turn else ""
                    print(f"[DEBUG][REQUEST_SUGGESTION] question_text='{question_text[:60] if question_text else 'NONE'}...'")
                    print(f"[DEBUG][REQUEST_SUGGESTION] context has {len(context)} turns")
                    
                    # DEBUG: Print full context being sent to pipeline
                    print("\n" + "="*80)
                    print("[DEBUG][REQUEST_SUGGESTION] FULL CONTEXT SENT TO PIPELINE")
                    print("="*80)
                    print(f"Total turns: {len(context)}")
                    for i, turn in enumerate(context):
                        speaker = turn.get('speaker', 'unknown')
                        text = turn.get('text', '')
                        timestamp = turn.get('timestamp', 'N/A')
                        print(f"  Turn {i}: speaker={speaker}")
                        print(f"         text='{text}'")
                        print(f"         timestamp={timestamp}")
                    print("="*80 + "\n")

                    # Send progress indicator
                    await websocket.send_json({
                        "type": "analysis",
                        "stage": "history_based",
                        "context_turns": len(context),
                    })

                    print(f"[DEBUG][REQUEST_SUGGESTION] Calling pipeline.process_question with context={len(context)} turns")
                    # Process through pipeline with context from conversation history
                    result = await pipeline.process_question(
                        question_text,
                        is_final=True,
                        on_progress=lambda e: websocket.send_json(e),
                        context=context,  # Pass the conversation context
                    )
                    print(f"[DEBUG][REQUEST_SUGGESTION] process_question completed")
                    
                    # Format response similar to manual_question
                    suggested_response = result.exchange.suggested_response
                    suggested_metadata = getattr(suggested_response, "metadata", {}) or {}
                    if not isinstance(suggested_metadata, dict):
                        suggested_metadata = {}
                    
                    # Determine actual mode from result
                    actual_mode = _resolve_result_mode(result, suggested_response, mode)
                    
                    await websocket.send_json({
                        "type": "suggestion",
                        "stage": "full",
                        "mode": actual_mode,
                        "source": "history_based",
                        "question": question_text,
                        "context_turns": len(context),
                        # P4-T1: full_response is primary; bullets are preview-only.
                        "full_response": result.exchange.suggested_response.full_response,
                        "bullets_preview": result.exchange.suggested_response.bullets,
                        "bullets": result.exchange.suggested_response.bullets,
                        "key_metrics": result.exchange.suggested_response.key_metrics,
                        "confidence": result.exchange.suggested_response.confidence,
                        "style": result.exchange.suggested_response.style_used.value,
                        "language": result.language_decision.final_language,
                        "quality_passed": result.quality_result.passed,
                        "quality_score": result.quality_result.score,
                        "quality_issues": result.quality_result.issues,
                        "latency_ms": result.total_latency_ms,
                        "processing_full_response": False,
                        "bullets_latency_ms": suggested_metadata.get("time_to_bullets_ms", result.total_latency_ms),
                        "full_latency_ms": suggested_metadata.get("time_to_full_ms", result.total_latency_ms),
                    })
                    
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    await websocket.send_json({
                        "type": "suggestion_error",
                        "message": f"History-based suggestion error: {str(e)}",
                    })
            
            else:
                await websocket.send_json({
                    "type": "error",
                    "message": f"Unknown message type: {msg_type}",
                })
    
    except WebSocketDisconnect:
        print(f"[WS] Pipeline client disconnected session_id={session_id}")
    except Exception as e:
        print(f"[WS] Error session_id={session_id}: {e}")
    finally:
        if stt_stream_manager:
            try:
                await stt_stream_manager.stop()
            except Exception:
                pass
        if pipeline:
            try:
                summary = await pipeline.end_session()
                print(f"[WS] Session ended session_id={session_id} summary={summary}")
            except Exception as e:
                print(f"[WS] Error ending session session_id={session_id}: {e}")
        # Unregister pipeline from global registry on disconnect
        if session_id:
            if session_id in _active_pipelines:
                del _active_pipelines[session_id]
                print(f"[WS] Pipeline unregistered on disconnect for session {session_id}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
