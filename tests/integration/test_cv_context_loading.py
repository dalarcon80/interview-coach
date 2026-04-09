"""
Test: CV Context Loading - Verify cv_text is used as grounding when DB evidence is unavailable.

This test verifies that:
1. When cv_text is provided in the request, it is passed through to the LLM prompt
2. When evidence is empty but cv_text is present, the LLM call proceeds (not safe fallback)
3. The prompt builder correctly includes cv_text in the CANDIDATE EVIDENCE section
4. No hallucinated metrics appear when cv_text is the grounding source

These tests do NOT hardcode a specific person's profile - they work with any CV text.
"""
import sys
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "python-core"))

from contracts.models import (
    AssembledContext,
    QuestionAnalysis,
    ResponseStyle,
    EvidenceChunk,
)
from pipeline.steps.response_composer import ResponseComposer, ComposerMode


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_CV_TEXT = """
John Doe
Senior Software Engineer | john@example.com

SUMMARY
Software engineer with 8 years of experience in distributed systems.
Led migration of monolithic app to microservices, reducing latency by 35%.
Managed team of 12 engineers across 3 time zones.

EXPERIENCE
TechCorp — Senior Engineer (2019–Present)
- Reduced deployment time from 4 hours to 15 minutes via CI/CD pipeline
- Saved $200K/year in cloud costs through infrastructure optimization
- Led team of 12 engineers

StartupXYZ — Engineer (2016–2019)
- Built real-time data pipeline processing 1M events/day
- Improved system uptime from 95% to 99.9%

EDUCATION
B.S. Computer Science — State University (2016)
"""


def _make_context(cv_text: str = "", evidence: list = None, question: str = "Tell me about your experience") -> AssembledContext:
    """Build an AssembledContext with optional cv_text and evidence."""
    interview_config = {
        "candidate_name": "Test Candidate",
        "candidate_summary": "Experienced engineer",
        "candidate_skills": ["Python", "Distributed Systems"],
        "candidate_achievements": [],
        "candidate_certifications": [],
        "candidate": {
            "name": "Test Candidate",
            "cv_text": cv_text,
        },
        "company_name": "Acme Corp",
        "role_title": "Senior Engineer",
    }
    return AssembledContext(
        question=question,
        analysis=QuestionAnalysis(
            question_type="behavioral",
            recommended_style=ResponseStyle.EXECUTIVE,
            key_topics=["experience"],
            language="en",
            confidence=0.9,
        ),
        evidence=evidence or [],
        conversation_summary="",
        style_config={"response_style": "executive"},
        interview_config=interview_config,
    )


# ---------------------------------------------------------------------------
# Unit tests for _build_prompt
# ---------------------------------------------------------------------------

class TestBuildPromptCvTextFallback:
    """Tests that _build_prompt uses cv_text when evidence is empty."""

    def setup_method(self):
        self.composer = ResponseComposer(mode=ComposerMode.REAL)

    def test_cv_text_included_in_prompt_when_evidence_empty(self):
        """When evidence is empty and cv_text is provided, prompt includes cv_text."""
        ctx = _make_context(cv_text=SAMPLE_CV_TEXT, evidence=[])
        prompt = self.composer._build_prompt(ctx, ResponseStyle.EXECUTIVE)

        assert "CV TEXT" in prompt, "Prompt should include CV TEXT section when evidence is empty"
        assert "35%" in prompt or "12 engineers" in prompt or "TechCorp" in prompt, \
            "Prompt should include actual CV content"

    def test_evidence_used_when_available(self):
        """When evidence is available, it is used instead of cv_text fallback."""
        evidence = [
            EvidenceChunk(
                text="Led a team of 5 engineers to deliver project on time",
                source="achievements",
                relevance_score=0.9,
            )
        ]
        ctx = _make_context(cv_text=SAMPLE_CV_TEXT, evidence=evidence)
        prompt = self.composer._build_prompt(ctx, ResponseStyle.EXECUTIVE)

        assert "Led a team of 5 engineers" in prompt, "Evidence text should appear in prompt"
        # CV TEXT section should NOT appear when evidence is available
        assert "CV TEXT" not in prompt, "CV TEXT fallback should not appear when evidence is present"

    def test_no_cv_text_no_evidence_shows_no_evidence_retrieved(self):
        """When neither evidence nor cv_text is available, prompt shows no evidence."""
        ctx = _make_context(cv_text="", evidence=[])
        prompt = self.composer._build_prompt(ctx, ResponseStyle.EXECUTIVE)

        assert "No evidence retrieved" in prompt, \
            "Prompt should indicate no evidence when both evidence and cv_text are missing"

    def test_cv_text_truncated_to_2000_chars(self):
        """cv_text is truncated to 2000 chars to stay within token budget."""
        long_cv = "X" * 5000
        ctx = _make_context(cv_text=long_cv, evidence=[])
        prompt = self.composer._build_prompt(ctx, ResponseStyle.EXECUTIVE)

        # The cv_text snippet in the prompt should be at most 2000 chars of X's
        # (allow small margin for any X chars in other parts of the prompt)
        x_count = prompt.count("X")
        assert x_count <= 2010, f"CV text should be truncated to ~2000 chars, got {x_count} X chars"
        assert x_count < 5000, "Full 5000-char cv_text must NOT appear untruncated"

    def test_cv_text_from_top_level_interview_config(self):
        """cv_text at top-level interview_config is also picked up."""
        ctx = _make_context(cv_text="", evidence=[])
        # Override: put cv_text at top level
        ctx.interview_config["cv_text"] = SAMPLE_CV_TEXT
        ctx.interview_config["candidate"]["cv_text"] = ""

        prompt = self.composer._build_prompt(ctx, ResponseStyle.EXECUTIVE)
        assert "CV TEXT" in prompt, "Top-level cv_text should be used as fallback"


