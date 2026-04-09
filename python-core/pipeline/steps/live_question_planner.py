"""
Interview Coach - Live Question Planner

Builds a live-only prepared context from the latest finalized interviewer
turns.

The live brain should stay simple:
- use the latest effective window of 1..5 interviewer turns
- clean only obvious STT noise and wrappers
- understand what the interviewer is asking in that block
- prepare a speakable answer draft in parallel
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Callable, Optional

from adapters.llm_adapter import (
    AnthropicLLMAdapter,
    OllamaLLMAdapter,
    OpenAILLMAdapter,
    _get_runtime_config,
    get_llm_adapter,
)
from contracts.models import (
    AskBrief,
    AskFamily,
    AnswerShape,
    ComplexityClass,
    LivePreparedContext,
    MetricsPolicy,
    PlannerResult,
)
from pipeline.steps.ask_normalizer import AskNormalizer


@dataclass
class LiveQuestionPlannerConfig:
    max_turns: int = 5
    max_secondary_asks: int = 3
    llm_alias: str = "fast"
    use_llm: bool = True
    llm_timeout_sec: float = 4.0
    llm_temperature: float = 0.1
    llm_max_tokens: int = 320
    min_llm_confidence: float = 0.45
    llm_draft_timeout_sec: float = 3.0


class LiveQuestionPlanner:
    """Prepare a live-only ask plan from the latest interviewer turns."""

    def __init__(
        self,
        ask_normalizer: Optional[AskNormalizer] = None,
        config: Optional[LiveQuestionPlannerConfig] = None,
        adapter_factory: Optional[Callable[[str], Any]] = None,
    ):
        self.ask_normalizer = ask_normalizer or AskNormalizer()
        self.config = config or LiveQuestionPlannerConfig()
        self._adapter_factory = adapter_factory or get_llm_adapter

    def build_signature(self, turns: list[dict[str, Any]]) -> str:
        sanitized_turns = self._sanitize_turns(turns)
        if not sanitized_turns:
            return ""
        serialized = [
            " ".join(str(turn.get("text", "")).lower().split()).strip()
            for turn in sanitized_turns
            if str(turn.get("text", "")).strip()
        ]
        return "\n".join(serialized).strip()

    def prepare_base(
        self,
        *,
        session_id: str,
        raw_turns: list[dict[str, Any]],
        interview_config: dict[str, Any],
        mode: str,
    ) -> Optional[LivePreparedContext]:
        started = perf_counter()

        raw_turn_window = list(raw_turns[-self.config.max_turns :])
        sanitized_turns = self._sanitize_turns(raw_turn_window)
        if not sanitized_turns:
            return None

        ask_block = self._build_ask_block(sanitized_turns)
        if not ask_block:
            return None

        signature = self.build_signature(raw_turn_window)
        deterministic_plan = self._build_deterministic_plan(
            ask_block=ask_block,
            sanitized_turns=sanitized_turns,
        )
        planner_result = deterministic_plan

        question_text = planner_result.resolved_question or planner_result.primary_ask or ask_block
        ask_brief = self._build_live_ask_brief(planner_result)

        latency_ms = int((perf_counter() - started) * 1000)
        request_payload = {
            "question": question_text,
            "session_id": session_id,
            "candidate_profile": interview_config.get("candidate") or {},
            "company_info": interview_config.get("company") or {},
            "interviewer_profile": interview_config.get("interviewer") or {},
            "style_id": interview_config.get("style_id") or interview_config.get("response_style") or "professional",
            "language": interview_config.get("language_preference") or "en",
            "mode": mode,
            "history_count": len(sanitized_turns),
            "profile_id": interview_config.get("profile_id"),
            "company_context_id": interview_config.get("company_context_id"),
            "interviewer_context_id": interview_config.get("interviewer_context_id"),
            "max_words": planner_result.target_length,
            "interview_type": interview_config.get("interview_type"),
            "conversation_history": sanitized_turns,
            "preserve_question_text": True,
        }

        latest_turn_text = (
            " ".join(str(raw_turn_window[-1].get("text") or raw_turn_window[-1].get("content") or "").split()).strip()
            if raw_turn_window
            else ""
        )
        latest_turn_included = bool(
            latest_turn_text
            and sanitized_turns
            and sanitized_turns[-1].get("text", "") == self._sanitize_turn_text(latest_turn_text)
        )

        return LivePreparedContext(
            raw_turns=raw_turn_window,
            sanitized_turns=sanitized_turns,
            turn_window_size=len(sanitized_turns),
            effective_turn_count=len(sanitized_turns),
            latest_turn_included=latest_turn_included,
            signature=signature,
            semantic_signature="",
            resolved_question=planner_result.resolved_question,
            asks_in_order=planner_result.asks_in_order,
            primary_ask=planner_result.primary_ask,
            secondary_asks=planner_result.secondary_asks,
            ordered_focus=planner_result.ordered_focus,
            answer_focus=planner_result.answer_focus,
            answer_style_guidance=planner_result.answer_style_guidance,
            draft_answer=planner_result.draft_answer,
            answer_family=ask_brief.answer_family,
            answer_contract=ask_brief.answer_contract,
            opening_strategy=ask_brief.opening_strategy,
            metrics_policy=ask_brief.metrics_policy,
            complexity_class=planner_result.complexity_class,
            answer_shape=planner_result.answer_shape,
            target_length=planner_result.target_length,
            allow_metrics=planner_result.allow_metrics,
            allow_profile_opening=planner_result.allow_profile_opening,
            require_ordered_coverage=planner_result.require_ordered_coverage,
            question_text=question_text,
            request_payload=request_payload,
            ask_brief=ask_brief,
            confidence=max(ask_brief.confidence, planner_result.confidence),
            planner_confidence=planner_result.confidence,
            latency_ms=latency_ms,
            time_to_base_plan_ms=latency_ms,
            time_to_semantic_plan_ms=0,
            fallback_used=False,
            artifact_sanitized=self._artifact_sanitized(raw_turn_window, sanitized_turns),
            sanitized_turn_count=len(sanitized_turns),
            plan_stage="base",
            planner_source=planner_result.planner_source,
            planner_provider=planner_result.planner_provider,
            planner_model=planner_result.planner_model,
            reasoning_summary=planner_result.reasoning_summary,
        )

    async def enrich(
        self,
        *,
        base_context: LivePreparedContext,
        interview_config: dict[str, Any],
        mode: str,
    ) -> Optional[LivePreparedContext]:
        if not self.config.use_llm:
            return None
        if not base_context.sanitized_turns:
            return None

        started = perf_counter()
        ask_block = self._build_ask_block(base_context.sanitized_turns)
        if not ask_block:
            return None

        deterministic_plan = self._build_deterministic_plan(
            ask_block=ask_block,
            sanitized_turns=base_context.sanitized_turns,
        )
        planner_result = await self._resolve_plan(
            ask_block=ask_block,
            sanitized_turns=base_context.sanitized_turns,
            deterministic_plan=deterministic_plan,
            language=interview_config.get("language_preference") or "en",
            interview_config=interview_config,
        )
        if planner_result.planner_source != "llm_fast":
            return None

        question_text = planner_result.resolved_question or planner_result.primary_ask or ask_block
        ask_brief = self._build_live_ask_brief(planner_result)
        semantic_latency_ms = int((perf_counter() - started) * 1000)

        request_payload = dict(base_context.request_payload or {})
        request_payload.update(
            {
                "question": question_text,
                "history_count": len(base_context.sanitized_turns),
                "max_words": planner_result.target_length,
                "conversation_history": base_context.sanitized_turns,
                "preserve_question_text": True,
            }
        )

        return base_context.model_copy(
            update={
                "primary_ask": planner_result.primary_ask,
                "secondary_asks": planner_result.secondary_asks,
                "ordered_focus": planner_result.ordered_focus,
                "resolved_question": planner_result.resolved_question,
                "asks_in_order": planner_result.asks_in_order,
                "answer_focus": planner_result.answer_focus,
                "answer_style_guidance": planner_result.answer_style_guidance,
                "draft_answer": planner_result.draft_answer,
                "answer_family": ask_brief.answer_family,
                "answer_contract": ask_brief.answer_contract,
                "opening_strategy": ask_brief.opening_strategy,
                "metrics_policy": ask_brief.metrics_policy,
                "complexity_class": planner_result.complexity_class,
                "answer_shape": planner_result.answer_shape,
                "target_length": planner_result.target_length,
                "allow_metrics": planner_result.allow_metrics,
                "allow_profile_opening": planner_result.allow_profile_opening,
                "require_ordered_coverage": planner_result.require_ordered_coverage,
                "question_text": question_text,
                "request_payload": request_payload,
                "ask_brief": ask_brief,
                "confidence": max(ask_brief.confidence, planner_result.confidence),
                "planner_confidence": planner_result.confidence,
                "latency_ms": base_context.time_to_base_plan_ms + semantic_latency_ms,
                "time_to_semantic_plan_ms": semantic_latency_ms,
                "fallback_used": False,
                "plan_stage": "semantic",
                "planner_source": planner_result.planner_source,
                "planner_provider": planner_result.planner_provider,
                "planner_model": planner_result.planner_model,
                "reasoning_summary": planner_result.reasoning_summary,
                "semantic_signature": base_context.signature,
            }
        )

    async def prepare(
        self,
        *,
        session_id: str,
        raw_turns: list[dict[str, Any]],
        interview_config: dict[str, Any],
        mode: str,
    ) -> Optional[LivePreparedContext]:
        base_context = self.prepare_base(
            session_id=session_id,
            raw_turns=raw_turns,
            interview_config=interview_config,
            mode=mode,
        )
        if base_context is None:
            return None
        drafted = await self.draft_from_prepared_context(
            prepared_context=base_context,
            interview_config=interview_config,
        )
        return drafted or base_context

    async def _resolve_plan(
        self,
        *,
        ask_block: str,
        sanitized_turns: list[dict[str, Any]],
        deterministic_plan: PlannerResult,
        language: str,
        interview_config: dict[str, Any],
    ) -> PlannerResult:
        if not self.config.use_llm:
            return deterministic_plan

        llm_plan = await self._plan_with_llm(
            ask_block=ask_block,
            sanitized_turns=sanitized_turns,
            language=language,
            deterministic_plan=deterministic_plan,
            interview_config=interview_config,
        )
        if llm_plan is None:
            return deterministic_plan
        if llm_plan.confidence < self.config.min_llm_confidence:
            return deterministic_plan
        return llm_plan

    def _build_deterministic_plan(
        self,
        *,
        ask_block: str,
        sanitized_turns: list[dict[str, Any]],
    ) -> PlannerResult:
        primary_ask, secondary_asks, ordered_focus = self._plan_focus(
            ask_block=ask_block,
            sanitized_turns=sanitized_turns,
        )
        (
            question_family,
            complexity_class,
            answer_shape,
            target_length,
            allow_metrics,
            allow_profile_opening,
            require_ordered_coverage,
            confidence,
        ) = self._minimal_live_defaults(ordered_focus)
        resolved_question = self._build_resolved_question(ordered_focus)
        answer_focus = (
            "Answer the direct interviewer ask."
            if len(ordered_focus) <= 1
            else "Answer the interviewer asks in order, without dropping any of the asks in the latest turn window."
        )
        answer_style_guidance = (
            "Keep it direct and speakable."
            if len(ordered_focus) <= 1
            else "Keep the structure visible and answer each ask in order."
        )
        return PlannerResult(
            resolved_question=resolved_question,
            asks_in_order=ordered_focus,
            primary_ask=primary_ask,
            secondary_asks=secondary_asks,
            ordered_focus=ordered_focus,
            answer_focus=answer_focus,
            answer_style_guidance=answer_style_guidance,
            question_family=question_family,
            complexity_class=complexity_class,
            answer_shape=answer_shape,
            target_length=target_length,
            allow_metrics=allow_metrics,
            allow_profile_opening=allow_profile_opening,
            require_ordered_coverage=require_ordered_coverage,
            confidence=confidence,
            reasoning_summary="Semantic live plan prepared from the current finalized turn window.",
            planner_source="deterministic",
        )

    async def _plan_with_llm(
        self,
        *,
        ask_block: str,
        sanitized_turns: list[dict[str, Any]],
        language: str,
        deterministic_plan: PlannerResult,
        interview_config: dict[str, Any],
    ) -> Optional[PlannerResult]:
        adapter = self._get_planner_adapter()
        if adapter is None:
            return None
        if adapter.__class__.__name__.lower().startswith("demo"):
            return None

        prompt = self._build_llm_prompt(
            sanitized_turns=sanitized_turns,
            language=language,
            deterministic_plan=deterministic_plan,
            interview_config=interview_config,
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a live interview question planner. "
                    "Analyze the latest finalized interviewer turns as a single block and return only valid JSON. "
                    "The interviewer has already asked the question. "
                    "Write the draft as the candidate speaking in first person. "
                    "Do not return coaching advice, interview tactics, or meta commentary. "
                    "Do not reply with placeholders like 'go ahead', 'I'm ready for your question', "
                    "'happy to answer', or clarification prompts when the ask is actionable."
                ),
            },
            {"role": "user", "content": prompt},
        ]
        config = {
            "temperature": self.config.llm_temperature,
            "max_tokens": self.config.llm_max_tokens,
        }

        try:
            raw = await asyncio.wait_for(
                adapter.generate(messages, config),
                timeout=self.config.llm_timeout_sec,
            )
            payload = self._extract_json_payload(raw)
            if not payload:
                return await self._fallback_to_direct_draft(
                    adapter=adapter,
                    deterministic_plan=deterministic_plan,
                    sanitized_turns=sanitized_turns,
                    interview_config=interview_config,
                    language=language,
                    reasoning_summary="Planner JSON was missing, so the live brain used a direct-draft fallback.",
                )
            candidate = PlannerResult.model_validate_json(payload)
            normalized = self._normalize_planner_result(
                candidate,
                deterministic_plan,
            )
            if not self._is_usable_draft_answer(
                normalized.draft_answer,
                normalized.ordered_focus or deterministic_plan.ordered_focus,
            ):
                print(
                    "[LiveQuestionPlanner] llm planner rejected unusable draft "
                    f"resolved='{(normalized.resolved_question or '')[:160]}' "
                    f"draft='{(normalized.draft_answer or '')[:160]}'"
                )
                return await self._fallback_to_direct_draft(
                    adapter=adapter,
                    deterministic_plan=normalized,
                    sanitized_turns=sanitized_turns,
                    interview_config=interview_config,
                    language=language,
                    reasoning_summary="Planner draft was unusable, so the live brain used a direct-draft fallback.",
                )
            return normalized.model_copy(
                update={
                    "planner_source": "llm_fast",
                    "planner_provider": self._infer_provider_name(adapter),
                    "planner_model": getattr(adapter, "model", "") or "",
                }
            )
        except Exception as exc:
            print(
                "[LiveQuestionPlanner] llm planner fallback "
                f"type={type(exc).__name__} detail={repr(exc)}"
            )
            return await self._fallback_to_direct_draft(
                adapter=adapter,
                deterministic_plan=deterministic_plan,
                sanitized_turns=sanitized_turns,
                interview_config=interview_config,
                language=language,
                reasoning_summary=f"Planner JSON generation failed with {type(exc).__name__}; used direct-draft fallback.",
            )

    async def _fallback_to_direct_draft(
        self,
        *,
        adapter: Any,
        deterministic_plan: PlannerResult,
        sanitized_turns: list[dict[str, Any]],
        interview_config: dict[str, Any],
        language: str,
        reasoning_summary: str,
        strict: bool = True,
    ) -> Optional[PlannerResult]:
        direct_prompt = self._build_direct_draft_prompt(
            sanitized_turns=sanitized_turns,
            deterministic_plan=deterministic_plan,
            interview_config=interview_config,
            language=language,
        )
        config = {
            "temperature": self.config.llm_temperature,
            "max_tokens": max(160, min(280, deterministic_plan.target_length + 70)),
        }
        try:
            raw = await asyncio.wait_for(
                adapter.generate(
                    [
                        {
                            "role": "system",
                            "content": (
                                "You are helping a candidate answer a live interview question. "
                                "Write only the answer the candidate should say out loud right now. "
                                "No advice. No meta commentary. No placeholders."
                            ),
                        },
                        {"role": "user", "content": direct_prompt},
                    ],
                    config,
                ),
                timeout=min(self.config.llm_draft_timeout_sec, self.config.llm_timeout_sec),
            )
        except Exception as exc:
            print(
                "[LiveQuestionPlanner] direct draft fallback failed "
                f"type={type(exc).__name__} detail={repr(exc)}"
            )
            return None

        draft = self._clean_draft_answer(self._compact_text(str(raw or "").strip(), limit=2200))
        rejection_reason = ""
        is_usable = (
            self._is_usable_draft_answer(draft, deterministic_plan.ordered_focus)
            if strict
            else self._is_best_effort_draft_answer(draft)
        )
        if not is_usable:
            rejection_reason = self._draft_rejection_reason(draft, strict=strict)
            print(
                "[LiveQuestionPlanner] direct draft rejected "
                f"strict={strict} reason={rejection_reason or 'unknown'} "
                f"draft='{draft[:180]}'"
            )
            return None

        return deterministic_plan.model_copy(
            update={
                "draft_answer": draft,
                "confidence": max(deterministic_plan.confidence, 0.68 if strict else 0.55),
                "reasoning_summary": reasoning_summary,
                "planner_source": "llm_fast",
                "planner_provider": self._infer_provider_name(adapter),
                "planner_model": getattr(adapter, "model", "") or "",
            }
        )

    async def draft_from_prepared_context(
        self,
        *,
        prepared_context: LivePreparedContext,
        interview_config: dict[str, Any],
    ) -> Optional[LivePreparedContext]:
        started = perf_counter()
        adapter = self._get_planner_adapter()
        if adapter is None or not prepared_context.sanitized_turns:
            return None

        deterministic_plan = PlannerResult(
            resolved_question=prepared_context.resolved_question,
            asks_in_order=list(prepared_context.asks_in_order or prepared_context.ordered_focus or []),
            primary_ask=prepared_context.primary_ask,
            secondary_asks=list(prepared_context.secondary_asks or []),
            ordered_focus=list(prepared_context.ordered_focus or prepared_context.asks_in_order or []),
            answer_focus=prepared_context.answer_focus,
            answer_style_guidance=prepared_context.answer_style_guidance,
            question_family=prepared_context.answer_family,
            complexity_class=prepared_context.complexity_class,
            answer_shape=prepared_context.answer_shape,
            target_length=prepared_context.target_length,
            allow_metrics=prepared_context.allow_metrics,
            allow_profile_opening=prepared_context.allow_profile_opening,
            require_ordered_coverage=prepared_context.require_ordered_coverage,
            confidence=max(prepared_context.planner_confidence, prepared_context.confidence),
            reasoning_summary=prepared_context.reasoning_summary,
            planner_source=prepared_context.planner_source,
            planner_provider=prepared_context.planner_provider,
            planner_model=prepared_context.planner_model,
        )

        drafted = await self._fallback_to_direct_draft(
            adapter=adapter,
            deterministic_plan=deterministic_plan,
            sanitized_turns=prepared_context.sanitized_turns,
            interview_config=interview_config,
            language=interview_config.get("language_preference") or "en",
            reasoning_summary="Used direct-draft live brain fallback from the prepared turn window.",
        )
        if drafted is None or not str(drafted.draft_answer or "").strip():
            return None

        semantic_latency_ms = int((perf_counter() - started) * 1000)

        return prepared_context.model_copy(
            update={
                "draft_answer": drafted.draft_answer,
                "confidence": max(prepared_context.confidence, drafted.confidence),
                "planner_confidence": max(prepared_context.planner_confidence, drafted.confidence),
                "latency_ms": prepared_context.time_to_base_plan_ms + semantic_latency_ms,
                "time_to_semantic_plan_ms": semantic_latency_ms,
                "plan_stage": "semantic",
                "planner_source": drafted.planner_source,
                "planner_provider": drafted.planner_provider,
                "planner_model": drafted.planner_model,
                "reasoning_summary": drafted.reasoning_summary,
                "semantic_signature": prepared_context.signature,
            }
        )

    async def write_best_effort_from_prepared_context(
        self,
        *,
        prepared_context: LivePreparedContext,
        interview_config: dict[str, Any],
    ) -> Optional[LivePreparedContext]:
        adapter = self._get_planner_adapter()
        if adapter is None or not prepared_context.sanitized_turns:
            return None

        deterministic_plan = PlannerResult(
            resolved_question=prepared_context.resolved_question,
            asks_in_order=list(prepared_context.asks_in_order or prepared_context.ordered_focus or []),
            primary_ask=prepared_context.primary_ask,
            secondary_asks=list(prepared_context.secondary_asks or []),
            ordered_focus=list(prepared_context.ordered_focus or prepared_context.asks_in_order or []),
            answer_focus=prepared_context.answer_focus,
            answer_style_guidance=prepared_context.answer_style_guidance,
            question_family=prepared_context.answer_family,
            complexity_class=prepared_context.complexity_class,
            answer_shape=prepared_context.answer_shape,
            target_length=prepared_context.target_length,
            allow_metrics=prepared_context.allow_metrics,
            allow_profile_opening=prepared_context.allow_profile_opening,
            require_ordered_coverage=prepared_context.require_ordered_coverage,
            confidence=max(prepared_context.planner_confidence, prepared_context.confidence),
            reasoning_summary=prepared_context.reasoning_summary,
            planner_source=prepared_context.planner_source,
            planner_provider=prepared_context.planner_provider,
            planner_model=prepared_context.planner_model,
        )

        drafted = await self._fallback_to_direct_draft(
            adapter=adapter,
            deterministic_plan=deterministic_plan,
            sanitized_turns=prepared_context.sanitized_turns,
            interview_config=interview_config,
            language=interview_config.get("language_preference") or "en",
            reasoning_summary="Used best-effort live emergency writer from the prepared turn window.",
            strict=False,
        )
        if drafted is None or not str(drafted.draft_answer or "").strip():
            return None

        return prepared_context.model_copy(
            update={
                "draft_answer": drafted.draft_answer,
                "confidence": max(prepared_context.confidence, drafted.confidence),
                "planner_confidence": max(prepared_context.planner_confidence, drafted.confidence),
                "planner_source": drafted.planner_source,
                "planner_provider": drafted.planner_provider,
                "planner_model": drafted.planner_model,
                "reasoning_summary": drafted.reasoning_summary,
            }
        )

    def _clean_draft_answer(self, text: str) -> str:
        cleaned = " ".join(str(text or "").split()).strip()
        if not cleaned:
            return ""

        paragraphs = [
            " ".join(paragraph.split()).strip()
            for paragraph in re.split(r"\n\s*\n", str(text or ""))
            if " ".join(paragraph.split()).strip()
        ]
        deduped_paragraphs: list[str] = []
        seen: set[str] = set()
        for paragraph in paragraphs:
            key = paragraph.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped_paragraphs.append(paragraph)
        if deduped_paragraphs:
            cleaned = "\n\n".join(deduped_paragraphs)

        sentences = [
            " ".join(sentence.split()).strip()
            for sentence in re.split(r"(?<=[.!?])\s+", cleaned)
            if " ".join(sentence.split()).strip()
        ]
        compact_sentences: list[str] = []
        for sentence in sentences:
            key = sentence.lower().rstrip(".!?")
            if compact_sentences and compact_sentences[-1].lower().rstrip(".!?") == key:
                continue
            compact_sentences.append(sentence)
        return " ".join(compact_sentences).strip()

    def _get_planner_adapter(self) -> Any:
        if self._adapter_factory is not get_llm_adapter:
            return self._adapter_factory(self.config.llm_alias)

        try:
            from adapters.provider_registry import get_registry

            cfg = get_registry().get_llm_config(alias=self.config.llm_alias)
            provider = (cfg.provider or "").strip().lower()
            model = (cfg.model or "").strip()
            runtime_config = _get_runtime_config() or {}
            runtime_llm = runtime_config.get("llm") or {}
            runtime_provider = (runtime_llm.get("provider") or "").strip().lower()
            runtime_api_key = runtime_llm.get("api_key") or ""
            runtime_enabled = bool(runtime_llm.get("enabled"))
            runtime_model = (runtime_llm.get("model") or "").strip()

            def _live_fast_model(provider_name: str, configured_model: str) -> str:
                provider_name = (provider_name or "").strip().lower()
                configured_model = (configured_model or "").strip()
                if provider_name == "anthropic":
                    return configured_model if "haiku" in configured_model.lower() else "claude-haiku-4-5-20251001"
                if provider_name == "openai":
                    lowered = configured_model.lower()
                    return configured_model if lowered in {"gpt-4o-mini", "gpt-4.1-mini"} else "gpt-4o-mini"
                return configured_model

            def _runtime_adapter() -> Any:
                if not runtime_enabled or not runtime_api_key:
                    return None
                if runtime_provider == "anthropic":
                    adapter = AnthropicLLMAdapter(model=_live_fast_model(runtime_provider, runtime_model))
                    adapter.api_key = runtime_api_key
                    return adapter
                if runtime_provider == "openai":
                    adapter = OpenAILLMAdapter(model=_live_fast_model(runtime_provider, runtime_model))
                    adapter.api_key = runtime_api_key
                    return adapter
                return None

            if provider == "anthropic":
                api_key = os.getenv("ANTHROPIC_API_KEY") or (
                    runtime_api_key if runtime_enabled and runtime_provider == "anthropic" else ""
                )
                if api_key:
                    adapter = AnthropicLLMAdapter(model=_live_fast_model(provider, model))
                    adapter.api_key = api_key
                    return adapter
            if provider == "openai":
                api_key = os.getenv("OPENAI_API_KEY") or (
                    runtime_api_key if runtime_enabled and runtime_provider == "openai" else ""
                )
                if api_key:
                    adapter = OpenAILLMAdapter(model=_live_fast_model(provider, model))
                    adapter.api_key = api_key
                    return adapter
            if provider == "ollama":
                runtime_adapter = _runtime_adapter()
                if runtime_adapter is not None:
                    print(
                        "[LiveQuestionPlanner] using runtime llm for planner "
                        f"runtime_provider={runtime_provider} runtime_model='{(runtime_model or '')[:80]}' "
                        f"configured_provider={provider} configured_model='{model[:80]}'"
                    )
                    return runtime_adapter
                base_url = runtime_llm.get("base_url") or os.getenv("OLLAMA_BASE_URL") or "http://localhost:11434"
                return OllamaLLMAdapter(model=model or "llama3.2", base_url=base_url)
            runtime_adapter = _runtime_adapter()
            if runtime_adapter is not None:
                print(
                    "[LiveQuestionPlanner] using runtime llm fallback for planner "
                    f"runtime_provider={runtime_provider} runtime_model='{(runtime_model or '')[:80]}' "
                    f"configured_provider={provider} configured_model='{model[:80]}'"
                )
                return runtime_adapter
        except Exception as exc:
            print(f"[LiveQuestionPlanner] fast adapter resolution fallback: {exc}")

        return self._adapter_factory(self.config.llm_alias)

    def _build_llm_prompt(
        self,
        *,
        sanitized_turns: list[dict[str, Any]],
        language: str,
        deterministic_plan: PlannerResult,
        interview_config: dict[str, Any],
    ) -> str:
        turns_text = "\n".join(
            f"{idx}. {turn.get('text', '')}"
            for idx, turn in enumerate(sanitized_turns, start=1)
        )
        compact_context = self._build_compact_live_context(
            interview_config=interview_config,
            target_length=deterministic_plan.target_length,
        )
        return f"""
