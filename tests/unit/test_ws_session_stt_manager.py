"""Unit tests for session-scoped STT manager behavior in websocket pipeline."""

from datetime import datetime
import time
from unittest.mock import AsyncMock, MagicMock, ANY, patch

import pytest

from adapters.interfaces import TranscriptionEvent
from api.server import (
    LiveDisplayCaptionState,
    LiveFrozenSnapshot,
    LiveWarmCheckpoint,
    LiveWarmResult,
    SessionSTTStreamManager,
    _build_live_question_from_prepared_context,
)
from pipeline.steps.ask_normalizer import AskNormalizer
from pipeline.steps.live_question_planner import LiveQuestionPlanner
from contracts.models import (
    LiveAskSummary,
    LivePreparedContext,
    BrainPlan,
    BrainSnapshot,
    CompactEvidencePack,
    ComplexityClass,
    AnswerShape,
    AskBrief,
    AskFamily,
    AnswerContract,
)
from conversation.tracker import ConversationTracker
from pipeline.steps.turn_assembler import SpeakerTurn


class _FakeWebSocket:
    def __init__(self):
        self.events: list[dict] = []

    async def send_json(self, payload: dict):
        self.events.append(payload)


class _StreamingFakeSTTAdapter:
    """Queue-driven fake STT adapter for persistent stream tests."""

    def __init__(self):
        self.stream_audio_calls = 0
        self._event_queue: asyncio.Queue[TranscriptionEvent] = asyncio.Queue()
        self.downstream_completed_calls = 0
        self.terminal_failure_reasons: list[str] = []
        self.open_stream_calls: list[str] = []
        self.close_stream_calls: list[str] = []

    async def push_event(self, event: TranscriptionEvent):
        await self._event_queue.put(event)

    async def stream_audio(self, audio_chunks):
        self.stream_audio_calls += 1

        async def _consume_chunks():
            async for _ in audio_chunks:
                pass

        consumer_task = asyncio.create_task(_consume_chunks())
        try:
            while True:
                event = await self._event_queue.get()
                yield event
                if event.is_final:
                    break
        finally:
            consumer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await consumer_task

    def mark_downstream_complete(self):
        self.downstream_completed_calls += 1

    def mark_terminal_failure(self, reason: str):
        self.terminal_failure_reasons.append(reason)

    async def open_stream(self, session_id: str | None = None):
        self.open_stream_calls.append(str(session_id))

    async def close_stream(self, session_id: str | None = None):
        self.close_stream_calls.append(str(session_id))


import asyncio
import contextlib


def _pipeline_result(mode: str = "real"):
    result = MagicMock()
    result.question_analysis = MagicMock()
    result.question_analysis.primary_type = MagicMock()
    result.question_analysis.primary_type.value = "behavioral"
    result.question_analysis.is_compound = False
    result.question_analysis.sub_questions = []
    result.question_analysis.key_topics = ["leadership"]
    result.question_analysis.underlying_intent = ["assess leadership"]
    result.question_analysis.red_flags = []

    result.language_decision = MagicMock()
    result.language_decision.final_language = "en"

    result.exchange = MagicMock()
    result.exchange.suggested_response = MagicMock()
    result.exchange.suggested_response.mode = mode
    result.exchange.suggested_response.bullets = ["Led team initiatives"]
    result.exchange.suggested_response.full_response = "I led cross-functional team initiatives..."
    result.exchange.suggested_response.key_metrics = ["3 initiatives"]
    result.exchange.suggested_response.confidence = 0.9
    result.exchange.suggested_response.style_used = MagicMock()
    result.exchange.suggested_response.style_used.value = "executive"
    result.exchange.suggested_response.metadata = {
        "time_to_bullets_ms": 800,
        "time_to_full_ms": 1200,
        "provider": "anthropic",
        "model": "claude",
    }

    result.quality_result = MagicMock()
    result.quality_result.passed = True
    result.quality_result.score = 0.91
    result.quality_result.issues = []
    result.total_latency_ms = 1200
    result.mode = mode
    return result

def _shared_suggest_response(full_response: str = "Shared manual-quality answer") -> dict:
    return {
        "success": True,
        "mode": "real",
        "full_response": full_response,
        "bullets": ["Point 1"],
        "confidence": 0.9,
        "latency_ms": 1200,
        "quality": {"passed": True, "score": 0.91, "issues": []},
        "language": {"detected": "en"},
        "suggestion": {"style": "executive", "keyMetrics": []},
        "debug": {
            "normalized_family": "general",
            "normalized_primary_ask": "Tell me about your leadership experience",
            "normalized_secondary_asks": [],
            "normalized_answer_contract": "general_direct",
            "normalized_metrics_policy": "prefer_if_supported",
            "normalizer_confidence": 0.9,
            "fallback_used": False,
        },
    }


def _force_hard_silence(manager: SessionSTTStreamManager, *, extra_sec: float = 0.1) -> None:
    threshold_sec = max(manager._turn_assembler.state.silence_threshold_ms / 1000.0, 0.0)
    manager._last_interviewer_activity_at = time.time() - threshold_sec - extra_sec


def _build_live_pipeline_stub() -> MagicMock:
    pipeline = MagicMock()
    pipeline.process_question = AsyncMock(return_value=_pipeline_result("real"))
    pipeline.conversation_tracker = ConversationTracker()
    pipeline.ask_normalizer = AskNormalizer()
    pipeline.live_question_planner = LiveQuestionPlanner(pipeline.ask_normalizer)
    pipeline.session_state = MagicMock(
        interview_config={
            "delivery_mode": "manual",
            "style_id": "professional",
            "language_preference": "en",
            "max_words": 200,
            "candidate": {"name": "Test"},
            "company": {"companyName": "Test Co"},
            "interviewer": {"name": "Interviewer"},
        }
    )
    return pipeline


@pytest.mark.asyncio
async def test_session_stt_manager_reuses_single_stream_across_multiple_audio_messages():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()

    fake_adapter = _StreamingFakeSTTAdapter()
    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-1",
        default_mode="real",
    )
    manager._suggestion_debounce_sec = 0.0

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("adapters.stt_adapter.get_stt_adapter", AsyncMock(return_value=fake_adapter))

        await manager.enqueue_audio(b"chunk-1", "system")
        await manager.enqueue_audio(b"chunk-2", "system")

        await fake_adapter.push_event(
            TranscriptionEvent(
                text="Tell me about",
                is_final=False,
                confidence=0.61,
                language="en",
                speaker=None,
            )
        )
        await fake_adapter.push_event(
            TranscriptionEvent(
                text="Tell me about your leadership experience",
                is_final=True,
                confidence=0.94,
                language="en",
                speaker="interviewer",
                utterance_complete=True,
            )
        )

        await manager.stop()

    # Persistent session stream: one stream invocation despite multiple audio enqueues.
    assert fake_adapter.stream_audio_calls == 1
    assert fake_adapter.open_stream_calls == ["session-stt-1"]
    assert fake_adapter.close_stream_calls == ["session-stt-1"]

    transcript_events = [event for event in websocket.events if event.get("type") == "transcript"]
    assert len(transcript_events) == 1
    assert transcript_events[0]["is_final"] is True
    assert transcript_events[0]["speaker"] == "interviewer"
    assert transcript_events[0]["speaker_reason"] == "stt_label"
    pipeline.process_question.assert_not_awaited()
    assert fake_adapter.downstream_completed_calls == 0


@pytest.mark.asyncio
async def test_display_event_debounces_live_preparation_refresh_for_interviewer_captions():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-display-refresh",
        default_mode="real",
    )
    manager._latest_source = "system"
    manager._live_preparation_debounce_sec = 0.0
    manager._refresh_live_prepared_context = AsyncMock()

    await manager._handle_display_event(
        TranscriptionEvent(
            text="What are you looking for in terms of the company and culture?",
            is_final=False,
            confidence=0.91,
            language="en",
            speaker="interviewer",
        )
    )
    await asyncio.sleep(0.01)

    manager._refresh_live_prepared_context.assert_awaited_once()


@pytest.mark.asyncio
async def test_session_stt_manager_unknown_speaker_does_not_poison_interviewer_assembly():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-unknown",
        default_mode="real",
    )

    await manager._handle_transcription_event(
        TranscriptionEvent(
            text="Tell me",
            is_final=False,
            confidence=0.7,
            language="en",
            speaker="interviewer",
            utterance_complete=False,
        )
    )
    await manager._handle_transcription_event(
        TranscriptionEvent(
            text="Tell me about your",
            is_final=True,
            confidence=0.6,
            language="en",
            speaker=None,
            utterance_complete=True,
        )
    )
    await manager._handle_transcription_event(
        TranscriptionEvent(
            text="Tell me about your leadership experience",
            is_final=True,
            confidence=0.93,
            language="en",
            speaker="interviewer",
            utterance_complete=True,
        )
    )

    transcript_events = [event for event in websocket.events if event.get("type") == "transcript"]
    assert len(transcript_events) == 2
    assert transcript_events[0]["speaker"] == "interviewer"
    assert transcript_events[0]["speaker_attribution"] == "interviewer"
    assert transcript_events[0]["speaker_reason"] == "audio_source_system"


@pytest.mark.asyncio
async def test_session_stt_manager_uses_system_source_for_unknown_speaker_transcripts():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-system-source",
        default_mode="real",
    )
    manager._latest_source = "system"

    await manager._handle_transcription_event(
        TranscriptionEvent(
            text="What roles did they have?",
            is_final=True,
            confidence=0.72,
            language="en",
            speaker=None,
            utterance_complete=True,
        )
    )

    transcript_events = [event for event in websocket.events if event.get("type") == "transcript"]
    assert len(transcript_events) == 1
    assert transcript_events[0]["speaker"] == "interviewer"
    assert transcript_events[0]["speaker_attribution"] == "interviewer"
    assert transcript_events[0]["speaker_reason"] == "audio_source_system"


@pytest.mark.asyncio
async def test_session_stt_manager_deduplicates_fragmented_duplicate_final_turns():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-dedup",
        default_mode="real",
    )

    final_event = TranscriptionEvent(
        text="Walk me through your architecture decision",
        is_final=True,
        confidence=0.95,
        language="en",
        speaker="interviewer",
        utterance_complete=True,
    )

    await manager._handle_transcription_event(
        TranscriptionEvent(
            text="Walk me through",
            is_final=False,
            confidence=0.65,
            language="en",
            speaker="interviewer",
            utterance_complete=False,
        )
    )
    await manager._handle_transcription_event(final_event)
    await manager._handle_transcription_event(final_event)

    # Duplicate final emission within dedup window should not schedule a second downstream pass.
    assert len(pipeline.conversation_tracker.state.turn_history) == 1
    transcript_events = [event for event in websocket.events if event.get("type") == "transcript"]
    assert len(transcript_events) == 2


@pytest.mark.asyncio
async def test_system_final_transcript_becomes_live_completed_turn_without_utterance_complete():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-final-direct",
        default_mode="real",
    )
    manager._schedule_completed_turn_processing = MagicMock()
    manager._latest_source = "system"
    manager._interviewer_candidate_flush_sec = 0.0

    await manager._handle_transcription_event(
        TranscriptionEvent(
            text="Tell me about your experience building from zero",
            is_final=True,
            confidence=0.92,
            language="en",
            speaker=None,
            utterance_complete=False,
        )
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert len(pipeline.conversation_tracker.state.turn_history) == 1
    recorded_turn = pipeline.conversation_tracker.state.turn_history[0]
    assert recorded_turn["speaker"] == "interviewer"
    assert recorded_turn["text"] == "Tell me about your experience building from zero"
    manager._schedule_completed_turn_processing.assert_called_once()


@pytest.mark.asyncio
async def test_system_final_fragments_are_coalesced_into_single_live_turn():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-fragment-coalesce",
        default_mode="real",
    )
    manager._schedule_completed_turn_processing = MagicMock()
    manager._latest_source = "system"
    manager._interviewer_candidate_flush_sec = 0.0

    await manager._handle_transcription_event(
        TranscriptionEvent(
            text="Tell me about your experience",
            is_final=True,
            confidence=0.89,
            language="en",
            speaker=None,
            utterance_complete=False,
        )
    )
    await manager._handle_transcription_event(
        TranscriptionEvent(
            text="Tell me about your experience building from zero",
            is_final=True,
            confidence=0.93,
            language="en",
            speaker=None,
            utterance_complete=False,
        )
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert len(pipeline.conversation_tracker.state.turn_history) == 1
    recorded_turn = pipeline.conversation_tracker.state.turn_history[0]
    assert recorded_turn["text"] == "Tell me about your experience building from zero"
    manager._schedule_completed_turn_processing.assert_called_once()


@pytest.mark.asyncio
async def test_system_utterance_complete_signal_flushes_pending_live_candidate():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-signal-flush",
        default_mode="real",
    )
    manager._schedule_completed_turn_processing = MagicMock()
    manager._latest_source = "system"
    manager._interviewer_candidate_flush_sec = 10.0

    await manager._handle_transcription_event(
        TranscriptionEvent(
            text="What are you looking for in terms of",
            is_final=True,
            confidence=0.91,
            language="en",
            speaker=None,
            utterance_complete=False,
        )
    )
    assert len(pipeline.conversation_tracker.state.turn_history) == 0

    await manager._handle_transcription_event(
        TranscriptionEvent(
            text="",
            is_final=False,
            confidence=0.0,
            language="en",
            speaker=None,
            utterance_complete=True,
            event_type="utterance_end",
        )
    )

    assert len(pipeline.conversation_tracker.state.turn_history) == 1
    recorded_turn = pipeline.conversation_tracker.state.turn_history[0]
    assert recorded_turn["text"] == "What are you looking for in terms of"
    manager._schedule_completed_turn_processing.assert_called_once()


@pytest.mark.asyncio
async def test_silence_trigger_flush_records_latest_pending_live_candidate_immediately():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-silence-flush",
        default_mode="real",
    )
    manager._schedule_completed_turn_processing = MagicMock()
    manager._latest_source = "system"
    manager._interviewer_candidate_flush_sec = 10.0

    await manager._handle_transcription_event(
        TranscriptionEvent(
            text="kinda start telling us or telling me a little bit about you and",
            is_final=True,
            confidence=0.92,
            language="en",
            speaker=None,
            utterance_complete=False,
        )
    )
    assert len(pipeline.conversation_tracker.state.turn_history) == 0

    manager._flush_pending_interviewer_candidate_for_silence()

    assert len(pipeline.conversation_tracker.state.turn_history) == 1
    recorded_turn = pipeline.conversation_tracker.state.turn_history[0]
    assert recorded_turn["text"] == "kinda start telling us or telling me a little bit about you and"
    manager._schedule_completed_turn_processing.assert_called_once()


@pytest.mark.asyncio
async def test_interviewer_candidate_merges_consecutive_final_fragments_without_losing_context():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-merge-fragments",
        default_mode="real",
    )
    manager._schedule_completed_turn_processing = MagicMock()
    manager._latest_source = "system"
    manager._interviewer_candidate_flush_sec = 10.0

    await manager._handle_transcription_event(
        TranscriptionEvent(
            text="What roles did they have, etcetera. Yeah. And last question as as we go. So if you want, just",
            is_final=True,
            confidence=0.9,
            language="en",
            speaker=None,
            utterance_complete=False,
        )
    )
    await manager._handle_transcription_event(
        TranscriptionEvent(
            text="kinda start telling us or telling me a little bit about you and",
            is_final=True,
            confidence=0.91,
            language="en",
            speaker=None,
            utterance_complete=False,
        )
    )

    assert manager._interviewer_turn_candidate is not None
    assert "What roles did they have" in manager._interviewer_turn_candidate.text
    assert "kinda start telling us" in manager._interviewer_turn_candidate.text

    manager._flush_pending_interviewer_candidate_for_silence()

    assert len(pipeline.conversation_tracker.state.turn_history) == 1
    recorded_turn = pipeline.conversation_tracker.state.turn_history[0]
    assert "What roles did they have" in recorded_turn["text"]
    assert "kinda start telling us or telling me a little bit about you and" in recorded_turn["text"]


def test_live_turn_window_uses_recent_display_tail_when_no_final_arrived_yet():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-display-tail",
        default_mode="real",
    )
    manager._latest_source = "system"

    manager._merge_current_live_interviewer_block(
        text="What roles did they have, etcetera. Yeah. And last question as as we go. So if you want, just",
        event_time=1.0,
    )
    manager._update_interviewer_display_caption(
        text="kinda start telling us or telling me a little bit about you and",
        is_partial=True,
        utterance_complete=False,
        speaker="interviewer",
    )

    raw_turns = manager._get_raw_live_turn_window(limit=5)

    assert raw_turns
    assert "what roles did they have" in raw_turns[-1]["text"].lower()
    assert "telling me a little bit about you" in raw_turns[-1]["text"].lower()
    assert "kinda start telling us or telling me a little bit about you and" in raw_turns[-1]["text"]


def test_display_caption_state_accumulates_interviewer_fragments():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-display-accumulate",
        default_mode="real",
    )
    manager._latest_source = "system"

    manager._update_interviewer_display_caption(
        text="like, your expectations in terms of the role. And or not the role, but, yeah",
        is_partial=True,
        utterance_complete=False,
        speaker="interviewer",
    )
    manager._update_interviewer_display_caption(
        text=(
            "what you have done in your experience So now I just wanted to ask you, like, "
            "what are you looking for in terms of the company, the culture, teams?"
        ),
        is_partial=True,
        utterance_complete=False,
        speaker="interviewer",
    )
    manager._update_interviewer_display_caption(
        text="What's important for you, or what kind of things you absolutely like.",
        is_partial=False,
        utterance_complete=False,
        speaker="interviewer",
    )

    caption_text = manager._get_recent_interviewer_display_caption_text()

    assert "what are you looking for in terms of the company, the culture, teams?" in caption_text
    assert "what kind of things you absolutely like." in caption_text


def test_duplicate_display_caption_does_not_reset_interviewer_silence_anchor():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-display-no-anchor-reset",
        default_mode="real",
    )
    manager._latest_source = "system"

    manager._update_interviewer_display_caption(
        text="Tell me a bit about your leadership experience and the teams you've managed",
        is_partial=True,
        utterance_complete=False,
        speaker="interviewer",
    )
    first_anchor = manager._last_interviewer_activity_at

    manager._update_interviewer_display_caption(
        text="Tell me a bit about your leadership experience and the teams you've managed",
        is_partial=False,
        utterance_complete=False,
        speaker="interviewer",
    )

    assert manager._last_interviewer_activity_at == first_anchor


def test_non_material_display_caption_edit_still_updates_live_interviewer_block():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-display-non-material-edit",
        default_mode="real",
    )
    manager._latest_source = "system"

    manager._update_interviewer_display_caption(
        text="Tell me about the teams you've managed across regions",
        is_partial=True,
        utterance_complete=False,
        speaker="interviewer",
    )
    first_anchor = manager._last_interviewer_activity_at

    manager._update_interviewer_display_caption(
        text="Tell me about the teams you managed across regions",
        is_partial=False,
        utterance_complete=False,
        speaker="interviewer",
    )

    assert manager._last_interviewer_activity_at == first_anchor
    assert manager._current_live_interviewer_block is not None
    assert manager._current_live_interviewer_block.text == "Tell me about the teams you managed across regions"


def test_utterance_complete_final_caption_does_not_reanchor_silence_after_partial():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-display-no-reanchor-on-utterance-complete",
        default_mode="real",
    )
    manager._latest_source = "system"

    manager._update_interviewer_display_caption(
        text="Tell me about your experience building teams from zero and leading delivery",
        is_partial=True,
        utterance_complete=False,
        speaker="interviewer",
    )
    first_anchor = manager._last_interviewer_activity_at

    manager._update_interviewer_display_caption(
        text="Tell me about your experience building teams from zero and leading delivery across regions.",
        is_partial=False,
        utterance_complete=True,
        speaker="interviewer",
    )

    assert manager._last_interviewer_activity_at == first_anchor
    assert manager._get_recent_interviewer_display_caption_text().endswith("across regions.")


