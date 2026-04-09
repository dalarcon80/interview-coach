"""
Interview Coach - Language Policy
Determines response language based on interviewer's language

Rules (in order of priority):
1. User preference (fixed) -> use that language (confidence 1.0)
2. Dominant language (>80% duration) -> use that
3. Bilingual turn -> language of last direct sentence
4. Low confidence (<0.6) -> use session stable language (last 3 exchanges)
5. Fallback -> Spanish

Post-condition: Response must be 100% in final_language
(exceptions: proper names and technical terms without natural translation)
"""
import re
from dataclasses import dataclass
from typing import Optional

from contracts.models import LanguageDecision


@dataclass
class LanguageSegment:
    """A segment of text with detected language"""
    text: str
    language: str  # "es" | "en"
    confidence: float
    duration_pct: float = 0.0  # Percentage of total turn duration


# Common technical terms that don't count as English
TECHNICAL_TERMS = {
    "kubernetes", "docker", "api", "rest", "graphql", "sql", "nosql",
    "aws", "azure", "gcp", "ci", "cd", "git", "github", "gitlab",
    "javascript", "typescript", "python", "java", "rust", "golang",
    "react", "vue", "angular", "node", "npm", "yarn",
    "microservices", "monolith", "serverless", "lambda",
    "kafka", "redis", "mongodb", "postgresql", "mysql",
    "devops", "sre", "qa", "ux", "ui", "ai", "ml", "llm",
}

# Proper names that don't count as any language
PROPER_NAMES = {
    "google", "microsoft", "amazon", "meta", "apple", "netflix",
    "spotify", "uber", "airbnb", "stripe", "square", "paypal",
}


