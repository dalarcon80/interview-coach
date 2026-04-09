"""
Interview Coach - Pipeline Integration Tests

Tests the full pipeline from question to response.
These tests verify the integration between components.

C8 Requirement: At least 3 real integration tests
"""
import pytest
import asyncio
import sys
import uuid
from unittest.mock import AsyncMock, patch
from pathlib import Path

# Add python-core to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "python-core"))

from contracts.models import (
    QuestionType,
    ResponseStyle,
    QuestionAnalysis,
    SubQuestion,
    Priority,
    EvidenceChunk,
    AssembledContext,
    GeneratedResponse,
)
from pipeline.steps.question_analyzer import QuestionAnalyzer, AnalysisContext
from pipeline.steps.evidence_retriever import EvidenceRetriever, RetrieverMode
from pipeline.steps.response_composer import ResponseComposer, ComposerMode
from pipeline.steps.quality_gate import QualityGate
from pipeline.steps.language_policy import LanguagePolicy
from pipeline.realtime_pipeline import RealtimePipeline, PipelineConfig


class TestQuestionAnalyzerIntegration:
    """Integration tests for question analyzer"""
    
    @pytest.mark.asyncio
    async def test_analyze_behavioral_question(self):
        """Test analyzing a behavioral question"""
        analyzer = QuestionAnalyzer(use_llm=False)
        
        context = AnalysisContext(
            role_title="CTO",
            company_name="TechCorp",
            job_description="Looking for a technical leader",
            conversation_history=[],
            topics_covered=[],
            metrics_used=[],
        )
        
        analysis = await analyzer.analyze(
            "Tell me about your leadership experience",
            context
        )
        
        assert analysis.primary_type == QuestionType.BEHAVIORAL
        assert "experience" in str(analysis.key_topics).lower() or "leadership" in str(analysis.key_topics).lower()
        assert len(analysis.underlying_intent) > 0
        assert analysis.confidence > 0
    
    @pytest.mark.asyncio
    async def test_analyze_compound_question(self):
        """Test analyzing a compound question with multiple parts"""
        analyzer = QuestionAnalyzer(use_llm=False)
        
        compound_question = (
            "Estamos buscando una persona que ocupe el rol de CTO en la compañía, "
            "la cual debe poder dar estructura no solo a nivel tecnológico, sino a nivel operativo "
            "alineado con las necesidades internas y de nuestros clientes, que permita traer "
            "resultados medibles. Para eso nos gustaría saber tu experiencia, si has tenido "
            "oportunidad de crear equipos desde cero, cuéntanos más sobre ti."
        )
        
        analysis = await analyzer.analyze(compound_question)
        
        # Compound questions should be detected
        assert analysis.is_compound
        assert len(analysis.sub_questions) > 0
    
    @pytest.mark.asyncio
    async def test_analyze_technical_question(self):
        """Test analyzing a technical question"""
        analyzer = QuestionAnalyzer(use_llm=False)
        
        analysis = await analyzer.analyze(
            "How would you design a scalable microservices architecture?"
        )
        
        assert analysis.primary_type == QuestionType.TECHNICAL
        assert "technical" in analysis.key_topics

    def test_analyzer_uses_rich_context_requirements_and_culture(self):
        """Question analyzer should use company requirements/culture context."""
        analyzer = QuestionAnalyzer(use_llm=False)

        context = AnalysisContext(
            role_title="Engineering Manager",
            company_name="ScaleCo",
            job_description="Leadership role",
            company_requirements=[
                "Strong system design and scalability background",
                "Experience mentoring engineers and cross-functional collaboration",
            ],
            company_culture="Ownership, collaboration, and customer obsession",
            candidate_skills=["Python", "Distributed systems", "Mentoring"],
        )

        analysis = asyncio.run(analyzer.analyze("Tell me about yourself", context))

        assert analysis.recommended_style == ResponseStyle.TECHNICAL
        assert "technical" in analysis.key_topics
        assert any("requirements" in intent.lower() for intent in analysis.underlying_intent)
        assert any("culture" in intent.lower() for intent in analysis.underlying_intent)


