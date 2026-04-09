"""
Interview Coach - Quality Gate
Draft → Validate → Repair → Expose pipeline
"""
import time
import re
from typing import Optional
from contracts.models import (
    GeneratedResponse, QualityResult, ConversationMap, 
    LanguageDecision, QuestionAnalysis, ResponseStyle
)
from adapters.interfaces import LLMAdapter


class QualityGate:
    """
    Implements the quality gate pipeline:
    1. validate_bullets - Quick heuristics (<50ms)
    2. validate_full_response - 6 comprehensive checks
    3. repair - Single repair attempt with specific instructions
    4. fallback - Deterministic fallback if repair fails
    """
    
    def __init__(self, llm_adapter: Optional[LLMAdapter] = None):
        self.llm = llm_adapter
        self.max_repair_attempts = 1
    
    async def validate_bullets(
        self, 
        bullets: list[str], 
        conversation_map: ConversationMap
    ) -> QualityResult:
        """
        Quick validation of bullet points using heuristics.
        Target: <50ms
        """
        start_time = time.time()
        issues = []
        repetitions = []
        
        for bullet in bullets:
            # Check for repeated metrics
            for metric in conversation_map.metrics_used:
                if metric.lower() in bullet.lower():
                    repetitions.append(f"Métrica repetida: {metric}")
            
            # Check for repeated claims
            for claim in conversation_map.claims:
                if claim.lower() in bullet.lower():
                    repetitions.append(f"Claim repetido: {claim}")
        
        passed = len(issues) == 0 and len(repetitions) == 0
        score = 1.0 - (len(issues) + len(repetitions)) * 0.2
        
        return QualityResult(
            passed=passed,
            score=max(0.0, score),
            issues=issues,
            repetitions=repetitions,
        )
    
    async def validate_full_response(
        self,
        response: GeneratedResponse,
        conversation_map: ConversationMap,
        language_decision: LanguageDecision,
        analysis: QuestionAnalysis,
    ) -> QualityResult:
        """
        Full validation with 6 checks:
        1. ¿Repite métrica ya usada en exchanges previos?
        2. ¿Contradice claim previo del usuario?
        3. ¿Cubre sub-preguntas must_answer?
        4. ¿Idioma consistente con LanguageDecision?
        5. ¿Largo apropiado? (< 250 palabras)
        6. ¿Estilo correcto?
        """
        issues = []
        contradictions = []
        repetitions = []
        
        full_text = response.full_response.lower()
        
        # Check 1: Repeated metrics
        for metric in conversation_map.metrics_used:
            if metric.lower() in full_text:
                repetitions.append(f"Métrica ya usada: {metric}")
        
        # Check 2: Contradicts previous claims
        # Simple heuristic - in production, use NLI model
        for claim in conversation_map.claims:
            # Very basic contradiction detection
            if self._check_contradiction(full_text, claim.lower()):
                contradictions.append(f"Posible contradicción con: {claim}")
        
        # Check 3: Covers must_answer sub-questions
        must_answer = [sq for sq in analysis.sub_questions if sq.priority.value == "must_answer"]
        covered = 0
        for sq in must_answer:
            # Check if any keyword from the sub-question appears
            keywords = sq.text.lower().split()[:5]
            if any(kw in full_text for kw in keywords):
                covered += 1
        
        if must_answer and covered < len(must_answer):
            issues.append(f"Sub-preguntas must_answer cubiertas: {covered}/{len(must_answer)}")
        
        # Check 4: Language consistency
        detected_lang = self._detect_language(response.full_response)
        if detected_lang != language_decision.final_language:
            issues.append(
                f"Idioma detectado ({detected_lang}) != esperado ({language_decision.final_language})"
            )
        
        # Check 5: Length
        word_count = len(response.full_response.split())
        if word_count > 250:
            issues.append(f"Respuesta muy larga: {word_count} palabras (máx 250)")
        elif word_count < 30:
            issues.append(f"Respuesta muy corta: {word_count} palabras")
        
        # Check 6: Style check (basic)
        if response.style_used != analysis.recommended_style and analysis.recommended_style.value != "mixed":
            issues.append(
                f"Estilo usado ({response.style_used.value}) != recomendado ({analysis.recommended_style.value})"
            )
        
        # Calculate score
        total_checks = 6
        failed_checks = len(issues) + len(contradictions) + len(repetitions)
        score = max(0.0, 1.0 - (failed_checks * 0.15))
        
        return QualityResult(
            passed=len(issues) == 0 and len(contradictions) == 0 and len(repetitions) == 0,
            score=score,
            issues=issues,
            contradictions=contradictions,
            repetitions=repetitions,
        )
    
    async def repair(
        self,
        response: GeneratedResponse,
        quality_result: QualityResult,
        conversation_map: ConversationMap,
    ) -> GeneratedResponse:
        """
        Single repair attempt with specific instructions.
        Only repairs what failed.
        """
        if self.llm is None:
            return self._fallback(response.bullets)
        
        # Build repair instructions
        repair_instructions = []
        
        for metric in quality_result.repetitions:
            repair_instructions.append(f"NO uses: {metric}")
        
        for claim in quality_result.contradictions:
            repair_instructions.append(f"EVITA contradecir: {claim}")
        
        for issue in quality_result.issues:
            repair_instructions.append(f"ARREGLA: {issue}")
        
        # Request repair from LLM
        repair_prompt = f"""
        La siguiente respuesta tiene problemas. Repárala siguiendo las instrucciones.
        
        RESPUESTA ORIGINAL:
        {response.full_response}
        
        INSTRUCCIONES DE REPARACIÓN:
        {chr(10).join(f'- {i}' for i in repair_instructions)}
        
        MÉTRICAS YA USADAS (NO REPETIR):
        {', '.join(conversation_map.metrics_used)}
        
        Genera una respuesta reparada manteniendo los bullets principales.
        """
        
        try:
            repaired_text = await self.llm.generate(
                messages=[{"role": "user", "content": repair_prompt}],
                config={"temperature": 0.2, "max_tokens": 300}
            )
            
            return GeneratedResponse(
                bullets=response.bullets,
                full_response=repaired_text,
                key_metrics=response.key_metrics,
                confidence=response.confidence * 0.9,
                style_used=response.style_used,
            )
        except Exception:
            return self._fallback(response.bullets)
    
    def _fallback(self, bullets: list[str]) -> GeneratedResponse:
        """
        Deterministic fallback when repair fails.
        Returns only bullets with a guide message.
        """
        return GeneratedResponse(
            bullets=bullets,
            full_response="Usa los puntos clave como guía para tu respuesta.",
            key_metrics=[],
            confidence=0.5,
            style_used=ResponseStyle.EXECUTIVE,
        )
    
    def _check_contradiction(self, text: str, claim: str) -> bool:
        """Basic contradiction detection - placeholder for NLI model"""
        # Simple heuristic: look for negation near claim keywords
        negation_patterns = ["no ", "nunca ", "jamás ", "never ", "not "]
        claim_words = claim.split()[:3]
        
        for pattern in negation_patterns:
            for word in claim_words:
                if pattern + word in text:
                    return True
        return False
    
    def _detect_language(self, text: str) -> str:
        """Simple language detection"""
        spanish_indicators = ["el ", "la ", "los ", "las ", "de ", "que ", "en ", "un ", "una "]
        english_indicators = ["the ", "is ", "are ", "in ", "of ", "to ", "a ", "an "]
        
        text_lower = text.lower()
        es_count = sum(1 for ind in spanish_indicators if ind in text_lower)
        en_count = sum(1 for ind in english_indicators if ind in text_lower)
        
        return "es" if es_count > en_count else "en"


# Import ResponseStyle for fallback
from contracts.models import ResponseStyle
