"""Tests for the live question planner."""

import json
from types import SimpleNamespace

import pytest

from pipeline.steps.ask_normalizer import AskNormalizer
from pipeline.steps.live_question_planner import LiveQuestionPlanner
from contracts.models import AskFamily, AnswerShape, ComplexityClass


def _interview_config() -> dict:
    return {
        "candidate": {"name": "Daniel"},
        "company": {"companyName": "Cuesta"},
        "interviewer": {"name": "Marcus"},
        "style_id": "professional",
        "language_preference": "en",
        "interview_type": "mixed",
        "max_words": 200,
    }


@pytest.mark.asyncio
async def test_planner_prioritizes_compound_focus_from_last_five_turns():
    planner = LiveQuestionPlanner(AskNormalizer())
    turns = [
        {"text": "So, yeah, so I guess, Danielle, in terms of your experience, I would like to hear specifically"},
        {"text": "Sorry. I have a terrible cough, and that won't go away. But I was"},
        {"text": "hear specifically examples of"},
        {
            "text": (
                "companies or experiences that you've had where you had to build from 0. "
                "Building a product from 0, a team from 0, a a service from Siro. "
                "Now I wanna get a sense of your experience in building from 0, building from scratch. Early stages. "
                "And then, also very curious, to hear about your team management experience. "
                "Big were the teams you've managed?"
            )
        },
        {
            "text": (
                "What roles did they have, etcetera. "
                "And last question as as we go. "
                "So if you want, just kinda start telling us or telling me a little bit about you."
            )
        },
    ]

    prepared = await planner.prepare(
        session_id="session-1",
        raw_turns=turns,
        interview_config=_interview_config(),
        mode="real",
    )

    assert prepared is not None
    assert prepared.turn_window_size == 5
    assert prepared.answer_family == AskFamily.MIXED_COMPOUND
    assert prepared.complexity_class == ComplexityClass.COMPOUND
    assert prepared.answer_shape == AnswerShape.DIRECT_STRUCTURED
    assert (
        "building from 0" in prepared.primary_ask.lower()
        or "build from 0" in prepared.primary_ask.lower()
    )
    assert any("team management" in ask.lower() for ask in prepared.secondary_asks)
    assert any("how big were the teams" in ask.lower() for ask in prepared.secondary_asks)
    assert any("what roles did they have" in ask.lower() for ask in prepared.secondary_asks)
    assert prepared.question_text == prepared.resolved_question
    assert prepared.asks_in_order[0] == prepared.primary_ask
    assert "tell us or telling me a little bit about you" not in prepared.question_text.lower()


@pytest.mark.asyncio
async def test_planner_shapes_culture_fit_as_simple_direct_answer():
    planner = LiveQuestionPlanner(AskNormalizer())
    turns = [
        {"text": "Danielle, we will talk about like, your expectations in terms of the role,"},
        {
            "text": (
                "and or not the role, but, yeah, but basically what you have done in your experience. "
                "So now I just wanted to ask you, like, what are you looking for in terms of"
            )
        },
        {
            "text": "the company, the culture, teams? What's important for you, or what kind of things you absolutely like."
        },
    ]

    prepared = await planner.prepare(
        session_id="session-2",
        raw_turns=turns,
        interview_config=_interview_config(),
        mode="real",
    )

    assert prepared is not None
    assert prepared.answer_family in {AskFamily.GENERAL, AskFamily.MIXED_COMPOUND}
    assert prepared.complexity_class in {ComplexityClass.SIMPLE, ComplexityClass.COMPOUND}
    assert prepared.answer_shape in {AnswerShape.DIRECT_SHORT, AnswerShape.DIRECT_STRUCTURED}
    assert prepared.allow_profile_opening is False
    assert prepared.allow_metrics is False
    assert "what are you looking for" in prepared.primary_ask.lower()
    assert prepared.question_text
    assert "company" in prepared.question_text.lower()
    assert "culture" in prepared.question_text.lower()
    assert prepared.latest_turn_included is True


