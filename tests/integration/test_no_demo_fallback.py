#!/usr/bin/env python3
"""
Integration Test: Verify Demo Fallback is Disabled

This test suite verifies that:
1. Demo mode is completely disabled in ResponseComposer
2. Demo mode is completely disabled in EvidenceRetriever
3. Real LLM is always used (errors if not available)
4. Real evidence is always retrieved (empty if DB unavailable)
5. No fake CV data is ever generated
6. Company isolation works correctly (Accenture ≠ Xertica)

Run with: python -m pytest tests/integration/test_no_demo_fallback.py -v
"""
import pytest
import asyncio
import os
import sys
from pathlib import Path

# Add python-core to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "python-core"))

from pipeline.steps.response_composer import ResponseComposer, ComposerMode
from pipeline.steps.evidence_retriever import EvidenceRetriever, RetrieverMode, RetrievalPlan
from pipeline.steps.retrieval_planner import RetrievalPlanner
from contracts.models import AssembledContext, EvidenceChunk, QuestionAnalysis, ResponseStyle


class TestResponseComposerNoDemoFallback:
    """Test that ResponseComposer never falls back to demo mode."""
    
    def test_demo_mode_returns_error_not_fake_data(self):
        """Demo mode should return error message, not fake CV data."""
        # Force demo mode (which should now be disabled)
        composer = ResponseComposer(mode=ComposerMode.DEMO, use_llm=False)
        
        # Create context with fake evidence (to see if it's used)
        fake_evidence = [
            EvidenceChunk(
                text="40% OPEX reduction achievement",
                source="achievement",
                relevance_score=0.9,
                metadata={"test": "data"}
            )
        ]
        
        context = AssembledContext(
            question="Tell me about your achievements",
            evidence=fake_evidence,
            analysis=QuestionAnalysis(
                question_type="behavioral",
                recommended_style=ResponseStyle.EXECUTIVE,
                topics=["leadership"],
                urgency="normal"
            ),
            interview_config={}
        )
        
        response = asyncio.run(composer.compose(context))
        
        # Should return error mode, not demo mode
        assert response.mode == "error" or response.mode == "real", \
            f"Expected mode='error' or 'real', got '{response.mode}'"
        
        # Should NOT contain fake metrics
        assert "40%" not in response.full_response, \
            "Response should not contain fake metrics from evidence"
        assert "demo_mode" not in str(response.metadata), \
            "Response metadata should not indicate demo mode"
    
    def test_from_environment_defaults_to_real(self):
        """from_environment() should default to REAL mode."""
        # Clear any env var
        old_mode = os.environ.pop("RESPONSE_COMPOSER_MODE", None)
        try:
            composer = ResponseComposer.from_environment()
            status = composer.get_status()
            assert status.mode == ComposerMode.REAL, \
                f"Expected REAL mode by default, got {status.mode}"
        finally:
            if old_mode:
                os.environ["RESPONSE_COMPOSER_MODE"] = old_mode
    
    def test_demo_env_var_treated_as_real(self):
        """Setting DEMO mode via env var should be treated as REAL."""
        old_mode = os.environ.get("RESPONSE_COMPOSER_MODE")
        os.environ["RESPONSE_COMPOSER_MODE"] = "demo"
        try:
            composer = ResponseComposer.from_environment()
            status = composer.get_status()
            # Should be REAL mode even though DEMO was requested
            assert status.mode == ComposerMode.REAL, \
                f"Demo mode should be treated as REAL, got {status.mode}"
        finally:
            if old_mode:
                os.environ["RESPONSE_COMPOSER_MODE"] = old_mode
            else:
                os.environ.pop("RESPONSE_COMPOSER_MODE", None)
    
    def test_no_fake_metrics_in_response(self):
        """Response should never contain common fake metrics."""
        composer = ResponseComposer(mode=ComposerMode.REAL, use_llm=False)
        
        context = AssembledContext(
            question="What is your experience?",
            evidence=[],  # No evidence
            analysis=QuestionAnalysis(
                question_type="behavioral",
                recommended_style=ResponseStyle.EXECUTIVE,
                topics=["experience"],
                urgency="normal"
            ),
            interview_config={}
        )
        
        response = asyncio.run(composer.compose(context))
        
        # Common fake metrics that should never appear
        fake_metrics = [
            "40%", "OPEX", "345", "indirect reports",
            "17+", "accounts", "50 engineers", "18 months"
        ]
        
        for metric in fake_metrics:
            assert metric not in response.full_response, \
                f"Response should not contain fake metric: {metric}"


