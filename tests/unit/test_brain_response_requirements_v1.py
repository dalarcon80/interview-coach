from datetime import datetime

from contracts.models import AskIntent, BrainPlan, InterviewerNeed, ResponseRequirement
from pipeline.steps.live_brain_service import LiveBrainService
from pipeline.steps.live_evidence_packer import LiveEvidencePacker
from pipeline.steps.live_finalizer import LiveFinalizer
from contracts.models import BrainSnapshot, CompactEvidencePack


def _interview_config() -> dict:
    return {
        "style_id": "detailed",
        "language": "en",
        "candidate": {
            "currentRole": "Technology Director, Data & AI",
            "summary": (
                "Technology executive with 20 years leading enterprise transformation across software modernization "
                "and the full data lifecycle."
            ),
            "achievements": [
                "Built and scaled a subscription operating model for modernization and data programs.",
                "Led core banking modernization across 6+ enterprise accounts and 100+ applications, delivering up to 40% OPEX reduction within 12 months.",
                "Founded the Generative AI practice in Colombia and developed 7 reusable assets.",
            ],
            "skills": ["AWS", "Data platforms", "Architecture", "Technical leadership"],
        },
        "company": {
            "roleTitle": "Director - Data Architecture & Engineering",
            "companySummary": "Consulting and technology firm building AI-ready data platforms.",
            "roleResponsibilities": [
                "Lead solution design and technical delivery for complex data engineering and architecture projects across AWS.",
                "Guide teams in defining scalable future-state data architectures.",
            ],
        },
        "interviewer": {
            "likelyFocusAreas": ["Data platform architecture", "AWS leadership", "LLM use cases"],
        },
    }


def _runtime_key_interview_config() -> dict:
    base = _interview_config()
    return {
        "style_id": base["style_id"],
        "language": base["language"],
        "candidate_profile": base["candidate"],
        "company_info": base["company"],
        "interviewer_profile": base["interviewer"],
    }


def test_live_brain_safe_plan_builds_profile_requirement_from_prior_technical_context():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-profile-alignment",
        utterance_id="u-profile-alignment",
        revision_id=1,
        snapshot_text=(
            "We need to prepare data into different storage patterns like graphs, knowledge bases, and vectors so LLMs can use it well. "
            "We're looking for someone with that background, AWS infrastructure knowledge, and the ability to lead teams on how to design for those AI use cases. "
            "So tell me a bit about yourself, if you would."
        ),
        conversation_history=[
            {"speaker": "interviewer", "text": "We need to prepare data into different storage patterns like graphs, knowledge bases, and vectors so LLMs can use it well."},
            {"speaker": "interviewer", "text": "We're looking for someone with that background, AWS infrastructure knowledge, and the ability to lead teams on how to design for those AI use cases."},
            {"speaker": "interviewer", "text": "So tell me a bit about yourself, if you would."},
        ],
        snapshot_hash="hash-profile-alignment",
        timestamp=datetime.utcnow(),
    )

    plan = service._plan_safely(snapshot=snapshot, interview_config=_interview_config())

    assert plan.ordered_asks == ["tell me a bit about yourself, if you would."]
    assert plan.literal_question == "tell me a bit about yourself, if you would."
    assert "llm" in plan.contextualized_question.lower() or "ai-ready" in plan.contextualized_question.lower()
    assert "most relevant to the interviewer problem" in plan.contextualized_question.lower()
    assert plan.response_shape == "direct_structured"
    assert plan.target_length >= 170
    assert plan.response_requirement.answer_mode == "profile_alignment"
    assert plan.response_requirement.profile_evidence_mode == "one_best_proof"
    assert plan.response_requirement.prior_context_mode == "evaluation_scope"
    assert any("AWS infrastructure" in item or "LLM" in item or "AI use cases" in item for item in plan.context_focus)
    assert "lead the problem just described" in plan.interviewer_need.summary.lower()
    assert any(
        "ai-ready data foundations" in item.lower() or "cloud and data platform architecture leadership" in item.lower()
        for item in plan.interviewer_need.dimensions
    )
    assert not any("what i'm really looking for" in item.lower() for item in plan.interviewer_need.dimensions)
    assert any("answer the introduction directly" in item.lower() for item in plan.response_requirement.required_moves)
    assert any("one concrete proof" in item.lower() for item in plan.response_requirement.required_moves)
    assert any("clarifies the problem" in item.lower() for item in plan.response_requirement.required_moves)
    assert any(
        "generic biography" in item.lower()
        or "professional introduction" in item.lower()
        for item in plan.response_requirement.required_moves
    )
    assert "role_evidence" in plan.response_requirement.evidence_priority
    assert "leadership_evidence" not in plan.response_requirement.evidence_priority
    assert "technical_alignment_evidence" in plan.response_requirement.evidence_priority
    assert any(
        "ai-ready data foundations" in item.lower() or "cloud and data platform architecture leadership" in item.lower()
        for item in plan.response_requirement.context_to_weave
    )
    assert not any("give a concise profile answer" in item.lower() for item in plan.response_requirement.must_cover)
    lowered_contextualized = plan.contextualized_question.lower()
    assert "introduce yourself professionally" in lowered_contextualized
    assert "most relevant to the interviewer problem" in lowered_contextualized
    assert "foregrounding" not in lowered_contextualized
    assert "open with a complete spoken sentence" not in lowered_contextualized
    assert "built and scaled a subscription operating model" in plan.response_requirement.must_cover[0].lower()
    assert "technology director, data & ai" not in " ".join(plan.response_requirement.must_cover).lower()
    assert "built and scaled a subscription operating model" not in " ".join(plan.response_requirement.context_to_weave).lower()
    lowered_draft = plan.draft_answer.lower()
    assert "built and scaled a subscription operating model" in lowered_draft or "founded the generative ai practice" in lowered_draft
    assert "guiding the teams building" in lowered_draft or "shaping ai-ready data platforms" in lowered_draft
    first_sentence = lowered_draft.split(".", 1)[0]
    assert "currently serving as technology director" in first_sentence or "technology executive" in first_sentence


def test_live_brain_preference_contract_keeps_direct_preferences_out_of_profile_evidence():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-preference-grounded",
        utterance_id="u-preference-grounded",
        revision_id=1,
        snapshot_text=(
            "What are you looking for in terms of the company, the culture, teams? "
            "What's important for you, or what kind of things you absolutely like."
        ),
        conversation_history=[
            {"speaker": "interviewer", "text": "What are you looking for in terms of the company, the culture, teams?"},
            {"speaker": "interviewer", "text": "What's important for you, or what kind of things you absolutely like."},
        ],
        snapshot_hash="hash-preference-grounded",
        timestamp=datetime.utcnow(),
    )

    plan = service._plan_safely(snapshot=snapshot, interview_config=_interview_config())

    assert plan.response_family == "culture_preferences"
    assert plan.response_requirement.answer_mode == "preferences"
    assert plan.response_requirement.profile_evidence_mode == "none"
    assert plan.response_requirement.company_evidence_mode == "preference_alignment"
    assert "company_snippets" in plan.response_requirement.evidence_priority
    assert "culture_alignment_evidence" in plan.response_requirement.evidence_priority
    assert "operating_style_evidence" not in plan.response_requirement.evidence_priority
    assert not any("ground the preference" in item.lower() for item in plan.response_requirement.required_moves)
    assert not any("preference anchor" in item.lower() for item in plan.response_requirement.must_cover)
    assert "company preferences" in plan.response_requirement.must_cover
    assert "culture preferences" in plan.response_requirement.must_cover
    assert "team preferences" in plan.response_requirement.must_cover
    lowered_contextualized = plan.contextualized_question.lower()
    assert "what you want in the company" in lowered_contextualized
    assert "what you value in the culture" in lowered_contextualized
    assert "how you want the team to operate" in lowered_contextualized
    assert "preference areas most relevant" not in lowered_contextualized
    assert "what i tend to avoid" not in plan.draft_answer.lower()


