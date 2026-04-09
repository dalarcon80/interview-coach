"""
Interview Coach - Unit Tests for Contracts
Tests for Pydantic model validation
"""
import pytest
from datetime import datetime

from contracts.models import (
    AskBrief,
    AskFamily,
    AnswerContract,
    LiveAskSummary,
    LivePreparedContext,
    ComplexityClass,
    AnswerShape,
    QuestionType,
    ResponseStyle,
    MetricsPolicy,
    EvidencePolicy,
    Priority,
    ProviderType,
    SubQuestion,
    QuestionAnalysis,
    EvidenceChunk,
    AssembledContext,
    GeneratedResponse,
    QualityResult,
    LanguageDecision,
    Exchange,
    ConversationMap,
    SessionState,
    ProviderConfig,
    ProviderRegistry,
    InterviewConfig,
    UserProfile,
)


class TestEnums:
    """Test enum values"""
    
    def test_question_type_values(self):
        """Test all question type enum values"""
        assert QuestionType.BEHAVIORAL.value == "behavioral"
        assert QuestionType.TECHNICAL.value == "technical"
        assert QuestionType.SITUATIONAL.value == "situational"
        assert QuestionType.CASUAL.value == "casual"
        assert QuestionType.FOLLOW_UP.value == "follow_up"
        assert QuestionType.STRESS.value == "stress"
        assert QuestionType.COMPOUND.value == "compound"
    
    def test_response_style_values(self):
        """Test all response style enum values"""
        assert ResponseStyle.EXECUTIVE.value == "executive"
        assert ResponseStyle.COMMERCIAL.value == "commercial"
        assert ResponseStyle.TECHNICAL.value == "technical"
        assert ResponseStyle.MIXED.value == "mixed"
    
    def test_priority_values(self):
        """Test all priority enum values"""
        assert Priority.MUST_ANSWER.value == "must_answer"
        assert Priority.SHOULD_ANSWER.value == "should_answer"
        assert Priority.NICE_TO_HAVE.value == "nice_to_have"

    def test_ask_family_values(self):
        assert AskFamily.CULTURE_FIT.value == "culture_fit"
        assert AskFamily.MIXED_COMPOUND.value == "mixed_compound"

    def test_answer_contract_values(self):
        assert AnswerContract.DIRECT_MULTI_PART.value == "direct_multi_part"
        assert AnswerContract.GENERAL_DIRECT.value == "general_direct"

    def test_live_complexity_values(self):
        assert ComplexityClass.SIMPLE.value == "simple"
        assert ComplexityClass.DEEP_TECHNICAL.value == "deep_technical"

    def test_answer_shape_values(self):
        assert AnswerShape.DIRECT_SHORT.value == "direct_short"
        assert AnswerShape.STRATEGIC_EXPLAINER.value == "strategic_explainer"


class TestSubQuestion:
    """Test SubQuestion model"""
    
    def test_subquestion_creation(self):
        """Test creating a subquestion"""
        sq = SubQuestion(
            text="What is your experience with scaling teams?",
            type=QuestionType.BEHAVIORAL,
            priority=Priority.MUST_ANSWER,
            weight=0.8,
        )
        assert sq.text == "What is your experience with scaling teams?"
        assert sq.type == QuestionType.BEHAVIORAL
        assert sq.priority == Priority.MUST_ANSWER
        assert sq.weight == 0.8
    
    def test_subquestion_default_weight(self):
        """Test default weight value"""
        sq = SubQuestion(
            text="Test question",
            type=QuestionType.TECHNICAL,
            priority=Priority.SHOULD_ANSWER,
        )
        assert sq.weight == 0.5
    
    def test_subquestion_weight_validation(self):
        """Test weight must be between 0 and 1"""
        with pytest.raises(ValueError):
            SubQuestion(
                text="Test",
                type=QuestionType.TECHNICAL,
                priority=Priority.SHOULD_ANSWER,
                weight=1.5,
            )
        with pytest.raises(ValueError):
            SubQuestion(
                text="Test",
                type=QuestionType.TECHNICAL,
                priority=Priority.SHOULD_ANSWER,
                weight=-0.5,
            )