def test_display_caption_reconciles_overlapping_hypotheses_without_repetition():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-display-reconcile",
        default_mode="real",
    )
    manager._latest_source = "system"

    manager._update_interviewer_display_caption(
        text=(
            "Danielle, we were talking about, like, your expectations in terms of the role "
            "and or not the role, but, yeah, but, basically"
        ),
        is_partial=True,
        utterance_complete=False,
        speaker="interviewer",
    )
    manager._update_interviewer_display_caption(
        text=(
            "Danielle, we were talking about your expectations in terms of the role and what "
            "are you looking for in terms of the company, the culture, teams?"
        ),
        is_partial=False,
        utterance_complete=False,
        speaker="interviewer",
    )

    caption_text = manager._get_recent_interviewer_display_caption_text().lower()

    assert "what are you looking for in terms of the company, the culture, teams?" in caption_text
    assert caption_text.count("expectations in terms of the role") == 1


def test_live_interviewer_block_preserves_last_display_tail_even_after_caption_state_stales():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-display-tail-persists",
        default_mode="real",
    )
    manager._latest_source = "system"

    manager._update_interviewer_display_caption(
        text="What roles did they have, etcetera. Yeah. And last question as as we go. So if you want, just",
        is_partial=True,
        utterance_complete=False,
        speaker="interviewer",
    )
    manager._update_interviewer_display_caption(
        text="kinda start telling us or telling me a little bit about you, and then I'll ask as we go. Okay.",
        is_partial=False,
        utterance_complete=False,
        speaker="interviewer",
    )
    assert manager._latest_interviewer_display_caption is not None
    manager._latest_interviewer_display_caption.updated_at = 0.0

    semantic_window = manager._build_live_interviewer_semantic_window(limit=5)

    assert semantic_window
    lowered = semantic_window[-1]["text"].lower()
    assert "start telling us or telling me a little bit about you" in lowered
    assert "then i'll ask as we go. okay." in lowered


def test_interviewer_turn_candidate_reconciles_overlapping_final_hypotheses():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-turn-reconcile",
        default_mode="real",
    )

    completed = manager._update_interviewer_turn_candidate(
        "Danielle, we were talking about, like, your expectations in terms of the role",
        "interviewer",
        True,
        False,
    )
    assert completed is None

    completed = manager._update_interviewer_turn_candidate(
        (
            "Danielle, we were talking about your expectations in terms of the role and what "
            "are you looking for in terms of the company, the culture, teams?"
        ),
        "interviewer",
        True,
        False,
    )
    assert completed is None
    assert manager._interviewer_turn_candidate is not None

    candidate_text = manager._interviewer_turn_candidate.text.lower()
    assert "what are you looking for in terms of the company, the culture, teams?" in candidate_text
    assert candidate_text.count("expectations in terms of the role") == 1


def test_complete_interviewer_turn_candidate_prefers_richer_recent_display_caption_tail():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-complete-from-display-tail",
        default_mode="real",
    )
    manager._latest_source = "system"

    manager._update_interviewer_turn_candidate(
        "what are you looking for in terms of the company, the culture, teams? What's important for you, or what kind of things you absolutely",
        "interviewer",
        True,
        False,
    )
    manager._update_interviewer_display_caption(
        text="the company, the culture, teams? What's important for you, or what kind of things you absolutely don't like.",
        is_partial=False,
        utterance_complete=False,
        speaker="interviewer",
    )

    completed_text = manager._complete_interviewer_turn_candidate(reason="test_merge_recent_display_tail")

    assert completed_text is not None
    assert "don't like." in completed_text.lower()


def test_reconcile_streaming_interviewer_text_keeps_full_question_when_incoming_is_tail_fragment():
    current = (
        "Yeah. We were gonna talk about like, your expectations in terms of the role and or not the role. "
        "Yeah. So, basically, what you had done in your experience So now I just wanted to ask you, like, "
        "what are you looking for in terms of the company, the culture, team? What's important for you, "
        "or what kind of things you absolutely don't like?"
    )
    incoming = "you, or what kind of things you absolutely don't like?"

    reconciled = SessionSTTStreamManager._reconcile_streaming_interviewer_text(current, incoming)

    assert reconciled == current


def test_recent_display_caption_keeps_richer_accumulated_question_when_tail_arrives():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-display-tail-fragment",
        default_mode="real",
    )
    manager._latest_source = "system"

    full_text = (
        "Yeah. We were gonna talk about like, your expectations in terms of the role and or not the role. "
        "Yeah. So, basically, what you had done in your experience So now I just wanted to ask you, like, "
        "what are you looking for in terms of the company, the culture, team? What's important for you, "
        "or what kind of things you absolutely don't like?"
    )
    tail_text = "you, or what kind of things you absolutely don't like?"

    manager._update_interviewer_display_caption(
        text=full_text,
        is_partial=False,
        utterance_complete=False,
        speaker="interviewer",
    )
    manager._update_interviewer_display_caption(
        text=tail_text,
        is_partial=False,
        utterance_complete=False,
        speaker="interviewer",
    )

    assert manager._get_recent_interviewer_display_caption_text() == full_text


def test_live_turn_window_prefers_accumulated_display_caption_over_partial_tracker_turn():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-display-richer-than-tracker",
        default_mode="real",
    )
    manager._latest_source = "system"

    tracker = pipeline.conversation_tracker
    tracker.add_turn(
        speaker="interviewer",
        text="Danielle, we will talk",
        utterance_count=1,
        start_time=0.0,
        end_time=0.2,
        reason="final",
    )
    tracker.add_turn(
        speaker="interviewer",
        text=(
            "like, your expectations in terms of the role. And or not the role, but, yeah, "
            "but basically what you have done in your experience So now I just wanted to ask you, like"
        ),
        utterance_count=1,
        start_time=0.3,
        end_time=0.8,
        reason="final",
    )
    tracker.add_turn(
        speaker="interviewer",
        text="So now I just wanted to ask you, like, what are you looking for in terms of the company?",
        utterance_count=1,
        start_time=0.9,
        end_time=1.1,
        reason="final",
    )

    manager._update_interviewer_display_caption(
        text=(
            "like, your expectations in terms of the role. And or not the role, but, yeah, "
            "but basically what you have done in your experience So now I just wanted to ask you, like, "
            "what are you looking for in terms of the company, the culture, teams? What's important for you, "
            "or what kind of things you absolutely like."
        ),
        is_partial=False,
        utterance_complete=False,
        speaker="interviewer",
    )

    raw_turns = manager._get_raw_live_turn_window(limit=5)

    assert raw_turns
    merged_texts = [turn["text"] for turn in raw_turns]
    assert any("the company, the culture, teams?" in text for text in merged_texts)
    assert any("what kind of things you absolutely like" in text.lower() for text in merged_texts)


def test_live_interviewer_semantic_window_splits_blocks_on_large_time_gap():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-semantic-gap",
        default_mode="real",
    )
    manager._live_interviewer_block_gap_sec = 5.0

    manager._merge_current_live_interviewer_block(
        text="hear specifically examples of companies or experiences",
        event_time=10.0,
    )
    manager._merge_current_live_interviewer_block(
        text="that you've had where you had to build from 0",
        event_time=10.8,
    )
    manager._merge_current_live_interviewer_block(
        text="Now I wanna get a sense of your experience in building from scratch. Early stages.",
        event_time=18.5,
    )

    semantic_window = manager._get_raw_live_turn_window(limit=5)

    assert len(semantic_window) == 2
    assert "hear specifically examples" in semantic_window[0]["text"]
    assert "build from 0" in semantic_window[0]["text"]
    assert "building from scratch" in semantic_window[1]["text"]


def test_live_turn_window_prefers_richer_tracker_turns_over_truncated_semantic_window():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()
    tracker = pipeline.conversation_tracker

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-richer-tracker-window",
        default_mode="real",
    )

    tracker.add_turn(
        speaker="interviewer",
        text="Daniel, we were talk about So now I just wanted to ask you, like",
        utterance_count=1,
        start_time=0.0,
        end_time=0.5,
        reason="final",
    )
    tracker.add_turn(
        speaker="interviewer",
        text="like, your expectations in terms of the role and or not the role, yeah, but basically what you have done in your experience So now I just wanted to ask you, like, what are you looking for in terms of",
        utterance_count=2,
        start_time=0.6,
        end_time=1.2,
        reason="final",
    )
    tracker.add_turn(
        speaker="interviewer",
        text="the company, the culture, teams? What's important for you, or what kind of things you absolutely like.",
        utterance_count=3,
        start_time=1.3,
        end_time=2.0,
        reason="final",
    )

    manager._completed_live_interviewer_blocks = [
        {
            "speaker": "interviewer",
            "text": "Daniel, we were talk about So now I just wanted to ask you, like",
        },
        {
            "speaker": "interviewer",
            "text": "like, your expectations in terms of the role and or not the role, yeah, but basically what you have done in your experience So now I just wanted to ask you, like, what are you looking for",
        },
        {
            "speaker": "interviewer",
            "text": "what are you looking for in terms of the company, the",
        },
    ]

    raw_turns = manager._get_raw_live_turn_window(limit=5)

    assert len(raw_turns) == 3
    assert "the company, the culture, teams?" in raw_turns[-1]["text"]
    assert "what kind of things you absolutely like" in raw_turns[-1]["text"].lower()
    assert "what are you looking for in terms of" in raw_turns[1]["text"]


def test_live_turn_window_uses_conversation_history_as_source_of_truth():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()
    tracker = pipeline.conversation_tracker

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-richer-semantic-window",
        default_mode="real",
    )

    tracker.add_turn(
        speaker="interviewer",
        text="We were talking about, like, your expectations in terms of the role",
        utterance_count=1,
        start_time=0.0,
        end_time=0.8,
        reason="final",
    )
    tracker.add_turn(
        speaker="interviewer",
        text=(
            "and or not the role, but, yeah, but, basically, what you have done in your experience "
            "to now I just wanted to ask you, like, what are you looking for in terms of"
        ),
        utterance_count=2,
        start_time=0.5,
        end_time=1.0,
        reason="final",
    )
    tracker.add_turn(
        speaker="interviewer",
        text="the company, the culture, teams? What's important for you, or what kind of things you absolutely don't like.",
        utterance_count=3,
        start_time=1.1,
        end_time=1.8,
        reason="final",
    )

    manager._completed_live_interviewer_blocks = [
        {
            "speaker": "interviewer",
            "text": "noisy semantic block that should not replace the stored turn history",
        },
        {
            "speaker": "interviewer",
            "text": "another noisy semantic block",
        },
    ]

    raw_turns = manager._get_raw_live_turn_window(limit=5)

    assert len(raw_turns) == 3
    assert "expectations in terms of the role" in raw_turns[0]["text"]
    assert "what kind of things you absolutely don't like" in raw_turns[-1]["text"].lower()


def test_ui_equivalent_transcript_history_matches_frontend_rolling_consolidation():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-ui-transcript-history",
        default_mode="real",
    )

    manager._record_ui_equivalent_transcript_entry(
        text="Daniel, we will talk about like, your expectations in terms of",
        speaker="interviewer",
        is_final=True,
        timestamp_ms=1_000,
    )
    manager._record_ui_equivalent_transcript_entry(
        text="the company, the culture, teams? What's important for you",
        speaker="interviewer",
        is_final=True,
        timestamp_ms=4_000,
    )
    manager._record_ui_equivalent_transcript_entry(
        text="or what kind of things you absolutely don't like.",
        speaker="interviewer",
        is_final=True,
        timestamp_ms=9_500,
    )

    raw_turns = manager._get_ui_equivalent_transcript_window(limit=5)

    assert len(raw_turns) == 2
    assert (
        raw_turns[0]["text"]
        == "Daniel, we will talk about like, your expectations in terms of the company, the culture, teams? What's important for you"
    )
    assert raw_turns[1]["text"] == "or what kind of things you absolutely don't like."


def test_live_turn_window_prefers_ui_equivalent_transcript_history_over_tracker_fragments():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()
    tracker = pipeline.conversation_tracker

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-ui-source-of-truth",
        default_mode="real",
    )

    tracker.add_turn(
        speaker="interviewer",
        text="and or not the role, but, yeah, but, basically, what you have done in",
        utterance_count=1,
        start_time=0.0,
        end_time=0.6,
        reason="final",
    )
    tracker.add_turn(
        speaker="interviewer",
        text="in your experience. So now I just wanted to ask you, like",
        utterance_count=2,
        start_time=0.7,
        end_time=1.3,
        reason="final",
    )
    tracker.add_turn(
        speaker="interviewer",
        text="what are you looking for in terms of",
        utterance_count=3,
        start_time=1.4,
        end_time=1.9,
        reason="final",
    )

    manager._record_ui_equivalent_transcript_entry(
        text=(
            "Daniel, we will talk about like, your expectations in terms of the role, "
            "and or not the role, but, yeah, but, basically, what you have done in in your experience. "
            "So now I just wanted to ask you, like, what are you looking for in terms of"
        ),
        speaker="interviewer",
        is_final=True,
        timestamp_ms=1_000,
    )
    manager._record_ui_equivalent_transcript_entry(
        text=(
            "the company, the culture, teams? What's important for you, or what kind of things you absolutely don't like."
        ),
        speaker="interviewer",
        is_final=True,
        timestamp_ms=7_000,
    )

    raw_turns = manager._get_raw_live_turn_window(limit=5)

    assert len(raw_turns) == 2
    assert raw_turns[0]["text"].startswith("Daniel, we will talk about like, your expectations")
    assert raw_turns[1]["text"] == (
        "the company, the culture, teams? What's important for you, or what kind of things you absolutely don't like."
    )


def test_live_turn_window_keeps_newer_ui_followup_tail_when_tracker_window_is_longer_but_older():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()
    tracker = pipeline.conversation_tracker

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-ui-newer-tail-merge",
        default_mode="real",
    )

    tracker_turns = [
        "building a product from 0, a team from 0,",
        "Now I wanna get a sense of your experience in building from 0, building",
        "in building from 0, building from scratch. Early stages.",
        "also very curious to hear about your team management experience. How big were the team How big were the teams you've managed? What",
        "What roles they have, etcetera. Yeah. And last question,",
    ]
    for idx, text in enumerate(tracker_turns, start=1):
        tracker.add_turn(
            speaker="interviewer",
            text=text,
            utterance_count=idx,
            start_time=float(idx * 5),
            end_time=float(idx * 5) + 0.5,
            reason="final",
        )

    ui_turns = [
        "They have a terrible cough. That won't go away. But I was hear specifically examples of companies or experiences that you",
        "had where you had to build from 0, whether it was",
        "building a product from 0, a team from 0, a service from Xero, Now I wanna get a sense of your experience in building from 0, building from scratch. Early stages.",
        "And then also very curious to hear about your team management experience. How big were the teams you've managed?",
        "What roles they have, etcetera. Yeah. And last question,",
        "as we go. So if you want just kinda start telling us or telling me a little bit about you.",
    ]
    for idx, text in enumerate(ui_turns, start=1):
        manager._record_ui_equivalent_transcript_entry(
            text=text,
            speaker="interviewer",
            is_final=True,
            timestamp_ms=idx * 8_000,
        )

    raw_turns = manager._get_raw_live_turn_window(limit=5)

    assert len(raw_turns) == 5
    assert "what roles they have" in raw_turns[-2]["text"].lower()
    assert "little bit about you" in raw_turns[-1]["text"].lower()


def test_build_live_brain_snapshot_v3_coalesces_fragmented_interviewer_turns():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-brain-coalesced",
        default_mode="real",
    )

    manager._get_raw_live_turn_window = lambda limit=5: [
        {"speaker": "interviewer", "text": "just wanted to ask you, like"},
        {"speaker": "interviewer", "text": "what are you looking for in terms of"},
        {"speaker": "interviewer", "text": "the company, the culture, teams? What's important for you? Or what kind of things you absolutely don't mind?"},
    ]

    snapshot = manager._build_live_brain_snapshot_v3(limit=5)

    assert snapshot is not None
    assert len(snapshot.conversation_history) == 3
    lowered = snapshot.snapshot_text.lower()
    assert "what are you looking for in terms of" in lowered
    assert "the company, the culture, teams?" in lowered
    assert "what kind of things you absolutely don't mind?" in snapshot.snapshot_text.lower()


def test_build_live_brain_snapshot_v3_preserves_accumulated_context_when_completed_turns_overlap():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-brain-overlap",
        default_mode="real",
    )

    manager._get_raw_live_turn_window = lambda limit=5: [
        {
            "speaker": "interviewer",
            "text": (
                "Now I wanna get a sense of your experience in building from 0, building from scratch. "
                "Early stages. And then, also very curious to hear about your team management experience."
            ),
        },
        {
            "speaker": "interviewer",
            "text": "How big were the teams you've managed? What roles did they have, etcetera.",
        },
        {
            "speaker": "interviewer",
            "text": "What roles did they have, etcetera. Yeah. And last question as as we go. So if you want, just kind of start telling us",
        },
    ]

    snapshot = manager._build_live_brain_snapshot_v3(limit=5)

    assert snapshot is not None
    assert len(snapshot.conversation_history) == 3
    lowered = snapshot.snapshot_text.lower()
    assert "building from 0" in lowered
    assert "how big were the teams you've managed?" in lowered
    assert "what roles did they have" in lowered
    assert "start telling us" in lowered


def test_build_live_brain_snapshot_v3_uses_conversation_history_as_brain_source_of_truth():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()
    tracker = pipeline.conversation_tracker

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-brain-semantic-source",
        default_mode="real",
    )

    tracker.add_turn(
        speaker="interviewer",
        text=(
            "Now I wanna get a sense of your experience in building from 0, building from scratch. "
            "Early stages. And then, also very curious to hear about your team management experience."
        ),
        utterance_count=1,
        start_time=0.0,
        end_time=0.8,
        reason="final",
    )
    tracker.add_turn(
        speaker="interviewer",
        text="How big were the teams you've managed? What roles did they have, etcetera.",
        utterance_count=2,
        start_time=0.9,
        end_time=1.6,
        reason="final",
    )
    tracker.add_turn(
        speaker="interviewer",
        text="What roles did they have, etcetera. Yeah. And last question as as we go. So if you want, just kind of start telling us",
        utterance_count=3,
        start_time=1.5,
        end_time=2.2,
        reason="final",
    )

    manager._completed_live_interviewer_blocks = [
        {
            "speaker": "interviewer",
            "text": "semantic block should not override conversation history",
        }
    ]

    snapshot = manager._build_live_brain_snapshot_v3(limit=5)

    assert snapshot is not None
    lowered = snapshot.snapshot_text.lower()
    assert "building from 0" in lowered
    assert "team management experience" in lowered
    assert "how big were the teams you've managed?" in lowered
    assert "start telling us" in lowered


def test_build_live_brain_snapshot_v3_preserves_last_five_tracker_turns_without_semantic_rewrite():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()
    tracker = pipeline.conversation_tracker

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-brain-last-five",
        default_mode="real",
    )

    turns = [
        "Sorry. I have a terrible cough, and that won't go away. But I was hear specifically examples of",
        "companies or experiences that you've had where you had to build from 0. Whether it was building a product from 0, a team from 0, a a service from Xero.",
        "Now I wanna get a sense of your experience in building from 0 building from scratch. Early stages.",
        "And then also very curious to hear about your team management experience. Big were the teams you've managed?",
        "What roles did they have, etcetera. Yeah. And last question as as we go. So if you want, just kinda start telling us or telling me a little bit about you.",
    ]
    for idx, text in enumerate(turns, start=1):
        tracker.add_turn(
            speaker="interviewer",
            text=text,
            utterance_count=idx,
            start_time=float(idx),
            end_time=float(idx) + 0.5,
            reason="final",
        )

    manager._completed_live_interviewer_blocks = [
        {"speaker": "interviewer", "text": "semantic block should not override tracker history"}
    ]

    snapshot = manager._build_live_brain_snapshot_v3(limit=5)

    assert snapshot is not None
    assert len(snapshot.conversation_history) == 5
    for actual, expected in zip(
        [turn["text"] for turn in snapshot.conversation_history],
        turns,
        strict=True,
    ):
        assert actual.rstrip(".") == expected.rstrip(".")
    assert "what roles did they have, etcetera" in snapshot.conversation_history[-1]["text"].lower()
    assert "little bit about you" in snapshot.conversation_history[-1]["text"].lower()


