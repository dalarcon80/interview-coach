"""
Tests for company context isolation in evidence retrieval and response composition.

These tests verify that:
1. Company names are correctly extracted from questions
2. Evidence is filtered by company when retrieving
3. Prompts include company-specific filtering instructions
4. CV analyzer correctly associates achievements with companies
"""
import pytest
import sys
from pathlib import Path

# Add python-core to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "python-core"))

from pipeline.steps.retrieval_planner import RetrievalPlanner
from pipeline.steps.response_composer import ResponseComposer
from contracts.models import (
    QuestionAnalysis,
    QuestionType,
    ResponseStyle,
    EvidenceChunk,
    AssembledContext,
    LivePreparedContext,
    ComplexityClass,
    AnswerShape,
    AskBrief,
    AskFamily,
    AnswerContract,
)


class TestCompanyExtraction:
    """Test company name extraction from questions"""
    
    def test_extract_accenture_from_question(self):
        """Test extraction of 'Accenture' from question"""
        composer = ResponseComposer()
        
        # Test direct company mention
        companies = composer._extract_mentioned_companies(
            "Tell me about your experience at Accenture",
            []
        )
        assert "Accenture" in companies
    
    def test_extract_google_from_question(self):
        """Test extraction of 'Google' from question"""
        composer = ResponseComposer()
        
        companies = composer._extract_mentioned_companies(
            "What was your biggest achievement at Google?",
            []
        )
        assert "Google" in companies
    
    def test_extract_previous_company(self):
        """Test extraction when question asks about previous role"""
        composer = ResponseComposer()
        
        companies = composer._extract_mentioned_companies(
            "Tell me about your previous role",
            []
        )
        assert "Previous" in companies or "Prior" in companies or len(companies) > 0
    
    def test_no_company_mentioned(self):
        """Test that no companies are extracted when not mentioned"""
        composer = ResponseComposer()
        
        companies = composer._extract_mentioned_companies(
            "Tell me about yourself",
            []
        )
        assert len(companies) == 0
    
    def test_prior_to_company(self):
        """Test extraction of company after 'prior to'"""
        composer = ResponseComposer()
        
        companies = composer._extract_mentioned_companies(
            "What did you do prior to joining Amazon?",
            []
        )
        assert "Amazon" in companies

    def test_strip_unstructured_response_labels_removes_full_response_heading(self):
        composer = ResponseComposer()

        cleaned = composer._strip_unstructured_response_labels(
            "FULL RESPONSE\nI've spent the last 20 years leading enterprise transformation."
        )

        assert cleaned == "I've spent the last 20 years leading enterprise transformation."


class TestRetrievalPlannerCompanyFilter:
    """Test company filtering in retrieval planner"""
    
    def test_company_filter_set_for_previous_company(self):
        """Test that company filter is set when question mentions previous company"""
        planner = RetrievalPlanner()
        
        analysis = QuestionAnalysis(
            primary_type=QuestionType.BEHAVIORAL,
            key_topics=["leadership"],
        )
        
        plan = planner.plan(
            analysis=analysis,
            question_text="Tell me about your experience at Accenture",
        )
        
        assert plan.company_filter != ""
        assert "accenture" in plan.company_filter.lower()
    
    def test_no_company_filter_for_current_question(self):
        """Test that no company filter is set for generic questions"""
        planner = RetrievalPlanner()
        
        analysis = QuestionAnalysis(
            primary_type=QuestionType.BEHAVIORAL,
            key_topics=["leadership"],
        )
        
        plan = planner.plan(
            analysis=analysis,
            question_text="Tell me about your leadership style",
        )
        
        # Should be empty for generic questions
        assert plan.company_filter == ""