Analyze these latest finalized interviewer turns as a single interviewer ask block.

Your job:
1. Understand what the interviewer is actually asking right now.
2. If there is one ask, keep it as one ask.
3. If there are multiple asks, preserve them in the order they should be answered.
4. Write a strong, speakable interview answer draft from the candidate perspective.

Rules:
- Use only the turns below to understand the ask.
- Treat all turns as interviewer speech.
- The interviewer turns are the source of truth.
- Use the supporting context only to strengthen the answer, never to replace the ask.
- If the ask is simple, answer it simply and directly.
- If the ask is compound, answer every ask in order with visible transitions.
- If the ask is compound, do not answer only the last ask.
- If one ask contains multiple requested dimensions or criteria, cover those dimensions explicitly.
- Do not ask for clarification if the ask is actionable.
- Do not turn the answer into a biography, company pitch, or generic profile summary unless the interviewer asked for that.
- The draft_answer must be something the candidate can say aloud right now.
- Do not explain how to answer, do not narrate body language, and do not give interview advice.
- Start with the answer itself, not with a career summary, unless the interviewer explicitly asked for background.
- Do not invent experience, metrics, or preferences not supported by the provided context.
- Keep the draft answer concise, speakable, and under about {deterministic_plan.target_length} words.
- Return ONLY JSON, no markdown.