def test_build_live_brain_snapshot_v3_prefers_ui_equivalent_transcript_history_for_last_followup():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()
    tracker = pipeline.conversation_tracker

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-brain-ui-followup",
        default_mode="real",
    )

    tracker.add_turn(
        speaker="interviewer",
        text="And then, also very curious to",
        utterance_count=1,
        start_time=0.0,
        end_time=0.5,
        reason="final",
    )
    tracker.add_turn(
        speaker="interviewer",
        text="to hear about your team management experience. How big were the teams you",
        utterance_count=2,
        start_time=0.6,
        end_time=1.1,
        reason="final",
    )
    tracker.add_turn(
        speaker="interviewer",
        text="kinda start telling us or telling me a little bit about you",
        utterance_count=3,
        start_time=1.2,
        end_time=1.7,
        reason="final",
    )

    manager._record_ui_equivalent_transcript_entry(
        text=(
            "companies or experiences that you've had where you had to build from 0. "
            "Whether it was building a product from 0, a team from 0, a a service from 0. "
            "Now I wanna get a sense of your experience in building from 0, building from scratch. Early stages."
        ),
        speaker="interviewer",
        is_final=True,
        timestamp_ms=1_000,
    )
    manager._record_ui_equivalent_transcript_entry(
        text="And then, also very curious to hear about your team management experience. How big were the teams you've managed?",
        speaker="interviewer",
        is_final=True,
        timestamp_ms=7_000,
    )
    manager._record_ui_equivalent_transcript_entry(
        text="What roles did they have, etcetera. Yeah. And last question as as we go. So if you want, just kinda start telling us or telling me a little bit about you.",
        speaker="interviewer",
        is_final=True,
        timestamp_ms=13_000,
    )

    snapshot = manager._build_live_brain_snapshot_v3(limit=5)

    assert snapshot is not None
    assert len(snapshot.conversation_history) == 3
    assert snapshot.conversation_history[1]["text"] == (
        "And then, also very curious to hear about your team management experience. How big were the teams you've managed?"
    )
    assert snapshot.conversation_history[2]["text"].rstrip(".") == (
        "What roles did they have, etcetera. Yeah. And last question as as we go. So if you want, just kinda start telling us or telling me a little bit about you"
    )


def test_build_live_brain_snapshot_v3_prefers_richer_tracker_turn_when_ui_equivalent_last_turn_is_truncated():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()
    tracker = pipeline.conversation_tracker

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-brain-ui-truncated-last-turn",
        default_mode="real",
    )

    tracker_turns = [
        "So, yeah, so I guess, Daniel, in terms of your experience, I would like to hear specifically",
        "sorry. I have a terrible cough, and that won't go away. But I was hear specifically examples of companies or experiences that you've had where you had to build",
        "from 0, whether it was building a product from 0 a team from Siro, a service from Xero, Now I wanna get a sense of your experience in building from 0, building from scratch. Early stages.",
        "And then also very curious to hear about your team management experience. How big were the teams you've managed?",
        "What roles they have, etcetera. Yeah. And last question as as we go. So if you want, just kind of start telling us or telling me a little bit about you.",
    ]
    for idx, text in enumerate(tracker_turns, start=1):
        tracker.add_turn(
            speaker="interviewer",
            text=text,
            utterance_count=idx,
            start_time=float(idx),
            end_time=float(idx) + 0.5,
            reason="final",
        )

    for idx, text in enumerate(tracker_turns[:-1], start=1):
        manager._record_ui_equivalent_transcript_entry(
            text=text,
            speaker="interviewer",
            is_final=True,
            timestamp_ms=idx * 1_000,
        )
    manager._record_ui_equivalent_transcript_entry(
        text="What roles they have, etcetera.",
        speaker="interviewer",
        is_final=True,
        timestamp_ms=9_000,
    )

    snapshot = manager._build_live_brain_snapshot_v3(limit=5)

    assert snapshot is not None
    assert len(snapshot.conversation_history) == 5
    assert snapshot.conversation_history[-1]["text"].rstrip(".") == tracker_turns[-1].rstrip(".")
    assert "little bit about you" in snapshot.conversation_history[-1]["text"].lower()


def test_live_turn_window_keeps_ui_history_but_enriches_last_turn_from_semantic_tail():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-ui-history-semantic-tail",
        default_mode="real",
    )
    manager._latest_source = "system"

    manager._record_ui_equivalent_transcript_entry(
        text=(
            "Companies or experiences that you had where you had to build from 0, whether it was "
            "building a product from 0, a team from 0, a service from zero."
        ),
        speaker="interviewer",
        is_final=True,
        timestamp_ms=1_000,
    )
    manager._record_ui_equivalent_transcript_entry(
        text=(
            "What roles did they have, etcetera. Yeah. And last question as as we go. "
            "So if you want, just"
        ),
        speaker="interviewer",
        is_final=True,
        timestamp_ms=9_000,
    )

    manager._merge_current_live_interviewer_block(
        text=(
            "What roles did they have, etcetera. Yeah. And last question as as we go. "
            "So if you want, just start telling us or telling me a little bit about you, and then"
        ),
        event_time=20.0,
    )

    raw_turns = manager._get_raw_live_turn_window(limit=5)

    assert len(raw_turns) == 2
    assert "build from 0" in raw_turns[0]["text"].lower()
    assert "what roles did they have" in raw_turns[1]["text"].lower()
    assert "little bit about you" in raw_turns[1]["text"].lower()
    assert raw_turns[1].get("live_tail_augmented") is True


def test_live_turn_window_appends_followup_tail_when_semantic_window_has_newer_extra_turn():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-ui-history-followup-tail",
        default_mode="real",
    )
    manager._latest_source = "system"

    manager._record_ui_equivalent_transcript_entry(
        text=(
            "Companies or experiences that you had where you had to build from 0, whether it was "
            "building a product from 0, a team from 0, a service from zero."
        ),
        speaker="interviewer",
        is_final=True,
        timestamp_ms=1_000,
    )
    manager._record_ui_equivalent_transcript_entry(
        text=(
            "What roles did they have, etcetera. Yeah. And last question as as we go. "
            "So if you want, just"
        ),
        speaker="interviewer",
        is_final=True,
        timestamp_ms=9_000,
    )

    manager._completed_live_interviewer_blocks = [
        {
            "speaker": "interviewer",
            "text": (
                "What roles did they have, etcetera. Yeah. And last question as as we go. "
                "So if you want, just"
            ),
            "timestamp": datetime.utcnow().isoformat(),
        },
        {
            "speaker": "interviewer",
            "text": "start telling us or telling me a little bit about you, and then",
            "timestamp": datetime.utcnow().isoformat(),
        },
    ]

    raw_turns = manager._get_raw_live_turn_window(limit=5)

    assert len(raw_turns) == 3
    assert "build from 0" in raw_turns[0]["text"].lower()
    assert "what roles did they have" in raw_turns[1]["text"].lower()
    assert "little bit about you" in raw_turns[2]["text"].lower()
    assert raw_turns[2].get("live_tail_augmented") is True


def test_build_live_brain_snapshot_v3_uses_post_commit_follow_up_as_active_context():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()
    tracker = pipeline.conversation_tracker

    for idx, (text, start_time) in enumerate(
        [
            ("What are you looking for in terms of the company?", 0.0),
            ("What do you absolutely not like?", 2.0),
            ("Tell me about your team management experience.", 40.0),
        ],
        start=1,
    ):
        accepted = tracker.add_turn(
            speaker="interviewer",
            text=text,
            utterance_count=1,
            start_time=start_time,
            end_time=start_time + 0.8,
            reason="final",
        )
        assert accepted is True

    tracker.record_answer_committed(
        committed_at=5.0,
        question_key="what are you looking for in terms of the company?",
        interviewer_generation=1,
    )

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-post-commit-followup",
        default_mode="real",
    )
    manager._latest_interviewer_generation = 2
    manager._get_raw_live_turn_window = MagicMock(return_value=tracker.get_last_n_turns(limit=10))

    snapshot = manager._build_live_brain_snapshot_v3(limit=5)

    assert snapshot is not None
    assert snapshot.snapshot_text == "Tell me about your team management experience."
    assert len(snapshot.conversation_history) == 1
    assert snapshot.conversation_history[0]["speaker"] == "interviewer"
    assert snapshot.conversation_history[0]["text"] == "Tell me about your team management experience."


def test_live_snapshot_is_current_rejects_changed_brain_snapshot_hash():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-snapshot-currentness",
        default_mode="real",
    )

    snapshot = LiveFrozenSnapshot(
        raw_turn_window=[{"speaker": "interviewer", "text": "Tell me about yourself"}],
        turn_window=[{"speaker": "interviewer", "text": "Tell me about yourself"}],
        raw_context_bundle={},
        signature="old-brain-hash",
        question_text="Tell me about yourself",
        conversation_history=[{"speaker": "interviewer", "text": "Tell me about yourself"}],
        prepared_context=None,
        request_payload={"question": "Tell me about yourself"},
        question_source="live_brain_v4",
        cache_hit=False,
        brain_snapshot=BrainSnapshot(
            session_id="session-stt-live-snapshot-currentness",
            utterance_id="u-1",
            revision_id=1,
            snapshot_text="Tell me about yourself",
            conversation_history=[{"speaker": "interviewer", "text": "Tell me about yourself"}],
            snapshot_hash="old-brain-hash",
            timestamp=datetime.utcnow(),
        ),
    )

    manager._get_raw_live_turn_window = lambda limit=5: [
        {"speaker": "interviewer", "text": "Tell me about yourself and your team management experience"}
    ]

    assert manager._live_snapshot_is_current(
        snapshot=snapshot,
        planner=None,
        generation_token=None,
        tracker=None,
    ) is False


@pytest.mark.asyncio
async def test_auto_silence_v3_waits_for_stabilization_and_prefers_richer_snapshot():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-v3-stabilization",
        default_mode="real",
    )
    manager._live_brain_v3_enabled = True
    manager._live_question_stabilization_sec = 0.0
    manager._silence_detector.should_trigger_suggestion = MagicMock(return_value=True)
    manager._silence_detector.record_trigger = MagicMock()
    manager._silence_detector.get_remaining_cooldown = MagicMock(return_value=0.0)

    partial_plan = BrainPlan(
        resolved_question="what are you looking for in terms of the company, the culture, teams?",
        ordered_asks=["what are you looking for in terms of the company, the culture, teams?"],
        raw_detected_asks=[
            "what are you looking for in terms of the company, the culture, teams?",
            "What's important for you?",
            "Or",
        ],
        coverage_points=["company", "culture", "teams"],
        question_completeness="partial",
        response_shape="direct_structured",
        directness="balanced",
        include_profile_opening=False,
        evidence_depth="medium",
        metrics_policy="avoid_unless_helpful",
        company_context_policy="support_if_relevant",
        candidate_context_policy="required",
        ordered_coverage_required=True,
        target_length=170,
        draft_answer="",
        serve_mode="finalize_from_plan",
        confidence=0.35,
        stability_state="stable",
        plan_source="safe_fallback",
        dropped_noise_clauses=["Or"],
    )
    partial_brain_snapshot = BrainSnapshot(
        session_id="session-stt-live-v3-stabilization",
        utterance_id="u-1",
        revision_id=1,
        snapshot_text=(
            "just wanted to ask you, like what are you looking for in terms of the company, the culture, teams? "
            "What's important for you? Or"
        ),
        conversation_history=[
            {
                "speaker": "interviewer",
                "text": "just wanted to ask you, like what are you looking for in terms of the company, the culture, teams? What's important for you? Or",
            }
        ],
        snapshot_hash="partial-hash",
        timestamp=datetime.utcnow(),
    )
    partial_snapshot = LiveFrozenSnapshot(
        raw_turn_window=[
            {"speaker": "interviewer", "text": "just wanted to ask you, like"},
            {"speaker": "interviewer", "text": "what are you looking for in terms of"},
            {"speaker": "interviewer", "text": "the company, the culture, teams? What's important for you? Or"},
        ],
        turn_window=[
            {"speaker": "interviewer", "text": "just wanted to ask you, like"},
            {"speaker": "interviewer", "text": "what are you looking for in terms of"},
            {"speaker": "interviewer", "text": "the company, the culture, teams? What's important for you? Or"},
        ],
        raw_context_bundle={},
        signature="partial-hash",
        question_text="what are you looking for in terms of the company, the culture, teams?",
        conversation_history=partial_brain_snapshot.conversation_history,
        prepared_context=None,
        request_payload={"question": "what are you looking for in terms of the company, the culture, teams?"},
        question_source="live_brain_v4",
        cache_hit=False,
        checkpoint_id="checkpoint-partial",
        question_key="partial-key",
        brain_snapshot=partial_brain_snapshot,
        brain_plan=partial_plan,
        compact_evidence_pack=CompactEvidencePack(plan_hash="partial-plan-hash", mode="minimal"),
        plan_hash="partial-plan-hash",
    )

    complete_plan = BrainPlan(
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
        raw_detected_asks=[
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
        stability_state="stable",
        plan_source="safe_fallback",
    )
    complete_brain_snapshot = BrainSnapshot(
        session_id="session-stt-live-v3-stabilization",
        utterance_id="u-2",
        revision_id=2,
        snapshot_text=(
            "just wanted to ask you, like what are you looking for in terms of the company, the culture, teams? "
            "What's important for you? Or what kind of things you absolutely don't mind?"
        ),
        conversation_history=[
            {
                "speaker": "interviewer",
                "text": "just wanted to ask you, like what are you looking for in terms of the company, the culture, teams? What's important for you? Or what kind of things you absolutely don't mind?",
            }
        ],
        snapshot_hash="complete-hash",
        timestamp=datetime.utcnow(),
    )
    complete_snapshot = LiveFrozenSnapshot(
        raw_turn_window=[
            {"speaker": "interviewer", "text": "just wanted to ask you, like"},
            {"speaker": "interviewer", "text": "what are you looking for in terms of"},
            {"speaker": "interviewer", "text": "the company, the culture, teams? What's important for you? Or what kind of things you absolutely don't mind?"},
        ],
        turn_window=[
            {"speaker": "interviewer", "text": "just wanted to ask you, like"},
            {"speaker": "interviewer", "text": "what are you looking for in terms of"},
            {"speaker": "interviewer", "text": "the company, the culture, teams? What's important for you? Or what kind of things you absolutely don't mind?"},
        ],
        raw_context_bundle={},
        signature="complete-hash",
        question_text=(
            "what are you looking for in terms of the company, the culture, teams?\n"
            "Also cover:\n"
            "- What's important for you?\n"
            "- what kind of things you absolutely don't mind?"
        ),
        conversation_history=complete_brain_snapshot.conversation_history,
        prepared_context=None,
        request_payload={"question": "what are you looking for in terms of the company, the culture, teams?"},
        question_source="live_brain_v4",
        cache_hit=False,
        checkpoint_id="checkpoint-complete",
        question_key="complete-key",
        brain_snapshot=complete_brain_snapshot,
        brain_plan=complete_plan,
        compact_evidence_pack=CompactEvidencePack(plan_hash="complete-plan-hash", mode="full"),
        plan_hash="complete-plan-hash",
    )

    manager._build_live_frozen_snapshot = AsyncMock(side_effect=[partial_snapshot, complete_snapshot])
    manager._live_snapshot_is_current = MagicMock(return_value=True)
    captured_snapshot: dict[str, LiveFrozenSnapshot] = {}

    async def _fake_generate_live_response_from_snapshot(
        *,
        snapshot,
        planner,
        tracker,
        interview_config,
        activity_epoch_at_trigger=None,
    ):
        captured_snapshot["value"] = snapshot
        return (
            {
                "mode": "real",
                "path_used": "brain_finalize_from_plan",
                "suggestion": {"full_response": "answer", "bullets": ["answer"], "confidence": 0.8},
                "quality": {"passed": True, "score": 0.9, "issues": []},
                "language": {"detected": "en", "confidence": 1.0},
                "debug": {"fallback_used": True},
            },
            "brain_finalize_from_plan",
            0,
            0,
            False,
        )

    manager._generate_live_response_from_snapshot = _fake_generate_live_response_from_snapshot  # type: ignore[method-assign]

    turn = SpeakerTurn(
        speaker="interviewer",
        text="What are you looking for in terms of the company, the culture, teams? What's important for you? Or what kind of things you absolutely don't mind?",
        start_time=0.0,
        end_time=4.0,
        utterances=["What are you looking for in terms of the company, the culture, teams? What's important for you? Or what kind of things you absolutely don't mind?"],
        language="en",
        metadata={},
        completion_reason="utterance_complete",
        is_complete=True,
    )

    _force_hard_silence(manager)
    await manager._try_auto_trigger_suggestion(turn, generation_token=1)

    assert manager._build_live_frozen_snapshot.await_count == 2
    assert captured_snapshot["value"].brain_plan is not None
    assert captured_snapshot["value"].brain_plan.question_completeness == "complete"
    assert len(captured_snapshot["value"].brain_plan.ordered_asks) == 3


@pytest.mark.asyncio
async def test_auto_silence_rebuilds_stale_snapshot_before_emitting_response():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-stale-rebuild",
        default_mode="real",
    )
    manager._silence_detector.should_trigger_suggestion = MagicMock(return_value=True)
    manager._silence_detector.record_trigger = MagicMock()
    manager._silence_detector.record_completion = MagicMock()
    manager._silence_detector.get_remaining_cooldown = MagicMock(return_value=0.0)

    stale_snapshot = LiveFrozenSnapshot(
        raw_turn_window=[{"speaker": "interviewer", "text": "What roles did they have?"}],
        turn_window=[{"speaker": "interviewer", "text": "What roles did they have?"}],
        raw_context_bundle={},
        signature="stale-signature",
        question_text="What roles did they have?",
        conversation_history=[{"speaker": "interviewer", "text": "What roles did they have?"}],
        prepared_context=None,
        request_payload={"question": "What roles did they have?"},
        question_source="live_brain_v4",
        cache_hit=False,
        checkpoint_id="checkpoint-stale",
        question_key="what roles did they have?",
        brain_snapshot=BrainSnapshot(
            session_id="session-stt-live-stale-rebuild",
            utterance_id="u-1",
            revision_id=1,
            snapshot_text="What roles did they have?",
            conversation_history=[{"speaker": "interviewer", "text": "What roles did they have?"}],
            snapshot_hash="stale-signature",
            timestamp=datetime.utcnow(),
        ),
        brain_plan=BrainPlan(
            resolved_question="What roles did they have?",
            ordered_asks=["What roles did they have?"],
            response_shape="direct_short",
            directness="direct",
            target_length=100,
            confidence=0.5,
        ),
        compact_evidence_pack=CompactEvidencePack(plan_hash="stale-plan", mode="minimal"),
        plan_hash="stale-plan",
    )
    fresh_snapshot = LiveFrozenSnapshot(
        raw_turn_window=[{"speaker": "interviewer", "text": "Tell me a bit about yourself"}],
        turn_window=[{"speaker": "interviewer", "text": "Tell me a bit about yourself"}],
        raw_context_bundle={},
        signature="fresh-signature",
        question_text="Tell me a bit about yourself",
        conversation_history=[{"speaker": "interviewer", "text": "Tell me a bit about yourself"}],
        prepared_context=None,
        request_payload={"question": "Tell me a bit about yourself"},
        question_source="live_brain_v4",
        cache_hit=False,
        checkpoint_id="checkpoint-fresh",
        question_key="tell me a bit about yourself",
        brain_snapshot=BrainSnapshot(
            session_id="session-stt-live-stale-rebuild",
            utterance_id="u-2",
            revision_id=2,
            snapshot_text="Tell me a bit about yourself",
            conversation_history=[{"speaker": "interviewer", "text": "Tell me a bit about yourself"}],
            snapshot_hash="fresh-signature",
            timestamp=datetime.utcnow(),
        ),
        brain_plan=BrainPlan(
            resolved_question="Tell me a bit about yourself",
            ordered_asks=["Tell me a bit about yourself"],
            response_shape="direct_short",
            directness="direct",
            target_length=100,
            confidence=0.8,
        ),
        compact_evidence_pack=CompactEvidencePack(plan_hash="fresh-plan", mode="minimal"),
        plan_hash="fresh-plan",
    )

    manager._build_live_frozen_snapshot = AsyncMock(side_effect=[stale_snapshot, fresh_snapshot])
    manager._live_snapshot_is_current = MagicMock(return_value=False)
    manager._generate_live_response_from_snapshot = AsyncMock(
        side_effect=[
            (
                {
                    "mode": "real",
                    "full_response": "stale answer",
                    "bullets": ["stale"],
                    "confidence": 0.5,
                    "latency_ms": 10,
                    "quality": {"passed": True, "score": 0.8, "issues": []},
                    "language": {"detected": "en", "confidence": 1.0},
                    "suggestion": {"style": "executive"},
                    "debug": {"fallback_used": True},
                },
                "brain_finalize_from_plan",
                0,
                0,
                False,
            ),
            (
                {
                    "mode": "real",
                    "full_response": "fresh answer",
                    "bullets": ["fresh"],
                    "confidence": 0.9,
                    "latency_ms": 10,
                    "quality": {"passed": True, "score": 0.95, "issues": []},
                    "language": {"detected": "en", "confidence": 1.0},
                    "suggestion": {"style": "executive"},
                    "debug": {"fallback_used": True},
                },
                "brain_finalize_from_plan",
                0,
                0,
                False,
            ),
        ]
    )

    _force_hard_silence(manager)
    await manager._try_auto_trigger_suggestion(
        SpeakerTurn(
            speaker="interviewer",
            text="Tell me a bit about yourself",
            start_time=0.0,
            end_time=1.0,
        ),
        generation_token=None,
    )

    assert manager._build_live_frozen_snapshot.await_count == 2
    assert manager._generate_live_response_from_snapshot.await_count == 2
    suggestion_events = [event for event in websocket.events if event.get("type") == "suggestion"]
    assert suggestion_events
    assert suggestion_events[-1]["full_response"] == "fresh answer"
    assert suggestion_events[-1]["debug"]["stale_snapshot_discarded"] is True


