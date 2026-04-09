"""
Unit tests for websocket STT forwarding helper in server.py.

Validates transcript forwarding and final-turn pipeline triggering for
_process_audio_for_stt().
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from adapters.interfaces import TranscriptionEvent
from api.server import _process_audio_for_stt


class _FakeWebSocket:
    def __init__(self):
        self.events: list[dict] = []

    async def send_json(self, payload: dict):
        self.events.append(payload)


class _FakeSTTAdapter:
    def __init__(self, events):
        self._events = events

    async def stream_audio(self, _audio_chunks):
        for event in self._events:
            yield event


def _mock_pipeline_result(mode: str = "real"):
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
    result.exchange.suggested_response.bullets = ["Led a team of 8 engineers"]
    result.exchange.suggested_response.full_response = "I led a team of 8 engineers..."
    result.exchange.suggested_response.key_metrics = ["8 engineers"]
    result.exchange.suggested_response.confidence = 0.9
    result.exchange.suggested_response.style_used = MagicMock()
    result.exchange.suggested_response.style_used.value = "executive"
    result.exchange.suggested_response.metadata = {
        "time_to_bullets_ms": 900,
        "time_to_full_ms": 1500,
        "provider": "anthropic",
        "model": "claude-3-5-sonnet",
    }

    result.quality_result = MagicMock()
    result.quality_result.passed = True
    result.quality_result.score = 0.93
    result.quality_result.issues = []
    result.total_latency_ms = 1500
    result.mode = mode
    return result


@pytest.mark.asyncio
async def test_process_audio_for_stt_emits_transcript_and_suggestion_for_final():
    websocket = _FakeWebSocket()
    stt_events = [
        TranscriptionEvent(
            text="Tell me",
            is_final=False,
            confidence=0.6,
            language="en",
            speaker="interviewer",
        ),
        TranscriptionEvent(
            text="Tell me about your leadership experience",
            is_final=True,
            confidence=0.92,
            language="en",
            speaker="interviewer",
        ),
    ]

    pipeline = MagicMock()
    pipeline.process_question = AsyncMock(return_value=_mock_pipeline_result(mode="real"))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("adapters.stt_adapter.get_stt_adapter", AsyncMock(return_value=_FakeSTTAdapter(stt_events)))
        await _process_audio_for_stt(
            audio_bytes=b"fake-pcm-audio",
            websocket=websocket,
            session_id="session-1",
            pipeline=pipeline,
            source="system",
        )

    transcript_events = [event for event in websocket.events if event.get("type") == "transcript"]
    suggestion_events = [event for event in websocket.events if event.get("type") == "suggestion"]

    assert len(transcript_events) == 2
    assert transcript_events[0]["is_final"] is False
    assert transcript_events[1]["is_final"] is True
    assert transcript_events[1]["speaker"] == "interviewer"
    assert transcript_events[1]["source"] == "system"

    pipeline.process_question.assert_awaited_once()
    assert len(suggestion_events) == 1
    assert suggestion_events[0]["mode"] == "real"
    assert suggestion_events[0]["stage"] == "full"
    assert suggestion_events[0]["full_response"].strip() != ""


@pytest.mark.asyncio
async def test_process_audio_for_stt_does_not_process_pipeline_without_final_text():
    websocket = _FakeWebSocket()
    stt_events = [
        TranscriptionEvent(
            text="Tell me about",
            is_final=False,
            confidence=0.55,
            language="en",
            speaker="interviewer",
        )
    ]

    pipeline = MagicMock()
    pipeline.process_question = AsyncMock(return_value=_mock_pipeline_result(mode="demo"))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("adapters.stt_adapter.get_stt_adapter", AsyncMock(return_value=_FakeSTTAdapter(stt_events)))
        await _process_audio_for_stt(
            audio_bytes=b"fake-pcm-audio",
            websocket=websocket,
            session_id="session-2",
            pipeline=pipeline,
            source="system",
        )

    transcript_events = [event for event in websocket.events if event.get("type") == "transcript"]
    suggestion_events = [event for event in websocket.events if event.get("type") == "suggestion"]

    assert len(transcript_events) == 1
    assert transcript_events[0]["is_final"] is False
    pipeline.process_question.assert_not_awaited()
    assert suggestion_events == []