class TestQuestionAnalysis:
    """Test QuestionAnalysis model"""
    
    def test_question_analysis_creation(self):
        """Test creating a question analysis"""
        analysis = QuestionAnalysis(
            primary_type=QuestionType.COMPOUND,
            is_compound=True,
            sub_questions=[
                SubQuestion(
                    text="Tell me about yourself",
                    type=QuestionType.BEHAVIORAL,
                    priority=Priority.MUST_ANSWER,
                )
            ],
            key_topics=["leadership", "scaling"],
            underlying_intent=["assess seniority"],
            red_flags=["avoid being vague"],
            recommended_style=ResponseStyle.EXECUTIVE,
        )
        assert analysis.primary_type == QuestionType.COMPOUND
        assert analysis.is_compound is True
        assert len(analysis.sub_questions) == 1
        assert "leadership" in analysis.key_topics
    
    def test_question_analysis_defaults(self):
        """Test default values for question analysis"""
        analysis = QuestionAnalysis()
        assert analysis.primary_type == QuestionType.BEHAVIORAL
        assert analysis.is_compound is False
        assert analysis.sub_questions == []
        assert analysis.confidence == 0.8
        assert analysis.ask_brief is None


class TestEvidenceChunk:
    """Test EvidenceChunk model"""
    
    def test_evidence_chunk_creation(self):
        """Test creating an evidence chunk"""
        chunk = EvidenceChunk(
            text="Led a team of 15 engineers",
            source="cv",
            relevance_score=0.9,
            metadata={"section": "experience"},
        )
        assert chunk.text == "Led a team of 15 engineers"
        assert chunk.source == "cv"
        assert chunk.relevance_score == 0.9
    
    def test_evidence_chunk_score_validation(self):
        """Test relevance score validation"""
        with pytest.raises(ValueError):
            EvidenceChunk(text="Test", source="cv", relevance_score=1.5)


class TestGeneratedResponse:
    """Test GeneratedResponse model"""
    
    def test_generated_response_creation(self):
        """Test creating a generated response"""
        response = GeneratedResponse(
            bullets=["First point", "Second point"],
            full_response="This is the full response",
            key_metrics=["15 engineers", "3x growth"],
            confidence=0.85,
            style_used=ResponseStyle.EXECUTIVE,
            generation_time_ms=500,
        )
        assert len(response.bullets) == 2
        assert response.full_response == "This is the full response"
        assert len(response.key_metrics) == 2


class TestAskBrief:
    def test_ask_brief_creation(self):
        brief = AskBrief(
            primary_ask="What are you looking for in a team?",
            secondary_asks=["What do you avoid?"],
            answer_family=AskFamily.CULTURE_FIT,
            answer_contract=AnswerContract.PREFERENCES_AND_ANTI_PATTERNS,
            evidence_policy=EvidencePolicy.LIGHT_PERSONAL_CONTEXT,
            metrics_policy=MetricsPolicy.AVOID_UNLESS_REQUESTED,
            confidence=0.82,
        )
        assert brief.answer_family == AskFamily.CULTURE_FIT
        assert brief.metrics_policy == MetricsPolicy.AVOID_UNLESS_REQUESTED
        assert brief.secondary_asks == ["What do you avoid?"]


class TestLiveAskSummary:
    def test_live_ask_summary_creation(self):
        summary = LiveAskSummary(
            source_turns=[{"speaker": "interviewer", "text": "Tell me about building from zero"}],
            turn_window_size=1,
            signature="build-zero",
            primary_ask="Tell me about building from zero",
            secondary_asks=["How big were the teams?", "What roles did they have?"],
            ordered_focus=[
                "Tell me about building from zero",
                "How big were the teams?",
                "What roles did they have?",
            ],
            answer_family=AskFamily.MIXED_COMPOUND,
            answer_contract=AnswerContract.DIRECT_MULTI_PART,
            evidence_policy=EvidencePolicy.EXAMPLES_FIRST,
            metrics_policy=MetricsPolicy.PREFER_IF_SUPPORTED,
            confidence=0.89,
            version=2,
            latency_ms=14,
        )
        assert summary.turn_window_size == 1
        assert summary.signature == "build-zero"
        assert summary.answer_family == AskFamily.MIXED_COMPOUND
        assert summary.ordered_focus[0] == "Tell me about building from zero"


class TestLivePreparedContext:
    def test_live_prepared_context_creation(self):
        prepared = LivePreparedContext(
            raw_turns=[{"speaker": "interviewer", "text": "What are you looking for?"}],
            sanitized_turns=[{"speaker": "interviewer", "text": "What are you looking for?"}],
            turn_window_size=1,
            signature="culture-fit",
            primary_ask="What are you looking for?",
            secondary_asks=["What do you avoid?"],
            ordered_focus=["What are you looking for?", "What do you avoid?"],
            answer_family=AskFamily.CULTURE_FIT,
            answer_contract=AnswerContract.PREFERENCES_AND_ANTI_PATTERNS,
            complexity_class=ComplexityClass.SIMPLE,
            answer_shape=AnswerShape.DIRECT_SHORT,
            target_length=110,
            allow_metrics=False,
            allow_profile_opening=False,
            require_ordered_coverage=False,
            question_text="What are you looking for?\nAlso cover:\n- What do you avoid?",
            request_payload={"question": "What are you looking for?"},
            ask_brief=AskBrief(primary_ask="What are you looking for?"),
            sanitized_turn_count=1,
        )
        assert prepared.complexity_class == ComplexityClass.SIMPLE
        assert prepared.answer_shape == AnswerShape.DIRECT_SHORT
        assert prepared.target_length == 110


