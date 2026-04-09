"""
Interview Coach - Realtime Pipeline
Orchestrates the full processing pipeline for interview coaching

Pipeline: 
  AudioReceiver → STTAdapter → TurnAssembler → LanguagePolicy 
  → QuestionAnalyzer → RetrievalPlanner → EvidenceRetriever 
  → ResponseComposer → QualityGate → Emitter
"""
import asyncio
from dataclasses import dataclass
from typing import Optional, Callable, Awaitable
from datetime import datetime
import time

from contracts.models import (
    SessionState,
    ConversationMap,
    Exchange,
    QuestionAnalysis,
    GeneratedResponse,
    QualityResult,
    LanguageDecision,
    AssembledContext,
    ResponseStyle,
    AskBrief,
)
from observability.latency import time_step, get_latency_tracker, PipelineLatency

# Pipeline steps
from pipeline.steps.turn_assembler import TurnAssembler, SpeakerTurn
from pipeline.steps.language_policy import LanguagePolicy
from pipeline.steps.question_analyzer import QuestionAnalyzer, AnalysisContext
from pipeline.steps.ask_normalizer import AskNormalizer, apply_ask_brief_policy
from pipeline.steps.live_question_planner import LiveQuestionPlanner
from pipeline.steps.retrieval_planner import RetrievalPlanner, RetrievalPlan
from pipeline.steps.evidence_retriever import EvidenceRetriever, MockEvidenceRetriever
from pipeline.steps.response_composer import ResponseComposer, MockResponseComposer
from pipeline.steps.quality_gate import QualityGate

# Conversation
from conversation.tracker import ConversationTracker

# Storage
from storage.session_repo import get_session_repository, SessionRepository


@dataclass
class PipelineConfig:
    """Configuration for the pipeline"""
    use_real_llm: bool = False
    use_real_stt: bool = False
    use_real_embeddings: bool = False
    silence_threshold_ms: int = 2500
    max_response_words: int = 250
    min_confidence: float = 0.7
    # Session persistence settings
    enable_session_persistence: bool = True
    auto_save_interval_turns: int = 3  # Save every N turns


@dataclass
class PipelineResult:
    """Result of processing a question"""
    exchange: Exchange
    language_decision: LanguageDecision
    question_analysis: QuestionAnalysis
    generated_response: GeneratedResponse
    quality_result: QualityResult
    total_latency_ms: int