class TestEvidenceRetrieverNoDemoFallback:
    """Test that EvidenceRetriever never returns fake evidence."""
    
    def test_demo_mode_returns_empty_not_fake_evidence(self):
        """Demo mode should return empty evidence, not fake data."""
        retriever = EvidenceRetriever(mode=RetrieverMode.DEMO, force_demo=True)
        
        plan = RetrievalPlan(
            achievement_queries=["leadership", "team scaling"],
            cv_queries=["experience"],
            top_k=3
        )
        
        evidence = asyncio.run(retriever.retrieve(plan))
        
        # Should return empty list, not fake evidence
        assert len(evidence) == 0, \
            f"Demo mode should return empty evidence, got {len(evidence)} chunks"
    
    def test_from_environment_defaults_to_real(self):
        """from_environment() should default to REAL mode."""
        old_mode = os.environ.pop("EVIDENCE_RETRIEVER_MODE", None)
        try:
            retriever = EvidenceRetriever.from_environment()
            status = retriever.get_status()
            assert status.mode == RetrieverMode.REAL, \
                f"Expected REAL mode by default, got {status.mode}"
        finally:
            if old_mode:
                os.environ["EVIDENCE_RETRIEVER_MODE"] = old_mode
    
    def test_force_demo_is_ignored(self):
        """force_demo=True should be ignored (demo mode disabled)."""
        retriever = EvidenceRetriever(mode=RetrieverMode.REAL, force_demo=True)
        
        # force_demo should be ignored
        assert retriever.force_demo == False, \
            "force_demo should be ignored and set to False"
        
        plan = RetrievalPlan(
            achievement_queries=["test"],
            cv_queries=["test"],
            top_k=1
        )
        
        evidence = asyncio.run(retriever.retrieve(plan))
        # Should attempt real retrieval (which will fail but not return fake data)
        assert all(chunk.metadata.get("mode") != "demo" for chunk in evidence), \
            "No evidence should be marked as demo mode"


class TestCompanyIsolation:
    """Test that company-specific questions return correct company data."""
    
    def test_question_analyzer_extracts_company_names(self):
        """Question analyzer should extract company names from questions."""
        from pipeline.steps.question_analyzer import QuestionAnalyzer
        
        analyzer = QuestionAnalyzer()
        
        # Test Accenture question
        result_accenture = asyncio.run(analyzer.analyze(
            "What did you do at Accenture?"
        ))
        
        # Test Xertica question
        result_xertica = asyncio.run(analyzer.analyze(
            "Tell me about your role at Xertica"
        ))
        
        # Company should be detected
        assert "accenture" in str(result_accenture.metadata).lower() or \
               result_accenture.company_filter is not None, \
            "Accenture should be detected in question"
        
        assert "xertica" in str(result_xertica.metadata).lower() or \
               result_xertica.company_filter is not None, \
            "Xertica should be detected in question"


class TestRealLLMRequired:
    """Test that real LLM is required and demo fallback is disabled."""
    
    def test_llm_adapter_without_api_key_returns_error(self):
        """Without API key, system should return error not demo."""
        # Temporarily clear API keys
        old_anthropic = os.environ.pop("ANTHROPIC_API_KEY", None)
        old_openai = os.environ.pop("OPENAI_API_KEY", None)
        
        try:
            from adapters.llm_adapter import get_llm_adapter
            
            adapter = get_llm_adapter()
            
            # Should return None (error) not demo adapter
            assert adapter is None, \
                "Without API keys, should return None, not demo adapter"
        finally:
            if old_anthropic:
                os.environ["ANTHROPIC_API_KEY"] = old_anthropic
            if old_openai:
                os.environ["OPENAI_API_KEY"] = old_openai


class TestEndToEndNoFakeData:
    """End-to-end test that no fake data flows through the pipeline."""
    
    def test_pipeline_with_no_cv_returns_safe_message(self):
        """Pipeline with no CV should return safe message, not fake data."""
        composer = ResponseComposer(mode=ComposerMode.REAL, use_llm=False)
        
        # Context with NO evidence
        context = AssembledContext(
            question="Tell me about your experience at Accenture",
            evidence=[],  # NO EVIDENCE - simulates no CV uploaded
            analysis=QuestionAnalysis(
                question_type="behavioral",
                recommended_style=ResponseStyle.EXECUTIVE,
                topics=["experience"],
                urgency="normal"
            ),
            interview_config={
                "candidate_name": "Test Candidate",
                "company_name": "Test Company"
            }
        )
        
        response = asyncio.run(composer.compose(context))
        
        # Should indicate no evidence/safe fallback
        assert response.confidence < 0.5, \
            f"Expected low confidence with no evidence, got {response.confidence}"
        
        # Should NOT invent fake metrics
        assert "40%" not in response.full_response
        assert "345" not in response.full_response
        assert "17+" not in response.full_response


def run_tests():
    """Run all tests."""
    pytest.main([__file__, "-v"])


if __name__ == "__main__":
    run_tests()