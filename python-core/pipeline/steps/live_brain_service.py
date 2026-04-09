from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from hashlib import sha1
from time import perf_counter
from typing import Any, Optional

from adapters.llm_adapter import AnthropicLLMAdapter, OpenAILLMAdapter, OllamaLLMAdapter, _get_runtime_config
from contracts.models import AskIntent, BrainPlan, BrainSnapshot, InterviewerNeed, ResponseRequirement


_QUESTION_LEADS = (
    "what",
    "how",
    "why",
    "when",
    "where",
    "who",
    "which",
    "tell me",
    "describe",
    "explain",
    "walk me through",
    "can you",
    "could you",
    "would you",
    "do you",
    "are you",
    "is there",
)
_REQUEST_INTENT_LEADS = (
    "tell us",
    "tell me",
    "also cover",
    "describe",
    "explain",
    "walk us through",
    "walk me through",
    "start telling us",
    "start telling me",
    "give me a sense of",
    "give us a sense of",
    "help me understand",
    "i want to get a sense of",
    "i wanna get a sense of",
    "i'd like to hear about",
    "i would like to hear about",
    "i'd love to hear about",
    "i would love to hear about",
    "i'm curious to hear about",
    "i am curious to hear about",
    "very curious to hear about",
    "curious to hear about",
)
_FILLER_STARTS = (
    "and ",
    "or ",
    "like",
    "now ",
    "so ",
    "yeah",
    "but ",
    "this ",
    "we ",
    "i ",
)
_PREAMBLE_PHRASES = (
    "we will talk about",
    "we were talking about",
    "i just wanted to ask you",
    "i wanted to ask you",
    "let's talk about",
)
_INTERVIEWER_ROLE_BRIEF_TERMS = (
    "i'm looking for",
    "i am looking for",
    "what i'm really looking for",
    "what i am really looking for",
    "we're looking for",
    "we are looking for",
    "looking for someone who",
    "the role",
    "that's the role",
    "so that's the role",
    "we need",
    "there's a need",
    "there is a need",
    "the company is trying to",
    "we're trying to",
    "we are trying to",
    "we've started down this",
    "we have started down this",
)
_INTERVIEWER_SELF_CONTEXT_TERMS = (
    "my name is",
    "i'm a",
    "i am a",
    "i've been here",
    "i have been here",
    "i joined",
    "i only became",
    "my background",
    "my direct expertise",
    "i have 20 years",
    "i've done",
    "i have done",
)
_INTERVIEWER_META_TERMS = (
    "any questions there",
    "any questions for me",
    "do you have any questions",
    "questions for me",
    "what you can expect from the process",
    "next step",
    "take home",
    "panel interview",
    "that's the process",
)
_COVERAGE_MARKERS = (
    "in terms of",
    "regarding",
    "around",
    "across",
    "about",
    "for",
)
_COVERAGE_STOPWORDS = {
    "the",
    "a",
    "an",
    "your",
    "their",
    "this",
    "that",
    "these",
    "those",
    "kind",
    "kinds",
    "things",
    "thing",
    "terms",
}
_COVERAGE_REJECT_TOKENS = {
    "i",
    "me",
    "my",
    "mine",
    "you",
    "your",
    "yours",
    "we",
    "our",
    "ours",
    "us",
    "they",
    "their",
    "theirs",
    "them",
    "he",
    "his",
    "him",
    "she",
    "her",
    "hers",
    "it",
    "its",
}
_COVERAGE_LEADING_NOISE_TOKENS = {
    "and",
    "or",
    "what",
    "which",
    "who",
    "why",
    "how",
    "when",
    "where",
}
_DANGLING_ENDS = {
    "absolutely",
    "like",
    "also",
    "about",
    "and",
    "or",
    "the",
    "a",
    "an",
    "of",
    "to",
    "for",
    "with",
    "in",
    "on",
    "that",
    "this",
    "these",
    "those",
    "your",
    "their",
    "our",
    "my",
}
_QUESTION_SPLIT_CONNECTORS = {
    "and",
    "or",
    "then",
    "also",
    "so",
    "but",
    "yeah",
    "okay",
    "ok",
}
_RECOVERABLE_OPEN_TAIL_TOKENS = {
    "and",
    "or",
    "then",
    "also",
    "so",
    "but",
    "yeah",
    "okay",
    "ok",
}
_TECHNICAL_SIGNAL_TERMS = {
    "architecture",
    "architect",
    "system",
    "systems",
    "design",
    "tradeoff",
    "tradeoffs",
    "scalability",
    "performance",
    "latency",
    "stack",
    "api",
    "apis",
    "schema",
    "schemas",
    "infra",
    "infrastructure",
    "platform",
    "platforms",
    "data model",
    "database",
    "databases",
}
_STRATEGIC_SIGNAL_TERMS = {
    "strategy",
    "business",
    "outcome",
    "outcomes",
    "impact",
    "stakeholder",
    "stakeholders",
    "executive",
    "roadmap",
    "priorities",
    "operating model",
    "transformation",
    "delivery model",
    "value",
    "growth",
}
_METRIC_SIGNAL_TERMS = {
    "metric",
    "metrics",
    "measure",
    "measured",
    "numbers",
    "number",
    "kpi",
    "kpis",
    "result",
    "results",
    "impact",
    "outcome",
    "outcomes",
}
_NON_FILLER_LIKE_PREV_TOKENS = {
    "don't",
    "dont",
    "not",
    "do",
    "did",
    "does",
    "would",
    "could",
    "can",
    "can't",
    "cannot",
    "should",
    "shouldn't",
}
_PREFERENCE_INTENSIFIERS = {
    "absolutely",
    "really",
    "generally",
    "typically",
    "usually",
    "personally",
}
_PREFERENCE_SIGNAL_TERMS = {
    "looking for",
    "important for you",
    "important to you",
    "what matters to you",
    "what matters most",
    "don't like",
    "do not like",
    "don't mind",
    "do not mind",
    "avoid",
    "open to",
    "comfortable with",
}

_ALL_QUESTION_LIKE_LEADS = tuple(dict.fromkeys([*_QUESTION_LEADS, *_REQUEST_INTENT_LEADS]))


@dataclass
class LiveBrainServiceConfig:
    llm_alias: str = "fast"
    llm_timeout_sec: float = 3.4
    llm_temperature: float = 0.1
    llm_max_tokens: int = 480
    stable_quiet_ms: int = 300
    direct_confidence_threshold: float = 0.84


