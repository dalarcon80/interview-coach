import asyncio
import contextlib
import time
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.server import LiveBrainWarmResult, LiveFrozenSnapshot, SessionSTTStreamManager
from adapters.llm_adapter import AnthropicLLMAdapter
from contracts.models import BrainPlan, BrainSnapshot, CompactEvidencePack, ResponseRequirement
from pipeline.steps.live_brain_service import LiveBrainService
from pipeline.steps.live_evidence_packer import LiveEvidencePacker
from pipeline.steps.live_finalizer import LiveFinalizer
from pipeline.steps.ask_normalizer import AskNormalizer
from pipeline.steps.live_question_planner import LiveQuestionPlanner
from conversation.tracker import ConversationTracker
from pipeline.steps.turn_assembler import SpeakerTurn


class _FakeWebSocket:
    def __init__(self):
        self.events: list[dict] = []

    async def send_json(self, payload: dict):
        self.events.append(payload)


def _build_live_pipeline_stub() -> MagicMock:
    pipeline = MagicMock()
    pipeline.process_question = AsyncMock()
    pipeline.conversation_tracker = ConversationTracker()
    pipeline.ask_normalizer = AskNormalizer()
    pipeline.live_question_planner = LiveQuestionPlanner(pipeline.ask_normalizer)
    pipeline.session_state = MagicMock(
        interview_config={
            "delivery_mode": "manual",
            "style_id": "professional",
            "language_preference": "en",
            "max_words": 180,
            "candidate": {
                "name": "Daniel",
                "currentRole": "Technology Director, Data & AI",
                "summary": "Technology executive with experience leading modernization and data programs.",
                "achievements": [
                    "Scaled a subscription delivery model to 17+ accounts.",
                    "Delivered up to 40% OPEX reduction across modernization programs.",
                ],
                "skills": ["Data", "AI", "Modernization"],
            },
            "company": {
                "companyName": "Cuesta Partners",
                "companySummary": "Consulting firm focused on pragmatic execution for mid-market companies.",
                "companyCulture": "Empathy, speed, execution focus.",
                "roleTitle": "Tech Lead | Latam",
                "recentFocus": ["Data-driven enterprises", "AI in M&A"],
            },
            "interviewer": {
                "name": "Marcus",
                "likelyFocusAreas": ["Operating style", "Client impact"],
            },
        }
    )
    return pipeline


@pytest.mark.asyncio
async def test_live_brain_service_deterministic_plan_from_snapshot():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-1",
        utterance_id="u-1",
        revision_id=2,
        snapshot_text=(
            "What are you looking for in a company?\n"
            "What do you want to avoid?"
        ),
        conversation_history=[
            {"speaker": "interviewer", "text": "What are you looking for in a company?"},
            {"speaker": "interviewer", "text": "What do you want to avoid?"},
        ],
        snapshot_hash="hash-1",
        timestamp=datetime.utcnow(),
    )

    plan = await service.plan(
        snapshot=snapshot,
        interview_config={"candidate": {}, "company": {}, "interviewer": {}},
    )

    assert plan.session_id == "s-1"
    assert len(plan.ordered_asks) >= 2
    assert plan.serve_mode == "finalize_from_plan"
    assert plan.stability_state == "draft"
    assert plan.question_completeness == "complete"
    assert plan.plan_source == "safe_fallback"
    assert "looking for" in plan.draft_answer.lower()
    assert "avoid" in plan.draft_answer.lower()
    assert "safe fallback" in plan.reasoning_summary.lower()


@pytest.mark.asyncio
async def test_live_brain_service_safe_fallback_builds_draft_for_complete_experience_question():
    service = LiveBrainService()
    interview_config = {
        "candidate": {
            "currentRole": "Technology Director, Data & AI",
            "summary": (
                "Technology executive with 20 years leading enterprise transformation across software modernization "
                "and the full data lifecycle. Global leadership scope managing 20 direct managers and 345 indirect reports."
            ),
            "achievements": [
                "Founded the Generative AI practice in Colombia and developed 7 reusable assets.",
                "Built and scaled a subscription operating model across 17+ accounts.",
            ],
            "cv_text": (
                "The teams spanned multiple disciplines including solution architects, data engineers, cloud engineers, "
                "delivery leads, and client-facing consultants."
            ),
        },
        "company": {
            "roleTitle": "Director - Data Architecture & Engineering",
        },
    }
    snapshot = BrainSnapshot(
        session_id="s-experience",
        utterance_id="u-experience",
        revision_id=1,
        snapshot_text=(
            "Tell me about your experience in building from 0, building from scratch. "
            "Also cover your team management experience, how big the teams were, what roles they had, "
            "and tell me a little bit about you."
        ),
        conversation_history=[
            {
                "speaker": "interviewer",
                "text": (
                    "Tell me about your experience in building from 0, building from scratch. "
                    "Also cover your team management experience, how big the teams were, what roles they had, "
                    "and tell me a little bit about you."
                ),
            }
        ],
        snapshot_hash="hash-experience",
        timestamp=datetime.utcnow(),
    )

    plan = await service.plan(
        snapshot=snapshot,
        interview_config=interview_config,
    )

    assert plan.plan_source == "safe_fallback"
    assert plan.question_completeness == "complete"
    assert plan.serve_mode == "finalize_from_plan"
    assert plan.response_family == "mixed_multi_part"
    assert "founded the generative ai practice" in plan.draft_answer.lower()
    assert "20 direct managers" in plan.draft_answer.lower()
    assert "solution architects" in plan.draft_answer.lower()
    assert any(segment.get("purpose") == "build_or_experience" for segment in plan.answer_blueprint)
    assert any(segment.get("purpose") == "leadership_scope" for segment in plan.answer_blueprint)
    assert any(segment.get("purpose") == "team_composition" for segment in plan.answer_blueprint)
    lowered_asks = [ask.lower() for ask in plan.ordered_asks]
    assert any("team management experience" in ask for ask in lowered_asks)
    assert any("how big the teams were" in ask or "how big were the teams" in ask for ask in lowered_asks)
    assert any("what roles they had" in ask or "what roles did they have" in ask for ask in lowered_asks)


@pytest.mark.asyncio
async def test_live_brain_service_reuses_previous_semantic_plan_for_same_complete_ask():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-reuse-complete",
        utterance_id="u-reuse-complete",
        revision_id=2,
        snapshot_text=(
            "What are you looking for in terms of the company, the culture, teams? "
            "What's important for you, or what kind of things you absolutely like?"
        ),
        conversation_history=[
            {
                "speaker": "interviewer",
                "text": (
                    "What are you looking for in terms of the company, the culture, teams? "
                    "What's important for you, or what kind of things you absolutely like?"
                ),
            }
        ],
        snapshot_hash="hash-reuse-complete",
        timestamp=datetime.utcnow(),
    )
    previous_plan = BrainPlan(
        session_id="s-reuse-complete",
        utterance_id="u-reuse-prev",
        revision_id=2,
        snapshot_hash="hash-prev",
        literal_question=(
            "What are you looking for in terms of the company, the culture, teams? "
            "What's important for you, or what kind of things you absolutely like?"
        ),
        contextualized_question=(
            "Answer by focusing on the preference areas most relevant to company, culture, and teams. "
            "Keep the answer on stated preferences and boundaries rather than background recap."
        ),
        ordered_asks=[
            "What are you looking for in terms of the company, the culture, teams?",
            "What's important for you, or what kind of things you absolutely like?",
        ],
        raw_detected_asks=[
            "What are you looking for in terms of the company, the culture, teams?",
            "What's important for you, or what kind of things you absolutely like?",
        ],
        resolved_question=(
            "Answer these interviewer asks in order:\n"
            "1. What are you looking for in terms of the company, the culture, teams?\n"
            "2. What's important for you, or what kind of things you absolutely like?"
        ),
        question_completeness="complete",
        question_type="behavioral",
        response_shape="direct_structured",
        answer_contract="preferences_and_anti_patterns",
        directness="balanced",
        tone="professional",
        response_family="culture_preferences",
        draft_answer=(
            "I'm looking for a company with a collaborative culture, clear expectations, and teams with strong ownership. "
            "What matters most to me is low-ego collaboration, fast decision-making, and room to build."
        ),
        confidence=0.91,
        stability_state="stable",
        plan_source="llm_fast",
    )

    plan = await service.plan(
        snapshot=snapshot,
        interview_config={"candidate": {}, "company": {}, "interviewer": {}},
        previous_plan=previous_plan,
    )

    assert plan.plan_source == "cached_stable"
    assert plan.ordered_asks == previous_plan.ordered_asks
    assert plan.question_completeness == "complete"
    assert plan.draft_answer == previous_plan.draft_answer
    assert "reused the previous semantic contract" in plan.reasoning_summary.lower()


@pytest.mark.asyncio
async def test_live_brain_service_ignores_previous_plan_after_revision_boundary():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-reset-window",
        utterance_id="u-reset-window",
        revision_id=2,
        snapshot_text="Tell me about your team management experience.",
        conversation_history=[
            {
                "speaker": "interviewer",
                "text": "Tell me about your team management experience.",
            }
        ],
        snapshot_hash="hash-reset-window",
        timestamp=datetime.utcnow(),
    )
    previous_plan = BrainPlan(
        session_id="s-reset-window",
        utterance_id="u-reset-prev",
        revision_id=1,
        snapshot_hash="hash-reset-prev",
        literal_question="What are you looking for in terms of the company, the culture, teams?",
        contextualized_question=(
            "Answer by focusing on the preference areas most relevant to company, culture, and teams. "
            "Keep the answer on stated preferences and boundaries rather than background recap."
        ),
        ordered_asks=[
            "What are you looking for in terms of the company, the culture, teams?",
        ],
        raw_detected_asks=[
            "What are you looking for in terms of the company, the culture, teams?",
        ],
        resolved_question="What are you looking for in terms of the company, the culture, teams?",
        question_completeness="complete",
        question_type="behavioral",
        response_shape="direct_structured",
        answer_contract="preferences_and_anti_patterns",
        directness="balanced",
        tone="professional",
        response_family="culture_preferences",
        draft_answer=(
            "I'm looking for a company with a collaborative culture, clear expectations, and teams with strong ownership."
        ),
        confidence=0.91,
        stability_state="stable",
        plan_source="llm_fast",
    )
    observed_previous_plans: list[BrainPlan | None] = []

    async def fake_plan_with_llm(*, snapshot, interview_config, previous_plan=None):
        observed_previous_plans.append(previous_plan)
        return (
            BrainPlan(
                session_id=snapshot.session_id,
                utterance_id=snapshot.utterance_id,
                revision_id=snapshot.revision_id,
                snapshot_hash=snapshot.snapshot_hash,
                literal_question=snapshot.snapshot_text,
                contextualized_question="Answer by focusing on team management experience and leadership scope.",
                ordered_asks=["Tell me about your team management experience."],
                raw_detected_asks=["Tell me about your team management experience."],
                resolved_question="Tell me about your team management experience.",
                question_completeness="complete",
                question_type="behavioral",
                response_shape="direct_short",
                answer_contract="general_direct",
                directness="direct",
                tone="professional",
                response_family="mixed_multi_part",
                draft_answer="I have led distributed teams across regions and disciplines.",
                confidence=0.73,
                stability_state="draft",
                plan_source="safe_fallback",
            ),
            "",
        )

    service._plan_with_llm = fake_plan_with_llm  # type: ignore[assignment]

    plan = await service.plan(
        snapshot=snapshot,
        interview_config={"candidate": {}, "company": {}, "interviewer": {}},
        previous_plan=previous_plan,
    )

    assert observed_previous_plans == [None]
    assert plan.plan_source == "llm_fast"
    assert plan.ordered_asks == ["Tell me about your team management experience."]
    assert "led distributed teams" in plan.draft_answer.lower()


@pytest.mark.asyncio
async def test_live_brain_service_does_not_reuse_previous_semantic_plan_when_new_ask_appears():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-reuse-novel",
        utterance_id="u-reuse-novel",
        revision_id=2,
        snapshot_text=(
            "What are you looking for in terms of the company, the culture, teams? "
            "Also tell me about your team management experience."
        ),
        conversation_history=[
            {
                "speaker": "interviewer",
                "text": (
                    "What are you looking for in terms of the company, the culture, teams? "
                    "Also tell me about your team management experience."
                ),
            }
        ],
        snapshot_hash="hash-reuse-novel",
        timestamp=datetime.utcnow(),
    )
    previous_plan = BrainPlan(
        session_id="s-reuse-novel",
        utterance_id="u-reuse-prev",
        revision_id=1,
        snapshot_hash="hash-prev-novel",
        literal_question=(
            "What are you looking for in terms of the company, the culture, teams? "
            "What's important for you, or what kind of things you absolutely like?"
        ),
        contextualized_question=(
            "Answer by focusing on the preference areas most relevant to company, culture, and teams. "
            "Keep the answer on stated preferences and boundaries rather than background recap."
        ),
        ordered_asks=[
            "What are you looking for in terms of the company, the culture, teams?",
            "What's important for you, or what kind of things you absolutely like?",
        ],
        raw_detected_asks=[
            "What are you looking for in terms of the company, the culture, teams?",
            "What's important for you, or what kind of things you absolutely like?",
        ],
        resolved_question=(
            "Answer these interviewer asks in order:\n"
            "1. What are you looking for in terms of the company, the culture, teams?\n"
            "2. What's important for you, or what kind of things you absolutely like?"
        ),
        question_completeness="complete",
        question_type="behavioral",
        response_shape="direct_structured",
        answer_contract="preferences_and_anti_patterns",
        directness="balanced",
        tone="professional",
        response_family="culture_preferences",
        draft_answer=(
            "I'm looking for a company with a collaborative culture, clear expectations, and teams with strong ownership."
        ),
        confidence=0.91,
        stability_state="stable",
        plan_source="llm_fast",
    )

    plan = await service.plan(
        snapshot=snapshot,
        interview_config={"candidate": {}, "company": {}, "interviewer": {}},
        previous_plan=previous_plan,
    )

    assert plan.plan_source == "safe_fallback"
    assert any("team management experience" in ask.lower() for ask in plan.ordered_asks)
    assert "reused the previous semantic contract" not in plan.reasoning_summary.lower()


@pytest.mark.asyncio
async def test_live_brain_service_safe_plan_merges_split_role_scope_clarification_prompt():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-role-scope",
        utterance_id="u-role-scope",
        revision_id=1,
        snapshot_text=(
            "Okay. So sounds like your position is more\n"
            "of a of a manager overseeing teams who do delivery."
        ),
        conversation_history=[
            {"speaker": "interviewer", "text": "Okay. So sounds like your position is more"},
            {"speaker": "interviewer", "text": "of a of a manager overseeing teams who do delivery."},
        ],
        snapshot_hash="hash-role-scope",
        timestamp=datetime.utcnow(),
    )

    plan = await service.plan(
        snapshot=snapshot,
        interview_config={
            "candidate": {
                "currentRole": "Technology Director, Data & AI",
                "summary": "Technology executive leading modernization and data programs.",
                "achievements": [
                    "Consolidated delivery across data lifecycle, application modernization, and platform transformation.",
                ],
            },
            "company": {"roleTitle": "Director - Data Architecture & Engineering"},
            "interviewer": {},
        },
    )

    assert plan.question_completeness == "complete"
    assert len(plan.ordered_asks) == 1
    assert "manager overseeing teams who do delivery" in plan.ordered_asks[0].lower()
    assert plan.ask_intents[0].ask_intent == "role_scope_clarification"


@pytest.mark.asyncio
async def test_live_brain_service_safe_plan_builds_local_referent_window_for_comparative_follow_up():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-local-follow-up",
        utterance_id="u-local-follow-up",
        revision_id=1,
        snapshot_text=(
            "Okay. But do do you have any that\n"
            "come up more frequently than others? Do you have a like, a specialization, or you you can do any of"
        ),
        conversation_history=[
            {"speaker": "interviewer", "text": "Okay. But do do you have any that"},
            {"speaker": "interviewer", "text": "come up more frequently than others? Do you have a like, a specialization, or you you can do any of"},
        ],
        snapshot_hash="hash-local-follow-up",
        timestamp=datetime.utcnow(),
    )

    plan = await service.plan(
        snapshot=snapshot,
        interview_config={"candidate": {}, "company": {}, "interviewer": {}},
    )

    assert plan.ordered_asks == ["do you have any that come up more frequently than others?"]
    assert plan.ask_intents[0].ask_intent in {"follow_up_clarification", "solution_specialization"}
    assert plan.ask_intents[0].prior_context_mode in {"disambiguate", "support_if_relevant"}
    assert plan.question_scope.referent_window == [
        "Do you have a like, a specialization, or you you can do any of"
    ]
    assert plan.context_focus == ["Do you have a like, a specialization, or you you can do any of"]


@pytest.mark.asyncio
async def test_live_brain_service_safe_plan_uses_local_referent_window_for_solution_specialization_follow_up():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-solution-specialization",
        utterance_id="u-solution-specialization",
        revision_id=1,
        snapshot_text=(
            "if you had to categorize the type of solutions that Globant customers come to you for, "
            "you know, what is it that you're delivering to them? Because when I look through your your CV, "
            "there's I drove executive adoption across strategic accounts, but adoption of of what exactly? "
            "Core banking modernization. So that sounds very business focused, maybe not so much data. "
            "Improved time to impact, but for for what? So I'm I'm trying to get an idea of the type of solutions that you specialize in."
        ),
        conversation_history=[
            {
                "speaker": "interviewer",
                "text": (
                    "if you had to categorize the type of solutions that Globant customers come to you for, "
                    "you know, what is it that you're delivering to them? Because when I look through your your CV, "
                    "there's I drove executive adoption across strategic accounts, but adoption of of what exactly? "
                    "Core banking modernization. So that sounds very business focused, maybe not so much data. "
                    "Improved time to impact, but for for what? So I'm I'm trying to get an idea of the type of solutions that you specialize in."
                ),
            }
        ],
        snapshot_hash="hash-solution-specialization",
        timestamp=datetime.utcnow(),
    )

    plan = await service.plan(
        snapshot=snapshot,
        interview_config={"candidate": {}, "company": {}, "interviewer": {}},
    )

    assert plan.ordered_asks == ["what is it that you're delivering to them?"]
    assert plan.ask_intents[0].ask_intent in {"follow_up_clarification", "solution_specialization"}
    assert plan.ask_intents[0].prior_context_mode in {"disambiguate", "support_if_relevant"}
    assert any(
        "core banking modernization" in item.lower()
        or "type of solutions that you specialize in" in item.lower()
        for item in plan.question_scope.referent_window
    )


@pytest.mark.asyncio
async def test_live_brain_service_safe_plan_uses_local_referent_window_for_stack_constraint_follow_up():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-stack-constraint",
        utterance_id="u-stack-constraint",
        revision_id=1,
        snapshot_text=(
            "Okay. Typically, when you when you look at a client's needs, Often, want to do things that they cannot do. "
            "With their current technology stack. Mhmm. Right? So how do you address that?"
        ),
        conversation_history=[
            {
                "speaker": "interviewer",
                "text": (
                    "Okay. Typically, when you when you look at a client's needs, Often, want to do things that they cannot do. "
                    "With their current technology stack. Mhmm. Right? So how do you address that?"
                ),
            }
        ],
        snapshot_hash="hash-stack-constraint",
        timestamp=datetime.utcnow(),
    )

    plan = await service.plan(
        snapshot=snapshot,
        interview_config={"candidate": {}, "company": {}, "interviewer": {}},
    )

    assert plan.ordered_asks == ["how do you address that?"]
    assert plan.ask_intents[0].ask_intent in {"follow_up_clarification", "constraint_handling"}
    assert plan.ask_intents[0].prior_context_mode == "disambiguate"
    assert plan.question_scope.referent_window == ["With their current technology stack."]


def test_live_brain_service_safe_plan_splits_also_cover_follow_ups_into_ordered_asks():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-also-cover-followups",
        utterance_id="u-also-cover-followups",
        revision_id=1,
        snapshot_text=(
            "Tell me about your experience in building from 0, building from scratch. "
            "Also cover your team management experience, how big the teams were, what roles they had, "
            "and tell me a little bit about you."
        ),
        conversation_history=[
            {
                "speaker": "interviewer",
                "text": (
                    "Tell me about your experience in building from 0, building from scratch. "
                    "Also cover your team management experience, how big the teams were, what roles they had, "
                    "and tell me a little bit about you."
                ),
            }
        ],
        snapshot_hash="hash-also-cover-followups",
        timestamp=datetime.utcnow(),
    )

    plan = service._plan_safely(snapshot=snapshot)

    lowered_asks = [ask.lower() for ask in plan.ordered_asks]
    assert any("tell me about your experience in building from 0" in ask for ask in lowered_asks)
    assert any("team management experience" in ask for ask in lowered_asks)
    assert any("how big the teams were" in ask or "how big were the teams" in ask for ask in lowered_asks)
    assert any("what roles they had" in ask or "what roles did they have" in ask for ask in lowered_asks)
    assert "little bit about you" in lowered_asks[-1]


@pytest.mark.asyncio
async def test_live_brain_service_safe_fallback_builds_draft_when_only_low_confidence_complete_preamble_is_dropped():
    service = LiveBrainService()
    interview_config = {
        "style_id": "detailed",
        "candidate": {
            "name": "Daniel Alarcón Ramírez",
            "currentRole": "Technology Director, Data & AI",
            "summary": (
                "Technology executive with 20 years leading enterprise transformation across software modernization "
                "and the full data lifecycle. Global leadership scope managing 20 direct managers and 345 indirect reports."
            ),
            "achievements": [
                "Founded the Generative AI practice in Colombia and developed 7 reusable assets.",
                "Built and scaled a subscription operating model across 17+ accounts.",
            ],
            "cv_text": (
                "The teams included solution architects, data engineers, cloud engineers, delivery leads, "
                "and client-facing consultants."
            ),
        },
        "company": {
            "roleTitle": "Director - Data Architecture & Engineering",
        },
    }
    snapshot = BrainSnapshot(
        session_id="s-experience-noisy-preamble",
        utterance_id="u-experience-noisy-preamble",
        revision_id=1,
        snapshot_text=(
            "And that won't go away. But I was\n"
            "hear specifically examples of\n"
            "companies or experiences that you've had where you had to build from 0. "
            "Whether it was building a product from 0, a team from 0, a a service from 0. "
            "Now I wanna get a sense of your experience in building from 0, building from scratch, early stages.\n"
            "And then also very curious to hear about your team management experience. "
            "How big were the teams you've managed?\n"
            "What roles did they have, etcetera. Yeah. And last question as as we go. "
            "So if you want just kinda start telling us or telling me a little bit about you."
        ),
        conversation_history=[
            {"speaker": "interviewer", "text": "And that won't go away. But I was"},
            {"speaker": "interviewer", "text": "hear specifically examples of"},
            {
                "speaker": "interviewer",
                "text": (
                    "companies or experiences that you've had where you had to build from 0. "
                    "Whether it was building a product from 0, a team from 0, a a service from 0. "
                    "Now I wanna get a sense of your experience in building from 0, building from scratch, early stages."
                ),
            },
            {
                "speaker": "interviewer",
                "text": "And then also very curious to hear about your team management experience. How big were the teams you've managed?",
            },
            {
                "speaker": "interviewer",
                "text": (
                    "What roles did they have, etcetera. Yeah. And last question as as we go. "
                    "So if you want just kinda start telling us or telling me a little bit about you."
                ),
            },
        ],
        snapshot_hash="hash-experience-noisy-preamble",
        timestamp=datetime.utcnow(),
    )

    plan = await service.plan(
        snapshot=snapshot,
        interview_config=interview_config,
    )

    assert plan.plan_source == "safe_fallback"
    assert plan.question_completeness == "complete"
    assert plan.serve_mode == "finalize_from_plan"
    assert plan.ask_intents[0].ask_intent == "build_from_zero_examples"
    assert "strongest probative value" in plan.ask_intents[0].response_goal.lower()
    assert "product, team, and service" in plan.ask_intents[0].response_goal.lower()
    assert "product, team, and service" in plan.interviewer_need.summary.lower()
    assert any("object built, stage, ownership, and outcome" in item.lower() for item in plan.response_requirement.required_moves)
    assert any("multiple examples clearly separated" in item.lower() for item in plan.response_requirement.required_moves)
    assert any("object built" in item.lower() for item in plan.response_requirement.must_cover)
    assert "founded the generative ai practice" in " ".join(plan.response_requirement.must_cover).lower()
    assert "built and scaled a subscription operating model" in " ".join(plan.response_requirement.must_cover).lower()
    first_two_paragraphs = " ".join(plan.response_requirement.paragraph_plan[:2]).lower()
    assert "answer tell me about your experience in building from 0" in first_two_paragraphs
    assert "answer tell me about your team management experience" in first_two_paragraphs or "answer how big were the teams" in first_two_paragraphs
    assert "object built" in plan.contextualized_question.lower()
    assert "foregrounding" not in plan.contextualized_question.lower()
    assert "founded the generative ai practice" not in plan.contextualized_question.lower()
    assert "built and scaled a subscription operating model" not in plan.contextualized_question.lower()
    assert "little bit about you" in " ".join(plan.ordered_asks).lower()
    assert "founded the generative ai practice" in plan.draft_answer.lower()
    assert "built and scaled a subscription operating model" in plan.draft_answer.lower()
    assert "expanded adoption from top 100" not in plan.draft_answer.lower()
    assert "20 direct managers" in plan.draft_answer.lower()
    assert "solution architects" in plan.draft_answer.lower()
    first_sentence = plan.draft_answer.lower().split(".", 1)[0]
    assert "built and scaled a subscription operating model" in first_sentence or "founded the generative ai practice" in first_sentence


