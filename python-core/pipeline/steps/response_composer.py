"""
Interview Coach - Response Composer
Generates interview responses using LLM

## IMPLEMENTATION STATUS (C7 Audit)

**CURRENT STATE: REAL MODE ONLY - DEMO FALLBACK DISABLED**

CRITICAL: Demo mode has been DISABLED to prevent fake CV data generation.
The system now ONLY uses real LLM calls with real CV context.

Mode behavior:
- **REAL MODE** (default): Uses LLM adapter (Claude/OpenAI) for generation
- **DEMO MODE**: DISABLED - returns error message instead of fake data
- **AUTO MODE**: Tries REAL, errors if no API key (no fallback to demo)

Requirements for operation:
1. Set `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` environment variable
2. Ensure LLM adapter is configured in `config/providers.yaml`
3. CV must be uploaded and stored in database with embeddings

If LLM fails or no API key is configured, the system returns an error
message instead of generating fake responses.

## Response Styles

### Executive
- Structure: Action → Method → Result with metrics
- Length: 150-220 words
- Tone: Professional, confident

### Commercial  
- Structure: Need → Proof → Value → Close
- Length: 150-200 words
- Tone: Persuasive, business-focused

### Technical
- Structure: Problem → Analysis → Solution → Outcome
- Length: 180-250 words
- Tone: Technical depth with business context

### Mixed (Adaptive)
- Auto-selects based on question type
- Blends styles for compound questions
"""
from typing import Optional, Callable, Awaitable
from dataclasses import dataclass
from enum import Enum
import os
import re
import time

from contracts.models import (
    AssembledContext,
    GeneratedResponse,
    ResponseStyle,
    ComplexityClass,
    AnswerShape,
)


def _compact_text(text: str, limit: int = 240) -> str:
    collapsed = re.sub(r"\s+", " ", text or "").strip()
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 3].rstrip() + "..."


class ComposerMode(str, Enum):
    """Response composer operation mode"""
    DEMO = "demo"  # Returns mock responses
    REAL = "real"  # Uses LLM
    AUTO = "auto"  # Tries real, falls back to demo


@dataclass
class ComposerStatus:
    """Status of the response composer"""
    mode: ComposerMode
    api_key_configured: bool
    provider: Optional[str]
    message: str


