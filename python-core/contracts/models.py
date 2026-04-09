"""
Interview Coach - Core Data Contracts
Pydantic models for the entire pipeline
Aligned with Architecture v3.2.1
"""
from pydantic import BaseModel, Field
from typing import Optional, Any, Literal
from enum import Enum
from datetime import datetime


# =====================
# ENUMS
# =====================

class QuestionType(str, Enum):
    BEHAVIORAL = "behavioral"
    TECHNICAL = "technical"
    SITUATIONAL = "situational"
    CASUAL = "casual"
    FOLLOW_UP = "follow_up"
    STRESS = "stress"
    COMPOUND = "compound"


class ResponseStyle(str, Enum):
    EXECUTIVE = "executive"
    COMMERCIAL = "commercial"
    TECHNICAL = "technical"
    MIXED = "mixed"


class QuestionMode(str, Enum):
    EXPERIENCE_BASED = "experience_based"
    CONCEPTUAL = "conceptual"
    MIXED = "mixed"


class ResponseMode(str, Enum):
    INTERVIEW_ANSWER = "interview_answer"
    COACH_EXPLAINER = "coach_explainer"
    HYBRID_DUAL = "hybrid_dual"


class AnswerIntent(str, Enum):
    PRINCIPLE = "principle"
    EXAMPLE = "example"
    EXPLANATION = "explanation"
    TRADEOFF = "tradeoff"
    BUSINESS_VALUE = "business_value"
    MIXED = "mixed"


class AskFamily(str, Enum):
    EXPERIENCE_SCOPE = "experience_scope"
    CULTURE_FIT = "culture_fit"
    TECHNICAL_CONCEPT = "technical_concept"
    TECHNICAL_EXPERIENCE = "technical_experience"
    ARCHITECTURE_DESIGN = "architecture_design"
    PRODUCT_SPECIFIC = "product_specific"
    BUSINESS_STRATEGY = "business_strategy"
    METRICS_OUTCOMES = "metrics_outcomes"
    FOLLOW_UP_CLARIFICATION = "follow_up_clarification"
    MIXED_COMPOUND = "mixed_compound"
    GENERAL = "general"


class AnswerContract(str, Enum):
    DIRECT_MULTI_PART = "direct_multi_part"
    PREFERENCES_AND_ANTI_PATTERNS = "preferences_and_anti_patterns"
    DIRECT_EXPLANATION = "direct_explanation"
    ARCHITECTURE_WALKTHROUGH = "architecture_walkthrough"
    PRODUCT_FIRST = "product_first"
    BUSINESS_WITH_OUTCOMES = "business_with_outcomes"
    OUTCOMES_REQUIRED = "outcomes_required"
    FOLLOW_UP_FOCUSED = "follow_up_focused"
    GENERAL_DIRECT = "general_direct"


class EvidencePolicy(str, Enum):
    EXAMPLES_FIRST = "examples_first"
    LIGHT_PERSONAL_CONTEXT = "light_personal_context"
    CONCEPT_ONLY_UNLESS_HELPFUL = "concept_only_unless_helpful"
    ARCHITECTURE_SIGNALS = "architecture_signals"
    PRODUCT_DOMAIN_FIRST = "product_domain_first"
    BUSINESS_CONTEXT_WITH_SUPPORT = "business_context_with_support"
    REQUIRE_SUPPORTED_OUTCOMES = "require_supported_outcomes"
    FOLLOW_UP_ONLY = "follow_up_only"
    BALANCED = "balanced"


class MetricsPolicy(str, Enum):
    REQUIRED = "required"
    PREFER_IF_SUPPORTED = "prefer_if_supported"
    AVOID_UNLESS_REQUESTED = "avoid_unless_requested"


class ComplexityClass(str, Enum):
    SIMPLE = "simple"
    COMPOUND = "compound"
    DEEP_TECHNICAL = "deep_technical"
    STRATEGY = "strategy"


class AnswerShape(str, Enum):
    DIRECT_SHORT = "direct_short"
    DIRECT_STRUCTURED = "direct_structured"
    TECHNICAL_EXPLAINER = "technical_explainer"
    STRATEGIC_EXPLAINER = "strategic_explainer"


class Priority(str, Enum):
    MUST_ANSWER = "must_answer"
    SHOULD_ANSWER = "should_answer"
    NICE_TO_HAVE = "nice_to_have"


class ProviderType(str, Enum):
    STT = "stt"
    LLM = "llm"
    EMBEDDING = "embedding"


# =====================
# CORE MODELS
# =====================