@pytest.mark.asyncio
async def test_live_brain_service_safe_fallback_keeps_draft_when_snapshot_is_partial_but_has_clear_accepted_asks():
    service = LiveBrainService()
    interview_config = {
        "style_id": "professional",
        "candidate": {
            "currentRole": "Technology Director, Data & AI",
            "summary": "Technology executive leading modernization and data programs.",
            "achievements": [
                "Built and scaled a subscription operating model across 17+ accounts.",
            ],
            "cv_text": "The teams included solution architects, data engineers, cloud engineers, and delivery leads.",
        },
        "company": {
            "roleTitle": "Director - Data Architecture & Engineering",
        },
    }
    snapshot = BrainSnapshot(
        session_id="s-partial-draft",
        utterance_id="u-partial-draft",
        revision_id=1,
        snapshot_text=(
            "This Danielle, we will talk about like, your expectations in terms of the role. "
            "And or not the role, yeah, but basically what you had done in your experience.\n"
            "Tell me about your experience in building from 0, building from scratch.\n"
            "What roles did they have, etcetera and what kind of things you absolutely"
        ),
        conversation_history=[
            {
                "speaker": "interviewer",
                "text": "This Danielle, we will talk about like, your expectations in terms of the role.",
            },
            {
                "speaker": "interviewer",
                "text": "Tell me about your experience in building from 0, building from scratch.",
            },
            {
                "speaker": "interviewer",
                "text": "What roles did they have, etcetera and what kind of things you absolutely",
            },
        ],
        snapshot_hash="hash-partial-draft",
        timestamp=datetime.utcnow(),
    )

    plan = await service.plan(
        snapshot=snapshot,
        interview_config=interview_config,
    )

    assert plan.plan_source == "safe_fallback"
    assert plan.question_completeness == "partial"
    assert plan.serve_mode == "finalize_from_plan"
    assert "built and scaled a subscription operating model" in plan.draft_answer.lower()


@pytest.mark.parametrize(
    ("text", "expected_question_type", "expected_shape", "expected_contract", "expected_candidate_policy"),
    [
        (
            "What are you looking for in terms of company, culture, and teams? What do you avoid?",
            "direct",
            "direct_structured",
            "preferences_and_anti_patterns",
            "avoid",
        ),
        (
            "Tell me about a role where you led a data transformation, what you did, and what outcomes it drove.",
            "business",
            "strategic_explainer",
            "business_with_outcomes",
            "required",
        ),
        (
            "How would you design a scalable data platform across AWS with low latency and clear tradeoffs?",
            "technical",
            "technical_explainer",
            "architecture_walkthrough",
            "support_if_relevant",
        ),
    ],
)
def test_live_brain_service_builds_category_specific_contracts(
    text: str,
    expected_question_type: str,
    expected_shape: str,
    expected_contract: str,
    expected_candidate_policy: str,
):
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-category",
        utterance_id="u-category",
        revision_id=1,
        snapshot_text=text,
        conversation_history=[{"speaker": "interviewer", "text": text}],
        snapshot_hash="hash-category",
        timestamp=datetime.utcnow(),
    )

    plan = service._plan_safely(snapshot=snapshot)

    assert plan.question_type == expected_question_type
    assert plan.response_shape == expected_shape
    assert plan.answer_contract == expected_contract
    assert plan.candidate_context_policy == expected_candidate_policy

    if expected_contract == "business_with_outcomes":
        assert any("role, what you did, and the outcome" in item.lower() for item in plan.delivery_instructions)
    if expected_contract == "preferences_and_anti_patterns":
        assert any("do not add biography" in item.lower() for item in plan.delivery_instructions)
    if expected_contract == "architecture_walkthrough":
        assert any("trade-offs" in item.lower() for item in plan.delivery_instructions)
    if expected_shape == "direct_structured":
        assert any("blank line" in item.lower() for item in plan.delivery_instructions)


def test_live_brain_service_safe_plan_recognizes_request_style_interviewer_asks():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-request",
        utterance_id="u-request",
        revision_id=1,
        snapshot_text=(
            "Now I wanna get a sense of your experience in building from 0, building from scratch. "
            "And then, also very curious to hear about your team management experience. "
            "How big were the teams you've managed? What roles did they have, etcetera. "
            "So if you want, just kind of start telling us a little bit about you."
        ),
        conversation_history=[
            {
                "speaker": "interviewer",
                "text": (
                    "Now I wanna get a sense of your experience in building from 0, building from scratch. "
                    "And then, also very curious to hear about your team management experience. "
                    "How big were the teams you've managed? What roles did they have, etcetera. "
                    "So if you want, just kind of start telling us a little bit about you."
                ),
            }
        ],
        snapshot_hash="hash-request",
        timestamp=datetime.utcnow(),
    )

    plan = service._plan_safely(snapshot=snapshot)

    lowered_asks = [ask.lower() for ask in plan.ordered_asks]
    assert any("tell me about your experience in building from 0" in ask for ask in lowered_asks)
    assert any("team management experience" in ask for ask in lowered_asks)
    assert any("how big were the teams you've managed?" in ask for ask in lowered_asks)
    assert any("what roles did they have" in ask for ask in lowered_asks)
    assert all("start telling" not in ask for ask in lowered_asks)


def test_live_brain_service_separates_interviewer_briefing_from_final_intro_ask():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-interviewer-briefing",
        utterance_id="u-interviewer-briefing",
        revision_id=1,
        snapshot_text=(
            "And I only became chief architect in November. So I joined as a software developer role, supporting mostly authorization and scalability for one of our core products.\n"
            "Now I'm looking for an AI data architect. We've started down this AI journey and need to make the data available in a way that LLMs and AI can understand, across data lakes, graphs, knowledge bases, and vectors.\n"
            "And so what I'm really looking for is someone who has that background, knows the AWS infrastructure, and can lead our teams on how to build for those AI use cases. So that's the role. Can you any questions there? No. No. No. It's perfect. I have 20 years working with data and analytics. Alright. So tell me a bit about yourself, if you would."
        ),
        conversation_history=[
            {
                "speaker": "interviewer",
                "text": "And I only became chief architect in November. So I joined as a software developer role, supporting mostly authorization and scalability for one of our core products.",
            },
            {
                "speaker": "interviewer",
                "text": "Now I'm looking for an AI data architect. We've started down this AI journey and need to make the data available in a way that LLMs and AI can understand, across data lakes, graphs, knowledge bases, and vectors.",
            },
            {
                "speaker": "interviewer",
                "text": "And so what I'm really looking for is someone who has that background, knows the AWS infrastructure, and can lead our teams on how to build for those AI use cases. So that's the role. Can you any questions there? No. No. No. It's perfect. I have 20 years working with data and analytics. Alright. So tell me a bit about yourself, if you would.",
            },
        ],
        snapshot_hash="hash-interviewer-briefing",
        timestamp=datetime.utcnow(),
    )

    plan = service._plan_safely(
        snapshot=snapshot,
        interview_config={
            "candidate": {
                "currentRole": "Technology Director, Data & AI",
                "summary": "Technology executive with 20 years leading enterprise transformation across software modernization and the full data lifecycle.",
                "achievements": [
                    "Built and scaled a subscription operating model for modernization and data programs.",
                    "Founded the Generative AI practice in Colombia and developed 7 reusable assets.",
                ],
            },
            "company": {
                "roleTitle": "AI Data Architect",
            },
        },
    )

    lowered_asks = [ask.lower() for ask in plan.ordered_asks]
    assert lowered_asks == ["tell me a bit about yourself, if you would."]
    assert plan.resolved_question.lower() == "tell me a bit about yourself, if you would."
    assert plan.coverage_points == []
    assert plan.question_type == "mixed"
    assert plan.response_shape == "direct_structured"
    assert plan.target_length >= 170
    assert plan.response_family == "intro_alignment"
    assert any("aws infrastructure" in item.lower() for item in plan.supporting_interviewer_context)
    assert any("ai-ready data foundations" in item.lower() or "cloud and data platform" in item.lower() for item in plan.alignment_brief)
    assert "avoid_unframed_fit_close" in plan.quality_guardrails
    assert all("any questions there" not in ask for ask in lowered_asks)
    assert all("who has that background" not in ask for ask in lowered_asks)
    assert "most of that work has focused on," not in plan.draft_answer.lower()
    assert "strong fit" not in plan.draft_answer.lower()
    assert "built and scaled a subscription operating model" in plan.draft_answer.lower() or "founded the generative ai practice" in plan.draft_answer.lower()
    assert "guiding the teams building" in plan.draft_answer.lower() or "shaping ai-ready data platforms" in plan.draft_answer.lower()


def test_live_brain_service_normalizes_llm_plan_by_restoring_latest_safe_intro_ask():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-llm-safe-restore",
        utterance_id="u-llm-safe-restore",
        revision_id=1,
        snapshot_text=(
            "Now I'm looking for an AI data architect. We've started down this AI journey and need to make the data available in a way that LLMs and AI can understand.\n"
            "And so what I'm really looking for is someone who has that background, knows the AWS infrastructure, and can lead our teams on how to build for those AI use cases. So that's the role. Can you any questions there? No. No. No. It's perfect. Alright. So tell me a bit about yourself, if you would."
        ),
        conversation_history=[
            {
                "speaker": "interviewer",
                "text": "Now I'm looking for an AI data architect. We've started down this AI journey and need to make the data available in a way that LLMs and AI can understand.",
            },
            {
                "speaker": "interviewer",
                "text": "And so what I'm really looking for is someone who has that background, knows the AWS infrastructure, and can lead our teams on how to build for those AI use cases. So that's the role. Can you any questions there? No. No. No. It's perfect. Alright. So tell me a bit about yourself, if you would.",
            },
        ],
        snapshot_hash="hash-llm-safe-restore",
        timestamp=datetime.utcnow(),
    )

    plan = service._normalize_llm_plan(
        snapshot=snapshot,
        payload={
            "asks": [
                "who has that background, does know a the AWS infrastructure and can come in and lead",
                "Can you any questions there?",
            ],
            "resolved_question": (
                "Answer these interviewer asks in order: "
                "1. who has that background, does know a the AWS infrastructure and can come in and lead "
                "2. Can you any questions there?"
            ),
            "question_completeness": "complete",
            "question_type": "direct",
            "response_shape": "direct_short",
            "answer_contract": "general_direct",
            "draft_answer": "",
            "confidence": 0.72,
        },
    )

    lowered_asks = [ask.lower() for ask in plan.ordered_asks]
    assert lowered_asks == ["tell me a bit about yourself, if you would."]
    assert plan.literal_question.lower() == "tell me a bit about yourself, if you would."
    assert plan.contextualized_question.lower() != "tell me a bit about yourself, if you would."
    assert "architecture leadership" in plan.contextualized_question.lower() or "aws" in plan.contextualized_question.lower()
    assert plan.resolved_question.lower() == "tell me a bit about yourself, if you would."
    assert plan.serve_mode == "finalize_from_plan"
    assert any("aws infrastructure" in item.lower() for item in plan.supporting_interviewer_context)


def test_live_brain_service_does_not_promote_meta_handoff_when_latest_actionable_ask_is_missing():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-meta-truncated",
        utterance_id="u-meta-truncated",
        revision_id=1,
        snapshot_text=(
            "There's a need for us to build not just a regular data platform in terms of data lakes and modeling for sharing data and accessibility, "
            "but also into preparing that data into different types of storage and databases graphs, and knowledge bases, vectors. Based on the data type "
            "to try and power those use And so what I'm really looking for is someone who has that background\n"
            "does know a the AWS infrastructure and can come in and lead how you're going to go and well, lead our teams tell them how we need to build and design for these things. "
            "In order to power the the number of agents and the LLM usage use cases. That the company is trying to build. Okay. So that's the role.\n"
            "Can you any questions there? No. No. No. It's perfect. K. That is music to my heart, really, because that is my my expertise. I have\n"
            "That the company is trying to build. Okay. So that's the role. Can you any questions there? No. No. No. It's perfect. K. That is music to my heart, really, because that is my my expertise. I have"
        ),
        conversation_history=[
            {
                "speaker": "interviewer",
                "text": "There's a need for us to build not just a regular data platform in terms of data lakes and modeling for sharing data and accessibility, but also into preparing that data into different types of storage and databases graphs, and knowledge bases, vectors. Based on the data type to try and power those use And so what I'm really looking for is someone who has that background",
            },
            {
                "speaker": "interviewer",
                "text": "does know a the AWS infrastructure and can come in and lead how you're going to go and well, lead our teams tell them how we need to build and design for these things. In order to power the the number of agents and the LLM usage use cases. That the company is trying to build. Okay. So that's the role.",
            },
            {
                "speaker": "interviewer",
                "text": "Can you any questions there? No. No. No. It's perfect. K. That is music to my heart, really, because that is my my expertise. I have",
            },
            {
                "speaker": "interviewer",
                "text": "That the company is trying to build. Okay. So that's the role. Can you any questions there? No. No. No. It's perfect. K. That is music to my heart, really, because that is my my expertise. I have",
            },
        ],
        snapshot_hash="hash-meta-truncated",
        timestamp=datetime.utcnow(),
    )

    plan = service._plan_safely(
        snapshot=snapshot,
        interview_config={
            "candidate": {
                "currentRole": "Technology Director, Data & AI",
                "summary": "Technology executive with 20 years leading enterprise transformation across software modernization and the full data lifecycle.",
            },
            "company": {"roleTitle": "AI Data Architect"},
        },
    )

    assert plan.ordered_asks == []
    assert plan.resolved_question == ""
    assert plan.literal_question == ""
    assert plan.question_completeness == "garbled"
    assert plan.question_type == "direct"
    assert plan.response_shape == "direct_short"
    assert "not captured clearly enough" in plan.contextualized_question.lower()
    assert "meta prompt" in plan.contextualized_question.lower()
    assert plan.draft_answer == "I did not catch the full question clearly enough to give you a reliable answer."
    assert any("aws infrastructure" in item.lower() for item in plan.supporting_interviewer_context)


def test_live_brain_service_normalizes_llm_plan_by_clearing_meta_only_payload_when_snapshot_is_garbled():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-meta-only-payload",
        utterance_id="u-meta-only-payload",
        revision_id=1,
        snapshot_text=(
            "And so what I'm really looking for is someone who has that background, knows the AWS infrastructure, and can lead our teams on how to build for those AI use cases. "
            "So that's the role. Can you any questions there? No. No. No. It's perfect. K. That is music to my heart, really, because that is my my expertise. I have"
        ),
        conversation_history=[
            {
                "speaker": "interviewer",
                "text": "And so what I'm really looking for is someone who has that background, knows the AWS infrastructure, and can lead our teams on how to build for those AI use cases. So that's the role. Can you any questions there? No. No. No. It's perfect. K. That is music to my heart, really, because that is my my expertise. I have",
            }
        ],
        snapshot_hash="hash-meta-only-payload",
        timestamp=datetime.utcnow(),
    )

    plan = service._normalize_llm_plan(
        snapshot=snapshot,
        payload={
            "asks": ["Can you any questions there?"],
            "literal_question": "Can you any questions there?",
            "contextualized_question": "Answer by focusing on AI-ready data foundations for LLM and agent use cases.",
            "resolved_question": "Can you any questions there?",
            "question_completeness": "complete",
            "question_type": "technical",
            "response_shape": "technical_explainer",
            "answer_contract": "architecture_walkthrough",
            "draft_answer": "",
            "confidence": 0.72,
        },
    )

    assert plan.ordered_asks == []
    assert plan.resolved_question == ""
    assert plan.literal_question == ""
    assert plan.question_completeness == "garbled"
    assert plan.question_type == "direct"
    assert plan.response_shape == "direct_short"
    assert "not captured clearly enough" in plan.contextualized_question.lower()
    assert "any questions there" not in plan.contextualized_question.lower()
    assert plan.draft_answer == "I did not catch the full question clearly enough to give you a reliable answer."


def test_live_brain_service_normalizes_contract_fields_from_llm_payload():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-normalize",
        utterance_id="u-normalize",
        revision_id=1,
        snapshot_text="What are you looking for in a company and what do you avoid?",
        conversation_history=[
            {"speaker": "interviewer", "text": "What are you looking for in a company and what do you avoid?"}
        ],
        snapshot_hash="hash-normalize",
        timestamp=datetime.utcnow(),
    )

    plan = service._normalize_llm_plan(
        snapshot=snapshot,
        payload={
            "asks": [
                "What are you looking for in a company?",
                "What do you avoid?",
            ],
            "coverage_points": ["company", "avoid"],
            "question_type": "direct",
            "answer_shape": "direct_structured",
            "answer_contract": "preferences_and_anti_patterns",
            "delivery_instructions": [
                "Answer the asks in order.",
                "End with what to avoid.",
            ],
            "use_candidate_context": False,
            "use_company_context": True,
            "use_metrics": False,
            "draft_answer": "I look for strong execution and clear ownership, and I avoid political environments.",
            "confidence": 0.9,
            "serve_mode": "direct_brain",
            "is_complete": True,
        },
    )

    assert plan.response_shape == "direct_structured"
    assert plan.answer_contract == "preferences_and_anti_patterns"
    assert plan.delivery_instructions == [
        "Answer the asks in order.",
        "End with what to avoid.",
    ]
    assert plan.candidate_context_policy == "avoid"
    assert plan.serve_mode == "finalize_from_draft"


def test_live_brain_service_rejects_non_json_llm_payloads():
    parsed, failure_kind = LiveBrainService._parse_llm_payload(
        """
        asks:
        - Tell me about your experience in building from 0, building from scratch.
        - Tell me about your team management experience.
        - How big were the teams you've managed?
        question_completeness: complete
        question_type: business
        """
    )

    assert parsed is None
    assert failure_kind == "json_not_found"


@pytest.mark.asyncio
async def test_live_brain_service_falls_back_safely_when_llm_returns_non_json_payload():
    service = LiveBrainService()
    adapter = MagicMock()
    adapter.generate = AsyncMock(
        return_value="""
        asks:
        - Tell me about your experience in building from 0, building from scratch.
        - Tell me about your team management experience.
        - How big were the teams you've managed?
        - What roles did they have?
        question_completeness: complete
        question_type: business
        response_shape: strategic_explainer
        use_candidate_context: true
        use_company_context: false
        use_metrics: false
        confidence: 0.86
        """
    )
    service._resolve_adapter = MagicMock(return_value=adapter)
    snapshot = BrainSnapshot(
        session_id="s-recovered-llm",
        utterance_id="u-recovered-llm",
        revision_id=1,
        snapshot_text=(
            "Tell me about your experience in building from 0, building from scratch. "
            "Also cover your team management experience, how big the teams were, and what roles they had."
        ),
        conversation_history=[
            {
                "speaker": "interviewer",
                "text": (
                    "Tell me about your experience in building from 0, building from scratch. "
                    "Also cover your team management experience, how big the teams were, and what roles they had."
                ),
            }
        ],
        snapshot_hash="hash-recovered-llm",
        timestamp=datetime.utcnow(),
    )

    plan = await service.plan(
        snapshot=snapshot,
        interview_config=_build_live_pipeline_stub().session_state.interview_config,
    )

    assert plan.plan_source == "safe_fallback"
    assert plan.question_completeness == "complete"
    assert len(plan.ordered_asks) >= 1
    assert "building from 0" in plan.ordered_asks[0].lower()
    assert service.last_llm_failure_kind == "json_not_found"


def test_live_brain_plan_hash_stays_stable_when_only_question_wording_is_enriched():
    plan = BrainPlan(
        resolved_question="Tell me about yourself.",
        literal_question="Tell me about yourself.",
        contextualized_question=(
            "Introduce yourself by focusing on the experience most relevant to the role."
        ),
        ordered_asks=["Tell me about yourself."],
        coverage_points=["relevant background", "role fit"],
        ask_intents=[
            {
                "ask_text": "Tell me about yourself.",
                "ask_intent": "profile_alignment",
                "response_goal": "Show relevant background for the role.",
                "required_evidence_types": ["role_evidence"],
                "expected_answer_shape": "direct_structured",
                "needs_context_from_prior_turns": True,
            }
        ],
        interviewer_need={
            "summary": "Decide whether the candidate has relevant background for the role.",
            "dimensions": ["role relevance", "leadership credibility"],
            "evidence_expected": ["relevant experience", "scope"],
        },
        response_requirement={
            "answer_mode": "direct",
            "response_order": ["relevant background", "supporting example"],
            "required_moves": [
                "Anchor the intro in the work most relevant to the role.",
                "Make the evidence of fit explicit.",
            ],
            "context_to_weave": ["technical leadership", "client delivery"],
            "evidence_priority": ["role_evidence", "leadership_evidence"],
            "must_cover": [
                "Why the candidate's background is relevant to this role.",
                "A concrete example that makes that fit visible.",
            ],
            "avoid": ["generic biography"],
            "paragraph_plan": [
                "Start with the role and relevant scope.",
                "Add one concrete example that proves fit.",
            ],
            "style_constraints": ["Be direct and specific."],
        },
        context_focus=["technical leadership", "client delivery"],
        question_completeness="complete",
        question_type="mixed",
        response_shape="direct_structured",
        answer_contract="general_direct",
        directness="balanced",
        include_profile_opening=False,
        evidence_depth="medium",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="support_if_relevant",
        candidate_context_policy="support_if_relevant",
        ordered_coverage_required=True,
        target_length=180,
        draft_answer="",
        serve_mode="finalize_from_plan",
        confidence=0.8,
        plan_source="llm_fast",
    )
    enriched_wording = plan.model_copy(
        update={
            "literal_question": "So tell me a bit about yourself, if you would.",
            "contextualized_question": (
                "Introduce yourself professionally by emphasizing the parts of your background "
                "that prove you can lead this kind of work."
            ),
        }
    )

    assert LiveBrainService.plan_hash(plan) == LiveBrainService.plan_hash(enriched_wording)


def test_live_evidence_packer_compacts_context():
    packer = LiveEvidencePacker()
    plan = BrainPlan(
        resolved_question="What are you looking for in the company and what do you avoid?",
        ordered_asks=[
            "What are you looking for in the company?",
            "What do you avoid?",
        ],
        response_shape="direct_structured",
        directness="direct",
        include_profile_opening=False,
        evidence_depth="light",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="avoid",
        candidate_context_policy="avoid",
        ordered_coverage_required=True,
        target_length=140,
        draft_answer="",
        serve_mode="finalize_from_plan",
        confidence=0.7,
        question_completeness="complete",
        plan_source="llm_fast",
    )

    pack = packer.pack(
        plan=plan,
        interview_config=_build_live_pipeline_stub().session_state.interview_config,
    )

    assert isinstance(pack, CompactEvidencePack)
    assert pack.plan_hash
    assert "generic_profile_opening" in pack.excluded_topics
    assert "unsupported_metrics" in pack.excluded_topics
    assert "company_pitch" in pack.excluded_topics
    assert "career_biography" in pack.excluded_topics
    assert pack.mode == "full"
    assert len(pack.candidate_snippets) <= 2
    assert len(pack.company_snippets) <= 2


