from api.server import (
    _build_active_pipeline_suggest_context,
    _build_frontend_suggest_context,
    _build_history_based_suggest_context,
)


class _FakeTracker:
    def build_normalized_realtime_context_bundle(self, limit: int = 5):
        return {
            "turns": [
                {
                    "speaker": "interviewer",
                    "text": "Tell me a little bit more about Globant.",
                    "timestamp": "2026-04-09T23:37:37.628000",
                }
            ],
            "active_turns": [
                {
                    "speaker": "interviewer",
                    "text": "Tell me a little bit more about Globant.",
                    "timestamp": "2026-04-09T23:37:37.628000",
                }
            ],
            "historical_turns": [
                {
                    "speaker": "interviewer",
                    "text": "Summarize the the type of, of position that you've that you've had.",
                    "timestamp": "2026-04-09T23:36:21.082000",
                }
            ],
            "primary_question": "Tell me a little bit more about Globant.",
            "primary_question_source": "post_commit_interviewer_turns",
        }


def test_build_active_pipeline_suggest_context_uses_only_active_turns():
    conversation_history, question_text, context_bundle = _build_active_pipeline_suggest_context(
        conversation_tracker=_FakeTracker(),
        history_count=5,
        question_text="stale request question",
        preserve_question_text=False,
    )

    assert question_text == "Tell me a little bit more about Globant."
    assert len(conversation_history) == 1
    assert conversation_history[0]["text"] == "Tell me a little bit more about Globant."
    assert context_bundle["historical_turns"]
    assert context_bundle["primary_question_source"] == "post_commit_interviewer_turns"


def test_build_history_based_suggest_context_uses_only_latest_active_turn():
    conversation_history, question_text, context_bundle = _build_history_based_suggest_context(
        recent_exchanges=[
            {"interviewer_utterance": "Summarize the the type of, of position that you've that you've had."},
            {"interviewer_utterance": "Tell me a little bit more about Globant."},
            {"interviewer_utterance": "Okay. So does that mean that you work on on projects yourself?"},
        ],
        question_text="stale request question",
        preserve_question_text=False,
    )

    assert question_text == "Okay. So does that mean that you work on on projects yourself?"
    assert len(conversation_history) == 1
    assert conversation_history[0]["text"] == "Okay. So does that mean that you work on on projects yourself?"
    assert context_bundle["historical_turns"]
    assert context_bundle["primary_question_source"] == "latest_interviewer_turn"


def test_build_frontend_suggest_context_uses_timing_to_reset_after_silence():
    conversation_history, question_text, context_bundle = _build_frontend_suggest_context(
        frontend_conversation_history=[
            {
                "speaker": "interviewer",
                "text": "Summarize the type of position that you've had.",
                "timestamp_ms": 1_000,
            },
            {
                "speaker": "interviewer",
                "text": "Tell me a little bit more about Globant.",
                "timestamp_ms": 12_000,
            },
            {
                "speaker": "interviewer",
                "text": "Okay. So does that mean that you work on projects yourself?",
                "timestamp_ms": 24_000,
            },
        ],
        question_text="stale request question",
        preserve_question_text=False,
    )

    assert question_text == "Okay. So does that mean that you work on projects yourself?"
    assert len(conversation_history) == 1
    assert conversation_history[0]["text"] == "Okay. So does that mean that you work on projects yourself?"
    assert context_bundle["historical_turns"]
    assert context_bundle["primary_question_source"] == "latest_interviewer_turn"
