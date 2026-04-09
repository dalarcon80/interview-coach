"""
Test Realtime Session End-to-End

Validates the complete realtime session flow through WebSocket.
Tests the OFFICIAL implementation in server.py, NOT the deprecated ws_realtime.py.
"""
import pytest
import time
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient


class TestRealtimeSessionE2E:
    """End-to-end tests for realtime WebSocket session."""

    def _read_first_suggestion(self, websocket):
        """Read events until first suggestion payload (analysis may be emitted first)."""
        first_event = websocket.receive_json()
        if first_event["type"] == "analysis":
            suggestion = websocket.receive_json()
            assert suggestion["type"] == "suggestion"
            return first_event, suggestion

        assert first_event["type"] == "suggestion"
        return None, first_event
    
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
        result.exchange.suggested_response.mode = "demo"
        result.quality_result = MagicMock()
        result.quality_result.passed = True
        result.quality_result.score = 0.9
        result.quality_result.issues = []
        result.total_latency_ms = 500
        result.mode = "demo"
        return result
    
    def test_websocket_connect_sends_connected_event(self):
        """WebSocket should send 'connected' event on connection."""
        from api.server import app
        from starlette.testclient import TestClient as WebSocketTestClient
        
        client = WebSocketTestClient(app)
        
        with client.websocket_connect("/ws/pipeline") as websocket:
            # Should receive connected event
            data = websocket.receive_json()
            assert data["type"] == "connected"
            assert "message" in data
            assert "timestamp" in data
    
    def test_websocket_start_session_returns_session_id(self, mock_pipeline_result):
        """WebSocket should create session and return session_started event."""
        from api.server import app
        from starlette.testclient import TestClient as WebSocketTestClient
        
        with patch('pipeline.realtime_pipeline.RealtimePipeline') as MockPipeline:
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
                        "company_name": "Test Corp",
                        "role_title": "Senior Engineer",
                        "response_style": "executive"
                    }
                })
                
                # Receive session_started
                data = websocket.receive_json()
                assert data["type"] == "session_started"
                assert "session_id" in data
                assert data["config"]["company_name"] == "Test Corp"
                assert data["mode"] in ["demo", "real"]
    
    def test_websocket_transcript_returns_analysis_and_suggestion(self, mock_pipeline_result):
        """WebSocket should return analysis and suggestion for transcript."""
        from api.server import app
        from starlette.testclient import TestClient as WebSocketTestClient
        
        with patch('pipeline.realtime_pipeline.RealtimePipeline') as MockPipeline:
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
                websocket.receive_json()  # session_started
                
                # Send transcript
                websocket.send_json({
                    "type": "transcript_ready",
                    "text": "Tell me about your leadership experience",
                    "is_final": True
                })

                analysis, suggestion = self._read_first_suggestion(websocket)
                if analysis is not None:
                    assert analysis["question_type"] == "behavioral"
                    assert "is_compound" in analysis

                assert suggestion["type"] == "suggestion"
                assert "bullets" in suggestion
                assert "full_response" in suggestion
                assert suggestion["mode"] in ["demo", "real"]
    
    def test_websocket_end_session_returns_summary(self, mock_pipeline_result):
        """WebSocket should return session summary on end_session."""
        from api.server import app
        from starlette.testclient import TestClient as WebSocketTestClient
        
        with patch('pipeline.realtime_pipeline.RealtimePipeline') as MockPipeline:
            mock_pipeline = MagicMock()
            mock_pipeline.start_session = AsyncMock()
            mock_pipeline.process_question = AsyncMock(return_value=mock_pipeline_result)
            mock_pipeline.end_session = AsyncMock(return_value={"duration_ms": 5000, "exchanges": 1})
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
                
                # Should receive session_ended
                data = websocket.receive_json()
                assert data["type"] == "session_ended"
                assert "summary" in data
    
    def test_websocket_ping_returns_pong(self):
        """WebSocket should respond to ping with pong."""
        from api.server import app
        from starlette.testclient import TestClient as WebSocketTestClient
        
        client = WebSocketTestClient(app)
        
        with client.websocket_connect("/ws/pipeline") as websocket:
            # Skip connected event
            websocket.receive_json()
            
            # Send ping
            websocket.send_json({"type": "ping"})
            
            # Receive pong
            data = websocket.receive_json()
            assert data["type"] == "pong"
    
    def test_websocket_error_without_session(self):
        """WebSocket should return error if transcript sent without session."""
        from api.server import app
        from starlette.testclient import TestClient as WebSocketTestClient
        
        client = WebSocketTestClient(app)
        
        with client.websocket_connect("/ws/pipeline") as websocket:
            # Skip connected event
            websocket.receive_json()
            
            # Send transcript without starting session
            websocket.send_json({
                "type": "transcript_ready",
                "text": "Hello",
                "is_final": True
            })
            
            # Should receive error
            data = websocket.receive_json()
            assert data["type"] == "error"
            assert "session" in data["message"].lower()