class LanguagePolicy:
    """
    Determines the response language based on the interviewer's utterance.
    
    Implements the 5-rule priority system from Architecture v3.2.1.
    """
    
    def __init__(self, user_preference: Optional[str] = None):
        """
        Initialize language policy.
        
        Args:
            user_preference: Fixed language preference ("es" or "en")
        """
        self.user_preference = user_preference
        self.session_history: list[str] = []  # Last 3 exchange languages
    
    def decide(self, text: str) -> LanguageDecision:
        """
        Determine the response language for the given text.
        
        Args:
            text: The interviewer's utterance
        
        Returns:
            LanguageDecision with final_language and confidence
        """
        # Rule 1: User preference takes highest priority
        if self.user_preference:
            return LanguageDecision(
                final_language=self.user_preference,
                confidence=1.0,
                method="user_preference",
                user_preference=self.user_preference,
            )
        
        # Detect language segments
        segments = self._detect_segments(text)
        
        # Calculate language distribution
        es_duration = sum(s.duration_pct for s in segments if s.language == "es")
        en_duration = sum(s.duration_pct for s in segments if s.language == "en")
        
        # Rule 2: Dominant language (>80%)
        if es_duration > 0.8:
            return LanguageDecision(
                final_language="es",
                confidence=0.95,
                method="dominant",
                segments=[{"text": s.text, "language": s.language} for s in segments],
            )
        
        if en_duration > 0.8:
            return LanguageDecision(
                final_language="en",
                confidence=0.95,
                method="dominant",
                segments=[{"text": s.text, "language": s.language} for s in segments],
            )
        
        # Rule 3: Bilingual turn - use last sentence language
        last_sentence = self._get_last_sentence(text)
        if last_sentence:
            last_lang = self._detect_single_language(last_sentence)
            if last_lang:
                return LanguageDecision(
                    final_language=last_lang,
                    confidence=0.7,
                    method="last_sentence",
                    segments=[{"text": s.text, "language": s.language} for s in segments],
                )
        
        # Rule 4: Low confidence - use session stable language
        stable_lang = self._get_session_stable_language()
        if stable_lang:
            return LanguageDecision(
                final_language=stable_lang,
                confidence=0.5,
                method="session_stable",
            )
        
        # Rule 5: Fallback to Spanish
        return LanguageDecision(
            final_language="es",
            confidence=0.3,
            method="fallback",
        )
    
    def _detect_segments(self, text: str) -> list[LanguageSegment]:
        """Detect language segments in text"""
        segments = []
        words = text.split()
        
        if not words:
            return segments
        
        # Simple word-by-word detection
        es_words = 0
        en_words = 0
        current_segment_words = []
        current_lang = None
        
        for word in words:
            clean_word = word.lower().strip(".,!?¿¡")
            
            # Skip technical terms and proper names
            if clean_word in TECHNICAL_TERMS or clean_word in PROPER_NAMES:
                continue
            
            lang = self._classify_word(clean_word)
            
            if lang != current_lang and current_segment_words:
                # Save previous segment
                segment_text = " ".join(current_segment_words)
                segments.append(LanguageSegment(
                    text=segment_text,
                    language=current_lang or "es",
                    confidence=0.8,
                    duration_pct=len(current_segment_words) / len(words),
                ))
                current_segment_words = []
            
            current_lang = lang
            current_segment_words.append(word)
            
            if lang == "es":
                es_words += 1
            elif lang == "en":
                en_words += 1
        
        # Don't forget the last segment
        if current_segment_words:
            segment_text = " ".join(current_segment_words)
            segments.append(LanguageSegment(
                text=segment_text,
                language=current_lang or "es",
                confidence=0.8,
                duration_pct=len(current_segment_words) / len(words),
            ))
        
        return segments
    
    def _classify_word(self, word: str) -> str:
        """Classify a single word as Spanish or English"""
        # Common Spanish patterns
        spanish_patterns = [
            r".*ción$", r".*dad$", r".*mente$", r".*ando$", r".*iendo$",
            r".*emos$", r".*áis$", r".*ías$", r".*qué$", r".*cómo$",
            r".*cuándo$", r".*dónde$", r".*porqué$",
        ]
        
        for pattern in spanish_patterns:
            if re.match(pattern, word):
                return "es"
        
        # Spanish common words
        spanish_words = {
            "el", "la", "los", "las", "un", "una", "y", "o", "pero",
            "que", "qué", "de", "del", "en", "es", "son", "está",
            "están", "ser", "estar", "tener", "hacer", "poder",
            "decir", "ir", "ver", "dar", "saber", "querer", "llegar",
            "pasar", "deber", "poner", "parecer", "quedar", "creer",
            "hablar", "llevar", "dejar", "seguir", "encontrar", "llamar",
            "cuéntame", "dime", "explica", "describe", "cuál", "cuáles",
            "quién", "quiénes", "cuánto", "cuánta", "cuántos", "cuántas",
            "por", "para", "con", "sin", "sobre", "entre", "hasta",
            "desde", "hacia", "durante", "mediante", "según", "contra",
            "esto", "eso", "aquello", "este", "ese", "aquel",
            "aquí", "ahí", "allí", "ahora", "siempre", "nunca",
            "también", "tampoco", "sí", "no", "ya", "muy", "mucho",
            "poco", "bastante", "demasiado", "todo", "nada", "algo",
            "alguien", "nadie", "cualquier", "cada", "varios", "otros",
            "mi", "tu", "su", "nuestro", "vuestro", "mis", "tus", "sus",
            "mío", "tuyo", "suyo", "nuestro", "vuestro", "mía", "tuya",
            "suya", "nuestra", "vuestra", "míos", "tuyos", "suyos",
        }
        
        # English common words
        english_words = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at",
            "to", "for", "of", "with", "by", "from", "as", "is", "was",
            "are", "were", "been", "be", "have", "has", "had", "do",
            "does", "did", "will", "would", "could", "should", "may",
            "might", "must", "shall", "can", "need", "dare", "ought",
            "used", "this", "that", "these", "those", "what", "which",
            "who", "whom", "whose", "where", "when", "why", "how",
            "tell", "me", "about", "describe", "explain", "what's",
            "how", "why", "when", "where", "which", "who", "whom",
            "i", "you", "he", "she", "it", "we", "they", "my", "your",
            "his", "her", "its", "our", "their", "mine", "yours", "hers",
            "ours", "theirs", "myself", "yourself", "himself", "herself",
            "itself", "ourselves", "themselves", "here", "there", "now",
            "then", "always", "never", "often", "sometimes", "usually",
            "just", "only", "also", "even", "still", "already", "yet",
        }
        
        if word in spanish_words:
            return "es"
        if word in english_words:
            return "en"
        
        # Default to Spanish for unknown
        return "es"
    
    def _detect_single_language(self, text: str) -> Optional[str]:
        """Detect language of a single text segment"""
        segments = self._detect_segments(text)
        if not segments:
            return None
        
        # Return the language of the largest segment
        return max(segments, key=lambda s: s.duration_pct).language
    
    def _get_last_sentence(self, text: str) -> str:
        """Get the last sentence from text"""
        # Split on sentence-ending punctuation
        sentences = re.split(r'[.!?¿¡]+', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        
        if sentences:
            return sentences[-1]
        return ""
    
    def _get_session_stable_language(self) -> Optional[str]:
        """Get the stable language from recent session history"""
        if len(self.session_history) < 3:
            return None
        
        # Get the most common language from last 3 exchanges
        recent = self.session_history[-3:]
        es_count = recent.count("es")
        en_count = recent.count("en")
        
        if es_count >= 2:
            return "es"
        if en_count >= 2:
            return "en"
        return None
    
    def record_exchange(self, language: str):
        """Record the language used in an exchange"""
        self.session_history.append(language)
        # Keep only last 3
        self.session_history = self.session_history[-3:]
    
    def reset(self):
        """Reset the policy state"""
        self.session_history = []


# Unit tests
if __name__ == "__main__":
    policy = LanguagePolicy()
    
    # Test Spanish detection
    decision = policy.decide("Cuéntame sobre tu experiencia profesional")
    assert decision.final_language == "es"
    assert decision.method == "dominant"
    
    # Test English detection
    decision = policy.decide("Tell me about your professional experience")
    assert decision.final_language == "en"
    assert decision.method == "dominant"
    
    # Test user preference
    policy_pref = LanguagePolicy(user_preference="en")
    decision = policy_pref.decide("Cuéntame sobre tu experiencia")
    assert decision.final_language == "en"
    assert decision.method == "user_preference"
    assert decision.confidence == 1.0
    
    print("LanguagePolicy tests passed!")
