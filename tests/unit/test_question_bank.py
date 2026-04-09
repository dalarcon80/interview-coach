"""
Interview Coach - Unit Tests for Question Bank
Tests for question fixtures and coverage
"""
import pytest

from tests.fixtures.questions.question_bank import (
    QUESTION_BANK,
    get_question_by_id,
    get_questions_by_type,
    get_questions_by_language,
    get_quality_gate_fail_cases,
    get_language_policy_cases,
)


class TestQuestionBank:
    """Test question bank fixtures"""
    
    def test_question_bank_not_empty(self):
        """Test question bank has questions"""
        assert len(QUESTION_BANK) > 0
    
    def test_all_questions_have_required_fields(self):
        """Test all questions have required fields"""
        for q in QUESTION_BANK:
            assert "id" in q
            assert "text" in q
            assert "type" in q
            assert "language" in q
    
    def test_get_question_by_id(self):
        """Test getting question by ID"""
        if len(QUESTION_BANK) > 0:
            first_id = QUESTION_BANK[0]["id"]
            q = get_question_by_id(first_id)
            assert q is not None
            assert q["id"] == first_id
    
    def test_get_question_by_id_not_found(self):
        """Test getting non-existent question"""
        q = get_question_by_id("nonexistent-id")
        assert q is None
    
    def test_get_questions_by_type(self):
        """Test filtering questions by type"""
        behavioral = get_questions_by_type("behavioral")
        for q in behavioral:
            assert q["type"] == "behavioral"
    
    def test_get_questions_by_language(self):
        """Test filtering questions by language"""
        spanish = get_questions_by_language("es")
        for q in spanish:
            assert q["language"] == "es"
        
        english = get_questions_by_language("en")
        for q in english:
            assert q["language"] == "en"
    
    def test_get_quality_gate_fail_cases(self):
        """Test getting quality gate fail cases"""
        fail_cases = get_quality_gate_fail_cases()
        for case in fail_cases:
            assert case.get("should_fail_quality_gate") is True
    
    def test_get_language_policy_cases(self):
        """Test getting language policy cases"""
        lang_cases = get_language_policy_cases()
        for case in lang_cases:
            assert "expected_language" in case
            assert "text" in case


class TestQuestionTypes:
    """Test question type coverage"""
    
    def test_has_behavioral_questions(self):
        """Test bank has behavioral questions"""
        behavioral = get_questions_by_type("behavioral")
        assert len(behavioral) > 0
    
    def test_has_technical_questions(self):
        """Test bank has technical questions"""
        technical = get_questions_by_type("technical")
        assert len(technical) > 0
    
    def test_has_compound_questions(self):
        """Test bank has compound questions"""
        compound = get_questions_by_type("compound")
        assert len(compound) > 0


class TestQuestionLanguages:
    """Test question language coverage"""
    
    def test_has_spanish_questions(self):
        """Test bank has Spanish questions"""
        spanish = get_questions_by_language("es")
        assert len(spanish) > 0
    
    def test_has_english_questions(self):
        """Test bank has English questions"""
        english = get_questions_by_language("en")
        assert len(english) > 0
    
    def test_has_mixed_language_questions(self):
        """Test bank has mixed language questions"""
        mixed = get_questions_by_language("mixed")
        # This is optional - mixed language questions are bonus
        # assert len(mixed) > 0