class RealtimePipeline:
    """
    Main pipeline for processing interview questions.
    
    Flow:
    1. Receive transcript from STT/TurnAssembler
    2. Detect language
    3. Analyze question
    4. Plan retrieval
    5. Retrieve evidence
    6. Compose response
    7. Quality gate validation
    8. Emit to UI
    """
    
    def __init__(self, config: Optional[PipelineConfig] = None):
        self.config = config or PipelineConfig()
        
        # Initialize components
        self.turn_assembler = TurnAssembler(
            silence_threshold_ms=self.config.silence_threshold_ms
        )
        self.language_policy = LanguagePolicy()
        self.question_analyzer = QuestionAnalyzer(
            use_llm=self.config.use_real_llm
        )
        self.ask_normalizer = AskNormalizer()
        self.live_question_planner = LiveQuestionPlanner(self.ask_normalizer)
        self.retrieval_planner = RetrievalPlanner()
        self.evidence_retriever = (
            MockEvidenceRetriever()
            if not self.config.use_real_embeddings
            else EvidenceRetriever.from_environment()
        )
        self.response_composer = MockResponseComposer() if not self.config.use_real_llm else ResponseComposer()
        self.quality_gate = QualityGate()
        self.conversation_tracker = ConversationTracker()
        
        # Session state
        self.session_state: Optional[SessionState] = None
        self._exchange_index = 0
        
        # Latency tracking for pipeline stages
        self._latency = PipelineLatency()
        
        # Session repository for persistence (optional - may be unavailable)
        self._session_repo: Optional[SessionRepository] = None
        self._turns_since_last_save = 0
    
    async def start_session(
        self,
        session_id: str,
        interview_config: dict,
    ) -> SessionState:
        """Start a new interview session"""
        self.session_state = SessionState(
            session_id=session_id,
            interview_config=interview_config,
            conversation_map=ConversationMap(),
        )
        self._exchange_index = 0
        self.conversation_tracker.reset()
        self._turns_since_last_save = 0
        
        # Initialize session repository for persistence
        if self.config.enable_session_persistence:
            try:
                self._session_repo = get_session_repository()
                # Try to load existing session or create new one
                existing = await self._session_repo.get_session(session_id)
                if existing:
                    print(f"[SESSION] Loading existing session_id={session_id}")
                    # Load exchanges from DB and restore state
                    exchanges = await self._session_repo.get_exchanges(session_id)
                    print(f"[SESSION] Loaded {len(exchanges)} exchanges from DB")
                else:
                    # Create new session in DB
                    # Get config_id from interview_config, validate it's a valid UUID in interview_configs
                    config_id = interview_config.get("config_id")
                    if config_id:
                        # Validate config_id exists in database before using it
                        # For now, skip if config_id looks like a session_id (not a proper config UUID)
                        # This prevents FK constraint errors when session_id is mistakenly used as config_id
                        try:
                            await self._session_repo.create_session(config_id, "active")
                            print(f"[SESSION] Created new session_id={session_id} with config_id={config_id}")
                        except Exception as create_err:
                            print(f"[SESSION] Warning: Could not create session with config_id={config_id}: {create_err}")
                            # Continue without persistence - session will work in-memory only
                            self._session_repo = None
                    else:
                        # No config_id provided - skip DB persistence for this session
                        print(f"[SESSION] No config_id provided, running session without persistence")
            except Exception as e:
                print(f"[SESSION] Warning: Could not initialize session persistence: {e}")
                self._session_repo = None
        
        # Set language preference if specified
        lang_pref = interview_config.get("language_preference")
        if lang_pref and lang_pref != "auto":
            self.language_policy.user_preference = lang_pref
        
        return self.session_state
    
    supports_transcript_metadata = True

    async def process_question(
        self,
        question: str,
        is_final: bool = True,
        on_progress: Optional[Callable[[dict], Awaitable[None] | None]] = None,
        transcript_metadata: Optional[dict[str, str]] = None,
        context: Optional[list[dict]] = None,
        ask_brief_override: Optional[AskBrief] = None,
    ) -> PipelineResult:
        """
        Process an interviewer question through the full pipeline.
        
        Args:
            question: The interviewer's utterance
            is_final: Whether this is a final (complete) transcript
            context: Optional list of recent conversation turns for context
        
        Returns:
            PipelineResult with all processing results
        """
        start_time = datetime.now()
        perf_start = time.perf_counter()
        
        # Handle partial transcripts
        if not is_final:
            # Speculative processing: just analyze intent
            return await self._process_partial(question)
        
        # Start latency tracking for this exchange
        self._latency.start_exchange()
        
        with time_step("total_pipeline"):
            interview_config = self.session_state.interview_config if self.session_state else {}
            candidate_context = interview_config.get("candidate", {}) if isinstance(interview_config.get("candidate", {}), dict) else {}
            company_context = interview_config.get("company", {}) if isinstance(interview_config.get("company", {}), dict) else {}

            role_title = (
                interview_config.get("role_title")
                or company_context.get("positionTitle")
                or company_context.get("roleTitle")
                or ""
            )
            company_name = (
                interview_config.get("company_name")
                or company_context.get("companyName")
                or ""
            )
            job_description = (
                interview_config.get("job_description")
                or company_context.get("positionDescription")
                or company_context.get("companyDescription")
                or ""
            )

            # Step 1: Language Detection
            self._latency.start_stage("language_detection")
            language_decision = self.language_policy.decide(question)
            self._latency.end_stage("language_detection")
            
            if transcript_metadata:
                print(
                    "[PIPELINE][HANDOFF] metadata_received "
                    f"session_id={transcript_metadata.get('session_id', 'unknown')} "
                    f"transcript_id={transcript_metadata.get('transcript_id', 'unknown')} "
                    f"request_id={transcript_metadata.get('request_id', 'unknown')} "
                    f"language={transcript_metadata.get('language', 'unknown')} "
                    f"speaker={transcript_metadata.get('speaker', 'unknown')}"
                )

            # Convert recent turns before analysis so the analyzer sees the same live context.
            conversation_history = []
            if context:
                for turn in context:
                    speaker = turn.get('speaker', 'unknown')
                    text = turn.get('text', '')
                    if speaker == 'interviewer':
                        role = 'interviewer'
                    elif speaker == 'candidate':
                        role = 'candidate'
                    else:
                        role = speaker
                    conversation_history.append({
                        "role": role,
                        "content": text,
                    })
                print(f"[PIPELINE] Converted {len(context)} context turns to conversation_history")

            # Step 2: Question Analysis
            analysis_context = AnalysisContext(
                role_title=role_title,
                company_name=company_name,
                job_description=job_description,
                company_industry=company_context.get("industry", interview_config.get("company_industry", "")),
                company_description=company_context.get("companyDescription", interview_config.get("company_description", "")),
                company_requirements=company_context.get("positionRequirements", interview_config.get("company_requirements", [])) or [],
                company_culture=company_context.get("companyCulture", interview_config.get("company_culture", "")),
                candidate_summary=candidate_context.get("summary", interview_config.get("candidate_summary", "")),
                candidate_skills=candidate_context.get("skills", interview_config.get("candidate_skills", [])) or [],
                candidate_achievements=candidate_context.get("achievements", interview_config.get("candidate_achievements", [])) or [],
                candidate_certifications=candidate_context.get("certifications", interview_config.get("candidate_certifications", [])) or [],
                interview_type=interview_config.get("interview_type", "mixed"),
                conversation_history=conversation_history,
                topics_covered=self.session_state.conversation_map.topics_covered if self.session_state else [],
                metrics_used=self.session_state.conversation_map.metrics_used if self.session_state else [],
            )

            delivery_mode = str(interview_config.get("delivery_mode") or "realtime").strip().lower()
            if delivery_mode not in {"realtime", "manual", "live_manual"}:
                delivery_mode = "realtime"

            normalized_turns = [
                {
                    "speaker": turn.get("speaker", "unknown"),
                    "text": turn.get("text", ""),
                }
                for turn in (context or [])
            ]
            ask_brief = ask_brief_override or self.ask_normalizer.normalize(
                question,
                normalized_turns,
                delivery_mode=delivery_mode,
            )
            
            self._latency.start_stage("question_analysis")
            question_analysis = await self.question_analyzer.analyze(
                question, analysis_context
            )
            self._latency.end_stage("question_analysis")
            question_analysis = apply_ask_brief_policy(
                question_analysis,
                ask_brief,
                delivery_mode=delivery_mode,
                confidence_threshold=self.ask_normalizer.config.confidence_threshold,
            )
            print(
                "[LIVE][PIPELINE] analysis "
                f"question='{question[:160]}' "
                f"family={ask_brief.answer_family.value} "
                f"confidence={ask_brief.confidence:.2f} "
                f"fallback={ask_brief.fallback_used} "
                f"sub_questions={len(question_analysis.sub_questions)} "
                f"response_mode={question_analysis.response_mode.value} "
                f"style={question_analysis.recommended_style.value}"
            )
            if question_analysis.sub_questions:
                print(
                    "[LIVE][PIPELINE] sub_questions "
                    + " | ".join(
                        f"{idx+1}:{sq.priority.value}:{sq.text[:120]}"
                        for idx, sq in enumerate(question_analysis.sub_questions[:5])
                    )
                )

            if on_progress:
                analysis_payload = {
                    "type": "analysis",
                    "question_type": question_analysis.primary_type.value,
                    "question_mode": question_analysis.question_mode.value,
                    "response_mode": question_analysis.response_mode.value,
                    "answer_intent": question_analysis.answer_intent.value,
                    "is_compound": question_analysis.is_compound,
                    "sub_questions": [
                        {
                            "text": sq.text,
                            "priority": sq.priority.value,
                            "weight": sq.weight,
                        }
                        for sq in question_analysis.sub_questions
                    ],
                    "underlying_intent": question_analysis.underlying_intent,
                    "red_flags": question_analysis.red_flags,
                    "normalized_family": ask_brief.answer_family.value,
                    "normalized_primary_ask": ask_brief.primary_ask,
                    "normalized_secondary_asks": ask_brief.secondary_asks,
                    "normalized_answer_contract": ask_brief.answer_contract.value,
                    "normalized_metrics_policy": ask_brief.metrics_policy.value,
                    "normalizer_confidence": ask_brief.confidence,
                    "normalizer_latency_ms": ask_brief.latency_ms,
                    "fallback_used": ask_brief.fallback_used,
                }
                maybe_coroutine = on_progress(analysis_payload)
                if hasattr(maybe_coroutine, "__await__"):
                    await maybe_coroutine
            
            # Step 3: Retrieval Planning
            self._latency.start_stage("retrieval_planning")
            retrieval_plan = self.retrieval_planner.plan(
                question_analysis,
                analysis_context.role_title,
                analysis_context.company_name,
                candidate_skills=analysis_context.candidate_skills,
                company_requirements=analysis_context.company_requirements,
                candidate_summary=analysis_context.candidate_summary,
                company_context_id=interview_config.get("company_context_id", ""),
                interviewer_context_id=interview_config.get("interviewer_context_id", ""),
            )
            self._latency.end_stage("retrieval_planning")
            
            # Step 4: Evidence Retrieval
            self._latency.start_stage("evidence_retrieval")
            evidence = await self.evidence_retriever.retrieve(retrieval_plan)
            self._latency.end_stage("evidence_retrieval")
            
            # Step 5: Response Composition (bullets-first)
            self._latency.start_stage("response_composition")
            
            # NEW: Extract max_words from interview_config or use default
            max_words = interview_config.get("max_words", 200)
            
            assembled_context = AssembledContext(
                question=question,
                analysis=question_analysis,
                ask_brief=ask_brief,
                evidence=evidence,
                conversation_summary=self.session_state.conversation_map.summary if self.session_state else "",
                conversation_history=conversation_history,  # HR-2: Pass conversation history
                topics_already_covered=analysis_context.topics_covered,
                metrics_already_used=analysis_context.metrics_used,
                achievements_referenced=analysis_context.candidate_achievements,
                style_config={
                    "response_style": interview_config.get("response_style", "mixed"),
                    "language_preference": interview_config.get("language_preference", "auto"),
                },
                interview_config=interview_config,
                delivery_mode=delivery_mode,
                max_words=max_words,  # NEW: Length control
            )

            tracker = get_latency_tracker()
            bullets_quality_result: Optional[QualityResult] = None
            bullets_preview_response: Optional[GeneratedResponse] = None
            time_to_bullets_ms: Optional[int] = None

            async def _emit_bullets_preview(preview: GeneratedResponse):
                nonlocal bullets_quality_result, bullets_preview_response, time_to_bullets_ms

                bullets_preview_response, bullets_quality_result = await self.quality_gate.process_bullets(
                    preview,
                    question_analysis,
                    self.session_state.conversation_map if self.session_state else None,
                    language_decision.final_language,
                )

                time_to_bullets_ms = int((time.perf_counter() - perf_start) * 1000)
                tracker.record("time_to_bullets", float(time_to_bullets_ms))
                self._latency.record_first_bullet(float(time_to_bullets_ms))

                preview_full_response = self._build_realtime_preview_response(
                    bullets_preview_response.bullets,
                    question_analysis,
                )

                if on_progress:
                    progress_payload = {
                        "type": "suggestion",
                        "stage": "bullets",
                        "mode": bullets_preview_response.mode,
                        "full_response": preview_full_response,
                        "bullets_preview": bullets_preview_response.bullets,
                        "bullets": bullets_preview_response.bullets,
                        "key_metrics": bullets_preview_response.key_metrics,
                        "confidence": bullets_preview_response.confidence,
                        "style": bullets_preview_response.style_used.value,
                        "language": language_decision.final_language,
                        "quality_passed": bullets_quality_result.passed,
                        "quality_score": bullets_quality_result.score,
                        "quality_issues": bullets_quality_result.issues,
                        "latency_ms": time_to_bullets_ms,
                        "processing_full_response": True,
                        "bullets_latency_ms": time_to_bullets_ms,
                        "time_to_first_answer_ms": time_to_bullets_ms,
                        "delivery_mode": delivery_mode,
                        "answer_intent": question_analysis.answer_intent.value,
                        "context_turns_used": len(context or []),
                        "normalized_family": ask_brief.answer_family.value,
                        "normalized_primary_ask": ask_brief.primary_ask,
                        "normalized_secondary_asks": ask_brief.secondary_asks,
                        "normalized_answer_contract": ask_brief.answer_contract.value,
                        "normalized_metrics_policy": ask_brief.metrics_policy.value,
                        "normalizer_confidence": ask_brief.confidence,
                        "normalizer_latency_ms": ask_brief.latency_ms,
                        "fallback_used": ask_brief.fallback_used,
                    }
                    maybe_coroutine = on_progress(progress_payload)
                    if hasattr(maybe_coroutine, "__await__"):
                        await maybe_coroutine

            generated_response = await self.response_composer.compose(
                assembled_context,
                on_bullets=_emit_bullets_preview,
            )
            self._latency.end_stage("response_composition")

            # Step 6: Quality Gate
            self._latency.start_stage("quality_gate")
            final_response, quality_result = await self.quality_gate.process(
                generated_response,
                question_analysis,
                self.session_state.conversation_map if self.session_state else None,
                language_decision.final_language,
            )
            self._latency.end_stage("quality_gate")

            total_latency_so_far = int((time.perf_counter() - perf_start) * 1000)
            tracker.record("time_to_full", float(total_latency_so_far))
            self._latency.record_full_response(float(total_latency_so_far))

            if time_to_bullets_ms is not None:
                print(
                    f"[Pipeline][Latency] question_ms bullets={time_to_bullets_ms} full={total_latency_so_far}"
                )

            final_response.metadata = {
                **(final_response.metadata or {}),
                "time_to_bullets_ms": time_to_bullets_ms if time_to_bullets_ms is not None else total_latency_so_far,
                "time_to_full_ms": total_latency_so_far,
                "time_to_first_answer_ms": time_to_bullets_ms if time_to_bullets_ms is not None else total_latency_so_far,
                "time_to_refined_answer_ms": total_latency_so_far,
                "delivery_mode": delivery_mode,
                "answer_intent": question_analysis.answer_intent.value,
                "context_turns_used": len(context or []),
                "normalized_family": ask_brief.answer_family.value,
                "normalized_primary_ask": ask_brief.primary_ask,
                "normalized_secondary_asks": ask_brief.secondary_asks,
                "normalized_answer_contract": ask_brief.answer_contract.value,
                "normalized_metrics_policy": ask_brief.metrics_policy.value,
                "normalizer_confidence": ask_brief.confidence,
                "normalizer_latency_ms": ask_brief.latency_ms,
                "fallback_used": ask_brief.fallback_used,
                "bullets_quality_passed": bullets_quality_result.passed if bullets_quality_result else None,
                "bullets_quality_score": bullets_quality_result.score if bullets_quality_result else None,
                "bullets_preview_count": len(bullets_preview_response.bullets) if bullets_preview_response else 0,
            }
            
            # Step 7: Create Exchange
            exchange = Exchange(
                index=self._exchange_index,
                timestamp=datetime.now(),
                interviewer_utterance=question,
                language_detected=language_decision.final_language,
                analysis=question_analysis,
                suggested_response=final_response,
                quality=quality_result,
                latency_ms=int((datetime.now() - start_time).total_seconds() * 1000),
            )

            if transcript_metadata:
                try:
                    exchange.model_extra = {
                        **(exchange.model_extra or {}),
                        "transcript_metadata": transcript_metadata,
                    }
                except Exception:
                    pass
            
            # Step 8: Update conversation tracker
            self.conversation_tracker.record_exchange(exchange, question_analysis)
            self._exchange_index += 1
            
            # Update session state
            if self.session_state:
                self.session_state.exchanges.append(exchange)
                self.session_state.conversation_map = self.conversation_tracker.get_map()
            
            # Step 9: Persist exchange to session repository (if available)
            await self._persist_exchange(exchange, question_analysis, final_response, quality_result)
            
            # Record language decision
            self.language_policy.record_exchange(language_decision.final_language)
            
            total_latency = int((datetime.now() - start_time).total_seconds() * 1000)
            
            return PipelineResult(
                exchange=exchange,
                language_decision=language_decision,
                question_analysis=question_analysis,
                generated_response=final_response,
                quality_result=quality_result,
                total_latency_ms=total_latency,
            )
    

    def _build_realtime_preview_response(
        self,
        bullets: list[str],
        question_analysis: QuestionAnalysis,
    ) -> str:
        """Turn preview bullets into a short, interview-usable first answer."""
        cleaned = [bullet.replace("•", "").strip() for bullet in bullets if bullet and bullet.strip()]
        if not cleaned:
            return ""

        if question_analysis.response_mode.value == "hybrid_dual":
            lead = cleaned[0]
            rest = cleaned[1:3]
            body = " ".join(rest)
            if body:
                return f"Technical answer: {lead}.\n\nHow to say it in the interview: {body}."
            return f"Technical answer: {lead}."

        sentences = []
        for bullet in cleaned[:3]:
            sentence = bullet
            if sentence and sentence[-1] not in ".!?":
                sentence += "."
            sentences.append(sentence)
        return " ".join(sentences)

    async def _process_partial(self, partial: str) -> PipelineResult:
        """Process a partial transcript (speculative)"""
        # Just do quick language detection and intent classification
        language_decision = self.language_policy.decide(partial)
        
        # Return minimal result for partial
        return PipelineResult(
            exchange=Exchange(
                index=self._exchange_index,
                interviewer_utterance=partial,
                language_detected=language_decision.final_language,
            ),
            language_decision=language_decision,
            question_analysis=QuestionAnalysis(primary_type=QuestionAnalysis.__annotations__['primary_type'].__args__[0].BEHAVIORAL),
            generated_response=GeneratedResponse(
                bullets=[],
                full_response="",
                key_metrics=[],
                confidence=0.0,
                style_used=ResponseStyle.EXECUTIVE,
            ),
            quality_result=QualityResult(
                passed=False,
                score=0.0,
                issues=["Partial transcript - awaiting final"],
            ),
            total_latency_ms=0,
        )
    
    def _get_question_history(self) -> list[str]:
        """Get history of questions asked"""
        if not self.session_state or not self.session_state.exchanges:
            return []
        return [e.interviewer_utterance for e in self.session_state.exchanges[-3:]]
    
    async def end_session(self) -> dict:
        """End the current session and return summary"""
        if not self.session_state:
            return {}
        
        summary = {
            "session_id": self.session_state.session_id,
            "total_exchanges": len(self.session_state.exchanges),
            "topics_covered": self.session_state.conversation_map.topics_covered,
            "metrics_used": self.session_state.conversation_map.metrics_used,
            "gaps": self.session_state.conversation_map.uncovered_gaps,
            "interviewer_values": self.session_state.conversation_map.interviewer_values,
            "warnings": self.session_state.conversation_map.warnings,
        }
        
        # Log latency summary for session
        latency_summary = self._latency.get_summary()
        if latency_summary.get("total_exchanges", 0) > 0:
            print(f"[SESSION][LATENCY] Session latency summary:")
            print(f"  Total exchanges: {latency_summary['total_exchanges']}")
            print(f"  First bullet - avg: {latency_summary['first_bullet']['avg']:.1f}ms, "
                  f"min: {latency_summary['first_bullet']['min']:.1f}ms, "
                  f"max: {latency_summary['first_bullet']['max']:.1f}ms")
            print(f"  Full response - avg: {latency_summary['full_response']['avg']:.1f}ms, "
                  f"min: {latency_summary['full_response']['min']:.1f}ms, "
                  f"max: {latency_summary['full_response']['max']:.1f}ms")
            print(f"  Target achievement:")
            print(f"    Bullets < 8s: {latency_summary['targets']['bullets_under_8s_pct']:.1f}%")
            print(f"    Full < 15s: {latency_summary['targets']['full_under_15s_pct']:.1f}%")
            
            # Log per-stage stats
            for stage, stats in latency_summary.get("stages", {}).items():
                if stats.get("count", 0) > 0:
                    print(f"  Stage '{stage}' - avg: {stats['avg']:.1f}ms, "
                          f"min: {stats['min']:.1f}ms, max: {stats['max']:.1f}ms")
        
        summary["latency_summary"] = latency_summary
        
        # End session in repository if available
        if self._session_repo and self.session_state:
            try:
                await self._session_repo.end_session(
                    self.session_state.session_id,
                    summary
                )
                print(f"[SESSION] Ended session_id={self.session_state.session_id}")
            except Exception as e:
                print(f"[SESSION] Warning: Could not end session: {e}")
        
        self.session_state.status = "ended"
        return summary
    
    async def _persist_exchange(
        self,
        exchange: Exchange,
        question_analysis: QuestionAnalysis,
        suggested_response: GeneratedResponse,
        quality_result: QualityResult,
    ) -> None:
        """Persist exchange to session repository if available"""
        if not self._session_repo or not self.session_state:
            return
        
        self._turns_since_last_save += 1
        
        try:
            # Extract serializable data from question analysis
            qa_dict = {
                "primary_type": question_analysis.primary_type.value,
                "is_compound": question_analysis.is_compound,
                "underlying_intent": question_analysis.underlying_intent,
                "key_topics": question_analysis.key_topics,
                "red_flags": question_analysis.red_flags,
            }
            
            # Extract serializable data from suggested response
            sr_dict = {
                "bullets": suggested_response.bullets,
                "full_response": suggested_response.full_response,
                "key_metrics": suggested_response.key_metrics,
                "confidence": suggested_response.confidence,
                "style_used": suggested_response.style_used.value,
            }
            
            # Extract serializable data from quality result
            qr_dict = {
                "passed": quality_result.passed,
                "score": quality_result.score,
                "issues": quality_result.issues,
            }
            
            # Create exchange in DB
            exchange_id = await self._session_repo.create_exchange(
                session_id=self.session_state.session_id,
                index=exchange.index,
                interviewer_utterance=exchange.interviewer_utterance,
                language_detected=exchange.language_detected,
                question_analysis=qa_dict,
                suggested_response=sr_dict,
                quality_result=qr_dict,
                latency_ms=exchange.latency_ms,
            )
            
            print(f"[SESSION] Saved exchange_id={exchange_id} for session_id={self.session_state.session_id}")
            
            # Auto-save every N turns
            if self._turns_since_last_save >= self.config.auto_save_interval_turns:
                print(f"[SESSION] Auto-save checkpoint for session_id={self.session_state.session_id}")
                self._turns_since_last_save = 0
                
        except Exception as e:
            print(f"[SESSION] Warning: Could not persist exchange: {e}")
            # Don't fail the pipeline if DB write fails
    
    def get_latency_stats(self) -> dict:
        """Get latency statistics for all pipeline steps"""
        tracker = get_latency_tracker()
        return tracker.get_all_stats()


# Unit tests
if __name__ == "__main__":
    import asyncio
    
    async def test():
        pipeline = RealtimePipeline()
        
        # Start session
        await pipeline.start_session(
            "test-session",
            {
                "company_name": "TechCorp",
                "role_title": "CTO",
                "language_preference": "auto",
            }
        )
        
        # Process question
        result = await pipeline.process_question(
            "Tell me about your leadership experience"
        )
        
        print(f"Language: {result.language_decision.final_language}")
        print(f"Type: {result.question_analysis.primary_type}")
        print(f"Bullets: {result.exchange.suggested_response.bullets}")
        print(f"Quality passed: {result.quality_result.passed}")
        print(f"Latency: {result.total_latency_ms}ms")
        
        # End session
        summary = await pipeline.end_session()
        print(f"\nSession summary: {summary}")
    
    asyncio.run(test())
