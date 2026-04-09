"""
Test Suggest Mode - Demo vs Real

Tests that /api/suggest correctly identifies and reports its mode.
"""
import pytest
import os
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient


STRUCTURED_CV_TEXT = """
JOHN DOE
Senior Engineer

PROFESSIONAL SUMMARY

Senior engineer with 10 years of Python and distributed systems experience leading backend modernization.

KEY ACHIEVEMENTS

- Improved latency by 40% on a core platform migration.
- Led a team at Google delivering large backend projects.

AREAS OF EXPERTISE

- Python
- Distributed Systems
- Leadership

PROFESSIONAL EXPERIENCE

Google — Senior Engineer
2020 – Present
"""


INSUFFICIENT_SIGNAL_CV_TEXT = """
linkedin.com/in/sample-profile-without-usable-candidate-identity
contact@test.example
http://portfolio.example.com/no-clear-role-or-company-details
+57 300 000 0000
"""


def _minimal_candidate_payload() -> dict:
    return {
        "name": "Ana",
        "current_role": "Technology Director - Data & AI",
        "company": "Globant",
        "summary": "Technology executive with global data and AI leadership experience.",
        "skills": ["Leadership", "Data strategy"],
        "achievements": ["Led modernization across enterprise clients"],
        "certifications": ["AWS SAA"],
    }


def _minimal_company_payload() -> dict:
    return {
        "companyName": "Slalom",
        "positionTitle": "Director - Data Architecture & Engineering",
        "industry": "Consulting",
    }