Metadata:
- language: {language or "en"}

Turns:
{turns_text}

Supporting answer context:
{compact_context}

Return JSON with exactly these fields:
{{
  "resolved_question": "single clean question or ordered ask summary",
  "asks_in_order": ["ask 1", "ask 2"],
  "answer_focus": "short note about what the answer should focus on",
  "answer_style_guidance": "short note about how the answer should be shaped",
  "draft_answer": "speakable interview answer from the candidate perspective",
  "confidence": 0.0,
  "reasoning_summary": "short explanation"
}}
"""

    def _build_direct_draft_prompt(
        self,
        *,
        sanitized_turns: list[dict[str, Any]],
        deterministic_plan: PlannerResult,
        interview_config: dict[str, Any],
        language: str,
    ) -> str:
        turns_text = "\n".join(
            f"{idx}. {turn.get('text', '')}"
            for idx, turn in enumerate(sanitized_turns, start=1)
        )
        asks_text = "\n".join(
            f"{idx}. {ask}" for idx, ask in enumerate(deterministic_plan.ordered_focus or [], start=1)
        ) or "1. Answer the interviewer ask directly."
        compact_context = self._build_compact_live_context(
            interview_config=interview_config,
            target_length=deterministic_plan.target_length,
        )
        return f"""
Write the candidate's spoken answer for this live interview moment.