@pytest.mark.asyncio
async def test_auto_silence_skips_while_downstream_response_is_already_in_flight():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-downstream-inflight",
        default_mode="real",
    )
    manager._downstream_in_flight = True
    manager._build_live_frozen_snapshot = AsyncMock()

    _force_hard_silence(manager)
    await manager._try_auto_trigger_suggestion(
        SpeakerTurn(
            speaker="interviewer",
            text="Tell me about your leadership experience",
            start_time=0.0,
            end_time=1.0,
        ),
        generation_token=None,
    )

    manager._build_live_frozen_snapshot.assert_not_awaited()
    assert manager._answer_gate_reason == "downstream_in_flight"
    assert not [event for event in websocket.events if event.get("type") == "suggestion"]


@pytest.mark.asyncio
async def test_auto_silence_does_not_retrigger_same_silence_window_after_answer():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-single-answer-per-silence-window",
        default_mode="real",
    )
    manager._build_live_frozen_snapshot = AsyncMock()
    manager._interviewer_activity_epoch = 4
    manager._silence_anchor_at_ms = 12345
    _force_hard_silence(manager)
    manager._mark_auto_suggestion_served()

    await manager._try_auto_trigger_suggestion(
        SpeakerTurn(
            speaker="interviewer",
            text="Tell me about your leadership experience",
            start_time=0.0,
            end_time=1.0,
        ),
        generation_token=None,
    )

    manager._build_live_frozen_snapshot.assert_not_awaited()
    assert manager._answer_gate_reason == "already_answered_current_silence_window"
    assert not [event for event in websocket.events if event.get("type") == "suggestion"]


@pytest.mark.asyncio
async def test_auto_silence_does_not_block_emit_when_recent_display_caption_is_still_active():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-recent-display-caption",
        default_mode="real",
    )
    snapshot = LiveFrozenSnapshot(
        raw_turn_window=[{"speaker": "interviewer", "text": "Tell me about your leadership experience"}],
        turn_window=[{"speaker": "interviewer", "text": "Tell me about your leadership experience"}],
        raw_context_bundle={"primary_question_index": 0},
        signature="recent-display-caption-signature",
        question_text="Tell me about your leadership experience",
        conversation_history=[{"speaker": "interviewer", "text": "Tell me about your leadership experience"}],
        prepared_context=None,
        request_payload={"question": "Tell me about your leadership experience"},
        question_source="live_brain_v4",
        cache_hit=False,
        checkpoint_id="recent-display-caption-checkpoint",
        question_key="tell me about your leadership experience",
    )
    manager._build_live_frozen_snapshot = AsyncMock(return_value=snapshot)
    manager._generate_live_response_from_snapshot = AsyncMock(
        return_value=(
            {
                "mode": "real",
                "full_response": "I’ve led cross-functional teams across delivery and transformation programs.",
                "bullets": ["I’ve led cross-functional teams across delivery and transformation programs."],
                "confidence": 0.9,
                "latency_ms": 900,
                "quality": {"passed": True, "score": 0.95, "issues": []},
                "language": {"detected": "en", "confidence": 1.0},
                "suggestion": {
                    "style": "professional",
                    "keyMetrics": [],
                    "full_response": "I’ve led cross-functional teams across delivery and transformation programs.",
                    "bullets": ["I’ve led cross-functional teams across delivery and transformation programs."],
                },
                "debug": {
                    "fallback_used": False,
                    "path_used": "brain_finalize_from_plan",
                    "normalized_family": "leadership_scope",
                    "normalized_primary_ask": "Tell me about your leadership experience",
                    "normalized_secondary_asks": [],
                    "normalized_answer_contract": "experience_with_outcomes",
                    "normalized_metrics_policy": "prefer_if_supported",
                    "normalizer_confidence": 0.9,
                },
            },
            "brain_finalize_from_plan",
            0,
            0,
            False,
        )
    )
    manager._latest_interviewer_display_caption = LiveDisplayCaptionState(
        text="still speaking right now",
        updated_at=time.time(),
        is_partial=True,
    )
    manager._silence_detector.should_trigger_suggestion = MagicMock(return_value=True)
    manager._silence_detector.record_trigger = MagicMock()
    manager._silence_detector.record_completion = MagicMock()
    manager._silence_detector.get_remaining_cooldown = MagicMock(return_value=0.0)
    manager._live_snapshot_is_current = MagicMock(return_value=True)

    _force_hard_silence(manager)
    await manager._try_auto_trigger_suggestion(
        SpeakerTurn(
            speaker="interviewer",
            text="Tell me about your leadership experience",
            start_time=0.0,
            end_time=1.0,
        ),
        generation_token=None,
    )

    manager._build_live_frozen_snapshot.assert_awaited()
    manager._generate_live_response_from_snapshot.assert_awaited_once()
    assert manager._answer_gate_reason == "triggering_suggestion"
    assert manager._hard_silence_authorized is True
    assert [event for event in websocket.events if event.get("type") == "suggestion"]


@pytest.mark.asyncio
async def test_auto_silence_still_emits_when_interviewer_resumes_during_emit():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-interviewer-resumes-during-emit",
        default_mode="real",
    )

    snapshot = LiveFrozenSnapshot(
        raw_turn_window=[{"speaker": "interviewer", "text": "Tell me about your leadership experience"}],
        turn_window=[{"speaker": "interviewer", "text": "Tell me about your leadership experience"}],
        raw_context_bundle={},
        signature="resume-during-emit-sig",
        question_text="Tell me about your leadership experience",
        conversation_history=[{"speaker": "interviewer", "text": "Tell me about your leadership experience"}],
        prepared_context=None,
        request_payload={"question": "Tell me about your leadership experience"},
        question_source="live_brain_v4",
        cache_hit=True,
        checkpoint_id="resume-during-emit-checkpoint",
        question_key="resume-during-emit-question-key",
    )

    async def _mock_generate(**kwargs):
        assert "activity_epoch_at_trigger" not in kwargs
        manager._interviewer_activity_epoch += 1
        return _shared_suggest_response("stale answer"), "writer_emergency_fallback", 0, 0, False

    manager._build_live_frozen_snapshot = AsyncMock(return_value=snapshot)
    manager._generate_live_response_from_snapshot = AsyncMock(side_effect=_mock_generate)
    manager._live_snapshot_is_current = MagicMock(return_value=False)

    _force_hard_silence(manager)
    await manager._try_auto_trigger_suggestion(
        SpeakerTurn(
            speaker="interviewer",
            text="Tell me about your leadership experience",
            start_time=0.0,
            end_time=1.0,
        ),
        generation_token=None,
    )

    assert manager._generate_live_response_from_snapshot.await_count >= 1
    suggestion_events = [event for event in websocket.events if event.get("type") == "suggestion"]
    stream_events = [event for event in websocket.events if event.get("type") == "suggestion_stream"]
    assert suggestion_events
    assert not stream_events
    assert manager._answer_gate_reason == "triggering_suggestion"
    assert manager._hard_silence_authorized is True


@pytest.mark.asyncio
async def test_completed_interviewer_turn_does_not_reschedule_silence_trigger_for_existing_activity():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-generation-dedup",
        default_mode="real",
    )
    manager._schedule_silence_suggestion = MagicMock()
    manager._ensure_hard_silence_gate_scheduled = MagicMock()
    manager._last_interviewer_activity_at = time.time()
    manager._interviewer_activity_epoch = 4

    turn = SpeakerTurn(
        speaker="interviewer",
        text="Tell me about your leadership experience",
        start_time=0.0,
        end_time=1.0,
    )

    await manager._process_completed_turn(turn)
    assert manager._latest_interviewer_generation == 1
    manager._schedule_silence_suggestion.assert_not_called()
    manager._ensure_hard_silence_gate_scheduled.assert_not_called()
    assert manager._answer_gate_reason == "completed_turn_waiting_for_silence"

    await manager._process_completed_turn(turn)
    assert manager._latest_interviewer_generation == 1
    manager._schedule_silence_suggestion.assert_not_called()
    manager._ensure_hard_silence_gate_scheduled.assert_not_called()


@pytest.mark.asyncio
async def test_new_debounce_does_not_cancel_inflight_live_generation():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-inflight",
        default_mode="real",
    )
    manager._suggestion_debounce_sec = 0.0

    events: list[tuple[str, int]] = []
    first_started = asyncio.Event()
    first_finished = asyncio.Event()

    async def _fake_try_auto_trigger_suggestion(turn: SpeakerTurn, *, generation_token: int | None = None):
        token = int(generation_token or 0)
        events.append(("start", token))
        if token == 1:
            first_started.set()
            await asyncio.sleep(0.05)
            events.append(("finish", token))
            first_finished.set()
            return
        events.append(("finish", token))

    manager._try_auto_trigger_suggestion = _fake_try_auto_trigger_suggestion  # type: ignore[method-assign]

    turn = SpeakerTurn(
        speaker="interviewer",
        text="Tell me about building from zero",
        start_time=0.0,
        end_time=1.0,
    )

    manager._latest_interviewer_generation = 1
    manager._schedule_silence_suggestion(turn, 1)
    await asyncio.wait_for(first_started.wait(), timeout=0.2)
    manager._latest_interviewer_generation = 2
    manager._schedule_silence_suggestion(turn, 2)
    await asyncio.wait_for(first_finished.wait(), timeout=0.2)

    assert ("start", 1) in events
    assert ("finish", 1) in events


@pytest.mark.asyncio
async def test_auto_silence_uses_shared_manual_core_with_cached_live_summary():
    websocket = _FakeWebSocket()
    tracker = ConversationTracker()
    for idx, text in enumerate(
        [
            "Tell me specifically about companies or experiences.",
            "Where did you have to build from zero?",
            "How big were the teams you've managed?",
            "What roles did they have?",
            "Give me a quick intro.",
        ]
    ):
        accepted = tracker.add_turn(
            speaker="interviewer",
            text=text,
            utterance_count=1,
            start_time=float(idx * 2),
            end_time=float(idx * 2) + 0.8,
            reason="final",
        )
        assert accepted is True

    tracker.cache_live_ask_summary(
        LiveAskSummary(
            source_turns=[
                {"speaker": "interviewer", "text": "Where did you have to build from zero?"},
                {"speaker": "interviewer", "text": "How big were the teams you've managed?"},
                {"speaker": "interviewer", "text": "What roles did they have?"},
            ],
            turn_window_size=5,
            signature="live-sig-1",
            primary_ask="Where did you have to build from zero?",
            secondary_asks=["How big were the teams you've managed?", "What roles did they have?"],
            ordered_focus=[
                "Where did you have to build from zero?",
                "How big were the teams you've managed?",
                "What roles did they have?",
            ],
            confidence=0.95,
            created_at=datetime.utcnow(),
            version=4,
            latency_ms=12,
        )
    )
    tracker.cache_live_prepared_context(
        LivePreparedContext(
            raw_turns=[
                {"speaker": "interviewer", "text": "Tell me specifically about companies or experiences."},
                {"speaker": "interviewer", "text": "Where did you have to build from zero?"},
                {"speaker": "interviewer", "text": "How big were the teams you've managed?"},
                {"speaker": "interviewer", "text": "What roles did they have?"},
                {"speaker": "interviewer", "text": "Give me a quick intro."},
            ],
            sanitized_turns=[
                {"speaker": "interviewer", "text": "Tell me specifically about companies or experiences."},
                {"speaker": "interviewer", "text": "Where did you have to build from zero?"},
                {"speaker": "interviewer", "text": "How big were the teams you've managed?"},
                {"speaker": "interviewer", "text": "What roles did they have?"},
                {"speaker": "interviewer", "text": "Give me a quick intro."},
            ],
            turn_window_size=5,
            effective_turn_count=5,
            latest_turn_included=True,
            signature="live-sig-1",
            version=4,
            primary_ask="Where did you have to build from zero?",
            secondary_asks=["How big were the teams you've managed?", "What roles did they have?"],
            ordered_focus=[
                "Where did you have to build from zero?",
                "How big were the teams you've managed?",
                "What roles did they have?",
            ],
            answer_family=AskFamily.MIXED_COMPOUND,
            answer_contract=AnswerContract.DIRECT_MULTI_PART,
            complexity_class=ComplexityClass.COMPOUND,
            answer_shape=AnswerShape.DIRECT_STRUCTURED,
            target_length=220,
            allow_metrics=True,
            allow_profile_opening=False,
            require_ordered_coverage=True,
            question_text="Where did you have to build from zero?\nAlso cover:\n- How big were the teams you've managed?\n- What roles did they have?",
            request_payload={
                "question": "Where did you have to build from zero?\nAlso cover:\n- How big were the teams you've managed?\n- What roles did they have?",
                "session_id": "session-stt-live-summary",
                "candidate_profile": {"name": "Daniel"},
                "company_info": {"companyName": "Cuesta"},
                "interviewer_profile": {"name": "Marcus"},
                "style_id": "professional",
                "language": "en",
                "mode": "real",
                "history_count": 5,
                "max_words": 220,
                "interview_type": "mixed",
                "conversation_history": [
                    {"speaker": "interviewer", "text": "Tell me specifically about companies or experiences."},
                    {"speaker": "interviewer", "text": "Where did you have to build from zero?"},
                    {"speaker": "interviewer", "text": "How big were the teams you've managed?"},
                    {"speaker": "interviewer", "text": "What roles did they have?"},
                    {"speaker": "interviewer", "text": "Give me a quick intro."},
                ],
                "preserve_question_text": True,
            },
            ask_brief=AskBrief(
                primary_ask="Where did you have to build from zero?",
                secondary_asks=["How big were the teams you've managed?", "What roles did they have?"],
                answer_family=AskFamily.MIXED_COMPOUND,
                answer_contract=AnswerContract.DIRECT_MULTI_PART,
            ),
            confidence=0.95,
            created_at=datetime.utcnow(),
            latency_ms=12,
            sanitized_turn_count=5,
        )
    )

    pipeline = MagicMock()
    pipeline.process_question = AsyncMock()
    pipeline.conversation_tracker = tracker
    pipeline.ask_normalizer = MagicMock()
    pipeline.ask_normalizer.config.confidence_threshold = 0.72
    pipeline.ask_normalizer.build_signature.return_value = "live-sig-1"
    pipeline.live_question_planner = MagicMock()
    pipeline.live_question_planner.build_signature.return_value = "live-sig-1"
    pipeline.live_question_planner.prepare = AsyncMock(return_value=None)
    pipeline.session_state = MagicMock(
        interview_config={
            "delivery_mode": "manual",
            "style_id": "professional",
            "language_preference": "en",
            "max_words": 200,
            "candidate": {"name": "Daniel"},
            "company": {"companyName": "Cuesta"},
            "interviewer": {"name": "Marcus"},
        }
    )

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-summary",
        default_mode="real",
    )
    manager._silence_detector.should_trigger_suggestion = MagicMock(return_value=True)
    manager._silence_detector.record_trigger = MagicMock()
    manager._silence_detector.record_completion = MagicMock()
    manager._silence_detector.get_remaining_cooldown = MagicMock(return_value=0.0)

    shared_response = {
        "success": True,
        "mode": "real",
        "full_response": "Shared manual-quality answer",
        "bullets": ["Build from zero", "Team scope", "Roles"],
        "confidence": 0.91,
        "latency_ms": 880,
        "quality": {"passed": True, "score": 0.93, "issues": []},
        "language": {"detected": "en"},
        "suggestion": {"style": "executive", "keyMetrics": []},
        "debug": {
            "normalized_family": "mixed_compound",
            "normalized_primary_ask": "Where did you have to build from zero?",
            "normalized_secondary_asks": ["How big were the teams you've managed?", "What roles did they have?"],
            "normalized_answer_contract": "direct_multi_part",
            "normalized_metrics_policy": "prefer_if_supported",
            "normalizer_confidence": 0.95,
            "fallback_used": False,
        },
    }

    with patch(
        "api.server._suggest_live_prepared_response",
        AsyncMock(return_value=shared_response),
    ) as mock_live_suggest:
        _force_hard_silence(manager)
        await manager._try_auto_trigger_suggestion(
            SpeakerTurn(
                speaker="interviewer",
                text="What roles did they have?",
                start_time=0.0,
                end_time=1.0,
            ),
            generation_token=None,
        )

    pipeline.process_question.assert_not_awaited()
    mock_live_suggest.assert_awaited_once()
    call_kwargs = mock_live_suggest.await_args.kwargs
    assert call_kwargs["session_id"] == "session-stt-live-summary"
    assert call_kwargs["question_text"].startswith("Where did you have to build from zero?")
    assert "Also cover:" in call_kwargs["question_text"]
    request_history = call_kwargs["conversation_history"]
    assert len(request_history) == 5
    assert all(turn["speaker"] == "interviewer" for turn in request_history)
    assert call_kwargs["live_prepared_context"].complexity_class.value == "compound"

    suggestion_events = [event for event in websocket.events if event.get("type") == "suggestion"]
    assert len(suggestion_events) == 1
    assert suggestion_events[0]["full_response"] == "Shared manual-quality answer"
    assert suggestion_events[0]["question_source"] == "live_prepared_context"


