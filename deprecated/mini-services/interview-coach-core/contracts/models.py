"""
Interview Coach - Core Data Contracts
Pydantic models for the entire pipeline
Aligned with Architecture v3.2.1
"""
from pydantic import BaseModel, Field
from typing import Optional, Any
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


class QuestionAnalysis(BaseModel):
    """Deep analysis of an interview question"""
    primary_type: QuestionType = QuestionType.BEHAVIORAL
    is_compound: bool = False
    sub_questions: list[SubQuestion] = Field(default_factory=list)
    key_topics: list[str] = Field(default_factory=list)
    underlying_intent: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    related_to_previous: bool = False
    builds_on_exchange: Optional[int] = None
    recommended_style: ResponseStyle = ResponseStyle.MIXED
    response_structure: list[str] = Field(default_factory=list)
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
    evidence: list[EvidenceChunk] = Field(default_factory=list)
    conversation_summary: str = ""
    topics_already_covered: list[str] = Field(default_factory=list)
    metrics_already_used: list[str] = Field(default_factory=list)
    achievements_referenced: list[str] = Field(default_factory=list)
    style_config: dict = Field(default_factory=dict)
    interview_config: dict = Field(default_factory=dict)


class GeneratedResponse(BaseModel):
    """A generated interview response"""
    bullets: list[str] = Field(default_factory=list)
    full_response: str = ""
    key_metrics: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    style_used: ResponseStyle = ResponseStyle.EXECUTIVE
    generation_time_ms: int = 0


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