def test_live_brain_preference_contextualized_question_does_not_weave_noisy_prior_preamble():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-preference-clean-context",
        utterance_id="u-preference-clean-context",
        revision_id=1,
        snapshot_text=(
            "The We already talked about, like, your expectations in terms of the role. "
            "And or not the role, but, yeah, but basically what you have done in your experience. "
            "So now I just wanted to ask you, like, what are you looking for in terms of "
            "the company, the culture, teams? What's important for you, or what kind of things you absolutely don't like."
        ),
        conversation_history=[
            {
                "speaker": "interviewer",
                "text": (
                    "The We already talked about, like, your expectations in terms of the role. "
                    "And or not the role, but, yeah, but basically what you have done in your experience."
                ),
            },
            {
                "speaker": "interviewer",
                "text": (
                    "So now I just wanted to ask you, like, what are you looking for in terms of "
                    "the company, the culture, teams? What's important for you, or what kind of things you absolutely don't like."
                ),
            },
        ],
        snapshot_hash="hash-preference-clean-context",
        timestamp=datetime.utcnow(),
    )

    plan = service._plan_safely(snapshot=snapshot, interview_config=_interview_config())

    lowered_contextualized = plan.contextualized_question.lower()
    assert "what you want in the company" in lowered_contextualized
    assert "what you value in the culture" in lowered_contextualized
    assert "how you want the team to operate" in lowered_contextualized
    assert "what you want to avoid" in lowered_contextualized
    assert "we already talked" not in lowered_contextualized
    assert "expectations in terms of the role" not in lowered_contextualized
    purposes = [segment.get("purpose") for segment in plan.answer_blueprint]
    assert "preferences_company" in purposes
    assert "preferences_culture" in purposes
    assert "preferences_team" in purposes
    assert "preferences_boundaries" in purposes
    blueprint_by_purpose = {segment.get("purpose"): segment for segment in plan.answer_blueprint}
    assert blueprint_by_purpose["preferences_company"]["preferred_evidence_types"] == [
        "company_snippets",
        "culture_alignment_evidence",
    ]
    assert blueprint_by_purpose["preferences_culture"]["preferred_evidence_types"] == [
        "company_snippets",
        "culture_alignment_evidence",
    ]
    assert blueprint_by_purpose["preferences_team"]["preferred_evidence_types"] == [
        "company_snippets",
        "culture_alignment_evidence",
    ]
    assert blueprint_by_purpose["preferences_boundaries"]["preferred_evidence_types"] == [
        "culture_alignment_evidence",
    ]


def test_live_brain_recovers_interviewer_self_repair_for_globant_follow_up():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-globant-followup",
        utterance_id="u-globant-followup",
        revision_id=1,
        snapshot_text=(
            "Operation on and execution. Yeah. That is my my current role. Matthew. I don't know if you\n"
            "wanna know. Yeah. But, yeah Tell me a little. Me a little bit more about Globant."
        ),
        conversation_history=[
            {
                "speaker": "interviewer",
                "text": "Operation on and execution. Yeah. That is my my current role. Matthew. I don't know if you",
            },
            {
                "speaker": "interviewer",
                "text": "wanna know. Yeah. But, yeah Tell me a little. Me a little bit more about Globant.",
            },
        ],
        snapshot_hash="hash-globant-followup",
        timestamp=datetime.utcnow(),
    )

    plan = service._plan_safely(snapshot=snapshot, interview_config=_interview_config())

    assert plan.ordered_asks == ["Tell me a little bit more about Globant."]
    assert plan.resolved_question == "Tell me a little bit more about Globant."
    assert plan.literal_question == "Tell me a little bit more about Globant."
    assert plan.question_completeness == "complete"
    assert "tell me a little." not in plan.contextualized_question.lower()


def test_live_brain_recovers_follow_up_question_after_short_preamble():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-projects-followup",
        utterance_id="u-projects-followup",
        revision_id=1,
        snapshot_text="Okay. So does that mean that you work on on projects yourself?",
        conversation_history=[
            {
                "speaker": "interviewer",
                "text": "Okay. So does that mean that you work on on projects yourself?",
            }
        ],
        snapshot_hash="hash-projects-followup",
        timestamp=datetime.utcnow(),
    )

    plan = service._plan_safely(snapshot=snapshot, interview_config=_interview_config())

    assert plan.ordered_asks == ["does that mean that you work on on projects yourself?"]
    assert plan.resolved_question == "does that mean that you work on on projects yourself?"
    assert plan.question_completeness == "complete"
    assert "latest actionable interviewer question was not captured clearly enough" not in plan.contextualized_question.lower()


def test_live_brain_normalizes_active_question_block_for_type_of_position_experience_ask():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-type-of-position",
        utterance_id="u-type-of-position",
        revision_id=1,
        snapshot_text=(
            "Maybe you can summarize the the type of of position that you've that you've had?"
        ),
        active_question_text=(
            "Maybe you can summarize the the type of of position that you've that you've had?"
        ),
        active_turns=[
            {
                "speaker": "interviewer",
                "text": "Maybe you can summarize the the type of of position that you've that you've had?",
            }
        ],
        historical_turns=[
            {
                "speaker": "interviewer",
                "text": "Latin American side of the business, Colombia. And Mexico, I guess.",
            },
            {
                "speaker": "interviewer",
                "text": "I just wanted to talk a little bit about your experience with data, data strategy, and business intelligence.",
            },
        ],
        conversation_history=[
            {
                "speaker": "interviewer",
                "text": "Latin American side of the business, Colombia. And Mexico, I guess.",
            },
            {
                "speaker": "interviewer",
                "text": "I just wanted to talk a little bit about your experience with data, data strategy, and business intelligence.",
            },
            {
                "speaker": "interviewer",
                "text": "Maybe you can summarize the the type of of position that you've that you've had?",
            },
        ],
        primary_question_source="active_turns",
        active_ask_key="maybe you can summarize the the type of of position that you've that you've had",
        snapshot_hash="hash-type-of-position",
        timestamp=datetime.utcnow(),
    )

    plan = service._normalize_llm_plan(
        snapshot=snapshot,
        payload={
            "asks": ["how it is and i guess"],
            "resolved_question": "how it is and i guess",
            "question_completeness": "complete",
            "question_type": "mixed",
            "response_shape": "direct_structured",
            "answer_contract": "business_with_outcomes",
            "confidence": 0.76,
        },
        interview_config=_interview_config(),
    )

    assert plan.ordered_asks == ["Maybe you can summarize the the type of of position that you've that you've had?"]
    assert plan.literal_question == "Maybe you can summarize the the type of of position that you've that you've had?"
    assert plan.resolved_question == "Maybe you can summarize the the type of of position that you've that you've had?"
    assert "how it is" not in " ".join(plan.raw_detected_asks).lower()
    assert any("data strategy" in item.lower() for item in plan.supporting_interviewer_context)
    assert plan.question_completeness == "complete"
    assert plan.response_requirement.answer_mode == "experience_with_outcomes"