@pytest.mark.asyncio
async def test_auto_silence_uses_single_turn_prepared_context_when_available():
    websocket = _FakeWebSocket()
    tracker = ConversationTracker()
    accepted = tracker.add_turn(
        speaker="interviewer",
        text="And tell me, why are you looking for a job? Like, what's what do you looking for?",
        utterance_count=1,
        start_time=0.0,
        end_time=0.8,
        reason="final",
    )
    assert accepted is True

    tracker.cache_live_prepared_context(
        LivePreparedContext(
            raw_turns=[
                {"speaker": "interviewer", "text": "And tell me, why are you looking for a job? Like, what's what do you looking for?"},
            ],
            sanitized_turns=[
                {"speaker": "interviewer", "text": "And tell me, why are you looking for a job? Like, what's what do you looking for?"},
            ],
            turn_window_size=1,
            effective_turn_count=1,
            latest_turn_included=True,
            signature="single-turn-live-sig",
            version=2,
            primary_ask="Why are you looking for a job?",
            secondary_asks=[],
            ordered_focus=["Why are you looking for a job?"],
            answer_family=AskFamily.CULTURE_FIT,
            answer_contract=AnswerContract.PREFERENCES_AND_ANTI_PATTERNS,
            complexity_class=ComplexityClass.SIMPLE,
            answer_shape=AnswerShape.DIRECT_SHORT,
            target_length=110,
            allow_metrics=False,
            allow_profile_opening=False,
            require_ordered_coverage=False,
            question_text="Why are you looking for a job?",
            request_payload={},
            ask_brief=AskBrief(
                primary_ask="Why are you looking for a job?",
                answer_family=AskFamily.CULTURE_FIT,
                answer_contract=AnswerContract.PREFERENCES_AND_ANTI_PATTERNS,
                confidence=0.55,
            ),
            confidence=0.55,
            planner_confidence=0.55,
            plan_stage="base",
        )
    )

    pipeline = MagicMock()
    pipeline.process_question = AsyncMock()
    pipeline.conversation_tracker = tracker
    pipeline.ask_normalizer = MagicMock()
    pipeline.ask_normalizer.config.confidence_threshold = 0.72
    pipeline.live_question_planner = MagicMock()
    pipeline.live_question_planner.build_signature.return_value = "single-turn-live-sig"
    pipeline.session_state = MagicMock(
        interview_config={
            "delivery_mode": "manual",
            "style_id": "professional",
            "language_preference": "en",
            "max_words": 140,
            "candidate": {"name": "Daniel"},
            "company": {"companyName": "Cuesta"},
            "interviewer": {"name": "Marcus"},
        }
    )

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-single-turn-live",
        default_mode="real",
    )
    manager._silence_detector.should_trigger_suggestion = MagicMock(return_value=True)
    manager._silence_detector.record_trigger = MagicMock()
    manager._silence_detector.record_completion = MagicMock()
    manager._silence_detector.get_remaining_cooldown = MagicMock(return_value=0.0)

    shared_response = _shared_suggest_response()
    shared_response["debug"]["normalized_primary_ask"] = "Why are you looking for a job?"

    with patch(
        "api.server._suggest_live_prepared_response",
        AsyncMock(return_value=shared_response),
    ) as mock_live_suggest:
        _force_hard_silence(manager)
        await manager._try_auto_trigger_suggestion(
            SpeakerTurn(
                speaker="interviewer",
                text="And tell me, why are you looking for a job? Like, what's what do you looking for?",
                start_time=0.0,
                end_time=1.0,
            ),
            generation_token=None,
        )

    mock_live_suggest.assert_awaited_once()
    call_kwargs = mock_live_suggest.await_args.kwargs
    assert call_kwargs["question_text"] == "Why are you looking for a job?"
    suggestion_events = [event for event in websocket.events if event.get("type") == "suggestion"]
    assert suggestion_events
    assert suggestion_events[0]["question_source"] == "live_prepared_context"


@pytest.mark.asyncio
async def test_auto_silence_does_not_emit_cached_brain_draft_as_final_answer():
    websocket = _FakeWebSocket()
    tracker = ConversationTracker()
    accepted = tracker.add_turn(
        speaker="interviewer",
        text="Why are you looking for a job?",
        utterance_count=1,
        start_time=0.0,
        end_time=0.8,
        reason="final",
    )
    assert accepted is True

    tracker.cache_live_prepared_context(
        LivePreparedContext(
            raw_turns=[
                {"speaker": "interviewer", "text": "Why are you looking for a job?"},
            ],
            sanitized_turns=[
                {"speaker": "interviewer", "text": "Why are you looking for a job?"},
            ],
            turn_window_size=1,
            effective_turn_count=1,
            latest_turn_included=True,
            signature="single-turn-draft-sig",
            version=2,
            primary_ask="Why are you looking for a job?",
            secondary_asks=[],
            ordered_focus=["Why are you looking for a job?"],
            answer_family=AskFamily.CULTURE_FIT,
            answer_contract=AnswerContract.PREFERENCES_AND_ANTI_PATTERNS,
            complexity_class=ComplexityClass.SIMPLE,
            answer_shape=AnswerShape.DIRECT_SHORT,
            target_length=110,
            allow_metrics=False,
            allow_profile_opening=False,
            require_ordered_coverage=False,
            question_text="Why are you looking for a job?",
            request_payload={},
            ask_brief=AskBrief(
                primary_ask="Why are you looking for a job?",
                answer_family=AskFamily.CULTURE_FIT,
                answer_contract=AnswerContract.PREFERENCES_AND_ANTI_PATTERNS,
                confidence=0.9,
            ),
            draft_answer="I'm looking for a role where I can stay close to delivery, have direct client impact, and work in a pragmatic team.",
            confidence=0.9,
            planner_confidence=0.9,
            plan_stage="semantic",
            planner_source="llm_fast",
        )
    )

    pipeline = MagicMock()
    pipeline.process_question = AsyncMock()
    pipeline.conversation_tracker = tracker
    pipeline.ask_normalizer = MagicMock()
    pipeline.ask_normalizer.config.confidence_threshold = 0.72
    pipeline.live_question_planner = MagicMock()
    pipeline.live_question_planner.build_signature.return_value = "single-turn-draft-sig"
    pipeline.session_state = MagicMock(
        interview_config={
            "delivery_mode": "manual",
            "style_id": "professional",
            "language_preference": "en",
            "max_words": 140,
            "candidate": {"name": "Daniel"},
            "company": {"companyName": "Cuesta"},
            "interviewer": {"name": "Marcus"},
        }
    )

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-draft",
        default_mode="real",
    )
    manager._silence_detector.should_trigger_suggestion = MagicMock(return_value=True)
    manager._silence_detector.record_trigger = MagicMock()
    manager._silence_detector.record_completion = MagicMock()
    manager._silence_detector.get_remaining_cooldown = MagicMock(return_value=0.0)

    with patch(
        "api.server._suggest_live_prepared_response",
        AsyncMock(return_value=_shared_suggest_response()),
    ) as live_suggest:
        _force_hard_silence(manager)
        await manager._try_auto_trigger_suggestion(
            SpeakerTurn(
                speaker="interviewer",
                text="Why are you looking for a job?",
                start_time=0.0,
                end_time=1.0,
            ),
            generation_token=None,
        )

    suggestion_events = [event for event in websocket.events if event.get("type") == "suggestion"]
    assert suggestion_events
    assert suggestion_events[0]["full_response"] == "Shared manual-quality answer"
    assert suggestion_events[0]["full_response"] != "I'm looking for a role where I can stay close to delivery, have direct client impact, and work in a pragmatic team."
    assert suggestion_events[0]["path_used"].startswith("writer_")
    live_suggest.assert_awaited()


@pytest.mark.asyncio
async def test_auto_silence_waits_briefly_for_current_live_snapshot_before_quality_writer():
    websocket = _FakeWebSocket()
    tracker = ConversationTracker()
    accepted = tracker.add_turn(
        speaker="interviewer",
        text="Why are you looking for a job?",
        utterance_count=1,
        start_time=0.0,
        end_time=0.8,
        reason="final",
    )
    assert accepted is True

    base_context = LivePreparedContext(
        raw_turns=[
            {"speaker": "interviewer", "text": "Why are you looking for a job?"},
        ],
        sanitized_turns=[
            {"speaker": "interviewer", "text": "Why are you looking for a job?"},
        ],
        turn_window_size=1,
        effective_turn_count=1,
        latest_turn_included=True,
        signature="single-turn-wait-sig",
        version=2,
        primary_ask="Why are you looking for a job?",
        secondary_asks=[],
        ordered_focus=["Why are you looking for a job?"],
        asks_in_order=["Why are you looking for a job?"],
        answer_family=AskFamily.CULTURE_FIT,
        answer_contract=AnswerContract.PREFERENCES_AND_ANTI_PATTERNS,
        complexity_class=ComplexityClass.SIMPLE,
        answer_shape=AnswerShape.DIRECT_SHORT,
        target_length=110,
        allow_metrics=False,
        allow_profile_opening=False,
        require_ordered_coverage=False,
        question_text="Why are you looking for a job?",
        request_payload={},
        ask_brief=AskBrief(
            primary_ask="Why are you looking for a job?",
            answer_family=AskFamily.CULTURE_FIT,
            answer_contract=AnswerContract.PREFERENCES_AND_ANTI_PATTERNS,
            confidence=0.9,
        ),
        confidence=0.9,
        planner_confidence=0.9,
        plan_stage="base",
        planner_source="deterministic",
    )
    tracker.cache_live_prepared_context(base_context)

    pipeline = MagicMock()
    pipeline.process_question = AsyncMock()
    pipeline.conversation_tracker = tracker
    pipeline.ask_normalizer = MagicMock()
    pipeline.ask_normalizer.config.confidence_threshold = 0.72
    pipeline.live_question_planner = MagicMock()
    pipeline.live_question_planner.build_signature.return_value = "single-turn-wait-sig"
    pipeline.session_state = MagicMock(
        interview_config={
            "delivery_mode": "manual",
            "style_id": "professional",
            "language_preference": "en",
            "max_words": 140,
            "candidate": {"name": "Daniel"},
            "company": {"companyName": "Cuesta"},
            "interviewer": {"name": "Marcus"},
        }
    )

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-wait-draft",
        default_mode="real",
    )
    manager._live_semantic_grace_sec = 0.1
    manager._silence_detector.should_trigger_suggestion = MagicMock(return_value=True)
    manager._silence_detector.record_trigger = MagicMock()
    manager._silence_detector.record_completion = MagicMock()
    manager._silence_detector.get_remaining_cooldown = MagicMock(return_value=0.0)

    async def _publish_enriched_context():
        await asyncio.sleep(0.01)
        tracker.cache_live_prepared_context(
            base_context.model_copy(
                update={
                    "version": 3,
                    "draft_answer": "I'm looking for a role where I can stay close to execution, have direct client impact, and work with a pragmatic team.",
                    "plan_stage": "semantic",
                    "planner_source": "llm_fast",
                    "planner_model": "claude-sonnet",
                }
            )
        )

    manager._live_semantic_refresh_signature = "single-turn-wait-sig"
    manager._live_semantic_refresh_task = asyncio.create_task(_publish_enriched_context())

    with patch(
        "api.server._suggest_live_prepared_response",
        AsyncMock(return_value=_shared_suggest_response()),
    ) as live_suggest:
        _force_hard_silence(manager)
        await manager._try_auto_trigger_suggestion(
            SpeakerTurn(
                speaker="interviewer",
                text="Why are you looking for a job?",
                start_time=0.0,
                end_time=1.0,
            ),
            generation_token=None,
        )

    suggestion_events = [event for event in websocket.events if event.get("type") == "suggestion"]
    assert suggestion_events
    assert suggestion_events[0]["full_response"] == "Shared manual-quality answer"
    assert suggestion_events[0]["silence_wait_ms"] >= 0
    live_suggest.assert_awaited()


@pytest.mark.asyncio
async def test_auto_silence_does_not_use_direct_brain_prepare_as_final_path():
    websocket = _FakeWebSocket()
    tracker = ConversationTracker()
    accepted = tracker.add_turn(
        speaker="interviewer",
        text="Why are you looking for a job?",
        utterance_count=1,
        start_time=0.0,
        end_time=0.8,
        reason="final",
    )
    assert accepted is True

    base_context = LivePreparedContext(
        raw_turns=[{"speaker": "interviewer", "text": "Why are you looking for a job?"}],
        sanitized_turns=[{"speaker": "interviewer", "text": "Why are you looking for a job?"}],
        turn_window_size=1,
        effective_turn_count=1,
        latest_turn_included=True,
        signature="single-turn-direct-brain-sig",
        version=2,
        primary_ask="Why are you looking for a job?",
        secondary_asks=[],
        ordered_focus=["Why are you looking for a job?"],
        asks_in_order=["Why are you looking for a job?"],
        answer_family=AskFamily.CULTURE_FIT,
        answer_contract=AnswerContract.PREFERENCES_AND_ANTI_PATTERNS,
        complexity_class=ComplexityClass.SIMPLE,
        answer_shape=AnswerShape.DIRECT_SHORT,
        target_length=110,
        allow_metrics=False,
        allow_profile_opening=False,
        require_ordered_coverage=False,
        question_text="Why are you looking for a job?",
        request_payload={},
        ask_brief=AskBrief(
            primary_ask="Why are you looking for a job?",
            answer_family=AskFamily.CULTURE_FIT,
            answer_contract=AnswerContract.PREFERENCES_AND_ANTI_PATTERNS,
            confidence=0.9,
        ),
        confidence=0.9,
        planner_confidence=0.9,
        plan_stage="base",
        planner_source="deterministic",
    )
    tracker.cache_live_prepared_context(base_context)

    semantic_context = base_context.model_copy(
        update={
            "version": 3,
            "draft_answer": "I'm looking for a role where I can stay close to delivery, have direct client impact, and work with a pragmatic team.",
            "plan_stage": "semantic",
            "planner_source": "llm_fast",
            "planner_model": "claude-sonnet",
        }
    )

    pipeline = MagicMock()
    pipeline.process_question = AsyncMock()
    pipeline.conversation_tracker = tracker
    pipeline.ask_normalizer = MagicMock()
    pipeline.ask_normalizer.config.confidence_threshold = 0.72
    pipeline.live_question_planner = MagicMock()
    pipeline.live_question_planner.build_signature.return_value = "single-turn-direct-brain-sig"
    pipeline.live_question_planner.prepare = AsyncMock(return_value=semantic_context)
    pipeline.session_state = MagicMock(
        interview_config={
            "delivery_mode": "manual",
            "style_id": "professional",
            "language_preference": "en",
            "max_words": 140,
            "candidate": {"name": "Daniel"},
            "company": {"companyName": "Cuesta"},
            "interviewer": {"name": "Marcus"},
        }
    )

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-direct-brain",
        default_mode="real",
    )
    manager._live_semantic_grace_sec = 0.0
    manager._silence_detector.should_trigger_suggestion = MagicMock(return_value=True)
    manager._silence_detector.record_trigger = MagicMock()
    manager._silence_detector.record_completion = MagicMock()
    manager._silence_detector.get_remaining_cooldown = MagicMock(return_value=0.0)

    with patch(
        "api.server._suggest_live_prepared_response",
        AsyncMock(return_value=_shared_suggest_response()),
    ) as live_suggest:
        _force_hard_silence(manager)
        await manager._try_auto_trigger_suggestion(
            SpeakerTurn(
                speaker="interviewer",
                text="Why are you looking for a job?",
                start_time=0.0,
                end_time=1.0,
            ),
            generation_token=None,
        )

    suggestion_events = [event for event in websocket.events if event.get("type") == "suggestion"]
    assert suggestion_events
    assert suggestion_events[0]["full_response"] == "Shared manual-quality answer"
    assert suggestion_events[0]["path_used"].startswith("writer_")
    pipeline.live_question_planner.prepare.assert_not_awaited()
    live_suggest.assert_awaited()


@pytest.mark.asyncio
async def test_auto_silence_uses_quality_writer_from_frozen_snapshot_when_no_prewarm_available():
    websocket = _FakeWebSocket()
    tracker = ConversationTracker()
    accepted = tracker.add_turn(
        speaker="interviewer",
        text="What are you looking for in a company and what do you avoid?",
        utterance_count=1,
        start_time=0.0,
        end_time=0.8,
        reason="final",
    )
    assert accepted is True

    base_context = LivePreparedContext(
        raw_turns=[{"speaker": "interviewer", "text": "What are you looking for in a company and what do you avoid?"}],
        sanitized_turns=[{"speaker": "interviewer", "text": "What are you looking for in a company and what do you avoid?"}],
        turn_window_size=1,
        effective_turn_count=1,
        latest_turn_included=True,
        signature="best-effort-live-sig",
        version=1,
        primary_ask="What are you looking for in a company?",
        secondary_asks=["What do you avoid?"],
        ordered_focus=["What are you looking for in a company?", "What do you avoid?"],
        asks_in_order=["What are you looking for in a company?", "What do you avoid?"],
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
            confidence=0.9,
        ),
        confidence=0.9,
        planner_confidence=0.9,
        plan_stage="base",
        planner_source="deterministic",
    )
    tracker.cache_live_prepared_context(base_context)

    pipeline = MagicMock()
    pipeline.process_question = AsyncMock()
    pipeline.conversation_tracker = tracker
    pipeline.ask_normalizer = MagicMock()
    pipeline.ask_normalizer.config.confidence_threshold = 0.72
    pipeline.live_question_planner = MagicMock()
    pipeline.live_question_planner.build_signature.return_value = "best-effort-live-sig"
    pipeline.live_question_planner.draft_from_prepared_context = AsyncMock(return_value=None)
    pipeline.live_question_planner.write_best_effort_from_prepared_context = AsyncMock()
    pipeline.session_state = MagicMock(
        interview_config={
            "delivery_mode": "manual",
            "style_id": "professional",
            "language_preference": "en",
            "max_words": 140,
            "candidate": {"name": "Daniel"},
            "company": {"companyName": "Cuesta"},
            "interviewer": {"name": "Marcus"},
        }
    )

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-best-effort",
        default_mode="real",
    )
    manager._live_semantic_grace_sec = 0.0
    manager._silence_detector.should_trigger_suggestion = MagicMock(return_value=True)
    manager._silence_detector.record_trigger = MagicMock()
    manager._silence_detector.record_completion = MagicMock()
    manager._silence_detector.get_remaining_cooldown = MagicMock(return_value=0.0)

    shared_response = _shared_suggest_response()
    with patch(
        "api.server._suggest_live_prepared_response",
        AsyncMock(return_value=shared_response),
    ) as live_suggest:
        _force_hard_silence(manager)
        await manager._try_auto_trigger_suggestion(
            SpeakerTurn(
                speaker="interviewer",
                text="What are you looking for in a company and what do you avoid?",
                start_time=0.0,
                end_time=1.0,
            ),
            generation_token=None,
        )

    suggestion_events = [event for event in websocket.events if event.get("type") == "suggestion"]
    assert suggestion_events
    assert suggestion_events[0]["full_response"] == "Shared manual-quality answer"
    assert suggestion_events[0]["path_used"].startswith("writer_")
    assert live_suggest.await_count >= 1
    call_kwargs = live_suggest.await_args_list[0].kwargs
    assert call_kwargs["question_text"] == "What are you looking for in a company?\nAlso cover:\n- What do you avoid?"
    assert call_kwargs["conversation_history"] == base_context.sanitized_turns
    pipeline.live_question_planner.write_best_effort_from_prepared_context.assert_not_awaited()


