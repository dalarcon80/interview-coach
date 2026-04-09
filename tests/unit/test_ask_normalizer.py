from pipeline.steps.ask_normalizer import AskNormalizer, apply_ask_brief_policy
from contracts.models import AskFamily, AnswerContract, MetricsPolicy, QuestionAnalysis, ResponseMode, Priority


def test_normalizer_builds_compound_experience_brief():
    normalizer = AskNormalizer()
    turns = [
        {"speaker": "interviewer", "text": "Tell me about your experience building from zero."},
        {"speaker": "interviewer", "text": "How big were the teams you've managed and what roles did they have?"},
        {"speaker": "interviewer", "text": "And briefly tell me a little bit about you."},
    ]

    brief = normalizer.normalize(
        "Tell me about your experience building from zero.\nHow big were the teams you've managed and what roles did they have?\nAnd briefly tell me a little bit about you.",
        turns,
        delivery_mode="realtime",
    )

    assert brief.answer_family == AskFamily.MIXED_COMPOUND
    assert brief.answer_contract == AnswerContract.DIRECT_MULTI_PART
    assert "build" in brief.primary_ask.lower()
    assert len(brief.secondary_asks) >= 1


def test_normalizer_detects_culture_fit_without_metrics_bias():
    normalizer = AskNormalizer()

    brief = normalizer.normalize(
        "What are you looking for in a company, the culture, teams, and what things do you absolutely not like?",
        [],
        delivery_mode="manual",
    )

    assert brief.answer_family == AskFamily.CULTURE_FIT
    assert brief.metrics_policy == MetricsPolicy.AVOID_UNLESS_REQUESTED
    assert "culture" in " ".join(brief.why).lower() or "preference" in " ".join(brief.why).lower()


def test_normalizer_limits_latest_interviewer_block_to_last_five_turns():
    normalizer = AskNormalizer()
    turns = [
        {"speaker": "interviewer", "text": "Turn one."},
        {"speaker": "interviewer", "text": "Turn two."},
        {"speaker": "interviewer", "text": "Turn three."},
        {"speaker": "interviewer", "text": "Turn four."},
        {"speaker": "interviewer", "text": "Turn five."},
        {"speaker": "interviewer", "text": "Turn six."},
    ]

    brief = normalizer.normalize("fallback", turns, delivery_mode="realtime")

    assert "Turn one." not in brief.primary_ask
    assert "Turn two." in brief.primary_ask
    assert "Turn six" in brief.primary_ask


def test_apply_ask_brief_policy_promotes_high_confidence_experience_brief():
    normalizer = AskNormalizer()
    turns = [
        {"speaker": "interviewer", "text": "Tell me about your experience building from zero."},
        {"speaker": "interviewer", "text": "How big were the teams you've managed?"},
        {"speaker": "interviewer", "text": "What roles did they have?"},
    ]
    brief = normalizer.normalize("fallback", turns, delivery_mode="realtime")

    analysis = apply_ask_brief_policy(QuestionAnalysis(), brief, delivery_mode="realtime")

    assert analysis.normalizer_applied is True
    assert analysis.is_compound is True
    assert analysis.sub_questions[0].priority == Priority.MUST_ANSWER
    assert analysis.response_mode == ResponseMode.INTERVIEW_ANSWER
    assert "AskNormalizer authoritative" in analysis.style_reason


def test_apply_ask_brief_policy_keeps_fallback_when_confidence_too_low():
    brief = AskNormalizer().normalize("short question", [], delivery_mode="manual")
    brief.confidence = 0.2
    analysis = apply_ask_brief_policy(QuestionAnalysis(), brief, delivery_mode="manual")

    assert analysis.normalizer_applied is False
    assert analysis.normalizer_fallback_used is True


def test_normalizer_filters_noise_and_keeps_actionable_asks():
    normalizer = AskNormalizer()
    turns = [
        {"speaker": "interviewer", "text": "Sorry. I have a terrible cough, and that won't go away."},
        {"speaker": "interviewer", "text": "I would like to hear specifically examples of companies where you had to build from 0."},
        {"speaker": "interviewer", "text": "How big were the teams you've managed?"},
        {"speaker": "interviewer", "text": "What roles did they have?"},
    ]

    brief = normalizer.normalize("fallback", turns, delivery_mode="realtime")

    assert "terrible cough" not in brief.primary_ask.lower()
    assert "build from 0" in brief.primary_ask.lower()
    assert any("teams you've managed" in ask.lower() for ask in brief.secondary_asks)
    assert any("roles did they have" in ask.lower() for ask in brief.secondary_asks)


def test_normalizer_demotes_broad_intro_when_mixed_with_specific_asks():
    normalizer = AskNormalizer()
    turns = [
        {"speaker": "interviewer", "text": "Tell me a little bit about you."},
        {"speaker": "interviewer", "text": "What are you looking for in a company and team culture?"},
        {"speaker": "interviewer", "text": "What things do you absolutely not like?"},
    ]

    brief = normalizer.normalize("fallback", turns, delivery_mode="realtime")

    assert "looking for" in brief.primary_ask.lower()
    assert any("tell me a little bit about you" in ask.lower() for ask in brief.secondary_asks)


def test_normalizer_handles_live_compound_experience_block_without_product_drift():
    normalizer = AskNormalizer()
    turns = [
        {"speaker": "interviewer", "text": "Sorry. I have a terrible cough, and that won't go away. But I was."},
        {"speaker": "interviewer", "text": "hear specifically examples of companies or experience"},
        {"speaker": "interviewer", "text": "experiences that you've had where you had to build from 0. Whether it was building a product from 0, a team from 0, a a service from Siro, Now I wanna get a sense of your experience in building from 0, building from scratch. Early stages."},
        {"speaker": "interviewer", "text": "And then also very curious to hear about your team management experience. How big were the teams you've managed?"},
        {"speaker": "interviewer", "text": "What roles did they have, etcetera. Yeah. And last question as as we go. So if you want, just kinda start telling us or telling me a little bit about you."},
    ]

    brief = normalizer.normalize("fallback", turns, delivery_mode="realtime")

    assert brief.answer_family == AskFamily.MIXED_COMPOUND
    assert "build from 0" in brief.primary_ask.lower() or "building from 0" in brief.primary_ask.lower()
    assert any(
        "team management" in ask.lower() and "teams you've managed" in ask.lower()
        for ask in brief.secondary_asks
    )
    assert any("what roles did they have" in ask.lower() for ask in brief.secondary_asks)