def test_live_brain_keeps_clarification_statement_intact_instead_of_relative_clause_fragment():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-delivery-clarification",
        utterance_id="u-delivery-clarification",
        revision_id=1,
        snapshot_text=(
            "Okay. So it sounds like your position is more of a of a manager overseeing teams who do delivery.\n"
            "of a of a manager overseeing teams who do delivery."
        ),
        conversation_history=[
            {
                "speaker": "interviewer",
                "text": "Okay. So it sounds like your position is more of a of a manager overseeing teams who do delivery.",
            },
            {
                "speaker": "interviewer",
                "text": "of a of a manager overseeing teams who do delivery.",
            },
        ],
        snapshot_hash="hash-delivery-clarification",
        timestamp=datetime.utcnow(),
    )

    plan = service._plan_safely(snapshot=snapshot, interview_config=_interview_config())

    assert plan.ordered_asks == [
        "So it sounds like your position is more of a of a manager overseeing teams who do delivery."
    ]
    assert plan.resolved_question == "So it sounds like your position is more of a of a manager overseeing teams who do delivery."
    assert plan.literal_question == "So it sounds like your position is more of a of a manager overseeing teams who do delivery."
    assert plan.question_completeness == "complete"
    assert "who do delivery." not in plan.contextualized_question.lower()


def test_live_brain_safe_plan_normalizes_runtime_metadata_keys_for_safe_fallback():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-profile-runtime-keys",
        utterance_id="u-profile-runtime-keys",
        revision_id=1,
        snapshot_text=(
            "We need to prepare data into different storage patterns like graphs, knowledge bases, and vectors so LLMs can use it well. "
            "We're looking for someone with that background, AWS infrastructure knowledge, and the ability to lead teams on how to design for those AI use cases. "
            "So tell me a bit about yourself, if you would."
        ),
        conversation_history=[
            {"speaker": "interviewer", "text": "We need to prepare data into different storage patterns like graphs, knowledge bases, and vectors so LLMs can use it well."},
            {"speaker": "interviewer", "text": "We're looking for someone with that background, AWS infrastructure knowledge, and the ability to lead teams on how to design for those AI use cases."},
            {"speaker": "interviewer", "text": "So tell me a bit about yourself, if you would."},
        ],
        snapshot_hash="hash-profile-runtime-keys",
        timestamp=datetime.utcnow(),
    )

    plan = service._plan_safely(snapshot=snapshot, interview_config=_runtime_key_interview_config())

    assert plan.draft_answer
    lowered_draft = plan.draft_answer.lower()
    assert "built and scaled a subscription operating model" in lowered_draft or "founded the generative ai practice" in lowered_draft
    assert "guiding the teams building" in lowered_draft or "shaping ai-ready data platforms" in lowered_draft
    assert "ai-ready data foundations" in plan.contextualized_question.lower() or "llm" in plan.contextualized_question.lower()


def test_live_brain_normalizes_llm_requirement_contract_and_derives_compatibility_fields():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-llm-requirement",
        utterance_id="u-llm-requirement",
        revision_id=1,
        snapshot_text="Tell me a bit about yourself, if you would.",
        conversation_history=[{"speaker": "interviewer", "text": "Tell me a bit about yourself, if you would."}],
        snapshot_hash="hash-llm-requirement",
        timestamp=datetime.utcnow(),
    )

    plan = service._normalize_llm_plan(
        snapshot=snapshot,
        payload={
            "literal_question": "Tell me a bit about yourself, if you would.",
            "contextualized_question": (
                "Introduce yourself by emphasizing the parts of your background that prove you can lead "
                "AWS/data platform architecture, guide teams, and design for LLM use cases."
            ),
            "asks": ["Tell me a bit about yourself, if you would."],
            "resolved_question": "Tell me a bit about yourself, if you would.",
            "question_completeness": "complete",
            "question_type": "behavioral",
            "response_shape": "direct_structured",
            "answer_contract": "business_with_outcomes",
            "context_focus": [
                "Prior interviewer context emphasizes AWS data platform leadership for LLM use cases.",
            ],
            "ask_intents": [
                {
                    "ask_text": "Tell me a bit about yourself, if you would.",
                    "ask_intent": "profile_positioning",
                    "response_goal": "Position the profile around the most relevant role, what was led, and the outcomes.",
                    "required_evidence_types": ["role_evidence", "build_evidence", "technical_alignment_evidence"],
                    "expected_answer_shape": "direct_structured",
                    "needs_context_from_prior_turns": True,
                }
            ],
            "interviewer_need": {
                "summary": "The interviewer wants a profile answer aligned to prior AWS/data platform/LLM context, not a generic biography.",
                "dimensions": ["AWS/data platform leadership", "LLM-ready architecture", "Team leadership"],
                "evidence_expected": ["role_evidence", "build_evidence", "technical_alignment_evidence"],
            },
            "response_requirement": {
                "answer_mode": "profile_alignment",
                "response_order": ["Tell me a bit about yourself, if you would."],
                "required_moves": [
                    "Open with the current role and relevant domain responsibility.",
                    "Explain what has been built, led, or designed that matches the prior interviewer context.",
                    "Include one or two concrete outcomes that show credibility.",
                ],
                "context_to_weave": ["AWS/data platform leadership for LLM use cases"],
                "evidence_priority": ["role_evidence", "build_evidence", "technical_alignment_evidence"],
                "must_cover": ["current role", "relevant work", "outcomes"],
                "avoid": ["generic_biography", "unsupported_fit_closure"],
                "paragraph_plan": ["Paragraph 1: role and relevant scope", "Paragraph 2: concrete outcomes and alignment"],
                "style_constraints": ["spoken", "no bullets", "short paragraphs"],
            },
            "confidence": 0.86,
        },
    )

    assert plan.response_requirement.answer_mode == "profile_alignment"
    assert plan.literal_question == "Tell me a bit about yourself, if you would."
    assert "aws/data platform architecture" in plan.contextualized_question.lower()
    assert plan.response_family == "intro_alignment"
    assert plan.ask_intents[0].ask_intent == "profile_positioning"
    assert plan.interviewer_need.dimensions[0] == "AWS/data platform leadership"
    assert any("current role" in item.lower() for item in plan.delivery_instructions)
    assert "avoid_unframed_fit_close" in plan.quality_guardrails
    assert plan.answer_blueprint[0]["purpose"] == "profile_core"