@pytest.mark.asyncio
async def test_auto_silence_uses_prewarmed_quality_writer_before_heavy_fallback():
    websocket = _FakeWebSocket()
    tracker = ConversationTracker()
    accepted = tracker.add_turn(
        speaker="interviewer",
        text="What are you looking for in a company and culture?",
        utterance_count=1,
        start_time=0.0,
        end_time=0.8,
        reason="final",
    )
    assert accepted is True

    prepared_context = LivePreparedContext(
        raw_turns=[{"speaker": "interviewer", "text": "What are you looking for in a company and culture?"}],
        sanitized_turns=[{"speaker": "interviewer", "text": "What are you looking for in a company and culture?"}],
        turn_window_size=1,
        effective_turn_count=1,
        latest_turn_included=True,
        signature="prewarmed-live-sig",
        version=1,
        primary_ask="What are you looking for in a company and culture?",
        secondary_asks=[],
        ordered_focus=["What are you looking for in a company and culture?"],
        asks_in_order=["What are you looking for in a company and culture?"],
        answer_family=AskFamily.CULTURE_FIT,
        answer_contract=AnswerContract.PREFERENCES_AND_ANTI_PATTERNS,
        complexity_class=ComplexityClass.SIMPLE,
        answer_shape=AnswerShape.DIRECT_SHORT,
        target_length=120,
        allow_metrics=False,
        allow_profile_opening=False,
        require_ordered_coverage=False,
        question_text="What are you looking for in a company and culture?",
        request_payload={},
        ask_brief=AskBrief(
            primary_ask="What are you looking for in a company and culture?",
            answer_family=AskFamily.CULTURE_FIT,
            answer_contract=AnswerContract.PREFERENCES_AND_ANTI_PATTERNS,
            confidence=0.9,
        ),
        confidence=0.9,
        planner_confidence=0.9,
        plan_stage="base",
        planner_source="deterministic",
    )
    tracker.cache_live_prepared_context(prepared_context)

    pipeline = MagicMock()
    pipeline.process_question = AsyncMock()
    pipeline.conversation_tracker = tracker
    pipeline.ask_normalizer = MagicMock()
    pipeline.ask_normalizer.config.confidence_threshold = 0.72
    pipeline.live_question_planner = MagicMock()
    pipeline.live_question_planner.build_signature.return_value = "prewarmed-live-sig"
    pipeline.live_question_planner.prepare_base.return_value = prepared_context
    pipeline.live_question_planner.draft_from_prepared_context = AsyncMock(return_value=None)
    pipeline.live_question_planner.write_best_effort_from_prepared_context = AsyncMock(
        side_effect=AssertionError("prewarmed writer should avoid best-effort fallback")
    )
    pipeline.session_state = MagicMock(
        interview_config={
            "delivery_mode": "manual",
            "style_id": "professional",
            "language_preference": "en",
            "max_words": 140,
            "candidate": {"name": "Daniel"},
            "company": {"companyName": "Cuesta"},
            "interviewer": {"name": "Marcus"},
        }
    )

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-prewarmed",
        default_mode="real",
    )
    manager._live_semantic_grace_sec = 0.0
    manager._silence_detector.should_trigger_suggestion = MagicMock(return_value=True)
    manager._silence_detector.record_trigger = MagicMock()
    manager._silence_detector.record_completion = MagicMock()
    manager._silence_detector.get_remaining_cooldown = MagicMock(return_value=0.0)
    manager._live_quality_cached_signature = "what are you looking for in a company and culture?"
    manager._live_quality_cached_context = prepared_context
    manager._live_quality_cached_response = _shared_suggest_response()

    with patch(
        "api.server._suggest_live_prepared_response",
        AsyncMock(side_effect=AssertionError("prewarmed writer should avoid heavy fallback")),
    ):
        _force_hard_silence(manager)
        await manager._try_auto_trigger_suggestion(
            SpeakerTurn(
                speaker="interviewer",
                text="What are you looking for in a company and culture?",
                start_time=0.0,
                end_time=1.0,
            ),
            generation_token=None,
        )

    suggestion_events = [event for event in websocket.events if event.get("type") == "suggestion"]
    assert suggestion_events
    assert suggestion_events[0]["full_response"] == "Shared manual-quality answer"
    assert suggestion_events[0]["path_used"] == "writer_prewarmed_fallback"
    assert suggestion_events[0]["warm_exact_match"] is True
    assert suggestion_events[0]["snapshot_source"] == "frozen_snapshot_v2"
    assert suggestion_events[0]["freeze_checkpoint_id"]


@pytest.mark.asyncio
async def test_auto_silence_uses_exact_warm_result_from_parallel_warmer_v2():
    websocket = _FakeWebSocket()
    tracker = ConversationTracker()
    accepted = tracker.add_turn(
        speaker="interviewer",
        text="What are you looking for in a company and culture?",
        utterance_count=1,
        start_time=0.0,
        end_time=0.8,
        reason="final",
    )
    assert accepted is True

    prepared_context = LivePreparedContext(
        raw_turns=[{"speaker": "interviewer", "text": "What are you looking for in a company and culture?"}],
        sanitized_turns=[{"speaker": "interviewer", "text": "What are you looking for in a company and culture?"}],
        turn_window_size=1,
        effective_turn_count=1,
        latest_turn_included=True,
        signature="parallel-warm-live-sig",
        version=1,
        primary_ask="What are you looking for in a company and culture?",
        secondary_asks=[],
        ordered_focus=["What are you looking for in a company and culture?"],
        asks_in_order=["What are you looking for in a company and culture?"],
        answer_family=AskFamily.CULTURE_FIT,
        answer_contract=AnswerContract.PREFERENCES_AND_ANTI_PATTERNS,
        complexity_class=ComplexityClass.SIMPLE,
        answer_shape=AnswerShape.DIRECT_SHORT,
        target_length=120,
        allow_metrics=False,
        allow_profile_opening=False,
        require_ordered_coverage=False,
        question_text="What are you looking for in a company and culture?",
        request_payload={},
        ask_brief=AskBrief(
            primary_ask="What are you looking for in a company and culture?",
            answer_family=AskFamily.CULTURE_FIT,
            answer_contract=AnswerContract.PREFERENCES_AND_ANTI_PATTERNS,
            confidence=0.9,
        ),
        confidence=0.9,
        planner_confidence=0.9,
        plan_stage="base",
        planner_source="deterministic",
    )
    tracker.cache_live_prepared_context(prepared_context)

    pipeline = MagicMock()
    pipeline.process_question = AsyncMock()
    pipeline.conversation_tracker = tracker
    pipeline.ask_normalizer = MagicMock()
    pipeline.ask_normalizer.config.confidence_threshold = 0.72
    pipeline.live_question_planner = MagicMock()
    pipeline.live_question_planner.build_signature.return_value = "parallel-warm-live-sig"
    pipeline.live_question_planner.prepare_base.return_value = prepared_context
    pipeline.session_state = MagicMock(
        interview_config={
            "delivery_mode": "manual",
            "style_id": "professional",
            "language_preference": "en",
            "max_words": 140,
            "candidate": {"name": "Daniel"},
            "company": {"companyName": "Cuesta"},
            "interviewer": {"name": "Marcus"},
        }
    )

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-parallel-warm-result",
        default_mode="real",
    )
    manager._silence_detector.should_trigger_suggestion = MagicMock(return_value=True)
    manager._silence_detector.record_trigger = MagicMock()
    manager._silence_detector.record_completion = MagicMock()
    manager._silence_detector.get_remaining_cooldown = MagicMock(return_value=0.0)
    manager._live_warm_latest_result = LiveWarmResult(
        checkpoint_id="warm-checkpoint-1",
        signature="parallel-warm-live-sig",
        question_key="what are you looking for in a company and culture?",
        question_text="What are you looking for in a company and culture?",
        response=_shared_suggest_response(),
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
        success=True,
    )

    with patch(
        "api.server._suggest_live_prepared_response",
        AsyncMock(side_effect=AssertionError("exact warm result should avoid heavy fallback")),
    ):
        _force_hard_silence(manager)
        await manager._try_auto_trigger_suggestion(
            SpeakerTurn(
                speaker="interviewer",
                text="What are you looking for in a company and culture?",
                start_time=0.0,
                end_time=1.0,
            ),
            generation_token=None,
        )

    suggestion_events = [event for event in websocket.events if event.get("type") == "suggestion"]
    assert suggestion_events
    assert suggestion_events[0]["full_response"] == "Shared manual-quality answer"
    assert suggestion_events[0]["path_used"] == "writer_prewarmed_fallback"
    assert suggestion_events[0]["warm_checkpoint_id"] == "warm-checkpoint-1"
    assert suggestion_events[0]["warm_exact_match"] is True
    assert suggestion_events[0]["warm_completed_before_silence"] is True
    assert suggestion_events[0]["snapshot_source"] == "frozen_snapshot_v2"


@pytest.mark.asyncio
async def test_parallel_warmer_keeps_compatible_inflight_checkpoint_when_question_extends():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()
    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-compatible-inflight",
        default_mode="real",
    )

    prepared_context = LivePreparedContext(
        raw_turns=[
            {
                "speaker": "interviewer",
                "text": "What are you looking for in terms of the company, the culture, teams? What's important for you?",
            }
        ],
        sanitized_turns=[
            {
                "speaker": "interviewer",
                "text": "What are you looking for in terms of the company, the culture, teams? What's important for you?",
            }
        ],
        turn_window_size=1,
        effective_turn_count=1,
        latest_turn_included=True,
        signature="compatible-live-sig",
        version=1,
        primary_ask="What are you looking for in terms of the company, the culture, teams?",
        secondary_asks=["What's important for you?"],
        ordered_focus=[
            "What are you looking for in terms of the company, the culture, teams?",
            "What's important for you?",
        ],
        asks_in_order=[
            "What are you looking for in terms of the company, the culture, teams?",
            "What's important for you?",
        ],
        answer_family=AskFamily.CULTURE_FIT,
        answer_contract=AnswerContract.PREFERENCES_AND_ANTI_PATTERNS,
        complexity_class=ComplexityClass.COMPOUND,
        answer_shape=AnswerShape.DIRECT_STRUCTURED,
        target_length=140,
        allow_metrics=False,
        allow_profile_opening=False,
        require_ordered_coverage=True,
        question_text="What are you looking for in terms of the company, the culture, teams?\nAlso cover:\n- What's important for you?",
        request_payload={},
        ask_brief=AskBrief(
            primary_ask="What are you looking for in terms of the company, the culture, teams?",
            secondary_asks=["What's important for you?"],
            answer_family=AskFamily.CULTURE_FIT,
            answer_contract=AnswerContract.PREFERENCES_AND_ANTI_PATTERNS,
            confidence=0.9,
        ),
        confidence=0.9,
        planner_confidence=0.9,
        plan_stage="base",
        planner_source="deterministic",
    )
    question_key = _build_live_question_from_prepared_context(prepared_context, "").lower()
    inflight_checkpoint = LiveWarmCheckpoint(
        checkpoint_id="warm-inflight-compatible",
        parent_checkpoint_id=None,
        signature="warm-prefix-sig",
        question_key="what are you looking for in terms of the company, the culture, teams?",
        question_text="What are you looking for in terms of the company, the culture, teams?",
        conversation_history=prepared_context.sanitized_turns,
        prepared_context=prepared_context,
        created_at=datetime.utcnow(),
        source_generation=1,
    )
    inflight_task = MagicMock()
    inflight_task.done.return_value = False
    inflight_task.cancel = MagicMock()
    manager._live_warm_inflight_checkpoint = inflight_checkpoint
    manager._live_warm_inflight_task = inflight_task

    snapshot = LiveFrozenSnapshot(
        raw_turn_window=prepared_context.raw_turns,
        turn_window=prepared_context.sanitized_turns,
        raw_context_bundle={},
        signature=prepared_context.signature,
        question_text=prepared_context.question_text,
        conversation_history=prepared_context.sanitized_turns,
        prepared_context=prepared_context,
        request_payload={"question": prepared_context.question_text},
        question_source="live_prepared_context",
        cache_hit=False,
        checkpoint_id="freeze-checkpoint-compatible",
        question_key=question_key,
    )

    with patch(
        "api.server.asyncio.create_task",
        side_effect=AssertionError("compatible inflight checkpoint should be preserved"),
    ):
        manager._schedule_live_parallel_warm_from_snapshot(
            snapshot=snapshot,
            interview_config=pipeline.session_state.interview_config,
        )

    inflight_task.cancel.assert_not_called()
    assert manager._live_warm_inflight_checkpoint == inflight_checkpoint


@pytest.mark.asyncio
async def test_auto_silence_uses_compatible_warm_result_as_working_draft_for_final_writer():
    websocket = _FakeWebSocket()
    tracker = ConversationTracker()
    accepted = tracker.add_turn(
        speaker="interviewer",
        text="What are you looking for in terms of the company, the culture, teams? What's important for you?",
        utterance_count=1,
        start_time=0.0,
        end_time=1.0,
        reason="final",
    )
    assert accepted is True

    prepared_context = LivePreparedContext(
        raw_turns=[
            {
                "speaker": "interviewer",
                "text": "What are you looking for in terms of the company, the culture, teams? What's important for you?",
            }
        ],
        sanitized_turns=[
            {
                "speaker": "interviewer",
                "text": "What are you looking for in terms of the company, the culture, teams? What's important for you?",
            }
        ],
        turn_window_size=1,
        effective_turn_count=1,
        latest_turn_included=True,
        signature="seeded-live-sig",
        version=1,
        primary_ask="What are you looking for in terms of the company, the culture, teams?",
        secondary_asks=["What's important for you?"],
        ordered_focus=[
            "What are you looking for in terms of the company, the culture, teams?",
            "What's important for you?",
        ],
        asks_in_order=[
            "What are you looking for in terms of the company, the culture, teams?",
            "What's important for you?",
        ],
        answer_family=AskFamily.CULTURE_FIT,
        answer_contract=AnswerContract.PREFERENCES_AND_ANTI_PATTERNS,
        complexity_class=ComplexityClass.COMPOUND,
        answer_shape=AnswerShape.DIRECT_STRUCTURED,
        target_length=140,
        allow_metrics=False,
        allow_profile_opening=False,
        require_ordered_coverage=True,
        question_text="What are you looking for in terms of the company, the culture, teams?\nAlso cover:\n- What's important for you?",
        request_payload={},
        ask_brief=AskBrief(
            primary_ask="What are you looking for in terms of the company, the culture, teams?",
            secondary_asks=["What's important for you?"],
            answer_family=AskFamily.CULTURE_FIT,
            answer_contract=AnswerContract.PREFERENCES_AND_ANTI_PATTERNS,
            confidence=0.9,
        ),
        confidence=0.9,
        planner_confidence=0.9,
        plan_stage="base",
        planner_source="deterministic",
    )
    tracker.cache_live_prepared_context(prepared_context)

    pipeline = MagicMock()
    pipeline.process_question = AsyncMock()
    pipeline.conversation_tracker = tracker
    pipeline.ask_normalizer = MagicMock()
    pipeline.ask_normalizer.config.confidence_threshold = 0.72
    pipeline.live_question_planner = MagicMock()
    pipeline.live_question_planner.build_signature.return_value = "seeded-live-sig"
    pipeline.live_question_planner.prepare_base.return_value = prepared_context
    pipeline.session_state = MagicMock(
        interview_config={
            "delivery_mode": "manual",
            "style_id": "professional",
            "language_preference": "en",
            "max_words": 140,
            "candidate": {"name": "Daniel"},
            "company": {"companyName": "Cuesta"},
            "interviewer": {"name": "Marcus"},
        }
    )

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-seeded-warm",
        default_mode="real",
    )
    manager._silence_detector.should_trigger_suggestion = MagicMock(return_value=True)
    manager._silence_detector.record_trigger = MagicMock()
    manager._silence_detector.record_completion = MagicMock()
    manager._silence_detector.get_remaining_cooldown = MagicMock(return_value=0.0)
    manager._live_warm_latest_result = LiveWarmResult(
        checkpoint_id="warm-seed-1",
        signature="seed-prefix-sig",
        question_key="what are you looking for in terms of the company, the culture, teams?",
        question_text="What are you looking for in terms of the company, the culture, teams?",
        response=_shared_suggest_response("I look for a collaborative team, strong ownership, and clear execution."),
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
        success=True,
    )

    captured_working_draft: dict[str, str] = {}

    async def _seeded_suggest(**kwargs):
        captured_working_draft["value"] = kwargs.get("working_draft") or ""
        return _shared_suggest_response("Final strong answer")

    _force_hard_silence(manager)
    with patch("api.server._suggest_live_prepared_response", AsyncMock(side_effect=_seeded_suggest)):
        await manager._try_auto_trigger_suggestion(
            SpeakerTurn(
                speaker="interviewer",
                text="What are you looking for in terms of the company, the culture, teams?",
                start_time=0.0,
                end_time=1.0,
            ),
            generation_token=None,
        )

    suggestion_events = [event for event in websocket.events if event.get("type") == "suggestion"]
    assert suggestion_events
    assert suggestion_events[0]["full_response"] == "Final strong answer"
    assert suggestion_events[0]["path_used"] == "writer_seeded_fallback"
    assert suggestion_events[0]["warm_seed_used"] is True
    assert suggestion_events[0]["warm_seed_question_key"] == "what are you looking for in terms of the company, the culture, teams?"
    assert captured_working_draft["value"] == "I look for a collaborative team, strong ownership, and clear execution."


@pytest.mark.asyncio
async def test_auto_silence_waits_for_compatible_inflight_warm_seed_before_final_writer():
    websocket = _FakeWebSocket()
    tracker = ConversationTracker()
    accepted = tracker.add_turn(
        speaker="interviewer",
        text="What are you looking for in terms of the company, the culture, teams? What's important for you?",
        utterance_count=1,
        start_time=0.0,
        end_time=1.0,
        reason="final",
    )
    assert accepted is True

    prepared_context = LivePreparedContext(
        raw_turns=[
            {
                "speaker": "interviewer",
                "text": "What are you looking for in terms of the company, the culture, teams? What's important for you?",
            }
        ],
        sanitized_turns=[
            {
                "speaker": "interviewer",
                "text": "What are you looking for in terms of the company, the culture, teams? What's important for you?",
            }
        ],
        turn_window_size=1,
        effective_turn_count=1,
        latest_turn_included=True,
        signature="seeded-live-inflight-sig",
        version=1,
        primary_ask="What are you looking for in terms of the company, the culture, teams?",
        secondary_asks=["What's important for you?"],
        ordered_focus=[
            "What are you looking for in terms of the company, the culture, teams?",
            "What's important for you?",
        ],
        asks_in_order=[
            "What are you looking for in terms of the company, the culture, teams?",
            "What's important for you?",
        ],
        answer_family=AskFamily.CULTURE_FIT,
        answer_contract=AnswerContract.PREFERENCES_AND_ANTI_PATTERNS,
        complexity_class=ComplexityClass.COMPOUND,
        answer_shape=AnswerShape.DIRECT_STRUCTURED,
        target_length=140,
        allow_metrics=False,
        allow_profile_opening=False,
        require_ordered_coverage=True,
        question_text="What are you looking for in terms of the company, the culture, teams?\nAlso cover:\n- What's important for you?",
        request_payload={},
        ask_brief=AskBrief(
            primary_ask="What are you looking for in terms of the company, the culture, teams?",
            secondary_asks=["What's important for you?"],
            answer_family=AskFamily.CULTURE_FIT,
            answer_contract=AnswerContract.PREFERENCES_AND_ANTI_PATTERNS,
            confidence=0.9,
        ),
        confidence=0.9,
        planner_confidence=0.9,
        plan_stage="base",
        planner_source="deterministic",
    )
    tracker.cache_live_prepared_context(prepared_context)

    pipeline = MagicMock()
    pipeline.process_question = AsyncMock()
    pipeline.conversation_tracker = tracker
    pipeline.ask_normalizer = MagicMock()
    pipeline.ask_normalizer.config.confidence_threshold = 0.72
    pipeline.live_question_planner = MagicMock()
    pipeline.live_question_planner.build_signature.return_value = "seeded-live-inflight-sig"
    pipeline.live_question_planner.prepare_base.return_value = prepared_context
    pipeline.session_state = MagicMock(
        interview_config={
            "delivery_mode": "manual",
            "style_id": "professional",
            "language_preference": "en",
            "max_words": 140,
            "candidate": {"name": "Daniel"},
            "company": {"companyName": "Cuesta"},
            "interviewer": {"name": "Marcus"},
        }
    )

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-seeded-inflight",
        default_mode="real",
    )
    manager._silence_detector.should_trigger_suggestion = MagicMock(return_value=True)
    manager._silence_detector.record_trigger = MagicMock()
    manager._silence_detector.record_completion = MagicMock()
    manager._silence_detector.get_remaining_cooldown = MagicMock(return_value=0.0)
    manager._live_warm_wait_sec = 0.1

    inflight_checkpoint = LiveWarmCheckpoint(
        checkpoint_id="warm-seed-inflight-1",
        parent_checkpoint_id=None,
        signature="seed-prefix-sig",
        question_key="what are you looking for in terms of the company, the culture, teams?",
        question_text="What are you looking for in terms of the company, the culture, teams?",
        conversation_history=prepared_context.sanitized_turns,
        prepared_context=prepared_context,
        created_at=datetime.utcnow(),
        source_generation=1,
    )
    manager._live_warm_inflight_checkpoint = inflight_checkpoint

    async def _complete_inflight_seed() -> None:
        await asyncio.sleep(0.01)
        manager._live_warm_latest_result = LiveWarmResult(
            checkpoint_id="warm-seed-inflight-1",
            signature="seed-prefix-sig",
            question_key="what are you looking for in terms of the company, the culture, teams?",
            question_text="What are you looking for in terms of the company, the culture, teams?",
            response=_shared_suggest_response(
                "I look for a collaborative team, strong ownership, and clear execution."
            ),
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
            success=True,
        )

    manager._live_warm_inflight_task = asyncio.create_task(_complete_inflight_seed())

    captured_working_draft: dict[str, str] = {}

    async def _seeded_suggest(**kwargs):
        captured_working_draft["value"] = kwargs.get("working_draft") or ""
        return _shared_suggest_response("Final strong answer")

    _force_hard_silence(manager)
    try:
        with patch("api.server._suggest_live_prepared_response", AsyncMock(side_effect=_seeded_suggest)):
            await manager._try_auto_trigger_suggestion(
                SpeakerTurn(
                    speaker="interviewer",
                    text="What are you looking for in terms of the company, the culture, teams?",
                    start_time=0.0,
                    end_time=1.0,
                ),
                generation_token=None,
            )
    finally:
        with contextlib.suppress(asyncio.CancelledError):
            await manager._live_warm_inflight_task

    suggestion_events = [event for event in websocket.events if event.get("type") == "suggestion"]
    assert suggestion_events
    assert suggestion_events[0]["full_response"] == "Final strong answer"
    assert suggestion_events[0]["path_used"] == "writer_seeded_fallback"
    assert suggestion_events[0]["warm_seed_used"] is True
    assert suggestion_events[0]["warm_in_flight_at_silence"] is True
    assert suggestion_events[0]["warm_wait_ms"] >= 0
    assert captured_working_draft["value"] == "I look for a collaborative team, strong ownership, and clear execution."


