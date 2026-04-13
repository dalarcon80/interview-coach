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
import copy
import inspect
import uuid
import time
import json
import re
import contextlib
from time import perf_counter
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from dataclasses import dataclass, replace
from hashlib import sha1
from typing import Any, Optional, Literal, Dict

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field
import yaml

# Expose RealtimePipeline symbols at module scope for integration test patching
from pipeline.realtime_pipeline import RealtimePipeline, PipelineConfig
from pipeline.steps.turn_assembler import TurnAssembler, SpeakerTurn
from pipeline.silence_detector import (
    DEFAULT_ACTIVE_ASK_IDLE_CLOSE_SEC,
    SilenceDetector,
    build_realtime_context_bundle,
    resolve_realtime_context_bundle,
    select_realtime_active_turn_window,
)
from pipeline.steps.live_question_planner import LiveQuestionPlanner
from conversation.speaker_fallback import SpeakerFallbackCorrector
from contracts.models import (
    AskBrief,
    AskFamily,
    AnswerContract,
    LiveAskSummary,
    LivePreparedContext,
    BrainSnapshot,
    BrainPlan,
    CompactEvidencePack,
    ComplexityClass,
    AnswerShape,
    MetricsPolicy,
)
from pipeline.steps.live_brain_service import LiveBrainService, LiveBrainServiceConfig
from pipeline.steps.live_evidence_packer import LiveEvidencePacker, LiveEvidencePackerConfig
from pipeline.steps.live_finalizer import LiveFinalizer, LiveFinalizerConfig
from pipeline.steps.insights_service import InsightsService
from storage.insights_store import InsightsStore
from runtime_config_store import get_runtime_config_path, load_runtime_config_payload, save_runtime_config_payload

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


# In-memory runtime config storage (loaded from a local config path on startup)
_RUNTIME_CONFIG: RuntimeConfig | None = None

# Global registry of active pipelines by session_id
# Used to access in-memory conversation history during active sessions
_active_pipelines: Dict[str, Any] = {}
_INSIGHTS_SERVICE = InsightsService()
_INSIGHTS_STORE = InsightsStore()


def load_runtime_config() -> RuntimeConfig | None:
    """Load runtime config from file if exists"""
    global _RUNTIME_CONFIG
    try:
        data = load_runtime_config_payload()
        if data is not None:
            _RUNTIME_CONFIG = RuntimeConfig(**data)
            print(f"[RuntimeConfig] Loaded from {get_runtime_config_path()}")
            return _RUNTIME_CONFIG
    except Exception as e:
        print(f"[RuntimeConfig] Could not load config: {e}")
    return None


def save_runtime_config(config: RuntimeConfig) -> RuntimeConfig:
    """Save runtime config to file"""
    global _RUNTIME_CONFIG
    try:
        save_runtime_config_payload(config.model_dump())
        _RUNTIME_CONFIG = config
        print(f"[RuntimeConfig] Saved to {get_runtime_config_path()}")
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
    target_company_info: Optional[dict[str, Any]] = None
    target_role_info: Optional[dict[str, Any]] = None
    interviewer_profile: Optional[dict[str, Any]] = None
    target_context: Optional[dict[str, Any]] = None
    style_id: Optional[str] = "professional"
    language: Optional[str] = "en"
    mode: Optional[Literal["real", "demo"]] = None
    # Profile ID for filtering evidence retrieval (from reindexed profile)
    profile_id: Optional[str] = None
    company_context_id: Optional[str] = None
    interviewer_context_id: Optional[str] = None
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


class ResearchContextAnalyzeRequest(BaseModel):
    kind: Literal["company", "interviewer"]
    urls: list[str] = Field(default_factory=list)
    manual_text: str = ""
    language: Optional[str] = "en"


class ResearchContextIndexRequest(BaseModel):
    kind: Literal["company", "interviewer"]
    context_id: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    raw_text: Optional[str] = None
    source_urls: list[str] = Field(default_factory=list)


class InsightsAnalyzeRequest(BaseModel):
    workspace_id: Optional[str] = None
    candidate_profile: Optional[dict[str, Any]] = None
    company_info: Optional[dict[str, Any]] = None
    interviewer_profile: Optional[dict[str, Any]] = None
    cv_text: str = ""
    language: Optional[str] = "en"
    target_role_override: Optional[str] = None
    archetype_override: Optional[str] = None
    seniority_override: Optional[str] = None
    specialty_ids: list[str] = Field(default_factory=list)


class InsightsAnswerRequest(BaseModel):
    workspace_id: str
    run_id: str
    question_id: str
    answer: str


class InsightsWorkspaceAutosaveRequest(BaseModel):
    ui_state: dict[str, Any] = Field(default_factory=dict)
    workspace_state: Optional[Literal["active", "stale", "draft", "approved"]] = None


class InsightsPreviewRequest(BaseModel):
    workspace_id: str
    run_id: str
    variant: Literal["master_cv", "role_variant_cv"] = "master_cv"


class InsightsApplyRequest(BaseModel):
    workspace_id: str
    run_id: str
    approved_change_ids: list[str] = Field(default_factory=list)
    approved_evidence_ids: list[str] = Field(default_factory=list)
    targets: list[Literal["candidate_profile", "cv_text"]] = Field(default_factory=list)
    variant: Optional[Literal["master_cv", "role_variant_cv"]] = None


class InsightsExportRequest(BaseModel):
    workspace_id: str
    run_id: str
    variant: Literal["master_cv", "role_variant_cv"] = "master_cv"


@dataclass(frozen=True)
class LiveFrozenSnapshot:
    raw_turn_window: list[dict[str, Any]]
    turn_window: list[dict[str, Any]]
    raw_context_bundle: dict[str, Any]
    signature: str
    question_text: str
    conversation_history: list[dict[str, Any]]
    prepared_context: Optional[LivePreparedContext]
    request_payload: dict[str, Any]
    question_source: str
    cache_hit: bool
    checkpoint_id: str = ""
    question_key: str = ""
    brain_snapshot: Optional[BrainSnapshot] = None
    brain_plan: Optional[BrainPlan] = None
    compact_evidence_pack: Optional[CompactEvidencePack] = None
    plan_hash: str = ""
    recovery_draft: str = ""
    recovery_draft_available: bool = False


@dataclass(frozen=True)
class LiveWarmCheckpoint:
    checkpoint_id: str
    parent_checkpoint_id: Optional[str]
    signature: str
    question_key: str
    question_text: str
    conversation_history: list[dict[str, Any]]
    prepared_context: LivePreparedContext
    created_at: datetime
    source_generation: int


@dataclass(frozen=True)
class LiveWarmResult:
    checkpoint_id: str
    signature: str
    question_key: str
    question_text: str
    response: dict[str, Any]
    started_at: datetime
    completed_at: datetime
    success: bool


@dataclass(frozen=True)
class LiveBrainWarmCheckpoint:
    checkpoint_id: str
    parent_checkpoint_id: Optional[str]
    plan_hash: str
    question_key: str
    question_text: str
    brain_plan: BrainPlan
    compact_evidence_pack: CompactEvidencePack
    conversation_history: list[dict[str, Any]]
    created_at: datetime
    source_revision_id: int


@dataclass(frozen=True)
class LiveBrainWarmResult:
    checkpoint_id: str
    plan_hash: str
    question_key: str
    question_text: str
    brain_plan: Optional[BrainPlan]
    response: dict[str, Any]
    started_at: datetime
    completed_at: datetime
    success: bool


def _clean_string_list(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []
    cleaned: list[str] = []
    for value in values:
        text = str(value).strip()
        if text:
            cleaned.append(text)
    return cleaned


def _compact_text(text: str, limit: int = 2400) -> str:
    collapsed = re.sub(r"\s+", " ", text or "").strip()
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 3].rstrip() + "..."


def _strip_transcript_artifacts(text: str) -> str:
    """Remove UI transcript labels/timestamps from pasted or forwarded transcript text."""
    if not text:
        return ""

    text = re.sub(r"\[STT Error:[^\]]+\]", " ", str(text), flags=re.IGNORECASE)

    speaker_labels = {
        "interviewer",
        "candidate",
        "system",
        "unknown",
        "nterviewer",
    }
    cleaned_lines: list[str] = []
    for raw_line in str(text).splitlines():
        line = " ".join(raw_line.split()).strip()
        if not line:
            continue
        lowered = line.lower()
        if lowered in speaker_labels:
            continue
        if re.fullmatch(r"\d{1,2}:\d{2}(?::\d{2})?\s*(am|pm)", lowered):
            continue
        cleaned_lines.append(line)
    return " ".join(cleaned_lines).strip()


def _sanitize_live_turn_text(text: str) -> str:
    cleaned = _strip_transcript_artifacts(text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _derive_live_complexity_and_shape(
    ask_brief: AskBrief,
    *,
    interview_type: str = "mixed",
) -> tuple[ComplexityClass, AnswerShape, int, bool, bool, bool]:
    ask_count = len([ask for ask in [ask_brief.primary_ask, *ask_brief.secondary_asks] if ask])
    family = ask_brief.answer_family
    interview_type_normalized = str(interview_type or "mixed").strip().lower()

    if family == AskFamily.CULTURE_FIT:
        return (
            ComplexityClass.SIMPLE,
            AnswerShape.DIRECT_SHORT,
            120,
            False,
            False,
            True,
        )

    if family in {family.TECHNICAL_CONCEPT, family.ARCHITECTURE_DESIGN} or interview_type_normalized in {
        "technical",
        "system_design",
    }:
        return (
            ComplexityClass.DEEP_TECHNICAL,
            AnswerShape.TECHNICAL_EXPLAINER,
            170,
            family == family.ARCHITECTURE_DESIGN,
            False,
            ask_count > 1,
        )

    if family in {family.BUSINESS_STRATEGY, family.METRICS_OUTCOMES}:
        return (
            ComplexityClass.STRATEGY,
            AnswerShape.STRATEGIC_EXPLAINER,
            180,
            True,
            False,
            ask_count > 1,
        )

    if ask_count > 1 or family in {family.MIXED_COMPOUND, family.EXPERIENCE_SCOPE}:
        return (
            ComplexityClass.COMPOUND,
            AnswerShape.DIRECT_STRUCTURED,
            220,
            ask_brief.metrics_policy != MetricsPolicy.AVOID_UNLESS_REQUESTED,
            False,
            True,
        )

    return (
        ComplexityClass.SIMPLE,
        AnswerShape.DIRECT_SHORT,
        110,
        ask_brief.metrics_policy == MetricsPolicy.REQUIRED,
        False,
        False,
    )


def _clean_live_focus_text(text: str) -> str:
    cleaned = _sanitize_live_turn_text(text)
    if not cleaned:
        return ""

    patterns = [
        r"^(daniel(?:le)?(?:\s+alarc[oó]n)?)[,:-]?\s*",
        r"^(so|yeah|and|but|okay|ok|well)\b[\s,.-]*",
        r"^(i guess|i mean|if you want|as we go)\b[\s,.-]*",
        r"^(we (?:will|were) talk(?:ing)? about)\b[\s,.-]*",
        r"^(in terms of your experience)\b[\s,.-]*",
        r"^(i (?:just )?wanted to ask you(?:, like)?)\b[\s,.-]*",
        r"^(or not the role, but)\b[\s,.-]*",
        r"^(basically what you have done in your experience)\b[\s,.-]*",
        r"^(hear specifically examples of)\b[\s,.-]*",
        r"^(last question as as we go)\b[\s,.-]*",
    ]
    previous = None
    while cleaned != previous:
        previous = cleaned
        for pattern in patterns:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()

    lowered = " ".join(cleaned.lower().split()).strip(" ,.-")
    if lowered in {
        "tell me",
        "and tell me",
        "and then",
        "last question",
        "if you want",
        "walk me through",
        "describe",
        "explain",
    }:
        return ""

    cleaned = re.sub(r"\betcetera\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.-")
    return cleaned


def _extract_live_culture_fit_focus(full_text: str) -> list[str]:
    normalized = " ".join(str(full_text or "").split()).strip()
    lowered = normalized.lower()
    if not lowered:
        return []

    asks: list[str] = []

    if "what are you looking for in terms of the company" in lowered:
        asks.append("What are you looking for in terms of the company, the culture, teams?")
    elif "what are you looking for in a company and culture" in lowered:
        asks.append("What are you looking for in a company and culture?")
    elif re.search(r"what are you looking for .*?\bcompany\b", lowered):
        asks.append("What are you looking for in a company?")

    important_phrase = ""
    if "what's important for you" in lowered:
        important_phrase = "What's important for you"
    elif "what is important for you" in lowered:
        important_phrase = "What is important for you"

    if important_phrase:
        if re.search(r"what kind of things you absolutely (?:don't|do not) like", lowered):
            asks.append(f"{important_phrase}, or what kind of things you absolutely don't like?")
        elif re.search(r"what kind of things you absolutely like", lowered):
            asks.append(f"{important_phrase}, or what kind of things you absolutely like?")
        else:
            asks.append(f"{important_phrase}?")
    elif re.search(r"what kind of things you absolutely (?:don't|do not) like", lowered):
        asks.append("What kind of things do you absolutely not like?")
    elif re.search(r"what kind of things you absolutely like", lowered):
        asks.append("What kind of things do you absolutely like?")

    deduped: list[str] = []
    for ask in asks:
        cleaned = _clean_live_focus_text(ask)
        if cleaned and cleaned not in deduped:
            deduped.append(cleaned)
    return deduped


def _canonicalize_live_asks(
    ask_brief: AskBrief,
    live_turn_window: list[dict[str, Any]],
) -> tuple[str, list[str], list[str]]:
    cleaned_asks: list[str] = []
    for ask in [ask_brief.primary_ask, *ask_brief.secondary_asks]:
        normalized = _clean_live_focus_text(ask)
        if normalized and normalized not in cleaned_asks:
            cleaned_asks.append(normalized)

    full_text = " ".join(turn.get("text", "") for turn in live_turn_window).lower()
    culture_fit_focus = _extract_live_culture_fit_focus(full_text)
    if culture_fit_focus:
        cleaned_asks = culture_fit_focus
    if not cleaned_asks:
        cleaned_turns = [
            _clean_live_focus_text(turn.get("text", ""))
            for turn in live_turn_window
        ]
        cleaned_asks = [ask for ask in cleaned_turns if ask]

    specific_asks: list[str] = []
    broad_intro_asks: list[str] = []
    for ask in cleaned_asks:
        ask_lower = ask.lower()
        is_intro = bool(
            re.search(
                r"tell(?:ing)? me a little bit about you|tell me about yourself|quick intro|brief intro|start telling",
                ask_lower,
            )
        )
        if is_intro:
            broad_intro_asks.append(ask)
        else:
            specific_asks.append(ask)

    canonical_focus: list[str] = []
    for ask in [*specific_asks, *broad_intro_asks]:
        if not ask:
            continue
        ask_lower = ask.lower()
        if ask_lower in full_text or ask not in canonical_focus:
            canonical_focus.append(ask)

    canonical_focus = canonical_focus[:4]
    primary_ask = canonical_focus[0] if canonical_focus else _clean_live_focus_text(ask_brief.primary_ask)
    secondary_asks = canonical_focus[1:4]
    ordered_focus = [ask for ask in [primary_ask, *secondary_asks] if ask]
    return primary_ask, secondary_asks, ordered_focus


def _build_live_question_from_focus(ordered_focus: list[str], fallback_question: str) -> str:
    normalized_focus = []
    for item in ordered_focus:
        normalized = " ".join(str(item or "").split()).strip()
        if normalized and normalized not in normalized_focus:
            normalized_focus.append(normalized)

    if not normalized_focus:
        return fallback_question
    if len(normalized_focus) == 1:
        return normalized_focus[0]

    lines = [normalized_focus[0], "Also cover:"]
    lines.extend(f"- {focus}" for focus in normalized_focus[1:])
    return "\n".join(lines)


def _normalize_live_question_text(text: str) -> str:
    lines = []
    for raw_line in str(text or "").splitlines():
        cleaned = " ".join(raw_line.split()).strip()
        if cleaned:
            lines.append(cleaned)
    if not lines:
        return ""
    return "\n".join(lines)


def _normalize_live_question_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in _normalize_live_question_text(text).splitlines():
        cleaned = raw_line.strip()
        if not cleaned:
            continue
        if cleaned.lower() == "also cover:":
            continue
        cleaned = re.sub(r"^[-*]\s*", "", cleaned)
        cleaned = " ".join(cleaned.split()).strip()
        if cleaned:
            lines.append(cleaned.lower())
    return lines


def _is_live_warm_seed_compatible(seed_question_text: str, target_question_text: str) -> bool:
    seed_lines = _normalize_live_question_lines(seed_question_text)
    target_lines = _normalize_live_question_lines(target_question_text)
    if not seed_lines or not target_lines:
        return False
    if len(seed_lines) > len(target_lines):
        return False
    return seed_lines == target_lines[: len(seed_lines)]


def _canonicalize_live_prepared_context(
    prepared_context: Optional[LivePreparedContext],
) -> Optional[LivePreparedContext]:
    # Keep the live planner simple. The prepared context used for generation
    # must reflect the exact snapshot that created it, without late rewrites.
    return prepared_context


def _build_live_quality_cache_key(
    prepared_context: Optional[LivePreparedContext],
) -> str:
    if prepared_context is None:
        return ""
    question_key = _build_live_question_from_prepared_context(prepared_context, "")
    question_key = _normalize_live_question_text(question_key)
    return question_key.lower()


def _build_live_question_from_brain_plan(
    plan: Optional[BrainPlan],
    fallback_question_text: str = "",
) -> str:
    if plan is None:
        return _normalize_live_question_text(fallback_question_text)

    asks = [
        _normalize_live_question_text(ask)
        for ask in list(plan.ordered_asks or [])
        if _normalize_live_question_text(ask)
    ]
    if not asks:
        resolved = _normalize_live_question_text(plan.resolved_question)
        return resolved or _normalize_live_question_text(fallback_question_text)
    if len(asks) == 1:
        return asks[0]
    return "\n".join(
        [
            asks[0],
            "Also cover:",
            *[f"- {ask}" for ask in asks[1:]],
        ]
    )


def _should_trust_live_brain_draft(plan: Optional[BrainPlan]) -> bool:
    if plan is None:
        return False
    plan_source = str(plan.plan_source or "").strip().lower()
    if plan_source not in {"llm_fast", "cached_stable"}:
        return False
    return bool(str(plan.draft_answer or "").strip())


def _build_live_brain_snapshot_hash(turn_window: list[dict[str, Any]]) -> str:
    payload = [
        {
            "speaker": str(turn.get("speaker") or "").strip().lower(),
            "text": " ".join(str(turn.get("text") or "").split()).strip(),
        }
        for turn in list(turn_window or [])
        if str(turn.get("text") or "").strip()
    ]
    return sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _build_live_brain_snapshot_text(turn_window: list[dict[str, Any]]) -> str:
    interviewer_lines: list[str] = []
    fallback_lines: list[str] = []
    for turn in list(turn_window or []):
        speaker = str(turn.get("speaker") or "").strip().lower()
        text = _normalize_live_question_text(turn.get("text") or "")
        if not text:
            continue
        fallback_lines.append(text)
        if speaker == "interviewer":
            interviewer_lines.append(text)
    lines = interviewer_lines or fallback_lines
    return "\n".join(lines[-5:])


_LIVE_TURN_OPEN_TAIL_TOKENS = {
    "and",
    "or",
    "but",
    "so",
    "like",
    "of",
    "for",
    "to",
    "in",
    "on",
    "with",
    "about",
}
_LIVE_TURN_CONTINUATION_START_TOKENS = {
    "and",
    "or",
    "but",
    "so",
    "the",
    "a",
    "an",
    "what",
    "which",
    "who",
    "why",
    "how",
    "when",
    "where",
}
_LIVE_TURN_QUESTION_TAIL_TOKENS = _LIVE_TURN_OPEN_TAIL_TOKENS | {
    "what",
    "which",
    "who",
    "why",
    "how",
    "when",
    "where",
    "absolutely",
}


def _should_merge_live_turn_entries(previous_text: str, current_text: str) -> bool:
    previous = _normalize_live_question_text(previous_text)
    current = _normalize_live_question_text(current_text)
    if not previous or not current:
        return False

    previous_tokens = re.findall(r"[a-z0-9']+", previous.lower())
    current_tokens = re.findall(r"[a-z0-9']+", current.lower())
    if not previous_tokens or not current_tokens:
        return False

    previous_ends_cleanly = previous.endswith(("?", ".", "!"))
    if not previous_ends_cleanly:
        return True
    if previous_tokens[-1] in _LIVE_TURN_OPEN_TAIL_TOKENS:
        return True
    if current_tokens[0] in _LIVE_TURN_CONTINUATION_START_TOKENS:
        return True
    if current[:1].islower():
        return True
    return False


def _looks_like_live_question_tail_fragment(text: str) -> bool:
    normalized = _normalize_live_question_text(text)
    if not normalized:
        return False
    if normalized.endswith(("?", ".", "!")):
        return False
    tokens = re.findall(r"[a-z0-9']+", normalized.lower())
    if not tokens:
        return False
    if tokens[-1] in _LIVE_TURN_QUESTION_TAIL_TOKENS:
        return True
    lowered = normalized.lower()
    return any(
        lowered.startswith(prefix) or f" {prefix}" in lowered
        for prefix in ("what", "how", "why", "when", "where", "who", "which", "tell me", "describe", "explain")
    )


def _brain_plan_to_complexity(plan: Optional[BrainPlan]) -> ComplexityClass:
    if plan is None:
        return ComplexityClass.SIMPLE
    response_shape = str(plan.response_shape or "").strip().lower()
    if response_shape == "technical_explainer":
        return ComplexityClass.DEEP_TECHNICAL
    if response_shape == "strategic_explainer":
        return ComplexityClass.STRATEGY
    if len(list(plan.ordered_asks or [])) > 1:
        return ComplexityClass.COMPOUND
    return ComplexityClass.SIMPLE


def _brain_plan_to_answer_shape(plan: Optional[BrainPlan]) -> AnswerShape:
    shape_map = {
        "direct_short": AnswerShape.DIRECT_SHORT,
        "direct_structured": AnswerShape.DIRECT_STRUCTURED,
        "technical_explainer": AnswerShape.TECHNICAL_EXPLAINER,
        "strategic_explainer": AnswerShape.STRATEGIC_EXPLAINER,
    }
    if plan is None:
        return AnswerShape.DIRECT_SHORT
    return shape_map.get(str(plan.response_shape or "").strip().lower(), AnswerShape.DIRECT_SHORT)


def _brain_plan_to_metrics_policy(plan: Optional[BrainPlan]) -> MetricsPolicy:
    if plan is None:
        return MetricsPolicy.PREFER_IF_SUPPORTED
    policy = str(plan.metrics_policy or "").strip().lower()
    if policy == "required":
        return MetricsPolicy.REQUIRED
    if policy == "avoid_unless_helpful":
        return MetricsPolicy.AVOID_UNLESS_REQUESTED
    return MetricsPolicy.PREFER_IF_SUPPORTED


def _build_compat_live_prepared_context_from_brain_plan(
    *,
    session_id: str,
    brain_snapshot: BrainSnapshot,
    brain_plan: BrainPlan,
    request_payload: dict[str, Any],
) -> LivePreparedContext:
    question_text = _build_live_question_from_brain_plan(brain_plan, brain_snapshot.snapshot_text)
    ordered_asks = list(brain_plan.ordered_asks or [])
    primary_ask = ordered_asks[0] if ordered_asks else question_text
    secondary_asks = ordered_asks[1:] if len(ordered_asks) > 1 else []
    response_shape = _brain_plan_to_answer_shape(brain_plan)
    complexity = _brain_plan_to_complexity(brain_plan)
    ask_brief = AskBrief(
        primary_ask=primary_ask,
        secondary_asks=secondary_asks,
        answer_family=AskFamily.GENERAL,
        answer_contract=AnswerContract.GENERAL_DIRECT,
        metrics_policy=_brain_plan_to_metrics_policy(brain_plan),
        opening_strategy="Follow the live brain plan and answer directly.",
        confidence=float(brain_plan.confidence or 0.0),
        why=[brain_plan.reasoning_summary] if str(brain_plan.reasoning_summary or "").strip() else [],
        shadow_mode=False,
    )
    return LivePreparedContext(
        raw_turns=copy.deepcopy(brain_snapshot.conversation_history),
        sanitized_turns=copy.deepcopy(brain_snapshot.conversation_history),
        turn_window_size=len(brain_snapshot.conversation_history),
        effective_turn_count=len(brain_snapshot.conversation_history),
        latest_turn_included=True,
        signature=brain_snapshot.snapshot_hash,
        semantic_signature=brain_snapshot.snapshot_hash,
        resolved_question=brain_plan.resolved_question or question_text,
        asks_in_order=ordered_asks,
        primary_ask=primary_ask,
        secondary_asks=secondary_asks,
        ordered_focus=ordered_asks,
        answer_focus="Answer the interviewer asks in the order decided by the live brain.",
        answer_style_guidance=f"Response shape: {brain_plan.response_shape}; directness: {brain_plan.directness}.",
        draft_answer=brain_plan.draft_answer or "",
        answer_family=AskFamily.GENERAL,
        answer_contract=AnswerContract.GENERAL_DIRECT,
        opening_strategy="Follow the live brain plan and answer directly.",
        metrics_policy=_brain_plan_to_metrics_policy(brain_plan),
        complexity_class=complexity,
        answer_shape=response_shape,
        target_length=int(brain_plan.target_length or 120),
        allow_metrics=str(brain_plan.metrics_policy or "").strip().lower() != "avoid_unless_helpful",
        allow_profile_opening=bool(brain_plan.include_profile_opening),
        require_ordered_coverage=bool(brain_plan.ordered_coverage_required),
        question_text=question_text,
        request_payload=copy.deepcopy(request_payload),
        ask_brief=ask_brief,
        confidence=float(brain_plan.confidence or 0.0),
        planner_confidence=float(brain_plan.confidence or 0.0),
        latency_ms=0,
        time_to_base_plan_ms=0,
        time_to_semantic_plan_ms=0,
        fallback_used=False,
        artifact_sanitized=True,
        sanitized_turn_count=len(brain_snapshot.conversation_history),
        plan_stage="semantic",
        planner_source="brain_v4",
        planner_provider="fast",
        planner_model="",
        reasoning_summary=brain_plan.reasoning_summary or "",
    )


async def _send_final_suggestion_with_commit(
    *,
    websocket: WebSocket,
    payload: dict[str, Any],
    tracker: Any = None,
    question_text: str = "",
    interviewer_generation: Optional[int] = None,
    session_id: str = "",
) -> None:
    await websocket.send_json(payload)
    if tracker is None:
        return

    committed_question = _normalize_live_question_text(question_text or payload.get("question", ""))
    if not committed_question:
        return

    try:
        tracker.record_answer_committed(
            committed_at=time.time(),
            question_key=committed_question,
            interviewer_generation=int(interviewer_generation or 0),
        )
    except Exception as exc:
        print(
            "[WS][COMMIT] record_answer_committed_failed "
            f"session_id={session_id} error={exc}"
        )


def _build_active_pipeline_suggest_context(
    *,
    conversation_tracker: Any,
    history_count: int,
    question_text: str,
    preserve_question_text: bool,
) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    """Resolve the live session history using the tracker-normalized active window."""
    context_bundle = build_realtime_context_bundle(conversation_tracker, limit=history_count) or {}
    active_turns = context_bundle.get("turns") or context_bundle.get("active_turns") or []
    conversation_history = [
        {
            "speaker": turn.get("speaker", "unknown"),
            "text": _strip_transcript_artifacts(turn.get("text", "")),
        }
        for turn in active_turns
        if _strip_transcript_artifacts(turn.get("text", ""))
    ]

    resolved_question = str(context_bundle.get("primary_question", "") or "")
    if resolved_question and (not preserve_question_text or not question_text):
        question_text = resolved_question

    return conversation_history, question_text, context_bundle


def _build_history_based_suggest_context(
    *,
    recent_exchanges: list[dict[str, Any]],
    question_text: str,
    preserve_question_text: bool,
) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    """Resolve a database-backed history request to its latest active interviewer turn."""
    recent_turns: list[dict[str, Any]] = []
    for index, exchange in enumerate(recent_exchanges):
        text = _strip_transcript_artifacts(exchange.get("interviewer_utterance", ""))
        if not text:
            continue

        turn: dict[str, Any] = {
            "speaker": "interviewer",
            "text": text,
        }
        timestamp = (
            exchange.get("timestamp")
            or exchange.get("created_at")
            or exchange.get("createdAt")
            or exchange.get("created")
        )
        if timestamp not in {None, ""}:
            turn["timestamp"] = timestamp
        else:
            # DB exchanges are already answer-bounded units. Missing timestamps
            # must not collapse separate exchanges into one active spoken block.
            turn["timestamp_ms"] = int(index * (DEFAULT_ACTIVE_ASK_IDLE_CLOSE_SEC + 1.0) * 1000)
        recent_turns.append(turn)

    context_bundle = resolve_realtime_context_bundle(recent_turns)
    active_turns = context_bundle.get("turns") or context_bundle.get("active_turns") or []
    historical_turns = context_bundle.get("historical_turns", [])
    conversation_history = [
        {
            "speaker": turn.get("speaker", "unknown"),
            "text": _strip_transcript_artifacts(turn.get("text", "")),
        }
        for turn in active_turns
        if _strip_transcript_artifacts(turn.get("text", ""))
    ]

    resolved_question = str(context_bundle.get("primary_question", "") or "")
    if resolved_question and (not preserve_question_text or not question_text):
        question_text = resolved_question

    context_bundle = {
        **context_bundle,
        "turns": active_turns,
        "active_turns": active_turns,
        "historical_turns": historical_turns,
        "source_turns": recent_turns,
        "source_turn_count": len(recent_turns),
        "active_turn_count": len(active_turns),
        "historical_turn_count": len(historical_turns),
    }

    return conversation_history, question_text, context_bundle


def _build_frontend_suggest_context(
    *,
    frontend_conversation_history: list[dict[str, Any]],
    question_text: str,
    preserve_question_text: bool,
) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    """Resolve the live frontend transcript history into the active interviewer block."""
    frontend_turns: list[dict[str, Any]] = []
    for turn in frontend_conversation_history:
        text = _strip_transcript_artifacts(turn.get("text", ""))
        if not text:
            continue

        normalized_turn: dict[str, Any] = {
            "speaker": turn.get("speaker", "unknown"),
            "text": text,
        }
        for key in ("start_time", "end_time", "timestamp", "timestamp_ms"):
            value = turn.get(key)
            if value not in {None, ""}:
                normalized_turn[key] = value
        frontend_turns.append(normalized_turn)

    context_bundle = resolve_realtime_context_bundle(frontend_turns)
    active_turns = context_bundle.get("turns") or context_bundle.get("active_turns") or []
    conversation_history = [
        {
            "speaker": turn.get("speaker", "unknown"),
            "text": _strip_transcript_artifacts(turn.get("text", "")),
        }
        for turn in active_turns
        if _strip_transcript_artifacts(turn.get("text", ""))
    ]

    resolved_question = str(context_bundle.get("primary_question", "") or "")
    if resolved_question and (not preserve_question_text or not question_text):
        question_text = resolved_question

    context_bundle = {
        **context_bundle,
        "turns": active_turns,
        "active_turns": active_turns,
        "historical_turns": context_bundle.get("historical_turns", []),
        "source_turns": frontend_turns,
        "source_turn_count": len(frontend_turns),
        "active_turn_count": len(active_turns),
        "historical_turn_count": len(context_bundle.get("historical_turns", [])),
    }

    return conversation_history, question_text, context_bundle


def _are_brain_plans_seed_compatible(
    seed_plan: Optional[BrainPlan],
    target_plan: Optional[BrainPlan],
) -> bool:
    if seed_plan is None or target_plan is None:
        return False
    seed_asks = _normalize_live_question_lines(_build_live_question_from_brain_plan(seed_plan))
    target_asks = _normalize_live_question_lines(_build_live_question_from_brain_plan(target_plan))
    if not seed_asks or not target_asks:
        return False
    if len(seed_asks) > len(target_asks):
        return False
    return seed_asks == target_asks[: len(seed_asks)]


def _is_cached_stable_brain_plan_compatible(
    stable_plan: Optional[BrainPlan],
    current_plan: Optional[BrainPlan],
    snapshot_text: str,
) -> bool:
    if stable_plan is None or current_plan is None:
        return False
    stable_asks = [
        _normalize_live_question_text(ask).rstrip("?.!").lower()
        for ask in list(stable_plan.ordered_asks or [])
        if _normalize_live_question_text(ask)
    ]
    if not stable_asks:
        return False
    searchable_snapshot = _normalize_live_question_text(snapshot_text).lower()
    searchable_raw = [
        _normalize_live_question_text(ask).lower()
        for ask in list(current_plan.raw_detected_asks or [])
        if _normalize_live_question_text(ask)
    ]
    lead = stable_asks[0]
    if not lead:
        return False
    if lead in searchable_snapshot:
        return True
    return any(lead in ask for ask in searchable_raw)


def _extract_live_quality_focuses(
    prepared_context: Optional[LivePreparedContext],
) -> list[str]:
    if prepared_context is None:
        return []
    canonical = _canonicalize_live_prepared_context(prepared_context) or prepared_context
    ordered_focus: list[str] = []
    for item in (
        list(canonical.asks_in_order or [])
        or list(canonical.ordered_focus or [])
        or [canonical.primary_ask, *list(canonical.secondary_asks or [])]
    ):
        normalized = _clean_live_focus_text(item)
        if normalized and normalized not in ordered_focus:
            ordered_focus.append(normalized)
    return ordered_focus


def _live_focus_token_set(text: str) -> set[str]:
    stopwords = {
        "what",
        "are",
        "you",
        "your",
        "for",
        "the",
        "and",
        "in",
        "terms",
        "of",
        "to",
        "a",
        "an",
        "is",
        "or",
        "kind",
        "things",
        "like",
        "would",
        "about",
    }
    return {
        token
        for token in re.findall(r"[a-z0-9]+", _clean_live_focus_text(text).lower())
        if len(token) > 2 and token not in stopwords
    }


def _live_focus_overlap_ratio(candidate: str, reference: str) -> float:
    candidate_tokens = _live_focus_token_set(candidate)
    reference_tokens = _live_focus_token_set(reference)
    if not candidate_tokens or not reference_tokens:
        return 0.0
    overlap = candidate_tokens & reference_tokens
    return len(overlap) / max(1, min(len(candidate_tokens), len(reference_tokens)))


def _live_focus_equivalent(candidate: str, reference: str) -> bool:
    candidate_clean = _clean_live_focus_text(candidate).lower()
    reference_clean = _clean_live_focus_text(reference).lower()
    if not candidate_clean or not reference_clean:
        return False
    if candidate_clean == reference_clean:
        return True
    if candidate_clean in reference_clean or reference_clean in candidate_clean:
        shorter = candidate_clean if len(candidate_clean) <= len(reference_clean) else reference_clean
        longer = reference_clean if shorter == candidate_clean else candidate_clean
        shorter_tokens = _live_focus_token_set(shorter)
        longer_tokens = _live_focus_token_set(longer)
        if shorter_tokens and shorter_tokens.issubset(longer_tokens):
            return len(longer_tokens - shorter_tokens) <= max(2, len(shorter_tokens) // 2)
    return _live_focus_overlap_ratio(candidate_clean, reference_clean) >= 0.72


def _classify_live_quality_delta(
    base_context: Optional[LivePreparedContext],
    current_context: Optional[LivePreparedContext],
) -> str:
    base_focuses = _extract_live_quality_focuses(base_context)
    current_focuses = _extract_live_quality_focuses(current_context)
    if not base_focuses or not current_focuses:
        return "material"

    if len(base_focuses) == len(current_focuses) and all(
        _live_focus_equivalent(base, current)
        for base, current in zip(base_focuses, current_focuses)
    ):
        return "same"

    if len(current_focuses) < len(base_focuses):
        return "material"

    current_index = 0
    extra_focuses: list[str] = []
    for base_focus in base_focuses:
        matched = False
        while current_index < len(current_focuses):
            current_focus = current_focuses[current_index]
            if _live_focus_equivalent(base_focus, current_focus):
                matched = True
                current_index += 1
                break
            extra_focuses.append(current_focus)
            current_index += 1
        if not matched:
            return "material"

    extra_focuses.extend(current_focuses[current_index:])
    if not extra_focuses:
        return "minor_refinement"
    if len(extra_focuses) == 1 and len(" ".join(extra_focuses).split()) <= 12:
        return "minor_extension"
    return "material"


def _html_fragment_to_text(fragment: str) -> str:
    if not fragment:
        return ""
    import html as html_lib

    text = fragment
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</li>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li[^>]*>", "- ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _build_company_manual_text(payload: dict[str, Any], raw_text: str = "") -> str:
    parts = [
        f"Company name: {payload.get('name', '')}",
        f"Industry: {payload.get('industry', '')}",
        f"Size: {payload.get('size', '')}",
        f"Culture: {payload.get('culture', '')}",
        f"Mission: {payload.get('mission', '')}",
        f"Values: {', '.join(_clean_string_list(payload.get('values')))}",
        f"Tech stack: {', '.join(_clean_string_list(payload.get('tech_stack') or payload.get('techStack')))}",
        f"Role title: {payload.get('role_title') or payload.get('roleTitle') or ''}",
        f"Role level: {payload.get('role_level') or payload.get('roleLevel') or ''}",
        f"Requirements: {', '.join(_clean_string_list(payload.get('role_requirements') or payload.get('roleRequirements') or payload.get('positionRequirements')))}",
        f"Responsibilities: {', '.join(_clean_string_list(payload.get('role_responsibilities') or payload.get('roleResponsibilities')))}",
        f"Interview focus: {', '.join(_clean_string_list(payload.get('interview_focus') or payload.get('interviewFocus')))}",
        f"Job description: {payload.get('job_description') or payload.get('jobDescription') or payload.get('positionDescription') or ''}",
        f"Company summary: {payload.get('company_summary') or ''}",
        f"Products/services: {', '.join(_clean_string_list(payload.get('products_services')))}",
        f"Recent focus: {', '.join(_clean_string_list(payload.get('recent_focus')))}",
        f"Research notes: {payload.get('research_notes') or ''}",
        f"Source URLs: {', '.join(_clean_string_list(payload.get('source_urls')))}",
        raw_text,
    ]
    return "\n".join([part for part in parts if part and str(part).strip()])


def _build_interviewer_manual_text(payload: dict[str, Any], raw_text: str = "") -> str:
    parts = [
        f"Name: {payload.get('name', '')}",
        f"Role title: {payload.get('role_title') or payload.get('roleTitle') or ''}",
        f"Company: {payload.get('company', '')}",
        f"Background summary: {payload.get('background_summary') or ''}",
        f"Expertise: {', '.join(_clean_string_list(payload.get('expertise')))}",
        f"Career highlights: {', '.join(_clean_string_list(payload.get('career_highlights') or payload.get('careerHighlights')))}",
        f"Likely focus areas: {', '.join(_clean_string_list(payload.get('likely_focus_areas') or payload.get('likelyFocusAreas')))}",
        f"Communication style: {payload.get('communication_style') or payload.get('communicationStyle') or ''}",
        f"Notes: {payload.get('notes') or ''}",
        f"Source URLs: {', '.join(_clean_string_list(payload.get('source_urls')))}",
        raw_text,
    ]
    return "\n".join([part for part in parts if part and str(part).strip()])


def _normalize_context_payload(kind: str, payload: dict[str, Any], source_urls: list[str], context_id: str) -> dict[str, Any]:
    normalized_urls = [url for url in _clean_string_list(source_urls) if url]
    if kind == "company":
        return {
            "kind": "company",
            "name": str(payload.get("name") or ""),
            "industry": str(payload.get("industry") or ""),
            "size": str(payload.get("size") or ""),
            "culture": str(payload.get("culture") or ""),
            "mission": str(payload.get("mission") or ""),
            "values": _clean_string_list(payload.get("values")),
            "tech_stack": _clean_string_list(payload.get("tech_stack") or payload.get("techStack")),
            "role_title": str(payload.get("role_title") or payload.get("roleTitle") or payload.get("positionTitle") or ""),
            "role_level": str(payload.get("role_level") or payload.get("roleLevel") or ""),
            "role_requirements": _clean_string_list(
                payload.get("role_requirements") or payload.get("roleRequirements") or payload.get("positionRequirements")
            ),
            "role_responsibilities": _clean_string_list(payload.get("role_responsibilities") or payload.get("roleResponsibilities")),
            "interview_type": str(payload.get("interview_type") or payload.get("interviewType") or "mixed"),
            "interview_focus": _clean_string_list(payload.get("interview_focus") or payload.get("interviewFocus")),
            "job_description": str(
                payload.get("job_description")
                or payload.get("jobDescription")
                or payload.get("positionDescription")
                or ""
            ),
            "company_summary": str(payload.get("company_summary") or ""),
            "products_services": _clean_string_list(payload.get("products_services")),
            "recent_focus": _clean_string_list(payload.get("recent_focus")),
            "source_urls": normalized_urls,
            "research_notes": str(payload.get("research_notes") or ""),
            "context_id": context_id,
            "max_words": int(payload.get("max_words") or payload.get("maxWords") or 200),
        }

    return {
        "kind": "interviewer",
        "name": str(payload.get("name") or ""),
        "role_title": str(payload.get("role_title") or payload.get("roleTitle") or ""),
        "company": str(payload.get("company") or ""),
        "background_summary": str(payload.get("background_summary") or ""),
        "expertise": _clean_string_list(payload.get("expertise")),
        "career_highlights": _clean_string_list(payload.get("career_highlights") or payload.get("careerHighlights")),
        "likely_focus_areas": _clean_string_list(payload.get("likely_focus_areas") or payload.get("likelyFocusAreas")),
        "communication_style": str(payload.get("communication_style") or payload.get("communicationStyle") or ""),
        "notes": str(payload.get("notes") or ""),
        "source_urls": normalized_urls,
        "context_id": context_id,
    }


def _merge_enriched_context(base: dict[str, Any], enrichment: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in enrichment.items():
        if key not in merged:
            merged[key] = value
            continue

        current = merged.get(key)
        if isinstance(current, str):
            if not current.strip() and isinstance(value, str) and value.strip():
                merged[key] = value
        elif isinstance(current, list):
            if not current and isinstance(value, list) and value:
                merged[key] = value
        elif current in (None, "", []):
            if value not in (None, "", []):
                merged[key] = value
    return merged


async def _fetch_url_text(url: str) -> tuple[str, list[str]]:
    warnings: list[str] = []
    if not url:
        return "", warnings

    try:
        import httpx

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
            )
        }
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, headers=headers) as client:
            response = await client.get(url)
            response.raise_for_status()
            html = response.text

        if _is_linkedin_job_url(url):
            title_match = re.search(
                r'<h1[^>]*class="[^"]*top-card-layout__title[^"]*"[^>]*>(.*?)</h1>',
                html,
                re.IGNORECASE | re.DOTALL,
            )
            company_match = re.search(
                r'<a[^>]*class="[^"]*topcard__org-name-link[^"]*"[^>]*>(.*?)</a>',
                html,
                re.IGNORECASE | re.DOTALL,
            )
            location_match = re.search(
                r'<span[^>]*class="[^"]*top-card-layout__first-subline[^"]*"[^>]*>(.*?)</span>',
                html,
                re.IGNORECASE | re.DOTALL,
            )
            description_match = re.search(
                r'<div[^>]*class="[^"]*description__text--rich[^"]*"[^>]*>(.*?)</div>',
                html,
                re.IGNORECASE | re.DOTALL,
            )

            structured_sections: list[str] = []
            title = _html_fragment_to_text(title_match.group(1)) if title_match else ""
            company = _html_fragment_to_text(company_match.group(1)) if company_match else ""
            location = _html_fragment_to_text(location_match.group(1)) if location_match else ""
            if title:
                structured_sections.append(f"Job title: {title}")
            if company:
                structured_sections.append(f"Company: {company}")
            if location:
                structured_sections.append(f"Location: {location}")

            if description_match:
                description_text = _html_fragment_to_text(description_match.group(1))
                if description_text:
                    structured_sections.append(f"Description:\n{description_text}")

            criteria_matches = re.findall(
                r'<span[^>]*class="[^"]*description__job-criteria-text[^"]*"[^>]*>(.*?)</span>',
                html,
                re.IGNORECASE | re.DOTALL,
            )
            criteria_text = [
                _html_fragment_to_text(match)
                for match in criteria_matches
                if _html_fragment_to_text(match)
            ]
            if criteria_text:
                structured_sections.append("Job criteria:\n" + "\n".join(f"- {item}" for item in criteria_text))

            description_block = "\n\n".join(structured_sections).strip()
            if description_block:
                return description_block, warnings

        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        title = title_match.group(1).strip() if title_match else ""
        meta_description = ""
        meta_match = re.search(
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
            html,
            re.IGNORECASE | re.DOTALL,
        )
        if meta_match:
            meta_description = meta_match.group(1).strip()

        text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()

        chunks = [part for part in [title, meta_description, text[:8000]] if part]
        if not chunks:
            warnings.append(f"No readable text extracted from {url}")
        return "\n".join(chunks), warnings
    except Exception as exc:
        warnings.append(f"Failed to fetch {url}: {exc}")
        return "", warnings


async def _build_research_source_text(urls: list[str], manual_text: str) -> tuple[str, list[str]]:
    all_warnings: list[str] = []
    sections: list[str] = []
    for url in _clean_string_list(urls):
        text, warnings = await _fetch_url_text(url)
        all_warnings.extend(warnings)
        if text:
            sections.append(f"[SOURCE: {url}]\n{text}")
    if manual_text.strip():
        sections.append(f"[MANUAL NOTES]\n{manual_text.strip()}")
    return "\n\n".join(sections), all_warnings


def _is_linkedin_job_url(url: str) -> bool:
    return "linkedin.com/jobs/view/" in (url or "").lower()


def _extract_linkedin_job_id(url: str) -> str:
    match = re.search(r"/jobs/view/(\d+)", url or "")
    return match.group(1) if match else ""


def _infer_role_level_from_text(text: str) -> str:
    normalized = (text or "").lower()
    if any(token in normalized for token in [" c-level", "chief", " cto", " ceo", " cfo", " cio"]):
        return "c-level"
    if any(token in normalized for token in [" vice president", " vp ", " vp-", " vp/", "vp "]):
        return "vp"
    if "director" in normalized:
        return "director"
    if "principal" in normalized:
        return "principal"
    if "staff" in normalized:
        return "staff"
    if "lead" in normalized:
        return "lead"
    if "senior" in normalized or " sr " in normalized or normalized.startswith("sr "):
        return "senior"
    if "mid" in normalized or "intermediate" in normalized:
        return "mid"
    if "junior" in normalized or "entry" in normalized or "graduate" in normalized:
        return "junior"
    return ""


def _infer_interview_type_from_text(text: str) -> str:
    normalized = (text or "").lower()
    technical_markers = [
        "engineer",
        "engineering",
        "technical",
        "data",
        "software",
        "backend",
        "frontend",
        "system design",
        "architecture",
    ]
    consulting_markers = ["consulting", "consultant", "case study", "stakeholder", "client"]
    behavioral_markers = ["people", "leadership", "culture", "behavioral", "communication"]
    if any(marker in normalized for marker in technical_markers):
        return "technical"
    if any(marker in normalized for marker in consulting_markers):
        return "case_study"
    if any(marker in normalized for marker in behavioral_markers):
        return "behavioral"
    return "mixed"


def _split_job_snippets(text: str, limit: int = 4) -> list[str]:
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+|[\n•;]+", text)
    snippets: list[str] = []
    for part in parts:
        candidate = _compact_text(part, 220)
        if len(candidate) < 20:
            continue
        snippets.append(candidate)
        if len(snippets) >= limit:
            break
    return snippets


def _build_company_job_focus(role_title: str, combined_text: str, responsibilities_text: str, requirements_text: str) -> list[str]:
    text = " ".join([role_title, combined_text, responsibilities_text, requirements_text]).lower()
    focus: list[str] = []

    def add(item: str) -> None:
        if item and item not in focus:
            focus.append(item)

    if any(token in text for token in ["lead", "leadership", "mentor", "mentoring", "team lead"]):
        add("technical leadership and mentoring")
    if any(token in text for token in ["consult", "client", "customer", "stakeholder"]):
        add("client-facing consulting and stakeholder communication")
    if any(token in text for token in ["data engineer", "data architecture", "data architect", "data modeling", "etl", "integration"]):
        add("data engineering architecture and delivery")
    if any(token in text for token in ["data modeling", "etl", "data integration", "data warehousing", "pipeline", "pipelines"]):
        add("data pipelines, ETL, and integration")
    if any(token in text for token in ["cloud", "aws", "azure", "gcp", "platform"]):
        add("cloud data platforms and tooling")
    if any(token in text for token in ["project", "planning", "timeline", "delivery", "execution"]):
        add("project delivery and execution")
    if any(token in text for token in ["collaborate", "cross-functional", "business stakeholder", "business stakeholders"]):
        add("cross-functional collaboration")
    if any(token in text for token in ["standards", "quality", "audit", "controls", "governance", "data integrity"]):
        add("data quality, governance, and standards")

    return focus[:6]


def _extract_job_source_hints(urls: list[str], source_text: str, manual_text: str = "") -> dict[str, Any]:
    job_url = next((url for url in _clean_string_list(urls) if _is_linkedin_job_url(url)), "")
    if not job_url:
        return {}

    combined_text = _compact_text("\n".join([source_text, manual_text]), limit=8000)
    combined_lower = combined_text.lower()
    job_id = _extract_linkedin_job_id(job_url)

    company_name = ""
    role_title = ""

    structured_title_match = re.search(
        r"(?:^|\s)Job title:\s*(.+?)(?:\s+Company:|\s+Location:|\s+Description:|\s+Job criteria:|$)",
        combined_text,
        re.IGNORECASE,
    )
    if structured_title_match:
        role_title = structured_title_match.group(1).strip()

    structured_company_match = re.search(
        r"(?:^|\s)Company:\s*(.+?)(?:\s+Location:|\s+Description:|\s+Job criteria:|$)",
        combined_text,
        re.IGNORECASE,
    )
    if structured_company_match:
        company_name = structured_company_match.group(1).strip()

    patterns = [
        r"(?P<company>[^|]{2,120}?) hiring (?P<role>[^|]{2,160}?)(?: in | at | for )",
        r"Join to apply for the (?P<role>.+?) role at (?P<company>.+?)(?:\s|$)",
        r"(?P<role>[^|]{2,160}?) role at (?P<company>[^|]{2,120}?)(?:\s|$)",
        r"(?P<company>[^|]{2,120}?) hiring (?P<role>[^|]{2,160}?)(?:\||$)",
    ]
    for pattern in patterns:
        if role_title and company_name:
            break
        match = re.search(pattern, combined_text, re.IGNORECASE)
        if not match:
            continue
        company_name = (match.groupdict().get("company") or company_name).strip(" -|")
        role_title = (match.groupdict().get("role") or role_title).strip(" -|")
        if company_name and role_title:
            break

    if not role_title:
        fallback_match = re.search(
            r"(?:tech lead|software engineer|data engineer|product manager|solution architect|consultant|manager|analyst|developer|designer|director|principal|staff engineer|site reliability engineer)",
            combined_lower,
            re.IGNORECASE,
        )
        if fallback_match:
            role_title = fallback_match.group(0).strip()

    requirements_text = ""
    responsibilities_text = ""
    requirement_markers = [
        "What We're Looking For:",
        "What We’re Looking For:",
        "Requirements:",
        "Qualifications:",
        "Must Have:",
        "You Will:",
        "Responsibilities:",
        "What You'll Do:",
        "What You’ll Do:",
    ]
    for marker in requirement_markers:
        idx = combined_text.lower().find(marker.lower())
        if idx == -1:
            continue
        tail = combined_text[idx + len(marker):]
        requirement_candidates = _split_job_snippets(tail, limit=4)
        if "looking for" in marker.lower() or "require" in marker.lower() or "qualif" in marker.lower() or "must have" in marker.lower():
            requirements_text = "; ".join(requirement_candidates[:3])
        else:
            responsibilities_text = "; ".join(requirement_candidates[:4])
        if requirements_text and responsibilities_text:
            break

    if not responsibilities_text:
        body_text = combined_text
        if role_title:
            role_idx = body_text.lower().find(role_title.lower())
            if role_idx != -1:
                body_text = body_text[role_idx + len(role_title):]
        earliest_marker_idx = None
        for marker in requirement_markers:
            idx = body_text.lower().find(marker.lower())
            if idx == -1:
                continue
            if earliest_marker_idx is None or idx < earliest_marker_idx:
                earliest_marker_idx = idx
        body_window = body_text[:earliest_marker_idx] if earliest_marker_idx is not None else body_text[:1400]
        body_snippets = _split_job_snippets(body_window, limit=5)
        if body_snippets:
            responsibilities_text = "; ".join(body_snippets[:4])

    if not role_title:
        title_candidates = [
            r"\bTechnical Lead\b",
            r"\bTech Lead\b",
            r"\bData Engineer\b",
            r"\bData Architect\b",
            r"\bEngineering Manager\b",
            r"\bLead\b",
            r"\bPrincipal\b",
            r"\bStaff Engineer\b",
            r"\bConsultant\b",
        ]
        for candidate in title_candidates:
            match = re.search(candidate, combined_text, re.IGNORECASE)
            if match:
                role_title = match.group(0).strip()
                break

    job_description = ""
    description_markers = [
        "About the role:",
        "Job description:",
        "Role description:",
        "About this role:",
        "This role:",
    ]
    for marker in description_markers:
        idx = combined_text.lower().find(marker.lower())
        if idx == -1:
            continue
        snippet = combined_text[idx + len(marker):]
        job_description = _compact_text(snippet, 420)
        if job_description:
            break

    if not job_description:
        job_description = _compact_text(combined_text, 320)

    interview_focus = _build_company_job_focus(role_title, combined_text, responsibilities_text, requirements_text)
    if not interview_focus:
        interview_focus = _clean_string_list(
            [
                "technical problem solving" if "technical" in combined_lower or "engineer" in combined_lower else "",
                "consulting experience" if "consult" in combined_lower else "",
                "role-specific expertise" if role_title else "",
                "stakeholder communication" if any(token in combined_lower for token in ["client", "lead", "director"]) else "",
            ]
        )

    role_level = _infer_role_level_from_text(role_title or combined_text)
    interview_type = _infer_interview_type_from_text(combined_text)

    return {
        "name": company_name,
        "role_title": role_title,
        "role_level": role_level,
        "role_requirements": _clean_string_list([requirements_text]) if requirements_text else [],
        "role_responsibilities": _clean_string_list([responsibilities_text]) if responsibilities_text else [],
        "interview_type": interview_type,
        "interview_focus": interview_focus,
        "job_description": job_description,
        "company_summary": _compact_text(combined_text, 280) if combined_text else "",
        "products_services": _clean_string_list(
            ["job posting" if job_id else "", "role context" if role_title else ""]
        ),
        "recent_focus": _clean_string_list(
            [
                "Role sourced from LinkedIn job posting" if job_id else "",
                f"LinkedIn job ID: {job_id}" if job_id else "",
            ]
        ),
        "source_urls": _clean_string_list([job_url]),
        "research_notes": _compact_text(combined_text, 600) if combined_text else "",
        "context_id": "",
    }


async def _analyze_research_context(
    kind: str,
    urls: list[str],
    manual_text: str,
    language: str = "en",
) -> tuple[dict[str, Any], str, list[str], str]:
    source_text, warnings = await _build_research_source_text(urls, manual_text)
    source_text = _compact_text(source_text, limit=8000)

    job_hints: dict[str, Any] = {}
    if kind == "company":
        job_hints = _extract_job_source_hints(urls, source_text, manual_text)
        if job_hints:
            job_signal_lines = [
                "[JOB POSTING PRIORITY SOURCE]",
                f"Job posting URL: {job_hints.get('source_urls', [''])[0] if job_hints.get('source_urls') else ''}",
                f"Inferred company hint: {job_hints.get('name', '')}",
                f"Inferred role hint: {job_hints.get('role_title', '')}",
                f"Role level hint: {job_hints.get('role_level', '')}",
                f"Requirements hint: {', '.join(job_hints.get('role_requirements', []) or [])}",
                f"Responsibilities hint: {', '.join(job_hints.get('role_responsibilities', []) or [])}",
                f"Interview focus hint: {', '.join(job_hints.get('interview_focus', []) or [])}",
                "Treat this source as authoritative for role_title, role_requirements, role_responsibilities, interview_focus, interview_type, and job_description.",
            ]
            source_text = "\n\n".join([part for part in [source_text, "\n".join(job_signal_lines)] if part]).strip()

    if not source_text:
        source_text = _compact_text(manual_text, limit=4000)

    if kind == "company":
        fallback = _normalize_context_payload(
            "company",
            {
                "name": "",
                "industry": "",
                "size": "",
                "culture": "",
                "mission": "",
                "values": [],
                "tech_stack": [],
                "role_title": "",
                "role_level": "",
                "role_requirements": [],
                "role_responsibilities": [],
                "interview_type": "mixed",
                "interview_focus": [],
                "job_description": "",
                "company_summary": _compact_text(manual_text, 400) or _compact_text(source_text, 400),
                "products_services": [],
                "recent_focus": [],
                "source_urls": urls,
                "research_notes": manual_text,
                "context_id": "",
            },
            urls,
            "",
        )
        output_schema = """
{
  "name": "Company name",
  "industry": "Industry",
  "size": "startup|small|medium|large|enterprise or empty",
  "culture": "Culture summary",
  "mission": "Mission statement",
  "values": ["value1", "value2"],
  "tech_stack": ["tech1", "tech2"],
  "role_title": "Target role title",
  "role_level": "junior|mid|senior|lead|staff|principal|director|vp|c-level",
  "role_requirements": ["requirement1", "requirement2"],
  "role_responsibilities": ["responsibility1", "responsibility2"],
  "interview_type": "behavioral|technical|system_design|case_study|mixed",
  "interview_focus": ["focus1", "focus2"],
  "job_description": "Concise job description",
  "company_summary": "Concise summary of company",
  "products_services": ["product1", "service2"],
  "recent_focus": ["recent focus1", "recent focus2"],
  "source_urls": ["https://..."],
  "research_notes": "raw notes"
}
"""
    else:
        fallback = _normalize_context_payload(
            "interviewer",
            {
                "name": "",
                "role_title": "",
                "company": "",
                "background_summary": _compact_text(manual_text, 400) or _compact_text(source_text, 400),
                "expertise": [],
                "career_highlights": [],
                "likely_focus_areas": [],
                "communication_style": "",
                "notes": manual_text,
                "source_urls": urls,
                "context_id": "",
            },
            urls,
            "",
        )
        output_schema = """
{
  "name": "Interviewer name",
  "role_title": "Role title",
  "company": "Company",
  "background_summary": "Summary of background",
  "expertise": ["expertise1", "expertise2"],
  "career_highlights": ["highlight1", "highlight2"],
  "likely_focus_areas": ["focus1", "focus2"],
  "communication_style": "Concise or conversational style summary",
  "notes": "Any extra notes",
  "source_urls": ["https://..."]
}
"""

    try:
        from adapters.llm_adapter import get_llm_adapter

        adapter = get_llm_adapter()
        if adapter is None:
            return fallback, source_text, warnings, "demo"

        system_prompt = (
            "You are a structured research assistant for interview coaching.\n"
            "Extract only clearly supported facts from the provided source material.\n"
            "Return ONLY valid JSON matching the requested schema.\n"
            f"Language preference: {language}.\n"
            f"Schema:\n{output_schema}"
        )
        user_prompt = (
            f"Research context kind: {kind}\n\n"
            f"Source material:\n{source_text[:12000]}"
        )
        response = await adapter.generate(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            {"temperature": 0.1, "max_tokens": 1800},
        )

        json_text = response.strip()
        if json_text.startswith("```"):
            lines = json_text.split("\n")
            json_text = "\n".join(lines[1:-1])

        data = json.loads(json_text)
        if not isinstance(data, dict):
            raise ValueError("LLM returned non-object JSON")

        if kind == "company":
            payload = _normalize_context_payload("company", data, _clean_string_list(data.get("source_urls") or urls), "")
            payload = _merge_enriched_context(payload, job_hints)
            if job_hints.get("role_title"):
                payload["role_title"] = job_hints["role_title"]
                payload["roleTitle"] = job_hints["role_title"]
                payload["positionTitle"] = job_hints["role_title"]
            if job_hints.get("name"):
                payload["name"] = job_hints["name"]
                payload["companyName"] = job_hints["name"]
        else:
            payload = _normalize_context_payload("interviewer", data, _clean_string_list(data.get("source_urls") or urls), "")

        return payload, source_text, warnings, "real"
    except Exception as exc:
        warnings.append(str(exc))
        if kind == "company" and job_hints:
            fallback = _merge_enriched_context(fallback, job_hints)
        return fallback, source_text, warnings, "fallback"


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
    """Check if API keys or LLM provider is configured for real LLM/embedding calls."""
    # Runtime config is the source of truth when it is enabled.
    try:
        runtime_config = get_runtime_config()
        if runtime_config and runtime_config.llm:
            llm_config = runtime_config.llm
            if llm_config.enabled:
                provider = llm_config.provider
                if provider == "ollama":
                    return True
                if provider in ("anthropic", "openai"):
                    return bool(llm_config.api_key)
                return False
    except Exception:
        pass

    # Fall back to environment variables only when runtime config is absent/disabled.
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


def _normalize_live_turn_window(turns: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    """Treat the latest completed live-caption turns as interviewer turns."""
    normalized: list[dict[str, Any]] = []
    for turn in list(turns or []):
        text = _sanitize_live_turn_text(turn.get("text") or turn.get("content") or "")
        if not text:
            continue
        if len(re.findall(r"[a-z0-9']+", text.lower())) < 3 and text.lower().rstrip(".!?") in {
            "and then",
            "and then all",
            "and then, all",
            "yeah",
            "okay",
            "ok",
        }:
            continue
        if normalized and normalized[-1]["text"].lower() == text.lower():
            normalized[-1]["timestamp"] = turn.get("timestamp") or normalized[-1].get("timestamp")
            timestamp_ms = turn.get("timestamp_ms")
            if timestamp_ms is not None:
                normalized[-1]["timestamp_ms"] = timestamp_ms
            normalized[-1]["start_time"] = normalized[-1].get("start_time") or turn.get("start_time")
            normalized[-1]["end_time"] = turn.get("end_time") or normalized[-1].get("end_time")
            continue
        normalized.append(
            {
                "speaker": "interviewer",
                "text": text,
                "timestamp": turn.get("timestamp"),
                "timestamp_ms": turn.get("timestamp_ms"),
                "start_time": turn.get("start_time"),
                "end_time": turn.get("end_time"),
            }
        )
    return normalized[-limit:]


def _build_live_question_from_summary(summary: Optional[LiveAskSummary], fallback_question: str) -> str:
    if summary is None:
        return fallback_question

    ordered_focus: list[str] = []
    for item in summary.ordered_focus or [summary.primary_ask, *summary.secondary_asks]:
        normalized = " ".join(str(item or "").split()).strip()
        if normalized and normalized not in ordered_focus:
            ordered_focus.append(normalized)

    if not ordered_focus:
        return fallback_question
    if len(ordered_focus) == 1:
        return ordered_focus[0]

    lines = [ordered_focus[0], "Also cover:"]
    lines.extend(f"- {focus}" for focus in ordered_focus[1:])
    return "\n".join(lines)


def _build_live_question_from_prepared_context(
    prepared_context: Optional[LivePreparedContext],
    fallback_question: str,
) -> str:
    if prepared_context is None:
        return _normalize_live_question_text(fallback_question)

    prepared_context = _canonicalize_live_prepared_context(prepared_context) or prepared_context
    ordered_focus: list[str] = []
    for item in (
        list(prepared_context.asks_in_order or [])
        or list(prepared_context.ordered_focus or [])
        or [prepared_context.primary_ask, *list(prepared_context.secondary_asks or [])]
    ):
        normalized = " ".join(str(item or "").split()).strip()
        if normalized and normalized not in ordered_focus:
            ordered_focus.append(normalized)

    structured_question = _build_live_question_from_focus(ordered_focus, "")
    if structured_question:
        return structured_question

    question_text = _normalize_live_question_text(
        prepared_context.question_text
        or prepared_context.resolved_question
        or prepared_context.primary_ask
    )
    fallback_question = _normalize_live_question_text(fallback_question)
    return question_text or fallback_question


def _is_live_prepared_context_usable(
    prepared_context: Optional[LivePreparedContext],
    *,
    confidence_threshold: float,
) -> bool:
    if prepared_context is None:
        return False
    if not prepared_context.question_text or not prepared_context.primary_ask:
        return False
    if not prepared_context.latest_turn_included:
        return False
    if not prepared_context.ordered_focus:
        return False
    if prepared_context.confidence >= confidence_threshold:
        return True
    return prepared_context.effective_turn_count <= 2 or prepared_context.complexity_class == ComplexityClass.SIMPLE


def _serialize_live_prepared_context(
    prepared_context: Optional[LivePreparedContext],
) -> dict[str, Any]:
    if prepared_context is None:
        return {}
    return prepared_context.model_dump(mode="json", exclude_none=True)


def _build_live_suggest_request(
    *,
    session_id: str,
    interview_config: dict[str, Any],
    question_text: str,
    conversation_history: list[dict[str, Any]],
    mode: str,
    live_prepared_context: Optional[LivePreparedContext] = None,
) -> SuggestRequest:
    candidate_profile = interview_config.get("candidate_profile") or interview_config.get("candidate") or {}
    company_info = interview_config.get("company_info") or interview_config.get("company") or {}
    interviewer_profile = interview_config.get("interviewer_profile") or interview_config.get("interviewer") or {}

    return SuggestRequest(
        question=question_text,
        session_id=session_id,
        candidate_profile=candidate_profile,
        company_info=company_info,
        target_company_info=(interview_config.get("target_context") or interview_config.get("target") or {}).get("company")
        if isinstance(interview_config.get("target_context") or interview_config.get("target") or {}, dict)
        else None,
        target_role_info=(interview_config.get("target_context") or interview_config.get("target") or {}).get("role")
        if isinstance(interview_config.get("target_context") or interview_config.get("target") or {}, dict)
        else None,
        interviewer_profile=interviewer_profile,
        target_context=interview_config.get("target_context") or interview_config.get("target"),
        style_id=interview_config.get("style_id") or interview_config.get("response_style") or "professional",
        language=interview_config.get("language_preference") or "en",
        mode=mode,
        history_count=5,
        profile_id=interview_config.get("profile_id"),
        company_context_id=interview_config.get("company_context_id"),
        interviewer_context_id=interview_config.get("interviewer_context_id"),
        max_words=interview_config.get("max_words") or 200,
        interview_type=interview_config.get("interview_type"),
        conversation_history=conversation_history,
        preserve_question_text=True,
        _live_prepared_context=_serialize_live_prepared_context(live_prepared_context),
        _delivery_mode_override="live_manual",
    )


def _build_live_fast_question_analysis(
    *,
    question_text: str,
    ask_brief: AskBrief,
    live_prepared_context: Optional[LivePreparedContext] = None,
    conversation_history: Optional[list[dict[str, Any]]] = None,
    delivery_mode: str = "live_manual",
):
    from contracts.models import Priority, QuestionAnalysis, QuestionType, SubQuestion
    from pipeline.steps.ask_normalizer import apply_ask_brief_policy

    analysis = QuestionAnalysis(confidence=max(0.75, ask_brief.confidence))
    policy_threshold = 0.45 if delivery_mode == "live_manual" else 0.72
    analysis = apply_ask_brief_policy(
        analysis,
        ask_brief,
        delivery_mode=delivery_mode,
        confidence_threshold=policy_threshold,
    )
    ordered_focus = (
        [ask for ask in (live_prepared_context.asks_in_order or []) if ask]
        if live_prepared_context is not None and live_prepared_context.asks_in_order
        else []
    )
    if not ordered_focus:
        primary_ask, secondary_asks, ordered_focus = _canonicalize_live_asks(
            ask_brief,
            conversation_history or [],
        )
        if primary_ask:
            ask_brief = ask_brief.model_copy(
                update={
                    "primary_ask": primary_ask,
                    "secondary_asks": secondary_asks,
                    "fallback_used": False,
                }
            )
    analysis.key_topics = ordered_focus[:4]
    analysis.underlying_intent = ordered_focus[:4]
    analysis.is_compound = len(ordered_focus) > 1
    if ordered_focus:
        analysis.sub_questions = [
            SubQuestion(
                text=ask,
                type=QuestionType.COMPOUND if len(ordered_focus) > 1 else QuestionType.CASUAL,
                priority=Priority.MUST_ANSWER if idx == 0 else Priority.SHOULD_ANSWER,
                weight=max(0.2, 1.0 - (idx * 0.15)),
            )
            for idx, ask in enumerate(ordered_focus)
        ]
    if ordered_focus:
        analysis.response_structure = [
            f"Answer this part in order: {ask}" for ask in ordered_focus
        ]
    elif question_text and not analysis.response_structure:
        analysis.response_structure = ["Answer the main ask directly"]
    return analysis


def _live_focus_terms(ordered_focus: list[str]) -> set[str]:
    stopwords = {
        "the", "a", "an", "and", "or", "to", "of", "in", "for", "from", "your",
        "you", "about", "what", "how", "why", "also", "then", "with", "have",
        "had", "were", "that", "this", "those", "them", "they", "their", "just",
        "into", "where", "when", "which", "tell", "me", "experience", "experiences",
    }
    tokens: set[str] = set()
    for ask in ordered_focus:
        for token in re.findall(r"[a-z0-9]+", _clean_live_focus_text(ask).lower()):
            if len(token) > 2 and token not in stopwords:
                tokens.add(token)
    return tokens


def _score_live_evidence_text(text: str, focus_terms: set[str]) -> float:
    if not text or not focus_terms:
        return 0.0
    evidence_terms = {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 2
    }
    if not evidence_terms:
        return 0.0
    overlap = focus_terms & evidence_terms
    return len(overlap) / max(1, min(len(focus_terms), len(evidence_terms)))


def _build_live_fast_evidence(
    *,
    candidate_context: dict[str, Any],
    company_context: dict[str, Any],
    interviewer_context: dict[str, Any],
    ordered_focus: Optional[list[str]] = None,
) -> list[Any]:
    from contracts.models import EvidenceChunk

    evidence: list[EvidenceChunk] = []
    focus_terms = _live_focus_terms(ordered_focus or [])

    candidate_summary = str(candidate_context.get("summary") or "").strip()
    current_role = str(candidate_context.get("current_role") or "").strip()
    current_company = str(
        candidate_context.get("company")
        or candidate_context.get("current_company")
        or candidate_context.get("currentCompany")
        or ""
    ).strip()
    years_experience = candidate_context.get("years_experience")
    achievements = candidate_context.get("achievements") or []
    skills = candidate_context.get("skills") or []
    candidate_cv_text = str(candidate_context.get("cv_text") or candidate_context.get("cvText") or "").strip()

    company_description = _compact_text(str(company_context.get("companyDescription") or "").strip(), limit=700)
    company_culture = _compact_text(str(company_context.get("companyCulture") or "").strip(), limit=300)
    role_requirements = company_context.get("roleRequirements") or []

    interviewer_focus = interviewer_context.get("likelyFocusAreas") or []

    if candidate_summary:
        evidence.append(
            EvidenceChunk(
                text=candidate_summary,
                source="cv",
                relevance_score=0.72,
                metadata={"mode": "live_fast", "kind": "candidate_summary"},
            )
        )

    if current_role or current_company or years_experience:
        role_parts = [
            part
            for part in [
                current_role,
                f"Current company: {current_company}" if current_company else "",
                f"{years_experience} years experience" if years_experience else "",
            ]
            if part
        ]
        if role_parts:
            evidence.append(
                EvidenceChunk(
                    text=" | ".join(role_parts),
                    source="cv",
                    relevance_score=0.66,
                    metadata={"mode": "live_fast", "kind": "role_context"},
                )
            )

    for achievement in achievements[:4]:
        text = " ".join(str(achievement or "").split()).strip()
        if not text:
            continue
        evidence.append(
            EvidenceChunk(
                text=text,
                source="achievement",
                relevance_score=0.84,
                metadata={"mode": "live_fast", "kind": "candidate_achievement"},
            )
        )

    if skills:
        evidence.append(
            EvidenceChunk(
                text="Skills: " + ", ".join(str(skill).strip() for skill in skills[:8] if str(skill).strip()),
                source="cv",
                relevance_score=0.7,
                metadata={"mode": "live_fast", "kind": "skills"},
                )
            )

    if len(evidence) < 2 and candidate_cv_text:
        evidence.append(
            EvidenceChunk(
                text=_compact_text(candidate_cv_text, limit=1200),
                source="cv",
                relevance_score=0.62,
                metadata={"mode": "live_fast", "kind": "cv_compact_fallback"},
            )
        )

    if company_description:
        evidence.append(
            EvidenceChunk(
                text=company_description,
                source="company",
                relevance_score=0.72,
                metadata={"mode": "live_fast", "kind": "company_description"},
            )
        )

    if company_culture:
        evidence.append(
            EvidenceChunk(
                text=company_culture,
                source="company",
                relevance_score=0.68,
                metadata={"mode": "live_fast", "kind": "company_culture"},
            )
        )

    if role_requirements:
        requirement_lines = [str(item).strip() for item in role_requirements[:4] if str(item).strip()]
        if requirement_lines:
            evidence.append(
                EvidenceChunk(
                    text="Role requirements: " + "; ".join(requirement_lines),
                    source="company",
                    relevance_score=0.73,
                    metadata={"mode": "live_fast", "kind": "role_requirements"},
                )
            )

    if interviewer_focus:
        focus_lines = [str(item).strip() for item in interviewer_focus[:4] if str(item).strip()]
        if focus_lines:
            evidence.append(
                EvidenceChunk(
                    text="Interviewer focus areas: " + "; ".join(focus_lines),
                    source="company",
                    relevance_score=0.6,
                    metadata={"mode": "live_fast", "kind": "interviewer_focus"},
                )
            )

    if focus_terms:
        rescored: list[EvidenceChunk] = []
        for chunk in evidence:
            overlap_score = _score_live_evidence_text(chunk.text, focus_terms)
            adjusted_score = chunk.relevance_score + (overlap_score * 0.28)
            kind = (chunk.metadata or {}).get("kind")
            if kind in {"candidate_summary", "role_context"} and overlap_score < 0.08:
                adjusted_score -= 0.22 if len(focus_terms) >= 4 else 0.12
            if kind == "candidate_achievement" and overlap_score > 0.0:
                adjusted_score += 0.12
            rescored.append(chunk.model_copy(update={"relevance_score": adjusted_score}))
        evidence = sorted(
            rescored,
            key=lambda item: item.relevance_score,
            reverse=True,
        )

    return evidence[:8]


def _build_live_preview_response_text(question_analysis: Any, bullets: list[str]) -> str:
    """Turn preview bullets into a short, speakable live answer."""
    cleaned = [bullet.replace("•", "").strip() for bullet in bullets if bullet and bullet.strip()]
    if not cleaned:
        return ""

    response_mode = getattr(getattr(question_analysis, "response_mode", None), "value", "")
    if response_mode == "hybrid_dual":
        lead = cleaned[0]
        rest = cleaned[1:3]
        body = " ".join(rest)
        if body:
            return f"Technical answer: {lead}.\n\nHow to say it in the interview: {body}."
        return f"Technical answer: {lead}."

    sentences: list[str] = []
    for bullet in cleaned[:3]:
        sentence = bullet
        if sentence and sentence[-1] not in ".!?":
            sentence += "."
        sentences.append(sentence)
    return " ".join(sentences)


def _draft_answer_to_bullets(text: str, limit: int = 3) -> list[str]:
    cleaned_text = " ".join(str(text or "").split()).strip()
    if not cleaned_text:
        return []

    line_bullets: list[str] = []
    for line in str(text or "").splitlines():
        normalized = line.strip().lstrip("-•").strip()
        if normalized:
            line_bullets.append(normalized)

    if len(line_bullets) <= 1:
        bullets = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", cleaned_text)
            if sentence.strip()
        ]
    else:
        bullets = line_bullets

    compacted: list[str] = []
    for bullet in bullets:
        normalized = " ".join(bullet.split()).strip()
        normalized = normalized.rstrip(".!?")
        if normalized:
            compacted.append(normalized)
        if len(compacted) >= limit:
            break
    return compacted


def _build_live_cached_draft_response(
    *,
    interview_config: dict[str, Any],
    question_text: str,
    live_prepared_context: LivePreparedContext,
    mode: str,
    path_used: str = "brain_cached",
) -> dict[str, Any]:
    draft_answer = " ".join(str(live_prepared_context.draft_answer or "").split()).strip()
    bullets = _draft_answer_to_bullets(draft_answer)
    ask_brief = live_prepared_context.ask_brief
    style = (
        interview_config.get("style_id")
        or interview_config.get("response_style")
        or "professional"
    )
    language = str(interview_config.get("language_preference") or "en").strip().lower() or "en"
    confidence = max(0.72, float(live_prepared_context.confidence or 0.0), float(live_prepared_context.planner_confidence or 0.0))

    return {
        "success": True,
        "mode": mode,
        "full_response": draft_answer,
        "bullets": bullets,
        "key_metrics": [],
        "confidence": confidence,
        "latency_ms": 1,
        "quality": {
            "passed": True,
            "score": confidence,
            "issues": [],
        },
        "language": {"detected": language},
        "suggestion": {
            "style": style,
            "keyMetrics": [],
        },
        "debug": {
            "question": question_text,
            "normalized_family": (
                ask_brief.answer_family.value
                if ask_brief is not None
                else live_prepared_context.answer_family.value
            ),
            "normalized_primary_ask": live_prepared_context.primary_ask,
            "normalized_secondary_asks": live_prepared_context.secondary_asks,
            "normalized_answer_contract": (
                ask_brief.answer_contract.value
                if ask_brief is not None
                else live_prepared_context.answer_contract.value
            ),
            "normalized_metrics_policy": (
                ask_brief.metrics_policy.value
                if ask_brief is not None
                else live_prepared_context.metrics_policy.value
            ),
            "normalizer_confidence": (
                ask_brief.confidence
                if ask_brief is not None
                else live_prepared_context.confidence
            ),
            "normalizer_latency_ms": live_prepared_context.latency_ms,
            "fallback_used": False,
            "live_fast_path_used": True,
            "live_brain_cached_draft_used": True,
            "path_used": path_used,
            "planner_source": live_prepared_context.planner_source,
            "planner_provider": live_prepared_context.planner_provider,
            "planner_model": live_prepared_context.planner_model,
            "planner_reasoning_summary": live_prepared_context.reasoning_summary,
        },
    }


def _is_live_fast_emergency_draft_usable(
    live_prepared_context: Optional[LivePreparedContext],
) -> bool:
    if live_prepared_context is None:
        return False
    draft_answer = " ".join(str(live_prepared_context.draft_answer or "").split()).strip()
    if len(draft_answer.split()) < 12:
        return False
    asks = [ask for ask in list(live_prepared_context.asks_in_order or []) if str(ask or "").strip()]
    if len(asks) <= 1:
        return True
    bullets = _draft_answer_to_bullets(draft_answer, limit=max(2, min(len(asks), 4)))
    return len(bullets) >= min(2, len(asks))


async def _suggest_live_prepared_response(
    *,
    websocket: WebSocket,
    session_id: str,
    interview_config: dict[str, Any],
    question_text: str,
    conversation_history: list[dict[str, Any]],
    live_prepared_context: LivePreparedContext,
    working_draft: str = "",
) -> dict[str, Any]:
    """
    Authoritative live quality writer.

    The live brain may prepare snapshots and drafts in parallel, but the final
    strong answer should always come from this writer path or from an exact
    prewarmed result produced by this same path.
    """
    from pipeline.steps.response_composer import ResponseComposer, ComposerMode

    runtime = await _build_live_prepared_runtime(
        interview_config=interview_config,
        question_text=question_text,
        conversation_history=conversation_history,
        live_prepared_context=live_prepared_context,
        working_draft=working_draft,
    )
    use_real = runtime["use_real"]
    default_mode_source = runtime["default_mode_source"]
    candidate_context = runtime["candidate_context"]
    company_context = runtime["company_context"]
    ask_brief = runtime["ask_brief"]
    language_decision = runtime["language_decision"]
    question_analysis = runtime["question_analysis"]
    evidence = runtime["evidence"]
    assembled_context = runtime["assembled_context"]
    live_prepared_context = runtime["live_prepared_context"]

    response_composer = ResponseComposer(
        mode=ComposerMode.REAL if use_real else ComposerMode.DEMO,
        use_llm=use_real,
    )
    start_perf = perf_counter()
    generated_response = await response_composer.compose(assembled_context, on_bullets=None)
    final_response = generated_response
    if not str(final_response.full_response or "").strip():
        final_response.full_response = _build_live_preview_response_text(
            question_analysis,
            final_response.bullets,
        )
    total_latency_ms = int((perf_counter() - start_perf) * 1000)
    suggested_metadata = getattr(final_response, "metadata", {}) or {}
    if not isinstance(suggested_metadata, dict):
        suggested_metadata = {}

    actual_mode = getattr(final_response, "mode", "real" if use_real else "demo")
    provider_used = suggested_metadata.get("provider")
    model_used = suggested_metadata.get("model")

    return {
        "success": True,
        "mode": actual_mode,
        "requested_mode": None,
        "resolved_mode": "real" if use_real else "demo",
        "mode_source": default_mode_source,
        "suggestion_id": session_id or str(uuid.uuid4()),
        "full_response": final_response.full_response,
        "bullets": final_response.bullets,
        "confidence": final_response.confidence,
        "quality_score": max(0.7, float(final_response.confidence or 0.0)),
        "suggestion": {
            "full_response": final_response.full_response,
            "suggestedAnswer": final_response.full_response,
            "bullets": final_response.bullets,
            "key_metrics": final_response.key_metrics,
            "keyMetrics": final_response.key_metrics,
            "confidence": final_response.confidence,
            "style": final_response.style_used.value,
            "questionType": question_analysis.primary_type.value,
            "questionMode": question_analysis.question_mode.value,
            "responseMode": question_analysis.response_mode.value,
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
            "styleReason": question_analysis.style_reason,
            "whyMetricsRequired": question_analysis.why_metrics_required,
            "normalizedFamily": ask_brief.answer_family.value,
            "normalizedPrimaryAsk": ask_brief.primary_ask,
            "normalizedSecondaryAsks": ask_brief.secondary_asks,
            "normalizedAnswerContract": ask_brief.answer_contract.value,
            "normalizedMetricsPolicy": ask_brief.metrics_policy.value,
            "normalizerConfidence": ask_brief.confidence,
            "normalizerLatencyMs": ask_brief.latency_ms,
            "fallbackUsed": True,
            "rewriteTriggered": bool(suggested_metadata.get("live_alignment_rewrite_applied")),
            "rewriteReason": "; ".join(suggested_metadata.get("live_alignment_issues", []) or []),
            "quality_score": max(0.7, float(final_response.confidence or 0.0)),
        },
        "language": {
            "detected": language_decision.final_language,
            "confidence": language_decision.confidence,
        },
        "quality": {
            "passed": True,
            "score": max(0.7, float(final_response.confidence or 0.0)),
            "issues": [],
        },
        "llm": {
            "provider": provider_used,
            "model": model_used,
        },
        "latency_ms": total_latency_ms,
        "candidate": (candidate_context.get("name") or "Candidato"),
        "company": (company_context.get("companyName") or company_context.get("name") or "Empresa"),
        "debug": {
            "question": question_text,
            "question_mode": question_analysis.question_mode.value,
            "response_mode": question_analysis.response_mode.value,
            "style_reason": question_analysis.style_reason,
            "why_metrics_required": question_analysis.why_metrics_required,
            "normalized_family": ask_brief.answer_family.value,
            "normalized_primary_ask": ask_brief.primary_ask,
            "normalized_secondary_asks": ask_brief.secondary_asks,
            "normalized_answer_contract": ask_brief.answer_contract.value,
            "normalized_metrics_policy": ask_brief.metrics_policy.value,
            "normalizer_confidence": ask_brief.confidence,
            "normalizer_latency_ms": ask_brief.latency_ms,
            "fallback_used": True,
            "complexity_class": live_prepared_context.complexity_class.value,
            "answer_shape": live_prepared_context.answer_shape.value,
            "target_length": live_prepared_context.target_length,
            "planner_source": live_prepared_context.planner_source,
            "planner_provider": live_prepared_context.planner_provider,
            "planner_model": live_prepared_context.planner_model,
            "planner_reasoning_summary": live_prepared_context.reasoning_summary,
            "live_fast_path_used": False,
            "live_fast_evidence_count": len(evidence),
            "rewrite_triggered": bool(suggested_metadata.get("live_alignment_rewrite_applied")),
            "rewrite_reason": "; ".join(suggested_metadata.get("live_alignment_issues", []) or []),
            "path_used": "writer_emergency_fallback",
            "time_to_bullets_ms": total_latency_ms,
        },
    }


async def _build_live_prepared_runtime(
    *,
    interview_config: dict[str, Any],
    question_text: str,
    conversation_history: list[dict[str, Any]],
    live_prepared_context: LivePreparedContext,
    working_draft: str = "",
) -> dict[str, Any]:
    from pipeline.steps.language_policy import LanguagePolicy
    from contracts.models import ResponseStyle, AssembledContext

    request_language = str(interview_config.get("language_preference") or "en").strip().lower() or "en"
    default_mode, default_mode_source, _, _, _ = await resolve_server_mode()
    use_real = default_mode == "real"

    style_str = interview_config.get("style_id") or interview_config.get("response_style") or "professional"
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
    response_style = style_map.get(str(style_str).lower(), ResponseStyle.MIXED)

    candidate_context = interview_config.get("candidate") or {}
    company_context = interview_config.get("company") or {}
    interviewer_context = interview_config.get("interviewer") or {}

    language_policy = LanguagePolicy(
        user_preference=request_language if request_language in {"es", "en"} else None
    )
    language_decision = language_policy.decide(question_text)

    ask_brief = live_prepared_context.ask_brief
    if ask_brief is None:
        ask_brief = AskNormalizer().normalize(
            question_text,
            conversation_history,
            delivery_mode="manual",
        )
    canonical_context = _canonicalize_live_prepared_context(live_prepared_context) or live_prepared_context
    ask_brief = canonical_context.ask_brief if canonical_context.ask_brief is not None else ask_brief

    question_analysis = _build_live_fast_question_analysis(
        question_text=question_text,
        ask_brief=ask_brief,
        live_prepared_context=canonical_context,
        conversation_history=conversation_history,
        delivery_mode="live_manual",
    )
    evidence = _build_live_fast_evidence(
        candidate_context=candidate_context,
        company_context=company_context,
        interviewer_context=interviewer_context,
        ordered_focus=canonical_context.asks_in_order if canonical_context is not None else None,
    )

    assembled_context = AssembledContext(
        question=question_text,
        analysis=question_analysis,
        ask_brief=ask_brief,
        evidence=evidence,
        conversation_summary="",
        conversation_history=conversation_history,
        topics_already_covered=[],
        metrics_already_used=[],
        achievements_referenced=candidate_context.get("achievements", []) or [],
        style_config={
            "response_style": interview_config.get("response_style", response_style.value),
            "language_preference": request_language,
            "style_id": style_str,
            "live_emergency_fallback": True,
        },
        interview_config=interview_config,
        delivery_mode="live_manual",
        max_words=canonical_context.target_length or interview_config.get("max_words") or 200,
        working_draft=working_draft,
        live_prepared_context=canonical_context,
    )

    return {
        "use_real": use_real,
        "default_mode_source": default_mode_source,
        "candidate_context": candidate_context,
        "company_context": company_context,
        "interviewer_context": interviewer_context,
        "ask_brief": ask_brief,
        "language_decision": language_decision,
        "question_analysis": question_analysis,
        "evidence": evidence,
        "assembled_context": assembled_context,
        "live_prepared_context": canonical_context,
    }


async def _repair_live_prepared_response(
    *,
    websocket: WebSocket,
    session_id: str,
    interview_config: dict[str, Any],
    question_text: str,
    conversation_history: list[dict[str, Any]],
    live_prepared_context: LivePreparedContext,
    base_response: dict[str, Any],
    issues: Optional[list[str]] = None,
) -> dict[str, Any]:
    from pipeline.steps.response_composer import ResponseComposer, ComposerMode

    runtime = await _build_live_prepared_runtime(
        interview_config=interview_config,
        question_text=question_text,
        conversation_history=conversation_history,
        live_prepared_context=live_prepared_context,
    )
    response_composer = ResponseComposer(
        mode=ComposerMode.REAL if runtime["use_real"] else ComposerMode.DEMO,
        use_llm=runtime["use_real"],
    )
    start_perf = perf_counter()
    repaired = await response_composer.repair_live_response(
        runtime["assembled_context"],
        str(base_response.get("full_response") or "").strip(),
        issues=issues,
    )
    if repaired is None or not str(repaired.full_response or "").strip():
        return {
            "success": False,
            "error": "live_repair_unavailable",
        }

    total_latency_ms = int((perf_counter() - start_perf) * 1000)
    metadata = getattr(repaired, "metadata", {}) or {}
    if not isinstance(metadata, dict):
        metadata = {}

    return {
        "success": True,
        "mode": getattr(repaired, "mode", "real" if runtime["use_real"] else "demo"),
        "requested_mode": None,
        "resolved_mode": "real" if runtime["use_real"] else "demo",
        "mode_source": runtime["default_mode_source"],
        "suggestion_id": session_id or str(uuid.uuid4()),
        "full_response": repaired.full_response,
        "bullets": repaired.bullets,
        "confidence": repaired.confidence,
        "quality_score": max(0.7, float(repaired.confidence or 0.0)),
        "suggestion": {
            "full_response": repaired.full_response,
            "suggestedAnswer": repaired.full_response,
            "bullets": repaired.bullets,
            "key_metrics": repaired.key_metrics,
            "keyMetrics": repaired.key_metrics,
            "confidence": repaired.confidence,
            "style": repaired.style_used.value,
            "questionType": runtime["question_analysis"].primary_type.value,
            "questionMode": runtime["question_analysis"].question_mode.value,
            "responseMode": runtime["question_analysis"].response_mode.value,
            "isCompound": runtime["question_analysis"].is_compound,
            "subQuestions": [
                {
                    "text": sq.text,
                    "priority": sq.priority.value,
                    "weight": sq.weight,
                }
                for sq in runtime["question_analysis"].sub_questions
            ],
            "underlyingIntent": runtime["question_analysis"].underlying_intent,
            "redFlags": runtime["question_analysis"].red_flags,
            "styleReason": runtime["question_analysis"].style_reason,
            "whyMetricsRequired": runtime["question_analysis"].why_metrics_required,
            "normalizedFamily": runtime["ask_brief"].answer_family.value,
            "normalizedPrimaryAsk": runtime["ask_brief"].primary_ask,
            "normalizedSecondaryAsks": runtime["ask_brief"].secondary_asks,
            "normalizedAnswerContract": runtime["ask_brief"].answer_contract.value,
            "normalizedMetricsPolicy": runtime["ask_brief"].metrics_policy.value,
            "normalizerConfidence": runtime["ask_brief"].confidence,
            "normalizerLatencyMs": runtime["ask_brief"].latency_ms,
            "fallbackUsed": True,
            "rewriteTriggered": True,
            "rewriteReason": "; ".join(metadata.get("repair_issues", []) or issues or []),
            "quality_score": max(0.7, float(repaired.confidence or 0.0)),
        },
        "language": {
            "detected": runtime["language_decision"].final_language,
            "confidence": runtime["language_decision"].confidence,
        },
        "quality": {
            "passed": True,
            "score": max(0.7, float(repaired.confidence or 0.0)),
            "issues": [],
        },
        "llm": {
            "provider": metadata.get("provider"),
            "model": metadata.get("model"),
        },
        "latency_ms": total_latency_ms,
        "candidate": (runtime["candidate_context"].get("name") or "Candidato"),
        "company": (runtime["company_context"].get("companyName") or runtime["company_context"].get("name") or "Empresa"),
        "debug": {
            "question": question_text,
            "question_mode": runtime["question_analysis"].question_mode.value,
            "response_mode": runtime["question_analysis"].response_mode.value,
            "style_reason": runtime["question_analysis"].style_reason,
            "why_metrics_required": runtime["question_analysis"].why_metrics_required,
            "normalized_family": runtime["ask_brief"].answer_family.value,
            "normalized_primary_ask": runtime["ask_brief"].primary_ask,
            "normalized_secondary_asks": runtime["ask_brief"].secondary_asks,
            "normalized_answer_contract": runtime["ask_brief"].answer_contract.value,
            "normalized_metrics_policy": runtime["ask_brief"].metrics_policy.value,
            "normalizer_confidence": runtime["ask_brief"].confidence,
            "normalizer_latency_ms": runtime["ask_brief"].latency_ms,
            "fallback_used": True,
            "complexity_class": runtime["live_prepared_context"].complexity_class.value,
            "answer_shape": runtime["live_prepared_context"].answer_shape.value,
            "target_length": runtime["live_prepared_context"].target_length,
            "planner_source": runtime["live_prepared_context"].planner_source,
            "planner_provider": runtime["live_prepared_context"].planner_provider,
            "planner_model": runtime["live_prepared_context"].planner_model,
            "planner_reasoning_summary": runtime["live_prepared_context"].reasoning_summary,
            "live_fast_path_used": False,
            "live_fast_evidence_count": len(runtime["evidence"]),
            "rewrite_triggered": True,
            "rewrite_reason": "; ".join(metadata.get("repair_issues", []) or issues or []),
            "path_used": "writer_prewarmed_repaired_fallback",
            "time_to_bullets_ms": total_latency_ms,
        },
    }


@dataclass
class InterviewerTurnCandidateState:
    """Minimal state for assembling an interviewer turn candidate."""

    text: str
    fragment_count: int = 1
    last_event_signature: Optional[str] = None


@dataclass
class LiveDisplayCaptionState:
    """Latest interviewer caption shown in the UI, including recent partial tails."""

    text: str
    updated_at: float
    is_partial: bool = True


@dataclass
class LiveInterviewerBlockState:
    """Semantic interviewer block accumulated across multiple finalized caption fragments."""

    text: str
    started_at: float
    updated_at: float
    fragment_count: int = 1


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
        self._interviewer_candidate_flush_task: Optional[asyncio.Task] = None
        self._interviewer_candidate_flush_token: int = 0
        self._interviewer_candidate_flush_sec: float = 1.0
        self._latest_interviewer_display_caption: Optional[LiveDisplayCaptionState] = None
        self._display_caption_stale_sec: float = 3.0
        self._current_live_interviewer_block: Optional[LiveInterviewerBlockState] = None
        self._completed_live_interviewer_blocks: list[dict[str, Any]] = []
        self._ui_transcript_history: list[dict[str, Any]] = []
        self._ui_transcript_consolidation_window_ms: int = 5000
        self._live_interviewer_block_gap_sec: float = 5.0
        self._last_completed_interviewer_turn_signature: Optional[str] = None
        self._last_completed_interviewer_turn_at: Optional[float] = None
        self._completed_interviewer_turn_count: int = 0
        self._latest_interviewer_generation: int = 0
        self._last_interviewer_activity_at: Optional[float] = None
        self._interviewer_activity_epoch: int = 0
        self._last_auto_suggestion_activity_epoch: Optional[int] = None
        self._last_auto_suggestion_silence_anchor_at_ms: Optional[int] = None
        self._last_auto_suggestion_interviewer_activity_at: Optional[float] = None
        self._last_auto_suggestion_question_key: str = ""
        self._hard_silence_gate_task: Optional[asyncio.Task] = None
        self._hard_silence_gate_epoch: int = 0
        self._silence_anchor_at_ms: Optional[int] = None
        self._silence_anchor_source: str = ""
        self._completed_turn_processed_at_ms: Optional[int] = None
        self._completed_turn_after_last_activity_ms: Optional[int] = None
        self._silence_gate_scheduled_delay_ms: Optional[int] = None
        self._silence_gate_fired_at_ms: Optional[int] = None
        self._duplicate_turn_window_sec: float = 3.0
        self._last_completed_turn_signature: Optional[str] = None
        self._last_completed_turn_at: Optional[float] = None
        self._speaker_corrector = SpeakerFallbackCorrector(session_id=session_id)
        self._speaker_fallback_enabled = True
        self._fallback_turn_confidence_threshold = 0.8
        self._turn_flush_task: Optional[asyncio.Task] = None
        self._turn_flush_token: int = 0
        # Turn boundary controls to prevent rapid-fire processing
        self._min_utterance_duration_ms = 2000  # Minimum 2 seconds
        self._min_utterance_words = 5  # Minimum 5 words
        self._suggestion_cooldown_sec = 5.0  # 5 second cooldown
        self._last_suggestion_at: Optional[float] = None
        self._background_tasks: set[asyncio.Task] = set()
        self._suggestion_debounce_task: Optional[asyncio.Task] = None
        self._suggestion_debounce_token: int = 0
        self._suggestion_debounce_sec: float = 0.7
        self._live_preparation_debounce_task: Optional[asyncio.Task] = None
        self._live_preparation_debounce_token: int = 0
        self._live_preparation_debounce_sec: float = 0.25
        self._live_semantic_refresh_task: Optional[asyncio.Task] = None
        self._live_semantic_refresh_signature: str = ""
        self._live_semantic_grace_sec: float = 0.3
        self._live_brain_refresh_task_v3: Optional[asyncio.Task] = None
        self._live_brain_refresh_pending_v3: bool = False
        self._live_brain_refresh_pending_reason_v3: str = ""
        self._live_brain_refresh_active_signature_v3: str = ""
        self._live_brain_refresh_active_started_at_v3: Optional[float] = None
        self._live_brain_last_signature: str = ""
        self._live_brain_last_status: str = "idle"
        self._live_brain_last_failure_reason: str = ""
        self._live_brain_last_llm_failure_kind: str = ""
        self._live_brain_last_duration_ms: int = 0
        self._live_brain_started_at_ms: Optional[int] = None
        self._live_brain_completed_at_ms: Optional[int] = None
        self._live_brain_semantic_revision_id_v3: int = 0
        self._live_brain_semantic_revision_hash_v3: str = ""
        self._live_brain_semantic_revision_text_v3: str = ""
        self._live_brain_semantic_word_count_v3: int = 0
        self._live_brain_semantic_completed_turn_count_v3: int = 0
        self._live_brain_last_refresh_reason_v3: str = "idle"
        self._live_quality_refresh_task: Optional[asyncio.Task] = None
        self._live_quality_refresh_signature: str = ""
        self._live_quality_refresh_context: Optional[LivePreparedContext] = None
        self._live_quality_refresh_started_at: Optional[float] = None
        self._live_quality_cached_signature: str = ""
        self._live_quality_cached_response: Optional[dict[str, Any]] = None
        self._live_quality_cached_context: Optional[LivePreparedContext] = None
        live_brain_v3_default = "0" if os.getenv("PYTEST_CURRENT_TEST") else "1"
        live_brain_direct_default = "0"
        live_legacy_fallback_default = "1" if os.getenv("PYTEST_CURRENT_TEST") else "0"
        self._live_brain_v3_enabled: bool = os.getenv(
            "LIVE_BRAIN_V3_ENABLED",
            live_brain_v3_default,
        ).strip().lower() not in {"0", "false", "off", "no"}
        self._live_brain_direct_enabled: bool = os.getenv(
            "LIVE_BRAIN_DIRECT_ENABLED",
            live_brain_direct_default,
        ).strip().lower() not in {"0", "false", "off", "no"}
        self._live_legacy_fallback_enabled: bool = os.getenv(
            "LIVE_LEGACY_FALLBACK",
            live_legacy_fallback_default,
        ).strip().lower() in {"1", "true", "on", "yes"}
        self._live_brain_service_v3 = LiveBrainService(LiveBrainServiceConfig())
        self._live_evidence_packer_v3 = LiveEvidencePacker(LiveEvidencePackerConfig())
        self._live_finalizer_v3 = LiveFinalizer(LiveFinalizerConfig())
        self._latest_brain_snapshot_v3: Optional[BrainSnapshot] = None
        self._latest_brain_plan_v3: Optional[BrainPlan] = None
        self._latest_stable_brain_plan_v3: Optional[BrainPlan] = None
        self._latest_compact_evidence_pack_v3: Optional[CompactEvidencePack] = None
        self._latest_brain_recovery_draft_v3: str = ""
        self._latest_stable_brain_recovery_draft_v3: str = ""
        self._latest_brain_plan_hash_v3: str = ""
        self._latest_brain_question_key_v3: str = ""
        self._brain_plan_changed_at_v3: Optional[float] = None
        self._brain_plan_repeat_count_v3: int = 0
        self._late_brain_readiness_task_v3: Optional[asyncio.Task] = None
        self._late_brain_readiness_epoch_v3: int = 0
        self._brain_warm_inflight_task_v3: Optional[asyncio.Task] = None
        self._brain_warm_inflight_checkpoint_v3: Optional[LiveBrainWarmCheckpoint] = None
        self._brain_warm_latest_result_v3: Optional[LiveBrainWarmResult] = None
        self._brain_warm_schedule_task_v3: Optional[asyncio.Task] = None
        self._brain_warm_scheduled_plan_hash_v3: str = ""
        self._brain_warm_attempted_plan_hashes_v3: set[str] = set()
        self._live_parallel_warmer_v2_enabled: bool = os.getenv(
            "LIVE_PARALLEL_WARMER_V2",
            "1",
        ).strip().lower() not in {"0", "false", "off", "no"}
        self._live_parallel_warmer_v2_shadow_mode: bool = os.getenv(
            "LIVE_PARALLEL_WARMER_V2_SHADOW",
            "0",
        ).strip().lower() in {"1", "true", "on", "yes"}
        self._live_warm_inflight_task: Optional[asyncio.Task] = None
        self._live_warm_inflight_checkpoint: Optional[LiveWarmCheckpoint] = None
        self._live_warm_latest_result: Optional[LiveWarmResult] = None
        self._live_warm_wait_sec: float = 1.2
        self._live_last_warm_debug: dict[str, Any] = {}
        self._brain_refresh_count_before_silence: int = 0
        self._emit_prewarm_started_before_silence: bool = False
        self._emit_prewarm_count_before_silence: int = 0
        self._emit_calls_before_silence: int = 0
        self._emit_finalize_calls_after_silence: int = 0
        self._answer_gate_reason: str = "idle"
        self._hard_silence_authorized: bool = False
        self._late_brain_refresh_started_before_silence: bool = False
        self._late_brain_refresh_completed_before_silence: bool = False
        self._brain_force_stable_at_freeze: bool = False
        self._brain_refresh_waited_at_freeze_ms: int = 0
        self._brain_immediate_safe_fallback_at_freeze: bool = False
        self._emit_started_at_ms: Optional[int] = None
        self._emit_stream_started_at_ms: Optional[int] = None
        self._emit_first_chunk_ms: Optional[int] = None
        self._emit_stream_completed_at_ms: Optional[int] = None
        self._emit_stream_chunk_count: int = 0
        self._emit_stream_partial_salvaged: bool = False
        self._live_question_stabilization_sec: float = 0.35
        self._live_quality_grace_sec: float = 0.65
        self._live_quality_extended_grace_sec: float = 2.2
        self._live_brain_freeze_wait_grace_sec: float = 0.2
        self._live_quality_final_emit_timeout_sec: float = 10.5
        self._live_emit_prewarm_enabled: bool = False
        self._live_brain_final_readiness_quiet_sec: float = 0.6
        self._live_emit_late_prewarm_quiet_sec: float = 0.6
        self._live_emit_late_prewarm_silence_wait_sec: float = 0.4
        silence_threshold_ms = 2000
        try:
            pipeline_silence_threshold_ms = int(getattr(self._pipeline, "config", None).silence_threshold_ms)
            silence_threshold_ms = max(2000, pipeline_silence_threshold_ms)
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
            context_turn_limit=5,
        )

    def _track_background_task(self, task: asyncio.Task) -> None:
        self._background_tasks.add(task)

        def _cleanup(completed_task: asyncio.Task) -> None:
            self._background_tasks.discard(completed_task)
            with contextlib.suppress(asyncio.CancelledError):
                exc = completed_task.exception()
                if exc is not None:
                    print(
                        "[WS][TURN] background_task_failed "
                        f"session_id={self._session_id} error={exc}"
                    )

        task.add_done_callback(_cleanup)

    def _cancel_live_brain_warm_schedule(self) -> None:
        if self._brain_warm_schedule_task_v3 and not self._brain_warm_schedule_task_v3.done():
            self._brain_warm_schedule_task_v3.cancel()
        self._brain_warm_schedule_task_v3 = None
        self._brain_warm_scheduled_plan_hash_v3 = ""

    def _cancel_live_brain_warm_inflight(self) -> None:
        if self._brain_warm_inflight_task_v3 and not self._brain_warm_inflight_task_v3.done():
            self._brain_warm_inflight_task_v3.cancel()
        self._brain_warm_inflight_task_v3 = None
        self._brain_warm_inflight_checkpoint_v3 = None

    def _cancel_hard_silence_gate(self) -> None:
        if self._hard_silence_gate_task and not self._hard_silence_gate_task.done():
            self._hard_silence_gate_task.cancel()
        self._hard_silence_gate_task = None
        self._hard_silence_gate_epoch = 0

    def _cancel_late_brain_readiness_refresh(self) -> None:
        if self._late_brain_readiness_task_v3 and not self._late_brain_readiness_task_v3.done():
            self._late_brain_readiness_task_v3.cancel()
        self._late_brain_readiness_task_v3 = None
        self._late_brain_readiness_epoch_v3 = 0

    def _reset_live_answer_attempt_counters(self) -> None:
        self._brain_refresh_count_before_silence = 0
        self._emit_prewarm_started_before_silence = False
        self._emit_prewarm_count_before_silence = 0
        self._emit_calls_before_silence = 0
        self._emit_finalize_calls_after_silence = 0
        self._answer_gate_reason = "waiting_for_hard_silence"
        self._hard_silence_authorized = False
        self._completed_turn_processed_at_ms = None
        self._completed_turn_after_last_activity_ms = None
        self._silence_gate_scheduled_delay_ms = None
        self._silence_gate_fired_at_ms = None
        self._late_brain_refresh_started_before_silence = False
        self._late_brain_refresh_completed_before_silence = False
        self._brain_force_stable_at_freeze = False
        self._brain_refresh_waited_at_freeze_ms = 0
        self._brain_immediate_safe_fallback_at_freeze = False
        self._emit_started_at_ms = None
        self._emit_stream_started_at_ms = None
        self._emit_first_chunk_ms = None
        self._emit_stream_completed_at_ms = None
        self._emit_stream_chunk_count = 0
        self._emit_stream_partial_salvaged = False
        self._brain_warm_attempted_plan_hashes_v3.clear()

    def _mark_interviewer_activity(
        self,
        *,
        event_time: Optional[float] = None,
        cancel_suggestion: bool = True,
        cancel_warm_schedule: bool = True,
        gate_reason: str = "interviewer_active",
        anchor_source: str = "display_caption",
    ) -> None:
        self._last_interviewer_activity_at = event_time or time.time()
        self._interviewer_activity_epoch += 1
        self._silence_anchor_at_ms = self._stream_elapsed_ms()
        self._silence_anchor_source = anchor_source
        self._reset_live_answer_attempt_counters()
        self._hard_silence_authorized = False
        self._answer_gate_reason = gate_reason
        if cancel_suggestion:
            self._cancel_suggestion_debounce()
        if cancel_warm_schedule:
            self._cancel_live_brain_warm_schedule()
        self._cancel_hard_silence_gate()
        self._cancel_late_brain_readiness_refresh()
        self._schedule_hard_silence_gate()
        self._schedule_final_brain_readiness_refresh()

    def _refresh_interviewer_gate_without_reanchoring(
        self,
        *,
        gate_reason: str,
        turn: Optional[SpeakerTurn] = None,
    ) -> None:
        self._hard_silence_authorized = False
        self._answer_gate_reason = gate_reason
        self._completed_turn_processed_at_ms = self._stream_elapsed_ms()
        if self._last_interviewer_activity_at is None and turn is not None:
            anchor_time = turn.end_time if isinstance(turn.end_time, (int, float)) else turn.start_time
            if isinstance(anchor_time, (int, float)):
                self._last_interviewer_activity_at = float(anchor_time)
                self._silence_anchor_at_ms = self._stream_elapsed_ms()
                self._silence_anchor_source = "completed_turn_fallback"
        if self._last_interviewer_activity_at is not None:
            self._completed_turn_after_last_activity_ms = int(
                max(0.0, time.time() - self._last_interviewer_activity_at) * 1000
            )
        self._cancel_suggestion_debounce()
        self._cancel_live_brain_warm_schedule()
        if (
            not self._downstream_in_flight
            and self._interviewer_activity_epoch == 0
            and self._last_interviewer_activity_at is not None
        ):
            self._schedule_hard_silence_gate()

    def _interviewer_activity_age_sec(self) -> Optional[float]:
        if self._last_interviewer_activity_at is None:
            return None
        return max(0.0, time.time() - self._last_interviewer_activity_at)

    def _remaining_hard_silence_sec(self) -> float:
        threshold_sec = max(self._turn_assembler.state.silence_threshold_ms / 1000.0, 0.0)
        age_sec = self._interviewer_activity_age_sec()
        if age_sec is None:
            return threshold_sec
        return max(0.0, threshold_sec - age_sec)

    def _hard_silence_is_satisfied(self) -> bool:
        return self._remaining_hard_silence_sec() <= 0.0

    def _auto_suggestion_already_served_for_current_silence(self) -> bool:
        same_epoch = (
            self._interviewer_activity_epoch > 0
            and self._last_auto_suggestion_activity_epoch == self._interviewer_activity_epoch
        )
        same_anchor = (
            self._silence_anchor_at_ms is not None
            and self._last_auto_suggestion_silence_anchor_at_ms is not None
            and self._silence_anchor_at_ms == self._last_auto_suggestion_silence_anchor_at_ms
        )
        same_activity_timestamp = (
            self._last_interviewer_activity_at is not None
            and self._last_auto_suggestion_interviewer_activity_at is not None
            and abs(
                self._last_interviewer_activity_at - self._last_auto_suggestion_interviewer_activity_at
            )
            <= 0.001
        )
        return same_epoch or same_anchor or same_activity_timestamp

    def _mark_auto_suggestion_served(self, *, snapshot: Optional[LiveFrozenSnapshot] = None) -> None:
        self._last_auto_suggestion_activity_epoch = self._interviewer_activity_epoch
        self._last_auto_suggestion_silence_anchor_at_ms = self._silence_anchor_at_ms
        self._last_auto_suggestion_interviewer_activity_at = self._last_interviewer_activity_at
        self._last_auto_suggestion_question_key = (
            str(getattr(snapshot, "question_key", "") or "").strip().lower()
            if snapshot is not None
            else ""
        )

    def _build_hard_silence_gate_turn(self) -> SpeakerTurn:
        gate_text = ""
        if self._current_live_interviewer_block is not None:
            gate_text = self._normalize_turn_text(self._current_live_interviewer_block.text)
        if not gate_text:
            gate_text = self._get_recent_interviewer_display_caption_text()
        if not gate_text and self._completed_live_interviewer_blocks:
            gate_text = self._normalize_turn_text(self._completed_live_interviewer_blocks[-1].get("text") or "")
        event_time = self._last_interviewer_activity_at or time.time()
        return SpeakerTurn(
            speaker="interviewer",
            text=gate_text,
            start_time=event_time,
            end_time=event_time,
            utterances=[gate_text] if gate_text else [],
            language="en",
            metadata={"source": "hard_silence_gate"},
            completion_reason="hard_silence_gate",
            is_complete=True,
        )

    def _ensure_hard_silence_gate_scheduled(self) -> None:
        if self._hard_silence_gate_task is not None and not self._hard_silence_gate_task.done():
            return
        if self._last_interviewer_activity_at is None:
            return
        self._schedule_hard_silence_gate()

    def _schedule_hard_silence_gate(self) -> None:
        if self._last_interviewer_activity_at is None:
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        self._cancel_hard_silence_gate()
        epoch = self._interviewer_activity_epoch
        delay_sec = self._remaining_hard_silence_sec()
        self._hard_silence_gate_epoch = epoch
        self._silence_gate_scheduled_delay_ms = int(max(0.0, delay_sec) * 1000)

        async def _run_hard_silence_gate() -> None:
            try:
                if delay_sec > 0:
                    await asyncio.sleep(delay_sec)
                if epoch != self._interviewer_activity_epoch:
                    return
                remaining_sec = self._remaining_hard_silence_sec()
                if remaining_sec > 0:
                    await asyncio.sleep(remaining_sec)
                if epoch != self._interviewer_activity_epoch or not self._hard_silence_is_satisfied():
                    return
                self._silence_gate_fired_at_ms = self._stream_elapsed_ms()
                task = asyncio.create_task(
                    self._try_auto_trigger_suggestion(
                        self._build_hard_silence_gate_turn(),
                        generation_token=None,
                    ),
                    name=f"live-hard-silence-{self._session_id}-{epoch}",
                )
                self._track_background_task(task)
            except asyncio.CancelledError:
                return
            finally:
                if self._hard_silence_gate_task is asyncio.current_task():
                    self._hard_silence_gate_task = None
                    self._hard_silence_gate_epoch = 0

        task = asyncio.create_task(
            _run_hard_silence_gate(),
            name=f"hard-silence-gate-{self._session_id}-{epoch}",
        )
        self._hard_silence_gate_task = task
        self._track_background_task(task)

    def _live_emit_timeout_for_plan(self, plan: Optional[BrainPlan]) -> float:
        base_timeout = self._live_quality_final_emit_timeout_sec
        if plan is None:
            return base_timeout
        ask_count = len(list(plan.ordered_asks or []))
        if ask_count >= 4:
            return max(base_timeout, 12.5)
        return base_timeout

    def _live_brain_warm_remaining_budget_sec(
        self,
        *,
        checkpoint: Optional[LiveBrainWarmCheckpoint],
        plan: Optional[BrainPlan],
    ) -> float:
        total_budget = self._live_emit_timeout_for_plan(plan)
        if checkpoint is None:
            return total_budget
        try:
            created_at = checkpoint.created_at
            if not isinstance(created_at, datetime):
                return total_budget
            elapsed_sec = max(0.0, (datetime.utcnow() - created_at).total_seconds())
        except Exception:
            return total_budget
        return max(self._live_emit_late_prewarm_silence_wait_sec, total_budget - elapsed_sec)

    def _live_brain_refresh_remaining_budget_sec(self) -> float:
        total_budget = self._live_brain_service_v3.config.llm_timeout_sec
        started_at = self._live_brain_refresh_active_started_at_v3
        if started_at is None:
            return total_budget
        elapsed_sec = max(0.0, perf_counter() - started_at)
        return max(0.2, total_budget - elapsed_sec)

    async def _await_live_brain_v3_refresh(
        self,
        *,
        snapshot_hash: str,
        timeout_sec: Optional[float] = None,
    ) -> int:
        task = self._live_brain_refresh_task_v3
        if not snapshot_hash or task is None or task.done():
            return 0
        active_signature = str(self._live_brain_refresh_active_signature_v3 or "").strip()
        if active_signature and active_signature != snapshot_hash:
            return 0
        wait_budget = timeout_sec if timeout_sec is not None else self._live_brain_refresh_remaining_budget_sec()
        wait_started = perf_counter()
        with contextlib.suppress(asyncio.TimeoutError, asyncio.CancelledError, Exception):
            await asyncio.wait_for(asyncio.shield(task), timeout=wait_budget)
        return int((perf_counter() - wait_started) * 1000)

    def _should_refresh_live_brain_v3(
        self,
        *,
        brain_snapshot: BrainSnapshot,
    ) -> tuple[bool, str]:
        text = _normalize_live_question_text(brain_snapshot.snapshot_text)
        if not text:
            return False, "empty_snapshot"

        previous_text = _normalize_live_question_text(self._live_brain_semantic_revision_text_v3)
        if not previous_text:
            return True, "first_revision"
        if text == previous_text:
            return False, "text_unchanged"

        if self._completed_interviewer_turn_count != self._live_brain_semantic_completed_turn_count_v3:
            return True, "completed_turn"

        if text.endswith(("?", ".", "!")) and not previous_text.endswith(("?", ".", "!")):
            return True, "sentence_boundary"

        current_words = len(text.split())
        added_words = max(0, current_words - self._live_brain_semantic_word_count_v3)
        if added_words >= 6:
            return True, "material_growth"

        if previous_text not in text and text not in previous_text:
            return True, "semantic_rewrite"

        return False, "caption_churn"

    def _record_live_brain_semantic_revision(
        self,
        *,
        brain_snapshot: BrainSnapshot,
        reason: str,
    ) -> None:
        normalized_text = _normalize_live_question_text(brain_snapshot.snapshot_text)
        self._live_brain_semantic_revision_id_v3 += 1
        self._live_brain_semantic_revision_hash_v3 = sha1(
            f"{brain_snapshot.snapshot_hash}:{self._live_brain_semantic_revision_id_v3}".encode("utf-8")
        ).hexdigest()
        self._live_brain_semantic_revision_text_v3 = normalized_text
        self._live_brain_semantic_word_count_v3 = len(normalized_text.split())
        self._live_brain_semantic_completed_turn_count_v3 = self._completed_interviewer_turn_count
        self._live_brain_last_refresh_reason_v3 = reason

    def _live_brain_plan_ready_for_snapshot_v3(
        self,
        *,
        brain_snapshot: BrainSnapshot,
    ) -> bool:
        latest_snapshot = self._latest_brain_snapshot_v3
        latest_plan = self._latest_brain_plan_v3
        if latest_snapshot is None or latest_plan is None:
            return False
        if latest_snapshot.snapshot_hash != brain_snapshot.snapshot_hash:
            return False
        if not list(latest_plan.ordered_asks or []):
            return False
        return self._brain_plan_completeness_rank(latest_plan) >= 3

    def _schedule_final_brain_readiness_refresh(self) -> None:
        if not self._live_brain_v3_enabled or self._last_interviewer_activity_at is None:
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        self._cancel_late_brain_readiness_refresh()
        epoch = self._interviewer_activity_epoch
        self._late_brain_readiness_epoch_v3 = epoch

        async def _run_final_brain_readiness() -> None:
            try:
                quiet_delay = max(
                    0.0,
                    self._live_brain_final_readiness_quiet_sec - (self._interviewer_activity_age_sec() or 0.0),
                )
                quiet_delay = min(quiet_delay, max(0.0, self._remaining_hard_silence_sec()))
                if quiet_delay > 0:
                    await asyncio.sleep(quiet_delay)
                if epoch != self._interviewer_activity_epoch or self._hard_silence_is_satisfied():
                    return
                brain_snapshot = self._build_live_brain_snapshot_v3(limit=5)
                if brain_snapshot is None or self._live_brain_plan_ready_for_snapshot_v3(brain_snapshot=brain_snapshot):
                    return
                self._late_brain_refresh_started_before_silence = True
                self._queue_live_brain_v3_refresh(reason="final_readiness")
                await self._await_live_brain_v3_refresh(snapshot_hash=brain_snapshot.snapshot_hash)
                if (
                    epoch == self._interviewer_activity_epoch
                    and not self._hard_silence_is_satisfied()
                    and self._live_brain_plan_ready_for_snapshot_v3(brain_snapshot=brain_snapshot)
                ):
                    self._late_brain_refresh_completed_before_silence = True
            except asyncio.CancelledError:
                return
            finally:
                if self._late_brain_readiness_task_v3 is asyncio.current_task():
                    self._late_brain_readiness_task_v3 = None
                    self._late_brain_readiness_epoch_v3 = 0

        task = asyncio.create_task(
            _run_final_brain_readiness(),
            name=f"final-brain-readiness-{self._session_id}-{epoch}",
        )
        self._late_brain_readiness_task_v3 = task
        self._track_background_task(task)

    def _normalize_live_brain_plan_for_active_route(self, plan: BrainPlan) -> BrainPlan:
        return plan.model_copy(
            update={
                "draft_answer": "",
                "serve_mode": "finalize_from_plan",
            }
        )

    def _normalize_live_v3_snapshot(self, snapshot: LiveFrozenSnapshot) -> LiveFrozenSnapshot:
        if snapshot.brain_plan is None:
            return snapshot
        normalized_plan = self._normalize_live_brain_plan_for_active_route(snapshot.brain_plan)
        if normalized_plan == snapshot.brain_plan:
            return snapshot
        normalized_plan_hash = self._live_brain_service_v3.plan_hash(normalized_plan)
        normalized_pack = snapshot.compact_evidence_pack
        if normalized_pack is not None and normalized_pack.plan_hash != normalized_plan_hash:
            normalized_pack = normalized_pack.model_copy(update={"plan_hash": normalized_plan_hash})
        return replace(
            snapshot,
            brain_plan=normalized_plan,
            compact_evidence_pack=normalized_pack,
            plan_hash=normalized_plan_hash,
        )

    def _queue_live_brain_v3_refresh(self, *, reason: str) -> None:
        self._live_brain_refresh_pending_v3 = True
        self._live_brain_refresh_pending_reason_v3 = reason
        if self._live_brain_refresh_task_v3 is not None and not self._live_brain_refresh_task_v3.done():
            return

        async def _run_refresh_loop() -> None:
            try:
                while self._live_brain_refresh_pending_v3:
                    self._live_brain_refresh_pending_v3 = False
                    refresh_reason = self._live_brain_refresh_pending_reason_v3 or "queued_refresh"
                    await self._refresh_live_brain_v3_state(refresh_reason=refresh_reason)
            except asyncio.CancelledError:
                return
            finally:
                if self._live_brain_refresh_task_v3 is asyncio.current_task():
                    self._live_brain_refresh_task_v3 = None

        task = asyncio.create_task(
            _run_refresh_loop(),
            name=f"live-brain-refresh-{self._session_id}",
        )
        self._live_brain_refresh_task_v3 = task
        self._track_background_task(task)

    def _stream_elapsed_ms(self) -> Optional[int]:
        if self._stream_started_at is None:
            return None
        return int((perf_counter() - self._stream_started_at) * 1000)

    def _mark_live_brain_started(self, *, signature: str) -> float:
        started = perf_counter()
        self._live_brain_refresh_active_signature_v3 = signature
        self._live_brain_refresh_active_started_at_v3 = started
        self._live_brain_last_signature = signature
        self._live_brain_last_status = "running"
        self._live_brain_last_failure_reason = ""
        self._live_brain_last_duration_ms = 0
        self._live_brain_started_at_ms = self._stream_elapsed_ms()
        self._live_brain_completed_at_ms = None
        return started

    def _mark_live_brain_finished(
        self,
        *,
        started_at: float,
        status: str,
        failure_reason: str = "",
    ) -> None:
        self._live_brain_last_status = status
        self._live_brain_last_failure_reason = failure_reason
        self._live_brain_last_duration_ms = int((perf_counter() - started_at) * 1000)
        self._live_brain_refresh_active_signature_v3 = ""
        self._live_brain_refresh_active_started_at_v3 = None
        self._live_brain_completed_at_ms = self._stream_elapsed_ms()

    async def _run_live_brain_draft(
        self,
        *,
        planner: Any,
        prepared_context: LivePreparedContext,
        interview_config: dict[str, Any],
    ) -> Optional[LivePreparedContext]:
        draft_fn = getattr(planner, "draft_from_prepared_context", None)
        if callable(draft_fn):
            drafted = draft_fn(
                prepared_context=prepared_context,
                interview_config=interview_config,
            )
            if inspect.isawaitable(drafted):
                drafted = await drafted
            if (
                isinstance(drafted, LivePreparedContext)
                and str(drafted.draft_answer or "").strip()
            ):
                return drafted

        prepare_fn = getattr(planner, "prepare", None)
        if callable(prepare_fn):
            prepared = prepare_fn(
                session_id=self._session_id,
                raw_turns=prepared_context.raw_turns,
                interview_config=interview_config,
                mode=self._default_mode,
            )
            if inspect.isawaitable(prepared):
                prepared = await prepared
            if (
                isinstance(prepared, LivePreparedContext)
                and str(prepared.draft_answer or "").strip()
            ):
                return prepared

        return None

    async def _run_live_best_effort_writer(
        self,
        *,
        planner: Any,
        prepared_context: LivePreparedContext,
        interview_config: dict[str, Any],
    ) -> Optional[LivePreparedContext]:
        write_fn = getattr(planner, "write_best_effort_from_prepared_context", None)
        if not callable(write_fn):
            return None

        drafted = write_fn(
            prepared_context=prepared_context,
            interview_config=interview_config,
        )
        if inspect.isawaitable(drafted):
            drafted = await drafted
        if (
            isinstance(drafted, LivePreparedContext)
            and _is_live_fast_emergency_draft_usable(drafted)
        ):
            return drafted
        return None

    def _schedule_completed_turn_processing(self, turn: SpeakerTurn) -> None:
        task = asyncio.create_task(
            self._process_completed_turn(turn),
            name=f"completed-turn-{self._session_id}",
        )
        self._track_background_task(task)

    @staticmethod
    def _is_interviewer_caption_source(source: Optional[str]) -> bool:
        normalized_source = str(source or "").strip().lower()
        return normalized_source in {"system", "loopback", "speaker", "desktop", "output"}

    def _build_completed_live_caption_turn(
        self,
        *,
        text: str,
        event_time: float,
        language: str,
        provider_metadata: dict[str, Any],
    ) -> SpeakerTurn:
        normalized_text = self._normalize_turn_text(text)
        synthetic_duration_sec = 0.6
        metadata = {
            "source": self._latest_source,
            "provider_event_type": provider_metadata.get("event_type"),
            "provider_request_id": _extract_request_id(provider_metadata) or "unknown",
            "provider_metadata": provider_metadata,
            "skip_duplicate_check": True,
            "live_caption_direct": True,
        }
        return SpeakerTurn(
            speaker="interviewer",
            text=normalized_text,
            start_time=event_time - synthetic_duration_sec,
            end_time=event_time,
            utterances=[normalized_text] if normalized_text else [],
            language=language,
            metadata=metadata,
            completion_reason="final_caption",
            is_complete=True,
        )

    def _cancel_interviewer_turn_candidate_flush(self) -> None:
        if self._interviewer_candidate_flush_task and not self._interviewer_candidate_flush_task.done():
            self._interviewer_candidate_flush_task.cancel()
        self._interviewer_candidate_flush_task = None

    def _complete_interviewer_turn_candidate(self, *, reason: str) -> Optional[str]:
        state = self._interviewer_turn_candidate
        if state is None:
            return None

        display_tail_text = self._get_recent_interviewer_display_caption_text()
        completed_text = (
            self._reconcile_streaming_interviewer_text(state.text, display_tail_text)
            if display_tail_text
            else state.text
        )
        completed_signature = completed_text.lower()
        self._interviewer_turn_candidate = None
        self._cancel_interviewer_turn_candidate_flush()
        now = perf_counter()

        if (
            completed_signature == self._last_completed_interviewer_turn_signature
            and self._last_completed_interviewer_turn_at is not None
            and (now - self._last_completed_interviewer_turn_at) <= self._duplicate_turn_window_sec
        ):
            print(
                "[WS][TURN] interviewer_turn_duplicate "
                f"session_id={self._session_id} reason={reason} text='{completed_text[:120]}'"
            )
            return None

        self._last_completed_interviewer_turn_signature = completed_signature
        self._last_completed_interviewer_turn_at = now
        self._completed_interviewer_turn_count += 1
        print(
            "[WS][TURN] interviewer_turn_candidate_complete "
            f"session_id={self._session_id} turn_index={self._completed_interviewer_turn_count} "
            f"fragments={state.fragment_count} reason={reason} text='{completed_text[:120]}'"
        )
        return completed_text

    def _schedule_interviewer_turn_candidate_flush(
        self,
        *,
        language: str,
        provider_metadata: dict[str, Any],
    ) -> None:
        self._cancel_interviewer_turn_candidate_flush()
        if self._interviewer_turn_candidate is None:
            return

        self._interviewer_candidate_flush_token += 1
        token = self._interviewer_candidate_flush_token

        async def _flush_candidate() -> None:
            try:
                await asyncio.sleep(self._interviewer_candidate_flush_sec)
                if token != self._interviewer_candidate_flush_token:
                    return
                completed_text = self._complete_interviewer_turn_candidate(reason="stabilized_final_caption")
                if not completed_text:
                    return
                self._ingest_completed_live_caption_turn(
                    text=completed_text,
                    event_time=self._last_interviewer_activity_at or time.time(),
                    language=language,
                    provider_metadata=provider_metadata,
                )
            except asyncio.CancelledError:
                return
            except Exception as e:
                print(
                    "[WS][TURN] interviewer_candidate_flush_failed "
                    f"session_id={self._session_id} error={e}"
                )

        task = asyncio.create_task(
            _flush_candidate(),
            name=f"interviewer-candidate-flush-{self._session_id}",
        )
        self._interviewer_candidate_flush_task = task
        self._track_background_task(task)

    def _ingest_completed_live_caption_turn(
        self,
        *,
        text: str,
        event_time: float,
        language: str,
        provider_metadata: dict[str, Any],
    ) -> bool:
        turn = self._build_completed_live_caption_turn(
            text=text,
            event_time=event_time,
            language=language,
            provider_metadata=provider_metadata,
        )
        if self._is_duplicate_turn(turn):
            print(
                "[WS][TURN] duplicate_live_caption_turn "
                f"session_id={self._session_id} text='{(turn.text or '')[:120]}'"
            )
            return False

        self._merge_current_live_interviewer_block(
            text=turn.text or "",
            event_time=event_time,
        )
        self._cancel_turn_flush()
        self._turn_assembler.reset()
        self._record_turn_event(turn)
        self._schedule_completed_turn_processing(turn)
        print(
            "[WS][TURN] live_caption_turn_complete "
            f"session_id={self._session_id} "
            f"source={self._latest_source} "
            f"text='{(turn.text or '')[:120]}'"
        )
        return True

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

    def _conversation_history_speaker_for_transcript_event(self, *, speaker: str) -> str:
        """Mirror the UI transcript speaker handling for conversation history."""
        if self._is_interviewer_caption_source(self._latest_source):
            return "interviewer"
        normalized = self._normalize_speaker(speaker)
        if normalized in {"interviewer", "candidate"}:
            return normalized
        return "unknown"

    def _record_ui_equivalent_transcript_entry(
        self,
        *,
        text: str,
        speaker: str,
        is_final: bool,
        timestamp_ms: Optional[int] = None,
    ) -> None:
        """Replicate the Tauri Conversation History rolling consolidation."""
        if not is_final:
            return

        normalized_text = self._normalize_turn_text(text)
        if not normalized_text:
            return

        now_ms = int(timestamp_ms if timestamp_ms is not None else time.time() * 1000)
        timestamp_iso = datetime.utcfromtimestamp(now_ms / 1000).isoformat()
        last_entry = self._ui_transcript_history[-1] if self._ui_transcript_history else None
        should_consolidate = (
            last_entry is not None
            and str(last_entry.get("speaker") or "") == speaker
            and (now_ms - int(last_entry.get("timestamp_ms") or 0)) < self._ui_transcript_consolidation_window_ms
        )

        if should_consolidate and last_entry is not None:
            last_text = self._normalize_turn_text(last_entry.get("text") or "")
            self._ui_transcript_history[-1] = {
                **last_entry,
                "text": f"{last_text} {normalized_text}".strip(),
                "timestamp_ms": now_ms,
                "timestamp": timestamp_iso,
                "is_final": is_final,
            }
        else:
            self._ui_transcript_history.append(
                {
                    "id": f"transcript-{now_ms}",
                    "speaker": speaker,
                    "text": normalized_text,
                    "timestamp_ms": now_ms,
                    "timestamp": timestamp_iso,
                    "is_final": is_final,
                }
            )

        self._ui_transcript_history = self._ui_transcript_history[-20:]

    def _get_ui_equivalent_transcript_window(self, limit: int = 5) -> list[dict[str, Any]]:
        window: list[dict[str, Any]] = []
        for entry in self._ui_transcript_history[-max(limit, 1):]:
            text = self._normalize_turn_text(entry.get("text") or "")
            if not text:
                continue
            window.append(
                {
                    "speaker": entry.get("speaker") or "unknown",
                    "text": text,
                    "timestamp": entry.get("timestamp"),
                    "timestamp_ms": entry.get("timestamp_ms"),
                    "ui_equivalent_transcript": True,
                }
            )
        return window[-limit:]

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
        current_words = current_text.split()
        incoming_words = incoming_text.split()
        max_overlap = min(len(current_words), len(incoming_words), 12)
        for overlap_size in range(max_overlap, 0, -1):
            if current_words[-overlap_size:] == incoming_words[:overlap_size]:
                merged_words = current_words + incoming_words[overlap_size:]
                return " ".join(merged_words).strip()
        return f"{current_text} {incoming_text}".strip()

    @staticmethod
    def _streaming_text_overlap_ratio(current_text: str, incoming_text: str) -> float:
        current_tokens = {
            token
            for token in re.findall(r"[a-z0-9]+", str(current_text or "").lower())
            if len(token) > 2
        }
        incoming_tokens = {
            token
            for token in re.findall(r"[a-z0-9]+", str(incoming_text or "").lower())
            if len(token) > 2
        }
        if not current_tokens or not incoming_tokens:
            return 0.0
        overlap = current_tokens & incoming_tokens
        return len(overlap) / max(1, min(len(current_tokens), len(incoming_tokens)))

    @staticmethod
    def _is_likely_streaming_tail_fragment(current_text: str, incoming_text: str) -> bool:
        current_tokens = re.findall(r"[a-z0-9]+", str(current_text or "").lower())
        incoming_tokens = re.findall(r"[a-z0-9]+", str(incoming_text or "").lower())
        if len(current_tokens) < 6 or len(incoming_tokens) < 3:
            return False
        if len(incoming_tokens) >= len(current_tokens):
            return False
        if len(incoming_tokens) > max(3, int(len(current_tokens) * 0.7)):
            return False
        for start in range(0, len(current_tokens) - len(incoming_tokens) + 1):
            if current_tokens[start : start + len(incoming_tokens)] == incoming_tokens:
                return True
        return False

    @classmethod
    def _reconcile_streaming_interviewer_text(cls, current_text: str, incoming_text: str) -> str:
        current = cls._normalize_turn_text(current_text)
        incoming = cls._normalize_turn_text(incoming_text)
        if not current:
            return incoming
        if not incoming:
            return current
        if current == incoming:
            return current
        if current in incoming:
            return incoming
        if incoming in current:
            return current
        if cls._is_likely_streaming_tail_fragment(current, incoming):
            return current

        overlap_ratio = cls._streaming_text_overlap_ratio(current, incoming)
        if overlap_ratio >= 0.58:
            # Streaming ASR events often resend the whole utterance with edits.
            # When two hypotheses strongly overlap, prefer the latest one instead
            # of concatenating them as if the incoming text were a delta.
            return incoming

        return cls._merge_turn_text(current, incoming)

    @classmethod
    def _is_material_interviewer_caption_progress(
        cls,
        *,
        previous_text: str,
        incoming_text: str,
        merged_text: str,
    ) -> bool:
        previous = cls._normalize_turn_text(previous_text)
        incoming = cls._normalize_turn_text(incoming_text)
        merged = cls._normalize_turn_text(merged_text)
        if not merged:
            return False
        if not previous:
            return True
        if merged == previous or incoming == previous:
            return False

        prev_tokens = re.findall(r"[a-z0-9]+", previous.lower())
        merged_tokens = re.findall(r"[a-z0-9]+", merged.lower())
        if len(merged_tokens) > len(prev_tokens):
            return True
        if len(merged) > len(previous) + 8:
            return True
        return False

    def _update_interviewer_display_caption(
        self,
        *,
        text: str,
        is_partial: bool,
        utterance_complete: bool,
        speaker: str,
    ) -> None:
        if speaker != "interviewer" or not self._is_interviewer_caption_source(self._latest_source):
            return
        normalized_text = self._normalize_turn_text(text)
        if not normalized_text:
            return
        event_time = time.time()
        previous_best_text = ""
        if self._current_live_interviewer_block is not None:
            previous_best_text = self._current_live_interviewer_block.text
        elif self._latest_interviewer_display_caption is not None:
            previous_best_text = self._latest_interviewer_display_caption.text
        current_text = normalized_text
        state = self._latest_interviewer_display_caption
        if state is not None and (event_time - state.updated_at) <= self._display_caption_stale_sec:
            current_text = self._reconcile_streaming_interviewer_text(state.text, normalized_text)
        if self._current_live_interviewer_block is not None:
            current_text = self._reconcile_streaming_interviewer_text(
                self._current_live_interviewer_block.text,
                current_text,
            )
        material_progress = self._is_material_interviewer_caption_progress(
            previous_text=previous_best_text,
            incoming_text=normalized_text,
            merged_text=current_text,
        )
        should_reanchor_silence = material_progress and (
            is_partial
            or not utterance_complete
            or self._last_interviewer_activity_at is None
        )
        if should_reanchor_silence:
            self._mark_interviewer_activity(
                event_time=event_time,
                cancel_suggestion=True,
                cancel_warm_schedule=True,
                gate_reason="interviewer_active",
                anchor_source="display_caption_final" if not is_partial else "display_caption_partial",
            )
        self._latest_interviewer_display_caption = LiveDisplayCaptionState(
            text=current_text,
            updated_at=event_time,
            is_partial=is_partial,
        )
        # Capture owns the live interviewer block. Persist the latest reconciled
        # display caption immediately so the final tail does not depend on
        # material-progress gating or a short-lived caption cache surviving until
        # silence handling.
        capture_event_time = event_time
        if self._current_live_interviewer_block is not None:
            capture_event_time = self._current_live_interviewer_block.updated_at + 0.001
        self._merge_current_live_interviewer_block(
            text=current_text,
            event_time=capture_event_time,
        )

    def _get_recent_interviewer_display_caption_text(self) -> str:
        state = self._latest_interviewer_display_caption
        if state is None:
            return ""
        if (time.time() - state.updated_at) > self._display_caption_stale_sec:
            return ""
        return self._normalize_turn_text(state.text)

    def _recent_interviewer_display_caption_is_active(self) -> bool:
        state = self._latest_interviewer_display_caption
        if state is None:
            return False
        activity_window_sec = min(
            self._display_caption_stale_sec,
            max(self._turn_assembler.state.silence_threshold_ms / 1000.0, 0.0),
        )
        return (time.time() - state.updated_at) < activity_window_sec

    @staticmethod
    def _extract_live_turn_texts(turns: list[dict[str, Any]]) -> list[str]:
        texts: list[str] = []
        for turn in turns:
            text = " ".join(str(turn.get("text") or turn.get("content") or "").split()).strip()
            if text:
                texts.append(text)
        return texts

    @staticmethod
    def _live_turn_ordering_value(turn: dict[str, Any]) -> float:
        timestamp_ms = turn.get("timestamp_ms")
        if isinstance(timestamp_ms, (int, float)):
            return float(timestamp_ms) / 1000.0

        for key in ("end_time", "start_time"):
            value = turn.get(key)
            if isinstance(value, (int, float)):
                return float(value)

        timestamp = str(turn.get("timestamp") or "").strip()
        if timestamp:
            with contextlib.suppress(ValueError, TypeError):
                return datetime.fromisoformat(timestamp).timestamp()

        return float("-inf")

    def _prefer_richer_live_turn_window(
        self,
        semantic_window: list[dict[str, Any]],
        tracker_window: list[dict[str, Any]],
        *,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        semantic_snapshot = _normalize_live_question_text(
            _build_live_brain_snapshot_text(_normalize_live_turn_window(semantic_window, limit=limit))
        ).lower()
        tracker_snapshot = _normalize_live_question_text(
            _build_live_brain_snapshot_text(_normalize_live_turn_window(tracker_window, limit=limit))
        ).lower()
        if semantic_snapshot and tracker_snapshot and semantic_snapshot != tracker_snapshot:
            if tracker_snapshot in semantic_snapshot and (len(semantic_snapshot) - len(tracker_snapshot)) >= 24:
                return semantic_window[-limit:]
            if semantic_snapshot in tracker_snapshot and (len(tracker_snapshot) - len(semantic_snapshot)) >= 24:
                return tracker_window[-limit:]

        semantic_texts = self._extract_live_turn_texts(semantic_window)
        tracker_texts = self._extract_live_turn_texts(tracker_window)

        if not semantic_texts:
            return tracker_window[-limit:]
        if not tracker_texts:
            return semantic_window[-limit:]

        max_len = max(len(semantic_texts), len(tracker_texts))
        for offset in range(1, max_len + 1):
            semantic_text = semantic_texts[-offset] if offset <= len(semantic_texts) else ""
            tracker_text = tracker_texts[-offset] if offset <= len(tracker_texts) else ""
            if semantic_text == tracker_text:
                continue
            if semantic_text and tracker_text:
                if semantic_text in tracker_text and len(tracker_text) > len(semantic_text):
                    return tracker_window[-limit:]
                if tracker_text in semantic_text and len(semantic_text) > len(tracker_text):
                    return semantic_window[-limit:]
                if len(tracker_text) != len(semantic_text):
                    return (
                        tracker_window[-limit:]
                        if len(tracker_text) > len(semantic_text)
                        else semantic_window[-limit:]
                    )
            elif tracker_text:
                return tracker_window[-limit:]
            elif semantic_text:
                return semantic_window[-limit:]

        semantic_total = sum(len(text) for text in semantic_texts)
        tracker_total = sum(len(text) for text in tracker_texts)
        if tracker_total > semantic_total:
            return tracker_window[-limit:]
        return semantic_window[-limit:]

    def _overlay_turn_matches_base_turn(
        self,
        *,
        base_text: str,
        overlay_text: str,
    ) -> bool:
        base = self._normalize_turn_text(base_text)
        overlay = self._normalize_turn_text(overlay_text)
        if not base or not overlay:
            return False
        if base == overlay:
            return True
        if base in overlay or overlay in base:
            return True

        merged = self._reconcile_streaming_interviewer_text(base, overlay)
        if merged == base or not _should_merge_live_turn_entries(base, overlay):
            return False
        return _looks_like_live_question_tail_fragment(base) or not base.endswith(("?", ".", "!"))

    def _compose_ui_window_with_live_overlay(
        self,
        *,
        ui_equivalent_window: list[dict[str, Any]],
        overlay_window: list[dict[str, Any]],
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        if not ui_equivalent_window or not overlay_window:
            return []

        composed = [dict(turn) for turn in ui_equivalent_window[-limit:]]
        base_last_turn = dict(composed[-1])
        base_last_text = self._normalize_turn_text(
            base_last_turn.get("text") or base_last_turn.get("content") or ""
        )
        if not base_last_text:
            return []

        overlay_last_turn = dict(overlay_window[-1])
        overlay_last_text = self._normalize_turn_text(
            overlay_last_turn.get("text") or overlay_last_turn.get("content") or ""
        )
        if not overlay_last_text or overlay_last_text == base_last_text:
            return []

        overlay_prev_text = ""
        if len(overlay_window) >= 2:
            overlay_prev_text = self._normalize_turn_text(
                overlay_window[-2].get("text") or overlay_window[-2].get("content") or ""
            )

        merged_text = self._reconcile_streaming_interviewer_text(base_last_text, overlay_last_text)
        overlay_extends_base = base_last_text in overlay_last_text and len(overlay_last_text) > len(base_last_text)
        mergeable_same_turn = (
            self._overlay_turn_matches_base_turn(
                base_text=base_last_text,
                overlay_text=overlay_last_text,
            )
            and len(merged_text) > len(base_last_text)
        )
        append_followup = (
            bool(overlay_prev_text)
            and self._overlay_turn_matches_base_turn(
                base_text=base_last_text,
                overlay_text=overlay_prev_text,
            )
            and overlay_last_text != overlay_prev_text
            and overlay_last_text != base_last_text
        )

        if append_followup:
            appended_turn = dict(overlay_last_turn)
            appended_turn["speaker"] = appended_turn.get("speaker") or base_last_turn.get("speaker") or "interviewer"
            appended_turn["text"] = overlay_last_text
            appended_turn["live_tail_augmented"] = True
            composed.append(appended_turn)
            return composed[-limit:]

        if overlay_extends_base or mergeable_same_turn:
            richer_text = overlay_last_text if len(overlay_last_text) >= len(merged_text) else merged_text
            merged_last_turn = dict(base_last_turn)
            merged_last_turn["text"] = richer_text
            merged_last_turn["live_tail_augmented"] = True
            for key in ("timestamp", "timestamp_ms", "start_time", "end_time"):
                overlay_value = overlay_last_turn.get(key)
                if overlay_value not in {None, ""}:
                    merged_last_turn[key] = overlay_value
            composed[-1] = merged_last_turn
            return composed[-limit:]

        return []

    def _should_prefer_tracker_window_over_ui_history(
        self,
        *,
        ui_equivalent_window: list[dict[str, Any]],
        tracker_window: list[dict[str, Any]],
    ) -> bool:
        if not ui_equivalent_window or not tracker_window:
            return False
        if len(tracker_window) <= len(ui_equivalent_window):
            return False

        ui_last_text = self._normalize_turn_text(
            ui_equivalent_window[-1].get("text") or ui_equivalent_window[-1].get("content") or ""
        )
        tracker_last_text = self._normalize_turn_text(
            tracker_window[-1].get("text") or tracker_window[-1].get("content") or ""
        )
        if not ui_last_text or not tracker_last_text:
            return False
        if ui_last_text not in tracker_last_text:
            return False
        if (len(tracker_last_text) - len(ui_last_text)) < 24:
            return False
        return True

    def _merge_ui_window_with_richer_last_turn(
        self,
        ui_equivalent_window: list[dict[str, Any]],
        richer_non_ui_window: list[dict[str, Any]],
        *,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        if not ui_equivalent_window or not richer_non_ui_window:
            return []
        if len(richer_non_ui_window) > (len(ui_equivalent_window) + 1):
            return []

        ui_last = self._normalize_turn_text(
            ui_equivalent_window[-1].get("text") or ui_equivalent_window[-1].get("content") or ""
        )
        richer_last = self._normalize_turn_text(
            richer_non_ui_window[-1].get("text") or richer_non_ui_window[-1].get("content") or ""
        )
        if not ui_last or not richer_last or ui_last == richer_last:
            return []
        if ui_last not in richer_last:
            return []

        merged_window = [dict(turn) for turn in ui_equivalent_window[-limit:]]
        merged_last_turn = dict(merged_window[-1])
        richer_last_turn = dict(richer_non_ui_window[-1])
        merged_last_turn["text"] = richer_last_turn.get("text") or richer_last
        merged_last_turn["live_tail_augmented"] = True
        for key in ("timestamp", "timestamp_ms", "start_time", "end_time"):
            if merged_last_turn.get(key) in {None, ""} and richer_last_turn.get(key) not in {None, ""}:
                merged_last_turn[key] = richer_last_turn.get(key)
        merged_window[-1] = merged_last_turn
        return merged_window[-limit:]

    def _augment_live_turn_window_with_recent_tail(
        self,
        turns: list[dict[str, Any]],
        *,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        window = [dict(turn) for turn in turns[-limit:]]

        pending_candidate_text = self._normalize_turn_text(
            self._interviewer_turn_candidate.text if self._interviewer_turn_candidate is not None else ""
        )
        display_tail_text = self._get_recent_interviewer_display_caption_text()

        if pending_candidate_text and display_tail_text:
            tail_text = self._reconcile_streaming_interviewer_text(
                pending_candidate_text,
                display_tail_text,
            )
        else:
            tail_text = pending_candidate_text or display_tail_text

        tail_text = self._normalize_turn_text(tail_text)
        if not tail_text:
            return window

        if pending_candidate_text:
            if window:
                last_text = self._normalize_turn_text(window[-1].get("text") or window[-1].get("content") or "")
                if last_text == tail_text or tail_text in last_text:
                    return window[-limit:]
            window.append(
                {
                    "speaker": "interviewer",
                    "text": tail_text,
                    "timestamp": datetime.utcnow().isoformat(),
                    "start_time": None,
                    "end_time": None,
                    "live_tail_augmented": True,
                }
            )
            return window[-limit:]

        if not window:
            return [
                {
                    "speaker": "interviewer",
                    "text": tail_text,
                    "timestamp": datetime.utcnow().isoformat(),
                    "start_time": None,
                    "end_time": None,
                    "live_tail_augmented": True,
                }
            ]

        last_turn = dict(window[-1])
        last_text = self._normalize_turn_text(last_turn.get("text") or last_turn.get("content") or "")
        merged_text = self._reconcile_streaming_interviewer_text(last_text, tail_text)
        if merged_text != last_text:
            last_turn["text"] = merged_text
            last_turn["live_tail_augmented"] = True
            window[-1] = last_turn
        return window[-limit:]

    def _build_non_tracker_live_turn_window(
        self,
        *,
        limit: int = 5,
        source_limit: Optional[int] = None,
        tracker: Any = None,
    ) -> list[dict[str, Any]]:
        source_limit = max(source_limit or max(limit * 3, 10), 1)
        ui_equivalent_window = _normalize_live_turn_window(
            self._get_ui_equivalent_transcript_window(limit=source_limit),
            limit=limit,
        )

        tracker_window: list[dict[str, Any]] = []
        if tracker is not None:
            raw_turns = tracker.get_last_n_turns(limit=source_limit)
            tracker_window = self._augment_live_turn_window_with_recent_tail(
                raw_turns,
                limit=source_limit,
            )
            tracker_window = _normalize_live_turn_window(tracker_window, limit=limit)

        semantic_window = _normalize_live_turn_window(
            self._build_live_interviewer_semantic_window(limit=source_limit),
            limit=limit,
        )

        if ui_equivalent_window:
            composed_ui_window = self._compose_ui_window_with_live_overlay(
                ui_equivalent_window=ui_equivalent_window,
                overlay_window=semantic_window,
                limit=limit,
            )
            if composed_ui_window:
                return composed_ui_window

            composed_tracker_window = self._compose_ui_window_with_live_overlay(
                ui_equivalent_window=ui_equivalent_window,
                overlay_window=tracker_window,
                limit=limit,
            )
            if self._should_prefer_tracker_window_over_ui_history(
                ui_equivalent_window=ui_equivalent_window,
                tracker_window=tracker_window,
            ):
                return tracker_window
            if composed_tracker_window:
                return composed_tracker_window

            return ui_equivalent_window

        if semantic_window and tracker_window:
            richer_non_ui_window = self._prefer_richer_live_turn_window(
                semantic_window,
                tracker_window,
                limit=limit,
            )
            if richer_non_ui_window:
                return richer_non_ui_window
        if semantic_window:
            return semantic_window
        if tracker_window:
            return tracker_window
        return []

    def _get_newer_non_tracker_active_turn_window(
        self,
        *,
        tracker_reference_window: list[dict[str, Any]],
        limit: int = 5,
        source_limit: Optional[int] = None,
        tracker: Any = None,
    ) -> list[dict[str, Any]]:
        source_limit = max(source_limit or max(limit * 3, 10), 1)
        candidate_window = self._get_newer_non_tracker_live_turn_window(
            tracker_reference_window=tracker_reference_window,
            limit=limit,
            source_limit=source_limit,
            tracker=tracker,
        )
        if not candidate_window:
            return []

        normalized_reference = _normalize_live_turn_window(
            tracker_reference_window,
            limit=source_limit,
        )
        if normalized_reference and self._extract_live_turn_texts(candidate_window) == self._extract_live_turn_texts(
            normalized_reference
        ):
            return []
        if normalized_reference:
            reference_last_text = self._normalize_turn_text(
                normalized_reference[-1].get("text") or normalized_reference[-1].get("content") or ""
            )
            candidate_last_text = self._normalize_turn_text(
                candidate_window[-1].get("text") or candidate_window[-1].get("content") or ""
            )
            if (
                reference_last_text
                and candidate_last_text
                and (
                    self._overlay_turn_matches_base_turn(
                        base_text=reference_last_text,
                        overlay_text=candidate_last_text,
                    )
                    or self._overlay_turn_matches_base_turn(
                        base_text=candidate_last_text,
                        overlay_text=reference_last_text,
                    )
                )
            ):
                answer_committed = self._last_auto_suggestion_interviewer_activity_at is not None
                if tracker is not None:
                    try:
                        commit_state = (
                            tracker.get_answer_commit_state()
                            if hasattr(tracker, "get_answer_commit_state")
                            else {}
                        )
                        answer_committed = answer_committed or bool(
                            isinstance(commit_state, dict)
                            and commit_state.get("last_answer_committed_at") is not None
                        )
                    except Exception:
                        pass
                reference_active_turns, _ = select_realtime_active_turn_window(
                    normalized_reference,
                    idle_close_sec=self._live_interviewer_block_gap_sec,
                    selected_turn_limit=source_limit,
                )
                reference_active_window = _normalize_live_turn_window(
                    reference_active_turns,
                    limit=limit,
                )
                if reference_active_window and len(reference_active_window) < len(normalized_reference):
                    candidate_active_turns, _ = select_realtime_active_turn_window(
                        candidate_window,
                        idle_close_sec=self._live_interviewer_block_gap_sec,
                        selected_turn_limit=source_limit,
                    )
                    candidate_active_window = _normalize_live_turn_window(
                        candidate_active_turns,
                        limit=limit,
                    )
                    if candidate_active_window and self._extract_live_turn_texts(
                        candidate_active_window
                    ) != self._extract_live_turn_texts(reference_active_window):
                        candidate_chars = sum(len(text) for text in self._extract_live_turn_texts(candidate_active_window))
                        reference_chars = sum(len(text) for text in self._extract_live_turn_texts(reference_active_window))
                        return candidate_active_window if candidate_chars >= reference_chars else []
                    return []
                if not answer_committed:
                    if len(candidate_window) > 1 and len(normalized_reference) > 1:
                        candidate_chars = sum(len(text) for text in self._extract_live_turn_texts(candidate_window))
                        reference_chars = sum(len(text) for text in self._extract_live_turn_texts(normalized_reference))
                        return candidate_window if candidate_chars >= reference_chars else normalized_reference[-limit:]
                    return normalized_reference[-limit:]
                candidate_active_turns, _ = select_realtime_active_turn_window(
                    candidate_window,
                    idle_close_sec=self._live_interviewer_block_gap_sec,
                    selected_turn_limit=source_limit,
                )
                reference_active_turns, _ = select_realtime_active_turn_window(
                    normalized_reference,
                    idle_close_sec=self._live_interviewer_block_gap_sec,
                    selected_turn_limit=source_limit,
                )
                candidate_active_window = _normalize_live_turn_window(
                    candidate_active_turns,
                    limit=limit,
                )
                reference_active_window = _normalize_live_turn_window(
                    reference_active_turns,
                    limit=limit,
                )
                candidate_isolated = len(candidate_active_window) < len(candidate_window)
                reference_isolated = len(reference_active_window) < len(normalized_reference)
                if candidate_active_window and candidate_isolated and not reference_isolated:
                    return candidate_active_window
                if reference_active_window and reference_isolated and not candidate_isolated:
                    return []
                if candidate_active_window and reference_active_window:
                    if self._extract_live_turn_texts(candidate_active_window) == self._extract_live_turn_texts(
                        reference_active_window
                    ):
                        return []
                    candidate_chars = sum(len(text) for text in self._extract_live_turn_texts(candidate_active_window))
                    reference_chars = sum(len(text) for text in self._extract_live_turn_texts(reference_active_window))
                    return candidate_active_window if candidate_chars >= reference_chars else []
                if candidate_active_window:
                    return candidate_active_window
                return []

        resolved_turn_window, _ = select_realtime_active_turn_window(
            candidate_window,
            idle_close_sec=self._live_interviewer_block_gap_sec,
            selected_turn_limit=source_limit,
        )
        active_candidate_window = _normalize_live_turn_window(
            resolved_turn_window or candidate_window,
            limit=limit,
        )
        if not active_candidate_window:
            return []

        if normalized_reference:
            tracker_last_order = self._live_turn_ordering_value(normalized_reference[-1])
            active_last_order = self._live_turn_ordering_value(active_candidate_window[-1])
            if active_last_order <= (tracker_last_order + 0.001):
                return []
        return active_candidate_window

    def _get_newer_non_tracker_live_turn_window(
        self,
        *,
        tracker_reference_window: list[dict[str, Any]],
        limit: int = 5,
        source_limit: Optional[int] = None,
        tracker: Any = None,
    ) -> list[dict[str, Any]]:
        source_limit = max(source_limit or max(limit * 3, 10), 1)
        candidate_window = self._build_non_tracker_live_turn_window(
            limit=limit,
            source_limit=source_limit,
            tracker=tracker,
        )
        if not candidate_window:
            return []

        normalized_reference = _normalize_live_turn_window(
            tracker_reference_window,
            limit=source_limit,
        )
        if normalized_reference:
            reference_last_text = self._normalize_turn_text(
                normalized_reference[-1].get("text") or normalized_reference[-1].get("content") or ""
            )
            candidate_last_text = self._normalize_turn_text(
                candidate_window[-1].get("text") or candidate_window[-1].get("content") or ""
            )
            if (
                reference_last_text
                and candidate_last_text
                and (
                    self._overlay_turn_matches_base_turn(
                        base_text=reference_last_text,
                        overlay_text=candidate_last_text,
                    )
                    or self._overlay_turn_matches_base_turn(
                        base_text=candidate_last_text,
                        overlay_text=reference_last_text,
                    )
                )
            ):
                if len(candidate_window) > 1 and len(normalized_reference) > 1:
                    candidate_chars = sum(len(text) for text in self._extract_live_turn_texts(candidate_window))
                    reference_chars = sum(len(text) for text in self._extract_live_turn_texts(normalized_reference))
                    return candidate_window if candidate_chars >= reference_chars else normalized_reference[-limit:]
                return normalized_reference[-limit:]

        candidate_last_order = self._live_turn_ordering_value(candidate_window[-1])
        if normalized_reference:
            tracker_last_order = self._live_turn_ordering_value(normalized_reference[-1])
            if candidate_last_order <= (tracker_last_order + 0.001):
                return []
        return candidate_window

    def _merge_current_live_interviewer_block(
        self,
        *,
        text: str,
        event_time: float,
    ) -> None:
        normalized_text = self._normalize_turn_text(text)
        if not normalized_text:
            return
        state = self._current_live_interviewer_block
        if state is None:
            self._current_live_interviewer_block = LiveInterviewerBlockState(
                text=normalized_text,
                started_at=event_time,
                updated_at=event_time,
                fragment_count=1,
            )
            return
        if (event_time - state.updated_at) > self._live_interviewer_block_gap_sec:
            self._finalize_current_live_interviewer_block(reason="time_gap_before_new_fragment")
            self._current_live_interviewer_block = LiveInterviewerBlockState(
                text=normalized_text,
                started_at=event_time,
                updated_at=event_time,
                fragment_count=1,
            )
            return
        merged_text = self._reconcile_streaming_interviewer_text(state.text, normalized_text)
        state.text = merged_text
        state.updated_at = event_time
        state.fragment_count += 1

    def _build_live_interviewer_semantic_window(
        self,
        *,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        window: list[dict[str, Any]] = [dict(block) for block in self._completed_live_interviewer_blocks[-limit:]]

        current_text = ""
        current_started_at: Optional[float] = None
        current_updated_at: Optional[float] = None
        current_fragment_count = 0

        if self._current_live_interviewer_block is not None:
            current_text = self._current_live_interviewer_block.text
            current_started_at = self._current_live_interviewer_block.started_at
            current_updated_at = self._current_live_interviewer_block.updated_at
            current_fragment_count = self._current_live_interviewer_block.fragment_count

        pending_candidate_text = self._normalize_turn_text(
            self._interviewer_turn_candidate.text if self._interviewer_turn_candidate is not None else ""
        )
        display_tail_text = self._get_recent_interviewer_display_caption_text()
        if pending_candidate_text:
            current_text = (
                self._reconcile_streaming_interviewer_text(current_text, pending_candidate_text)
                if current_text
                else pending_candidate_text
            )
        if display_tail_text:
            current_text = (
                self._reconcile_streaming_interviewer_text(current_text, display_tail_text)
                if current_text
                else display_tail_text
            )

        current_text = self._normalize_turn_text(current_text)
        if current_text:
            timestamp = None
            if current_updated_at is not None:
                timestamp = datetime.utcfromtimestamp(current_updated_at).isoformat()
            window.append(
                {
                    "speaker": "interviewer",
                    "text": current_text,
                    "timestamp": timestamp,
                    "start_time": current_started_at,
                    "end_time": current_updated_at,
                    "semantic_block": True,
                    "fragment_count": max(current_fragment_count, 1),
                }
            )

        return window[-limit:]

    def _finalize_current_live_interviewer_block(self, *, reason: str) -> None:
        window = self._build_live_interviewer_semantic_window(limit=1)
        if not window:
            self._current_live_interviewer_block = None
            return

        block = dict(window[-1])
        normalized_text = self._normalize_turn_text(block.get("text") or "")
        if not normalized_text:
            self._current_live_interviewer_block = None
            return

        block["text"] = normalized_text
        block["finalized_reason"] = reason

        if self._completed_live_interviewer_blocks:
            last_text = self._normalize_turn_text(self._completed_live_interviewer_blocks[-1].get("text") or "")
            if last_text == normalized_text:
                self._completed_live_interviewer_blocks[-1] = block
            else:
                self._completed_live_interviewer_blocks.append(block)
        else:
            self._completed_live_interviewer_blocks.append(block)

        self._completed_live_interviewer_blocks = self._completed_live_interviewer_blocks[-10:]
        self._current_live_interviewer_block = None

    def _freeze_live_active_ask(
        self,
        *,
        tracker: Any,
        question_fallback: str,
        interviewer_generation: Optional[int],
    ) -> None:
        if tracker is None or not hasattr(tracker, "record_active_ask_frozen"):
            return

        question_key = self._normalize_turn_text(question_fallback)
        active_turn_window, active_context_bundle = self._get_live_active_turn_window(limit=5)
        if active_turn_window:
            question_key = self._normalize_turn_text(
                (active_context_bundle.get("primary_question") if isinstance(active_context_bundle, dict) else "")
                or _build_live_brain_snapshot_text(active_turn_window)
                or question_key
            )
        builder = getattr(tracker, "build_normalized_realtime_context_bundle", None)
        if callable(builder) and not question_key:
            try:
                context_bundle = builder(limit=5)
                if hasattr(context_bundle, "model_dump"):
                    context_bundle = context_bundle.model_dump(mode="json")
                if isinstance(context_bundle, dict):
                    question_key = self._normalize_turn_text(
                        context_bundle.get("primary_question") or question_key
                    )
            except Exception as exc:
                print(
                    "[AUTO][SILENCE] freeze_boundary_preview_failed "
                    f"session_id={self._session_id} error={exc}"
                )

        if not question_key:
            return

        try:
            tracker.record_active_ask_frozen(
                frozen_at=time.time(),
                question_key=question_key,
                interviewer_generation=interviewer_generation,
            )
        except Exception as exc:
            print(
                "[AUTO][SILENCE] freeze_boundary_failed "
                f"session_id={self._session_id} error={exc}"
            )

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
            state.text = self._reconcile_streaming_interviewer_text(state.text, normalized_text)
            state.fragment_count += 1
            state.last_event_signature = incoming_signature

        if not (is_final and utterance_complete):
            return None

        return self._complete_interviewer_turn_candidate(reason="utterance_complete")

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
                self._schedule_live_preparation_refresh()
        except Exception as e:
            print(f"[TURN][ASSEMBLY] tracker_log_failed session_id={self._session_id} error={e}")

    def _schedule_live_preparation_refresh(self) -> None:
        task = asyncio.create_task(
            self._refresh_live_parallel_state()
            if self._live_brain_v3_enabled or self._live_parallel_warmer_v2_enabled
            else self._refresh_live_prepared_context(),
            name=f"live-preparation-{self._session_id}",
        )
        self._track_background_task(task)

    def _schedule_live_summary_refresh(self) -> None:
        self._schedule_live_preparation_refresh()

    def _get_raw_live_turn_window(self, limit: int = 5) -> list[dict[str, Any]]:
        source_limit = max(limit * 3, 10)
        tracker = getattr(self._pipeline, "conversation_tracker", None)
        tracker_reference_window: list[dict[str, Any]] = []

        def _active_window(turn_window: list[dict[str, Any]]) -> list[dict[str, Any]]:
            active_turns, _ = select_realtime_active_turn_window(
                turn_window,
                idle_close_sec=self._live_interviewer_block_gap_sec,
                selected_turn_limit=source_limit,
            )
            return _normalize_live_turn_window(active_turns, limit=limit)

        if tracker is not None:
            raw_reference_turns = tracker.get_last_n_turns(limit=source_limit)
            tracker_reference_window = self._augment_live_turn_window_with_recent_tail(
                raw_reference_turns,
                limit=source_limit,
            )
            tracker_reference_window = _normalize_live_turn_window(
                tracker_reference_window,
                limit=source_limit,
            )
            tracker_context_bundle = build_realtime_context_bundle(tracker, limit=source_limit)
            active_turn_count = int(tracker_context_bundle.get("active_turn_count") or 0)
            active_ask_state = tracker_context_bundle.get("active_ask_state") or {}
            last_answer_committed_at = None
            if isinstance(active_ask_state, dict):
                last_answer_committed_at = active_ask_state.get("last_answer_committed_at")
            else:
                last_answer_committed_at = getattr(active_ask_state, "last_answer_committed_at", None)
            newer_non_tracker_window = self._get_newer_non_tracker_live_turn_window(
                tracker_reference_window=tracker_reference_window,
                limit=limit,
                source_limit=source_limit,
                tracker=tracker,
            )
            if newer_non_tracker_window:
                return newer_non_tracker_window
            if active_turn_count > 0:
                return _active_window(
                    tracker_context_bundle.get("active_turns")
                    or tracker_context_bundle.get("turns")
                    or [],
                )
            if last_answer_committed_at is not None:
                return []

        fallback_window = self._build_non_tracker_live_turn_window(
            limit=limit,
            source_limit=source_limit,
            tracker=tracker,
        )
        if fallback_window:
            return _active_window(fallback_window)
        return []

    def _get_live_active_turn_window(
        self,
        limit: int = 5,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        source_limit = max(limit * 3, 10)
        tracker = getattr(self._pipeline, "conversation_tracker", None)
        tracker_context_bundle: dict[str, Any] = {}
        tracker_reference_window: list[dict[str, Any]] = []

        if tracker is not None:
            raw_reference_turns = tracker.get_last_n_turns(limit=source_limit)
            tracker_reference_window = self._augment_live_turn_window_with_recent_tail(
                raw_reference_turns,
                limit=source_limit,
            )
            tracker_reference_window = _normalize_live_turn_window(
                tracker_reference_window,
                limit=source_limit,
            )

        if tracker is not None:
            try:
                tracker_context_bundle = build_realtime_context_bundle(tracker, limit=source_limit) or {}
            except Exception as exc:
                print(
                    "[LIVE][BRAIN] tracker_window_failed "
                    f"session_id={self._session_id} error={exc}"
                )
                tracker_context_bundle = {}

            tracker_turns = (
                tracker_context_bundle.get("active_turns")
                or tracker_context_bundle.get("turns")
                or []
            )
            active_turn_window = _normalize_live_turn_window(tracker_turns, limit=limit)

            active_ask_state = tracker_context_bundle.get("active_ask_state") or {}
            boundary_closed = False
            if isinstance(active_ask_state, dict):
                boundary_closed = bool(
                    active_ask_state.get("last_active_ask_frozen_at") is not None
                    or active_ask_state.get("last_answer_committed_at") is not None
                    or str(active_ask_state.get("status") or "").strip().lower() == "closed"
                )
            newer_non_tracker_window = self._get_newer_non_tracker_active_turn_window(
                tracker_reference_window=tracker_reference_window,
                limit=limit,
                source_limit=source_limit,
                tracker=tracker,
            )
            if newer_non_tracker_window:
                return newer_non_tracker_window, tracker_context_bundle
            if active_turn_window:
                return active_turn_window, tracker_context_bundle
            if boundary_closed:
                return [], tracker_context_bundle

        raw_turn_window = self._get_raw_live_turn_window(limit=limit)
        if not raw_turn_window:
            return [], tracker_context_bundle

        resolved_turn_window, resolved_bundle = select_realtime_active_turn_window(
            raw_turn_window,
            idle_close_sec=self._live_interviewer_block_gap_sec,
            selected_turn_limit=source_limit,
        )
        if resolved_turn_window:
            return _normalize_live_turn_window(resolved_turn_window, limit=limit), resolved_bundle
        return _normalize_live_turn_window(raw_turn_window, limit=limit), resolved_bundle

    def _get_live_turn_window(self, limit: int = 5) -> list[dict[str, Any]]:
        active_turn_window, _ = self._get_live_active_turn_window(limit=limit)
        return _normalize_live_turn_window(active_turn_window, limit=limit)

    def _flush_pending_interviewer_candidate_for_silence(self) -> None:
        if self._interviewer_turn_candidate is None:
            return

        completed_text = self._complete_interviewer_turn_candidate(reason="silence_trigger_flush")
        if not completed_text:
            return

        interview_config = getattr(getattr(self._pipeline, "session_state", None), "interview_config", {}) or {}
        language = str(interview_config.get("language_preference") or "en").strip() or "en"
        self._ingest_completed_live_caption_turn(
            text=completed_text,
            event_time=self._last_interviewer_activity_at or time.time(),
            language=language,
            provider_metadata={"event_type": "silence_trigger_flush"},
        )

    def _cache_live_prepared_context(
        self,
        *,
        tracker: Any,
        prepared_context: LivePreparedContext,
    ) -> None:
        cached_prepared_context = tracker.get_live_prepared_context()
        cached_summary = tracker.get_live_ask_summary()
        version = 1
        if cached_prepared_context is not None:
            version = cached_prepared_context.version + 1
        elif cached_summary is not None:
            version = cached_summary.version + 1

        prepared_context = _canonicalize_live_prepared_context(prepared_context) or prepared_context
        request_payload = copy.deepcopy(prepared_context.request_payload or {})
        if request_payload:
            canonical_history = (
                prepared_context.sanitized_turns
                if prepared_context.sanitized_turns
                else prepared_context.raw_turns
            )
            request_payload["question"] = (
                prepared_context.question_text
                or prepared_context.resolved_question
                or prepared_context.primary_ask
            )
            request_payload["conversation_history"] = canonical_history
            request_payload["history_count"] = len(canonical_history)
            request_payload["preserve_question_text"] = True

        prepared_context = prepared_context.model_copy(
            update={
                "version": version,
                "request_payload": request_payload,
            }
        )
        summary_kwargs = {
            "source_turns": prepared_context.sanitized_turns,
            "turn_window_size": prepared_context.turn_window_size,
            "signature": prepared_context.signature,
            "primary_ask": prepared_context.primary_ask,
            "secondary_asks": prepared_context.secondary_asks,
            "ordered_focus": prepared_context.ordered_focus,
            "answer_family": prepared_context.answer_family,
            "answer_contract": prepared_context.answer_contract,
            "metrics_policy": prepared_context.metrics_policy,
            "opening_strategy": prepared_context.opening_strategy,
            "confidence": prepared_context.confidence,
            "version": version,
            "latency_ms": prepared_context.latency_ms,
            "fallback_used": prepared_context.fallback_used,
        }
        if prepared_context.ask_brief is not None:
            summary_kwargs["evidence_policy"] = prepared_context.ask_brief.evidence_policy
        summary = LiveAskSummary(**summary_kwargs)
        tracker.cache_live_ask_summary(summary)
        tracker.cache_live_prepared_context(prepared_context)
        if prepared_context.ask_brief is not None:
            tracker.cache_latest_ask_brief(
                primary_question=prepared_context.primary_ask,
                ask_brief=prepared_context.ask_brief,
            )
        print(
            "[LIVE][PREPARED] cached "
            f"session_id={self._session_id} "
            f"turns={prepared_context.turn_window_size} "
            f"effective_turn_count={prepared_context.effective_turn_count} "
            f"latest_turn_included={prepared_context.latest_turn_included} "
            f"version={summary.version} "
            f"plan_stage={prepared_context.plan_stage} "
            f"family={prepared_context.answer_family.value} "
            f"complexity={prepared_context.complexity_class.value} "
            f"shape={prepared_context.answer_shape.value} "
            f"planner_source={prepared_context.planner_source} "
            f"planner_model='{(prepared_context.planner_model or '')[:80]}' "
            f"confidence={prepared_context.confidence:.2f} "
            f"time_to_base_plan_ms={prepared_context.time_to_base_plan_ms} "
            f"time_to_semantic_plan_ms={prepared_context.time_to_semantic_plan_ms} "
            f"primary='{prepared_context.primary_ask[:180]}' "
            f"secondary={prepared_context.secondary_asks[:4]}"
        )

    def _schedule_live_semantic_refresh(
        self,
        *,
        planner: Any,
        tracker: Any,
        prepared_context: LivePreparedContext,
        interview_config: dict[str, Any],
    ) -> None:
        if (
            self._live_semantic_refresh_task is not None
            and not self._live_semantic_refresh_task.done()
            and self._live_semantic_refresh_signature
            and prepared_context.signature != self._live_semantic_refresh_signature
        ):
            print(
                "[LIVE][PREPARED] semantic_cancel_stale "
                f"session_id={self._session_id} "
                f"stale_signature='{self._live_semantic_refresh_signature[:120]}' "
                f"next_signature='{prepared_context.signature[:120]}'"
            )
            self._live_semantic_refresh_task.cancel()
            self._live_brain_last_status = "cancelled"
            self._live_brain_last_failure_reason = "stale_signature_replaced"

        if prepared_context.signature == self._live_semantic_refresh_signature:
            if self._live_semantic_refresh_task and not self._live_semantic_refresh_task.done():
                return

        self._live_semantic_refresh_signature = prepared_context.signature

        async def _run_semantic_refresh() -> None:
            brain_started = self._mark_live_brain_started(signature=prepared_context.signature)
            try:
                drafted = await self._run_live_brain_draft(
                    planner=planner,
                    prepared_context=prepared_context,
                    interview_config=interview_config,
                )
                if drafted is None:
                    self._mark_live_brain_finished(
                        started_at=brain_started,
                        status="failed",
                        failure_reason="draft_unavailable",
                    )
                    if not self._live_parallel_warmer_v2_enabled:
                        self._schedule_live_quality_refresh(
                            planner=planner,
                            tracker=tracker,
                            prepared_context=prepared_context,
                            interview_config=interview_config,
                        )
                    return
                latest_prepared_context = tracker.get_live_prepared_context()
                if latest_prepared_context is None:
                    self._mark_live_brain_finished(
                        started_at=brain_started,
                        status="failed",
                        failure_reason="prepared_context_missing",
                    )
                    return
                if latest_prepared_context.signature != prepared_context.signature:
                    print(
                        "[LIVE][PREPARED] semantic_skip_stale "
                        f"session_id={self._session_id} signature='{prepared_context.signature[:120]}' "
                        f"latest_signature='{latest_prepared_context.signature[:120]}'"
                    )
                    self._mark_live_brain_finished(
                        started_at=brain_started,
                        status="cancelled",
                        failure_reason="stale_result",
                    )
                    return
                self._cache_live_prepared_context(
                    tracker=tracker,
                    prepared_context=drafted,
                )
                self._mark_live_brain_finished(
                    started_at=brain_started,
                    status="completed",
                )
            except asyncio.CancelledError:
                self._mark_live_brain_finished(
                    started_at=brain_started,
                    status="cancelled",
                    failure_reason="task_cancelled",
                )
                return
            except Exception as e:
                self._mark_live_brain_finished(
                    started_at=brain_started,
                    status="failed",
                    failure_reason=type(e).__name__,
                )
                print(f"[LIVE][PREPARED] semantic_failed session_id={self._session_id} error={e}")

        task = asyncio.create_task(
            _run_semantic_refresh(),
            name=f"live-semantic-preparation-{self._session_id}",
        )
        self._live_semantic_refresh_task = task
        self._track_background_task(task)

    async def _await_live_semantic_refresh(
        self,
        *,
        signature: str,
        timeout_sec: Optional[float] = None,
    ) -> None:
        task = self._live_semantic_refresh_task
        if not signature or task is None or task.done():
            return
        if self._live_semantic_refresh_signature != signature:
            return

        wait_budget = timeout_sec if timeout_sec is not None else self._live_semantic_grace_sec
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=wait_budget)
            print(
                "[LIVE][PREPARED] semantic_wait_completed "
                f"session_id={self._session_id} "
                f"signature='{signature[:120]}' "
                f"wait_budget_sec={wait_budget:.2f}"
            )
        except asyncio.TimeoutError:
            print(
                "[LIVE][PREPARED] semantic_wait_timeout "
                f"session_id={self._session_id} "
                f"signature='{signature[:120]}' "
                f"wait_budget_sec={wait_budget:.2f}"
            )
        except asyncio.CancelledError:
            return
        except Exception as e:
            print(
                "[LIVE][PREPARED] semantic_wait_failed "
                f"session_id={self._session_id} error={e}"
            )

    def _get_live_quality_cached_response(
        self,
        *,
        signature_or_key: str,
        prepared_context: Optional[LivePreparedContext] = None,
    ) -> Optional[dict[str, Any]]:
        if self._live_parallel_warmer_v2_enabled:
            warm_result = self._get_live_warm_exact_result(question_key=signature_or_key)
            if warm_result is not None:
                return copy.deepcopy(warm_result.response)
        if (
            self._live_quality_cached_response is not None
            and signature_or_key
            and self._live_quality_cached_signature == signature_or_key
        ):
            return copy.deepcopy(self._live_quality_cached_response)
        return None

    def _get_live_related_quality_cached_response(
        self,
        *,
        prepared_context: Optional[LivePreparedContext],
    ) -> tuple[Optional[dict[str, Any]], str]:
        cached_context = self._live_quality_cached_context
        if prepared_context is None or cached_context is None or self._live_quality_cached_response is None:
            return None, ""
        delta_class = _classify_live_quality_delta(cached_context, prepared_context)
        if delta_class in {"same", "minor_refinement", "minor_extension"}:
            return copy.deepcopy(self._live_quality_cached_response), delta_class
        return None, delta_class

    async def _await_live_related_quality_refresh(
        self,
        *,
        prepared_context: Optional[LivePreparedContext],
        timeout_sec: Optional[float] = None,
    ) -> bool:
        task = self._live_quality_refresh_task
        refresh_context = self._live_quality_refresh_context
        if prepared_context is None or refresh_context is None or task is None or task.done():
            return False

        delta_class = _classify_live_quality_delta(refresh_context, prepared_context)
        if delta_class not in {"same", "minor_refinement", "minor_extension"}:
            return False

        wait_budget = self._resolve_live_quality_wait_budget(timeout_sec=timeout_sec)
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=wait_budget)
            print(
                "[LIVE][WRITER] prewarm_related_wait_completed "
                f"session_id={self._session_id} "
                f"delta_class={delta_class} "
                f"wait_budget_sec={wait_budget:.2f}"
            )
            return True
        except asyncio.TimeoutError:
            print(
                "[LIVE][WRITER] prewarm_related_wait_timeout "
                f"session_id={self._session_id} "
                f"delta_class={delta_class} "
                f"wait_budget_sec={wait_budget:.2f}"
            )
            return False
        except asyncio.CancelledError:
            return False
        except Exception as e:
            print(
                "[LIVE][WRITER] prewarm_related_wait_failed "
                f"session_id={self._session_id} error={e}"
            )
            return False

    async def _await_live_quality_refresh(
        self,
        *,
        signature_or_key: str,
        timeout_sec: Optional[float] = None,
    ) -> None:
        task = self._live_quality_refresh_task
        if not signature_or_key or task is None or task.done():
            return
        if self._live_quality_refresh_signature != signature_or_key:
            return

        wait_budget = self._resolve_live_quality_wait_budget(timeout_sec=timeout_sec)
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=wait_budget)
            print(
                "[LIVE][WRITER] prewarm_wait_completed "
                f"session_id={self._session_id} "
                f"quality_key='{signature_or_key[:120]}' "
                f"wait_budget_sec={wait_budget:.2f}"
            )
        except asyncio.TimeoutError:
            print(
                "[LIVE][WRITER] prewarm_wait_timeout "
                f"session_id={self._session_id} "
                f"quality_key='{signature_or_key[:120]}' "
                f"wait_budget_sec={wait_budget:.2f}"
            )
        except asyncio.CancelledError:
            return
        except Exception as e:
            print(
                "[LIVE][WRITER] prewarm_wait_failed "
                f"session_id={self._session_id} error={e}"
            )

    def _resolve_live_quality_wait_budget(
        self,
        *,
        timeout_sec: Optional[float] = None,
    ) -> float:
        if timeout_sec is not None:
            return timeout_sec

        wait_budget = self._live_quality_grace_sec
        task = self._live_quality_refresh_task
        started_at = self._live_quality_refresh_started_at
        if task is None or task.done() or started_at is None:
            return wait_budget

        elapsed_sec = perf_counter() - started_at
        if elapsed_sec >= 1.5:
            return max(wait_budget, self._live_quality_extended_grace_sec)
        return wait_budget

    def _get_live_warm_exact_result(self, *, question_key: str, signature: str = "") -> Optional[LiveWarmResult]:
        if not question_key:
            return None
        warm_result = self._live_warm_latest_result
        if (
            warm_result is not None
            and warm_result.success
            and warm_result.question_key == question_key
        ):
            return LiveWarmResult(
                checkpoint_id=warm_result.checkpoint_id,
                signature=warm_result.signature,
                question_key=warm_result.question_key,
                question_text=warm_result.question_text,
                response=copy.deepcopy(warm_result.response),
                started_at=warm_result.started_at,
                completed_at=warm_result.completed_at,
                success=warm_result.success,
            )
        return None

    def _get_live_warm_seed_result(
        self,
        *,
        question_text: str,
        question_key: str,
    ) -> Optional[LiveWarmResult]:
        if not question_text:
            return None
        warm_result = self._live_warm_latest_result
        if warm_result is None or not warm_result.success:
            return None
        if warm_result.question_key == question_key:
            return None
        if not _is_live_warm_seed_compatible(warm_result.question_text, question_text):
            return None
        return LiveWarmResult(
            checkpoint_id=warm_result.checkpoint_id,
            signature=warm_result.signature,
            question_key=warm_result.question_key,
            question_text=warm_result.question_text,
            response=copy.deepcopy(warm_result.response),
            started_at=warm_result.started_at,
            completed_at=warm_result.completed_at,
            success=warm_result.success,
        )

    async def _await_live_warm_exact_result(
        self,
        *,
        question_key: str,
        timeout_sec: Optional[float] = None,
    ) -> bool:
        if not question_key:
            return False
        task = self._live_warm_inflight_task
        checkpoint = self._live_warm_inflight_checkpoint
        if task is None or checkpoint is None or task.done():
            return False
        if checkpoint.question_key != question_key:
            return False

        wait_budget = timeout_sec if timeout_sec is not None else self._live_warm_wait_sec
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=wait_budget)
            return True
        except asyncio.TimeoutError:
            return False
        except asyncio.CancelledError:
            return False
        except Exception:
            return False

    async def _await_live_warm_checkpoint(
        self,
        *,
        checkpoint_id: str,
        timeout_sec: Optional[float] = None,
    ) -> bool:
        if not checkpoint_id:
            return False
        task = self._live_warm_inflight_task
        checkpoint = self._live_warm_inflight_checkpoint
        if task is None or checkpoint is None or task.done():
            return False
        if checkpoint.checkpoint_id != checkpoint_id:
            return False

        wait_budget = timeout_sec if timeout_sec is not None else self._live_warm_wait_sec
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=wait_budget)
            return True
        except asyncio.TimeoutError:
            return False
        except asyncio.CancelledError:
            return False
        except Exception:
            return False

    def _schedule_live_parallel_warm_from_snapshot(
        self,
        *,
        snapshot: LiveFrozenSnapshot,
        interview_config: dict[str, Any],
    ) -> None:
        if not self._live_parallel_warmer_v2_enabled:
            return
        prepared_context = snapshot.prepared_context
        if prepared_context is None or not snapshot.question_key or not snapshot.question_text:
            return

        current_result = self._live_warm_latest_result
        if (
            current_result is not None
            and current_result.success
            and current_result.question_key == snapshot.question_key
        ):
            return

        current_checkpoint = self._live_warm_inflight_checkpoint
        if (
            current_checkpoint is not None
            and self._live_warm_inflight_task is not None
            and not self._live_warm_inflight_task.done()
        ):
            if current_checkpoint.question_key == snapshot.question_key:
                return
            if _is_live_warm_seed_compatible(current_checkpoint.question_text, snapshot.question_text):
                return
            self._live_warm_inflight_task.cancel()

        parent_checkpoint_id = None
        if current_checkpoint is not None:
            parent_checkpoint_id = current_checkpoint.checkpoint_id
        elif current_result is not None:
            parent_checkpoint_id = current_result.checkpoint_id

        checkpoint = LiveWarmCheckpoint(
            checkpoint_id=snapshot.checkpoint_id or uuid.uuid4().hex,
            parent_checkpoint_id=parent_checkpoint_id,
            signature=snapshot.signature,
            question_key=snapshot.question_key,
            question_text=snapshot.question_text,
            conversation_history=copy.deepcopy(snapshot.conversation_history),
            prepared_context=prepared_context,
            created_at=datetime.utcnow(),
            source_generation=self._latest_interviewer_generation,
        )
        self._live_warm_inflight_checkpoint = checkpoint
        self._live_quality_refresh_signature = checkpoint.question_key
        self._live_quality_refresh_context = prepared_context
        self._live_quality_refresh_started_at = perf_counter()

        async def _run_live_warm_checkpoint() -> None:
            started_at = datetime.utcnow()
            try:
                response = await _suggest_live_prepared_response(
                    websocket=self._websocket,
                    session_id=self._session_id,
                    interview_config=interview_config,
                    question_text=checkpoint.question_text,
                    conversation_history=checkpoint.conversation_history,
                    live_prepared_context=checkpoint.prepared_context,
                )
                if not response.get("success"):
                    return
                if (
                    self._live_warm_inflight_checkpoint is None
                    or self._live_warm_inflight_checkpoint.checkpoint_id != checkpoint.checkpoint_id
                ):
                    return
                warm_result = LiveWarmResult(
                    checkpoint_id=checkpoint.checkpoint_id,
                    signature=checkpoint.signature,
                    question_key=checkpoint.question_key,
                    question_text=checkpoint.question_text,
                    response=copy.deepcopy(response),
                    started_at=started_at,
                    completed_at=datetime.utcnow(),
                    success=True,
                )
                self._live_warm_latest_result = warm_result
                self._live_quality_cached_signature = checkpoint.question_key
                self._live_quality_cached_response = copy.deepcopy(response)
                self._live_quality_cached_context = checkpoint.prepared_context
            except asyncio.CancelledError:
                return
            except Exception as e:
                print(
                    "[LIVE][WARM] checkpoint_failed "
                    f"session_id={self._session_id} "
                    f"checkpoint_id={checkpoint.checkpoint_id} error={e}"
                )
            finally:
                if self._live_warm_inflight_task is asyncio.current_task():
                    self._live_warm_inflight_checkpoint = None
                    self._live_quality_refresh_context = None
                    self._live_quality_refresh_started_at = None

        task = asyncio.create_task(
            _run_live_warm_checkpoint(),
            name=f"live-quality-warmer-v2-{self._session_id}",
        )
        self._live_warm_inflight_task = task
        self._live_quality_refresh_task = task
        self._track_background_task(task)

    def _build_live_brain_snapshot_v3(self, *, limit: int = 5) -> Optional[BrainSnapshot]:
        # The brain should think over the same consolidated conversation history
        # that Capture preserves and Emit will later send downstream.
        raw_turn_window, _ = self._get_live_active_turn_window(limit=limit)
        if not raw_turn_window:
            return None
        turn_window = _normalize_live_turn_window(raw_turn_window, limit=limit)
        snapshot_text = _build_live_brain_snapshot_text(turn_window)
        if not snapshot_text:
            return None
        snapshot_hash = _build_live_brain_snapshot_hash(turn_window)
        return BrainSnapshot(
            session_id=self._session_id,
            utterance_id=f"{self._session_id}:{self._completed_interviewer_turn_count}",
            revision_id=max(1, self._latest_interviewer_generation),
            snapshot_text=snapshot_text,
            conversation_history=turn_window,
            snapshot_hash=snapshot_hash,
            timestamp=datetime.utcnow(),
        )

    async def _compute_live_brain_plan_v3(
        self,
        *,
        brain_snapshot: BrainSnapshot,
        interview_config: dict[str, Any],
        force_stable: bool = False,
        immediate_safe_fallback: bool = False,
    ) -> tuple[BrainPlan, CompactEvidencePack]:
        can_use_cached_plan = (
            self._latest_brain_snapshot_v3 is not None
            and self._latest_brain_plan_v3 is not None
            and self._latest_brain_snapshot_v3.snapshot_hash == brain_snapshot.snapshot_hash
            and self._latest_brain_snapshot_v3.revision_id == brain_snapshot.revision_id
        )
        if can_use_cached_plan:
            cached_plan = self._normalize_live_brain_plan_for_active_route(self._latest_brain_plan_v3)
            cached_recovery_draft = str(self._latest_brain_recovery_draft_v3 or "")
            if force_stable and self._brain_plan_completeness_rank(cached_plan) < 3:
                can_use_cached_plan = False
            else:
                if force_stable and cached_plan.stability_state != "stable":
                    cached_plan = cached_plan.model_copy(update={"stability_state": "stable"})
                    self._latest_brain_plan_v3 = cached_plan
                    self._latest_stable_brain_plan_v3 = cached_plan
                    self._latest_stable_brain_recovery_draft_v3 = cached_recovery_draft
                evidence_pack = self._latest_compact_evidence_pack_v3 or self._live_evidence_packer_v3.pack(
                    plan=cached_plan,
                    interview_config=interview_config,
                )
                self._latest_compact_evidence_pack_v3 = evidence_pack
                self._latest_brain_recovery_draft_v3 = cached_recovery_draft
                return cached_plan, evidence_pack

        brain_started = self._mark_live_brain_started(signature=brain_snapshot.snapshot_hash)
        previous_plan = self._latest_brain_plan_v3
        if previous_plan is not None and previous_plan.revision_id != brain_snapshot.revision_id:
            previous_plan = None
        try:
            if immediate_safe_fallback:
                plan = self._live_brain_service_v3.safe_plan(
                    snapshot=brain_snapshot,
                    interview_config=interview_config,
                    reasoning_summary=(
                        "Live brain used immediate safe fallback at freeze to avoid extra silence latency."
                    ),
                )
                self._live_brain_last_llm_failure_kind = "freeze_immediate_safe_fallback"
            else:
                plan = await self._live_brain_service_v3.plan(
                    snapshot=brain_snapshot,
                    interview_config=interview_config,
                    previous_plan=previous_plan,
                )
                self._live_brain_last_llm_failure_kind = self._live_brain_service_v3.last_llm_failure_kind or ""
            recovery_draft = str(plan.draft_answer or "")
            reusable_stable_plan = self._latest_stable_brain_plan_v3
            if reusable_stable_plan is not None and reusable_stable_plan.revision_id != brain_snapshot.revision_id:
                reusable_stable_plan = None
            if (
                reusable_stable_plan is not None
                and str(plan.plan_source or "").strip().lower() == "safe_fallback"
                and str(reusable_stable_plan.plan_source or "").strip().lower() == "llm_fast"
                and _is_cached_stable_brain_plan_compatible(
                    reusable_stable_plan,
                    plan,
                    brain_snapshot.snapshot_text,
                )
            ):
                plan = reusable_stable_plan.model_copy(
                    update={
                        "utterance_id": brain_snapshot.utterance_id,
                        "revision_id": brain_snapshot.revision_id,
                        "snapshot_hash": brain_snapshot.snapshot_hash,
                        "generated_at": brain_snapshot.timestamp,
                        "stability_state": "stable",
                        "plan_source": "cached_stable",
                        "serve_mode": (
                            "finalize_from_draft"
                            if str(reusable_stable_plan.draft_answer or "").strip()
                            else "finalize_from_plan"
                        ),
                    }
                )
                recovery_draft = str(self._latest_stable_brain_recovery_draft_v3 or recovery_draft)
            plan = self._normalize_live_brain_plan_for_active_route(plan)
            now = perf_counter()
            equivalent = LiveBrainService.plans_equivalent(previous_plan, plan)
            if equivalent:
                self._brain_plan_repeat_count_v3 += 1
            else:
                self._brain_plan_repeat_count_v3 = 1
                self._brain_plan_changed_at_v3 = now

            stability_state = "draft"
            if self._brain_plan_repeat_count_v3 >= 2:
                stability_state = "stable_candidate"
            quiet_sec = self._live_brain_service_v3.config.stable_quiet_ms / 1000.0
            if force_stable or (
                self._brain_plan_changed_at_v3 is not None
                and (now - self._brain_plan_changed_at_v3) >= quiet_sec
            ):
                stability_state = "stable"

            serve_mode = plan.serve_mode
            if serve_mode == "direct_brain":
                serve_mode = "finalize_from_draft" if str(plan.draft_answer or "").strip() else "finalize_from_plan"

            plan = plan.model_copy(
                update={
                    "stability_state": stability_state,
                    "serve_mode": "finalize_from_plan",
                }
            )
            evidence_pack = self._live_evidence_packer_v3.pack(
                plan=plan,
                interview_config=interview_config,
            )

            self._latest_brain_snapshot_v3 = brain_snapshot
            self._latest_brain_plan_v3 = plan
            self._latest_brain_recovery_draft_v3 = recovery_draft
            if plan.stability_state in {"stable_candidate", "stable"} and str(plan.plan_source or "").strip().lower() == "llm_fast":
                self._latest_stable_brain_plan_v3 = plan
                self._latest_stable_brain_recovery_draft_v3 = recovery_draft
            self._latest_compact_evidence_pack_v3 = evidence_pack
            self._latest_brain_plan_hash_v3 = self._live_brain_service_v3.plan_hash(plan)
            self._latest_brain_question_key_v3 = _normalize_live_question_text(
                _build_live_question_from_brain_plan(plan, brain_snapshot.snapshot_text)
            ).lower()
            self._mark_live_brain_finished(started_at=brain_started, status="completed")
            return plan, evidence_pack
        except Exception as e:
            self._live_brain_last_llm_failure_kind = self._live_brain_service_v3.last_llm_failure_kind or ""
            self._mark_live_brain_finished(
                started_at=brain_started,
                status="failed",
                failure_reason=type(e).__name__,
            )
            raise

    def _get_live_brain_warm_result_for_plan_hash(
        self,
        *,
        plan_hash: str,
        include_failed: bool = False,
    ) -> Optional[LiveBrainWarmResult]:
        if not plan_hash:
            return None
        result = self._brain_warm_latest_result_v3
        if result is None or result.plan_hash != plan_hash:
            return None
        if not include_failed and not result.success:
            return None
        return LiveBrainWarmResult(
            checkpoint_id=result.checkpoint_id,
            plan_hash=result.plan_hash,
            question_key=result.question_key,
            question_text=result.question_text,
            brain_plan=result.brain_plan,
            response=copy.deepcopy(result.response),
            started_at=result.started_at,
            completed_at=result.completed_at,
            success=result.success,
        )

    def _get_live_brain_warm_exact_result(self, *, plan_hash: str) -> Optional[LiveBrainWarmResult]:
        return self._get_live_brain_warm_result_for_plan_hash(
            plan_hash=plan_hash,
            include_failed=False,
        )

    def _get_live_brain_warm_seed_result(
        self,
        *,
        target_plan: Optional[BrainPlan],
    ) -> Optional[LiveBrainWarmResult]:
        result = self._brain_warm_latest_result_v3
        if result is None or not result.success:
            return None
        if not _are_brain_plans_seed_compatible(result.brain_plan, target_plan):
            return None
        return LiveBrainWarmResult(
            checkpoint_id=result.checkpoint_id,
            plan_hash=result.plan_hash,
            question_key=result.question_key,
            question_text=result.question_text,
            brain_plan=result.brain_plan,
            response=copy.deepcopy(result.response),
            started_at=result.started_at,
            completed_at=result.completed_at,
            success=result.success,
        )

    async def _await_live_brain_warm_exact_result(
        self,
        *,
        plan_hash: str,
        timeout_sec: Optional[float] = None,
    ) -> None:
        task = self._brain_warm_inflight_task_v3
        checkpoint = self._brain_warm_inflight_checkpoint_v3
        if (
            not plan_hash
            or task is None
            or task.done()
            or checkpoint is None
            or checkpoint.plan_hash != plan_hash
        ):
            return
        wait_budget = timeout_sec if timeout_sec is not None else self._live_warm_wait_sec
        with contextlib.suppress(asyncio.TimeoutError, asyncio.CancelledError, Exception):
            await asyncio.wait_for(asyncio.shield(task), timeout=wait_budget)

    async def _await_live_brain_warm_checkpoint(
        self,
        *,
        checkpoint_id: str,
        timeout_sec: Optional[float] = None,
    ) -> None:
        task = self._brain_warm_inflight_task_v3
        checkpoint = self._brain_warm_inflight_checkpoint_v3
        if (
            not checkpoint_id
            or task is None
            or task.done()
            or checkpoint is None
            or checkpoint.checkpoint_id != checkpoint_id
        ):
            return
        wait_budget = timeout_sec if timeout_sec is not None else self._live_warm_wait_sec
        with contextlib.suppress(asyncio.TimeoutError, asyncio.CancelledError, Exception):
            await asyncio.wait_for(asyncio.shield(task), timeout=wait_budget)

    def _schedule_live_brain_warm_from_plan(
        self,
        *,
        brain_snapshot: BrainSnapshot,
        brain_plan: BrainPlan,
        evidence_pack: CompactEvidencePack,
        interview_config: dict[str, Any],
    ) -> None:
        if not self._live_emit_prewarm_enabled:
            return
        brain_plan = self._normalize_live_brain_plan_for_active_route(brain_plan)
        plan_source = str(brain_plan.plan_source or "").strip().lower()
        if plan_source not in {"llm_fast", "safe_fallback", "cached_stable"}:
            return
        if str(brain_plan.question_completeness or "").strip().lower() != "complete":
            return
        if not list(brain_plan.ordered_asks or []):
            return

        plan_hash = self._live_brain_service_v3.plan_hash(brain_plan)
        question_text = _build_live_question_from_brain_plan(brain_plan, brain_snapshot.snapshot_text)
        question_key = _normalize_live_question_text(question_text).lower()

        if plan_hash in self._brain_warm_attempted_plan_hashes_v3:
            return
        if self._get_live_brain_warm_exact_result(plan_hash=plan_hash) is not None:
            return

        if (
            self._brain_warm_schedule_task_v3 is not None
            and not self._brain_warm_schedule_task_v3.done()
            and self._brain_warm_scheduled_plan_hash_v3 == plan_hash
        ):
            return

        if (
            self._brain_warm_inflight_checkpoint_v3 is not None
            and self._brain_warm_inflight_task_v3 is not None
            and not self._brain_warm_inflight_task_v3.done()
        ):
            if self._brain_warm_inflight_checkpoint_v3.plan_hash == plan_hash:
                return
            return

        self._cancel_live_brain_warm_schedule()

        checkpoint = LiveBrainWarmCheckpoint(
            checkpoint_id=uuid.uuid4().hex,
            parent_checkpoint_id=self._brain_warm_inflight_checkpoint_v3.checkpoint_id
            if self._brain_warm_inflight_checkpoint_v3 is not None
            else None,
            plan_hash=plan_hash,
            question_key=question_key,
            question_text=question_text,
            brain_plan=brain_plan,
            compact_evidence_pack=evidence_pack,
            conversation_history=copy.deepcopy(brain_snapshot.conversation_history),
            created_at=datetime.utcnow(),
            source_revision_id=brain_snapshot.revision_id,
        )
        self._brain_warm_scheduled_plan_hash_v3 = plan_hash

        async def _schedule_late_warm() -> None:
            try:
                remaining_quiet_sec = self._live_emit_late_prewarm_quiet_sec - (
                    self._interviewer_activity_age_sec() or 0.0
                )
                if remaining_quiet_sec > 0:
                    await asyncio.sleep(remaining_quiet_sec)
                if self._hard_silence_is_satisfied():
                    return
                if (self._interviewer_activity_age_sec() or 0.0) < self._live_emit_late_prewarm_quiet_sec:
                    return
                if self._latest_brain_plan_hash_v3 and self._latest_brain_plan_hash_v3 != plan_hash:
                    return
                if (
                    self._brain_warm_inflight_task_v3 is not None
                    and not self._brain_warm_inflight_task_v3.done()
                ):
                    return
                self._brain_warm_attempted_plan_hashes_v3.add(plan_hash)
                self._emit_prewarm_started_before_silence = True
                self._emit_prewarm_count_before_silence += 1
                self._emit_calls_before_silence += 1
                self._brain_warm_inflight_checkpoint_v3 = checkpoint

                async def _run_brain_warm_checkpoint() -> None:
                    started_at = datetime.utcnow()
                    try:
                        response = await self._live_finalizer_v3.finalize(
                            plan=brain_plan,
                            evidence_pack=evidence_pack,
                            question_text=question_text,
                            conversation_history=brain_snapshot.conversation_history,
                            interview_config=interview_config,
                            working_draft="",
                            strict_emit_only=True,
                            timeout_override_sec=self._live_emit_timeout_for_plan(brain_plan),
                        )
                        metadata = response.get("metadata") or {}
                        if (
                            self._brain_warm_inflight_checkpoint_v3 is None
                            or self._brain_warm_inflight_checkpoint_v3.checkpoint_id != checkpoint.checkpoint_id
                        ):
                            return
                        self._brain_warm_latest_result_v3 = LiveBrainWarmResult(
                            checkpoint_id=checkpoint.checkpoint_id,
                            plan_hash=checkpoint.plan_hash,
                            question_key=checkpoint.question_key,
                            question_text=checkpoint.question_text,
                            brain_plan=brain_plan,
                            response=copy.deepcopy(response),
                            started_at=started_at,
                            completed_at=datetime.utcnow(),
                            success=metadata.get("finalizer_fallback_kind") != "explicit_failure",
                        )
                    except asyncio.CancelledError:
                        return
                    except Exception as e:
                        print(
                            "[LIVE][BRAIN][WARM] failed "
                            f"session_id={self._session_id} plan_hash='{plan_hash[:32]}' error={e}"
                        )
                    finally:
                        if self._brain_warm_inflight_task_v3 is asyncio.current_task():
                            self._brain_warm_inflight_checkpoint_v3 = None

                task = asyncio.create_task(
                    _run_brain_warm_checkpoint(),
                    name=f"live-brain-warm-{self._session_id}",
                )
                self._brain_warm_inflight_task_v3 = task
                self._track_background_task(task)
            except asyncio.CancelledError:
                return
            finally:
                if self._brain_warm_schedule_task_v3 is asyncio.current_task():
                    self._brain_warm_schedule_task_v3 = None
                    self._brain_warm_scheduled_plan_hash_v3 = ""

        task = asyncio.create_task(
            _schedule_late_warm(),
            name=f"live-brain-warm-schedule-{self._session_id}",
        )
        self._brain_warm_schedule_task_v3 = task
        self._track_background_task(task)

    async def _refresh_live_brain_v3_state(self, *, refresh_reason: str = "parallel_refresh") -> None:
        brain_snapshot = self._build_live_brain_snapshot_v3(limit=5)
        if brain_snapshot is None:
            return
        should_refresh, semantic_reason = self._should_refresh_live_brain_v3(
            brain_snapshot=brain_snapshot,
        )
        final_readiness_refresh = refresh_reason == "final_readiness"
        refresh_reason_to_record = semantic_reason or refresh_reason
        self._live_brain_last_refresh_reason_v3 = refresh_reason_to_record
        if final_readiness_refresh and not should_refresh:
            should_refresh = not self._live_brain_plan_ready_for_snapshot_v3(
                brain_snapshot=brain_snapshot,
            )
            if should_refresh:
                refresh_reason_to_record = "final_readiness"
                self._live_brain_last_refresh_reason_v3 = refresh_reason_to_record
        if not should_refresh:
            interview_config = getattr(getattr(self._pipeline, "session_state", None), "interview_config", {}) or {}
            if self._latest_brain_plan_v3 is not None and self._latest_compact_evidence_pack_v3 is not None:
                self._schedule_live_brain_warm_from_plan(
                    brain_snapshot=brain_snapshot,
                    brain_plan=self._latest_brain_plan_v3,
                    evidence_pack=self._latest_compact_evidence_pack_v3,
                    interview_config=interview_config,
                )
            return
        interview_config = getattr(getattr(self._pipeline, "session_state", None), "interview_config", {}) or {}
        self._record_live_brain_semantic_revision(
            brain_snapshot=brain_snapshot,
            reason=refresh_reason_to_record,
        )
        try:
            brain_plan, evidence_pack = await self._compute_live_brain_plan_v3(
                brain_snapshot=brain_snapshot,
                interview_config=interview_config,
            )
        except Exception as e:
            print(
                "[LIVE][BRAIN][V3] refresh_failed "
                f"session_id={self._session_id} error={e}"
            )
            return
        self._brain_refresh_count_before_silence += 1
        if final_readiness_refresh and not self._hard_silence_is_satisfied():
            self._late_brain_refresh_completed_before_silence = True

        self._schedule_live_brain_warm_from_plan(
            brain_snapshot=brain_snapshot,
            brain_plan=brain_plan,
            evidence_pack=evidence_pack,
            interview_config=interview_config,
        )

    async def _refresh_live_parallel_state(self) -> None:
        if self._live_brain_v3_enabled:
            self._queue_live_brain_v3_refresh(reason="parallel_refresh")
            return
        await self._refresh_live_prepared_context()
        if not self._live_parallel_warmer_v2_enabled:
            return

        tracker = getattr(self._pipeline, "conversation_tracker", None)
        planner = getattr(self._pipeline, "live_question_planner", None)
        if planner is None:
            normalizer = getattr(self._pipeline, "ask_normalizer", None)
            planner = LiveQuestionPlanner(normalizer) if normalizer is not None else None
        interview_config = getattr(getattr(self._pipeline, "session_state", None), "interview_config", {}) or {}
        if tracker is None or planner is None:
            return

        snapshot = await self._build_live_frozen_snapshot(
            planner=planner,
            tracker=tracker,
            interview_config=interview_config,
        )
        if snapshot is None:
            return
        self._schedule_live_parallel_warm_from_snapshot(
            snapshot=snapshot,
            interview_config=interview_config,
        )

    def _live_question_needs_stabilization(
        self,
        *,
        planner: Any,
        question_text: str,
        prepared_context: Optional[LivePreparedContext],
    ) -> bool:
        def _planner_signal(method_name: str, candidate: str) -> Optional[bool]:
            method = getattr(planner, method_name, None)
            if not callable(method):
                return None
            try:
                result = method(candidate)
            except Exception:
                return None
            return result if isinstance(result, bool) else None

        candidates: list[str] = []
        if prepared_context is not None:
            candidates.extend(
                [
                    prepared_context.primary_ask,
                    *list(prepared_context.secondary_asks or []),
                ]
            )
        if not candidates:
            candidates.append(question_text)
            if prepared_context is not None and prepared_context.sanitized_turns:
                candidates.append(prepared_context.sanitized_turns[-1].get("text", ""))

        for raw_candidate in candidates:
            candidate = " ".join(str(raw_candidate or "").split()).strip()
            if not candidate:
                continue
            if _planner_signal("_needs_continuation", candidate) is True:
                return True
            if _planner_signal("_is_fragmentary", candidate) is True:
                if _planner_signal("_looks_like_direct_ask", candidate) is not True:
                    return True

        return False

    def _schedule_live_quality_refresh(
        self,
        *,
        planner: Any,
        tracker: Any,
        prepared_context: LivePreparedContext,
        interview_config: dict[str, Any],
    ) -> None:
        if prepared_context is None or not prepared_context.signature:
            return
        if str(prepared_context.draft_answer or "").strip():
            return
        if self._live_question_needs_stabilization(
            planner=planner,
            question_text=prepared_context.question_text,
            prepared_context=prepared_context,
        ):
            return

        quality_key = _build_live_quality_cache_key(prepared_context) or prepared_context.signature

        if (
            self._live_quality_cached_response is not None
            and self._live_quality_cached_signature == quality_key
        ):
            return

        if (
            self._live_quality_refresh_task is not None
            and not self._live_quality_refresh_task.done()
            and self._live_quality_refresh_signature
            and self._live_quality_refresh_signature != quality_key
        ):
            self._live_quality_refresh_task.cancel()

        if (
            self._live_quality_refresh_task is not None
            and not self._live_quality_refresh_task.done()
            and self._live_quality_refresh_signature == quality_key
        ):
            return

        self._live_quality_refresh_signature = quality_key
        self._live_quality_refresh_context = prepared_context
        self._live_quality_refresh_started_at = perf_counter()

        async def _run_live_quality_refresh() -> None:
            try:
                question_text = _build_live_question_from_prepared_context(
                    prepared_context,
                    prepared_context.question_text or prepared_context.resolved_question,
                )
                response = await _suggest_live_prepared_response(
                    websocket=self._websocket,
                    session_id=self._session_id,
                    interview_config=interview_config,
                    question_text=question_text,
                    conversation_history=(
                        prepared_context.sanitized_turns
                        if prepared_context.sanitized_turns
                        else prepared_context.raw_turns
                    ),
                    live_prepared_context=prepared_context,
                )
                latest_prepared_context = tracker.get_live_prepared_context() if tracker is not None else None
                latest_quality_key = _build_live_quality_cache_key(latest_prepared_context)
                if latest_prepared_context is None or latest_quality_key != quality_key:
                    print(
                        "[LIVE][WRITER] prewarm_skip_stale "
                        f"session_id={self._session_id} "
                        f"quality_key='{quality_key[:120]}'"
                    )
                    return
                if not response.get("success"):
                    print(
                        "[LIVE][WRITER] prewarm_failed "
                        f"session_id={self._session_id} "
                        f"quality_key='{quality_key[:120]}' "
                        f"error='{str(response.get('error') or '')[:160]}'"
                        )
                    return
                self._live_quality_cached_signature = quality_key
                self._live_quality_cached_response = copy.deepcopy(response)
                self._live_quality_cached_context = latest_prepared_context
                print(
                    "[LIVE][WRITER] prewarm_cached "
                    f"session_id={self._session_id} "
                    f"quality_key='{quality_key[:120]}'"
                )
            except asyncio.CancelledError:
                return
            except Exception as e:
                print(
                    "[LIVE][WRITER] prewarm_exception "
                    f"session_id={self._session_id} "
                    f"quality_key='{quality_key[:120]}' "
                    f"error={e}"
                )
            finally:
                if self._live_quality_refresh_task is asyncio.current_task():
                    self._live_quality_refresh_context = None
                    self._live_quality_refresh_started_at = None

        task = asyncio.create_task(
            _run_live_quality_refresh(),
            name=f"live-quality-prewarm-{self._session_id}",
        )
        self._live_quality_refresh_task = task
        self._track_background_task(task)

    async def _refresh_live_prepared_context(self) -> None:
        try:
            tracker = getattr(self._pipeline, "conversation_tracker", None)
            planner = getattr(self._pipeline, "live_question_planner", None)
            if planner is None:
                normalizer = getattr(self._pipeline, "ask_normalizer", None)
                planner = LiveQuestionPlanner(normalizer) if normalizer is not None else None
            if tracker is None or planner is None:
                return

            raw_turn_window, _ = self._get_live_active_turn_window(limit=5)
            if not raw_turn_window:
                return
            signature = planner.build_signature(raw_turn_window)
            interview_config = getattr(getattr(self._pipeline, "session_state", None), "interview_config", {}) or {}
            cached_prepared_context = tracker.get_live_prepared_context()
            if cached_prepared_context is not None and cached_prepared_context.signature == signature:
                print(
                    "[LIVE][PREPARED] cache_hit "
                    f"session_id={self._session_id} signature='{signature[:80]}'"
                )
                if not str(cached_prepared_context.draft_answer or "").strip():
                    if not self._live_parallel_warmer_v2_enabled:
                        self._schedule_live_quality_refresh(
                            planner=planner,
                            tracker=tracker,
                            prepared_context=cached_prepared_context,
                            interview_config=interview_config,
                        )
                    self._schedule_live_semantic_refresh(
                        planner=planner,
                        tracker=tracker,
                        prepared_context=cached_prepared_context,
                        interview_config=interview_config,
                    )
                return

            prepared_context = planner.prepare_base(
                session_id=self._session_id,
                raw_turns=raw_turn_window,
                interview_config=interview_config,
                mode=self._default_mode,
            )
            if prepared_context is None:
                return
            self._cache_live_prepared_context(
                tracker=tracker,
                prepared_context=prepared_context,
            )
            if not self._live_parallel_warmer_v2_enabled:
                self._schedule_live_quality_refresh(
                    planner=planner,
                    tracker=tracker,
                    prepared_context=prepared_context,
                    interview_config=interview_config,
                )
            self._schedule_live_semantic_refresh(
                planner=planner,
                tracker=tracker,
                prepared_context=prepared_context,
                interview_config=interview_config,
            )
        except Exception as e:
            print(f"[LIVE][PREPARED] cache_failed session_id={self._session_id} error={e}")

    async def _refresh_live_ask_summary(self) -> None:
        await self._refresh_live_prepared_context()

    def _build_live_v3_response_payload(
        self,
        *,
        snapshot: LiveFrozenSnapshot,
        interview_config: dict[str, Any],
        final_result: dict[str, Any],
        path_used: str,
        direct_brain_served: bool = False,
    ) -> dict[str, Any]:
        brain_plan = snapshot.brain_plan
        evidence_pack = snapshot.compact_evidence_pack
        question_text = snapshot.question_text
        confidence = float(final_result.get("confidence") or (brain_plan.confidence if brain_plan is not None else 0.78) or 0.78)
        raw_full_response = str(final_result.get("full_response") or "").replace("\r\n", "\n").replace("\r", "\n")
        full_response_paragraphs = [
            " ".join(paragraph.split()).strip()
            for paragraph in re.split(r"\n\s*\n+", raw_full_response)
        ]
        full_response = "\n\n".join(
            paragraph for paragraph in full_response_paragraphs if paragraph
        ).strip()
        bullets = list(final_result.get("bullets") or _draft_answer_to_bullets(full_response, limit=max(2, min(len(list(brain_plan.ordered_asks or [])) if brain_plan is not None else 1, 4))))
        style_id = str(interview_config.get("style_id") or interview_config.get("response_style") or "professional")
        language = str(interview_config.get("language_preference") or "en").strip().lower() or "en"
        quality_score = max(0.75, confidence)
        metadata = final_result.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        fallback_used = bool(
            metadata.get("deterministic_fallback")
            or (brain_plan is not None and str(brain_plan.plan_source or "").strip().lower() != "llm_fast")
        )

        normalized_primary = None
        normalized_secondary: list[str] = []
        asks_in_order: list[str] = []
        if brain_plan is not None:
            asks_in_order = list(brain_plan.ordered_asks or [])
            if asks_in_order:
                normalized_primary = asks_in_order[0]
                normalized_secondary = asks_in_order[1:]

        return {
            "success": True,
            "mode": self._default_mode,
            "resolved_mode": self._default_mode,
            "mode_source": "live_brain_v4",
            "suggestion_id": self._session_id or str(uuid.uuid4()),
            "full_response": full_response,
            "bullets": bullets,
            "confidence": confidence,
            "quality_score": quality_score,
            "suggestion": {
                "full_response": full_response,
                "suggestedAnswer": full_response,
                "bullets": bullets,
                "key_metrics": list(evidence_pack.supporting_metrics or []) if evidence_pack is not None else [],
                "keyMetrics": list(evidence_pack.supporting_metrics or []) if evidence_pack is not None else [],
                "confidence": confidence,
                "style": style_id,
                "questionType": "live_brain_v4",
                "questionMode": "brain_plan",
                "responseMode": "interview_answer",
                "isCompound": len(asks_in_order) > 1,
                "subQuestions": [{"text": ask, "priority": "must_answer", "weight": 1.0} for ask in asks_in_order],
                "underlyingIntent": [brain_plan.reasoning_summary] if brain_plan and brain_plan.reasoning_summary else [],
                "redFlags": [],
                "styleReason": brain_plan.reasoning_summary if brain_plan is not None else "",
                "whyMetricsRequired": bool(brain_plan is not None and brain_plan.metrics_policy == "required"),
                "normalizedFamily": "brain_v4",
                "normalizedPrimaryAsk": normalized_primary,
                "normalizedSecondaryAsks": normalized_secondary,
                "normalizedAnswerContract": brain_plan.answer_contract if brain_plan is not None else "general_direct",
                "normalizedMetricsPolicy": brain_plan.metrics_policy if brain_plan is not None else "avoid_unless_helpful",
                "normalizerConfidence": confidence,
                "normalizerLatencyMs": 0,
                "fallbackUsed": fallback_used,
                "quality_score": quality_score,
            },
            "language": {
                "detected": language,
                "confidence": 1.0,
            },
            "quality": {
                "passed": True,
                "score": quality_score,
                "issues": [],
            },
            "llm": {
                "provider": metadata.get("provider"),
                "model": metadata.get("model"),
            },
            "latency_ms": int(final_result.get("latency_ms") or 0),
            "candidate": ((interview_config.get("candidate") or {}).get("name") or "Candidato"),
            "company": ((interview_config.get("company") or {}).get("companyName") or (interview_config.get("company") or {}).get("name") or "Empresa"),
            "debug": {
                "question": question_text,
                "resolved_question": brain_plan.resolved_question if brain_plan is not None else question_text,
                "primary_ask": normalized_primary,
                "secondary_asks": normalized_secondary,
                "asks_in_order": asks_in_order,
                "answer_focus": "Answer the interviewer asks in the order decided by the live brain.",
                "answer_style_guidance": (
                    f"Contract={brain_plan.answer_contract}; shape={brain_plan.response_shape}; "
                    f"directness={brain_plan.directness}; target_length={brain_plan.target_length}; "
                    f"metrics={brain_plan.metrics_policy}"
                    if brain_plan is not None
                    else None
                ),
                "literal_question": brain_plan.literal_question if brain_plan is not None else question_text,
                "contextualized_question": (
                    brain_plan.contextualized_question
                    if brain_plan is not None and str(brain_plan.contextualized_question or "").strip()
                    else question_text
                ),
                "draft_answer": brain_plan.draft_answer if brain_plan is not None else "",
                "brain_contract": {
                    "literal_question": brain_plan.literal_question if brain_plan is not None else question_text,
                    "contextualized_question": (
                        brain_plan.contextualized_question
                        if brain_plan is not None and str(brain_plan.contextualized_question or "").strip()
                        else question_text
                    ),
                    "resolved_question": brain_plan.resolved_question if brain_plan is not None else question_text,
                    "asks_in_order": asks_in_order,
                    "coverage_points": list(brain_plan.coverage_points or []) if brain_plan is not None else [],
                    "ask_intents": [item.model_dump(mode="json") for item in list(brain_plan.ask_intents or [])] if brain_plan is not None else [],
                    "interviewer_need": brain_plan.interviewer_need.model_dump(mode="json") if brain_plan is not None else None,
                    "context_focus": list(brain_plan.context_focus or []) if brain_plan is not None else [],
                    "response_requirement": brain_plan.response_requirement.model_dump(mode="json") if brain_plan is not None else None,
                    "answer_contract": brain_plan.answer_contract if brain_plan is not None else None,
                    "delivery_instructions": list(brain_plan.delivery_instructions or []) if brain_plan is not None else [],
                    "serve_mode": brain_plan.serve_mode if brain_plan is not None else None,
                    "confidence": brain_plan.confidence if brain_plan is not None else None,
                },
                "semantic_blocks_window": snapshot.conversation_history,
                "request_payload": snapshot.request_payload,
                "signature": snapshot.signature,
                "plan_stage": "brain_v4",
                "planner_source": "brain_v4",
                "planner_provider": "fast",
                "planner_model": metadata.get("brain_model"),
                "planner_reasoning_summary": brain_plan.reasoning_summary if brain_plan is not None else None,
                "planner_confidence": brain_plan.confidence if brain_plan is not None else None,
                "path_used": path_used,
                "fallback_used": fallback_used,
                "brain_plan_revision": brain_plan.revision_id if brain_plan is not None else None,
                "brain_plan_confidence": brain_plan.confidence if brain_plan is not None else None,
                "brain_plan_stability": brain_plan.stability_state if brain_plan is not None else None,
                "brain_plan_serve_mode": brain_plan.serve_mode if brain_plan is not None else None,
                "brain_plan_hash": snapshot.plan_hash,
                "brain_plan_source": brain_plan.plan_source if brain_plan is not None else None,
                "brain_response_shape": brain_plan.response_shape if brain_plan is not None else None,
                "brain_answer_contract": brain_plan.answer_contract if brain_plan is not None else None,
                "brain_delivery_instructions": list(brain_plan.delivery_instructions or []) if brain_plan is not None else [],
                "brain_ask_intents": [item.model_dump(mode="json") for item in list(brain_plan.ask_intents or [])] if brain_plan is not None else [],
                "brain_interviewer_need": brain_plan.interviewer_need.model_dump(mode="json") if brain_plan is not None else None,
                "brain_context_focus": list(brain_plan.context_focus or []) if brain_plan is not None else [],
                "brain_response_requirement": brain_plan.response_requirement.model_dump(mode="json") if brain_plan is not None else None,
                "brain_evidence_depth": brain_plan.evidence_depth if brain_plan is not None else None,
                "brain_metrics_policy": brain_plan.metrics_policy if brain_plan is not None else None,
                "brain_company_context_policy": brain_plan.company_context_policy if brain_plan is not None else None,
                "brain_candidate_context_policy": brain_plan.candidate_context_policy if brain_plan is not None else None,
                "brain_llm_used": bool(
                    brain_plan is not None and str(brain_plan.plan_source or "").strip().lower() == "llm_fast"
                ),
                "brain_llm_timeout_ms": int(self._live_brain_service_v3.config.llm_timeout_sec * 1000),
                "question_completeness": brain_plan.question_completeness if brain_plan is not None else None,
                "raw_detected_asks": list(brain_plan.raw_detected_asks or []) if brain_plan is not None else [],
                "coverage_points": list(brain_plan.coverage_points or []) if brain_plan is not None else [],
                "dropped_noise_clauses": list(brain_plan.dropped_noise_clauses or []) if brain_plan is not None else [],
                "stable_plan_reused": bool(
                    brain_plan is not None and str(brain_plan.plan_source or "").strip().lower() == "cached_stable"
                ),
                "compact_evidence_ready": evidence_pack is not None,
                "compact_evidence_pack": evidence_pack.model_dump(mode="json") if evidence_pack is not None else None,
                "evidence_pack_mode": evidence_pack.mode if evidence_pack is not None else None,
                "snapshot_hash": snapshot.brain_snapshot.snapshot_hash if snapshot.brain_snapshot is not None else snapshot.signature,
                "normalized_family": "brain_v4",
                "normalized_primary_ask": normalized_primary,
                "normalized_secondary_asks": normalized_secondary,
                "normalized_answer_contract": brain_plan.answer_contract if brain_plan is not None else "general_direct",
                "normalized_metrics_policy": brain_plan.metrics_policy if brain_plan is not None else "avoid_unless_helpful",
                "normalizer_confidence": confidence,
                "normalizer_latency_ms": 0,
                "finalizer_fallback_kind": metadata.get("finalizer_fallback_kind"),
                "finalizer_llm_called": bool(metadata.get("llm_called")),
                "finalizer_provider": metadata.get("provider"),
                "finalizer_model": metadata.get("model"),
                "finalizer_configured_provider": metadata.get("configured_provider"),
                "finalizer_configured_model": metadata.get("configured_model"),
                "finalizer_primary_mode": metadata.get("finalizer_primary_mode"),
                "finalizer_primary_success": bool(metadata.get("finalizer_primary_success")),
                "finalizer_recovery_attempted": bool(metadata.get("finalizer_recovery_attempted")),
                "finalizer_recovery_kind": metadata.get("finalizer_recovery_kind"),
                "finalizer_recovery_success": bool(metadata.get("finalizer_recovery_success")),
                "finalizer_recovery_skipped_reason": metadata.get("finalizer_recovery_skipped_reason"),
                "recovery_applied": bool(metadata.get("finalizer_recovery_success")),
                "recovery_kind": metadata.get("finalizer_recovery_kind"),
                "recovery_draft_available": bool(
                    metadata.get("recovery_draft_available", snapshot.recovery_draft_available)
                ),
                "output_sanitizer_applied": bool(metadata.get("output_sanitizer_applied")),
                "silence_anchor_at_ms": self._silence_anchor_at_ms,
                "silence_anchor_source": self._silence_anchor_source,
                "completed_turn_processed_at_ms": self._completed_turn_processed_at_ms,
                "completed_turn_after_last_activity_ms": self._completed_turn_after_last_activity_ms,
                "silence_gate_scheduled_delay_ms": self._silence_gate_scheduled_delay_ms,
                "silence_gate_fired_at_ms": self._silence_gate_fired_at_ms,
                "late_brain_refresh_started_before_silence": self._late_brain_refresh_started_before_silence,
                "late_brain_refresh_completed_before_silence": self._late_brain_refresh_completed_before_silence,
                "brain_force_stable_at_freeze": self._brain_force_stable_at_freeze,
                "brain_refresh_waited_at_freeze_ms": self._brain_refresh_waited_at_freeze_ms,
                "brain_immediate_safe_fallback_at_freeze": self._brain_immediate_safe_fallback_at_freeze,
                "emit_started_at_ms": self._emit_started_at_ms,
                "emit_stream_started_at_ms": self._emit_stream_started_at_ms,
                "emit_first_chunk_ms": self._emit_first_chunk_ms,
                "emit_stream_completed_at_ms": self._emit_stream_completed_at_ms,
                "emit_stream_chunk_count": self._emit_stream_chunk_count,
                "emit_stream_partial_salvaged": self._emit_stream_partial_salvaged,
            },
        }

    @staticmethod
    def _build_live_llm_failure_notice(failure_kind: str) -> str:
        normalized = str(failure_kind or "").strip().lower()
        runtime_config = load_runtime_config_payload() or {}
        runtime_llm = runtime_config.get("llm") if isinstance(runtime_config.get("llm"), dict) else {}
        configured_provider = str(runtime_llm.get("provider") or "").strip().lower()
        provider_label = "Anthropic" if configured_provider == "anthropic" else "the configured LLM"
        if normalized == "api_key_missing":
            return (
                f"I could not generate a reliable answer because the {provider_label} API key is missing in Settings. "
                "Open Settings, add the key, and save it again."
            )
        if normalized == "authenticationerror":
            return (
                f"I could not generate a reliable answer because {provider_label} rejected the configured API key. "
                "Open Settings, re-enter the key, and save it again."
            )
        if normalized in {"api_connectionerror", "apiconnectionerror"}:
            return (
                f"I could not generate a reliable answer because {provider_label} could not be reached from this machine. "
                "Check network access and try again."
            )
        return "I could not generate a reliable answer because the live brain planner failed."

    async def _build_live_frozen_snapshot_v3(
        self,
        *,
        interview_config: dict[str, Any],
    ) -> Optional[LiveFrozenSnapshot]:
        raw_turn_window, tracker_context_bundle = self._get_live_active_turn_window(limit=5)
        if not raw_turn_window:
            return None
        turn_window = _normalize_live_turn_window(raw_turn_window, limit=5)
        raw_context_bundle = (
            tracker_context_bundle
            if tracker_context_bundle
            else resolve_realtime_context_bundle(turn_window)
        )
        brain_snapshot = self._build_live_brain_snapshot_v3(limit=5)
        if brain_snapshot is None:
            return None

        prior_snapshot = self._latest_brain_snapshot_v3
        cache_hit = bool(
            prior_snapshot is not None and prior_snapshot.snapshot_hash == brain_snapshot.snapshot_hash
        )
        brain_refresh_wait_ms = 0
        if (
            not self._live_brain_plan_ready_for_snapshot_v3(brain_snapshot=brain_snapshot)
            and self._live_brain_refresh_task_v3 is not None
            and not self._live_brain_refresh_task_v3.done()
            and self._live_brain_refresh_active_signature_v3 == brain_snapshot.snapshot_hash
        ):
            brain_refresh_wait_ms = await self._await_live_brain_v3_refresh(
                snapshot_hash=brain_snapshot.snapshot_hash,
                timeout_sec=self._live_brain_freeze_wait_grace_sec,
            )
            prior_snapshot = self._latest_brain_snapshot_v3
            cache_hit = bool(
                prior_snapshot is not None and prior_snapshot.snapshot_hash == brain_snapshot.snapshot_hash
            )
        self._brain_refresh_waited_at_freeze_ms = brain_refresh_wait_ms
        use_immediate_safe_fallback = not self._live_brain_plan_ready_for_snapshot_v3(
            brain_snapshot=brain_snapshot,
        )
        self._brain_force_stable_at_freeze = use_immediate_safe_fallback
        self._brain_immediate_safe_fallback_at_freeze = use_immediate_safe_fallback
        brain_plan, evidence_pack = await self._compute_live_brain_plan_v3(
            brain_snapshot=brain_snapshot,
            interview_config=interview_config,
            force_stable=True,
            immediate_safe_fallback=use_immediate_safe_fallback,
        )
        recovery_draft = str(self._latest_brain_recovery_draft_v3 or "")
        question_text = _build_live_question_from_brain_plan(brain_plan, brain_snapshot.snapshot_text)
        question_key = _normalize_live_question_text(question_text).lower()
        max_words = int(interview_config.get("max_words") or brain_plan.target_length or 180)
        request_payload = {
            "question": question_text,
            "session_id": self._session_id,
            "candidate_profile": copy.deepcopy(
                interview_config.get("candidate_profile") or interview_config.get("candidate") or {}
            ),
            "company_info": copy.deepcopy(
                interview_config.get("company_info") or interview_config.get("company") or {}
            ),
            "target_company_info": copy.deepcopy(
                (
                    (interview_config.get("target_context") or interview_config.get("target") or {}).get("company")
                    if isinstance(interview_config.get("target_context") or interview_config.get("target") or {}, dict)
                    else {}
                )
            ),
            "target_role_info": copy.deepcopy(
                (
                    (interview_config.get("target_context") or interview_config.get("target") or {}).get("role")
                    if isinstance(interview_config.get("target_context") or interview_config.get("target") or {}, dict)
                    else {}
                )
            ),
            "interviewer_profile": copy.deepcopy(
                interview_config.get("interviewer_profile") or interview_config.get("interviewer") or {}
            ),
            "target_context": copy.deepcopy(
                interview_config.get("target_context") or interview_config.get("target") or {}
            ),
            "style_id": interview_config.get("style_id") or interview_config.get("response_style") or "professional",
            "language": interview_config.get("language_preference") or "en",
            "mode": self._default_mode,
            "history_count": len(brain_snapshot.conversation_history),
            "max_words": max_words,
            "interview_type": interview_config.get("interview_type"),
            "conversation_history": copy.deepcopy(brain_snapshot.conversation_history),
            "preserve_question_text": True,
        }
        if "profile_id" in interview_config:
            request_payload["profile_id"] = interview_config.get("profile_id")
        if "company_context_id" in interview_config:
            request_payload["company_context_id"] = interview_config.get("company_context_id")
        if "interviewer_context_id" in interview_config:
            request_payload["interviewer_context_id"] = interview_config.get("interviewer_context_id")

        compat_prepared_context = _build_compat_live_prepared_context_from_brain_plan(
            session_id=self._session_id,
            brain_snapshot=brain_snapshot,
            brain_plan=brain_plan,
            request_payload=request_payload,
        )
        return LiveFrozenSnapshot(
            raw_turn_window=raw_turn_window,
            turn_window=turn_window,
            raw_context_bundle=raw_context_bundle,
            signature=brain_snapshot.snapshot_hash,
            question_text=question_text,
            conversation_history=brain_snapshot.conversation_history,
            prepared_context=compat_prepared_context,
            request_payload=request_payload,
            question_source="live_brain_v4",
            cache_hit=cache_hit,
            checkpoint_id=uuid.uuid4().hex,
            question_key=question_key,
            brain_snapshot=brain_snapshot,
            brain_plan=brain_plan,
            compact_evidence_pack=evidence_pack,
            plan_hash=self._live_brain_service_v3.plan_hash(brain_plan),
            recovery_draft=recovery_draft,
            recovery_draft_available=bool(recovery_draft.strip()),
        )

    @staticmethod
    def _brain_plan_completeness_rank(plan: Optional[BrainPlan]) -> int:
        normalized = str(getattr(plan, "question_completeness", "") or "").strip().lower()
        if normalized == "complete":
            return 3
        if normalized == "partial":
            return 2
        if normalized == "garbled":
            return 1
        return 0

    def _live_brain_snapshot_needs_stabilization(
        self,
        *,
        snapshot: LiveFrozenSnapshot,
    ) -> bool:
        brain_plan = snapshot.brain_plan
        brain_snapshot = snapshot.brain_snapshot
        if brain_plan is None or brain_snapshot is None:
            return False

        if self._brain_plan_completeness_rank(brain_plan) < 3:
            return True

        latest_question_tail = _normalize_live_question_text(
            brain_snapshot.snapshot_text.splitlines()[-1] if brain_snapshot.snapshot_text else ""
        )
        if _looks_like_live_question_tail_fragment(latest_question_tail):
            return True

        latest_raw_turn = ""
        if snapshot.raw_turn_window:
            latest_raw_turn = _normalize_live_question_text(snapshot.raw_turn_window[-1].get("text") or "")
        if _looks_like_live_question_tail_fragment(latest_raw_turn):
            return True

        raw_detected_asks = list(brain_plan.raw_detected_asks or [])
        if raw_detected_asks:
            latest_raw_ask = _normalize_live_question_text(raw_detected_asks[-1])
            if _looks_like_live_question_tail_fragment(latest_raw_ask):
                return True

        dropped_noise = list(brain_plan.dropped_noise_clauses or [])
        if dropped_noise:
            latest_dropped_clause = _normalize_live_question_text(dropped_noise[-1])
            if _looks_like_live_question_tail_fragment(latest_dropped_clause):
                return True

        return False

    def _live_snapshot_requires_more_interviewer_context(
        self,
        *,
        snapshot: LiveFrozenSnapshot,
    ) -> bool:
        brain_plan = snapshot.brain_plan
        if brain_plan is not None:
            if self._brain_plan_completeness_rank(brain_plan) < 3:
                return True
            if self._live_brain_snapshot_needs_stabilization(snapshot=snapshot):
                return True

        question_text = _normalize_live_question_text(snapshot.question_text)
        if _looks_like_live_question_tail_fragment(question_text):
            return True

        return False

    def _prefer_live_brain_snapshot(
        self,
        *,
        current: LiveFrozenSnapshot,
        candidate: LiveFrozenSnapshot,
    ) -> LiveFrozenSnapshot:
        current_rank = self._brain_plan_completeness_rank(current.brain_plan)
        candidate_rank = self._brain_plan_completeness_rank(candidate.brain_plan)
        if candidate_rank > current_rank:
            return candidate
        if candidate_rank < current_rank:
            return current

        current_asks = len(list(current.brain_plan.ordered_asks or [])) if current.brain_plan is not None else 0
        candidate_asks = len(list(candidate.brain_plan.ordered_asks or [])) if candidate.brain_plan is not None else 0
        if candidate_asks > current_asks:
            return candidate
        if candidate_asks < current_asks:
            return current

        current_text_len = len(_normalize_live_question_text(current.question_text))
        candidate_text_len = len(_normalize_live_question_text(candidate.question_text))
        if candidate_text_len > current_text_len:
            return candidate
        return current

    async def _build_live_frozen_snapshot(
        self,
        *,
        planner: Any,
        tracker: Any,
        interview_config: dict[str, Any],
    ) -> Optional[LiveFrozenSnapshot]:
        if self._live_brain_v3_enabled:
            try:
                return await self._build_live_frozen_snapshot_v3(
                    interview_config=interview_config,
                )
            except Exception as e:
                if not self._live_legacy_fallback_enabled:
                    raise
                print(
                    "[LIVE][BRAIN][V3] freeze_failed_fallbacking "
                    f"session_id={self._session_id} error={e}"
                )
        tracker = getattr(self._pipeline, "conversation_tracker", None)
        raw_turn_window, raw_context_bundle = self._get_live_active_turn_window(limit=5)
        if not raw_turn_window:
            return None

        turn_window = _normalize_live_turn_window(raw_turn_window, limit=5)
        raw_context_bundle = raw_context_bundle or resolve_realtime_context_bundle(turn_window)
        fallback_question_text = raw_context_bundle.get("primary_question", "") or "\n".join(
            turn_entry.get("text", "") for turn_entry in turn_window
        ).strip()

        signature = ""
        if planner is not None and raw_turn_window:
            signature = planner.build_signature(raw_turn_window)

        prepared_context = tracker.get_live_prepared_context() if tracker is not None else None
        cache_hit = bool(prepared_context is not None and prepared_context.signature == signature)

        if planner is not None and not cache_hit:
            prepared_context = planner.prepare_base(
                session_id=self._session_id,
                raw_turns=raw_turn_window,
                interview_config=interview_config,
                mode=self._default_mode,
            )
            if prepared_context is not None and tracker is not None:
                self._cache_live_prepared_context(
                    tracker=tracker,
                    prepared_context=prepared_context,
                )
            cache_hit = bool(prepared_context is not None and prepared_context.signature == signature)

        question_text = _build_live_question_from_prepared_context(
            prepared_context,
            fallback_question_text,
        )
        conversation_history = (
            prepared_context.sanitized_turns
            if prepared_context is not None and prepared_context.sanitized_turns
            else turn_window
        )
        request_payload = copy.deepcopy(prepared_context.request_payload or {}) if prepared_context is not None else {}
        request_payload["question"] = question_text
        request_payload["conversation_history"] = conversation_history
        request_payload["history_count"] = len(conversation_history)
        request_payload["preserve_question_text"] = True
        question_key = (
            _build_live_quality_cache_key(prepared_context)
            if prepared_context is not None
            else _normalize_live_question_text(question_text).lower()
        )

        return LiveFrozenSnapshot(
            raw_turn_window=raw_turn_window,
            turn_window=turn_window,
            raw_context_bundle=raw_context_bundle,
            signature=signature,
            question_text=question_text,
            conversation_history=conversation_history,
            prepared_context=prepared_context,
            request_payload=request_payload,
            question_source="live_prepared_context" if prepared_context is not None else "live_turn_window_fallback",
            cache_hit=cache_hit,
            checkpoint_id=uuid.uuid4().hex,
            question_key=question_key,
        )

    def _live_snapshot_is_current(
        self,
        *,
        snapshot: LiveFrozenSnapshot,
        planner: Any,
        generation_token: Optional[int],
        tracker: Any = None,
    ) -> bool:
        latest_raw_turn_window, _ = self._get_live_active_turn_window(limit=5)
        if snapshot.brain_snapshot is not None:
            if generation_token is not None and generation_token != self._latest_interviewer_generation:
                return False
            latest_turn_window = _normalize_live_turn_window(latest_raw_turn_window, limit=5)
            latest_hash = _build_live_brain_snapshot_hash(latest_turn_window)
            return bool(latest_hash) and latest_hash == snapshot.signature

        latest_prepared_context = tracker.get_live_prepared_context() if tracker is not None else None
        latest_quality_key = _build_live_quality_cache_key(latest_prepared_context)
        snapshot_quality_key = (
            _build_live_quality_cache_key(snapshot.prepared_context)
            if snapshot.prepared_context is not None
            else _normalize_live_question_text(snapshot.question_text).lower()
        )
        if snapshot_quality_key and latest_quality_key and snapshot_quality_key == latest_quality_key:
            return True

        if generation_token is not None and generation_token != self._latest_interviewer_generation:
            return False

        if planner is not None:
            latest_signature = planner.build_signature(latest_raw_turn_window)
            if latest_signature:
                return latest_signature == snapshot.signature

        if snapshot_quality_key and latest_quality_key:
            return snapshot_quality_key == latest_quality_key
        return True

    async def _generate_live_response_from_snapshot_v3(
        self,
        *,
        snapshot: LiveFrozenSnapshot,
        interview_config: dict[str, Any],
        activity_epoch_at_trigger: Optional[int] = None,
    ) -> tuple[dict[str, Any], str, int, int, bool]:
        snapshot = self._normalize_live_v3_snapshot(snapshot)
        if snapshot.brain_plan is None or snapshot.compact_evidence_pack is None or snapshot.brain_snapshot is None:
            raise RuntimeError("Live brain V3 freeze is missing plan or evidence")

        brain_plan = snapshot.brain_plan
        evidence_pack = snapshot.compact_evidence_pack
        path_used = "brain_finalize_from_plan"
        silence_wait_ms = 0
        quality_prewarm_wait_ms = 0
        draft_ready_at_silence = False
        self._live_last_warm_debug = {
            "freeze_checkpoint_id": snapshot.checkpoint_id,
            "freeze_question_key": snapshot.question_key,
            "warm_checkpoint_id": None,
            "warm_question_key": None,
            "warm_exact_match": False,
            "warm_seed_used": False,
            "warm_seed_question_key": None,
            "warm_in_flight_at_silence": False,
            "warm_completed_before_silence": False,
            "warm_wait_ms": 0,
            "snapshot_source": "live_brain_v4",
            "brain_plan_hash": snapshot.plan_hash,
            "semantic_revision_id": self._live_brain_semantic_revision_id_v3,
            "semantic_revision_hash": self._live_brain_semantic_revision_hash_v3,
            "brain_refresh_reason": self._live_brain_last_refresh_reason_v3,
            "brain_refresh_count_before_silence": self._brain_refresh_count_before_silence,
            "brain_refresh_waited_at_freeze_ms": self._brain_refresh_waited_at_freeze_ms,
            "emit_prewarm_started_before_silence": self._emit_prewarm_started_before_silence,
            "emit_prewarm_count_before_silence": self._emit_prewarm_count_before_silence,
            "emit_calls_before_silence": self._emit_calls_before_silence,
            "emit_finalize_calls_after_silence": self._emit_finalize_calls_after_silence,
            "answer_gate_reason": self._answer_gate_reason,
            "hard_silence_authorized": self._hard_silence_authorized,
            "last_interviewer_activity_age_ms": int((self._interviewer_activity_age_sec() or 0.0) * 1000),
            "emit_timeout_budget_ms": int(self._live_emit_timeout_for_plan(brain_plan) * 1000),
            "silence_anchor_at_ms": self._silence_anchor_at_ms,
            "silence_anchor_source": self._silence_anchor_source,
            "completed_turn_processed_at_ms": self._completed_turn_processed_at_ms,
            "completed_turn_after_last_activity_ms": self._completed_turn_after_last_activity_ms,
            "silence_gate_scheduled_delay_ms": self._silence_gate_scheduled_delay_ms,
            "silence_gate_fired_at_ms": self._silence_gate_fired_at_ms,
            "late_brain_refresh_started_before_silence": self._late_brain_refresh_started_before_silence,
            "late_brain_refresh_completed_before_silence": self._late_brain_refresh_completed_before_silence,
            "brain_force_stable_at_freeze": self._brain_force_stable_at_freeze,
            "brain_immediate_safe_fallback_at_freeze": self._brain_immediate_safe_fallback_at_freeze,
            "emit_started_at_ms": self._emit_started_at_ms,
            "emit_stream_started_at_ms": self._emit_stream_started_at_ms,
            "emit_first_chunk_ms": self._emit_first_chunk_ms,
            "emit_stream_completed_at_ms": self._emit_stream_completed_at_ms,
            "emit_stream_chunk_count": self._emit_stream_chunk_count,
            "emit_stream_partial_salvaged": self._emit_stream_partial_salvaged,
        }

        self._cancel_live_brain_warm_schedule()

        exact_result = self._get_live_brain_warm_exact_result(plan_hash=snapshot.plan_hash)
        if exact_result is not None:
            self._live_last_warm_debug.update(
                {
                    "warm_checkpoint_id": exact_result.checkpoint_id,
                    "warm_question_key": exact_result.question_key,
                    "warm_exact_match": True,
                    "warm_completed_before_silence": True,
                }
            )
            response = self._build_live_v3_response_payload(
                snapshot=snapshot,
                interview_config=interview_config,
                final_result=exact_result.response,
                path_used="brain_prewarmed_exact",
                direct_brain_served=False,
            )
            return response, "brain_prewarmed_exact", silence_wait_ms, quality_prewarm_wait_ms, draft_ready_at_silence

        inflight_checkpoint = self._brain_warm_inflight_checkpoint_v3
        if (
            inflight_checkpoint is not None
            and self._brain_warm_inflight_task_v3 is not None
            and not self._brain_warm_inflight_task_v3.done()
            and inflight_checkpoint.plan_hash == snapshot.plan_hash
        ):
            self._live_last_warm_debug.update(
                {
                    "warm_checkpoint_id": inflight_checkpoint.checkpoint_id,
                    "warm_question_key": inflight_checkpoint.question_key,
                    "warm_in_flight_at_silence": True,
                }
            )
            wait_started = perf_counter()
            await self._await_live_brain_warm_exact_result(
                plan_hash=snapshot.plan_hash,
                timeout_sec=self._live_emit_late_prewarm_silence_wait_sec,
            )
            quality_prewarm_wait_ms = int((perf_counter() - wait_started) * 1000)
            self._live_last_warm_debug["warm_wait_ms"] = quality_prewarm_wait_ms

            exact_result = self._get_live_brain_warm_exact_result(plan_hash=snapshot.plan_hash)
            if exact_result is not None:
                self._live_last_warm_debug.update(
                    {
                        "warm_checkpoint_id": exact_result.checkpoint_id,
                        "warm_question_key": exact_result.question_key,
                        "warm_exact_match": True,
                        "warm_completed_before_silence": True,
                    }
                )
                response = self._build_live_v3_response_payload(
                    snapshot=snapshot,
                    interview_config=interview_config,
                    final_result=exact_result.response,
                    path_used="brain_prewarmed_exact",
                    direct_brain_served=False,
                )
                return response, "brain_prewarmed_exact", silence_wait_ms, quality_prewarm_wait_ms, draft_ready_at_silence

            failed_result = self._get_live_brain_warm_result_for_plan_hash(
                plan_hash=snapshot.plan_hash,
                include_failed=True,
            )
            if failed_result is not None and not failed_result.success:
                self._live_last_warm_debug.update(
                    {
                        "warm_checkpoint_id": failed_result.checkpoint_id,
                        "warm_question_key": failed_result.question_key,
                        "warm_exact_match": True,
                        "warm_failed_before_finalize": True,
                    }
                )

        llm_failure_kind = str(self._live_brain_last_llm_failure_kind or "").strip().lower()
        if llm_failure_kind in {"authenticationerror", "api_connectionerror", "apiconnectionerror", "api_key_missing"}:
            self._live_brain_last_failure_reason = llm_failure_kind
            failure_notice = self._build_live_llm_failure_notice(llm_failure_kind)
            failure_result = {
                "full_response": failure_notice,
                "bullets": [failure_notice],
                "confidence": 0.0,
                "latency_ms": 0,
                "metadata": {
                    "emit_stream_used": False,
                    "emit_stream_first_chunk_ms": None,
                    "emit_stream_completed_ms": None,
                    "emit_stream_chunk_count": 0,
                    "emit_stream_partial_salvaged": False,
                    "finalizer_primary_mode": "normal",
                    "finalizer_primary_success": False,
                    "recovery_draft_available": False,
                    "finalizer_recovery_attempted": False,
                    "finalizer_recovery_kind": "none",
                    "finalizer_recovery_success": False,
                    "finalizer_recovery_skipped_reason": "llm_auth_failure",
                    "finalizer_fallback_kind": "explicit_failure",
                    "llm_called": False,
                    "provider": None,
                    "model": None,
                    "configured_provider": None,
                    "configured_model": None,
                    "emit_failure_kind": llm_failure_kind,
                    "output_sanitizer_applied": False,
                },
            }
            self._live_last_warm_debug["emit_failure_kind"] = llm_failure_kind
            response = self._build_live_v3_response_payload(
                snapshot=snapshot,
                interview_config=interview_config,
                final_result=failure_result,
                path_used="brain_llm_failure_notice",
                direct_brain_served=False,
            )
            return response, "brain_llm_failure_notice", silence_wait_ms, quality_prewarm_wait_ms, draft_ready_at_silence

        if (
            self._brain_warm_inflight_checkpoint_v3 is not None
            and self._brain_warm_inflight_checkpoint_v3.plan_hash == snapshot.plan_hash
            and self._brain_warm_inflight_task_v3 is not None
            and not self._brain_warm_inflight_task_v3.done()
        ):
            self._live_last_warm_debug["warm_abandoned_at_silence"] = True
            self._cancel_live_brain_warm_inflight()

        self._emit_finalize_calls_after_silence += 1
        self._live_last_warm_debug["emit_finalize_calls_after_silence"] = self._emit_finalize_calls_after_silence
        self._emit_started_at_ms = self._stream_elapsed_ms()
        self._live_last_warm_debug["emit_started_at_ms"] = self._emit_started_at_ms
        self._emit_stream_started_at_ms = self._emit_started_at_ms
        self._live_last_warm_debug["emit_stream_started_at_ms"] = self._emit_stream_started_at_ms

        if activity_epoch_at_trigger is None or activity_epoch_at_trigger == self._interviewer_activity_epoch:
            await self._websocket.send_json(
                {
                    "type": "suggestion_stream",
                    "stage": "start",
                    "mode": self._default_mode,
                    "source": "auto_silence",
                    "trigger": "silence",
                    "question": snapshot.question_text,
                    "question_source": snapshot.question_source,
                    "context_turns": len(snapshot.conversation_history),
                    "full_response": "",
                    "processing_full_response": True,
                }
            )

        last_stream_response = ""

        async def _emit_stream_partial(partial_payload: dict[str, Any]) -> None:
            nonlocal last_stream_response
            if (
                activity_epoch_at_trigger is not None
                and activity_epoch_at_trigger != self._interviewer_activity_epoch
            ):
                return
            full_response = str(partial_payload.get("full_response") or "")
            if not full_response or full_response == last_stream_response:
                return
            chunk_count = int(partial_payload.get("chunk_count") or 0)
            if chunk_count > self._emit_stream_chunk_count:
                self._emit_stream_chunk_count = chunk_count
            first_chunk_ms = partial_payload.get("first_chunk_ms")
            if isinstance(first_chunk_ms, int) and first_chunk_ms >= 0 and self._emit_first_chunk_ms is None:
                if self._emit_started_at_ms is not None:
                    self._emit_first_chunk_ms = self._emit_started_at_ms + first_chunk_ms
                else:
                    self._emit_first_chunk_ms = first_chunk_ms
            self._live_last_warm_debug.update(
                {
                    "emit_first_chunk_ms": self._emit_first_chunk_ms,
                    "emit_stream_chunk_count": self._emit_stream_chunk_count,
                }
            )
            await self._websocket.send_json(
                {
                    "type": "suggestion_stream",
                    "stage": "stream",
                    "mode": self._default_mode,
                    "source": "auto_silence",
                    "trigger": "silence",
                    "question": snapshot.question_text,
                    "question_source": snapshot.question_source,
                    "context_turns": len(snapshot.conversation_history),
                    "full_response": full_response,
                    "processing_full_response": True,
                    "provider": partial_payload.get("provider"),
                    "model": partial_payload.get("model"),
                }
            )
            last_stream_response = full_response

        final_result = await self._live_finalizer_v3.finalize(
            plan=brain_plan,
            evidence_pack=evidence_pack,
            question_text=snapshot.question_text,
            conversation_history=snapshot.conversation_history,
            interview_config=interview_config,
            working_draft="",
            strict_emit_only=True,
            recovery_draft=snapshot.recovery_draft,
            allow_post_failure_recovery=True,
            timeout_override_sec=self._live_emit_timeout_for_plan(brain_plan),
            on_partial_response=_emit_stream_partial,
            partial_emit_interval_sec=0.05,
        )
        final_metadata = final_result.get("metadata") or {}
        if not isinstance(final_metadata, dict):
            final_metadata = {}
        completed_rel_ms = int(final_metadata.get("emit_stream_completed_ms") or final_result.get("latency_ms") or 0)
        if completed_rel_ms > 0:
            if self._emit_started_at_ms is not None:
                self._emit_stream_completed_at_ms = self._emit_started_at_ms + completed_rel_ms
            else:
                self._emit_stream_completed_at_ms = completed_rel_ms
        first_chunk_rel_ms = final_metadata.get("emit_stream_first_chunk_ms")
        if isinstance(first_chunk_rel_ms, int) and first_chunk_rel_ms >= 0 and self._emit_first_chunk_ms is None:
            if self._emit_started_at_ms is not None:
                self._emit_first_chunk_ms = self._emit_started_at_ms + first_chunk_rel_ms
            else:
                self._emit_first_chunk_ms = first_chunk_rel_ms
        self._emit_stream_chunk_count = max(
            self._emit_stream_chunk_count,
            int(final_metadata.get("emit_stream_chunk_count") or 0),
        )
        self._emit_stream_partial_salvaged = bool(final_metadata.get("emit_stream_partial_salvaged"))
        self._live_last_warm_debug.update(
            {
                "emit_first_chunk_ms": self._emit_first_chunk_ms,
                "emit_stream_completed_at_ms": self._emit_stream_completed_at_ms,
                "emit_stream_chunk_count": self._emit_stream_chunk_count,
                "emit_stream_partial_salvaged": self._emit_stream_partial_salvaged,
            }
        )
        path_used = "brain_finalize_from_plan"
        response = self._build_live_v3_response_payload(
            snapshot=snapshot,
            interview_config=interview_config,
            final_result=final_result,
            path_used=path_used,
            direct_brain_served=False,
        )
        return response, path_used, silence_wait_ms, quality_prewarm_wait_ms, draft_ready_at_silence

    async def _generate_live_response_from_snapshot(
        self,
        *,
        snapshot: LiveFrozenSnapshot,
        planner: Any,
        tracker: Any,
        interview_config: dict[str, Any],
        activity_epoch_at_trigger: Optional[int] = None,
    ) -> tuple[dict[str, Any], str, int, int, bool]:
        if self._live_brain_v3_enabled and snapshot.brain_plan is not None:
            return await self._generate_live_response_from_snapshot_v3(
                snapshot=snapshot,
                interview_config=interview_config,
                activity_epoch_at_trigger=activity_epoch_at_trigger,
            )
        path_used = "writer_emergency_fallback"
        silence_wait_ms = 0
        quality_prewarm_wait_ms = 0
        draft_ready_at_silence = False
        prepared_context = snapshot.prepared_context
        self._live_last_warm_debug = {
            "freeze_checkpoint_id": snapshot.checkpoint_id,
            "freeze_question_key": snapshot.question_key,
            "warm_checkpoint_id": None,
            "warm_question_key": None,
            "warm_exact_match": False,
            "warm_seed_used": False,
            "warm_seed_question_key": None,
            "warm_in_flight_at_silence": False,
            "warm_completed_before_silence": False,
            "warm_wait_ms": 0,
            "snapshot_source": "frozen_snapshot_v2",
        }

        if self._live_parallel_warmer_v2_enabled:
            if prepared_context is None:
                raise RuntimeError("Live quality writer could not prepare a usable snapshot")

            question_key = snapshot.question_key or _normalize_live_question_text(snapshot.question_text).lower()
            completed_result = self._get_live_warm_exact_result(question_key=question_key)
            prewarmed_response = None
            if (
                self._live_quality_cached_response is not None
                and self._live_quality_cached_signature == question_key
            ):
                prewarmed_response = copy.deepcopy(self._live_quality_cached_response)
            if completed_result is not None:
                self._live_last_warm_debug.update(
                    {
                        "warm_checkpoint_id": completed_result.checkpoint_id,
                        "warm_question_key": completed_result.question_key,
                        "warm_exact_match": True,
                        "warm_completed_before_silence": True,
                    }
                )
                if not self._live_parallel_warmer_v2_shadow_mode:
                    response = copy.deepcopy(completed_result.response)
                    response.setdefault("debug", {})
                    response["debug"]["path_used"] = "writer_prewarmed_fallback"
                    response["debug"]["fallback_used"] = True
                    path_used = "writer_prewarmed_fallback"
                    draft_ready_at_silence = bool(str(prepared_context.draft_answer or "").strip())
                    return response, path_used, silence_wait_ms, quality_prewarm_wait_ms, draft_ready_at_silence
            elif prewarmed_response is not None:
                self._live_last_warm_debug.update(
                    {
                        "warm_question_key": question_key,
                        "warm_exact_match": True,
                        "warm_completed_before_silence": True,
                    }
                )
                if not self._live_parallel_warmer_v2_shadow_mode:
                    response = copy.deepcopy(prewarmed_response)
                    response.setdefault("debug", {})
                    response["debug"]["path_used"] = "writer_prewarmed_fallback"
                    response["debug"]["fallback_used"] = True
                    path_used = "writer_prewarmed_fallback"
                    draft_ready_at_silence = bool(str(prepared_context.draft_answer or "").strip())
                    return response, path_used, silence_wait_ms, quality_prewarm_wait_ms, draft_ready_at_silence

            inflight_checkpoint = self._live_warm_inflight_checkpoint
            if (
                inflight_checkpoint is not None
                and self._live_warm_inflight_task is not None
                and not self._live_warm_inflight_task.done()
                and inflight_checkpoint.question_key == question_key
            ):
                self._live_last_warm_debug.update(
                    {
                        "warm_checkpoint_id": inflight_checkpoint.checkpoint_id,
                        "warm_question_key": inflight_checkpoint.question_key,
                        "warm_in_flight_at_silence": True,
                    }
                )
                wait_started = perf_counter()
                await self._await_live_warm_exact_result(question_key=question_key)
                quality_prewarm_wait_ms = int((perf_counter() - wait_started) * 1000)
                self._live_last_warm_debug["warm_wait_ms"] = quality_prewarm_wait_ms
                completed_result = self._get_live_warm_exact_result(question_key=question_key)
                if completed_result is not None:
                    self._live_last_warm_debug.update(
                        {
                            "warm_checkpoint_id": completed_result.checkpoint_id,
                            "warm_question_key": completed_result.question_key,
                            "warm_exact_match": True,
                        }
                    )
                    if not self._live_parallel_warmer_v2_shadow_mode:
                        response = copy.deepcopy(completed_result.response)
                        response.setdefault("debug", {})
                        response["debug"]["path_used"] = "writer_prewarmed_fallback"
                        response["debug"]["fallback_used"] = True
                        path_used = "writer_prewarmed_fallback"
                        draft_ready_at_silence = bool(str(prepared_context.draft_answer or "").strip())
                        return response, path_used, silence_wait_ms, quality_prewarm_wait_ms, draft_ready_at_silence
            elif (
                self._live_quality_refresh_task is not None
                and not self._live_quality_refresh_task.done()
                and self._live_quality_refresh_signature == question_key
            ):
                self._live_last_warm_debug.update(
                    {
                        "warm_question_key": question_key,
                        "warm_in_flight_at_silence": True,
                    }
                )
                wait_started = perf_counter()
                await self._await_live_quality_refresh(signature_or_key=question_key, timeout_sec=self._live_warm_wait_sec)
                quality_prewarm_wait_ms = int((perf_counter() - wait_started) * 1000)
                self._live_last_warm_debug["warm_wait_ms"] = quality_prewarm_wait_ms
                if (
                    self._live_quality_cached_response is not None
                    and self._live_quality_cached_signature == question_key
                ):
                    prewarmed_response = copy.deepcopy(self._live_quality_cached_response)
                if prewarmed_response is not None:
                    self._live_last_warm_debug.update(
                        {
                            "warm_question_key": question_key,
                            "warm_exact_match": True,
                        }
                    )
                    if not self._live_parallel_warmer_v2_shadow_mode:
                        response = copy.deepcopy(prewarmed_response)
                        response.setdefault("debug", {})
                        response["debug"]["path_used"] = "writer_prewarmed_fallback"
                        response["debug"]["fallback_used"] = True
                        path_used = "writer_prewarmed_fallback"
                        draft_ready_at_silence = bool(str(prepared_context.draft_answer or "").strip())
                        return response, path_used, silence_wait_ms, quality_prewarm_wait_ms, draft_ready_at_silence

            compatible_inflight_checkpoint = None
            if (
                self._live_warm_inflight_checkpoint is not None
                and self._live_warm_inflight_task is not None
                and not self._live_warm_inflight_task.done()
                and self._live_warm_inflight_checkpoint.question_key != question_key
                and _is_live_warm_seed_compatible(
                    self._live_warm_inflight_checkpoint.question_text,
                    snapshot.question_text,
                )
            ):
                compatible_inflight_checkpoint = self._live_warm_inflight_checkpoint
                self._live_last_warm_debug.update(
                    {
                        "warm_checkpoint_id": compatible_inflight_checkpoint.checkpoint_id,
                        "warm_question_key": compatible_inflight_checkpoint.question_key,
                        "warm_in_flight_at_silence": True,
                    }
                )
                wait_started = perf_counter()
                await self._await_live_warm_checkpoint(
                    checkpoint_id=compatible_inflight_checkpoint.checkpoint_id,
                    timeout_sec=self._live_warm_wait_sec,
                )
                quality_prewarm_wait_ms = int((perf_counter() - wait_started) * 1000)
                self._live_last_warm_debug["warm_wait_ms"] = quality_prewarm_wait_ms

            working_draft = ""
            seed_result = self._get_live_warm_seed_result(
                question_text=snapshot.question_text,
                question_key=question_key,
            )
            if seed_result is not None:
                working_draft = " ".join(
                    str(seed_result.response.get("full_response") or "").split()
                ).strip()
                if working_draft:
                    self._live_last_warm_debug.update(
                        {
                            "warm_seed_used": True,
                            "warm_seed_question_key": seed_result.question_key,
                        }
                    )

            response = await _suggest_live_prepared_response(
                websocket=self._websocket,
                session_id=self._session_id,
                interview_config=interview_config,
                question_text=snapshot.question_text,
                conversation_history=snapshot.conversation_history,
                live_prepared_context=prepared_context,
                working_draft=working_draft,
            )
            if working_draft:
                path_used = "writer_seeded_fallback"
            if not response.get("success"):
                raise RuntimeError(response.get("error") or "Live shared answer core failed")

            draft_ready_at_silence = bool(str(prepared_context.draft_answer or "").strip())
            return response, path_used, silence_wait_ms, quality_prewarm_wait_ms, draft_ready_at_silence

        if (
            prepared_context is not None
            and not str(prepared_context.draft_answer or "").strip()
            and prepared_context.plan_stage != "semantic"
        ):
            wait_started = perf_counter()
            await self._await_live_semantic_refresh(signature=snapshot.signature)
            silence_wait_ms = int((perf_counter() - wait_started) * 1000)
            refreshed_snapshot = await self._build_live_frozen_snapshot(
                planner=planner,
                tracker=tracker,
                interview_config=interview_config,
            )
            if refreshed_snapshot is not None and refreshed_snapshot.signature == snapshot.signature:
                prepared_context = refreshed_snapshot.prepared_context

        if prepared_context is None:
            raise RuntimeError("Live quality writer could not prepare a usable snapshot")

        quality_key = _build_live_quality_cache_key(prepared_context) or _normalize_live_question_text(
            snapshot.question_text
        ).lower()

        prewarmed_response = self._get_live_quality_cached_response(signature_or_key=quality_key)
        if prewarmed_response is None:
            if planner is not None and tracker is not None:
                self._schedule_live_quality_refresh(
                    planner=planner,
                    tracker=tracker,
                    prepared_context=prepared_context,
                    interview_config=interview_config,
                )
            wait_started = perf_counter()
            await self._await_live_quality_refresh(signature_or_key=quality_key)
            quality_prewarm_wait_ms = int((perf_counter() - wait_started) * 1000)
            prewarmed_response = self._get_live_quality_cached_response(signature_or_key=quality_key)

        if prewarmed_response is not None:
            response = prewarmed_response
            response.setdefault("debug", {})
            response["debug"]["path_used"] = "writer_prewarmed_fallback"
            response["debug"]["fallback_used"] = True
            path_used = "writer_prewarmed_fallback"
        else:
            response = await _suggest_live_prepared_response(
                websocket=self._websocket,
                session_id=self._session_id,
                interview_config=interview_config,
                question_text=snapshot.question_text,
                conversation_history=snapshot.conversation_history,
                live_prepared_context=prepared_context,
            )

        if not response.get("success"):
            raise RuntimeError(response.get("error") or "Live shared answer core failed")

        draft_ready_at_silence = bool(
            prepared_context is not None and str(prepared_context.draft_answer or "").strip()
        )
        return response, path_used, silence_wait_ms, quality_prewarm_wait_ms, draft_ready_at_silence

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

    def _cancel_suggestion_debounce(self) -> None:
        if self._suggestion_debounce_task and not self._suggestion_debounce_task.done():
            self._suggestion_debounce_task.cancel()
        self._suggestion_debounce_task = None

    def _cancel_live_preparation_debounce(self) -> None:
        if self._live_preparation_debounce_task and not self._live_preparation_debounce_task.done():
            self._live_preparation_debounce_task.cancel()
        self._live_preparation_debounce_task = None

    def _schedule_live_preparation_refresh_debounced(self) -> None:
        self._cancel_live_preparation_debounce()
        self._live_preparation_debounce_token += 1
        debounce_token = self._live_preparation_debounce_token

        async def _debounced_refresh() -> None:
            try:
                await asyncio.sleep(self._live_preparation_debounce_sec)
                if debounce_token != self._live_preparation_debounce_token:
                    return
                if self._live_brain_v3_enabled:
                    self._queue_live_brain_v3_refresh(reason="display_caption")
                    return
                if self._live_parallel_warmer_v2_enabled:
                    await self._refresh_live_parallel_state()
                else:
                    await self._refresh_live_prepared_context()
            except asyncio.CancelledError:
                return
            except Exception as e:
                print(
                    "[LIVE][PREPARED] debounced_refresh_failed "
                    f"session_id={self._session_id} error={e}"
                )

        task = asyncio.create_task(
            _debounced_refresh(),
            name=f"live-preparation-debounce-{self._session_id}",
        )
        self._live_preparation_debounce_task = task
        self._track_background_task(task)

    def _schedule_silence_suggestion(
        self,
        turn: SpeakerTurn,
        generation_token: int,
        *,
        delay_sec: Optional[float] = None,
    ) -> None:
        self._cancel_suggestion_debounce()
        self._suggestion_debounce_token += 1
        debounce_token = self._suggestion_debounce_token
        delay = delay_sec if delay_sec is not None else self._suggestion_debounce_sec

        print(
            "[AUTO][SILENCE] schedule_debounce "
            f"session_id={self._session_id} "
            f"generation={generation_token} "
            f"debounce_token={debounce_token} "
            f"delay_sec={delay:.1f} "
            f"text='{(turn.text or '')[:80]}'"
        )

        async def _debounced_trigger() -> None:
            try:
                await asyncio.sleep(delay)
                if debounce_token != self._suggestion_debounce_token:
                    return
                if turn.speaker == "interviewer" and generation_token != self._latest_interviewer_generation:
                    return
                task = asyncio.create_task(
                    self._try_auto_trigger_suggestion(turn, generation_token=generation_token),
                    name=f"live-suggestion-{self._session_id}-{generation_token}",
                )
                self._track_background_task(task)
            except asyncio.CancelledError:
                return
            except Exception as e:
                print(
                    "[AUTO][SILENCE] debounce_failed "
                    f"session_id={self._session_id} error={e}"
                )

        task = asyncio.create_task(
            _debounced_trigger(),
            name=f"silence-suggestion-{self._session_id}",
        )
        self._suggestion_debounce_task = task
        self._track_background_task(task)

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
                self._schedule_completed_turn_processing(completed)
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
            self._schedule_turn_flush()
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

    async def _try_auto_trigger_suggestion(self, turn: SpeakerTurn, *, generation_token: Optional[int] = None) -> None:
        """
        Try to trigger an automatic suggestion using relaxed constraints.
        
        This is called when the strict constraints fail, allowing shorter
        interviewer questions to still trigger auto-suggestions.
        
        Uses SilenceDetector with:
        - min_turn_duration_ms: 500 (vs 2000 strict)
        - min_word_count: 2 (vs 5 strict)
        - cooldown_sec: 5.0
        """
        if self._downstream_in_flight:
            self._answer_gate_reason = "downstream_in_flight"
            return

        if self._auto_suggestion_already_served_for_current_silence():
            self._answer_gate_reason = "already_answered_current_silence_window"
            print(
                "[AUTO][SILENCE] skip_trigger "
                f"session_id={self._session_id} "
                "reason=already_answered_current_silence_window"
            )
            return

        if not self._hard_silence_is_satisfied():
            remaining_silence_sec = self._remaining_hard_silence_sec()
            self._answer_gate_reason = "waiting_for_hard_silence"
            self._hard_silence_authorized = False
            print(
                "[AUTO][SILENCE] waiting_for_hard_silence "
                f"session_id={self._session_id} "
                f"remaining_sec={remaining_silence_sec:.2f} "
                f"generation={generation_token if generation_token is not None else 'n/a'}"
            )
            if generation_token is not None and turn.speaker == "interviewer":
                self._schedule_silence_suggestion(
                    turn,
                    generation_token,
                    delay_sec=remaining_silence_sec,
                )
            else:
                self._ensure_hard_silence_gate_scheduled()
            return

        self._hard_silence_authorized = True
        self._answer_gate_reason = "hard_silence_authorized"
        if self._recent_interviewer_display_caption_is_active():
            self._answer_gate_reason = "recent_display_caption_activity"
            self._hard_silence_authorized = False
            self._ensure_hard_silence_gate_scheduled()
            return
        self._flush_pending_interviewer_candidate_for_silence()
        tracker = getattr(self._pipeline, "conversation_tracker", None)
        normalizer = getattr(self._pipeline, "ask_normalizer", None)
        planner = getattr(self._pipeline, "live_question_planner", None)
        if planner is None and normalizer is not None:
            planner = LiveQuestionPlanner(normalizer)
        interview_config = getattr(getattr(self._pipeline, "session_state", None), "interview_config", {}) or {}
        snapshot = await self._build_live_frozen_snapshot(
            planner=planner,
            tracker=tracker,
            interview_config=interview_config,
        )
        stabilization_wait_ms = 0
        if snapshot is None:
            print(
                "[AUTO][SILENCE] skip_trigger "
                f"session_id={self._session_id} reason=no_snapshot"
            )
            return

        if self._live_brain_v3_enabled:
            if self._live_brain_snapshot_needs_stabilization(snapshot=snapshot):
                wait_started = perf_counter()
                await asyncio.sleep(self._live_question_stabilization_sec)
                self._flush_pending_interviewer_candidate_for_silence()
                refreshed_snapshot = await self._build_live_frozen_snapshot(
                    planner=planner,
                    tracker=tracker,
                    interview_config=interview_config,
                )
                if refreshed_snapshot is not None:
                    snapshot = self._prefer_live_brain_snapshot(
                        current=snapshot,
                        candidate=refreshed_snapshot,
                    )
                stabilization_wait_ms = int((perf_counter() - wait_started) * 1000)
        elif (
            planner is not None
            and self._live_question_needs_stabilization(
                planner=planner,
                question_text=snapshot.question_text,
                prepared_context=snapshot.prepared_context,
            )
        ):
            wait_started = perf_counter()
            await asyncio.sleep(self._live_question_stabilization_sec)
            self._flush_pending_interviewer_candidate_for_silence()
            refreshed_snapshot = await self._build_live_frozen_snapshot(
                planner=planner,
                tracker=tracker,
                interview_config=interview_config,
            )
            if refreshed_snapshot is not None:
                snapshot = refreshed_snapshot
            stabilization_wait_ms = int((perf_counter() - wait_started) * 1000)

        if not self._hard_silence_is_satisfied():
            self._answer_gate_reason = "stabilization_interrupted_by_activity"
            self._hard_silence_authorized = False
            return

        if self._live_snapshot_requires_more_interviewer_context(snapshot=snapshot):
            self._answer_gate_reason = "waiting_for_more_interviewer_context"
            completeness = (
                str(snapshot.brain_plan.question_completeness or "").strip().lower()
                if snapshot.brain_plan is not None
                else "unknown"
            )
            print(
                "[AUTO][SILENCE] skip_trigger "
                f"session_id={self._session_id} "
                "reason=waiting_for_more_interviewer_context "
                f"question_completeness={completeness or 'unknown'} "
                f"question_source={snapshot.question_source} "
                f"question_text='{snapshot.question_text[:180]}'"
            )
            return

        if not snapshot.question_text:
            self._answer_gate_reason = "no_question_text"
            print(
                "[AUTO][SILENCE] skip_trigger "
                f"session_id={self._session_id} reason=no_question_text"
            )
            return

        # Evaluate the bundled interviewer block rather than only the last turn.
        turn_data = {
            "speaker": "interviewer",
            "duration_ms": max(turn.duration_ms, self._silence_detector.min_turn_duration_ms),
            "text": snapshot.question_text,
        }

        # Check if we should trigger with relaxed constraints
        if not self._silence_detector.should_trigger_suggestion(turn_data):
            self._answer_gate_reason = "constraints_not_met"
            remaining_cooldown = self._silence_detector.get_remaining_cooldown()
            print(
                "[AUTO][SILENCE] skip_trigger "
                f"session_id={self._session_id} "
                f"reason=constraints_not_met "
                f"duration_ms={turn_data['duration_ms']} "
                f"word_count={len(str(snapshot.question_text or '').split())} "
                f"question_source={snapshot.question_source} "
                f"remaining_cooldown={remaining_cooldown:.1f}s"
            )
            return

        # Record that we're about to trigger
        self._answer_gate_reason = "generating_suggestion"
        trigger_activity_epoch = self._interviewer_activity_epoch
        self._cancel_suggestion_debounce()
        self._cancel_hard_silence_gate()
        
        print(
            "[AUTO][SILENCE] triggering_suggestion "
            f"session_id={self._session_id} "
            f"duration_ms={turn_data['duration_ms']} "
            f"word_count={len(str(snapshot.question_text or '').split())} "
            f"question_source={snapshot.question_source} "
            f"generation={generation_token if generation_token is not None else 'n/a'}"
        )
        print(
            "[LIVE][HANDOFF] resolved_context "
            f"session_id={self._session_id} "
            f"question_source={snapshot.question_source} "
            f"context_turns={len(snapshot.conversation_history)} "
            f"question_text='{snapshot.question_text[:180]}'"
        )
        if snapshot.prepared_context is not None:
            print(
                "[LIVE][HANDOFF] prepared_context "
                f"session_id={self._session_id} "
                f"version={snapshot.prepared_context.version} "
                f"complexity={snapshot.prepared_context.complexity_class.value} "
                f"shape={snapshot.prepared_context.answer_shape.value} "
                f"target_length={snapshot.prepared_context.target_length} "
                f"planner_source={snapshot.prepared_context.planner_source} "
                f"planner_model='{(snapshot.prepared_context.planner_model or '')[:80]}' "
                f"draft_ready={bool(str(snapshot.prepared_context.draft_answer or '').strip())} "
                f"primary='{snapshot.prepared_context.primary_ask[:180]}' "
                f"secondary={snapshot.prepared_context.secondary_asks[:4]}"
            )
        else:
            print(
                "[LIVE][HANDOFF] prepared_context_missing "
                f"session_id={self._session_id}"
            )

        # Send progress indicator
        await self._websocket.send_json({
            "type": "analysis",
            "stage": "auto_silence",
            "context_turns": len(snapshot.conversation_history),
            "question_source": snapshot.question_source,
            "primary_question_index": snapshot.raw_context_bundle.get("primary_question_index"),
        })
        if self._stream_started_at is not None and self._analysis_emitted_at_ms is None:
            self._analysis_emitted_at_ms = int((perf_counter() - self._stream_started_at) * 1000)
            print(
                "[WS][STT] analysis_emitted "
                f"session_id={self._session_id} "
                f"timestamp_ms={self._analysis_emitted_at_ms}"
            )
        
        try:
            effective_delivery_mode = str(interview_config.get("delivery_mode") or "manual").strip().lower()
            if effective_delivery_mode not in {"realtime", "manual", "live_manual"}:
                effective_delivery_mode = "manual"
            self._downstream_in_flight = True
            silence_started = perf_counter()
            stale_snapshot_discarded = False
            response, path_used, silence_wait_ms, quality_prewarm_wait_ms, draft_ready_at_silence = await self._generate_live_response_from_snapshot(
                snapshot=snapshot,
                planner=planner,
                tracker=tracker,
                interview_config=interview_config,
                activity_epoch_at_trigger=trigger_activity_epoch,
            )
            if trigger_activity_epoch != self._interviewer_activity_epoch:
                stale_snapshot_discarded = True
                self._answer_gate_reason = "interviewer_resumed_during_emit"
                print(
                    "[AUTO][SILENCE] abort_emit "
                    f"session_id={self._session_id} "
                    "reason=interviewer_resumed_during_emit"
                )
                return
            if not self._live_snapshot_is_current(
                snapshot=snapshot,
                planner=planner,
                generation_token=generation_token,
                tracker=tracker,
            ):
                stale_snapshot_discarded = True
                print(
                    "[AUTO][SILENCE] stale_snapshot_rebuild "
                    f"session_id={self._session_id} "
                    f"checkpoint_id={snapshot.checkpoint_id} "
                    f"question_source={snapshot.question_source}"
                )
                self._flush_pending_interviewer_candidate_for_silence()
                refreshed_snapshot = await self._build_live_frozen_snapshot(
                    planner=planner,
                    tracker=tracker,
                    interview_config=interview_config,
                )
                if refreshed_snapshot is not None and refreshed_snapshot.question_text:
                    snapshot = refreshed_snapshot
                    response, path_used, silence_wait_ms, quality_prewarm_wait_ms, draft_ready_at_silence = await self._generate_live_response_from_snapshot(
                        snapshot=snapshot,
                        planner=planner,
                        tracker=tracker,
                        interview_config=interview_config,
                        activity_epoch_at_trigger=trigger_activity_epoch,
                    )

            debug_info = response.get("debug") or {}
            suggestion_info = response.get("suggestion") or {}
            quality_info = response.get("quality") or {}
            language_info = response.get("language") or {}
            brain_plan = snapshot.brain_plan
            evidence_pack = snapshot.compact_evidence_pack
            latest_display_caption = self._get_recent_interviewer_display_caption_text()
            pending_interviewer_candidate = self._normalize_turn_text(
                self._interviewer_turn_candidate.text if self._interviewer_turn_candidate is not None else ""
            )
            live_cache_age_ms = None
            prepared_context = snapshot.prepared_context
            if prepared_context is not None:
                live_cache_age_ms = int((datetime.utcnow() - prepared_context.created_at).total_seconds() * 1000)
            time_from_silence_to_answer_ms = int((perf_counter() - silence_started) * 1000)
            time_from_silence_to_shared_core_ms = 0 if path_used == "writer_prewarmed_fallback" else time_from_silence_to_answer_ms
            warm_debug = dict(self._live_last_warm_debug or {})
            warm_debug["freeze_to_emit_ms"] = time_from_silence_to_answer_ms
            fallback_used = debug_info.get("fallback_used")
            if fallback_used is None:
                fallback_used = path_used.startswith("writer_")

            self._freeze_live_active_ask(
                tracker=tracker,
                question_fallback=self._normalize_turn_text(turn.text or ""),
                interviewer_generation=(
                    generation_token if generation_token is not None else self._latest_interviewer_generation
                ),
            )
            self._finalize_current_live_interviewer_block(reason="suggestion_triggered")
            self._silence_detector.record_trigger()
            self._answer_gate_reason = "triggering_suggestion"
            
            suggestion_payload = {
                "type": "suggestion",
                "stage": "full",
                "mode": response.get("mode", self._default_mode),
                "source": "auto_silence",
                "trigger": "silence",
                "question": snapshot.question_text,
                "context_turns": len(snapshot.conversation_history),
                "question_source": snapshot.question_source,
                "context_turns_used": len(snapshot.conversation_history),
                "primary_question_index": snapshot.raw_context_bundle.get("primary_question_index"),
                "interviewer_question_index": snapshot.raw_context_bundle.get("interviewer_question_index"),
                "delivery_mode": effective_delivery_mode,
                "answer_intent": suggestion_info.get("answerIntent"),
                "full_response": response.get("full_response", ""),
                "bullets_preview": response.get("bullets", []),
                "bullets": response.get("bullets", []),
                "key_metrics": suggestion_info.get("keyMetrics", response.get("key_metrics", [])),
                "confidence": response.get("confidence", 0.0),
                "style": suggestion_info.get("style"),
                "language": language_info.get("detected"),
                "quality_passed": quality_info.get("passed"),
                "quality_score": quality_info.get("score"),
                "quality_issues": quality_info.get("issues", []),
                "latency_ms": response.get("latency_ms"),
                "processing_full_response": False,
                "bullets_latency_ms": response.get("latency_ms"),
                "full_latency_ms": response.get("latency_ms"),
                "time_to_first_answer_ms": response.get("latency_ms"),
                "time_to_refined_answer_ms": response.get("latency_ms"),
                "normalized_family": debug_info.get("normalized_family"),
                "normalized_primary_ask": debug_info.get("normalized_primary_ask"),
                "normalized_secondary_asks": debug_info.get("normalized_secondary_asks"),
                "normalized_answer_contract": debug_info.get("normalized_answer_contract"),
                "normalized_metrics_policy": debug_info.get("normalized_metrics_policy"),
                "normalizer_confidence": debug_info.get("normalizer_confidence"),
                "normalizer_latency_ms": prepared_context.latency_ms if prepared_context is not None else debug_info.get("normalizer_latency_ms"),
                "fallback_used": fallback_used,
                "live_turn_count": len(snapshot.conversation_history),
                "normalizer_signature": prepared_context.signature if prepared_context is not None else snapshot.signature,
                "normalizer_version": (
                    prepared_context.version if prepared_context is not None
                    else None
                ),
                "cache_hit": snapshot.cache_hit,
                "cache_age_ms": live_cache_age_ms,
                "time_to_summary_ms": (
                    prepared_context.latency_ms if prepared_context is not None
                    else None
                ),
                "prepared_context_version": prepared_context.version if prepared_context is not None else None,
                "prepared_context_signature": prepared_context.signature if prepared_context is not None else None,
                "prepared_context_age_ms": live_cache_age_ms,
                "prepared_context_cache_hit": snapshot.cache_hit,
                "cache_signature_matches_current": bool(
                    prepared_context is not None and prepared_context.signature == snapshot.signature
                ),
                "effective_turn_count": prepared_context.effective_turn_count if prepared_context is not None else len(snapshot.conversation_history),
                "latest_turn_included": prepared_context.latest_turn_included if prepared_context is not None else None,
                "plan_stage": prepared_context.plan_stage if prepared_context is not None else None,
                "complexity_class": prepared_context.complexity_class.value if prepared_context is not None else None,
                "answer_shape": prepared_context.answer_shape.value if prepared_context is not None else None,
                "target_length": prepared_context.target_length if prepared_context is not None else None,
                "planner_source": prepared_context.planner_source if prepared_context is not None else None,
                "planner_provider": prepared_context.planner_provider if prepared_context is not None else None,
                "planner_model": prepared_context.planner_model if prepared_context is not None else None,
                "planner_reasoning_summary": prepared_context.reasoning_summary if prepared_context is not None else None,
                "planner_confidence": prepared_context.planner_confidence if prepared_context is not None else None,
                "brain_plan_revision": brain_plan.revision_id if brain_plan is not None else None,
                "brain_plan_confidence": brain_plan.confidence if brain_plan is not None else None,
                "brain_plan_stability": brain_plan.stability_state if brain_plan is not None else None,
                "brain_plan_serve_mode": brain_plan.serve_mode if brain_plan is not None else None,
                "brain_plan_hash": snapshot.plan_hash or None,
                "brain_plan_source": brain_plan.plan_source if brain_plan is not None else None,
                "brain_question_type": brain_plan.question_type if brain_plan is not None else None,
                "brain_tone": brain_plan.tone if brain_plan is not None else None,
                "brain_llm_used": bool(
                    brain_plan is not None and str(brain_plan.plan_source or "").strip().lower() == "llm_fast"
                ),
                "brain_llm_timeout_ms": int(self._live_brain_service_v3.config.llm_timeout_sec * 1000),
                "brain_llm_failure_kind": self._live_brain_last_llm_failure_kind or None,
                "question_completeness": brain_plan.question_completeness if brain_plan is not None else None,
                "raw_detected_asks": list(brain_plan.raw_detected_asks or []) if brain_plan is not None else [],
                "dropped_noise_clauses": list(brain_plan.dropped_noise_clauses or []) if brain_plan is not None else [],
                "stable_plan_reused": bool(
                    brain_plan is not None and str(brain_plan.plan_source or "").strip().lower() == "cached_stable"
                ),
                "compact_evidence_ready": evidence_pack is not None,
                "evidence_pack_mode": evidence_pack.mode if evidence_pack is not None else None,
                "artifact_sanitized": prepared_context.artifact_sanitized if prepared_context is not None else None,
                "sanitized_turn_count": prepared_context.sanitized_turn_count if prepared_context is not None else None,
                "time_to_prepare_ms": prepared_context.latency_ms if prepared_context is not None else None,
                "time_to_base_plan_ms": prepared_context.time_to_base_plan_ms if prepared_context is not None else None,
                "time_to_semantic_plan_ms": prepared_context.time_to_semantic_plan_ms if prepared_context is not None else None,
                "brain_started": self._live_brain_started_at_ms is not None,
                "brain_completed": self._live_brain_last_status == "completed",
                "brain_status": self._live_brain_last_status,
                "brain_failure_reason": self._live_brain_last_failure_reason or None,
                "brain_duration_ms": self._live_brain_last_duration_ms or None,
                "brain_started_at_ms": self._live_brain_started_at_ms,
                "brain_completed_at_ms": self._live_brain_completed_at_ms,
                "draft_ready_at_silence": draft_ready_at_silence,
                "silence_wait_ms": silence_wait_ms,
                "quality_prewarm_wait_ms": quality_prewarm_wait_ms,
                "question_stabilization_wait_ms": stabilization_wait_ms,
                "path_used": debug_info.get("path_used") or path_used,
                "draft_confidence": prepared_context.confidence if prepared_context is not None else response.get("confidence"),
                "time_from_silence_to_shared_core_ms": time_from_silence_to_shared_core_ms,
                "time_from_silence_to_answer_ms": time_from_silence_to_answer_ms,
                "freeze_checkpoint_id": warm_debug.get("freeze_checkpoint_id"),
                "freeze_question_key": warm_debug.get("freeze_question_key"),
                "warm_checkpoint_id": warm_debug.get("warm_checkpoint_id"),
                "warm_question_key": warm_debug.get("warm_question_key"),
                "warm_exact_match": warm_debug.get("warm_exact_match"),
                "warm_seed_used": warm_debug.get("warm_seed_used"),
                "warm_seed_question_key": warm_debug.get("warm_seed_question_key"),
                "warm_in_flight_at_silence": warm_debug.get("warm_in_flight_at_silence"),
                "warm_completed_before_silence": warm_debug.get("warm_completed_before_silence"),
                "warm_wait_ms": warm_debug.get("warm_wait_ms"),
                "freeze_to_emit_ms": warm_debug.get("freeze_to_emit_ms"),
                "snapshot_source": warm_debug.get("snapshot_source"),
                "brain_refresh_reason": warm_debug.get("brain_refresh_reason"),
                "brain_refresh_count_before_silence": warm_debug.get("brain_refresh_count_before_silence"),
                "brain_refresh_waited_at_freeze_ms": warm_debug.get("brain_refresh_waited_at_freeze_ms"),
                "semantic_revision_id": warm_debug.get("semantic_revision_id"),
                "semantic_revision_hash": warm_debug.get("semantic_revision_hash"),
                "last_interviewer_activity_age_ms": warm_debug.get("last_interviewer_activity_age_ms"),
                "hard_silence_authorized": warm_debug.get("hard_silence_authorized"),
                "silence_anchor_at_ms": warm_debug.get("silence_anchor_at_ms"),
                "silence_anchor_source": warm_debug.get("silence_anchor_source"),
                "completed_turn_processed_at_ms": warm_debug.get("completed_turn_processed_at_ms"),
                "completed_turn_after_last_activity_ms": warm_debug.get("completed_turn_after_last_activity_ms"),
                "silence_gate_scheduled_delay_ms": warm_debug.get("silence_gate_scheduled_delay_ms"),
                "silence_gate_fired_at_ms": warm_debug.get("silence_gate_fired_at_ms"),
                "late_brain_refresh_started_before_silence": warm_debug.get("late_brain_refresh_started_before_silence"),
                "late_brain_refresh_completed_before_silence": warm_debug.get("late_brain_refresh_completed_before_silence"),
                "brain_force_stable_at_freeze": warm_debug.get("brain_force_stable_at_freeze"),
                "brain_immediate_safe_fallback_at_freeze": warm_debug.get("brain_immediate_safe_fallback_at_freeze"),
                "emit_started_at_ms": warm_debug.get("emit_started_at_ms"),
                "emit_stream_started_at_ms": warm_debug.get("emit_stream_started_at_ms"),
                "emit_first_chunk_ms": warm_debug.get("emit_first_chunk_ms"),
                "emit_stream_completed_at_ms": warm_debug.get("emit_stream_completed_at_ms"),
                "emit_stream_chunk_count": warm_debug.get("emit_stream_chunk_count"),
                "emit_stream_partial_salvaged": warm_debug.get("emit_stream_partial_salvaged"),
                "emit_prewarm_started_before_silence": warm_debug.get("emit_prewarm_started_before_silence"),
                "emit_prewarm_count_before_silence": warm_debug.get("emit_prewarm_count_before_silence"),
                "emit_calls_before_silence": warm_debug.get("emit_calls_before_silence"),
                "emit_finalize_calls_after_silence": warm_debug.get("emit_finalize_calls_after_silence"),
                "answer_gate_reason": warm_debug.get("answer_gate_reason"),
                "finalizer_fallback_kind": debug_info.get("finalizer_fallback_kind"),
                "output_sanitizer_applied": debug_info.get("output_sanitizer_applied"),
                "debug": {
                    "history_count": len(snapshot.conversation_history),
                    "conversation_history": snapshot.conversation_history,
                    "question": snapshot.question_text,
                    "consolidated_interviewer_block": (
                        snapshot.brain_snapshot.snapshot_text
                        if snapshot.brain_snapshot is not None
                        else snapshot.question_text
                    ),
                    "resolved_question": (
                        prepared_context.resolved_question
                        if prepared_context is not None
                        else snapshot.question_text
                    ),
                    "primary_ask": (
                        prepared_context.primary_ask
                        if prepared_context is not None
                        else debug_info.get("normalized_primary_ask")
                    ),
                    "secondary_asks": (
                        prepared_context.secondary_asks
                        if prepared_context is not None
                        else debug_info.get("normalized_secondary_asks")
                    ),
                    "asks_in_order": (
                        prepared_context.asks_in_order
                        if prepared_context is not None
                        else []
                    ),
                    "answer_focus": (
                        prepared_context.answer_focus
                        if prepared_context is not None and prepared_context.answer_focus
                        else debug_info.get("answer_focus")
                    ),
                    "answer_style_guidance": (
                        prepared_context.answer_style_guidance
                        if prepared_context is not None and prepared_context.answer_style_guidance
                        else debug_info.get("answer_style_guidance")
                    ),
                    "response_structure": (
                        prepared_context.asks_in_order
                        if prepared_context is not None and prepared_context.asks_in_order
                        else [snapshot.question_text] if snapshot.question_text else []
                    ),
                    "literal_question": (
                        brain_plan.literal_question
                        if brain_plan is not None and str(brain_plan.literal_question or "").strip()
                        else snapshot.question_text
                    ),
                    "contextualized_question": (
                        brain_plan.contextualized_question
                        if brain_plan is not None and str(brain_plan.contextualized_question or "").strip()
                        else snapshot.question_text
                    ),
                    "brain_contract": {
                        "literal_question": (
                            brain_plan.literal_question
                            if brain_plan is not None and str(brain_plan.literal_question or "").strip()
                            else snapshot.question_text
                        ),
                        "contextualized_question": (
                            brain_plan.contextualized_question
                            if brain_plan is not None and str(brain_plan.contextualized_question or "").strip()
                            else snapshot.question_text
                        ),
                        "resolved_question": (
                            prepared_context.resolved_question
                            if prepared_context is not None
                            else snapshot.question_text
                        ),
                        "asks_in_order": (
                            prepared_context.asks_in_order
                            if prepared_context is not None
                            else []
                        ),
                        "coverage_points": list(brain_plan.coverage_points or []) if brain_plan is not None else [],
                        "ask_intents": [item.model_dump(mode="json") for item in list(brain_plan.ask_intents or [])] if brain_plan is not None else [],
                        "interviewer_need": brain_plan.interviewer_need.model_dump(mode="json") if brain_plan is not None else None,
                        "context_focus": list(brain_plan.context_focus or []) if brain_plan is not None else [],
                        "response_requirement": brain_plan.response_requirement.model_dump(mode="json") if brain_plan is not None else None,
                        "answer_contract": brain_plan.answer_contract if brain_plan is not None else None,
                        "delivery_instructions": list(brain_plan.delivery_instructions or []) if brain_plan is not None else [],
                        "answer_focus": (
                            prepared_context.answer_focus
                            if prepared_context is not None and prepared_context.answer_focus
                            else debug_info.get("answer_focus")
                        ),
                        "answer_style_guidance": (
                            prepared_context.answer_style_guidance
                            if prepared_context is not None and prepared_context.answer_style_guidance
                            else debug_info.get("answer_style_guidance")
                        ),
                        "serve_mode": brain_plan.serve_mode if brain_plan is not None else None,
                        "confidence": brain_plan.confidence if brain_plan is not None else None,
                    },
                    "draft_answer": (
                        prepared_context.draft_answer
                        if prepared_context is not None
                        else ""
                    ),
                    "question_stabilization_wait_ms": stabilization_wait_ms,
                    "semantic_blocks_window": snapshot.conversation_history,
                    "latest_display_caption": latest_display_caption or None,
                    "pending_interviewer_candidate": pending_interviewer_candidate or None,
                    "request_payload": snapshot.request_payload,
                    "signature": snapshot.signature,
                    "effective_turn_count": (
                        prepared_context.effective_turn_count
                        if prepared_context is not None
                        else len(snapshot.conversation_history)
                    ),
                    "latest_turn_included": (
                        prepared_context.latest_turn_included
                        if prepared_context is not None
                        else None
                    ),
                    "plan_stage": (
                        prepared_context.plan_stage
                        if prepared_context is not None
                        else None
                    ),
                    "planner_source": (
                        prepared_context.planner_source
                        if prepared_context is not None
                        else None
                    ),
                    "planner_provider": (
                        prepared_context.planner_provider
                        if prepared_context is not None
                        else None
                    ),
                    "planner_model": (
                        prepared_context.planner_model
                        if prepared_context is not None
                        else None
                    ),
                    "planner_reasoning_summary": (
                        prepared_context.reasoning_summary
                        if prepared_context is not None
                        else None
                    ),
                    "planner_confidence": (
                        prepared_context.planner_confidence
                        if prepared_context is not None
                        else None
                    ),
                    "brain_plan_revision": brain_plan.revision_id if brain_plan is not None else None,
                    "brain_plan_confidence": brain_plan.confidence if brain_plan is not None else None,
                    "brain_plan_stability": brain_plan.stability_state if brain_plan is not None else None,
                    "brain_plan_serve_mode": brain_plan.serve_mode if brain_plan is not None else None,
                    "brain_plan_hash": snapshot.plan_hash or None,
                    "brain_plan_source": brain_plan.plan_source if brain_plan is not None else None,
                    "brain_question_type": brain_plan.question_type if brain_plan is not None else None,
                    "brain_tone": brain_plan.tone if brain_plan is not None else None,
                    "brain_response_shape": brain_plan.response_shape if brain_plan is not None else None,
                    "brain_answer_contract": brain_plan.answer_contract if brain_plan is not None else None,
                    "brain_delivery_instructions": list(brain_plan.delivery_instructions or []) if brain_plan is not None else [],
                    "brain_ask_intents": [item.model_dump(mode="json") for item in list(brain_plan.ask_intents or [])] if brain_plan is not None else [],
                    "brain_interviewer_need": brain_plan.interviewer_need.model_dump(mode="json") if brain_plan is not None else None,
                    "brain_context_focus": list(brain_plan.context_focus or []) if brain_plan is not None else [],
                    "brain_response_requirement": brain_plan.response_requirement.model_dump(mode="json") if brain_plan is not None else None,
                    "brain_evidence_depth": brain_plan.evidence_depth if brain_plan is not None else None,
                    "brain_metrics_policy": brain_plan.metrics_policy if brain_plan is not None else None,
                    "brain_company_context_policy": brain_plan.company_context_policy if brain_plan is not None else None,
                    "brain_candidate_context_policy": brain_plan.candidate_context_policy if brain_plan is not None else None,
                    "brain_llm_used": bool(
                        brain_plan is not None and str(brain_plan.plan_source or "").strip().lower() == "llm_fast"
                    ),
                    "brain_llm_timeout_ms": int(self._live_brain_service_v3.config.llm_timeout_sec * 1000),
                    "brain_llm_failure_kind": self._live_brain_last_llm_failure_kind or None,
                    "question_completeness": brain_plan.question_completeness if brain_plan is not None else None,
                    "raw_detected_asks": list(brain_plan.raw_detected_asks or []) if brain_plan is not None else [],
                    "coverage_points": list(brain_plan.coverage_points or []) if brain_plan is not None else [],
                    "dropped_noise_clauses": list(brain_plan.dropped_noise_clauses or []) if brain_plan is not None else [],
                    "stable_plan_reused": bool(
                        brain_plan is not None and str(brain_plan.plan_source or "").strip().lower() == "cached_stable"
                    ),
                    "compact_evidence_ready": evidence_pack is not None,
                    "compact_evidence_pack": evidence_pack.model_dump(mode="json") if evidence_pack is not None else None,
                    "evidence_pack_mode": evidence_pack.mode if evidence_pack is not None else None,
                    "path_used": debug_info.get("path_used") or path_used,
                    "normalized_answer_contract": debug_info.get("normalized_answer_contract"),
                    "finalizer_fallback_kind": debug_info.get("finalizer_fallback_kind"),
                    "finalizer_llm_called": debug_info.get("finalizer_llm_called"),
                    "finalizer_model": debug_info.get("finalizer_model"),
                    "finalizer_configured_model": debug_info.get("finalizer_configured_model"),
                    "output_sanitizer_applied": debug_info.get("output_sanitizer_applied"),
                    "cache_hit": snapshot.cache_hit,
                    "cache_signature_matches_current": bool(
                        prepared_context is not None and prepared_context.signature == snapshot.signature
                    ),
                    "current_signature": snapshot.signature,
                    "prepared_context_signature": prepared_context.signature if prepared_context is not None else None,
                    "draft_ready_at_silence": draft_ready_at_silence,
                    "brain_status": self._live_brain_last_status,
                    "brain_failure_reason": self._live_brain_last_failure_reason or None,
                    "brain_duration_ms": self._live_brain_last_duration_ms or None,
                    "brain_started_at_ms": self._live_brain_started_at_ms,
                    "brain_completed_at_ms": self._live_brain_completed_at_ms,
                    "silence_wait_ms": silence_wait_ms,
                    "time_to_prepare_ms": (
                        prepared_context.latency_ms
                        if prepared_context is not None
                        else None
                    ),
                    "time_to_base_plan_ms": (
                        prepared_context.time_to_base_plan_ms
                        if prepared_context is not None
                        else None
                    ),
                    "time_to_semantic_plan_ms": (
                        prepared_context.time_to_semantic_plan_ms
                        if prepared_context is not None
                        else None
                    ),
                    "time_from_silence_to_answer_ms": time_from_silence_to_answer_ms,
                    "fallback_used": fallback_used,
                    "stale_snapshot_discarded": stale_snapshot_discarded,
                    "freeze_checkpoint_id": warm_debug.get("freeze_checkpoint_id"),
                    "freeze_question_key": warm_debug.get("freeze_question_key"),
                    "warm_checkpoint_id": warm_debug.get("warm_checkpoint_id"),
                    "warm_question_key": warm_debug.get("warm_question_key"),
                    "warm_exact_match": warm_debug.get("warm_exact_match"),
                    "warm_seed_used": warm_debug.get("warm_seed_used"),
                    "warm_seed_question_key": warm_debug.get("warm_seed_question_key"),
                    "warm_in_flight_at_silence": warm_debug.get("warm_in_flight_at_silence"),
                    "warm_completed_before_silence": warm_debug.get("warm_completed_before_silence"),
                    "warm_wait_ms": warm_debug.get("warm_wait_ms"),
                    "freeze_to_emit_ms": warm_debug.get("freeze_to_emit_ms"),
                    "snapshot_source": warm_debug.get("snapshot_source"),
                    "brain_refresh_reason": warm_debug.get("brain_refresh_reason"),
                    "brain_refresh_count_before_silence": warm_debug.get("brain_refresh_count_before_silence"),
                    "brain_refresh_waited_at_freeze_ms": warm_debug.get("brain_refresh_waited_at_freeze_ms"),
                    "semantic_revision_id": warm_debug.get("semantic_revision_id"),
                    "semantic_revision_hash": warm_debug.get("semantic_revision_hash"),
                    "last_interviewer_activity_age_ms": warm_debug.get("last_interviewer_activity_age_ms"),
                    "hard_silence_authorized": warm_debug.get("hard_silence_authorized"),
                    "silence_anchor_at_ms": warm_debug.get("silence_anchor_at_ms"),
                    "silence_anchor_source": warm_debug.get("silence_anchor_source"),
                    "completed_turn_processed_at_ms": warm_debug.get("completed_turn_processed_at_ms"),
                    "completed_turn_after_last_activity_ms": warm_debug.get("completed_turn_after_last_activity_ms"),
                    "silence_gate_scheduled_delay_ms": warm_debug.get("silence_gate_scheduled_delay_ms"),
                    "silence_gate_fired_at_ms": warm_debug.get("silence_gate_fired_at_ms"),
                    "late_brain_refresh_started_before_silence": warm_debug.get("late_brain_refresh_started_before_silence"),
                    "late_brain_refresh_completed_before_silence": warm_debug.get("late_brain_refresh_completed_before_silence"),
                    "brain_force_stable_at_freeze": warm_debug.get("brain_force_stable_at_freeze"),
                    "brain_immediate_safe_fallback_at_freeze": warm_debug.get("brain_immediate_safe_fallback_at_freeze"),
                    "emit_started_at_ms": warm_debug.get("emit_started_at_ms"),
                    "emit_stream_started_at_ms": warm_debug.get("emit_stream_started_at_ms"),
                    "emit_first_chunk_ms": warm_debug.get("emit_first_chunk_ms"),
                    "emit_stream_completed_at_ms": warm_debug.get("emit_stream_completed_at_ms"),
                    "emit_stream_chunk_count": warm_debug.get("emit_stream_chunk_count"),
                    "emit_stream_partial_salvaged": warm_debug.get("emit_stream_partial_salvaged"),
                    "emit_prewarm_started_before_silence": warm_debug.get("emit_prewarm_started_before_silence"),
                    "emit_prewarm_count_before_silence": warm_debug.get("emit_prewarm_count_before_silence"),
                    "emit_calls_before_silence": warm_debug.get("emit_calls_before_silence"),
                    "emit_finalize_calls_after_silence": warm_debug.get("emit_finalize_calls_after_silence"),
                    "answer_gate_reason": warm_debug.get("answer_gate_reason"),
                },
            }
            await _send_final_suggestion_with_commit(
                websocket=self._websocket,
                payload=suggestion_payload,
                tracker=getattr(self._pipeline, "conversation_tracker", None),
                question_text=snapshot.question_text,
                interviewer_generation=self._latest_interviewer_generation,
                session_id=self._session_id,
            )
            self._mark_auto_suggestion_served(snapshot=snapshot)
            
            print(
                "[AUTO][SILENCE] suggestion_emitted "
                f"session_id={self._session_id} "
                f"latency_ms={response.get('latency_ms')}"
            )
            self._last_suggestion_at = perf_counter()
            if self._stream_started_at is not None and self._suggestion_emitted_at_ms is None:
                self._suggestion_emitted_at_ms = int((perf_counter() - self._stream_started_at) * 1000)
                print(
                    "[WS][STT] suggestion_emitted "
                    f"session_id={self._session_id} "
                    f"timestamp_ms={self._suggestion_emitted_at_ms}"
                )
            if self._stt_adapter is not None and hasattr(self._stt_adapter, "mark_downstream_complete"):
                self._stt_adapter.mark_downstream_complete()
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            await self._websocket.send_json({
                "type": "error",
                "message": f"Auto-suggestion error: {str(e)}",
            })
        finally:
            self._downstream_in_flight = False
            self._silence_detector.record_completion()

    async def _process_completed_turn(self, turn: SpeakerTurn) -> None:
        skip_duplicate_check = bool((turn.metadata or {}).get("skip_duplicate_check"))
        if not skip_duplicate_check and self._is_duplicate_turn(turn):
            print(
                "[TURN][ASSEMBLY] duplicate_turn "
                f"session_id={self._session_id} text='{(turn.text or '')[:120]}'"
            )
            return
        if turn.speaker != "interviewer":
            self._finalize_current_live_interviewer_block(reason="non_interviewer_turn")
            self._cancel_suggestion_debounce()
            self._cancel_hard_silence_gate()
            self._cancel_late_brain_readiness_refresh()
            print(
                "[WS][TURN] skip_downstream "
                f"session_id={self._session_id} reason=non_interviewer speaker={turn.speaker}"
            )
            return

        self._latest_interviewer_generation += 1
        generation_token = self._latest_interviewer_generation
        self._refresh_interviewer_gate_without_reanchoring(
            gate_reason="completed_turn_waiting_for_silence",
            turn=turn,
        )
        print(
            "[WS][TURN] interviewer_generation_advanced "
            f"session_id={self._session_id} generation={generation_token} "
            f"text='{(turn.text or '')[:120]}'"
        )

        return

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

        self._cancel_suggestion_debounce()
        for task in list(self._background_tasks):
            if not task.done():
                task.cancel()
        if self._background_tasks:
            with contextlib.suppress(Exception):
                await asyncio.gather(*list(self._background_tasks), return_exceptions=True)
        self._background_tasks.clear()

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
            source_hint=self._latest_source,
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
        self._update_interviewer_display_caption(
            text=transcript_text,
            is_partial=not is_final,
            utterance_complete=bool(getattr(event, "utterance_complete", False)),
            speaker=speaker,
        )
        if speaker == "interviewer" and self._is_interviewer_caption_source(self._latest_source):
            self._schedule_live_preparation_refresh_debounced()
        
        print(
            f"[WS][DISPLAY] live_caption session_id={self._session_id} "
            f"is_partial={not is_final} speaker={speaker} text='{transcript_text[:80]}'"
        )

    async def _handle_transcription_event(self, event: Any) -> None:
        event_type = getattr(event, "event_type", None)
        is_final = bool(getattr(event, "is_final", False))
        utterance_complete = bool(getattr(event, "utterance_complete", False))
        transcript_text = (getattr(event, "text", "") or "").strip()

        if not transcript_text:
            # Some STT providers can signal the end of an utterance without
            # attaching a final transcript fragment. In that case we should try
            # to close the current turn instead of silently dropping the event.
            if utterance_complete or event_type in {"utterance_end", "utteranceend"}:
                if self._is_interviewer_caption_source(self._latest_source):
                    completed_live_text = self._complete_interviewer_turn_candidate(
                        reason="utterance_complete_signal"
                    )
                    if completed_live_text:
                        self._ingest_completed_live_caption_turn(
                            text=completed_live_text,
                            event_time=time.time(),
                            language="en",
                            provider_metadata={},
                        )
                completed_turn = self._turn_assembler.force_complete(
                    reason="utterance_complete_signal",
                    end_time=time.time(),
                )
                self._cancel_turn_flush()
                if completed_turn is not None:
                    self._record_turn_event(completed_turn)
                    self._schedule_completed_turn_processing(completed_turn)
            return

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
            source_hint=self._latest_source,
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

        if speaker == "candidate":
            self._cancel_suggestion_debounce()

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
            self._record_ui_equivalent_transcript_entry(
                text=transcript_text,
                speaker=self._conversation_history_speaker_for_transcript_event(speaker=speaker),
                is_final=is_final,
                timestamp_ms=int(event_time * 1000),
            )

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
            # Keep a pause-based flush armed even when the provider never emits
            # a clean final transcript for the utterance.
            return

        # Keep explicit fallback/error behavior truthful: final STT error payloads are
        # surfaced as transcript text and do not trigger pipeline processing.
        if transcript_text.startswith("[STT Error:"):
            self._provider_errors.append(transcript_text)
            print(f"[WS][STT] provider_error session_id={self._session_id} detail={transcript_text}")
            if self._stt_adapter is not None and hasattr(self._stt_adapter, "mark_terminal_failure"):
                self._stt_adapter.mark_terminal_failure("provider_error_transcript")
            return

        if is_final and self._is_interviewer_caption_source(self._latest_source):
            completed_live_text = self._update_interviewer_turn_candidate(
                transcript_text,
                "interviewer",
                is_final,
                utterance_complete,
            )
            if completed_live_text:
                self._ingest_completed_live_caption_turn(
                    text=completed_live_text,
                    event_time=event_time,
                    language=language,
                    provider_metadata=provider_metadata,
                )
            else:
                self._schedule_interviewer_turn_candidate_flush(
                    language=language,
                    provider_metadata=provider_metadata,
                )
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
        self._schedule_completed_turn_processing(assembled_turn)


def _is_generic_candidate_profile_payload(candidate: dict[str, Any]) -> bool:
    summary = str(candidate.get("summary") or "").strip()
    normalized_skills = [str(item).strip().lower() for item in (candidate.get("skills") or []) if str(item).strip()]
    normalized_achievements = [
        str(item).strip().lower() for item in (candidate.get("achievements") or []) if str(item).strip()
    ]
    return (
        bool(summary)
        and re.match(r"^Experienced professional with \d+\+ years in the industry\.?$", summary, re.IGNORECASE)
        is not None
        and normalized_skills == ["leadership", "strategy", "team building"]
        and normalized_achievements == ["led teams", "delivered projects", "drove growth"]
    )


def _candidate_payload_issue(candidate: dict[str, Any]) -> Optional[str]:
    name = str(candidate.get("name") or "").strip()
    current_role = str(candidate.get("current_role") or candidate.get("currentRole") or "").strip()
    current_company = str(
        candidate.get("company") or candidate.get("current_company") or candidate.get("currentCompany") or ""
    ).strip()
    summary = str(candidate.get("summary") or "").strip()
    skills = [str(item).strip() for item in (candidate.get("skills") or []) if str(item).strip()]
    achievements = [str(item).strip() for item in (candidate.get("achievements") or []) if str(item).strip()]

    if _is_generic_candidate_profile_payload(candidate):
        return (
            "Candidate profile still matches the old generic placeholder. Refresh the candidate profile from the CV "
            "in Prepare before requesting coaching."
        )
    if not name:
        return "Candidate name is required. Complete it in Prepare before requesting coaching."
    if not current_role:
        return "Candidate current role is required. Complete it in Prepare before requesting coaching."
    if not current_company:
        return "Candidate current company is required. Complete it in Prepare before requesting coaching."
    if not (summary or skills or achievements):
        return (
            "Candidate profile is missing real evidence. Refresh it from the current CV in Prepare or complete the "
            "summary, skills, and achievements manually before requesting coaching."
        )
    return None


def _target_payload_issue(company: dict[str, Any]) -> Optional[str]:
    company_name = str(company.get("name") or company.get("companyName") or "").strip()
    role_title = str(company.get("role_title") or company.get("roleTitle") or company.get("positionTitle") or "").strip()
    if not company_name:
        return "Target company is required. Complete it in Prepare before requesting coaching."
    if not role_title:
        return "Target role is required. Complete it in Prepare before requesting coaching."
    return None


@app.post("/api/suggest")
async def suggest_response(request: SuggestRequest):
    """
    Generate interview response suggestion.
    
    This is the main coaching endpoint that:
    1. Analyzes the question
    2. Retrieves relevant evidence from profile
    3. Generates response in the selected style
    4. Validates through quality gate
    
    Returns explicit 'mode' field indicating the runtime response mode.
    """
    from pipeline.steps.language_policy import LanguagePolicy
    from pipeline.steps.ask_normalizer import AskNormalizer, apply_ask_brief_policy
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
    question_text = _strip_transcript_artifacts(question_text)
    preserve_question_text = bool(
        request_data.get("preserve_question_text")
        or request_data.get("_preserve_question_text")
    )
    live_prepared_context_payload = request_data.get("_live_prepared_context")
    live_prepared_context: Optional[LivePreparedContext] = None
    if isinstance(live_prepared_context_payload, dict):
        try:
            live_prepared_context = LivePreparedContext.model_validate(live_prepared_context_payload)
        except Exception as e:
            print(f"[/api/suggest] Warning: invalid _live_prepared_context payload: {e}")
    delivery_mode_override = str(request_data.get("_delivery_mode_override") or "").strip().lower()
    
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
            history_count = 5
    else:
        history_count = 5
    
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
        conversation_history_from_session, question_text, frontend_context_bundle = _build_frontend_suggest_context(
            frontend_conversation_history=frontend_conversation_history,
            question_text=question_text,
            preserve_question_text=preserve_question_text,
        )
        print(f"[/api/suggest] Loaded {len(conversation_history_from_session)} active turns from frontend request")
        # Log each turn for debugging
        for i, turn in enumerate(conversation_history_from_session):
            print(f"[/api/suggest][DEBUG] Frontend turn {i}: speaker={turn['speaker']}, text='{turn['text'][:50]}...'")
        resolved_question = frontend_context_bundle.get("primary_question", "")
        if resolved_question:
            print(
                f"[/api/suggest] Resolved primary question from frontend history "
                f"source={frontend_context_bundle.get('primary_question_source')} "
                f"question='{question_text[:120]}...'"
            )
    
    if session_id and not conversation_history_from_session:
        try:
            # OPTION 1: Check active pipeline's conversation_tracker (in-memory, for live sessions)
            active_pipeline = _active_pipelines.get(session_id)
            if active_pipeline and hasattr(active_pipeline, 'conversation_tracker'):
                print(f"[/api/suggest] Found active pipeline for session {session_id}")
                conversation_history_from_session, resolved_question_text, tracker_context_bundle = _build_active_pipeline_suggest_context(
                    conversation_tracker=active_pipeline.conversation_tracker,
                    history_count=history_count,
                    question_text=question_text,
                    preserve_question_text=preserve_question_text,
                )
                recent_turns = conversation_history_from_session
                recent_exchanges = [
                    {
                        "interviewer_utterance": turn.get("text", ""),
                        "candidate_response": "",
                        "timestamp": turn.get("timestamp", datetime.now().isoformat()),
                    }
                    for turn in recent_turns
                ]
                print(f"[/api/suggest] Got {len(recent_turns)} turns from normalized active tracker bundle")
                for i, turn in enumerate(recent_turns):
                    print(
                        f"[/api/suggest][DEBUG] Active turn {i}: "
                        f"speaker={turn.get('speaker', 'unknown')} "
                        f"text='{str(turn.get('text', ''))[:50]}...'"
                    )
                if resolved_question_text and resolved_question_text != question_text:
                    question_text = resolved_question_text
                    print(
                        f"[/api/suggest] Resolved primary question from active tracker "
                        f"source={tracker_context_bundle.get('primary_question_source')} "
                        f"question='{question_text[:120]}...'"
                    )
                
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
                conversation_history_from_session, resolved_question_text, history_context_bundle = _build_history_based_suggest_context(
                    recent_exchanges=recent_exchanges,
                    question_text=question_text,
                    preserve_question_text=preserve_question_text,
                )
                if resolved_question_text and resolved_question_text != question_text:
                    question_text = resolved_question_text
                    print(
                        f"[/api/suggest] Resolved primary question from history "
                        f"source={history_context_bundle.get('primary_question_source')} "
                        f"question='{question_text[:120]}...'"
                    )
                print(
                    f"[/api/suggest] Loaded {len(conversation_history_from_session)} active turns "
                    f"from session {session_id}"
                )
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
    interviewer = (
        request_data.get("interviewer_profile")
        or request_data.get("interviewer")
        or {}
    )
    target_context = (
        request_data.get("target_context")
        or request_data.get("targetContext")
        or {}
    )
    explicit_target_company = (
        request_data.get("target_company_info")
        or request_data.get("targetCompanyInfo")
        or {}
    )
    explicit_target_role = (
        request_data.get("target_role_info")
        or request_data.get("targetRoleInfo")
        or {}
    )
    target_company = target_context.get("company") if isinstance(target_context, dict) else {}
    target_role = target_context.get("role") if isinstance(target_context, dict) else {}
    target_interviewer = target_context.get("interviewer") if isinstance(target_context, dict) else {}

    candidate_name = request_data.get("candidate_name") or request_data.get("candidateName")
    role_title = request_data.get("role") or request_data.get("role_title") or request_data.get("roleTitle")
    company_name = request_data.get("company_name") or request_data.get("companyName")
    interviewer_name = request_data.get("interviewer_name") or request_data.get("interviewerName")

    if isinstance(candidate, str):
        candidate = {"name": candidate}
    if isinstance(company, str):
        company = {"companyName": company}
    if isinstance(interviewer, str):
        interviewer = {"name": interviewer}
    if not isinstance(target_company, dict):
        target_company = {}
    if not isinstance(target_role, dict):
        target_role = {}
    if not isinstance(target_interviewer, dict):
        target_interviewer = {}
    if not isinstance(explicit_target_company, dict):
        explicit_target_company = {}
    if not isinstance(explicit_target_role, dict):
        explicit_target_role = {}

    if explicit_target_company:
        target_company = {
            **target_company,
            **explicit_target_company,
        }
    if explicit_target_role:
        target_role = {
            **target_role,
            **explicit_target_role,
        }

    if target_company:
        company = {
            **company,
            **target_company,
        }
    if target_role:
        company = {
            **company,
            "roleTitle": target_role.get("title") or target_role.get("roleTitle") or target_role.get("positionTitle") or "",
            "positionTitle": target_role.get("title") or target_role.get("roleTitle") or target_role.get("positionTitle") or "",
            "roleLevel": target_role.get("level") or target_role.get("roleLevel") or "",
            "jobDescription": target_role.get("description") or target_role.get("jobDescription") or "",
            "positionDescription": target_role.get("description") or target_role.get("positionDescription") or "",
            "roleRequirements": target_role.get("requirements") or target_role.get("roleRequirements") or [],
            "positionRequirements": target_role.get("requirements") or target_role.get("positionRequirements") or [],
            "roleResponsibilities": target_role.get("responsibilities") or target_role.get("roleResponsibilities") or [],
            "interviewType": target_role.get("interview_type") or target_role.get("interviewType") or "",
            "interviewFocus": target_role.get("interview_focus") or target_role.get("interviewFocus") or [],
            "max_words": target_role.get("max_words") or target_role.get("maxWords") or None,
        }
    if target_interviewer:
        interviewer = {
            **interviewer,
            **target_interviewer,
        }

    if candidate_name and not candidate.get("name"):
        candidate["name"] = candidate_name
    if company_name and not company.get("companyName"):
        company["companyName"] = company_name
    if role_title and not company.get("roleTitle"):
        company["roleTitle"] = role_title
    if interviewer_name and not interviewer.get("name"):
        interviewer["name"] = interviewer_name

    candidate_issue = _candidate_payload_issue(candidate)
    if candidate_issue:
        return {
            "success": False,
            "error": candidate_issue,
            "mode": "error",
        }
    target_issue = _target_payload_issue(company)
    if target_issue:
        return {
            "success": False,
            "error": target_issue,
            "mode": "error",
        }
    
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
    candidate_company = (
        candidate.get("company")
        or candidate.get("current_company")
        or candidate.get("currentCompany")
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
        "company": candidate_company,
        "current_company": candidate_company,
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

    interviewer_role_title = (
        interviewer.get("role_title")
        or interviewer.get("roleTitle")
        or ""
    )
    interviewer_company = (
        interviewer.get("company")
        or interviewer.get("companyName")
        or company.get("companyName")
        or company.get("name")
        or ""
    )
    interviewer_background_summary = (
        interviewer.get("background_summary")
        or interviewer.get("backgroundSummary")
        or ""
    )
    interviewer_expertise = _as_list(interviewer.get("expertise", []))
    interviewer_career_highlights = _as_list(
        interviewer.get("career_highlights")
        or interviewer.get("careerHighlights")
        or []
    )
    interviewer_focus_areas = _as_list(
        interviewer.get("likely_focus_areas")
        or interviewer.get("likelyFocusAreas")
        or []
    )
    interviewer_communication_style = (
        interviewer.get("communication_style")
        or interviewer.get("communicationStyle")
        or ""
    )
    interviewer_notes = interviewer.get("notes") or ""
    interviewer_source_urls = _as_list(interviewer.get("source_urls") or interviewer.get("sourceUrls") or [])

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

    interviewer_context = {
        "name": interviewer.get("name") or "",
        "role_title": interviewer_role_title,
        "roleTitle": interviewer_role_title,
        "company": interviewer_company,
        "companyName": interviewer_company,
        "background_summary": interviewer_background_summary,
        "backgroundSummary": interviewer_background_summary,
        "expertise": interviewer_expertise,
        "career_highlights": interviewer_career_highlights,
        "careerHighlights": interviewer_career_highlights,
        "likely_focus_areas": interviewer_focus_areas,
        "likelyFocusAreas": interviewer_focus_areas,
        "communication_style": interviewer_communication_style,
        "communicationStyle": interviewer_communication_style,
        "notes": interviewer_notes,
        "source_urls": interviewer_source_urls,
        "sourceUrls": interviewer_source_urls,
        "context_id": request_data.get("interviewer_context_id") or "",
    }

    normalized_target_context = {
        "company": {
            "name": normalized_company_name,
            "industry": company_industry,
            "size": company.get("size") or "",
            "culture": company_culture,
            "mission": company.get("mission") or "",
            "values": company_values,
            "tech_stack": company_tech_stack,
            "summary": company.get("companySummary") or company.get("company_summary") or company_description,
            "products_services": _as_list(company.get("productsServices") or company.get("products_services") or []),
            "recent_focus": _as_list(company.get("recentFocus") or company.get("recent_focus") or []),
            "source_urls": _as_list(company.get("sourceUrls") or company.get("source_urls") or []),
            "research_notes": company.get("researchNotes") or company.get("research_notes") or "",
            "context_id": request_data.get("company_context_id") or "",
        },
        "role": {
            "title": normalized_role_title,
            "level": company.get("roleLevel") or company.get("role_level") or "",
            "description": normalized_job_description,
            "requirements": company_requirements,
            "responsibilities": role_responsibilities,
            "interview_type": interview_type,
            "interview_focus": interview_focus,
            "max_words": max_words,
        },
        "interviewer": interviewer_context,
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
        "interviewer": interviewer_context,
        "target_context": normalized_target_context,
        "company_context_id": request_data.get("company_context_id") or "",
        "interviewer_context_id": request_data.get("interviewer_context_id") or "",
    }
    
    try:
        start_perf = perf_counter()

        # Direct manual path (no audio/STT/turn assembler)
        language_policy = LanguagePolicy(
            user_preference=request_language if request_language in {"es", "en"} else None
        )
        ask_normalizer = AskNormalizer()
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
            interview_type=interview_type,
            conversation_history=conversation_history_from_session if conversation_history_from_session else [],
            topics_covered=[],
            metrics_used=[],
        )

        normalized_turns = [
            {
                "speaker": turn.get("speaker", "unknown"),
                "text": turn.get("text", ""),
            }
            for turn in conversation_history_from_session
        ]
        if live_prepared_context is not None and live_prepared_context.ask_brief is not None:
            ask_brief = live_prepared_context.ask_brief
        else:
            ask_brief = ask_normalizer.normalize(
                question_text,
                normalized_turns,
                delivery_mode="manual",
            )

        live_fast_path = bool(
            delivery_mode_override == "live_manual"
            and live_prepared_context is not None
            and ask_brief is not None
        )

        if live_fast_path:
            live_prepared_context = _canonicalize_live_prepared_context(live_prepared_context) or live_prepared_context
            if live_prepared_context is not None and live_prepared_context.ask_brief is not None:
                ask_brief = live_prepared_context.ask_brief
            print(
                "[/api/suggest] live_fast_path enabled "
                f"session_id={session_id} family={ask_brief.answer_family.value} "
                f"complexity={live_prepared_context.complexity_class.value}"
            )
            question_analysis = _build_live_fast_question_analysis(
                question_text=question_text,
                ask_brief=ask_brief,
                live_prepared_context=live_prepared_context,
                conversation_history=conversation_history_from_session,
                delivery_mode="live_manual",
            )
            evidence = _build_live_fast_evidence(
                candidate_context=candidate_context,
                company_context=company_context,
                interviewer_context=interviewer_context,
                ordered_focus=live_prepared_context.asks_in_order if live_prepared_context is not None else None,
            )
        else:
            question_analyzer = QuestionAnalyzer(use_llm=use_real)
            retrieval_planner = RetrievalPlanner()
            evidence_retriever = EvidenceRetriever(
                mode=RetrieverMode.AUTO if use_real else RetrieverMode.DEMO,
                force_demo=not use_real,
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
                company_context_id=interview_config.get("company_context_id", ""),
                interviewer_context_id=interview_config.get("interviewer_context_id", ""),
            )
            evidence = await evidence_retriever.retrieve(retrieval_plan)

        assembled_context = AssembledContext(
            question=question_text,
            analysis=question_analysis,
            ask_brief=ask_brief if live_prepared_context is not None else None,
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
            delivery_mode=delivery_mode_override or "manual",
            max_words=max_words,  # NEW: Length control
            live_prepared_context=live_prepared_context,
        )

        # DEBUG: Build prompt with the same effective style the composer will use.
        effective_style = question_analysis.recommended_style if question_analysis else response_style
        debug_prompt = response_composer._build_prompt(assembled_context, effective_style)
        debug_system_prompt = response_composer._get_system_prompt(effective_style)

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
                "questionMode": question_analysis.question_mode.value,
                "responseMode": question_analysis.response_mode.value,
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
                "styleReason": question_analysis.style_reason,
                "whyMetricsRequired": question_analysis.why_metrics_required,
                "normalizedFamily": ask_brief.answer_family.value,
                "normalizedPrimaryAsk": ask_brief.primary_ask,
                "normalizedSecondaryAsks": ask_brief.secondary_asks,
                "normalizedAnswerContract": ask_brief.answer_contract.value,
                "normalizedMetricsPolicy": ask_brief.metrics_policy.value,
                "normalizerConfidence": ask_brief.confidence,
                "normalizerLatencyMs": ask_brief.latency_ms,
                "fallbackUsed": ask_brief.fallback_used,
                "rewriteTriggered": bool(suggested_metadata.get("live_alignment_rewrite_applied")),
                "rewriteReason": "; ".join(suggested_metadata.get("live_alignment_issues", []) or []),
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
                "question_mode": question_analysis.question_mode.value,
                "response_mode": question_analysis.response_mode.value,
                "style_reason": question_analysis.style_reason,
                "why_metrics_required": question_analysis.why_metrics_required,
                "normalized_family": ask_brief.answer_family.value,
                "normalized_primary_ask": ask_brief.primary_ask,
                "normalized_secondary_asks": ask_brief.secondary_asks,
                "normalized_answer_contract": ask_brief.answer_contract.value,
                "normalized_metrics_policy": ask_brief.metrics_policy.value,
                "normalizer_confidence": ask_brief.confidence,
                "normalizer_latency_ms": ask_brief.latency_ms,
                "fallback_used": ask_brief.fallback_used,
                "complexity_class": live_prepared_context.complexity_class.value if live_prepared_context is not None else None,
                "answer_shape": live_prepared_context.answer_shape.value if live_prepared_context is not None else None,
                "target_length": live_prepared_context.target_length if live_prepared_context is not None else None,
                "planner_source": live_prepared_context.planner_source if live_prepared_context is not None else None,
                "planner_provider": live_prepared_context.planner_provider if live_prepared_context is not None else None,
                "planner_model": live_prepared_context.planner_model if live_prepared_context is not None else None,
                "planner_reasoning_summary": live_prepared_context.reasoning_summary if live_prepared_context is not None else None,
                "live_fast_path_used": live_fast_path,
                "live_fast_evidence_count": len(evidence) if live_fast_path else None,
                "rewrite_triggered": bool(suggested_metadata.get("live_alignment_rewrite_applied")),
                "rewrite_reason": "; ".join(suggested_metadata.get("live_alignment_issues", []) or []),
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
    """
    from pipeline.steps.cv_analyzer import CVAnalyzer
    
    cv_text = request.get("cvText") or request.get("cv_text", "")
    
    if not cv_text:
        return {"success": False, "error": "CV text required"}
    
    analyzer = CVAnalyzer.from_environment()
    result = await analyzer.analyze(cv_text)

    if not result.success:
        return {
            "success": False,
            "mode": "unavailable",
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

    return response


@app.post("/api/coach/analyze-cv")
async def analyze_cv_proxy(request: dict):
    """Alias endpoint to match /api/coach/analyze-cv clients."""
    return await analyze_cv(request)


# =============================================================================
# INSIGHTS ENDPOINTS - CV strengthening + role alignment
# =============================================================================


async def _persist_candidate_insights_context(
    *,
    workspace_id: str,
    run_id: str,
    workspace: dict[str, Any],
    apply_result: dict[str, Any],
) -> dict[str, Any]:
    from storage.database import execute_query, execute_scalar
    from storage.embedding_utils import build_query_embedding, vector_literal

    preview = apply_result.get("approved_context_preview") or {}
    summary = _compact_text(str(preview.get("summary") or ""), limit=4000)
    reusable_evidence = _clean_string_list(preview.get("reusable_evidence") or [])
    project_evidence = _clean_string_list(preview.get("project_evidence") or [])
    focus_areas = _clean_string_list(preview.get("focus_areas") or [])
    top_role_signals = _clean_string_list(preview.get("top_role_signals") or [])
    approved_change_titles = _clean_string_list(preview.get("approved_change_titles") or [])

    if not summary and not reusable_evidence and not project_evidence:
        return {
            "saved": False,
            "deleted": {"document_chunks": 0},
            "indexed": {"document_chunks": 0},
        }

    context_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"candidate-insights:{workspace_id}"))
    candidate_name = (
        apply_result.get("candidate_profile", {}).get("name")
        or workspace.get("input_snapshot", {}).get("candidate_profile", {}).get("name")
        or preview.get("candidate_name")
        or "Candidate"
    )

    payload = {
        "workspace_id": workspace_id,
        "run_id": run_id,
        "candidate_name": candidate_name,
        "summary": summary,
        "focus_areas": focus_areas,
        "reusable_evidence": reusable_evidence,
        "project_evidence": project_evidence,
        "top_role_signals": top_role_signals,
        "approved_change_titles": approved_change_titles,
        "benchmark_source": workspace.get("benchmark_source", {}),
        "primary_scores": workspace.get("primary_scores", {}),
        "overall_match": workspace.get("overall_match", 0),
        "support_level": workspace.get("support_level", "unsupported"),
        "answers": workspace.get("answers", {}),
    }
    raw_text = _compact_text(
        "\n".join(
            line
            for line in [
                summary,
                f"Focus areas: {', '.join(focus_areas)}" if focus_areas else "",
                f"Reusable evidence: {' | '.join(reusable_evidence)}" if reusable_evidence else "",
                f"Project evidence: {' | '.join(project_evidence)}" if project_evidence else "",
                f"Top role signals: {', '.join(top_role_signals)}" if top_role_signals else "",
            ]
            if line
        ),
        limit=12000,
    )

    profile_exists = await execute_scalar(
        "SELECT id FROM context_profiles WHERE id = $1",
        context_id,
    )
    deleted_chunks = 0
    payload_json = json.dumps(payload)
    if profile_exists:
        deleted_rows = await execute_query(
            "DELETE FROM context_document_chunks WHERE context_id = $1 RETURNING id",
            context_id,
        )
        deleted_chunks = len(deleted_rows) if deleted_rows else 0
        await execute_query(
            """
            UPDATE context_profiles
            SET kind = $2, name = $3, payload = $4::jsonb, source_urls = $5::text[],
                raw_text = $6, updated_at = NOW()
            WHERE id = $1
            """,
            context_id,
            "candidate_insights",
            candidate_name,
            payload_json,
            [],
            raw_text,
        )
    else:
        await execute_query(
            """
            INSERT INTO context_profiles
            (id, kind, name, payload, source_urls, raw_text, created_at, updated_at)
            VALUES ($1, $2, $3, $4::jsonb, $5::text[], $6, NOW(), NOW())
            """,
            context_id,
            "candidate_insights",
            candidate_name,
            payload_json,
            [],
            raw_text,
        )

    chunk_specs = [
        ("insights_summary", summary),
        (
            "insights_role_alignment",
            _compact_text(
                "\n".join(
                    line
                    for line in [
                        f"Target role: {(workspace.get('benchmark_source') or {}).get('target_role', '')}",
                        f"Top role signals: {', '.join(top_role_signals)}" if top_role_signals else "",
                        f"Focus areas: {', '.join(focus_areas)}" if focus_areas else "",
                    ]
                    if line
                ),
                limit=3000,
            ),
        ),
        ("insights_evidence", _compact_text("\n".join(reusable_evidence), limit=3000)),
        ("insights_projects", _compact_text("\n".join(project_evidence), limit=3000)),
    ]

    indexed_chunks = 0
    for section, chunk_text in chunk_specs:
        chunk_text = _compact_text(str(chunk_text or ""), limit=3000)
        if len(chunk_text) < 20:
            continue
        embedding = await build_query_embedding(chunk_text)
        embedding_vec = vector_literal(embedding)
        await execute_query(
            """
            INSERT INTO context_document_chunks
            (context_id, kind, source, section, content, embedding, metadata, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, NOW())
            """,
            context_id,
            "candidate_insights",
            "candidate_insights",
            section,
            chunk_text,
            embedding_vec,
            json.dumps(
                {
                    "indexed_from": "insights_apply",
                    "workspace_id": workspace_id,
                    "run_id": run_id,
                    "section": section,
                    "kind": "candidate_insights",
                }
            ),
        )
        indexed_chunks += 1

    return {
        "saved": True,
        "deleted": {"document_chunks": deleted_chunks},
        "indexed": {"document_chunks": indexed_chunks},
    }


def _hydrate_insights_response(
    *,
    workspace_id: str,
    run_id: str,
    workspace: dict[str, Any],
    context_index_status: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    payload = copy.deepcopy(workspace)
    payload["workspace_id"] = workspace_id
    payload["run_id"] = run_id
    if context_index_status is not None:
        payload["context_index_status"] = context_index_status
    return payload


def _insights_approvals_snapshot(
    workspace: dict[str, Any],
    *,
    context_index_status: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    return {
        "recommended_profile": copy.deepcopy(workspace.get("recommended_profile", {})),
        "proposed_changes": copy.deepcopy(workspace.get("proposed_changes", [])),
        "approved_context_preview": copy.deepcopy(workspace.get("approved_context_preview", {})),
        "cv_health": workspace.get("cv_health", ""),
        "role_match_summary": workspace.get("role_match_summary", ""),
        "mode": workspace.get("mode", "fallback"),
        "global_score": workspace.get("global_score", workspace.get("overall_match", 0)),
        "top_strengths": copy.deepcopy(workspace.get("top_strengths", [])),
        "top_gaps": copy.deepcopy(workspace.get("top_gaps", [])),
        "score_delta_available": workspace.get("score_delta_available", 0),
        "score_history": copy.deepcopy(workspace.get("score_history", [])),
        "interpretation": workspace.get("interpretation", ""),
        "next_actions": copy.deepcopy(workspace.get("next_actions", [])),
        "improvement_plan": copy.deepcopy(workspace.get("improvement_plan", {})),
        "context_index_status": copy.deepcopy(
            context_index_status
            or {
                "saved": False,
                "deleted": {"document_chunks": 0},
                "indexed": {"document_chunks": 0},
            }
        ),
    }


def _workspace_from_store(record: dict[str, Any]) -> dict[str, Any]:
    run = copy.deepcopy(record["run"])
    approvals = copy.deepcopy(run.get("approvals", {}))
    approved_context_preview = approvals.get("approved_context_preview", {}) or {}
    ui_state = copy.deepcopy(record["workspace"].get("ui_state", {}) or {})
    score_history = copy.deepcopy(approvals.get("score_history") or ui_state.get("score_history") or [])
    return {
        "mode": approvals.get("mode", "fallback"),
        "analysis_summary": approved_context_preview.get("summary", ""),
        "benchmark_source": run.get("benchmark_source", {}),
        "support_level": run.get("support_level") or record["workspace"].get("support_level", "unsupported"),
        "workspace_state": record["workspace"].get("workspace_state", "active"),
        "primary_scores": run.get("primary_scores", {}),
        "global_score": approvals.get("global_score", run.get("overall_match", 0)),
        "overall_match": run.get("overall_match", 0),
        "coverage_pct": run.get("coverage_pct", 0),
        "confidence": {
            "label": run.get("confidence_label", "Low"),
            "score": run.get("confidence_score", 0),
        },
        "top_strengths": approvals.get("top_strengths", []),
        "top_gaps": approvals.get("top_gaps", []),
        "score_delta_available": approvals.get("score_delta_available", 0),
        "score_history": score_history,
        "interpretation": approvals.get("interpretation", ""),
        "next_actions": approvals.get("next_actions", []),
        "improvement_plan": approvals.get("improvement_plan", {}),
        "dimension_states": run.get("dimension_states", []),
        "required_signals": run.get("signal_snapshot", {}).get("required_signals", []),
        "supporting_signals": run.get("signal_snapshot", {}).get("supporting_signals", []),
        "differentiator_signals": run.get("signal_snapshot", {}).get("differentiator_signals", []),
        "anti_signals": run.get("signal_snapshot", {}).get("anti_signals", []),
        "not_applicable_signals": run.get("signal_snapshot", {}).get("not_applicable_signals", []),
        "gap_map": run.get("gap_map", []),
        "evidence_cards": run.get("evidence_cards", []),
        "questions": run.get("question_backlog", []),
        "proposed_changes": approvals.get("proposed_changes", []),
        "recommended_profile": approvals.get("recommended_profile", {}),
        "approved_context_preview": approved_context_preview,
        "insights_context_summary": approved_context_preview.get("summary", ""),
        "cv_health": approvals.get("cv_health", ""),
        "role_match_summary": approvals.get("role_match_summary", ""),
        "cv_variants": run.get("cv_variants", {}),
        "answers": run.get("answers", {}),
        "input_snapshot": run.get("input_snapshot", {}),
        "signal_snapshot": run.get("signal_snapshot", {}),
        "ui_state": ui_state,
        "context_index_status": approvals.get(
            "context_index_status",
            {
                "saved": False,
                "deleted": {"document_chunks": 0},
                "indexed": {"document_chunks": 0},
            },
        ),
        "last_generated_at": run.get("created_at"),
        "workspace_last_active_at": record["workspace"].get("last_active_at"),
    }


def _log_insights_event(event: str, **fields: Any) -> None:
    payload = {
        "event": event,
        "timestamp": datetime.now(UTC).isoformat(),
        **fields,
    }
    try:
        print(f"[Insights] {json.dumps(payload, default=str, sort_keys=True)}")
    except Exception:
        print(f"[Insights] {event} {fields}")


def _extract_score_history(record: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not record:
        return []
    workspace = _workspace_from_store(record)
    return copy.deepcopy(workspace.get("score_history", []))


def _build_score_history_event(
    *,
    source: Literal["initial_analysis", "question_answer", "evidence_approval", "rewrite_apply"],
    label: str,
    before_workspace: Optional[dict[str, Any]],
    after_workspace: dict[str, Any],
) -> dict[str, Any]:
    before_overall = int((before_workspace or {}).get("overall_match") or 0)
    after_overall = int(after_workspace.get("overall_match") or 0)
    before_scores = (before_workspace or {}).get("primary_scores", {}) or {}
    after_scores = after_workspace.get("primary_scores", {}) or {}
    dimension_deltas = {
        "profile_strength": int(after_scores.get("profile_strength", 0)) - int(before_scores.get("profile_strength", 0)),
        "role_fit": int(after_scores.get("role_fit", 0)) - int(before_scores.get("role_fit", 0)),
        "proof_strength": int(after_scores.get("proof_strength", 0)) - int(before_scores.get("proof_strength", 0)),
        "cv_representation_quality": int(after_scores.get("cv_representation_quality", 0)) - int(before_scores.get("cv_representation_quality", 0)),
    }
    return {
        "event_id": str(uuid.uuid4()),
        "source": source,
        "label": label,
        "score_before": before_overall,
        "score_after": after_overall,
        "delta": after_overall - before_overall,
        "dimension_deltas": dimension_deltas,
        "created_at": datetime.now(UTC).isoformat(),
    }


@app.post("/api/insights/analyze")
async def analyze_insights(request: InsightsAnalyzeRequest):
    previous_record = await _INSIGHTS_STORE.get_run(workspace_id=request.workspace_id) if request.workspace_id else None
    previous_workspace = _workspace_from_store(previous_record) if previous_record else None
    workspace = await _INSIGHTS_SERVICE.analyze(
        candidate_profile=request.candidate_profile,
        company_info=request.company_info,
        interviewer_profile=request.interviewer_profile,
        cv_text=request.cv_text,
        language=request.language or "en",
        target_role_override=request.target_role_override,
        archetype_override=request.archetype_override,
        seniority_override=request.seniority_override,
        specialty_ids=request.specialty_ids,
    )
    prior_history = _extract_score_history(previous_record)
    workspace["score_history"] = prior_history + [
        _build_score_history_event(
            source="initial_analysis",
            label="Initial benchmark generated" if not prior_history else "Benchmark refreshed",
            before_workspace=previous_workspace,
            after_workspace=workspace,
        )
    ]
    workspace_id, run_id = await _INSIGHTS_STORE.save_run(
        workspace_id=request.workspace_id,
        profile_id=str((request.candidate_profile or {}).get("profile_id") or "").strip() or None,
        target_role=workspace.get("benchmark_source", {}).get("target_role", ""),
        normalized_target_role=workspace.get("benchmark_source", {}).get("normalized_target_role", ""),
        archetype_pack_id=workspace.get("benchmark_source", {}).get("archetype_pack_id", ""),
        role_family_pack_id=workspace.get("benchmark_source", {}).get("family_pack_id", ""),
        seniority_pack_id=workspace.get("benchmark_source", {}).get("seniority_pack_id", ""),
        specialty_pack_ids=list(workspace.get("benchmark_source", {}).get("specialty_ids", [])),
        support_level=workspace.get("support_level", "unsupported"),
        benchmark_source_fingerprint=workspace.get("benchmark_source", {}).get("benchmark_source_fingerprint", ""),
        benchmark_source=workspace.get("benchmark_source", {}),
        input_snapshot=workspace.get("input_snapshot", {}),
        primary_scores=workspace.get("primary_scores", {}),
        overall_match=workspace.get("overall_match", 0),
        coverage_pct=workspace.get("coverage_pct", 0),
        confidence_score=(workspace.get("confidence", {}) or {}).get("score", 0),
        confidence_label=(workspace.get("confidence", {}) or {}).get("label", "Low"),
        dimension_states=workspace.get("dimension_states", []),
        signal_snapshot=workspace.get("signal_snapshot", {}),
        gap_map=workspace.get("gap_map", []),
        question_backlog=workspace.get("questions", []),
        evidence_cards=workspace.get("evidence_cards", []),
        cv_variants=workspace.get("cv_variants", {}),
        answers=workspace.get("answers", {}),
        approvals=_insights_approvals_snapshot(workspace),
    )
    _log_insights_event(
        "analyze",
        workspace_id=workspace_id,
        run_id=run_id,
        target_role=workspace.get("benchmark_source", {}).get("target_role"),
        support_level=workspace.get("support_level"),
        overall_match=workspace.get("overall_match"),
    )
    return {"success": True, **_hydrate_insights_response(workspace_id=workspace_id, run_id=run_id, workspace=workspace)}


@app.get("/api/insights/workspace")
async def find_insights_workspace(profile_id: Optional[str] = None, target_role: Optional[str] = None):
    record = await _INSIGHTS_STORE.find_workspace(profile_id=profile_id, target_role=target_role)
    if not record:
        raise HTTPException(status_code=404, detail="Insights workspace not found")
    workspace = _workspace_from_store(record)
    _log_insights_event(
        "restore_lookup",
        workspace_id=record["workspace"]["id"],
        run_id=record["run"]["id"],
        target_role=workspace.get("benchmark_source", {}).get("target_role"),
    )
    return {
        "success": True,
        **_hydrate_insights_response(
            workspace_id=record["workspace"]["id"],
            run_id=record["run"]["id"],
            workspace=workspace,
            context_index_status=workspace.get("context_index_status"),
        ),
    }


@app.get("/api/insights/workspace/{workspace_id}")
async def get_insights_workspace(workspace_id: str, run_id: Optional[str] = None):
    record = await _INSIGHTS_STORE.get_run(workspace_id=workspace_id, run_id=run_id)
    if not record:
        raise HTTPException(status_code=404, detail="Insights workspace not found")
    workspace = _workspace_from_store(record)
    _log_insights_event(
        "restore_workspace",
        workspace_id=workspace_id,
        run_id=record["run"]["id"],
        workspace_state=workspace.get("workspace_state"),
    )
    return {
        "success": True,
        **_hydrate_insights_response(
            workspace_id=workspace_id,
            run_id=record["run"]["id"],
            workspace=workspace,
            context_index_status=workspace.get("context_index_status"),
        ),
    }


@app.get("/api/insights/workspace/{workspace_id}/status")
async def get_insights_workspace_status(workspace_id: str):
    status = await _INSIGHTS_STORE.get_workspace_status(workspace_id=workspace_id)
    if not status:
        raise HTTPException(status_code=404, detail="Insights workspace not found")
    _log_insights_event("workspace_status", **status)
    return {"success": True, **status}


@app.put("/api/insights/workspace/{workspace_id}")
async def autosave_insights_workspace(workspace_id: str, request: InsightsWorkspaceAutosaveRequest):
    record = await _INSIGHTS_STORE.get_run(workspace_id=workspace_id)
    if not record:
        raise HTTPException(status_code=404, detail="Insights workspace not found")
    saved = await _INSIGHTS_STORE.save_ui_state(
        workspace_id=workspace_id,
        ui_state=request.ui_state,
        workspace_state=request.workspace_state,
    )
    if not saved:
        raise HTTPException(status_code=404, detail="Insights workspace not found")
    refreshed = await _INSIGHTS_STORE.get_run(workspace_id=workspace_id)
    if not refreshed:
        raise HTTPException(status_code=404, detail="Insights workspace not found after autosave")
    workspace = _workspace_from_store(refreshed)
    _log_insights_event(
        "autosave_workspace",
        workspace_id=workspace_id,
        run_id=refreshed["run"]["id"],
        workspace_state=workspace.get("workspace_state"),
        ui_state_keys=sorted((request.ui_state or {}).keys()),
        idempotent=True,
    )
    return {
        "success": True,
        **_hydrate_insights_response(
            workspace_id=workspace_id,
            run_id=refreshed["run"]["id"],
            workspace=workspace,
            context_index_status=workspace.get("context_index_status"),
        ),
    }


@app.post("/api/insights/questions/answer")
async def answer_insight_question(request: InsightsAnswerRequest):
    record = await _INSIGHTS_STORE.get_run(workspace_id=request.workspace_id, run_id=request.run_id)
    if not record:
        raise HTTPException(status_code=404, detail="Insights analysis not found")

    answer = request.answer.strip()
    if not answer:
        return {"success": False, "error": "Answer required"}

    previous_workspace = _workspace_from_store(record)
    prior_history = _extract_score_history(record)
    input_snapshot = record["run"].get("input_snapshot", {})
    answers = dict(record["run"].get("answers", {}))
    answers[request.question_id] = answer
    workspace = await _INSIGHTS_SERVICE.analyze(
        candidate_profile=input_snapshot.get("candidate_profile"),
        company_info=input_snapshot.get("company_info"),
        interviewer_profile=input_snapshot.get("interviewer_profile"),
        cv_text=input_snapshot.get("cv_text", ""),
        language=input_snapshot.get("language", "en"),
        answers=answers,
        target_role_override=input_snapshot.get("target_role_override"),
        archetype_override=input_snapshot.get("archetype_override"),
        seniority_override=input_snapshot.get("seniority_override"),
        specialty_ids=input_snapshot.get("specialty_ids") or [],
    )
    matching_question = next(
        (question for question in previous_workspace.get("questions", []) if question.get("id") == request.question_id),
        None,
    )
    workspace["score_history"] = prior_history + [
        _build_score_history_event(
            source="question_answer",
            label=f"Answered: {(matching_question or {}).get('title') or request.question_id}",
            before_workspace=previous_workspace,
            after_workspace=workspace,
        )
    ]
    workspace_id, run_id = await _INSIGHTS_STORE.save_run(
        workspace_id=request.workspace_id,
        profile_id=str((input_snapshot.get("candidate_profile") or {}).get("profile_id") or "").strip() or None,
        target_role=workspace.get("benchmark_source", {}).get("target_role", ""),
        normalized_target_role=workspace.get("benchmark_source", {}).get("normalized_target_role", ""),
        archetype_pack_id=workspace.get("benchmark_source", {}).get("archetype_pack_id", ""),
        role_family_pack_id=workspace.get("benchmark_source", {}).get("family_pack_id", ""),
        seniority_pack_id=workspace.get("benchmark_source", {}).get("seniority_pack_id", ""),
        specialty_pack_ids=list(workspace.get("benchmark_source", {}).get("specialty_ids", [])),
        support_level=workspace.get("support_level", "unsupported"),
        benchmark_source_fingerprint=workspace.get("benchmark_source", {}).get("benchmark_source_fingerprint", ""),
        benchmark_source=workspace.get("benchmark_source", {}),
        input_snapshot=workspace.get("input_snapshot", {}),
        primary_scores=workspace.get("primary_scores", {}),
        overall_match=workspace.get("overall_match", 0),
        coverage_pct=workspace.get("coverage_pct", 0),
        confidence_score=(workspace.get("confidence", {}) or {}).get("score", 0),
        confidence_label=(workspace.get("confidence", {}) or {}).get("label", "Low"),
        dimension_states=workspace.get("dimension_states", []),
        signal_snapshot=workspace.get("signal_snapshot", {}),
        gap_map=workspace.get("gap_map", []),
        question_backlog=workspace.get("questions", []),
        evidence_cards=workspace.get("evidence_cards", []),
        cv_variants=workspace.get("cv_variants", {}),
        answers=workspace.get("answers", {}),
        approvals=_insights_approvals_snapshot(workspace),
    )
    _log_insights_event(
        "answer_question",
        workspace_id=workspace_id,
        previous_run_id=request.run_id,
        run_id=run_id,
        question_id=request.question_id,
        overall_match=workspace.get("overall_match"),
    )
    return {"success": True, **_hydrate_insights_response(workspace_id=workspace_id, run_id=run_id, workspace=workspace)}


@app.post("/api/insights/cv/preview")
async def preview_insight_cv(request: InsightsPreviewRequest):
    record = await _INSIGHTS_STORE.get_run(workspace_id=request.workspace_id, run_id=request.run_id)
    if not record:
        return {"success": False, "error": "Insights analysis not found"}

    variant = record["run"].get("cv_variants", {}).get(request.variant)
    if not variant:
        return {"success": False, "error": "CV variant not available"}

    return {"success": True, "workspace_id": request.workspace_id, "run_id": request.run_id, "variant": variant}


@app.post("/api/insights/apply")
async def apply_insight_changes(request: InsightsApplyRequest):
    record = await _INSIGHTS_STORE.get_run(workspace_id=request.workspace_id, run_id=request.run_id)
    if not record:
        raise HTTPException(status_code=404, detail="Insights analysis not found")

    workspace = _workspace_from_store(record)
    previous_workspace = copy.deepcopy(workspace)
    prior_history = _extract_score_history(record)
    result = _INSIGHTS_SERVICE.apply_workspace(
        analysis={
            "candidate_profile": copy.deepcopy(record["run"].get("input_snapshot", {}).get("candidate_profile", {})),
            "cv_text": record["run"].get("input_snapshot", {}).get("cv_text", ""),
            "workspace": workspace,
        },
        approved_change_ids=request.approved_change_ids,
        approved_evidence_ids=request.approved_evidence_ids,
        targets=request.targets,
        variant=request.variant,
    )
    input_snapshot = record["run"].get("input_snapshot", {})
    rescored_workspace = await _INSIGHTS_SERVICE.analyze(
        candidate_profile=result["candidate_profile"],
        company_info=input_snapshot.get("company_info"),
        interviewer_profile=input_snapshot.get("interviewer_profile"),
        cv_text=result["cv_text"],
        language=input_snapshot.get("language", "en"),
        answers=record["run"].get("answers", {}),
        target_role_override=input_snapshot.get("target_role_override"),
        archetype_override=input_snapshot.get("archetype_override"),
        seniority_override=input_snapshot.get("seniority_override"),
        specialty_ids=input_snapshot.get("specialty_ids") or [],
    )
    context_index_status = {
        "saved": False,
        "deleted": {"document_chunks": 0},
        "indexed": {"document_chunks": 0},
    }
    try:
        context_index_status = await _persist_candidate_insights_context(
            workspace_id=request.workspace_id,
            run_id=request.run_id,
            workspace=rescored_workspace,
            apply_result=result,
        )
    except Exception as exc:
        print(f"[InsightsApply] Context persistence skipped: {exc}")

    result["context_index_status"] = {
        "saved": bool(context_index_status.get("saved")),
        "deleted": context_index_status.get("deleted", {"document_chunks": 0}),
        "indexed": context_index_status.get("indexed", {"document_chunks": 0}),
    }
    rescored_workspace["approved_context_preview"] = result["approved_context_preview"]
    rescored_workspace["context_index_status"] = result["context_index_status"]
    rescored_workspace["score_history"] = prior_history + [
        _build_score_history_event(
            source="rewrite_apply" if request.targets else "evidence_approval",
            label=(
                f"Applied {request.variant or 'selected'} rewrite"
                if request.targets
                else "Approved evidence into Insights context"
            ),
            before_workspace=previous_workspace,
            after_workspace=rescored_workspace,
        )
    ]
    workspace_id, run_id = await _INSIGHTS_STORE.save_run(
        workspace_id=request.workspace_id,
        profile_id=str((result.get("candidate_profile") or {}).get("profile_id") or "").strip() or None,
        target_role=rescored_workspace.get("benchmark_source", {}).get("target_role", ""),
        normalized_target_role=rescored_workspace.get("benchmark_source", {}).get("normalized_target_role", ""),
        archetype_pack_id=rescored_workspace.get("benchmark_source", {}).get("archetype_pack_id", ""),
        role_family_pack_id=rescored_workspace.get("benchmark_source", {}).get("family_pack_id", ""),
        seniority_pack_id=rescored_workspace.get("benchmark_source", {}).get("seniority_pack_id", ""),
        specialty_pack_ids=list(rescored_workspace.get("benchmark_source", {}).get("specialty_ids", [])),
        support_level=rescored_workspace.get("support_level", "unsupported"),
        benchmark_source_fingerprint=rescored_workspace.get("benchmark_source", {}).get("benchmark_source_fingerprint", ""),
        benchmark_source=rescored_workspace.get("benchmark_source", {}),
        input_snapshot=rescored_workspace.get("input_snapshot", {}),
        primary_scores=rescored_workspace.get("primary_scores", {}),
        overall_match=rescored_workspace.get("overall_match", 0),
        coverage_pct=rescored_workspace.get("coverage_pct", 0),
        confidence_score=(rescored_workspace.get("confidence", {}) or {}).get("score", 0),
        confidence_label=(rescored_workspace.get("confidence", {}) or {}).get("label", "Low"),
        dimension_states=rescored_workspace.get("dimension_states", []),
        signal_snapshot=rescored_workspace.get("signal_snapshot", {}),
        gap_map=rescored_workspace.get("gap_map", []),
        question_backlog=rescored_workspace.get("questions", []),
        evidence_cards=rescored_workspace.get("evidence_cards", []),
        cv_variants=rescored_workspace.get("cv_variants", {}),
        answers=rescored_workspace.get("answers", {}),
        approvals=_insights_approvals_snapshot(
            rescored_workspace,
            context_index_status=result["context_index_status"],
        ),
    )
    _log_insights_event(
        "apply_workspace",
        workspace_id=workspace_id,
        previous_run_id=request.run_id,
        run_id=run_id,
        targets=request.targets,
        variant=request.variant,
        overall_match=rescored_workspace.get("overall_match"),
    )
    hydrated = _hydrate_insights_response(
        workspace_id=workspace_id,
        run_id=run_id,
        workspace=rescored_workspace,
        context_index_status=result["context_index_status"],
    )
    return {"success": True, **hydrated, **result}


@app.post("/api/insights/cv/export")
async def export_insight_cv(request: InsightsExportRequest):
    record = await _INSIGHTS_STORE.get_run(workspace_id=request.workspace_id, run_id=request.run_id)
    if not record:
        return {"success": False, "error": "Insights analysis not found"}

    variant = record["run"].get("cv_variants", {}).get(request.variant)
    if not variant:
        return {"success": False, "error": "CV variant not available"}

    try:
        export_payload = _INSIGHTS_SERVICE.build_docx_export(
            variant=variant,
            candidate_name=(
                record["run"].get("input_snapshot", {}).get("candidate_profile", {}).get("name")
                or (record["run"].get("approvals", {}).get("recommended_profile", {}) or {}).get("name")
                or "candidate"
            ),
        )
    except Exception as exc:
        return {"success": False, "error": f"Export failed: {exc}"}

    return {"success": True, "workspace_id": request.workspace_id, "run_id": request.run_id, **export_payload}


# =============================================================================
# RESEARCH CONTEXT ENDPOINTS - Company / Interviewer intake
# =============================================================================


@app.post("/api/context/analyze")
async def analyze_context(request: ResearchContextAnalyzeRequest):
    kind = request.kind
    urls = _clean_string_list(request.urls)
    manual_text = request.manual_text or ""
    language = request.language or "en"

    try:
        analyzed, extracted_text, warnings, mode = await _analyze_research_context(
            kind=kind,
            urls=urls,
            manual_text=manual_text,
            language=language,
        )

        return {
            "success": True,
            "kind": kind,
            "mode": mode,
            "extracted_text": extracted_text,
            "source_urls": analyzed.get("source_urls", urls),
            "warnings": warnings,
            "analyzed": analyzed,
            "suggested_values": analyzed,
            "note": (
                "URL fetches are best-effort; pasted notes remain the safest fallback."
                if warnings
                else "Context analyzed successfully."
            ),
        }
    except Exception as e:
        print(f"[ContextAnalyze] Error: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "kind": kind,
            "mode": "fallback",
            "warnings": [str(e)],
            "error": str(e),
        }


@app.post("/api/coach/context/analyze")
async def analyze_context_proxy(request: ResearchContextAnalyzeRequest):
    """Alias endpoint for clients that use the /api/coach prefix."""
    return await analyze_context(request)


@app.post("/api/context/index")
async def index_context(request: ResearchContextIndexRequest):
    from storage.database import execute_query, execute_scalar
    from storage.embedding_utils import build_query_embedding, vector_literal

    kind = request.kind
    payload = request.payload or {}
    context_id = request.context_id or str(uuid.uuid4())
    source_urls = _clean_string_list(request.source_urls or payload.get("source_urls"))
    raw_text = request.raw_text or ""
    normalized = _normalize_context_payload(kind, payload, source_urls, context_id)

    if not normalized.get("name") and kind == "company":
        normalized["name"] = str(payload.get("company_name") or payload.get("name") or "")
    if not normalized.get("name") and kind == "interviewer":
        normalized["name"] = str(payload.get("name") or "")

    source_text = (
        _build_company_manual_text(payload, raw_text)
        if kind == "company"
        else _build_interviewer_manual_text(payload, raw_text)
    )
    source_text = _compact_text(source_text or raw_text, limit=12000)
    if not source_text.strip():
        return {"success": False, "kind": kind, "error": "No context text provided to index"}

    try:
        profile_exists = await execute_scalar(
            "SELECT id FROM context_profiles WHERE id = $1",
            context_id,
        )
        deleted_chunks = 0

        # Indexing must preserve the edited form as the source of truth.
        # Analysis can suggest values during "Analyze", but "Index" should only
        # persist and embed what is currently loaded in the form.
        warnings: list[str] = []
        analysis_mode = "real"
        normalized["source_urls"] = _clean_string_list(normalized.get("source_urls") or source_urls)

        normalized_json = json.dumps(normalized)
        if profile_exists:
            deleted_rows = await execute_query(
                "DELETE FROM context_document_chunks WHERE context_id = $1 RETURNING id",
                context_id,
            )
            deleted_chunks = len(deleted_rows) if deleted_rows else 0
            await execute_query(
                """
                UPDATE context_profiles
                SET kind = $2, name = $3, payload = $4::jsonb, source_urls = $5::text[],
                    raw_text = $6, updated_at = NOW()
                WHERE id = $1
                """,
                context_id,
                kind,
                normalized.get("name", ""),
                normalized_json,
                source_urls,
                source_text,
            )
        else:
            await execute_query(
                """
                INSERT INTO context_profiles
                (id, kind, name, payload, source_urls, raw_text, created_at, updated_at)
                VALUES ($1, $2, $3, $4::jsonb, $5::text[], $6, NOW(), NOW())
                """,
                context_id,
                kind,
                normalized.get("name", ""),
                normalized_json,
                source_urls,
                source_text,
            )

        chunk_specs: list[tuple[str, str]] = []
        if kind == "company":
            chunk_specs = [
                ("company_summary", normalized.get("company_summary") or ""),
                (
                    "company_role_context",
                    "\n".join(
                        [
                            f"Role title: {normalized.get('role_title', '')}",
                            f"Role level: {normalized.get('role_level', '')}",
                            f"Requirements: {', '.join(normalized.get('role_requirements', []) or [])}",
                            f"Responsibilities: {', '.join(normalized.get('role_responsibilities', []) or [])}",
                            f"Interview focus: {', '.join(normalized.get('interview_focus', []) or [])}",
                        ]
                    ).strip(),
                ),
                ("company_job_description", normalized.get("job_description") or ""),
                ("company_notes", normalized.get("research_notes") or ""),
            ]
        else:
            chunk_specs = [
                ("interviewer_background", normalized.get("background_summary") or ""),
                (
                    "interviewer_expertise",
                    "\n".join(
                        [
                            f"Expertise: {', '.join(normalized.get('expertise', []) or [])}",
                            f"Likely focus areas: {', '.join(normalized.get('likely_focus_areas', []) or [])}",
                            f"Communication style: {normalized.get('communication_style', '')}",
                        ]
                    ).strip(),
                ),
                ("interviewer_notes", normalized.get("notes") or ""),
            ]

        indexed_chunks = 0
        for section, chunk_text in chunk_specs:
            chunk_text = _compact_text(str(chunk_text or ""), limit=3000)
            if len(chunk_text) < 20:
                continue
            embedding = await build_query_embedding(chunk_text)
            embedding_vec = vector_literal(embedding)
            await execute_query(
                """
                INSERT INTO context_document_chunks
                (context_id, kind, source, section, content, embedding, metadata, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, NOW())
                """,
                context_id,
                kind,
                kind,
                section,
                chunk_text,
                embedding_vec,
                json.dumps({
                    "indexed_from": "context_index",
                    "source_urls": source_urls,
                    "section": section,
                    "kind": kind,
                }),
            )
            indexed_chunks += 1

        return {
            "success": True,
            "kind": kind,
            "context_id": context_id,
            "context": normalized,
            "deleted": {"document_chunks": deleted_chunks},
            "indexed": {"document_chunks": indexed_chunks},
            "warnings": warnings,
            "message": f"Indexed {indexed_chunks} chunks for {kind} context",
            "mode": analysis_mode,
        }
    except Exception as e:
        print(f"[ContextIndex] Error: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "kind": kind, "error": str(e)}


@app.post("/api/coach/context/index")
async def index_context_proxy(request: ResearchContextIndexRequest):
    """Alias endpoint for clients that use the /api/coach prefix."""
    return await index_context(request)


# =============================================================================
# PROFILE REINDEX ENDPOINT - For re-indexing after profile edits
# =============================================================================

class ProfileReindexRequest(BaseModel):
    """Request to reindex a profile after edits"""
    profile_id: Optional[str] = None
    name: Optional[str] = None
    current_role: Optional[str] = None
    company: Optional[str] = None
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
            request.name or request.summary or request.current_role or request.company or
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

        if request.company:
            profile_sections.append(f"Current Company: {request.company}")
        
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
            
            suggestion_payload = {
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
            }
            await _send_final_suggestion_with_commit(
                websocket=websocket,
                payload=suggestion_payload,
                tracker=getattr(pipeline, "conversation_tracker", None),
                question_text=transcript_text,
                interviewer_generation=0,
                session_id=session_id,
            )
            
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
                    suggestion_payload = {
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
                    }
                    await _send_final_suggestion_with_commit(
                        websocket=websocket,
                        payload=suggestion_payload,
                        tracker=getattr(pipeline, "conversation_tracker", None),
                        question_text=text,
                        interviewer_generation=0,
                        session_id=session_id or "",
                    )

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
                    
                    suggestion_payload = {
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
                        "time_to_first_answer_ms": suggested_metadata.get("time_to_first_answer_ms", suggested_metadata.get("time_to_bullets_ms", result.total_latency_ms)),
                        "time_to_refined_answer_ms": suggested_metadata.get("time_to_refined_answer_ms", suggested_metadata.get("time_to_full_ms", result.total_latency_ms)),
                        "normalized_family": suggested_metadata.get("normalized_family"),
                        "normalized_primary_ask": suggested_metadata.get("normalized_primary_ask"),
                        "normalized_secondary_asks": suggested_metadata.get("normalized_secondary_asks"),
                        "normalized_answer_contract": suggested_metadata.get("normalized_answer_contract"),
                        "normalized_metrics_policy": suggested_metadata.get("normalized_metrics_policy"),
                        "normalizer_confidence": suggested_metadata.get("normalizer_confidence"),
                        "normalizer_latency_ms": suggested_metadata.get("normalizer_latency_ms"),
                        "fallback_used": suggested_metadata.get("fallback_used"),
                    }
                    await _send_final_suggestion_with_commit(
                        websocket=websocket,
                        payload=suggestion_payload,
                        tracker=getattr(pipeline, "conversation_tracker", None),
                        question_text=question,
                        interviewer_generation=0,
                        session_id=session_id or "",
                    )
                    
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
                context_bundle = build_realtime_context_bundle(pipeline.conversation_tracker, limit=5)
                recent_turns = context_bundle.get("turns", [])

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

                print(f"[DEBUG][REQUEST_SUGGESTION] Selected primary question source: {context_bundle.get('primary_question_source')}")

                # Process through history-based pipeline (bypasses constraints)
                try:
                    from time import perf_counter

                    context = recent_turns
                    question_text = context_bundle.get("primary_question", "")
                    ask_brief_override = pipeline.conversation_tracker.get_cached_ask_brief(question_text)
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
                        "question_source": context_bundle.get("primary_question_source"),
                        "primary_question_index": context_bundle.get("primary_question_index"),
                    })

                    print(f"[DEBUG][REQUEST_SUGGESTION] Calling pipeline.process_question with context={len(context)} turns")
                    # Process through pipeline with context from conversation history
                    result = await pipeline.process_question(
                        question_text,
                        is_final=True,
                        on_progress=lambda e: websocket.send_json(e),
                        context=context,  # Pass the conversation context
                        ask_brief_override=ask_brief_override,
                    )
                    print(f"[DEBUG][REQUEST_SUGGESTION] process_question completed")
                    
                    # Format response similar to manual_question
                    suggested_response = result.exchange.suggested_response
                    suggested_metadata = getattr(suggested_response, "metadata", {}) or {}
                    if not isinstance(suggested_metadata, dict):
                        suggested_metadata = {}
                    
                    # Determine actual mode from result
                    actual_mode = _resolve_result_mode(result, suggested_response, mode)
                    
                    suggestion_payload = {
                        "type": "suggestion",
                        "stage": "full",
                        "mode": actual_mode,
                        "source": "history_based",
                        "question": question_text,
                        "context_turns": len(context),
                        "question_source": context_bundle.get("primary_question_source"),
                        "context_turns_used": len(context),
                        "primary_question_index": context_bundle.get("primary_question_index"),
                        "interviewer_question_index": context_bundle.get("interviewer_question_index"),
                        "delivery_mode": str((pipeline.session_state.interview_config or {}).get("delivery_mode") or "realtime"),
                        "answer_intent": result.question_analysis.answer_intent.value,
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
                        "time_to_first_answer_ms": suggested_metadata.get("time_to_first_answer_ms", suggested_metadata.get("time_to_bullets_ms", result.total_latency_ms)),
                        "time_to_refined_answer_ms": suggested_metadata.get("time_to_refined_answer_ms", suggested_metadata.get("time_to_full_ms", result.total_latency_ms)),
                        "normalized_family": suggested_metadata.get("normalized_family"),
                        "normalized_primary_ask": suggested_metadata.get("normalized_primary_ask"),
                        "normalized_secondary_asks": suggested_metadata.get("normalized_secondary_asks"),
                        "normalized_answer_contract": suggested_metadata.get("normalized_answer_contract"),
                        "normalized_metrics_policy": suggested_metadata.get("normalized_metrics_policy"),
                        "normalizer_confidence": suggested_metadata.get("normalizer_confidence"),
                        "normalizer_latency_ms": suggested_metadata.get("normalizer_latency_ms"),
                        "fallback_used": suggested_metadata.get("fallback_used"),
                    }
                    await _send_final_suggestion_with_commit(
                        websocket=websocket,
                        payload=suggestion_payload,
                        tracker=getattr(pipeline, "conversation_tracker", None),
                        question_text=question_text,
                        interviewer_generation=0,
                        session_id=session_id or "",
                    )
                    
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
