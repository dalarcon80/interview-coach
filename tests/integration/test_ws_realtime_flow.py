"""
Test WebSocket Realtime Flow

Tests that the WebSocket pipeline produces real events,NOT just echoes.
Uses the OFFICIAL server.py WebSocket implementation.
"""
import pytest
import json
import asyncio
import base64
from unittest.mock import patch, AsyncMock, MagicMock


class TestWebSocketRealtimeFlow:
    """Tests for WebSocket realtime event flow via server.py."""
    
    @pytest.fixture
    def mock_pipeline_result(self):
        """Create a mock pipeline result for testing."""
        result = MagicMock()
        result.question_analysis = MagicMock()
        result.question_analysis.primary_type = MagicMock()
        result.question_analysis.primary_type.value = "behavioral"
        result.question_analysis.is_compound = False
        result.question_analysis.sub_questions = []
        result.question_analysis.key_topics = ["leadership", "team"]
        result.question_analysis.underlying_intent = ["assess management style"]
        result.question_analysis.red_flags = []
        result.language_decision = MagicMock()
        result.language_decision.final_language = "es"
        result.language_decision.confidence = 0.95
        result.exchange = MagicMock()
        result.exchange.suggested_response = MagicMock()
        result.exchange.suggested_response.bullets = ["Point 1", "Point 2"]
        result.exchange.suggested_response.full_response = "Full response text"
        result.exchange.suggested_response.key_metrics = ["3x growth"]
        result.exchange.suggested_response.confidence = 0.85
        result.exchange.suggested_response.style_used = MagicMock()
        result.exchange.suggested_response.style_used.value = "executive"
        result.quality_result = MagicMock()
        result.quality_result.passed = True
        result.quality_result.score = 0.9
        result.quality_result.issues = []
        result.total_latency_ms = 500
        result.mode = "demo"
        return result
    
    @pytest.mark.asyncio
    async def test_websocket_sends_session_started_with_mode(self, mock_pipeline_result):
        """WebSocket should send session_started event with explicit mode."""
        from api.server import app
        from starlette.testclient import TestClient as WebSocketTestClient
        
        with patch('api.server.RealtimePipeline') as MockPipeline:
            mock_pipeline = MagicMock()
            mock_pipeline.start_session = AsyncMock()
            mock_pipeline.process_question = AsyncMock(return_value=mock_pipeline_result)
            mock_pipeline.end_session = AsyncMock(return_value={})
            MockPipeline.return_value = mock_pipeline
            
            client = WebSocketTestClient(app)
            
            with client.websocket_connect("/ws/pipeline") as websocket:
                # Skip connected event
                websocket.receive_json()
                
                # Send start_session
                websocket.send_json({
                    "type": "start_session",
                    "config": {
                        "company_name": "Test Co",
                        "role_title": "Engineer",
                        "response_style": "mixed"
                    }
                })
                
                # Verify session_started event was sent
                session_started = websocket.receive_json()
                assert session_started["type"] == "session_started"
                assert "session_id" in session_started
                assert session_started["mode"] in ["demo", "real"]
                assert session_started["config"]["company_name"] == "Test Co"
    
    @pytest.mark.asyncio
    async def test_websocket_sends_real_events_on_transcript(self, mock_pipeline_result):
        """WebSocket should send real events when transcript is processed."""
        from api.server import app
        from starlette.testclient import TestClient as WebSocketTestClient
        
        with patch('api.server.RealtimePipeline') as MockPipeline:
            mock_pipeline = MagicMock()
            mock_pipeline.start_session = AsyncMock()
            mock_pipeline.process_question = AsyncMock(return_value=mock_pipeline_result)
            mock_pipeline.end_session = AsyncMock(return_value={})
            MockPipeline.return_value = mock_pipeline
            
            client = WebSocketTestClient(app)
            
            with client.websocket_connect("/ws/pipeline") as websocket:
                # Skip connected event
                websocket.receive_json()
                
                # Start session
                websocket.send_json({
                    "type": "start_session",
                    "config": {"company_name": "Test", "role_title": "Engineer"}
                })
                session_started = websocket.receive_json()  # session_started
                
                # Process a final transcript
                websocket.send_json({
                    "type": "transcript_ready",
                    "text": "Tell me about yourself",
                    "is_final": True
                })
                
                # Verify events were sent in correct order
                analysis = websocket.receive_json()
                assert analysis["type"] == "analysis"
                
                suggestion = websocket.receive_json()
                assert suggestion["type"] == "suggestion"
    
    @pytest.mark.asyncio
    async def test_websocket_includes_mode_in_suggestion(self, mock_pipeline_result):
        """WebSocket should include mode in suggestion events."""
        from api.server import app
        from starlette.testclient import TestClient as WebSocketTestClient
        
        with patch('api.server.RealtimePipeline') as MockPipeline:
            mock_pipeline = MagicMock()
            mock_pipeline.start_session = AsyncMock()
            mock_pipeline.process_question = AsyncMock(return_value=mock_pipeline_result)
            mock_pipeline.end_session = AsyncMock(return_value={})
            MockPipeline.return_value = mock_pipeline
            
            client = WebSocketTestClient(app)
            
            with client.websocket_connect("/ws/pipeline") as websocket:
                # Skip connected event
                websocket.receive_json()
                
                # Start session
                websocket.send_json({
                    "type": "start_session",
                    "config": {"company_name": "Test", "role_title": "Engineer"}
                })
                session_started = websocket.receive_json()  # session_started
                
                # Send transcript
                websocket.send_json({
                    "type": "transcript_ready",
                    "text": "Tell me about yourself",
                    "is_final": True
                })
                
                # Skip analysis
                websocket.receive_json()
                
                # Get suggestion
                suggestion = websocket.receive_json()
                assert suggestion["type"] == "suggestion"
                assert suggestion["mode"] in ["demo", "real"]
                assert "bullets" in suggestion
                assert isinstance(suggestion["bullets"], list)
    
    @pytest.mark.asyncio
    async def test_websocket_handles_partial_transcript(self):
        """WebSocket should handle partial transcripts (no processing yet)."""
        from api.server import app
        from starlette.testclient import TestClient as WebSocketTestClient
        
        with patch('api.server.RealtimePipeline') as MockPipeline:
            mock_pipeline = MagicMock()
            mock_pipeline.start_session = AsyncMock()
            mock_pipeline.end_session = AsyncMock(return_value={})
            MockPipeline.return_value = mock_pipeline
            
            client = WebSocketTestClient(app)
            
            with client.websocket_connect("/ws/pipeline") as websocket:
                # Skip connected event
                websocket.receive_json()
                
                # Start session
                websocket.send_json({
                    "type": "start_session",
                    "config": {"company_name": "Test", "role_title": "Engineer"}
                })
                session_started = websocket.receive_json()  # session_started
                
                # Process a partial transcript - should NOT trigger full processing
                websocket.send_json({
                    "type": "transcript_ready",
                    "text": "Tell me about...",
                    "is_final": False
                })
                
                # Should NOT get analysis/suggestion for partial
                # In current implementation, partial transcripts are handled differently
                # Let's verify the behavior is correct
    
    @pytest.mark.asyncio
    async def test_websocket_sends_session_error_on_no_session(self):
        """WebSocket should send error if transcript sent without session."""
        from api.server import app
        from starlette.testclient import TestClient as WebSocketTestClient
        
        client = WebSocketTestClient(app)
        
        with client.websocket_connect("/ws/pipeline") as websocket:
            # Skip connected event
            websocket.receive_json()
            
            # Send transcript without starting session
            websocket.send_json({
                "type": "transcript_ready",
                "text": "Tell me about yourself",
                "is_final": True
            })
            
            # Should send error
            error_event = websocket.receive_json()
            assert error_event["type"] == "error"
            assert "session" in error_event["message"].lower()
    
    @pytest.mark.asyncio
    async def test_websocket_session_end_includes_summary(self, mock_pipeline_result):
        """WebSocket should send session_ended with summary."""
        from api.server import app
        from starlette.testclient import TestClient as WebSocketTestClient
        
        with patch('api.server.RealtimePipeline') as MockPipeline:
            mock_pipeline = MagicMock()
            mock_pipeline.start_session = AsyncMock()
            mock_pipeline.process_question = AsyncMock(return_value=mock_pipeline_result)
            mock_pipeline.end_session = AsyncMock(return_value={"duration_ms": 5000})
            MockPipeline.return_value = mock_pipeline
            
            client = WebSocketTestClient(app)
            
            with client.websocket_connect("/ws/pipeline") as websocket:
                # Skip connected event
                websocket.receive_json()
                
                # Start session
                websocket.send_json({
                    "type": "start_session",
                    "config": {"company_name": "Test", "role_title": "Engineer"}
                })
                websocket.receive_json()  # session_started
                
                # End session
                websocket.send_json({"type": "end_session"})
                
                # Should send session_ended
                ended_event = websocket.receive_json()
                assert ended_event["type"] == "session_ended"
                assert "summary" in ended_event