def test_compact_evidence_pack_includes_operating_style_and_client_posture_buckets():
    pack = CompactEvidencePack(
        plan_hash="plan-hash",
        operating_style_evidence=["Built a governed operating model with quality gates."],
        client_posture_evidence=["Opened executive relationships and aligned on roadmaps."],
    )

    assert pack.operating_style_evidence == ["Built a governed operating model with quality gates."]
    assert pack.client_posture_evidence == ["Opened executive relationships and aligned on roadmaps."]


def test_live_evidence_packer_skips_irrelevant_profile_snippets_when_only_support_if_relevant():
    packer = LiveEvidencePacker()
    plan = BrainPlan(
        resolved_question="What are you looking for in terms of company culture and teams?",
        ordered_asks=["What are you looking for in terms of company culture and teams?"],
        coverage_points=["company", "culture", "teams"],
        question_type="direct",
        response_shape="direct_structured",
        directness="direct",
        include_profile_opening=False,
        evidence_depth="light",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="support_if_relevant",
        candidate_context_policy="support_if_relevant",
        ordered_coverage_required=True,
        target_length=140,
        draft_answer="",
        serve_mode="finalize_from_plan",
        confidence=0.8,
        question_completeness="complete",
        plan_source="llm_fast",
    )

    pack = packer.pack(
        plan=plan,
        interview_config=_build_live_pipeline_stub().session_state.interview_config,
    )

    assert pack.candidate_snippets == []
    assert "career_biography" not in pack.excluded_topics


def test_live_brain_safe_strategy_avoids_candidate_context_for_direct_preference_question():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-preference",
        utterance_id="u-preference",
        revision_id=1,
        snapshot_text="What are you looking for in terms of the company, the culture, teams?",
        conversation_history=[
            {
                "speaker": "interviewer",
                "text": "What are you looking for in terms of the company, the culture, teams?",
            }
        ],
        snapshot_hash="hash-preference",
        timestamp=datetime.utcnow(),
    )

    plan = service._plan_safely(
        snapshot=snapshot,
        interview_config={"style_id": "concise"},
    )

    assert plan.question_type == "direct"
    assert plan.answer_contract == "preferences_and_anti_patterns"
    assert plan.response_family == "culture_preferences"
    assert plan.candidate_context_policy == "avoid"
    assert plan.serve_mode == "finalize_from_plan"
    assert "looking for" in plan.draft_answer.lower()
    assert "company" in plan.draft_answer.lower()
    assert "culture" in plan.draft_answer.lower()
    assert "team" in plan.draft_answer.lower()


@pytest.mark.asyncio
async def test_live_brain_service_safe_fallback_builds_draft_for_direct_preference_question_without_profile_context():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-direct-preference-safe",
        utterance_id="u-direct-preference-safe",
        revision_id=1,
        snapshot_text=(
            "Danielle, we will talk about like, your expectations in terms of the role. "
            "And or not the role, but, yeah, but basically what you have done in your experience. "
            "So now I just wanted to ask you, like, what are you looking for in terms of the company, the culture, teams? "
            "What's important for you, or what kind of things you absolutely don't like."
        ),
        conversation_history=[
            {
                "speaker": "interviewer",
                "text": "Danielle, we will talk about like, your expectations in terms of the role.",
            },
            {
                "speaker": "interviewer",
                "text": (
                    "And or not the role, but, yeah, but basically what you have done in your experience. "
                    "So now I just wanted to ask you, like, what are you looking for in terms of"
                ),
            },
            {
                "speaker": "interviewer",
                "text": (
                    "the company, the culture, teams? What's important for you, or what kind of things you absolutely don't like."
                ),
            },
        ],
        snapshot_hash="hash-direct-preference-safe",
        timestamp=datetime.utcnow(),
    )

    plan = await service.plan(
        snapshot=snapshot,
        interview_config={
            "style_id": "detailed",
            "company": {
                "values": [
                    "People-first approach",
                    "Local market autonomy",
                    "Collaboration and partnership",
                ],
                "companyCulture": (
                    "People-first culture focused on flexibility, autonomy, and local market empowerment "
                    "with emphasis on collaboration and community impact"
                ),
            },
        },
    )

    assert plan.plan_source == "safe_fallback"
    assert plan.question_completeness == "complete"
    assert plan.answer_contract == "preferences_and_anti_patterns"
    assert plan.response_family == "culture_preferences"
    assert plan.candidate_context_policy == "avoid"
    assert plan.serve_mode == "finalize_from_plan"
    assert "looking for" in plan.draft_answer.lower()
    assert "people-first approach" in plan.draft_answer.lower()
    assert "collaboration and partnership" in plan.draft_answer.lower()
    assert "low-trust" in plan.draft_answer.lower()
    assert "avoid" in plan.draft_answer.lower()
    assert "technology executive" not in plan.draft_answer.lower()
    assert "20 years" not in plan.draft_answer.lower()


def test_live_evidence_packer_does_not_send_interviewer_profile_into_live_answer_evidence():
    packer = LiveEvidencePacker()
    plan = BrainPlan(
        resolved_question="What are you looking for in terms of company culture and teams?",
        ordered_asks=["What are you looking for in terms of company culture and teams?"],
        coverage_points=["company", "culture", "teams"],
        question_type="direct",
        response_shape="direct_structured",
        answer_contract="preferences_and_anti_patterns",
        directness="balanced",
        include_profile_opening=False,
        evidence_depth="light",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="support_if_relevant",
        candidate_context_policy="avoid",
        ordered_coverage_required=True,
        target_length=140,
        response_requirement=ResponseRequirement(
            answer_mode="preferences",
            profile_evidence_mode="none",
            company_evidence_mode="preference_alignment",
            prior_context_mode="none",
        ),
        draft_answer="",
        serve_mode="finalize_from_plan",
        confidence=0.8,
        question_completeness="complete",
        plan_source="safe_fallback",
    )

    pack = packer.pack(
        plan=plan,
        interview_config=_build_live_pipeline_stub().session_state.interview_config,
    )

    assert pack.interviewer_snippets == []
    assert pack.candidate_snippets == []
    assert not any("20 direct managers" in item.lower() for item in pack.culture_alignment_evidence)


def test_live_evidence_packer_can_surface_operating_style_evidence_for_grounded_preferences():
    packer = LiveEvidencePacker()
    plan = BrainPlan(
        resolved_question="What are you looking for in terms of company culture and teams?",
        ordered_asks=["What are you looking for in terms of company culture and teams?"],
        coverage_points=["company", "culture", "teams"],
        question_type="direct",
        response_shape="direct_structured",
        answer_contract="preferences_and_anti_patterns",
        directness="balanced",
        include_profile_opening=False,
        evidence_depth="light",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="support_if_relevant",
        candidate_context_policy="avoid",
        ordered_coverage_required=True,
        target_length=180,
        response_requirement=ResponseRequirement(
            answer_mode="preferences",
            profile_evidence_mode="one_best_proof",
            company_evidence_mode="preference_alignment",
            prior_context_mode="none",
            evidence_priority=["operating_style_evidence", "culture_alignment_evidence"],
        ),
        draft_answer="",
        serve_mode="finalize_from_plan",
        confidence=0.8,
        question_completeness="complete",
        plan_source="safe_fallback",
        response_family="culture_preferences",
    )

    pack = packer.pack(
        plan=plan,
        interview_config=_build_live_pipeline_stub().session_state.interview_config,
    )

    assert pack.operating_style_evidence
    assert any(
        term in " ".join(pack.operating_style_evidence).lower()
        for term in ("governance", "quality", "predictable", "operating model", "delivery model", "standardized")
    )


def test_live_evidence_packer_builds_structured_evidence_slots_for_intro_alignment():
    packer = LiveEvidencePacker()
    plan = BrainPlan(
        resolved_question="tell me a bit about yourself, if you would.",
        ordered_asks=["tell me a bit about yourself, if you would."],
        response_family="intro_alignment",
        alignment_brief=["AI-ready data foundations for LLM and agent use cases"],
        question_type="behavioral",
        answer_contract="business_with_outcomes",
        candidate_context_policy="required",
        company_context_policy="support_if_relevant",
        plan_source="safe_fallback",
    )

    evidence = packer.pack(
        plan=plan,
        interview_config={
            "candidate": {
                "currentRole": "Technology Director, Data & AI",
                "summary": "Technology executive with 20 years leading data and modernization programs.",
                "achievements": [
                    "Designed and scaled a subscription-based delivery model for AI and modernization programs.",
                    "Led teams delivering AI-ready data platforms across strategic accounts.",
                ],
            },
            "company": {
                "roleTitle": "AI Data Architect",
                "roleResponsibilities": [
                    "Lead data platform architecture on AWS for AI and LLM use cases.",
                ],
            },
        },
    )

    assert evidence.role_evidence
    assert evidence.technical_alignment_evidence
    assert evidence.operating_style_evidence
    assert "unsupported_fit_closure" in evidence.excluded_topics


@pytest.mark.asyncio
async def test_live_finalizer_rebuilds_intro_alignment_when_draft_uses_unframed_strong_fit():
    finalizer = LiveFinalizer()
    plan = BrainPlan(
        resolved_question="tell me a bit about yourself, if you would.",
        ordered_asks=["tell me a bit about yourself, if you would."],
        response_family="intro_alignment",
        answer_blueprint=[
            {
                "purpose": "profile_core",
                "ask_refs": ["tell me a bit about yourself, if you would."],
                "required_elements": ["current role", "core domain expertise"],
                "preferred_evidence_types": ["role_evidence"],
                "avoid_topics": [],
                "target_sentence_count": 2,
            },
            {
                "purpose": "alignment",
                "ask_refs": ["tell me a bit about yourself, if you would."],
                "required_elements": ["alignment to interviewer context"],
                "preferred_evidence_types": ["technical_alignment_evidence"],
                "avoid_topics": ["strong_fit_claim_without_fit_ask"],
                "target_sentence_count": 1,
            },
        ],
        alignment_brief=["AI-ready data foundations for LLM and agent use cases"],
        quality_guardrails=["direct_first_sentence", "avoid_unframed_fit_close"],
        question_type="behavioral",
        response_shape="direct_short",
        answer_contract="business_with_outcomes",
        candidate_context_policy="required",
        company_context_policy="support_if_relevant",
        draft_answer=(
            "At a high level, I'm a technology executive with 20 years leading enterprise transformation. "
            "That is why roles centered on AI-ready data platforms are a strong fit for me."
        ),
        serve_mode="finalize_from_draft",
        question_completeness="complete",
        plan_source="safe_fallback",
        confidence=0.8,
    )
    evidence_pack = CompactEvidencePack(
        plan_hash="plan-hash-intro",
        role_evidence=["Technology Director, Data & AI"],
        technical_alignment_evidence=[
            "Led teams delivering AI-ready data platforms across strategic accounts.",
        ],
        candidate_snippets=[],
        company_snippets=[],
        interviewer_snippets=[],
        supporting_metrics=[],
        excluded_topics=["unsupported_fit_closure"],
        mode="full",
    )

    result = await finalizer.finalize(
        plan=plan,
        evidence_pack=evidence_pack,
        question_text=plan.resolved_question,
        conversation_history=[{"speaker": "interviewer", "text": plan.resolved_question}],
        interview_config=_build_live_pipeline_stub().session_state.interview_config,
    )

    assert "strong fit" not in result["full_response"].lower()
    assert "ai-ready data platforms" in result["full_response"].lower()


@pytest.mark.asyncio
async def test_live_finalizer_returns_explicit_failure_when_no_llm_or_brain_draft_is_available():
    finalizer = LiveFinalizer()
    plan = BrainPlan(
        resolved_question="What matters to you in a company?",
        ordered_asks=["What matters to you in a company?"],
        response_shape="direct_short",
        directness="direct",
        include_profile_opening=False,
        evidence_depth="light",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="support_if_relevant",
        candidate_context_policy="support_if_relevant",
        ordered_coverage_required=False,
        target_length=120,
        draft_answer="",
        serve_mode="finalize_from_plan",
        confidence=0.8,
        question_completeness="complete",
        plan_source="llm_fast",
    )
    evidence_pack = CompactEvidencePack(
        plan_hash="plan-hash",
        candidate_snippets=["I work best in pragmatic teams that stay close to execution."],
        company_snippets=["Empathy, speed, and execution focus."],
        interviewer_snippets=[],
        supporting_metrics=["Delivered 40% OPEX reduction in modernization programs."],
        excluded_topics=["unsupported_metrics"],
        mode="full",
    )

    result = await finalizer.finalize(
        plan=plan,
        evidence_pack=evidence_pack,
        question_text="What matters to you in a company?",
        conversation_history=[{"speaker": "interviewer", "text": "What matters to you in a company?"}],
        interview_config=_build_live_pipeline_stub().session_state.interview_config,
    )

    assert result["full_response"] == "I could not generate a reliable answer for this question in time."
    assert result["bullets"]
    assert result["metadata"]["finalizer_fallback_kind"] == "explicit_failure"


@pytest.mark.asyncio
async def test_live_finalizer_strict_emit_only_ignores_brain_draft_and_reports_timeout():
    finalizer = LiveFinalizer()
    async def _mock_finalize_with_llm(**_: Any) -> str:
        finalizer.last_llm_failure_kind = "timeout"
        return ""

    finalizer._finalize_with_llm = AsyncMock(side_effect=_mock_finalize_with_llm)
    plan = BrainPlan(
        resolved_question="Tell me about your experience in building from 0.",
        ordered_asks=["Tell me about your experience in building from 0."],
        response_shape="direct_short",
        directness="direct",
        include_profile_opening=False,
        evidence_depth="light",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="support_if_relevant",
        candidate_context_policy="required",
        ordered_coverage_required=False,
        target_length=120,
        draft_answer="A fallback draft that should never be surfaced in strict emit mode.",
        serve_mode="finalize_from_plan",
        confidence=0.8,
        question_completeness="complete",
        plan_source="safe_fallback",
    )
    evidence_pack = CompactEvidencePack(
        plan_hash="plan-hash-strict-emit-timeout",
        candidate_snippets=["Founded the Generative AI practice in Colombia."],
        company_snippets=[],
        interviewer_snippets=[],
        supporting_metrics=[],
        excluded_topics=[],
        mode="full",
    )

    result = await finalizer.finalize(
        plan=plan,
        evidence_pack=evidence_pack,
        question_text=plan.resolved_question,
        conversation_history=[{"speaker": "interviewer", "text": plan.resolved_question}],
        interview_config=_build_live_pipeline_stub().session_state.interview_config,
        strict_emit_only=True,
    )

    assert result["full_response"] == "I could not generate a reliable answer because the final answer stage timed out."
    assert result["metadata"]["finalizer_fallback_kind"] == "explicit_failure"


@pytest.mark.asyncio
async def test_live_finalizer_strict_emit_only_recovers_with_deterministic_answer_after_llm_failure():
    finalizer = LiveFinalizer()

    async def _mock_finalize_with_llm(**_: Any) -> str:
        finalizer.last_llm_failure_kind = "error"
        return ""

    finalizer._finalize_with_llm = AsyncMock(side_effect=_mock_finalize_with_llm)
    finalizer._finalize_deterministically = MagicMock(return_value="Deterministic recovery answer.")
    plan = BrainPlan(
        resolved_question="Tell me about your experience in building from 0.",
        ordered_asks=["Tell me about your experience in building from 0."],
        response_shape="direct_short",
        directness="direct",
        include_profile_opening=False,
        evidence_depth="light",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="support_if_relevant",
        candidate_context_policy="required",
        ordered_coverage_required=False,
        target_length=120,
        draft_answer="A draft that stays outside the active route.",
        serve_mode="finalize_from_plan",
        confidence=0.8,
        question_completeness="complete",
        plan_source="safe_fallback",
    )
    evidence_pack = CompactEvidencePack(
        plan_hash="plan-hash-strict-emit-deterministic-recovery",
        candidate_snippets=["Founded the Generative AI practice in Colombia."],
        company_snippets=[],
        interviewer_snippets=[],
        supporting_metrics=[],
        excluded_topics=[],
        mode="full",
    )

    result = await finalizer.finalize(
        plan=plan,
        evidence_pack=evidence_pack,
        question_text=plan.resolved_question,
        conversation_history=[{"speaker": "interviewer", "text": plan.resolved_question}],
        interview_config=_build_live_pipeline_stub().session_state.interview_config,
        strict_emit_only=True,
        allow_post_failure_recovery=True,
    )

    assert result["full_response"] == "Deterministic recovery answer."
    assert result["metadata"]["finalizer_fallback_kind"] == "deterministic"
    assert result["metadata"]["finalizer_primary_mode"] == "strict_emit_only"
    assert result["metadata"]["finalizer_primary_success"] is False
    assert result["metadata"]["finalizer_recovery_attempted"] is True
    assert result["metadata"]["finalizer_recovery_kind"] == "deterministic"
    assert result["metadata"]["finalizer_recovery_success"] is True


@pytest.mark.asyncio
async def test_live_finalizer_strict_emit_only_recovers_with_brain_draft_after_deterministic_failure():
    finalizer = LiveFinalizer()

    async def _mock_finalize_with_llm(**_: Any) -> str:
        finalizer.last_llm_failure_kind = "error"
        return ""

    finalizer._finalize_with_llm = AsyncMock(side_effect=_mock_finalize_with_llm)
    finalizer._finalize_deterministically = MagicMock(return_value="")
    plan = BrainPlan(
        resolved_question="Tell me about your experience in building from 0.",
        ordered_asks=["Tell me about your experience in building from 0."],
        response_shape="direct_short",
        directness="direct",
        include_profile_opening=False,
        evidence_depth="light",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="support_if_relevant",
        candidate_context_policy="required",
        ordered_coverage_required=False,
        target_length=120,
        draft_answer="A draft that should remain outside the active route.",
        serve_mode="finalize_from_plan",
        confidence=0.8,
        question_completeness="complete",
        plan_source="safe_fallback",
    )
    evidence_pack = CompactEvidencePack(
        plan_hash="plan-hash-strict-emit-draft-recovery",
        candidate_snippets=["Founded the Generative AI practice in Colombia."],
        company_snippets=[],
        interviewer_snippets=[],
        supporting_metrics=[],
        excluded_topics=[],
        mode="full",
    )

    result = await finalizer.finalize(
        plan=plan,
        evidence_pack=evidence_pack,
        question_text=plan.resolved_question,
        conversation_history=[{"speaker": "interviewer", "text": plan.resolved_question}],
        interview_config=_build_live_pipeline_stub().session_state.interview_config,
        strict_emit_only=True,
        recovery_draft="I've built capabilities from zero.\n\nI've led multi-region teams.",
        allow_post_failure_recovery=True,
    )

    assert result["full_response"].startswith("I've built capabilities from zero.")
    assert result["metadata"]["finalizer_fallback_kind"] == "brain_draft"
    assert result["metadata"]["recovery_draft_available"] is True
    assert result["metadata"]["finalizer_recovery_attempted"] is True
    assert result["metadata"]["finalizer_recovery_kind"] == "brain_draft"
    assert result["metadata"]["finalizer_recovery_success"] is True


@pytest.mark.asyncio
async def test_live_finalizer_strict_emit_only_skips_recovery_when_question_is_partial():
    finalizer = LiveFinalizer()

    async def _mock_finalize_with_llm(**_: Any) -> str:
        finalizer.last_llm_failure_kind = "error"
        return ""

    finalizer._finalize_with_llm = AsyncMock(side_effect=_mock_finalize_with_llm)
    finalizer._finalize_deterministically = MagicMock(return_value="Should not be used.")
    plan = BrainPlan(
        resolved_question="Tell me about your experience...",
        ordered_asks=["Tell me about your experience..."],
        response_shape="direct_short",
        directness="direct",
        include_profile_opening=False,
        evidence_depth="light",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="support_if_relevant",
        candidate_context_policy="required",
        ordered_coverage_required=False,
        target_length=120,
        draft_answer="A draft that stays outside the active route.",
        serve_mode="finalize_from_plan",
        confidence=0.8,
        question_completeness="partial",
        plan_source="safe_fallback",
    )
    evidence_pack = CompactEvidencePack(
        plan_hash="plan-hash-strict-emit-partial-skip",
        candidate_snippets=["Founded the Generative AI practice in Colombia."],
        company_snippets=[],
        interviewer_snippets=[],
        supporting_metrics=[],
        excluded_topics=[],
        mode="full",
    )

    result = await finalizer.finalize(
        plan=plan,
        evidence_pack=evidence_pack,
        question_text=plan.resolved_question,
        conversation_history=[{"speaker": "interviewer", "text": plan.resolved_question}],
        interview_config=_build_live_pipeline_stub().session_state.interview_config,
        strict_emit_only=True,
        recovery_draft="Recovery draft that should not be used.",
        allow_post_failure_recovery=True,
    )

    assert result["full_response"] == "I could not generate a reliable answer because the final answer stage failed."
    assert result["metadata"]["finalizer_fallback_kind"] == "explicit_failure"
    assert result["metadata"]["finalizer_recovery_attempted"] is False
    assert result["metadata"]["finalizer_recovery_skipped_reason"] == "question_incomplete"
    finalizer._finalize_deterministically.assert_not_called()


@pytest.mark.asyncio
async def test_live_finalizer_strict_emit_only_salvages_streamed_partial_on_timeout():
    finalizer = LiveFinalizer()

    async def _mock_finalize_with_llm(**_: Any):
        finalizer.last_llm_failure_kind = "timeout"
        return "", {
            "emit_stream_used": True,
            "emit_stream_first_chunk_ms": 45,
            "emit_stream_completed_ms": 120,
            "emit_stream_chunk_count": 2,
            "emit_stream_partial_salvaged": False,
            "emit_stream_partial_response": "I've built capabilities from zero and led multi-region teams.",
        }

    finalizer._finalize_with_llm = AsyncMock(side_effect=_mock_finalize_with_llm)
    plan = BrainPlan(
        resolved_question="Tell me about your experience in building from 0.",
        ordered_asks=["Tell me about your experience in building from 0."],
        response_shape="direct_short",
        directness="direct",
        include_profile_opening=False,
        evidence_depth="light",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="support_if_relevant",
        candidate_context_policy="required",
        ordered_coverage_required=False,
        target_length=120,
        draft_answer="A fallback draft that should never be surfaced in strict emit mode.",
        serve_mode="finalize_from_plan",
        confidence=0.8,
        question_completeness="complete",
        plan_source="safe_fallback",
    )
    evidence_pack = CompactEvidencePack(
        plan_hash="plan-hash-strict-emit-partial-timeout",
        candidate_snippets=["Founded the Generative AI practice in Colombia."],
        company_snippets=[],
        interviewer_snippets=[],
        supporting_metrics=[],
        excluded_topics=[],
        mode="full",
    )

    result = await finalizer.finalize(
        plan=plan,
        evidence_pack=evidence_pack,
        question_text=plan.resolved_question,
        conversation_history=[{"speaker": "interviewer", "text": plan.resolved_question}],
        interview_config=_build_live_pipeline_stub().session_state.interview_config,
        strict_emit_only=True,
    )

    assert result["full_response"] == "I've built capabilities from zero and led multi-region teams."
    assert result["metadata"]["finalizer_fallback_kind"] == "llm_partial"
    assert result["metadata"]["emit_stream_partial_salvaged"] is True