class TestSuggestModeIndicator:
    """Tests for mode indicator in /api/suggest endpoint."""
    
    @pytest.fixture
    def mock_pipeline_result(self):
        """Create a mock pipeline result."""
        result = MagicMock()
        result.question_analysis = MagicMock()
        result.question_analysis.primary_type = MagicMock()
        result.question_analysis.primary_type.value = "behavioral"
        result.question_analysis.question_mode = MagicMock()
        result.question_analysis.question_mode.value = "experience_based"
        result.question_analysis.response_mode = MagicMock()
        result.question_analysis.response_mode.value = "interview_answer"
        result.question_analysis.style_reason = "default"
        result.question_analysis.why_metrics_required = False
        result.question_analysis.is_compound = False
        result.question_analysis.sub_questions = []
        result.question_analysis.key_topics = []
        result.question_analysis.underlying_intent = []
        result.question_analysis.red_flags = []
        result.question_analysis.ask_brief = None
        result.question_analysis.normalizer_applied = False
        result.question_analysis.normalizer_fallback_used = True
        result.language_decision = MagicMock()
        result.language_decision.final_language = "es"
        result.language_decision.confidence = 0.9
        result.exchange = MagicMock()
        result.exchange.suggested_response = MagicMock()
        result.exchange.suggested_response.bullets = ["Point 1"]
        result.exchange.suggested_response.full_response = "Response"
        result.exchange.suggested_response.key_metrics = []
        result.exchange.suggested_response.confidence = 0.8
        result.exchange.suggested_response.style_used = MagicMock()
        result.exchange.suggested_response.style_used.value = "mixed"
        result.quality_result = MagicMock()
        result.quality_result.passed = True
        result.quality_result.score = 0.9
        result.quality_result.issues = []
        result.total_latency_ms = 100
        result.mode = "demo"
        return result
    
    @pytest.mark.asyncio
    async def test_suggest_returns_demo_mode_without_api_keys(self, mock_pipeline_result):
        """Suggest should surface the explicit safe fallback mode when no grounded evidence is available."""
        from api.server import app
        from contracts.models import GeneratedResponse, ResponseStyle

        with patch.dict(os.environ, {}, clear=True):
            with patch('api.server.check_api_keys_available', return_value=False):
                async def fake_compose(self, context, on_bullets=None):
                    return GeneratedResponse(
                        bullets=["Point 1"],
                        full_response="Response",
                        key_metrics=[],
                        confidence=0.8,
                        style_used=ResponseStyle.MIXED,
                        generation_time_ms=1,
                        mode="safe_fallback",
                        metadata={},
                    )

                with patch("pipeline.steps.response_composer.ResponseComposer.compose", new=fake_compose):

                    client = TestClient(app)
                    response = client.post("/api/suggest", json={
                        "questionText": "Tell me about yourself",
                        "style": "mixed",
                        "candidate": _minimal_candidate_payload(),
                        "company": _minimal_company_payload(),
                    })

                    assert response.status_code == 200
                    data = response.json()
                    assert data["success"] is True
                    assert data["mode"] == "safe_fallback"

    def test_suggest_returns_real_mode_with_api_keys(self, mock_pipeline_result):
        """Suggest should return mode='real' when API keys are configured."""
        from api.server import app
        from contracts.models import GeneratedResponse, ResponseStyle

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            with patch('api.server.check_api_keys_available', return_value=True):
                async def fake_compose(self, context, on_bullets=None):
                    return GeneratedResponse(
                        bullets=["Point 1"],
                        full_response="Response",
                        key_metrics=[],
                        confidence=0.8,
                        style_used=ResponseStyle.MIXED,
                        generation_time_ms=1,
                        mode="real",
                        metadata={"provider": "anthropic", "model": "claude-sonnet-test"},
                    )

                with patch("pipeline.steps.response_composer.ResponseComposer.compose", new=fake_compose):

                    client = TestClient(app)
                    response = client.post("/api/suggest", json={
                        "questionText": "Tell me about yourself",
                        "style": "mixed",
                        "candidate": _minimal_candidate_payload(),
                        "company": _minimal_company_payload(),
                    })
                    
                    assert response.status_code == 200
                    data = response.json()
                    assert data["success"] is True
                    assert data["mode"] == "real"
                    assert data["llm"]["provider"] == "anthropic"
                    assert data["llm"]["model"] == "claude-sonnet-test"

    def test_suggest_returns_fallback_mode_when_pipeline_response_fallback(self, mock_pipeline_result):
        """Suggest should expose fallback mode when composer falls back from real path."""
        from api.server import app
        from contracts.models import GeneratedResponse, ResponseStyle

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            with patch('api.server.check_api_keys_available', return_value=True):
                async def fake_compose(self, context, on_bullets=None):
                    return GeneratedResponse(
                        bullets=["Point 1"],
                        full_response="Response",
                        key_metrics=[],
                        confidence=0.8,
                        style_used=ResponseStyle.MIXED,
                        generation_time_ms=1,
                        mode="fallback",
                        metadata={
                            "provider": "anthropic",
                            "model": "claude-sonnet-test",
                            "fallback_reason": "error: upstream timeout",
                        },
                    )

                with patch("pipeline.steps.response_composer.ResponseComposer.compose", new=fake_compose):

                    client = TestClient(app)
                    response = client.post("/api/suggest", json={
                        "questionText": "Tell me about yourself",
                        "style": "mixed",
                        "candidate": _minimal_candidate_payload(),
                        "company": _minimal_company_payload(),
                    })

                    assert response.status_code == 200
                    data = response.json()
                    assert data["success"] is True
                    assert data["mode"] == "fallback"

    def test_suggest_real_mode_label_is_from_response_not_key_presence(self, mock_pipeline_result):
        """Mode label should follow pipeline response mode, not only API key presence."""
        from api.server import app
        from contracts.models import GeneratedResponse, ResponseStyle

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            with patch('api.server.check_api_keys_available', return_value=True):
                async def fake_compose(self, context, on_bullets=None):
                    return GeneratedResponse(
                        bullets=["Point 1"],
                        full_response="Response",
                        key_metrics=[],
                        confidence=0.8,
                        style_used=ResponseStyle.MIXED,
                        generation_time_ms=1,
                        mode="demo",
                        metadata={},
                    )

                with patch("pipeline.steps.response_composer.ResponseComposer.compose", new=fake_compose):

                    client = TestClient(app)
                    response = client.post("/api/suggest", json={
                        "questionText": "Tell me about yourself",
                        "style": "mixed",
                        "candidate": _minimal_candidate_payload(),
                        "company": _minimal_company_payload(),
                    })

                    assert response.status_code == 200
                    data = response.json()
                    assert data["success"] is True
                    assert data["mode"] == "demo"
    
    @pytest.mark.asyncio
    async def test_suggest_returns_error_mode_on_exception(self):
        """Suggest should return mode='error' on pipeline exceptions."""
        from api.server import app

        async def broken_compose(self, context, on_bullets=None):
            raise Exception("Pipeline error")

        with patch("pipeline.steps.response_composer.ResponseComposer.compose", new=broken_compose):
            
            client = TestClient(app)
            response = client.post("/api/suggest", json={
                "questionText": "Tell me about yourself",
                "style": "mixed",
                "candidate": _minimal_candidate_payload(),
                "company": _minimal_company_payload(),
            })
            
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is False
            assert data["mode"] == "error"
            assert "error" in data
    
    @pytest.mark.asyncio
    async def test_suggest_requires_question(self):
        """Suggest should return error if no question provided."""
        from api.server import app
        
        client = TestClient(app)
        response = client.post("/api/suggest", json={
            "style": "mixed"
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["mode"] == "error"


class TestSuggestResponseStructure:
    """Tests for response structure from /api/suggest."""
    
    @pytest.fixture
    def mock_pipeline_result(self):
        result = MagicMock()
        result.question_analysis = MagicMock()
        result.question_analysis.primary_type = MagicMock()
        result.question_analysis.primary_type.value = "technical"
        result.question_analysis.question_mode = MagicMock()
        result.question_analysis.question_mode.value = "conceptual"
        result.question_analysis.response_mode = MagicMock()
        result.question_analysis.response_mode.value = "hybrid_dual"
        result.question_analysis.style_reason = "technical conceptual question"
        result.question_analysis.why_metrics_required = False
        result.question_analysis.is_compound = True
        result.question_analysis.sub_questions = [
            MagicMock(text="Q1", priority=MagicMock(value="must_answer"), weight=0.6),
            MagicMock(text="Q2", priority=MagicMock(value="should_answer"), weight=0.4),
        ]
        result.question_analysis.key_topics = ["architecture", "scalability"]
        result.question_analysis.underlying_intent = ["assess technical depth"]
        result.question_analysis.red_flags = []
        result.question_analysis.ask_brief = None
        result.question_analysis.normalizer_applied = False
        result.question_analysis.normalizer_fallback_used = True
        result.language_decision = MagicMock()
        result.language_decision.final_language = "en"
        result.language_decision.confidence = 0.95
        result.exchange = MagicMock()
        result.exchange.suggested_response = MagicMock()
        result.exchange.suggested_response.bullets = ["Bullet 1", "Bullet 2", "Bullet 3"]
        result.exchange.suggested_response.full_response = "Full response text here"
        result.exchange.suggested_response.key_metrics = ["50%", "2x"]
        result.exchange.suggested_response.confidence = 0.85
        result.exchange.suggested_response.style_used = MagicMock()
        result.exchange.suggested_response.style_used.value = "technical"
        result.quality_result = MagicMock()
        result.quality_result.passed = True
        result.quality_result.score = 0.92
        result.quality_result.issues = []
        result.total_latency_ms = 350
        result.mode = "demo"
        return result
    
    @pytest.mark.asyncio
    async def test_suggest_includes_full_analysis(self, mock_pipeline_result):
        """Suggest response should include full question analysis."""
        from api.server import app
        
        with patch('api.server.check_api_keys_available', return_value=False):
            with patch('api.server.RealtimePipeline') as MockPipeline:
                mock_pipeline = MagicMock()
                mock_pipeline.start_session = AsyncMock()
                mock_pipeline.process_question = AsyncMock(return_value=mock_pipeline_result)
                MockPipeline.return_value = mock_pipeline
                
                client = TestClient(app)
                response = client.post("/api/suggest", json={
                    "questionText": "How would you design a scalable system?",
                    "style": "technical",
                    "candidate": _minimal_candidate_payload(),
                    "company": _minimal_company_payload(),
                })
                
                data = response.json()
                assert "suggestion" in data

                suggestion = data["suggestion"]
                assert suggestion["questionType"] == "technical"
                assert isinstance(suggestion["isCompound"], bool)
                assert isinstance(suggestion["subQuestions"], list)
                assert isinstance(suggestion["underlyingIntent"], list)
    
    @pytest.mark.asyncio
    async def test_suggest_includes_quality_results(self, mock_pipeline_result):
        """Suggest response should include quality gate results."""
        from api.server import app
        
        with patch('api.server.check_api_keys_available', return_value=False):
            with patch('api.server.RealtimePipeline') as MockPipeline:
                mock_pipeline = MagicMock()
                mock_pipeline.start_session = AsyncMock()
                mock_pipeline.process_question = AsyncMock(return_value=mock_pipeline_result)
                MockPipeline.return_value = mock_pipeline
                
                client = TestClient(app)
                response = client.post("/api/suggest", json={
                    "questionText": "Test question",
                    "style": "mixed",
                    "candidate": _minimal_candidate_payload(),
                    "company": _minimal_company_payload(),
                })
                
                data = response.json()
                assert "quality" in data
                assert data["quality"]["passed"] is True
                assert data["quality"]["score"] >= 0.9
    
    @pytest.mark.asyncio
    async def test_suggest_includes_latency(self, mock_pipeline_result):
        """Suggest response should include latency metrics."""
        from api.server import app
        
        with patch('api.server.check_api_keys_available', return_value=False):
            with patch('api.server.RealtimePipeline') as MockPipeline:
                mock_pipeline = MagicMock()
                mock_pipeline.start_session = AsyncMock()
                mock_pipeline.process_question = AsyncMock(return_value=mock_pipeline_result)
                MockPipeline.return_value = mock_pipeline
                
                client = TestClient(app)
                response = client.post("/api/suggest", json={
                    "questionText": "Test question",
                    "candidate": _minimal_candidate_payload(),
                    "company": _minimal_company_payload(),
                })
                
                data = response.json()
                assert "latency_ms" in data
                assert isinstance(data["latency_ms"], int)

    @pytest.mark.asyncio
    async def test_suggest_includes_shadow_normalizer_debug_fields(self, mock_pipeline_result):
        from api.server import app
        with patch('api.server.check_api_keys_available', return_value=False):
            client = TestClient(app)
            response = client.post("/api/suggest", json={
                "questionText": "What are you looking for in a company and team? What do you not like?",
                "style": "mixed",
                "candidate": _minimal_candidate_payload(),
                "company": _minimal_company_payload(),
                "conversation_history": [
                    {"speaker": "interviewer", "text": "What are you looking for in a company and team?"},
                    {"speaker": "interviewer", "text": "What do you not like?"},
                ],
            })

            data = response.json()
            assert data["success"] is True
            assert data["debug"]["normalized_family"]
            assert data["debug"]["normalized_primary_ask"]
            assert data["debug"]["normalized_answer_contract"]
            assert data["debug"]["normalizer_confidence"] >= 0
            assert "fallback_used" in data["debug"]

    def test_suggest_passes_rich_context_to_pipeline_start_session(self, mock_pipeline_result):
        """Suggest should pass rich candidate/company context into the assembled context."""
        from api.server import app
        from contracts.models import GeneratedResponse, ResponseStyle

        captured: dict = {}

        with patch('api.server.check_api_keys_available', return_value=False):
            async def fake_compose(self, context, on_bullets=None):
                captured["interview_config"] = context.interview_config
                return GeneratedResponse(
                    bullets=["Bullet 1"],
                    full_response="Full response text here",
                    key_metrics=["50%", "2x"],
                    confidence=0.85,
                    style_used=ResponseStyle.TECHNICAL,
                    generation_time_ms=1,
                    mode="real",
                    metadata={},
                )

            with patch("pipeline.steps.response_composer.ResponseComposer.compose", new=fake_compose):

                client = TestClient(app)
                response = client.post("/api/suggest", json={
                    "questionText": "Why are you a good fit for this role?",
                    "style": "mixed",
                    "candidate": {
                        **_minimal_candidate_payload(),
                        "summary": "Senior backend engineer",
                        "skills": ["Python", "PostgreSQL", "System design"],
                        "achievements": ["Reduced latency by 35%"],
                    },
                    "company": {
                        **_minimal_company_payload(),
                        "companyName": "ScaleWorks",
                        "positionTitle": "Staff Engineer",
                        "industry": "SaaS",
                        "companyDescription": "Workflow platform",
                        "positionRequirements": ["Design scalable services", "Mentor engineers"],
                        "companyCulture": "Ownership and collaboration"
                    }
                })

                assert response.status_code == 200
                interview_config = captured["interview_config"]

                assert interview_config["candidate_skills"] == ["Python", "PostgreSQL", "System design"]
                assert interview_config["candidate_achievements"] == ["Reduced latency by 35%"]
                assert interview_config["candidate_certifications"] == ["AWS SAA"]
                assert interview_config["company_requirements"] == ["Design scalable services", "Mentor engineers"]
                assert interview_config["company_culture"] == "Ownership and collaboration"
                assert interview_config["role_title"] == "Staff Engineer"

    def test_suggest_keeps_candidate_and_target_context_separate(self, mock_pipeline_result):
        """Suggest should preserve candidate company separately from target company/role context."""
        from api.server import app
        from contracts.models import GeneratedResponse, ResponseStyle

        captured: dict = {}

        with patch("api.server.check_api_keys_available", return_value=False):
            async def fake_compose(self, context, on_bullets=None):
                captured["interview_config"] = context.interview_config
                return GeneratedResponse(
                    bullets=["Point 1"],
                    full_response="Response",
                    key_metrics=[],
                    confidence=0.8,
                    style_used=ResponseStyle.MIXED,
                    generation_time_ms=1,
                    mode="real",
                    metadata={},
                )

            with patch("pipeline.steps.response_composer.ResponseComposer.compose", new=fake_compose):

                client = TestClient(app)
                response = client.post("/api/suggest", json={
                    "questionText": "Why are you a good fit for this role?",
                    "candidate_profile": {
                        "name": "Daniel",
                        "current_role": "Technology Director - Data & AI",
                        "company": "Globant",
                        "summary": "Technology executive with global data and AI leadership scope.",
                        "skills": ["Data strategy", "Leadership"],
                        "achievements": ["Led core banking modernization across 6+ enterprise clients"],
                    },
                    "target_context": {
                        "company": {
                            "name": "Slalom",
                            "industry": "Consulting",
                        },
                        "role": {
                            "title": "Director - Data Architecture & Engineering",
                            "level": "director",
                            "description": "Lead client-facing data engineering and architecture delivery.",
                            "requirements": ["Consulting experience", "Cloud data platforms"],
                            "responsibilities": ["Lead client delivery"],
                        },
                        "interviewer": {
                            "name": "Bernardo Najlis",
                            "company": "Slalom",
                        },
                    },
                })

                assert response.status_code == 200
                interview_config = captured["interview_config"]

                assert interview_config["candidate"]["company"] == "Globant"
                assert interview_config["company"]["companyName"] == "Slalom"
                assert interview_config["role_title"] == "Director - Data Architecture & Engineering"
                assert interview_config["target_context"]["company"]["name"] == "Slalom"
                assert interview_config["target_context"]["role"]["title"] == "Director - Data Architecture & Engineering"
                assert interview_config["target_context"]["interviewer"]["company"] == "Slalom"

    def test_suggest_accepts_explicit_target_company_and_role_aliases(self, mock_pipeline_result):
        """Suggest should accept explicit target company/role aliases and preserve them separately from candidate data."""
        from api.server import app
        from contracts.models import GeneratedResponse, ResponseStyle

        captured: dict = {}

        with patch("api.server.check_api_keys_available", return_value=False):
            async def fake_compose(self, context, on_bullets=None):
                captured["interview_config"] = context.interview_config
                return GeneratedResponse(
                    bullets=["Point 1"],
                    full_response="Response",
                    key_metrics=[],
                    confidence=0.8,
                    style_used=ResponseStyle.MIXED,
                    generation_time_ms=1,
                    mode="real",
                    metadata={},
                )

            with patch("pipeline.steps.response_composer.ResponseComposer.compose", new=fake_compose):
                client = TestClient(app)
                response = client.post("/api/suggest", json={
                    "questionText": "Why are you a good fit for this role?",
                    "candidate_profile": {
                        "name": "Daniel",
                        "current_role": "Technology Director - Data & AI",
                        "company": "Globant",
                        "summary": "Technology executive with global data and AI leadership scope.",
                        "skills": ["Data strategy", "Leadership"],
                        "achievements": ["Led core banking modernization across 6+ enterprise clients"],
                    },
                    "target_company_info": {
                        "name": "Slalom",
                        "industry": "Consulting",
                        "culture": "People-first consulting culture",
                    },
                    "target_role_info": {
                        "title": "Director - Data Architecture & Engineering",
                        "level": "director",
                        "description": "Lead client-facing data engineering and architecture delivery.",
                        "requirements": ["Consulting experience", "Cloud data platforms"],
                        "responsibilities": ["Lead client delivery"],
                    },
                    "interviewer_profile": {
                        "name": "Bernardo Najlis",
                        "company": "Slalom",
                    },
                })

                assert response.status_code == 200
                interview_config = captured["interview_config"]

                assert interview_config["candidate"]["company"] == "Globant"
                assert interview_config["company"]["companyName"] == "Slalom"
                assert interview_config["target_context"]["company"]["name"] == "Slalom"
                assert interview_config["target_context"]["role"]["title"] == "Director - Data Architecture & Engineering"
                assert interview_config["target_context"]["interviewer"]["company"] == "Slalom"

    def test_suggest_rejects_generic_candidate_profile_without_real_prepare_data(self, mock_pipeline_result):
        """Suggest should fail fast instead of accepting the old generic placeholder profile."""
        from api.server import app

        with patch("api.server.check_api_keys_available", return_value=False):
            with patch("pipeline.realtime_pipeline.RealtimePipeline") as MockPipeline:
                mock_pipeline = MagicMock()
                mock_pipeline.start_session = AsyncMock()
                mock_pipeline.process_question = AsyncMock(return_value=mock_pipeline_result)
                MockPipeline.return_value = mock_pipeline

                client = TestClient(app)
                response = client.post("/api/suggest", json={
                    "questionText": "Tell me about yourself",
                    "candidate_profile": {
                        "name": "Daniel",
                        "current_role": "Technology Director - Data & AI",
                        "company": "Globant",
                        "summary": "Experienced professional with 0+ years in the industry.",
                        "skills": ["Leadership", "Strategy", "Team Building"],
                        "achievements": ["Led teams", "Delivered projects", "Drove growth"],
                    },
                    "company_info": {
                        "name": "Slalom",
                        "role_title": "Director - Data Architecture & Engineering",
                    },
                })

                assert response.status_code == 200
                data = response.json()
                assert data["success"] is False
                assert data["mode"] == "error"
                assert "generic placeholder" in data["error"]
                assert mock_pipeline.start_session.await_count == 0

    def test_suggest_does_not_repair_generic_candidate_from_cv_text(self, mock_pipeline_result):
        """Suggest should reject generic candidate payloads even if raw CV text is present."""
        from api.server import app

        client = TestClient(app)
        response = client.post("/api/suggest", json={
            "questionText": "Tell me about yourself",
            "candidate_profile": {
                "name": "Daniel",
                "current_role": "Technology Director - Data & AI",
                "company": "Globant",
                "summary": "Experienced professional with 0+ years in the industry.",
                "skills": ["Leadership", "Strategy", "Team Building"],
                "achievements": ["Led teams", "Delivered projects", "Drove growth"],
                "cv_text": (
                    "DANIEL ALARCON\n"
                    "Globant — Technology Director, Data & AI\n"
                    "Technology executive with 20 years leading enterprise transformation.\n"
                ),
            },
            "target_context": {
                "company": {"name": "Slalom"},
                "role": {"title": "Director - Data Architecture & Engineering"},
            },
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["mode"] == "error"
        assert "generic placeholder" in data["error"]


class TestCVAnalyzeModes:
    """Tests for /api/analyze-cv mode labeling and failure behavior."""

    def test_analyze_cv_returns_real_mode_and_structured_profile(self):
        """analyze-cv should return mode='real' with structured extraction when LLM works."""
        from api.server import app

        class FakeAdapter:
            async def generate(self, messages, config):
                return (
                    '{'
                    '"name":"John Doe",'
                    '"email":null,'
                    '"current_role":"Senior Engineer",'
                    '"company":"Google",'
                    '"summary":"Senior engineer with Python and distributed systems experience.",'
                    '"years_experience":10,'
                    '"skills":["Python","Distributed Systems","Leadership"],'
                    '"achievements":["Improved latency by 40%"],'
                    '"leadership_roles":["Team Lead"],'
                    '"technical_stack":["Python","PostgreSQL"],'
                    '"metrics":["40% latency improvement"]'
                    '}'
                )

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            with patch("adapters.llm_adapter.get_llm_adapter", return_value=FakeAdapter()):
                with patch("api.server.check_db_connection", new_callable=AsyncMock) as mock_db:
                    mock_db.return_value = False

                    client = TestClient(app)
                    response = client.post("/api/analyze-cv", json={
                        "cv_text": (
                            "John Doe. Senior Engineer with 10 years Python experience. "
                            "Led team at Google. Built distributed systems and improved latency by 40%."
                        )
                    })

                    assert response.status_code == 200
                    data = response.json()
                    assert data["success"] is True
                    assert data["mode"] == "real"
                    assert data["profile"]["name"] == "John Doe"
                    assert data["profile"]["summary"]
                    assert "Python" in data["profile"]["skills"]
                    assert data["profile"]["yearsExperience"] == 10

    def test_analyze_cv_returns_real_mode_without_api_key(self):
        """analyze-cv should still return real structured extraction when no API key is configured."""
        from api.server import app

        with patch.dict(os.environ, {}, clear=True):
            with patch("api.server.check_db_connection", new_callable=AsyncMock) as mock_db:
                mock_db.return_value = False

                client = TestClient(app)
                response = client.post("/api/analyze-cv", json={
                    "cv_text": STRUCTURED_CV_TEXT
                })

                assert response.status_code == 200
                data = response.json()
                assert data["success"] is True
                assert data["mode"] == "real"
                assert isinstance(data["profile"]["skills"], list)

    def test_analyze_cv_returns_real_mode_when_llm_fails(self):
        """analyze-cv should keep structured extraction in real mode and surface the LLM failure."""
        from api.server import app

        class BrokenAdapter:
            async def generate(self, messages, config):
                raise RuntimeError("simulated llm failure")

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            with patch("adapters.llm_adapter.get_llm_adapter", return_value=BrokenAdapter()):
                with patch("api.server.check_db_connection", new_callable=AsyncMock) as mock_db:
                    mock_db.return_value = False

                    client = TestClient(app)
                    response = client.post("/api/analyze-cv", json={
                        "cv_text": STRUCTURED_CV_TEXT
                    })

                    assert response.status_code == 200
                    data = response.json()
                    assert data["success"] is True
                    assert data["mode"] == "real"
                    assert data["profile"]["name"]
                    assert isinstance(data["profile"]["skills"], list)
                    assert data["error"] == "simulated llm failure"

    def test_analyze_cv_returns_unavailable_when_signal_is_insufficient(self):
        """analyze-cv should fail clearly instead of inventing a placeholder profile."""
        from api.server import app

        with patch.dict(os.environ, {}, clear=True):
            with patch("api.server.check_db_connection", new_callable=AsyncMock) as mock_db:
                mock_db.return_value = False

                client = TestClient(app)
                response = client.post("/api/analyze-cv", json={
                    "cv_text": INSUFFICIENT_SIGNAL_CV_TEXT
                })

                assert response.status_code == 200
                data = response.json()
                assert data["success"] is False
                assert data["mode"] == "unavailable"
                assert "Complete Prepare manually" in data["error"]

    def test_analyze_cv_requires_cv_text(self):
        """analyze-cv should return error if no cv text is provided."""
        from api.server import app

        client = TestClient(app)
        response = client.post("/api/analyze-cv", json={})

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["error"] == "CV text required"