def test_live_brain_normalizes_llm_plan_using_snapshot_text_to_recover_richer_build_contract():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-llm-build-contract",
        utterance_id="u-llm-build-contract",
        revision_id=1,
        snapshot_text=(
            "Tell me about your experience building from 0. "
            "Whether it was building a product from 0, a team from 0, or a service from 0. "
            "Also cover your team management experience, how big the teams you've managed were, what roles they had, "
            "and tell me a little bit about you."
        ),
        conversation_history=[
            {
                "speaker": "interviewer",
                "text": (
                    "Tell me about your experience building from 0. "
                    "Whether it was building a product from 0, a team from 0, or a service from 0. "
                    "Also cover your team management experience, how big the teams you've managed were, what roles they had, "
                    "and tell me a little bit about you."
                ),
            }
        ],
        snapshot_hash="hash-llm-build-contract",
        timestamp=datetime.utcnow(),
    )

    plan = service._normalize_llm_plan(
        snapshot=snapshot,
        payload={
            "asks": [
                "Tell me about your experience building from 0.",
                "Tell me about your team management experience.",
                "How big were the teams you've managed?",
                "What roles did they have?",
                "Tell me a little bit about you.",
            ],
            "resolved_question": (
                "Answer these interviewer asks in order: 1. Tell me about your experience building from 0. "
                "2. Tell me about your team management experience. 3. How big were the teams you've managed? "
                "4. What roles did they have? 5. Tell me a little bit about you."
            ),
            "question_completeness": "complete",
            "question_type": "mixed",
            "response_shape": "direct_structured",
            "answer_contract": "business_with_outcomes",
            "ask_intents": [],
            "interviewer_need": {
                "summary": "The interviewer wants relevant experience.",
            },
            "response_requirement": {
                "answer_mode": "experience_with_outcomes",
            },
            "confidence": 0.82,
        },
        interview_config=_interview_config(),
    )

    assert plan.ask_intents[0].ask_intent == "build_from_zero_examples"
    assert "strongest probative value" in plan.ask_intents[0].response_goal.lower()
    assert "product, team, and service" in plan.ask_intents[0].response_goal.lower()
    assert any("0-to-1 / early-stage building" in item for item in plan.interviewer_need.dimensions)
    assert any("kind of thing built from zero: product, team, and service" in item.lower() for item in plan.interviewer_need.dimensions)
    assert any("object built" in item.lower() for item in plan.response_requirement.must_cover)
    assert any("product, team, and service" in item.lower() for item in plan.response_requirement.must_cover)
    assert "built and scaled a subscription operating model" in " ".join(plan.response_requirement.must_cover).lower()
    assert "founded the generative ai practice" in " ".join(plan.response_requirement.must_cover).lower()
    lowered_contextualized = plan.contextualized_question.lower()
    assert "foregrounding" not in lowered_contextualized
    assert "object built" in lowered_contextualized


def test_live_brain_prompt_includes_candidate_profile_evidence_snapshot_for_current_turn():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-brain-prompt-profile-evidence",
        utterance_id="u-brain-prompt-profile-evidence",
        revision_id=1,
        snapshot_text=(
            "We need to prepare data into different storage patterns like graphs, knowledge bases, and vectors so LLMs can use it well. "
            "We're looking for someone with that background, AWS infrastructure knowledge, and the ability to lead teams on how to design for those AI use cases. "
            "So tell me a bit about yourself, if you would."
        ),
        conversation_history=[
            {"speaker": "interviewer", "text": "We need to prepare data into different storage patterns like graphs, knowledge bases, and vectors so LLMs can use it well."},
            {"speaker": "interviewer", "text": "We're looking for someone with that background, AWS infrastructure knowledge, and the ability to lead teams on how to design for those AI use cases."},
            {"speaker": "interviewer", "text": "So tell me a bit about yourself, if you would."},
        ],
        snapshot_hash="hash-brain-prompt-profile-evidence",
        timestamp=datetime.utcnow(),
    )

    prompt = service._build_prompt(
        snapshot=snapshot,
        interview_config=_interview_config(),
        previous_plan=None,
    )

    assert "candidate profile evidence snapshot" in prompt.lower()
    assert "founded the generative ai practice" in prompt.lower()
    assert "built and scaled a subscription operating model" in prompt.lower()
    assert "profile evidence:" in prompt.lower()
    assert "do not rely on canned mappings" in prompt.lower()
    assert "profile_evidence_mode" in prompt.lower()
    assert "company_evidence_mode" in prompt.lower()
    assert "prior_context_mode" in prompt.lower()
    assert "must not script the answer" in prompt.lower()
    assert "preserve one response segment per interviewer ask" in prompt.lower()


def test_live_brain_prompt_normalizes_runtime_metadata_keys():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-brain-prompt-runtime-keys",
        utterance_id="u-brain-prompt-runtime-keys",
        revision_id=1,
        snapshot_text="So tell me a bit about yourself, if you would.",
        conversation_history=[{"speaker": "interviewer", "text": "So tell me a bit about yourself, if you would."}],
        snapshot_hash="hash-brain-prompt-runtime-keys",
        timestamp=datetime.utcnow(),
    )

    prompt = service._build_prompt(
        snapshot=snapshot,
        interview_config=_runtime_key_interview_config(),
        previous_plan=None,
    )

    lowered_prompt = prompt.lower()
    assert "candidate_context_available: true" in lowered_prompt
    assert "company_context_available: true" in lowered_prompt
    assert "interviewer_context_available: true" in lowered_prompt
    assert "founded the generative ai practice" in lowered_prompt