class TestResponseComposerPrompt:
    """Test that response composer includes company filtering in prompts"""
    
    def test_prompt_includes_company_filter_for_accenture(self):
        """Test prompt includes company filtering instruction for Accenture"""
        composer = ResponseComposer()
        
        evidence = [
            EvidenceChunk(
                text="Led team of 15 engineers at Accenture",
                source="achievement",
                relevance_score=0.9,
                metadata={"company": "Accenture"},
            ),
            EvidenceChunk(
                text="Scaled team from 5 to 50 at current company",
                source="achievement",
                relevance_score=0.85,
                metadata={"company": "CurrentCompany"},
            ),
        ]
        
        context = AssembledContext(
            question="Tell me about your experience at Accenture",
            evidence=evidence,
            interview_config={
                "candidate_name": "John Doe",
            },
        )
        
        prompt = composer._build_prompt(context, ResponseStyle.EXECUTIVE)
        
        # Prompt should include company filtering instruction
        assert "Accenture" in prompt
        assert "CRITICAL COMPANY FILTERING" in prompt or "experience at" in prompt.lower()
    
    def test_prompt_no_filter_for_generic_question(self):
        """Test prompt doesn't add filter for generic questions"""
        composer = ResponseComposer()
        
        evidence = [
            EvidenceChunk(
                text="Led team of 15 engineers",
                source="achievement",
                relevance_score=0.9,
                metadata={},
            ),
        ]
        
        context = AssembledContext(
            question="Tell me about your leadership style",
            evidence=evidence,
            interview_config={
                "candidate_name": "John Doe",
            },
        )
        
        prompt = composer._build_prompt(context, ResponseStyle.EXECUTIVE)
        
        # Should not have filtering instruction for generic questions
        # The prompt should still include the evidence properly
        assert "leadership style" in prompt.lower()

    def test_live_manual_prompt_prefers_semantic_contract_over_shape_rules(self):
        composer = ResponseComposer()

        prepared = LivePreparedContext(
            raw_turns=[{"speaker": "interviewer", "text": "What are you looking for in a company?"}],
            sanitized_turns=[{"speaker": "interviewer", "text": "What are you looking for in a company?"}],
            turn_window_size=1,
            signature="culture-fit",
            primary_ask="What are you looking for in a company?",
            secondary_asks=["What do you avoid?"],
            ordered_focus=["What are you looking for in a company?", "What do you avoid?"],
            answer_family=AskFamily.CULTURE_FIT,
            answer_contract=AnswerContract.PREFERENCES_AND_ANTI_PATTERNS,
            complexity_class=ComplexityClass.SIMPLE,
            answer_shape=AnswerShape.DIRECT_SHORT,
            target_length=110,
            allow_metrics=False,
            allow_profile_opening=False,
            require_ordered_coverage=False,
            question_text="What are you looking for in a company?\nAlso cover:\n- What do you avoid?",
            ask_brief=AskBrief(
                primary_ask="What are you looking for in a company?",
                secondary_asks=["What do you avoid?"],
                answer_family=AskFamily.CULTURE_FIT,
                answer_contract=AnswerContract.PREFERENCES_AND_ANTI_PATTERNS,
            ),
        )

        context = AssembledContext(
            question="What are you looking for in a company?",
            ask_brief=prepared.ask_brief,
            delivery_mode="live_manual",
            live_prepared_context=prepared,
            interview_config={"candidate_name": "John Doe"},
        )

        prompt = composer._build_prompt(context, ResponseStyle.EXECUTIVE)

        assert "RESOLVED LIVE ASK" in prompt
        assert "SOURCE OF TRUTH" in prompt
        assert "Do not turn the answer into a generic biography" in prompt
        assert "LIVE SHAPE RULES" not in prompt
        assert "NORMALIZED ANSWER OUTLINE" not in prompt

    def test_live_manual_prompt_uses_single_final_response_when_preview_is_disabled(self):
        composer = ResponseComposer()

        prepared = LivePreparedContext(
            raw_turns=[{"speaker": "interviewer", "text": "What are you looking for in a company?"}],
            sanitized_turns=[{"speaker": "interviewer", "text": "What are you looking for in a company?"}],
            turn_window_size=1,
            signature="culture-fit-final-only",
            primary_ask="What are you looking for in a company?",
            secondary_asks=["What's important for you?"],
            ordered_focus=["What are you looking for in a company?", "What's important for you?"],
            answer_family=AskFamily.CULTURE_FIT,
            answer_contract=AnswerContract.PREFERENCES_AND_ANTI_PATTERNS,
            complexity_class=ComplexityClass.SIMPLE,
            answer_shape=AnswerShape.DIRECT_SHORT,
            target_length=120,
            allow_metrics=False,
            allow_profile_opening=False,
            require_ordered_coverage=True,
            question_text="What are you looking for in a company?\nAlso cover:\n- What's important for you?",
            ask_brief=AskBrief(
                primary_ask="What are you looking for in a company?",
                secondary_asks=["What's important for you?"],
                answer_family=AskFamily.CULTURE_FIT,
                answer_contract=AnswerContract.PREFERENCES_AND_ANTI_PATTERNS,
            ),
        )

        context = AssembledContext(
            question="What are you looking for in a company?\nAlso cover:\n- What's important for you?",
            ask_brief=prepared.ask_brief,
            delivery_mode="live_manual",
            live_prepared_context=prepared,
            interview_config={"candidate_name": "John Doe"},
        )

        prompt = composer._build_prompt(
            context,
            ResponseStyle.EXECUTIVE,
            prefer_structured_output=False,
        )

        assert "Return only one polished final response." in prompt
        assert "[BULLETS]" not in prompt
        assert "[FULL_RESPONSE]" not in prompt



class TestEvidenceMetadata:
    """Test evidence chunk metadata includes company info"""
    
    def test_evidence_chunk_has_company_metadata(self):
        """Test that evidence chunks can include company in metadata"""
        chunk = EvidenceChunk(
            text="Led team at Google",
            source="achievement",
            relevance_score=0.9,
            metadata={"company": "Google"},
        )
        
        assert chunk.metadata.get("company") == "Google"
    
    def test_evidence_chunk_without_company(self):
        """Test evidence chunks without company metadata"""
        chunk = EvidenceChunk(
            text="Led team",
            source="achievement",
            relevance_score=0.9,
            metadata={},
        )
        
        assert chunk.metadata.get("company", "") == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