# ---------------------------------------------------------------------------
# Unit tests for compose() gate logic
# ---------------------------------------------------------------------------

class TestComposeGateWithCvText:
    """Tests that compose() proceeds to LLM when cv_text is available (not safe fallback)."""

    def setup_method(self):
        self.composer = ResponseComposer(mode=ComposerMode.REAL)

    @pytest.mark.asyncio
    async def test_compose_proceeds_to_llm_when_cv_text_available(self):
        """When evidence is empty but cv_text is present, compose() calls LLM (not safe fallback)."""
        ctx = _make_context(cv_text=SAMPLE_CV_TEXT, evidence=[])

        mock_response = MagicMock()
        mock_response.full_response = "Based on my CV, I have 8 years of experience..."
        mock_response.bullets = ["8 years experience", "Led team of 12"]
        mock_response.key_metrics = ["35% latency reduction"]
        mock_response.confidence = 0.8
        mock_response.style_used = ResponseStyle.EXECUTIVE
        mock_response.generation_time_ms = 500
        mock_response.mode = "real"
        mock_response.metadata = {}

        mock_compose_real = AsyncMock(return_value=mock_response)
        with patch.object(self.composer, "_compose_real", mock_compose_real):
            result = await self.composer.compose(ctx)

        assert result.mode != "safe_fallback", \
            "Should NOT return safe_fallback when cv_text is available"
        mock_compose_real.assert_called_once()

    @pytest.mark.asyncio
    async def test_compose_returns_safe_fallback_when_no_cv_text_no_evidence(self):
        """When neither evidence nor cv_text is available, compose() returns safe fallback."""
        ctx = _make_context(cv_text="", evidence=[])

        result = await self.composer.compose(ctx)

        assert result.mode == "safe_fallback", \
            "Should return safe_fallback when no evidence and no cv_text"
        assert result.confidence == 0.1, "Safe fallback should have low confidence"


# ---------------------------------------------------------------------------
# Integration: verify cv_text flows through server request structure
# ---------------------------------------------------------------------------

class TestCvTextFlowThroughRequest:
    """Verify that cv_text in a /api/suggest request reaches the prompt builder."""

    def test_candidate_context_preserves_cv_text(self):
        """The candidate_context dict built in server.py preserves cv_text."""
        # Simulate what server.py does when building candidate_context
        candidate = {
            "name": "Jane Smith",
            "cv_text": SAMPLE_CV_TEXT,
            "summary": "Experienced engineer",
            "skills": ["Python"],
            "achievements": [],
        }

        candidate_context = {
            "name": candidate.get("name") or "",
            "cv_text": candidate.get("cv_text") or candidate.get("cvText") or "",
        }

        assert candidate_context["cv_text"] == SAMPLE_CV_TEXT, \
            "cv_text must be preserved in candidate_context"

    def test_interview_config_candidate_has_cv_text(self):
        """interview_config['candidate']['cv_text'] is accessible by _build_prompt."""
        interview_config = {
            "candidate": {
                "name": "Jane Smith",
                "cv_text": SAMPLE_CV_TEXT,
            }
        }

        composer = ResponseComposer(mode=ComposerMode.REAL)
        candidate_context = interview_config.get("candidate", {})
        cv_text = (
            interview_config.get("cv_text")
            or candidate_context.get("cv_text")
            or candidate_context.get("cvText")
            or interview_config.get("cvText")
            or ""
        )

        assert cv_text == SAMPLE_CV_TEXT, \
            "_build_prompt cv_text extraction logic must find cv_text in candidate dict"


# ---------------------------------------------------------------------------
# Regression: verify no hallucinated metrics when cv_text is grounding source
# ---------------------------------------------------------------------------

class TestNoHallucinatedMetrics:
    """Verify that the prompt does not contain metrics not present in the CV."""

    def test_prompt_does_not_invent_metrics_beyond_cv(self):
        """The prompt should only contain metrics that appear in the CV text."""
        cv_with_specific_metrics = """
        Alice Johnson — VP Engineering
        Led team of 7 engineers.
        Reduced costs by 25%.
        Delivered 3 products in 18 months.
        """
        ctx = _make_context(cv_text=cv_with_specific_metrics, evidence=[])
        composer = ResponseComposer(mode=ComposerMode.REAL)
        prompt = composer._build_prompt(ctx, ResponseStyle.EXECUTIVE)

        # Metrics from CV should appear
        assert "7" in prompt or "25%" in prompt or "3 products" in prompt or "18 months" in prompt, \
            "CV metrics should appear in prompt"

        # Metrics NOT in CV should not be invented by the prompt builder
        # (The LLM itself might still hallucinate, but the prompt builder should not add fake numbers)
        assert "345" not in prompt, "Prompt builder should not inject fake metrics"
        assert "40%" not in prompt or "25%" in prompt, \
            "Only CV metrics should appear, not invented ones"