@pytest.mark.asyncio
async def test_auto_silence_ignores_incompatible_warm_result_when_building_final_writer():
    websocket = _FakeWebSocket()
    tracker = ConversationTracker()
    accepted = tracker.add_turn(
        speaker="interviewer",
        text="What are you looking for in terms of the company, the culture, teams? What's important for you?",
        utterance_count=1,
        start_time=0.0,
        end_time=1.0,
        reason="final",
    )
    assert accepted is True

    prepared_context = LivePreparedContext(
        raw_turns=[
            {
                "speaker": "interviewer",
                "text": "What are you looking for in terms of the company, the culture, teams? What's important for you?",
            }
        ],
        sanitized_turns=[
            {
                "speaker": "interviewer",
                "text": "What are you looking for in terms of the company, the culture, teams? What's important for you?",
            }
        ],
        turn_window_size=1,
        effective_turn_count=1,
        latest_turn_included=True,
        signature="seeded-live-ignore-sig",
        version=1,
        primary_ask="What are you looking for in terms of the company, the culture, teams?",
        secondary_asks=["What's important for you?"],
        ordered_focus=[
            "What are you looking for in terms of the company, the culture, teams?",
            "What's important for you?",
        ],
        asks_in_order=[
            "What are you looking for in terms of the company, the culture, teams?",
            "What's important for you?",
        ],
        answer_family=AskFamily.CULTURE_FIT,
        answer_contract=AnswerContract.PREFERENCES_AND_ANTI_PATTERNS,
        complexity_class=ComplexityClass.COMPOUND,
        answer_shape=AnswerShape.DIRECT_STRUCTURED,
        target_length=140,
        allow_metrics=False,
        allow_profile_opening=False,
        require_ordered_coverage=True,
        question_text="What are you looking for in terms of the company, the culture, teams?\nAlso cover:\n- What's important for you?",
        request_payload={},
        ask_brief=AskBrief(
            primary_ask="What are you looking for in terms of the company, the culture, teams?",
            secondary_asks=["What's important for you?"],
            answer_family=AskFamily.CULTURE_FIT,
            answer_contract=AnswerContract.PREFERENCES_AND_ANTI_PATTERNS,
            confidence=0.9,
        ),
        confidence=0.9,
        planner_confidence=0.9,
        plan_stage="base",
        planner_source="deterministic",
    )
    tracker.cache_live_prepared_context(prepared_context)

    pipeline = MagicMock()
    pipeline.process_question = AsyncMock()
    pipeline.conversation_tracker = tracker
    pipeline.ask_normalizer = MagicMock()
    pipeline.ask_normalizer.config.confidence_threshold = 0.72
    pipeline.live_question_planner = MagicMock()
    pipeline.live_question_planner.build_signature.return_value = "seeded-live-ignore-sig"
    pipeline.live_question_planner.prepare_base.return_value = prepared_context
    pipeline.session_state = MagicMock(
        interview_config={
            "delivery_mode": "manual",
            "style_id": "professional",
            "language_preference": "en",
            "max_words": 140,
            "candidate": {"name": "Daniel"},
            "company": {"companyName": "Cuesta"},
            "interviewer": {"name": "Marcus"},
        }
    )

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-ignore-seed",
        default_mode="real",
    )
    manager._silence_detector.should_trigger_suggestion = MagicMock(return_value=True)
    manager._silence_detector.record_trigger = MagicMock()
    manager._silence_detector.record_completion = MagicMock()
    manager._silence_detector.get_remaining_cooldown = MagicMock(return_value=0.0)
    manager._live_warm_latest_result = LiveWarmResult(
        checkpoint_id="warm-seed-2",
        signature="unrelated-sig",
        question_key="tell me about yourself",
        question_text="Tell me about yourself",
        response=_shared_suggest_response("Warm result that should not be reused."),
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
        success=True,
    )

    captured_working_draft: dict[str, str] = {}

    async def _seedless_suggest(**kwargs):
        captured_working_draft["value"] = kwargs.get("working_draft") or ""
        return _shared_suggest_response("Final answer without seed")

    _force_hard_silence(manager)
    with patch("api.server._suggest_live_prepared_response", AsyncMock(side_effect=_seedless_suggest)):
        await manager._try_auto_trigger_suggestion(
            SpeakerTurn(
                speaker="interviewer",
                text="What are you looking for in terms of the company, the culture, teams?",
                start_time=0.0,
                end_time=1.0,
            ),
            generation_token=None,
        )

    suggestion_events = [event for event in websocket.events if event.get("type") == "suggestion"]
    assert suggestion_events
    assert suggestion_events[0]["full_response"] == "Final answer without seed"
    assert suggestion_events[0]["path_used"] == "writer_emergency_fallback"
    assert suggestion_events[0]["warm_seed_used"] is False
    assert suggestion_events[0]["warm_seed_question_key"] is None
    assert captured_working_draft["value"] == ""


@pytest.mark.asyncio
async def test_auto_silence_reuses_prewarmed_quality_writer_when_structured_question_matches():
    websocket = _FakeWebSocket()
    tracker = ConversationTracker()
    accepted = tracker.add_turn(
        speaker="interviewer",
        text="And or not the role, but, yeah, but basically what you have done in your experience. So now I just wanted to ask you, like, what are you looking for in terms of the company, the culture, teams? What's important for you",
        utterance_count=1,
        start_time=0.0,
        end_time=0.8,
        reason="final",
    )
    assert accepted is True
    accepted = tracker.add_turn(
        speaker="interviewer",
        text="the company, the culture, teams? What's important for you, or what kind of things you absolutely like.",
        utterance_count=2,
        start_time=0.9,
        end_time=1.6,
        reason="final",
    )
    assert accepted is True

    cached_context = LivePreparedContext(
        raw_turns=[
            {
                "speaker": "interviewer",
                "text": "What are you looking for in terms of the company, the culture, teams? What's important for you, or what kind of things you absolutely like?",
            }
        ],
        sanitized_turns=[
            {
                "speaker": "interviewer",
                "text": "What are you looking for in terms of the company, the culture, teams? What's important for you, or what kind of things you absolutely like?",
            }
        ],
        turn_window_size=1,
        effective_turn_count=1,
        latest_turn_included=True,
        signature="older-live-sig",
        primary_ask="what are you looking for in terms of the company, the culture, teams?",
        secondary_asks=["What's important for you, or what kind of things you absolutely like?"],
        ordered_focus=[
            "what are you looking for in terms of the company, the culture, teams?",
            "What's important for you, or what kind of things you absolutely like?",
        ],
        asks_in_order=[
            "what are you looking for in terms of the company, the culture, teams?",
            "What's important for you, or what kind of things you absolutely like?",
        ],
        question_text="what are you looking for in terms of the company, the culture, teams?\nAlso cover:\n- What's important for you, or what kind of things you absolutely like?",
        resolved_question="Answer these interviewer asks in order:\n1. what are you looking for in terms of the company, the culture, teams?\n2. What's important for you, or what kind of things you absolutely like?",
        ask_brief=AskBrief(
            primary_ask="what are you looking for in terms of the company, the culture, teams?",
            secondary_asks=["What's important for you, or what kind of things you absolutely like?"],
            answer_family=AskFamily.CULTURE_FIT,
            answer_contract=AnswerContract.PREFERENCES_AND_ANTI_PATTERNS,
            confidence=0.9,
        ),
        confidence=0.9,
        planner_confidence=0.9,
        plan_stage="base",
        planner_source="deterministic",
    )
    tracker.cache_live_prepared_context(cached_context)

    current_context = cached_context.model_copy(
        update={
            "signature": "newer-live-sig",
            "raw_turns": [
                {
                    "speaker": "interviewer",
                    "text": "And or not the role, but, yeah, but basically what you have done in your experience. So now I just wanted to ask you, like, what are you looking for in terms of the company, the culture, teams? What's important for you",
                },
                {
                    "speaker": "interviewer",
                    "text": "the company, the culture, teams? What's important for you, or what kind of things you absolutely like.",
                },
            ],
            "sanitized_turns": [
                {
                    "speaker": "interviewer",
                    "text": "And or not the role, but, yeah, but basically what you have done in your experience. So now I just wanted to ask you, like, what are you looking for in terms of the company, the culture, teams? What's important for you",
                },
                {
                    "speaker": "interviewer",
                    "text": "the company, the culture, teams? What's important for you, or what kind of things you absolutely like.",
                },
            ],
        }
    )
    tracker.cache_live_prepared_context(current_context)

    pipeline = MagicMock()
    pipeline.process_question = AsyncMock()
    pipeline.conversation_tracker = tracker
    pipeline.ask_normalizer = MagicMock()
    pipeline.ask_normalizer.config.confidence_threshold = 0.72
    pipeline.live_question_planner = MagicMock()
    pipeline.live_question_planner.build_signature.return_value = "newer-live-sig"
    pipeline.live_question_planner.prepare_base.return_value = current_context
    pipeline.live_question_planner.draft_from_prepared_context = AsyncMock(return_value=None)
    pipeline.live_question_planner.write_best_effort_from_prepared_context = AsyncMock()
    pipeline.session_state = MagicMock(
        interview_config={
            "delivery_mode": "manual",
            "style_id": "professional",
            "language_preference": "en",
            "max_words": 140,
            "candidate": {"name": "Daniel"},
            "company": {"companyName": "Cuesta"},
            "interviewer": {"name": "Marcus"},
        }
    )

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-prewarmed-equivalent",
        default_mode="real",
    )
    manager._live_semantic_grace_sec = 0.0
    manager._silence_detector.should_trigger_suggestion = MagicMock(return_value=True)
    manager._silence_detector.record_trigger = MagicMock()
    manager._silence_detector.record_completion = MagicMock()
    manager._silence_detector.get_remaining_cooldown = MagicMock(return_value=0.0)
    manager._live_quality_cached_signature = (
        "what are you looking for in terms of the company, the culture, teams?\n"
        "also cover:\n"
        "- what's important for you, or what kind of things you absolutely like?"
    )
    manager._live_quality_cached_context = cached_context
    manager._live_quality_cached_response = _shared_suggest_response()
    manager._live_quality_grace_sec = 0.0

    with patch(
        "api.server._suggest_live_prepared_response",
        AsyncMock(side_effect=AssertionError("matching structured question should reuse prewarmed quality response")),
    ) as live_suggest:
        _force_hard_silence(manager)
        await manager._try_auto_trigger_suggestion(
            SpeakerTurn(
                speaker="interviewer",
                text="What are you looking for in terms of the company and culture?",
                start_time=0.0,
                end_time=1.0,
            ),
            generation_token=None,
        )

    suggestion_events = [event for event in websocket.events if event.get("type") == "suggestion"]
    assert suggestion_events
    assert suggestion_events[0]["full_response"] == "Shared manual-quality answer"
    assert suggestion_events[0]["path_used"] == "writer_prewarmed_fallback"
    assert manager._live_quality_cached_signature == (
        "what are you looking for in terms of the company, the culture, teams?\n"
        "also cover:\n"
        "- what's important for you, or what kind of things you absolutely like?"
    )
    assert live_suggest.await_count == 0


@pytest.mark.asyncio
async def test_auto_silence_waits_briefly_for_inflight_quality_prewarm_before_heavy_fallback():
    websocket = _FakeWebSocket()
    tracker = ConversationTracker()
    accepted = tracker.add_turn(
        speaker="interviewer",
        text="What are you looking for in terms of the company, the culture, teams? What's important for you?",
        utterance_count=1,
        start_time=0.0,
        end_time=0.8,
        reason="final",
    )
    assert accepted is True

    prepared_context = LivePreparedContext(
        raw_turns=[
            {
                "speaker": "interviewer",
                "text": "What are you looking for in terms of the company, the culture, teams? What's important for you?",
            }
        ],
        sanitized_turns=[
            {
                "speaker": "interviewer",
                "text": "What are you looking for in terms of the company, the culture, teams? What's important for you?",
            }
        ],
        turn_window_size=1,
        effective_turn_count=1,
        latest_turn_included=True,
        signature="quality-wait-sig",
        version=1,
        primary_ask="What are you looking for in terms of the company, the culture, teams?",
        secondary_asks=["What's important for you?"],
        ordered_focus=[
            "What are you looking for in terms of the company, the culture, teams?",
            "What's important for you?",
        ],
        asks_in_order=[
            "What are you looking for in terms of the company, the culture, teams?",
            "What's important for you?",
        ],
        answer_family=AskFamily.CULTURE_FIT,
        answer_contract=AnswerContract.PREFERENCES_AND_ANTI_PATTERNS,
        complexity_class=ComplexityClass.COMPOUND,
        answer_shape=AnswerShape.DIRECT_STRUCTURED,
        target_length=140,
        allow_metrics=False,
        allow_profile_opening=False,
        require_ordered_coverage=True,
        question_text="What are you looking for in terms of the company, the culture, teams?\nAlso cover:\n- What's important for you?",
        request_payload={},
        ask_brief=AskBrief(
            primary_ask="What are you looking for in terms of the company, the culture, teams?",
            secondary_asks=["What's important for you?"],
            answer_family=AskFamily.CULTURE_FIT,
            answer_contract=AnswerContract.PREFERENCES_AND_ANTI_PATTERNS,
            confidence=0.9,
        ),
        confidence=0.9,
        planner_confidence=0.9,
        plan_stage="base",
        planner_source="deterministic",
    )
    tracker.cache_live_prepared_context(prepared_context)

    pipeline = MagicMock()
    pipeline.process_question = AsyncMock()
    pipeline.conversation_tracker = tracker
    pipeline.ask_normalizer = MagicMock()
    pipeline.ask_normalizer.config.confidence_threshold = 0.72
    pipeline.live_question_planner = MagicMock()
    pipeline.live_question_planner.build_signature.return_value = "quality-wait-sig"
    pipeline.live_question_planner.prepare_base.return_value = prepared_context
    pipeline.live_question_planner.draft_from_prepared_context = AsyncMock(return_value=None)
    pipeline.live_question_planner.write_best_effort_from_prepared_context = AsyncMock(
        side_effect=AssertionError("quality prewarm wait should avoid best-effort fallback")
    )
    pipeline.session_state = MagicMock(
        interview_config={
            "delivery_mode": "manual",
            "style_id": "professional",
            "language_preference": "en",
            "max_words": 140,
            "candidate": {"name": "Daniel"},
            "company": {"companyName": "Cuesta"},
            "interviewer": {"name": "Marcus"},
        }
    )

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-quality-wait",
        default_mode="real",
    )
    manager._live_semantic_grace_sec = 0.0
    manager._live_quality_grace_sec = 0.2
    manager._silence_detector.should_trigger_suggestion = MagicMock(return_value=True)
    manager._silence_detector.record_trigger = MagicMock()
    manager._silence_detector.record_completion = MagicMock()
    manager._silence_detector.get_remaining_cooldown = MagicMock(return_value=0.0)

    async def _complete_prewarm():
        await asyncio.sleep(0.05)
        manager._live_quality_cached_signature = (
            "what are you looking for in terms of the company, the culture, teams?\n"
            "also cover:\n"
            "- what's important for you?"
        )
        manager._live_quality_cached_context = prepared_context
        manager._live_quality_cached_response = _shared_suggest_response()

    manager._live_quality_refresh_signature = (
        "what are you looking for in terms of the company, the culture, teams?\n"
        "also cover:\n"
        "- what's important for you?"
    )
    manager._live_quality_refresh_task = asyncio.create_task(_complete_prewarm())

    with patch(
        "api.server._suggest_live_prepared_response",
        AsyncMock(side_effect=AssertionError("quality prewarm wait should avoid heavy fallback")),
    ):
        _force_hard_silence(manager)
        await manager._try_auto_trigger_suggestion(
            SpeakerTurn(
                speaker="interviewer",
                text="What are you looking for in terms of the company and culture?",
                start_time=0.0,
                end_time=1.0,
            ),
            generation_token=None,
        )

    suggestion_events = [event for event in websocket.events if event.get("type") == "suggestion"]
    assert suggestion_events
    assert suggestion_events[0]["full_response"] == "Shared manual-quality answer"
    assert suggestion_events[0]["path_used"] == "writer_prewarmed_fallback"
    assert suggestion_events[0]["quality_prewarm_wait_ms"] >= 0
    assert suggestion_events[0]["warm_in_flight_at_silence"] is True
    assert suggestion_events[0]["warm_wait_ms"] >= 0


