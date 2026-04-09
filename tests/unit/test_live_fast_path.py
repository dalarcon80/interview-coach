from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from api.server import (
    SuggestRequest,
    _build_live_cached_draft_response,
    _canonicalize_live_prepared_context,
    _suggest_live_prepared_response,
    suggest_response,
)
from contracts.models import (
    AskBrief,
    AskFamily,
    AnswerContract,
    AnswerShape,
    ComplexityClass,
    GeneratedResponse,
    LivePreparedContext,
    QualityResult,
    ResponseStyle,
)


def _live_prepared_context() -> LivePreparedContext:
    return LivePreparedContext(
        raw_turns=[
            {"speaker": "interviewer", "text": "What are you looking for in a company?"},
            {"speaker": "interviewer", "text": "What do you avoid?"},
        ],
        sanitized_turns=[
            {"speaker": "interviewer", "text": "What are you looking for in a company?"},
            {"speaker": "interviewer", "text": "What do you avoid?"},
        ],
        turn_window_size=2,
        signature="live-fast-sig",
        version=3,
        created_at=datetime.utcnow(),
        primary_ask="What are you looking for in a company?",
        secondary_asks=["What do you avoid?"],
        ordered_focus=[
            "What are you looking for in a company?",
            "What do you avoid?",
        ],
        answer_family=AskFamily.CULTURE_FIT,
        answer_contract=AnswerContract.PREFERENCES_AND_ANTI_PATTERNS,
        complexity_class=ComplexityClass.SIMPLE,
        answer_shape=AnswerShape.DIRECT_SHORT,
        target_length=120,
        allow_metrics=False,
        allow_profile_opening=False,
        require_ordered_coverage=True,
        question_text="What are you looking for in a company?\nAlso cover:\n- What do you avoid?",
        request_payload={},
        ask_brief=AskBrief(
            primary_ask="What are you looking for in a company?",
            secondary_asks=["What do you avoid?"],
            answer_family=AskFamily.CULTURE_FIT,
            answer_contract=AnswerContract.PREFERENCES_AND_ANTI_PATTERNS,
            confidence=0.92,
        ),
        draft_answer="I'm looking for a role with technical depth, direct client impact, and a pragmatic team. I avoid overly political environments and work that stays too far from execution.",
        confidence=0.92,
        latency_ms=15,
        planner_source="deterministic",
    )


class _FakeWebSocket:
    def __init__(self):
        self.events: list[dict] = []

    async def send_json(self, payload: dict):
        self.events.append(payload)


@pytest.mark.asyncio
async def test_live_manual_prepared_context_skips_heavy_analyzer_and_retrieval():
    prepared = _live_prepared_context()
    request = SuggestRequest(
        question=prepared.question_text,
        session_id="live-fast-session",
        candidate_profile={
            "name": "Daniel",
            "current_role": "Technology Director - Data & AI",
            "company": "Globant",
            "summary": "Technology executive with experience in transformation and delivery.",
            "achievements": [
                "Built AI Pods from scratch and scaled it to 17+ accounts.",
                "Founded GenAI practice in Colombia.",
            ],
            "skills": ["Data", "AI", "Modernization"],
        },
        company_info={
            "companyName": "Cuesta Partners",
            "positionTitle": "Principal Consultant",
            "roleTitle": "Principal Consultant",
            "companyDescription": "Consulting firm focused on mid-market companies.",
            "companyCulture": "Pragmatic, hands-on, operator mindset.",
            "roleRequirements": ["Technical depth", "Client impact"],
        },
        interviewer_profile={
            "name": "Marcus",
            "likelyFocusAreas": ["Culture fit", "Operating style"],
        },
        style_id="professional",
        language="en",
        mode="real",
        max_words=140,
        interview_type="mixed",
        conversation_history=prepared.sanitized_turns,
        preserve_question_text=True,
        _live_prepared_context=prepared.model_dump(mode="json"),
        _delivery_mode_override="live_manual",
    )

    generated = GeneratedResponse(
        bullets=["technical depth", "operator culture"],
        full_response="I'm looking for technical depth, direct client impact, and a pragmatic culture.",
        confidence=0.9,
        mode="real",
        metadata={},
    )
    quality = QualityResult(passed=True, score=0.92, issues=[])

    with patch(
        "pipeline.steps.question_analyzer.QuestionAnalyzer.analyze",
        new=AsyncMock(side_effect=AssertionError("heavy analyzer should not run for live fast path")),
    ), patch(
        "pipeline.steps.evidence_retriever.EvidenceRetriever.retrieve",
        new=AsyncMock(side_effect=AssertionError("vector retrieval should not run for live fast path")),
    ), patch(
        "pipeline.steps.response_composer.ResponseComposer.compose",
        new=AsyncMock(return_value=generated),
    ), patch(
        "pipeline.steps.quality_gate.QualityGate.process",
        new=AsyncMock(return_value=(generated, quality)),
    ):
        response = await suggest_response(request)

    assert response["success"] is True
    assert response["full_response"] == generated.full_response
    assert response["debug"]["live_fast_path_used"] is True
    assert response["debug"]["live_fast_evidence_count"] >= 1
    assert response["debug"]["normalized_primary_ask"] == "What are you looking for in a company?"