@pytest.mark.asyncio
async def test_live_finalizer_strict_emit_only_flushes_first_stream_chunk_immediately():
    finalizer = LiveFinalizer()

    class _StreamingAdapter:
        async def generate(self, messages, config):
            return "This should not be used."

        async def stream(self, messages, config):
            yield "I've "
            await asyncio.sleep(0)
            yield "built teams"
            await asyncio.sleep(0)
            yield "."

    finalizer._resolve_adapter = MagicMock(return_value=_StreamingAdapter())
    plan = BrainPlan(
        resolved_question="Tell me about your experience in building from 0.",
        ordered_asks=["Tell me about your experience in building from 0."],
        response_shape="direct_short",
        directness="direct",
        include_profile_opening=False,
        evidence_depth="light",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="avoid",
        candidate_context_policy="required",
        ordered_coverage_required=False,
        target_length=120,
        serve_mode="finalize_from_plan",
        confidence=0.8,
        question_completeness="complete",
        plan_source="safe_fallback",
    )
    evidence_pack = CompactEvidencePack(
        plan_hash="plan-hash-strict-emit-first-chunk",
        candidate_snippets=["Built and scaled a subscription operating model across 17+ accounts."],
        company_snippets=[],
        interviewer_snippets=[],
        supporting_metrics=[],
        excluded_topics=[],
        mode="full",
    )
    partials: list[str] = []

    async def _on_partial(payload):
        partials.append(str(payload.get("full_response") or ""))

    response, metadata = await finalizer._finalize_with_llm(
        plan=plan,
        evidence_pack=evidence_pack,
        question_text=plan.resolved_question,
        conversation_history=[{"speaker": "interviewer", "text": plan.resolved_question}],
        interview_config=_build_live_pipeline_stub().session_state.interview_config,
        working_draft="",
        strict_emit_only=True,
        timeout_override_sec=5,
        on_partial_response=_on_partial,
        partial_emit_interval_sec=10.0,
    )

    assert response == "I've built teams."
    assert partials == ["I've ", "I've built teams."]
    assert metadata["emit_stream_used"] is True
    assert metadata["emit_stream_chunk_count"] == 3
    assert metadata["emit_stream_first_chunk_ms"] is not None


@pytest.mark.asyncio
async def test_live_finalizer_strict_emit_prompt_uses_contract_and_structured_evidence_only():
    finalizer = LiveFinalizer()
    interview_config = _build_live_pipeline_stub().session_state.interview_config
    interview_config["candidate"] = {
        **interview_config["candidate"],
        "company": "Globant",
        "currentCompany": "Globant",
    }
    interview_config["target_context"] = {
        "company": {
            "name": "Slalom",
            "industry": "Consulting",
            "summary": "People-first consulting firm.",
            "culture": "Empathy and collaboration.",
            "values": ["People", "Execution"],
        },
        "role": {
            "title": "Director - Data Architecture & Engineering",
            "level": "director",
            "description": "Lead client-facing data architecture and engineering work.",
            "requirements": ["Consulting experience", "Cloud data platforms"],
            "responsibilities": ["Lead client delivery"],
            "interview_focus": ["Leadership", "Client impact"],
        },
        "interviewer": {
            "name": "Bernardo Najlis",
            "company": "Slalom",
            "roleTitle": "Consulting Leader",
            "backgroundSummary": "Strategic consulting leader.",
            "likelyFocusAreas": ["Operating style", "Client impact"],
        },
    }
    plan = BrainPlan(
        resolved_question="Tell me about your experience in building from 0.",
        ordered_asks=[
            "Tell me about your experience in building from 0.",
            "Tell me about your team management experience.",
        ],
        answer_blueprint=[
            {
                "purpose": "build_or_experience",
                "ask_refs": ["Tell me about your experience in building from 0."],
                "required_elements": ["concrete build example"],
                "preferred_evidence_types": ["build_evidence"],
                "avoid_topics": [],
                "target_sentence_count": 2,
            }
        ],
        quality_guardrails=["preserve_ask_order"],
        delivery_instructions=["Answer the asks in order."],
        question_type="behavioral",
        response_shape="direct_structured",
        answer_contract="business_with_outcomes",
        tone="professional",
        directness="balanced",
        target_length=180,
        ordered_coverage_required=True,
        draft_answer="This draft should not appear.",
    )
    evidence_pack = CompactEvidencePack(
        plan_hash="plan-hash-strict-prompt",
        candidate_snippets=["Technology executive with 20 years leading enterprise transformation."],
        company_snippets=["People-first culture."],
        interviewer_snippets=["Recruiting leader growing data teams."],
        role_evidence=["I'm currently serving as Technology Director, Data & AI at Globant."],
        build_evidence=["I founded the Generative AI practice in Colombia and developed seven reusable assets."],
        leadership_evidence=["I've managed 20 direct managers and 345 indirect reports across multiple regions."],
        team_scope_evidence=["solution architects, data engineers, consultants, delivery managers, and engineering leads"],
        supporting_metrics=["Delivered up to 40% OPEX reduction within 12 months."],
        excluded_topics=["company_pitch"],
        mode="full",
    )

    prompt = finalizer._build_prompt(
        plan=plan,
        evidence_pack=evidence_pack,
        question_text=plan.resolved_question,
        conversation_history=[
            {"speaker": "interviewer", "text": "Long raw history that should not be sent in strict mode."}
        ],
        interview_config=interview_config,
        working_draft="",
        include_plan_draft=False,
        strict_emit_only=True,
    )

    assert "RECENT CONVERSATION HISTORY" not in prompt
    assert "COMPACT EVIDENCE" not in prompt
    assert "WORKING DRAFT" not in prompt
    assert "Long raw history that should not be sent in strict mode." not in prompt
    assert "This draft should not appear." not in prompt
    assert "STRUCTURED EVIDENCE" in prompt
    assert "ORDERED ASKS" in prompt
    assert "SOURCE OF TRUTH CONTEXT" in prompt
    assert "CANDIDATE PROFILE FACTS" in prompt
    assert "Current company: Globant" in prompt
    assert "TARGET COMPANY CONTEXT (APPLICATION TARGET ONLY)" in prompt
    assert "Name: Slalom" in prompt
    assert "TARGET ROLE CONTEXT (APPLICATION TARGET ONLY)" in prompt
    assert "Title: Director - Data Architecture & Engineering" in prompt
    assert "INTERVIEWER CONTEXT" in prompt
    assert "Never state or imply that the candidate works at the target company" in prompt


def test_live_finalizer_optional_target_context_does_not_win_over_candidate_build_detail():
    finalizer = LiveFinalizer()
    plan = BrainPlan(
        resolved_question="Tell me about your experience in building from 0.",
        ordered_asks=["Tell me about your experience in building from 0."],
        question_type="behavioral",
        response_family="mixed_multi_part",
        response_shape="direct_structured",
        answer_contract="business_with_outcomes",
        candidate_context_policy="required",
        company_context_policy="support_if_relevant",
        question_completeness="complete",
    )
    evidence_pack = CompactEvidencePack(
        plan_hash="plan-hash-candidate-first",
        candidate_snippets=["Built and scaled AI Pods across 17+ accounts at Globant."],
        company_snippets=["Slalom is a consulting firm hiring a Director of Data Architecture & Engineering."],
        interviewer_snippets=[],
        supporting_metrics=[],
        excluded_topics=[],
        mode="full",
    )

    detail = finalizer._pick_best_detail(plan, evidence_pack)

    assert "Globant" in detail
    assert "Slalom" not in detail


@pytest.mark.asyncio
async def test_live_finalizer_explicit_failure_does_not_leak_profile_or_interviewer_for_direct_preference_question():
    finalizer = LiveFinalizer()
    plan = BrainPlan(
        resolved_question="What are you looking for in terms of company, culture, and teams?",
        ordered_asks=["What are you looking for in terms of company, culture, and teams?"],
        coverage_points=["company", "culture", "teams"],
        question_type="direct",
        response_shape="direct_structured",
        answer_contract="preferences_and_anti_patterns",
        tone="professional",
        directness="balanced",
        include_profile_opening=False,
        evidence_depth="light",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="support_if_relevant",
        candidate_context_policy="avoid",
        ordered_coverage_required=True,
        target_length=140,
        draft_answer="",
        serve_mode="finalize_from_plan",
        confidence=0.6,
        question_completeness="complete",
        plan_source="safe_fallback",
    )
    evidence_pack = CompactEvidencePack(
        plan_hash="plan-hash-no-leak",
        candidate_snippets=[
            "Technology executive with 20 years leading enterprise transformation across software modernization and the full data lifecycle.",
        ],
        company_snippets=[
            "Slalom is a global management consulting and technology services firm offering strategy, data, AI, cloud, systems implementation, and digital transformation services.",
        ],
        interviewer_snippets=[
            "Talent Acquisition leader with over 14 years of experience, specializing in growing Slalom's Data teams. Based in Toronto.",
        ],
        supporting_metrics=[],
        excluded_topics=[],
        mode="full",
    )

    result = await finalizer.finalize(
        plan=plan,
        evidence_pack=evidence_pack,
        question_text=plan.resolved_question,
        conversation_history=[{"speaker": "interviewer", "text": plan.resolved_question}],
        interview_config=_build_live_pipeline_stub().session_state.interview_config,
    )

    assert result["full_response"] == "I could not generate a reliable answer for this question in time."


def test_live_finalizer_resolve_adapter_uses_runtime_main_model(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with patch(
        "pipeline.steps.live_finalizer._get_runtime_config",
        return_value={
            "llm": {
                "provider": "anthropic",
                "model": "claude-sonnet-4-5-20250929",
                "api_key": "test-key",
                "enabled": True,
            }
        },
    ):
        adapter = LiveFinalizer()._resolve_adapter(alias="main")

    assert isinstance(adapter, AnthropicLLMAdapter)
    assert adapter.model == "claude-sonnet-4-5-20250929"
    assert adapter.api_key == "test-key"


def test_live_brain_service_resolve_adapter_uses_runtime_settings_model(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-anthropic-key")

    with patch(
        "pipeline.steps.live_brain_service._get_runtime_config",
        return_value={
            "llm": {
                "provider": "anthropic",
                "model": "claude-sonnet-4-6",
                "api_key": "runtime-anthropic-key",
                "enabled": True,
            }
        },
    ):
        adapter = LiveBrainService()._resolve_adapter(alias="fast")

    assert isinstance(adapter, AnthropicLLMAdapter)
    assert adapter.model == "claude-sonnet-4-6"
    assert adapter.api_key == "runtime-anthropic-key"


def test_live_question_planner_uses_runtime_settings_model(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-anthropic-key")

    planner = LiveQuestionPlanner()
    with patch(
        "pipeline.steps.live_question_planner._get_runtime_config",
        return_value={
            "llm": {
                "provider": "anthropic",
                "model": "claude-sonnet-4-6",
                "api_key": "runtime-anthropic-key",
                "enabled": True,
            }
        },
    ):
        adapter = planner._get_planner_adapter()

    assert isinstance(adapter, AnthropicLLMAdapter)
    assert adapter.model == "claude-sonnet-4-6"
    assert adapter.api_key == "runtime-anthropic-key"


def test_live_finalizer_resolve_adapter_uses_runtime_settings_model(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-anthropic-key")

    with patch(
        "pipeline.steps.live_finalizer._get_runtime_config",
        return_value={
            "llm": {
                "provider": "anthropic",
                "model": "claude-sonnet-4-6",
                "api_key": "runtime-anthropic-key",
                "enabled": True,
            }
        },
    ):
        adapter = LiveFinalizer()._resolve_adapter(alias="main")

    assert isinstance(adapter, AnthropicLLMAdapter)
    assert adapter.model == "claude-sonnet-4-6"
    assert adapter.api_key == "runtime-anthropic-key"


def test_live_llm_failure_notice_mentions_the_configured_api_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "api.server.load_runtime_config_payload",
        lambda: {
            "llm": {
                "provider": "anthropic",
                "model": "claude-sonnet-4-6",
                "api_key": "runtime-anthropic-key",
                "enabled": True,
            }
        },
    )

    notice = SessionSTTStreamManager._build_live_llm_failure_notice("authenticationerror")

    assert "Anthropic" in notice
    assert "configured API key" in notice
    assert "Open Settings" in notice


def test_live_llm_failure_notice_mentions_missing_api_key_in_settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "api.server.load_runtime_config_payload",
        lambda: {
            "llm": {
                "provider": "anthropic",
                "model": "claude-sonnet-4-6",
                "api_key": "",
                "enabled": True,
            }
        },
    )

    notice = SessionSTTStreamManager._build_live_llm_failure_notice("api_key_missing")

    assert "Anthropic" in notice
    assert "missing in Settings" in notice
    assert "Open Settings" in notice


@pytest.mark.asyncio
async def test_live_finalizer_emits_structured_brain_draft_as_is():
    finalizer = LiveFinalizer()
    plan = BrainPlan(
        resolved_question="What are you looking for in terms of company culture and teams?",
        ordered_asks=[
            "What are you looking for in terms of company culture and teams?",
            "What's important to you in an opportunity, or what do you absolutely value?",
        ],
        coverage_points=["company", "culture", "teams"],
        question_type="direct",
        response_shape="direct_structured",
        directness="direct",
        include_profile_opening=False,
        evidence_depth="light",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="support_if_relevant",
        candidate_context_policy="support_if_relevant",
        ordered_coverage_required=True,
        target_length=160,
        draft_answer=(
            "I'm looking for a culture that values strategic thinking and execution. "
            "After 20 years leading enterprise transformation, I thrive in environments where there's genuine collaboration between technical and business teams. "
            "I absolutely value autonomy to drive impact, continuous learning, and working with people who are intellectually curious. "
            "A team that moves fast but thinks strategically is essential for me."
        ),
        serve_mode="finalize_from_draft",
        confidence=0.86,
        question_completeness="complete",
        plan_source="llm_fast",
    )
    evidence_pack = CompactEvidencePack(
        plan_hash="plan-hash-structured",
        candidate_snippets=[],
        company_snippets=["Empathy, speed, and execution focus."],
        interviewer_snippets=[],
        supporting_metrics=[],
        excluded_topics=[],
        mode="full",
    )

    result = await finalizer.finalize(
        plan=plan,
        evidence_pack=evidence_pack,
        question_text=plan.resolved_question,
        conversation_history=[{"speaker": "interviewer", "text": plan.resolved_question}],
        interview_config=_build_live_pipeline_stub().session_state.interview_config,
        working_draft=plan.draft_answer,
    )

    assert result["full_response"] == plan.draft_answer
    assert result["metadata"]["finalizer_fallback_kind"] == "brain_draft"


@pytest.mark.asyncio
async def test_live_brain_service_safe_fallback_drops_noisy_preamble_and_incomplete_tail():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-2",
        utterance_id="u-2",
        revision_id=4,
        snapshot_text=(
            "This Danielle, we will talk about like, your expectations in terms of the role. "
            "And or not the role, yeah, but basically what you had done in your experience.\n"
            "What are you looking for in terms of the company, the culture, teams?\n"
            "What's important for you, or what kind of things you absolutely"
        ),
        conversation_history=[
            {"speaker": "interviewer", "text": "This Danielle, we will talk about like, your expectations in terms of the role."},
            {"speaker": "interviewer", "text": "What are you looking for in terms of the company, the culture, teams?"},
            {"speaker": "interviewer", "text": "What's important for you, or what kind of things you absolutely"},
        ],
        snapshot_hash="hash-2",
        timestamp=datetime.utcnow(),
    )

    plan = await service.plan(
        snapshot=snapshot,
        interview_config={"candidate": {}, "company": {}, "interviewer": {}},
    )

    assert plan.plan_source == "safe_fallback"
    assert plan.question_completeness == "partial"
    assert plan.ordered_asks == ["What are you looking for in terms of the company, the culture, teams?"]
    assert any("absolutely" in clause for clause in plan.dropped_noise_clauses)
    assert all("expectations in terms of the role" not in ask.lower() for ask in plan.ordered_asks)


@pytest.mark.asyncio
async def test_live_brain_service_safe_fallback_merges_split_question_and_ignores_tail():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-3",
        utterance_id="u-3",
        revision_id=5,
        snapshot_text=(
            "like, your expectations in terms of the role. And are And or not the role, but, yeah, but\n"
            "And or not the role, but, yeah, but basically what you have done in your experience. "
            "So now I just wanted to ask you, like, what are you looking for in terms of\n"
            "the company, the culture, teams? What's important for you, or what kind of things you absolutely"
        ),
        conversation_history=[
            {"speaker": "interviewer", "text": "Talk about like, your expectations in terms of the role."},
            {"speaker": "interviewer", "text": "And or not the role, but, yeah, but basically what you have done in your experience. So now I just wanted to ask you, like, what are you looking for in terms of"},
            {"speaker": "interviewer", "text": "the company, the culture, teams? What's important for you, or what kind of things you absolutely"},
        ],
        snapshot_hash="hash-3",
        timestamp=datetime.utcnow(),
    )

    plan = await service.plan(
        snapshot=snapshot,
        interview_config={"candidate": {}, "company": {}, "interviewer": {}},
    )

    assert plan.plan_source == "safe_fallback"
    assert plan.question_completeness == "partial"
    assert plan.resolved_question == "what are you looking for in terms of the company, the culture, teams?"
    assert plan.ordered_asks == ["what are you looking for in terms of the company, the culture, teams?"]
    assert plan.coverage_points == ["company", "culture", "teams"]
    assert all("absolutely" not in ask.lower() for ask in plan.ordered_asks)
    assert any("absolutely" in clause.lower() for clause in plan.raw_detected_asks + plan.dropped_noise_clauses)


@pytest.mark.asyncio
async def test_live_brain_service_extracts_generic_coverage_points_from_enumerated_focuses():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-4",
        utterance_id="u-4",
        revision_id=3,
        snapshot_text="What are you looking for in terms of scope, stakeholders, and operating model?",
        conversation_history=[
            {"speaker": "interviewer", "text": "What are you looking for in terms of scope, stakeholders, and operating model?"},
        ],
        snapshot_hash="hash-4",
        timestamp=datetime.utcnow(),
    )

    plan = await service.plan(
        snapshot=snapshot,
        interview_config={"candidate": {}, "company": {}, "interviewer": {}},
    )

    assert plan.coverage_points == ["scope", "stakeholders", "operating model"]
    assert plan.response_shape == "strategic_explainer"
    assert plan.evidence_depth == "medium"
    assert plan.ordered_coverage_required is True


def test_live_brain_service_safe_plan_preserves_positive_preference_follow_up_in_run_on_block():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-positive-preference",
        utterance_id="u-positive-preference",
        revision_id=3,
        snapshot_text=(
            "like, your expectations in terms of the role and or not the role, yeah, but basically what you have done "
            "in your experience So now I just wanted to ask you, like, what are you looking for in terms of the "
            "company, the culture, teams? What's important for you, or what kind of things you absolutely like."
        ),
        conversation_history=[
            {
                "speaker": "interviewer",
                "text": (
                    "like, your expectations in terms of the role and or not the role, yeah, but basically what you "
                    "have done in your experience So now I just wanted to ask you, like, what are you looking for "
                    "in terms of the company, the culture, teams? What's important for you, or what kind of things "
                    "you absolutely like."
                ),
            }
        ],
        snapshot_hash="hash-positive-preference",
        timestamp=datetime.utcnow(),
    )

    plan = service._plan_safely(snapshot=snapshot)

    assert plan.question_completeness == "complete"
    assert plan.question_type == "direct"
    assert plan.coverage_points == ["company", "culture", "teams"]
    assert plan.ordered_asks == [
        "what are you looking for in terms of the company, the culture, teams?",
        "What's important for you, or what kind of things you absolutely like.",
    ]


@pytest.mark.asyncio
async def test_live_brain_service_preserves_multiple_complete_asks_even_if_snapshot_has_noise():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-5",
        utterance_id="u-5",
        revision_id=4,
        snapshot_text=(
            "So now I just wanted to ask you, like, what are you looking for\n"
            "what are you looking for in terms of the company, the culture, teams? "
            "What's important for you, or what kind of things you absolutely don't like."
        ),
        conversation_history=[
            {"speaker": "interviewer", "text": "So now I just wanted to ask you, like, what are you looking for"},
            {"speaker": "interviewer", "text": "what are you looking for in terms of the company, the culture, teams? What's important for you, or what kind of things you absolutely don't like."},
        ],
        snapshot_hash="hash-5",
        timestamp=datetime.utcnow(),
    )

    plan = await service.plan(
        snapshot=snapshot,
        interview_config={"candidate": {}, "company": {}, "interviewer": {}},
    )

    assert plan.question_completeness == "partial"
    assert plan.ordered_asks == [
        "what are you looking for in terms of the company, the culture, teams?",
        "What's important for you, or what kind of things you absolutely don't like.",
    ]
    assert plan.coverage_points == ["company", "culture", "teams"]
    assert plan.response_shape == "direct_structured"


@pytest.mark.asyncio
async def test_live_brain_service_merges_split_follow_up_ask_across_lines():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-5b",
        utterance_id="u-5b",
        revision_id=5,
        snapshot_text=(
            "now I just wanted to ask you, like, what are you looking for in terms of\n"
            "the company, the culture, teams? What's important for you\n"
            "or what kind of things you absolutely don't like."
        ),
        conversation_history=[
            {"speaker": "interviewer", "text": "now I just wanted to ask you, like, what are you looking for in terms of"},
            {"speaker": "interviewer", "text": "the company, the culture, teams? What's important for you"},
            {"speaker": "interviewer", "text": "or what kind of things you absolutely don't like."},
        ],
        snapshot_hash="hash-5b",
        timestamp=datetime.utcnow(),
    )

    plan = await service.plan(
        snapshot=snapshot,
        interview_config={"candidate": {}, "company": {}, "interviewer": {}},
    )

    assert plan.ordered_asks == [
        "what are you looking for in terms of the company, the culture, teams?",
        "What's important for you or what kind of things you absolutely don't like.",
    ]
    assert plan.response_shape == "direct_structured"
    assert plan.evidence_depth == "medium"
    assert plan.candidate_context_policy == "avoid"


def test_live_brain_service_safe_plan_keeps_explicit_intro_follow_up_at_the_end_without_overriding_specific_asks():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-prune-intro",
        utterance_id="u-prune-intro",
        revision_id=2,
        snapshot_text=(
            "Now I wanna get a sense of your experience in building from 0, building from scratch. "
            "And then, also very curious to hear about your team management experience. "
            "How big were the teams you've managed? What roles did they have, etcetera. "
            "So if you want, just kind of start telling us a little bit about you."
        ),
        conversation_history=[
            {
                "speaker": "interviewer",
                "text": (
                    "Now I wanna get a sense of your experience in building from 0, building from scratch. "
                    "And then, also very curious to hear about your team management experience. "
                    "How big were the teams you've managed? What roles did they have, etcetera. "
                    "So if you want, just kind of start telling us a little bit about you."
                ),
            }
        ],
        snapshot_hash="hash-prune-intro",
        timestamp=datetime.utcnow(),
    )

    plan = service._plan_safely(snapshot=snapshot)

    lowered_asks = [ask.lower() for ask in plan.ordered_asks]
    assert any("tell me about your experience in building from 0" in ask for ask in lowered_asks)
    assert any("tell me about your team management experience" in ask for ask in lowered_asks)
    assert any("how big were the teams you've managed?" in ask for ask in lowered_asks)
    assert any("what roles did they have" in ask for ask in lowered_asks)
    assert "little bit about you" in lowered_asks[-1]


def test_live_brain_service_safe_plan_keeps_intro_follow_up_when_valid_ask_ends_with_dangling_and():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-intro-dangling-and",
        utterance_id="u-intro-dangling-and",
        revision_id=5,
        snapshot_text=(
            "There was building a product. "
            "From 0, a team from 0, a service from 0, now I wanna get a sense of your experience in building from 0, "
            "building from scratch. Early stages. "
            "And then also very curious to hear about your team experience. How big were the teams you've managed? "
            "What roles they have, etcetera. Yeah. And last question as as we go. So if you want, just "
            "kinda start telling us or telling me a little bit about you, and"
        ),
        conversation_history=[
            {"speaker": "interviewer", "text": "There was building a product"},
            {
                "speaker": "interviewer",
                "text": (
                    "From 0, a team from 0, a service from 0, now I wanna get a sense of your experience in building "
                    "from 0, building from scratch. Early stages."
                ),
            },
            {
                "speaker": "interviewer",
                "text": "And then also very curious to hear about your team experience. How big were the teams you've managed?",
            },
            {
                "speaker": "interviewer",
                "text": "What roles they have, etcetera. Yeah. And last question as as we go. So if you want, just",
            },
            {
                "speaker": "interviewer",
                "text": "kinda start telling us or telling me a little bit about you, and",
            },
        ],
        snapshot_hash="hash-intro-dangling-and",
        timestamp=datetime.utcnow(),
    )

    plan = service._plan_safely(snapshot=snapshot)

    lowered_asks = [ask.lower() for ask in plan.ordered_asks]
    assert any("tell me about your experience in building from 0" in ask for ask in lowered_asks)
    assert any("tell me about your team experience" in ask for ask in lowered_asks)
    assert any("how big were the teams you've managed?" in ask for ask in lowered_asks)
    assert any("what roles did they have" in ask for ask in lowered_asks)
    assert "little bit about you" in lowered_asks[-1]