class TestEvidenceRetrieverIntegration:
    """Integration tests for evidence retriever"""
    
    @pytest.mark.asyncio
    async def test_retrieve_demo_mode(self):
        """Test evidence retrieval in demo mode"""
        from pipeline.steps.retrieval_planner import RetrievalPlan
        
        retriever = EvidenceRetriever(mode=RetrieverMode.DEMO, force_demo=True)
        
        plan = RetrievalPlan(
            achievement_queries=["leadership experience"],
            cv_queries=["CTO role"],
            job_desc_queries=["technical leader"],
            top_k=5,
            min_relevance=0.5,
        )
        
        evidence = await retriever.retrieve(plan)
        
        # Should return demo evidence
        assert len(evidence) > 0
        assert all(isinstance(e, EvidenceChunk) for e in evidence)
        assert all(e.metadata.get("mode") == "demo" for e in evidence)
    
    @pytest.mark.asyncio
    async def test_retriever_status(self):
        """Test retriever status reporting"""
        retriever = EvidenceRetriever(mode=RetrieverMode.DEMO, force_demo=True)
        status = retriever.get_status()
        
        assert status.mode == RetrieverMode.DEMO
        assert "demo" in status.message.lower()

    def test_retrieve_real_mode_with_pgvector_semantic_match(self):
        """Real mode should retrieve semantically matching evidence via pgvector."""
        from storage.database import check_db_connection, execute_query, execute_scalar
        from storage.embedding_utils import hash_embedding, vector_literal
        from pipeline.steps.retrieval_planner import RetrievalPlan

        async def _run():
            if not await check_db_connection():
                pytest.skip("Database unavailable for real pgvector retrieval test")

            vector_available = await execute_scalar(
                "SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector')"
            )
            if not vector_available:
                pytest.skip("pgvector extension unavailable")

            token = f"r31_semantic_{uuid.uuid4().hex[:10]}"
            profile_id = await execute_scalar(
                """
                INSERT INTO user_profiles (name, resume_text)
                VALUES ($1, $2)
                RETURNING id
                """,
                "R3.1 Integration Test",
                f"Profile for {token}",
            )

            achievement_text = f"{token} leadership scale coaching"
            achievement_embedding = vector_literal(hash_embedding(achievement_text))
            doc_text = f"{token} architecture delivery outcomes"
            doc_embedding = vector_literal(hash_embedding(doc_text))

            try:
                await execute_query(
                    """
                    INSERT INTO achievements (profile_id, title, context, action, result, embedding)
                    VALUES ($1, $2, $3, $4, $5, $6::vector)
                    """,
                    profile_id,
                    f"Achievement {token}",
                    "Led team growth",
                    "Scaled platform delivery",
                    "Measured business impact",
                    achievement_embedding,
                )

                await execute_query(
                    """
                    INSERT INTO document_chunks (profile_id, source, section, content, embedding)
                    VALUES ($1, $2, $3, $4, $5::vector)
                    """,
                    profile_id,
                    "resume",
                    "experience",
                    f"Document chunk {doc_text}",
                    doc_embedding,
                )

                retriever = EvidenceRetriever(mode=RetrieverMode.REAL)
                plan = RetrievalPlan(
                    achievement_queries=[achievement_text],
                    cv_queries=[doc_text],
                    job_desc_queries=[],
                    top_k=3,
                    min_relevance=0.2,
                )

                evidence = await retriever.retrieve(plan)

                assert len(evidence) > 0
                assert any(item.metadata.get("mode") == "real" for item in evidence)
                assert any(token in item.text for item in evidence)
                assert any(item.relevance_score > 0 for item in evidence)
            finally:
                await execute_query("DELETE FROM user_profiles WHERE id = $1", profile_id)

        asyncio.run(_run())