class SubQuestion(BaseModel):
    """A decomposed sub-question from a compound question"""
    text: str
    type: QuestionType
    priority: Priority
    weight: float = Field(default=0.5, ge=0.0, le=1.0)


class AskBrief(BaseModel):
    """Structured ask brief produced by AskNormalizer."""
    primary_ask: str = ""
    secondary_asks: list[str] = Field(default_factory=list)
    answer_family: AskFamily = AskFamily.GENERAL
    answer_contract: AnswerContract = AnswerContract.GENERAL_DIRECT
    evidence_policy: EvidencePolicy = EvidencePolicy.BALANCED
    metrics_policy: MetricsPolicy = MetricsPolicy.PREFER_IF_SUPPORTED
    opening_strategy: str = "Answer the main ask directly."
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    why: list[str] = Field(default_factory=list)
    shadow_mode: bool = True
    latency_ms: int = 0
    fallback_used: bool = False


class LiveAskSummary(BaseModel):
    """Cached normalized summary for the latest live turn window."""
    source_turns: list[dict[str, Any]] = Field(default_factory=list)
    turn_window_size: int = 0
    signature: str = ""
    primary_ask: str = ""
    secondary_asks: list[str] = Field(default_factory=list)
    ordered_focus: list[str] = Field(default_factory=list)
    answer_family: AskFamily = AskFamily.GENERAL
    answer_contract: AnswerContract = AnswerContract.GENERAL_DIRECT
    evidence_policy: EvidencePolicy = EvidencePolicy.BALANCED
    metrics_policy: MetricsPolicy = MetricsPolicy.PREFER_IF_SUPPORTED
    opening_strategy: str = "Answer the main ask directly."
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    version: int = 1
    latency_ms: int = 0
    fallback_used: bool = False


class PlannerResult(BaseModel):
    """Structured output from the live question planner."""
    resolved_question: str = ""
    asks_in_order: list[str] = Field(default_factory=list)
    primary_ask: str = ""
    secondary_asks: list[str] = Field(default_factory=list)
    ordered_focus: list[str] = Field(default_factory=list)
    answer_focus: str = ""
    answer_style_guidance: str = ""
    draft_answer: str = ""
    question_family: AskFamily = AskFamily.GENERAL
    complexity_class: ComplexityClass = ComplexityClass.SIMPLE
    answer_shape: AnswerShape = AnswerShape.DIRECT_SHORT
    target_length: int = 120
    allow_metrics: bool = False
    allow_profile_opening: bool = False
    require_ordered_coverage: bool = False
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reasoning_summary: str = ""
    planner_source: str = "deterministic"
    planner_provider: str = ""
    planner_model: str = ""


class LivePreparedContext(BaseModel):
    """Cached live-only prepared context for low-latency post-silence generation."""
    raw_turns: list[dict[str, Any]] = Field(default_factory=list)
    sanitized_turns: list[dict[str, Any]] = Field(default_factory=list)
    turn_window_size: int = 0
    effective_turn_count: int = 0
    latest_turn_included: bool = False
    signature: str = ""
    semantic_signature: str = ""
    version: int = 1
    created_at: datetime = Field(default_factory=datetime.utcnow)
    resolved_question: str = ""
    asks_in_order: list[str] = Field(default_factory=list)
    primary_ask: str = ""
    secondary_asks: list[str] = Field(default_factory=list)
    ordered_focus: list[str] = Field(default_factory=list)
    answer_focus: str = ""
    answer_style_guidance: str = ""
    draft_answer: str = ""
    answer_family: AskFamily = AskFamily.GENERAL
    answer_contract: AnswerContract = AnswerContract.GENERAL_DIRECT
    opening_strategy: str = "Answer the main ask directly."
    metrics_policy: MetricsPolicy = MetricsPolicy.PREFER_IF_SUPPORTED
    complexity_class: ComplexityClass = ComplexityClass.SIMPLE
    answer_shape: AnswerShape = AnswerShape.DIRECT_SHORT
    target_length: int = 120
    allow_metrics: bool = False
    allow_profile_opening: bool = False
    require_ordered_coverage: bool = False
    question_text: str = ""
    request_payload: dict[str, Any] = Field(default_factory=dict)
    ask_brief: Optional[AskBrief] = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    planner_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    latency_ms: int = 0
    time_to_base_plan_ms: int = 0
    time_to_semantic_plan_ms: int = 0
    fallback_used: bool = False
    artifact_sanitized: bool = False
    sanitized_turn_count: int = 0
    plan_stage: Literal["base", "semantic"] = "base"
    planner_source: str = "deterministic"
    planner_provider: str = ""
    planner_model: str = ""
    reasoning_summary: str = ""