@pytest.mark.asyncio
async def test_live_brain_service_keeps_follow_up_ask_without_terminal_punctuation_when_it_ends_in_dont_like():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-5c",
        utterance_id="u-5c",
        revision_id=5,
        snapshot_text=(
            "I just wanted to ask you, like, are you looking for in terms of the company, the culture, teams? "
            "What's important for you, or what kind of things you absolutely don't like"
        ),
        conversation_history=[
            {
                "speaker": "interviewer",
                "text": (
                    "I just wanted to ask you, like, are you looking for in terms of the company, the culture, teams? "
                    "What's important for you, or what kind of things you absolutely don't like"
                ),
            }
        ],
        snapshot_hash="hash-5c",
        timestamp=datetime.utcnow(),
    )

    plan = await service.plan(
        snapshot=snapshot,
        interview_config={"candidate": {}, "company": {}, "interviewer": {}},
    )

    assert plan.ordered_asks == [
        "are you looking for in terms of the company, the culture, teams?",
        "What's important for you, or what kind of things you absolutely don't like",
    ]
    assert plan.question_completeness == "complete"
    assert plan.response_shape == "direct_structured"


@pytest.mark.asyncio
async def test_live_finalizer_sanitizes_full_response_wrapper():
    finalizer = LiveFinalizer()
    plan = BrainPlan(
        resolved_question="What are you looking for in a company?",
        ordered_asks=["What are you looking for in a company?"],
        question_completeness="complete",
        response_shape="direct_short",
        directness="direct",
        include_profile_opening=False,
        evidence_depth="light",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="support_if_relevant",
        candidate_context_policy="avoid",
        ordered_coverage_required=False,
        target_length=110,
        draft_answer="FULL RESPONSE: I’m looking for a team with strong execution and low bureaucracy.",
        serve_mode="finalize_from_draft",
        confidence=0.9,
        plan_source="llm_fast",
    )
    evidence_pack = CompactEvidencePack(
        plan_hash="plan-hash-2",
        company_snippets=["Empathy, speed, and execution focus."],
        mode="full",
    )

    result = await finalizer.finalize(
        plan=plan,
        evidence_pack=evidence_pack,
        question_text="What are you looking for in a company?",
        conversation_history=[{"speaker": "interviewer", "text": "What are you looking for in a company?"}],
        interview_config=_build_live_pipeline_stub().session_state.interview_config,
    )

    assert result["full_response"].startswith("I’m looking for a team")
    assert "FULL RESPONSE" not in result["full_response"]
    assert result["metadata"]["output_sanitizer_applied"] is True


@pytest.mark.asyncio
async def test_live_finalizer_sanitizer_preserves_paragraph_breaks():
    finalizer = LiveFinalizer()
    plan = BrainPlan(
        resolved_question="What are you looking for in terms of company, culture, and teams?",
        ordered_asks=[
            "What are you looking for in terms of company, culture, and teams?",
            "What's important to you?",
        ],
        question_completeness="complete",
        response_shape="direct_structured",
        directness="balanced",
        include_profile_opening=False,
        evidence_depth="light",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="support_if_relevant",
        candidate_context_policy="avoid",
        ordered_coverage_required=True,
        target_length=140,
        draft_answer=(
            "FULL RESPONSE: I'm looking for a company with strong execution.\n\n"
            "Culture-wise, I value low bureaucracy and real collaboration.\n\n"
            "In terms of teams, I look for curiosity and technical depth."
        ),
        serve_mode="finalize_from_draft",
        confidence=0.9,
        plan_source="llm_fast",
    )
    evidence_pack = CompactEvidencePack(
        plan_hash="plan-hash-paragraphs",
        company_snippets=[],
        mode="full",
    )

    result = await finalizer.finalize(
        plan=plan,
        evidence_pack=evidence_pack,
        question_text=plan.resolved_question,
        conversation_history=[{"speaker": "interviewer", "text": plan.resolved_question}],
        interview_config=_build_live_pipeline_stub().session_state.interview_config,
    )

    assert "FULL RESPONSE" not in result["full_response"]
    assert "\n\nCulture-wise," in result["full_response"]
    assert "\n\nIn terms of teams," in result["full_response"]


@pytest.mark.asyncio
async def test_live_finalizer_returns_partial_failure_notice_without_deterministic_answer():
    finalizer = LiveFinalizer()
    plan = BrainPlan(
        resolved_question="what are you looking for in terms of the company, the culture, teams?",
        ordered_asks=["what are you looking for in terms of the company, the culture, teams?"],
        question_completeness="partial",
        response_shape="direct_short",
        directness="direct",
        include_profile_opening=False,
        evidence_depth="light",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="support_if_relevant",
        candidate_context_policy="support_if_relevant",
        ordered_coverage_required=False,
        target_length=110,
        draft_answer="",
        serve_mode="finalize_from_plan",
        confidence=0.35,
        plan_source="safe_fallback",
    )
    evidence_pack = CompactEvidencePack(
        plan_hash="plan-hash-safe",
        candidate_snippets=["I work best in pragmatic teams with low bureaucracy and clear execution ownership."],
        company_snippets=["Empathy, speed, and execution focus."],
        interviewer_snippets=[],
        supporting_metrics=[],
        excluded_topics=["unsupported_metrics"],
        mode="minimal",
    )

    result = await finalizer.finalize(
        plan=plan,
        evidence_pack=evidence_pack,
        question_text=plan.resolved_question,
        conversation_history=[{"speaker": "interviewer", "text": plan.resolved_question}],
        interview_config=_build_live_pipeline_stub().session_state.interview_config,
    )

    assert result["full_response"] == "I did not catch the full question clearly enough to give you a reliable answer."


@pytest.mark.asyncio
async def test_live_finalizer_does_not_generate_structured_answer_from_plan_when_brain_has_no_draft():
    finalizer = LiveFinalizer()
    plan = BrainPlan(
        resolved_question="Answer these interviewer asks in order:\n1. What are you looking for in terms of scope, stakeholders, and operating model?\n2. What's important for you, or what kind of things you absolutely don't like.",
        ordered_asks=[
            "What are you looking for in terms of scope, stakeholders, and operating model?",
            "What's important for you, or what kind of things you absolutely don't like.",
        ],
        coverage_points=["scope", "stakeholders", "operating model"],
        question_completeness="partial",
        response_shape="direct_structured",
        directness="direct",
        include_profile_opening=False,
        evidence_depth="light",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="support_if_relevant",
        candidate_context_policy="support_if_relevant",
        ordered_coverage_required=True,
        target_length=140,
        draft_answer="",
        serve_mode="finalize_from_plan",
        confidence=0.5,
        plan_source="safe_fallback",
    )
    evidence_pack = CompactEvidencePack(
        plan_hash="plan-hash-generic-axes",
        candidate_snippets=["I work best when the scope is clear, stakeholders are aligned, and the operating model supports execution."],
        company_snippets=["Pragmatic execution with clear ownership."],
        interviewer_snippets=[],
        supporting_metrics=[],
        excluded_topics=["unsupported_metrics"],
        mode="minimal",
    )

    result = await finalizer.finalize(
        plan=plan,
        evidence_pack=evidence_pack,
        question_text=plan.resolved_question,
        conversation_history=[{"speaker": "interviewer", "text": plan.resolved_question}],
        interview_config=_build_live_pipeline_stub().session_state.interview_config,
    )

    assert result["full_response"] == "I did not catch the full question clearly enough to give you a reliable answer."


@pytest.mark.asyncio
async def test_live_finalizer_prefers_main_llm_when_available_for_structured_focuses():
    finalizer = LiveFinalizer()
    finalizer._finalize_with_llm = AsyncMock(
        return_value=(
            "I’m looking for a company with strong execution, collaborative teams, and clear expectations."
        )
    )
    plan = BrainPlan(
        resolved_question="Answer these interviewer asks in order:\n1. What are you looking for in terms of scope, stakeholders, and operating model?\n2. What do you avoid?",
        ordered_asks=[
            "What are you looking for in terms of scope, stakeholders, and operating model?",
            "What do you avoid?",
        ],
        coverage_points=["scope", "stakeholders", "operating model"],
        question_completeness="complete",
        response_shape="direct_structured",
        directness="direct",
        include_profile_opening=False,
        evidence_depth="light",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="support_if_relevant",
        candidate_context_policy="support_if_relevant",
        ordered_coverage_required=True,
        target_length=150,
        draft_answer="",
        serve_mode="finalize_from_plan",
        confidence=0.6,
        plan_source="safe_fallback",
    )
    evidence_pack = CompactEvidencePack(
        plan_hash="plan-hash-quality-floor",
        candidate_snippets=["I work best when the scope is clear, stakeholders are aligned, and the operating model supports execution."],
        company_snippets=["Pragmatic execution with clear ownership."],
        interviewer_snippets=[],
        supporting_metrics=[],
        excluded_topics=["unsupported_metrics"],
        mode="minimal",
    )

    result = await finalizer.finalize(
        plan=plan,
        evidence_pack=evidence_pack,
        question_text=plan.resolved_question,
        conversation_history=[{"speaker": "interviewer", "text": plan.resolved_question}],
        interview_config=_build_live_pipeline_stub().session_state.interview_config,
    )

    assert result["full_response"] == "I’m looking for a company with strong execution, collaborative teams, and clear expectations."
    assert result["metadata"]["finalizer_fallback_kind"] == "llm"
    assert result["metadata"]["llm_called"] is True


@pytest.mark.asyncio
async def test_live_finalizer_formats_multi_part_llm_response_with_visible_spacing():
    finalizer = LiveFinalizer()
    finalizer._finalize_with_llm = AsyncMock(
        return_value=(
            "I'm looking for a company that values innovation and autonomy. "
            "Culture-wise, I thrive in environments with real collaboration and low bureaucracy. "
            "In terms of teams, I value curiosity, strong technical depth, and constructive challenge."
        )
    )
    plan = BrainPlan(
        resolved_question=(
            "Answer these interviewer asks in order:\n"
            "1. What are you looking for in terms of company, culture, and teams?\n"
            "2. What's important to you?"
        ),
        ordered_asks=[
            "What are you looking for in terms of company, culture, and teams?",
            "What's important to you?",
        ],
        coverage_points=["company", "culture", "teams"],
        question_completeness="complete",
        response_shape="direct_structured",
        directness="balanced",
        include_profile_opening=False,
        evidence_depth="light",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="support_if_relevant",
        candidate_context_policy="avoid",
        ordered_coverage_required=True,
        target_length=150,
        draft_answer="",
        serve_mode="finalize_from_plan",
        confidence=0.6,
        plan_source="safe_fallback",
    )
    evidence_pack = CompactEvidencePack(
        plan_hash="plan-hash-visible-spacing",
        candidate_snippets=[],
        company_snippets=[],
        interviewer_snippets=[],
        supporting_metrics=[],
        excluded_topics=[],
        mode="minimal",
    )

    result = await finalizer.finalize(
        plan=plan,
        evidence_pack=evidence_pack,
        question_text=plan.resolved_question,
        conversation_history=[{"speaker": "interviewer", "text": plan.resolved_question}],
        interview_config=_build_live_pipeline_stub().session_state.interview_config,
    )

    assert "\n\nCulture-wise," in result["full_response"]
    assert "\n\nIn terms of teams," in result["full_response"]


@pytest.mark.asyncio
async def test_live_finalizer_splits_multi_part_single_block_into_paragraphs_without_explicit_breaks():
    finalizer = LiveFinalizer()
    finalizer._finalize_with_llm = AsyncMock(
        return_value=(
            "I've built several things from zero throughout my career. "
            "Most recently I founded a generative AI practice and built reusable assets. "
            "I've led teams at multiple scales, from focused squads to large multi-region organizations. "
            "Those teams included architects, engineers, product leaders, and client-facing delivery roles."
        )
    )
    plan = BrainPlan(
        resolved_question=(
            "Answer these interviewer asks in order:\n"
            "1. Tell me about your experience in building from zero.\n"
            "2. Tell me about your team management experience.\n"
            "3. What roles did those teams have?"
        ),
        ordered_asks=[
            "Tell me about your experience in building from zero.",
            "Tell me about your team management experience.",
            "What roles did those teams have?",
        ],
        question_completeness="complete",
        response_shape="direct_structured",
        directness="balanced",
        include_profile_opening=False,
        evidence_depth="medium",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="avoid",
        candidate_context_policy="required",
        ordered_coverage_required=True,
        target_length=180,
        draft_answer="",
        serve_mode="finalize_from_plan",
        confidence=0.6,
        plan_source="safe_fallback",
    )
    evidence_pack = CompactEvidencePack(
        plan_hash="plan-hash-split-single-block",
        candidate_snippets=[],
        company_snippets=[],
        interviewer_snippets=[],
        supporting_metrics=[],
        excluded_topics=[],
        mode="minimal",
    )

    result = await finalizer.finalize(
        plan=plan,
        evidence_pack=evidence_pack,
        question_text=plan.resolved_question,
        conversation_history=[{"speaker": "interviewer", "text": plan.resolved_question}],
        interview_config=_build_live_pipeline_stub().session_state.interview_config,
    )

    assert result["full_response"].count("\n\n") >= 1


@pytest.mark.asyncio
async def test_live_finalizer_uses_default_token_budget_for_direct_structured_answers():
    finalizer = LiveFinalizer()
    adapter = MagicMock()
    adapter.generate = AsyncMock(return_value="I’m looking for strong execution, low bureaucracy, and collaborative teams.")
    finalizer._resolve_adapter = MagicMock(return_value=adapter)
    plan = BrainPlan(
        resolved_question="What are you looking for in terms of company, culture, and teams?",
        ordered_asks=["What are you looking for in terms of company, culture, and teams?"],
        question_completeness="complete",
        response_shape="direct_structured",
        directness="balanced",
        include_profile_opening=False,
        evidence_depth="light",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="support_if_relevant",
        candidate_context_policy="avoid",
        ordered_coverage_required=True,
        target_length=140,
        draft_answer="",
        serve_mode="finalize_from_plan",
        confidence=0.7,
        plan_source="safe_fallback",
    )
    evidence_pack = CompactEvidencePack(
        plan_hash="plan-hash-token-budget",
        candidate_snippets=[],
        company_snippets=[],
        interviewer_snippets=[],
        supporting_metrics=[],
        excluded_topics=[],
        mode="minimal",
    )

    await finalizer.finalize(
        plan=plan,
        evidence_pack=evidence_pack,
        question_text=plan.resolved_question,
        conversation_history=[{"speaker": "interviewer", "text": plan.resolved_question}],
        interview_config=_build_live_pipeline_stub().session_state.interview_config,
    )

    _, config = adapter.generate.await_args.args
    assert config["max_tokens"] == finalizer._resolve_emit_max_tokens(plan=plan)


@pytest.mark.asyncio
async def test_live_finalizer_does_not_expand_follow_up_preference_asks_without_brain_or_llm_output():
    finalizer = LiveFinalizer()
    plan = BrainPlan(
        resolved_question=(
            "Answer these interviewer asks in order:\n"
            "1. what are you looking for in terms of the company, the culture, teams?\n"
            "2. What's important for you?\n"
            "3. what kind of things you absolutely don't mind?"
        ),
        ordered_asks=[
            "what are you looking for in terms of the company, the culture, teams?",
            "What's important for you?",
            "what kind of things you absolutely don't mind?",
        ],
        coverage_points=["company", "culture", "teams"],
        question_completeness="complete",
        response_shape="direct_structured",
        directness="balanced",
        include_profile_opening=False,
        evidence_depth="medium",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="support_if_relevant",
        candidate_context_policy="required",
        ordered_coverage_required=True,
        target_length=190,
        draft_answer="",
        serve_mode="finalize_from_plan",
        confidence=0.55,
        plan_source="safe_fallback",
    )
    evidence_pack = CompactEvidencePack(
        plan_hash="plan-hash-preference-follow-up",
        candidate_snippets=["I work best in pragmatic teams with clear ownership, low bureaucracy, and direct communication."],
        company_snippets=["Empathy, speed, and execution focus."],
        interviewer_snippets=[],
        supporting_metrics=[],
        excluded_topics=["unsupported_metrics"],
        mode="full",
    )

    result = await finalizer.finalize(
        plan=plan,
        evidence_pack=evidence_pack,
        question_text=plan.resolved_question,
        conversation_history=[{"speaker": "interviewer", "text": plan.resolved_question}],
        interview_config=_build_live_pipeline_stub().session_state.interview_config,
    )

    assert result["full_response"] == "I could not generate a reliable answer for this question in time."


@pytest.mark.asyncio
async def test_live_finalizer_emits_complete_brain_draft_without_rethinking():
    finalizer = LiveFinalizer()
    finalizer._finalize_with_llm = AsyncMock(return_value="This should not be used.")
    draft = (
        "I value collaborative teams where there is psychological safety to challenge ideas and experiment. "
        "I need clarity on strategy and ownership so my work stays connected to outcomes. "
        "I thrive in environments with strong technical rigor and continuous learning. "
        "What I avoid is siloed decision-making, low transparency, and micromanagement."
    )
    plan = BrainPlan(
        resolved_question=(
            "Answer these interviewer asks in order:\n"
            "1. What is important to you in terms of company culture and teams?\n"
            "2. What kind of things do you absolutely not like in a work environment?"
        ),
        ordered_asks=[
            "What is important to you in terms of company culture and teams?",
            "What kind of things do you absolutely not like in a work environment?",
        ],
        coverage_points=["company", "culture", "teams"],
        question_completeness="complete",
        question_type="behavioral",
        response_shape="direct_structured",
        directness="direct",
        include_profile_opening=False,
        evidence_depth="medium",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="support_if_relevant",
        candidate_context_policy="support_if_relevant",
        ordered_coverage_required=True,
        target_length=180,
        draft_answer=draft,
        serve_mode="finalize_from_draft",
        confidence=0.88,
        plan_source="llm_fast",
    )
    evidence_pack = CompactEvidencePack(
        plan_hash="plan-hash-brain-draft",
        candidate_snippets=[],
        company_snippets=[],
        interviewer_snippets=[],
        supporting_metrics=[],
        excluded_topics=[],
        mode="minimal",
    )

    result = await finalizer.finalize(
        plan=plan,
        evidence_pack=evidence_pack,
        question_text=plan.resolved_question,
        conversation_history=[{"speaker": "interviewer", "text": plan.resolved_question}],
        interview_config=_build_live_pipeline_stub().session_state.interview_config,
        working_draft=draft,
    )

    assert result["full_response"] == draft
    assert result["metadata"]["finalizer_fallback_kind"] == "brain_draft"
    finalizer._finalize_with_llm.assert_not_awaited()


@pytest.mark.asyncio
async def test_live_finalizer_returns_explicit_failure_for_multi_part_experience_question_without_brain_or_llm_output():
    finalizer = LiveFinalizer()
    plan = BrainPlan(
        resolved_question=(
            "Answer these interviewer asks in order:\n"
            "1. Tell me about your experience in building from 0, building from scratch.\n"
            "2. Tell me about your team management experience.\n"
            "3. How big were the teams you've managed?\n"
            "4. What roles did they have?"
        ),
        ordered_asks=[
            "Tell me about your experience in building from 0, building from scratch.",
            "Tell me about your team management experience.",
            "How big were the teams you've managed?",
            "What roles did they have?",
        ],
        question_type="behavioral",
        response_shape="direct_structured",
        directness="balanced",
        include_profile_opening=False,
        evidence_depth="medium",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="avoid",
        candidate_context_policy="required",
        ordered_coverage_required=True,
        target_length=190,
        draft_answer="",
        serve_mode="finalize_from_plan",
        confidence=0.55,
        question_completeness="complete",
        plan_source="safe_fallback",
    )
    evidence_pack = CompactEvidencePack(
        plan_hash="plan-hash-experience-multipart",
        candidate_snippets=[
            "Built and scaled a subscription operating model for modernization and data programs from scratch.",
            "Managed 20 direct managers and 345 indirect reports across multiple regions.",
            "Roles included engineers, architects, data scientists, and delivery leads in cross-functional teams.",
        ],
        company_snippets=[],
        interviewer_snippets=[],
        supporting_metrics=[],
        excluded_topics=[],
        mode="full",
    )

    result = await finalizer.finalize(
        plan=plan,
        evidence_pack=evidence_pack,
        question_text=plan.resolved_question,
        conversation_history=[{"speaker": "interviewer", "text": plan.resolved_question}],
        interview_config=_build_live_pipeline_stub().session_state.interview_config,
    )

    assert result["full_response"] == "I could not generate a reliable answer for this question in time."


@pytest.mark.asyncio
async def test_live_finalizer_ignores_safe_fallback_multi_ask_draft_and_rebuilds_from_evidence():
    finalizer = LiveFinalizer()
    finalizer._finalize_with_llm = AsyncMock(return_value="")
    plan = BrainPlan(
        resolved_question=(
            "Answer these interviewer asks in order:\n"
            "1. Tell me about your experience in building from 0, building from scratch.\n"
            "2. Tell me about your team management experience.\n"
            "3. What roles did they have?\n"
            "4. Tell me a little bit about you."
        ),
        ordered_asks=[
            "Tell me about your experience in building from 0, building from scratch.",
            "Tell me about your team management experience.",
            "What roles did they have?",
            "Tell me a little bit about you.",
        ],
        coverage_points=["building from 0", "team management", "team roles", "profile overview"],
        response_family="mixed_multi_part",
        answer_blueprint=[
            {
                "purpose": "build_or_experience",
                "ask_refs": ["Tell me about your experience in building from 0, building from scratch."],
                "required_elements": ["concrete build-from-zero example"],
                "preferred_evidence_types": ["build_evidence"],
                "avoid_topics": [],
                "target_sentence_count": 2,
            },
            {
                "purpose": "leadership_scope",
                "ask_refs": ["Tell me about your team management experience."],
                "required_elements": ["scope and scale"],
                "preferred_evidence_types": ["leadership_evidence"],
                "avoid_topics": [],
                "target_sentence_count": 2,
            },
            {
                "purpose": "team_composition",
                "ask_refs": ["What roles did they have?"],
                "required_elements": ["team composition"],
                "preferred_evidence_types": ["team_scope_evidence"],
                "avoid_topics": [],
                "target_sentence_count": 1,
            },
            {
                "purpose": "intro_tail",
                "ask_refs": ["Tell me a little bit about you."],
                "required_elements": ["current role"],
                "preferred_evidence_types": ["role_evidence"],
                "avoid_topics": [],
                "target_sentence_count": 1,
            },
        ],
        question_type="behavioral",
        response_shape="direct_structured",
        answer_contract="business_with_outcomes",
        directness="balanced",
        include_profile_opening=False,
        evidence_depth="medium",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="support_if_relevant",
        candidate_context_policy="required",
        ordered_coverage_required=True,
        target_length=190,
        question_completeness="complete",
        draft_answer=(
            "One clear example is, I built and scaled a subscription operating model for modernization and data programs. "
            "On team leadership, global leadership scope managing 20 direct managers and 345 indirect reports across multiple regions. "
            "Those teams included Technology executive with 20 years leading enterprise transformation across software modernization and the full data lifecycle."
        ),
        serve_mode="finalize_from_plan",
        confidence=0.6,
        plan_source="safe_fallback",
    )
    evidence_pack = CompactEvidencePack(
        plan_hash="plan-hash-safe-fallback-rebuild",
        candidate_snippets=[],
        company_snippets=[],
        interviewer_snippets=[],
        role_evidence=["I'm currently serving as Technology Director, Data & AI at Globant."],
        build_evidence=["I founded the Generative AI practice in Colombia and developed seven reusable assets."],
        leadership_evidence=["I've managed 20 direct managers and 345 indirect reports across multiple regions."],
        team_scope_evidence=["solution architects, data engineers, consultants, delivery managers, and engineering leads"],
        supporting_metrics=[],
        excluded_topics=[],
        mode="full",
    )

    result = await finalizer.finalize(
        plan=plan,
        evidence_pack=evidence_pack,
        question_text=plan.resolved_question,
        conversation_history=[{"speaker": "interviewer", "text": plan.resolved_question}],
        interview_config=_build_live_pipeline_stub().session_state.interview_config,
        working_draft=plan.draft_answer,
    )

    lowered = result["full_response"].lower()
    assert result["metadata"]["finalizer_fallback_kind"] == "deterministic"
    assert "founded the generative ai practice" in lowered
    assert "20 direct managers and 345 indirect reports" in lowered
    assert "solution architects" in lowered
    assert "technology executive with 20 years" not in lowered
    finalizer._finalize_with_llm.assert_awaited_once()