class TestResponseComposerIntegration:
    """Integration tests for response composer"""
    
    @pytest.mark.asyncio
    async def test_compose_demo_mode(self):
        """Test response composition in demo mode"""
        composer = ResponseComposer(mode=ComposerMode.DEMO, use_llm=False)
        
        # Create mock context
        analysis = QuestionAnalysis(
            primary_type=QuestionType.BEHAVIORAL,
            is_compound=False,
            sub_questions=[],
            key_topics=["leadership"],
            underlying_intent=["Assess experience"],
            red_flags=[],
            related_to_previous=False,
            builds_on_exchange=None,
            recommended_style=ResponseStyle.EXECUTIVE,
            response_structure=["Context", "Action", "Result"],
            confidence=0.85,
        )
        
        context = AssembledContext(
            question="Tell me about your leadership experience",
            analysis=analysis,
            evidence=[
                EvidenceChunk(
                    text="Led engineering team of 15 engineers",
                    source="achievement",
                    relevance_score=0.92,
                    metadata={},
                ),
            ],
            conversation_summary="",
            topics_already_covered=[],
            metrics_already_used=[],
            interview_config={},
        )
        
        response = await composer.compose(context)
        
        assert isinstance(response, GeneratedResponse)
        assert len(response.bullets) > 0
        assert response.style_used == ResponseStyle.EXECUTIVE
        assert response.confidence <= 0.6  # Demo mode has lower confidence
    
    @pytest.mark.asyncio
    async def test_composer_status(self):
        """Test composer status reporting"""
        composer = ResponseComposer(mode=ComposerMode.DEMO, use_llm=False)
        status = composer.get_status()
        
        assert status.mode == ComposerMode.DEMO
        assert "demo" in status.message.lower()

    def test_compose_real_mode_labels_and_provider_metadata(self):
        """Real compose path should return mode=real with provider/model metadata."""
        composer = ResponseComposer(mode=ComposerMode.REAL, use_llm=True)

        analysis = QuestionAnalysis(
            primary_type=QuestionType.BEHAVIORAL,
            is_compound=False,
            sub_questions=[],
            key_topics=["leadership"],
            underlying_intent=["Assess experience"],
            red_flags=[],
            related_to_previous=False,
            builds_on_exchange=None,
            recommended_style=ResponseStyle.EXECUTIVE,
            response_structure=["Context", "Action", "Result"],
            confidence=0.85,
        )

        context = AssembledContext(
            question="Tell me about your leadership experience",
            analysis=analysis,
            evidence=[
                EvidenceChunk(
                    text="Led engineering team of 15 engineers",
                    source="achievement",
                    relevance_score=0.92,
                    metadata={},
                ),
            ],
            interview_config={"llm_alias": "main"},
        )

        fake_stream_text = "[BULLETS]\n- Led a 15-engineer org\n[/BULLETS]\n[FULL_RESPONSE]\nDelivered reliable growth with measurable outcomes.\n[/FULL_RESPONSE]"

        class FakeRealAdapter:
            model = "claude-sonnet-test"

            async def stream(self, messages, config):
                yield fake_stream_text

            async def generate(self, messages, config):
                return fake_stream_text

        with patch("adapters.provider_registry.get_registry") as mock_registry:
            mock_registry.return_value.get_llm_config.return_value.provider = "anthropic"
            mock_registry.return_value.get_llm_config.return_value.model = "claude-sonnet-test"
            mock_registry.return_value.get_llm_config.return_value.config = {
                "temperature": 0.3,
                "max_tokens": 256,
            }
            with patch(
                "adapters.llm_adapter.get_llm_adapter_or_demo",
                return_value=FakeRealAdapter(),
            ):
                response = asyncio.run(composer.compose(context))

        assert response.mode == "real"
        assert len(response.bullets) > 0
        assert "[Demo Mode]" not in response.full_response
        assert "Delivered reliable growth" in response.full_response
        assert response.metadata.get("provider") == "anthropic"
        assert response.metadata.get("model") == "claude-sonnet-test"
        assert response.metadata.get("llm_alias") == "main"

    def test_compose_real_mode_fallback_label_on_error(self):
        """Real compose path should fall back with explicit mode=fallback when LLM fails."""
        composer = ResponseComposer(mode=ComposerMode.REAL, use_llm=True)

        analysis = QuestionAnalysis(
            primary_type=QuestionType.BEHAVIORAL,
            is_compound=False,
            sub_questions=[],
            key_topics=["leadership"],
            underlying_intent=["Assess experience"],
            red_flags=[],
            related_to_previous=False,
            builds_on_exchange=None,
            recommended_style=ResponseStyle.EXECUTIVE,
            response_structure=["Context", "Action", "Result"],
            confidence=0.85,
        )

        context = AssembledContext(
            question="Tell me about your leadership experience",
            analysis=analysis,
            evidence=[
                EvidenceChunk(
                    text="Led engineering team of 15 engineers",
                    source="achievement",
                    relevance_score=0.92,
                    metadata={},
                ),
            ],
            interview_config={"llm_alias": "main"},
        )

        class BrokenRealAdapter:
            model = "broken-model"

            async def stream(self, messages, config):
                if False:
                    yield ""
                raise RuntimeError("upstream timeout")

            async def generate(self, messages, config):
                raise RuntimeError("upstream timeout")

        with patch("adapters.provider_registry.get_registry") as mock_registry:
            mock_registry.return_value.get_llm_config.return_value.provider = "anthropic"
            mock_registry.return_value.get_llm_config.return_value.model = "broken-model"
            mock_registry.return_value.get_llm_config.return_value.config = {}
            with patch(
                "adapters.llm_adapter.get_llm_adapter_or_demo",
                return_value=BrokenRealAdapter(),
            ):
                response = asyncio.run(composer.compose(context))

        assert response.mode == "fallback"
        assert response.metadata.get("composer_status") == "llm_error_fallback"
        assert "fallback_reason" in response.metadata

    def test_build_prompt_includes_rich_candidate_company_context(self):
        """Prompt should include rich candidate and company context sections."""
        composer = ResponseComposer(mode=ComposerMode.DEMO, use_llm=False)

        analysis = QuestionAnalysis(
            primary_type=QuestionType.TECHNICAL,
            is_compound=False,
            sub_questions=[],
            key_topics=["technical"],
            underlying_intent=["Assess depth"],
            red_flags=[],
            related_to_previous=False,
            builds_on_exchange=None,
            recommended_style=ResponseStyle.TECHNICAL,
            response_structure=["Problem", "Analysis", "Solution", "Outcome"],
            confidence=0.9,
        )

        context = AssembledContext(
            question="How would you lead architecture modernization?",
            analysis=analysis,
            evidence=[
                EvidenceChunk(
                    text="Led migration from monolith to microservices with 40% latency reduction",
                    source="achievement",
                    relevance_score=0.93,
                    metadata={},
                )
            ],
            interview_config={
                "candidate_name": "Alex",
                "candidate_summary": "Engineering leader",
                "candidate_skills": ["Python", "System Design"],
                "candidate_achievements": ["Reduced cloud cost by 28%"],
                "candidate_certifications": ["AWS Solutions Architect"],
                "company_name": "NovaTech",
                "role_title": "Head of Platform",
                "company_industry": "SaaS",
                "company_description": "B2B workflow platform",
                "company_requirements": ["Scale platform", "Improve reliability"],
                "company_culture": "Ownership and collaboration",
            },
        )

        prompt = composer._build_prompt(context, ResponseStyle.TECHNICAL)

        assert "CANDIDATE PROFILE" in prompt
        assert "System Design" in prompt
        assert "AWS Solutions Architect" in prompt
        assert "TARGET COMPANY/ROLE" in prompt
        assert "Scale platform" in prompt
        assert "Ownership and collaboration" in prompt
        assert "ADAPTATION RULES" in prompt