class TestFrontendBackendContracts:
    """Tests for contract alignment between frontend and backend."""
    
    def test_suggest_request_contract_matches_tauri(self):
        """Verify /api/suggest accepts Tauri app request format."""
        from api.server import app
        from fastapi.testclient import TestClient
        
        mock_result = MagicMock()
        mock_result.question_analysis = MagicMock()
        mock_result.question_analysis.primary_type = MagicMock()
        mock_result.question_analysis.primary_type.value = "behavioral"
        mock_result.question_analysis.is_compound = False
        mock_result.question_analysis.sub_questions = []
        mock_result.question_analysis.key_topics = []
        mock_result.question_analysis.underlying_intent = []
        mock_result.question_analysis.red_flags = []
        mock_result.language_decision = MagicMock()
        mock_result.language_decision.final_language = "es"
        mock_result.language_decision.confidence = 0.9
        mock_result.exchange = MagicMock()
        mock_result.exchange.suggested_response = MagicMock()
        mock_result.exchange.suggested_response.bullets = ["Test"]
        mock_result.exchange.suggested_response.full_response = "Test"
        mock_result.exchange.suggested_response.key_metrics = []
        mock_result.exchange.suggested_response.confidence = 0.8
        mock_result.exchange.suggested_response.style_used = MagicMock()
        mock_result.exchange.suggested_response.style_used.value = "mixed"
        mock_result.exchange.suggested_response.mode = "demo"
        mock_result.quality_result = MagicMock()
        mock_result.quality_result.passed = True
        mock_result.quality_result.score = 0.9
        mock_result.quality_result.issues = []
        mock_result.total_latency_ms = 100
        mock_result.mode = "demo"
        
        with patch('api.server.check_api_keys_available', return_value=False):
            with patch('pipeline.realtime_pipeline.RealtimePipeline') as MockPipeline:
                mock_pipeline = MagicMock()
                mock_pipeline.start_session = AsyncMock()
                mock_pipeline.process_question = AsyncMock(return_value=mock_result)
                MockPipeline.return_value = mock_pipeline
                
                client = TestClient(app)
                
                # This is the exact format sent by Tauri app
                response = client.post("/api/suggest", json={
                    "questionText": "Tell me about yourself",
                    "style": "mixed",
                    "candidate": {"name": "Test User"},
                    "company": {
                        "companyName": "Target Company",
                        "roleTitle": "Senior Engineer"
                    }
                })
                
                assert response.status_code == 200
                data = response.json()
                assert data["success"] is True
                assert "suggestion" in data
                assert "mode" in data
    
    def test_websocket_message_contract_matches_frontend(self):
        """Verify WebSocket message format matches frontend expectations."""
        from api.server import app
        from starlette.testclient import TestClient as WebSocketTestClient
        
        mock_result = MagicMock()
        mock_result.question_analysis = MagicMock()
        mock_result.question_analysis.primary_type = MagicMock()
        mock_result.question_analysis.primary_type.value = "technical"
        mock_result.question_analysis.is_compound = True
        mock_result.question_analysis.sub_questions = []
        mock_result.question_analysis.key_topics = ["system design"]
        mock_result.question_analysis.underlying_intent = []
        mock_result.question_analysis.red_flags = []
        mock_result.language_decision = MagicMock()
        mock_result.language_decision.final_language = "en"
        mock_result.language_decision.confidence = 0.95
        mock_result.exchange = MagicMock()
        mock_result.exchange.suggested_response = MagicMock()
        mock_result.exchange.suggested_response.bullets = ["Use microservices", "Add caching layer"]
        mock_result.exchange.suggested_response.full_response = "Full response..."
        mock_result.exchange.suggested_response.key_metrics = ["99.9% uptime"]
        mock_result.exchange.suggested_response.confidence = 0.88
        mock_result.exchange.suggested_response.style_used = MagicMock()
        mock_result.exchange.suggested_response.style_used.value = "technical"
        mock_result.exchange.suggested_response.mode = "demo"
        mock_result.quality_result = MagicMock()
        mock_result.quality_result.passed = True
        mock_result.quality_result.score = 0.92
        mock_result.quality_result.issues = []
        mock_result.total_latency_ms = 450
        mock_result.mode = "demo"
        
        with patch('pipeline.realtime_pipeline.RealtimePipeline') as MockPipeline:
            mock_pipeline = MagicMock()
            mock_pipeline.start_session = AsyncMock()
            mock_pipeline.process_question = AsyncMock(return_value=mock_result)
            mock_pipeline.end_session = AsyncMock(return_value={})
            MockPipeline.return_value = mock_pipeline
            
            client = WebSocketTestClient(app)
            
            with client.websocket_connect("/ws/pipeline") as websocket:
                # Skip connected
                websocket.receive_json()
                
                # Start session (format from frontend)
                websocket.send_json({
                    "type": "start_session",
                    "config": {
                        "company_name": "TechCorp",
                        "role_title": "Senior Engineer",
                        "response_style": "technical",
                        "language_preference": "auto"
                    }
                })
                
                session_started = websocket.receive_json()
                assert session_started["type"] == "session_started"
                
                # Send transcript (format from frontend)
                websocket.send_json({
                    "type": "transcript_ready",
                    "text": "How would you design a scalable system?",
                    "is_final": True,
                    "language": "en"
                })

                analysis = websocket.receive_json()
                if analysis["type"] == "analysis":
                    assert "question_type" in analysis
                    assert "is_compound" in analysis
                    suggestion = websocket.receive_json()
                else:
                    suggestion = analysis

                assert suggestion["type"] == "suggestion"
                assert "bullets" in suggestion
                assert "full_response" in suggestion
                assert "mode" in suggestion
                assert "quality_passed" in suggestion
                assert "latency_ms" in suggestion