@pytest.mark.asyncio
async def test_live_finalizer_returns_explicit_failure_instead_of_using_company_requirement_fallback_for_experience_question():
    finalizer = LiveFinalizer()
    plan = BrainPlan(
        resolved_question=(
            "Answer these interviewer asks in order:\n"
            "1. Tell me about your experience in building from 0, building from scratch.\n"
            "2. Tell me about your team management experience.\n"
            "3. How big were the teams you've managed?\n"
            "4. What roles did they have?"
        ),
        ordered_asks=[
            "Tell me about your experience in building from 0, building from scratch.",
            "Tell me about your team management experience.",
            "How big were the teams you've managed?",
            "What roles did they have?",
        ],
        coverage_points=["experience in building from 0", "building from scratch", "team management experience"],
        question_type="behavioral",
        answer_contract="business_with_outcomes",
        response_shape="direct_structured",
        directness="balanced",
        include_profile_opening=False,
        evidence_depth="medium",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="support_if_relevant",
        candidate_context_policy="required",
        ordered_coverage_required=True,
        target_length=190,
        draft_answer="",
        serve_mode="finalize_from_plan",
        confidence=0.55,
        question_completeness="complete",
        plan_source="safe_fallback",
    )
    evidence_pack = CompactEvidencePack(
        plan_hash="plan-hash-experience-priority",
        candidate_snippets=[
            "Founded the Generative AI practice in Colombia and developed 7 reusable assets.",
            "Managed 20 direct managers and 345 indirect reports across multiple regions.",
            "Roles included engineers, architects, data scientists, and delivery leads.",
        ],
        company_snippets=[
            "5+ years in technical leadership and team management roles.",
            "Director - Data Architecture & Engineering",
        ],
        interviewer_snippets=[],
        supporting_metrics=[],
        excluded_topics=[],
        mode="full",
    )

    result = await finalizer.finalize(
        plan=plan,
        evidence_pack=evidence_pack,
        question_text=plan.resolved_question,
        conversation_history=[{"speaker": "interviewer", "text": plan.resolved_question}],
        interview_config=_build_live_pipeline_stub().session_state.interview_config,
    )

    assert result["full_response"] == "I could not generate a reliable answer for this question in time."


@pytest.mark.asyncio
async def test_manager_v3_emits_debug_payload_for_new_architecture(monkeypatch):
    monkeypatch.setenv("LIVE_BRAIN_V3_ENABLED", "1")
    monkeypatch.setenv("LIVE_LEGACY_FALLBACK", "0")

    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()
    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-v3-debug",
        default_mode="real",
    )

    manager._get_raw_live_turn_window = lambda limit=5: [
        {
            "speaker": "interviewer",
            "text": "What are you looking for in a company and what do you avoid?",
            "timestamp": datetime.utcnow().isoformat(),
        }
    ]

    manager._live_brain_service_v3.plan = AsyncMock(
        return_value=BrainPlan(
            session_id="session-v3-debug",
            utterance_id="u-1",
            revision_id=3,
            snapshot_hash="hash-v3",
            ordered_asks=[
                "What are you looking for in a company?",
                "What do you avoid?",
            ],
            raw_detected_asks=[
                "What are you looking for in a company?",
                "What do you avoid?",
            ],
            resolved_question="Answer these interviewer asks in order:\n1. What are you looking for in a company?\n2. What do you avoid?",
            question_completeness="complete",
            question_type="direct",
            response_shape="direct_structured",
            answer_contract="preferences_and_anti_patterns",
            delivery_instructions=[
                "Answer the asks in order.",
                "State what matters most first, then what to avoid.",
            ],
            tone="professional",
            directness="direct",
            include_profile_opening=False,
            evidence_depth="light",
            metrics_policy="avoid_unless_helpful",
            company_context_policy="support_if_relevant",
            candidate_context_policy="support_if_relevant",
            ordered_coverage_required=True,
            target_length=130,
            draft_answer="I’m looking for a pragmatic company with strong execution, and I avoid overly political environments that slow decisions down.",
                serve_mode="finalize_from_draft",
            confidence=0.92,
            stability_state="draft",
            plan_source="llm_fast",
            reasoning_summary="Plan asks in order and answer directly without extra profile noise.",
        )
    )

    turn = SpeakerTurn(
        speaker="interviewer",
        text="What are you looking for in a company and what do you avoid?",
        start_time=0.0,
        end_time=3.0,
        utterances=["What are you looking for in a company and what do you avoid?"],
        language="en",
        metadata={},
        completion_reason="utterance_complete",
        is_complete=True,
    )
    manager._latest_interviewer_generation = 1
    manager._last_interviewer_activity_at = (
        time.time() - (manager._turn_assembler.state.silence_threshold_ms / 1000.0) - 0.1
    )

    await manager._try_auto_trigger_suggestion(turn, generation_token=1)

    suggestion_events = [event for event in websocket.events if event.get("type") == "suggestion"]
    assert suggestion_events
    suggestion = suggestion_events[-1]
    assert suggestion["path_used"] == "brain_finalize_from_plan"
    assert suggestion["debug"]["question"] == suggestion["debug"]["request_payload"]["question"]
    assert suggestion["debug"]["planner_source"] == "brain_v4"
    assert suggestion["debug"]["brain_plan_serve_mode"] == "finalize_from_plan"
    assert suggestion["debug"]["draft_answer"] == ""
    assert suggestion["debug"]["literal_question"] == suggestion["debug"]["question"]
    assert suggestion["debug"]["contextualized_question"] != ""
    assert "company" in suggestion["debug"]["contextualized_question"].lower()
    assert suggestion["debug"]["brain_contract"]["literal_question"] == suggestion["debug"]["question"]
    assert suggestion["debug"]["brain_contract"]["contextualized_question"] == suggestion["debug"]["contextualized_question"]
    assert suggestion["debug"]["compact_evidence_ready"] is True
    assert suggestion["debug"]["brain_plan_source"] in {"llm_fast", "safe_fallback"}
    assert suggestion["debug"]["question_completeness"] == "complete"
    assert suggestion["debug"]["brain_answer_contract"] == "preferences_and_anti_patterns"
    assert suggestion["debug"]["brain_delivery_instructions"]
    assert suggestion["debug"]["normalized_answer_contract"] == "preferences_and_anti_patterns"
    assert suggestion["debug"]["hard_silence_authorized"] is True
    assert "brain_immediate_safe_fallback_at_freeze" in suggestion["debug"]


@pytest.mark.asyncio
async def test_manager_v3_waits_for_hard_silence_before_auto_suggestion():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()
    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-v3-hard-silence-gate",
        default_mode="real",
    )

    turn = SpeakerTurn(
        speaker="interviewer",
        text="Tell me a bit about yourself.",
        start_time=0.0,
        end_time=1.0,
        utterances=["Tell me a bit about yourself."],
        language="en",
        metadata={},
        completion_reason="utterance_complete",
        is_complete=True,
    )
    manager._latest_interviewer_generation = 3
    manager._last_interviewer_activity_at = time.time()
    manager._schedule_silence_suggestion = MagicMock()

    await manager._try_auto_trigger_suggestion(turn, generation_token=3)

    assert not [event for event in websocket.events if event.get("type") == "suggestion"]
    manager._schedule_silence_suggestion.assert_called_once()
    assert manager._answer_gate_reason == "waiting_for_hard_silence"
    assert manager._hard_silence_authorized is False


@pytest.mark.asyncio
async def test_manager_v3_completed_turn_preserves_real_silence_anchor():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()
    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-v3-anchor-preserved",
        default_mode="real",
    )
    manager._stream_started_at = time.perf_counter()

    anchor_time = time.time() - 1.4
    manager._last_interviewer_activity_at = anchor_time
    manager._interviewer_activity_epoch = 1

    turn = SpeakerTurn(
        speaker="interviewer",
        text="Tell me about your team management experience.",
        start_time=anchor_time - 1.0,
        end_time=anchor_time,
        utterances=["Tell me about your team management experience."],
        language="en",
        metadata={},
        completion_reason="utterance_complete",
        is_complete=True,
    )

    await manager._process_completed_turn(turn)

    assert manager._last_interviewer_activity_at == anchor_time
    assert manager._completed_turn_processed_at_ms is not None
    assert manager._completed_turn_after_last_activity_ms is not None
    assert manager._answer_gate_reason == "completed_turn_waiting_for_silence"


@pytest.mark.asyncio
async def test_manager_v3_hard_silence_gate_triggers_immediately_when_satisfied():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()
    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-v3-hard-silence-immediate",
        default_mode="real",
    )
    manager._stream_started_at = time.perf_counter()

    threshold_sec = manager._turn_assembler.state.silence_threshold_ms / 1000.0
    manager._interviewer_activity_epoch = 3
    manager._last_interviewer_activity_at = time.time() - threshold_sec - 0.1
    manager._completed_live_interviewer_blocks = [
        {"speaker": "interviewer", "text": "Tell me a bit about yourself."}
    ]
    manager._try_auto_trigger_suggestion = AsyncMock()

    manager._schedule_hard_silence_gate()
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    manager._try_auto_trigger_suggestion.assert_awaited_once()
    assert manager._silence_gate_scheduled_delay_ms == 0
    assert manager._silence_gate_fired_at_ms is not None


@pytest.mark.asyncio
async def test_manager_v3_final_brain_readiness_refresh_runs_for_incomplete_exact_snapshot():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()
    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-v3-final-readiness",
        default_mode="real",
    )
    manager._live_brain_v3_enabled = True

    brain_snapshot = BrainSnapshot(
        session_id="session-v3-final-readiness",
        utterance_id="u-final-readiness",
        revision_id=2,
        snapshot_text="Tell me about your experience in building from scratch and the teams you led.",
        conversation_history=[
            {
                "speaker": "interviewer",
                "text": "Tell me about your experience in building from scratch and the teams you led.",
            }
        ],
        snapshot_hash="hash-final-readiness",
        timestamp=datetime.utcnow(),
    )
    manager._latest_brain_snapshot_v3 = brain_snapshot
    manager._latest_brain_plan_v3 = BrainPlan(
        session_id="session-v3-final-readiness",
        utterance_id="u-final-readiness",
        revision_id=2,
        snapshot_hash="hash-final-readiness",
        ordered_asks=["Tell me about your experience in building from scratch and the teams you led."],
        resolved_question="Tell me about your experience in building from scratch and the teams you led.",
        question_completeness="partial",
        response_shape="direct_structured",
        directness="balanced",
        include_profile_opening=False,
        evidence_depth="medium",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="support_if_relevant",
        candidate_context_policy="required",
        ordered_coverage_required=True,
        target_length=180,
        draft_answer="",
        serve_mode="finalize_from_plan",
        confidence=0.8,
        stability_state="draft",
        plan_source="llm_fast",
    )
    manager._build_live_brain_snapshot_v3 = MagicMock(return_value=brain_snapshot)
    manager._queue_live_brain_v3_refresh = MagicMock()
    manager._await_live_brain_v3_refresh = AsyncMock(return_value=0)
    manager._interviewer_activity_epoch = 5
    manager._last_interviewer_activity_at = time.time() - manager._live_emit_late_prewarm_quiet_sec - 0.1

    manager._schedule_final_brain_readiness_refresh()
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert manager._late_brain_refresh_started_before_silence is True
    manager._queue_live_brain_v3_refresh.assert_called_once_with(reason="final_readiness")


@pytest.mark.asyncio
async def test_manager_v3_freeze_waits_for_matching_inflight_refresh_before_force_stable():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()
    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-v3-freeze-inflight-refresh",
        default_mode="real",
    )

    raw_turn_window = [
        {
            "speaker": "interviewer",
            "text": "Tell me about your experience in building from scratch and leading teams.",
            "timestamp": datetime.utcnow().isoformat(),
        }
    ]
    brain_snapshot = BrainSnapshot(
        session_id="session-v3-freeze-inflight-refresh",
        utterance_id="u-freeze-inflight-refresh",
        revision_id=4,
        snapshot_text="Tell me about your experience in building from scratch and leading teams.",
        conversation_history=raw_turn_window,
        snapshot_hash="hash-freeze-inflight-refresh",
        timestamp=datetime.utcnow(),
    )
    ready_plan = BrainPlan(
        session_id="session-v3-freeze-inflight-refresh",
        utterance_id="u-freeze-inflight-refresh",
        revision_id=4,
        snapshot_hash="hash-freeze-inflight-refresh",
        ordered_asks=["Tell me about your experience in building from scratch and leading teams."],
        resolved_question="Tell me about your experience in building from scratch and leading teams.",
        question_completeness="complete",
        response_shape="direct_structured",
        directness="balanced",
        include_profile_opening=False,
        evidence_depth="medium",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="support_if_relevant",
        candidate_context_policy="required",
        ordered_coverage_required=True,
        target_length=180,
        draft_answer="",
        serve_mode="finalize_from_plan",
        confidence=0.86,
        stability_state="stable",
        plan_source="llm_fast",
    )
    evidence_pack = CompactEvidencePack(
        plan_hash=LiveBrainService.plan_hash(ready_plan),
        candidate_snippets=["Built and scaled a subscription operating model across 17+ accounts."],
        company_snippets=[],
        interviewer_snippets=[],
        supporting_metrics=[],
        excluded_topics=[],
        mode="full",
    )

    manager._get_raw_live_turn_window = MagicMock(return_value=raw_turn_window)
    manager._build_live_brain_snapshot_v3 = MagicMock(return_value=brain_snapshot)
    manager._live_brain_refresh_active_signature_v3 = brain_snapshot.snapshot_hash
    manager._live_brain_refresh_task_v3 = asyncio.create_task(asyncio.sleep(10))

    async def _fake_wait_for_refresh(*, snapshot_hash: str, timeout_sec=None):
        manager._latest_brain_snapshot_v3 = brain_snapshot
        manager._latest_brain_plan_v3 = ready_plan
        manager._latest_compact_evidence_pack_v3 = evidence_pack
        return 123

    manager._await_live_brain_v3_refresh = AsyncMock(side_effect=_fake_wait_for_refresh)

    try:
        snapshot = await manager._build_live_frozen_snapshot_v3(
            interview_config=pipeline.session_state.interview_config,
        )
    finally:
        manager._live_brain_refresh_task_v3.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await manager._live_brain_refresh_task_v3

    assert snapshot is not None
    assert manager._brain_refresh_waited_at_freeze_ms == 123
    assert manager._brain_force_stable_at_freeze is False


@pytest.mark.asyncio
async def test_manager_v3_freeze_uses_immediate_safe_fallback_when_refresh_is_not_ready():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()
    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-v3-freeze-immediate-safe-fallback",
        default_mode="real",
    )

    raw_turn_window = [
        {
            "speaker": "interviewer",
            "text": "Tell me about your experience building from scratch and the teams you led.",
            "timestamp": datetime.utcnow().isoformat(),
        }
    ]
    brain_snapshot = BrainSnapshot(
        session_id="session-v3-freeze-immediate-safe-fallback",
        utterance_id="u-freeze-immediate-safe-fallback",
        revision_id=5,
        snapshot_text="Tell me about your experience building from scratch and the teams you led.",
        conversation_history=raw_turn_window,
        snapshot_hash="hash-freeze-immediate-safe-fallback",
        timestamp=datetime.utcnow(),
    )
    safe_plan = BrainPlan(
        session_id="session-v3-freeze-immediate-safe-fallback",
        utterance_id="u-freeze-immediate-safe-fallback",
        revision_id=5,
        snapshot_hash="hash-freeze-immediate-safe-fallback",
        ordered_asks=["Tell me about your experience building from scratch and the teams you led."],
        resolved_question="Tell me about your experience building from scratch and the teams you led.",
        question_completeness="complete",
        response_shape="direct_structured",
        directness="balanced",
        include_profile_opening=False,
        evidence_depth="medium",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="support_if_relevant",
        candidate_context_policy="required",
        ordered_coverage_required=True,
        target_length=180,
        draft_answer="",
        serve_mode="finalize_from_plan",
        confidence=0.72,
        stability_state="draft",
        plan_source="safe_fallback",
    )

    manager._get_raw_live_turn_window = MagicMock(return_value=raw_turn_window)
    manager._build_live_brain_snapshot_v3 = MagicMock(return_value=brain_snapshot)
    manager._live_brain_refresh_active_signature_v3 = brain_snapshot.snapshot_hash
    manager._live_brain_refresh_task_v3 = asyncio.create_task(asyncio.sleep(10))
    manager._await_live_brain_v3_refresh = AsyncMock(return_value=200)
    manager._live_brain_service_v3.plan = AsyncMock(side_effect=AssertionError("llm plan should not run at freeze"))
    manager._live_brain_service_v3.safe_plan = MagicMock(return_value=safe_plan)

    try:
        snapshot = await manager._build_live_frozen_snapshot_v3(
            interview_config=pipeline.session_state.interview_config,
        )
    finally:
        manager._live_brain_refresh_task_v3.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await manager._live_brain_refresh_task_v3

    assert snapshot is not None
    assert snapshot.brain_plan.plan_source == "safe_fallback"
    assert manager._brain_refresh_waited_at_freeze_ms == 200
    assert manager._brain_force_stable_at_freeze is True
    assert manager._brain_immediate_safe_fallback_at_freeze is True
    manager._live_brain_service_v3.safe_plan.assert_called_once()


def test_manager_v3_skips_brain_refresh_for_small_caption_churn():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()
    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-v3-caption-churn",
        default_mode="real",
    )

    manager._live_brain_semantic_revision_text_v3 = (
        "Tell me about your experience in building from zero and leading teams"
    )
    manager._live_brain_semantic_word_count_v3 = 12
    manager._live_brain_semantic_completed_turn_count_v3 = 2
    manager._completed_interviewer_turn_count = 2

    snapshot = BrainSnapshot(
        session_id="session-v3-caption-churn",
        utterance_id="u-caption-churn",
        revision_id=2,
        snapshot_text=(
            "Tell me about your experience in building from zero and leading teams across regions"
        ),
        conversation_history=[
            {
                "speaker": "interviewer",
                "text": "Tell me about your experience in building from zero and leading teams across regions",
            }
        ],
        snapshot_hash="hash-caption-churn",
        timestamp=datetime.utcnow(),
    )

    should_refresh, reason = manager._should_refresh_live_brain_v3(
        brain_snapshot=snapshot,
    )

    assert should_refresh is False
    assert reason == "caption_churn"


@pytest.mark.asyncio
async def test_manager_v3_does_not_prewarm_emit_before_silence_even_when_plan_is_complete():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()
    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-v3-safe-fallback-no-warm",
        default_mode="real",
    )

    manager._live_finalizer_v3.finalize = AsyncMock(
        return_value={
            "full_response": "I founded the Generative AI practice in Colombia and later led teams across multiple regions.",
            "bullets": ["I founded the Generative AI practice in Colombia."],
            "confidence": 0.8,
            "latency_ms": 20,
            "metadata": {"finalizer_fallback_kind": "llm"},
        }
    )

    brain_snapshot = BrainSnapshot(
        session_id="session-v3-safe-fallback-no-warm",
        utterance_id="u-safe-fallback-no-warm",
        revision_id=4,
        snapshot_text=(
            "Tell me about your experience in building from 0, building from scratch. "
            "Also cover your team management experience."
        ),
        conversation_history=[
            {
                "speaker": "interviewer",
                "text": (
                    "Tell me about your experience in building from 0, building from scratch. "
                    "Also cover your team management experience."
                ),
            }
        ],
        snapshot_hash="hash-safe-fallback-no-warm",
        timestamp=datetime.utcnow(),
    )
    brain_plan = BrainPlan(
        session_id="session-v3-safe-fallback-no-warm",
        utterance_id="u-safe-fallback-no-warm",
        revision_id=4,
        snapshot_hash="hash-safe-fallback-no-warm",
        ordered_asks=[
            "Tell me about your experience in building from 0, building from scratch.",
            "Tell me about your team management experience.",
        ],
        raw_detected_asks=[
            "Tell me about your experience in building from 0, building from scratch.",
            "Tell me about your team management experience.",
        ],
        resolved_question=(
            "Answer these interviewer asks in order:\n"
            "1. Tell me about your experience in building from 0, building from scratch.\n"
            "2. Tell me about your team management experience."
        ),
        question_completeness="complete",
        question_type="behavioral",
        response_shape="direct_structured",
        answer_contract="business_with_outcomes",
        delivery_instructions=["Answer the asks in order."],
        tone="professional",
        directness="balanced",
        include_profile_opening=False,
        evidence_depth="medium",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="support_if_relevant",
        candidate_context_policy="required",
        ordered_coverage_required=True,
        target_length=180,
        draft_answer=(
            "I've built capabilities from zero in multiple contexts.\n\n"
            "On team leadership, I've managed leaders and broader delivery organizations."
        ),
        serve_mode="finalize_from_draft",
        confidence=0.55,
        stability_state="draft",
        plan_source="safe_fallback",
    )
    evidence_pack = CompactEvidencePack(
        plan_hash="plan-hash-safe-fallback-warm",
        candidate_snippets=["Founded the Generative AI practice in Colombia and developed 7 reusable assets."],
        company_snippets=[],
        interviewer_snippets=[],
        supporting_metrics=[],
        excluded_topics=[],
        mode="full",
    )
    manager._last_interviewer_activity_at = (
        time.time() - manager._live_emit_late_prewarm_quiet_sec - 0.2
    )

    manager._schedule_live_brain_warm_from_plan(
        brain_snapshot=brain_snapshot,
        brain_plan=brain_plan,
        evidence_pack=evidence_pack,
        interview_config=pipeline.session_state.interview_config,
    )

    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert manager._brain_warm_inflight_task_v3 is None
    assert manager._brain_warm_latest_result_v3 is None
    assert manager._emit_prewarm_count_before_silence == 0
    assert manager._emit_calls_before_silence == 0
    manager._live_finalizer_v3.finalize.assert_not_awaited()