class ActiveAskState(BaseModel):
    """Normalized state for the currently active interviewer ask."""
    ask_key: str = ""
    question_text: str = ""
    status: Literal["open", "closed"] = "open"
    source: str = "none"
    carry_forward_reason: str = ""
    interviewer_generation: int = 0
    source_turn_start_index: Optional[int] = None
    source_turn_end_index: Optional[int] = None
    opened_at: Optional[float] = None
    updated_at: Optional[float] = None
    last_answer_committed_at: Optional[float] = None
    last_answer_committed_question_key: str = ""
    last_answer_committed_interviewer_generation: Optional[int] = None
    idle_close_threshold_sec: float = 25.0


class NormalizedRealtimeContextBundle(BaseModel):
    """Structured realtime context split into active and historical support turns."""
    turns: list[dict[str, Any]] = Field(default_factory=list)
    active_turns: list[dict[str, Any]] = Field(default_factory=list)
    historical_turns: list[dict[str, Any]] = Field(default_factory=list)
    source_turns: list[dict[str, Any]] = Field(default_factory=list)
    context_turns: int = 0
    source_turn_count: int = 0
    active_turn_count: int = 0
    historical_turn_count: int = 0
    primary_question: str = ""
    primary_question_index: Optional[int] = None
    interviewer_question_index: Optional[int] = None
    primary_question_source: str = "none"
    carry_forward_reason: str = ""
    source_signature: str = ""
    active_ask_state: ActiveAskState = Field(default_factory=ActiveAskState)


class BrainSnapshot(BaseModel):
    """Immutable snapshot consumed by the live brain."""
    session_id: str = ""
    utterance_id: str = ""
    revision_id: int = 0
    snapshot_text: str = ""
    conversation_history: list[dict[str, Any]] = Field(default_factory=list)
    snapshot_hash: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class AskIntent(BaseModel):
    """Semantic interpretation of a single interviewer ask."""
    ask_text: str = ""
    ask_intent: str = ""
    speech_act: str = ""
    decision_target: str = ""
    response_goal: str = ""
    required_evidence_types: list[str] = Field(default_factory=list)
    expected_answer_shape: str = ""
    needs_context_from_prior_turns: bool = False
    profile_evidence_mode: str = "support_if_relevant"
    company_evidence_mode: str = "support_if_relevant"
    prior_context_mode: str = "support_if_relevant"


class InterviewerNeed(BaseModel):
    """What the interviewer is really trying to learn behind the asks."""
    summary: str = ""
    dimensions: list[str] = Field(default_factory=list)
    evidence_expected: list[str] = Field(default_factory=list)


class ResponseRequirement(BaseModel):
    """Structured answer contract that Emit should realize directly."""
    answer_mode: str = "direct"
    response_order: list[str] = Field(default_factory=list)
    required_moves: list[str] = Field(default_factory=list)
    context_to_weave: list[str] = Field(default_factory=list)
    evidence_priority: list[str] = Field(default_factory=list)
    must_cover: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    paragraph_plan: list[str] = Field(default_factory=list)
    style_constraints: list[str] = Field(default_factory=list)
    profile_evidence_mode: str = "support_if_relevant"
    company_evidence_mode: str = "support_if_relevant"
    prior_context_mode: str = "support_if_relevant"


class BrainPlan(BaseModel):
    """Brain-owned response policy and structured draft for live answering."""
    session_id: str = ""
    utterance_id: str = ""
    revision_id: int = 0
    snapshot_hash: str = ""
    literal_question: str = ""
    contextualized_question: str = ""
    ordered_asks: list[str] = Field(default_factory=list)
    coverage_points: list[str] = Field(default_factory=list)
    raw_detected_asks: list[str] = Field(default_factory=list)
    clause_classifications: list[dict[str, Any]] = Field(default_factory=list)
    supporting_interviewer_context: list[str] = Field(default_factory=list)
    ask_intents: list[AskIntent] = Field(default_factory=list)
    interviewer_need: InterviewerNeed = Field(default_factory=InterviewerNeed)
    response_requirement: ResponseRequirement = Field(default_factory=ResponseRequirement)
    context_focus: list[str] = Field(default_factory=list)
    response_family: str = "mixed_multi_part"
    answer_blueprint: list[dict[str, Any]] = Field(default_factory=list)
    alignment_brief: list[str] = Field(default_factory=list)
    quality_guardrails: list[str] = Field(default_factory=list)
    resolved_question: str = ""
    question_completeness: Literal["complete", "partial", "garbled"] = "partial"
    question_type: Literal["direct", "behavioral", "technical", "business", "mixed"] = "mixed"
    response_shape: str = "direct_short"
    answer_contract: str = "general_direct"
    delivery_instructions: list[str] = Field(default_factory=list)
    tone: Literal["concise", "balanced", "professional", "technical", "executive"] = "balanced"
    directness: str = "direct"
    include_profile_opening: bool = False
    evidence_depth: str = "light"
    metrics_policy: str = "avoid_unless_helpful"
    company_context_policy: str = "support_if_relevant"
    candidate_context_policy: str = "support_if_relevant"
    ordered_coverage_required: bool = False
    target_length: int = 120
    draft_answer: str = ""
    serve_mode: Literal["direct_brain", "finalize_from_draft", "finalize_from_plan"] = "finalize_from_draft"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    stability_state: Literal["draft", "stable_candidate", "stable"] = "draft"
    plan_source: Literal["llm_fast", "safe_fallback", "cached_stable"] = "safe_fallback"
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    reasoning_summary: str = ""
    dropped_noise_clauses: list[str] = Field(default_factory=list)