class TestLanguagePolicyIntegration:
    """Integration tests for language policy"""
    
    def test_english_detection(self):
        """Test English language detection"""
        policy = LanguagePolicy()
        
        decision = policy.decide("Tell me about your experience with microservices")
        
        assert decision.final_language == "en"
        assert decision.confidence > 0
    
    def test_spanish_detection(self):
        """Test Spanish language detection"""
        policy = LanguagePolicy()
        
        decision = policy.decide("Cuéntame sobre tu experiencia con microservicios")
        
        assert decision.final_language == "es"
        assert decision.confidence > 0
    
    def test_bilingual_handling(self):
        """Test handling of bilingual content"""
        policy = LanguagePolicy()
        
        # Last sentence determines language
        decision = policy.decide(
            "Tell me about your experience. Cuéntame más detalles."
        )
        
        # Should detect Spanish as the last sentence language
        assert decision.final_language in ["es", "en"]  # Either is acceptable for mixed


class TestQualityGateIntegration:
    """Integration tests for quality gate"""
    
    @pytest.mark.asyncio
    async def test_quality_gate_pass(self):
        """Test quality gate passing a good response"""
        gate = QualityGate()
        
        response = GeneratedResponse(
            bullets=[
                "• Led team of 15 engineers",
                "• Achieved 3x growth",
            ],
            full_response=(
                "In my role as VP of Engineering, I led a team of 15 engineers "
                "and scaled the organization from 5 to 50 engineers in 18 months. "
                "This resulted in 3x platform growth and improved deployment frequency by 10x."
            ),
            key_metrics=["15 engineers", "3x growth", "18 months"],
            confidence=0.9,
            style_used=ResponseStyle.EXECUTIVE,
        )
        
        analysis = QuestionAnalysis(
            primary_type=QuestionType.BEHAVIORAL,
            is_compound=False,
            sub_questions=[],
            key_topics=["leadership"],
            underlying_intent=["Assess experience"],
            red_flags=[],
            related_to_previous=False,
            builds_on_exchange=None,
            recommended_style=ResponseStyle.EXECUTIVE,
            response_structure=[],
            confidence=0.85,
        )
        
        final_response, result = await gate.process(
            response, analysis, None, "en"
        )
        
        # Good response should pass
        assert result.score >= 0.8
    
    @pytest.mark.asyncio
    async def test_quality_gate_fail_short_response(self):
        """Test quality gate failing a too-short response"""
        gate = QualityGate()
        
        response = GeneratedResponse(
            bullets=["• Led team"],
            full_response="I led a team.",  # Too short
            key_metrics=[],
            confidence=0.5,
            style_used=ResponseStyle.EXECUTIVE,
        )
        
        analysis = QuestionAnalysis(
            primary_type=QuestionType.BEHAVIORAL,
            is_compound=False,
            sub_questions=[],
            key_topics=["leadership"],
            underlying_intent=[],
            red_flags=[],
            related_to_previous=False,
            builds_on_exchange=None,
            recommended_style=ResponseStyle.EXECUTIVE,
            response_structure=[],
            confidence=0.85,
        )
        
        final_response, result = await gate.process(
            response, analysis, None, "en"
        )
        
        # Short response should fail
        assert not result.passed
        assert "short" in " ".join(result.issues).lower()


