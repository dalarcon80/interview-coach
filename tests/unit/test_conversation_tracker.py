"""
Interview Coach - Unit Tests for Conversation Tracker
"""

from contracts.models import LiveAskSummary
from conversation.tracker import ConversationTracker
from pipeline.silence_detector import (
    build_realtime_context_bundle,
    resolve_realtime_context_bundle,
    select_realtime_active_turn_window,
)


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
    assert len(bundle["active_turns"]) == 1
    assert len(bundle["historical_turns"]) == 2
    assert len(bundle["source_turns"]) == 3
    assert bundle["turns"][0]["speaker"] == "interviewer"
    assert bundle["turns"][0]["text"] == "Tell me about your team management experience."
    assert bundle["turns"][0]["start_time"] == 40.0
    assert bundle["turns"][0]["end_time"] == 40.8
    assert bundle["active_ask_state"]["status"] == "open"


def test_build_realtime_context_bundle_keeps_only_latest_post_commit_interviewer_turn_active():
    tracker = ConversationTracker()

    assert tracker.add_turn(
        speaker="interviewer",
        text="With data, data strategy, working with data, and all of that, maybe summarize the type of position that you've had?",
        utterance_count=1,
        start_time=0.0,
        end_time=0.8,
        reason="final",
    )

    tracker.record_answer_committed(
        committed_at=5.0,
        question_key="with data, data strategy, working with data, and all of that, maybe summarize the type of position that you've had?",
        interviewer_generation=1,
    )

    assert tracker.add_turn(
        speaker="interviewer",
        text="Tell me a little bit more about Globant.",
        utterance_count=1,
        start_time=40.0,
        end_time=40.8,
        reason="final",
    )
    assert tracker.add_turn(
        speaker="interviewer",
        text="So does that mean that you work on projects yourself?",
        utterance_count=1,
        start_time=50.0,
        end_time=50.8,
        reason="final",
    )

    bundle = build_realtime_context_bundle(tracker, limit=5)

    assert bundle["primary_question"] == "So does that mean that you work on projects yourself?"
    assert bundle["primary_question_source"] == "post_commit_interviewer_turns"
    assert bundle["carry_forward_reason"] == "new_interviewer_after_committed_answer"
    assert len(bundle["turns"]) == 1
    assert len(bundle["active_turns"]) == 1
    assert len(bundle["historical_turns"]) == 2
    assert len(bundle["source_turns"]) == 3
    assert bundle["turns"][0]["text"] == "So does that mean that you work on projects yourself?"
    assert bundle["turns"][0]["start_time"] == 50.0
    assert bundle["turns"][0]["end_time"] == 50.8
    assert bundle["active_ask_state"]["status"] == "open"


def test_build_realtime_context_bundle_keeps_only_latest_post_freeze_interviewer_turn_active():
    tracker = ConversationTracker()

    assert tracker.add_turn(
        speaker="interviewer",
        text="Summarize the type of position that you've had.",
        utterance_count=1,
        start_time=0.0,
        end_time=0.8,
        reason="final",
    )

    tracker.record_active_ask_frozen(
        frozen_at=5.0,
        question_key="summarize the type of position that you've had.",
        interviewer_generation=1,
    )

    assert tracker.add_turn(
        speaker="interviewer",
        text="Tell me a little bit more about Globant.",
        utterance_count=1,
        start_time=40.0,
        end_time=40.8,
        reason="final",
    )
    assert tracker.add_turn(
        speaker="interviewer",
        text="So does that mean that you work on projects yourself?",
        utterance_count=1,
        start_time=50.0,
        end_time=50.8,
        reason="final",
    )

    bundle = build_realtime_context_bundle(tracker, limit=5)

    assert bundle["primary_question"] == "So does that mean that you work on projects yourself?"
    assert bundle["primary_question_source"] == "post_freeze_interviewer_turns"
    assert bundle["carry_forward_reason"] == "new_interviewer_after_frozen_answer"
    assert len(bundle["turns"]) == 1
    assert len(bundle["active_turns"]) == 1
    assert len(bundle["historical_turns"]) == 2
    assert len(bundle["source_turns"]) == 3
    assert bundle["turns"][0]["text"] == "So does that mean that you work on projects yourself?"
    assert bundle["turns"][0]["start_time"] == 50.0
    assert bundle["turns"][0]["end_time"] == 50.8
    assert bundle["active_ask_state"]["status"] == "open"


def test_build_realtime_context_bundle_keeps_only_latest_interviewer_turn_active_without_commit():
    tracker = ConversationTracker()

    assert tracker.add_turn(
        speaker="interviewer",
        text="Summarize the the type of, of position that you've that you've had.",
        utterance_count=1,
        start_time=0.0,
        end_time=0.8,
        reason="final",
    )
    assert tracker.add_turn(
        speaker="interviewer",
        text="Tell me a little bit more about Globant.",
        utterance_count=1,
        start_time=40.0,
        end_time=40.8,
        reason="final",
    )
    assert tracker.add_turn(
        speaker="interviewer",
        text="Okay. So does that mean that you work on on projects yourself?",
        utterance_count=1,
        start_time=50.0,
        end_time=50.8,
        reason="final",
    )

    bundle = build_realtime_context_bundle(tracker, limit=5)

    assert bundle["primary_question"] == "Okay. So does that mean that you work on on projects yourself?"
    assert bundle["primary_question_source"] == "latest_interviewer_turn"
    assert bundle["carry_forward_reason"] == ""
    assert len(bundle["turns"]) == 1
    assert len(bundle["active_turns"]) == 1
    assert len(bundle["historical_turns"]) == 2
    assert len(bundle["source_turns"]) == 3
    assert bundle["turns"][0]["text"] == "Okay. So does that mean that you work on on projects yourself?"
    assert bundle["turns"][0]["start_time"] == 50.0
    assert bundle["turns"][0]["end_time"] == 50.8
    assert bundle["active_ask_state"]["status"] == "open"