class CompactEvidencePack(BaseModel):
    """Small, plan-aware evidence bundle for the finalizer."""
    plan_hash: str = ""
    candidate_snippets: list[str] = Field(default_factory=list)
    company_snippets: list[str] = Field(default_factory=list)
    interviewer_snippets: list[str] = Field(default_factory=list)
    role_evidence: list[str] = Field(default_factory=list)
    build_evidence: list[str] = Field(default_factory=list)
    leadership_evidence: list[str] = Field(default_factory=list)
    team_scope_evidence: list[str] = Field(default_factory=list)
    culture_alignment_evidence: list[str] = Field(default_factory=list)
    technical_alignment_evidence: list[str] = Field(default_factory=list)
    supporting_metrics: list[str] = Field(default_factory=list)
    excluded_topics: list[str] = Field(default_factory=list)
    mode: Literal["minimal", "full"] = "full"


class QuestionAnalysis(BaseModel):
    """Deep analysis of an interview question"""
    primary_type: QuestionType = QuestionType.BEHAVIORAL
    question_mode: QuestionMode = QuestionMode.EXPERIENCE_BASED
    response_mode: ResponseMode = ResponseMode.INTERVIEW_ANSWER
    answer_intent: AnswerIntent = AnswerIntent.MIXED
    is_compound: bool = False
    sub_questions: list[SubQuestion] = Field(default_factory=list)
    key_topics: list[str] = Field(default_factory=list)
    underlying_intent: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    related_to_previous: bool = False
    builds_on_exchange: Optional[int] = None
    recommended_style: ResponseStyle = ResponseStyle.MIXED
    response_structure: list[str] = Field(default_factory=list)
    style_reason: str = ""
    why_metrics_required: bool = True
    ask_brief: Optional[AskBrief] = None
    normalizer_applied: bool = False
    normalizer_fallback_used: bool = False
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class EvidenceChunk(BaseModel):
    """A piece of evidence retrieved from the user's profile"""
    text: str
    source: str  # "cv" | "achievement" | "job_desc" | "company"
    relevance_score: float = Field(default=0.5, ge=0.0, le=1.0)
    metadata: dict = Field(default_factory=dict)


class AssembledContext(BaseModel):
    """Full context for response generation"""
    question: str = ""
    analysis: Optional[QuestionAnalysis] = None
    ask_brief: Optional[AskBrief] = None
    evidence: list[EvidenceChunk] = Field(default_factory=list)
    conversation_summary: str = ""
    conversation_history: list[dict] = Field(default_factory=list)  # HR-2: Full conversation history for context
    topics_already_covered: list[str] = Field(default_factory=list)
    metrics_already_used: list[str] = Field(default_factory=list)
    achievements_referenced: list[str] = Field(default_factory=list)
    style_config: dict = Field(default_factory=dict)
    interview_config: dict = Field(default_factory=dict)
    delivery_mode: str = "manual"
    max_words: int = Field(default=200, ge=50, le=500)  # NEW: Control de longitud de respuesta
    working_draft: str = ""
    live_prepared_context: Optional[LivePreparedContext] = None
    brain_plan: Optional[BrainPlan] = None
    compact_evidence_pack: Optional[CompactEvidencePack] = None