class LiveBrainService:
    def __init__(
        self,
        config: Optional[LiveBrainServiceConfig] = None,
    ):
        self.config = config or LiveBrainServiceConfig()
        self.last_llm_failure_kind: str = ""

    async def plan(
        self,
        *,
        snapshot: BrainSnapshot,
        interview_config: dict[str, Any],
        previous_plan: Optional[BrainPlan] = None,
    ) -> BrainPlan:
        started = perf_counter()
        self.last_llm_failure_kind = ""
        llm_plan, llm_failure_kind = await self._plan_with_llm(
            snapshot=snapshot,
            interview_config=interview_config,
            previous_plan=previous_plan,
        )
        if llm_plan is not None:
            normalized_llm_plan = llm_plan.model_copy(
                update={
                    "generated_at": snapshot.timestamp,
                    "plan_source": "llm_fast",
                    "reasoning_summary": llm_plan.reasoning_summary
                    or "Live brain plan generated from the latest interviewer snapshot.",
                }
            )
            carried_plan = self._carry_forward_previous_semantic_plan(
                snapshot=snapshot,
                current_plan=normalized_llm_plan,
                previous_plan=previous_plan,
            )
            if carried_plan is not None:
                return carried_plan
            return normalized_llm_plan

        plan = self._plan_safely(snapshot=snapshot, interview_config=interview_config)
        carried_plan = self._carry_forward_previous_semantic_plan(
            snapshot=snapshot,
            current_plan=plan,
            previous_plan=previous_plan,
        )
        if carried_plan is not None:
            carried_reason = self._build_semantic_carry_forward_reason(
                current_plan=plan,
                llm_failure_kind=llm_failure_kind,
            )
            return carried_plan.model_copy(
                update={
                    "generated_at": snapshot.timestamp,
                    "reasoning_summary": carried_reason,
                }
            )
        elapsed_ms = int((perf_counter() - started) * 1000)
        failure_suffix = (
            f" after fast-planner {llm_failure_kind.replace('_', '-')} "
            if llm_failure_kind
            else " after fast-planner unavailable "
        )
        return plan.model_copy(
            update={
                "reasoning_summary": f"Live brain used safe fallback{failure_suffix}({elapsed_ms} ms).",
                "generated_at": snapshot.timestamp,
            }
        )

    def safe_plan(
        self,
        *,
        snapshot: BrainSnapshot,
        interview_config: Optional[dict[str, Any]] = None,
        reasoning_summary: Optional[str] = None,
    ) -> BrainPlan:
        plan = self._plan_safely(snapshot=snapshot, interview_config=interview_config)
        return plan.model_copy(
            update={
                "reasoning_summary": (
                    reasoning_summary
                    or "Live brain used immediate safe fallback from the latest interviewer snapshot."
                ),
                "generated_at": snapshot.timestamp,
            }
        )

    @staticmethod
    def _metadata_value_present(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, tuple, set, dict)):
            return bool(value)
        return True

    def _merge_metadata_dicts(self, *values: Any) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for value in values:
            if not isinstance(value, dict):
                continue
            for key, item in value.items():
                if key not in merged or not self._metadata_value_present(merged.get(key)):
                    if self._metadata_value_present(item):
                        merged[key] = item
        return merged

    def _normalize_interview_metadata(
        self, interview_config: Optional[dict[str, Any]]
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        config = interview_config or {}
        target_context = config.get("target_context") or {}
        target_company = target_context.get("company") if isinstance(target_context, dict) else {}
        target_role = target_context.get("role") if isinstance(target_context, dict) else {}
        target_interviewer = target_context.get("interviewer") if isinstance(target_context, dict) else {}

        candidate = self._merge_metadata_dicts(
            config.get("candidate"),
            config.get("candidate_profile"),
        )
        company = self._merge_metadata_dicts(
            config.get("company"),
            config.get("company_info"),
            config.get("target_company_info"),
            config.get("target_role_info"),
            target_company,
            target_role,
        )
        interviewer = self._merge_metadata_dicts(
            config.get("interviewer"),
            config.get("interviewer_profile"),
            target_interviewer,
        )
        return candidate, company, interviewer

    @staticmethod
    def plan_hash(plan: BrainPlan) -> str:
        payload = {
            "resolved_question": plan.resolved_question,
            "ordered_asks": list(plan.ordered_asks or []),
            "coverage_points": list(plan.coverage_points or []),
            "ask_intents": [item.model_dump(mode="json") for item in list(plan.ask_intents or [])],
            "interviewer_need": plan.interviewer_need.model_dump(mode="json"),
            "response_requirement": plan.response_requirement.model_dump(mode="json"),
            "context_focus": list(plan.context_focus or []),
            "question_completeness": plan.question_completeness,
            "question_type": plan.question_type,
            "response_shape": plan.response_shape,
            "answer_contract": plan.answer_contract,
            "delivery_instructions": list(plan.delivery_instructions or []),
            "tone": plan.tone,
            "directness": plan.directness,
            "include_profile_opening": plan.include_profile_opening,
            "evidence_depth": plan.evidence_depth,
            "metrics_policy": plan.metrics_policy,
            "company_context_policy": plan.company_context_policy,
            "candidate_context_policy": plan.candidate_context_policy,
            "ordered_coverage_required": plan.ordered_coverage_required,
            "target_length": plan.target_length,
            "serve_mode": plan.serve_mode,
        }
        return sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    @staticmethod
    def plans_equivalent(left: Optional[BrainPlan], right: Optional[BrainPlan]) -> bool:
        if left is None or right is None:
            return False
        return (
            LiveBrainService._normalize_text(left.resolved_question) == LiveBrainService._normalize_text(right.resolved_question)
            and [LiveBrainService._normalize_text(ask) for ask in left.ordered_asks]
            == [LiveBrainService._normalize_text(ask) for ask in right.ordered_asks]
            and [LiveBrainService._normalize_text(point) for point in left.coverage_points]
            == [LiveBrainService._normalize_text(point) for point in right.coverage_points]
            and str(left.question_completeness or "").strip().lower()
            == str(right.question_completeness or "").strip().lower()
        )

    @staticmethod
    def _question_completeness_rank(plan: Optional[BrainPlan]) -> int:
        normalized = str(getattr(plan, "question_completeness", "") or "").strip().lower()
        if normalized == "complete":
            return 3
        if normalized == "partial":
            return 2
        if normalized == "garbled":
            return 1
        return 0

    def _carry_forward_previous_semantic_plan(
        self,
        *,
        snapshot: BrainSnapshot,
        current_plan: Optional[BrainPlan],
        previous_plan: Optional[BrainPlan],
    ) -> Optional[BrainPlan]:
        if current_plan is None or previous_plan is None:
            return None

        previous_source = str(previous_plan.plan_source or "").strip().lower()
        if previous_source not in {"llm_fast", "cached_stable"}:
            return None
        if self._question_completeness_rank(previous_plan) < 3:
            return None

        previous_asks = [
            self._normalize_text(ask)
            for ask in list(previous_plan.ordered_asks or [])
            if self._normalize_text(ask)
        ]
        if not previous_asks:
            return None

        current_asks = self._normalize_unique_strings(
            [
                *list(current_plan.ordered_asks or []),
                *list(current_plan.raw_detected_asks or []),
            ]
        )
        previous_rank = self._question_completeness_rank(previous_plan)
        current_rank = self._question_completeness_rank(current_plan)
        if current_rank > previous_rank:
            return None

        snapshot_text = self._normalize_text(snapshot.snapshot_text).lower()
        previous_lead = self._normalize_text(previous_asks[0]).rstrip("?.!").lower()
        preserves_previous_semantics = bool(previous_lead and previous_lead in snapshot_text)
        if not preserves_previous_semantics:
            preserves_previous_semantics = any(
                self._asks_semantically_overlap(previous_ask, current_ask)
                for previous_ask in previous_asks
                for current_ask in current_asks
            )
        if not preserves_previous_semantics:
            return None

        if current_asks:
            introduces_novel_semantics = any(
                not any(self._asks_semantically_overlap(current_ask, previous_ask) for previous_ask in previous_asks)
                for current_ask in current_asks
            )
            if introduces_novel_semantics:
                return None

        current_source = str(current_plan.plan_source or "").strip().lower()
        current_has_same_or_weaker_shape = len(current_asks or previous_asks) <= len(previous_asks)
        if current_rank == previous_rank == 3:
            if current_source != "safe_fallback":
                return None
            if not current_has_same_or_weaker_shape:
                return None
        elif current_rank >= previous_rank and current_source != "safe_fallback":
            return None

        merged_context_focus = self._normalize_unique_strings(
            [*list(current_plan.context_focus or []), *list(previous_plan.context_focus or [])]
        )[:4]
        merged_alignment_brief = self._normalize_unique_strings(
            [*list(current_plan.alignment_brief or []), *list(previous_plan.alignment_brief or [])]
        )[:3]
        merged_supporting_context = self._normalize_unique_strings(
            [
                *list(current_plan.supporting_interviewer_context or []),
                *list(previous_plan.supporting_interviewer_context or []),
            ]
        )[:6]
        merged_raw_detected_asks = self._normalize_unique_strings(
            [
                *list(current_plan.raw_detected_asks or []),
                *list(previous_plan.raw_detected_asks or []),
                *list(previous_plan.ordered_asks or []),
            ]
        )[:5]
        merged_dropped_noise = self._normalize_unique_strings(
            [*list(current_plan.dropped_noise_clauses or []), *list(previous_plan.dropped_noise_clauses or [])]
        )[:8]
        contextualized_question = self._derive_contextualized_question(
            literal_question=previous_plan.literal_question,
            resolved_question=previous_plan.resolved_question,
            question_completeness=previous_plan.question_completeness,
            response_requirement=previous_plan.response_requirement,
            interviewer_need=previous_plan.interviewer_need,
            alignment_brief=merged_alignment_brief,
            context_focus=merged_context_focus,
        )

        return previous_plan.model_copy(
            update={
                "utterance_id": snapshot.utterance_id,
                "revision_id": snapshot.revision_id,
                "snapshot_hash": snapshot.snapshot_hash,
                "generated_at": snapshot.timestamp,
                "context_focus": merged_context_focus,
                "alignment_brief": merged_alignment_brief,
                "supporting_interviewer_context": merged_supporting_context,
                "raw_detected_asks": merged_raw_detected_asks,
                "dropped_noise_clauses": merged_dropped_noise,
                "clause_classifications": list(current_plan.clause_classifications or previous_plan.clause_classifications or [])[:8],
                "contextualized_question": contextualized_question,
                "plan_source": "cached_stable",
                "stability_state": "stable",
                "serve_mode": (
                    "finalize_from_draft"
                    if str(previous_plan.draft_answer or "").strip()
                    else "finalize_from_plan"
                ),
                "confidence": max(float(previous_plan.confidence or 0.0), float(current_plan.confidence or 0.0)),
            }
        )

    def _build_semantic_carry_forward_reason(
        self,
        *,
        current_plan: BrainPlan,
        llm_failure_kind: str,
    ) -> str:
        current_rank = self._question_completeness_rank(current_plan)
        if current_rank < 3:
            reason = "Live brain reused the previous semantic contract because the latest snapshot preserved the same ask but ended weaker or incomplete."
        else:
            reason = "Live brain reused the previous semantic contract because the latest snapshot preserved the same ask and the new fallback did not add new semantics."
        if llm_failure_kind:
            return f"{reason} Fast planner status: {llm_failure_kind.replace('_', '-')}."
        return reason

    async def _plan_with_llm(
        self,
        *,
        snapshot: BrainSnapshot,
        interview_config: dict[str, Any],
        previous_plan: Optional[BrainPlan],
    ) -> tuple[Optional[BrainPlan], str]:
        adapter = self._resolve_adapter(alias=self.config.llm_alias)
        if adapter is None:
            self.last_llm_failure_kind = "adapter_unavailable"
            return None, self.last_llm_failure_kind

        prompt = self._build_prompt(
            snapshot=snapshot,
            interview_config=interview_config,
            previous_plan=previous_plan,
        )
        config = {
            "temperature": self.config.llm_temperature,
            "max_tokens": self.config.llm_max_tokens,
        }
        try:
            raw = await asyncio.wait_for(
                adapter.generate(
                    [
                        {
                            "role": "system",
                            "content": (
                                "You are the autonomous live interview brain. "
                                "Decide only what the interviewer is asking and how the answer should be delivered. "
                                "Ignore filler, preambles, repeated fragments, and unfinished tails. "
                                "Return only valid JSON. "
                                "The first non-whitespace character must be { and the last must be }. "
                                "Do not return markdown. "
                                "Do not invent evidence. "
                                "If the latest ask is incomplete, mark question_completeness as partial or garbled and do not force a direct answer."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    config,
                ),
                timeout=self.config.llm_timeout_sec,
            )
        except Exception as exc:
            failure_kind = type(exc).__name__.lower() or "llm_exception"
            self.last_llm_failure_kind = failure_kind
            return None, failure_kind

        parsed, failure_kind = self._parse_llm_payload(raw)
        if parsed is None:
            self.last_llm_failure_kind = failure_kind
            return None, failure_kind
        self.last_llm_failure_kind = ""
        return self._normalize_llm_plan(
            snapshot=snapshot,
            payload=parsed,
            interview_config=interview_config,
        ), ""

    def _plan_safely(self, *, snapshot: BrainSnapshot, interview_config: Optional[dict[str, Any]] = None) -> BrainPlan:
        candidate, _company, _interviewer = self._normalize_interview_metadata(interview_config)
        (
            raw_detected_asks,
            ordered_asks,
            dropped_noise_clauses,
            question_completeness,
            clause_classifications,
            supporting_interviewer_context,
        ) = self._extract_safe_candidates(snapshot.snapshot_text)
        coverage_points = self._extract_coverage_points(ordered_asks)
        resolved_question = ordered_asks[0] if len(ordered_asks) == 1 else self._build_resolved_question(ordered_asks)
        if not resolved_question:
            resolved_question = self._select_safe_resolved_question(
                raw_detected_asks=raw_detected_asks,
                snapshot_text=snapshot.snapshot_text,
                clause_classifications=clause_classifications,
            )

        preserved_asks = (
            ordered_asks[:5]
            if len(ordered_asks) > 1
            else (ordered_asks[:1] if question_completeness != "complete" else ordered_asks[:5])
        )
        context_focus = self._normalize_unique_strings(supporting_interviewer_context[:4])
        strategy = self._infer_safe_strategy(
            asks=preserved_asks,
            coverage_points=coverage_points,
            resolved_question=resolved_question,
            question_completeness=question_completeness,
            context_focus=context_focus,
            style_hint=self._normalize_text((interview_config or {}).get("style_id") or (interview_config or {}).get("response_style") or "professional"),
        )
        response_shape = strategy["response_shape"]
        include_profile_opening = (
            question_completeness == "complete" and self._looks_like_intro_request(resolved_question)
        )
        supports_context = bool(ordered_asks) and question_completeness in {"complete", "partial"}
        ordered_coverage_required = strategy["ordered_coverage_required"] or bool(
            len(preserved_asks) > 1 or (question_completeness == "complete" and len(coverage_points) > 1)
        )
        target_length = strategy["target_length"]
        ask_intents = self._build_default_ask_intents(
            ordered_asks=preserved_asks,
            question_type=strategy["question_type"],
            answer_contract=strategy["answer_contract"],
            response_shape=response_shape,
            context_focus=context_focus,
            snapshot_text=snapshot.snapshot_text,
        )
        interviewer_need = self._build_default_interviewer_need(
            ordered_asks=preserved_asks,
            question_type=strategy["question_type"],
            coverage_points=coverage_points[:5],
            context_focus=context_focus,
            ask_intents=ask_intents,
            snapshot_text=snapshot.snapshot_text,
        )
        response_requirement = self._build_default_response_requirement(
            ordered_asks=preserved_asks,
            coverage_points=coverage_points[:5],
            question_type=strategy["question_type"],
            answer_contract=strategy["answer_contract"],
            response_shape=response_shape,
            tone=strategy["tone"],
            directness=strategy["directness"],
            target_length=target_length,
            context_focus=context_focus,
            ask_intents=ask_intents,
            interviewer_need=interviewer_need,
            style_hint=self._normalize_text((interview_config or {}).get("style_id") or (interview_config or {}).get("response_style") or "professional"),
            metrics_policy=strategy["metrics_policy"],
            candidate_context_policy=(
                strategy["candidate_context_policy"] if supports_context else "avoid"
            ),
            company_context_policy=(
                strategy["company_context_policy"] if supports_context else "avoid"
            ),
            ordered_coverage_required=ordered_coverage_required,
            candidate=candidate,
            snapshot_text=snapshot.snapshot_text,
        )
        compatibility = self._derive_compatibility_contract(
            ordered_asks=preserved_asks,
            question_type=strategy["question_type"],
            answer_contract=strategy["answer_contract"],
            response_requirement=response_requirement,
            interviewer_need=interviewer_need,
            ask_intents=ask_intents,
        )
        response_family = compatibility["response_family"]
        alignment_brief = compatibility["alignment_brief"]
        quality_guardrails = compatibility["quality_guardrails"]
        answer_blueprint = compatibility["answer_blueprint"]
        delivery_instructions = compatibility["delivery_instructions"]
        literal_question = preserved_asks[0] if len(preserved_asks) == 1 else resolved_question
        contextualized_question = self._derive_contextualized_question(
            literal_question=literal_question,
            resolved_question=resolved_question,
            question_completeness=question_completeness,
            response_requirement=response_requirement,
            interviewer_need=interviewer_need,
            alignment_brief=alignment_brief,
            context_focus=context_focus,
        )
        draft_answer = self._build_safe_fallback_draft(
            snapshot=snapshot,
            interview_config=interview_config or {},
            asks=preserved_asks,
            coverage_points=coverage_points[:5],
            resolved_question=resolved_question,
            question_completeness=question_completeness,
            question_type=strategy["question_type"],
            answer_contract=strategy["answer_contract"],
            candidate_context_policy=(
                strategy["candidate_context_policy"] if supports_context else "avoid"
            ),
            company_context_policy=(
                strategy["company_context_policy"] if supports_context else "avoid"
            ),
            supporting_interviewer_context=supporting_interviewer_context,
            response_family=response_family,
            response_requirement=response_requirement,
            answer_blueprint=answer_blueprint,
            alignment_brief=alignment_brief,
            quality_guardrails=quality_guardrails,
            include_profile_opening=include_profile_opening,
            target_length=target_length,
        )
        serve_mode = "finalize_from_plan"
        confidence = 0.55 if len(preserved_asks) > 1 else (0.45 if preserved_asks else 0.25)
        if draft_answer:
            confidence = max(confidence, 0.62)
        if question_completeness == "garbled":
            confidence = min(confidence, 0.2)

        return BrainPlan(
            session_id=snapshot.session_id,
            utterance_id=snapshot.utterance_id,
            revision_id=snapshot.revision_id,
            snapshot_hash=snapshot.snapshot_hash,
            literal_question=literal_question,
            contextualized_question=contextualized_question,
            ordered_asks=preserved_asks,
            coverage_points=coverage_points[:5],
            raw_detected_asks=raw_detected_asks[:5],
            clause_classifications=clause_classifications[:8],
            supporting_interviewer_context=supporting_interviewer_context[:6],
            ask_intents=ask_intents[:5],
            interviewer_need=interviewer_need,
            response_requirement=response_requirement,
            context_focus=context_focus[:4],
            response_family=response_family,
            answer_blueprint=answer_blueprint,
            alignment_brief=alignment_brief[:3],
            quality_guardrails=quality_guardrails[:6],
            resolved_question=resolved_question,
            question_completeness=question_completeness,
            question_type=strategy["question_type"],
            response_shape=response_shape,
            answer_contract=strategy["answer_contract"],
            delivery_instructions=delivery_instructions[:6],
            tone=strategy["tone"],
            directness=strategy["directness"],
            include_profile_opening=include_profile_opening,
            evidence_depth=strategy["evidence_depth"],
            metrics_policy=strategy["metrics_policy"],
            company_context_policy=(
                strategy["company_context_policy"] if supports_context else "avoid"
            ),
            candidate_context_policy=(
                strategy["candidate_context_policy"] if supports_context else "avoid"
            ),
            ordered_coverage_required=ordered_coverage_required,
            target_length=target_length,
            draft_answer=draft_answer,
            serve_mode=serve_mode,
            confidence=confidence,
            stability_state="draft",
            plan_source="safe_fallback",
            dropped_noise_clauses=dropped_noise_clauses[:6],
        )

    def _build_safe_fallback_draft(
        self,
        *,
        snapshot: BrainSnapshot,
        interview_config: dict[str, Any],
        asks: list[str],
        coverage_points: list[str],
        resolved_question: str,
        question_completeness: str,
        question_type: str,
        answer_contract: str,
        candidate_context_policy: str,
        company_context_policy: str,
        supporting_interviewer_context: Optional[list[str]] = None,
        response_family: str,
        response_requirement: ResponseRequirement,
        answer_blueprint: list[dict[str, Any]],
        alignment_brief: list[str],
        quality_guardrails: list[str],
        include_profile_opening: bool,
        target_length: int,
    ) -> str:
        if (
            question_completeness == "garbled"
            and not asks
            and not coverage_points
            and not self._normalize_text(resolved_question)
        ):
            return "I did not catch the full question clearly enough to give you a reliable answer."
        if question_completeness == "garbled":
            return ""
        if not asks and not coverage_points and not self._normalize_text(resolved_question):
            return ""

        candidate, company, _interviewer = self._normalize_interview_metadata(interview_config)
        if not candidate and not company and question_type != "direct":
            return ""

        direct_contracts = {
            "general_direct",
            "direct_multi_part",
            "direct_explanation",
            "preferences_and_anti_patterns",
        }

        if response_family == "intro_alignment":
            draft = self._build_family_intro_alignment_draft(
                candidate=candidate,
                company=company,
                supporting_interviewer_context=supporting_interviewer_context or [],
                alignment_brief=alignment_brief,
                response_requirement=response_requirement,
                target_length=target_length,
            )
        elif response_family == "culture_preferences":
            draft = self._build_safe_direct_draft(
                asks=asks,
                coverage_points=coverage_points,
                resolved_question=resolved_question,
                answer_contract=answer_contract,
                company=company,
                company_context_policy=company_context_policy,
                target_length=target_length,
            )
        elif response_family == "technical_fit":
            draft = self._build_safe_technical_draft(
                asks=asks,
                coverage_points=coverage_points,
                candidate=candidate,
                company=company,
                supporting_interviewer_context=supporting_interviewer_context or [],
                alignment_brief=alignment_brief,
                target_length=target_length,
            )
        elif response_family in {"behavioral_story", "leadership_scope", "mixed_multi_part"}:
            draft = self._build_blueprint_experience_draft(
                asks=asks,
                coverage_points=coverage_points,
                resolved_question=resolved_question,
                snapshot_text=snapshot.snapshot_text,
                candidate=candidate,
                company=company,
                response_family=response_family,
                response_requirement=response_requirement,
                answer_blueprint=answer_blueprint,
                answer_contract=answer_contract,
                candidate_context_policy=candidate_context_policy,
                company_context_policy=company_context_policy,
                supporting_interviewer_context=supporting_interviewer_context or [],
                alignment_brief=alignment_brief,
                quality_guardrails=quality_guardrails,
                include_profile_opening=include_profile_opening,
                target_length=target_length,
            )
        elif answer_contract == "architecture_walkthrough" or question_type == "technical":
            draft = self._build_safe_technical_draft(
                asks=asks,
                coverage_points=coverage_points,
                candidate=candidate,
                company=company,
                supporting_interviewer_context=supporting_interviewer_context or [],
                alignment_brief=alignment_brief,
                target_length=target_length,
            )
        elif answer_contract in direct_contracts and candidate_context_policy == "avoid":
            draft = self._build_safe_direct_draft(
                asks=asks,
                coverage_points=coverage_points,
                resolved_question=resolved_question,
                answer_contract=answer_contract,
                company=company,
                company_context_policy=company_context_policy,
                target_length=target_length,
            )
        else:
            draft = self._build_safe_experience_draft(
                asks=asks,
                coverage_points=coverage_points,
                resolved_question=resolved_question,
                snapshot_text=snapshot.snapshot_text,
                candidate=candidate,
                company=company,
                response_requirement=response_requirement,
                answer_contract=answer_contract,
                candidate_context_policy=candidate_context_policy,
                company_context_policy=company_context_policy,
                supporting_interviewer_context=supporting_interviewer_context or [],
                include_profile_opening=include_profile_opening,
                target_length=target_length,
            )

        if not draft and candidate_context_policy != "avoid":
            draft = self._build_safe_general_background_draft(
                candidate=candidate,
                company=company,
                supporting_interviewer_context=supporting_interviewer_context or [],
                response_requirement=response_requirement,
                target_length=target_length,
            )

        return self._normalize_text(draft)

    def _build_safe_direct_draft(
        self,
        *,
        asks: list[str],
        coverage_points: list[str],
        resolved_question: str,
        answer_contract: str,
        company: dict[str, Any],
        company_context_policy: str,
        target_length: int,
    ) -> str:
        normalized_points = [
            self._normalize_text(point)
            for point in list(coverage_points or [])
            if self._normalize_text(point)
        ]
        if not normalized_points:
            normalized_points = self._extract_coverage_points(
                list(asks or []) or ([resolved_question] if self._normalize_text(resolved_question) else [])
            )

        focus_phrase = self._spoken_focus_list(normalized_points[:4])
        wants_avoid = answer_contract == "preferences_and_anti_patterns"
        company_values = self._normalize_unique_strings(company.get("values") or [])
        preferred_values = [
            self._lowercase_first(value)
            for value in company_values[:3]
            if self._normalize_text(value)
        ]
        culture_fragment = self._normalize_text(company.get("companyCulture"))
        culture_detail = ""
        if company_context_policy != "avoid":
            if preferred_values:
                culture_detail = self._spoken_focus_list(preferred_values)
            elif culture_fragment:
                culture_detail = self._normalize_text(
                    re.sub(
                        r"^.*?focused on\s+",
                        "",
                        culture_fragment,
                        flags=re.IGNORECASE,
                    )
                )

        sentences: list[str] = []
        if answer_contract == "preferences_and_anti_patterns":
            if focus_phrase and focus_phrase.lower() in {"company", "culture", "teams", "company, culture, and teams"}:
                sentences.append("I'm looking for the right company, culture, and team environment.")
            elif focus_phrase:
                if len(normalized_points) == 1:
                    sentences.append(f"I'm looking for the right fit around {focus_phrase}.")
                else:
                    sentences.append(f"I'm looking for alignment across {focus_phrase}.")
            else:
                sentences.append(
                    "I'm looking for the right environment in terms of company, culture, and team fit."
                )
            if culture_detail:
                sentences.append(f"In practice, that means an environment grounded in {culture_detail}.")
            if wants_avoid:
                sentences.append("I tend to avoid low-trust environments and unclear decision-making.")
            return self._trim_to_word_budget(" ".join(sentence for sentence in sentences if sentence), target_length)

        if focus_phrase:
            if len(normalized_points) == 1:
                sentences.append(f"I'm looking for strong alignment around {focus_phrase}.")
            else:
                sentences.append(f"I'm looking for strong alignment across {focus_phrase}.")
        else:
            sentences.append(
                "I'm looking for an environment with clear expectations and room to do strong work."
            )

        return self._trim_to_word_budget(" ".join(sentence for sentence in sentences if sentence), target_length)

    def _build_family_intro_alignment_draft(
        self,
        *,
        candidate: dict[str, Any],
        company: dict[str, Any],
        supporting_interviewer_context: list[str],
        alignment_brief: list[str],
        response_requirement: ResponseRequirement,
        target_length: int,
    ) -> str:
        role = self._normalize_text(candidate.get("currentRole") or company.get("roleTitle") or company.get("positionTitle"))
        intro = self._build_candidate_intro(candidate=candidate, role=role)
        opening = self._build_condensed_intro(intro=intro, role=role) or intro
        allow_scope_expansion = self._intro_scope_expansion_allowed(response_requirement=response_requirement)
        candidate_fragments = self._candidate_context_fragments(candidate)
        candidate_proof_fragments = self._select_intro_proof_fragments(
            candidate=candidate,
            response_requirement=response_requirement,
            allow_scope_expansion=allow_scope_expansion,
        )
        requirement_proofs = self._extract_requirement_proof_fragments(
            response_requirement=response_requirement,
            limit=2,
        )
        requirement_scopes = self._extract_requirement_scope_fragments(
            response_requirement=response_requirement,
            limit=1,
        )
        alignment_terms = self._derive_supporting_alignment_terms(supporting_interviewer_context)
        requirement_terms = self._derive_supporting_alignment_terms(
            [*list(response_requirement.context_to_weave or []), *list(response_requirement.must_cover or [])]
        )
        scope_terms = alignment_terms | requirement_terms
        aligned_fragment = self._normalize_text(requirement_proofs[0]) if requirement_proofs else ""
        if not aligned_fragment:
            aligned_fragment = self._pick_best_proof_fragment(
                candidate_proof_fragments or candidate_fragments,
                focus_terms=alignment_terms,
                exclude={item.lower() for item in [opening] if item},
            )
        if aligned_fragment and self._normalize_text(aligned_fragment).lower() in self._normalize_text(intro).lower():
            aligned_fragment = self._pick_best_proof_fragment(
                candidate_proof_fragments or candidate_fragments,
                focus_terms=alignment_terms,
                exclude={item.lower() for item in [opening, aligned_fragment] if item},
            )
        scale_fragment = self._normalize_text(requirement_scopes[0]) if requirement_scopes else ""
        if not scale_fragment and allow_scope_expansion:
            scale_fragment = self._pick_best_fragment(
                candidate_fragments,
                focus_terms=scope_terms or alignment_terms,
                exclude={item.lower() for item in [opening, aligned_fragment] if item},
            )
        if (
            scale_fragment
            and allow_scope_expansion
            and not requirement_scopes
            and self._fragment_repeats_intro(fragment=scale_fragment, intro=opening)
        ):
            scale_fragment = self._pick_best_fragment(
                candidate_fragments,
                focus_terms=scope_terms or alignment_terms,
                exclude={item.lower() for item in [opening, aligned_fragment, scale_fragment] if item},
            )

        role_orientation = self._build_current_role_orientation(candidate=candidate, role=role)
        primary_fragment = aligned_fragment or scale_fragment
        sentences: list[str] = []
        if opening:
            sentences.append(opening)
        elif role_orientation:
            sentences.append(role_orientation)
        if primary_fragment and (
            not opening
            or not self._fragment_repeats_intro(fragment=primary_fragment, intro=opening)
        ):
            sentences.append(self._to_spoken_sentence(primary_fragment))
        if (
            allow_scope_expansion
            and
            scale_fragment
            and self._compact_text(scale_fragment, limit=80).lower() != self._compact_text(primary_fragment, limit=80).lower()
            and not self._fragment_repeats_intro(fragment=scale_fragment, intro=self._normalize_text(primary_fragment))
        ):
            sentences.append(self._to_spoken_sentence(scale_fragment, lead="In terms of leadership scope"))

        alignment_sentence = self._build_intro_fit_sentence(
            role=role,
            supporting_interviewer_context=supporting_interviewer_context,
        ) or self._build_alignment_statement(
            supporting_interviewer_context=supporting_interviewer_context,
            alignment_brief=alignment_brief,
            explicit_fit=False,
        )
        if alignment_sentence and not any(
            self._fragment_repeats_intro(fragment=alignment_sentence, intro=sentence)
            for sentence in [primary_fragment, scale_fragment]
            if sentence
        ):
            sentences.append(alignment_sentence)

        return self._trim_to_word_budget(" ".join(sentence for sentence in sentences if sentence), target_length)

    def _build_blueprint_experience_draft(
        self,
        *,
        asks: list[str],
        coverage_points: list[str],
        resolved_question: str,
        snapshot_text: str,
        candidate: dict[str, Any],
        company: dict[str, Any],
        response_family: str,
        response_requirement: ResponseRequirement,
        answer_blueprint: list[dict[str, Any]],
        answer_contract: str,
        candidate_context_policy: str,
        company_context_policy: str,
        supporting_interviewer_context: list[str],
        alignment_brief: list[str],
        quality_guardrails: list[str],
        include_profile_opening: bool,
        target_length: int,
    ) -> str:
        candidate_fragments = self._candidate_context_fragments(candidate)
        company_fragments = self._company_context_fragments(company)
        role = self._normalize_text(candidate.get("currentRole") or company.get("roleTitle") or company.get("positionTitle"))
        intro = self._build_candidate_intro(candidate=candidate, role=role)
        build_examples = self._extract_requirement_proof_fragments(
            response_requirement=response_requirement,
            limit=2,
        ) or self._select_probative_build_examples(
            candidate=candidate,
            asks=asks,
            snapshot_text=snapshot_text,
            limit=2,
        )
        build_primary = self._pick_best_fragment(
            candidate_fragments,
            focus_terms={"build", "building", "built", "scratch", "zero", "ground", "founded", "practice", "subscription", "delivery", "model", "service", "product", "team"},
        )
        build_outcome = self._pick_best_fragment(
            candidate_fragments,
            focus_terms={"outcome", "outcomes", "impact", "reduction", "improved", "scale", "scaled", "efficiency", "assets", "accounts", "applications"},
            exclude={build_primary.lower()} if build_primary else set(),
        )
        team_primary = self._pick_best_fragment(
            candidate_fragments,
            focus_terms={"team", "teams", "managed", "management", "direct", "indirect", "reports", "leaders", "managers", "organization", "regions"},
        )
        team_roles = self._extract_team_roles(candidate_fragments)
        company_focus = self._pick_best_fragment(
            company_fragments,
            focus_terms={"data", "engineering", "architecture", "leadership", "delivery", "platform", "cloud"},
        )
        wants_multiple_build_examples = self._seed_requests_multiple_examples(
            asks=asks,
            resolved_question=resolved_question,
            snapshot_text=snapshot_text,
        ) and self._seed_focuses_on_build_from_zero(
            asks=asks,
            resolved_question=resolved_question,
            snapshot_text=snapshot_text,
        )

        paragraphs: list[str] = []
        for segment in list(answer_blueprint or []):
            purpose = self._normalize_text((segment or {}).get("purpose")).lower()
            if purpose == "build_or_experience" and wants_multiple_build_examples and build_examples:
                paragraphs.extend(self._build_probative_build_paragraphs(build_examples))
                continue
            paragraph = self._realize_blueprint_segment(
                segment=segment,
                intro=intro,
                role=role,
                build_examples=build_examples,
                build_primary=build_primary,
                build_outcome=build_outcome,
                team_primary=team_primary,
                team_roles=team_roles,
                company_focus=company_focus,
                supporting_interviewer_context=supporting_interviewer_context,
                alignment_brief=alignment_brief,
            )
            if paragraph:
                paragraphs.append(paragraph)

        if not paragraphs:
            return self._build_safe_experience_draft(
                asks=asks,
                coverage_points=coverage_points,
                resolved_question=resolved_question,
                snapshot_text=snapshot_text,
                candidate=candidate,
                company=company,
                response_requirement=response_requirement,
                answer_contract=answer_contract,
                candidate_context_policy=candidate_context_policy,
                company_context_policy=company_context_policy,
                supporting_interviewer_context=supporting_interviewer_context,
                include_profile_opening=include_profile_opening,
                target_length=target_length,
            )

        if (
            response_family == "mixed_multi_part"
            and "intro_subordinate_to_specific_asks" in quality_guardrails
            and len(paragraphs) > 1
        ):
            intro_paragraphs = [item for item in paragraphs if item.lower().startswith("at a high level")]
            other_paragraphs = [item for item in paragraphs if item not in intro_paragraphs]
            paragraphs = other_paragraphs + intro_paragraphs

        return self._trim_to_word_budget("\n\n".join(self._dedupe_paragraphs(paragraphs)), target_length)

    def _realize_blueprint_segment(
        self,
        *,
        segment: dict[str, Any],
        intro: str,
        role: str,
        build_examples: list[str],
        build_primary: str,
        build_outcome: str,
        team_primary: str,
        team_roles: str,
        company_focus: str,
        supporting_interviewer_context: list[str],
        alignment_brief: list[str],
    ) -> str:
        purpose = self._normalize_text((segment or {}).get("purpose")).lower()
        if purpose == "profile_core":
            return intro
        if purpose == "alignment":
            return self._build_alignment_statement(
                supporting_interviewer_context=supporting_interviewer_context,
                alignment_brief=alignment_brief,
                explicit_fit=False,
            )
        if purpose == "build_or_experience":
            sentences: list[str] = []
            primary_example = build_examples[0] if build_examples else build_primary
            if primary_example:
                sentences.append(self._to_spoken_sentence(primary_example))
            if build_outcome:
                sentences.append(self._to_spoken_sentence(build_outcome, lead="The result was"))
            return " ".join(sentence for sentence in sentences if sentence)
        if purpose == "leadership_scope":
            sentences = []
            if team_primary:
                sentences.append(self._to_spoken_sentence(team_primary, lead="On team leadership"))
            elif role:
                sentences.append(f"On team leadership, in my current role as {role}, I've led cross-functional teams across delivery and modernization.")
            if build_outcome:
                sentences.append(self._to_spoken_sentence(build_outcome, lead="That helped"))
            return " ".join(sentence for sentence in sentences if sentence)
        if purpose == "team_composition":
            if team_roles:
                return f"Those teams included {team_roles}."
            return ""
        if purpose == "intro_tail":
            return self._build_condensed_intro(intro=intro, role=role)
        if purpose == "technical_positioning":
            if company_focus:
                return self._to_spoken_sentence(company_focus, lead="Technically")
            return self._build_condensed_intro(intro=intro, role=role)
        if purpose == "technical_approach":
            return self._build_alignment_statement(
                supporting_interviewer_context=supporting_interviewer_context,
                alignment_brief=alignment_brief,
                explicit_fit=False,
            )
        if purpose == "preferences_company_culture_team":
            return ""
        if purpose == "preferences_boundaries":
            return ""
        return ""

    def _build_condensed_intro(self, *, intro: str, role: str) -> str:
        normalized_intro = self._normalize_text(intro)
        if normalized_intro:
            sentences = re.split(r"(?<=[.!?])\s+", normalized_intro)
            if sentences and len(sentences[0].split()) <= 18:
                return sentences[0]
        if role:
            return f"At a high level, I'm currently serving as {role}."
        return ""

    def _select_probative_build_examples(
        self,
        *,
        candidate: dict[str, Any],
        asks: list[str],
        snapshot_text: str,
        limit: int,
    ) -> list[str]:
        build_asks = [
            self._normalize_text(ask)
            for ask in list(asks or [])
            if self._normalize_text(ask) and self._seed_focuses_on_build_from_zero(asks=[ask])
        ]
        object_types = self._extract_build_from_zero_object_types(
            asks=build_asks or asks,
            snapshot_text=snapshot_text,
        )
        candidate_fragments = self._candidate_core_proof_fragments(candidate) or self._candidate_proof_fragments(candidate)
        genesis_fragments = [
            fragment
            for fragment in list(candidate_fragments or [])
            if self._looks_like_genesis_anchor(fragment)
        ]
        if genesis_fragments:
            return self._normalize_unique_strings(genesis_fragments)[: max(1, limit)]

        explicit_build_fragments = [
            fragment
            for fragment in list(candidate_fragments or [])
            if self._looks_like_profile_evidence_anchor(fragment)
            and any(
                token in fragment.lower()
                for token in (
                    "build",
                    "built",
                    "building",
                    "founded",
                    "created",
                    "co-created",
                    "launched",
                    "established",
                    "started",
                    "opened",
                    "from zero",
                    "from scratch",
                )
            )
        ]
        if explicit_build_fragments:
            return self._normalize_unique_strings(explicit_build_fragments)[: max(1, limit)]

        seed_text = " ".join([*list(build_asks or asks or []), " ".join(object_types)]).lower()
        focus_terms = {
            token
            for token in re.findall(r"[a-z0-9]+", seed_text)
            if len(token) >= 4 and token not in _COVERAGE_REJECT_TOKENS
        }
        selected_fallback: list[str] = []
        exclude: set[str] = set()
        for _ in range(max(1, limit)):
            fragment = self._pick_best_fragment(
                candidate_fragments,
                focus_terms=focus_terms,
                exclude=exclude,
            )
            if not fragment:
                break
            selected_fallback.append(fragment)
            exclude.add(fragment.lower())

        return self._normalize_unique_strings(selected_fallback)[: max(1, limit)]

    def _build_probative_build_paragraphs(self, build_examples: list[str]) -> list[str]:
        normalized_examples = [self._normalize_text(item) for item in list(build_examples or []) if self._normalize_text(item)]
        if not normalized_examples:
            return []
        paragraphs: list[str] = []
        for index, example in enumerate(normalized_examples[:2]):
            lead = "" if index == 0 else "Second"
            paragraphs.append(self._to_spoken_sentence(example, lead=lead))
        return paragraphs

    def _extract_requirement_proof_fragments(
        self,
        *,
        response_requirement: Optional[ResponseRequirement],
        limit: int,
    ) -> list[str]:
        if response_requirement is None:
            return []

        proof_fragments: list[str] = []
        for raw_item in [
            *list(response_requirement.context_to_weave or []),
            *list(response_requirement.must_cover or []),
        ]:
            item = self._normalize_text(raw_item)
            if not item:
                continue
            lowered = item.lower()
            if lowered.startswith("selected example 1 proof:") or lowered.startswith("selected example 2 proof:"):
                item = self._normalize_text(item.split(":", 1)[1])
            if not item:
                continue
            if self._looks_like_profile_evidence_anchor(item) or self._looks_like_genesis_anchor(item):
                proof_fragments.append(item)

        return self._normalize_unique_strings(proof_fragments)[: max(1, limit)]

    def _extract_requirement_scope_fragments(
        self,
        *,
        response_requirement: Optional[ResponseRequirement],
        limit: int,
    ) -> list[str]:
        if response_requirement is None:
            return []

        ignored_items = {
            "the strongest matching proof from the profile",
            "how your leadership scope lets you guide the teams building it",
            "what you have built, led, or designed that matches the interviewer context",
            "why that background is relevant to the architecture or team leadership problem",
            "current role and relevant scope",
            "team scale and composition",
            "brief positioning close",
            "ai-ready data foundations for llm and agent use cases",
            "cloud and data platform architecture leadership",
            "technical leadership and delivery direction",
            "turning delivery and architecture needs into clear solution direction",
        }
        scope_fragments: list[str] = []
        for raw_item in [
            *list(response_requirement.context_to_weave or []),
            *list(response_requirement.must_cover or []),
        ]:
            item = self._normalize_text(raw_item)
            if not item:
                continue
            lowered = item.lower()
            if lowered in ignored_items or lowered.startswith("selected example "):
                continue
            if self._looks_like_profile_evidence_anchor(item) or self._looks_like_genesis_anchor(item):
                continue
            scope_fragments.append(item)

        return self._normalize_unique_strings(scope_fragments)[: max(1, limit)]

    def _select_profile_alignment_proof_points(
        self,
        *,
        candidate: dict[str, Any],
        context_focus: list[str],
        interviewer_need: InterviewerNeed,
    ) -> tuple[str, str]:
        candidate_fragments = self._candidate_context_fragments(candidate)
        prompt_proof_fragments = self._candidate_prompt_evidence_fragments(candidate, limit=8)
        candidate_proof_fragments = [
            fragment
            for fragment in list(prompt_proof_fragments or [])
            if self._looks_like_profile_evidence_anchor(fragment) or self._looks_like_genesis_anchor(fragment)
        ] or (
            prompt_proof_fragments
            or self._candidate_core_proof_fragments(candidate)
            or self._candidate_proof_fragments(candidate)
        )
        focus_seed = [
            *list(context_focus or []),
            self._normalize_text(interviewer_need.summary),
            *list(interviewer_need.dimensions or []),
        ]
        focus_terms = self._derive_supporting_alignment_terms(focus_seed)
        scope_terms = set(focus_terms) | {
            "lead",
            "leader",
            "leaders",
            "leadership",
            "guide",
            "guiding",
            "team",
            "teams",
            "manager",
            "managers",
            "reports",
            "scope",
            "global",
            "organization",
        }
        primary_proof = self._pick_best_proof_fragment(
            candidate_proof_fragments or candidate_fragments,
            focus_terms=focus_terms,
        )
        current_role = self._normalize_text(
            candidate.get("currentRole") or candidate.get("current_role") or candidate.get("role")
        )
        scope_fragments = [
            fragment
            for fragment in list(candidate_fragments or [])
            if not self._looks_like_profile_evidence_anchor(fragment)
            and not self._looks_like_genesis_anchor(fragment)
        ]
        leadership_scope = self._pick_best_fragment(
            scope_fragments,
            focus_terms=scope_terms,
            exclude={
                item.lower()
                for item in [primary_proof, current_role]
                if item
            },
        )
        if not leadership_scope:
            leadership_scope = self._pick_best_fragment(
                candidate_fragments,
                focus_terms=scope_terms,
                exclude={
                    item.lower()
                    for item in [primary_proof, current_role]
                    if item
                },
            )
        intro = self._build_candidate_intro(
            candidate=candidate,
            role=current_role,
        )
        if leadership_scope and self._fragment_repeats_intro(fragment=leadership_scope, intro=intro):
            leadership_scope = self._pick_best_fragment(
                candidate_fragments,
                focus_terms=scope_terms,
                exclude={
                    item.lower()
                    for item in [primary_proof, leadership_scope, intro, current_role]
                    if item
                },
            )
        if (
            leadership_scope
            and self._looks_like_genesis_anchor(leadership_scope)
            and not self._looks_like_genesis_anchor(primary_proof)
        ):
            primary_proof, leadership_scope = leadership_scope, primary_proof
        if leadership_scope and primary_proof and self._normalize_text(leadership_scope).lower() == self._normalize_text(primary_proof).lower():
            leadership_scope = ""
        return (
            self._normalize_text(primary_proof),
            self._normalize_text(leadership_scope),
        )

    def _build_safe_experience_draft(
        self,
        *,
        asks: list[str],
        coverage_points: list[str],
        resolved_question: str,
        snapshot_text: str,
        candidate: dict[str, Any],
        company: dict[str, Any],
        response_requirement: ResponseRequirement,
        answer_contract: str,
        candidate_context_policy: str,
        company_context_policy: str,
        supporting_interviewer_context: list[str],
        include_profile_opening: bool,
        target_length: int,
    ) -> str:
        answer_mode = self._normalize_text(response_requirement.answer_mode).lower()
        evidence_priority = {
            self._normalize_text(item).lower()
            for item in list(response_requirement.evidence_priority or [])
            if self._normalize_text(item)
        }
        contract_seed = " ".join(
            [
                *list(response_requirement.required_moves or []),
                *list(response_requirement.must_cover or []),
                *list(response_requirement.response_order or []),
                *list(response_requirement.paragraph_plan or []),
            ]
        ).lower()
        wants_intro = answer_mode == "profile_alignment" or include_profile_opening
        wants_build = bool(
            "build_evidence" in evidence_priority
            or any(
                phrase in contract_seed
                for phrase in (
                    "object built",
                    "ownership and outcome",
                    "stage, ownership, and outcome",
                )
            )
        )
        wants_team = bool(
            evidence_priority & {"leadership_evidence", "team_scope_evidence"}
            or any(
                phrase in contract_seed
                for phrase in (
                    "team scale",
                    "team composition",
                    "management scope",
                    "roles and disciplines",
                )
            )
        )

        candidate_fragments = self._candidate_context_fragments(candidate)
        company_fragments = self._company_context_fragments(company)
        role = self._normalize_text(candidate.get("currentRole") or company.get("roleTitle") or company.get("positionTitle"))
        intro = self._build_candidate_intro(candidate=candidate, role=role)
        wants_multiple_build_examples = wants_build and any(
            phrase in contract_seed
            for phrase in (
                "multiple examples clearly separated",
                "multiple examples",
                "examples clearly separated",
            )
        )
        build_examples = self._extract_requirement_proof_fragments(
            response_requirement=response_requirement,
            limit=2 if wants_multiple_build_examples else 1,
        ) or self._select_probative_build_examples(
            candidate=candidate,
            asks=asks,
            snapshot_text=snapshot_text,
            limit=2 if wants_multiple_build_examples else 1,
        )

        if answer_mode == "profile_alignment":
            intro_draft = self._build_safe_intro_draft(
                candidate=candidate,
                company=company,
                supporting_interviewer_context=supporting_interviewer_context,
                response_requirement=response_requirement,
                intro=intro,
                role=role,
                target_length=target_length,
            )
            if intro_draft:
                return intro_draft

        if wants_intro and not wants_build and not wants_team:
            intro_draft = self._build_safe_intro_draft(
                candidate=candidate,
                company=company,
                supporting_interviewer_context=supporting_interviewer_context,
                response_requirement=response_requirement,
                intro=intro,
                role=role,
                target_length=target_length,
            )
            if intro_draft:
                return intro_draft

        build_primary = self._pick_best_fragment(
            candidate_fragments,
            focus_terms={"build", "building", "built", "scratch", "zero", "ground", "founded", "founded", "founded", "practice", "subscription", "delivery", "model", "service", "product", "team"},
        )
        build_support = self._pick_best_fragment(
            candidate_fragments,
            focus_terms={"accounts", "outcomes", "impact", "reduction", "improved", "scale", "scaled", "time", "efficiency", "assets", "practice", "subscription"},
            exclude={build_primary.lower()} if build_primary else set(),
        )
        team_primary = self._pick_best_fragment(
            candidate_fragments,
            focus_terms={"team", "teams", "managed", "management", "direct", "indirect", "reports", "leaders", "managers", "organization"},
        )
        team_roles = self._extract_team_roles(candidate_fragments)
        company_focus = self._pick_best_fragment(
            company_fragments,
            focus_terms={"data", "engineering", "architecture", "leadership", "delivery", "client"},
        )

        paragraphs: list[str] = []
        if wants_build or answer_contract == "business_with_outcomes":
            if wants_multiple_build_examples and build_examples:
                paragraphs.extend(self._build_probative_build_paragraphs(build_examples))
            else:
                sentences: list[str] = []
                primary_example = build_examples[0] if build_examples else build_primary
                if primary_example:
                    sentences.append(self._to_spoken_sentence(primary_example))
                elif intro:
                    sentences.append(intro)
                if build_support:
                    sentences.append(self._to_spoken_sentence(build_support, lead="Another example is"))
                if not sentences and company_focus and company_context_policy != "avoid":
                    sentences.append(self._to_spoken_sentence(company_focus))
                paragraph = " ".join(sentence for sentence in sentences if sentence)
                if paragraph:
                    paragraphs.append(paragraph)

        if wants_team:
            sentences = []
            if team_primary:
                sentences.append(self._to_spoken_sentence(team_primary, lead="On team leadership"))
            elif role:
                sentences.append(
                    f"On team leadership, in my current role as {role}, I've led cross-functional teams across delivery, modernization, and client execution."
                )
            if team_roles:
                sentences.append(f"Those teams included {team_roles}.")
            paragraph = " ".join(sentence for sentence in sentences if sentence)
            if paragraph:
                paragraphs.append(paragraph)

        if wants_intro and not ((wants_build or wants_team) and bool(paragraphs)):
            intro_paragraph = self._build_condensed_intro(intro=intro, role=role) if (wants_build or wants_team) else intro
            if intro_paragraph and intro_paragraph not in paragraphs:
                paragraphs.append(intro_paragraph)

        if not paragraphs and candidate_context_policy != "avoid":
            fallback = self._build_safe_general_background_draft(
                candidate=candidate,
                company=company,
                response_requirement=response_requirement,
                target_length=target_length,
            )
            if fallback:
                paragraphs.append(fallback)

        return self._trim_to_word_budget("\n\n".join(self._dedupe_paragraphs(paragraphs)), target_length)

    def _build_safe_technical_draft(
        self,
        *,
        asks: list[str],
        coverage_points: list[str],
        candidate: dict[str, Any],
        company: dict[str, Any],
        supporting_interviewer_context: list[str],
        alignment_brief: list[str],
        target_length: int,
    ) -> str:
        candidate_fragments = self._candidate_context_fragments(candidate)
        company_fragments = self._company_context_fragments(company)
        role = self._normalize_text(candidate.get("currentRole") or company.get("roleTitle") or company.get("positionTitle"))
        technical_focus = self._pick_best_fragment(
            candidate_fragments,
            focus_terms={"data", "architecture", "engineering", "platform", "modernization", "cloud", "ai", "pipeline", "system", "design"},
        )
        outcome_focus = self._pick_best_fragment(
            candidate_fragments,
            focus_terms={"reduction", "improved", "impact", "accounts", "applications", "efficiency", "time", "value"},
            exclude={technical_focus.lower()} if technical_focus else set(),
        )
        company_focus = self._pick_best_fragment(
            company_fragments,
            focus_terms={"aws", "azure", "gcp", "architecture", "engineering", "delivery", "platform", "pipeline"},
        )

        sentences: list[str] = []
        alignment_sentence = self._build_alignment_statement(
            supporting_interviewer_context=supporting_interviewer_context,
            alignment_brief=alignment_brief,
            explicit_fit=False,
        )
        if alignment_sentence:
            sentences.append("That kind of architecture work sits directly in my background.")
        if role:
            sentences.append(f"Technically, my experience is strongest in roles like {role}, where I've been responsible for data, AI, and modernization work.")
        if technical_focus:
            sentences.append(self._to_spoken_sentence(technical_focus, lead="In practice"))
        if outcome_focus:
            sentences.append(self._to_spoken_sentence(outcome_focus, lead="That work delivered"))
        elif company_focus and not alignment_sentence:
            sentences.append(self._to_spoken_sentence(company_focus, lead="The focus has been"))
        return self._trim_to_word_budget(" ".join(sentence for sentence in sentences if sentence), target_length)

    def _build_safe_general_background_draft(
        self,
        *,
        candidate: dict[str, Any],
        company: dict[str, Any],
        supporting_interviewer_context: Optional[list[str]] = None,
        response_requirement: Optional[ResponseRequirement] = None,
        target_length: int,
    ) -> str:
        role = self._normalize_text(candidate.get("currentRole") or company.get("roleTitle") or company.get("positionTitle"))
        intro = self._build_candidate_intro(candidate=candidate, role=role)
        if not intro:
            return ""
        draft = self._build_safe_intro_draft(
            candidate=candidate,
            company=company,
            supporting_interviewer_context=supporting_interviewer_context or [],
            response_requirement=response_requirement,
            intro=intro,
            role=role,
            target_length=target_length,
        )
        return draft or self._trim_to_word_budget(intro, target_length)

    def _build_safe_intro_draft(
        self,
        *,
        candidate: dict[str, Any],
        company: dict[str, Any],
        supporting_interviewer_context: list[str],
        response_requirement: Optional[ResponseRequirement],
        intro: str,
        role: str,
        target_length: int,
    ) -> str:
        if not intro:
            return ""

        opening = self._build_condensed_intro(intro=intro, role=role) or intro
        allow_scope_expansion = self._intro_scope_expansion_allowed(response_requirement=response_requirement)
        candidate_fragments = self._candidate_context_fragments(candidate)
        candidate_proof_fragments = self._select_intro_proof_fragments(
            candidate=candidate,
            response_requirement=response_requirement,
            allow_scope_expansion=allow_scope_expansion,
        )
        requirement_proofs = self._extract_requirement_proof_fragments(
            response_requirement=response_requirement,
            limit=2,
        )
        requirement_scopes = self._extract_requirement_scope_fragments(
            response_requirement=response_requirement,
            limit=1,
        )
        alignment_terms = self._derive_supporting_alignment_terms(supporting_interviewer_context)
        requirement_terms = self._derive_supporting_alignment_terms(
            [*list(response_requirement.context_to_weave or []), *list(response_requirement.must_cover or [])]
        ) if response_requirement else set()
        scope_terms = alignment_terms | requirement_terms
        aligned_fragment = self._normalize_text(requirement_proofs[0]) if requirement_proofs else ""
        if not aligned_fragment:
            aligned_fragment = self._pick_best_proof_fragment(
                candidate_proof_fragments or candidate_fragments,
                focus_terms=alignment_terms,
                exclude={item.lower() for item in [opening] if item},
            )
        if aligned_fragment and self._normalize_text(aligned_fragment).lower() in self._normalize_text(intro).lower():
            aligned_fragment = self._pick_best_proof_fragment(
                candidate_proof_fragments or candidate_fragments,
                focus_terms=alignment_terms,
                exclude={item.lower() for item in [opening, aligned_fragment] if item},
            )
        scale_fragment = self._normalize_text(requirement_scopes[0]) if requirement_scopes else ""
        if not scale_fragment and allow_scope_expansion:
            scale_fragment = self._pick_best_fragment(
                candidate_fragments,
                focus_terms=scope_terms or alignment_terms,
                exclude={item.lower() for item in [opening, aligned_fragment] if item},
            )
        if (
            scale_fragment
            and allow_scope_expansion
            and not requirement_scopes
            and self._fragment_repeats_intro(fragment=scale_fragment, intro=opening)
        ):
            scale_fragment = self._pick_best_fragment(
                candidate_fragments,
                focus_terms=scope_terms or alignment_terms,
                exclude={item.lower() for item in [opening, aligned_fragment, scale_fragment] if item},
            )

        role_orientation = self._build_current_role_orientation(candidate=candidate, role=role)
        primary_fragment = aligned_fragment or scale_fragment
        sentences: list[str] = []
        if opening:
            sentences.append(opening)
        elif role_orientation:
            sentences.append(role_orientation)
        if primary_fragment and (
            not opening
            or not self._fragment_repeats_intro(fragment=primary_fragment, intro=opening)
        ):
            sentences.append(self._to_spoken_sentence(primary_fragment))
        fit_sentence = self._build_intro_fit_sentence(
            role=role,
            supporting_interviewer_context=supporting_interviewer_context,
        )
        if (
            allow_scope_expansion
            and
            scale_fragment
            and self._compact_text(scale_fragment, limit=80).lower() != self._compact_text(primary_fragment, limit=80).lower()
            and not self._fragment_repeats_intro(fragment=scale_fragment, intro=self._normalize_text(primary_fragment))
        ):
            sentences.append(self._to_spoken_sentence(scale_fragment, lead="In terms of leadership scope"))
        if fit_sentence and not any(
            self._fragment_repeats_intro(fragment=fit_sentence, intro=sentence)
            for sentence in [primary_fragment, scale_fragment]
            if sentence
        ):
            sentences.append(fit_sentence)

        return self._trim_to_word_budget(
            " ".join(sentence for sentence in sentences if sentence),
            target_length,
        )

    def _intro_scope_expansion_allowed(
        self,
        *,
        response_requirement: Optional[ResponseRequirement],
    ) -> bool:
        if response_requirement is None:
            return True
        profile_mode = self._normalize_text(response_requirement.profile_evidence_mode).lower()
        if profile_mode in {"none", "orientation_only", "one_best_proof"}:
            explicit_scope = self._extract_requirement_scope_fragments(
                response_requirement=response_requirement,
                limit=1,
            )
            return bool(explicit_scope)
        evidence_priority = {
            self._normalize_text(item).lower()
            for item in list(response_requirement.evidence_priority or [])
            if self._normalize_text(item)
        }
        return bool(evidence_priority & {"leadership_evidence", "team_scope_evidence"}) or profile_mode in {
            "scope_only",
            "multi_proof",
            "support_if_relevant",
        }

    def _select_intro_proof_fragments(
        self,
        *,
        candidate: dict[str, Any],
        response_requirement: Optional[ResponseRequirement],
        allow_scope_expansion: bool,
    ) -> list[str]:
        prompt_fragments = self._candidate_prompt_evidence_fragments(candidate, limit=8)
        if allow_scope_expansion or response_requirement is None:
            return (
                prompt_fragments
                or self._candidate_core_proof_fragments(candidate)
                or self._candidate_proof_fragments(candidate)
            )

        profile_mode = self._normalize_text(response_requirement.profile_evidence_mode).lower()
        if profile_mode not in {"orientation_only", "one_best_proof"}:
            return (
                prompt_fragments
                or self._candidate_core_proof_fragments(candidate)
                or self._candidate_proof_fragments(candidate)
            )

        focused_fragments = [
            fragment
            for fragment in list(prompt_fragments or [])
            if self._looks_like_profile_evidence_anchor(fragment) or self._looks_like_genesis_anchor(fragment)
        ]
        return (
            focused_fragments
            or prompt_fragments
            or self._candidate_core_proof_fragments(candidate)
            or self._candidate_proof_fragments(candidate)
        )

    def _build_current_role_orientation(self, *, candidate: dict[str, Any], role: str) -> str:
        normalized_role = self._normalize_text(role)
        company = self._normalize_text(
            candidate.get("company") or candidate.get("current_company") or candidate.get("currentCompany")
        )
        if normalized_role and company:
            return self._ensure_terminal_punctuation(f"Currently, I'm {normalized_role} at {company}")
        if normalized_role:
            return self._ensure_terminal_punctuation(f"Currently, I'm {normalized_role}")
        return ""

    def _build_intro_fit_sentence(
        self,
        *,
        role: str,
        supporting_interviewer_context: list[str],
    ) -> str:
        support_seed = " ".join(self._normalize_text(item) for item in list(supporting_interviewer_context or [])).lower()
        if any(term in support_seed for term in ("ai", "llm", "agent", "agents", "vector", "vectors", "graph", "graphs", "knowledge")):
            return "That is what lets me set the architecture direction for AI-ready data platforms and guide the teams building them."
        if any(term in support_seed for term in ("aws", "cloud", "infrastructure", "platform", "architecture", "design")):
            return "That is what lets me set the direction for data platform architecture and cloud design while guiding the teams building it."
        if role:
            return f"That is why roles like {role} are a strong fit for me."
        return ""

    def _fragment_repeats_intro(self, *, fragment: str, intro: str) -> bool:
        normalized_fragment = self._normalize_text(fragment).lower()
        normalized_intro = self._normalize_text(intro).lower()
        if not normalized_fragment or not normalized_intro:
            return False
        return normalized_fragment in normalized_intro or normalized_intro in normalized_fragment

    def _build_alignment_statement(
        self,
        *,
        supporting_interviewer_context: list[str],
        alignment_brief: list[str],
        explicit_fit: bool,
    ) -> str:
        support_seed = " ".join(self._normalize_text(item) for item in list(supporting_interviewer_context or [])).lower()
        if any(term in support_seed for term in ("ai", "llm", "agent", "agents")) and any(term in support_seed for term in ("aws", "cloud", "platform", "architecture", "data")):
            return (
                "A lot of my recent work has been about shaping data platforms and architecture so teams can support AI and LLM use cases reliably."
                if not explicit_fit
                else "That combination is very close to the kind of AI and data platform work I've been leading recently."
            )
        if any(term in support_seed for term in ("aws", "cloud", "platform", "architecture", "design")):
            return (
                "A lot of my recent work has centered on cloud and data platform architecture, especially where teams need clear design direction."
                if not explicit_fit
                else "That is very close to the kind of cloud and platform architecture work I've been leading recently."
            )
        if alignment_brief:
            return (
                f"The common thread in my recent work has been {self._lowercase_first(alignment_brief[0])}."
                if not explicit_fit
                else f"That aligns well with the emphasis on {self._lowercase_first(alignment_brief[0])}."
            )
        return ""

    def _derive_supporting_alignment_terms(self, supporting_interviewer_context: list[str]) -> set[str]:
        lowered_fragments = " ".join(self._normalize_text(fragment).lower() for fragment in list(supporting_interviewer_context or []))
        focus_terms: set[str] = {
            "data",
            "architecture",
            "engineering",
            "platform",
            "delivery",
            "leadership",
            "modernization",
            "transformation",
            "ai",
        }
        for token in re.findall(r"[a-z0-9']+", lowered_fragments):
            if len(token) >= 4 and token not in _COVERAGE_REJECT_TOKENS:
                focus_terms.add(token)
        return focus_terms

    def _candidate_context_fragments(self, candidate: dict[str, Any]) -> list[str]:
        candidate_company = self._normalize_text(
            candidate.get("company") or candidate.get("current_company") or candidate.get("currentCompany")
        )
        raw_values: list[Any] = []
        for raw in (
            candidate.get("currentRole"),
            f"Current company: {candidate_company}" if candidate_company else "",
            candidate.get("summary"),
            *(candidate.get("achievements") or []),
            *(candidate.get("skills") or []),
            candidate.get("cv_text"),
        ):
            if self._normalize_text(raw):
                raw_values.append(raw)
        return self._context_fragments(raw_values)

    def _company_context_fragments(self, company: dict[str, Any]) -> list[str]:
        raw_values: list[Any] = []
        for raw in (
            company.get("roleTitle"),
            company.get("positionTitle"),
            company.get("companySummary"),
            company.get("companyCulture"),
            *(company.get("roleRequirements") or []),
            *(company.get("roleResponsibilities") or []),
            *(company.get("recentFocus") or []),
        ):
            if self._normalize_text(raw):
                raw_values.append(raw)
        return self._context_fragments(raw_values)

    @staticmethod
    def _split_source_text(value: Any) -> list[str]:
        if value is None:
            return []
        text = str(value)
        if not text.strip():
            return []
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        chunks: list[str] = []
        for block in re.split(r"[\n]+|[|•▪]", text):
            if not str(block).strip():
                continue
            chunks.extend(re.split(r"(?<=[.!?])\s+", block))
        return [chunk for chunk in chunks if str(chunk).strip()]

    def _context_fragments(self, values: list[Any]) -> list[str]:
        fragments: list[str] = []
        seen: set[str] = set()
        for value in list(values or []):
            for chunk in self._split_source_text(value):
                normalized = self._normalize_text(chunk)
                if not normalized:
                    continue
                word_count = len(normalized.split())
                if word_count < 3:
                    continue
                if word_count > 32:
                    normalized = " ".join(normalized.split()[:32]).rstrip(",;:")
                lowered = normalized.lower()
                if lowered in seen:
                    continue
                seen.add(lowered)
                fragments.append(normalized)
        return fragments

    def _candidate_proof_fragments(self, candidate: dict[str, Any]) -> list[str]:
        raw_values: list[Any] = []
        for raw in (
            *(candidate.get("achievements") or []),
            candidate.get("cv_text"),
            candidate.get("summary"),
        ):
            if self._normalize_text(raw):
                raw_values.append(raw)
        fragments = self._context_fragments(raw_values)
        if fragments:
            return fragments
        fallback_values: list[Any] = []
        for raw in (
            candidate.get("currentRole"),
            *(candidate.get("skills") or []),
        ):
            if self._normalize_text(raw):
                fallback_values.append(raw)
        return self._context_fragments(fallback_values)

    def _candidate_core_proof_fragments(self, candidate: dict[str, Any]) -> list[str]:
        raw_values: list[Any] = []
        for raw in (
            *(candidate.get("achievements") or []),
            candidate.get("cv_text"),
        ):
            if self._normalize_text(raw):
                raw_values.append(raw)
        return self._context_fragments(raw_values)

    def _candidate_prompt_evidence_fragments(self, candidate: dict[str, Any], *, limit: int) -> list[str]:
        core_fragments = self._candidate_core_proof_fragments(candidate)
        proof_fragments = self._candidate_proof_fragments(candidate)
        genesis_fragments = [
            fragment
            for fragment in list(core_fragments or [])
            if self._looks_like_genesis_anchor(fragment)
        ]
        explicit_fragments = [
            fragment
            for fragment in list(core_fragments or proof_fragments or [])
            if self._looks_like_profile_evidence_anchor(fragment)
        ]
        ordered_fragments = self._normalize_unique_strings(
            [*genesis_fragments, *explicit_fragments, *(core_fragments or proof_fragments or [])]
        )
        return ordered_fragments[: max(1, int(limit or 1))]

    def _build_candidate_evidence_snapshot_for_prompt(
        self,
        *,
        candidate: dict[str, Any],
        snapshot_text: str,
    ) -> str:
        if not candidate:
            return "None"
        summary = self._normalize_text(candidate.get("summary"))
        summary_sentence = self._compact_text(re.split(r"(?<=[.!?])\s+", summary)[0], limit=88) if summary else ""
        lines: list[str] = []
        current_role = self._compact_text(candidate.get("currentRole") or candidate.get("current_role"), limit=64)
        if current_role:
            lines.append(f"- current role: {current_role}")
        if summary_sentence:
            lines.append(f"- profile summary: {summary_sentence}")
        for fragment in self._candidate_prompt_evidence_fragments(candidate, limit=3):
            lines.append(f"- profile evidence: {self._compact_text(fragment, limit=96)}")
        return "\n".join(lines[:5]) or "None"

    def _pick_best_fragment(
        self,
        fragments: list[str],
        *,
        focus_terms: set[str],
        exclude: Optional[set[str]] = None,
    ) -> str:
        best_fragment = ""
        best_score = 0.0
        blocked = {item for item in list(exclude or set()) if item}
        for index, fragment in enumerate(list(fragments or [])):
            lowered_fragment = fragment.lower()
            if lowered_fragment in blocked:
                continue
            fragment_terms = {
                token
                for token in re.findall(r"[a-z0-9']+", lowered_fragment)
                if len(token) > 2 or token in focus_terms
            }
            overlap = len(fragment_terms & focus_terms)
            if overlap <= 0:
                continue
            score = overlap + min(len(fragment.split()) / 30.0, 0.35) - (index * 0.001)
            if score > best_score:
                best_score = score
                best_fragment = fragment
        return best_fragment

    def _pick_best_proof_fragment(
        self,
        fragments: list[str],
        *,
        focus_terms: set[str],
        exclude: Optional[set[str]] = None,
    ) -> str:
        best_fragment = ""
        best_score = 0.0
        blocked = {item for item in list(exclude or set()) if item}
        for index, fragment in enumerate(list(fragments or [])):
            lowered_fragment = fragment.lower()
            if lowered_fragment in blocked:
                continue
            fragment_terms = {
                token
                for token in re.findall(r"[a-z0-9']+", lowered_fragment)
                if len(token) > 2 or token in focus_terms
            }
            overlap = len(fragment_terms & focus_terms)
            if overlap <= 0 and not self._looks_like_profile_evidence_anchor(fragment):
                continue
            score = overlap + min(len(fragment.split()) / 30.0, 0.35) - (index * 0.08)
            if self._looks_like_genesis_anchor(fragment):
                score += 1.5
            elif self._looks_like_profile_evidence_anchor(fragment):
                score += 0.3
            if score > best_score:
                best_score = score
                best_fragment = fragment
        return best_fragment

    def _build_candidate_intro(self, *, candidate: dict[str, Any], role: str) -> str:
        summary = self._normalize_text(candidate.get("summary"))
        if summary:
            sentence = re.split(r"(?<=[.!?])\s+", summary)[0].strip()
            lowered = sentence.lower()
            if lowered.startswith(("i ", "i'm ", "i’ve ", "i've ")):
                return self._ensure_terminal_punctuation(f"At a high level, {lowered}")
            return self._ensure_terminal_punctuation(f"At a high level, I'm a {lowered}")
        if role:
            return self._ensure_terminal_punctuation(f"At a high level, I'm currently serving as {role}")
        return ""

    def _extract_team_roles(self, fragments: list[str]) -> str:
        role_labels = [
            "solution architects",
            "data architects",
            "architects",
            "data engineers",
            "cloud engineers",
            "engineers",
            "product managers",
            "delivery leads",
            "delivery managers",
            "consultants",
            "client-facing consultants",
            "engineering leads",
            "managers",
        ]
        found: list[str] = []
        lowered_fragments = " ".join(fragment.lower() for fragment in list(fragments or []))
        for label in role_labels:
            singular = label[:-1] if label.endswith("s") else label
            if label in lowered_fragments or singular in lowered_fragments:
                found.append(label)
        unique: list[str] = []
        for label in found:
            if label not in unique:
                unique.append(label)
        if "solution architects" in unique:
            unique = [label for label in unique if label != "architects"]
        elif "data architects" in unique:
            unique = [label for label in unique if label != "architects"]
        if "data engineers" in unique or "cloud engineers" in unique:
            unique = [label for label in unique if label != "engineers"]
        if "client-facing consultants" in unique:
            unique = [label for label in unique if label != "consultants"]
        if not unique:
            return "architects, engineers, and delivery leads"
        if len(unique) == 1:
            return unique[0]
        if len(unique) == 2:
            return f"{unique[0]} and {unique[1]}"
        return ", ".join(unique[:-1]) + f", and {unique[-1]}"

    def _to_spoken_sentence(self, fragment: str, *, lead: str = "") -> str:
        normalized = self._normalize_text(fragment).strip(" ,;:")
        if not normalized:
            return ""
        lowered = normalized.lower()
        common_verbs = (
            "founded",
            "built",
            "led",
            "scaled",
            "managed",
            "drove",
            "delivered",
            "improved",
            "opened",
            "designed",
            "created",
            "owned",
            "expanded",
            "co-led",
            "consolidated",
            "translated",
            "standardized",
            "achieved",
        )
        if lowered.startswith(("i ", "i'm ", "i’ve ", "i've ", "my ")):
            body = normalized if not lead else self._lowercase_first(normalized)
        elif lowered.startswith(common_verbs):
            body = f"I {lowered}"
        else:
            body = normalized if not lead else self._lowercase_first(normalized)
        sentence = f"{lead}, {body}" if lead else body
        return self._ensure_terminal_punctuation(sentence)

    @staticmethod
    def _ensure_terminal_punctuation(text: str) -> str:
        normalized = LiveBrainService._normalize_text(text)
        if not normalized:
            return ""
        if normalized.endswith((".", "!", "?")):
            return normalized
        return f"{normalized}."

    @staticmethod
    def _lowercase_first(text: str) -> str:
        normalized = LiveBrainService._normalize_text(text)
        if not normalized:
            return ""
        return normalized[0].lower() + normalized[1:]

    @staticmethod
    def _dedupe_paragraphs(paragraphs: list[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for paragraph in list(paragraphs or []):
            normalized = LiveBrainService._normalize_text(paragraph)
            if not normalized:
                continue
            lowered = normalized.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            deduped.append(paragraph.strip())
        return deduped

    @staticmethod
    def _spoken_focus_list(points: list[str]) -> str:
        normalized = [
            LiveBrainService._normalize_text(point)
            for point in list(points or [])
            if LiveBrainService._normalize_text(point)
        ]
        if not normalized:
            return ""
        if len(normalized) == 1:
            return normalized[0]
        if len(normalized) == 2:
            return f"{normalized[0]} and {normalized[1]}"
        return ", ".join(normalized[:-1]) + f", and {normalized[-1]}"

    @staticmethod
    def _direct_asks_include_avoid(*, asks: list[str], resolved_question: str) -> bool:
        seed = " ".join([resolved_question or "", *list(asks or [])]).lower()
        return any(
            phrase in seed
            for phrase in (
                "avoid",
                "don't like",
                "do not like",
                "not a fit",
                "absolutely don't like",
            )
        )

    @staticmethod
    def _trim_to_word_budget(text: str, budget: int) -> str:
        normalized = text.strip()
        if not normalized or budget <= 0:
            return normalized
        words = normalized.split()
        if len(words) <= budget:
            return normalized
        trimmed = " ".join(words[:budget]).rstrip(",;:")
        if not trimmed.endswith((".", "!", "?")):
            trimmed += "."
        return trimmed

    @staticmethod
    def _normalize_evidence_types(values: list[Any]) -> list[str]:
        allowed = {
            "candidate_snippets",
            "company_snippets",
            "interviewer_snippets",
            "role_evidence",
            "build_evidence",
            "leadership_evidence",
            "team_scope_evidence",
            "culture_alignment_evidence",
            "technical_alignment_evidence",
            "supporting_metrics",
        }
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in list(values or []):
            value = LiveBrainService._normalize_text(raw).lower().replace(" ", "_")
            if value not in allowed or value in seen:
                continue
            seen.add(value)
            normalized.append(value)
        return normalized

    @staticmethod
    def _normalize_profile_evidence_mode(value: Any, default: str = "support_if_relevant") -> str:
        return LiveBrainService._normalize_choice(
            value,
            {"none", "orientation_only", "scope_only", "one_best_proof", "multi_proof", "support_if_relevant"},
            default,
        )

    @staticmethod
    def _normalize_company_evidence_mode(value: Any, default: str = "support_if_relevant") -> str:
        return LiveBrainService._normalize_choice(
            value,
            {"none", "preference_alignment", "problem_mapping", "support_if_relevant"},
            default,
        )

    @staticmethod
    def _normalize_prior_context_mode(value: Any, default: str = "support_if_relevant") -> str:
        return LiveBrainService._normalize_choice(
            value,
            {"none", "disambiguate", "evaluation_scope", "support_if_relevant"},
            default,
        )

    @staticmethod
    def _profile_evidence_rank(mode: str) -> int:
        return {
            "none": 0,
            "orientation_only": 1,
            "scope_only": 2,
            "support_if_relevant": 3,
            "one_best_proof": 4,
            "multi_proof": 5,
        }.get(LiveBrainService._normalize_text(mode).lower(), 3)

    @staticmethod
    def _company_evidence_rank(mode: str) -> int:
        return {
            "none": 0,
            "support_if_relevant": 1,
            "preference_alignment": 2,
            "problem_mapping": 3,
        }.get(LiveBrainService._normalize_text(mode).lower(), 1)

    @staticmethod
    def _prior_context_rank(mode: str) -> int:
        return {
            "none": 0,
            "support_if_relevant": 1,
            "disambiguate": 2,
            "evaluation_scope": 3,
        }.get(LiveBrainService._normalize_text(mode).lower(), 1)

    def _merge_profile_evidence_mode(self, values: list[str], default: str = "support_if_relevant") -> str:
        normalized = [
            self._normalize_profile_evidence_mode(value, default)
            for value in list(values or [])
            if self._normalize_text(value)
        ]
        if not normalized:
            return default
        return max(normalized, key=self._profile_evidence_rank)

    def _merge_company_evidence_mode(self, values: list[str], default: str = "support_if_relevant") -> str:
        normalized = [
            self._normalize_company_evidence_mode(value, default)
            for value in list(values or [])
            if self._normalize_text(value)
        ]
        if not normalized:
            return default
        return max(normalized, key=self._company_evidence_rank)

    def _merge_prior_context_mode(self, values: list[str], default: str = "support_if_relevant") -> str:
        normalized = [
            self._normalize_prior_context_mode(value, default)
            for value in list(values or [])
            if self._normalize_text(value)
        ]
        if not normalized:
            return default
        return max(normalized, key=self._prior_context_rank)

    @staticmethod
    def _seed_requests_multiple_examples(
        *,
        asks: list[str],
        resolved_question: str = "",
        snapshot_text: str = "",
    ) -> bool:
        seed = " ".join([snapshot_text or "", resolved_question or "", *list(asks or [])]).lower()
        if not seed.strip():
            return False
        return bool(re.search(r"\bexamples\b", seed)) or any(
            phrase in seed
            for phrase in (
                "companies or experiences",
                "whether it was",
                "multiple examples",
                "several examples",
                "two examples",
                "2 examples",
            )
        )

    @staticmethod
    def _seed_focuses_on_build_from_zero(
        *,
        asks: list[str],
        resolved_question: str = "",
        snapshot_text: str = "",
    ) -> bool:
        seed = " ".join([snapshot_text or "", resolved_question or "", *list(asks or [])]).lower()
        return any(
            phrase in seed
            for phrase in (
                "build from 0",
                "build from zero",
                "building from 0",
                "building from zero",
                "build from scratch",
                "building from scratch",
                "from scratch",
                "from the ground up",
                "early stages",
            )
        )

    @staticmethod
    def _extract_build_from_zero_object_types(
        *,
        asks: list[str],
        resolved_question: str = "",
        snapshot_text: str = "",
    ) -> list[str]:
        seed = LiveBrainService._normalize_text(
            " ".join([snapshot_text or "", resolved_question or "", *list(asks or [])]).lower()
        )
        if not seed:
            return []
        candidates: list[str] = []
        for pattern in (
            r"(?:building|build|built)\s+(?:a|an|the)?\s*([a-z][a-z\s-]{0,30}?)\s+from (?:0|zero)",
            r"(?:^|,|\bor\b|\band\b)\s*(?:a|an|the)?\s*([a-z][a-z\s-]{0,30}?)\s+from (?:0|zero)",
            r"(?:building|build|built)\s+(?:a|an|the)?\s*([a-z][a-z\s-]{0,30}?)\s+from scratch",
        ):
            candidates.extend(match.group(1) for match in re.finditer(pattern, seed))

        rejected_tokens = {
            "company",
            "companies",
            "context",
            "contexts",
            "example",
            "examples",
            "experience",
            "experiences",
            "stage",
            "stages",
            "thing",
            "things",
            "zero",
        }
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in candidates:
            cleaned = LiveBrainService._normalize_text(
                re.sub(r"^(?:whether it was|it was|your|our|their)\s+", "", raw, flags=re.IGNORECASE)
            ).strip(" ,.;:-")
            cleaned = LiveBrainService._normalize_text(
                re.sub(r"^(?:(?:or|and)\s+)*(?:a|an|the)\s+", "", cleaned, flags=re.IGNORECASE)
            ).strip(" ,.;:-")
            cleaned = LiveBrainService._normalize_text(
                re.sub(r"^(?:or|and)\s+", "", cleaned, flags=re.IGNORECASE)
            ).strip(" ,.;:-")
            tokens = [token for token in re.findall(r"[a-z0-9]+", cleaned.lower()) if token not in rejected_tokens]
            if not tokens or len(tokens) > 3:
                continue
            phrase = " ".join(tokens)
            if phrase in seen:
                continue
            seen.add(phrase)
            normalized.append(phrase)
        return normalized[:4]

    def _build_from_zero_object_focus_phrase(
        self,
        *,
        asks: list[str],
        resolved_question: str = "",
        snapshot_text: str = "",
    ) -> str:
        object_types = self._extract_build_from_zero_object_types(
            asks=asks,
            resolved_question=resolved_question,
            snapshot_text=snapshot_text,
        )
        return self._join_natural_phrases(object_types[:3])

    def _derive_interviewer_evaluation_dimensions(
        self,
        *,
        context_focus: list[str],
        coverage_points: list[str],
        asks: list[str],
        snapshot_text: str = "",
        ask_intents: Optional[list[AskIntent]] = None,
    ) -> list[str]:
        dimensions = list(
            self._derive_context_dimensions(
                context_focus=context_focus,
                coverage_points=coverage_points,
            )
        )
        focuses_on_build_from_zero = self._seed_focuses_on_build_from_zero(
            asks=asks,
            snapshot_text=snapshot_text,
        )
        asks_team_scope = any(
            self._normalize_text(intent.ask_intent).lower() in {"leadership_scope", "team_composition"}
            for intent in list(ask_intents or [])
        )
        object_focus_phrase = self._build_from_zero_object_focus_phrase(
            asks=asks,
            snapshot_text=snapshot_text,
        )

        inferred_dimensions: list[str] = []
        if focuses_on_build_from_zero:
            inferred_dimensions.append("0-to-1 / early-stage building")
            if object_focus_phrase:
                inferred_dimensions.append(f"kind of thing built from zero: {object_focus_phrase}")
            inferred_dimensions.append("ownership and decision scope in the build")
        if asks_team_scope:
            inferred_dimensions.append("team leadership scale and composition")

        return self._normalize_unique_strings([*inferred_dimensions, *dimensions])[:4]

    def _build_zero_response_goal(
        self,
        *,
        wants_multiple_examples: bool,
        object_focus_phrase: str,
    ) -> str:
        subject = "the two profile examples" if wants_multiple_examples else "the profile example"
        goal = f"Choose {subject} with the strongest probative value for the build-from-zero experience the interviewer is testing"
        if object_focus_phrase:
            goal += f", especially around {object_focus_phrase}"
        goal += ", using direct proof of what was created or built rather than downstream adoption alone, and make the object built, the stage, your ownership, and the outcome explicit"
        if wants_multiple_examples:
            goal += " in each one."
        else:
            goal += "."
        return goal

    def _default_ask_intent(
        self,
        *,
        ask: str,
        question_type: str,
        answer_contract: str,
        wants_multiple_examples: bool = False,
        build_from_zero_object_focus: str = "",
    ) -> tuple[str, str, str, str, list[str], str, str, str, str]:
        lowered = self._normalize_text(ask).lower()
        if self._looks_like_intro_request(ask):
            return (
                "profile_positioning",
                "professional introduction",
                "whether the candidate's background should be trusted to lead the problem just described",
                "Show why the background most directly proves the candidate can lead the interviewer problem, using the strongest matching proof rather than a generic biography.",
                ["build_evidence", "technical_alignment_evidence", "role_evidence"],
                "direct_structured",
                "one_best_proof",
                "none",
                "evaluation_scope",
            )
        if self._seed_focuses_on_build_from_zero(asks=[ask]):
            if wants_multiple_examples:
                return (
                    "build_from_zero_examples",
                    "experience proof",
                    (
                        f"whether the candidate has personally built {build_from_zero_object_focus} from zero"
                        if build_from_zero_object_focus
                        else "whether the candidate has personally built the requested kind of thing from zero"
                    ),
                    self._build_zero_response_goal(
                        wants_multiple_examples=True,
                        object_focus_phrase=build_from_zero_object_focus,
                    ),
                    ["build_evidence", "leadership_evidence", "role_evidence", "supporting_metrics"],
                    "direct_structured",
                    "multi_proof",
                    "none",
                    "none",
                )
            return (
                "build_from_zero_experience",
                "experience proof",
                (
                    f"whether the candidate has personally built {build_from_zero_object_focus} from zero"
                    if build_from_zero_object_focus
                    else "whether the candidate has personally built the requested kind of thing from zero"
                ),
                self._build_zero_response_goal(
                    wants_multiple_examples=False,
                    object_focus_phrase=build_from_zero_object_focus,
                ),
                ["build_evidence", "leadership_evidence", "role_evidence", "supporting_metrics"],
                "direct_structured",
                "one_best_proof",
                "none",
                "none",
            )
        if answer_contract == "preferences_and_anti_patterns":
            return (
                "preferences_fit",
                "preference statement",
                "what environment, culture, and team conditions the candidate prefers",
                "State the preference clearly and only add boundaries or anti-patterns when asked.",
                ["culture_alignment_evidence", "company_snippets"],
                "direct_structured",
                "none",
                "preference_alignment",
                "none",
            )
        if any(term in lowered for term in ("roles did they have", "role did they have", "team composition")):
            return (
                "team_composition",
                "team composition description",
                "whether the candidate has led the right mix of roles and disciplines",
                "Describe who was on the team and how the team was composed.",
                ["team_scope_evidence", "leadership_evidence"],
                "direct_short",
                "scope_only",
                "none",
                "none",
            )
        if any(term in lowered for term in ("team", "managed", "management", "reports", "scope")):
            return (
                "leadership_scope",
                "leadership scope description",
                "whether the candidate has led teams of the right size and management scope",
                "Show the scale of the team, the management scope, and how leadership was exercised.",
                ["leadership_evidence", "team_scope_evidence"],
                "direct_structured",
                "scope_only",
                "none",
                "none",
            )
        if answer_contract == "architecture_walkthrough" or question_type == "technical":
            return (
                "technical_judgment",
                "technical explanation",
                "whether the candidate can set technical direction and make sound architecture decisions",
                "Answer directly, explain the approach, and show the trade-offs or design reasoning.",
                ["technical_alignment_evidence", "role_evidence"],
                "technical_explainer",
                "one_best_proof",
                "problem_mapping",
                "evaluation_scope",
            )
        if answer_contract == "business_with_outcomes" or question_type in {"behavioral", "business"}:
            return (
                "experience_with_outcomes",
                "experience summary",
                "whether the candidate has relevant experience and can show concrete outcomes",
                "Use a relevant example that shows role, what was done, scale, and outcome.",
                ["build_evidence", "leadership_evidence", "supporting_metrics"],
                "strategic_explainer",
                "one_best_proof",
                "none",
                "support_if_relevant",
            )
        return (
            "direct_response",
            "direct answer",
            "whether the candidate can answer the ask clearly and directly",
            "Answer the ask directly and keep the structure easy to follow.",
            ["candidate_snippets"],
            "direct_short" if question_type == "direct" else "direct_structured",
            "support_if_relevant",
            "none",
            "support_if_relevant",
        )

    def _build_default_ask_intents(
        self,
        *,
        ordered_asks: list[str],
        question_type: str,
        answer_contract: str,
        response_shape: str,
        context_focus: list[str],
        snapshot_text: str = "",
    ) -> list[AskIntent]:
        ask_intents: list[AskIntent] = []
        wants_multiple_examples = self._seed_requests_multiple_examples(
            asks=ordered_asks,
            snapshot_text=snapshot_text,
        )
        build_from_zero_object_focus = self._build_from_zero_object_focus_phrase(
            asks=ordered_asks,
            snapshot_text=snapshot_text,
        )
        for ask in list(ordered_asks or []):
            (
                intent_name,
                speech_act,
                decision_target,
                response_goal,
                evidence_types,
                expected_shape,
                profile_evidence_mode,
                company_evidence_mode,
                prior_context_mode,
            ) = self._default_ask_intent(
                ask=ask,
                question_type=question_type,
                answer_contract=answer_contract,
                wants_multiple_examples=wants_multiple_examples,
                build_from_zero_object_focus=build_from_zero_object_focus,
            )
            ask_intents.append(
                AskIntent(
                    ask_text=ask,
                    ask_intent=intent_name,
                    speech_act=speech_act,
                    decision_target=decision_target,
                    response_goal=response_goal,
                    required_evidence_types=evidence_types,
                    expected_answer_shape=expected_shape or response_shape,
                    needs_context_from_prior_turns=bool(context_focus),
                    profile_evidence_mode=profile_evidence_mode,
                    company_evidence_mode=company_evidence_mode,
                    prior_context_mode=prior_context_mode if context_focus else "none",
                )
            )
        return ask_intents

    def _build_default_interviewer_need(
        self,
        *,
        ordered_asks: list[str],
        question_type: str,
        coverage_points: list[str],
        context_focus: list[str],
        ask_intents: list[AskIntent],
        snapshot_text: str = "",
    ) -> InterviewerNeed:
        if not ordered_asks:
            return InterviewerNeed(
                summary="No reliable actionable interviewer question is available yet, so the answer should not guess or respond to meta prompts.",
                dimensions=[],
                evidence_expected=[],
            )
        decision_targets = self._normalize_unique_strings(
            [
                self._normalize_text(intent.decision_target)
                for intent in list(ask_intents or [])
                if self._normalize_text(intent.decision_target)
            ]
        )
        if decision_targets:
            summary = self._join_natural_phrases(decision_targets[:3])
        elif question_type == "technical":
            summary = "whether the candidate can set technical direction and make sound architecture decisions"
        elif question_type == "business":
            summary = "whether the candidate has relevant business-facing leadership experience and outcome credibility"
        elif question_type == "behavioral":
            summary = "whether the candidate has relevant experience, ownership, and concrete outcomes"
        elif question_type == "mixed":
            summary = "whether the candidate can address the full set of asks clearly and in order"
        else:
            summary = "whether the candidate can answer the ask directly and stay aligned to the real interviewer need"
        if summary and not summary.lower().startswith("whether "):
            summary = f"whether {summary[0].lower()}{summary[1:]}" if len(summary) > 1 else f"whether {summary.lower()}"
        dimension_seed = self._derive_interviewer_evaluation_dimensions(
            context_focus=context_focus,
            coverage_points=coverage_points,
            asks=ordered_asks,
            snapshot_text=snapshot_text,
            ask_intents=ask_intents,
        )
        if not dimension_seed:
            dimension_seed = self._normalize_unique_strings([intent.ask_text for intent in ask_intents[:2]])
        dimensions = dimension_seed[:4]
        evidence_expected = self._normalize_evidence_types(
            [evidence for intent in ask_intents for evidence in list(intent.required_evidence_types or [])]
        )[:4]
        return InterviewerNeed(
            summary=summary,
            dimensions=dimensions,
            evidence_expected=evidence_expected,
        )

    def _build_default_response_requirement(
        self,
        *,
        ordered_asks: list[str],
        coverage_points: list[str],
        question_type: str,
        answer_contract: str,
        response_shape: str,
        tone: str,
        directness: str,
        target_length: int,
        context_focus: list[str],
        ask_intents: list[AskIntent],
        interviewer_need: InterviewerNeed,
        style_hint: str,
        metrics_policy: str,
        candidate_context_policy: str,
        company_context_policy: str,
        ordered_coverage_required: bool,
        candidate: dict[str, Any],
        snapshot_text: str = "",
    ) -> ResponseRequirement:
        if not ordered_asks and not coverage_points:
            return ResponseRequirement(
                answer_mode="structured_direct",
                response_order=[],
                required_moves=[
                    "Do not answer a self-answered meta prompt or an incomplete tail.",
                    "Wait for a clearer actionable interviewer question before giving a substantive answer.",
                ],
                context_to_weave=[],
                evidence_priority=[],
                must_cover=["that the actionable question was not captured clearly enough"],
                avoid=["guessed_answer", "meta_prompt_response"],
                paragraph_plan=["One short sentence: say the full question was not caught clearly enough."],
                style_constraints=["Keep it brief and natural.", "Do not invent or infer a missing question."],
            )
        if len(ordered_asks) == 1 and ordered_asks and self._looks_like_intro_request(ordered_asks[0]) and context_focus:
            answer_mode = "profile_alignment"
        elif answer_contract == "architecture_walkthrough" or question_type == "technical":
            answer_mode = "technical_walkthrough"
        elif answer_contract == "preferences_and_anti_patterns":
            answer_mode = "preferences"
        elif answer_contract == "business_with_outcomes" or question_type in {"behavioral", "business"}:
            answer_mode = "experience_with_outcomes"
        else:
            answer_mode = "structured_direct"

        evidence_priority = self._normalize_evidence_types(
            interviewer_need.evidence_expected
            or [evidence for intent in ask_intents for evidence in list(intent.required_evidence_types or [])]
        )
        if not evidence_priority:
            evidence_priority = ["candidate_snippets"]
        profile_evidence_mode = self._merge_profile_evidence_mode(
            [intent.profile_evidence_mode for intent in list(ask_intents or [])],
            "support_if_relevant",
        )
        company_evidence_mode = self._merge_company_evidence_mode(
            [intent.company_evidence_mode for intent in list(ask_intents or [])],
            "support_if_relevant",
        )
        prior_context_mode = self._merge_prior_context_mode(
            [intent.prior_context_mode for intent in list(ask_intents or [])],
            "support_if_relevant",
        )
        if candidate_context_policy == "avoid" and profile_evidence_mode == "support_if_relevant":
            profile_evidence_mode = "none"
        if company_context_policy == "avoid" and company_evidence_mode == "support_if_relevant":
            company_evidence_mode = "none"
        if not context_focus:
            prior_context_mode = "none"
        wants_multiple_examples = self._seed_requests_multiple_examples(
            asks=ordered_asks,
            snapshot_text=snapshot_text,
        )
        focuses_on_build_from_zero = self._seed_focuses_on_build_from_zero(
            asks=ordered_asks,
            snapshot_text=snapshot_text,
        )
        asks_team_scope = any(
            self._normalize_text(intent.ask_intent).lower() in {"leadership_scope", "team_composition"}
            for intent in list(ask_intents or [])
        )
        asks_intro = any(self._looks_like_intro_request(intent.ask_text) for intent in list(ask_intents or []))
        object_focus_phrase = self._build_from_zero_object_focus_phrase(
            asks=ordered_asks,
            snapshot_text=snapshot_text,
        )
        profile_alignment_proof = ""
        profile_alignment_scope = ""
        if answer_mode == "profile_alignment":
            profile_alignment_proof, profile_alignment_scope = self._select_profile_alignment_proof_points(
                candidate=candidate,
                context_focus=context_focus,
                interviewer_need=interviewer_need,
            )
        selected_build_examples: list[str] = []
        if wants_multiple_examples and focuses_on_build_from_zero:
            selected_build_examples = self._select_probative_build_examples(
                candidate=candidate,
                asks=ordered_asks,
                snapshot_text=snapshot_text,
                limit=2,
            )

        contextual_dimensions = self._derive_interviewer_evaluation_dimensions(
            context_focus=context_focus,
            coverage_points=coverage_points,
            asks=ordered_asks,
            snapshot_text=snapshot_text,
            ask_intents=ask_intents,
        ) or self._normalize_unique_strings(list(interviewer_need.dimensions or []))[:4]
        required_moves: list[str] = []
        if answer_mode == "profile_alignment":
            required_moves.extend(
                [
                    "Answer the introduction directly before expanding.",
                    "Use one concrete proof that best matches the interviewer decision.",
                    "Only weave prior context that clarifies the problem being mapped.",
                    "Keep the answer as a professional introduction, not a generic biography.",
                ]
            )
        elif answer_mode == "technical_walkthrough":
            required_moves.extend(
                [
                    "Answer directly before expanding.",
                    "Explain the approach, the main design choices, and the trade-offs.",
                    "Use direct answer, then approach and trade-offs, then the practical takeaway.",
                    "Close with the operational or business outcome of that approach.",
                ]
            )
        elif answer_mode == "preferences":
            required_moves.extend(
                [
                    "State the preference directly.",
                    "Organize the answer by the preference areas the interviewer named.",
                    "Stay on preferences and boundaries rather than drifting into profile recap.",
                ]
            )
        elif answer_mode == "experience_with_outcomes":
            required_moves.extend(
                [
                    "Use role, what you did, and the outcome or business impact in that order.",
                    "Use direct proof for the main ask rather than abstract summary.",
                    "Make ownership and outcome explicit.",
                    "Make the transitions audible when there are multiple asks.",
                ]
            )
        else:
            required_moves.extend(
                [
                    "Answer the asks directly and in order.",
                    "Keep one short segment per interviewer ask when there are multiple asks.",
                ]
            )
        if focuses_on_build_from_zero:
            required_moves.append("For build-from-zero proof, make the object built, stage, ownership, and outcome explicit.")
            if wants_multiple_examples:
                required_moves.append("Keep multiple examples clearly separated and easy to compare.")
        if ordered_coverage_required or len(ordered_asks) > 1:
            required_moves.append("Format multi-part answers as short paragraphs separated by a blank line, without bullets or headings.")
        required_moves = self._normalize_unique_strings([item for item in required_moves if self._normalize_text(item)])[:6]

        avoid = ["generic_biography", "resume_fragments", "repeated_profile_summary"]
        if answer_mode == "profile_alignment":
            avoid.append("unsupported_fit_closure")
        if metrics_policy != "required":
            avoid.append("unsupported_metrics")
        if company_context_policy == "avoid":
            avoid.append("company_pitch")
        if candidate_context_policy == "avoid" or profile_evidence_mode == "none":
            avoid.append("career_biography")
        if answer_mode == "preferences":
            avoid.append("leadership_scope_detour")

        if len(ask_intents) > 1:
            paragraph_plan = [
                f"Paragraph {index + 1}: answer {self._compact_text(intent.ask_text, limit=72)}."
                for index, intent in enumerate(ask_intents[:4])
            ]
        elif answer_mode == "profile_alignment":
            paragraph_plan = [
                "Paragraph 1: direct introduction and best supporting proof.",
                "Paragraph 2: why that background matches the interviewer problem.",
            ]
        else:
            paragraph_plan = [
                f"Paragraph {index + 1}: {intent.response_goal}"
                for index, intent in enumerate(ask_intents[:4])
            ]
        if not paragraph_plan:
            paragraph_plan = ["Paragraph 1: answer the main ask directly."]

        style_constraints: list[str] = []
        if candidate_context_policy == "avoid" or profile_evidence_mode == "none":
            style_constraints.append("Do not add biography, years of experience, or profile summary unless the ask requires it.")
        if answer_mode == "profile_alignment":
            style_constraints.append("Keep the answer centered on the relevant background for the interviewer problem, not on a generic biography.")
            style_constraints.append("Use prior interviewer context only to clarify what part of the background matters.")
        if answer_mode == "preferences":
            style_constraints.append("Keep the answer inside the stated preferences and do not convert it into a background summary.")
        if wants_multiple_examples and focuses_on_build_from_zero:
            style_constraints.append("Keep the build examples brief, distinct, and easy to follow aloud.")
        style_constraints.extend(
            [
                f"Use a {self._normalize_text(style_hint).lower() or tone} spoken style.",
                f"Keep the answer {directness} and natural for live delivery.",
                f"Target about {target_length} words.",
            ]
        )
        if ordered_coverage_required or len(ordered_asks) > 1:
            style_constraints.append("Format multi-part answers as short paragraphs separated by a blank line, without bullets or headings.")
        if response_shape == "direct_short":
            style_constraints.append("Keep it compact and avoid unnecessary background.")

        if answer_mode == "profile_alignment":
            must_cover_seed = [profile_alignment_proof or "one concrete proof that best supports the introduction"]
            if profile_alignment_scope and any(
                evidence in {"leadership_evidence", "team_scope_evidence"}
                for evidence in evidence_priority
            ):
                must_cover_seed.append(profile_alignment_scope)
            if prior_context_mode != "none":
                must_cover_seed.extend(list(contextual_dimensions or [])[:1])
        elif answer_mode == "technical_walkthrough":
            must_cover_seed = [
                *list(contextual_dimensions or [])[:2],
                "direct answer",
                "main design choices or trade-offs",
                "practical outcome or operational implication",
            ]
        elif answer_mode == "experience_with_outcomes":
            must_cover_seed = [
                "role and scope",
                "what was done or led",
                "outcome or business impact",
                *list(contextual_dimensions or [])[:2],
            ]
        elif answer_mode == "preferences":
            must_cover_seed = [*list(coverage_points or [])[:3]]
            if any("don't like" in ask.lower() or "do not like" in ask.lower() for ask in list(ordered_asks or [])):
                must_cover_seed.append("boundaries or anti-patterns")
        else:
            must_cover_seed = [
                *list(coverage_points or []),
                *[
                    self._normalize_text(intent.decision_target) or self._normalize_text(intent.response_goal)
                    for intent in ask_intents[:3]
                ],
            ]
        if wants_multiple_examples and focuses_on_build_from_zero:
            must_cover_seed = [
                (
                    self._compact_text(selected_build_examples[0], limit=110)
                    if len(selected_build_examples) >= 1
                    else "example 1: object built, stage, ownership, and outcome"
                ),
                (
                    self._compact_text(selected_build_examples[1], limit=110)
                    if len(selected_build_examples) >= 2
                    else "example 2: object built, stage, ownership, and outcome"
                ),
                "for each example: object built, stage, ownership, and outcome",
                f"interviewer-named build categories: {object_focus_phrase}" if object_focus_phrase else "",
                *(["team scale and composition"] if asks_team_scope else []),
            ]
        if answer_mode == "profile_alignment":
            context_to_weave = self._normalize_unique_strings(
                [
                    *list(contextual_dimensions or []),
                ]
            )[:4]
        elif prior_context_mode != "none":
            context_to_weave = self._normalize_unique_strings(list(contextual_dimensions or [])[:3])[:4]
        elif wants_multiple_examples and focuses_on_build_from_zero:
            context_to_weave = self._normalize_unique_strings(
                [
                    *list(selected_build_examples or []),
                    *list(contextual_dimensions or []),
                ]
            )[:4]
        elif answer_mode == "preferences":
            context_to_weave = []
        else:
            context_to_weave = list(contextual_dimensions or [])

        return ResponseRequirement(
            answer_mode=answer_mode,
            response_order=list(ordered_asks or []),
            required_moves=required_moves,
            context_to_weave=context_to_weave,
            evidence_priority=evidence_priority[:4],
            must_cover=self._normalize_unique_strings(must_cover_seed)[:5],
            avoid=self._normalize_unique_strings(avoid)[:5],
            paragraph_plan=self._normalize_unique_strings(paragraph_plan)[:4],
            style_constraints=self._normalize_unique_strings(style_constraints)[:6],
            profile_evidence_mode=profile_evidence_mode,
            company_evidence_mode=company_evidence_mode,
            prior_context_mode=prior_context_mode,
        )

    def _derive_context_dimensions(
        self,
        *,
        context_focus: list[str],
        coverage_points: list[str],
    ) -> list[str]:
        seed = " ".join([*list(context_focus or []), *list(coverage_points or [])]).lower()
        dimensions: list[str] = []
        if any(term in seed for term in ("ai", "llm", "agent", "agents", "vector", "vectors", "graph", "graphs", "knowledge")):
            dimensions.append("AI-ready data foundations for LLM and agent use cases")
        if any(term in seed for term in ("aws", "cloud", "infrastructure", "platform", "architecture", "design")):
            dimensions.append("cloud and data platform architecture leadership")
        if any(term in seed for term in ("lead", "leadership", "teams", "build", "delivery", "operating")):
            dimensions.append("technical leadership and delivery direction")
        if any(term in seed for term in ("client", "stakeholder", "roadmap", "requirements", "solutions", "design")):
            dimensions.append("turning delivery and architecture needs into clear solution direction")
        return self._normalize_unique_strings(dimensions)[:4]

    def _derive_compatibility_contract(
        self,
        *,
        ordered_asks: list[str],
        question_type: str,
        answer_contract: str,
        response_requirement: ResponseRequirement,
        interviewer_need: InterviewerNeed,
        ask_intents: list[AskIntent],
    ) -> dict[str, Any]:
        answer_mode = self._normalize_text(response_requirement.answer_mode).lower()
        if answer_mode == "profile_alignment":
            response_family = "intro_alignment"
        elif answer_mode == "technical_walkthrough" or question_type == "technical" or answer_contract == "architecture_walkthrough":
            response_family = "technical_fit"
        elif answer_mode == "preferences" or answer_contract == "preferences_and_anti_patterns":
            response_family = "culture_preferences"
        elif len(list(ordered_asks or [])) > 1:
            response_family = "mixed_multi_part"
        elif answer_mode == "experience_with_outcomes" or question_type in {"behavioral", "business"}:
            response_family = "behavioral_story"
        else:
            response_family = "mixed_multi_part" if len(list(ordered_asks or [])) > 1 else "intro_alignment"

        alignment_brief = self._derive_context_dimensions(
            context_focus=[
                interviewer_need.summary or "",
                *list(interviewer_need.dimensions or []),
                *list(response_requirement.context_to_weave or []),
            ],
            coverage_points=[],
        ) or self._normalize_unique_strings(
            [*list(interviewer_need.dimensions or [])[:3], *list(response_requirement.context_to_weave or [])[:2]]
        )[:3]
        guardrails = ["direct_first_sentence"]
        if len(list(ordered_asks or [])) > 1:
            guardrails.append("preserve_ask_order")
        avoid_map = {
            "unsupported_metrics": "avoid_unsupported_metrics",
            "company_pitch": "avoid_generic_company_pitch",
            "career_biography": "avoid_biography",
            "generic_biography": "avoid_biography",
            "unsupported_fit_closure": "avoid_unframed_fit_close",
            "resume_fragments": "avoid_resume_fragments",
            "repeated_profile_summary": "avoid_repeated_profile_summary",
        }
        for item in list(response_requirement.avoid or []):
            mapped = avoid_map.get(self._normalize_text(item).lower())
            if mapped:
                guardrails.append(mapped)
        delivery_instructions = self._normalize_unique_strings(
            [*list(response_requirement.required_moves or []), *list(response_requirement.style_constraints or [])]
        )[:6]

        blueprint: list[dict[str, Any]] = []
        for intent in list(ask_intents or []):
            ask_text = self._normalize_text(intent.ask_text)
            if not ask_text:
                continue
            lowered_ask = ask_text.lower()
            lowered_intent = self._normalize_text(intent.ask_intent).lower()
            if self._looks_like_intro_request(ask_text):
                purpose = "intro_tail" if len(list(ordered_asks or [])) > 1 else "profile_core"
            elif "team_composition" in lowered_intent or any(term in lowered_ask for term in ("roles did they have", "role did they have", "team composition")):
                purpose = "team_composition"
            elif "leadership" in lowered_intent or any(term in lowered_ask for term in ("team management", "teams you've managed", "how big were the teams", "team scope")):
                purpose = "leadership_scope"
            elif "technical" in lowered_intent or answer_contract == "architecture_walkthrough":
                purpose = "technical_approach"
            elif answer_contract == "preferences_and_anti_patterns":
                purpose = "preferences_company_culture_team"
            else:
                purpose = "build_or_experience" if question_type in {"behavioral", "business", "mixed"} else "ask_response"
            required_elements = [intent.response_goal] if self._normalize_text(intent.response_goal) else []
            if purpose == "build_or_experience":
                required_elements = self._normalize_unique_strings(
                    [
                        *required_elements,
                        *[
                            item
                            for item in list(response_requirement.must_cover or [])
                            if any(term in item.lower() for term in ("example", "built", "ownership", "outcome", "stage"))
                        ],
                    ]
                )[:4]
            blueprint.append(
                self._make_blueprint_segment(
                    purpose=purpose,
                    ask_refs=[ask_text],
                    required_elements=required_elements,
                    preferred_evidence_types=list(intent.required_evidence_types or response_requirement.evidence_priority or []),
                    avoid_topics=list(response_requirement.avoid or []),
                    target_sentence_count=1 if intent.expected_answer_shape == "direct_short" else 2,
                )
            )

        return {
            "response_family": response_family,
            "alignment_brief": alignment_brief,
            "quality_guardrails": self._normalize_unique_strings(guardrails)[:6],
            "delivery_instructions": delivery_instructions,
            "answer_blueprint": blueprint[:5],
        }

    def _normalize_llm_plan(
        self,
        *,
        snapshot: BrainSnapshot,
        payload: dict[str, Any],
        interview_config: Optional[dict[str, Any]] = None,
    ) -> BrainPlan:
        raw_detected_asks = self._normalize_unique_strings(payload.get("raw_detected_asks") or [])
        dropped_noise_clauses = self._normalize_unique_strings(payload.get("dropped_noise_clauses") or [])
        ordered_asks = self._normalize_unique_strings(payload.get("asks") or payload.get("ordered_asks") or [])
        coverage_points = self._normalize_unique_strings(payload.get("coverage_points") or [])
        resolved_question = self._normalize_text(payload.get("resolved_question"))
        if not raw_detected_asks:
            raw_detected_asks = list(ordered_asks)
        if not ordered_asks and resolved_question:
            ordered_asks = [resolved_question]
        if not coverage_points:
            coverage_points = self._extract_coverage_points(ordered_asks or ([resolved_question] if resolved_question else []))
        if not resolved_question:
            resolved_question = ordered_asks[0] if len(ordered_asks) == 1 else self._build_resolved_question(ordered_asks)

        (
            safe_raw_detected,
            safe_accepted,
            safe_dropped,
            safe_completeness,
            safe_clause_classifications,
            safe_supporting_interviewer_context,
        ) = self._extract_safe_candidates(
            snapshot.snapshot_text
        )
        ordered_asks, raw_detected_asks, dropped_noise_clauses, resolved_question = self._prefer_stronger_safe_asks(
            ordered_asks=ordered_asks,
            raw_detected_asks=raw_detected_asks,
            dropped_noise_clauses=dropped_noise_clauses,
            resolved_question=resolved_question,
            safe_accepted=safe_accepted,
            safe_raw_detected=safe_raw_detected,
            safe_dropped=safe_dropped,
        )
        if ordered_asks and not safe_accepted:
            actionable_payload_asks = [
                ask
                for ask in list(ordered_asks or [])
                if not self._looks_like_meta_handoff_clause(ask)
                and not self._looks_like_relative_clause_fragment(ask)
            ]
            if not actionable_payload_asks:
                ordered_asks = []
                resolved_question = ""
        if not ordered_asks:
            resolved_question = self._select_safe_resolved_question(
                raw_detected_asks=safe_raw_detected or raw_detected_asks,
                snapshot_text=snapshot.snapshot_text,
                clause_classifications=safe_clause_classifications,
            )

        compact_is_complete = payload.get("is_complete")
        question_completeness = self._normalize_choice(
            payload.get("question_completeness"),
            {"complete", "partial", "garbled"},
            "complete" if compact_is_complete is True else ("partial" if ordered_asks else "garbled"),
        )
        if not ordered_asks and not resolved_question and question_completeness == "complete":
            question_completeness = safe_completeness if safe_completeness in {"partial", "garbled"} else "garbled"
        if (
            safe_completeness == "complete"
            and self._ask_bundle_quality(safe_accepted, completeness=safe_completeness)
            > self._ask_bundle_quality(ordered_asks, completeness=question_completeness)
        ):
            question_completeness = "complete"
        if not ordered_asks and not resolved_question and question_completeness != "complete":
            question_type = "direct"
        else:
            question_type = self._normalize_choice(
                payload.get("question_type"),
                {"direct", "behavioral", "technical", "business", "mixed"},
                self._derive_question_type(ordered_asks=ordered_asks, resolved_question=resolved_question),
            )
        literal_question = self._normalize_text(payload.get("literal_question"))
        if not ordered_asks and not resolved_question and question_completeness != "complete":
            literal_question = ""
        if not literal_question:
            literal_question = ordered_asks[0] if len(ordered_asks) == 1 else resolved_question
        contextualized_question = self._normalize_text(
            payload.get("contextualized_question") or payload.get("effective_question")
        )
        if not ordered_asks and not resolved_question and question_completeness != "complete":
            contextualized_question = ""
        if not contextualized_question:
            contextualized_question = literal_question or resolved_question
        if not ordered_asks and not resolved_question and question_completeness != "complete":
            response_shape = "direct_short"
            answer_contract = "general_direct"
            tone = "concise"
            directness = "direct"
        else:
            response_shape = self._normalize_choice(
                payload.get("response_shape") or payload.get("answer_shape"),
                {"direct_short", "direct_structured", "technical_explainer", "strategic_explainer"},
                "direct_structured" if len(ordered_asks) > 1 or len(coverage_points) > 1 else "direct_short",
            )
            answer_contract = self._normalize_choice(
                payload.get("answer_contract"),
                {
                    "general_direct",
                    "direct_multi_part",
                    "preferences_and_anti_patterns",
                    "direct_explanation",
                    "architecture_walkthrough",
                    "business_with_outcomes",
                    "follow_up_focused",
                },
                self._derive_answer_contract(
                    question_type=question_type,
                    response_shape=response_shape,
                    asks=ordered_asks,
                    coverage_points=coverage_points,
                ),
            )
            tone = self._normalize_choice(
                payload.get("tone"),
                {"concise", "balanced", "professional", "technical", "executive"},
                self._derive_tone(question_type=question_type, response_shape=response_shape),
            )
            directness = self._normalize_choice(
                payload.get("directness"),
                {"direct", "balanced", "detailed"},
                self._tone_to_directness(tone),
            )
        evidence_depth = self._normalize_choice(payload.get("evidence_depth"), {"light", "medium", "deep"}, "light")
        use_metrics = payload.get("use_metrics")
        metrics_policy = self._normalize_choice(
            payload.get("metrics_policy"),
            {"avoid_unless_helpful", "prefer_if_supported", "required"},
            "prefer_if_supported" if use_metrics else "avoid_unless_helpful",
        )
        use_company_context = payload.get("use_company_context")
        company_context_policy = self._normalize_choice(
            payload.get("company_context_policy"),
            {"avoid", "support_if_relevant", "required"},
            "avoid" if use_company_context is False else "support_if_relevant",
        )
        use_candidate_context = payload.get("use_candidate_context")
        candidate_context_policy = self._normalize_choice(
            payload.get("candidate_context_policy"),
            {"avoid", "support_if_relevant", "required"},
            self._candidate_context_policy_from_flag(
                enabled=use_candidate_context,
                question_type=question_type,
                asks=ordered_asks,
            ),
        )
        if not ordered_asks and not resolved_question and question_completeness != "complete":
            company_context_policy = "avoid"
            candidate_context_policy = "avoid"
        draft_answer = self._normalize_text(payload.get("draft_answer"))
        if not draft_answer and not ordered_asks and not resolved_question and question_completeness == "garbled":
            draft_answer = "I did not catch the full question clearly enough to give you a reliable answer."
        target_length = int(payload.get("target_length") or (110 if len(ordered_asks) <= 1 else 170))
        if not ordered_asks and not resolved_question and question_completeness != "complete":
            target_length = 90
        target_length = max(80, min(target_length, 260))
        confidence = float(payload.get("confidence") or 0.5)
        confidence = max(0.0, min(confidence, 1.0))
        context_focus = self._normalize_unique_strings(payload.get("context_focus") or [])
        if not context_focus:
            context_focus = self._normalize_unique_strings(safe_supporting_interviewer_context[:4])
        ask_intents = self._normalize_payload_ask_intents(
            values=payload.get("ask_intents") or [],
            ordered_asks=ordered_asks,
            question_type=question_type,
            answer_contract=answer_contract,
            response_shape=response_shape,
            context_focus=context_focus,
            snapshot_text=snapshot.snapshot_text,
        )
        interviewer_need = self._normalize_payload_interviewer_need(
            value=payload.get("interviewer_need"),
            ordered_asks=ordered_asks,
            question_type=question_type,
            coverage_points=coverage_points,
            context_focus=context_focus,
            ask_intents=ask_intents,
            snapshot_text=snapshot.snapshot_text,
        )
        normalized_candidate, _normalized_company, _normalized_interviewer = self._normalize_interview_metadata(interview_config)
        response_requirement = self._normalize_payload_response_requirement(
            value=payload.get("response_requirement"),
            ordered_asks=ordered_asks,
            coverage_points=coverage_points,
            question_type=question_type,
            answer_contract=answer_contract,
            response_shape=response_shape,
            tone=tone,
            directness=directness,
            target_length=target_length,
            context_focus=context_focus,
            ask_intents=ask_intents,
            interviewer_need=interviewer_need,
            style_hint=tone,
            metrics_policy=metrics_policy,
            candidate_context_policy=candidate_context_policy,
            company_context_policy=company_context_policy,
            ordered_coverage_required=bool(question_completeness == "complete" and len(coverage_points) > 1),
            delivery_hints=self._normalize_unique_strings(payload.get("delivery_instructions") or []),
            alignment_hints=self._normalize_unique_strings(payload.get("alignment_brief") or []),
            avoid_hints=self._normalize_unique_strings(payload.get("quality_guardrails") or []),
            candidate=normalized_candidate,
            snapshot_text=snapshot.snapshot_text,
        )
        compatibility = self._derive_compatibility_contract(
            ordered_asks=ordered_asks,
            question_type=question_type,
            answer_contract=answer_contract,
            response_requirement=response_requirement,
            interviewer_need=interviewer_need,
            ask_intents=ask_intents,
        )
        serve_mode = self._normalize_choice(
            payload.get("serve_mode"),
            {"direct_brain", "finalize_from_draft", "finalize_from_plan"},
            self._derive_serve_mode(
                question_completeness=question_completeness,
                draft_answer=draft_answer,
                confidence=confidence,
                response_shape=response_shape,
                ask_count=len(ordered_asks),
                coverage_count=len(coverage_points),
            ),
        )
        if serve_mode == "direct_brain":
            serve_mode = "finalize_from_draft" if draft_answer else "finalize_from_plan"

        if question_completeness != "complete" and len(ordered_asks) <= 1:
            ordered_asks = ordered_asks[:1]
        if not coverage_points:
            coverage_points = self._extract_coverage_points(ordered_asks or ([resolved_question] if resolved_question else []))
        response_family = compatibility["response_family"]
        alignment_brief = compatibility["alignment_brief"]
        quality_guardrails = compatibility["quality_guardrails"]
        answer_blueprint = compatibility["answer_blueprint"]
        delivery_instructions = compatibility["delivery_instructions"]
        explicit_delivery_instructions = self._normalize_unique_strings(payload.get("delivery_instructions") or [])
        if explicit_delivery_instructions:
            delivery_instructions = explicit_delivery_instructions[:6]
        if not contextualized_question or contextualized_question == literal_question:
            contextualized_question = self._derive_contextualized_question(
                literal_question=literal_question,
                resolved_question=resolved_question,
                question_completeness=question_completeness,
                response_requirement=response_requirement,
                interviewer_need=interviewer_need,
                alignment_brief=alignment_brief,
                context_focus=context_focus,
            )

        return BrainPlan(
            session_id=snapshot.session_id,
            utterance_id=snapshot.utterance_id,
            revision_id=snapshot.revision_id,
            snapshot_hash=snapshot.snapshot_hash,
            literal_question=literal_question,
            contextualized_question=contextualized_question,
            ordered_asks=ordered_asks,
            coverage_points=coverage_points[:4],
            raw_detected_asks=raw_detected_asks,
            clause_classifications=safe_clause_classifications[:8],
            supporting_interviewer_context=safe_supporting_interviewer_context[:6],
            ask_intents=ask_intents[:5],
            interviewer_need=interviewer_need,
            response_requirement=response_requirement,
            context_focus=context_focus[:4],
            response_family=response_family,
            answer_blueprint=answer_blueprint[:5],
            alignment_brief=alignment_brief[:3],
            quality_guardrails=quality_guardrails[:6],
            resolved_question=(
                resolved_question
                or (snapshot.snapshot_text if question_completeness == "complete" else "")
            ),
            question_completeness=question_completeness,
            question_type=question_type,
            response_shape=response_shape,
            answer_contract=answer_contract,
            delivery_instructions=delivery_instructions[:6],
            tone=tone,
            directness=directness,
            include_profile_opening=bool(payload.get("include_profile_opening")),
            evidence_depth=evidence_depth,
            metrics_policy=metrics_policy,
            company_context_policy=company_context_policy,
            candidate_context_policy=candidate_context_policy,
            ordered_coverage_required=bool(
                payload.get("ordered_coverage_required")
                if question_completeness == "complete"
                else False
            ) or bool(question_completeness == "complete" and len(coverage_points) > 1),
            target_length=target_length,
            draft_answer=draft_answer,
            serve_mode=serve_mode,
            confidence=confidence,
            stability_state="draft",
            plan_source="llm_fast",
            reasoning_summary=self._normalize_text(payload.get("reasoning_summary"))
            or "Live brain plan generated from the latest interviewer snapshot.",
            dropped_noise_clauses=dropped_noise_clauses,
        )

    def _normalize_payload_ask_intents(
        self,
        *,
        values: Any,
        ordered_asks: list[str],
        question_type: str,
        answer_contract: str,
        response_shape: str,
        context_focus: list[str],
        snapshot_text: str = "",
    ) -> list[AskIntent]:
        defaults = self._build_default_ask_intents(
            ordered_asks=ordered_asks,
            question_type=question_type,
            answer_contract=answer_contract,
            response_shape=response_shape,
            context_focus=context_focus,
            snapshot_text=snapshot_text,
        )
        if not isinstance(values, list) or not values:
            return defaults

        ask_intents: list[AskIntent] = []
        for index, item in enumerate(values):
            fallback = defaults[index] if index < len(defaults) else AskIntent()
            if isinstance(item, str):
                ask_intents.append(
                    fallback.model_copy(
                        update={
                            "ask_text": fallback.ask_text or (ordered_asks[index] if index < len(ordered_asks) else ""),
                            "ask_intent": self._normalize_text(item) or fallback.ask_intent,
                        }
                    )
                )
                continue
            if not isinstance(item, dict):
                continue
            ask_text = self._normalize_text(item.get("ask_text")) or fallback.ask_text or (ordered_asks[index] if index < len(ordered_asks) else "")
            ask_intent = self._normalize_text(item.get("ask_intent")) or fallback.ask_intent
            speech_act = self._normalize_text(item.get("speech_act")) or fallback.speech_act
            decision_target = self._normalize_text(item.get("decision_target")) or fallback.decision_target
            response_goal = self._normalize_text(item.get("response_goal")) or fallback.response_goal
            required_evidence_types = self._normalize_evidence_types(item.get("required_evidence_types") or fallback.required_evidence_types)
            expected_answer_shape = self._normalize_choice(
                item.get("expected_answer_shape"),
                {"direct_short", "direct_structured", "technical_explainer", "strategic_explainer"},
                fallback.expected_answer_shape or response_shape,
            )
            ask_intents.append(
                AskIntent(
                    ask_text=ask_text,
                    ask_intent=ask_intent,
                    speech_act=speech_act,
                    decision_target=decision_target,
                    response_goal=response_goal,
                    required_evidence_types=required_evidence_types,
                    expected_answer_shape=expected_answer_shape,
                    needs_context_from_prior_turns=bool(
                        item.get("needs_context_from_prior_turns")
                        if item.get("needs_context_from_prior_turns") is not None
                        else fallback.needs_context_from_prior_turns
                    ),
                    profile_evidence_mode=self._normalize_profile_evidence_mode(
                        item.get("profile_evidence_mode"),
                        fallback.profile_evidence_mode or "support_if_relevant",
                    ),
                    company_evidence_mode=self._normalize_company_evidence_mode(
                        item.get("company_evidence_mode"),
                        fallback.company_evidence_mode or "support_if_relevant",
                    ),
                    prior_context_mode=self._normalize_prior_context_mode(
                        item.get("prior_context_mode"),
                        fallback.prior_context_mode or "support_if_relevant",
                    ),
                )
            )
        return ask_intents or defaults

    def _normalize_payload_interviewer_need(
        self,
        *,
        value: Any,
        ordered_asks: list[str],
        question_type: str,
        coverage_points: list[str],
        context_focus: list[str],
        ask_intents: list[AskIntent],
        snapshot_text: str = "",
    ) -> InterviewerNeed:
        default_need = self._build_default_interviewer_need(
            ordered_asks=ordered_asks,
            question_type=question_type,
            coverage_points=coverage_points,
            context_focus=context_focus,
            ask_intents=ask_intents,
            snapshot_text=snapshot_text,
        )
        if isinstance(value, str):
            summary = self._normalize_text(value)
            return default_need.model_copy(update={"summary": summary or default_need.summary})
        if not isinstance(value, dict):
            return default_need
        summary = self._normalize_text(value.get("summary")) or default_need.summary
        dimensions = self._normalize_unique_strings(
            [*list(value.get("dimensions") or []), *list(default_need.dimensions or [])]
        )[:4]
        evidence_expected = self._normalize_evidence_types(
            [*list(value.get("evidence_expected") or []), *list(default_need.evidence_expected or [])]
        )[:4]
        return InterviewerNeed(
            summary=summary,
            dimensions=dimensions,
            evidence_expected=evidence_expected,
        )

    def _normalize_payload_response_requirement(
        self,
        *,
        value: Any,
        ordered_asks: list[str],
        coverage_points: list[str],
        question_type: str,
        answer_contract: str,
        response_shape: str,
        tone: str,
        directness: str,
        target_length: int,
        context_focus: list[str],
        ask_intents: list[AskIntent],
        interviewer_need: InterviewerNeed,
        style_hint: str,
        metrics_policy: str,
        candidate_context_policy: str,
        company_context_policy: str,
        ordered_coverage_required: bool,
        delivery_hints: list[str],
        alignment_hints: list[str],
        avoid_hints: list[str],
        candidate: dict[str, Any],
        snapshot_text: str = "",
    ) -> ResponseRequirement:
        default_requirement = self._build_default_response_requirement(
            ordered_asks=ordered_asks,
            coverage_points=coverage_points,
            question_type=question_type,
            answer_contract=answer_contract,
            response_shape=response_shape,
            tone=tone,
            directness=directness,
            target_length=target_length,
            context_focus=context_focus,
            ask_intents=ask_intents,
            interviewer_need=interviewer_need,
            style_hint=style_hint,
            metrics_policy=metrics_policy,
            candidate_context_policy=candidate_context_policy,
            company_context_policy=company_context_policy,
            ordered_coverage_required=ordered_coverage_required,
            candidate=candidate,
            snapshot_text=snapshot_text,
        )
        if not isinstance(value, dict):
            return default_requirement.model_copy(
                update={
                    "required_moves": self._normalize_unique_strings(
                        [*list(default_requirement.required_moves or []), *list(delivery_hints or [])]
                    )[:5],
                    "context_to_weave": self._normalize_unique_strings(
                        [*list(default_requirement.context_to_weave or []), *list(alignment_hints or [])]
                    )[:4],
                    "avoid": self._normalize_unique_strings(
                        [*list(default_requirement.avoid or []), *list(avoid_hints or [])]
                    )[:5],
                }
            )
        answer_mode = self._normalize_text(value.get("answer_mode")) or default_requirement.answer_mode
        response_order = self._normalize_unique_strings(value.get("response_order") or default_requirement.response_order)[:5]
        required_moves = self._normalize_unique_strings(
            [*list(value.get("required_moves") or []), *list(delivery_hints or []), *list(default_requirement.required_moves or [])]
        )[:5]
        context_to_weave = self._normalize_unique_strings(
            [*list(value.get("context_to_weave") or []), *list(value.get("context_focus") or []), *list(alignment_hints or []), *list(default_requirement.context_to_weave or [])]
        )[:4]
        evidence_priority = self._normalize_evidence_types(
            value.get("evidence_priority")
            or [evidence for intent in ask_intents for evidence in list(intent.required_evidence_types or [])]
            or default_requirement.evidence_priority
        )[:4]
        must_cover = self._normalize_unique_strings(
            [*list(value.get("must_cover") or []), *list(default_requirement.must_cover or [])]
        )[:5]
        avoid = self._normalize_unique_strings(
            [*list(value.get("avoid") or []), *list(avoid_hints or []), *list(default_requirement.avoid or [])]
        )[:5]
        paragraph_plan = self._normalize_unique_strings(
            [*list(value.get("paragraph_plan") or []), *list(default_requirement.paragraph_plan or [])]
        )[:4]
        style_constraints = self._normalize_unique_strings(
            [*list(value.get("style_constraints") or []), *list(default_requirement.style_constraints or [])]
        )[:5]
        return ResponseRequirement(
            answer_mode=answer_mode,
            response_order=response_order,
            required_moves=required_moves,
            context_to_weave=context_to_weave,
            evidence_priority=evidence_priority,
            must_cover=must_cover,
            avoid=avoid,
            paragraph_plan=paragraph_plan,
            style_constraints=style_constraints,
            profile_evidence_mode=self._normalize_profile_evidence_mode(
                value.get("profile_evidence_mode"),
                default_requirement.profile_evidence_mode,
            ),
            company_evidence_mode=self._normalize_company_evidence_mode(
                value.get("company_evidence_mode"),
                default_requirement.company_evidence_mode,
            ),
            prior_context_mode=self._normalize_prior_context_mode(
                value.get("prior_context_mode"),
                default_requirement.prior_context_mode,
            ),
        )

    def _prefer_stronger_safe_asks(
        self,
        *,
        ordered_asks: list[str],
        raw_detected_asks: list[str],
        dropped_noise_clauses: list[str],
        resolved_question: str,
        safe_accepted: list[str],
        safe_raw_detected: list[str],
        safe_dropped: list[str],
    ) -> tuple[list[str], list[str], list[str], str]:
        normalized_llm_asks = self._prune_low_priority_asks(self._normalize_unique_strings(ordered_asks))
        normalized_safe_asks = self._prune_low_priority_asks(self._normalize_unique_strings(safe_accepted))
        if not normalized_safe_asks:
            return ordered_asks, raw_detected_asks, dropped_noise_clauses, resolved_question

        latest_safe_ask = normalized_safe_asks[-1]
        llm_keeps_latest_safe = any(
            self._asks_semantically_overlap(llm_ask, latest_safe_ask)
            for llm_ask in normalized_llm_asks
        )
        llm_contains_meta_or_fragment = any(
            self._looks_like_meta_handoff_clause(llm_ask)
            or self._looks_like_relative_clause_fragment(llm_ask)
            for llm_ask in normalized_llm_asks
        )
        if (
            latest_safe_ask
            and self._is_complete_question_clause(latest_safe_ask)
            and not llm_keeps_latest_safe
            and (
                self._looks_like_intro_request(latest_safe_ask)
                or llm_contains_meta_or_fragment
            )
        ):
            merged_raw = self._normalize_unique_strings([*safe_raw_detected, *raw_detected_asks])
            merged_dropped = self._normalize_unique_strings([*dropped_noise_clauses, *safe_dropped])
            next_resolved = (
                normalized_safe_asks[0]
                if len(normalized_safe_asks) == 1
                else self._build_resolved_question(normalized_safe_asks)
            )
            return normalized_safe_asks[:5], merged_raw[:5], merged_dropped[:8], next_resolved or resolved_question

        llm_quality = self._ask_bundle_quality(normalized_llm_asks, completeness="complete" if normalized_llm_asks else "garbled")
        safe_quality = self._ask_bundle_quality(normalized_safe_asks, completeness="complete")
        if safe_quality <= llm_quality + 0.5:
            return ordered_asks, raw_detected_asks, dropped_noise_clauses, resolved_question

        merged_raw = self._normalize_unique_strings([*safe_raw_detected, *raw_detected_asks])
        merged_dropped = self._normalize_unique_strings([*dropped_noise_clauses, *safe_dropped])
        next_resolved = (
            normalized_safe_asks[0]
            if len(normalized_safe_asks) == 1
            else self._build_resolved_question(normalized_safe_asks)
        )
        return normalized_safe_asks[:5], merged_raw[:5], merged_dropped[:8], next_resolved or resolved_question

    def _ask_bundle_quality(self, asks: list[str], *, completeness: str) -> float:
        normalized_asks = [self._normalize_text(ask) for ask in list(asks or []) if self._normalize_text(ask)]
        if not normalized_asks:
            return 0.0
        score = sum(self._question_clause_score(ask) for ask in normalized_asks[:5])
        score += len(normalized_asks[:5]) * 1.5
        if str(completeness or "").strip().lower() == "complete":
            score += 1.0
        if any(self._looks_like_intro_request(ask) for ask in normalized_asks) and len(normalized_asks) > 1:
            score -= 1.25
        return score

    def _build_prompt(
        self,
        *,
        snapshot: BrainSnapshot,
        interview_config: dict[str, Any],
        previous_plan: Optional[BrainPlan],
    ) -> str:
        candidate, company, interviewer = self._normalize_interview_metadata(interview_config)
        style_hint = self._normalize_text(interview_config.get("style_id") or interview_config.get("response_style") or "professional")
        candidate_role = self._compact_text(candidate.get("currentRole") or candidate.get("current_role"), limit=60) or "unknown"
        company_role = self._compact_text((company.get("roleTitle") or company.get("positionTitle")), limit=60) or "unknown"
        candidate_evidence_snapshot = self._build_candidate_evidence_snapshot_for_prompt(
            candidate=candidate,
            snapshot_text=snapshot.snapshot_text,
        )
        previous_summary = "None"
        if previous_plan is not None and self._normalize_text(previous_plan.resolved_question):
            previous_summary = self._build_previous_plan_semantic_snapshot(previous_plan)

        return f"""
You are the autonomous live interview brain.
Your job is to read the consolidated interviewer history, decide what must be answered now,
and hand Emit a precise semantic contract so Emit can answer without reinterpreting the interview.

CONSOLIDATED INTERVIEWER HISTORY:
{snapshot.snapshot_text}

RECENT CONVERSATION HISTORY:
{self._format_history(snapshot.conversation_history[-5:])}

AVAILABLE METADATA:
- interview_type: {self._normalize_text(interview_config.get("interview_type") or "unknown")}
- style_hint: {style_hint}
- candidate_role: {candidate_role}
- target_role: {company_role}
- candidate_context_available: {bool(candidate)}
- company_context_available: {bool(company)}
- interviewer_context_available: {bool(interviewer)}
- previous_plan: {previous_summary}

CANDIDATE PROFILE EVIDENCE SNAPSHOT:
{candidate_evidence_snapshot}

What you must decide:
1. The exact asks that should be answered now, in order.
2. What is interviewer context versus what is the literal question being asked now.
3. What the interviewer really wants to learn behind the ask.
4. Which kinds of profile evidence, company evidence, and prior context are actually needed for each ask.
5. The minimal response contract Emit needs.

Hard rules:
- Ignore filler, preamble, repeated fragments, and interviewer self-commentary unless they materially shape how the answer should be framed.
- Keep attached follow-ups with the right ask when they belong together.
- If the latest ask is incomplete, mark question_completeness as partial or garbled and leave draft_answer empty.
- Treat prior turns as interviewer context when they define the problem, constraints, success criteria, leadership expectations, technical environment, or why the current question matters.
- Use context_focus for prior interviewer context that should shape the answer, not as extra asks.
- literal_question must be the explicit latest question the interviewer asked.
- contextualized_question must clarify the effective question using relevant prior context, but it must not script the answer or list concrete proof lines.
- If the literal question is broad or underspecified, contextualized_question should make the evaluation target explicit without inventing new asks.
- Never turn prior interviewer context into extra asks unless the interviewer explicitly asked those things now.
- interviewer_need.summary must describe the real decision being made about the candidate, not just the topic.
- ask_intents.decision_target must describe the decision behind that ask.
- Infer the needed proof from the asks, prior context, and profile snapshot itself; do not rely on canned mappings or fixed per-question examples.
- ask_intents.profile_evidence_mode must be one of: none, orientation_only, scope_only, one_best_proof, multi_proof, support_if_relevant.
- ask_intents.company_evidence_mode must be one of: none, preference_alignment, problem_mapping, support_if_relevant.
- ask_intents.prior_context_mode must be one of: none, disambiguate, evaluation_scope, support_if_relevant.
- profile_evidence_mode semantics: none means no profile facts should be used; orientation_only means minimal positioning only; scope_only means only leadership/team scope; one_best_proof means one supporting proof beyond orientation; multi_proof means multiple distinct proofs are required.
- company_evidence_mode semantics: none means ignore company context; preference_alignment means use company context only to mirror preference areas; problem_mapping means use company context only to clarify the problem being mapped.
- prior_context_mode semantics: none means do not weave prior interviewer context; disambiguate means use it only to resolve what the ask means; evaluation_scope means use it only to clarify what decision the interviewer is making.
- response_requirement.must_cover should describe obligations that follow from the semantic contract, not scripted openings.
- For multi-ask prompts, preserve one response segment per interviewer ask. Do not collapse a trailing ask into a vague close.
- response_requirement.required_moves should be concrete and minimal.
- response_requirement.must_cover should state obligations, not script the opening sentence.
- draft_answer is optional. Leave it empty unless a compact spoken draft is materially helpful.
- Return exactly one JSON object and nothing else.
- The first non-whitespace character must be {{ and the last must be }}.

JSON schema:
{{
  "literal_question": "the explicit latest question",
  "contextualized_question": "the effective question Emit should answer using the relevant context",
  "asks": ["ask 1", "ask 2"],
  "resolved_question": "single resolved question or ordered ask summary",
  "question_completeness": "complete|partial|garbled",
  "question_type": "direct|behavioral|technical|business|mixed",
  "response_shape": "direct_short|direct_structured|technical_explainer|strategic_explainer",
  "answer_contract": "general_direct|direct_multi_part|preferences_and_anti_patterns|direct_explanation|architecture_walkthrough|business_with_outcomes|follow_up_focused",
  "use_candidate_context": true,
  "use_company_context": false,
  "use_metrics": false,
  "coverage_points": ["focus 1", "focus 2"],
  "ask_intents": [
    {{
      "ask_text": "ask text",
      "ask_intent": "what this ask is trying to learn",
      "speech_act": "professional introduction | experience proof | preference statement | technical explanation | ...",
      "decision_target": "the actual hiring/interview decision behind this ask",
      "response_goal": "what a strong answer should accomplish",
      "required_evidence_types": ["role_evidence", "build_evidence"],
      "expected_answer_shape": "direct_structured",
      "needs_context_from_prior_turns": true,
      "profile_evidence_mode": "none|orientation_only|scope_only|one_best_proof|multi_proof|support_if_relevant",
      "company_evidence_mode": "none|preference_alignment|problem_mapping|support_if_relevant",
      "prior_context_mode": "none|disambiguate|evaluation_scope|support_if_relevant"
    }}
  ],
  "interviewer_need": {{
    "summary": "the actual decision being made about the candidate",
    "dimensions": ["dimension 1", "dimension 2"],
    "evidence_expected": ["role_evidence", "technical_alignment_evidence"]
  }},
  "context_focus": ["prior interviewer context that should shape the answer"],
  "response_requirement": {{
    "answer_mode": "profile_alignment|experience_with_outcomes|technical_walkthrough|preferences|structured_direct",
    "response_order": ["ask 1", "ask 2"],
    "required_moves": ["specific move Emit must make"],
    "context_to_weave": ["context item to weave into the answer"],
    "evidence_priority": ["role_evidence", "build_evidence"],
    "must_cover": ["thing that must be covered"],
    "avoid": ["generic biography", "company pitch"],
    "paragraph_plan": ["paragraph 1 purpose", "paragraph 2 purpose"],
    "style_constraints": ["spoken", "no bullets"],
    "profile_evidence_mode": "none|orientation_only|scope_only|one_best_proof|multi_proof|support_if_relevant",
    "company_evidence_mode": "none|preference_alignment|problem_mapping|support_if_relevant",
    "prior_context_mode": "none|disambiguate|evaluation_scope|support_if_relevant"
  }},
  "delivery_instructions": ["specific instruction 1"],
  "draft_answer": "optional compact spoken answer; usually empty unless materially helpful",
  "confidence": 0.0,
  "reasoning_summary": "one short sentence"
}}
"""

    def _build_previous_plan_semantic_snapshot(self, previous_plan: BrainPlan) -> str:
        ask_summary = " | ".join(
            self._compact_text(ask, limit=80)
            for ask in list(previous_plan.ordered_asks or [])[:3]
            if self._normalize_text(ask)
        ) or "None"
        context_summary = " | ".join(
            self._compact_text(item, limit=72)
            for item in list(previous_plan.context_focus or [])[:3]
            if self._normalize_text(item)
        ) or "None"
        must_cover_summary = " | ".join(
            self._compact_text(item, limit=72)
            for item in list(previous_plan.response_requirement.must_cover or [])[:3]
            if self._normalize_text(item)
        ) or "None"
        return (
            f"asks={ask_summary}; "
            f"complete={previous_plan.question_completeness}; "
            f"type={previous_plan.question_type}; "
            f"family={previous_plan.response_family}; "
            f"contract={previous_plan.answer_contract}; "
            f"profile_mode={previous_plan.response_requirement.profile_evidence_mode or 'None'}; "
            f"company_mode={previous_plan.response_requirement.company_evidence_mode or 'None'}; "
            f"prior_mode={previous_plan.response_requirement.prior_context_mode or 'None'}; "
            f"context={context_summary}; "
            f"must_cover={must_cover_summary}"
        )

    def _extract_safe_candidates(
        self,
        text: str,
    ) -> tuple[list[str], list[str], list[str], str, list[dict[str, Any]], list[str]]:
        clauses = self._merge_question_continuations(self._split_candidate_clauses(text))
        raw_detected: list[str] = []
        accepted: list[str] = []
        dropped: list[str] = []
        clause_classifications: list[dict[str, Any]] = []
        supporting_interviewer_context: list[str] = []

        for index, clause in enumerate(clauses):
            original = self._normalize_text(clause)
            if not original:
                continue
            clause_function = self._classify_clause_function(
                clause=original,
                index=index,
                total=len(clauses),
            )
            clause_record: dict[str, Any] = {
                "text": original,
                "function": clause_function,
                "generated_asks": [],
            }
            clause_classifications.append(clause_record)

            if clause_function == "supporting_context":
                supporting_interviewer_context.append(original)
                continue
            if clause_function in {"interviewer_self_context", "meta_handoff", "other"}:
                continue

            generated_asks: list[str] = []
            clause_candidates = self._expand_enumerated_follow_up_candidates(original)
            if not clause_candidates:
                clause_candidates = self._split_embedded_question_candidates(original)
            for clause_candidate in clause_candidates:
                normalized = self._trim_to_question_lead(self._normalize_text(clause_candidate)).strip(" ,")
                normalized = self._canonicalize_safe_ask_text(normalized)
                if not normalized or not self._looks_like_question_clause(normalized):
                    continue
                generated_asks.append(normalized)
            clause_record["generated_asks"] = generated_asks[:4]

            for generated in generated_asks:
                raw_detected.append(generated)
                score = self._question_clause_score(generated)
                complete = self._is_complete_question_clause(generated)
                if complete and score >= 2.0:
                    if generated not in accepted:
                        accepted.append(generated)
                else:
                    dropped.append(generated)

        accepted = self._prune_low_priority_asks(accepted)
        raw_detected = self._prune_low_priority_asks(raw_detected)
        dropped = self._prune_low_priority_asks(dropped)

        question_completeness = "garbled"
        if accepted and not dropped:
            question_completeness = "complete"
        elif accepted:
            noisy_only_drops = all(
                (
                    self._is_complete_question_clause(clause)
                    and self._question_clause_score(clause) < 2.0
                )
                or (
                    not self._is_complete_question_clause(clause)
                    and self._question_clause_score(clause) < 0.75
                )
                for clause in dropped
            )
            question_completeness = "complete" if noisy_only_drops else "partial"
        elif raw_detected:
            question_completeness = "partial"

        if question_completeness != "complete" and not accepted:
            best_clear = self._pick_best_clear_ask(raw_detected)
            accepted = [best_clear] if best_clear else []

        if not raw_detected and self._normalize_text(text):
            dropped = [self._normalize_text(text)]

        return (
            raw_detected[:5],
            accepted[:5],
            dropped[:8],
            question_completeness,
            clause_classifications[:8],
            self._normalize_unique_strings(supporting_interviewer_context)[:6],
        )

    def _classify_clause_function(
        self,
        *,
        clause: str,
        index: int,
        total: int,
    ) -> str:
        normalized = self._normalize_text(clause)
        trimmed = self._canonicalize_safe_ask_text(self._trim_to_question_lead(normalized).strip(" ,"))
        actionable_request = self._is_actionable_request_frame(trimmed)
        actionable_request_in_original = self._is_actionable_request_frame(normalized)
        supporting_context = self._looks_like_supporting_interviewer_context(normalized)
        embedded_explicit_request = self._has_embedded_explicit_request(normalized)
        detached_trimmed_lead = self._has_detached_trimmed_question_lead(
            original_clause=normalized,
            trimmed_clause=trimmed,
        )
        original_complete_question = (
            self._looks_like_question_clause(normalized)
            and self._is_complete_question_clause(normalized)
            and not detached_trimmed_lead
        )

        if self._looks_like_meta_handoff_clause(normalized):
            return "meta_handoff"
        if embedded_explicit_request:
            return "actionable_ask"
        if supporting_context and not actionable_request_in_original and not embedded_explicit_request:
            return "supporting_context"
        if supporting_context and not actionable_request and not embedded_explicit_request:
            return "supporting_context"
        if self._looks_like_interviewer_self_context(normalized) and not actionable_request:
            return "interviewer_self_context"
        if actionable_request and not detached_trimmed_lead:
            return "actionable_ask"
        if original_complete_question:
            return "actionable_ask"
        if index == total - 1 and self._looks_like_intro_request(trimmed):
            return "actionable_ask"
        return "other"

    @staticmethod
    def _has_detached_trimmed_question_lead(
        *,
        original_clause: str,
        trimmed_clause: str,
    ) -> bool:
        original = LiveBrainService._normalize_text(original_clause)
        trimmed = LiveBrainService._normalize_text(trimmed_clause)
        if not original or not trimmed or original == trimmed:
            return False

        lead_index = original.lower().find(trimmed.lower())
        if lead_index <= 0:
            return False

        prefix = original[:lead_index]
        lowered_prefix = prefix.lower().strip()
        if any(phrase in lowered_prefix for phrase in _PREAMBLE_PHRASES):
            return False
        if any(lowered_prefix.startswith(start.strip()) for start in _FILLER_STARTS):
            return False
        if any(lowered_prefix.startswith(prefix_start) for prefix_start in _REQUEST_INTENT_LEADS):
            return False
        prefix_tokens = re.findall(r"[a-z0-9']+", prefix.lower())
        return len(prefix_tokens) > 4

    def _is_actionable_request_frame(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        lowered = normalized.lower()
        if not lowered:
            return False
        if (
            self._looks_like_supporting_interviewer_context(normalized)
            and not any(lowered.startswith(prefix) for prefix in _REQUEST_INTENT_LEADS)
            and not self._looks_like_intro_request(normalized)
        ):
            return False
        if self._looks_like_intro_request(normalized):
            return True
        if any(lowered.startswith(prefix) for prefix in _REQUEST_INTENT_LEADS):
            return True
        return self._looks_like_question_clause(normalized) and self._has_interrogative_structure(normalized)

    @staticmethod
    def _has_embedded_explicit_request(text: str) -> bool:
        normalized = LiveBrainService._normalize_text(text)
        lowered = normalized.lower()
        if not lowered:
            return False
        candidates = LiveBrainService._split_embedded_question_candidates(normalized)
        if len(candidates) <= 1:
            return False
        for candidate in candidates[1:]:
            canonical = LiveBrainService._canonicalize_safe_ask_text(
                LiveBrainService._trim_to_question_lead(LiveBrainService._normalize_text(candidate)).strip(" ,")
            )
            lowered_candidate = canonical.lower()
            if not lowered_candidate:
                continue
            if LiveBrainService._looks_like_intro_request(canonical):
                return True
            if any(lowered_candidate.startswith(prefix) for prefix in _REQUEST_INTENT_LEADS):
                return True
            if lowered_candidate.startswith(
                (
                    "what's ",
                    "what are ",
                    "what do ",
                    "what kind ",
                    "how do ",
                    "how are ",
                    "how big ",
                    "how many ",
                    "how much ",
                    "how long ",
                    "why ",
                )
            ):
                return True
        return False

    @staticmethod
    def _looks_like_supporting_interviewer_context(text: str) -> bool:
        lowered = LiveBrainService._normalize_text(text).lower()
        if not lowered:
            return False
        return any(term in lowered for term in _INTERVIEWER_ROLE_BRIEF_TERMS)

    @staticmethod
    def _looks_like_interviewer_self_context(text: str) -> bool:
        lowered = LiveBrainService._normalize_text(text).lower()
        if not lowered:
            return False
        return any(term in lowered for term in _INTERVIEWER_SELF_CONTEXT_TERMS)

    @staticmethod
    def _looks_like_meta_handoff_clause(text: str) -> bool:
        lowered = LiveBrainService._normalize_text(text).lower()
        if not lowered:
            return False
        return any(term in lowered for term in _INTERVIEWER_META_TERMS)

    def _pick_best_clear_ask(self, asks: list[str]) -> str:
        best = ""
        best_score = float("-inf")
        for ask in reversed(list(asks or [])):
            score = self._question_clause_score(ask)
            if self._is_complete_question_clause(ask):
                score += 1.0
            if score > best_score:
                best_score = score
                best = ask
        return best if best_score >= 2.0 else ""

    def _extract_coverage_points(self, asks: list[str]) -> list[str]:
        points: list[str] = []
        seen: set[str] = set()
        for ask in list(asks or []):
            for point in self._extract_coverage_points_from_text(ask):
                lowered = point.lower()
                if lowered in seen:
                    continue
                seen.add(lowered)
                points.append(point)
        return points[:4]

    def _extract_coverage_points_from_text(self, text: str) -> list[str]:
        normalized = self._normalize_text(text).rstrip("?.!")
        if self._looks_like_intro_request(normalized):
            return []
        lowered = normalized.lower()
        segment = ""
        for marker in _COVERAGE_MARKERS:
            token = f"{marker} "
            idx = lowered.find(token)
            if idx >= 0:
                segment = normalized[idx + len(token):]
                break
        if not segment and "looking for " in lowered:
            idx = lowered.find("looking for ")
            segment = normalized[idx + len("looking for "):]
        if not segment:
            return []

        segment = re.split(
            r"\b(?:what's|what is|which|who|why|how|don't like|do not like|avoid)\b",
            segment,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        candidates = re.split(r",|/|\band\b", segment)
        points: list[str] = []
        for candidate in candidates:
            cleaned = self._normalize_text(candidate).strip(" ,.;:-")
            cleaned = re.sub(r"^(?:in|for|on|around|about|regarding|across|with)\s+", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"^(the|a|an|your|their|our)\s+", "", cleaned, flags=re.IGNORECASE)
            if not cleaned:
                continue
            tokens = re.findall(r"[a-z0-9']+", cleaned.lower())
            if not tokens:
                continue
            filtered_tokens = [token for token in tokens if token not in _COVERAGE_STOPWORDS]
            if (
                not filtered_tokens
                or len(filtered_tokens) > 5
                or filtered_tokens[0] in _COVERAGE_LEADING_NOISE_TOKENS
                or all(token in _COVERAGE_REJECT_TOKENS for token in filtered_tokens)
            ):
                continue
            points.append(" ".join(filtered_tokens))
        return points

    def _select_safe_resolved_question(
        self,
        *,
        raw_detected_asks: list[str],
        snapshot_text: str,
        clause_classifications: Optional[list[dict[str, Any]]] = None,
    ) -> str:
        best_clear = self._pick_best_clear_ask(raw_detected_asks)
        if best_clear and not self._looks_like_meta_handoff_clause(best_clear):
            return best_clear
        normalized_classifications = list(clause_classifications or [])
        if not normalized_classifications:
            clauses = self._merge_question_continuations(self._split_candidate_clauses(snapshot_text))
            for index, clause in enumerate(clauses):
                normalized_clause = self._normalize_text(clause)
                if not normalized_clause:
                    continue
                normalized_classifications.append(
                    {
                        "text": normalized_clause,
                        "function": self._classify_clause_function(
                            clause=normalized_clause,
                            index=index,
                            total=len(clauses),
                        ),
                        "generated_asks": [],
                    }
                )

        for record in reversed(normalized_classifications):
            if self._normalize_text(record.get("function")) != "actionable_ask":
                continue

            generated_asks = [
                self._normalize_text(item)
                for item in list(record.get("generated_asks") or [])
                if self._normalize_text(item)
            ]
            for generated in reversed(generated_asks):
                if not self._looks_like_meta_handoff_clause(generated) and self._is_complete_question_clause(generated):
                    return generated

            normalized = self._canonicalize_safe_ask_text(
                self._trim_to_question_lead(self._normalize_text(record.get("text"))).strip(" ,")
            )
            if (
                normalized
                and not self._looks_like_meta_handoff_clause(normalized)
                and self._looks_like_question_clause(normalized)
                and self._is_complete_question_clause(normalized)
            ):
                return normalized
        return ""

    @staticmethod
    def _split_candidate_clauses(text: str) -> list[str]:
        normalized = str(text or "").replace("\r", "\n")
        clauses: list[str] = []
        for line in normalized.splitlines():
            line = " ".join(line.split()).strip()
            if not line:
                continue
            sentence_parts = [
                part.strip()
                for part in re.findall(r"[^?.!]+[?.!]?", line)
                if part and part.strip()
            ]
            for part in sentence_parts:
                clauses.append(part.strip())
        return clauses

    @staticmethod
    def _split_embedded_question_candidates(text: str) -> list[str]:
        normalized = LiveBrainService._normalize_text(text)
        if not normalized:
            return []

        lowered = normalized.lower()
        split_points: list[int] = [0]
        matches: list[tuple[int, str]] = []
        for lead in sorted(_ALL_QUESTION_LIKE_LEADS, key=len, reverse=True):
            for match in re.finditer(rf"(?<![a-z0-9]){re.escape(lead)}", lowered):
                start = match.start()
                if start <= 0:
                    continue
                matches.append((start, lead))

        for start, lead in sorted(matches, key=lambda item: item[0]):
            if start in split_points:
                continue
            if not LiveBrainService._should_split_at_question_lead(
                lowered_text=lowered,
                split_points=split_points,
                start=start,
                lead=lead,
            ):
                continue
            split_points.append(start)

        split_points = sorted(set(split_points))
        if len(split_points) == 1:
            return [normalized]

        clauses: list[str] = []
        for index, start in enumerate(split_points):
            end = split_points[index + 1] if index + 1 < len(split_points) else len(normalized)
            clause = normalized[start:end].strip(" ,")
            if clause:
                clauses.append(clause)
        return clauses or [normalized]

    def _expand_enumerated_follow_up_candidates(self, text: str) -> list[str]:
        normalized = self._normalize_text(text)
        lowered = normalized.lower()
        if not lowered.startswith("also cover "):
            return []

        body = normalized[len("also cover ") :].strip(" ,")
        if not body:
            return []

        raw_parts = [
            self._normalize_text(part).strip(" ,")
            for part in re.split(r",\s*", body)
            if self._normalize_text(part).strip(" ,")
        ]
        if not raw_parts:
            return []

        expanded: list[str] = []
        first_part = raw_parts[0]
        first_candidate = self._canonicalize_safe_ask_text(f"Tell me about {first_part}")
        first_candidate = self._ensure_terminal_punctuation(first_candidate)
        if first_candidate:
            expanded.append(first_candidate)

        for part in raw_parts[1:]:
            cleaned = re.sub(r"^(?:and|or)\s+", "", part, flags=re.IGNORECASE).strip(" ,")
            if not cleaned:
                continue
            if any(cleaned.lower().startswith(prefix) for prefix in _ALL_QUESTION_LIKE_LEADS):
                candidate = cleaned
            elif re.match(r"^(?:what|how|why|when|where|who|which)\b", cleaned, flags=re.IGNORECASE):
                candidate = cleaned
            else:
                candidate = f"Tell me about {cleaned}"
            candidate = self._canonicalize_safe_ask_text(candidate)
            candidate = self._ensure_terminal_punctuation(candidate)
            if candidate:
                expanded.append(candidate)

        return self._normalize_unique_strings(expanded)

    @staticmethod
    def _should_split_at_question_lead(
        *,
        lowered_text: str,
        split_points: list[int],
        start: int,
        lead: str,
    ) -> bool:
        prefix = lowered_text[:start].rstrip()
        if not prefix:
            return False

        prefix_tokens = re.findall(r"[a-z0-9']+", prefix)
        if not prefix_tokens:
            return False

        immediate_prev = prefix_tokens[-1]
        if immediate_prev in {"or", "and"}:
            return False
        if immediate_prev in {"what", "how", "why", "when", "where", "who", "which"}:
            return False

        request_prefix = any(
            prefix.strip().startswith(existing)
            for existing in _REQUEST_INTENT_LEADS
        )
        if (
            request_prefix
            and lead in {"what", "how", "why", "when", "where", "who", "which"}
            and not prefix.rstrip().endswith(("?", ".", "!"))
            and immediate_prev not in _QUESTION_SPLIT_CONNECTORS
        ):
            return False

        has_prior_question_lead = any(
            re.search(rf"(?<![a-z0-9]){re.escape(existing)}", prefix)
            for existing in _ALL_QUESTION_LIKE_LEADS
        )
        if has_prior_question_lead:
            return True

        if len(split_points) > 1:
            return True

        if immediate_prev in _QUESTION_SPLIT_CONNECTORS:
            return True

        if lead in _REQUEST_INTENT_LEADS and len(prefix_tokens) >= 4:
            return True

        return False

    def _merge_question_continuations(self, clauses: list[str]) -> list[str]:
        merged: list[str] = []
        idx = 0
        while idx < len(clauses):
            current = self._normalize_text(clauses[idx])
            if not current:
                idx += 1
                continue
            current = self._trim_to_question_lead(current)
            while idx + 1 < len(clauses):
                nxt = self._normalize_text(clauses[idx + 1])
                if not self._should_merge_question_continuation(current, nxt):
                    break
                current = self._merge_clauses(current, nxt)
                idx += 1
            merged.append(current)
            idx += 1
        return merged

    def _should_merge_question_continuation(self, current: str, nxt: str) -> bool:
        current_normalized = self._trim_to_question_lead(self._normalize_text(current))
        next_normalized = self._normalize_text(nxt)
        if not current_normalized or not next_normalized:
            return False
        if not self._looks_like_question_clause(current_normalized):
            return False
        lowered_next = next_normalized.lower()
        current_tokens = re.findall(r"[a-z0-9']+", current_normalized.lower())
        if lowered_next.startswith(("or ", "and ")) and len(current_tokens) <= 10:
            return True
        if (
            not current_normalized.endswith(("?", ".", "!"))
            and lowered_next.startswith(("or ", "and "))
            and len(current_tokens) <= 6
        ):
            return True
        first_token_match = re.findall(r"[a-z0-9']+", lowered_next)
        first_token = first_token_match[0] if first_token_match else ""
        if (
            current_normalized.rstrip().endswith(",")
            and first_token in {"what", "how", "which", "who", "where", "when"}
            and any(current_normalized.lower().startswith(prefix) for prefix in _REQUEST_INTENT_LEADS)
        ):
            return True
        if self._is_complete_question_clause(current_normalized) and not lowered_next.startswith(("or ", "and ")):
            return False
        if not self._has_open_tail(current_normalized) and current_normalized.endswith(("?", ".", "!")):
            return False
        next_trimmed = self._trim_to_question_lead(next_normalized)
        if next_trimmed == next_normalized and self._looks_like_question_clause(next_trimmed):
            return False
        if any(phrase in lowered_next for phrase in _PREAMBLE_PHRASES):
            return False
        if not first_token_match:
            return False
        if first_token in _DANGLING_ENDS:
            return True
        if next_normalized.endswith(("?", ".")):
            return True
        return next_normalized[:1].islower()

    @staticmethod
    def _asks_semantically_overlap(left: str, right: str) -> bool:
        normalized_left = re.sub(r"[^\w\s']+", "", LiveBrainService._normalize_text(left).lower()).strip()
        normalized_right = re.sub(r"[^\w\s']+", "", LiveBrainService._normalize_text(right).lower()).strip()
        if not normalized_left or not normalized_right:
            return False
        return (
            normalized_left == normalized_right
            or normalized_left in normalized_right
            or normalized_right in normalized_left
        )

    @staticmethod
    def _looks_like_relative_clause_fragment(text: str) -> bool:
        normalized = LiveBrainService._normalize_text(text)
        lowered = normalized.lower()
        if not lowered or lowered.endswith("?"):
            return False
        tokens = re.findall(r"[a-z0-9']+", lowered)
        if len(tokens) < 4 or tokens[0] not in {"who", "which", "that"}:
            return False
        if any(lowered.startswith(prefix) for prefix in _REQUEST_INTENT_LEADS):
            return False
        return any(token in {"has", "have", "had", "is", "are", "was", "were", "does", "did"} for token in tokens[1:4])

    def _infer_safe_strategy(
        self,
        *,
        asks: list[str],
        coverage_points: list[str],
        resolved_question: str,
        question_completeness: str,
        context_focus: list[str],
        style_hint: str,
    ) -> dict[str, Any]:
        if question_completeness != "complete" and not list(asks or []) and not self._normalize_text(resolved_question):
            return {
                "question_type": "direct",
                "response_shape": "direct_short",
                "answer_contract": "general_direct",
                "delivery_instructions": [
                    "Do not answer a self-answered meta prompt or an incomplete tail.",
                    "Wait for a clearer actionable interviewer question before giving a substantive answer.",
                    "Keep any fallback notice brief and natural.",
                ],
                "tone": "concise",
                "directness": "direct",
                "evidence_depth": "light",
                "metrics_policy": "avoid_unless_helpful",
                "company_context_policy": "avoid",
                "candidate_context_policy": "avoid",
                "ordered_coverage_required": False,
                "target_length": 90,
            }

        seed = " ".join(
            [
                resolved_question or "",
                *list(asks or []),
                *list(coverage_points or []),
                *list(context_focus or []),
            ]
        ).lower()
        is_technical = any(term in seed for term in _TECHNICAL_SIGNAL_TERMS)
        is_strategic = any(term in seed for term in _STRATEGIC_SIGNAL_TERMS)
        requires_metrics = any(term in seed for term in _METRIC_SIGNAL_TERMS)
        is_preference = any(term in seed for term in _PREFERENCE_SIGNAL_TERMS)
        asks_candidate_background = self._asks_need_candidate_background(asks=asks, resolved_question=resolved_question)
        is_multi_focus = len(list(asks or [])) > 1 or len(list(coverage_points or [])) > 1
        has_contextual_intro = (
            asks_candidate_background
            and bool(context_focus)
            and (
                any(self._looks_like_intro_request(ask) for ask in list(asks or []))
                or self._looks_like_intro_request(resolved_question)
            )
        )

        response_shape = "direct_short"
        if has_contextual_intro:
            response_shape = "direct_structured"
        elif is_technical:
            response_shape = "technical_explainer"
        elif is_strategic:
            response_shape = "strategic_explainer"
        elif is_multi_focus:
            response_shape = "direct_structured"

        evidence_depth = "light"
        if has_contextual_intro:
            evidence_depth = "medium"
        elif is_technical:
            evidence_depth = "deep"
        elif is_strategic or is_multi_focus:
            evidence_depth = "medium"

        target_length = 100
        if response_shape == "direct_structured":
            target_length = 190 if is_preference else 170
        elif response_shape in {"technical_explainer", "strategic_explainer"}:
            target_length = 190
        normalized_style_hint = self._normalize_text(style_hint).lower()
        if normalized_style_hint == "concise":
            target_length = min(target_length, 120 if response_shape == "direct_short" else 150)
        elif normalized_style_hint == "detailed":
            target_length = max(target_length, 210)
        elif normalized_style_hint in {"professional", "executive"}:
            target_length = max(target_length, 140 if response_shape == "direct_short" else 170)
        if has_contextual_intro:
            target_length = max(target_length, 170)

        directness = "direct" if response_shape == "direct_short" else "balanced"
        question_type = "direct"
        if has_contextual_intro and (is_technical or is_strategic):
            question_type = "mixed"
        elif is_technical and is_strategic:
            question_type = "mixed"
        elif is_technical:
            question_type = "technical"
        elif is_strategic:
            question_type = "business"
        elif is_preference:
            question_type = "direct"
        elif asks_candidate_background:
            question_type = "behavioral"
        elif is_multi_focus:
            question_type = "mixed"

        tone = "concise"
        if has_contextual_intro:
            tone = "professional"
        elif response_shape == "technical_explainer":
            tone = "technical"
        elif response_shape == "strategic_explainer":
            tone = "executive"
        elif is_multi_focus or is_preference:
            tone = "professional"
        elif directness == "balanced":
            tone = "balanced"
        company_context_policy = "support_if_relevant"
        candidate_context_policy = "required" if asks_candidate_background else "support_if_relevant"
        if is_preference and not asks_candidate_background:
            candidate_context_policy = "avoid"
        if question_type == "direct" and not asks_candidate_background and not is_technical and not is_strategic:
            candidate_context_policy = "avoid"
        if is_technical and not is_multi_focus:
            company_context_policy = "avoid"
        metrics_policy = "required" if requires_metrics else ("prefer_if_supported" if is_strategic else "avoid_unless_helpful")
        answer_contract = self._derive_answer_contract(
            question_type=question_type,
            response_shape=response_shape,
            asks=asks,
            coverage_points=coverage_points,
        )
        delivery_instructions = self._build_delivery_instructions(
            answer_contract=answer_contract,
            question_type=question_type,
            response_shape=response_shape,
            asks=asks,
            coverage_points=coverage_points,
            style_hint=normalized_style_hint,
            candidate_context_policy=candidate_context_policy,
            metrics_policy=metrics_policy,
        )

        return {
            "question_type": question_type,
            "response_shape": response_shape,
            "answer_contract": answer_contract,
            "delivery_instructions": delivery_instructions,
            "tone": tone,
            "directness": directness,
            "evidence_depth": evidence_depth,
            "metrics_policy": metrics_policy,
            "company_context_policy": company_context_policy,
            "candidate_context_policy": candidate_context_policy,
            "ordered_coverage_required": bool(
                question_completeness == "complete" and is_multi_focus
            ),
            "target_length": target_length,
        }

    def _derive_response_family(
        self,
        *,
        asks: list[str],
        coverage_points: list[str],
        resolved_question: str,
        question_type: str,
        answer_contract: str,
    ) -> str:
        seed = " ".join([resolved_question or "", *list(asks or []), *list(coverage_points or [])]).lower()
        has_intro = any(self._looks_like_intro_request(ask) for ask in asks) or self._looks_like_intro_request(resolved_question)
        has_build = any(
            phrase in seed
            for phrase in (
                "build from 0",
                "build from zero",
                "building from 0",
                "building from zero",
                "build from scratch",
                "building from scratch",
                "from scratch",
                "from the ground up",
                "early stages",
                "founded",
                "founded a",
            )
        )
        has_leadership = any(
            phrase in seed
            for phrase in (
                "team management",
                "team experience",
                "teams you've managed",
                "teams you have managed",
                "how big were the teams",
                "what roles did they have",
                "roles did they have",
                "direct reports",
                "indirect reports",
                "lead our teams",
                "leadership",
            )
        )
        has_culture = answer_contract == "preferences_and_anti_patterns" or any(
            phrase in seed
            for phrase in (
                "company",
                "culture",
                "what matters",
                "what's important",
                "important for you",
                "don't like",
                "do not like",
                "absolutely like",
                "absolutely don't like",
                "looking for",
                "what are you looking for",
            )
        )
        has_technical = question_type == "technical" or answer_contract == "architecture_walkthrough"

        if has_culture:
            return "culture_preferences"
        if len(list(asks or [])) > 1 and (has_build or has_leadership or has_intro):
            return "mixed_multi_part"
        if has_technical and not has_intro:
            return "technical_fit"
        if has_intro:
            return "intro_alignment" if not (has_build or has_leadership) else "mixed_multi_part"
        if has_leadership and not has_build:
            return "leadership_scope"
        if has_build:
            return "behavioral_story"
        if has_technical:
            return "technical_fit"
        if question_type in {"behavioral", "business"}:
            return "behavioral_story"
        return "mixed_multi_part" if len(list(asks or [])) > 1 else "intro_alignment"

    def _derive_alignment_brief(
        self,
        *,
        supporting_interviewer_context: list[str],
        response_family: str,
    ) -> list[str]:
        lowered = " ".join(self._normalize_text(item).lower() for item in list(supporting_interviewer_context or []))
        brief: list[str] = []
        if any(term in lowered for term in ("ai", "llm", "llms", "agent", "agents", "vector", "vectors", "graph", "graphs", "knowledge")):
            brief.append("AI-ready data foundations for LLM and agent use cases")
        if any(term in lowered for term in ("aws", "cloud", "infrastructure", "platform", "architecture", "design")):
            brief.append("cloud and data platform architecture leadership")
        if any(term in lowered for term in ("lead", "leadership", "teams", "build", "delivery", "operating")):
            brief.append("technical leadership and delivery direction")
        if response_family == "culture_preferences" and any(term in lowered for term in ("culture", "team", "collaboration", "ownership")):
            brief.append("team culture and working style alignment")
        return self._normalize_unique_strings(brief)[:3]

    def _build_quality_guardrails(
        self,
        *,
        asks: list[str],
        response_family: str,
        metrics_policy: str,
        candidate_context_policy: str,
    ) -> list[str]:
        guardrails = ["direct_first_sentence", "preserve_ask_order"]
        if metrics_policy != "required":
            guardrails.append("avoid_unsupported_metrics")
        if candidate_context_policy == "avoid" or response_family in {"culture_preferences", "technical_fit"}:
            guardrails.append("avoid_biography")
        if response_family == "intro_alignment":
            guardrails.extend(["avoid_generic_company_pitch", "avoid_unframed_fit_close"])
        if response_family == "mixed_multi_part" and any(self._looks_like_intro_request(ask) for ask in asks[1:]):
            guardrails.append("intro_subordinate_to_specific_asks")
        if response_family == "culture_preferences":
            guardrails.append("avoid_achievement_dump")
        return self._normalize_unique_strings(guardrails)[:6]

    def _build_answer_blueprint(
        self,
        *,
        asks: list[str],
        response_family: str,
        alignment_brief: list[str],
        question_type: str,
        metrics_policy: str,
    ) -> list[dict[str, Any]]:
        normalized_asks = [self._normalize_text(ask) for ask in list(asks or []) if self._normalize_text(ask)]
        if response_family == "intro_alignment":
            blueprint = [
                self._make_blueprint_segment(
                    purpose="profile_core",
                    ask_refs=normalized_asks[:1],
                    required_elements=[
                        "strongest matching proof from the profile",
                        "why that proof maps to the interviewer problem",
                        "current role only as orientation",
                    ],
                    preferred_evidence_types=["build_evidence", "leadership_evidence", "technical_alignment_evidence", "role_evidence"],
                    avoid_topics=["generic_company_pitch", "unsupported_metrics"],
                    target_sentence_count=2,
                ),
                self._make_blueprint_segment(
                    purpose="alignment",
                    ask_refs=normalized_asks[:1],
                    required_elements=self._normalize_unique_strings(
                        [
                            "leadership scope",
                            "how that scope lets the candidate set direction and guide the teams building it",
                            *list(alignment_brief or []),
                        ]
                    )[:3],
                    preferred_evidence_types=["leadership_evidence", "technical_alignment_evidence", "build_evidence"],
                    avoid_topics=["strong_fit_claim_without_fit_ask"],
                    target_sentence_count=1,
                ),
            ]
            return blueprint
        if response_family == "culture_preferences":
            return [
                self._make_blueprint_segment(
                    purpose="preferences_company_culture_team",
                    ask_refs=normalized_asks[:2],
                    required_elements=["company preferences", "culture preferences", "team preferences"],
                    preferred_evidence_types=["culture_alignment_evidence"],
                    avoid_topics=["career_biography", "unsupported_metrics"],
                    target_sentence_count=2,
                ),
                self._make_blueprint_segment(
                    purpose="preferences_boundaries",
                    ask_refs=normalized_asks[2:] or normalized_asks[-1:],
                    required_elements=["what to like or avoid"],
                    preferred_evidence_types=["culture_alignment_evidence"],
                    avoid_topics=["achievement_dump"],
                    target_sentence_count=1,
                ),
            ]
        if response_family == "technical_fit":
            return [
                self._make_blueprint_segment(
                    purpose="technical_positioning",
                    ask_refs=normalized_asks[:1],
                    required_elements=["direct answer", "relevant architecture scope"],
                    preferred_evidence_types=["role_evidence", "technical_alignment_evidence"],
                    avoid_topics=["generic_profile_summary"],
                    target_sentence_count=1,
                ),
                self._make_blueprint_segment(
                    purpose="technical_approach",
                    ask_refs=normalized_asks[:1],
                    required_elements=["approach", "design considerations", "trade-offs"],
                    preferred_evidence_types=["technical_alignment_evidence", "build_evidence"],
                    avoid_topics=["unsupported_metrics"],
                    target_sentence_count=2,
                ),
            ]

        blueprint: list[dict[str, Any]] = []
        for ask in normalized_asks:
            ask_lower = ask.lower()
            if self._looks_like_intro_request(ask):
                blueprint.append(
                    self._make_blueprint_segment(
                        purpose="intro_tail",
                        ask_refs=[ask],
                        required_elements=["brief positioning close anchored in the proof already given"],
                        preferred_evidence_types=["build_evidence", "leadership_evidence", "role_evidence"],
                        avoid_topics=["long_biography", "unsupported_metrics"],
                        target_sentence_count=1,
                    )
                )
            elif any(term in ask_lower for term in ("roles did they have", "what roles did they have", "what roles they have")):
                blueprint.append(
                    self._make_blueprint_segment(
                        purpose="team_composition",
                        ask_refs=[ask],
                        required_elements=["team roles and composition"],
                        preferred_evidence_types=["team_scope_evidence", "leadership_evidence"],
                        avoid_topics=["generic_profile_summary"],
                        target_sentence_count=1,
                    )
                )
            elif any(term in ask_lower for term in ("how big were the teams", "team management", "teams you've managed", "team experience")):
                blueprint.append(
                    self._make_blueprint_segment(
                        purpose="leadership_scope",
                        ask_refs=[ask],
                        required_elements=["leadership scope", "team scale", "operating model or outcomes"],
                        preferred_evidence_types=["leadership_evidence", "team_scope_evidence"],
                        avoid_topics=["unsupported_metrics" if metrics_policy != "required" else ""],
                        target_sentence_count=2,
                    )
                )
            else:
                blueprint.append(
                    self._make_blueprint_segment(
                        purpose="build_or_experience",
                        ask_refs=[ask],
                        required_elements=["concrete example", "what you built or led", "ownership", "outcome"],
                        preferred_evidence_types=["build_evidence", "role_evidence"],
                        avoid_topics=["generic_modernization_summary"],
                        target_sentence_count=2,
                    )
                )
        if not blueprint:
            blueprint.append(
                self._make_blueprint_segment(
                    purpose="direct_answer",
                    ask_refs=normalized_asks[:1],
                    required_elements=["direct answer"],
                    preferred_evidence_types=["role_evidence"],
                    avoid_topics=["unsupported_metrics"],
                    target_sentence_count=2,
                )
            )
        return blueprint[:5]

    @staticmethod
    def _make_blueprint_segment(
        *,
        purpose: str,
        ask_refs: list[str],
        required_elements: list[str],
        preferred_evidence_types: list[str],
        avoid_topics: list[str],
        target_sentence_count: int,
    ) -> dict[str, Any]:
        return {
            "purpose": purpose,
            "ask_refs": [item for item in ask_refs if item],
            "required_elements": [item for item in required_elements if item],
            "preferred_evidence_types": [item for item in preferred_evidence_types if item],
            "avoid_topics": [item for item in avoid_topics if item],
            "target_sentence_count": max(1, int(target_sentence_count or 1)),
        }

    @staticmethod
    def _merge_clauses(left: str, right: str) -> str:
        merged = f"{LiveBrainService._normalize_text(left).rstrip(' ,.;:')} {LiveBrainService._normalize_text(right).lstrip(' ,.;:')}"
        return LiveBrainService._normalize_text(merged)

    @staticmethod
    def _trim_to_question_lead(text: str) -> str:
        normalized = LiveBrainService._normalize_text(text)
        lowered = normalized.lower()
        if any(lowered.startswith(prefix) for prefix in _ALL_QUESTION_LIKE_LEADS):
            return normalized

        best_pos: Optional[int] = None
        for prefix in _ALL_QUESTION_LIKE_LEADS:
            match = re.search(rf"(?<![a-z0-9]){re.escape(prefix)}", lowered)
            if match is None:
                continue
            if best_pos is None or match.start() < best_pos:
                best_pos = match.start()

        if best_pos is None or best_pos <= 0:
            return normalized

        prefix_text = lowered[:best_pos]
        if any(prefix_text.strip().startswith(prefix_start) for prefix_start in _REQUEST_INTENT_LEADS):
            return normalized
        noisy_prefix = (
            any(phrase in prefix_text for phrase in _PREAMBLE_PHRASES)
            or any(prefix_text.strip().startswith(start.strip()) for start in _FILLER_STARTS)
            or "," in prefix_text
        )
        if not noisy_prefix:
            return normalized
        return normalized[best_pos:].strip(" ,")

    @staticmethod
    def _has_open_tail(text: str) -> bool:
        tokens = re.findall(r"[a-z0-9']+", LiveBrainService._normalize_text(text).lower())
        if not tokens:
            return False
        return LiveBrainService._last_token_is_dangling(tokens)

    @staticmethod
    def _looks_like_question_clause(text: str) -> bool:
        lowered = " ".join(str(text or "").lower().split())
        return any(
            lowered.startswith(prefix) or f" {prefix}" in lowered
            for prefix in _ALL_QUESTION_LIKE_LEADS
        )

    @staticmethod
    def _question_clause_score(text: str) -> float:
        lowered = " ".join(str(text or "").lower().split())
        score = 0.0
        starts_with_request_intent = any(lowered.startswith(prefix) for prefix in _REQUEST_INTENT_LEADS)
        if any(lowered.startswith(prefix) for prefix in _ALL_QUESTION_LIKE_LEADS):
            score += 2.0
        elif any(f" {prefix}" in lowered for prefix in _ALL_QUESTION_LIKE_LEADS):
            score += 1.0
        if "?" in lowered:
            score += 1.0
        if any(lowered.startswith(prefix) for prefix in _FILLER_STARTS) and not starts_with_request_intent:
            score -= 1.25
        if any(phrase in lowered for phrase in _PREAMBLE_PHRASES):
            score -= 1.0
        if len(lowered.split()) < 5:
            score -= 0.5
        if not LiveBrainService._has_interrogative_structure(text):
            score -= 1.25
        if not LiveBrainService._is_complete_question_clause(text):
            score -= 1.0
        return score

    @staticmethod
    def _is_complete_question_clause(text: str) -> bool:
        normalized = " ".join(str(text or "").split()).strip()
        if not normalized:
            return False
        if normalized.endswith("?"):
            return LiveBrainService._has_interrogative_structure(normalized)
        if (
            normalized.endswith(".")
            and LiveBrainService._looks_like_question_clause(normalized)
            and LiveBrainService._has_interrogative_structure(normalized)
        ):
            return True
        last_token = re.findall(r"[a-z0-9']+", normalized.lower())
        if not last_token:
            return False
        if LiveBrainService._last_token_is_dangling(last_token):
            return False
        return (
            LiveBrainService._looks_like_question_clause(normalized)
            and LiveBrainService._has_interrogative_structure(normalized)
        )

    @staticmethod
    def _last_token_is_dangling(tokens: list[str]) -> bool:
        if not tokens:
            return False
        last_token = tokens[-1]
        if last_token != "like":
            return last_token in _DANGLING_ENDS
        if len(tokens) >= 2 and tokens[-2] in _NON_FILLER_LIKE_PREV_TOKENS:
            return False
        if len(tokens) >= 2 and tokens[-2] in _PREFERENCE_INTENSIFIERS:
            return False
        return True

    def _prune_low_priority_asks(self, asks: list[str]) -> list[str]:
        normalized_asks = [self._normalize_text(ask) for ask in list(asks or []) if self._normalize_text(ask)]
        if len(normalized_asks) <= 1:
            return normalized_asks
        last_index = len(normalized_asks) - 1
        specific = [
            ask
            for index, ask in enumerate(normalized_asks)
            if not self._looks_like_intro_request(ask) or index == last_index
        ]
        return specific or normalized_asks

    @staticmethod
    def _asks_need_candidate_background(*, asks: list[str], resolved_question: str) -> bool:
        if LiveBrainService._looks_like_intro_request(resolved_question):
            return True
        if any(LiveBrainService._looks_like_intro_request(ask) for ask in list(asks or [])):
            return True
        seed = " ".join([resolved_question or "", *list(asks or [])]).lower()
        return any(
            phrase in seed
            for phrase in (
                "tell me about yourself",
                "tell us about yourself",
                "tell me a bit about yourself",
                "tell us a bit about yourself",
                "little bit about you",
                "little bit about yourself",
                "your experience",
                "team management",
                "team experience",
                "teams you've managed",
                "what roles did they have",
                "roles did they have",
                "building from 0",
                "building from scratch",
                "example",
                "examples",
                "scope",
                "results",
                "led",
                "managed",
            )
        )

    @staticmethod
    def _has_interrogative_structure(text: str) -> bool:
        lowered = LiveBrainService._trim_to_question_lead(text).lower()
        if not lowered:
            return False
        direct_prefixes = (
            "tell us",
            "tell me",
            "describe",
            "explain",
            "walk us through",
            "walk me through",
            "start telling us",
            "start telling me",
            "give me a sense of",
            "give us a sense of",
            "help me understand",
            "can you",
            "could you",
            "would you",
            "do you",
            "are you",
            "is there",
        )
        if any(lowered.startswith(prefix) for prefix in direct_prefixes):
            return True
        if any(lowered.startswith(prefix) for prefix in _REQUEST_INTENT_LEADS):
            return True
        if any(lowered.startswith(prefix) for prefix in ("what's ", "how's ", "why's ", "who's ", "where's ", "when's ")):
            return True

        tokens = re.findall(r"[a-z0-9']+", lowered)
        if len(tokens) < 2:
            return False
        first, second = tokens[0], tokens[1]
        wh_words = {"what", "how", "why", "when", "where", "who", "which"}
        auxiliaries = {
            "is",
            "are",
            "am",
            "was",
            "were",
            "do",
            "does",
            "did",
            "have",
            "has",
            "had",
            "can",
            "could",
            "would",
            "should",
            "will",
            "kind",
            "kinds",
            "type",
            "types",
            "matters",
            "matter",
            "important",
        }
        pronouns = {"you", "we", "they", "he", "she", "i"}
        if first in wh_words:
            if second in pronouns:
                return lowered.endswith("?")
            if second in auxiliaries:
                return True
            if any(token in auxiliaries for token in tokens[1:4]):
                return True
            if lowered.endswith("?"):
                return True
            return False
        return True

    @staticmethod
    def _build_resolved_question(asks: list[str]) -> str:
        asks = [ask for ask in asks if ask]
        if not asks:
            return ""
        if len(asks) == 1:
            return asks[0]
        lines = ["Answer these interviewer asks in order:"]
        lines.extend(f"{idx}. {ask}" for idx, ask in enumerate(asks, start=1))
        return "\n".join(lines)

    @staticmethod
    def _looks_like_intro_request(text: str) -> bool:
        lowered = " ".join(str(text or "").lower().split())
        if not lowered:
            return False
        direct_patterns = (
            "tell me about yourself",
            "tell us about yourself",
            "walk me through your background",
            "start telling us",
            "start telling me",
            "little bit about you",
            "little bit about yourself",
            "quick intro",
            "brief intro",
        )
        if any(pattern in lowered for pattern in direct_patterns):
            return True
        return bool(
            re.search(
                r"\btell\s+(?:me|us)\s+(?:a\s+)?(?:little\s+)?bit\s+about\s+(?:you|yourself)\b",
                lowered,
            )
        )

    @staticmethod
    def _normalize_text(value: Any) -> str:
        return " ".join(str(value or "").split()).strip()

    @staticmethod
    def _canonicalize_safe_ask_text(text: str) -> str:
        normalized = LiveBrainService._normalize_text(text)
        if not normalized:
            return ""

        rewrites = (
            (
                r"^(?:start\s+telling\s+(?:us|me)(?:\s+or\s+telling\s+(?:us|me))?\s+a\s+little\s+bit\s+about\s+you)\b",
                "Tell me a little bit about you",
            ),
            (
                r"^(?:also\s+cover)\s+",
                "Tell me about ",
            ),
            (
                r"^(?:i\s+(?:(?:want\s+to)|wanna)\s+get\s+a\s+sense\s+of)\s+",
                "Tell me about ",
            ),
            (
                r"^(?:give\s+(?:me|us)\s+a\s+sense\s+of)\s+",
                "Tell me about ",
            ),
            (
                r"^(?:i'?m\s+curious\s+to\s+hear\s+about|i\s+am\s+curious\s+to\s+hear\s+about|very\s+curious\s+to\s+hear\s+about|curious\s+to\s+hear\s+about)\s+",
                "Tell me about ",
            ),
            (
                r"^(?:start\s+telling\s+(?:us|me)(?:\s+or\s+telling\s+(?:us|me))?)\s+",
                "Tell me about ",
            ),
        )
        for pattern, replacement in rewrites:
            rewritten = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)
            if rewritten != normalized:
                normalized = rewritten
                break
        deduped = normalized
        for _ in range(2):
            deduped = re.sub(
                r"\b(?P<phrase>[a-z][a-z0-9']*(?:\s+[a-z][a-z0-9']*){2,8})\s+(?P=phrase)\b",
                r"\g<phrase>",
                deduped,
                flags=re.IGNORECASE,
            )
        normalized = deduped
        normalized = re.sub(
            r"^tell me about a little bit about you\b",
            "Tell me a little bit about you",
            normalized,
            flags=re.IGNORECASE,
        )
        normalized = re.sub(
            r"\bhow big were the team\b(?:\s+big were the teams\b)?",
            "How big were the teams",
            normalized,
            flags=re.IGNORECASE,
        )
        normalized = re.sub(
            r"^how big the teams were\b",
            "How big were the teams",
            normalized,
            flags=re.IGNORECASE,
        )
        normalized = re.sub(
            r"^what roles they had\b",
            "What roles did they have",
            normalized,
            flags=re.IGNORECASE,
        )
        normalized = re.sub(
            r"^what roles they have\b",
            "What roles did they have",
            normalized,
            flags=re.IGNORECASE,
        )
        normalized = LiveBrainService._trim_recoverable_open_tail(normalized)
        normalized = re.sub(r"\balso very\b$", "", normalized, flags=re.IGNORECASE).strip(" ,")
        return LiveBrainService._normalize_text(normalized)

    @staticmethod
    def _trim_recoverable_open_tail(text: str) -> str:
        normalized = LiveBrainService._normalize_text(text)
        if not normalized or not LiveBrainService._has_open_tail(normalized):
            return normalized

        candidate = normalized
        for _ in range(3):
            tokens = re.findall(r"[a-z0-9']+", candidate.lower())
            if not tokens or not LiveBrainService._last_token_is_dangling(tokens):
                break
            if tokens[-1] not in _RECOVERABLE_OPEN_TAIL_TOKENS:
                break
            stripped = re.sub(r"[\s,;:-]*[a-z0-9']+[\s,;:-]*$", "", candidate, flags=re.IGNORECASE).strip(" ,;:-")
            if not stripped or stripped == candidate:
                break
            candidate = stripped
            if (
                LiveBrainService._looks_like_intro_request(candidate)
                or LiveBrainService._is_complete_question_clause(candidate)
            ):
                return candidate
        return normalized

    def _derive_question_type(self, *, ordered_asks: list[str], resolved_question: str) -> str:
        seed = " ".join([resolved_question or "", *list(ordered_asks or [])]).lower()
        has_technical = any(term in seed for term in _TECHNICAL_SIGNAL_TERMS)
        has_business = any(term in seed for term in _STRATEGIC_SIGNAL_TERMS)
        has_behavioral = any(term in seed for term in _PREFERENCE_SIGNAL_TERMS) or "experience" in seed
        kinds = sum(bool(flag) for flag in (has_technical, has_business, has_behavioral))
        if kinds > 1:
            return "mixed"
        if has_technical:
            return "technical"
        if has_business:
            return "business"
        if has_behavioral:
            return "behavioral"
        return "direct"

    def _derive_answer_contract(
        self,
        *,
        question_type: str,
        response_shape: str,
        asks: list[str],
        coverage_points: list[str],
    ) -> str:
        seed = " ".join([*list(asks or []), *list(coverage_points or [])]).lower()
        if question_type == "technical":
            return "architecture_walkthrough" if any(term in seed for term in ("architecture", "design", "system", "platform")) else "direct_explanation"
        if question_type in {"business", "behavioral"} and any(token in seed for token in ("outcome", "outcomes", "results", "impact", "experience", "led", "built")):
            return "business_with_outcomes"
        if any(self._looks_like_intro_request(ask) for ask in asks[1:]):
            return "follow_up_focused"
        if any(term in seed for term in ("looking for", "important to you", "important for you", "what matters", "avoid", "don't like", "do not like", "absolutely like")):
            return "preferences_and_anti_patterns"
        if len(list(asks or [])) > 1 or len(list(coverage_points or [])) > 1:
            return "direct_multi_part"
        return "general_direct"

    def _build_delivery_instructions(
        self,
        *,
        answer_contract: str,
        question_type: str,
        response_shape: str,
        asks: list[str],
        coverage_points: list[str],
        style_hint: str,
        candidate_context_policy: str,
        metrics_policy: str,
    ) -> list[str]:
        instructions: list[str] = ["Start with the direct answer in the first sentence."]
        if len(list(asks or [])) > 1:
            ordered = " | ".join(self._normalize_text(ask) for ask in asks[:4] if self._normalize_text(ask))
            if ordered:
                instructions.append(f"Answer the asks in this exact order: {ordered}")
        elif len(list(coverage_points or [])) > 1:
            focus = " | ".join(self._normalize_text(point) for point in coverage_points[:4] if self._normalize_text(point))
            if focus:
                instructions.append(f"Keep the structure visible across these focus areas: {focus}")
        if len(list(asks or [])) > 1 or len(list(coverage_points or [])) > 1:
            instructions.append("Format multi-part answers as short paragraphs separated by a blank line, without bullets or headings.")

        contract_rules = {
            "preferences_and_anti_patterns": "State what matters most by focus area, and include what to avoid only if it is explicitly asked.",
            "business_with_outcomes": "Use role, what you did, and the outcome or business impact in that order.",
            "architecture_walkthrough": "Use direct answer, then approach and trade-offs, then the result or practical takeaway.",
            "direct_explanation": "Explain the answer clearly without drifting into biography or generic company pitch.",
            "follow_up_focused": "Keep any broad intro request brief and subordinate to the more specific asks.",
            "direct_multi_part": "Use short transitions such as First, Second, and Finally so the structure is audible.",
            "general_direct": "Keep the answer direct, speakable, and tightly aligned to the current ask.",
        }
        rule = contract_rules.get(answer_contract)
        if rule:
            instructions.append(rule)

        if candidate_context_policy == "avoid":
            instructions.append("Do not add biography, years of experience, or profile summary unless the ask requires it.")
        if metrics_policy == "required":
            instructions.append("Include one concrete supported outcome or metric.")

        normalized_style = self._normalize_text(style_hint).lower()
        style_rules = {
            "concise": "Keep it concise: 3-5 sentences, no filler, no extra background.",
            "detailed": "Be detailed: 6-9 sentences with more explanation and reasoning.",
            "professional": "Keep it polished and structured, with visible transitions when the ask is multi-part.",
            "executive": "Take a position early and keep the rationale concise and outcome-oriented.",
        }
        instructions.append(style_rules.get(normalized_style, "Keep it polished, direct, and easy to say aloud."))
        return instructions[:6]

    def _derive_contextualized_question(
        self,
        *,
        literal_question: str,
        resolved_question: str,
        question_completeness: str,
        response_requirement: ResponseRequirement,
        interviewer_need: InterviewerNeed,
        alignment_brief: list[str],
        context_focus: list[str],
    ) -> str:
        literal = self._normalize_text(literal_question or resolved_question)
        if not literal:
            if str(question_completeness or "").strip().lower() in {"partial", "garbled"}:
                return (
                    "The latest actionable interviewer question was not captured clearly enough. "
                    "Do not answer a self-answered meta prompt or an incomplete tail."
                )
            return self._normalize_text(resolved_question)

        raw_focus_items = self._normalize_unique_strings(
            [
                *list(alignment_brief or []),
                *list(interviewer_need.dimensions or []),
                *list(response_requirement.context_to_weave or []),
                *list(context_focus or []),
            ]
        )
        focus_items = [
            item
            for item in raw_focus_items
        ]
        compact_focus = [
            self._compact_text(item, limit=96)
            for item in focus_items[:4]
            if self._normalize_text(item)
        ]
        if not compact_focus:
            return literal

        must_cover_items = self._normalize_unique_strings(list(response_requirement.must_cover or []))
        must_cover = [
            self._compact_text(item, limit=64)
            for item in must_cover_items[:3]
            if self._normalize_text(item)
        ]
        answer_mode = self._normalize_text(response_requirement.answer_mode).lower()
        focus_text = self._join_natural_phrases(compact_focus[:3])
        must_cover_text = self._join_natural_phrases(must_cover[:3])
        response_order = [
            self._normalize_text(item)
            for item in list(response_requirement.response_order or [])
            if self._normalize_text(item)
        ]
        evidence_priority = {
            self._normalize_text(item).lower()
            for item in list(response_requirement.evidence_priority or [])
            if self._normalize_text(item)
        }
        contract_seed = " ".join(
            [
                *list(response_requirement.required_moves or []),
                *list(response_requirement.paragraph_plan or []),
                *list(response_requirement.response_order or []),
            ]
        ).lower()
        focuses_on_build_from_zero = bool(
            "build_evidence" in evidence_priority
            or any("build from 0" in item.lower() or "build-from-zero" in item.lower() for item in response_order)
            or any("object built" in item.lower() for item in must_cover_items)
        )
        requests_multiple_examples = any(
            phrase in contract_seed
            for phrase in (
                "multiple examples clearly separated",
                "multiple examples",
                "examples clearly separated",
            )
        )

        if answer_mode == "profile_alignment":
            profile_focus = self._join_natural_phrases(
                [
                    item
                    for item in list(alignment_brief or [])[:3]
                    if self._normalize_text(item)
                ]
            ) or focus_text
            sentence = "Introduce yourself professionally in a way that maps your background to the interviewer problem"
            if profile_focus:
                sentence += f", especially around {profile_focus}"
            if response_requirement.prior_context_mode != "none" and focus_text:
                sentence += ". Use the prior interviewer context only to clarify the decision scope behind the introduction"
            sentence += ". Keep it as a profile answer, not a generic biography"
            return sentence.rstrip(".") + "."
        if focuses_on_build_from_zero and any("object built" in item.lower() for item in must_cover_items):
            lead_phrase = (
                "with clearly separated build-from-zero examples"
                if requests_multiple_examples
                else "by making the build-from-zero example"
            )
            sentence = f"Answer the build-from-zero ask {lead_phrase} explicit."
            sentence += " Make the object built, stage, ownership, and outcome explicit"
            if any("team scale and composition" in item.lower() for item in list(response_requirement.must_cover or [])):
                sentence += ". Then cover team scale and roles explicitly"
            return sentence.rstrip(".") + "."
        if answer_mode == "technical_walkthrough":
            return (
                f"Answer by focusing on {focus_text}, and make the key decisions, trade-offs, and practical outcomes explicit."
            )
        if answer_mode == "experience_with_outcomes":
            sentence = (
                f"Answer by focusing on {focus_text}, and use concrete experience, operating scope, and outcomes to prove credibility"
            )
            if must_cover_text:
                sentence += f", while making clear your {must_cover_text}"
            return sentence.rstrip(".") + "."
        if answer_mode == "preferences":
            sentence = f"Answer by focusing on the preference areas most relevant to {focus_text}"
            if must_cover_text:
                sentence += f", and make clear your {must_cover_text}"
            sentence += ". Keep the answer on stated preferences and boundaries rather than background recap"
            return sentence.rstrip(".") + "."
        sentence = f"Answer by focusing on {focus_text}"
        if must_cover_text:
            sentence += f", while making clear your {must_cover_text}"
        return sentence.rstrip(".") + "."

    @staticmethod
    def _join_natural_phrases(values: list[str]) -> str:
        items = [
            LiveBrainService._normalize_text(value)
            for value in list(values or [])
            if LiveBrainService._normalize_text(value)
        ]
        if not items:
            return ""
        if len(items) == 1:
            return items[0]
        if len(items) == 2:
            return f"{items[0]} and {items[1]}"
        return f"{', '.join(items[:-1])}, and {items[-1]}"

    @staticmethod
    def _looks_like_profile_evidence_anchor(text: str) -> bool:
        normalized = LiveBrainService._normalize_text(text).lower()
        if len(normalized.split()) < 6:
            return False
        return bool(
            re.search(
                r"^(?:built|building|founded|created|designed|launched|led|managed|scaled|developed|delivered|improved|owned|co-led|consolidated|translated|standardized|expanded)\b",
                normalized,
            )
        )

    @staticmethod
    def _looks_like_genesis_anchor(text: str) -> bool:
        normalized = LiveBrainService._normalize_text(text).lower()
        if len(normalized.split()) < 6:
            return False
        return bool(
            re.search(
                r"^(?:built|building|founded|created|co-created|launched|established|started|opened)\b",
                normalized,
            )
        )

    @staticmethod
    def _derive_tone(*, question_type: str, response_shape: str) -> str:
        if response_shape == "technical_explainer" or question_type == "technical":
            return "technical"
        if response_shape == "strategic_explainer" or question_type == "business":
            return "executive"
        if response_shape == "direct_short":
            return "concise"
        if question_type in {"behavioral", "mixed"}:
            return "professional"
        return "balanced"

    @staticmethod
    def _tone_to_directness(tone: str) -> str:
        if tone == "concise":
            return "direct"
        if tone == "technical":
            return "detailed"
        return "balanced"

    @staticmethod
    def _candidate_context_policy_from_flag(*, enabled: Any, question_type: str, asks: list[str]) -> str:
        if enabled is False:
            return "avoid"
        asks_text = " ".join(LiveBrainService._normalize_text(ask) for ask in list(asks or []))
        needs_background = LiveBrainService._asks_need_candidate_background(
            asks=asks,
            resolved_question=asks_text,
        )
        if enabled is True and needs_background:
            return "required"
        if needs_background or question_type in {"behavioral", "business", "technical", "mixed"}:
            return "support_if_relevant"
        return "avoid"

    def _derive_serve_mode(
        self,
        *,
        question_completeness: str,
        draft_answer: str,
        confidence: float,
        response_shape: str,
        ask_count: int,
        coverage_count: int,
    ) -> str:
        if draft_answer:
            return "finalize_from_draft"
        return "finalize_from_plan"

    @staticmethod
    def _normalize_choice(value: Any, allowed: set[str], default: str) -> str:
        normalized = " ".join(str(value or "").split()).strip().lower()
        return normalized if normalized in allowed else default

    @staticmethod
    def _normalize_unique_strings(values: list[Any]) -> list[str]:
        unique: list[str] = []
        seen: set[str] = set()
        for value in list(values or []):
            normalized = LiveBrainService._normalize_text(value)
            if not normalized:
                continue
            lowered = normalized.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            unique.append(normalized)
        return unique

    @staticmethod
    def _extract_json_payload(raw_text: str) -> str:
        text = LiveBrainService._strip_code_fences(str(raw_text or "").strip())
        if not text:
            return ""
        if text.startswith("{") and text.endswith("}"):
            return text
        balanced = LiveBrainService._extract_balanced_json_object(text)
        if balanced:
            return balanced
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        return match.group(0) if match else ""

    @classmethod
    def _parse_llm_payload(cls, raw_text: str) -> tuple[Optional[dict[str, Any]], str]:
        text = cls._strip_code_fences(str(raw_text or "").strip())
        if not text:
            return None, "json_not_found"

        payload = cls._extract_json_payload(text)
        if not payload:
            return None, "json_not_found"

        parsed = cls._parse_with_json(payload)
        if isinstance(parsed, dict):
            return cls._to_json_compatible(parsed), ""

        repaired = cls._repair_json_candidate(payload)
        if repaired and repaired != payload:
            parsed = cls._parse_with_json(repaired)
            if isinstance(parsed, dict):
                return cls._to_json_compatible(parsed), ""
        line_based = cls._parse_line_based_payload(text)
        if isinstance(line_based, dict) and line_based:
            return cls._to_json_compatible(line_based), ""
        return None, "invalid_json"


    @staticmethod
    def _deserialize_payload_candidate(candidate: str) -> Optional[dict[str, Any]]:
        text = str(candidate or "").strip()
        if not text:
            return None
        for parser in (LiveBrainService._parse_with_json, LiveBrainService._parse_with_python_literal):
            parsed = parser(text)
            if isinstance(parsed, dict):
                return LiveBrainService._to_json_compatible(parsed)
        repaired = LiveBrainService._repair_json_candidate(text)
        if repaired and repaired != text:
            for parser in (LiveBrainService._parse_with_json, LiveBrainService._parse_with_python_literal):
                parsed = parser(repaired)
                if isinstance(parsed, dict):
                    return LiveBrainService._to_json_compatible(parsed)
        return None

    @staticmethod
    def _parse_with_json(text: str) -> Optional[dict[str, Any]]:
        try:
            parsed = json.loads(text)
        except Exception:
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _parse_with_python_literal(text: str) -> Optional[dict[str, Any]]:
        return None

    @staticmethod
    def _repair_json_candidate(text: str) -> str:
        repaired = str(text or "").strip()
        if not repaired:
            return ""
        repaired = repaired.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
        repaired = re.sub(r",(\s*[}\]])", r"\1", repaired)
        return repaired

    @staticmethod
    def _parse_line_based_payload(text: str) -> Optional[dict[str, Any]]:
        known_keys = {
            "asks",
            "ordered_asks",
            "coverage_points",
            "context_focus",
            "resolved_question",
            "question_completeness",
            "question_type",
            "response_shape",
            "answer_shape",
            "answer_contract",
            "tone",
            "directness",
            "use_candidate_context",
            "use_company_context",
            "use_metrics",
            "ordered_coverage_required",
            "target_length",
            "delivery_instructions",
            "draft_answer",
            "confidence",
            "reasoning_summary",
            "is_complete",
        }
        list_keys = {"asks", "ordered_asks", "coverage_points", "context_focus", "delivery_instructions"}
        payload: dict[str, Any] = {}
        current_list_key: Optional[str] = None

        for raw_line in text.splitlines():
            line = str(raw_line or "").strip().rstrip(",")
            if not line or line.startswith("```"):
                continue
            if line.startswith("- ") and current_list_key:
                value = LiveBrainService._parse_inline_scalar(line[2:].strip())
                if value not in {"", None}:
                    payload.setdefault(current_list_key, []).append(value)
                continue

            current_list_key = None
            match = re.match(r'^"?([a-zA-Z_][a-zA-Z0-9_]*)"?\s*:\s*(.*)$', line)
            if not match:
                continue
            key = match.group(1).strip()
            if key not in known_keys:
                continue
            raw_value = match.group(2).strip()
            if key in list_keys:
                if not raw_value:
                    payload.setdefault(key, [])
                    current_list_key = key
                    continue
                parsed_value = LiveBrainService._parse_inline_collection_or_scalar(raw_value)
                if isinstance(parsed_value, list):
                    payload[key] = parsed_value
                elif parsed_value not in {"", None}:
                    payload[key] = [parsed_value]
                continue
            payload[key] = LiveBrainService._parse_inline_collection_or_scalar(raw_value)

        return payload if payload.get("asks") or payload.get("ordered_asks") or payload.get("question_completeness") else None

    @staticmethod
    def _parse_inline_collection_or_scalar(raw_value: str) -> Any:
        value = str(raw_value or "").strip().rstrip(",")
        if not value:
            return ""
        if value.startswith("{") and value.endswith("}"):
            parsed = LiveBrainService._deserialize_payload_candidate(value)
            return parsed if parsed is not None else value
        if value.startswith("[") and value.endswith("]"):
            for parser in (json.loads, ast.literal_eval):
                try:
                    parsed = parser(value)
                except Exception:
                    continue
                if isinstance(parsed, list):
                    return [LiveBrainService._parse_inline_scalar(item) for item in parsed]
        return LiveBrainService._parse_inline_scalar(value)

    @staticmethod
    def _parse_inline_scalar(raw_value: Any) -> Any:
        if isinstance(raw_value, (bool, int, float)) or raw_value is None:
            return raw_value
        value = str(raw_value or "").strip().rstrip(",")
        if not value:
            return ""
        lowered = value.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        if lowered == "null":
            return None
        if re.fullmatch(r"-?\d+", value):
            try:
                return int(value)
            except Exception:
                return value
        if re.fullmatch(r"-?\d+\.\d+", value):
            try:
                return float(value)
            except Exception:
                return value
        return value.strip('"').strip("'")

    @staticmethod
    def _to_json_compatible(value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): LiveBrainService._to_json_compatible(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [LiveBrainService._to_json_compatible(item) for item in value]
        return value

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        value = str(text or "").strip()
        if not value.startswith("```"):
            return value
        lines = value.splitlines()
        if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].startswith("```"):
            return "\n".join(lines[1:-1]).strip()
        return value

    @staticmethod
    def _extract_balanced_json_object(text: str) -> str:
        value = str(text or "")
        start = value.find("{")
        if start < 0:
            return ""
        depth = 0
        in_string = False
        escaped = False
        quote_char = ""
        for idx in range(start, len(value)):
            char = value[idx]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote_char:
                    in_string = False
                continue
            if char in {'"', "'"}:
                in_string = True
                quote_char = char
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return value[start: idx + 1].strip()
        return ""

    @staticmethod
    def _compact_text(value: Any, *, limit: int = 240) -> str:
        text = " ".join(str(value or "").split()).strip()
        if len(text) <= limit:
            return text
        return text[: limit - 3].rstrip() + "..."

    @staticmethod
    def _format_history(history: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for turn in history[-5:]:
            speaker = (turn.get("speaker") or turn.get("role") or "interviewer").upper()
            text = " ".join(str(turn.get("text") or turn.get("content") or "").split()).strip()
            if text:
                lines.append(f"{speaker}: {text}")
        return "\n".join(lines) if lines else "INTERVIEWER: Not available"

    def _resolve_adapter(self, *, alias: str) -> Optional[Any]:
        if os.getenv("PYTEST_CURRENT_TEST"):
            return None

        runtime_config = _get_runtime_config() or {}
        runtime_llm = runtime_config.get("llm") or {}
        runtime_provider = str(runtime_llm.get("provider") or "").strip().lower()
        runtime_enabled = bool(runtime_llm.get("enabled"))
        runtime_api_key = runtime_llm.get("api_key") or ""
        runtime_model = str(runtime_llm.get("model") or "").strip()

        if alias == "fast":
            if runtime_enabled and runtime_provider == "anthropic" and runtime_api_key:
                adapter = AnthropicLLMAdapter(model="claude-haiku-4-5-20251001")
                adapter.api_key = runtime_api_key
                return adapter
            if runtime_enabled and runtime_provider == "openai" and runtime_api_key:
                adapter = OpenAILLMAdapter(model="gpt-4o-mini")
                adapter.api_key = runtime_api_key
                return adapter
            if runtime_enabled and runtime_provider == "ollama":
                return OllamaLLMAdapter(model="llama3.2:1b", base_url=runtime_llm.get("base_url") or "http://localhost:11434")
        else:
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
