from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Awaitable, Callable, Optional

from adapters.llm_adapter import AnthropicLLMAdapter, OpenAILLMAdapter, OllamaLLMAdapter, _get_runtime_config
from contracts.models import BrainPlan, CompactEvidencePack

_DETAIL_STOPWORDS = {
    "what",
    "which",
    "who",
    "why",
    "how",
    "when",
    "where",
    "tell",
    "give",
    "looking",
    "terms",
    "term",
    "about",
    "into",
    "from",
    "with",
    "that",
    "this",
    "these",
    "those",
    "your",
    "you",
    "yours",
    "are",
    "for",
    "and",
    "the",
    "kind",
    "kinds",
    "type",
    "types",
    "most",
    "matter",
    "matters",
    "important",
    "value",
    "values",
    "role",
}


@dataclass
class LiveFinalizerConfig:
    llm_alias: str = "main"
    llm_timeout_sec: float = 7.5
    llm_temperature: float = 0.15
    llm_max_tokens: int = 650


class LiveFinalizer:
    def __init__(self, config: Optional[LiveFinalizerConfig] = None):
        self.config = config or LiveFinalizerConfig()
        self.last_llm_failure_kind: str = ""

    async def finalize(
        self,
        *,
        plan: BrainPlan,
        evidence_pack: CompactEvidencePack,
        question_text: str,
        conversation_history: list[dict[str, Any]],
        interview_config: dict[str, Any],
        working_draft: str = "",
        strict_emit_only: bool = False,
        recovery_draft: str = "",
        allow_post_failure_recovery: bool = False,
        timeout_override_sec: Optional[float] = None,
        on_partial_response: Optional[Callable[[dict[str, Any]], Awaitable[None]]] = None,
        partial_emit_interval_sec: float = 0.2,
    ) -> dict[str, Any]:
        started = perf_counter()
        metadata = self._metadata()
        self.last_llm_failure_kind = ""
        recovery_draft_text = self._normalize_text_preserving_paragraphs(recovery_draft)
        metadata.update(
            {
                "emit_stream_used": False,
                "emit_stream_first_chunk_ms": None,
                "emit_stream_completed_ms": None,
                "emit_stream_chunk_count": 0,
                "emit_stream_partial_salvaged": False,
                "finalizer_primary_mode": "strict_emit_only" if strict_emit_only else "normal",
                "finalizer_primary_success": False,
                "recovery_draft_available": bool(recovery_draft_text),
                "finalizer_recovery_attempted": False,
                "finalizer_recovery_kind": "none",
                "finalizer_recovery_success": False,
                "finalizer_recovery_skipped_reason": "",
            }
        )
        source_draft = ""
        if not strict_emit_only:
            source_draft = self._normalize_text(working_draft) or self._normalize_text(plan.draft_answer)
        full_response = ""
        sanitizer_applied = False
        use_brain_draft_directly = (not strict_emit_only) and bool(source_draft) and self._should_use_brain_draft_directly(
            plan=plan,
            text=source_draft,
        )

        if use_brain_draft_directly:
            draft_response, draft_sanitized = self._sanitize_output_text(source_draft)
            full_response = draft_response
            sanitizer_applied = sanitizer_applied or draft_sanitized
            metadata["finalizer_fallback_kind"] = "brain_draft"
            if full_response:
                metadata["finalizer_primary_success"] = True
                metadata["finalizer_recovery_skipped_reason"] = "not_needed"
        else:
            llm_result = await self._finalize_with_llm(
                plan=plan,
                evidence_pack=evidence_pack,
                question_text=question_text,
                conversation_history=conversation_history,
                interview_config=interview_config,
                working_draft=source_draft,
                strict_emit_only=strict_emit_only,
                timeout_override_sec=timeout_override_sec,
                on_partial_response=on_partial_response,
                partial_emit_interval_sec=partial_emit_interval_sec,
            )
            if isinstance(llm_result, tuple):
                llm_response, stream_metadata = llm_result
            else:
                llm_response, stream_metadata = llm_result, {}
            metadata.update(stream_metadata)
            if llm_response:
                full_response, llm_sanitized = self._sanitize_output_text(llm_response)
                sanitizer_applied = llm_sanitized
                if full_response:
                    metadata["llm_called"] = True
                    metadata["provider"] = metadata.get("configured_provider")
                    metadata["model"] = metadata.get("configured_model")
                    metadata["finalizer_fallback_kind"] = "llm"
                    metadata["finalizer_primary_success"] = True
                    metadata["finalizer_recovery_skipped_reason"] = "not_needed"
            elif strict_emit_only:
                partial_response = self._normalize_text(
                    metadata.get("emit_stream_partial_response") or ""
                )
                if partial_response:
                    partial_response, partial_sanitized = self._sanitize_output_text(partial_response)
                    sanitizer_applied = sanitizer_applied or partial_sanitized
                    if partial_response:
                        full_response = partial_response
                        metadata["llm_called"] = True
                        metadata["provider"] = metadata.get("configured_provider")
                        metadata["model"] = metadata.get("configured_model")
                        metadata["emit_stream_partial_salvaged"] = True
                        metadata["finalizer_fallback_kind"] = "llm_partial"
                        metadata["finalizer_primary_success"] = True
                        metadata["finalizer_recovery_skipped_reason"] = "not_needed"
            should_use_deterministic = (
                not strict_emit_only
                and bool(plan.answer_blueprint or plan.alignment_brief or plan.quality_guardrails)
            )
            if not full_response and should_use_deterministic:
                deterministic_response = self._finalize_deterministically(
                    plan=plan,
                    evidence_pack=evidence_pack,
                    question_text=question_text,
                    working_draft=source_draft,
                )
                deterministic_response, deterministic_sanitized = self._sanitize_output_text(deterministic_response)
                sanitizer_applied = sanitizer_applied or deterministic_sanitized
                if deterministic_response:
                    full_response = deterministic_response
                    metadata["finalizer_fallback_kind"] = "deterministic"
                    metadata["finalizer_primary_success"] = True
                    metadata["finalizer_recovery_skipped_reason"] = "not_needed"
            if not full_response and (not strict_emit_only) and source_draft:
                draft_response, draft_sanitized = self._sanitize_output_text(source_draft)
                full_response = draft_response
                sanitizer_applied = sanitizer_applied or draft_sanitized
                metadata["finalizer_fallback_kind"] = "brain_draft"
                if full_response:
                    metadata["finalizer_primary_success"] = True
                    metadata["finalizer_recovery_skipped_reason"] = "not_needed"
        if not full_response and strict_emit_only:
            completeness = str(plan.question_completeness or "").strip().lower()
            if not allow_post_failure_recovery:
                metadata["finalizer_recovery_skipped_reason"] = "disabled"
            elif completeness != "complete":
                metadata["finalizer_recovery_skipped_reason"] = "question_incomplete"
            else:
                metadata["finalizer_recovery_attempted"] = True
                deterministic_response = self._finalize_deterministically(
                    plan=plan,
                    evidence_pack=evidence_pack,
                    question_text=question_text,
                    working_draft="",
                )
                deterministic_response, deterministic_sanitized = self._sanitize_output_text(deterministic_response)
                sanitizer_applied = sanitizer_applied or deterministic_sanitized
                if deterministic_response:
                    full_response = deterministic_response
                    metadata["finalizer_fallback_kind"] = "deterministic"
                    metadata["finalizer_recovery_kind"] = "deterministic"
                    metadata["finalizer_recovery_success"] = True
                elif recovery_draft_text:
                    draft_response, draft_sanitized = self._sanitize_output_text(recovery_draft_text)
                    sanitizer_applied = sanitizer_applied or draft_sanitized
                    if draft_response:
                        full_response = draft_response
                        metadata["finalizer_fallback_kind"] = "brain_draft"
                        metadata["finalizer_recovery_kind"] = "brain_draft"
                        metadata["finalizer_recovery_success"] = True
                if not full_response and not recovery_draft_text:
                    metadata["finalizer_recovery_skipped_reason"] = "no_recovery_draft"
        if not full_response:
            failure_kind = self.last_llm_failure_kind if strict_emit_only else ""
            if failure_kind:
                metadata["emit_failure_kind"] = failure_kind
            failure_response = self._build_explicit_failure_notice(plan=plan, failure_kind=failure_kind)
            full_response, failure_sanitized = self._sanitize_output_text(failure_response)
            sanitizer_applied = sanitizer_applied or failure_sanitized
            metadata["finalizer_fallback_kind"] = "explicit_failure"

        full_response = self._apply_visible_structure(
            text=full_response,
            plan=plan,
            aggressive_sentence_split=metadata.get("finalizer_fallback_kind") not in {"brain_draft", "explicit_failure"},
        )
        elapsed_ms = int((perf_counter() - started) * 1000)
        metadata["output_sanitizer_applied"] = sanitizer_applied
        return {
            "full_response": full_response,
            "bullets": self._to_bullets(full_response, limit=max(2, min(len(plan.ordered_asks or []), 4))),
            "confidence": max(0.76, float(plan.confidence or 0.0)),
            "latency_ms": elapsed_ms,
            "metadata": metadata,
        }

    @staticmethod
    def _effective_question_text(plan: BrainPlan, question_text: str) -> str:
        return (
            LiveFinalizer._normalize_text(plan.contextualized_question)
            or LiveFinalizer._normalize_text(plan.resolved_question)
            or LiveFinalizer._normalize_text(question_text)
        )

    def _build_explicit_failure_notice(self, *, plan: BrainPlan, failure_kind: str = "") -> str:
        if failure_kind == "timeout":
            return "I could not generate a reliable answer because the final answer stage timed out."
        if failure_kind == "llm_unavailable":
            return "I could not generate a reliable answer because the final answer stage was unavailable."
        if failure_kind == "error":
            return "I could not generate a reliable answer because the final answer stage failed."
        completeness = str(plan.question_completeness or "").strip().lower()
        if completeness in {"partial", "garbled"}:
            return "I did not catch the full question clearly enough to give you a reliable answer."
        return "I could not generate a reliable answer for this question in time."

    def _resolve_emit_max_tokens(self, *, plan: BrainPlan) -> int:
        target_length = max(120, int(plan.target_length or 180))
        ask_count = max(1, len(list(plan.ordered_asks or [])))
        requested = target_length + 120 + max(0, ask_count - 1) * 30
        return max(260, min(self.config.llm_max_tokens, requested))

    def _should_use_brain_draft_directly(self, *, plan: BrainPlan, text: str) -> bool:
        plan_source = str(plan.plan_source or "").strip().lower()
        if plan_source not in {"llm_fast", "cached_stable"}:
            return False
        return self._meets_structural_quality_floor(plan=plan, text=text)

    async def _finalize_with_llm(
        self,
        *,
        plan: BrainPlan,
        evidence_pack: CompactEvidencePack,
        question_text: str,
        conversation_history: list[dict[str, Any]],
        interview_config: dict[str, Any],
        working_draft: str,
        strict_emit_only: bool,
        timeout_override_sec: Optional[float],
        on_partial_response: Optional[Callable[[dict[str, Any]], Awaitable[None]]],
        partial_emit_interval_sec: float,
    ) -> tuple[str, dict[str, Any]]:
        adapter = self._resolve_adapter(alias=self.config.llm_alias)
        stream_metadata = {
            "emit_stream_used": False,
            "emit_stream_first_chunk_ms": None,
            "emit_stream_completed_ms": None,
            "emit_stream_chunk_count": 0,
            "emit_stream_partial_salvaged": False,
            "emit_stream_partial_response": "",
            "configured_provider": (_get_runtime_config() or {}).get("llm", {}).get("provider"),
            "configured_model": (_get_runtime_config() or {}).get("llm", {}).get("model"),
        }
        if adapter is None:
            self.last_llm_failure_kind = "llm_unavailable"
            return "", stream_metadata

        prompt = self._build_prompt(
            plan=plan,
            evidence_pack=evidence_pack,
            question_text=question_text,
            conversation_history=conversation_history,
            interview_config=interview_config,
            working_draft=working_draft,
            include_plan_draft=not strict_emit_only,
            strict_emit_only=strict_emit_only,
        )
        config = {
            "temperature": self.config.llm_temperature,
            "max_tokens": self._resolve_emit_max_tokens(plan=plan),
        }
        messages = self._build_llm_messages(prompt=prompt)
        timeout_budget = timeout_override_sec or self.config.llm_timeout_sec

        if on_partial_response is None:
            try:
                response = await asyncio.wait_for(
                    adapter.generate(messages, config),
                    timeout=timeout_budget,
                )
                self.last_llm_failure_kind = ""
                return response, stream_metadata
            except asyncio.TimeoutError:
                self.last_llm_failure_kind = "timeout"
                return "", stream_metadata
            except Exception:
                self.last_llm_failure_kind = "error"
                return "", stream_metadata

        partial_response = ""
        last_emitted_response = ""
        stream_started = perf_counter()
        last_emit_at = stream_started

        async def _emit_partial(force: bool = False) -> None:
            nonlocal last_emitted_response, last_emit_at
            normalized_partial = partial_response.replace("\r\n", "\n").replace("\r", "\n")
            if not normalized_partial.strip():
                return
            if normalized_partial == last_emitted_response:
                return
            await on_partial_response(
                {
                    "full_response": normalized_partial,
                    "provider": stream_metadata.get("configured_provider"),
                    "model": stream_metadata.get("configured_model"),
                    "chunk_count": stream_metadata["emit_stream_chunk_count"],
                    "first_chunk_ms": stream_metadata["emit_stream_first_chunk_ms"],
                }
            )
            last_emitted_response = normalized_partial
            last_emit_at = perf_counter()

        async def _consume_stream() -> str:
            nonlocal partial_response
            stream_metadata["emit_stream_used"] = True
            async for chunk in adapter.stream(messages, config):
                if not chunk:
                    continue
                partial_response += chunk
                stream_metadata["emit_stream_chunk_count"] += 1
                if stream_metadata["emit_stream_first_chunk_ms"] is None:
                    stream_metadata["emit_stream_first_chunk_ms"] = int(
                        (perf_counter() - stream_started) * 1000
                    )
                    # Emit the very first chunk immediately so Live can paint text
                    # as soon as the model starts writing, matching the stable UX.
                    await _emit_partial(force=True)
                    continue
                should_flush = (
                    (perf_counter() - last_emit_at) >= partial_emit_interval_sec
                    or chunk.endswith((".", "!", "?", "\n"))
                )
                if should_flush:
                    await _emit_partial()
            await _emit_partial(force=True)
            return partial_response

        try:
            response = await asyncio.wait_for(
                _consume_stream(),
                timeout=timeout_budget,
            )
            stream_metadata["emit_stream_completed_ms"] = int(
                (perf_counter() - stream_started) * 1000
            )
            stream_metadata["emit_stream_partial_response"] = partial_response
            self.last_llm_failure_kind = ""
            return response, stream_metadata
        except asyncio.TimeoutError:
            self.last_llm_failure_kind = "timeout"
            stream_metadata["emit_stream_completed_ms"] = int(
                (perf_counter() - stream_started) * 1000
            )
            stream_metadata["emit_stream_partial_response"] = partial_response
            return "", stream_metadata
        except Exception:
            stream_metadata["emit_stream_completed_ms"] = int(
                (perf_counter() - stream_started) * 1000
            )
            stream_metadata["emit_stream_partial_response"] = partial_response
            if partial_response.strip():
                self.last_llm_failure_kind = "error"
                return "", stream_metadata
            try:
                response = await asyncio.wait_for(
                    adapter.generate(messages, config),
                    timeout=timeout_budget,
                )
                self.last_llm_failure_kind = ""
                return response, stream_metadata
            except asyncio.TimeoutError:
                self.last_llm_failure_kind = "timeout"
                return "", stream_metadata
            except Exception:
                self.last_llm_failure_kind = "error"
                return "", stream_metadata

    @staticmethod
    def _build_llm_messages(prompt: str) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    "You are the live interview emit stage. "
                    "The brain contract is the source of truth. "
                    "Do not reinterpret the question, re-plan the answer, or add new topics. "
                    "Use the configured main model to realize the contract into one strong spoken answer. "
                    "Respect the requested style, structure, and context boundaries. "
                    "When the contract is multi-part, separate the parts with a blank line so the structure is easy to scan. "
                    "Do not output wrappers like FULL RESPONSE, ANSWER, headings, bullets, or markdown labels."
                ),
            },
            {"role": "user", "content": prompt},
        ]

    def _finalize_deterministically(
        self,
        *,
        plan: BrainPlan,
        evidence_pack: CompactEvidencePack,
        question_text: str,
        working_draft: str,
    ) -> str:
        source_draft = self._normalize_text(working_draft) or self._normalize_text(plan.draft_answer)
        if source_draft and self._meets_structural_quality_floor(plan=plan, text=source_draft):
            return source_draft

        blueprint_answer = self._build_answer_from_blueprint(
            plan=plan,
            evidence_pack=evidence_pack,
            draft_text=source_draft,
        )
        if blueprint_answer:
            return blueprint_answer

        asks = list(plan.ordered_asks or [])
        if str(plan.question_completeness or "").strip().lower() != "complete" and len(asks) <= 1:
            asks = asks[:1]
        structured_from_draft = self._build_structured_answer_from_draft(
            plan=plan,
            asks=asks,
            draft_text=source_draft,
            detail=self._pick_best_detail(plan, evidence_pack),
        )
        if structured_from_draft:
            return structured_from_draft

        structured_from_plan = self._build_structured_answer_from_plan(
            plan=plan,
            asks=asks,
            evidence_pack=evidence_pack,
            detail=self._pick_best_detail(plan, evidence_pack),
        )
        if structured_from_plan:
            return structured_from_plan

        answer_parts: list[str] = []
        detail = self._pick_best_detail(plan, evidence_pack)
        lead = self._conservative_opening(plan, asks)
        if lead:
            answer_parts.append(lead)
        if detail:
            answer_parts.append(detail)

        if (
            plan.metrics_policy == "required"
            and evidence_pack.supporting_metrics
            and str(plan.plan_source or "").strip().lower() == "llm_fast"
        ):
            answer_parts.append(f"A concrete proof point is {self._sanitize_source_snippet(evidence_pack.supporting_metrics[0])}.")

        response = self._join_answer_parts(answer_parts, plan=plan, add_terminal_period=False)
        if not response:
            response = self._fallback_to_safe_summary(plan=plan, question_text=question_text)
        return response

    def _build_prompt(
        self,
        *,
        plan: BrainPlan,
        evidence_pack: CompactEvidencePack,
        question_text: str,
        conversation_history: list[dict[str, Any]],
        interview_config: dict[str, Any],
        working_draft: str,
        include_plan_draft: bool,
        strict_emit_only: bool = False,
    ) -> str:
        style_id = self._normalize_text(interview_config.get("style_id") or interview_config.get("response_style") or "professional")
        language = self._normalize_text(interview_config.get("language") or "en")
        source_of_truth_context = self._build_source_of_truth_context_block(
            interview_config,
            plan=plan,
        )
        effective_question = self._effective_question_text(plan, question_text)
        literal_question = self._normalize_text(plan.literal_question) or self._normalize_text(question_text)
        evidence_lines = []
        for label, items in (
            ("Candidate profile evidence", evidence_pack.candidate_snippets),
            ("Target company and role context", evidence_pack.company_snippets),
            ("Interviewer context", evidence_pack.interviewer_snippets),
            ("Supporting metrics", evidence_pack.supporting_metrics),
        ):
            value = "; ".join(items) if items else "None"
            evidence_lines.append(f"- {label}: {value}")
        excluded = ", ".join(evidence_pack.excluded_topics) if evidence_pack.excluded_topics else "None"
        delivery_instructions = plan.delivery_instructions or []
        delivery_block = "\n".join(f"- {item}" for item in delivery_instructions) if delivery_instructions else "- None"
        blueprint_lines = []
        for segment in list(plan.answer_blueprint or []):
            purpose = self._normalize_text(segment.get("purpose"))
            ask_refs = " | ".join(segment.get("ask_refs") or []) or "None"
            required = " | ".join(segment.get("required_elements") or []) or "None"
            preferred = " | ".join(segment.get("preferred_evidence_types") or []) or "None"
            avoid = " | ".join(segment.get("avoid_topics") or []) or "None"
            blueprint_lines.append(
                f"- purpose={purpose}; asks={ask_refs}; required={required}; evidence={preferred}; avoid={avoid}; target_sentences={segment.get('target_sentence_count', 1)}"
            )
        blueprint_block = "\n".join(blueprint_lines) if blueprint_lines else "- None"
        alignment_block = " | ".join(plan.alignment_brief or []) or "None"
        guardrails_block = " | ".join(plan.quality_guardrails or []) or "None"
        history_block = self._format_history(conversation_history)
        structured_evidence_lines = [
            f"- Candidate role evidence: {'; '.join(evidence_pack.role_evidence) if evidence_pack.role_evidence else 'None'}",
            f"- Candidate build evidence: {'; '.join(evidence_pack.build_evidence) if evidence_pack.build_evidence else 'None'}",
            f"- Candidate leadership evidence: {'; '.join(evidence_pack.leadership_evidence) if evidence_pack.leadership_evidence else 'None'}",
            f"- Candidate team scope evidence: {'; '.join(evidence_pack.team_scope_evidence) if evidence_pack.team_scope_evidence else 'None'}",
            f"- Target alignment evidence: {'; '.join(evidence_pack.culture_alignment_evidence) if evidence_pack.culture_alignment_evidence else 'None'}",
            f"- Target technical alignment evidence: {'; '.join(evidence_pack.technical_alignment_evidence) if evidence_pack.technical_alignment_evidence else 'None'}",
        ]

        draft_seed = ""
        if working_draft:
            draft_seed = working_draft
        elif include_plan_draft:
            draft_seed = plan.draft_answer or ""

        if strict_emit_only:
            ask_lines = "\n".join(f"- {ask}" for ask in (plan.ordered_asks or [])) or "- None"
            ask_intent_lines = []
            for item in list(plan.ask_intents or []):
                ask_intent_lines.append(
                    (
                        f"- ask={self._normalize_text(item.ask_text) or 'None'}; "
                        f"intent={self._normalize_text(item.ask_intent) or 'None'}; "
                        f"goal={self._normalize_text(item.response_goal) or 'None'}; "
                        f"evidence={' | '.join(item.required_evidence_types or []) or 'None'}; "
                        f"shape={self._normalize_text(item.expected_answer_shape) or 'None'}; "
                        f"needs_prior_context={bool(item.needs_context_from_prior_turns)}"
                    )
                )
            ask_intents_block = "\n".join(ask_intent_lines) if ask_intent_lines else "- None"
            interviewer_need = plan.interviewer_need
            interviewer_need_block = "\n".join(
                [
                    f"- Summary: {self._normalize_text(interviewer_need.summary) or 'None'}",
                    f"- Dimensions: {' | '.join(interviewer_need.dimensions or []) or 'None'}",
                    f"- Evidence expected: {' | '.join(interviewer_need.evidence_expected or []) or 'None'}",
                ]
            )
            context_focus_block = "\n".join(f"- {item}" for item in list(plan.context_focus or [])) or "- None"
            response_requirement = plan.response_requirement
            response_requirements = [
                f"- Question type: {plan.question_type}",
                f"- Response shape: {plan.response_shape}",
                f"- Answer contract: {plan.answer_contract}",
                f"- Tone: {plan.tone}",
                f"- Directness: {plan.directness}",
                f"- Target length: {plan.target_length}",
                f"- Style hint: {style_id}",
                f"- Language: {language}",
                f"- Ordered coverage required: {plan.ordered_coverage_required}",
                f"- Answer mode: {self._normalize_text(response_requirement.answer_mode) or 'None'}",
                f"- Profile evidence mode: {self._normalize_text(response_requirement.profile_evidence_mode) or 'None'}",
                f"- Company evidence mode: {self._normalize_text(response_requirement.company_evidence_mode) or 'None'}",
                f"- Prior context mode: {self._normalize_text(response_requirement.prior_context_mode) or 'None'}",
                f"- Response order: {' | '.join(response_requirement.response_order or []) or 'None'}",
                f"- Required moves: {' | '.join(response_requirement.required_moves or []) or 'None'}",
                f"- Context to weave: {' | '.join(response_requirement.context_to_weave or []) or 'None'}",
                f"- Evidence priority: {' | '.join(response_requirement.evidence_priority or []) or 'None'}",
                f"- Must cover: {' | '.join(response_requirement.must_cover or []) or 'None'}",
                f"- Avoid: {' | '.join(response_requirement.avoid or []) or 'None'}",
                f"- Paragraph plan: {' | '.join(response_requirement.paragraph_plan or []) or 'None'}",
                f"- Style constraints: {' | '.join(response_requirement.style_constraints or []) or 'None'}",
            ]
            compact_structured_evidence = [
                line for line in structured_evidence_lines if not line.endswith(": None")
            ] or ["- None"]
            return f"""
QUESTION TO ANSWER:
{effective_question}

LITERAL QUESTION:
{literal_question}

ORDERED ASKS:
{ask_lines}

ASK INTENTS:
{ask_intents_block}

SOURCE OF TRUTH CONTEXT:
{source_of_truth_context}

INTERVIEWER NEED:
{interviewer_need_block}

CONTEXT FOCUS:
{context_focus_block}

RESPONSE REQUIREMENTS:
{chr(10).join(response_requirements)}

STRUCTURED EVIDENCE:
{chr(10).join(compact_structured_evidence)}

EXCLUDED TOPICS:
{excluded}

Instructions:
- Treat QUESTION TO ANSWER as the operative ask. Use LITERAL QUESTION only as wording reference.
- Answer only from the brain contract and the structured evidence.
- Cover every ask explicitly and in order.
- Realize the interviewer need and the response requirement exactly. Do not reinterpret the interview.
- Treat Candidate Profile Facts as the only source for the candidate's current company, prior experience, and what the candidate built or led.
- Treat Target Company Context and Target Role Context as application context only. Never state or imply that the candidate works at the target company or built something there unless the candidate evidence explicitly says so.
- Treat Interviewer Context as interviewer background only. Never attribute interviewer details to the candidate or the target role.
- For biography, experience, leadership, build-from-zero, and team-management asks, rely on candidate evidence first and ignore target context unless the ask explicitly asks about fit, alignment, or preferences.
- Treat the evidence modes as hard permissions, not hints.
- If Profile evidence mode is none, do not add candidate background, role scope, years of experience, or achievement proof.
- If Profile evidence mode is orientation_only, use only minimal orientation and do not expand into proof or leadership scope unless explicitly required.
- If Profile evidence mode is one_best_proof, use at most one supporting candidate proof beyond a brief orientation.
- If Profile evidence mode is scope_only, stay on team size, management scope, or composition and do not broaden into general biography.
- If Company evidence mode is none, ignore target company context.
- If Company evidence mode is preference_alignment, use company context only to mirror preference areas, not to turn the answer into a fit pitch.
- If Prior context mode is none, do not weave prior interviewer context into the answer.
- Keep the answer natural and speakable, as if the candidate were saying it aloud now.
- Use concrete evidence, not generic labels.
- Do not repeat profile summaries or titles across paragraphs.
- Do not paste resume fragments verbatim.
- If there are multiple asks, use short paragraphs separated by a blank line.
- Do not use bullets, headings, wrappers, or markdown.
- Return only the answer text.
"""

        return f"""
QUESTION:
{effective_question}

LITERAL QUESTION:
{literal_question}

RECENT CONVERSATION HISTORY:
{history_block}

SOURCE OF TRUTH CONTEXT:
{source_of_truth_context}

BRAIN PLAN:
- Literal question: {plan.literal_question or 'None'}
- Contextualized question: {plan.contextualized_question or 'None'}
- Resolved question: {plan.resolved_question}
- Ordered asks: {' | '.join(plan.ordered_asks or []) or 'None'}
- Coverage points: {' | '.join(plan.coverage_points or []) or 'None'}
- Response family: {plan.response_family}
- Question type: {plan.question_type}
- Response shape: {plan.response_shape}
- Answer contract: {plan.answer_contract}
- Tone: {plan.tone}
- Directness: {plan.directness}
- Include profile opening: {plan.include_profile_opening}
- Evidence depth: {plan.evidence_depth}
- Metrics policy: {plan.metrics_policy}
- Company context policy: {plan.company_context_policy}
- Candidate context policy: {plan.candidate_context_policy}
- Ordered coverage required: {plan.ordered_coverage_required}
- Target length: {plan.target_length}
- Question completeness: {plan.question_completeness}
- Plan source: {plan.plan_source}
- Style hint: {style_id}
- Profile evidence mode: {plan.response_requirement.profile_evidence_mode or 'None'}
- Company evidence mode: {plan.response_requirement.company_evidence_mode or 'None'}
- Prior context mode: {plan.response_requirement.prior_context_mode or 'None'}

ALIGNMENT BRIEF:
{alignment_block}

QUALITY GUARDRAILS:
{guardrails_block}

ANSWER BLUEPRINT:
{blueprint_block}

DELIVERY INSTRUCTIONS:
{delivery_block}

COMPACT EVIDENCE:
{chr(10).join(evidence_lines)}

STRUCTURED EVIDENCE:
{chr(10).join(structured_evidence_lines)}

EXCLUDED TOPICS:
{excluded}

WORKING DRAFT:
{draft_seed or 'None'}

Instructions:
- Treat QUESTION as the operative ask. Use LITERAL QUESTION only as wording reference.
- Realize the brain contract exactly; do not reinterpret the question.
- Keep the answer speakable and natural, as if the candidate were saying it aloud now.
- Candidate Profile Facts are the only source for the candidate's current company, prior experience, and what the candidate built or led.
- Target Company Context and Target Role Context are application context only. Never present them as the candidate's past or current experience.
- Interviewer Context belongs only to the interviewer. Never attribute it to the candidate or the target role.
- If the working draft is good, improve clarity and polish without changing the contract.
- If the working draft is weak, or if it conflicts with the evidence modes, rebuild the answer from the contract and evidence only.
- Treat the evidence modes as hard permissions, not hints.
- If Profile evidence mode is none, do not add candidate background, role scope, years of experience, or achievement proof.
- If Profile evidence mode is orientation_only, use only minimal orientation and do not expand into proof or leadership scope unless explicitly required.
- If Profile evidence mode is one_best_proof, use at most one supporting candidate proof beyond a brief orientation.
- If Profile evidence mode is scope_only, stay on team size, management scope, or composition and do not broaden into general biography.
- If Company evidence mode is none, ignore target company context.
- If Company evidence mode is preference_alignment, use company context only to mirror preference areas, not to turn the answer into a fit pitch.
- If Prior context mode is none, do not weave prior interviewer context into the answer.
- When Plan source is safe_fallback, treat WORKING DRAFT as a weak seed and prefer the contract over the draft whenever they differ.
- Preserve the order of asks and the visible structure when the plan says coverage is ordered.
- If there are multiple asks or focus areas, use short paragraphs separated by a blank line. Do not use bullets or headings.
- Cover every ask explicitly. Do not silently drop the last ask.
- Prefer concrete evidence over generic labels. Mention what was built, led, designed, or achieved.
- Do not repeat the same profile sentence or title-based summary across paragraphs.
- Do not paste profile fragments or resume-style snippets verbatim. Rewrite them as natural spoken language.
- Use candidate context only when the plan allows it; otherwise keep biography out.
- Use company context only when the plan allows it; otherwise keep company pitch out.
- Use metrics only when the plan allows it and the evidence supports it.
- If question_completeness is partial or garbled, answer only the clearest complete ask and ignore incomplete tails.
- Do not copy evidence snippets verbatim if they sound like source text; paraphrase them into a natural spoken answer.
- Honor the requested style hint and target length.
- Return only the answer text.
"""

    @staticmethod
    def _extract_source_of_truth_context(
        interview_config: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
        candidate = interview_config.get("candidate") or {}
        company = interview_config.get("company") or {}
        interviewer = interview_config.get("interviewer") or {}
        target_context = interview_config.get("target_context") or {}
        target_company = target_context.get("company") if isinstance(target_context, dict) else {}
        target_role = target_context.get("role") if isinstance(target_context, dict) else {}
        target_interviewer = target_context.get("interviewer") if isinstance(target_context, dict) else {}

        if not isinstance(candidate, dict):
            candidate = {}
        if not isinstance(company, dict):
            company = {}
        if not isinstance(interviewer, dict):
            interviewer = {}
        if not isinstance(target_company, dict):
            target_company = {}
        if not isinstance(target_role, dict):
            target_role = {}
        if not isinstance(target_interviewer, dict):
            target_interviewer = {}

        if not target_company:
            target_company = {
                "name": company.get("companyName") or company.get("name") or "",
                "industry": company.get("industry") or "",
                "summary": company.get("companySummary") or company.get("companyDescription") or "",
                "culture": company.get("companyCulture") or company.get("culture") or "",
                "values": company.get("values") or [],
            }
        if not target_role:
            target_role = {
                "title": company.get("roleTitle") or company.get("positionTitle") or company.get("role_title") or "",
                "level": company.get("roleLevel") or company.get("role_level") or "",
                "description": company.get("jobDescription") or company.get("positionDescription") or company.get("job_description") or "",
                "requirements": company.get("roleRequirements") or company.get("positionRequirements") or company.get("role_requirements") or [],
                "responsibilities": company.get("roleResponsibilities") or company.get("role_responsibilities") or [],
                "interview_focus": company.get("interviewFocus") or company.get("interview_focus") or [],
            }

        merged_interviewer = {**interviewer}
        if target_interviewer:
            merged_interviewer = {**merged_interviewer, **target_interviewer}
        return candidate, target_company, target_role, merged_interviewer

    def _build_source_of_truth_context_block(
        self,
        interview_config: dict[str, Any],
        *,
        plan: BrainPlan | None = None,
    ) -> str:
        candidate, target_company, target_role, interviewer = self._extract_source_of_truth_context(interview_config)
        response_requirement = getattr(plan, "response_requirement", None)
        profile_mode = (
            self._normalize_text(getattr(response_requirement, "profile_evidence_mode", "support_if_relevant")).lower()
            or "support_if_relevant"
        )
        company_mode = (
            self._normalize_text(getattr(response_requirement, "company_evidence_mode", "support_if_relevant")).lower()
            or "support_if_relevant"
        )
        prior_mode = (
            self._normalize_text(getattr(response_requirement, "prior_context_mode", "support_if_relevant")).lower()
            or "support_if_relevant"
        )

        candidate_lines = [f"- Name: {self._normalize_text(candidate.get('name')) or 'None'}"]
        if profile_mode == "none":
            candidate_lines.append("- Candidate profile details: Restricted by profile evidence mode.")
        else:
            candidate_lines.extend(
                [
                    f"- Current role: {self._normalize_text(candidate.get('current_role') or candidate.get('currentRole')) or 'None'}",
                    f"- Current company: {self._normalize_text(candidate.get('company') or candidate.get('current_company') or candidate.get('currentCompany')) or 'None'}",
                ]
            )
            if profile_mode in {"support_if_relevant", "multi_proof"}:
                candidate_lines.append(
                    f"- Years of experience: {candidate.get('years_experience') or candidate.get('yearsExperience') or 'None'}"
                )
            elif profile_mode == "scope_only":
                candidate_lines.append("- Use structured evidence for management scope and team composition.")

        if company_mode == "none":
            target_company_lines = ["- Target company context: Restricted by company evidence mode."]
            target_role_lines = ["- Target role context: Restricted by company evidence mode."]
        elif company_mode == "preference_alignment":
            target_company_lines = [
                f"- Name: {self._normalize_text(target_company.get('name') or target_company.get('companyName')) or 'None'}",
                f"- Culture: {self._normalize_text(target_company.get('culture') or target_company.get('companyCulture')) or 'None'}",
                f"- Values: {' | '.join(target_company.get('values') or []) or 'None'}",
            ]
            target_role_lines = [
                f"- Title: {self._normalize_text(target_role.get('title') or target_role.get('roleTitle') or target_role.get('positionTitle')) or 'None'}",
                f"- Level: {self._normalize_text(target_role.get('level') or target_role.get('roleLevel')) or 'None'}",
            ]
        else:
            target_company_lines = [
                f"- Name: {self._normalize_text(target_company.get('name') or target_company.get('companyName')) or 'None'}",
                f"- Industry: {self._normalize_text(target_company.get('industry')) or 'None'}",
                f"- Summary: {self._normalize_text(target_company.get('summary') or target_company.get('companySummary') or target_company.get('companyDescription')) or 'None'}",
                f"- Culture: {self._normalize_text(target_company.get('culture') or target_company.get('companyCulture')) or 'None'}",
                f"- Values: {' | '.join(target_company.get('values') or []) or 'None'}",
            ]
            target_role_lines = [
                f"- Title: {self._normalize_text(target_role.get('title') or target_role.get('roleTitle') or target_role.get('positionTitle')) or 'None'}",
                f"- Level: {self._normalize_text(target_role.get('level') or target_role.get('roleLevel')) or 'None'}",
                f"- Description: {self._normalize_text(target_role.get('description') or target_role.get('jobDescription') or target_role.get('positionDescription')) or 'None'}",
                f"- Requirements: {' | '.join(target_role.get('requirements') or target_role.get('roleRequirements') or []) or 'None'}",
                f"- Responsibilities: {' | '.join(target_role.get('responsibilities') or target_role.get('roleResponsibilities') or []) or 'None'}",
                f"- Interview focus: {' | '.join(target_role.get('interview_focus') or target_role.get('interviewFocus') or []) or 'None'}",
            ]

        if prior_mode == "none":
            interviewer_lines = ["- Interviewer context: Restricted by prior context mode."]
        elif prior_mode == "disambiguate":
            interviewer_lines = [
                f"- Name: {self._normalize_text(interviewer.get('name')) or 'None'}",
                f"- Role title: {self._normalize_text(interviewer.get('role_title') or interviewer.get('roleTitle')) or 'None'}",
                f"- Company: {self._normalize_text(interviewer.get('company') or interviewer.get('companyName')) or 'None'}",
                f"- Focus areas: {' | '.join(interviewer.get('likely_focus_areas') or interviewer.get('likelyFocusAreas') or []) or 'None'}",
            ]
        else:
            interviewer_lines = [
                f"- Name: {self._normalize_text(interviewer.get('name')) or 'None'}",
                f"- Role title: {self._normalize_text(interviewer.get('role_title') or interviewer.get('roleTitle')) or 'None'}",
                f"- Company: {self._normalize_text(interviewer.get('company') or interviewer.get('companyName')) or 'None'}",
                f"- Background: {self._normalize_text(interviewer.get('background_summary') or interviewer.get('backgroundSummary')) or 'None'}",
                f"- Focus areas: {' | '.join(interviewer.get('likely_focus_areas') or interviewer.get('likelyFocusAreas') or []) or 'None'}",
            ]
        return "\n".join(
            [
                "CANDIDATE PROFILE FACTS:",
                *candidate_lines,
                "",
                "TARGET COMPANY CONTEXT (APPLICATION TARGET ONLY):",
                *target_company_lines,
                "",
                "TARGET ROLE CONTEXT (APPLICATION TARGET ONLY):",
                *target_role_lines,
                "",
                "INTERVIEWER CONTEXT:",
                *interviewer_lines,
            ]
        )

    def _build_answer_from_blueprint(
        self,
        *,
        plan: BrainPlan,
        evidence_pack: CompactEvidencePack,
        draft_text: str,
    ) -> str:
        blueprint = list(plan.answer_blueprint or [])
        if not blueprint:
            return ""

        sentence_bank = (
            self._draft_sentence_bank(
                draft_text=draft_text,
                allow_profile_context=plan.candidate_context_policy != "avoid",
            )
            if str(plan.plan_source or "").strip().lower() in {"llm_fast", "cached_stable"}
            else []
        )
        paragraphs: list[str] = []
        for segment in blueprint:
            paragraph = self._realize_blueprint_segment(
                plan=plan,
                evidence_pack=evidence_pack,
                segment=segment,
                sentence_bank=sentence_bank,
            )
            if paragraph:
                paragraphs.append(paragraph)

        if not paragraphs:
            return ""
        return self._join_answer_parts(paragraphs, plan=plan, add_terminal_period=False)

    def _realize_blueprint_segment(
        self,
        *,
        plan: BrainPlan,
        evidence_pack: CompactEvidencePack,
        segment: dict[str, Any],
        sentence_bank: list[str],
    ) -> str:
        purpose = self._normalize_text((segment or {}).get("purpose")).lower()
        ask_seed = " ".join(segment.get("ask_refs") or segment.get("required_elements") or [])
        preferred_sources = self._sources_for_blueprint_segment(
            plan=plan,
            evidence_pack=evidence_pack,
            preferred_types=list(segment.get("preferred_evidence_types") or []),
        )
        sentence = self._pop_best_sentence_for_prompt(ask_seed, sentence_bank) if sentence_bank else ""
        prefer_evidence = str(plan.plan_source or "").strip().lower() == "safe_fallback"
        if (
            sentence
            and "strong fit" in sentence.lower()
            and (
                "avoid_unframed_fit_close" in {self._normalize_text(item).lower() for item in list(plan.quality_guardrails or [])}
                or "strong_fit_claim_without_fit_ask" in {self._normalize_text(item).lower() for item in list(segment.get("avoid_topics") or [])}
            )
        ):
            sentence = ""
        detail = self._pick_best_detail_from_ask_terms(
            ask_terms=self._detail_terms_for_prompt(ask_seed),
            sources=preferred_sources,
        )
        primary = detail if prefer_evidence and detail else sentence or detail
        if purpose == "profile_core":
            return primary
        if purpose == "alignment":
            return primary
        if purpose in {"build_or_experience", "leadership_scope", "technical_positioning", "technical_approach"}:
            return primary
        if purpose == "team_composition":
            if detail:
                return f"Those teams included {self._normalize_text(detail).rstrip('.')}."
            return sentence
        if purpose == "intro_tail":
            return primary
        if purpose.startswith("preferences_"):
            return primary
        return primary

    @staticmethod
    def _sources_for_blueprint_segment(
        *,
        plan: Optional[BrainPlan],
        evidence_pack: CompactEvidencePack,
        preferred_types: list[str],
    ) -> list[str]:
        mapping = {
            "role_evidence": list(evidence_pack.role_evidence or []),
            "build_evidence": list(evidence_pack.build_evidence or []),
            "leadership_evidence": list(evidence_pack.leadership_evidence or []),
            "team_scope_evidence": list(evidence_pack.team_scope_evidence or []),
            "culture_alignment_evidence": list(evidence_pack.culture_alignment_evidence or []),
            "technical_alignment_evidence": list(evidence_pack.technical_alignment_evidence or []),
        }
        ordered: list[str] = []
        for key in list(preferred_types or []):
            ordered.extend(mapping.get(key, []))
        if not ordered:
            ordered.extend(list(evidence_pack.candidate_snippets or []))
            if LiveFinalizer._should_allow_company_context_in_fallback(plan):
                ordered.extend(list(evidence_pack.company_snippets or []))
        return ordered

    @staticmethod
    def _should_allow_company_context_in_fallback(plan: Optional[BrainPlan]) -> bool:
        if plan is None:
            return True
        if str(plan.company_context_policy or "").strip().lower() == "required":
            return True
        response_family = str(plan.response_family or "").strip().lower()
        return response_family in {"intro_alignment", "culture_preferences", "technical_fit"}

    def _preferred_structured_sources(
        self,
        *,
        plan: BrainPlan,
        evidence_pack: CompactEvidencePack,
    ) -> list[str]:
        family = self._normalize_text(plan.response_family).lower()
        if family == "intro_alignment":
            return [
                *list(evidence_pack.role_evidence or []),
                *list(evidence_pack.technical_alignment_evidence or []),
                *list(evidence_pack.build_evidence or []),
            ]
        if family in {"behavioral_story", "mixed_multi_part"}:
            return [
                *list(evidence_pack.build_evidence or []),
                *list(evidence_pack.leadership_evidence or []),
                *list(evidence_pack.team_scope_evidence or []),
            ]
        if family == "leadership_scope":
            return [
                *list(evidence_pack.leadership_evidence or []),
                *list(evidence_pack.team_scope_evidence or []),
            ]
        if family == "culture_preferences":
            return list(evidence_pack.culture_alignment_evidence or [])
        if family == "technical_fit":
            return [
                *list(evidence_pack.technical_alignment_evidence or []),
                *list(evidence_pack.role_evidence or []),
            ]
        return []

    def _pick_best_detail(self, plan: BrainPlan, evidence_pack: CompactEvidencePack) -> str:
        asks = list(plan.ordered_asks or [])
        focus_terms = self._plan_focus_terms(plan)
        prefer_candidate_details = self._should_prefer_candidate_details(plan)
        structured_preferred_sources = self._preferred_structured_sources(plan=plan, evidence_pack=evidence_pack)
        structured_detail = self._pick_best_detail_from_sources(
            sources=structured_preferred_sources,
            focus_terms=focus_terms,
            required=False,
            base_bonus=0.18,
        )
        if structured_detail:
            return structured_detail
        if evidence_pack.mode == "minimal":
            filtered_pack = CompactEvidencePack(
                plan_hash=evidence_pack.plan_hash,
                candidate_snippets=evidence_pack.candidate_snippets if plan.candidate_context_policy != "avoid" else [],
                company_snippets=evidence_pack.company_snippets if plan.company_context_policy != "avoid" else [],
                interviewer_snippets=evidence_pack.interviewer_snippets,
                role_evidence=evidence_pack.role_evidence,
                build_evidence=evidence_pack.build_evidence,
                leadership_evidence=evidence_pack.leadership_evidence,
                team_scope_evidence=evidence_pack.team_scope_evidence,
                culture_alignment_evidence=evidence_pack.culture_alignment_evidence,
                technical_alignment_evidence=evidence_pack.technical_alignment_evidence,
                supporting_metrics=evidence_pack.supporting_metrics,
                excluded_topics=evidence_pack.excluded_topics,
                mode=evidence_pack.mode,
            )
            if asks:
                detail = self._pick_detail_for_ask(asks[0], filtered_pack, plan=plan)
                if detail:
                    return detail
            return ""

        if prefer_candidate_details:
            preferred = self._pick_best_detail_from_sources(
                sources=list(evidence_pack.candidate_snippets or []),
                focus_terms=focus_terms,
                required=(plan.candidate_context_policy == "required"),
                base_bonus=0.12,
            )
            if preferred:
                return preferred

        scored: list[tuple[float, str]] = []
        candidate_required = plan.candidate_context_policy == "required"
        company_required = plan.company_context_policy == "required"
        company_context_allowed = self._should_allow_company_context_in_fallback(plan)
        pools = [
            (
                evidence_pack.candidate_snippets if plan.candidate_context_policy != "avoid" else [],
                candidate_required,
                0.12 if candidate_required else 0.0,
            ),
        ]
        if company_context_allowed and plan.company_context_policy != "avoid":
            pools.append(
                (
                    evidence_pack.company_snippets,
                    company_required,
                    0.08 if company_required else 0.0,
                )
            )

        for pool, required, base_bonus in pools:
            for item in pool:
                normalized = self._normalize_text(item)
                if not normalized:
                    continue
                item_terms = {
                    token
                    for token in re.findall(r"[a-z0-9]+", normalized.lower())
                    if len(token) > 2
                }
                overlap = len(item_terms & focus_terms) / max(len(focus_terms), 1) if focus_terms else 0.0
                if overlap <= 0.0 and not required:
                    continue
                scored.append((overlap + base_bonus, normalized))

        if not scored:
            return ""
        scored.sort(key=lambda item: item[0], reverse=True)
        best_score, best_text = scored[0]
        if best_score <= 0.0:
            return ""
        return self._sanitize_source_snippet(best_text)

    def _pick_detail_for_ask(
        self,
        ask: str,
        evidence_pack: CompactEvidencePack,
        *,
        plan: Optional[BrainPlan] = None,
    ) -> str:
        ask_terms = self._detail_terms_for_prompt(ask)
        if not ask_terms:
            return ""

        if self._should_prefer_candidate_details(plan):
            candidate_match = self._pick_best_detail_from_ask_terms(
                ask_terms=ask_terms,
                sources=list(evidence_pack.candidate_snippets or []),
            )
            if candidate_match:
                return candidate_match

        best_item = ""
        best_score = 0.0
        for item in self._iter_allowed_detail_items(plan=plan, evidence_pack=evidence_pack):
            item_terms = {
                token
                for token in re.findall(r"[a-z0-9]+", item.lower())
                if len(token) > 2 and token not in _DETAIL_STOPWORDS
            }
            score = len(item_terms & ask_terms) / max(len(ask_terms), 1)
            if score > best_score:
                best_score = score
                best_item = item
        if best_score <= 0.0:
            return ""
        return self._sanitize_source_snippet(best_item)

    @staticmethod
    def _detail_terms_for_prompt(prompt_text: str) -> set[str]:
        lowered = LiveFinalizer._normalize_text(prompt_text).lower()
        terms = {
            token
            for token in re.findall(r"[a-z0-9]+", lowered)
            if len(token) > 2 and token not in _DETAIL_STOPWORDS
        }
        if any(phrase in lowered for phrase in ("building from 0", "building from zero", "building from scratch", "from scratch")):
            terms.update({"built", "build", "founded", "created", "launched", "scaled", "started", "practice", "service", "product", "team", "model", "assets"})
        if any(phrase in lowered for phrase in ("team management", "teams you've managed", "teams you have managed", "how big were the teams", "team size")):
            terms.update({"managed", "managers", "management", "team", "teams", "reports", "direct", "indirect", "leadership", "leaders", "organization", "regions", "headcount", "scale"})
        if any(phrase in lowered for phrase in ("what roles did they have", "roles did they have", "what roles they have", "roles they have")):
            terms.update({"roles", "included", "engineers", "architects", "scientists", "delivery", "leads", "consultants", "managers"})
        if any(phrase in lowered for phrase in ("little bit about you", "about you", "about yourself")):
            terms.update({"background", "role", "technology", "director", "data", "ai"})
        return terms

    @staticmethod
    def _plan_focus_terms(plan: BrainPlan) -> set[str]:
        seed = " ".join(
            [
                plan.resolved_question or "",
                *list(plan.ordered_asks or []),
                *list(plan.coverage_points or []),
            ]
        )
        return {
            token
            for token in re.findall(r"[a-z0-9]+", seed.lower())
            if len(token) > 2 and token not in _DETAIL_STOPWORDS
        }

    @staticmethod
    def _iter_allowed_detail_items(
        *,
        plan: Optional[BrainPlan],
        evidence_pack: CompactEvidencePack,
    ) -> list[str]:
        items: list[str] = []
        if plan is None or plan.candidate_context_policy != "avoid":
            items.extend(list(evidence_pack.candidate_snippets or []))
            items.extend(list(evidence_pack.role_evidence or []))
            items.extend(list(evidence_pack.build_evidence or []))
            items.extend(list(evidence_pack.leadership_evidence or []))
            items.extend(list(evidence_pack.team_scope_evidence or []))
        if plan is None or (
            plan.company_context_policy != "avoid" and LiveFinalizer._should_allow_company_context_in_fallback(plan)
        ):
            items.extend(list(evidence_pack.company_snippets or []))
            items.extend(list(evidence_pack.culture_alignment_evidence or []))
            items.extend(list(evidence_pack.technical_alignment_evidence or []))
        items.extend(list(evidence_pack.supporting_metrics or []))
        return items

    def _conservative_opening(self, plan: BrainPlan, asks: list[str]) -> str:
        if not asks:
            return ""
        ask = asks[0]
        completeness = str(plan.question_completeness or "").strip().lower()
        if completeness != "complete":
            return f"On {self._shorten_ask_label(ask)}, I’d keep it simple."
        if len(asks) == 1:
            return f"On {self._shorten_ask_label(ask)}, I’d answer it this way."
        return "There are a couple of things I’d emphasize."

    def _fallback_to_safe_summary(self, *, plan: BrainPlan, question_text: str) -> str:
        asks = list(plan.ordered_asks or [])
        if asks:
            return f"On {self._shorten_ask_label(asks[0])}, I’d answer it directly and keep it aligned with the role and team you described."
        return self._normalize_text(question_text)

    def _build_structured_answer_from_draft(
        self,
        *,
        plan: BrainPlan,
        asks: list[str],
        draft_text: str,
        detail: str,
    ) -> str:
        normalized_draft = self._normalize_text(draft_text)
        if not normalized_draft:
            return ""
        coverage_points = [
            self._normalize_text(point)
            for point in list(plan.coverage_points or [])
            if self._normalize_text(point)
        ]
        if not coverage_points and len(asks) <= 1:
            return ""
        sentence_bank = self._draft_sentence_bank(
            draft_text=normalized_draft,
            allow_profile_context=plan.candidate_context_policy == "required",
        )
        if not sentence_bank and detail:
            sentence_bank = [detail]
        if not sentence_bank:
            return ""

        sections = coverage_points[:4] or asks[:4]
        use_explicit_labels = bool(coverage_points) and not self._should_prefer_candidate_details(plan)
        answer_parts: list[str] = []
        if len(sections) > 1:
            answer_parts.append(f"There are {len(sections)} parts I’d cover.")

        remaining_sentences = list(sentence_bank)
        ordinal_labels = ("First", "Second", "Third", "Finally")
        for index, section in enumerate(sections):
            sentence = self._pop_best_sentence_for_prompt(section, remaining_sentences)
            if not sentence and detail:
                sentence = detail
            if not sentence:
                continue
            if use_explicit_labels:
                answer_parts.append(f"In terms of {section}, {self._lowercase_first(sentence)}")
            else:
                prefix = ordinal_labels[min(index, len(ordinal_labels) - 1)]
                answer_parts.append(f"{prefix}, {self._lowercase_first(sentence)}")

        for ask in asks:
            if self._looks_like_priority_ask(ask) or self._looks_like_positive_preference_ask(ask):
                sentence = self._pop_best_sentence_for_prompt(ask, remaining_sentences)
                if sentence:
                    answer_parts.append(sentence)
            elif self._looks_like_avoid_ask(ask):
                sentence = self._pop_best_sentence_for_prompt(ask, remaining_sentences)
                if sentence:
                    answer_parts.append(sentence)
            elif self._looks_like_tolerance_ask(ask):
                sentence = self._pop_best_sentence_for_prompt(ask, remaining_sentences)
                if sentence:
                    answer_parts.append(sentence)

        if not answer_parts:
            answer_parts.extend(sentence_bank[:3])
        return self._join_answer_parts(answer_parts, plan=plan)

    def _build_structured_answer_from_plan(
        self,
        *,
        plan: BrainPlan,
        asks: list[str],
        evidence_pack: CompactEvidencePack,
        detail: str,
    ) -> str:
        detail_text = self._normalize_text(detail)
        allowed_items = self._iter_allowed_detail_items(plan=plan, evidence_pack=evidence_pack)
        if not detail_text and not any(allowed_items):
            return ""

        coverage_points = [
            self._normalize_text(point)
            for point in list(plan.coverage_points or [])
            if self._normalize_text(point)
        ]
        sections = asks[:4] if self._should_prefer_candidate_details(plan) and asks else (coverage_points[:4] or asks[:4])
        if not sections:
            return ""

        clause_bank = self._detail_clause_bank(detail_text) or [detail_text]
        answer_parts: list[str] = []
        if len(sections) > 1:
            answer_parts.append(f"There are {len(sections)} parts I’d emphasize.")

        use_explicit_labels = bool(coverage_points) and not self._should_prefer_candidate_details(plan)
        ordinal_labels = ("First", "Second", "Third", "Finally")
        for index, section in enumerate(sections):
            prompt_text = asks[index] if index < len(asks) else section
            ask_specific_detail = self._pick_detail_for_ask(prompt_text, evidence_pack, plan=plan)
            clause = ask_specific_detail or (clause_bank[index] if index < len(clause_bank) else detail_text)
            if not clause:
                continue
            if use_explicit_labels:
                answer_parts.append(f"In terms of {section}, {self._lowercase_first(clause)}")
            else:
                prefix = ordinal_labels[min(index, len(ordinal_labels) - 1)]
                answer_parts.append(f"{prefix}, {self._lowercase_first(clause)}")

        if any(self._looks_like_priority_ask(ask) or self._looks_like_positive_preference_ask(ask) for ask in asks):
            answer_parts.append("What I particularly value is seeing those conditions show up consistently in how the team operates")
        if any(self._looks_like_tolerance_ask(ask) for ask in asks):
            answer_parts.append("I’m comfortable with pace and some ambiguity as long as communication stays direct")
        elif any(self._looks_like_avoid_ask(ask) for ask in asks):
            answer_parts.append("I tend to avoid environments where those basics are missing")

        return self._join_answer_parts(answer_parts, plan=plan)

    def _join_answer_parts(
        self,
        answer_parts: list[str],
        *,
        plan: BrainPlan,
        add_terminal_period: bool = True,
    ) -> str:
        cleaned_parts: list[str] = []
        for part in answer_parts:
            normalized = self._normalize_text(part)
            if not normalized:
                continue
            if add_terminal_period:
                normalized = normalized.rstrip(". ") + "."
            cleaned_parts.append(normalized)
        if not cleaned_parts:
            return ""
        if max(len(plan.ordered_asks or []), len(plan.coverage_points or [])) > 1:
            return "\n\n".join(cleaned_parts)
        return " ".join(cleaned_parts)

    def _apply_visible_structure(
        self,
        *,
        text: str,
        plan: BrainPlan,
        aggressive_sentence_split: bool = True,
    ) -> str:
        normalized = self._normalize_text_preserving_paragraphs(text)
        if not normalized:
            return ""
        if max(len(plan.ordered_asks or []), len(plan.coverage_points or [])) <= 1:
            return normalized
        if "\n\n" in normalized:
            return normalized

        structured = normalized
        transition_patterns = (
            r"\s+(First,\s+)",
            r"\s+(Second,\s+)",
            r"\s+(Third,\s+)",
            r"\s+(Finally,\s+)",
            r"\s+(Most recently,\s+)",
            r"\s+(Earlier in my career,\s+)",
            r"\s+(Earlier,\s+)",
            r"\s+(In my most recent role,\s+)",
            r"\s+(At the largest scale,\s+)",
            r"\s+(In terms of [^,]{1,80},\s+)",
            r"\s+(Culture-wise,\s+)",
            r"\s+(On team management,\s+)",
            r"\s+(What I particularly value\s+)",
            r"\s+(What(?:'s| is) absolutely important to me\s+)",
            r"\s+(What I absolutely don't like\s+)",
            r"\s+(What I tend to avoid\s+)",
        )
        for pattern in transition_patterns:
            structured = re.sub(pattern, r"\n\n\1", structured)
        structured = structured.strip()
        if "\n\n" in structured:
            return structured
        if not aggressive_sentence_split:
            return structured

        sentences = self._split_sentences_for_visible_structure(structured)
        if len(sentences) < 2:
            return structured

        ask_count = max(len(plan.ordered_asks or []), len(plan.coverage_points or []), 2)
        target_blocks = min(ask_count, max(2, (len(sentences) + 1) // 2))
        if target_blocks <= 1:
            return structured

        blocks: list[str] = []
        index = 0
        remaining_sentences = len(sentences)
        remaining_blocks = target_blocks
        while index < len(sentences) and remaining_blocks > 0:
            take = max(1, (remaining_sentences + remaining_blocks - 1) // remaining_blocks)
            block = " ".join(sentences[index : index + take]).strip()
            if block:
                blocks.append(block)
            index += take
            remaining_sentences = len(sentences) - index
            remaining_blocks -= 1

        if len(blocks) >= 2:
            return "\n\n".join(blocks)
        return structured

    def _meets_structural_quality_floor(self, *, plan: BrainPlan, text: str) -> bool:
        normalized = self._normalize_text(text)
        if not normalized or len(normalized.split()) < 6:
            return False

        lowered = normalized.lower()
        asks = list(plan.ordered_asks or [])
        guardrails = {self._normalize_text(item).lower() for item in list(plan.quality_guardrails or [])}
        if any(self._looks_like_avoid_ask(ask) for ask in asks):
            if not any(needle in lowered for needle in ("avoid", "don't like", "do not like", "not like", "not a fit", "micromanagement")):
                return False
        elif any(self._looks_like_tolerance_ask(ask) for ask in asks):
            if not any(needle in lowered for needle in ("comfortable with", "open to", "don't mind", "do not mind")):
                return False
        elif any(self._looks_like_priority_ask(ask) or self._looks_like_positive_preference_ask(ask) for ask in asks):
            if not any(needle in lowered for needle in ("important", "value", "looking for", "care about")):
                return False

        brain_draft = self._normalize_text(plan.draft_answer)
        if (
            brain_draft
            and normalized == brain_draft
            and str(plan.question_completeness or "").strip().lower() == "complete"
            and str(plan.plan_source or "").strip().lower() in {"llm_fast", "cached_stable"}
        ):
            return True

        coverage_points = [
            self._normalize_text(point).lower()
            for point in list(plan.coverage_points or [])
            if self._normalize_text(point)
        ]
        if coverage_points and (bool(plan.ordered_coverage_required) or len(coverage_points) > 1):
            mentioned = 0
            for point in coverage_points[:4]:
                point_tokens = [token for token in re.findall(r"[a-z0-9']+", point) if token]
                if point_tokens and all(token in lowered for token in point_tokens):
                    mentioned += 1

            required_mentions = min(len(coverage_points[:4]), 3)
            if mentioned < required_mentions:
                return False

        if "avoid_unframed_fit_close" in guardrails and "strong fit" in lowered:
            return False
        if "avoid_biography" in guardrails and any(
            phrase in lowered
            for phrase in (
                "after 20 years",
                "throughout my career",
                "my experience spans",
            )
        ):
            return False
        if "avoid_unsupported_metrics" in guardrails and re.search(r"\b\d+[%+]\b|\b\d+\s*(accounts|applications|reports)\b", lowered):
            asks_text = " ".join(ask.lower() for ask in asks)
            if not any(term in asks_text for term in ("how big", "how many", "outcome", "impact", "results", "scope")):
                return False

        return True

    @staticmethod
    def _draft_sentence_bank(*, draft_text: str, allow_profile_context: bool) -> list[str]:
        sentences = [
            LiveFinalizer._normalize_text(sentence)
            for sentence in re.split(r"(?<=[.!?])\s+", draft_text)
            if LiveFinalizer._normalize_text(sentence)
        ]
        if allow_profile_context:
            return sentences
        filtered: list[str] = []
        for sentence in sentences:
            lowered = sentence.lower()
            if re.search(r"\bafter \d+\s+years\b", lowered):
                continue
            if any(
                phrase in lowered
                for phrase in (
                    "my experience spans",
                    "most recently",
                    "i'm a ",
                    "i am a ",
                    "i've spent",
                    "i have spent",
                )
            ):
                continue
            filtered.append(sentence)
        return filtered or sentences[:2]

    @staticmethod
    def _pop_best_sentence_for_prompt(prompt_text: str, sentences: list[str]) -> str:
        if not sentences:
            return ""
        prompt_terms = {
            token
            for token in re.findall(r"[a-z0-9]+", prompt_text.lower())
            if len(token) > 2
        }
        if not prompt_terms:
            return sentences.pop(0)

        best_index = 0
        best_score = -1.0
        for index, sentence in enumerate(sentences):
            sentence_terms = {
                token
                for token in re.findall(r"[a-z0-9]+", sentence.lower())
                if len(token) > 2
            }
            score = len(prompt_terms & sentence_terms)
            if score > best_score:
                best_score = score
                best_index = index
        return sentences.pop(best_index)

    @staticmethod
    def _lowercase_first(text: str) -> str:
        normalized = LiveFinalizer._normalize_text(text)
        if not normalized:
            return ""
        return normalized[0].lower() + normalized[1:]

    @staticmethod
    def _detail_clause_bank(detail_text: str) -> list[str]:
        clauses = [
            LiveFinalizer._normalize_text(clause)
            for clause in re.split(r",|\band\b", detail_text, flags=re.IGNORECASE)
            if LiveFinalizer._normalize_text(clause)
        ]
        return clauses[:4]

    @staticmethod
    def _extract_preference_qualities(detail: str) -> list[str]:
        lowered = LiveFinalizer._normalize_text(detail).lower()
        qualities: list[str] = []
        for needle, phrase in (
            ("pragmatic", "a pragmatic culture"),
            ("execution focus", "strong execution"),
            ("execution", "strong execution"),
            ("empathy", "empathy"),
            ("speed", "speed"),
            ("collabor", "collaborative teams"),
            ("team", "collaborative teams"),
            ("clear", "clear expectations"),
            ("ownership", "clear ownership"),
            ("bureaucr", "low bureaucracy"),
        ):
            if needle in lowered and phrase not in qualities:
                qualities.append(phrase)
        return qualities

    @staticmethod
    def _looks_like_preference_ask(ask: str) -> bool:
        lowered = LiveFinalizer._normalize_text(ask).lower()
        return any(
            phrase in lowered
            for phrase in (
                "looking for",
                "important for you",
                "important to you",
                "what matters to you",
                "what matters most",
                "don't like",
                "do not like",
                "don't mind",
                "do not mind",
                "open to",
                "comfortable with",
                "avoid",
            )
        )

    @staticmethod
    def _looks_like_avoid_ask(ask: str) -> bool:
        lowered = LiveFinalizer._normalize_text(ask).lower()
        return any(
            phrase in lowered
            for phrase in (
                "don't like",
                "do not like",
                "not like",
                "avoid",
            )
        )

    @staticmethod
    def _looks_like_priority_ask(ask: str) -> bool:
        lowered = LiveFinalizer._normalize_text(ask).lower()
        return any(
            phrase in lowered
            for phrase in (
                "important for you",
                "important to you",
                "what matters to you",
                "what matters most",
            )
        )

    @staticmethod
    def _looks_like_positive_preference_ask(ask: str) -> bool:
        lowered = LiveFinalizer._normalize_text(ask).lower()
        return any(
            phrase in lowered
            for phrase in (
                "absolutely like",
                "absolutely value",
                "absolutely look for",
                "looking for",
                "what do you like",
            )
        )

    @staticmethod
    def _looks_like_tolerance_ask(ask: str) -> bool:
        lowered = LiveFinalizer._normalize_text(ask).lower()
        return any(
            phrase in lowered
            for phrase in (
                "don't mind",
                "do not mind",
                "open to",
                "comfortable with",
            )
        )

    @staticmethod
    def _should_prefer_candidate_details(plan: Optional[BrainPlan]) -> bool:
        if plan is None:
            return False
        if str(plan.candidate_context_policy or "").strip().lower() != "required":
            return False
        if str(plan.answer_contract or "").strip().lower() == "business_with_outcomes":
            return True
        if str(plan.question_type or "").strip().lower() in {"behavioral", "business"}:
            return True
        asks_text = " ".join(LiveFinalizer._normalize_text(ask) for ask in list(plan.ordered_asks or []))
        lowered = asks_text.lower()
        return any(
            phrase in lowered
            for phrase in (
                "your experience",
                "building from 0",
                "building from scratch",
                "team management",
                "teams you've managed",
                "what roles did they have",
                "led",
                "managed",
                "examples",
            )
        )

    def _pick_best_detail_from_sources(
        self,
        *,
        sources: list[str],
        focus_terms: set[str],
        required: bool,
        base_bonus: float,
    ) -> str:
        scored: list[tuple[float, str]] = []
        for item in list(sources or []):
            normalized = self._normalize_text(item)
            if not normalized:
                continue
            item_terms = {
                token
                for token in re.findall(r"[a-z0-9]+", normalized.lower())
                if len(token) > 2
            }
            overlap = len(item_terms & focus_terms) / max(len(focus_terms), 1) if focus_terms else 0.0
            if overlap <= 0.0 and not required:
                continue
            scored.append((overlap + base_bonus, normalized))
        if not scored:
            return ""
        scored.sort(key=lambda item: item[0], reverse=True)
        best_score, best_text = scored[0]
        if best_score <= 0.0:
            return ""
        return self._sanitize_source_snippet(best_text)

    def _pick_best_detail_from_ask_terms(
        self,
        *,
        ask_terms: set[str],
        sources: list[str],
    ) -> str:
        best_item = ""
        best_score = 0.0
        for item in list(sources or []):
            item_terms = {
                token
                for token in re.findall(r"[a-z0-9]+", item.lower())
                if len(token) > 2 and token not in _DETAIL_STOPWORDS
            }
            score = len(item_terms & ask_terms) / max(len(ask_terms), 1)
            if score > best_score:
                best_score = score
                best_item = item
        if best_score <= 0.0:
            return ""
        return self._sanitize_source_snippet(best_item)

    @staticmethod
    def _sanitize_source_snippet(text: str) -> str:
        normalized = LiveFinalizer._normalize_text(text)
        if not normalized:
            return ""
        if len(normalized.split()) > 18:
            normalized = " ".join(normalized.split()[:18]).rstrip(",.;:") + "."
        return normalized

    @staticmethod
    def _shorten_ask_label(ask: str) -> str:
        normalized = LiveFinalizer._normalize_text(ask)
        if len(normalized) <= 60:
            return normalized
        return normalized[:57].rstrip() + "..."

    @staticmethod
    def _join_phrases(phrases: list[str]) -> str:
        normalized = [LiveFinalizer._normalize_text(item).strip(" ,.;:") for item in phrases if LiveFinalizer._normalize_text(item)]
        if not normalized:
            return ""
        if len(normalized) == 1:
            return normalized[0]
        if len(normalized) == 2:
            return f"{normalized[0]} and {normalized[1]}"
        return f"{', '.join(normalized[:-1])}, and {normalized[-1]}"

    @staticmethod
    def _split_sentences_for_visible_structure(text: str) -> list[str]:
        return [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", text)
            if sentence.strip()
        ]

    @staticmethod
    def _to_bullets(text: str, *, limit: int) -> list[str]:
        bullets = [
            sentence.strip().rstrip(".!?")
            for sentence in re.split(r"(?<=[.!?])\s+", text)
            if sentence.strip()
        ]
        compacted: list[str] = []
        for bullet in bullets:
            normalized = LiveFinalizer._normalize_text(bullet)
            if normalized:
                compacted.append(normalized)
            if len(compacted) >= limit:
                break
        return compacted or ([LiveFinalizer._normalize_text(text)] if LiveFinalizer._normalize_text(text) else [])

    @staticmethod
    def _format_history(history: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for turn in history[-5:]:
            speaker = (turn.get("speaker") or turn.get("role") or "interviewer").upper()
            text = LiveFinalizer._normalize_text(turn.get("text") or turn.get("content") or "")
            if text:
                lines.append(f"{speaker}: {text}")
        return "\n".join(lines) if lines else "INTERVIEWER: Not available"

    @staticmethod
    def _normalize_text(value: Any) -> str:
        return " ".join(str(value or "").split()).strip()

    @staticmethod
    def _normalize_text_preserving_paragraphs(value: Any) -> str:
        raw = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
        paragraphs = [
            " ".join(paragraph.split()).strip()
            for paragraph in re.split(r"\n\s*\n+", raw)
        ]
        normalized = [paragraph for paragraph in paragraphs if paragraph]
        return "\n\n".join(normalized).strip()

    @staticmethod
    def _sanitize_output_text(text: str) -> tuple[str, bool]:
        original = str(text or "")
        cleaned = original.strip()
        changed = False
        for pattern in (
            r"^\s*FULL RESPONSE\s*:?\s*",
            r"^\s*ANSWER\s*:?\s*",
            r"^\s*RESPONSE\s*:?\s*",
            r"^\s*#+\s*FULL RESPONSE\s*",
            r"^\s*#+\s*ANSWER\s*",
            r"^\s*[-*]\s*FULL RESPONSE\s*:?\s*",
        ):
            new_cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
            if new_cleaned != cleaned:
                cleaned = new_cleaned
                changed = True
        cleaned = LiveFinalizer._normalize_text_preserving_paragraphs(cleaned)
        return cleaned, changed

    def _resolve_adapter(self, *, alias: str) -> Optional[Any]:
        if os.getenv("PYTEST_CURRENT_TEST"):
            return None

        runtime_config = _get_runtime_config() or {}
        runtime_llm = runtime_config.get("llm") or {}
        runtime_provider = str(runtime_llm.get("provider") or "").strip().lower()
        runtime_enabled = bool(runtime_llm.get("enabled"))
        runtime_api_key = runtime_llm.get("api_key") or ""
        runtime_model = str(runtime_llm.get("model") or "").strip()

        if alias == "main":
            if runtime_enabled and runtime_provider == "anthropic" and runtime_api_key:
                adapter = AnthropicLLMAdapter(model=runtime_model or "claude-sonnet-4-5-20250929")
                adapter.api_key = runtime_api_key
                return adapter
            if runtime_enabled and runtime_provider == "openai" and runtime_api_key:
                adapter = OpenAILLMAdapter(model=runtime_model or "gpt-4o")
                adapter.api_key = runtime_api_key
                return adapter
            if runtime_enabled and runtime_provider == "ollama":
                return OllamaLLMAdapter(model=runtime_model or "qwen3.5:latest", base_url=runtime_llm.get("base_url") or "http://localhost:11434")
        return None

    def _metadata(self) -> dict[str, Any]:
        runtime_config = _get_runtime_config() or {}
        runtime_llm = runtime_config.get("llm") or {}
        return {
            "provider": None,
            "model": None,
            "configured_provider": runtime_llm.get("provider"),
            "configured_model": runtime_llm.get("model"),
            "llm_called": False,
            "finalizer_fallback_kind": None,
            "emit_failure_kind": "",
            "finalizer_primary_mode": "normal",
            "finalizer_primary_success": False,
            "recovery_draft_available": False,
            "finalizer_recovery_attempted": False,
            "finalizer_recovery_kind": "none",
            "finalizer_recovery_success": False,
            "finalizer_recovery_skipped_reason": "",
        }