def test_live_brain_prompt_includes_previous_plan_semantic_snapshot():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-brain-prompt-previous-plan",
        utterance_id="u-brain-prompt-previous-plan",
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
        snapshot_hash="hash-brain-prompt-previous-plan",
        timestamp=datetime.utcnow(),
    )
    previous_plan = BrainPlan(
        ordered_asks=[
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
        response_family="culture_preferences",
        answer_contract="preferences_and_anti_patterns",
        context_focus=["company, culture, and teams"],
        response_requirement=ResponseRequirement(
            profile_evidence_mode="none",
            company_evidence_mode="preference_alignment",
            prior_context_mode="none",
            must_cover=["company, culture, and teams"],
        ),
        plan_source="llm_fast",
    )

    prompt = service._build_prompt(
        snapshot=snapshot,
        interview_config=_interview_config(),
        previous_plan=previous_plan,
    )

    lowered_prompt = prompt.lower()
    assert "previous_plan:" in lowered_prompt
    assert "family=culture_preferences" in lowered_prompt
    assert "profile_mode=none" in lowered_prompt
    assert "company_mode=preference_alignment" in lowered_prompt
    assert "must_cover=company, culture, and teams" in lowered_prompt


def test_live_evidence_packer_prioritizes_requirement_driven_evidence():
    packer = LiveEvidencePacker()
    plan = BrainPlan(
        literal_question="Tell me a bit about yourself, if you would.",
        contextualized_question=(
            "Introduce yourself by emphasizing the experience that shows you can lead AWS/data platform "
            "architecture, guide teams, and design for LLM use cases."
        ),
        resolved_question="Tell me a bit about yourself, if you would.",
        ordered_asks=["Tell me a bit about yourself, if you would."],
        ask_intents=[
            AskIntent(
                ask_text="Tell me a bit about yourself, if you would.",
                ask_intent="profile_positioning",
                response_goal="Position the profile around relevant architecture leadership and outcomes.",
                required_evidence_types=["role_evidence", "build_evidence", "technical_alignment_evidence"],
                expected_answer_shape="direct_structured",
                needs_context_from_prior_turns=True,
            )
        ],
        interviewer_need=InterviewerNeed(
            summary="The interviewer wants a profile answer aligned to AWS/data platform/LLM leadership.",
            dimensions=["AWS infrastructure", "data platform architecture", "LLM use cases"],
            evidence_expected=["role_evidence", "build_evidence", "technical_alignment_evidence"],
        ),
        response_requirement=ResponseRequirement(
            answer_mode="profile_alignment",
            response_order=["Tell me a bit about yourself, if you would."],
            required_moves=["Open with the current role and relevant domain responsibility."],
            context_to_weave=["AWS infrastructure", "data platform architecture", "LLM use cases"],
            evidence_priority=["role_evidence", "build_evidence", "technical_alignment_evidence"],
            must_cover=["current role", "relevant work", "outcomes"],
            avoid=["generic_biography"],
            paragraph_plan=["Paragraph 1: role and relevant scope"],
            style_constraints=["spoken"],
        ),
        context_focus=["AWS infrastructure leadership for LLM-ready data platforms."],
        question_type="behavioral",
        response_shape="direct_structured",
        answer_contract="business_with_outcomes",
        directness="balanced",
        candidate_context_policy="required",
        company_context_policy="support_if_relevant",
        metrics_policy="avoid_unless_helpful",
        confidence=0.8,
        question_completeness="complete",
        plan_source="llm_fast",
    )

    pack = packer.pack(plan=plan, interview_config=_interview_config())

    assert pack.role_evidence
    assert "technology director" in pack.role_evidence[0].lower()
    assert pack.build_evidence
    assert any("built and scaled" in item.lower() or "founded the generative ai practice" in item.lower() for item in pack.build_evidence)
    assert pack.technical_alignment_evidence
    assert any("aws" in item.lower() or "architecture" in item.lower() for item in pack.technical_alignment_evidence)


def test_live_evidence_packer_preference_alignment_uses_company_culture_sources_not_role_responsibilities():
    packer = LiveEvidencePacker()
    plan = BrainPlan(
        literal_question="What are you looking for in terms of the company, the culture, teams?",
        contextualized_question=(
            "Answer directly by stating what you want in the company, what you value in the culture, "
            "and how you want the team to operate."
        ),
        resolved_question="What are you looking for in terms of the company, the culture, teams?",
        ordered_asks=["What are you looking for in terms of the company, the culture, teams?"],
        response_family="culture_preferences",
        answer_contract="preferences_and_anti_patterns",
        candidate_context_policy="avoid",
        company_context_policy="support_if_relevant",
        response_requirement=ResponseRequirement(
            answer_mode="preferences",
            profile_evidence_mode="none",
            company_evidence_mode="preference_alignment",
            prior_context_mode="none",
            evidence_priority=["company_snippets", "culture_alignment_evidence"],
        ),
    )

    interview_config = _interview_config()
    interview_config["company"]["companySummary"] = "Consulting firm focused on long-term client impact."
    interview_config["company"]["companyCulture"] = "People-first consulting culture with collaborative partnership."
    interview_config["company"]["values"] = [
        "People-centered approach",
        "Collaborative partnership",
    ]
    interview_config["company"]["roleResponsibilities"] = [
        "Guide teams in defining scalable future-state data architectures."
    ]

    pack = packer.pack(plan=plan, interview_config=interview_config)

    lowered_company = " ".join(pack.company_snippets).lower()
    lowered_culture = " ".join(pack.culture_alignment_evidence).lower()
    assert "people-first consulting culture" in lowered_company
    assert "collaborative partnership" in lowered_company
    assert "guide teams in defining scalable future-state data architectures" not in lowered_company
    assert "guide teams in defining scalable future-state data architectures" not in lowered_culture


def test_live_evidence_packer_keeps_intro_alignment_buckets_distinct_when_candidate_has_rich_proof():
    packer = LiveEvidencePacker()
    plan = BrainPlan(
        literal_question="tell me a bit about yourself, if you would.",
        contextualized_question=(
            "Introduce yourself by emphasizing the parts of your background most relevant to AI-ready data platforms, "
            "architecture leadership, and guiding teams through design decisions for LLM use cases."
        ),
        resolved_question="tell me a bit about yourself, if you would.",
        ordered_asks=["tell me a bit about yourself, if you would."],
        ask_intents=[
            AskIntent(
                ask_text="tell me a bit about yourself, if you would.",
                ask_intent="profile_positioning",
                response_goal="Position the profile around architecture leadership, what was built, and leadership scope.",
                required_evidence_types=["role_evidence", "build_evidence", "leadership_evidence", "technical_alignment_evidence"],
                expected_answer_shape="direct_structured",
                needs_context_from_prior_turns=True,
            )
        ],
        interviewer_need=InterviewerNeed(
            summary="The interviewer wants a profile answer aligned to AI-ready data platform leadership, not a generic biography.",
            dimensions=["AI-ready data foundations", "architecture leadership", "team direction"],
            evidence_expected=["role_evidence", "build_evidence", "leadership_evidence", "technical_alignment_evidence"],
        ),
        response_requirement=ResponseRequirement(
            answer_mode="profile_alignment",
            response_order=["tell me a bit about yourself, if you would."],
            required_moves=[
                "Open with the current role and relevant decision scope.",
                "Explain what was built, led, or designed that matches the prior interviewer context.",
                "Show how you guide architecture or team decisions in that context.",
            ],
            context_to_weave=["AI-ready data platforms", "architecture leadership", "team direction"],
            evidence_priority=["role_evidence", "build_evidence", "leadership_evidence", "technical_alignment_evidence"],
            must_cover=["current role", "relevant work", "leadership scope", "proof point"],
            avoid=["generic_biography"],
            paragraph_plan=["Paragraph 1: role and relevant scope", "Paragraph 2: proof and alignment"],
            style_constraints=["spoken"],
        ),
        context_focus=[
            "The interviewer needs someone who can guide teams and design AI-ready data platform solutions.",
        ],
        response_family="intro_alignment",
        question_type="behavioral",
        response_shape="direct_structured",
        answer_contract="business_with_outcomes",
        directness="balanced",
        candidate_context_policy="required",
        company_context_policy="support_if_relevant",
        metrics_policy="avoid_unless_helpful",
        confidence=0.8,
        question_completeness="complete",
        plan_source="safe_fallback",
    )

    interview_config = {
        "candidate": {
            "currentRole": "Technology Director, Data & AI",
            "company": "Globant",
            "summary": (
                "Technology executive with 20 years leading enterprise transformation across software modernization "
                "and the full data lifecycle. Global leadership scope: 20 direct managers and 345 indirect reports."
            ),
            "skills": ["AWS", "Data platforms", "Architecture", "Technical leadership"],
            "achievements": [
                "Built and scaled a subscription operating model for modernization and data programs.",
                "Led core banking modernization across 6+ enterprise accounts and 100+ applications, delivering up to 40% OPEX reduction within 12 months.",
            ],
            "cv_text": (
                "Co-led execution of Globant's GenAI strategy and co-created AI Pods as a subscription operating model. "
                "Consolidated delivery across data lifecycle, application modernization, and platform transformation. "
                "Led teams through architecture and platform decisions for AI-ready workloads."
            ),
        },
        "company": {
            "roleTitle": "Director - Data Architecture & Engineering",
            "roleResponsibilities": [
                "Lead solution design and technical delivery for complex data engineering and architecture projects across AWS.",
            ],
        },
    }

    pack = packer.pack(plan=plan, interview_config=interview_config)

    assert pack.role_evidence
    assert any("technology director" in item.lower() for item in pack.role_evidence)
    assert pack.build_evidence
    assert any(
        "built and scaled a subscription operating model" in item.lower()
        or "co-led execution" in item.lower()
        for item in pack.build_evidence
    )
    assert pack.leadership_evidence
    assert any(
        "20 direct managers" in item.lower()
        or "led teams through architecture and platform decisions" in item.lower()
        for item in pack.leadership_evidence
    )
    assert pack.technical_alignment_evidence
    assert any(
        "aws" in item.lower()
        or "data lifecycle" in item.lower()
        or "platform transformation" in item.lower()
        for item in pack.technical_alignment_evidence
    )
    structured_heads = [
        pack.role_evidence[0].lower(),
        pack.build_evidence[0].lower(),
        pack.leadership_evidence[0].lower(),
        pack.technical_alignment_evidence[0].lower(),
    ]
    assert len(set(structured_heads)) >= 3


def test_live_brain_safe_plan_requires_two_examples_when_interviewer_asks_for_examples_in_plural():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-build-zero-two-examples",
        utterance_id="u-build-zero-two-examples",
        revision_id=1,
        snapshot_text=(
            "I want to hear specifically examples of companies or experiences where you had to build from 0. "
            "Whether it was building a product from 0, a team from 0, or a service from 0. "
            "Now I want to get a sense of your experience in building from 0, building from scratch, early stages. "
            "And then also very curious to hear about your team management experience. "
            "How big were the teams you've managed? What roles did they have? "
            "And last, tell me a little bit about you."
        ),
        conversation_history=[
            {
                "speaker": "interviewer",
                "text": (
                    "I want to hear specifically examples of companies or experiences where you had to build from 0. "
                    "Whether it was building a product from 0, a team from 0, or a service from 0."
                ),
            },
            {
                "speaker": "interviewer",
                "text": (
                    "Now I want to get a sense of your experience in building from 0, building from scratch, early stages. "
                    "And then also very curious to hear about your team management experience. "
                    "How big were the teams you've managed? What roles did they have? "
                    "And last, tell me a little bit about you."
                ),
            },
        ],
        snapshot_hash="hash-build-zero-two-examples",
        timestamp=datetime.utcnow(),
    )

    plan = service._plan_safely(snapshot=snapshot, interview_config=_interview_config())

    assert plan.ask_intents[0].ask_intent == "build_from_zero_examples"
    assert "strongest probative value" in plan.ask_intents[0].response_goal.lower()
    assert "product, team, and service" in plan.ask_intents[0].response_goal.lower()
    assert "product, team, and service" in plan.interviewer_need.summary.lower()
    assert any("0-to-1 / early-stage building" in item for item in plan.interviewer_need.dimensions)
    assert any("kind of thing built from zero: product, team, and service" in item.lower() for item in plan.interviewer_need.dimensions)
    assert any("object built, stage, ownership, and outcome" in item.lower() for item in plan.response_requirement.required_moves)
    assert any("multiple examples clearly separated" in item.lower() for item in plan.response_requirement.required_moves)
    assert any("object built" in item.lower() for item in plan.response_requirement.must_cover)
    assert "built and scaled a subscription operating model" in " ".join(plan.response_requirement.must_cover).lower()
    assert "founded the generative ai practice" in " ".join(plan.response_requirement.must_cover).lower()
    assert "answer tell me about your experience in building from 0" in plan.response_requirement.paragraph_plan[0].lower()
    assert "answer how big were the teams" in " ".join(plan.response_requirement.paragraph_plan).lower()
    lowered_contextualized = plan.contextualized_question.lower()
    assert "foregrounding" not in lowered_contextualized
    assert "object built" in lowered_contextualized