class ResponseComposer:
    """
    Composes interview responses using LLM.
    
    In REAL mode, generates responses using Claude/OpenAI.
    In DEMO mode, returns mock responses for testing.
    """
    
    @staticmethod
    def from_environment() -> "ResponseComposer":
        """
        Construct composer using RESPONSE_COMPOSER_MODE env var.
        Supported values: real | auto (default: real).
        
        CRITICAL: Demo mode is disabled. If 'demo' is specified,
        it will be treated as 'real' mode.
        
        Returns:
            ResponseComposer configured for real LLM only
        """
        mode_raw = os.getenv("RESPONSE_COMPOSER_MODE", "real").strip().lower()
        if mode_raw == "demo":
            print("[ResponseComposer] WARNING: Demo mode requested but disabled. Using REAL mode.")
            mode = ComposerMode.REAL
        elif mode_raw == "auto":
            mode = ComposerMode.AUTO
        else:
            # Default to REAL mode
            mode = ComposerMode.REAL
        
        return ResponseComposer(mode=mode, use_llm=True)
    
    def __init__(
        self,
        mode: ComposerMode = ComposerMode.AUTO,
        use_llm: bool = True,
    ):
        """
        Initialize response composer.
        
        Args:
            mode: Operation mode (AUTO, DEMO, REAL)
            use_llm: If True, attempt to use LLM (respects mode)
        """
        self.mode = mode
        self.use_llm = use_llm
        self._api_checked = False
        self._api_available = False
        self._provider = None

    @staticmethod
    def _debug_logging_enabled() -> bool:
        return os.getenv("RESPONSE_COMPOSER_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}
    
    def _check_api_availability(self) -> bool:
        """Check if LLM API is available"""
        if self._api_checked:
            return self._api_available
        
        # First check runtime config (includes Ollama detection)
        try:
            from adapters.llm_adapter import get_llm_adapter
            adapter = get_llm_adapter()
            if adapter is not None:
                # Determine provider from adapter type
                adapter_class = type(adapter).__name__
                if "Ollama" in adapter_class:
                    self._provider = "ollama"
                elif "Anthropic" in adapter_class:
                    self._provider = "anthropic"
                elif "OpenAI" in adapter_class:
                    self._provider = "openai"
                self._api_available = True
                self._api_checked = True
                return True
        except Exception:
            pass
        
        # Fall back to environment variables
        if os.getenv("ANTHROPIC_API_KEY"):
            self._api_available = True
            self._provider = "anthropic"
        elif os.getenv("OPENAI_API_KEY"):
            self._api_available = True
            self._provider = "openai"
        else:
            self._api_available = False
            self._provider = None
        
        self._api_checked = True
        return self._api_available
    
    def get_status(self) -> ComposerStatus:
        """Get current composer status"""
        if self.mode == ComposerMode.DEMO:
            return ComposerStatus(
                mode=ComposerMode.DEMO,
                api_key_configured=self._api_available,
                provider=self._provider,
                message="Demo mode - returning mock responses",
            )
        
        if self.mode == ComposerMode.REAL:
            if self._api_available:
                return ComposerStatus(
                    mode=ComposerMode.REAL,
                    api_key_configured=True,
                    provider=self._provider,
                    message=f"Real mode - using {self._provider} LLM",
                )
            else:
                return ComposerStatus(
                    mode=ComposerMode.REAL,
                    api_key_configured=False,
                    provider=None,
                    message="Real mode requested but no API key configured",
                )
        
        # AUTO mode
        if self._api_available:
            return ComposerStatus(
                mode=ComposerMode.REAL,
                api_key_configured=True,
                provider=self._provider,
                message=f"Auto mode - using {self._provider} LLM",
            )
        else:
            return ComposerStatus(
                mode=ComposerMode.DEMO,
                api_key_configured=False,
                provider=None,
                message="Auto mode - using demo (no API key)",
            )
    
    async def compose(
        self,
        context: AssembledContext,
        on_bullets: Optional[Callable[[GeneratedResponse], Awaitable[None] | None]] = None,
    ) -> GeneratedResponse:
        """
        Generate a response from context.
        
        In REAL mode: Uses LLM adapter for generation.
        In DEMO mode: Returns mock response built from evidence.
        
        IMPORTANT: Context Gate - If no evidence is available, we return
        a safe fallback to prevent hallucination. The LLM should never
        generate specific details (numbers, dates, achievements) without
        evidence from the CV.
        """
        # Check API availability
        self._check_api_availability()
        
        # CONTEXT GATE: Check if we have evidence to ground the response
        has_evidence = context.evidence and len(context.evidence) > 0
        evidence_count = len(context.evidence) if context.evidence else 0

        # Check if cv_text is available as fallback grounding context
        _ic = context.interview_config or {}
        _cc = _ic.get("candidate", {}) if isinstance(_ic.get("candidate", {}), dict) else {}
        _ip = _ic.get("interviewer", {}) if isinstance(_ic.get("interviewer", {}), dict) else {}
        has_cv_text = bool(
            _ic.get("cv_text") or _cc.get("cv_text") or _cc.get("cvText") or _ic.get("cvText")
        )
        
        if self._debug_logging_enabled():
            print(f"[ResponseComposer] === COMPOSE START ===")
            print(f"[ResponseComposer] Question: {context.question[:80] if context.question else 'None'}...")
            print(f"[ResponseComposer] Evidence count: {evidence_count}")
            print(f"[ResponseComposer] Has cv_text fallback: {has_cv_text}")
            print(f"[ResponseComposer] API available: {self._api_available}")
            print(f"[ResponseComposer] Mode: {self.mode}")
            print(f"[ResponseComposer] Conversation history: {len(context.conversation_history)} turns")
            if context.conversation_history:
                for i, turn in enumerate(context.conversation_history[-3:]):
                    print(f"[ResponseComposer] History[{i}]: {turn.get('speaker', 'unknown')}: {turn.get('text', '')[:50]}...")

            if context.evidence:
                for i, ev in enumerate(context.evidence[:3]):
                    print(f"[ResponseComposer] Evidence[{i}]: {ev.text[:60] if ev.text else 'Empty'}...")
                    print(f"[ResponseComposer]   Source: {ev.source}, Score: {ev.relevance_score}")
        
        if not has_evidence and not has_cv_text:
            # Generate safe fallback response when no evidence AND no cv_text is available
            # This prevents hallucination of specific details
            print("[ResponseComposer] ⚠️ WARNING: No evidence and no cv_text found in context!")
            print("[ResponseComposer] Returning safe fallback to prevent hallucination")
            
            # Get candidate summary for general context (safe to use)
            interview_config = context.interview_config or {}
            candidate_context = interview_config.get("candidate", {}) if isinstance(interview_config.get("candidate", {}), dict) else {}
            interviewer_context = interview_config.get("interviewer", {}) if isinstance(interview_config.get("interviewer", {}), dict) else {}
            candidate_name = interview_config.get("candidate_name") or candidate_context.get("name") or "the candidate"
            candidate_summary = interview_config.get("candidate_summary") or candidate_context.get("summary") or ""
            company_name = interview_config.get("company_name") or ""
            role_title = interview_config.get("role_title") or ""
            interviewer_name = interviewer_context.get("name") or ""
            
            # Build a safe, generic response that doesn't claim specific details
            safe_fallback_bullets = [
                "• I can discuss my general experience and background",
                "• I can speak to my skills and qualifications",
                "• I'd like to ensure I'm sharing accurate information",
            ]
            
            if candidate_summary:
                safe_fallback_text = (
                    f"I don't have specific details about that in my CV stored for this session. "
                    f"I can discuss my general experience: {candidate_summary[:100]}... "
                    f"Would you like me to focus on a specific area of my background?"
                )
            else:
                safe_fallback_text = (
                    f"I don't have specific information about that in my CV. "
                    f"To give you an accurate answer, could you clarify which role or experience you're asking about? "
                    f"I want to ensure I share only verified details from my actual experience."
                )
            
            # Emit bullets if callback provided
            if on_bullets:
                await self._emit_bullets(
                    on_bullets,
                    GeneratedResponse(
                        bullets=safe_fallback_bullets,
                        full_response="",
                        key_metrics=[],
                        confidence=0.1,  # Low confidence - no evidence
                        style_used=ResponseStyle.EXECUTIVE,
                        generation_time_ms=1,
                        mode="safe_fallback",
                        metadata={
                            "composer_status": "no_evidence_fallback",
                            "evidence_count": 0,
                            "warning": "Generated safe fallback - no evidence available",
                            "candidate_name": candidate_name,
                            "interviewer_name": interviewer_name,
                        },
                    ),
                )
            
            style = context.analysis.recommended_style if context.analysis else ResponseStyle.EXECUTIVE
            
            return GeneratedResponse(
                bullets=safe_fallback_bullets,
                full_response=safe_fallback_text,
                key_metrics=[],
                confidence=0.1,  # Low confidence - no evidence
                style_used=style,
                generation_time_ms=1,
                mode="safe_fallback",
                metadata={
                    "composer_status": "no_evidence_fallback",
                    "evidence_count": 0,
                    "warning": "Generated safe fallback - no evidence available",
                    "candidate_name": candidate_name,
                    "company_name": company_name,
                    "role_title": role_title,
                    "interviewer_name": interviewer_name,
                },
            )
        
        # Determine which implementation to use
        status = self.get_status()
        
        # CRITICAL: Demo mode is disabled - always use real LLM
        if status.mode == ComposerMode.DEMO:
            print("[ResponseComposer] WARNING: Demo mode was requested but is DISABLED")
            print("[ResponseComposer] Attempting real LLM call instead...")
            response = await self._compose_real(context, on_bullets=on_bullets)
        else:
            response = await self._compose_real(context, on_bullets=on_bullets)

        # P4-T1: ensure full_response is always populated before emit.
        final_response = self._ensure_full_response(context, response)
        
        if self._debug_logging_enabled():
            print(f"[ResponseComposer] === COMPOSE END ===")
            print(f"[ResponseComposer] Response mode: {final_response.mode}")
            print(f"[ResponseComposer] Response confidence: {final_response.confidence}")
            print(f"[ResponseComposer] Response length: {len(final_response.full_response) if final_response.full_response else 0} chars")
            print(f"[ResponseComposer] Bullets count: {len(final_response.bullets) if final_response.bullets else 0}")
        
        return final_response

    async def _compose_demo(
        self,
        context: AssembledContext,
        on_bullets: Optional[Callable[[GeneratedResponse], Awaitable[None] | None]] = None,
    ) -> GeneratedResponse:
        """
        DEPRECATED: Demo composition is disabled to prevent fake data generation.
        
        This method now returns a safe fallback message instead of mock responses.
        Never generate fake CV details - always use real LLM with real context.
        """
        style = context.analysis.recommended_style if context.analysis else ResponseStyle.EXECUTIVE
        
        # Safe fallback message - never invent fake metrics
        safe_bullets = [
            "• Unable to generate response - demo mode is disabled",
            "• Please ensure API keys are configured for real LLM generation",
            "• CV context must be loaded from database, not mock data",
        ]
        
        safe_response = (
            "I don't have access to my CV details at the moment. "
            "The system is configured to only use real data from my actual CV. "
            "Please ensure the API is properly configured and my CV has been uploaded."
        )
        
        # Emit safe bullets if callback provided
        if on_bullets:
            await self._emit_bullets(
                on_bullets,
                GeneratedResponse(
                    bullets=safe_bullets,
                    full_response="",
                    key_metrics=[],
                    confidence=0.0,
                    style_used=style,
                    generation_time_ms=1,
                    mode="error",
                    metadata={
                        "composer_status": "demo_mode_disabled",
                        "stage": "bullets",
                        "time_to_bullets_ms": 1,
                        "error": "Demo mode is disabled - real LLM required",
                    },
                ),
            )
        
        return GeneratedResponse(
            bullets=safe_bullets,
            full_response=safe_response,
            key_metrics=[],
            confidence=0.0,
            style_used=style,
            generation_time_ms=1,
            mode="error",
            metadata={
                "composer_status": "demo_mode_disabled",
                "evidence_count": len(context.evidence),
                "api_available": self._api_available,
                "stage": "full",
                "time_to_bullets_ms": 1,
                "time_to_full_ms": 1,
                "error": "Demo mode is disabled - configure ANTHROPIC_API_KEY or OPENAI_API_KEY",
            },
        )

    async def _compose_real(
        self,
        context: AssembledContext,
        on_bullets: Optional[Callable[[GeneratedResponse], Awaitable[None] | None]] = None,
    ) -> GeneratedResponse:
        """
        Real composition using LLM.
        
        This requires:
        1. ANTHROPIC_API_KEY or OPENAI_API_KEY configured
        2. LLM adapter available
        
        Returns mode='real' when successful, mode='fallback' when
        falling back to demo due to errors.
        """
        style = context.analysis.recommended_style if context.analysis else ResponseStyle.EXECUTIVE
        llm_alias = str((context.interview_config or {}).get("llm_alias", "main"))
        
        try:
            # Import LLM adapter - use required version for explicit error handling
            from adapters.llm_adapter import get_llm_adapter_required, DemoLLMAdapter
            
            # Get adapter - raises ValueError if no config available
            adapter = get_llm_adapter_required(alias=llm_alias)
            
            # Check if we got a real adapter or demo - should not happen with _required version
            if isinstance(adapter, DemoLLMAdapter):
                # This should not happen with get_llm_adapter_required, but handle gracefully
                print(f"[ResponseComposer] No real LLM adapter available for alias={llm_alias}; using demo mode")
                response = await self._compose_demo(context, on_bullets=on_bullets)
                response.mode = "demo"
                response.metadata["composer_status"] = "no_api_keys"
                response.metadata["llm_alias"] = llm_alias
                return response

            adapter_class = adapter.__class__.__name__.lower()
            provider_name = self._provider
            if not provider_name:
                if "anthropic" in adapter_class:
                    provider_name = "anthropic"
                elif "openai" in adapter_class:
                    provider_name = "openai"
            if provider_name:
                self._provider = provider_name
            model_name = getattr(adapter, "model", None)
            
            prefer_structured_output = on_bullets is not None

            # Build prompt based on style
            prompt = self._build_prompt(
                context,
                style,
                prefer_structured_output=prefer_structured_output,
            )
            
            # Build messages for the LLM
            messages = [
                {"role": "system", "content": self._get_system_prompt(style)},
                {"role": "user", "content": prompt}
            ]
            
            if self._debug_logging_enabled():
                print("\n" + "="*80)
                print("[DEBUG][RESPONSE_COMPOSER] FULL LLM REQUEST")
                print("="*80)
                print(f"\n[DEBUG] Conversation History ({len(context.conversation_history)} messages):")
                for i, msg in enumerate(context.conversation_history):
                    role = msg.get('role', 'unknown')
                    content = msg.get('content', '')
                    print(f"  [{i}] {role.upper()}: {content[:100]}{'...' if len(content) > 100 else ''}")
                print(f"\n[DEBUG] Question: {context.question}")
                print(f"\n[DEBUG] System Prompt:\n{self._get_system_prompt(style)[:500]}...")
                print(f"\n[DEBUG] User Prompt (first 1000 chars):\n{prompt[:1000]}...")
                print("="*80 + "\n")
            
            # Calculate max_tokens from max_words with a smaller buffer when preview bullets are disabled.
            max_words = getattr(context, 'max_words', 200)
            output_buffer = 200 if prefer_structured_output else 120
            calculated_max_tokens = min(int(max_words * 2) + output_buffer, 8192)
            
            # Get config from provider registry
            config = {
                "temperature": 0.7,
                "max_tokens": calculated_max_tokens,  # Use calculated value instead of hardcoded 1024
            }
            try:
                from adapters.provider_registry import get_registry

                llm_cfg = get_registry().get_llm_config(alias=llm_alias)
                llm_cfg_values = llm_cfg.config or {}
                # Use calculated max_tokens as priority, only use registry if explicitly set
                # This ensures responses are not truncated due to low max_tokens in config
                config["temperature"] = llm_cfg_values.get("temperature", config["temperature"])
                # Only use registry max_tokens if it's higher than calculated (never override with lower)
                registry_max_tokens = llm_cfg_values.get("max_tokens", 0)
                if registry_max_tokens > calculated_max_tokens:
                    config["max_tokens"] = registry_max_tokens

                # Get model from adapter (which uses runtime_config as source of truth)
                # Only use registry model if adapter doesn't have one
                if not model_name and llm_cfg.model:
                    model_name = llm_cfg.model
                
                # Determine provider from actual adapter type (not registry config)
                # This ensures we use the correct provider even if registry has wrong info
                if adapter is not None:
                    adapter_class = type(adapter).__name__
                    if "Ollama" in adapter_class:
                        self._provider = "ollama"
                    elif "Anthropic" in adapter_class:
                        self._provider = "anthropic"
                    elif "OpenAI" in adapter_class:
                        self._provider = "openai"
            except Exception as registry_error:
                print(f"[ResponseComposer] Could not resolve LLM config for alias={llm_alias}: {registry_error}")

            if self._debug_logging_enabled():
                print(
                    f"[ResponseComposer] REAL LLM call provider={self._provider or 'unknown'} "
                    f"model={model_name or 'unknown'} alias={llm_alias}"
                )
            
            # Call LLM with streaming to unlock bullets-first rendering
            start_time = time.perf_counter()
            llm_response = ""
            time_to_bullets_ms: Optional[int] = None
            bullets_emitted = False

            if prefer_structured_output:
                try:
                    async for chunk in adapter.stream(messages, config):
                        llm_response += chunk

                        if not bullets_emitted and self._has_complete_bullets_section(llm_response):
                            parsed_bullets, _ = self._parse_structured_response(llm_response)
                            if parsed_bullets:
                                time_to_bullets_ms = int((time.perf_counter() - start_time) * 1000)
                                bullets_preview = GeneratedResponse(
                                    bullets=parsed_bullets,
                                    full_response="",
                                    key_metrics=self._extract_metrics_from_text(" ".join(parsed_bullets)),
                                    confidence=0.85,
                                    style_used=style,
                                    generation_time_ms=time_to_bullets_ms,
                                    mode="real",
                                    metadata={
                                        "composer_status": "llm_streaming",
                                        "stage": "bullets",
                                        "time_to_bullets_ms": time_to_bullets_ms,
                                        "provider": self._provider,
                                        "model": model_name,
                                        "llm_alias": llm_alias,
                                    },
                                )
                                if on_bullets:
                                    await self._emit_bullets(on_bullets, bullets_preview)
                                bullets_emitted = True
                except Exception as stream_error:
                    if self._debug_logging_enabled():
                        print(f"[ResponseComposer] Streaming unavailable, falling back to generate(): {stream_error}")
                    llm_response = await adapter.generate(messages, config)

                if not llm_response:
                    llm_response = await adapter.generate(messages, config)
            else:
                llm_response = await adapter.generate(messages, config)

            elapsed_ms = int((time.perf_counter() - start_time) * 1000)

            # Parse structured output: [BULLETS] + [FULL_RESPONSE]
            bullets, full_response = self._parse_structured_response(llm_response)
            if not bullets:
                bullets = self._parse_bullets_from_response(llm_response)
            if not full_response:
                full_response = llm_response.strip()
            if not prefer_structured_output:
                full_response = self._strip_unstructured_response_labels(full_response or llm_response)

            alignment_issues = self._detect_realtime_alignment_issues(context, full_response)
            rewrite_issues = list(alignment_issues)
            if getattr(context, "delivery_mode", "manual") == "live_manual":
                style_config = getattr(context, "style_config", {}) or {}
                if not style_config.get("live_emergency_fallback"):
                    rewrite_issues = []
                else:
                    rewrite_issues = [
                        issue
                        for issue in alignment_issues
                        if any(
                            marker in issue.lower()
                            for marker in (
                                "empty",
                                "opening does not answer",
                                "does not clearly cover",
                                "asks for clarification",
                            )
                        )
                    ]
            if rewrite_issues:
                print(f"[ResponseComposer] Realtime alignment rewrite triggered: {rewrite_issues}")
                rewrite_messages = [
                    {"role": "system", "content": self._get_system_prompt(style)},
                    {
                        "role": "user",
                        "content": self._build_realtime_alignment_rewrite_prompt(
                            context,
                            full_response,
                            rewrite_issues,
                            prefer_structured_output=prefer_structured_output,
                        ),
                    },
                ]
                rewritten_response = await adapter.generate(rewrite_messages, config)
                rewritten_bullets, rewritten_full_response = self._parse_structured_response(rewritten_response)
                if not rewritten_bullets:
                    rewritten_bullets = self._parse_bullets_from_response(rewritten_response)
                if rewritten_full_response:
                    full_response = rewritten_full_response.strip()
                else:
                    full_response = rewritten_response.strip() or full_response
                if not prefer_structured_output:
                    full_response = self._strip_unstructured_response_labels(full_response)
                if rewritten_bullets:
                    bullets = rewritten_bullets
                elapsed_ms = int((time.perf_counter() - start_time) * 1000)

            # If bullets were not emitted during streaming, emit now
            if on_bullets and bullets and not bullets_emitted:
                time_to_bullets_ms = time_to_bullets_ms or elapsed_ms
                await self._emit_bullets(
                    on_bullets,
                    GeneratedResponse(
                        bullets=bullets,
                        full_response="",
                        key_metrics=self._extract_metrics_from_text(" ".join(bullets)),
                        confidence=0.85,
                        style_used=style,
                        generation_time_ms=time_to_bullets_ms,
                        mode="real",
                        metadata={
                            "composer_status": "llm_generated",
                            "stage": "bullets",
                            "time_to_bullets_ms": time_to_bullets_ms,
                            "provider": self._provider,
                            "model": model_name,
                            "llm_alias": llm_alias,
                        },
                    ),
                )

            key_metrics = self._extract_metrics_from_text(full_response)

            return GeneratedResponse(
                bullets=bullets,
                full_response=full_response,
                key_metrics=key_metrics,
                confidence=0.9,  # Higher confidence for real mode
                style_used=style,
                generation_time_ms=elapsed_ms,
                mode="real",
                metadata={
                    "composer_status": "llm_generated",
                    "evidence_count": len(context.evidence),
                    "api_available": True,
                    "provider": self._provider,
                    "model": model_name,
                    "llm_alias": llm_alias,
                    "stage": "full",
                    "time_to_bullets_ms": time_to_bullets_ms if time_to_bullets_ms is not None else elapsed_ms,
                    "time_to_full_ms": elapsed_ms,
                    "live_alignment_rewrite_applied": bool(rewrite_issues),
                    "live_alignment_issues": alignment_issues,
                },
            )
            
        except Exception as e:
            import traceback
            error_msg = str(e)
            error_type = type(e).__name__
            stack_trace = traceback.format_exc()
            print(f"[ResponseComposer] LLM call FAILED: {error_type}: {error_msg}")
            print(f"[ResponseComposer] Stack trace:\n{stack_trace}")
            print(f"[ResponseComposer] llm_alias={llm_alias}, provider={self._provider}, api_available={self._api_available}")
            
            # CRITICAL: Never fall back to demo mode - return error instead
            # Demo fallback was causing fake CV data to be generated
            print("[ResponseComposer] CRITICAL: LLM failed - returning error response, NOT demo fallback")
            
            error_bullets = [
                f"• Error: LLM generation failed ({error_type})",
                "• Real LLM is required - demo fallback is disabled",
                "• Check API keys and LLM configuration",
            ]
            
            error_response = GeneratedResponse(
                bullets=error_bullets,
                full_response=(
                    f"I apologize, but I cannot generate a response at this time. "
                    f"The AI service encountered an error: {error_msg}. "
                    f"Please check that ANTHROPIC_API_KEY or OPENAI_API_KEY is configured correctly."
                ),
                key_metrics=[],
                confidence=0.0,
                style_used=style,
                generation_time_ms=0,
                mode="error",
                metadata={
                    "composer_status": "llm_error",
                    "llm_alias": llm_alias,
                    "error_type": error_type,
                    "error_message": error_msg,
                    "stack_trace": stack_trace,
                    "warning": "Demo fallback is disabled - real LLM required",
                },
            )
            
            # Emit error bullets if callback provided
            if on_bullets:
                await self._emit_bullets(on_bullets, error_response)
            
            return error_response

    def _ensure_full_response(
        self,
        context: AssembledContext,
        response: GeneratedResponse,
    ) -> GeneratedResponse:
        """Guarantee full_response is non-empty for primary artifact emission."""
        if response.full_response and response.full_response.strip():
            return response

        # P4-T1: build a meaningful fallback from bullets/evidence/question.
        response.full_response = self._build_full_response_fallback(
            context,
            response.bullets,
        )
        if not isinstance(response.metadata, dict):
            response.metadata = {}
        response.metadata["full_response_fallback"] = True
        return response

    def _build_full_response_fallback(
        self,
        context: AssembledContext,
        bullets: list[str],
    ) -> str:
        """Create a non-empty, useful full response when LLM output is missing."""
        cleaned_bullets = [
            bullet.replace("•", "").strip()
            for bullet in bullets
            if bullet and bullet.strip()
        ]
        delivery_mode = getattr(context, "delivery_mode", "manual")
        response_mode = getattr(getattr(context, "analysis", None), "response_mode", None)
        if cleaned_bullets:
            sentence = " ".join(cleaned_bullets)
            if sentence and sentence[-1] not in ".!?":
                sentence += "."
            if delivery_mode in {"realtime", "live_manual"} or getattr(response_mode, "value", "") in {"coach_explainer", "hybrid_dual"}:
                return sentence
            return (
                f"{sentence} "
                "I would connect this to the role requirements and the impact I delivered."
            )

        evidence = getattr(context, "evidence", []) or []
        evidence_snippets = [
            snippet.text.strip()
            for snippet in evidence
            if getattr(snippet, "text", "").strip()
        ]
        if evidence_snippets:
            sentence = " ".join(evidence_snippets[:2])
            if sentence and sentence[-1] not in ".!?":
                sentence += "."
            return (
                f"{sentence} "
                "I would frame this as a concrete example of my impact and decision-making."
            )

        question_text = (getattr(context, "question", "") or "the role").strip() or "the role"
        return (
            "I would answer by framing the context, sharing a relevant example, "
            f"and linking the outcome back to {question_text}."
        )
    
    def _get_system_prompt(self, style: ResponseStyle) -> str:
        """Get system prompt for the given style"""
        base = """You are an expert interview coach.
Choose the most useful coaching behavior for the question:
- For conceptual technical questions, teach directly and clearly.
- For interview evaluation questions, craft an interview-ready answer.

Global rules:
1. Do not invent facts, metrics, achievements, or outcomes.
2. Do not force first-person framing unless the question requires an interview-style answer.
3. Do not force business impact, role alignment, or KPIs unless the question is about those topics.
4. Prefer precision, clarity, and directness over generic executive language.
"""
        style_additions = {
            ResponseStyle.EXECUTIVE: "\nStyle bias: Executive - concise, structured, outcome-aware when outcomes are relevant.",
            ResponseStyle.COMMERCIAL: "\nStyle bias: Commercial - emphasize business value, stakeholder impact, and prioritization when the question calls for it.",
            ResponseStyle.TECHNICAL: "\nStyle bias: Technical - emphasize principles, trade-offs, architecture, constraints, and implementation judgment.",
            ResponseStyle.MIXED: "\nStyle bias: Mixed - adapt based on the detected question mode and primary intent.",
        }
        return base + style_additions.get(style, "")
    
    def _parse_bullets_from_response(self, text: str) -> list[str]:
        """Parse bullet points from LLM response"""
        bullets = []
        lines = text.split('\n')
        
        # First pass: look for explicit bullet markers
        for line in lines:
            line = line.strip()
            if line.startswith('• ') or line.startswith('- ') or line.startswith('* '):
                bullets.append(line)
        
        # Second pass: if no bullets found, try to extract key sentences
        # This handles cases where LLM doesn't follow bullet format exactly
        if not bullets and text:
            # Look for sentences that look like key points
            import re
            # Split into sentences and look for ones with metrics or strong verbs
            sentences = re.split(r'(?<=[.!?])\s+', text)
            for sent in sentences[:5]:
                sent = sent.strip()
                # Skip very short sentences or the first sentence (often an intro)
                if len(sent) > 30 and not sent.startswith("I "):
                    bullets.append(f"• {sent[:100]}{'...' if len(sent) > 100 else ''}")
        
        return bullets[:5]  # Max 5 bullets

    def _has_complete_bullets_section(self, text: str) -> bool:
        """Return True when the streamed text contains a complete bullets block."""
        upper_text = text.upper()
        return "[/BULLETS]" in upper_text or ("[BULLETS]" in upper_text and "[FULL_RESPONSE]" in upper_text)

    def _parse_structured_response(self, text: str) -> tuple[list[str], str]:
        """Parse [BULLETS] and [FULL_RESPONSE] sections from model output."""
        if not text:
            return [], ""

        bullets_block = ""
        full_block = ""

        bullets_match = re.search(r"\[BULLETS\](.*?)\[/BULLETS\]", text, re.IGNORECASE | re.DOTALL)
        if bullets_match:
            bullets_block = bullets_match.group(1)
        else:
            bullets_fallback = re.search(r"\[BULLETS\](.*?)(\[FULL_RESPONSE\]|$)", text, re.IGNORECASE | re.DOTALL)
            if bullets_fallback:
                bullets_block = bullets_fallback.group(1)

        full_match = re.search(r"\[FULL_RESPONSE\](.*?)\[/FULL_RESPONSE\]", text, re.IGNORECASE | re.DOTALL)
        if full_match:
            full_block = full_match.group(1)
        else:
            full_fallback = re.search(r"\[FULL_RESPONSE\](.*)$", text, re.IGNORECASE | re.DOTALL)
            if full_fallback:
                full_block = full_fallback.group(1)

        bullets: list[str] = []
        for raw_line in bullets_block.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            line = re.sub(r"^[-*•]\s*", "", line).strip()
            if not line:
                continue
            bullets.append(f"• {line}")

        # Deduplicate while preserving order
        deduped_bullets = list(dict.fromkeys(bullets))[:5]
        return deduped_bullets, full_block.strip()

    @staticmethod
    def _strip_unstructured_response_labels(text: str) -> str:
        cleaned = (text or "").strip()
        if not cleaned:
            return ""

        label_patterns = [
            r"^\s*\[?\s*FULL[\s_]+RESPONSE\s*\]?\s*:?\s*",
            r"^\s*\[?\s*FINAL[\s_]+RESPONSE\s*\]?\s*:?\s*",
            r"^\s*\[?\s*RESPONSE\s*\]?\s*:?\s*",
            r"^\s*\[?\s*BULLETS\s*\]?\s*:?\s*",
        ]
        updated = True
        while updated and cleaned:
            updated = False
            for pattern in label_patterns:
                stripped = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
                if stripped != cleaned:
                    cleaned = stripped.strip()
                    updated = True

        cleaned = re.sub(
            r"\[/?\s*(BULLETS|FULL[\s_]+RESPONSE|FINAL[\s_]+RESPONSE|RESPONSE)\s*\]",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        return cleaned.strip()

    async def _emit_bullets(
        self,
        callback: Callable[[GeneratedResponse], Awaitable[None] | None],
        bullets_response: GeneratedResponse,
    ) -> None:
        """Emit bullets preview through sync or async callback."""
        maybe_coroutine = callback(bullets_response)
        if hasattr(maybe_coroutine, "__await__"):
            await maybe_coroutine
    
    def _extract_metrics_from_text(self, text: str) -> list[str]:
        """Extract key metrics from response text"""
        import re
        metrics = []
        
        # Look for numbers with context
        patterns = [
            r'\b(\d+(?:\.\d+)?(?:\+)?%?)\s*(?:engineers?|years?|months?|times?|x|growth|increase|reduction)',
            r'\b(\\\$?\d+(?:\.\d+)?(?:[MBK])?)\b',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            metrics.extend(matches[:2])
        
        return list(set(metrics))[:4]

    @staticmethod
    def _count_words(text: str) -> int:
        return len(re.findall(r"\b\w+\b", text or ""))

    @staticmethod
    def _contains_metric_like_signal(text: str) -> bool:
        return bool(re.search(r"\b\d+(?:\.\d+)?(?:%|x|k|m|b)?\b", text or "", re.IGNORECASE))

    @staticmethod
    def _get_live_prepared_context(context: AssembledContext):
        prepared = getattr(context, "live_prepared_context", None)
        if getattr(context, "delivery_mode", "manual") not in {"realtime", "live_manual"}:
            return None
        return prepared

    def _build_live_shape_rules(self, prepared_context) -> str:
        if not prepared_context:
            return ""

        shape = prepared_context.answer_shape
        if shape == AnswerShape.DIRECT_SHORT:
            return """
LIVE SHAPE RULES:
- This is a simple ask. Answer it directly in the first sentence.
- Keep the answer short and high-signal.
- Use at most one brief supporting reason or example.
- Stop once the ask has been answered.
- Do not expand into a profile summary or consulting thesis.
"""
        if shape == AnswerShape.DIRECT_STRUCTURED:
            return """
LIVE SHAPE RULES:
- This is a compound ask. Answer the parts in order.
- Keep the structure visible.
- Use concrete examples, but do not turn each point into a long story.
"""
        if shape == AnswerShape.TECHNICAL_EXPLAINER:
            return """
LIVE SHAPE RULES:
- This is a technical ask. Start with the direct answer.
- Then explain principles or trade-offs.
- End with one practical takeaway.
- Do not drift into biography or generic business framing.
"""
        if shape == AnswerShape.STRATEGIC_EXPLAINER:
            return """
LIVE SHAPE RULES:
- Take a clear position early.
- Explain the reasoning.
- Add the outcome or KPI lens only if it helps answer the ask.
"""
        return ""

    def _build_live_manual_prompt(
        self,
        *,
        context: AssembledContext,
        style: ResponseStyle,
        interview_type: str,
        question_mode: str,
        response_mode: str,
        answer_intent: str,
        delivery_mode: str,
        max_words: int,
        live_prepared_context,
        conversation_section: str,
        evidence_section: str,
        candidate_name: str,
        candidate_summary: str,
        candidate_skills_text: str,
        candidate_achievements_text: str,
        company_name: str,
        role_title: str,
        company_description: str,
        company_culture: str,
        company_requirements_text: str,
        interviewer_name: str,
        interviewer_focus_areas: list[str],
        style_instruction: str,
        response_mode_instruction: str,
        delivery_mode_instruction: str,
        prefer_structured_output: bool,
        working_draft: str,
    ) -> str:
        asks_in_order = [ask for ask in (live_prepared_context.asks_in_order or []) if ask]
        asks_section = "\n".join(
            f"{idx}. {ask}" for idx, ask in enumerate(asks_in_order, start=1)
        ) or "1. Answer the interviewer ask directly."
        interviewer_focus_text = ", ".join(interviewer_focus_areas[:6]) if interviewer_focus_areas else "Not provided"
        working_draft_section = ""
        compact_working_draft = _compact_text(working_draft or "", limit=900)
        if compact_working_draft:
            working_draft_section = f"""
WORKING DRAFT (NOT SOURCE OF TRUTH):
{compact_working_draft}

Use this only as a speed scaffold.
If any part of it conflicts with the interviewer block or resolved live ask, ignore it.
"""

        output_format_section = """
OUTPUT FORMAT (MANDATORY):
[BULLETS]
- Bullet 1 must be the direct answer or thesis.
- Bullet 2-4 must be the strongest supporting points only.
[/BULLETS]
[FULL_RESPONSE]
For interview_answer: one polished interview-ready response that starts with the direct answer.
For coach_explainer: one direct, precise explanation.
For hybrid_dual: use exactly this structure:
Technical answer:
...

How to say it in the interview:
...
[/FULL_RESPONSE]
""".strip()
        if not prefer_structured_output:
            output_format_section = """
OUTPUT FORMAT (MANDATORY):
Return only one polished final response.
Do not include bullets, labels, section headers, markdown tags, or prefatory notes.
Start with the direct answer and cover every ask in order.
""".strip()

        return f"""
You are helping the candidate answer a live interview question.

SOURCE OF TRUTH:
- Use the interviewer block below to decide what must be answered.
- Do not let the candidate bio, company info, or role pitch replace the actual ask.

INTERVIEWER BLOCK:
{conversation_section}

RESOLVED LIVE ASK:
- Resolved question: {live_prepared_context.resolved_question or context.question}
- Asks in order:
{asks_section}
- Answer focus: {live_prepared_context.answer_focus or "Answer what the interviewer is asking right now."}
- Style guidance: {live_prepared_context.answer_style_guidance or "Keep it direct and speakable."}
{working_draft_section}

GROUNDING CONTEXT:
- Candidate name: {candidate_name or "Not provided"}
- Candidate summary: {candidate_summary or "Not provided"}
- Candidate skills: {candidate_skills_text}
- Candidate achievements:
{candidate_achievements_text}
- Target company: {company_name or "Not provided"}
- Target role: {role_title or "Not provided"}
- Company summary: {company_description or "Not provided"}
- Culture signals: {company_culture or "Not provided"}
- Role requirements:
{company_requirements_text}
- Interviewer name: {interviewer_name or "Not provided"}
- Interviewer focus areas: {interviewer_focus_text}

CANDIDATE EVIDENCE:
{evidence_section}

INTERVIEW TYPE: {interview_type}
STYLE: {style.value}
QUESTION MODE: {question_mode}
RESPONSE MODE: {response_mode}
ANSWER INTENT: {answer_intent}
DELIVERY MODE: {delivery_mode}

INSTRUCTIONS:
- Start by answering what the interviewer is asking now.
- If there is one ask, answer it directly in the first sentence.
- If there are multiple asks, answer every ask in order and make the structure visible with short transitions such as "First", "Second", and "Finally".
- Use the grounding context only when it sharpens the answer.
- Do not turn the answer into a generic biography, role pitch, or company pitch unless the interviewer explicitly asked for that.
- Do not ask for clarification if the ask is actionable.
- Do not invent facts or unsupported metrics.
- Keep it speakable, strong, and close to {max_words} words.

STYLE GUIDANCE:
{style_instruction}
{response_mode_instruction}
{delivery_mode_instruction}

{output_format_section}
"""

    @staticmethod
    def _normalize_text(text: str) -> str:
        return " ".join((text or "").lower().split())

    @staticmethod
    def _is_broad_intro_ask(text: str) -> bool:
        lowered = " ".join((text or "").lower().split())
        patterns = [
            "tell me a little bit about you",
            "tell me about yourself",
            "walk me through your background",
            "quick intro",
            "brief intro",
            "start telling us",
            "start telling me",
        ]
        return any(pattern in lowered for pattern in patterns)

    def _is_generic_biography_opening(self, text: str) -> bool:
        opening = " ".join(self._normalize_text(text).split()[:28])
        biography_openers = [
            "i'm a technology executive",
            "i am a technology executive",
            "i have over",
            "i have 20 years",
            "over the past 20 years",
            "right now i'm",
            "currently i'm",
            "my background is",
        ]
        return any(opener in opening for opener in biography_openers)

    @staticmethod
    def _is_clarification_response(text: str) -> bool:
        lowered = " ".join((text or "").lower().split())
        clarification_markers = [
            "could you clarify",
            "can you clarify",
            "what would you like to know more about",
            "i want to make sure i give you the most useful answer",
            "just want to make sure i'm answering",
            "would you like me to focus on a specific area",
        ]
        return any(marker in lowered for marker in clarification_markers)

    @staticmethod
    def _extract_salient_terms(text: str) -> list[str]:
        stopwords = {
            "about", "after", "again", "also", "along", "among", "and", "are", "as",
            "ask", "asked", "basically", "been", "being", "briefly",
            "but", "can", "could", "did", "does", "early", "etcetera", "for", "from",
            "get", "had", "have", "hear", "how", "i", "if", "in", "into", "is", "it",
            "just", "kind", "kinda", "last", "little", "me", "more", "my",
            "now", "of", "on", "or", "our", "really", "say", "so",
            "start", "tell", "that", "the", "their", "them", "then", "there", "these",
            "they", "this", "to", "up", "us", "very", "were", "what", "where",
            "which", "who", "why", "with", "would", "you", "your", "yourself",
        }
        words = re.findall(r"\b[a-z][a-z0-9+\-]{3,}\b", (text or "").lower())
        salient: list[str] = []
        for word in words:
            if word in stopwords:
                continue
            if word not in salient:
                salient.append(word)
        return salient[:6]

    def _ask_coverage_score(self, ask: str, response_lower: str) -> float:
        ask_lower = self._normalize_text(ask)
        if not ask_lower:
            return 0.0
        if ask_lower in response_lower:
            return 1.0

        salient_terms = self._extract_salient_terms(ask_lower)
        if not salient_terms:
            return 0.0

        hits = 0
        for term in salient_terms:
            if term in response_lower:
                hits += 1
        return hits / max(1, len(salient_terms))

    def _first_ask_signal_position(self, ask: str, response_lower: str) -> int:
        ask_lower = self._normalize_text(ask)
        if not ask_lower:
            return -1
        exact = response_lower.find(ask_lower)
        if exact >= 0:
            return exact

        positions = [
            response_lower.find(term)
            for term in self._extract_salient_terms(ask_lower)
            if term and response_lower.find(term) >= 0
        ]
        return min(positions) if positions else -1

    def _detect_realtime_alignment_issues(self, context: AssembledContext, full_response: str) -> list[str]:
        ask_brief = getattr(context, "ask_brief", None)
        prepared_context = self._get_live_prepared_context(context)
        if getattr(context, "delivery_mode", "manual") not in {"realtime", "live_manual"} or not ask_brief:
            return []

        response_lower = self._normalize_text(full_response)
        if not response_lower:
            return ["The answer is empty."]

        issues: list[str] = []
        asks_in_order = (
            [ask for ask in (prepared_context.asks_in_order or []) if ask]
            if prepared_context is not None and prepared_context.asks_in_order
            else [ask for ask in [ask_brief.primary_ask, *ask_brief.secondary_asks] if ask]
        )
        specific_asks = [ask for ask in asks_in_order if not self._is_broad_intro_ask(ask)]
        intro_asks = [ask for ask in asks_in_order if self._is_broad_intro_ask(ask)]

        if specific_asks and self._is_generic_biography_opening(full_response):
            issues.append("The opening is a generic biography instead of answering the most specific ask directly.")

        opening_window = self._normalize_text(" ".join((full_response or "").split()[:45]))
        if specific_asks:
            first_specific = specific_asks[0]
            if self._ask_coverage_score(first_specific, opening_window) < 0.34:
                issues.append("The opening does not answer the primary ask before moving into supporting detail.")

        coverage_failures: list[str] = []
        for ask in specific_asks[:3]:
            if self._ask_coverage_score(ask, response_lower) < 0.34:
                coverage_failures.append(ask)

        if coverage_failures:
            issues.append(
                "The answer does not clearly cover these asks: "
                + "; ".join(coverage_failures)
            )

        if len(specific_asks) > 1:
            positioned = [
                (ask, self._first_ask_signal_position(ask, response_lower))
                for ask in specific_asks[:4]
            ]
            positioned = [(ask, pos) for ask, pos in positioned if pos >= 0]
            if len(positioned) >= 2:
                positions = [pos for _, pos in positioned]
                if positions != sorted(positions):
                    issues.append("The answer covers multiple asks, but not in the interviewer order.")

        if intro_asks and specific_asks and self._ask_coverage_score(intro_asks[0], response_lower) > 0.55:
            first_specific = specific_asks[0]
            if self._ask_coverage_score(first_specific, response_lower) < 0.45:
                issues.append("The broad intro ask is overweighted before the more specific asks are answered.")

        if prepared_context is not None:
            word_count = self._count_words(full_response)
            if (
                prepared_context.complexity_class == ComplexityClass.SIMPLE
                and word_count > max(int(prepared_context.target_length * 1.45), 150)
            ):
                issues.append("This is a simple ask, but the answer is too long and over-developed.")
            if not prepared_context.allow_profile_opening and self._is_generic_biography_opening(full_response):
                issues.append("The answer opens like a profile summary instead of answering the ask directly.")
            if not prepared_context.allow_metrics and self._contains_metric_like_signal(full_response):
                issues.append("The answer uses metrics or business framing even though this ask should stay direct and simple.")
            if prepared_context.primary_ask and self._is_clarification_response(full_response):
                issues.append("The answer asks for clarification even though the normalized ask is actionable.")

        return issues

    def _build_realtime_alignment_rewrite_prompt(
        self,
        context: AssembledContext,
        draft_response: str,
        issues: list[str],
        *,
        prefer_structured_output: bool = True,
    ) -> str:
        ask_brief = getattr(context, "ask_brief", None)
        prepared_context = self._get_live_prepared_context(context)
        asks_in_order = (
            [ask for ask in (prepared_context.asks_in_order or []) if ask]
            if prepared_context is not None and prepared_context.asks_in_order
            else [ask for ask in ([ask_brief.primary_ask, *ask_brief.secondary_asks] if ask_brief else []) if ask]
        )
        primary_ask = asks_in_order[0] if asks_in_order else (ask_brief.primary_ask if ask_brief else context.question)
        secondary_asks = asks_in_order[1:] if asks_in_order else (ask_brief.secondary_asks if ask_brief else [])
        secondary_text = "\n".join(f"- {ask}" for ask in secondary_asks) if secondary_asks else "- None"
        issues_text = "\n".join(f"- {issue}" for issue in issues)
        prepared_shape_section = ""
        if prepared_context is not None:
            prepared_shape_section = f"""
PREPARED LIVE POLICY:
- Resolved question: {prepared_context.resolved_question or primary_ask}
- Complexity class: {prepared_context.complexity_class.value}
- Answer shape: {prepared_context.answer_shape.value}
- Target length: about {prepared_context.target_length} words
- Allow metrics: {"yes" if prepared_context.allow_metrics else "no"}
- Allow profile opening: {"yes" if prepared_context.allow_profile_opening else "no"}
- Require ordered coverage: {"yes" if prepared_context.require_ordered_coverage else "no"}
"""

        output_format_rules = """
- Return the same mandatory format:
[BULLETS] ... [/BULLETS]
[FULL_RESPONSE] ... [/FULL_RESPONSE]
""".strip()
        if not prefer_structured_output:
            output_format_rules = """
- Return only one polished final response.
- Do not include bullets, labels, markdown tags, or section headers.
""".strip()

        return f"""
Rewrite the interview answer below so it directly answers the normalized ask.

PRIMARY ASK:
{primary_ask}

SECONDARY ASKS:
{secondary_text}

PROBLEMS TO FIX:
{issues_text}
{prepared_shape_section}

RULES:
- Keep the same facts and evidence already present in the draft.
- Do not invent any new facts, metrics, roles, or outcomes.
- Start by answering the main ask directly.
- Answer the primary ask first and the secondary asks in the normalized order.
- If there are multiple asks, make the structure explicit in the FULL_RESPONSE using clear transitions such as "First", "Second", and "Finally".
- If there is a broad intro/background ask mixed with more specific asks, keep the intro brief and place it after the specific asks.
- Avoid generic biography openings.
- Do not ask the interviewer to clarify unless the draft contains no actionable ask at all.
- Keep it speakable and concise for live interview delivery.
{output_format_rules}

DRAFT TO REWRITE:
[FULL_RESPONSE]
{draft_response}
[/FULL_RESPONSE]
"""

    async def repair_live_response(
        self,
        context: AssembledContext,
        draft_response: str,
        *,
        issues: Optional[list[str]] = None,
    ) -> Optional[GeneratedResponse]:
        style = context.analysis.recommended_style if context.analysis else ResponseStyle.EXECUTIVE
        llm_alias = str((context.interview_config or {}).get("llm_alias", "main"))
        repaired_issues = list(issues or self._detect_realtime_alignment_issues(context, draft_response))
        if not repaired_issues:
            repaired_issues = ["Refresh the answer so it fully covers the latest normalized asks in order."]

        try:
            from adapters.llm_adapter import get_llm_adapter_required, DemoLLMAdapter

            adapter = get_llm_adapter_required(alias=llm_alias)
            if isinstance(adapter, DemoLLMAdapter):
                return None

            provider_name = self._provider
            adapter_class = adapter.__class__.__name__.lower()
            if not provider_name:
                if "anthropic" in adapter_class:
                    provider_name = "anthropic"
                elif "openai" in adapter_class:
                    provider_name = "openai"
            if provider_name:
                self._provider = provider_name
            model_name = getattr(adapter, "model", None)

            max_words = getattr(context, "max_words", 200)
            calculated_max_tokens = min(int(max_words * 2) + 100, 1024)
            config = {
                "temperature": 0.2,
                "max_tokens": calculated_max_tokens,
            }
            try:
                from adapters.provider_registry import get_registry

                llm_cfg = get_registry().get_llm_config(alias=llm_alias)
                llm_cfg_values = llm_cfg.config or {}
                registry_max_tokens = llm_cfg_values.get("max_tokens", 0)
                if registry_max_tokens > calculated_max_tokens:
                    config["max_tokens"] = registry_max_tokens
                if not model_name and llm_cfg.model:
                    model_name = llm_cfg.model
            except Exception:
                pass

            raw = await adapter.generate(
                [
                    {"role": "system", "content": self._get_system_prompt(style)},
                    {
                        "role": "user",
                        "content": self._build_realtime_alignment_rewrite_prompt(
                            context,
                            draft_response,
                            repaired_issues,
                            prefer_structured_output=False,
                        ),
                    },
                ],
                config,
            )

            bullets, parsed_full_response = self._parse_structured_response(raw or "")
            full_response = self._strip_unstructured_response_labels(parsed_full_response or raw or "")
            if not full_response:
                return None
            if not bullets:
                bullets = self._parse_bullets_from_response(full_response)

            return GeneratedResponse(
                bullets=bullets,
                full_response=full_response,
                key_metrics=self._extract_metrics_from_text(full_response),
                confidence=0.9,
                style_used=style,
                generation_time_ms=0,
                mode="real",
                metadata={
                    "composer_status": "llm_rewritten",
                    "provider": self._provider,
                    "model": model_name,
                    "llm_alias": llm_alias,
                    "stage": "repair",
                    "repair_issues": repaired_issues,
                },
            )
        except Exception as exc:
            if self._debug_logging_enabled():
                print(f"[ResponseComposer] live repair failed: {type(exc).__name__}: {exc}")
            return None

    def _build_normalized_answer_outline(self, ask_brief, delivery_mode: str) -> tuple[str, str]:
        """Build a stricter, family-aware answer outline from the normalized ask."""
        if not ask_brief:
            return "", ""

        lines: list[str] = []
        rules: list[str] = []

        if ask_brief.answer_family.value in {"experience_scope", "mixed_compound"}:
            asks_in_order = [ask_brief.primary_ask, *ask_brief.secondary_asks]
            for idx, ask in enumerate([ask for ask in asks_in_order if ask], start=1):
                lines.append(f"{idx}. Cover this ask directly: {ask}")
            rules.extend([
                "Do not open with a generic executive biography.",
                "Answer each ask in order and make the transitions obvious.",
                "If a broad introduction is requested alongside specific asks, keep it brief and place it last or near the close.",
                "Answer the parts in order and make each part visible in the flow of the answer.",
            ])

        elif ask_brief.answer_family.value == "culture_fit":
            lines.extend([
                "1. State what you are looking for in a company or team.",
                "2. State what you do not like or want to avoid.",
                "3. Add one short reason why those conditions matter to your best work.",
            ])
            rules.extend([
                "Do not turn this into a biography.",
                "Do not default to achievements or metrics unless they sharpen one preference.",
            ])

        elif ask_brief.answer_family.value == "technical_concept":
            lines.extend([
                "1. Answer the technical question directly.",
                "2. Explain the key principles or trade-offs.",
                "3. End with one concise practical takeaway.",
            ])
            rules.extend([
                "Do not force first-person biography language.",
                "Do not force business outcomes unless the question asks for them.",
            ])

        elif ask_brief.answer_family.value == "business_strategy":
            lines.extend([
                "1. Take a clear position.",
                "2. Explain the business reasoning.",
                "3. Add the outcome or KPI lens that would matter.",
            ])

        if delivery_mode in {"realtime", "live_manual"}:
            rules.append("The first sentence must already be usable aloud in the interview.")

        outline_section = "\n".join(lines)
        rules_section = "\n".join(f"- {rule}" for rule in rules)
        return outline_section, rules_section
    
    def _build_prompt(
        self,
        context: AssembledContext,
        style: ResponseStyle,
        *,
        prefer_structured_output: bool = True,
    ) -> str:
        """Build LLM prompt based on style and context"""
        # NEW: Extract max_words and interview_type from context
        max_words = getattr(context, 'max_words', 200)
        interview_config = context.interview_config or {}
        interview_type = interview_config.get('interview_type', 'mixed')
        analysis = context.analysis
        ask_brief = getattr(context, "ask_brief", None)
        live_prepared_context = self._get_live_prepared_context(context)
        question_mode = analysis.question_mode.value if analysis else "experience_based"
        response_mode = analysis.response_mode.value if analysis else "interview_answer"
        answer_intent = analysis.answer_intent.value if analysis else "mixed"
        metrics_required = analysis.why_metrics_required if analysis else True
        delivery_mode = getattr(context, 'delivery_mode', 'manual')
        sub_questions = analysis.sub_questions if analysis else []
        normalized_primary_ask = ask_brief.primary_ask if ask_brief and ask_brief.primary_ask else (context.question or "")
        normalized_secondary_asks = ask_brief.secondary_asks if ask_brief else []
        normalized_family = ask_brief.answer_family.value if ask_brief else "general"
        normalized_contract = ask_brief.answer_contract.value if ask_brief else "general_direct"
        normalized_metrics_policy = ask_brief.metrics_policy.value if ask_brief else ("required" if metrics_required else "prefer_if_supported")
        if ask_brief and normalized_metrics_policy == "avoid_unless_requested":
            metrics_required = False
        if live_prepared_context is not None:
            max_words = live_prepared_context.target_length or max_words
            if not live_prepared_context.allow_metrics:
                metrics_required = False
        normalized_asks_in_order = [ask for ask in [normalized_primary_ask, *normalized_secondary_asks] if ask]
        if live_prepared_context is not None and live_prepared_context.asks_in_order:
            normalized_asks_in_order = [ask for ask in live_prepared_context.asks_in_order if ask]
            if normalized_asks_in_order:
                normalized_primary_ask = normalized_asks_in_order[0]
                normalized_secondary_asks = normalized_asks_in_order[1:]
        
        candidate_context = interview_config.get("candidate", {}) if isinstance(interview_config.get("candidate", {}), dict) else {}
        company_context = interview_config.get("company", {}) if isinstance(interview_config.get("company", {}), dict) else {}
        interviewer_context = interview_config.get("interviewer", {}) if isinstance(interview_config.get("interviewer", {}), dict) else {}

        candidate_name = interview_config.get("candidate_name") or candidate_context.get("name") or ""
        candidate_summary = interview_config.get("candidate_summary") or candidate_context.get("summary") or ""
        candidate_skills = interview_config.get("candidate_skills") or candidate_context.get("skills") or []
        candidate_achievements = interview_config.get("candidate_achievements") or candidate_context.get("achievements") or []
        candidate_certifications = interview_config.get("candidate_certifications") or candidate_context.get("certifications") or []

        # CV full text - used as fallback context when evidence retrieval is unavailable (no DB)
        cv_text = (
            interview_config.get("cv_text")
            or candidate_context.get("cv_text")
            or candidate_context.get("cvText")
            or interview_config.get("cvText")
            or ""
        )

        company_name = interview_config.get("company_name") or company_context.get("companyName") or ""
        role_title = interview_config.get("role_title") or company_context.get("positionTitle") or company_context.get("roleTitle") or ""
        company_industry = interview_config.get("company_industry") or company_context.get("industry") or ""
        company_description = interview_config.get("company_description") or company_context.get("companyDescription") or ""
        company_requirements = interview_config.get("company_requirements") or company_context.get("positionRequirements") or []
        company_culture = interview_config.get("company_culture") or company_context.get("companyCulture") or ""
        interviewer_name = interviewer_context.get("name") or ""
        interviewer_role_title = interviewer_context.get("role_title") or interviewer_context.get("roleTitle") or ""
        interviewer_company = interviewer_context.get("company") or interviewer_context.get("companyName") or ""
        interviewer_background = interviewer_context.get("background_summary") or interviewer_context.get("backgroundSummary") or ""
        interviewer_expertise = interviewer_context.get("expertise") or []
        interviewer_career_highlights = interviewer_context.get("career_highlights") or interviewer_context.get("careerHighlights") or []
        interviewer_focus_areas = interviewer_context.get("likely_focus_areas") or interviewer_context.get("likelyFocusAreas") or []
        interviewer_style = interviewer_context.get("communication_style") or interviewer_context.get("communicationStyle") or ""
        interviewer_notes = interviewer_context.get("notes") or ""

        # CRITICAL: Detect if question mentions a specific previous company
        # and add explicit instructions to filter evidence accordingly
        question_text = normalized_primary_ask or context.question or ""
        mentioned_companies = self._extract_mentioned_companies(question_text, candidate_achievements)
        
        company_filter_instruction = ""
        if mentioned_companies:
            company_list = ", ".join(mentioned_companies)
            company_filter_instruction = f"""
CRITICAL COMPANY FILTERING:
The question specifically asks about: {company_list}
When answering, you MUST only use evidence and achievements from {company_list}.
Do NOT mix in details, metrics, or achievements from other companies.
If no specific evidence exists for {company_list}, state that clearly.
"""

        simple_live = bool(
            live_prepared_context is not None
            and live_prepared_context.complexity_class == ComplexityClass.SIMPLE
        )
        compact_live = delivery_mode == "live_manual"
        if compact_live:
            candidate_summary = _compact_text(candidate_summary, limit=220 if simple_live else 420)
            company_description = _compact_text(company_description, limit=260 if simple_live else 420)
            company_culture = _compact_text(company_culture, limit=180)
            interviewer_background = _compact_text(interviewer_background, limit=220)
            interviewer_notes = _compact_text(interviewer_notes, limit=160)
        candidate_skills_text = ", ".join(candidate_skills[:6 if simple_live else 10]) if candidate_skills else "None provided"
        candidate_achievements_limit = 2 if simple_live else (4 if compact_live else 8)
        candidate_achievements_text = "\n".join([f"- {a}" for a in candidate_achievements[:candidate_achievements_limit]]) if candidate_achievements else "- None provided"
        candidate_certs_text = ", ".join(candidate_certifications[:8]) if candidate_certifications else "None provided"
        company_requirements_limit = 3 if simple_live else (5 if compact_live else 10)
        company_requirements_text = "\n".join([f"- {r}" for r in company_requirements[:company_requirements_limit]]) if company_requirements else "- None provided"

        # Interview type specific instructions
        interview_type_instructions = {
            'behavioral': """
                Use STAR method:
                - Situation: Set the context
                - Task: What was required
                - Action: What YOU specifically did
                - Result: Quantified outcome
                Focus on YOUR actions, not the team's.""",
            'technical': """
                Structure: Problem → Analysis → Solution
                Include:
                - Technical trade-offs considered
                - Specific technologies/tools used
                - Implementation details
                - Business impact only if the question asks for it""",
            'system_design': """
                Structure:
                1. Requirements clarification
                2. High-level architecture
                3. Component breakdown
                4. Data flow
                5. Trade-offs and alternatives
                6. Scaling considerations""",
            'case_study': """
                Use structured business thinking:
                1. Problem understanding
                2. Framework selection
                3. Analysis with data
                4. Recommendation
                5. Risk assessment
                6. Next steps""",
            'mixed': """
                Blend behavioral and technical elements.
                For behavioral aspects: use STAR method.
                For technical aspects: include trade-offs and implementation details.""",
        }
        
        type_instruction = interview_type_instructions.get(
            interview_type, 
            interview_type_instructions['mixed']
        )

        # NEW: Dynamic word count based on max_words
        word_count_min = int(max_words * 0.9)
        word_count_max = int(max_words * 1.1)
        style_instructions = {
            ResponseStyle.EXECUTIVE: "Use a concise, structured answer. Prioritize decisions, actions, and outcomes only when relevant.",
            ResponseStyle.COMMERCIAL: "Use business language. Emphasize value, KPIs, priorities, ROI, and stakeholder impact when relevant.",
            ResponseStyle.TECHNICAL: "Use precise technical language. Emphasize architecture, trade-offs, risks, scaling, and implementation judgment.",
            ResponseStyle.MIXED: "Blend technical and executive language only when the question genuinely requires both.",
        }

        response_mode_instructions = {
            "interview_answer": f"""
                RESPONSE MODE: Interview answer
                - Write as an interview-ready answer the candidate can say out loud.
                - Use first person when helpful.
                - Use STAR / executive / commercial framing when relevant.
                - Use metrics only if they are supported by evidence and relevant to the question.
                - Connect to role requirements only when that improves the answer naturally.
                TARGET LENGTH: {max_words} words (range: {word_count_min}-{word_count_max}).
            """,
            "coach_explainer": f"""
                RESPONSE MODE: Coach explainer
                - Answer the question directly and precisely.
                - Do not force first-person candidate framing.
                - Do not force metrics, outcomes, or business value unless the question asks for them.
                - Focus on principles, trade-offs, decision criteria, examples, and failure modes.
                TARGET LENGTH: {max_words} words (range: {word_count_min}-{word_count_max}).
            """,
            "hybrid_dual": f"""
                RESPONSE MODE: Hybrid dual
                - Produce two short sections:
                  1. Technical answer
                  2. How to say it in the interview
                - The first section must be direct, technical, and precise.
                - The second section must translate the idea into concise interview language without sounding robotic.
                - Do not force metrics unless truly relevant.
                TARGET LENGTH: {max_words} words total (range: {word_count_min}-{word_count_max}).
            """,
        }

        delivery_mode_instructions = {
            "realtime": """
                DELIVERY MODE: Realtime
                - Answer the exact question in the first sentence.
                - Optimize for immediacy, clarity, and speakability.
                - If asked for qualities, list 2-4 qualities directly.
                - If asked for best practices, give best practices directly.
                - If asked for an explanation, explain the concept directly.
                - Avoid canned openings like 'For me' or 'As a technology leader' unless the question explicitly asks for personal perspective.
                - Avoid unrelated metrics, budget, stakeholder, or commercial framing unless relevant.
                - Keep the opening high-signal and concise.
            """,
            "live_manual": """
                DELIVERY MODE: Live Manual Quality
                - This is a live interview answer, but it should be as complete and faithful as a strong manual coaching answer.
                - Answer the exact question in the first sentence.
                - Keep it speakable aloud, but do not collapse into a generic executive biography.
                - When the ask is compound, answer the parts in order and make each part visible.
                - Prefer the normalized ask structure over broad profile summaries.
            """,
            "manual": """
                DELIVERY MODE: Manual
                - You can be more complete and polished, but still answer the actual question directly.
            """,
        }
        
        # PRIORITY: Use cv_text if available (most recent, authoritative source)
        # Fall back to database evidence only if cv_text is not provided
        evidence_lines = [f"- {e.text}" for e in context.evidence] if context.evidence else []
        
        prefer_compact_live_grounding = delivery_mode == "live_manual"

        if cv_text and not prefer_compact_live_grounding:
            # cv_text is the authoritative source - use it directly
            # Use up to 5000 chars to ensure full CV sections (e.g. Xertica) are included
            cv_snippet = cv_text[:5000].strip()
            evidence_section = f"[CV TEXT - PRIMARY SOURCE, use as grounding, do not invent facts beyond this]\n{cv_snippet}"
            print(f"[ResponseComposer] ✓ Using cv_text as PRIMARY evidence source ({len(cv_snippet)} chars)")
        elif evidence_lines:
            # No cv_text, but we have database evidence
            evidence_section = chr(10).join(evidence_lines)
            if prefer_compact_live_grounding:
                print(f"[ResponseComposer] ✓ Using compact live evidence ({len(evidence_lines)} items)")
            else:
                print(f"[ResponseComposer] Using database evidence ({len(evidence_lines)} items)")
        elif cv_text and prefer_compact_live_grounding:
            cv_snippet = cv_text[:1200].strip()
            evidence_section = f"[COMPACT CV CONTEXT]\n{cv_snippet}"
            print(f"[ResponseComposer] ✓ Using compact cv_text fallback for live ({len(cv_snippet)} chars)")
        else:
            # No cv_text and no database evidence
            evidence_section = "No evidence retrieved."
            print(f"[ResponseComposer] ⚠️ No evidence and no cv_text - risk of hallucination!")

        # HR-2: Build conversation history section
        conversation_section = ""
        if context.conversation_history:
            # Format the conversation history as role/content pairs
            history_lines = []
            history_source = (
                live_prepared_context.sanitized_turns
                if live_prepared_context is not None and live_prepared_context.sanitized_turns
                else context.conversation_history
            )
            for msg in history_source:
                role = msg.get("role") or msg.get("speaker") or "unknown"
                content = msg.get("content") or msg.get("text") or ""
                if role and content:
                    history_lines.append(f"{role.upper()}: {content}")
            conversation_section = "\n".join(history_lines)
        else:
            conversation_section = "First question in the interview."

        normalized_question_breakdown = []
        if normalized_primary_ask:
            normalized_question_breakdown.append(f"1. [primary] {normalized_primary_ask}")
        for idx, ask in enumerate(normalized_secondary_asks[:4], start=2):
            normalized_question_breakdown.append(f"{idx}. [secondary] {ask}")

        sub_questions_section = ""
        if normalized_question_breakdown:
            sub_questions_section = "\n".join(normalized_question_breakdown)
        elif sub_questions:
            sub_question_lines = []
            for idx, sub_question in enumerate(sub_questions, start=1):
                sub_question_lines.append(
                    f"{idx}. [{sub_question.priority.value}] {sub_question.text}"
                )
            sub_questions_section = "\n".join(sub_question_lines)
        else:
            sub_questions_section = "1. [must_answer] Answer the main question directly."

        compound_ask_section = ""
        if len(normalized_asks_in_order) > 1:
            ordered_asks_text = "\n".join(
                f"{idx}. {ask}" for idx, ask in enumerate(normalized_asks_in_order, start=1)
            )
            compound_ask_section = f"""
COMPOUND ASK PRIORITY RULES:
- This is a multi-part ask. Answer the parts in this normalized order:
{ordered_asks_text}
- Keep the answer focused on the asks above instead of falling back to a broad profile summary.
- If one of the asks is a broad intro/background request, keep it brief and place it after the more specific asks.
"""

        live_semantic_contract_section = ""
        if live_prepared_context is not None and live_prepared_context.asks_in_order:
            ordered_live_asks = "\n".join(
                f"{idx}. {ask}" for idx, ask in enumerate(live_prepared_context.asks_in_order, start=1)
            )
            if len(live_prepared_context.asks_in_order) == 1:
                live_semantic_contract_section = f"""
LIVE SEMANTIC CONTRACT:
- The latest interviewer block resolves to one actionable ask.
- Answer that ask directly in the first sentence.
- Do not ask for clarification.
{ordered_live_asks}
"""
            else:
                live_semantic_contract_section = f"""
LIVE SEMANTIC CONTRACT:
- The latest interviewer block contains multiple asks.
- Treat every ask below as mandatory.
- Answer them in exactly this order.
- In the FULL_RESPONSE, make the structure explicit with short transitions such as "First", "Second", and "Finally".
- Keep any broad intro ask brief and after the specific asks.
{ordered_live_asks}
"""

        normalized_brief_section = ""
        if ask_brief:
            normalized_brief_section = f"""
NORMALIZED ASK BRIEF:
- Primary ask: {normalized_primary_ask or "Not resolved"}
- Secondary asks: {", ".join(normalized_secondary_asks) if normalized_secondary_asks else "None"}
- Answer family: {normalized_family}
- Answer contract: {normalized_contract}
- Evidence policy: {ask_brief.evidence_policy.value}
- Metrics policy: {normalized_metrics_policy}
- Opening strategy: {ask_brief.opening_strategy}
- Confidence: {ask_brief.confidence:.2f}
- Why: {"; ".join(ask_brief.why) if ask_brief.why else "No explanation"}
"""

        family_contract_rules = {
            "experience_scope": """
EXPERIENCE-SCOPE RULES:
- Start with the direct experience answer, not a biography.
- Cover the asks in order.
- Use 1-2 concrete examples only.
""",
            "mixed_compound": """
MIXED-COMPOUND RULES:
- Treat the latest interviewer block as a multi-part ask.
- Answer the main ask first, then the secondary asks in order.
- Keep any broad intro request to one short sentence at most.
- Do not collapse the answer into a general professional summary.
""",
            "culture_fit": """
CULTURE-FIT RULES:
- State clearly what you look for.
- State clearly what you avoid.
- Add a brief why.
- Do not pivot into achievements unless they sharpen a preference.
""",
            "technical_concept": """
TECHNICAL-CONCEPT RULES:
- Explain the concept directly.
- Prioritize principles, trade-offs, and decision criteria.
- Avoid candidate-branding filler and biography language.
""",
            "architecture_design": """
ARCHITECTURE-DESIGN RULES:
- Start with the design goal and constraints.
- Then explain major decisions, trade-offs, and scaling/risk considerations.
""",
            "business_strategy": """
BUSINESS-STRATEGY RULES:
- Take a clear position.
- Use business reasoning and outcomes.
- Metrics/KPIs are helpful when supported by evidence.
""",
            "metrics_outcomes": """
METRICS-OUTCOMES RULES:
- Anchor the answer in measurable outcomes.
- Prefer supported KPIs and avoid vague impact claims.
""",
        }
        family_contract_section = family_contract_rules.get(normalized_family, "")
        normalized_outline_section, normalized_outline_rules = self._build_normalized_answer_outline(
            ask_brief,
            delivery_mode,
        )
        live_shape_rules = self._build_live_shape_rules(live_prepared_context)
        live_prepared_section = ""
        if live_prepared_context is not None:
            live_prepared_section = f"""
LIVE PREPARED CONTEXT:
- Resolved question: {live_prepared_context.resolved_question or "Not provided"}
- Asks in order: {", ".join(live_prepared_context.asks_in_order) if live_prepared_context.asks_in_order else "Not provided"}
- Answer focus: {live_prepared_context.answer_focus or "Answer what the interviewer is asking right now."}
- Answer style guidance: {live_prepared_context.answer_style_guidance or "Keep it direct and speakable."}
- Complexity class: {live_prepared_context.complexity_class.value}
- Answer shape: {live_prepared_context.answer_shape.value}
- Target length: {live_prepared_context.target_length} words
- Allow metrics: {"yes" if live_prepared_context.allow_metrics else "no"}
- Allow profile opening: {"yes" if live_prepared_context.allow_profile_opening else "no"}
- Require ordered coverage: {"yes" if live_prepared_context.require_ordered_coverage else "no"}
- Prepared context version: {live_prepared_context.version}
"""

        if delivery_mode == "live_manual" and live_prepared_context is not None:
            return self._build_live_manual_prompt(
                context=context,
                style=style,
                interview_type=interview_type,
                question_mode=question_mode,
                response_mode=response_mode,
                answer_intent=answer_intent,
                delivery_mode=delivery_mode,
                max_words=max_words,
                live_prepared_context=live_prepared_context,
                conversation_section=conversation_section,
                evidence_section=evidence_section,
                candidate_name=candidate_name,
                candidate_summary=candidate_summary,
                candidate_skills_text=candidate_skills_text,
                candidate_achievements_text=candidate_achievements_text,
                company_name=company_name,
                role_title=role_title,
                company_description=company_description,
                company_culture=company_culture,
                company_requirements_text=company_requirements_text,
                interviewer_name=interviewer_name,
                interviewer_focus_areas=interviewer_focus_areas,
                style_instruction=style_instructions.get(style, ""),
                response_mode_instruction=response_mode_instructions.get(response_mode, ""),
                delivery_mode_instruction=delivery_mode_instructions.get(delivery_mode, ""),
                prefer_structured_output=prefer_structured_output,
                working_draft=getattr(context, "working_draft", ""),
            )

        return f"""
You are an interview coach helping a candidate answer a question.

PRIMARY QUESTION TO ANSWER: {(live_prepared_context.resolved_question if live_prepared_context is not None and live_prepared_context.resolved_question else normalized_primary_ask) or context.question}
RAW QUESTION / LAST USER-LEVEL FRAGMENT: {context.question}
{live_semantic_contract_section}

PREVIOUS CONVERSATION (for context):
{conversation_section}

CANDIDATE EVIDENCE:
{evidence_section}
{company_filter_instruction}

CANDIDATE PROFILE:
- Name: {candidate_name or "Not provided"}
- Summary: {candidate_summary or "Not provided"}
- Skills: {candidate_skills_text}
- Certifications: {candidate_certs_text}
- Prior achievements:
{candidate_achievements_text}

TARGET COMPANY/ROLE:
- Company: {company_name or "Not provided"}
- Role: {role_title or "Not provided"}
- Industry: {company_industry or "Not provided"}
- Company description: {company_description or "Not provided"}
- Culture signals: {company_culture or "Not provided"}
- Role requirements:
{company_requirements_text}

INTERVIEWER CONTEXT:
- Name: {interviewer_name or "Not provided"}
- Role: {interviewer_role_title or "Not provided"}
- Company: {interviewer_company or "Not provided"}
- Background: {interviewer_background or "Not provided"}
- Expertise: {", ".join(interviewer_expertise[:8]) if interviewer_expertise else "Not provided"}
- Career highlights: {", ".join(interviewer_career_highlights[:5]) if interviewer_career_highlights else "Not provided"}
- Likely focus areas: {", ".join(interviewer_focus_areas[:8]) if interviewer_focus_areas else "Not provided"}
- Communication style: {interviewer_style or "Not provided"}
- Notes: {interviewer_notes or "Not provided"}

INTERVIEW TYPE: {interview_type}
{type_instruction}

STYLE: {style.value}
{style_instructions.get(style, "")}

QUESTION MODE: {question_mode}
RESPONSE MODE: {response_mode}
ANSWER INTENT: {answer_intent}
DELIVERY MODE: {delivery_mode}
STYLE REASON: {analysis.style_reason if analysis else "Default style behavior"}
METRICS REQUIRED: {"yes" if metrics_required else "no"}

STYLE GUIDANCE:
{style_instructions.get(style, "")}
{response_mode_instructions.get(response_mode, "")}
{delivery_mode_instructions.get(delivery_mode, "")}

ADAPTATION RULES:
- Ground the answer in the candidate profile and retrieved evidence; do not invent facts.
- If interviewer context exists, adapt detail level and emphasis to match likely priorities.
- Only connect to role requirements or culture when it helps answer the actual question.
- For conceptual technical questions, prioritize correctness and clarity over candidate branding.
- For business, KPI, leadership, executive, or commercial questions, keep value and stakeholder framing.
- If the question asks for principles or qualities, answer with principles or qualities first.
- If the question asks for trade-offs, compare options explicitly.
- If no supporting metric exists, do not fabricate one.
- For preference, culture, team, or "what are you looking for" questions:
  answer in plain, direct interview language.
- In those preference/culture-fit questions, do NOT default to achievements, KPIs, or long career summaries.
- Mention past examples only briefly and only if they sharpen one preference.
- If the interviewer asks what you do not like, name the specific anti-patterns clearly instead of pivoting into a biography.
{normalized_brief_section}
{compound_ask_section}
{live_semantic_contract_section}
{family_contract_section}
{live_prepared_section}
{live_shape_rules}

NORMALIZED ANSWER OUTLINE (MANDATORY WHEN PRESENT):
{normalized_outline_section or "No explicit outline inferred."}

NORMALIZED ANSWER RULES:
{normalized_outline_rules or "- No additional normalized rules."}

QUESTION BREAKDOWN:
{sub_questions_section}

COMPOUND QUESTION RULES:
- If the interviewer asked multiple related questions, answer the MUST_ANSWER parts first and in order.
- When a broad intro prompt like "tell me a little bit about yourself" appears alongside more specific asks, keep the intro to one short sentence and spend most of the answer on the specific asks.
- Do not collapse a compound question into a generic biography.
- The opening sentence should reflect the real focus of the latest interviewer block, not just the last fragment.
{compound_ask_section}

CRITICAL LENGTH REQUIREMENT:
Generate a response of approximately {max_words} words.
The response MUST be complete and well-formed. Do not cut off mid-sentence.
If you cannot fit everything, prioritize the most relevant points.

OUTPUT FORMAT (MANDATORY):
[BULLETS]
- Bullet 1 must be the direct answer or thesis.
- Bullet 2-4 must be the strongest supporting points only.
[/BULLETS]
[FULL_RESPONSE]
For interview_answer: one polished interview-ready response that starts with the direct answer.
For coach_explainer: one direct, precise explanation.
For hybrid_dual: use exactly this structure:
Technical answer:
...

How to say it in the interview:
...
[/FULL_RESPONSE]

For realtime delivery, the opening line must already be usable aloud in the interview.
Generate the most useful coaching output for the detected response mode.
"""
    
    def _extract_metrics_from_evidence(self, evidence: list) -> list[str]:
        """Extract key metrics from evidence text"""
        import re
        metrics = []
        
        for e in evidence:
            # Look for numbers with context
            matches = re.findall(r'\b(\d+(?:\.\d+)?(?:\+)?\s*(?:engineers?|years?|months?|%|x|times?))\b', e.text.lower())
            metrics.extend(matches[:2])
        
        return list(set(metrics))[:4]
    
    def _extract_mentioned_companies(
        self, 
        question: str, 
        achievements: list
    ) -> list[str]:
        """
        Extract company names mentioned in the question.
        
        Looks for explicit company mentions and cross-references with
        candidate achievements to identify which company the question refers to.
        """
        import re
        
        if not question:
            return []
        
        question_lower = question.lower()
        
        # Known company name patterns to look for
        # These should ideally come from the candidate's profile, but we
        # also check common company name patterns in the question
        common_companies = [
            "accenture", "google", "amazon", "microsoft", "meta", "facebook",
            "apple", "netflix", "uber", "airbnb", "stripe", "square", "shopify",
            "salesforce", "oracle", "ibm", "intel", "cisco", "nvidia", "tesla",
            "jp morgan", "goldman sachs", "morgan stanley", "bank of america",
            "startup", "previous", "former", "current", "prior"
        ]
        
        mentioned = []
        
        # Check for common company mentions in question
        for company in common_companies:
            if company in question_lower:
                # Capitalize properly for display
                if company == "jp morgan":
                    mentioned.append("JP Morgan")
                elif company == "goldman sachs":
                    mentioned.append("Goldman Sachs")
                elif company == "bank of america":
                    mentioned.append("Bank of America")
                else:
                    mentioned.append(company.title())
        
        # Also try to extract any company names from achievements if they contain
        # explicit company references
        if achievements:
            # Look for company names in achievement text
            for achievement in achievements:
                if isinstance(achievement, str):
                    # Check if any known company is mentioned in achievements
                    for company in common_companies:
                        if company in achievement.lower():
                            # Only add if also in question (correlates the two)
                            if company in question_lower:
                                if company == "jp morgan":
                                    mentioned.append("JP Morgan")
                                elif company == "goldman sachs":
                                    mentioned.append("Goldman Sachs")
                                elif company == "bank of america":
                                    mentioned.append("Bank of America")
                                else:
                                    mentioned.append(company.title())
        
        # If no explicit company found but question asks about "previous" or "prior",
        # we need to signal that we should not use current company info
        if any(word in question_lower for word in ["previous", "prior", "former", "before", "at your last"]):
            if "Previous" not in mentioned and "Prior" not in mentioned:
                mentioned.append("PREVIOUS_COMPANY")
        
        return list(set(mentioned))[:3]  # Max 3 companies


class MockResponseComposer(ResponseComposer):
    """
    Mock composer for testing - explicitly always returns demo responses.
    """
    
    def __init__(self):
        super().__init__(mode=ComposerMode.DEMO, use_llm=False)
    
    async def compose(
        self,
        context: AssembledContext,
        on_bullets: Optional[Callable[[GeneratedResponse], Awaitable[None] | None]] = None,
    ) -> GeneratedResponse:
        """Return mock response - explicitly for testing"""
        return await self._compose_demo(context, on_bullets=on_bullets)