class TestQualityResult:
    """Test QualityResult model"""
    
    def test_quality_result_pass(self):
        """Test passing quality result"""
        result = QualityResult(
            passed=True,
            score=0.9,
            issues=[],
        )
        assert result.passed is True
        assert result.score == 0.9
    
    def test_quality_result_fail(self):
        """Test failing quality result"""
        result = QualityResult(
            passed=False,
            score=0.4,
            issues=["Repeats metric from exchange 2", "Too long"],
            contradictions=["Claimed 3x growth but previously said 2x"],
        )
        assert result.passed is False
        assert len(result.issues) == 2
        assert len(result.contradictions) == 1


class TestLanguageDecision:
    """Test LanguageDecision model"""
    
    def test_language_decision_spanish(self):
        """Test Spanish language decision"""
        decision = LanguageDecision(
            final_language="es",
            confidence=0.95,
            method="dominant",
        )
        assert decision.final_language == "es"
        assert decision.confidence == 0.95
    
    def test_language_decision_english(self):
        """Test English language decision"""
        decision = LanguageDecision(
            final_language="en",
            confidence=0.9,
            method="user_preference",
            user_preference="en",
        )
        assert decision.final_language == "en"
        assert decision.user_preference == "en"


class TestExchange:
    """Test Exchange model"""
    
    def test_exchange_creation(self):
        """Test creating an exchange"""
        exchange = Exchange(
            index=1,
            interviewer_utterance="Tell me about yourself",
            language_detected="es",
            latency_ms=1200,
        )
        assert exchange.index == 1
        assert exchange.interviewer_utterance == "Tell me about yourself"
        assert exchange.latency_ms == 1200


class TestSessionState:
    """Test SessionState model"""
    
    def test_session_state_creation(self):
        """Test creating a session state"""
        state = SessionState(
            session_id="test-session-123",
            status="active",
        )
        assert state.session_id == "test-session-123"
        assert state.status == "active"
        assert isinstance(state.conversation_map, ConversationMap)
        assert state.exchanges == []
    
    def test_session_state_with_exchanges(self):
        """Test session state with exchanges"""
        exchange = Exchange(
            index=0,
            interviewer_utterance="First question",
        )
        state = SessionState(
            session_id="test-session",
            exchanges=[exchange],
        )
        assert len(state.exchanges) == 1


class TestProviderConfig:
    """Test ProviderConfig model"""
    
    def test_provider_config_creation(self):
        """Test creating a provider config"""
        config = ProviderConfig(
            alias="llm_main",
            provider="anthropic",
            model="claude-sonnet-4-20250514",
            config={"temperature": 0.3},
        )
        assert config.alias == "llm_main"
        assert config.provider == "anthropic"
        assert config.model == "claude-sonnet-4-20250514"


class TestInterviewConfig:
    """Test InterviewConfig model"""
    
    def test_interview_config_creation(self):
        """Test creating an interview config"""
        config = InterviewConfig(
            company_name="Acme Corp",
            role_title="CTO",
            response_style=ResponseStyle.EXECUTIVE,
            language_preference="es",
        )
        assert config.company_name == "Acme Corp"
        assert config.role_title == "CTO"
        assert config.response_style == ResponseStyle.EXECUTIVE
    
    def test_interview_config_defaults(self):
        """Test default values for interview config"""
        config = InterviewConfig()
        assert config.response_style == ResponseStyle.MIXED
        assert config.language_preference == "auto"
        assert config.stt_alias == "stt_primary"
        assert config.llm_alias == "llm_main"


class TestUserProfile:
    """Test UserProfile model"""
    
    def test_user_profile_creation(self):
        """Test creating a user profile"""
        profile = UserProfile(
            name="John Doe",
            resume_text="Experienced CTO...",
            achievements=["Scaled team from 5 to 50"],
            skills=["Python", "Leadership", "Architecture"],
            experience_years=15,
        )
        assert profile.name == "John Doe"
        assert len(profile.achievements) == 1
        assert len(profile.skills) == 3
        assert profile.experience_years == 15