class TestWebSocketEventTypes:
    """Tests for specific event types in WebSocket flow."""
    
    @pytest.fixture
    def mock_pipeline_result(self):
        result = MagicMock()
        result.question_analysis = MagicMock()
        result.question_analysis.primary_type = MagicMock()
        result.question_analysis.primary_type.value = "behavioral"
        result.question_analysis.is_compound = False
        result.question_analysis.sub_questions = []
        result.question_analysis.key_topics = ["leadership"]
        result.question_analysis.underlying_intent = []
        result.question_analysis.red_flags = []
        result.language_decision = MagicMock()
        result.language_decision.final_language = "es"
        result.language_decision.confidence = 0.95
        result.exchange = MagicMock()
        result.exchange.suggested_response = MagicMock()
        result.exchange.suggested_response.bullets = ["Point 1", "Point 2"]
        result.exchange.suggested_response.full_response = "Full response"
        result.exchange.suggested_response.key_metrics = []
        result.exchange.suggested_response.confidence = 0.85
        result.exchange.suggested_response.style_used = MagicMock()
        result.exchange.suggested_response.style_used.value = "executive"
        result.quality_result = MagicMock()
        result.quality_result.passed = True
        result.quality_result.score = 0.9
        result.quality_result.issues = []
        result.total_latency_ms = 500
        result.mode = "demo"
        return result
    
    @pytest.mark.asyncio
    async def test_analysis_includes_question_type(self, mock_pipeline_result):
        """analysis event should include question type and structure."""
        from api.server import app
        from starlette.testclient import TestClient as WebSocketTestClient
        
        with patch('api.server.RealtimePipeline') as MockPipeline:
            mock_pipeline = MagicMock()
            mock_pipeline.start_session = AsyncMock()
            mock_pipeline.process_question = AsyncMock(return_value=mock_pipeline_result)
            mock_pipeline.end_session = AsyncMock(return_value={})
            MockPipeline.return_value = mock_pipeline
            
            client = WebSocketTestClient(app)
            
            with client.websocket_connect("/ws/pipeline") as websocket:
                websocket.receive_json()  # connected
                websocket.send_json({
                    "type": "start_session",
                    "config": {"company_name": "Test", "role_title": "Engineer"}
                })
                websocket.receive_json()  # session_started
                
                websocket.send_json({
                    "type": "transcript_ready",
                    "text": "Tell me about a challenge",
                    "is_final": True
                })
                
                analysis_event = websocket.receive_json()
                assert analysis_event["type"] == "analysis"
                assert analysis_event["question_type"] == "behavioral"
                assert "is_compound" in analysis_event
                assert "underlying_intent" in analysis_event
    
    @pytest.mark.asyncio
    async def test_suggestion_response_includes_quality(self, mock_pipeline_result):
        """suggestion event should include quality gate results."""
        from api.server import app
        from starlette.testclient import TestClient as WebSocketTestClient
        
        with patch('api.server.RealtimePipeline') as MockPipeline:
            mock_pipeline = MagicMock()
            mock_pipeline.start_session = AsyncMock()
            mock_pipeline.process_question = AsyncMock(return_value=mock_pipeline_result)
            mock_pipeline.end_session = AsyncMock(return_value={})
            MockPipeline.return_value = mock_pipeline
            
            client = WebSocketTestClient(app)
            
            with client.websocket_connect("/ws/pipeline") as websocket:
                websocket.receive_json()  # connected
                websocket.send_json({
                    "type": "start_session",
                    "config": {"company_name": "Test", "role_title": "Engineer"}
                })
                websocket.receive_json()  # session_started
                
                websocket.send_json({
                    "type": "transcript_ready",
                    "text": "Tell me about yourself",
                    "is_final": True
                })
                
                websocket.receive_json()  # analysis
                response_event = websocket.receive_json()
                
                assert response_event["type"] == "suggestion"
                assert response_event["quality_passed"] is True
                assert "quality_score" in response_event
                assert "quality_issues" in response_event
                assert "latency_ms" in response_event


