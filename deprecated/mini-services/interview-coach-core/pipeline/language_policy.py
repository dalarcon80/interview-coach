"""
Interview Coach - Language Policy
5 priority rules for language detection and response
"""
import re
from typing import Optional
from contracts.models import LanguageDecision


class LanguagePolicy:
    """
    Implements language detection with 5 priority rules:
    1. User preference override (confidence 1.0)
    2. Dominant language (>80% duration)
    3. Bilingual turn → last sentence's language
    4. Low confidence (<0.6) → session stable language
    5. Absolute fallback → Spanish
    
    Post-condition: Response MUST be 100% in final_language
    Exceptions: proper names and technical terms without natural translation
    """
    
    def __init__(self, user_preference: Optional[str] = None):
        self.user_preference = user_preference
        self.session_history: list[LanguageDecision] = []
    
    def detect(self, utterance: str, partial: bool = False) -> LanguageDecision:
        """
        Detect language using the 5 priority rules.
        Returns the final language decision.
        """
        segments = self._segment_language(utterance)
        
        # Rule 1: User preference override
        if self.user_preference and self.user_preference != "auto":
            return LanguageDecision(
                final_language=self.user_preference,
                confidence=1.0,
                method="user_preference",
                segments=segments,
                user_preference=self.user_preference,
            )
        
        # Calculate language distribution
        es_duration = sum(s["duration"] for s in segments if s["lang"] == "es")
        en_duration = sum(s["duration"] for s in segments if s["lang"] == "en")
        total_duration = es_duration + en_duration
        
        if total_duration == 0:
            return self._fallback_decision(utterance, segments)
        
        es_ratio = es_duration / total_duration
        en_ratio = en_duration / total_duration
        
        # Rule 2: Dominant language (>80%)
        if es_ratio > 0.8:
            return LanguageDecision(
                final_language="es",
                confidence=es_ratio,
                method="dominant_language",
                segments=segments,
            )
        elif en_ratio > 0.8:
            return LanguageDecision(
                final_language="en",
                confidence=en_ratio,
                method="dominant_language",
                segments=segments,
            )
        
        # Rule 3: Bilingual turn → last sentence's language
        if es_ratio > 0.2 and en_ratio > 0.2:
            last_sentence_lang = self._detect_last_sentence_language(utterance)
            return LanguageDecision(
                final_language=last_sentence_lang,
                confidence=0.7,
                method="bilingual_last_segment",
                segments=segments,
            )
        
        # Rule 4: Low confidence → session stable language
        primary_lang = "es" if es_ratio > en_ratio else "en"
        confidence = max(es_ratio, en_ratio)
        
        if confidence < 0.6:
            stable_lang = self._get_session_stable_language()
            return LanguageDecision(
                final_language=stable_lang,
                confidence=0.6,
                method="session_stable",
                segments=segments,
            )
        
        # Rule 5: Fallback
        return LanguageDecision(
            final_language=primary_lang,
            confidence=confidence,
            method="primary_detected",
            segments=segments,
        )
    
    def _segment_language(self, text: str) -> list[dict]:
        """
        Segment text by language.
        Returns list of {lang, text, duration} dicts.
        """
        segments = []
        sentences = re.split(r'[.!?]+', text)
        
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            
            lang = self._detect_sentence_language(sentence)
            segments.append({
                "lang": lang,
                "text": sentence,
                "duration": len(sentence.split()),  # Word count as proxy for duration
            })
        
        return segments
    
    def _detect_sentence_language(self, sentence: str) -> str:
        """Detect language of a single sentence"""
        spanish_indicators = [
            "el ", "la ", "los ", "las ", "de ", "que ", "en ", "un ", "una ",
            "es ", "son ", "está ", "están ", "por ", "con ", "para ", "como ",
            "yo ", "tú ", "él ", "ella ", "nosotros ", "ellos ", "mi ", "tu ",
            "¿", "¡", "ción", "dad", "mente",
        ]
        english_indicators = [
            "the ", "is ", "are ", "in ", "of ", "to ", "a ", "an ",
            "and ", "or ", "but ", "for ", "with ", "as ", "at ",
            "i ", "you ", "he ", "she ", "we ", "they ", "my ", "your ",
            "ing ", "tion", "ness", "ment",
        ]
        
        sentence_lower = sentence.lower()
        
        es_count = sum(1 for ind in spanish_indicators if ind in sentence_lower)
        en_count = sum(1 for ind in english_indicators if ind in sentence_lower)
        
        return "es" if es_count >= en_count else "en"
    
    def _detect_last_sentence_language(self, text: str) -> str:
        """Detect language of the last sentence"""
        sentences = re.split(r'[.!?]+', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        
        if not sentences:
            return "es"
        
        return self._detect_sentence_language(sentences[-1])
    
    def _get_session_stable_language(self) -> str:
        """
        Get stable language from recent exchanges.
        Returns most common language from last 3 exchanges.
        """
        if not self.session_history:
            return "es"
        
        recent = self.session_history[-3:]
        lang_counts = {"es": 0, "en": 0}
        
        for decision in recent:
            lang_counts[decision.final_language] += 1
        
        return "es" if lang_counts["es"] >= lang_counts["en"] else "en"
    
    def _fallback_decision(self, utterance: str, segments: list) -> LanguageDecision:
        """Rule 5: Absolute fallback to Spanish"""
        return LanguageDecision(
            final_language="es",
            confidence=0.5,
            method="absolute_fallback",
            segments=segments,
        )
    
    def record_decision(self, decision: LanguageDecision) -> None:
        """Record a decision for session history"""
        self.session_history.append(decision)
    
    def validate_response(
        self, 
        response: str, 
        expected_language: str
    ) -> tuple[bool, list[str]]:
        """
        Validate that response is in the expected language.
        Returns (is_valid, list_of_violations)
        """
        violations = []
        sentences = re.split(r'[.!?]+', response)
        
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            
            detected = self._detect_sentence_language(sentence)
            
            # Check if sentence is in wrong language
            # Allow exceptions for proper names and technical terms
            if detected != expected_language:
                # Check if it's likely a proper name or technical term
                words = sentence.split()
                if len(words) <= 3 and all(w[0].isupper() or w.isupper() for w in words if w):
                    continue  # Likely a name or acronym
                violations.append(f"Idioma incorrecto en: '{sentence[:50]}...'")
        
        return len(violations) == 0, violations