@pytest.mark.asyncio
async def test_manager_v3_prefers_plan_finalization_over_safe_fallback_draft_at_silence():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()
    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-v3-draft-at-silence",
        default_mode="real",
    )

    manager._await_live_brain_warm_exact_result = AsyncMock()
    manager._live_finalizer_v3.finalize = AsyncMock(
        return_value={
            "full_response": (
                "I've built capabilities from zero in multiple contexts.\n\n"
                "On team leadership, I've led managers and multi-region delivery teams."
            ),
            "bullets": ["I've built capabilities from zero in multiple contexts."],
            "confidence": 0.84,
            "latency_ms": 20,
            "metadata": {"finalizer_fallback_kind": "brain_draft"},
        }
    )

    sleep_task = asyncio.create_task(asyncio.sleep(10))
    manager._brain_warm_inflight_task_v3 = sleep_task
    manager._brain_warm_inflight_checkpoint_v3 = MagicMock(
        checkpoint_id="ck-draft-silence",
        plan_hash="plan-hash-draft-silence",
        question_key="question-key-draft-silence",
    )

    brain_plan = BrainPlan(
        session_id="session-v3-draft-at-silence",
        utterance_id="u-draft-at-silence",
        revision_id=7,
        snapshot_hash="hash-draft-at-silence",
        ordered_asks=[
            "Tell me about your experience in building from 0, building from scratch.",
            "Tell me about your team management experience.",
        ],
        resolved_question=(
            "Answer these interviewer asks in order:\n"
            "1. Tell me about your experience in building from 0, building from scratch.\n"
            "2. Tell me about your team management experience."
        ),
        question_completeness="complete",
        question_type="behavioral",
        response_shape="direct_structured",
        answer_contract="business_with_outcomes",
        directness="balanced",
        include_profile_opening=False,
        evidence_depth="medium",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="support_if_relevant",
        candidate_context_policy="required",
        ordered_coverage_required=True,
        target_length=180,
        draft_answer=(
            "I've built capabilities from zero in multiple contexts.\n\n"
            "On team leadership, I've led managers and multi-region delivery teams."
        ),
        serve_mode="finalize_from_draft",
        confidence=0.78,
        stability_state="draft",
        plan_source="safe_fallback",
    )
    snapshot = LiveFrozenSnapshot(
        raw_turn_window=[{"speaker": "interviewer", "text": "Tell me about your experience in building from 0."}],
        turn_window=[{"speaker": "interviewer", "text": "Tell me about your experience in building from 0."}],
        raw_context_bundle={},
        signature="sig-draft-at-silence",
        question_text=brain_plan.resolved_question,
        conversation_history=[{"speaker": "interviewer", "text": "Tell me about your experience in building from 0."}],
        prepared_context=None,
        request_payload={"question": brain_plan.resolved_question},
        question_source="brain_v4",
        cache_hit=False,
        brain_snapshot=BrainSnapshot(
            session_id="session-v3-draft-at-silence",
            utterance_id="u-draft-at-silence",
            revision_id=7,
            snapshot_text="Tell me about your experience in building from 0.",
            conversation_history=[{"speaker": "interviewer", "text": "Tell me about your experience in building from 0."}],
            snapshot_hash="hash-draft-at-silence",
            timestamp=datetime.utcnow(),
        ),
        brain_plan=brain_plan,
        compact_evidence_pack=CompactEvidencePack(
            plan_hash="plan-hash-draft-silence",
            candidate_snippets=[],
            company_snippets=[],
            interviewer_snippets=[],
            supporting_metrics=[],
            excluded_topics=[],
            mode="full",
        ),
        plan_hash="plan-hash-draft-silence",
        checkpoint_id="checkpoint-draft-at-silence",
        question_key="question-key-draft-at-silence",
    )

    response, path_used, _, quality_prewarm_wait_ms, draft_ready_at_silence = await manager._generate_live_response_from_snapshot_v3(
        snapshot=snapshot,
        interview_config=pipeline.session_state.interview_config,
    )

    assert path_used == "brain_finalize_from_plan"
    assert quality_prewarm_wait_ms == 0
    assert draft_ready_at_silence is False
    assert response["full_response"].startswith("I've built capabilities from zero")
    manager._await_live_brain_warm_exact_result.assert_not_awaited()
    assert manager._live_finalizer_v3.finalize.await_args.kwargs["working_draft"] == ""
    assert manager._live_finalizer_v3.finalize.await_args.kwargs["strict_emit_only"] is True
    assert (
        manager._live_finalizer_v3.finalize.await_args.kwargs["timeout_override_sec"]
        == manager._live_quality_final_emit_timeout_sec
    )
    sleep_task.cancel()


@pytest.mark.asyncio
async def test_manager_v3_passes_recovery_draft_to_strict_finalizer_and_surfaces_recovery_debug():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()
    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-v3-recovery-debug",
        default_mode="real",
    )

    brain_plan = BrainPlan(
        session_id="session-v3-recovery-debug",
        utterance_id="u-recovery-debug",
        revision_id=7,
        snapshot_hash="hash-recovery-debug",
        ordered_asks=["Tell me about your experience in building from 0."],
        resolved_question="Tell me about your experience in building from 0.",
        question_completeness="complete",
        response_shape="direct_short",
        directness="direct",
        include_profile_opening=False,
        evidence_depth="medium",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="support_if_relevant",
        candidate_context_policy="required",
        ordered_coverage_required=True,
        target_length=140,
        draft_answer="This draft should be stripped from the active route.",
        serve_mode="finalize_from_draft",
        confidence=0.81,
        stability_state="draft",
        plan_source="safe_fallback",
    )
    snapshot = LiveFrozenSnapshot(
        raw_turn_window=[{"speaker": "interviewer", "text": "Tell me about your experience in building from 0."}],
        turn_window=[{"speaker": "interviewer", "text": "Tell me about your experience in building from 0."}],
        raw_context_bundle={},
        signature="sig-recovery-debug",
        question_text=brain_plan.resolved_question,
        conversation_history=[{"speaker": "interviewer", "text": "Tell me about your experience in building from 0."}],
        prepared_context=None,
        request_payload={"question": brain_plan.resolved_question},
        question_source="brain_v4",
        cache_hit=False,
        brain_snapshot=BrainSnapshot(
            session_id="session-v3-recovery-debug",
            utterance_id="u-recovery-debug",
            revision_id=7,
            snapshot_text="Tell me about your experience in building from 0.",
            conversation_history=[{"speaker": "interviewer", "text": "Tell me about your experience in building from 0."}],
            snapshot_hash="hash-recovery-debug",
            timestamp=datetime.utcnow(),
        ),
        brain_plan=brain_plan,
        compact_evidence_pack=CompactEvidencePack(
            plan_hash="plan-hash-recovery-debug",
            candidate_snippets=[],
            company_snippets=[],
            interviewer_snippets=[],
            supporting_metrics=[],
            excluded_topics=[],
            mode="full",
        ),
        plan_hash="plan-hash-recovery-debug",
        checkpoint_id="checkpoint-recovery-debug",
        question_key="question-key-recovery-debug",
        recovery_draft="Recovered from freeze draft.",
        recovery_draft_available=True,
    )
    manager._live_finalizer_v3.finalize = AsyncMock(
        return_value={
            "full_response": "Deterministic recovery answer.",
            "bullets": ["Deterministic recovery answer."],
            "confidence": 0.86,
            "latency_ms": 30,
            "metadata": {
                "finalizer_fallback_kind": "deterministic",
                "finalizer_primary_mode": "strict_emit_only",
                "finalizer_primary_success": False,
                "recovery_draft_available": True,
                "finalizer_recovery_attempted": True,
                "finalizer_recovery_kind": "deterministic",
                "finalizer_recovery_success": True,
                "finalizer_recovery_skipped_reason": "",
            },
        }
    )

    response, path_used, _, _, _ = await manager._generate_live_response_from_snapshot_v3(
        snapshot=snapshot,
        interview_config=pipeline.session_state.interview_config,
    )

    assert path_used == "brain_finalize_from_plan"
    assert response["debug"]["recovery_applied"] is True
    assert response["debug"]["recovery_kind"] == "deterministic"
    assert response["debug"]["recovery_draft_available"] is True
    assert response["debug"]["finalizer_primary_success"] is False
    assert response["debug"]["finalizer_recovery_success"] is True
    assert manager._live_finalizer_v3.finalize.await_args.kwargs["working_draft"] == ""
    assert manager._live_finalizer_v3.finalize.await_args.kwargs["strict_emit_only"] is True
    assert manager._live_finalizer_v3.finalize.await_args.kwargs["recovery_draft"] == "Recovered from freeze draft."
    assert manager._live_finalizer_v3.finalize.await_args.kwargs["allow_post_failure_recovery"] is True


@pytest.mark.asyncio
async def test_manager_v3_keeps_active_plan_draft_empty_while_using_snapshot_recovery_draft():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()
    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-v3-recovery-draft-route",
        default_mode="real",
    )

    brain_plan = BrainPlan(
        session_id="session-v3-recovery-draft-route",
        utterance_id="u-recovery-draft-route",
        revision_id=7,
        snapshot_hash="hash-recovery-draft-route",
        ordered_asks=["Tell me about your experience in building from 0."],
        resolved_question="Tell me about your experience in building from 0.",
        question_completeness="complete",
        response_shape="direct_short",
        directness="direct",
        include_profile_opening=False,
        evidence_depth="medium",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="support_if_relevant",
        candidate_context_policy="required",
        ordered_coverage_required=True,
        target_length=140,
        draft_answer="This draft must not survive in the active route.",
        serve_mode="finalize_from_draft",
        confidence=0.81,
        stability_state="draft",
        plan_source="safe_fallback",
    )
    snapshot = LiveFrozenSnapshot(
        raw_turn_window=[{"speaker": "interviewer", "text": "Tell me about your experience in building from 0."}],
        turn_window=[{"speaker": "interviewer", "text": "Tell me about your experience in building from 0."}],
        raw_context_bundle={},
        signature="sig-recovery-draft-route",
        question_text=brain_plan.resolved_question,
        conversation_history=[{"speaker": "interviewer", "text": "Tell me about your experience in building from 0."}],
        prepared_context=None,
        request_payload={"question": brain_plan.resolved_question},
        question_source="brain_v4",
        cache_hit=False,
        brain_snapshot=BrainSnapshot(
            session_id="session-v3-recovery-draft-route",
            utterance_id="u-recovery-draft-route",
            revision_id=7,
            snapshot_text="Tell me about your experience in building from 0.",
            conversation_history=[{"speaker": "interviewer", "text": "Tell me about your experience in building from 0."}],
            snapshot_hash="hash-recovery-draft-route",
            timestamp=datetime.utcnow(),
        ),
        brain_plan=brain_plan,
        compact_evidence_pack=CompactEvidencePack(
            plan_hash="plan-hash-recovery-draft-route",
            candidate_snippets=[],
            company_snippets=[],
            interviewer_snippets=[],
            supporting_metrics=[],
            excluded_topics=[],
            mode="full",
        ),
        plan_hash="plan-hash-recovery-draft-route",
        checkpoint_id="checkpoint-recovery-draft-route",
        question_key="question-key-recovery-draft-route",
        recovery_draft="I've built capabilities from zero.\n\nI've led multi-region teams.",
        recovery_draft_available=True,
    )
    manager._live_finalizer_v3.finalize = AsyncMock(
        return_value={
            "full_response": "I've built capabilities from zero.\n\nI've led multi-region teams.",
            "bullets": ["I've built capabilities from zero.", "I've led multi-region teams."],
            "confidence": 0.84,
            "latency_ms": 26,
            "metadata": {
                "finalizer_fallback_kind": "brain_draft",
                "finalizer_primary_mode": "strict_emit_only",
                "finalizer_primary_success": False,
                "recovery_draft_available": True,
                "finalizer_recovery_attempted": True,
                "finalizer_recovery_kind": "brain_draft",
                "finalizer_recovery_success": True,
                "finalizer_recovery_skipped_reason": "",
            },
        }
    )

    response, path_used, _, _, _ = await manager._generate_live_response_from_snapshot_v3(
        snapshot=snapshot,
        interview_config=pipeline.session_state.interview_config,
    )

    assert path_used == "brain_finalize_from_plan"
    assert response["debug"]["draft_answer"] == ""
    assert response["debug"]["recovery_kind"] == "brain_draft"
    assert response["debug"]["recovery_draft_available"] is True
    assert manager._live_finalizer_v3.finalize.await_args.kwargs["recovery_draft"] == (
        "I've built capabilities from zero.\n\nI've led multi-region teams."
    )


@pytest.mark.asyncio
async def test_manager_v3_does_not_emit_partial_stream_events_before_final_suggestion():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()
    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-v3-stream-after-silence",
        default_mode="real",
    )

    brain_plan = BrainPlan(
        session_id="session-v3-stream-after-silence",
        utterance_id="u-stream-after-silence",
        revision_id=7,
        snapshot_hash="hash-stream-after-silence",
        ordered_asks=["Tell me about your experience in building from 0."],
        resolved_question="Tell me about your experience in building from 0.",
        question_completeness="complete",
        question_type="behavioral",
        response_shape="direct_short",
        answer_contract="business_with_outcomes",
        directness="balanced",
        include_profile_opening=False,
        evidence_depth="medium",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="support_if_relevant",
        candidate_context_policy="required",
        ordered_coverage_required=True,
        target_length=140,
        draft_answer="",
        serve_mode="finalize_from_plan",
        confidence=0.82,
        stability_state="draft",
        plan_source="safe_fallback",
    )
    snapshot = LiveFrozenSnapshot(
        raw_turn_window=[{"speaker": "interviewer", "text": "Tell me about your experience in building from 0."}],
        turn_window=[{"speaker": "interviewer", "text": "Tell me about your experience in building from 0."}],
        raw_context_bundle={},
        signature="sig-stream-after-silence",
        question_text=brain_plan.resolved_question,
        conversation_history=[{"speaker": "interviewer", "text": "Tell me about your experience in building from 0."}],
        prepared_context=None,
        request_payload={"question": brain_plan.resolved_question},
        question_source="brain_v4",
        cache_hit=False,
        brain_snapshot=BrainSnapshot(
            session_id="session-v3-stream-after-silence",
            utterance_id="u-stream-after-silence",
            revision_id=7,
            snapshot_text="Tell me about your experience in building from 0.",
            conversation_history=[{"speaker": "interviewer", "text": "Tell me about your experience in building from 0."}],
            snapshot_hash="hash-stream-after-silence",
            timestamp=datetime.utcnow(),
        ),
        brain_plan=brain_plan,
        compact_evidence_pack=CompactEvidencePack(
            plan_hash="plan-hash-stream-after-silence",
            candidate_snippets=[],
            company_snippets=[],
            interviewer_snippets=[],
            supporting_metrics=[],
            excluded_topics=[],
            mode="full",
        ),
        plan_hash="plan-hash-stream-after-silence",
        checkpoint_id="checkpoint-stream-after-silence",
        question_key="question-key-stream-after-silence",
    )

    async def _streaming_finalize(**kwargs):
        await kwargs["on_partial_response"](
            {
                "full_response": "I've built capabilities from zero",
                "provider": "anthropic",
                "model": "claude-test",
                "chunk_count": 1,
                "first_chunk_ms": 45,
            }
        )
        await kwargs["on_partial_response"](
            {
                "full_response": "I've built capabilities from zero and led teams across multiple regions.",
                "provider": "anthropic",
                "model": "claude-test",
                "chunk_count": 2,
                "first_chunk_ms": 45,
            }
        )
        return {
            "full_response": "I've built capabilities from zero and led teams across multiple regions.",
            "bullets": ["I've built capabilities from zero and led teams across multiple regions."],
            "confidence": 0.86,
            "latency_ms": 120,
            "metadata": {
                "finalizer_fallback_kind": "llm",
                "provider": "anthropic",
                "model": "claude-test",
                "emit_stream_used": True,
                "emit_stream_first_chunk_ms": 45,
                "emit_stream_completed_ms": 120,
                "emit_stream_chunk_count": 2,
                "emit_stream_partial_salvaged": False,
            },
        }

    manager._live_finalizer_v3.finalize = AsyncMock(side_effect=_streaming_finalize)

    response, path_used, _, _, _ = await manager._generate_live_response_from_snapshot_v3(
        snapshot=snapshot,
        interview_config=pipeline.session_state.interview_config,
    )

    stream_events = [event for event in websocket.events if event.get("type") == "suggestion_stream"]
    suggestion_events = [event for event in websocket.events if event.get("type") == "suggestion"]
    assert path_used == "brain_finalize_from_plan"
    assert [event.get("stage") for event in stream_events] == ["start", "stream", "stream"]
    assert stream_events[-1].get("processing_full_response") is True
    assert suggestion_events == []
    assert response["debug"]["emit_stream_chunk_count"] == 2
    assert response["debug"]["emit_first_chunk_ms"] is not None


@pytest.mark.asyncio
async def test_manager_v3_reuses_completed_exact_warm_result_after_silence():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()
    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-v3-reuse-completed-exact-warm",
        default_mode="real",
    )

    brain_plan = BrainPlan(
        session_id="session-v3-reuse-completed-exact-warm",
        utterance_id="u-reuse-completed-exact-warm",
        revision_id=7,
        snapshot_hash="hash-reuse-completed-exact-warm",
        ordered_asks=["tell me a bit about yourself, if you would."],
        resolved_question="tell me a bit about yourself, if you would.",
        question_completeness="complete",
        question_type="behavioral",
        response_shape="direct_short",
        answer_contract="business_with_outcomes",
        directness="direct",
        include_profile_opening=True,
        evidence_depth="medium",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="support_if_relevant",
        candidate_context_policy="required",
        ordered_coverage_required=True,
        target_length=140,
        draft_answer="",
        serve_mode="finalize_from_plan",
        confidence=0.82,
        stability_state="draft",
        plan_source="safe_fallback",
    )
    snapshot = LiveFrozenSnapshot(
        raw_turn_window=[{"speaker": "interviewer", "text": "Tell me a bit about yourself, if you would."}],
        turn_window=[{"speaker": "interviewer", "text": "Tell me a bit about yourself, if you would."}],
        raw_context_bundle={},
        signature="sig-reuse-completed-exact-warm",
        question_text=brain_plan.resolved_question,
        conversation_history=[{"speaker": "interviewer", "text": "Tell me a bit about yourself, if you would."}],
        prepared_context=None,
        request_payload={"question": brain_plan.resolved_question},
        question_source="brain_v4",
        cache_hit=False,
        brain_snapshot=BrainSnapshot(
            session_id="session-v3-reuse-completed-exact-warm",
            utterance_id="u-reuse-completed-exact-warm",
            revision_id=7,
            snapshot_text="Tell me a bit about yourself, if you would.",
            conversation_history=[{"speaker": "interviewer", "text": "Tell me a bit about yourself, if you would."}],
            snapshot_hash="hash-reuse-completed-exact-warm",
            timestamp=datetime.utcnow(),
        ),
        brain_plan=brain_plan,
        compact_evidence_pack=CompactEvidencePack(
            plan_hash="plan-hash-reuse-completed-exact-warm",
            candidate_snippets=[],
            company_snippets=[],
            interviewer_snippets=[],
            supporting_metrics=[],
            excluded_topics=[],
            mode="full",
        ),
        plan_hash="plan-hash-reuse-completed-exact-warm",
        checkpoint_id="checkpoint-reuse-completed-exact-warm",
        question_key="question-key-reuse-completed-exact-warm",
    )
    manager._brain_warm_latest_result_v3 = LiveBrainWarmResult(
        checkpoint_id="brain-warm-success",
        plan_hash="plan-hash-reuse-completed-exact-warm",
        question_key="question-key-reuse-completed-exact-warm",
        question_text="Tell me a bit about yourself, if you would.",
        brain_plan=brain_plan,
        response={
            "full_response": "I'm a technology executive focused on data, AI, and modernization.",
            "bullets": ["I'm a technology executive focused on data, AI, and modernization."],
            "confidence": 0.9,
            "latency_ms": 24,
            "metadata": {"finalizer_fallback_kind": "llm"},
        },
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
        success=True,
    )
    manager._live_finalizer_v3.finalize = AsyncMock()

    response, path_used, _, quality_prewarm_wait_ms, _ = await manager._generate_live_response_from_snapshot_v3(
        snapshot=snapshot,
        interview_config=pipeline.session_state.interview_config,
    )

    assert path_used == "brain_prewarmed_exact"
    assert quality_prewarm_wait_ms == 0
    assert response["full_response"].startswith("I'm a technology executive")
    assert manager._live_last_warm_debug["warm_exact_match"] is True
    manager._live_finalizer_v3.finalize.assert_not_awaited()


@pytest.mark.asyncio
async def test_manager_v3_ignores_failed_brain_exact_warm_result_and_retries_finalize_from_plan():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()
    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-v3-ignore-failed-brain-warm",
        default_mode="real",
    )

    brain_plan = BrainPlan(
        session_id="session-v3-ignore-failed-brain-warm",
        utterance_id="u-ignore-failed-brain-warm",
        revision_id=7,
        snapshot_hash="hash-ignore-failed-brain-warm",
        ordered_asks=["tell me a bit about yourself, if you would."],
        resolved_question="tell me a bit about yourself, if you would.",
        question_completeness="complete",
        question_type="behavioral",
        response_shape="direct_short",
        answer_contract="business_with_outcomes",
        directness="direct",
        include_profile_opening=True,
        evidence_depth="medium",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="support_if_relevant",
        candidate_context_policy="required",
        ordered_coverage_required=True,
        target_length=140,
        draft_answer="At a high level, I'm a technology executive leading data and AI programs.",
        serve_mode="finalize_from_plan",
        confidence=0.82,
        stability_state="draft",
        plan_source="safe_fallback",
    )
    snapshot = LiveFrozenSnapshot(
        raw_turn_window=[{"speaker": "interviewer", "text": "Tell me a bit about yourself, if you would."}],
        turn_window=[{"speaker": "interviewer", "text": "Tell me a bit about yourself, if you would."}],
        raw_context_bundle={},
        signature="sig-ignore-failed-brain-warm",
        question_text=brain_plan.resolved_question,
        conversation_history=[{"speaker": "interviewer", "text": "Tell me a bit about yourself, if you would."}],
        prepared_context=None,
        request_payload={"question": brain_plan.resolved_question},
        question_source="brain_v4",
        cache_hit=False,
        brain_snapshot=BrainSnapshot(
            session_id="session-v3-ignore-failed-brain-warm",
            utterance_id="u-ignore-failed-brain-warm",
            revision_id=7,
            snapshot_text="Tell me a bit about yourself, if you would.",
            conversation_history=[{"speaker": "interviewer", "text": "Tell me a bit about yourself, if you would."}],
            snapshot_hash="hash-ignore-failed-brain-warm",
            timestamp=datetime.utcnow(),
        ),
        brain_plan=brain_plan,
        compact_evidence_pack=CompactEvidencePack(
            plan_hash="plan-hash-ignore-failed-brain-warm",
            candidate_snippets=[],
            company_snippets=[],
            interviewer_snippets=[],
            supporting_metrics=[],
            excluded_topics=[],
            mode="full",
        ),
        plan_hash="plan-hash-ignore-failed-brain-warm",
        checkpoint_id="checkpoint-ignore-failed-brain-warm",
        question_key="question-key-ignore-failed-brain-warm",
    )
    manager._brain_warm_latest_result_v3 = LiveBrainWarmResult(
        checkpoint_id="brain-warm-timeout",
        plan_hash="plan-hash-ignore-failed-brain-warm",
        question_key="question-key-ignore-failed-brain-warm",
        question_text="Tell me a bit about yourself, if you would.",
        brain_plan=brain_plan,
        response={
            "full_response": "I could not generate a reliable answer because the final answer stage timed out.",
            "bullets": ["I could not generate a reliable answer because the final answer stage timed out."],
            "confidence": 0.76,
            "latency_ms": 7500,
            "metadata": {
                "finalizer_fallback_kind": "explicit_failure",
                "emit_failure_kind": "timeout",
            },
        },
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
        success=False,
    )
    manager._live_finalizer_v3.finalize = AsyncMock(
        return_value={
            "full_response": (
                "I'm currently a Technology Director, Data and AI, and most of my recent work has been about "
                "leading AI-ready data platform and modernization programs with measurable outcomes."
            ),
            "bullets": ["I'm currently a Technology Director, Data and AI."],
            "confidence": 0.88,
            "latency_ms": 35,
            "metadata": {"finalizer_fallback_kind": "llm"},
        }
    )

    response, path_used, _, quality_prewarm_wait_ms, _ = await manager._generate_live_response_from_snapshot_v3(
        snapshot=snapshot,
        interview_config=pipeline.session_state.interview_config,
    )

    assert path_used == "brain_finalize_from_plan"
    assert quality_prewarm_wait_ms == 0
    assert response["full_response"].startswith("I'm currently a Technology Director")
    assert manager._live_finalizer_v3.finalize.await_args.kwargs["timeout_override_sec"] == manager._live_quality_final_emit_timeout_sec


