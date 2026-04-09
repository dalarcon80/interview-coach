"""
Interview Coach - Realtime Pipeline
Main orchestration for the interview coaching flow
"""
import asyncio
import time
import uuid
from typing import AsyncGenerator, Optional, Any, Dict
from datetime import datetime

# Import contracts
from contracts.models import (
    SessionState,
    Exchange,
    QuestionAnalysis,
    QuestionType,
    GeneratedResponse,
    QualityResult,
    LanguageDecision,
    EvidenceChunk,
    AssembledContext,
    InterviewConfig,
    UserProfile,
    ResponseStyle,
)

# Import components
from adapters.interfaces import LLMAdapter, EmbeddingAdapter
from adapters.provider_registry import get_registry
from pipeline.quality_gate import QualityGate
from pipeline.language_policy import LanguagePolicy
from styles.registry import get_style
from conversation.tracker import ConversationTracker


class RealtimePipeline:
    """
    Real-time interview coaching pipeline.
    
    Flow:
    1. Speculative work during partial transcripts
    2. Question analysis when turn ends
    3. Evidence retrieval
    4. Response generation (bullets first, then full)
    5. Quality gate validation
    6. Emit to UI
    """
    
    def __init__(
        self,
        llm_adapter: LLMAdapter,
        embedding_adapter: EmbeddingAdapter,
        config: InterviewConfig,
        profile: UserProfile,
    ):
        self.llm = llm_adapter
        self.embedding = embedding_adapter
        self.config = config
        self.profile = profile
        
        # Initialize components
        self.quality_gate = QualityGate(llm_adapter)
        self.language_policy = LanguagePolicy(config.language_preference)
        self.tracker = ConversationTracker()
        
        # Session state
        self.state = SessionState(
            session_id=str(uuid.uuid4()),
            interview_config=config.model_dump(),
        )
        
        # Speculative state
        self._speculative_intent: Optional[str] = None
        self._preloaded_chunks: list[EvidenceChunk] = []
    
    async def on_partial_transcript(self, partial: str) -> None:
        """
        Handle partial transcript (while interviewer is speaking).
        Do speculative work WITHOUT using LLM.
        """
        # Quick intent classification using heuristics
        self._speculative_intent = self._quick_intent_classify(partial)
        
        # Pre-fetch evidence in parallel
        prefetch_task = self._prefetch_evidence(partial)
        
        # Wait for prefetch (can be made async if needed)
        self._preloaded_chunks = await prefetch_task
        
        # Update state
        self.state.speculative_intent = self._speculative_intent
        self.state.preloaded_chunks = self._preloaded_chunks
    
    async def on_final_transcript(
        self, 
        utterance: str,
        language: Optional[str] = None,
    ) -> Exchange:
        """
        Handle final transcript when interviewer finishes speaking.
        Main pipeline execution.
        """
        start_time = time.time()
        exchange_index = len(self.state.exchanges)
        
        # Step 1: Detect language
        lang_decision = self.language_policy.detect(utterance)
        self.language_policy.record_decision(lang_decision)
        
        # Step 2: Analyze question
        analysis = await self._analyze_question(utterance, lang_decision)
        
        # Step 3: Retrieve evidence
        evidence = await self._retrieve_evidence(analysis)
        
        # Step 4: Assemble context
        context = self._assemble_context(utterance, analysis, evidence)
        
        # Step 5a: Generate bullets (fast)
        bullets_response = await self._generate_bullets(context)
        
        # Step 5b: Generate full response (in parallel with bullets validation)
        full_response_task = asyncio.create_task(
            self._generate_full_response(context)
        )
        
        # Step 6: Quality gate on bullets
        bullets_quality = await self.quality_gate.validate_bullets(
            bullets_response.bullets,
            self.tracker.to_map()
        )
        
        # Repair bullets if needed
        if not bullets_quality.passed:
            bullets_response = await self._repair_bullets(bullets_response, bullets_quality)
        
        # Wait for full response
        full_response = await full_response_task
        
        # Step 7: Quality gate on full response
        full_quality = await self.quality_gate.validate_full_response(
            full_response,
            self.tracker.to_map(),
            lang_decision,
            analysis,
        )
        
        # Repair if needed
        if not full_quality.passed:
            repair_attempts = 0
            while repair_attempts < 1 and not full_quality.passed:
                full_response = await self.quality_gate.repair(
                    full_response,
                    full_quality,
                    self.tracker.to_map()
                )
                full_quality = await self.quality_gate.validate_full_response(
                    full_response,
                    self.tracker.to_map(),
                    lang_decision,
                    analysis,
                )
                repair_attempts += 1
            
            # If still failing, use fallback
            if not full_quality.passed:
                full_response = self.quality_gate._fallback(bullets_response.bullets)
        
        # Update tracker
        self.tracker.update_from_analysis(analysis, full_response)
        
        # Create exchange record
        latency_ms = int((time.time() - start_time) * 1000)
        
        exchange = Exchange(
            index=exchange_index,
            timestamp=datetime.now(),
            interviewer_utterance=utterance,
            language_detected=lang_decision.final_language,
            analysis=analysis,
            suggested_response=GeneratedResponse(
                bullets=bullets_response.bullets,
                full_response=full_response.full_response,
                key_metrics=full_response.key_metrics,
                confidence=full_response.confidence,
                style_used=full_response.style_used,
                generation_time_ms=latency_ms,
            ),
            quality=full_quality,
            latency_ms=latency_ms,
        )
        
        # Add to state
        self.state.exchanges.append(exchange)
        
        return exchange
    
    def _quick_intent_classify(self, text: str) -> str:
        """Quick heuristic-based intent classification (no LLM)"""
        text_lower = text.lower()
        
        # Behavioral patterns
        behavioral_patterns = [
            "cuéntame", "háblame de", "dime sobre",
            "tell me about", "describe", "share",
            "experiencia", "experience", "situación",
        ]
        
        # Technical patterns
        technical_patterns = [
            "cómo", "how", "implementaste", "architect",
            "diseñaste", "designed", "tecnología", "technology",
            "sistema", "system", "código", "code",
        ]
        
        # Stress patterns
        stress_patterns = [
            "por qué dejaste", "debilidad", "fallaste",
            "why did you leave", "weakness", "failed",
            "error", "mistake", "conflicto", "conflict",
        ]
        
        for pattern in behavioral_patterns:
            if pattern in text_lower:
                return "behavioral"
        
        for pattern in technical_patterns:
            if pattern in text_lower:
                return "technical"
        
        for pattern in stress_patterns:
            if pattern in text_lower:
                return "stress"
        
        return "behavioral"  # Default
    
    async def _prefetch_evidence(self, text: str) -> list[EvidenceChunk]:
        """Pre-fetch evidence based on partial transcript"""
        chunks = []
        
        # Simple keyword matching for prefetch
        keywords = text.lower().split()[:10]
        
        # Check profile achievements
        for achievement in self.profile.achievements:
            achievement_lower = achievement.lower()
            if any(kw in achievement_lower for kw in keywords):
                chunks.append(EvidenceChunk(
                    text=achievement,
                    source="achievement",
                    relevance_score=0.5,
                ))
        
        # Check resume text
        if self.profile.resume_text:
            resume_sentences = self.profile.resume_text.split('.')[:20]
            for sentence in resume_sentences:
                if any(kw in sentence.lower() for kw in keywords):
                    chunks.append(EvidenceChunk(
                        text=sentence.strip(),
                        source="cv",
                        relevance_score=0.4,
                    ))
        
        return chunks[:5]  # Limit to 5 chunks
    
    async def _analyze_question(
        self, 
        question: str,
        lang_decision: LanguageDecision
    ) -> QuestionAnalysis:
        """Analyze the question using LLM"""
        
        prompt = f"""Analiza la siguiente pregunta de entrevista y extrae:
1. Tipo principal: behavioral, technical, situational, casual, follow_up, stress, compound
2. Si es compuesta, desglosa en sub-preguntas
3. Topics clave
4. Intent subyacente (qué busca realmente el entrevistador)
5. Red flags (qué evitar)
6. Estilo recomendado: executive, commercial, technical, mixed

PREGUNTA: {question}

IDIOMA: {lang_decision.final_language}

Responde en JSON con la estructura de QuestionAnalysis."""

        try:
            response = await self.llm.generate(
                messages=[{"role": "user", "content": prompt}],
                config={"temperature": 0.2, "max_tokens": 500}
            )
            
            # Parse response (simplified)
            # In production, use proper JSON parsing
            primary_type = self._quick_intent_classify(question)
            
            return QuestionAnalysis(
                primary_type=QuestionType(primary_type),
                is_compound="compound" in response.lower() or "y" in question.lower()[:50],
                key_topics=self._extract_topics(question),
                underlying_intent=["Evaluar experiencia y capacidad"],
                red_flags=[],
                recommended_style=ResponseStyle.MIXED,
                confidence=0.8,
            )
        except Exception as e:
            # Fallback to heuristics
            return QuestionAnalysis(
                primary_type=QuestionType(self._quick_intent_classify(question)),
                key_topics=self._extract_topics(question),
                recommended_style=ResponseStyle.MIXED,
            )
    
    def _extract_topics(self, text: str) -> list[str]:
        """Extract key topics from text"""
        # Simple keyword extraction
        stop_words = {"el", "la", "los", "las", "de", "que", "en", "un", "una", "es", "son", "the", "a", "an", "is", "are", "of", "to", "in"}
        words = text.lower().split()
        topics = [w for w in words if w not in stop_words and len(w) > 3]
        return list(set(topics))[:5]
    
    async def _retrieve_evidence(
        self, 
        analysis: QuestionAnalysis
    ) -> list[EvidenceChunk]:
        """Retrieve relevant evidence from profile"""
        # Use preloaded chunks as base
        evidence = list(self._preloaded_chunks)
        
        # Could add vector search here if embedding adapter is available
        
        return evidence[:5]
    
    def _assemble_context(
        self,
        question: str,
        analysis: QuestionAnalysis,
        evidence: list[EvidenceChunk],
    ) -> AssembledContext:
        """Assemble full context for response generation"""
        return AssembledContext(
            question=question,
            analysis=analysis,
            evidence=evidence,
            conversation_summary=self.tracker.get_summary(),
            topics_already_covered=self.tracker.map.topics_covered,
            metrics_already_used=self.tracker.map.metrics_used,
            style_config={"style": analysis.recommended_style.value},
            interview_config=self.config.model_dump(),
        )
    
    async def _generate_bullets(self, context: AssembledContext) -> GeneratedResponse:
        """Generate bullet points (fast, ~300ms target)"""
        style = get_style(
            context.analysis.recommended_style,
            context.analysis.primary_type
        )
        
        prompt = f"""Genera 3-5 bullets clave para responder esta pregunta de entrevista.

PREGUNTA: {context.question}

EVIDENCIA DEL PERFIL:
{chr(10).join(f'- {e.text}' for e in context.evidence[:3])}

MÉTRICAS YA USADAS (NO REPETIR):
{', '.join(context.metrics_already_used) if context.metrics_already_used else 'Ninguna'}

ESTILO: {style.name}

Responde SOLO con los bullets, uno por línea."""

        try:
            response = await self.llm.generate(
                messages=[{"role": "user", "content": prompt}],
                config={"temperature": 0.3, "max_tokens": 150}
            )
            
            bullets = [b.strip() for b in response.strip().split('\n') if b.strip() and not b.startswith('#')]
            
            return GeneratedResponse(
                bullets=bullets[:5],
                full_response="",
                style_used=context.analysis.recommended_style,
                confidence=0.7,
            )
        except Exception:
            return GeneratedResponse(
                bullets=["Prepara tu respuesta", "Menciona experiencia relevante", "Conecta con el rol"],
                style_used=ResponseStyle.EXECUTIVE,
            )
    
    async def _generate_full_response(self, context: AssembledContext) -> GeneratedResponse:
        """Generate full response (longer, ~500ms target)"""
        style = get_style(
            context.analysis.recommended_style,
            context.analysis.primary_type
        )
        
        prompt = style.get_prompt_template().format(
            language="español",
            question=context.question,
            evidence=chr(10).join(f'- {e.text}' for e in context.evidence[:5]),
            conversation_context=context.conversation_summary,
            metrics_used=', '.join(context.metrics_already_used) if context.metrics_already_used else 'Ninguna',
            company_context=f"{self.config.company_name} - {self.config.role_title}",
            technical_context=self.profile.resume_text or "Experiencia técnica variada",
        )
        
        try:
            response = await self.llm.generate(
                messages=[{"role": "user", "content": prompt}],
                config={"temperature": 0.3, "max_tokens": 300}
            )
            
            # Extract metrics from response
            metrics = self._extract_metrics_from_response(response)
            
            return GeneratedResponse(
                bullets=[],
                full_response=response,
                key_metrics=metrics,
                style_used=context.analysis.recommended_style,
                confidence=0.85,
            )
        except Exception:
            return GeneratedResponse(
                bullets=[],
                full_response="Prepara una respuesta conectando tu experiencia con el rol.",
                style_used=ResponseStyle.EXECUTIVE,
            )
    
    def _extract_metrics_from_response(self, text: str) -> list[str]:
        """Extract metrics from generated response"""
        import re
        metrics = []
        
        # Find percentages
        metrics.extend(re.findall(r'\d+%', text))
        
        # Find monetary values
        metrics.extend(re.findall(r'\$[\d,]+(?:k|K|M|m)?', text))
        
        # Find time periods
        metrics.extend(re.findall(r'\d+\s*(?:años?|years?|meses?|months?)', text, re.IGNORECASE))
        
        return metrics
    
    async def _repair_bullets(
        self, 
        response: GeneratedResponse,
        quality: QualityResult
    ) -> GeneratedResponse:
        """Repair bullets based on quality issues"""
        # Remove bullets with repeated metrics
        repaired_bullets = []
        
        for bullet in response.bullets:
            has_repeat = False
            for rep in quality.repetitions:
                if rep.lower() in bullet.lower():
                    has_repeat = True
                    break
            
            if not has_repeat:
                repaired_bullets.append(bullet)
        
        # If all bullets removed, add generic ones
        if not repaired_bullets:
            repaired_bullets = [
                "Enfócate en tu experiencia más relevante",
                "Menciona un logro cuantificable",
                "Conecta con las necesidades del rol",
            ]
        
        return GeneratedResponse(
            bullets=repaired_bullets,
            full_response=response.full_response,
            style_used=response.style_used,
            confidence=response.confidence * 0.9,
        )