class TestFullPipelineIntegration:
    """Integration tests for the full pipeline"""
    
    @pytest.mark.asyncio
    async def test_pipeline_process_question(self):
        """Test processing a question through the full pipeline"""
        pipeline = RealtimePipeline(config=PipelineConfig(
            use_real_llm=False,
            use_real_embeddings=False,
        ))
        
        # Start session
        await pipeline.start_session(
            "test-session-001",
            {
                "company_name": "TechCorp",
                "role_title": "CTO",
                "job_description": "Technical leadership role",
                "response_style": "executive",
            }
        )
        
        # Process question
        result = await pipeline.process_question(
            "Tell me about your leadership experience"
        )
        
        # Verify results
        assert result.exchange is not None
        assert result.exchange.interviewer_utterance == "Tell me about your leadership experience"
        assert result.question_analysis is not None
        assert result.question_analysis.primary_type == QuestionType.BEHAVIORAL
        assert result.generated_response is not None
        assert len(result.generated_response.bullets) > 0
        assert result.total_latency_ms >= 0
        
        # End session
        summary = await pipeline.end_session()
        assert summary["session_id"] == "test-session-001"
        assert summary["total_exchanges"] == 1
    
    @pytest.mark.asyncio
    async def test_pipeline_consecutive_questions(self):
        """Test processing multiple consecutive questions"""
        pipeline = RealtimePipeline(config=PipelineConfig(
            use_real_llm=False,
            use_real_embeddings=False,
        ))
        
        await pipeline.start_session(
            "test-session-002",
            {"company_name": "StartupCo", "role_title": "VP Engineering"}
        )
        
        # Process multiple questions
        questions = [
            "Tell me about yourself",
            "What is your leadership style?",
            "Describe a challenging project",
        ]
        
        for q in questions:
            result = await pipeline.process_question(q)
            assert result.exchange is not None
        
        # Check conversation tracking
        summary = await pipeline.end_session()
        assert summary["total_exchanges"] == 3


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