@pytest.mark.asyncio
async def test_manager_v3_awaits_inflight_exact_warm_and_reuses_it_after_silence():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()
    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-v3-short-warm-grace",
        default_mode="real",
    )

    brain_plan = BrainPlan(
        session_id="session-v3-short-warm-grace",
        utterance_id="u-short-warm-grace",
        revision_id=3,
        snapshot_hash="hash-short-warm-grace",
        ordered_asks=["Tell me a bit about yourself."],
        resolved_question="Tell me a bit about yourself.",
        question_completeness="complete",
        response_shape="direct_short",
        directness="direct",
        include_profile_opening=True,
        evidence_depth="medium",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="support_if_relevant",
        candidate_context_policy="required",
        ordered_coverage_required=True,
        target_length=140,
        draft_answer="",
        serve_mode="finalize_from_plan",
        confidence=0.81,
        stability_state="draft",
        plan_source="safe_fallback",
    )
    snapshot = LiveFrozenSnapshot(
        raw_turn_window=[{"speaker": "interviewer", "text": "Tell me a bit about yourself."}],
        turn_window=[{"speaker": "interviewer", "text": "Tell me a bit about yourself."}],
        raw_context_bundle={},
        signature="sig-short-warm-grace",
        question_text=brain_plan.resolved_question,
        conversation_history=[{"speaker": "interviewer", "text": "Tell me a bit about yourself."}],
        prepared_context=None,
        request_payload={"question": brain_plan.resolved_question},
        question_source="brain_v4",
        cache_hit=False,
        brain_snapshot=BrainSnapshot(
            session_id="session-v3-short-warm-grace",
            utterance_id="u-short-warm-grace",
            revision_id=3,
            snapshot_text="Tell me a bit about yourself.",
            conversation_history=[{"speaker": "interviewer", "text": "Tell me a bit about yourself."}],
            snapshot_hash="hash-short-warm-grace",
            timestamp=datetime.utcnow(),
        ),
        brain_plan=brain_plan,
        compact_evidence_pack=CompactEvidencePack(
            plan_hash="plan-hash-short-warm-grace",
            candidate_snippets=[],
            company_snippets=[],
            interviewer_snippets=[],
            supporting_metrics=[],
            excluded_topics=[],
            mode="full",
        ),
        plan_hash="plan-hash-short-warm-grace",
        checkpoint_id="checkpoint-short-warm-grace",
        question_key="question-key-short-warm-grace",
    )
    snapshot = manager._normalize_live_v3_snapshot(snapshot)

    blocker = asyncio.create_task(asyncio.sleep(10))
    manager._brain_warm_inflight_task_v3 = blocker
    manager._brain_warm_inflight_checkpoint_v3 = MagicMock(
        checkpoint_id="warm-short-grace",
        plan_hash=snapshot.plan_hash,
        question_key="question-key-short-warm-grace",
    )

    async def _record_successful_warm(*args, **kwargs):
        manager._brain_warm_latest_result_v3 = LiveBrainWarmResult(
            checkpoint_id="warm-short-grace",
            plan_hash=snapshot.plan_hash,
            question_key="question-key-short-warm-grace",
            question_text=snapshot.question_text,
            brain_plan=snapshot.brain_plan,
            response={
                "full_response": "I'm a technology executive leading data and AI programs.",
                "bullets": ["I'm a technology executive leading data and AI programs."],
                "confidence": 0.9,
                "latency_ms": 20,
                "metadata": {"finalizer_fallback_kind": "llm"},
            },
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
            success=True,
        )
        blocker.cancel()
        manager._brain_warm_inflight_checkpoint_v3 = None

    manager._await_live_brain_warm_exact_result = AsyncMock(side_effect=_record_successful_warm)
    manager._live_finalizer_v3.finalize = AsyncMock()

    response, path_used, _, _, _ = await manager._generate_live_response_from_snapshot_v3(
        snapshot=snapshot,
        interview_config=pipeline.session_state.interview_config,
    )

    assert path_used == "brain_prewarmed_exact"
    assert response["full_response"].startswith("I'm a technology executive")
    manager._await_live_brain_warm_exact_result.assert_awaited_once()
    manager._live_finalizer_v3.finalize.assert_not_awaited()
    await asyncio.sleep(0)
    assert blocker.cancelled() is True


@pytest.mark.asyncio
async def test_manager_v3_ignores_failed_inflight_exact_warm_and_finalizes_from_plan():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()
    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-v3-ignore-failed-inflight-warm",
        default_mode="real",
    )

    brain_plan = BrainPlan(
        session_id="session-v3-ignore-failed-inflight-warm",
        utterance_id="u-ignore-failed-inflight-warm",
        revision_id=3,
        snapshot_hash="hash-ignore-failed-inflight-warm",
        ordered_asks=["Tell me a bit about yourself."],
        resolved_question="Tell me a bit about yourself.",
        question_completeness="complete",
        response_shape="direct_short",
        directness="direct",
        include_profile_opening=True,
        evidence_depth="medium",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="support_if_relevant",
        candidate_context_policy="required",
        ordered_coverage_required=True,
        target_length=140,
        draft_answer="",
        serve_mode="finalize_from_plan",
        confidence=0.81,
        stability_state="draft",
        plan_source="safe_fallback",
    )
    snapshot = LiveFrozenSnapshot(
        raw_turn_window=[{"speaker": "interviewer", "text": "Tell me a bit about yourself."}],
        turn_window=[{"speaker": "interviewer", "text": "Tell me a bit about yourself."}],
        raw_context_bundle={},
        signature="sig-ignore-failed-inflight-warm",
        question_text=brain_plan.resolved_question,
        conversation_history=[{"speaker": "interviewer", "text": "Tell me a bit about yourself."}],
        prepared_context=None,
        request_payload={"question": brain_plan.resolved_question},
        question_source="brain_v4",
        cache_hit=False,
        brain_snapshot=BrainSnapshot(
            session_id="session-v3-ignore-failed-inflight-warm",
            utterance_id="u-ignore-failed-inflight-warm",
            revision_id=3,
            snapshot_text="Tell me a bit about yourself.",
            conversation_history=[{"speaker": "interviewer", "text": "Tell me a bit about yourself."}],
            snapshot_hash="hash-ignore-failed-inflight-warm",
            timestamp=datetime.utcnow(),
        ),
        brain_plan=brain_plan,
        compact_evidence_pack=CompactEvidencePack(
            plan_hash="plan-hash-ignore-failed-inflight-warm",
            candidate_snippets=[],
            company_snippets=[],
            interviewer_snippets=[],
            supporting_metrics=[],
            excluded_topics=[],
            mode="full",
        ),
        plan_hash="plan-hash-ignore-failed-inflight-warm",
        checkpoint_id="checkpoint-ignore-failed-inflight-warm",
        question_key="question-key-ignore-failed-inflight-warm",
    )
    snapshot = manager._normalize_live_v3_snapshot(snapshot)

    blocker = asyncio.create_task(asyncio.sleep(10))
    manager._brain_warm_inflight_task_v3 = blocker
    manager._brain_warm_inflight_checkpoint_v3 = MagicMock(
        checkpoint_id="warm-ignore-failed-inflight",
        plan_hash=snapshot.plan_hash,
        question_key="question-key-ignore-failed-inflight-warm",
    )

    async def _record_failed_warm(*args, **kwargs):
        manager._brain_warm_latest_result_v3 = LiveBrainWarmResult(
            checkpoint_id="warm-ignore-failed-inflight",
            plan_hash=snapshot.plan_hash,
            question_key="question-key-ignore-failed-inflight-warm",
            question_text=snapshot.question_text,
            brain_plan=snapshot.brain_plan,
            response={
                "full_response": "I could not generate a reliable answer because the final answer stage timed out.",
                "bullets": ["I could not generate a reliable answer because the final answer stage timed out."],
                "confidence": 0.76,
                "latency_ms": 7500,
                "metadata": {
                    "finalizer_fallback_kind": "explicit_failure",
                    "emit_failure_kind": "timeout",
                },
            },
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
            success=False,
        )
        blocker.cancel()
        manager._brain_warm_inflight_checkpoint_v3 = None

    manager._await_live_brain_warm_exact_result = AsyncMock(side_effect=_record_failed_warm)
    manager._live_finalizer_v3.finalize = AsyncMock(
        return_value={
            "full_response": "I'm currently a Technology Director focused on data and AI transformation.",
            "bullets": ["I'm currently a Technology Director focused on data and AI transformation."],
            "confidence": 0.89,
            "latency_ms": 22,
            "metadata": {"finalizer_fallback_kind": "llm"},
        }
    )

    response, path_used, _, _, _ = await manager._generate_live_response_from_snapshot_v3(
        snapshot=snapshot,
        interview_config=pipeline.session_state.interview_config,
    )

    assert path_used == "brain_finalize_from_plan"
    assert response["full_response"].startswith("I'm currently a Technology Director")
    manager._await_live_brain_warm_exact_result.assert_awaited_once()
    manager._live_finalizer_v3.finalize.assert_awaited_once()
    await asyncio.sleep(0)
    assert blocker.cancelled() is True


@pytest.mark.asyncio
async def test_manager_v3_discards_compatible_seed_and_rewarms_exact_plan():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()
    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-v3-no-compatible-seed",
        default_mode="real",
    )

    blocker = asyncio.create_task(asyncio.sleep(10))
    manager._brain_warm_inflight_task_v3 = blocker
    manager._brain_warm_inflight_checkpoint_v3 = MagicMock(
        checkpoint_id="ck-old",
        plan_hash="plan-hash-old",
        question_key="question-key-old",
        brain_plan=BrainPlan(
            ordered_asks=["Tell me about your experience in building from 0, building from scratch."],
            resolved_question="Tell me about your experience in building from 0, building from scratch.",
            question_completeness="complete",
            response_shape="direct_short",
            directness="direct",
            include_profile_opening=False,
            evidence_depth="light",
            metrics_policy="avoid_unless_helpful",
            company_context_policy="support_if_relevant",
            candidate_context_policy="required",
            ordered_coverage_required=True,
            target_length=100,
            plan_source="safe_fallback",
        ),
    )
    manager._live_finalizer_v3.finalize = AsyncMock(
        return_value={
            "full_response": "I founded the Generative AI practice in Colombia and later led multi-region delivery teams.",
            "bullets": ["I founded the Generative AI practice in Colombia."],
            "confidence": 0.82,
            "latency_ms": 18,
            "metadata": {"finalizer_fallback_kind": "llm"},
        }
    )

    brain_snapshot = BrainSnapshot(
        session_id="session-v3-no-compatible-seed",
        utterance_id="u-no-compatible-seed",
        revision_id=6,
        snapshot_text=(
            "Tell me about your experience in building from 0, building from scratch. "
            "Also cover your team management experience."
        ),
        conversation_history=[
            {
                "speaker": "interviewer",
                "text": (
                    "Tell me about your experience in building from 0, building from scratch. "
                    "Also cover your team management experience."
                ),
            }
        ],
        snapshot_hash="hash-no-compatible-seed",
        timestamp=datetime.utcnow(),
    )
    brain_plan = BrainPlan(
        session_id="session-v3-no-compatible-seed",
        utterance_id="u-no-compatible-seed",
        revision_id=6,
        snapshot_hash="hash-no-compatible-seed",
        ordered_asks=[
            "Tell me about your experience in building from 0, building from scratch.",
            "Tell me about your team management experience.",
        ],
        resolved_question=(
            "Answer these interviewer asks in order:\n"
            "1. Tell me about your experience in building from 0, building from scratch.\n"
            "2. Tell me about your team management experience."
        ),
        question_completeness="complete",
        response_shape="direct_structured",
        directness="balanced",
        include_profile_opening=False,
        evidence_depth="medium",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="support_if_relevant",
        candidate_context_policy="required",
        ordered_coverage_required=True,
        target_length=180,
        draft_answer="A generic seeded answer that should never be reused.",
        serve_mode="finalize_from_plan",
        confidence=0.54,
        plan_source="safe_fallback",
    )
    evidence_pack = CompactEvidencePack(
        plan_hash="plan-hash-no-compatible-seed",
        candidate_snippets=["Founded the Generative AI practice in Colombia."],
        company_snippets=[],
        interviewer_snippets=[],
        supporting_metrics=[],
        excluded_topics=[],
        mode="full",
    )

    manager._schedule_live_brain_warm_from_plan(
        brain_snapshot=brain_snapshot,
        brain_plan=brain_plan,
        evidence_pack=evidence_pack,
        interview_config=pipeline.session_state.interview_config,
    )

    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert blocker.cancelled() is False
    assert manager._brain_warm_latest_result_v3 is None
    manager._live_finalizer_v3.finalize.assert_not_awaited()


@pytest.mark.asyncio
async def test_manager_v3_reuses_cached_stable_plan_when_latest_plan_is_partial():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()
    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-v3-cached-stable",
        default_mode="real",
    )

    stable_plan = BrainPlan(
        session_id="session-v3-cached-stable",
        utterance_id="u-10",
        revision_id=3,
        snapshot_hash="hash-old",
        ordered_asks=["What are you looking for in terms of the company, the culture, teams?"],
        raw_detected_asks=["What are you looking for in terms of the company, the culture, teams?"],
        resolved_question="What are you looking for in terms of the company, the culture, teams?",
        question_completeness="complete",
        response_shape="direct_short",
        directness="direct",
        include_profile_opening=False,
        evidence_depth="light",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="support_if_relevant",
        candidate_context_policy="support_if_relevant",
        ordered_coverage_required=False,
        target_length=110,
        draft_answer="I’m looking for a team with strong execution, collaboration, and low bureaucracy.",
        serve_mode="direct_brain",
        confidence=0.9,
        stability_state="stable",
        plan_source="llm_fast",
    )
    manager._latest_stable_brain_plan_v3 = stable_plan
    manager._latest_stable_brain_recovery_draft_v3 = stable_plan.draft_answer
    manager._live_brain_service_v3.plan = AsyncMock(
        return_value=BrainPlan(
            session_id="session-v3-cached-stable",
            utterance_id="u-11",
            revision_id=3,
            snapshot_hash="hash-new",
            ordered_asks=[],
            raw_detected_asks=[
                "What are you looking for in terms of the company, the culture, teams?",
                "What's important for you, or what kind of things you absolutely",
            ],
            resolved_question="What's important for you, or what kind of things you absolutely",
            question_completeness="partial",
            response_shape="direct_short",
            directness="direct",
            include_profile_opening=False,
            evidence_depth="light",
            metrics_policy="avoid_unless_helpful",
            company_context_policy="avoid",
            candidate_context_policy="avoid",
            ordered_coverage_required=False,
            target_length=100,
            draft_answer="",
            serve_mode="finalize_from_plan",
            confidence=0.2,
            stability_state="draft",
            plan_source="safe_fallback",
        )
    )

    brain_snapshot = BrainSnapshot(
        session_id="session-v3-cached-stable",
        utterance_id="u-11",
        revision_id=3,
        snapshot_text=(
            "What are you looking for in terms of the company, the culture, teams?\n"
            "What's important for you, or what kind of things you absolutely"
        ),
        conversation_history=[
            {"speaker": "interviewer", "text": "What are you looking for in terms of the company, the culture, teams?"},
            {"speaker": "interviewer", "text": "What's important for you, or what kind of things you absolutely"},
        ],
        snapshot_hash="hash-new",
        timestamp=datetime.utcnow(),
    )

    plan, evidence_pack = await manager._compute_live_brain_plan_v3(
        brain_snapshot=brain_snapshot,
        interview_config=pipeline.session_state.interview_config,
        force_stable=True,
    )

    assert plan.plan_source == "cached_stable"
    assert plan.ordered_asks == stable_plan.ordered_asks
    assert plan.serve_mode == "finalize_from_plan"
    assert evidence_pack.mode == "minimal"
    assert manager._latest_brain_recovery_draft_v3 == stable_plan.draft_answer


@pytest.mark.asyncio
async def test_manager_v3_does_not_reuse_cached_stable_plan_across_revision_boundary():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()
    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-v3-cached-stable-boundary",
        default_mode="real",
    )

    stable_plan = BrainPlan(
        session_id="session-v3-cached-stable-boundary",
        utterance_id="u-15",
        revision_id=2,
        snapshot_hash="hash-old-boundary",
        ordered_asks=["What are you looking for in terms of the company, the culture, teams?"],
        raw_detected_asks=["What are you looking for in terms of the company, the culture, teams?"],
        resolved_question="What are you looking for in terms of the company, the culture, teams?",
        question_completeness="complete",
        response_shape="direct_short",
        directness="direct",
        include_profile_opening=False,
        evidence_depth="light",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="support_if_relevant",
        candidate_context_policy="support_if_relevant",
        ordered_coverage_required=False,
        target_length=110,
        draft_answer="I’m looking for a team with strong execution, collaboration, and low bureaucracy.",
        serve_mode="direct_brain",
        confidence=0.9,
        stability_state="stable",
        plan_source="llm_fast",
    )
    manager._latest_stable_brain_plan_v3 = stable_plan
    manager._latest_stable_brain_recovery_draft_v3 = stable_plan.draft_answer
    manager._live_brain_service_v3.plan = AsyncMock(
        return_value=BrainPlan(
            session_id="session-v3-cached-stable-boundary",
            utterance_id="u-16",
            revision_id=3,
            snapshot_hash="hash-new-boundary",
            ordered_asks=[],
            raw_detected_asks=[
                "What are you looking for in terms of the company, the culture, teams?",
                "What's important for you, or what kind of things you absolutely",
            ],
            resolved_question="What's important for you, or what kind of things you absolutely",
            question_completeness="partial",
            response_shape="direct_short",
            directness="direct",
            include_profile_opening=False,
            evidence_depth="light",
            metrics_policy="avoid_unless_helpful",
            company_context_policy="avoid",
            candidate_context_policy="avoid",
            ordered_coverage_required=False,
            target_length=100,
            draft_answer="",
            serve_mode="finalize_from_plan",
            confidence=0.2,
            stability_state="draft",
            plan_source="safe_fallback",
        )
    )

    brain_snapshot = BrainSnapshot(
        session_id="session-v3-cached-stable-boundary",
        utterance_id="u-16",
        revision_id=3,
        snapshot_text=(
            "What are you looking for in terms of the company, the culture, teams?\n"
            "What's important for you, or what kind of things you absolutely"
        ),
        conversation_history=[
            {"speaker": "interviewer", "text": "What are you looking for in terms of the company, the culture, teams?"},
            {"speaker": "interviewer", "text": "What's important for you, or what kind of things you absolutely"},
        ],
        snapshot_hash="hash-new-boundary",
        timestamp=datetime.utcnow(),
    )

    plan, evidence_pack = await manager._compute_live_brain_plan_v3(
        brain_snapshot=brain_snapshot,
        interview_config=pipeline.session_state.interview_config,
        force_stable=True,
    )

    assert plan.plan_source == "safe_fallback"
    assert plan.ordered_asks == []
    assert evidence_pack.mode == "minimal"
    assert manager._latest_brain_recovery_draft_v3 == ""


@pytest.mark.asyncio
async def test_manager_v3_reuses_cached_stable_plan_when_latest_fallback_is_complete_but_compatible():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()
    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-v3-cached-stable-complete",
        default_mode="real",
    )

    stable_plan = BrainPlan(
        session_id="session-v3-cached-stable-complete",
        utterance_id="u-20",
        revision_id=5,
        snapshot_hash="hash-stable",
        ordered_asks=[
            "What are you looking for in terms of the company, the culture, teams?",
            "What's important for you, or what kind of things you absolutely don't like?",
        ],
        raw_detected_asks=[
            "What are you looking for in terms of the company, the culture, teams?",
            "What's important for you, or what kind of things you absolutely don't like?",
        ],
        resolved_question=(
            "Answer these interviewer asks in order:\n"
            "1. What are you looking for in terms of the company, the culture, teams?\n"
            "2. What's important for you, or what kind of things you absolutely don't like?"
        ),
        question_completeness="complete",
        question_type="behavioral",
        response_shape="direct_structured",
        tone="professional",
        directness="balanced",
        include_profile_opening=False,
        evidence_depth="medium",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="support_if_relevant",
        candidate_context_policy="required",
        ordered_coverage_required=True,
        target_length=180,
        draft_answer=(
            "I look for a company with strong execution, a collaborative culture, and teams with clear ownership. "
            "What matters most to me is clarity on priorities and low bureaucracy, and I tend to avoid environments "
            "where expectations are unclear or decisions move too slowly."
        ),
        serve_mode="direct_brain",
        confidence=0.93,
        stability_state="stable",
        plan_source="llm_fast",
    )
    manager._latest_stable_brain_plan_v3 = stable_plan
    manager._latest_stable_brain_recovery_draft_v3 = stable_plan.draft_answer
    manager._live_brain_service_v3.plan = AsyncMock(
        return_value=BrainPlan(
            session_id="session-v3-cached-stable-complete",
            utterance_id="u-21",
            revision_id=5,
            snapshot_hash="hash-fallback",
            ordered_asks=[
                "What are you looking for in terms of the company, the culture, teams?"
            ],
            raw_detected_asks=[
                "What are you looking for in terms of the company, the culture, teams?",
                "What's important for you, or what kind of things you absolutely don't like?",
            ],
            resolved_question="What are you looking for in terms of the company, the culture, teams?",
            question_completeness="complete",
            question_type="behavioral",
            response_shape="direct_structured",
            tone="professional",
            directness="balanced",
            include_profile_opening=False,
            evidence_depth="light",
            metrics_policy="avoid_unless_helpful",
            company_context_policy="support_if_relevant",
            candidate_context_policy="support_if_relevant",
            ordered_coverage_required=True,
            target_length=150,
            draft_answer="",
            serve_mode="finalize_from_plan",
            confidence=0.48,
            stability_state="draft",
            plan_source="safe_fallback",
        )
    )

    brain_snapshot = BrainSnapshot(
        session_id="session-v3-cached-stable-complete",
        utterance_id="u-21",
        revision_id=5,
        snapshot_text=(
            "What are you looking for in terms of the company, the culture, teams? "
            "What's important for you, or what kind of things you absolutely don't like?"
        ),
        conversation_history=[
            {
                "speaker": "interviewer",
                "text": (
                    "What are you looking for in terms of the company, the culture, teams? "
                    "What's important for you, or what kind of things you absolutely don't like?"
                ),
            }
        ],
        snapshot_hash="hash-fallback",
        timestamp=datetime.utcnow(),
    )

    plan, evidence_pack = await manager._compute_live_brain_plan_v3(
        brain_snapshot=brain_snapshot,
        interview_config=pipeline.session_state.interview_config,
        force_stable=True,
    )

    assert plan.plan_source == "cached_stable"
    assert plan.ordered_asks == stable_plan.ordered_asks
    assert plan.serve_mode == "finalize_from_plan"
    assert evidence_pack.mode == "full"
    assert manager._latest_brain_recovery_draft_v3 == stable_plan.draft_answer


def test_live_brain_service_structured_llm_draft_uses_finalize_from_draft():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-structured",
        utterance_id="u-structured",
        revision_id=1,
        snapshot_text="What matters to you in a company, culture, and team, and what do you avoid?",
        conversation_history=[
            {
                "speaker": "interviewer",
                "text": "What matters to you in a company, culture, and team, and what do you avoid?",
            }
        ],
        snapshot_hash="hash-structured",
        timestamp=datetime.utcnow(),
    )

    plan = service._normalize_llm_plan(
        snapshot=snapshot,
        payload={
            "asks": [
                "What matters to you in a company, culture, and team?",
                "What do you avoid?",
            ],
            "coverage_points": ["company", "culture", "team"],
            "question_type": "behavioral",
            "response_shape": "direct_structured",
            "tone": "professional",
            "use_candidate_context": True,
            "use_company_context": False,
            "use_metrics": False,
            "target_length": 170,
            "draft_answer": (
                "What matters most to me is clarity, strong execution, and teams with ownership. "
                "I also tend to avoid environments with unnecessary bureaucracy or unclear expectations."
            ),
            "confidence": 0.94,
            "is_complete": True,
        },
    )

    assert plan.serve_mode == "finalize_from_draft"