Interviewer turns:
{turns_text}

Best current understanding of the asks:
{asks_text}

Support context:
{compact_context}

Rules:
- The interviewer turns are the source of truth.
- Answer what is being asked now.
- If there is one ask, answer it directly in the first sentence.
- If there are multiple asks, answer them in order with short transitions like First, Second, Finally.
- If one ask includes multiple dimensions or criteria, cover them explicitly.
- Use the support context only to strengthen the answer.
- Do not turn the answer into biography, coaching advice, or meta commentary.
- Do not ask for clarification if the ask is actionable.
- Start with the requested answer, not with a generic career summary, unless the interviewer explicitly asked for background.
- Language: {language or "en"}.
- Keep it natural, interview-ready, and around {max(60, min(deterministic_plan.target_length, 180))} words.
"""

    def _is_usable_draft_answer(
        self,
        draft_answer: str,
        ordered_focus: list[str],
    ) -> bool:
        cleaned = " ".join(str(draft_answer or "").split()).strip()
        if len(cleaned.split()) < 8:
            return False

        if self._looks_like_placeholder_or_meta(cleaned):
            return False

        if not ordered_focus:
            return True
        return True

    def _is_best_effort_draft_answer(self, draft_answer: str) -> bool:
        cleaned = " ".join(str(draft_answer or "").split()).strip()
        if len(cleaned.split()) < 5:
            return False
        return not self._looks_like_placeholder_or_meta(cleaned)

    def _draft_rejection_reason(self, draft_answer: str, *, strict: bool) -> str:
        cleaned = " ".join(str(draft_answer or "").split()).strip()
        min_words = 8 if strict else 5
        if len(cleaned.split()) < min_words:
            return "too_short"
        if self._looks_like_placeholder_or_meta(cleaned):
            return "placeholder_or_meta"
        return "unusable"

    @staticmethod
    def _looks_like_placeholder_or_meta(text: str) -> bool:
        lowered = " ".join(str(text or "").lower().split()).strip()
        placeholder_markers = (
            "go ahead",
            "i'm ready for your question",
            "i am ready for your question",
            "happy to answer",
            "happy to walk through",
            "what would you like me to tell you about",
            "what would you like me to know more about",
            "could you clarify",
            "can you clarify",
            "just want to make sure",
            "i want to make sure i give you the most useful answer",
        )
        if any(marker in lowered for marker in placeholder_markers):
            return True

        meta_answer_markers = (
            "i'd pause",
            "i would pause",
            "wait to see if you continue",
            "this approach prioritizes",
            "professional prompt shows",
            "gives you control of the conversation",
            "demonstrating composure",
            "body language",
            "finish that thought",
            "rewrite this effectively",
            "provide the full question",
            "could you provide the full question",
            "primary ask shows only",
        )
        return any(marker in lowered for marker in meta_answer_markers)

    def _normalize_planner_result(
        self,
        planner_result: PlannerResult,
        deterministic_plan: PlannerResult,
    ) -> PlannerResult:
        candidate_asks = [
            self._normalize_candidate(ask)
            for ask in list(planner_result.asks_in_order or [])
        ]
        if not candidate_asks:
            candidate_asks = [self._normalize_candidate(planner_result.primary_ask)]
            candidate_asks.extend(self._normalize_candidate(ask) for ask in planner_result.secondary_asks)

        ordered_focus: list[str] = []
        for ask in candidate_asks:
            normalized = self._normalize_candidate(ask)
            if not normalized or self._is_noise_candidate(normalized):
                continue
            if any(self._is_redundant_focus(normalized, existing) for existing in ordered_focus):
                continue
            ordered_focus.append(normalized)

        if not ordered_focus:
            ordered_focus = list(deterministic_plan.ordered_focus or [])

        primary = ordered_focus[0] if ordered_focus else deterministic_plan.primary_ask
        secondary = ordered_focus[1 : 1 + self.config.max_secondary_asks]
        resolved_question = self._normalize_candidate(planner_result.resolved_question)
        if not resolved_question or self._is_noise_candidate(resolved_question):
            resolved_question = self._build_resolved_question(ordered_focus)
        (
            question_family,
            complexity_class,
            answer_shape,
            target_length,
            allow_metrics,
            allow_profile_opening,
            require_ordered_coverage,
            _,
        ) = self._minimal_live_defaults(ordered_focus)
        answer_focus = (planner_result.answer_focus or deterministic_plan.answer_focus or "").strip()
        answer_style_guidance = (planner_result.answer_style_guidance or deterministic_plan.answer_style_guidance or "").strip()
        draft_answer = self._clean_draft_answer((planner_result.draft_answer or "").strip())

        return PlannerResult(
            resolved_question=resolved_question,
            asks_in_order=ordered_focus,
            primary_ask=primary,
            secondary_asks=secondary,
            ordered_focus=ordered_focus,
            answer_focus=answer_focus,
            answer_style_guidance=answer_style_guidance,
            draft_answer=self._compact_text(draft_answer, limit=2200),
            question_family=question_family,
            complexity_class=complexity_class,
            answer_shape=answer_shape,
            target_length=target_length,
            allow_metrics=allow_metrics,
            allow_profile_opening=allow_profile_opening,
            require_ordered_coverage=require_ordered_coverage,
            confidence=max(0.0, min(planner_result.confidence, 1.0)),
            reasoning_summary=(planner_result.reasoning_summary or "").strip(),
            planner_source="llm_fast",
        )

    @staticmethod
    def _compact_text(text: str, *, limit: int = 360) -> str:
        collapsed = re.sub(r"\s+", " ", str(text or "")).strip()
        if len(collapsed) <= limit:
            return collapsed
        return collapsed[: limit - 3].rstrip() + "..."

    def _build_compact_live_context(
        self,
        *,
        interview_config: dict[str, Any],
        target_length: int,
    ) -> str:
        candidate_context = interview_config.get("candidate") or {}
        company_context = interview_config.get("company") or {}
        interviewer_context = interview_config.get("interviewer") or {}

        lines: list[str] = []

        candidate_name = str(candidate_context.get("name") or "").strip()
        current_role = str(candidate_context.get("current_role") or "").strip()
        years_experience = candidate_context.get("years_experience")
        candidate_summary = self._compact_text(
            str(candidate_context.get("summary") or "").strip(),
            limit=90,
        )
        achievements = [
            self._compact_text(str(item).strip(), limit=110)
            for item in (candidate_context.get("achievements") or [])[:1]
            if str(item).strip()
        ]
        skills = [str(item).strip() for item in (candidate_context.get("skills") or [])[:3] if str(item).strip()]

        company_name = str(company_context.get("companyName") or company_context.get("name") or "").strip()
        role_name = str(
            company_context.get("roleTitle")
            or company_context.get("jobTitle")
            or company_context.get("positionTitle")
            or company_context.get("roleName")
            or ""
        ).strip()
        company_description = self._compact_text(
            str(company_context.get("companyDescription") or "").strip(),
            limit=80,
        )
        company_culture = self._compact_text(
            str(company_context.get("companyCulture") or "").strip(),
            limit=60,
        )
        role_requirements = [
            self._compact_text(str(item).strip(), limit=70)
            for item in (company_context.get("roleRequirements") or [])[:1]
            if str(item).strip()
        ]

        interviewer_name = str(interviewer_context.get("name") or "").strip()

        if candidate_name:
            lines.append(f"- candidate_name: {candidate_name}")
        if current_role or years_experience:
            role_bits = [bit for bit in [current_role, f"{years_experience} years experience" if years_experience else ""] if bit]
            if role_bits:
                lines.append(f"- candidate_role: {' | '.join(role_bits)}")
        if candidate_summary:
            lines.append(f"- candidate_summary: {candidate_summary}")
        if achievements:
            lines.append(f"- candidate_achievements: {'; '.join(achievements)}")
        if skills:
            lines.append(f"- candidate_skills: {', '.join(skills[:3])}")
        if company_name or role_name:
            company_bits = [bit for bit in [company_name, role_name] if bit]
            lines.append(f"- target_role_context: {' | '.join(company_bits)}")
        if company_description:
            lines.append(f"- company_summary: {company_description}")
        if company_culture:
            lines.append(f"- company_culture: {company_culture}")
        if role_requirements:
            lines.append(f"- role_requirements: {'; '.join(role_requirements)}")
        if interviewer_name:
            lines.append(f"- interviewer_name: {interviewer_name}")
        lines.append(f"- answer_budget_words: {max(60, min(int(target_length or 140), 180))}")

        return "\n".join(lines) if lines else "- none"

    def _build_live_ask_brief(
        self,
        planner_result: PlannerResult,
    ) -> AskBrief:
        is_compound = len(planner_result.ordered_focus) > 1
        family = AskFamily.MIXED_COMPOUND if is_compound else AskFamily.GENERAL
        answer_contract = (
            self.ask_normalizer._contract_for_family(AskFamily.MIXED_COMPOUND, "manual")[0]
            if is_compound
            else self.ask_normalizer._contract_for_family(AskFamily.GENERAL, "manual")[0]
        )
        evidence_policy = self.ask_normalizer._contract_for_family(AskFamily.GENERAL, "manual")[1]
        metrics_policy = MetricsPolicy.AVOID_UNLESS_REQUESTED

        why: list[str] = []
        if planner_result.answer_focus:
            why.append(planner_result.answer_focus)
        if planner_result.answer_style_guidance:
            why.append(planner_result.answer_style_guidance)
        if planner_result.reasoning_summary:
            why.append(planner_result.reasoning_summary)

        return AskBrief(
            primary_ask=planner_result.primary_ask,
            secondary_asks=planner_result.secondary_asks,
            answer_family=family,
            answer_contract=answer_contract,
            evidence_policy=evidence_policy,
            metrics_policy=metrics_policy,
            opening_strategy=(
                planner_result.answer_style_guidance
                or ("Answer each ask in order." if is_compound else "Answer the interviewer directly.")
            ),
            confidence=max(0.72, planner_result.confidence),
            why=why,
            shadow_mode=False,
            fallback_used=False,
        )

    def _plan_focus(
        self,
        *,
        ask_block: str,
        sanitized_turns: list[dict[str, Any]],
    ) -> tuple[str, list[str], list[str]]:
        ordered = self._extract_ordered_asks_from_turns(sanitized_turns)
        if not ordered:
            latest_turn_candidate = self._extract_latest_turn_candidate(sanitized_turns)
            if latest_turn_candidate:
                ordered = [latest_turn_candidate]
        if not ordered:
            fallback = self._humanize_candidate(self._trim_to_actionable_core(ask_block))
            ordered = [fallback] if fallback and not self._is_noise_candidate(fallback) else []
        if not ordered:
            return "", [], []

        specific = [candidate for candidate in ordered if not self._is_broad_intro_request(candidate)]
        intro = [candidate for candidate in ordered if self._is_broad_intro_request(candidate)]
        ordered = specific + intro[:1] if specific else ordered

        primary = ordered[0]
        secondary = ordered[1 : 1 + self.config.max_secondary_asks]
        return primary, secondary, [primary, *secondary]

    def _extract_ordered_asks_from_turns(
        self,
        sanitized_turns: list[dict[str, Any]],
    ) -> list[str]:
        ordered: list[str] = []
        pending = ""

        for turn in sanitized_turns:
            turn_text = self._normalize_candidate(turn.get("text", ""))
            if not turn_text:
                continue
            for clause in self._split_turn_into_ask_clauses(turn_text):
                candidate = self._humanize_candidate(self._trim_to_actionable_core(clause))
                if not candidate or self._is_noise_candidate(candidate):
                    continue
                if pending:
                    merged = self._humanize_candidate(
                        self._merge_continuation_candidate(pending, candidate)
                    )
                    candidate = merged or candidate
                    pending = ""
                if self._is_empty_prompt_wrapper(candidate):
                    continue
                if self._needs_continuation(candidate):
                    pending = candidate
                    continue
                if not self._looks_like_actionable_candidate(candidate) and not self._is_broad_intro_request(candidate):
                    continue
                if any(self._is_redundant_focus(candidate, existing) for existing in ordered):
                    continue
                ordered.append(candidate)

        if pending:
            pending = self._humanize_candidate(self._trim_to_actionable_core(pending))
            if (
                pending
                and not self._is_empty_prompt_wrapper(pending)
                and (self._looks_like_actionable_candidate(pending) or self._is_broad_intro_request(pending))
                and not any(self._is_redundant_focus(pending, existing) for existing in ordered)
            ):
                ordered.append(pending)

        return ordered

    @staticmethod
    def _split_turn_into_ask_clauses(turn_text: str) -> list[str]:
        text = re.sub(r"\s+", " ", str(turn_text or "")).strip()
        if not text:
            return []
        parts = re.split(
            r"(?<=[?.!])\s+|\s+(?=(?:and then|also|finally|plus|and last question)\b)",
            text,
            flags=re.IGNORECASE,
        )
        return [part.strip(" ,.-") for part in parts if part and part.strip(" ,.-")]

    def _consolidate_candidates_in_order(self, candidates: list[str]) -> list[str]:
        ordered: list[str] = []
        for candidate in candidates:
            normalized = self._humanize_candidate(self._normalize_candidate(candidate))
            if not normalized or self._is_noise_candidate(normalized):
                continue
            if not self._looks_like_actionable_candidate(normalized) and not self._is_broad_intro_request(normalized):
                continue
            if self._is_fragmentary(normalized) and not self._looks_like_actionable_candidate(normalized):
                continue
            if self._is_generic_wrapper_candidate(normalized):
                if any(self._semantic_overlap_ratio(normalized, existing) >= 0.4 for existing in ordered):
                    continue
            if any(self._is_redundant_focus(normalized, existing) for existing in ordered):
                continue
            ordered.append(normalized)
        return ordered

    def _extract_latest_turn_candidate(self, sanitized_turns: list[dict[str, Any]]) -> str:
        for turn in reversed(sanitized_turns):
            text = self._normalize_candidate(turn.get("text", ""))
            if not text:
                continue
            candidate = self._trim_to_actionable_core(text)
            if candidate and not self._is_noise_candidate(candidate):
                return candidate
            if self._looks_like_direct_ask(text):
                return text.strip(" ,.-")
        return ""

    def _build_question_text(
        self,
        *,
        family: AskFamily,
        primary_ask: str,
        secondary_asks: list[str],
    ) -> str:
        asks = [ask for ask in [primary_ask, *secondary_asks] if ask]
        if not asks:
            return primary_ask
        if len(asks) == 1:
            return asks[0]

        header = "Also mention:" if family == AskFamily.CULTURE_FIT else "Also cover:"
        lines = [asks[0], header]
        lines.extend(f"- {ask}" for ask in asks[1:])
        return "\n".join(lines)

    def _build_resolved_question(self, asks_in_order: list[str]) -> str:
        asks = [ask for ask in asks_in_order if ask]
        if not asks:
            return ""
        if len(asks) == 1:
            return asks[0]
        lines = ["Answer these interviewer asks in order:"]
        lines.extend(f"{idx}. {ask}" for idx, ask in enumerate(asks, start=1))
        return "\n".join(lines)

    def _minimal_live_defaults(
        self,
        ordered_focus: list[str],
    ) -> tuple[AskFamily, ComplexityClass, AnswerShape, int, bool, bool, bool, float]:
        ask_count = len([ask for ask in ordered_focus if ask])

        if ask_count <= 1:
            family = AskFamily.GENERAL
            complexity = ComplexityClass.SIMPLE
            shape = AnswerShape.DIRECT_SHORT
            target_length = 105
            confidence = 0.8
        else:
            family = AskFamily.MIXED_COMPOUND
            complexity = ComplexityClass.COMPOUND
            shape = AnswerShape.DIRECT_STRUCTURED
            target_length = 180 if ask_count == 2 else 210
            confidence = 0.86

        return (
            family,
            complexity,
            shape,
            target_length,
            False,
            False,
            ask_count > 1,
            confidence,
        )

    def _build_ask_block(self, turns: list[dict[str, Any]]) -> str:
        return "\n".join(turn.get("text", "") for turn in turns).strip()

    def _sanitize_turns(self, turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
        sanitized: list[dict[str, Any]] = []
        for turn in turns[-self.config.max_turns :]:
            text = self._sanitize_turn_text(turn.get("text") or turn.get("content") or "")
            if not text:
                continue
            sanitized.append(
                {
                    "speaker": "interviewer",
                    "text": text,
                    "timestamp": turn.get("timestamp"),
                    "start_time": turn.get("start_time"),
                    "end_time": turn.get("end_time"),
                }
            )
        return sanitized

    @staticmethod
    def _sanitize_turn_text(text: str) -> str:
        cleaned = re.sub(r"\[STT Error:[^\]]+\]", " ", str(text or ""), flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        cleaned = re.sub(r"^(interviewer|candidate|system|unknown|nterviewer)\b[\s:,-]*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^\d{1,2}:\d{2}(?::\d{2})?\s*(am|pm)\b[\s:,-]*", "", cleaned, flags=re.IGNORECASE)
        return cleaned.strip(" ,.-")

    def _extract_focus_candidates(self, ask_block: str) -> list[str]:
        lines = [self._normalize_candidate(line) for line in ask_block.splitlines()]
        lines = [line for line in lines if line]
        raw_candidates: list[str] = []
        for line in lines:
            raw_candidates.extend(self._split_line_into_candidates(line))

        stitched: list[str] = []
        buffer = ""
        for candidate in raw_candidates:
            normalized = self._normalize_candidate(candidate)
            if not normalized or self._is_noise_candidate(normalized):
                continue
            if buffer:
                normalized = self._merge_continuation_candidate(buffer, normalized)
                buffer = ""
            if self._needs_continuation(normalized):
                buffer = normalized
                continue
            stitched.append(normalized)
        if buffer and not self._is_noise_candidate(buffer):
            stitched.append(buffer)

        deduped: list[str] = []
        for candidate in stitched:
            normalized = self._normalize_candidate(candidate)
            if not normalized or self._is_noise_candidate(normalized):
                continue
            if any(self._is_redundant_focus(normalized, existing) for existing in deduped):
                continue
            deduped.append(normalized)
        return deduped[: max(8, 1 + (self.config.max_secondary_asks * 2))]

    @classmethod
    def _merge_continuation_candidate(cls, buffer: str, candidate: str) -> str:
        buffer_words = str(buffer or "").split()
        candidate_words = str(candidate or "").split()
        if not buffer_words:
            return cls._normalize_candidate(candidate)
        if not candidate_words:
            return cls._normalize_candidate(buffer)

        max_overlap = min(len(buffer_words), len(candidate_words), 8)
        for overlap_size in range(max_overlap, 0, -1):
            if buffer_words[-overlap_size:] == candidate_words[:overlap_size]:
                merged = buffer_words + candidate_words[overlap_size:]
                return cls._normalize_candidate(" ".join(merged))

        return cls._normalize_candidate(f"{buffer} {candidate}")

    def _split_line_into_candidates(self, line: str) -> list[str]:
        segments = re.split(r"(?<=[?.!])\s+|\s+(?=(?:and then|also|finally|plus)\b)", line, flags=re.IGNORECASE)
        candidates: list[str] = []
        for segment in segments:
            candidate = self._trim_to_actionable_core(segment)
            if not candidate:
                continue
            if self._is_fragmentary(candidate) and not self._looks_like_actionable_candidate(candidate):
                continue
            candidates.append(candidate)
        return candidates

    def _trim_to_actionable_core(self, text: str) -> str:
        text = self._normalize_candidate(text)
        if not text:
            return ""

        prefixes = [
            r"^(so|yeah|and|but|okay|ok|well)\b[\s,.-]*",
            r"^(i mean|i guess|if you want|as we go)\b[\s,.-]*",
            r"^(daniel(?:le)?(?:\s+alarc[oó]n)?)[,:-]?\s*",
            r"^(sorry[^.?!]*[.?!]\s*)",
            r"^(we (?:will|were) talk(?:ing)? about)\b[\s,.-]*",
            r"^(in terms of your experience)\b[\s,.-]*",
            r"^(i (?:just )?wanted to ask you(?:, like)?)\b[\s,.-]*",
            r"^(or not the role, but)\b[\s,.-]*",
            r"^(basically what you have done in your experience)\b[\s,.-]*",
            r"^(hear specifically examples of)\b[\s,.-]*",
            r"^(last question as as we go)\b[\s,.-]*",
            r"^(like)\b[\s,.-]*",
        ]
        previous = None
        while text != previous:
            previous = text
            for pattern in prefixes:
                text = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()

        lowered = text.lower()
        if lowered in {
            "i would like to hear specifically",
            "hear specifically examples of",
            "examples of",
            "what you have done in your experience",
            "what are you",
            "looking for in terms of",
        }:
            return ""
        if self._is_empty_prompt_wrapper(text):
            return ""

        actionable_anchor = re.compile(
            r"(?i)\bwhat\b|\bhow\b|\bwhy\b|tell me|describe|explain|walk me through|"
            r"looking for|important for you|what kind of things|expectations? in terms of|"
            r"get a sense of|curious to hear about|hear about|experience in|examples of|"
            r"where you had to|build(?:ing)? from|from scratch|team management|"
            r"how big were the teams|what roles did"
        )
        match = actionable_anchor.search(text)
        if match and match.start() > 0:
            text = text[match.start():]
        return text.strip(" ,.-")

    @staticmethod
    def _is_empty_prompt_wrapper(text: str) -> bool:
        lowered = " ".join(str(text or "").lower().split()).strip(" ,.-")
        if not lowered:
            return True
        if lowered in {
            "tell me",
            "and tell me",
            "and then",
            "last question",
            "if you want",
            "walk me through",
            "describe",
            "explain",
        }:
            return True
        return bool(re.fullmatch(r"(tell me|describe|explain|walk me through)(?: please)?", lowered))

    @staticmethod
    def _normalize_candidate(text: str) -> str:
        normalized = re.sub(r"\s+", " ", str(text or "")).strip(" ,.-")
        normalized = re.sub(r"(?i)^big were the teams", "How big were the teams", normalized)
        normalized = re.sub(r"(?i)^roles did they have", "What roles did they have", normalized)
        normalized = re.sub(r"(?i)^then,?\s+", "", normalized)
        return normalized

    @staticmethod
    def _humanize_candidate(text: str) -> str:
        normalized = str(text or "").strip()
        if not normalized:
            return ""
        normalized = re.sub(
            r"(?i)^where you had to\s+",
            "Tell me about experiences where you had to ",
            normalized,
        )
        normalized = re.sub(
            r"(?i)^(hear about|curious to hear about|get a sense of)\s+your\s+",
            "Tell me about your ",
            normalized,
        )
        normalized = re.sub(r"(?i)^tell me,\s*", "", normalized)
        return normalized.strip(" ,.-")

    @staticmethod
    def _is_fragmentary(text: str) -> bool:
        lowered = text.lower().strip()
        if "?" in lowered and len(lowered) >= 12:
            return False
        if re.search(r"^(what|how|why)\b", lowered):
            return False
        if re.search(r"tell me|describe|explain|walk me through|looking for|important for you|what kind of things", lowered):
            return False
        if len(lowered) < 18:
            return True
        if len(lowered.split()) <= 3:
            return True
        fragment_endings = (
            "in terms of",
            "what are you",
            "looking for",
            "looking for in terms of the company",
            "looking for in terms of the company, the culture",
            "what you have done",
            "or what",
            "what kind of",
            "what kind of things you absolutely",
            "you absolutely",
            "absolutely",
            "also very curious",
            "curious to",
            "to hear about",
        )
        return lowered.endswith(fragment_endings)

    @staticmethod
    def _is_broad_intro_request(text: str) -> bool:
        lowered = text.lower()
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

    @staticmethod
    def _needs_continuation(text: str) -> bool:
        lowered = text.lower().strip()
        if "?" in lowered:
            return False
        if re.search(r"what are you looking for in terms of the company(?:, the culture)?$", lowered):
            return True
        if re.search(r"what(?:'s| is) important for you,? or what kind of things you absolutely$", lowered):
            return True
        continuation_endings = (
            "in terms of",
            "what are you looking for",
            "what are you looking for in terms of",
            "looking for",
            "looking for in terms of",
            "important for",
            "important to",
            "what kind of things",
            "what kind of things you absolutely",
            "you absolutely",
            "absolutely",
            "examples of",
            "hear about",
            "curious to hear about",
        )
        return lowered.endswith(continuation_endings)

    @staticmethod
    def _is_noise_candidate(text: str) -> bool:
        lowered = text.lower().strip()
        if not lowered:
            return True
        noise_patterns = (
            r"^sorry\b",
            r"^i have a terrible cough\b",
            r"^that won't go away\b",
            r"^but i was\b",
            r"^i was\b$",
            r"^i would like to hear specifically\b",
            r"^hear specifically examples of\b",
            r"^examples of\b$",
            r"^what you have done in your experience\b$",
            r"^what are you\b$",
            r"^looking for in terms of\b$",
        )
        return any(re.search(pattern, lowered) for pattern in noise_patterns)

    @staticmethod
    def _looks_like_direct_ask(text: str) -> bool:
        lowered = text.lower().strip()
        if not lowered:
            return False
        if "?" in lowered and len(lowered.split()) >= 3:
            return True
        return bool(
            re.search(
                r"^(what|how|why|when|where|who|which|can|could|would|do|does|did|is|are)\b|"
                r"tell me|describe|explain|walk me through|looking for|important for you|what kind of things",
                lowered,
            )
        )

    @staticmethod
    def _looks_like_actionable_candidate(text: str) -> bool:
        lowered = text.lower().strip()
        if not lowered:
            return False
        if "?" in lowered and len(lowered.split()) >= 3:
            return True
        return bool(
            re.search(
                r"^(what|how|why|when|where|who|which|can|could|would|do|does|did|is|are)\b|"
                r"tell me|describe|explain|walk me through|looking for|important for you|what kind of things|"
                r"hear about|get a sense of|experience in|where you had to|what roles did|how big were the teams",
                lowered,
            )
        )

    @staticmethod
    def _is_generic_wrapper_candidate(text: str) -> bool:
        lowered = text.lower().strip()
        return bool(
            re.search(
                r"^(get a sense of|hear about|curious to hear about|experience in|i want to hear examples of|tell me about your experience in)\b",
                lowered,
            )
        )

    @staticmethod
    def _content_tokens(text: str) -> set[str]:
        stopwords = {
            "the", "a", "an", "and", "or", "to", "of", "in", "for", "from", "your",
            "you", "about", "what", "how", "why", "also", "then", "with", "have",
            "had", "were", "that", "this", "those", "them", "they", "their", "just",
            "into", "where", "when", "which", "hear", "about", "sense", "experience",
            "experiences", "tell", "describe", "explain", "walk", "through", "me",
        }

        def _stem(token: str) -> str:
            for suffix in ("ing", "ed", "es", "s"):
                if token.endswith(suffix) and len(token) > len(suffix) + 2:
                    return token[: -len(suffix)]
            return token

        return {
            _stem(token)
            for token in re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(token) > 2 and token not in stopwords
        }

    def _semantic_overlap_ratio(self, candidate: str, reference: str) -> float:
        candidate_tokens = self._content_tokens(candidate)
        reference_tokens = self._content_tokens(reference)
        if not candidate_tokens or not reference_tokens:
            return 0.0
        overlap = candidate_tokens & reference_tokens
        return len(overlap) / max(1, min(len(candidate_tokens), len(reference_tokens)))

    def _is_redundant_focus(self, candidate: str, reference: str) -> bool:
        candidate_lower = candidate.lower().strip()
        reference_lower = reference.lower().strip()
        if not candidate_lower or not reference_lower:
            return False
        if candidate_lower == reference_lower:
            return True
        if candidate_lower in reference_lower or reference_lower in candidate_lower:
            return True

        candidate_tokens = self._content_tokens(candidate_lower)
        reference_tokens = self._content_tokens(reference_lower)
        if not candidate_tokens or not reference_tokens:
            return False

        overlap = candidate_tokens & reference_tokens
        min_size = min(len(candidate_tokens), len(reference_tokens))
        if min_size > 0 and (len(overlap) / min_size) >= 0.7:
            return True

        return self._semantic_overlap_ratio(candidate_lower, reference_lower) >= 0.7

    def _score_candidate(self, text: str, family: AskFamily, index: int) -> float:
        lowered = text.lower()
        score = 0.0
        if re.search(r"^(what|how|why)\b", lowered):
            score += 5.0
        if re.search(r"tell me|describe|explain|walk me through", lowered):
            score += 4.0
        if re.search(r"looking for|important for you|what kind of things|expectations? in terms of", lowered):
            score += 4.0
        if re.search(r"get a sense of|curious to hear about|hear about|where you had to", lowered):
            score += 4.0
        if re.search(r"build(?:ing)? from|from scratch|team management|how big were the teams|what roles did", lowered):
            score += 3.0
        if re.search(r"roles?\b|culture\b|teams?\b", lowered):
            score += 2.0
        if family == AskFamily.CULTURE_FIT and re.search(r"looking for|important|avoid|don't like|do not like", lowered):
            score += 2.0
        if lowered.startswith(("building a ", "a team from", "a service from")) and "get a sense" not in lowered:
            score -= 2.0
        if self._is_broad_intro_request(text):
            score -= 3.0
        score += max(0.0, 2.0 - (index * 0.2))
        score += min(2.0, len(lowered.split()) / 8.0)
        return score

    @staticmethod
    def _derive_shape(
        ask_brief: AskBrief,
        *,
        interview_type: str = "mixed",
    ) -> tuple[ComplexityClass, AnswerShape, int, bool, bool, bool]:
        ask_count = len([ask for ask in [ask_brief.primary_ask, *ask_brief.secondary_asks] if ask])
        family = ask_brief.answer_family
        interview_type_normalized = str(interview_type or "mixed").strip().lower()

        if family == AskFamily.CULTURE_FIT:
            return (
                ComplexityClass.SIMPLE,
                AnswerShape.DIRECT_SHORT,
                120,
                False,
                False,
                ask_count > 1,
            )

        if family in {AskFamily.TECHNICAL_CONCEPT, AskFamily.ARCHITECTURE_DESIGN} or interview_type_normalized in {
            "technical",
            "system_design",
        }:
            return (
                ComplexityClass.DEEP_TECHNICAL,
                AnswerShape.TECHNICAL_EXPLAINER,
                170,
                family == AskFamily.ARCHITECTURE_DESIGN,
                False,
                ask_count > 1,
            )

        if family in {AskFamily.BUSINESS_STRATEGY, AskFamily.METRICS_OUTCOMES}:
            return (
                ComplexityClass.STRATEGY,
                AnswerShape.STRATEGIC_EXPLAINER,
                180,
                True,
                False,
                ask_count > 1,
            )

        if ask_count > 1 or family in {AskFamily.MIXED_COMPOUND, AskFamily.EXPERIENCE_SCOPE}:
            return (
                ComplexityClass.COMPOUND,
                AnswerShape.DIRECT_STRUCTURED,
                220,
                ask_brief.metrics_policy != MetricsPolicy.AVOID_UNLESS_REQUESTED,
                False,
                True,
            )

        return (
            ComplexityClass.SIMPLE,
            AnswerShape.DIRECT_SHORT,
            110,
            ask_brief.metrics_policy == MetricsPolicy.REQUIRED,
            False,
            False,
        )

    @staticmethod
    def _artifact_sanitized(raw_turns: list[dict[str, Any]], sanitized_turns: list[dict[str, Any]]) -> bool:
        raw_text = "\n".join(
            " ".join(str(turn.get("text") or "").split()).strip()
            for turn in raw_turns
            if str(turn.get("text") or "").strip()
        )
        sanitized_text = "\n".join(turn.get("text", "") for turn in sanitized_turns)
        return raw_text != sanitized_text

    @staticmethod
    def _extract_json_payload(raw_text: str) -> str:
        text = (raw_text or "").strip()
        if not text:
            return ""
        if text.startswith("{") and text.endswith("}"):
            return text
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        return match.group(0) if match else ""

    @staticmethod
    def _infer_provider_name(adapter: Any) -> str:
        class_name = adapter.__class__.__name__.lower()
        if "anthropic" in class_name:
            return "anthropic"
        if "openai" in class_name:
            return "openai"
        if "ollama" in class_name:
            return "ollama"
        return class_name or "unknown"