def test_build_realtime_context_bundle_keeps_latest_interviewer_block_without_commit():
    tracker = ConversationTracker()

    assert tracker.add_turn(
        speaker="interviewer",
        text="And then, also very curious to",
        utterance_count=1,
        start_time=0.0,
        end_time=0.5,
        reason="final",
    )
    assert tracker.add_turn(
        speaker="interviewer",
        text="to hear about your team management experience. How big were the teams you",
        utterance_count=2,
        start_time=0.6,
        end_time=1.1,
        reason="final",
    )
    assert tracker.add_turn(
        speaker="interviewer",
        text="kinda start telling us or telling me a little bit about you",
        utterance_count=3,
        start_time=1.2,
        end_time=1.7,
        reason="final",
    )

    bundle = build_realtime_context_bundle(tracker, limit=5)

    assert bundle["primary_question"] == (
        "And then, also very curious to\n"
        "to hear about your team management experience. How big were the teams you\n"
        "kinda start telling us or telling me a little bit about you"
    )
    assert bundle["primary_question_source"] == "latest_interviewer_block"
    assert bundle["carry_forward_reason"] == ""
    assert len(bundle["turns"]) == 3
    assert len(bundle["active_turns"]) == 3
    assert len(bundle["historical_turns"]) == 0
    assert len(bundle["source_turns"]) == 3
    assert bundle["turns"][0]["text"] == "And then, also very curious to"
    assert bundle["turns"][-1]["text"] == "kinda start telling us or telling me a little bit about you"
    assert bundle["active_ask_state"]["status"] == "open"


class _TimestampMsTracker:
    def get_last_n_turns(self, limit: int = 5):
        return [
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
        ][-limit:]


def test_build_realtime_context_bundle_uses_timestamp_ms_for_silence_boundaries():
    bundle = resolve_realtime_context_bundle(_TimestampMsTracker().get_last_n_turns(limit=5))

    assert bundle["primary_question"] == "Okay. So does that mean that you work on projects yourself?"
    assert bundle["primary_question_source"] == "latest_interviewer_turn"
    assert len(bundle["turns"]) == 1
    assert len(bundle["active_turns"]) == 1
    assert len(bundle["historical_turns"]) == 2


def test_select_realtime_active_turn_window_resets_after_long_silence():
    active_turns, context_bundle = select_realtime_active_turn_window(
        [
            {
                "speaker": "interviewer",
                "text": "I just wanted to talk a little bit about your experience with",
                "timestamp": "2026-04-10T11:52:27.395000",
                "timestamp_ms": 1_000,
            },
            {
                "speaker": "interviewer",
                "text": "with data, data strategy, with data, and and that kind of, you know, business intelligence, all of these things. So, maybe you can I see I mean, I've seen your resume, but maybe you can summarize the the type of, of position that you've that you've had?",
                "timestamp": "2026-04-10T11:52:45.023000",
                "timestamp_ms": 12_000,
            },
            {
                "speaker": "interviewer",
                "text": "Tell me a little bit more about Globant.",
                "timestamp": "2026-04-10T11:54:01.538000",
                "timestamp_ms": 78_000,
            },
        ],
        idle_close_sec=5.0,
    )

    assert [turn["text"] for turn in active_turns] == ["Tell me a little bit more about Globant."]
    assert active_turns[0]["timestamp_ms"] == 78_000
    assert context_bundle["primary_question"] == "Tell me a little bit more about Globant."
    assert context_bundle["historical_turn_count"] == 2


def test_select_realtime_active_turn_window_handles_newest_first_input():
    active_turns, context_bundle = select_realtime_active_turn_window(
        [
            {
                "speaker": "interviewer",
                "text": "Tell me a little bit more about Globant.",
                "timestamp": "2026-04-10T11:54:01.538000",
                "timestamp_ms": 78_000,
            },
            {
                "speaker": "interviewer",
                "text": "with data, data strategy, with data, and and that kind of, you know, business intelligence, all of these things. So, maybe you can I see I mean, I've seen your resume, but maybe you can summarize the the type of, of position that you've that you've had?",
                "timestamp": "2026-04-10T11:52:45.023000",
                "timestamp_ms": 12_000,
            },
            {
                "speaker": "interviewer",
                "text": "I just wanted to talk a little bit about your experience with",
                "timestamp": "2026-04-10T11:52:27.395000",
                "timestamp_ms": 1_000,
            },
        ],
        idle_close_sec=5.0,
    )

    assert [turn["text"] for turn in active_turns] == ["Tell me a little bit more about Globant."]
    assert active_turns[0]["timestamp_ms"] == 78_000
    assert context_bundle["primary_question"] == "Tell me a little bit more about Globant."
    assert context_bundle["historical_turn_count"] == 2