@pytest.mark.asyncio
async def test_planner_merges_continuation_without_duplicate_overlap():
    planner = LiveQuestionPlanner(AskNormalizer())
    turns = [
        {"text": "So now I just wanted to ask you, like, what are you looking for in terms of"},
        {
            "text": (
                "the company, the culture, teams? What's important for you, "
                "or what kind of things you absolutely"
            )
        },
        {"text": "you absolutely like"},
    ]

    prepared = planner.prepare_base(
        session_id="session-2b",
        raw_turns=turns,
        interview_config=_interview_config(),
        mode="real",
    )

    assert prepared is not None
    combined_question = prepared.question_text.lower()
    assert "you absolutely you absolutely like" not in combined_question
    assert "what kind of things you absolutely like" in combined_question
    assert any(
        "what kind of things you absolutely like" in ask.lower()
        for ask in prepared.asks_in_order
    )


@pytest.mark.asyncio
async def test_planner_builds_live_request_payload_from_sanitized_turns():
    planner = LiveQuestionPlanner(AskNormalizer())
    turns = [
        {"text": "[STT Error: sent 1000 (OK); then received 1000 (OK)] What are you looking for in terms of"},
        {"text": "the company, the culture, teams?"},
    ]

    prepared = await planner.prepare(
        session_id="session-3",
        raw_turns=turns,
        interview_config=_interview_config(),
        mode="real",
    )

    assert prepared is not None
    assert prepared.artifact_sanitized is True
    assert prepared.request_payload["preserve_question_text"] is True
    assert prepared.request_payload["conversation_history"] == prepared.sanitized_turns
    assert all(turn["speaker"] == "interviewer" for turn in prepared.sanitized_turns)
    assert "[stt error" not in prepared.question_text.lower()


def test_planner_signature_uses_exact_effective_turn_window():
    planner = LiveQuestionPlanner(AskNormalizer())
    turns_a = [
        {"text": "What are you looking for in a company?"},
        {"text": "What do you avoid?"},
    ]
    turns_b = [
        {"text": "What are you looking for in a company?"},
        {"text": "What do you avoid the most?"},
    ]

    sig_a = planner.build_signature(turns_a)
    sig_b = planner.build_signature(turns_b)

    assert sig_a
    assert sig_b
    assert sig_a != sig_b


@pytest.mark.asyncio
async def test_planner_handles_single_direct_turn_without_waiting_for_five():
    planner = LiveQuestionPlanner(AskNormalizer())
    turns = [
        {"text": "And tell me, why are you looking for a job? Like, what's what do you looking for?"},
    ]

    prepared = planner.prepare_base(
        session_id="session-single-turn",
        raw_turns=turns,
        interview_config=_interview_config(),
        mode="real",
    )

    assert prepared is not None
    assert prepared.turn_window_size == 1
    assert prepared.effective_turn_count == 1
    assert prepared.latest_turn_included is True
    assert prepared.plan_stage == "base"
    assert prepared.primary_ask
    assert "clarify" not in prepared.question_text.lower()
    assert prepared.question_text == prepared.resolved_question == prepared.primary_ask
    assert prepared.ask_brief is not None
    assert prepared.ask_brief.fallback_used is False
    assert "looking for" in prepared.primary_ask.lower() or "why are you looking" in prepared.primary_ask.lower()


@pytest.mark.asyncio
async def test_planner_discards_empty_wrapper_turn_before_direct_question():
    planner = LiveQuestionPlanner(AskNormalizer())
    turns = [
        {"text": "And tell me,"},
        {"text": "why are you looking for a job? Like, what's what are you looking for?"},
    ]

    prepared = planner.prepare_base(
        session_id="session-wrapper-turn",
        raw_turns=turns,
        interview_config=_interview_config(),
        mode="real",
    )

    assert prepared is not None
    assert prepared.turn_window_size == 1 or prepared.turn_window_size == 2
    assert prepared.latest_turn_included is True
    assert prepared.primary_ask.lower() == "why are you looking for a job?"
    assert prepared.secondary_asks == []
    assert prepared.asks_in_order == ["why are you looking for a job?"]
    assert prepared.resolved_question == "why are you looking for a job?"


class _FakeFastAdapter:
    model = "test-fast"

    async def generate(self, messages, config):
        return (
            "First, I built a couple of things from zero, including the GenAI practice at "
            "Accenture and the AI Pods operating model at Globant. Second, on team management, "
            "I currently lead 20 direct managers and 345 people indirectly. Finally, those teams "
            "included delivery leads, architects, engineers, and program managers."
        )