@pytest.mark.asyncio
async def test_live_prepared_response_uses_single_final_fallback_without_preview():
    prepared = _live_prepared_context()
    websocket = _FakeWebSocket()
    interview_config = {
        "candidate": {
            "name": "Daniel",
            "current_role": "Technology Director - Data & AI",
            "company": "Globant",
            "summary": "Technology executive with experience in transformation and delivery.",
            "achievements": [
                "Built AI Pods from scratch and scaled it to 17+ accounts.",
            ],
            "skills": ["Data", "AI", "Modernization"],
        },
        "company": {
            "companyName": "Cuesta Partners",
            "positionTitle": "Principal Consultant",
            "roleTitle": "Principal Consultant",
            "companyDescription": "Consulting firm focused on mid-market companies.",
            "companyCulture": "Pragmatic, hands-on, operator mindset.",
            "roleRequirements": ["Technical depth", "Client impact"],
        },
        "interviewer": {
            "name": "Marcus",
            "likelyFocusAreas": ["Culture fit", "Operating style"],
        },
        "style_id": "professional",
        "language_preference": "en",
        "max_words": 140,
    }

    generated = GeneratedResponse(
        bullets=["technical depth", "operator culture"],
        full_response="I'm looking for technical depth, direct client impact, and an operator culture.",
        key_metrics=[],
        confidence=0.91,
        style_used=ResponseStyle.EXECUTIVE,
        generation_time_ms=900,
        mode="real",
        metadata={"provider": "anthropic", "model": "claude"},
    )
    async def _compose_without_preview(context, on_bullets=None):
        assert on_bullets is None
        return generated

    with patch(
        "api.server.resolve_server_mode",
        new=AsyncMock(return_value=("real", "env", None, None, None)),
    ), patch(
        "pipeline.steps.response_composer.ResponseComposer.compose",
        new=AsyncMock(side_effect=_compose_without_preview),
    ):
        response = await _suggest_live_prepared_response(
            websocket=websocket,
            session_id="live-preview-session",
            interview_config=interview_config,
            question_text=prepared.question_text,
            conversation_history=prepared.sanitized_turns,
            live_prepared_context=prepared,
        )

    assert response["success"] is True
    assert response["full_response"] == generated.full_response
    assert websocket.events == []
    assert response["debug"]["path_used"] == "writer_emergency_fallback"
    assert response["debug"]["fallback_used"] is True


def test_canonicalize_live_prepared_context_keeps_original_snapshot():
    prepared = LivePreparedContext(
        raw_turns=[
            {"speaker": "interviewer", "text": "And tell me,"},
            {"speaker": "interviewer", "text": "why are you looking for a job? Like, what's what are you looking for?"},
        ],
        sanitized_turns=[
            {"speaker": "interviewer", "text": "tell me"},
            {"speaker": "interviewer", "text": "why are you looking for a job? Like, what's what are you looking for?"},
        ],
        turn_window_size=2,
        signature="wrapper-sig",
        version=1,
        created_at=datetime.utcnow(),
        primary_ask="tell me",
        secondary_asks=["why are you looking for a job?"],
        ordered_focus=["tell me", "why are you looking for a job?"],
        question_text="tell me\nAlso cover:\n- why are you looking for a job?",
        ask_brief=AskBrief(
            primary_ask="tell me",
            secondary_asks=["why are you looking for a job?"],
            answer_family=AskFamily.GENERAL,
            answer_contract=AnswerContract.GENERAL_DIRECT,
            confidence=0.8,
        ),
        confidence=0.8,
    )

    canonical = _canonicalize_live_prepared_context(prepared)

    assert canonical is not None
    assert canonical == prepared


def test_canonicalize_live_prepared_context_does_not_rewrite_compound_ask():
    prepared = LivePreparedContext(
        raw_turns=[
            {
                "speaker": "interviewer",
                "text": "We were talking about your expectations. So now I just wanted to ask you, like, what are you looking for in terms of the company, the culture, teams? What's important for you, or what kind of things",
            },
            {
                "speaker": "interviewer",
                "text": "the company, the culture, teams? What's important for you, or what kind of things you absolutely don't like.",
            },
        ],
        sanitized_turns=[
            {
                "speaker": "interviewer",
                "text": "what are you looking for in terms of the company, the culture, teams? What's important for you, or what kind of things",
            },
            {
                "speaker": "interviewer",
                "text": "the company, the culture, teams? What's important for you, or what kind of things you absolutely don't like.",
            },
        ],
        turn_window_size=2,
        signature="culture-fit-sig",
        version=1,
        created_at=datetime.utcnow(),
        primary_ask="what are you looking for in terms of the company, the culture, teams?",
        secondary_asks=["What's important for you, or what kind of things the company, the culture, teams?"],
        ordered_focus=[
            "what are you looking for in terms of the company, the culture, teams?",
            "What's important for you, or what kind of things the company, the culture, teams?",
        ],
        question_text="what are you looking for in terms of the company, the culture, teams?\nAlso cover:\n- What's important for you, or what kind of things the company, the culture, teams?",
        ask_brief=AskBrief(
            primary_ask="what are you looking for in terms of the company, the culture, teams?",
            secondary_asks=["What's important for you, or what kind of things the company, the culture, teams?"],
            answer_family=AskFamily.CULTURE_FIT,
            answer_contract=AnswerContract.PREFERENCES_AND_ANTI_PATTERNS,
            confidence=0.85,
        ),
        confidence=0.85,
    )

    canonical = _canonicalize_live_prepared_context(prepared)

    assert canonical is not None
    assert canonical == prepared


def test_build_live_cached_draft_response_uses_prepared_context_contract():
    prepared = _live_prepared_context()

    response = _build_live_cached_draft_response(
        interview_config={
            "style_id": "professional",
            "language_preference": "en",
        },
        question_text=prepared.question_text,
        live_prepared_context=prepared,
        mode="real",
    )

    assert response["success"] is True
    assert response["full_response"] == prepared.draft_answer
    assert response["debug"]["live_brain_cached_draft_used"] is True
    assert response["debug"]["normalized_primary_ask"] == "What are you looking for in a company?"
    assert response["bullets"] == [
        "I'm looking for a role with technical depth, direct client impact, and a pragmatic team",
        "I avoid overly political environments and work that stays too far from execution",
    ]