def test_live_brain_build_from_zero_prefers_distinct_genesis_examples_over_ai_pods_variant():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-build-zero-distinct-genesis",
        utterance_id="u-build-zero-distinct-genesis",
        revision_id=1,
        snapshot_text=(
            "I want to hear specifically examples of companies or experiences where you had to build from 0. "
            "Whether it was building a product from 0, a team from 0, or a service from 0. "
            "Now I want to get a sense of your experience in building from 0, building from scratch, early stages. "
            "And then also very curious to hear about your team management experience. "
            "How big were the teams you've managed? What roles did they have? "
            "And last, tell me a little bit about you."
        ),
        conversation_history=[
            {
                "speaker": "interviewer",
                "text": (
                    "I want to hear specifically examples of companies or experiences where you had to build from 0. "
                    "Whether it was building a product from 0, a team from 0, or a service from 0."
                ),
            },
            {
                "speaker": "interviewer",
                "text": (
                    "Now I want to get a sense of your experience in building from 0, building from scratch, early stages. "
                    "And then also very curious to hear about your team management experience. "
                    "How big were the teams you've managed? What roles did they have? "
                    "And last, tell me a little bit about you."
                ),
            },
        ],
        snapshot_hash="hash-build-zero-distinct-genesis",
        timestamp=datetime.utcnow(),
    )
    interview_config = _interview_config()
    interview_config["candidate"]["summary"] = (
        "Technology executive with 20 years leading enterprise transformation across software modernization and the full data lifecycle. "
        "Global leadership scope: 20 direct managers / 345 indirect reports across North America, LATAM, Middle East, Europe, and Australia. "
        "Designed, scaled, and operated a subscription-based delivery model (AI Pods) with governance, quality controls, predictable monthly cost, and KPI-based management."
    )
    interview_config["candidate"]["achievements"] = [
        "Built and scaled a subscription operating model (governance, quality gates, predictable monthly cost, KPI cadence) for modernization and data programs.",
        "Designed, scaled, and operated a subscription-based delivery model (AI Pods) with governance, quality controls, predictable monthly cost, and KPI-based management.",
        "Founded the Generative AI practice in Colombia (Genoma) and developed 7 reusable assets to accelerate time-to-value and support deal conversion and implementation.",
    ]

    plan = service._plan_safely(snapshot=snapshot, interview_config=interview_config)

    first_two = " ".join(plan.response_requirement.must_cover[:2]).lower()
    assert "built and scaled a subscription operating model" in first_two
    assert "founded the generative ai practice" in first_two
    assert "ai pods" not in first_two


def test_live_brain_recovers_embedded_build_from_zero_ask_before_team_follow_ups():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-build-zero-embedded-noisy",
        utterance_id="u-build-zero-embedded-noisy",
        revision_id=1,
        snapshot_text=(
            "But I was hear specifically examples of companies or experiences that you've had where you had to build from 0, "
            "whether it was building a product from 0, a team from 0, a service from Xero, "
            "Now I wanna get a sense of your experience in building from 0, building scratch. "
            "Early stages. And then, also very curious to hear about your team management experience. "
            "How big were the teams you've managed? What roles did they have, etcetera. Yeah. "
            "And last question as as we go. So if you want, just kind of start telling us or telling me a little bit about you. "
            "kinda start telling us or telling me a"
        ),
        conversation_history=[
            {
                "speaker": "interviewer",
                "text": "But I was hear specifically examples of companies or experiences that you've had where you had to build from 0, whether it was building a product from 0, a team from 0, a service from Xero.",
            },
            {
                "speaker": "interviewer",
                "text": "Now I wanna get a sense of your experience in building from 0, building scratch.",
            },
            {
                "speaker": "interviewer",
                "text": "And then, also very curious to hear about your team management experience. How big were the teams you've managed?",
            },
            {
                "speaker": "interviewer",
                "text": "What roles did they have, etcetera. Yeah. And last question as as we go. So if you want, just kind of start telling us or telling me a little bit about you.",
            },
            {
                "speaker": "interviewer",
                "text": "kinda start telling us or telling me a",
            },
        ],
        snapshot_hash="hash-build-zero-embedded-noisy",
        timestamp=datetime.utcnow(),
    )

    plan = service._plan_safely(snapshot=snapshot, interview_config=_interview_config())

    lowered_asks = [ask.lower() for ask in plan.ordered_asks]
    assert plan.question_completeness == "complete"
    assert "building from 0" in lowered_asks[0]
    assert "team management experience" in lowered_asks[1]
    assert "how big were the teams" in lowered_asks[2]
    assert "what roles did they have" in lowered_asks[3]
    assert "little bit about you" in lowered_asks[4]
    assert "build-from-zero ask" in plan.contextualized_question.lower()