class TestRealtimeSessionE2EUseful:
    """Realtime E2E verification for bullets usefulness and tracker continuity."""

    def _send_turn_and_collect_events(self, websocket, question_text: str) -> dict:
        """Send one transcript turn and collect analysis + bullets + full events with timing."""
        turn_start = time.perf_counter()

        websocket.send_json({
            "type": "transcript_ready",
            "text": question_text,
            "is_final": True,
            "language": "en",
        })

        analysis = websocket.receive_json()
        analysis_received = time.perf_counter()
        assert analysis["type"] == "analysis"

        bullets_event = websocket.receive_json()
        bullets_received = time.perf_counter()
        assert bullets_event["type"] == "suggestion"
        assert bullets_event.get("stage") == "bullets"

        full_event = websocket.receive_json()
        full_received = time.perf_counter()
        assert full_event["type"] == "suggestion"
        assert full_event.get("stage") == "full"

        return {
            "analysis": analysis,
            "bullets_event": bullets_event,
            "full_event": full_event,
            "analysis_wall_ms": int((analysis_received - turn_start) * 1000),
            "bullets_wall_ms": int((bullets_received - turn_start) * 1000),
            "full_wall_ms": int((full_received - turn_start) * 1000),
        }

    def test_realtime_session_multiturn_useful_bullets_and_tracker_continuity(self):
        """
        R4.1 E2E verification:
        1) start session with full context
        2) process two transcript turns
        3) verify bullets-first then full response timing bounds
        4) verify bullets usefulness heuristics
        5) verify tracker continuity across turns
        """
        from api.server import app
        from starlette.testclient import TestClient as WebSocketTestClient

        session_config = {
            "response_style": "executive",
            "language_preference": "en",
            "candidate": {
                "name": "Alex Rivera",
                "summary": "Engineering leader with distributed systems and team scaling experience.",
                "skills": ["Python", "System Design", "Leadership", "Mentoring"],
                "achievements": [
                    "Scaled a platform from 5 to 50 engineers in 18 months",
                    "Reduced p95 latency by 40%",
                ],
                "certifications": ["AWS Solutions Architect"],
            },
            "company": {
                "companyName": "GrowthTech",
                "positionTitle": "Senior Engineering Manager",
                "industry": "SaaS",
                "companyDescription": "B2B SaaS company scaling globally",
                "positionRequirements": [
                    "Lead cross-functional engineering teams",
                    "Own scalable architecture decisions",
                ],
                "companyCulture": "Ownership, collaboration, customer obsession",
            },
        }

        client = WebSocketTestClient(app)
        with patch("api.server.check_api_keys_available", return_value=False):
            with client.websocket_connect("/ws/pipeline") as websocket:
                connected = websocket.receive_json()
                assert connected["type"] == "connected"

                websocket.send_json({
                    "type": "start_session",
                    "config": session_config,
                })
                session_started = websocket.receive_json()
                assert session_started["type"] == "session_started"
                assert session_started["mode"] == "demo"
                assert session_started["config"]["candidate"]["name"] == "Alex Rivera"
                assert session_started["config"]["company"]["companyName"] == "GrowthTech"

                first_turn = self._send_turn_and_collect_events(
                    websocket,
                    "Tell me about your leadership experience",
                )

                # Full context should influence analysis intent
                first_intents = [intent.lower() for intent in first_turn["analysis"]["underlying_intent"]]
                assert any("explicit role requirements" in intent for intent in first_intents)
                assert any("culture and collaboration fit" in intent for intent in first_intents)

                # Bullets-first timing contract (SLA cap checks)
                assert first_turn["bullets_wall_ms"] <= 4000
                assert first_turn["full_wall_ms"] <= 8000
                assert first_turn["full_wall_ms"] >= first_turn["bullets_wall_ms"]

                # Payload timing metadata should also respect ordering and cap
                assert first_turn["bullets_event"]["bullets_latency_ms"] <= 4000
                assert first_turn["full_event"]["full_latency_ms"] <= 8000
                assert first_turn["full_event"]["full_latency_ms"] >= first_turn["bullets_event"]["bullets_latency_ms"]

                # Bullets usefulness heuristics: relevant + actionable + quantified
                bullets = first_turn["bullets_event"]["bullets"]
                assert len(bullets) >= 2
                assert any("lead" in bullet.lower() or "team" in bullet.lower() for bullet in bullets)
                assert any(any(char.isdigit() for char in bullet) for bullet in bullets)
                assert first_turn["full_event"]["full_response"].strip() != ""

                second_turn = self._send_turn_and_collect_events(
                    websocket,
                    "You mentioned leadership earlier. Why this company?",
                )

                # Follow-up detection should reflect conversation continuity
                assert second_turn["analysis"]["question_type"] == "follow_up"

                websocket.send_json({"type": "end_session"})
                session_ended = websocket.receive_json()
                assert session_ended["type"] == "session_ended"

                summary = session_ended["summary"]
                assert summary["total_exchanges"] == 2
                assert "leadership" in summary["topics_covered"]
                assert len(summary["metrics_used"]) >= 1
                assert isinstance(summary["warnings"], list)
