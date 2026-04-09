"""
Interview Coach - Conversation Tracker
Maintains ConversationMap with claims, metrics, gaps, and coherence
"""
import re
from typing import Optional, List
from contracts.models import (
    ConversationMap, Exchange, QuestionType,
    QuestionAnalysis, GeneratedResponse, EvidenceChunk
)


class ConversationTracker:
    """
    Tracks conversation state:
    - claims: what the candidate has said
    - metrics_used: metrics already mentioned
    - achievements_referenced: profile achievements cited
    - uncovered_gaps: topics the interviewer looked for but weren't covered well
    - interviewer_values: topics the interviewer seems to value (inferred)
    - warnings: contradictions or repetitions detected
    
    Updates after each user response (captured via mic).
    """
    
    def __init__(self):
        self.map = ConversationMap()
        self.exchanges: List[Exchange] = []
    
    def update_from_analysis(
        self,
        analysis: QuestionAnalysis,
        suggested_response: GeneratedResponse,
    ) -> None:
        """Update conversation map from the analysis and suggested response"""
        
        # Extract new metrics from the suggested response
        new_metrics = self._extract_metrics(suggested_response.key_metrics)
        self.map.metrics_used.extend(new_metrics)
        
        # Extract claims from the suggested response
        claims = self._extract_claims(suggested_response.full_response)
        self.map.claims.extend(claims)
        
        # Track topics covered
        self.map.topics_covered.extend(analysis.key_topics)
        
        # Check for gaps
        self._detect_gaps(analysis)
        
        # Infer interviewer values from red flags and intent
        self._infer_interviewer_values(analysis)
    
    def update_from_user_response(
        self,
        user_response: str,
        analysis: Optional[QuestionAnalysis] = None,
    ) -> list[str]:
        """
        Update based on user's actual response.
        Returns list of warnings if any issues detected.
        """
        warnings = []
        
        # Extract claims from user response
        claims = self._extract_claims(user_response)
        
        # Check for contradictions with previous claims
        for claim in claims:
            contradiction = self._check_contradiction(claim)
            if contradiction:
                warnings.append(f"Posible contradicción: {contradiction}")
                self.map.warnings.append(contradiction)
        
        # Check for new metrics
        metrics = self._extract_metrics_from_text(user_response)
        for metric in metrics:
            if metric in self.map.metrics_used:
                warnings.append(f"Métrica repetida: {metric}")
            else:
                self.map.metrics_used.append(metric)
        
        # Update claims (user's actual claims, not suggested)
        self.map.claims.extend(claims)
        
        # Check if user covered gaps
        if analysis and analysis.key_topics:
            for gap in self.map.uncovered_gaps:
                if any(topic.lower() in user_response.lower() for topic in analysis.key_topics):
                    self.map.uncovered_gaps.remove(gap)
        
        return warnings
    
    def _extract_metrics(self, metrics_list: List[str]) -> List[str]:
        """Extract and normalize metrics"""
        normalized = []
        for metric in metrics_list:
            # Normalize metric format
            clean = metric.strip().lower()
            if clean and clean not in self.map.metrics_used:
                normalized.append(clean)
        return normalized
    
    def _extract_metrics_from_text(self, text: str) -> List[str]:
        """Extract metrics from text using patterns"""
        metrics = []
        
        # Pattern for percentages
        percentages = re.findall(r'\d+%', text)
        metrics.extend(percentages)
        
        # Pattern for monetary values
        money = re.findall(r'\$[\d,]+(?:\.\d+)?(?:k|K|M|m)?', text)
        metrics.extend(money)
        
        # Pattern for time periods
        time_periods = re.findall(r'\d+\s*(?:años?|years?|meses?|months?)', text, re.IGNORECASE)
        metrics.extend(time_periods)
        
        # Pattern for counts
        counts = re.findall(r'\d+\s*(?:personas?|people|equipos?|teams?|proyectos?|projects?)', text, re.IGNORECASE)
        metrics.extend(counts)
        
        return metrics
    
    def _extract_claims(self, text: str) -> List[str]:
        """Extract key claims from text"""
        claims = []
        
        # Split into sentences
        sentences = re.split(r'[.!?]+', text)
        
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            
            # Look for claim indicators
            claim_patterns = [
                r'(?:yo |en mi |cuando )',
                r'(?:logré|conseguí|implementé|creé|diseñé)',
                r'(?:i |when i |in my )',
                r'(?:achieved|implemented|created|designed)',
            ]
            
            for pattern in claim_patterns:
                if re.search(pattern, sentence, re.IGNORECASE):
                    # Clean and add
                    clean = sentence[:100].strip()
                    if clean:
                        claims.append(clean)
                    break
        
        return claims
    
    def _check_contradiction(self, new_claim: str) -> Optional[str]:
        """Check if new claim contradicts previous claims"""
        # Simple heuristic - look for negation of previous claims
        negation_patterns = [
            r'no (?:trabajé|estuve|hice)',
            r'never (?:worked|was|did)',
            r'no tengo (?:experiencia|conocimiento)',
        ]
        
        for pattern in negation_patterns:
            if re.search(pattern, new_claim, re.IGNORECASE):
                # Check if there's a contradictory positive claim
                positive_version = self._get_positive_version(new_claim)
                for existing in self.map.claims:
                    if positive_version.lower() in existing.lower():
                        return f"Contradicción: '{new_claim[:50]}...' vs '{existing[:50]}...'"
        
        return None
    
    def _get_positive_version(self, negated_claim: str) -> str:
        """Convert negated claim to positive for comparison"""
        # Simple heuristic
        replacements = [
            (r'no (trabajé|estuve|hice)', r'\1'),
            (r'never (worked|was|did)', r'\1'),
            (r'no tengo (experiencia|conocimiento)', r'tengo \1'),
        ]
        
        result = negated_claim
        for pattern, replacement in replacements:
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
        
        return result
    
    def _detect_gaps(self, analysis: QuestionAnalysis) -> None:
        """Detect topics the interviewer asked about that weren't covered"""
        # Add must_answer sub-questions as potential gaps
        for sq in analysis.sub_questions:
            if sq.priority.value == "must_answer":
                gap = sq.text[:50]
                if gap not in self.map.uncovered_gaps:
                    self.map.uncovered_gaps.append(gap)
    
    def _infer_interviewer_values(self, analysis: QuestionAnalysis) -> None:
        """Infer what the interviewer values from their questions"""
        # Add underlying intent as potential values
        for intent in analysis.underlying_intent:
            if intent not in self.map.interviewer_values:
                self.map.interviewer_values.append(intent)
        
        # Add key topics as values
        for topic in analysis.key_topics:
            if topic not in self.map.interviewer_values:
                self.map.interviewer_values.append(topic)
    
    def get_summary(self) -> str:
        """Generate a summary of the conversation so far"""
        parts = []
        
        if self.map.topics_covered:
            topics = ', '.join(self.map.topics_covered[-5:])
            parts.append(f"Temas cubiertos: {topics}")
        
        if self.map.metrics_used:
            metrics = ', '.join(self.map.metrics_used[-3:])
            parts.append(f"Métricas usadas: {metrics}")
        
        if self.map.uncovered_gaps:
            gaps = ', '.join(self.map.uncovered_gaps[:3])
            parts.append(f"Gaps pendientes: {gaps}")
        
        if self.map.warnings:
            parts.append(f"Advertencias: {len(self.map.warnings)}")
        
        return ' | '.join(parts) if parts else "Inicio de conversación"
    
    def to_map(self) -> ConversationMap:
        """Export as ConversationMap"""
        return self.map.copy()
    
    def reset(self) -> None:
        """Reset for a new session"""
        self.map = ConversationMap()
        self.exchanges = []