def test_live_brain_profile_alignment_uses_intro_opening_and_keeps_scope_out_of_default_intro_contract():
    service = LiveBrainService()
    snapshot = BrainSnapshot(
        session_id="s-profile-alignment-separate-scope",
        utterance_id="u-profile-alignment-separate-scope",
        revision_id=1,
        snapshot_text=(
            "We need to prepare data into graphs, knowledge bases, and vectors so LLMs can use it well. "
            "We're looking for someone with that background, AWS infrastructure knowledge, and the ability to lead teams on how to design for those AI use cases. "
            "So tell me a bit about yourself, if you would."
        ),
        conversation_history=[
            {"speaker": "interviewer", "text": "We need to prepare data into graphs, knowledge bases, and vectors so LLMs can use it well."},
            {"speaker": "interviewer", "text": "We're looking for someone with that background, AWS infrastructure knowledge, and the ability to lead teams on how to design for those AI use cases."},
            {"speaker": "interviewer", "text": "So tell me a bit about yourself, if you would."},
        ],
        snapshot_hash="hash-profile-alignment-separate-scope",
        timestamp=datetime.utcnow(),
    )
    interview_config = _interview_config()
    interview_config["candidate"]["summary"] = (
        "Technology executive with 20 years leading enterprise transformation across software modernization and the full data lifecycle. "
        "Global leadership scope: 20 direct managers / 345 indirect reports across North America, LATAM, Middle East, Europe, and Australia. "
        "Designed, scaled, and operated a subscription-based delivery model (AI Pods) with governance, quality controls, predictable monthly cost, and KPI-based management."
    )
    interview_config["candidate"]["achievements"] = [
        "Built and scaled a subscription operating model (governance, quality gates, predictable monthly cost, KPI cadence) for modernization and data programs.",
        "Designed, scaled, and operated a subscription-based delivery model (AI Pods) with governance, quality controls, predictable monthly cost, and KPI-based management.",
        "Founded the Generative AI practice in Colombia (Genoma) and developed 7 reusable assets to accelerate time-to-value and support deal conversion and implementation.",
    ]
    interview_config["candidate"]["skills"] = ["AWS", "Azure", "GCP", "Data platforms", "Architecture", "Technical leadership"]
    interview_config["company"]["roleResponsibilities"] = [
        "Lead solution design and technical delivery for complex data engineering and architecture projects across AWS, Azure, and GCP.",
        "Guide teams in defining scalable future-state data architectures.",
        "Lead teams building data platforms for AI and agent use cases.",
    ]

    plan = service._plan_safely(snapshot=snapshot, interview_config=interview_config)

    first_sentence = plan.draft_answer.split(".", 1)[0].lower()
    must_cover_text = " ".join(plan.response_requirement.must_cover).lower()
    lowered_draft = plan.draft_answer.lower()
    assert "..." not in first_sentence
    assert "currently serving as technology director" in first_sentence or "technology executive" in first_sentence
    assert "built and scaled a subscription operating model" in lowered_draft
    assert "open with a complete spoken sentence" not in plan.contextualized_question.lower()
    assert "20 direct managers / 345 indirect reports" not in must_cover_text
    assert "ai pods" not in must_cover_text
    assert "20 direct managers / 345 indirect reports" not in lowered_draft
    assert "shaping ai-ready data platforms" in lowered_draft or "setting direction for data platform architecture" in lowered_draft


def test_live_finalizer_strict_prompt_uses_response_requirement_contract():
    finalizer = LiveFinalizer()
    plan = BrainPlan(
        literal_question="Tell me a bit about yourself, if you would.",
        contextualized_question=(
            "Introduce yourself by emphasizing the parts of your background most relevant to AWS/data platform "
            "leadership, LLM-ready architecture, and leading teams through those design decisions."
        ),
        resolved_question="Tell me a bit about yourself, if you would.",
        ordered_asks=["Tell me a bit about yourself, if you would."],
        ask_intents=[
            AskIntent(
                ask_text="Tell me a bit about yourself, if you would.",
                ask_intent="profile_positioning",
                response_goal="Position the profile around relevant AWS/data platform leadership and outcomes.",
                required_evidence_types=["role_evidence", "build_evidence", "technical_alignment_evidence"],
                expected_answer_shape="direct_structured",
                needs_context_from_prior_turns=True,
            )
        ],
        interviewer_need=InterviewerNeed(
            summary="The interviewer wants a profile answer aligned to prior AWS/data platform/LLM context, not a generic biography.",
            dimensions=["AWS/data platform leadership", "LLM-ready architecture", "Team leadership"],
            evidence_expected=["role_evidence", "build_evidence", "technical_alignment_evidence"],
        ),
        response_requirement=ResponseRequirement(
            answer_mode="profile_alignment",
            response_order=["Tell me a bit about yourself, if you would."],
            required_moves=[
                "Open with the current role and relevant domain responsibility.",
                "Explain what has been built, led, or designed that matches the prior interviewer context.",
                "Include one or two concrete outcomes that show credibility.",
            ],
            context_to_weave=["AWS/data platform leadership for LLM use cases"],
            evidence_priority=["role_evidence", "build_evidence", "technical_alignment_evidence"],
            must_cover=["current role", "relevant work", "outcomes"],
            avoid=["generic_biography", "unsupported_fit_closure"],
            paragraph_plan=["Paragraph 1: role and relevant scope", "Paragraph 2: outcomes and alignment"],
            style_constraints=["spoken", "no bullets"],
        ),
        context_focus=["AWS/data platform leadership for LLM use cases"],
        response_family="intro_alignment",
        alignment_brief=["AWS/data platform leadership", "LLM-ready architecture"],
        quality_guardrails=["direct_first_sentence", "avoid_unframed_fit_close"],
        delivery_instructions=["Open with the current role and relevant domain responsibility."],
    )
    evidence_pack = CompactEvidencePack(
        plan_hash="plan-hash-strict-contract",
        role_evidence=["I'm currently serving as Technology Director, Data & AI at Globant."],
        build_evidence=["I built and scaled a subscription operating model for modernization and data programs."],
        technical_alignment_evidence=["Led architecture and operating decisions for AI-ready data platforms on AWS."],
        excluded_topics=["generic_biography"],
    )

    prompt = finalizer._build_prompt(
        plan=plan,
        evidence_pack=evidence_pack,
        question_text=plan.resolved_question,
        conversation_history=[{"speaker": "interviewer", "text": "Raw history should not appear."}],
        interview_config=_interview_config(),
        working_draft="",
        include_plan_draft=False,
        strict_emit_only=True,
    )

    assert "ASK INTENTS" in prompt
    assert "LITERAL QUESTION:" in prompt
    assert "Tell me a bit about yourself, if you would." in prompt
    assert "AWS/data platform leadership" in prompt
    assert "INTERVIEWER NEED" in prompt
    assert "CONTEXT FOCUS" in prompt
    assert "AWS/data platform leadership for LLM use cases" in prompt
    assert "Open with the current role and relevant domain responsibility." in prompt
    assert "Raw history should not appear." not in prompt
    assert "ALIGNMENT BRIEF" not in prompt
    assert "QUALITY GUARDRAILS" not in prompt
    assert "ANSWER BLUEPRINT" not in prompt
    assert "DELIVERY INSTRUCTIONS" not in prompt