@pytest.mark.asyncio
async def test_planner_prefers_fast_llm_result_when_available():
    planner = LiveQuestionPlanner(
        AskNormalizer(),
        adapter_factory=lambda alias: _FakeFastAdapter(),
    )
    turns = [
        {"text": "I want to hear examples of what you've built from zero."},
        {"text": "How big were the teams you've managed?"},
        {"text": "What roles did they have?"},
    ]

    prepared = await planner.prepare(
        session_id="session-4",
        raw_turns=turns,
        interview_config=_interview_config(),
        mode="real",
    )

    assert prepared is not None
    assert prepared.planner_source == "llm_fast"
    assert prepared.planner_model == "test-fast"
    assert prepared.plan_stage == "semantic"
    assert prepared.semantic_signature == prepared.signature
    assert prepared.resolved_question.startswith("Answer these interviewer asks in order:")
    assert prepared.draft_answer.startswith("First, I built a couple of things from zero")
    assert "20 direct managers and 345 people indirectly" in prepared.draft_answer
    assert "direct-draft live brain fallback" in prepared.reasoning_summary.lower()


class _PlaceholderFastAdapter:
    model = "test-fast"

    async def generate(self, messages, config):
        return json.dumps(
            {
                "resolved_question": "Why are you looking for a job?",
                "asks_in_order": ["Why are you looking for a job?"],
                "answer_focus": "Answer the motivation directly.",
                "answer_style_guidance": "Keep it direct and speakable.",
                "draft_answer": "Go ahead—I'm ready for your question.",
                "confidence": 0.88,
                "reasoning_summary": "Simple direct ask.",
            }
        )


@pytest.mark.asyncio
async def test_planner_rejects_placeholder_draft_from_fast_llm():
    planner = LiveQuestionPlanner(
        AskNormalizer(),
        adapter_factory=lambda alias: _PlaceholderFastAdapter(),
    )
    turns = [
        {"text": "And tell me, why are you looking for a job?"},
    ]

    prepared = await planner.prepare(
        session_id="session-placeholder-reject",
        raw_turns=turns,
        interview_config=_interview_config(),
        mode="real",
    )

    assert prepared is not None
    assert prepared.planner_source == "deterministic"
    assert prepared.plan_stage == "base"
    assert prepared.draft_answer == ""


class _RecoveringFastAdapter:
    model = "test-fast"

    def __init__(self):
        self.calls = 0

    async def generate(self, messages, config):
        self.calls += 1
        return (
            "I'm looking for a company with real client impact, a pragmatic culture, "
            "and a team where I can stay close to the work."
        )


@pytest.mark.asyncio
async def test_planner_recovers_with_direct_draft_when_json_plan_fails():
    adapter = _RecoveringFastAdapter()
    planner = LiveQuestionPlanner(
        AskNormalizer(),
        adapter_factory=lambda alias: adapter,
    )
    turns = [
        {"text": "What are you looking for in terms of the company, culture, and teams?"},
    ]

    prepared = await planner.prepare(
        session_id="session-direct-draft-recovery",
        raw_turns=turns,
        interview_config=_interview_config(),
        mode="real",
    )

    assert prepared is not None
    assert prepared.plan_stage == "semantic"
    assert prepared.planner_source == "llm_fast"
    assert prepared.draft_answer.startswith("I'm looking for a company with real client impact")
    assert adapter.calls == 1


def test_planner_prefers_runtime_provider_when_fast_alias_is_local(monkeypatch):
    planner = LiveQuestionPlanner(AskNormalizer())

    monkeypatch.setattr(
        "pipeline.steps.live_question_planner._get_runtime_config",
        lambda: {
            "llm": {
                "provider": "anthropic",
                "model": "claude-sonnet-4-5-20250929",
                "api_key": "runtime-anthropic-key",
                "enabled": True,
            }
        },
    )

    class _RegistryStub:
        def get_llm_config(self, alias: str):
            assert alias == "fast"
            return SimpleNamespace(provider="ollama", model="llama3.2:1b")

    monkeypatch.setattr(
        "adapters.provider_registry.get_registry",
        lambda: _RegistryStub(),
    )

    adapter = planner._get_planner_adapter()

    assert adapter is not None
    assert adapter.__class__.__name__ == "AnthropicLLMAdapter"
    assert getattr(adapter, "api_key", "") == "runtime-anthropic-key"
    assert getattr(adapter, "model", "") == "claude-haiku-4-5-20251001"