class GeneratedResponse(BaseModel):
    """A generated interview response"""
    bullets: list[str] = Field(default_factory=list)
    full_response: str = ""
    key_metrics: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    style_used: ResponseStyle = ResponseStyle.EXECUTIVE
    generation_time_ms: int = 0
    mode: str = "demo"  # "demo" | "real" | "fallback" - explicit mode indicator
    metadata: dict = Field(default_factory=dict)  # Additional metadata about generation


class SuggestionUpdate(BaseModel):
    """P4-T1: WebSocket suggestion payload with full_response as primary artifact."""
    type: Literal["suggestion"] = "suggestion"
    stage: Literal["bullets", "full"] = "full"
    mode: str = "demo"
    full_response: str = ""
    bullets_preview: list[str] = Field(default_factory=list)
    bullets: list[str] = Field(default_factory=list)  # Backward-compatible field
    key_metrics: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    style: Optional[str] = None
    language: Optional[str] = None
    quality_passed: Optional[bool] = None
    quality_score: Optional[float] = None
    quality_issues: list[str] = Field(default_factory=list)
    latency_ms: Optional[int] = None
    processing_full_response: Optional[bool] = None
    bullets_latency_ms: Optional[int] = None
    full_latency_ms: Optional[int] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    transcript_id: Optional[str] = None
    request_id: Optional[str] = None
    question: Optional[str] = None
    delivery_mode: Optional[str] = None
    answer_intent: Optional[str] = None
    question_source: Optional[str] = None
    context_turns_used: Optional[int] = None
    primary_question_index: Optional[int] = None
    interviewer_question_index: Optional[int] = None
    time_to_first_answer_ms: Optional[int] = None
    time_to_refined_answer_ms: Optional[int] = None


class QualityResult(BaseModel):
    """Result of quality gate validation"""
    passed: bool = False
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    issues: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    repetitions: list[str] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=datetime.now)


class LanguageDecision(BaseModel):
    """Language detection and decision"""
    final_language: str = "es"  # "es" | "en"
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    method: str = "default"
    segments: list[dict] = Field(default_factory=list)
    user_preference: Optional[str] = None


class Exchange(BaseModel):
    """A single exchange in the interview"""
    index: int = 0
    timestamp: datetime = Field(default_factory=datetime.now)
    interviewer_utterance: str = ""
    language_detected: str = "es"
    analysis: Optional[QuestionAnalysis] = None
    suggested_response: Optional[GeneratedResponse] = None
    quality: Optional[QualityResult] = None
    user_actual_response: Optional[str] = None
    latency_ms: int = 0


# =====================
# CONVERSATION STATE
# =====================

class ConversationMap(BaseModel):
    """Tracks the state of the conversation"""
    claims: list[str] = Field(default_factory=list)
    metrics_used: list[str] = Field(default_factory=list)
    achievements_referenced: list[str] = Field(default_factory=list)
    uncovered_gaps: list[str] = Field(default_factory=list)
    interviewer_values: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    topics_covered: list[str] = Field(default_factory=list)
    summary: str = ""


class SessionState(BaseModel):
    """Full session state - single source of truth"""
    session_id: str = ""
    interview_config: dict = Field(default_factory=dict)
    conversation_map: ConversationMap = Field(default_factory=ConversationMap)
    exchanges: list[Exchange] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=datetime.now)
    status: str = "active"
    speculative_intent: Optional[str] = None
    preloaded_chunks: list[EvidenceChunk] = Field(default_factory=list)


# =====================
# PROVIDER CONFIG
# =====================

class ProviderConfig(BaseModel):
    """Configuration for a provider"""
    alias: str = ""
    provider: str = ""
    model: str = ""
    config: dict = Field(default_factory=dict)


class ProviderRegistry(BaseModel):
    """Registry of all providers"""
    stt: dict[str, ProviderConfig] = Field(default_factory=dict)
    llm: dict[str, ProviderConfig] = Field(default_factory=dict)
    embedding: dict[str, ProviderConfig] = Field(default_factory=dict)


# =====================
# INTERVIEW CONFIG
# =====================

class InterviewConfig(BaseModel):
    """User's interview configuration"""
    company_name: str = ""
    role_title: str = ""
    job_description: Optional[str] = None
    company_values: list[str] = Field(default_factory=list)
    response_style: ResponseStyle = ResponseStyle.MIXED
    language_preference: str = "auto"  # "auto" | "es" | "en"
    custom_rules: Optional[str] = None
    stt_alias: str = "stt_primary"
    llm_alias: str = "llm_main"
    embedding_alias: str = "embedding_primary"


class UserProfile(BaseModel):
    """User's professional profile"""
    name: str = ""
    resume_text: Optional[str] = None
    achievements: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    experience_years: int = 0