def test_live_finalizer_filters_source_of_truth_context_by_evidence_modes():
    finalizer = LiveFinalizer()
    plan = BrainPlan(
        literal_question="What are you looking for in terms of the company, the culture, teams?",
        contextualized_question=(
            "Answer by focusing on the preference areas most relevant to company, culture, and teams. "
            "Keep the answer on stated preferences and boundaries rather than background recap."
        ),
        resolved_question="What are you looking for in terms of the company, the culture, teams?",
        ordered_asks=["What are you looking for in terms of the company, the culture, teams?"],
        response_requirement=ResponseRequirement(
            answer_mode="preferences",
            profile_evidence_mode="none",
            company_evidence_mode="preference_alignment",
            prior_context_mode="none",
        ),
        question_type="direct",
        response_shape="direct_structured",
        answer_contract="preferences_and_anti_patterns",
    )
    evidence_pack = CompactEvidencePack(
        plan_hash="plan-hash-filtered-source-context",
        company_snippets=["People-first culture.", "Values include people and execution."],
        excluded_topics=[],
        mode="full",
    )
    interview_config = {
        "style_id": "detailed",
        "language": "en",
        "candidate": {
            "name": "Daniel Alarcón Ramírez",
            "currentRole": "Technology Director, Data & AI",
            "company": "Globant",
            "currentCompany": "Globant",
            "yearsExperience": 20,
            "summary": "Technology executive with 20 years leading enterprise transformation.",
            "skills": ["AWS", "Architecture"],
            "achievements": ["Built and scaled a subscription operating model."],
        },
        "target_context": {
            "company": {
                "name": "Slalom",
                "culture": "People-first consulting culture.",
                "values": ["People", "Execution"],
            },
            "role": {
                "title": "Director - Data Architecture & Engineering",
                "level": "director",
                "requirements": ["Consulting experience", "Cloud data platforms"],
                "responsibilities": ["Lead client delivery"],
            },
            "interviewer": {
                "name": "Bernardo Najlis",
                "roleTitle": "Consulting Leader",
                "company": "Slalom",
                "backgroundSummary": "Strategic consulting leader.",
                "likelyFocusAreas": ["Operating style", "Client impact"],
            },
        },
    }

    prompt = finalizer._build_prompt(
        plan=plan,
        evidence_pack=evidence_pack,
        question_text=plan.resolved_question,
        conversation_history=[],
        interview_config=interview_config,
        working_draft="",
        include_plan_draft=False,
        strict_emit_only=True,
    )

    lowered_prompt = prompt.lower()
    assert "candidate profile facts" in lowered_prompt
    assert "candidate profile details: restricted by profile evidence mode." in lowered_prompt
    assert "technology executive with 20 years leading enterprise transformation." not in lowered_prompt
    assert "aws | architecture" not in lowered_prompt
    assert "built and scaled a subscription operating model." not in lowered_prompt
    assert "years of experience:" not in lowered_prompt
    assert "current company:" not in lowered_prompt
    assert "target company context (application target only)" in lowered_prompt
    assert "culture: people-first consulting culture." in lowered_prompt
    assert "values: people | execution" in lowered_prompt
    assert "consulting experience | cloud data platforms" not in lowered_prompt
    assert "lead client delivery" not in lowered_prompt
    assert "interviewer context: restricted by prior context mode." in lowered_prompt
    assert "strategic consulting leader." not in lowered_prompt


def test_live_finalizer_realizes_preference_blueprint_with_explicit_company_culture_team_segments():
    finalizer = LiveFinalizer()
    plan = BrainPlan(
        literal_question="What are you looking for in terms of the company, the culture, teams?",
        contextualized_question=(
            "Answer directly by stating what you want in the company, what you value in the culture, "
            "how you want the team to operate, and what you want to avoid."
        ),
        resolved_question="What are you looking for in terms of the company, the culture, teams?",
        ordered_asks=[
            "What are you looking for in terms of the company, the culture, teams?",
            "What's important for you, or what kind of things you absolutely don't like?",
        ],
        coverage_points=["company", "culture", "teams"],
        response_requirement=ResponseRequirement(
            answer_mode="preferences",
            profile_evidence_mode="none",
            company_evidence_mode="preference_alignment",
            prior_context_mode="none",
        ),
        question_type="direct",
        response_shape="direct_structured",
        answer_contract="preferences_and_anti_patterns",
        response_family="culture_preferences",
        answer_blueprint=[
            {
                "purpose": "preferences_company",
                "ask_refs": ["company"],
                "required_elements": ["company preferences"],
                "preferred_evidence_types": ["company_snippets"],
                "avoid_topics": [],
                "target_sentence_count": 1,
            },
            {
                "purpose": "preferences_culture",
                "ask_refs": ["culture"],
                "required_elements": ["culture preferences"],
                "preferred_evidence_types": ["company_snippets", "culture_alignment_evidence"],
                "avoid_topics": [],
                "target_sentence_count": 1,
            },
            {
                "purpose": "preferences_team",
                "ask_refs": ["team"],
                "required_elements": ["team preferences"],
                "preferred_evidence_types": ["company_snippets", "culture_alignment_evidence"],
                "avoid_topics": [],
                "target_sentence_count": 1,
            },
            {
                "purpose": "preferences_boundaries",
                "ask_refs": ["avoid"],
                "required_elements": ["boundaries or anti-patterns"],
                "preferred_evidence_types": ["culture_alignment_evidence"],
                "avoid_topics": [],
                "target_sentence_count": 1,
            },
        ],
        plan_source="safe_fallback",
    )
    evidence_pack = CompactEvidencePack(
        plan_hash="plan-hash-preference-segments",
        company_snippets=["a company with durable client impact and strong delivery standards"],
        culture_alignment_evidence=["collaborative, low-ego environments with clear expectations"],
        excluded_topics=[],
        mode="full",
    )

    answer = finalizer._build_answer_from_blueprint(
        plan=plan,
        evidence_pack=evidence_pack,
        draft_text=(
            "On the company side, I'm looking for durable client impact and strong delivery standards. "
            "In terms of culture, I value collaborative, low-ego environments with clear expectations. "
            "For the team itself, I value shared ownership and direct communication. "
            "What I tend to avoid is environments where those basics are missing."
        ),
    )

    lowered = answer.lower()
    assert "on the company side" in lowered
    assert "in terms of culture" in lowered
    assert "for the team itself" in lowered
    assert "what i tend to avoid" in lowered
    assert "where those basics are missing" in lowered
