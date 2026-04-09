"""
Interview Coach - Unit Tests for Quality Gate
Tests for quality gate pass/fail validation
"""
import pytest

from contracts.models import (
    QualityResult,
    GeneratedResponse,
    ResponseStyle,
    ConversationMap,
)


class TestQualityResult:
    """Test QualityResult model"""
    
    def test_passing_result(self):
        """Test creating a passing quality result"""
        result = QualityResult(
            passed=True,
            score=0.9,
            issues=[],
        )
        assert result.passed is True
        assert result.score == 0.9
        assert len(result.issues) == 0
    
    def test_failing_result(self):
        """Test creating a failing quality result"""
        result = QualityResult(
            passed=False,
            score=0.4,
            issues=["Response too long", "Repeats metrics"],
        )
        assert result.passed is False
        assert result.score == 0.4
        assert len(result.issues) == 2
    
    def test_result_with_contradictions(self):
        """Test quality result with contradictions"""
        result = QualityResult(
            passed=False,
            score=0.3,
            contradictions=["Claimed 50 engineers but previously said 15"],
        )
        assert len(result.contradictions) == 1


class TestQualityGateCases:
    """Test quality gate validation cases from question bank"""
    
    def test_response_too_long_fails(self):
        """Test that overly long responses fail"""
        # Response over 250 words should fail
        long_response = " ".join(["word"] * 300)
        
        result = QualityResult(
            passed=False,
            score=0.3,
            issues=["Response exceeds 250 word limit"],
        )
        assert result.passed is False
    
    def test_metric_repetition_fails(self):
        """Test that repeating metrics fails"""
        result = QualityResult(
            passed=False,
            score=0.4,
            repetitions=["'15 engineers' was already used in exchange 1"],
        )
        assert result.passed is False
        assert len(result.repetitions) == 1
    
    def test_contradiction_fails(self):
        """Test that contradictions fail"""
        result = QualityResult(
            passed=False,
            score=0.2,
            contradictions=["Said 'I built the team from scratch' but previously said 'inherited a team of 10'"],
        )
        assert result.passed is False
        assert len(result.contradictions) == 1
    
    def test_missing_must_answer_fails(self):
        """Test that missing must-answer sub-questions fails"""
        result = QualityResult(
            passed=False,
            score=0.5,
            issues=["Did not address required sub-question: 'experience scaling teams'"],
        )
        assert result.passed is False
    
    def test_language_mismatch_fails(self):
        """Test that language mismatch fails"""
        result = QualityResult(
            passed=False,
            score=0.4,
            issues=["Response language (en) does not match expected (es)"],
        )
        assert result.passed is False


class TestQualityGatePass:
    """Test quality gate passing cases"""
    
    def test_valid_response_passes(self):
        """Test that valid responses pass"""
        response = GeneratedResponse(
            bullets=["Led team of 15 engineers", "Achieved 3x growth"],
            full_response="In my role as VP of Engineering, I led a team of 15 engineers and achieved 3x revenue growth.",
            key_metrics=["15 engineers", "3x growth"],
            confidence=0.9,
            style_used=ResponseStyle.EXECUTIVE,
        )
        
        result = QualityResult(
            passed=True,
            score=0.95,
            issues=[],
        )
        
        assert result.passed is True
        assert result.score > 0.8
    
    def test_response_with_unique_metrics_passes(self):
        """Test that responses with unique metrics pass"""
        conversation_map = ConversationMap(
            metrics_used=["15 engineers", "3x growth"],
        )
        
        # New response with different metrics
        new_response = GeneratedResponse(
            key_metrics=["5 products", "$10M ARR"],
        )
        
        # All metrics are new - should pass
        result = QualityResult(
            passed=True,
            score=0.9,
        )
        assert result.passed is True


class TestQualityGateScoreThresholds:
    """Test quality gate score thresholds"""
    
    def test_score_above_0_8_passes(self):
        """Test score >= 0.8 passes"""
        result = QualityResult(passed=True, score=0.8)
        assert result.passed is True
        
        result = QualityResult(passed=True, score=0.9)
        assert result.passed is True
    
    def test_score_below_0_6_fails(self):
        """Test score < 0.6 fails"""
        result = QualityResult(passed=False, score=0.5)
        assert result.passed is False
        
        result = QualityResult(passed=False, score=0.3)
        assert result.passed is False


class TestConversationMapValidation:
    """Test conversation map validation for quality gate"""
    
    def test_empty_conversation_map(self):
        """Test validation with empty conversation map"""
        conversation_map = ConversationMap()
        
        assert len(conversation_map.claims) == 0
        assert len(conversation_map.metrics_used) == 0
    
    def test_conversation_map_with_history(self):
        """Test conversation map with history"""
        conversation_map = ConversationMap(
            claims=["I have 15 years of experience"],
            metrics_used=["15 engineers", "3x growth", "$50M budget"],
            achievements_referenced=["scaled-team-001"],
            topics_covered=["leadership", "scaling"],
        )
        
        assert len(conversation_map.claims) == 1
        assert len(conversation_map.metrics_used) == 3
        assert len(conversation_map.topics_covered) == 2
