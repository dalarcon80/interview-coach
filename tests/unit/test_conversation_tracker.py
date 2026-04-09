"""
Interview Coach - Unit Tests for Conversation Tracker
"""

from contracts.models import LiveAskSummary
from conversation.tracker import ConversationTracker
from pipeline.silence_detector import build_realtime_context_bundle


def test_short_turn_rejected():
    tracker = ConversationTracker()

    accepted = tracker.add_turn(
        speaker="interviewer",
        text="Hello",
        utterance_count=1,
        start_time=10.0,
        end_time=10.3,
        reason="final",
    )

    assert accepted is False
    conv_map = tracker.get_map()
    assert any("short_turn_rejected" in warning for warning in conv_map.warnings)


def test_max_turns_pruning():
    tracker = ConversationTracker()
    tracker.max_turns = 3

    for idx in range(5):
        start = float(idx * 2)
        end = start + 0.6
        accepted = tracker.add_turn(
            speaker="interviewer",
            text=f"Turn {idx}",
            utterance_count=1,
            start_time=start,
            end_time=end,
            reason="final",
        )
        assert accepted is True

    assert len(tracker.state.turn_history) == 3
    remaining_texts = [turn["text"] for turn in tracker.state.turn_history]
    assert remaining_texts == ["Turn 2", "Turn 3", "Turn 4"]


def test_rapid_switch_warning():
    tracker = ConversationTracker()

    accepted_first = tracker.add_turn(
        speaker="interviewer",
        text="First",
        utterance_count=1,
        start_time=0.0,
        end_time=1.0,
        reason="final",
    )
    accepted_second = tracker.add_turn(
        speaker="candidate",
        text="Second",
        utterance_count=1,
        start_time=1.2,
        end_time=2.0,
        reason="final",
    )

    assert accepted_first is True
    assert accepted_second is True

    conv_map = tracker.get_map()
    assert any(
        warning.startswith("rapid_speaker_switch") for warning in conv_map.warnings
    )


def test_live_ask_summary_cache_roundtrip():
    tracker = ConversationTracker()
    summary = LiveAskSummary(
        source_turns=[{"speaker": "interviewer", "text": "What did you build from zero?"}],
        turn_window_size=1,
        signature="sig-1",
        primary_ask="What did you build from zero?",
        secondary_asks=["How large were the teams?"],
        ordered_focus=["What did you build from zero?", "How large were the teams?"],
        confidence=0.91,
        version=3,
    )

    tracker.cache_live_ask_summary(summary)

    cached = tracker.get_live_ask_summary()
    assert cached is not None
    assert cached.signature == "sig-1"
    assert cached.version == 3
    assert cached.secondary_asks == ["How large were the teams?"]


def test_build_realtime_context_bundle_prefers_post_commit_follow_up_over_answered_prior_ask():
    tracker = ConversationTracker()

    assert tracker.add_turn(
        speaker="interviewer",
        text="What are you looking for in terms of the company?",
        utterance_count=1,
        start_time=0.0,
        end_time=0.8,
        reason="final",
    )
    assert tracker.add_turn(
        speaker="interviewer",
        text="What do you absolutely not like?",
        utterance_count=1,
        start_time=2.0,
        end_time=2.8,
        reason="final",
    )

    tracker.record_answer_committed(
        committed_at=5.0,
        question_key="what are you looking for in terms of the company?",
        interviewer_generation=1,
    )

    assert tracker.add_turn(
        speaker="interviewer",
        text="Tell me about your team management experience.",
        utterance_count=1,
        start_time=40.0,
        end_time=40.8,
        reason="final",
    )

    bundle = build_realtime_context_bundle(tracker, limit=5)

    assert bundle["primary_question"] == "Tell me about your team management experience."
    assert bundle["primary_question_source"] == "post_commit_interviewer_turns"
    assert bundle["carry_forward_reason"] == "new_interviewer_after_committed_answer"
    assert len(bundle["turns"]) == 1
    assert bundle["turns"][0]["speaker"] == "interviewer"
    assert bundle["turns"][0]["text"] == "Tell me about your team management experience."
    assert bundle["turns"][0]["start_time"] == 40.0
    assert bundle["turns"][0]["end_time"] == 40.8