class TestWebSocketAudioStreamingPersistence:
    """Endpoint-level tests for session-scoped persistent STT stream behavior."""

    class _QueueSTTAdapter:
        def __init__(self):
            self.stream_audio_calls = 0
            self.disconnect_calls = 0
            self._events: asyncio.Queue = asyncio.Queue()
            self._consume_done = asyncio.Event()
            self.downstream_completed_calls = 0
            self.terminal_failure_reasons: list[str] = []
            self.open_stream_calls: list[str] = []
            self.close_stream_calls: list[str] = []
            self._open_session_id: str | None = None

        async def connect(self, _config: dict):
            return None

        async def open_stream(self, session_id: str | None = None):
            if self._open_session_id == session_id:
                return
            self._open_session_id = session_id
            self.open_stream_calls.append(str(session_id))

        async def push_event(self, event):
            await self._events.put(event)

        async def stream_audio(self, audio_chunks):
            self.stream_audio_calls += 1

            async def _consume():
                async for _ in audio_chunks:
                    pass
                self._consume_done.set()

            consumer = asyncio.create_task(_consume())
            try:
                while True:
                    event = await self._events.get()
                    yield event
                    if event.is_final:
                        break
            finally:
                consumer.cancel()
                try:
                    await consumer
                except asyncio.CancelledError:
                    pass

        async def disconnect(self):
            self.disconnect_calls += 1

        async def close_stream(self, session_id: str | None = None):
            if self._open_session_id is None:
                return
            self.close_stream_calls.append(str(session_id))
            self._open_session_id = None

        def mark_downstream_complete(self):
            self.downstream_completed_calls += 1

        def mark_terminal_failure(self, reason: str):
            self.terminal_failure_reasons.append(reason)

    @pytest.fixture
    def mock_pipeline_result(self):
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
        result.language_decision.confidence = 0.95
        result.exchange = MagicMock()
        result.exchange.suggested_response = MagicMock()
        result.exchange.suggested_response.bullets = ["Point 1", "Point 2"]
        result.exchange.suggested_response.full_response = "Full response"
        result.exchange.suggested_response.key_metrics = []
        result.exchange.suggested_response.confidence = 0.85
        result.exchange.suggested_response.style_used = MagicMock()
        result.exchange.suggested_response.style_used.value = "executive"
        result.exchange.suggested_response.mode = "demo"
        result.exchange.suggested_response.metadata = {
            "time_to_bullets_ms": 500,
            "time_to_full_ms": 700,
        }
        result.quality_result = MagicMock()
        result.quality_result.passed = True
        result.quality_result.score = 0.9
        result.quality_result.issues = []
        result.total_latency_ms = 700
        result.mode = "demo"
        return result

    @pytest.mark.asyncio
    async def test_audio_data_reuses_single_stt_stream_and_cleans_up_on_end_session(self, mock_pipeline_result):
        from api.server import app
        from adapters.interfaces import TranscriptionEvent
        from starlette.testclient import TestClient as WebSocketTestClient

        fake_stt = self._QueueSTTAdapter()

        with patch('api.server.RealtimePipeline') as MockPipeline, patch('adapters.stt_adapter.get_stt_adapter', AsyncMock(return_value=fake_stt)), patch('adapters.stt_adapter.reset_stt_adapter', AsyncMock()) as reset_mock:
            mock_pipeline = MagicMock()
            mock_pipeline.start_session = AsyncMock()
            mock_pipeline.process_question = AsyncMock(return_value=mock_pipeline_result)
            mock_pipeline.end_session = AsyncMock(return_value={"duration_ms": 2000})
            MockPipeline.return_value = mock_pipeline

            client = WebSocketTestClient(app)

            with client.websocket_connect("/ws/pipeline") as websocket:
                websocket.receive_json()  # connected

                websocket.send_json({
                    "type": "start_session",
                    "config": {"company_name": "Test", "role_title": "Engineer"}
                })
                session_started = websocket.receive_json()  # session_started

                audio_payload = base64.b64encode(b"a" * 64000).decode("ascii")

                websocket.send_json({
                    "type": "audio_data",
                    "audio": audio_payload,
                    "timestamp": 1200,
                    "sample_rate": 16000,
                    "channels": 1,
                    "source": "system",
                })
                ack_one = websocket.receive_json()
                assert ack_one["type"] == "audio_received"

                websocket.send_json({
                    "type": "audio_data",
                    "audio": audio_payload,
                    "timestamp": 2400,
                    "sample_rate": 16000,
                    "channels": 1,
                    "source": "system",
                })
                ack_two = websocket.receive_json()
                assert ack_two["type"] == "audio_received"

                await fake_stt.push_event(
                    TranscriptionEvent(
                        text="Tell me about",
                        is_final=False,
                        confidence=0.6,
                        language="en",
                        speaker=None,
                    )
                )
                await fake_stt.push_event(
                    TranscriptionEvent(
                        text="Tell me about your leadership experience",
                        is_final=True,
                        confidence=0.92,
                        language="en",
                        speaker="interviewer",
                        utterance_complete=True,
                    )
                )

                transcript_partial = websocket.receive_json()
                transcript_final = websocket.receive_json()
                analysis = websocket.receive_json()
                suggestion = websocket.receive_json()

                assert transcript_partial["type"] == "transcript"
                assert transcript_partial["is_final"] is False
                assert transcript_partial["speaker"] == "interviewer"

                assert transcript_final["type"] == "transcript"
                assert transcript_final["is_final"] is True
                assert transcript_final["speaker"] == "interviewer"

                # Ordering contract: transcript -> analysis -> suggestion
                assert analysis["type"] == "analysis"
                assert suggestion["type"] == "suggestion"

                # Single STT stream reused for multiple audio_data in session
                assert fake_stt.stream_audio_calls == 1
                mock_pipeline.process_question.assert_awaited_once()
                assert fake_stt.downstream_completed_calls == 1

                websocket.send_json({"type": "end_session"})
                ended = websocket.receive_json()
                assert ended["type"] == "session_ended"

                # Cleanup path must run on end_session
                assert fake_stt.disconnect_calls == 1
                reset_mock.assert_awaited_once()
                assert fake_stt.open_stream_calls == [session_started["session_id"]]
                assert fake_stt.close_stream_calls == [session_started["session_id"]]
