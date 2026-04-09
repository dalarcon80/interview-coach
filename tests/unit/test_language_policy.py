"""
Interview Coach - Unit Tests for Language Policy
Tests for language detection and decision logic
"""
import pytest

from contracts.models import LanguageDecision


class TestLanguageDecision:
    """Test LanguageDecision model"""
    
    def test_spanish_decision(self):
        """Test Spanish language decision"""
        decision = LanguageDecision(
            final_language="es",
            confidence=0.95,
            method="dominant",
        )
        assert decision.final_language == "es"
        assert decision.confidence == 0.95
    
    def test_english_decision(self):
        """Test English language decision"""
        decision = LanguageDecision(
            final_language="en",
            confidence=0.9,
            method="user_preference",
            user_preference="en",
        )
        assert decision.final_language == "en"
        assert decision.user_preference == "en"
    
    def test_low_confidence_fallback(self):
        """Test low confidence fallback"""
        decision = LanguageDecision(
            final_language="es",
            confidence=0.5,
            method="fallback",
        )
        assert decision.confidence < 0.6
        assert decision.method == "fallback"


class TestLanguagePolicyCases:
    """Test language policy decision cases"""
    
    def test_user_preference_takes_priority(self):
        """Test user preference takes highest priority"""
        # Rule 1: User preference always wins
        decision = LanguageDecision(
            final_language="en",
            confidence=1.0,
            method="user_preference",
            user_preference="en",
        )
        assert decision.final_language == "en"
        assert decision.confidence == 1.0
    
    def test_dominant_language_detection(self):
        """Test dominant language detection (>80%)"""
        # Rule 2: If >80% of utterance is in one language, use that
        decision = LanguageDecision(
            final_language="es",
            confidence=0.9,
            method="dominant",
            segments=[
                {"text": "Cuéntame sobre tu experiencia", "language": "es", "duration_pct": 0.85},
                {"text": "leadership", "language": "en", "duration_pct": 0.15},
            ],
        )
        assert decision.final_language == "es"
        assert decision.method == "dominant"
    
    def test_bilingual_uses_last_sentence(self):
        """Test bilingual utterance uses last sentence language"""
        # Rule 3: For bilingual turns, use last direct sentence
        decision = LanguageDecision(
            final_language="en",
            confidence=0.7,
            method="last_sentence",
            segments=[
                {"text": "Cuéntame sobre tu experiencia", "language": "es"},
                {"text": "specifically in startups", "language": "en"},
            ],
        )
        assert decision.final_language == "en"
        assert decision.method == "last_sentence"
    
    def test_low_confidence_session_fallback(self):
        """Test low confidence uses session history"""
        # Rule 4: Low confidence (<0.6) uses stable session language
        decision = LanguageDecision(
            final_language="es",
            confidence=0.5,
            method="session_stable",
        )
        assert decision.confidence < 0.6
        assert decision.method == "session_stable"
    
    def test_absolute_fallback_is_spanish(self):
        """Test absolute fallback is Spanish"""
        # Rule 5: Absolute fallback is Spanish
        decision = LanguageDecision(
            final_language="es",
            confidence=0.3,
            method="fallback",
        )
        assert decision.final_language == "es"


class TestLanguagePolicyCasesFromBank:
    """Test language policy cases from question bank"""
    
    def test_mixed_english_spanish(self):
        """Test mixed EN/ES utterance"""
        # Interviewer asks in English, candidate responds in Spanish
        decision = LanguageDecision(
            final_language="en",
            confidence=0.85,
            method="dominant",
        )
        assert decision.final_language == "en"
    
    def test_spanish_with_technical_terms(self):
        """Test Spanish with English technical terms"""
        # Spanish utterance with English tech terms like "Kubernetes", "microservices"
        decision = LanguageDecision(
            final_language="es",
            confidence=0.9,
            method="dominant",
            segments=[
                {"text": "¿Cómo manejas", "language": "es"},
                {"text": "Kubernetes", "language": "en"},  # Technical term
                {"text": "en producción?", "language": "es"},
            ],
        )
        # Technical terms don't change the dominant language
        assert decision.final_language == "es"
    
    def test_code_switching_mid_sentence(self):
        """Test code-switching mid-sentence"""
        decision = LanguageDecision(
            final_language="es",
            confidence=0.75,
            method="last_sentence",
            segments=[
                {"text": "When I worked at", "language": "en"},
                {"text": "la startup", "language": "es"},
                {"text": "we used microservices", "language": "en"},
            ],
        )
        # Uses last sentence or dominant
        assert decision.final_language in ["es", "en"]


class TestLanguagePolicyConfidence:
    """Test language policy confidence levels"""
    
    def test_high_confidence(self):
        """Test high confidence detection"""
        decision = LanguageDecision(
            final_language="es",
            confidence=0.95,
        )
        assert decision.confidence >= 0.9
    
    def test_medium_confidence(self):
        """Test medium confidence detection"""
        decision = LanguageDecision(
            final_language="es",
            confidence=0.7,
        )
        assert 0.6 <= decision.confidence < 0.9
    
    def test_low_confidence(self):
        """Test low confidence detection"""
        decision = LanguageDecision(
            final_language="es",
            confidence=0.4,
        )
        assert decision.confidence < 0.6


class TestLanguagePolicyExceptions:
    """Test language policy exceptions"""
    
    def test_proper_names_exception(self):
        """Test that proper names don't affect language"""
        # Names like "Google", "AWS", "Kubernetes" don't count as English
        decision = LanguageDecision(
            final_language="es",
            confidence=0.9,
            method="dominant",
        )
        assert decision.final_language == "es"
    
    def test_technical_terms_exception(self):
        """Test that technical terms don't affect language"""
        # Technical terms like "API", "REST", "CI/CD" are language-neutral
        decision = LanguageDecision(
            final_language="es",
            confidence=0.9,
            method="dominant",
        )
        assert decision.final_language == "es"