@pytest.mark.asyncio
async def test_auto_silence_uses_same_frozen_snapshot_for_question_history_and_debug():
    websocket = _FakeWebSocket()
    tracker = ConversationTracker()
    accepted = tracker.add_turn(
        speaker="interviewer",
        text="your expectations in terms of the role and what you have done in your experience",
        utterance_count=1,
        start_time=0.0,
        end_time=0.8,
        reason="final",
    )
    assert accepted is True

    full_window = [
        {
            "speaker": "interviewer",
            "text": "your expectations in terms of the role and what you have done in your experience",
        },
        {
            "speaker": "interviewer",
            "text": "what are you looking for in terms of the company, the culture, teams? What's important for you, or what kind of things you absolutely like?",
        },
    ]

    frozen_context = LivePreparedContext(
        raw_turns=[
            dict(turn) for turn in full_window
        ],
        sanitized_turns=[
            dict(turn) for turn in full_window
        ],
        turn_window_size=2,
        effective_turn_count=2,
        latest_turn_included=True,
        signature="frozen-snapshot-sig",
        version=1,
        primary_ask="What are you looking for in terms of the company, the culture, teams?",
        secondary_asks=["What's important for you, or what kind of things you absolutely like?"],
        ordered_focus=[
            "What are you looking for in terms of the company, the culture, teams?",
            "What's important for you, or what kind of things you absolutely like?",
        ],
        asks_in_order=[
            "What are you looking for in terms of the company, the culture, teams?",
            "What's important for you, or what kind of things you absolutely like?",
        ],
        answer_family=AskFamily.CULTURE_FIT,
        answer_contract=AnswerContract.PREFERENCES_AND_ANTI_PATTERNS,
        complexity_class=ComplexityClass.COMPOUND,
        answer_shape=AnswerShape.DIRECT_STRUCTURED,
        target_length=140,
        allow_metrics=False,
        allow_profile_opening=False,
        require_ordered_coverage=True,
        question_text="What are you looking for in terms of the company, the culture, teams?\nAlso cover:\n- What's important for you, or what kind of things you absolutely like?",
        request_payload={
            "question": "What are you looking for in terms of the company, the culture, teams?\nAlso cover:\n- What's important for you, or what kind of things you absolutely like?",
            "conversation_history": [dict(turn) for turn in full_window],
        },
        ask_brief=AskBrief(
            primary_ask="What are you looking for in terms of the company, the culture, teams?",
            secondary_asks=["What's important for you, or what kind of things you absolutely like?"],
            answer_family=AskFamily.CULTURE_FIT,
            answer_contract=AnswerContract.PREFERENCES_AND_ANTI_PATTERNS,
            confidence=0.9,
        ),
        confidence=0.9,
        planner_confidence=0.9,
        plan_stage="base",
        planner_source="deterministic",
    )
    tracker.cache_live_prepared_context(frozen_context)

    pipeline = MagicMock()
    pipeline.process_question = AsyncMock()
    pipeline.conversation_tracker = tracker
    pipeline.ask_normalizer = MagicMock()
    pipeline.ask_normalizer.config.confidence_threshold = 0.72
    pipeline.live_question_planner = MagicMock()
    pipeline.live_question_planner.build_signature.return_value = "frozen-snapshot-sig"
    pipeline.live_question_planner.prepare_base.return_value = frozen_context
    pipeline.session_state = MagicMock(
        interview_config={
            "delivery_mode": "manual",
            "style_id": "professional",
            "language_preference": "en",
            "max_words": 140,
            "candidate": {"name": "Daniel"},
            "company": {"companyName": "Cuesta"},
            "interviewer": {"name": "Marcus"},
        }
    )

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-frozen-snapshot",
        default_mode="real",
    )
    manager._live_semantic_grace_sec = 0.0
    manager._silence_detector.should_trigger_suggestion = MagicMock(return_value=True)
    manager._silence_detector.record_trigger = MagicMock()
    manager._silence_detector.record_completion = MagicMock()
    manager._silence_detector.get_remaining_cooldown = MagicMock(return_value=0.0)
    manager._get_raw_live_turn_window = MagicMock(return_value=[dict(turn) for turn in full_window])

    with patch(
        "api.server._suggest_live_prepared_response",
        AsyncMock(return_value=_shared_suggest_response()),
    ) as live_suggest:
        _force_hard_silence(manager)
        await manager._try_auto_trigger_suggestion(
            SpeakerTurn(
                speaker="interviewer",
                text="what are you looking for in terms of the company, the culture, teams?",
                start_time=0.0,
                end_time=1.0,
            ),
            generation_token=None,
        )

    suggestion_events = [event for event in websocket.events if event.get("type") == "suggestion"]
    assert suggestion_events
    event = suggestion_events[0]
    debug = event["debug"]
    live_suggest.assert_awaited_once()
    call_kwargs = live_suggest.await_args.kwargs
    expected_question = "What are you looking for in terms of the company, the culture, teams?\nAlso cover:\n- What's important for you, or what kind of things you absolutely like?"
    assert call_kwargs["question_text"] == expected_question
    assert call_kwargs["conversation_history"] == full_window
    assert debug["question"] == expected_question
    assert debug["conversation_history"] == full_window
    assert debug["semantic_blocks_window"] == full_window
    assert debug["request_payload"]["question"] == expected_question
    assert debug["request_payload"]["conversation_history"] == full_window
    assert debug["snapshot_source"] == "frozen_snapshot_v2"
    assert debug["freeze_checkpoint_id"]
    assert event["snapshot_source"] == "frozen_snapshot_v2"


def test_build_live_question_from_prepared_context_prefers_structured_ordered_asks():
    prepared_context = LivePreparedContext(
        signature="question-structure-sig",
        question_text="expectations in terms of the role and what you have done in your experience so now i just wanted to ask you like what are you looking for in terms of",
        resolved_question="expectations in terms of the role and what you have done in your experience so now i just wanted to ask you like what are you looking for in terms of",
        primary_ask="What are you looking for in terms of the company, the culture, teams?",
        secondary_asks=["What's important for you?"],
        asks_in_order=[
            "What are you looking for in terms of the company, the culture, teams?",
            "What's important for you?",
        ],
        ordered_focus=[
            "What are you looking for in terms of the company, the culture, teams?",
            "What's important for you?",
        ],
        latest_turn_included=True,
    )

    question = _build_live_question_from_prepared_context(
        prepared_context,
        "fallback question",
    )

    assert question == (
        "What are you looking for in terms of the company, the culture, teams?\n"
        "Also cover:\n"
        "- What's important for you?"
    )


@pytest.mark.asyncio
async def test_auto_silence_uses_frozen_snapshot_without_stale_regeneration():
    websocket = _FakeWebSocket()
    pipeline = MagicMock()
    pipeline.process_question = AsyncMock()
    pipeline.conversation_tracker = ConversationTracker()
    pipeline.ask_normalizer = MagicMock()
    pipeline.ask_normalizer.config.confidence_threshold = 0.72
    pipeline.live_question_planner = MagicMock()
    pipeline.live_question_planner.build_signature.return_value = "latest-live-sig"
    pipeline.session_state = MagicMock(
        interview_config={
            "delivery_mode": "manual",
            "style_id": "professional",
            "language_preference": "en",
            "max_words": 140,
            "candidate": {"name": "Daniel"},
            "company": {"companyName": "Cuesta"},
            "interviewer": {"name": "Marcus"},
        }
    )

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-frozen-snapshot-once",
        default_mode="real",
    )
    manager._silence_detector.should_trigger_suggestion = MagicMock(return_value=True)
    manager._silence_detector.record_trigger = MagicMock()
    manager._silence_detector.record_completion = MagicMock()
    manager._silence_detector.get_remaining_cooldown = MagicMock(return_value=0.0)

    stale_context = LivePreparedContext(
        signature="stale-live-sig",
        question_text="Old question",
        sanitized_turns=[{"speaker": "interviewer", "text": "Old question"}],
        raw_turns=[{"speaker": "interviewer", "text": "Old question"}],
        primary_ask="Old question",
        latest_turn_included=True,
    )
    stale_snapshot = LiveFrozenSnapshot(
        raw_turn_window=[{"speaker": "interviewer", "text": "Old question"}],
        turn_window=[{"speaker": "interviewer", "text": "Old question"}],
        raw_context_bundle={"primary_question_index": 0, "interviewer_question_index": 0},
        signature="stale-live-sig",
        question_text="Old question",
        conversation_history=[{"speaker": "interviewer", "text": "Old question"}],
        prepared_context=stale_context,
        request_payload={"question": "Old question", "conversation_history": [{"speaker": "interviewer", "text": "Old question"}]},
        question_source="live_prepared_context",
        cache_hit=True,
    )
    stale_response = _shared_suggest_response()
    stale_response["full_response"] = "Stale answer"

    manager._build_live_frozen_snapshot = AsyncMock(return_value=stale_snapshot)
    manager._generate_live_response_from_snapshot = AsyncMock(
        return_value=(stale_response, "writer_emergency_fallback", 0, 0, False)
    )
    manager._live_snapshot_is_current = MagicMock(return_value=True)

    _force_hard_silence(manager)
    await manager._try_auto_trigger_suggestion(
        SpeakerTurn(
            speaker="interviewer",
            text="Latest question",
            start_time=0.0,
            end_time=1.0,
        ),
        generation_token=None,
    )

    suggestion_events = [event for event in websocket.events if event.get("type") == "suggestion"]
    assert suggestion_events
    event = suggestion_events[0]
    assert event["full_response"] == "Stale answer"
    assert event["question"] == "Old question"
    assert event["debug"]["current_signature"] == "stale-live-sig"
    assert event["debug"]["stale_snapshot_discarded"] is False
    manager._live_snapshot_is_current.assert_called_once()
    assert manager._build_live_frozen_snapshot.await_count == 1
    assert manager._generate_live_response_from_snapshot.await_count == 1


@pytest.mark.asyncio
async def test_auto_silence_does_not_emit_error_when_snapshot_changes_after_freeze():
    websocket = _FakeWebSocket()
    pipeline = MagicMock()
    pipeline.process_question = AsyncMock()
    pipeline.conversation_tracker = ConversationTracker()
    pipeline.ask_normalizer = MagicMock()
    pipeline.ask_normalizer.config.confidence_threshold = 0.72
    pipeline.live_question_planner = MagicMock()
    pipeline.live_question_planner.build_signature.return_value = "latest-live-sig"
    pipeline.session_state = MagicMock(
        interview_config={
            "delivery_mode": "manual",
            "style_id": "professional",
            "language_preference": "en",
            "max_words": 140,
            "candidate": {"name": "Daniel"},
            "company": {"companyName": "Cuesta"},
            "interviewer": {"name": "Marcus"},
        }
    )

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-no-stale-loop",
        default_mode="real",
    )
    manager._silence_detector.should_trigger_suggestion = MagicMock(return_value=True)
    manager._silence_detector.record_trigger = MagicMock()
    manager._silence_detector.record_completion = MagicMock()
    manager._silence_detector.get_remaining_cooldown = MagicMock(return_value=0.0)

    stale_context = LivePreparedContext(
        signature="stale-live-sig",
        question_text="Old question",
        sanitized_turns=[{"speaker": "interviewer", "text": "Old question"}],
        raw_turns=[{"speaker": "interviewer", "text": "Old question"}],
        primary_ask="Old question",
        latest_turn_included=True,
    )
    stale_snapshot = LiveFrozenSnapshot(
        raw_turn_window=[{"speaker": "interviewer", "text": "Old question"}],
        turn_window=[{"speaker": "interviewer", "text": "Old question"}],
        raw_context_bundle={"primary_question_index": 0, "interviewer_question_index": 0},
        signature="stale-live-sig",
        question_text="Old question",
        conversation_history=[{"speaker": "interviewer", "text": "Old question"}],
        prepared_context=stale_context,
        request_payload={"question": "Old question", "conversation_history": [{"speaker": "interviewer", "text": "Old question"}]},
        question_source="live_prepared_context",
        cache_hit=True,
    )
    stale_response = _shared_suggest_response()
    stale_response["full_response"] = "Stale answer"

    fresh_context = stale_context.model_copy(
        update={
            "signature": "fresh-live-sig",
            "question_text": "New question",
            "sanitized_turns": [{"speaker": "interviewer", "text": "New question"}],
            "raw_turns": [{"speaker": "interviewer", "text": "New question"}],
            "primary_ask": "New question",
        }
    )
    fresh_snapshot = LiveFrozenSnapshot(
        raw_turn_window=[{"speaker": "interviewer", "text": "New question"}],
        turn_window=[{"speaker": "interviewer", "text": "New question"}],
        raw_context_bundle={"primary_question_index": 0, "interviewer_question_index": 0},
        signature="fresh-live-sig",
        question_text="New question",
        conversation_history=[{"speaker": "interviewer", "text": "New question"}],
        prepared_context=fresh_context,
        request_payload={"question": "New question", "conversation_history": [{"speaker": "interviewer", "text": "New question"}]},
        question_source="live_prepared_context",
        cache_hit=True,
    )
    fresh_response = _shared_suggest_response()
    fresh_response["full_response"] = "Fresh answer"

    manager._build_live_frozen_snapshot = AsyncMock(side_effect=[stale_snapshot, fresh_snapshot])
    manager._generate_live_response_from_snapshot = AsyncMock(
        side_effect=[
            (stale_response, "writer_emergency_fallback", 0, 0, False),
            (fresh_response, "writer_emergency_fallback", 0, 0, False),
        ]
    )
    manager._live_snapshot_is_current = MagicMock(return_value=False)

    _force_hard_silence(manager)
    await manager._try_auto_trigger_suggestion(
        SpeakerTurn(
            speaker="interviewer",
            text="Still changing question",
            start_time=0.0,
            end_time=1.0,
        ),
        generation_token=None,
    )

    error_events = [event for event in websocket.events if event.get("type") == "error"]
    suggestion_events = [event for event in websocket.events if event.get("type") == "suggestion"]
    assert not error_events
    assert suggestion_events
    assert suggestion_events[0]["full_response"] == "Fresh answer"
    assert suggestion_events[0]["question"] == "New question"
    assert suggestion_events[0]["debug"]["stale_snapshot_discarded"] is True


@pytest.mark.asyncio
async def test_live_snapshot_is_current_accepts_same_structured_question_with_new_signature():
    websocket = _FakeWebSocket()
    tracker = ConversationTracker()
    pipeline = MagicMock()
    pipeline.process_question = AsyncMock()
    pipeline.conversation_tracker = tracker
    pipeline.ask_normalizer = MagicMock()
    pipeline.ask_normalizer.config.confidence_threshold = 0.72
    pipeline.live_question_planner = MagicMock()

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-current-same-question",
        default_mode="real",
    )

    snapshot_context = LivePreparedContext(
        signature="older-live-sig",
        question_text="What are you looking for in terms of the company, the culture, teams?\nAlso cover:\n- What's important for you?",
        primary_ask="What are you looking for in terms of the company, the culture, teams?",
        secondary_asks=["What's important for you?"],
        asks_in_order=[
            "What are you looking for in terms of the company, the culture, teams?",
            "What's important for you?",
        ],
        ordered_focus=[
            "What are you looking for in terms of the company, the culture, teams?",
            "What's important for you?",
        ],
        latest_turn_included=True,
    )
    latest_context = snapshot_context.model_copy(update={"signature": "newer-live-sig"})
    tracker.cache_live_prepared_context(latest_context)

    snapshot = LiveFrozenSnapshot(
        raw_turn_window=[{"speaker": "interviewer", "text": "Older raw transcript"}],
        turn_window=[{"speaker": "interviewer", "text": "Older raw transcript"}],
        raw_context_bundle={"primary_question_index": 0, "interviewer_question_index": 0},
        signature="older-live-sig",
        question_text=snapshot_context.question_text,
        conversation_history=[{"speaker": "interviewer", "text": "Older raw transcript"}],
        prepared_context=snapshot_context,
        request_payload={"question": snapshot_context.question_text, "conversation_history": [{"speaker": "interviewer", "text": "Older raw transcript"}]},
        question_source="live_prepared_context",
        cache_hit=True,
    )

    pipeline.live_question_planner.build_signature.return_value = "newer-live-sig"

    is_current = manager._live_snapshot_is_current(
        snapshot=snapshot,
        planner=pipeline.live_question_planner,
        generation_token=None,
        tracker=tracker,
    )

    assert is_current is True


@pytest.mark.asyncio
async def test_live_snapshot_is_current_accepts_same_structured_question_with_new_generation_token():
    websocket = _FakeWebSocket()
    tracker = ConversationTracker()
    pipeline = MagicMock()
    pipeline.process_question = AsyncMock()
    pipeline.conversation_tracker = tracker
    pipeline.ask_normalizer = MagicMock()
    pipeline.ask_normalizer.config.confidence_threshold = 0.72
    pipeline.live_question_planner = MagicMock()

    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-current-same-generation",
        default_mode="real",
    )
    manager._latest_interviewer_generation = 9

    snapshot_context = LivePreparedContext(
        signature="older-live-sig",
        question_text="What are you looking for in terms of the company, the culture, teams?\nAlso cover:\n- What's important for you?",
        primary_ask="What are you looking for in terms of the company, the culture, teams?",
        secondary_asks=["What's important for you?"],
        asks_in_order=[
            "What are you looking for in terms of the company, the culture, teams?",
            "What's important for you?",
        ],
        ordered_focus=[
            "What are you looking for in terms of the company, the culture, teams?",
            "What's important for you?",
        ],
        latest_turn_included=True,
    )
    tracker.cache_live_prepared_context(snapshot_context.model_copy(update={"signature": "newer-live-sig"}))

    snapshot = LiveFrozenSnapshot(
        raw_turn_window=[{"speaker": "interviewer", "text": "Older raw transcript"}],
        turn_window=[{"speaker": "interviewer", "text": "Older raw transcript"}],
        raw_context_bundle={"primary_question_index": 0, "interviewer_question_index": 0},
        signature="older-live-sig",
        question_text=snapshot_context.question_text,
        conversation_history=[{"speaker": "interviewer", "text": "Older raw transcript"}],
        prepared_context=snapshot_context,
        request_payload={"question": snapshot_context.question_text, "conversation_history": [{"speaker": "interviewer", "text": "Older raw transcript"}]},
        question_source="live_prepared_context",
        cache_hit=True,
    )

    is_current = manager._live_snapshot_is_current(
        snapshot=snapshot,
        planner=pipeline.live_question_planner,
        generation_token=7,
        tracker=tracker,
    )

    assert is_current is True


@pytest.mark.asyncio
async def test_build_live_v3_response_payload_preserves_paragraph_breaks():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()
    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-v3-paragraphs",
        default_mode="real",
    )

    brain_plan = BrainPlan(
        session_id="session-stt-live-v3-paragraphs",
        utterance_id="u-live-v3-paragraphs",
        revision_id=1,
        snapshot_hash="hash-live-v3-paragraphs",
        ordered_asks=[
            "Tell me about your experience building from zero.",
            "Tell me about your team management experience.",
        ],
        resolved_question=(
            "Answer these interviewer asks in order:\n"
            "1. Tell me about your experience building from zero.\n"
            "2. Tell me about your team management experience."
        ),
        response_shape="direct_structured",
        answer_contract="business_with_outcomes",
        directness="balanced",
        metrics_policy="avoid_unless_helpful",
        target_length=180,
        confidence=0.82,
        question_completeness="complete",
        plan_source="safe_fallback",
    )
    evidence_pack = CompactEvidencePack(
        plan_hash="plan-hash-live-v3-paragraphs",
        candidate_snippets=[],
        company_snippets=[],
        interviewer_snippets=[],
        supporting_metrics=[],
        excluded_topics=[],
        mode="minimal",
    )
    snapshot = LiveFrozenSnapshot(
        raw_turn_window=[{"speaker": "interviewer", "text": "Tell me about your experience building from zero."}],
        turn_window=[{"speaker": "interviewer", "text": "Tell me about your experience building from zero."}],
        raw_context_bundle={},
        signature="sig-live-v3-paragraphs",
        question_text=brain_plan.resolved_question,
        conversation_history=[{"speaker": "interviewer", "text": "Tell me about your experience building from zero."}],
        prepared_context=None,
        request_payload={"question": brain_plan.resolved_question},
        question_source="brain_v4",
        cache_hit=False,
        brain_plan=brain_plan,
        compact_evidence_pack=evidence_pack,
        plan_hash="plan-hash-live-v3-paragraphs",
    )

    payload = manager._build_live_v3_response_payload(
        snapshot=snapshot,
        interview_config=pipeline.session_state.interview_config,
        final_result={
            "full_response": (
                "I've built several things from zero.\n\n"
                "Most recently, I founded a generative AI practice and built reusable assets.\n\n"
                "On team management, I've led both focused squads and large multi-region organizations."
            ),
            "bullets": [],
            "confidence": 0.84,
            "latency_ms": 1200,
            "metadata": {"finalizer_fallback_kind": "llm"},
        },
        path_used="brain_finalize_from_plan",
    )

    assert "\n\nMost recently," in payload["full_response"]
    assert "\n\nOn team management," in payload["full_response"]
    assert "\n\nMost recently," in payload["suggestion"]["full_response"]



@pytest.mark.asyncio
async def test_schedule_live_semantic_refresh_cancels_stale_inflight_task():
    websocket = _FakeWebSocket()
    pipeline = _build_live_pipeline_stub()
    manager = SessionSTTStreamManager(
        websocket=websocket,
        pipeline=pipeline,
        session_id="session-stt-live-cancel-stale",
        default_mode="real",
    )

    tracker = pipeline.conversation_tracker

    async def _old_refresh():
        await asyncio.sleep(10)

    old_task = asyncio.create_task(_old_refresh())
    manager._live_semantic_refresh_task = old_task
    manager._live_semantic_refresh_signature = "stale-sig"

    prepared_context = LivePreparedContext(
        raw_turns=[{"speaker": "interviewer", "text": "Tell me about your leadership experience"}],
        sanitized_turns=[{"speaker": "interviewer", "text": "Tell me about your leadership experience"}],
        turn_window_size=1,
        effective_turn_count=1,
        latest_turn_included=True,
        signature="fresh-sig",
        primary_ask="Tell me about your leadership experience",
        ordered_focus=["Tell me about your leadership experience"],
        asks_in_order=["Tell me about your leadership experience"],
        question_text="Tell me about your leadership experience",
    )

    planner = MagicMock()
    planner.enrich = AsyncMock(return_value=None)

    manager._schedule_live_semantic_refresh(
        planner=planner,
        tracker=tracker,
        prepared_context=prepared_context,
        interview_config={},
    )
    await asyncio.sleep(0)

    assert old_task.cancelled() is True
    assert manager._live_semantic_refresh_signature == "fresh-sig"
