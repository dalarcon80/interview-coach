from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from hashlib import sha1
from typing import Any

from contracts.models import BrainPlan, CompactEvidencePack

_FOCUS_STOPWORDS = {
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
    "are",
    "for",
    "and",
}

_EVIDENCE_TYPE_HINTS = {
    "role_evidence": {"role", "director", "lead", "leadership", "responsibility", "scope"},
    "build_evidence": {"build", "built", "building", "founded", "created", "launched", "zero", "scratch", "service", "product", "practice", "model"},
    "leadership_evidence": {"team", "teams", "managed", "management", "leaders", "direct", "indirect", "reports", "regions", "organization"},
    "team_scope_evidence": {"roles", "architects", "engineers", "consultants", "managers", "delivery", "composition", "staffing"},
    "operating_style_evidence": {"governance", "quality", "predictable", "operating", "cadence", "execution", "delivery", "workflow", "standardized", "controls", "kpi"},
    "client_posture_evidence": {"executive", "stakeholder", "stakeholders", "client", "clients", "proposal", "proposals", "commercial", "roadmap", "roadmaps", "advisory", "alignment"},
    "culture_alignment_evidence": {"culture", "team", "ownership", "collaboration", "communication", "autonomy", "people"},
    "technical_alignment_evidence": {"aws", "cloud", "architecture", "platform", "data", "ai", "llm", "agent", "agents", "design", "tradeoff", "tradeoffs", "pipeline"},
    "candidate_snippets": {"experience", "background", "outcomes"},
    "company_snippets": {"company", "role", "team", "business", "market"},
    "interviewer_snippets": {"interviewer", "focus", "expectation"},
    "supporting_metrics": {"metric", "metrics", "outcome", "impact", "result", "results", "kpi"},
}


@dataclass
class LiveEvidencePackerConfig:
    max_candidate_snippets: int = 2
    max_company_snippets: int = 2
    max_interviewer_snippets: int = 0
    max_metrics: int = 1
    minimal_candidate_snippets: int = 1
    minimal_company_snippets: int = 1
    minimal_interviewer_snippets: int = 0
    minimal_metrics: int = 0


class LiveEvidencePacker:
    def __init__(self, config: LiveEvidencePackerConfig | None = None):
        self.config = config or LiveEvidencePackerConfig()

    def pack(
        self,
        *,
        plan: BrainPlan,
        interview_config: dict[str, Any],
    ) -> CompactEvidencePack:
        candidate = interview_config.get("candidate") or {}
        company = interview_config.get("company") or {}
        interviewer = interview_config.get("interviewer") or {}
        candidate_sections = self._candidate_source_sections(candidate)
        focus_terms = self._focus_terms(plan)
        mode = self._mode_for_plan(plan)
        evidence_priority = self._evidence_priority(plan)
        profile_evidence_mode = self._profile_evidence_mode(plan)
        company_evidence_mode = self._company_evidence_mode(plan)

        candidate_limit = self.config.max_candidate_snippets if mode == "full" else self.config.minimal_candidate_snippets
        company_limit = self.config.max_company_snippets if mode == "full" else self.config.minimal_company_snippets
        interviewer_limit = self.config.max_interviewer_snippets if mode == "full" else self.config.minimal_interviewer_snippets
        metrics_limit = self.config.max_metrics if mode == "full" else self.config.minimal_metrics

        candidate_snippets = self._rank_snippets(
            candidate_sections["candidate_snippets"] if profile_evidence_mode != "none" else [],
            focus_terms=self._bucket_focus_terms(plan, "candidate_snippets", base_focus=focus_terms),
            limit=candidate_limit,
            allow_zero_overlap=bool(
                plan.include_profile_opening
                or plan.candidate_context_policy == "required"
                or profile_evidence_mode in {"orientation_only", "scope_only", "one_best_proof", "multi_proof"}
                or "candidate_snippets" in evidence_priority
            ),
        )
        company_sources = (
            self._company_preference_sources(company)
            if company_evidence_mode == "preference_alignment"
            else self._company_sources(company)
        )
        company_snippets = self._rank_snippets(
            company_sources,
            focus_terms=self._bucket_focus_terms(plan, "company_snippets", base_focus=focus_terms),
            limit=company_limit,
            allow_zero_overlap=bool(
                plan.company_context_policy == "required"
                or company_evidence_mode != "none"
                or "company_snippets" in evidence_priority
            ),
        )
        interviewer_snippets = self._rank_snippets(
            self._interviewer_sources(interviewer),
            focus_terms=self._bucket_focus_terms(plan, "interviewer_snippets", base_focus=focus_terms),
            limit=interviewer_limit,
            allow_zero_overlap=True,
        )
        used_structured_snippets: set[str] = set()
        role_evidence = self._select_bucket_snippets(
            candidate_sections["role_evidence"] if profile_evidence_mode != "none" else [],
            focus_terms=self._bucket_focus_terms(plan, "role_evidence", base_focus=focus_terms),
            limit=2 if mode == "full" else 1,
            allow_zero_overlap="role_evidence" in evidence_priority,
            used_normalized=used_structured_snippets,
        )
        build_evidence = self._select_bucket_snippets(
            candidate_sections["build_evidence"] if profile_evidence_mode != "none" else [],
            focus_terms=self._bucket_focus_terms(plan, "build_evidence", base_focus=focus_terms),
            limit=2 if mode == "full" else 1,
            allow_zero_overlap="build_evidence" in evidence_priority,
            used_normalized=used_structured_snippets,
        )
        leadership_evidence = self._select_bucket_snippets(
            candidate_sections["leadership_evidence"] if profile_evidence_mode != "none" else [],
            focus_terms=self._bucket_focus_terms(plan, "leadership_evidence", base_focus=focus_terms),
            limit=2 if mode == "full" else 1,
            allow_zero_overlap="leadership_evidence" in evidence_priority,
            used_normalized=used_structured_snippets,
        )
        team_scope_evidence = self._select_bucket_snippets(
            candidate_sections["team_scope_evidence"] if profile_evidence_mode != "none" else [],
            focus_terms=self._bucket_focus_terms(plan, "team_scope_evidence", base_focus=focus_terms),
            limit=2 if mode == "full" else 1,
            allow_zero_overlap="team_scope_evidence" in evidence_priority,
            used_normalized=used_structured_snippets,
        )
        operating_style_evidence = self._select_bucket_snippets(
            candidate_sections["operating_style_evidence"] if profile_evidence_mode != "none" else [],
            focus_terms=self._bucket_focus_terms(plan, "operating_style_evidence", base_focus=focus_terms),
            limit=2 if mode == "full" else 1,
            allow_zero_overlap="operating_style_evidence" in evidence_priority,
            used_normalized=used_structured_snippets,
        )
        client_posture_evidence = self._select_bucket_snippets(
            candidate_sections["client_posture_evidence"] if profile_evidence_mode != "none" else [],
            focus_terms=self._bucket_focus_terms(plan, "client_posture_evidence", base_focus=focus_terms),
            limit=2 if mode == "full" else 1,
            allow_zero_overlap="client_posture_evidence" in evidence_priority,
            used_normalized=used_structured_snippets,
        )
        culture_alignment_evidence = self._rank_snippets(
            [
                *company_sources,
                *(
                    candidate_sections["candidate_snippets"]
                    if profile_evidence_mode != "none"
                    else []
                ),
            ],
            focus_terms=self._bucket_focus_terms(plan, "culture_alignment_evidence", base_focus=focus_terms),
            limit=2 if mode == "full" else 1,
            allow_zero_overlap="culture_alignment_evidence" in evidence_priority,
        )
        technical_alignment_evidence = self._select_bucket_snippets(
            [
                *(
                    candidate_sections["technical_alignment_evidence"]
                    if profile_evidence_mode != "none"
                    else []
                ),
                *(
                    self._company_sources(company)
                    if company_evidence_mode != "none"
                    else []
                ),
            ],
            focus_terms=self._bucket_focus_terms(plan, "technical_alignment_evidence", base_focus=focus_terms),
            limit=2 if mode == "full" else 1,
            allow_zero_overlap="technical_alignment_evidence" in evidence_priority,
            used_normalized=used_structured_snippets,
        )
        supporting_metrics = self._select_metrics(
            sources=self._metric_sources(candidate, company),
            focus_terms=self._bucket_focus_terms(plan, "supporting_metrics", base_focus=focus_terms),
            limit=metrics_limit if plan.metrics_policy == "required" else min(metrics_limit, 1),
        )
        (
            candidate_snippets,
            role_evidence,
            build_evidence,
            leadership_evidence,
            team_scope_evidence,
            operating_style_evidence,
            client_posture_evidence,
            technical_alignment_evidence,
        ) = self._apply_profile_evidence_mode_constraints(
            plan=plan,
            candidate_snippets=candidate_snippets,
            role_evidence=role_evidence,
            build_evidence=build_evidence,
            leadership_evidence=leadership_evidence,
            team_scope_evidence=team_scope_evidence,
            operating_style_evidence=operating_style_evidence,
            client_posture_evidence=client_posture_evidence,
            technical_alignment_evidence=technical_alignment_evidence,
        )
        excluded_topics = self._excluded_topics(plan)

        return CompactEvidencePack(
            plan_hash=self._plan_hash(plan),
            candidate_snippets=candidate_snippets,
            company_snippets=company_snippets,
            interviewer_snippets=interviewer_snippets,
            role_evidence=role_evidence,
            build_evidence=build_evidence,
            leadership_evidence=leadership_evidence,
            team_scope_evidence=team_scope_evidence,
            operating_style_evidence=operating_style_evidence,
            client_posture_evidence=client_posture_evidence,
            culture_alignment_evidence=culture_alignment_evidence,
            technical_alignment_evidence=technical_alignment_evidence,
            supporting_metrics=supporting_metrics,
            excluded_topics=excluded_topics,
            mode=mode,
        )

    def _apply_profile_evidence_mode_constraints(
        self,
        *,
        plan: BrainPlan,
        candidate_snippets: list[str],
        role_evidence: list[str],
        build_evidence: list[str],
        leadership_evidence: list[str],
        team_scope_evidence: list[str],
        operating_style_evidence: list[str],
        client_posture_evidence: list[str],
        technical_alignment_evidence: list[str],
    ) -> tuple[list[str], list[str], list[str], list[str], list[str], list[str], list[str], list[str]]:
        profile_mode = self._profile_evidence_mode(plan)
        evidence_priority = self._evidence_priority(plan)

        if profile_mode == "none":
            return [], [], [], [], [], [], [], technical_alignment_evidence

        if profile_mode == "orientation_only":
            return candidate_snippets[:1], role_evidence[:1], [], [], [], [], [], []

        if profile_mode == "scope_only":
            return [], [], [], leadership_evidence[:1], team_scope_evidence[:2], [], [], []

        if profile_mode != "one_best_proof":
            return (
                candidate_snippets,
                role_evidence,
                build_evidence,
                leadership_evidence,
                team_scope_evidence,
                operating_style_evidence,
                client_posture_evidence,
                technical_alignment_evidence,
            )

        proof_buckets = {
            "build_evidence": build_evidence[:1],
            "leadership_evidence": leadership_evidence[:1],
            "team_scope_evidence": team_scope_evidence[:1],
            "operating_style_evidence": operating_style_evidence[:1],
            "client_posture_evidence": client_posture_evidence[:1],
            "technical_alignment_evidence": technical_alignment_evidence[:1],
        }
        selected_bucket = ""
        for bucket in evidence_priority:
            items = proof_buckets.get(bucket) or []
            if items:
                selected_bucket = bucket
                break
        if not selected_bucket:
            for bucket in (
                "operating_style_evidence",
                "technical_alignment_evidence",
                "build_evidence",
                "client_posture_evidence",
                "leadership_evidence",
                "team_scope_evidence",
            ):
                if proof_buckets[bucket]:
                    selected_bucket = bucket
                    break

        return (
            candidate_snippets[:1],
            role_evidence[:1],
            proof_buckets["build_evidence"] if selected_bucket == "build_evidence" else [],
            proof_buckets["leadership_evidence"] if selected_bucket == "leadership_evidence" else [],
            proof_buckets["team_scope_evidence"] if selected_bucket == "team_scope_evidence" else [],
            proof_buckets["operating_style_evidence"] if selected_bucket == "operating_style_evidence" else [],
            proof_buckets["client_posture_evidence"] if selected_bucket == "client_posture_evidence" else [],
            proof_buckets["technical_alignment_evidence"] if selected_bucket == "technical_alignment_evidence" else [],
        )

    @staticmethod
    def _candidate_sources(candidate: dict[str, Any]) -> list[str]:
        return LiveEvidencePacker._candidate_source_sections(candidate)["candidate_snippets"]

    @staticmethod
    def _candidate_source_sections(candidate: dict[str, Any]) -> dict[str, list[str]]:
        current_role = LiveEvidencePacker._normalize_text(candidate.get("currentRole") or candidate.get("current_role"))
        candidate_company = LiveEvidencePacker._normalize_text(
            candidate.get("company") or candidate.get("current_company") or candidate.get("currentCompany")
        )
        current_company = f"Current company: {candidate_company}" if candidate_company else ""
        summary_snippets = LiveEvidencePacker._split_text_snippets(candidate.get("summary"))
        cv_snippets = LiveEvidencePacker._split_text_snippets(candidate.get("cv_text"))
        achievement_snippets = [
            LiveEvidencePacker._normalize_text(raw)
            for raw in (candidate.get("achievements") or [])
            if LiveEvidencePacker._normalize_text(raw)
        ]
        skill_snippets = [
            LiveEvidencePacker._normalize_text(raw)
            for raw in (candidate.get("skills") or [])
            if LiveEvidencePacker._normalize_text(raw)
        ]
        role_sources = LiveEvidencePacker._unique_preserve_order(
            [current_role, current_company, *summary_snippets]
        )
        build_sources = LiveEvidencePacker._unique_preserve_order(
            [*achievement_snippets, *cv_snippets, *summary_snippets]
        )
        leadership_sources = LiveEvidencePacker._unique_preserve_order(
            [*summary_snippets, *cv_snippets, *achievement_snippets]
        )
        team_scope_sources = LiveEvidencePacker._unique_preserve_order(
            [*cv_snippets, *achievement_snippets, *summary_snippets]
        )
        operating_style_sources = LiveEvidencePacker._unique_preserve_order(
            LiveEvidencePacker._filter_sources_by_terms(
                [*achievement_snippets, *summary_snippets, *cv_snippets],
                _EVIDENCE_TYPE_HINTS["operating_style_evidence"],
            )
        )
        client_posture_sources = LiveEvidencePacker._unique_preserve_order(
            LiveEvidencePacker._filter_sources_by_terms(
                [*cv_snippets, *achievement_snippets, *summary_snippets],
                _EVIDENCE_TYPE_HINTS["client_posture_evidence"],
            )
        )
        technical_sources = LiveEvidencePacker._unique_preserve_order(
            [*skill_snippets, *cv_snippets, *achievement_snippets, *summary_snippets]
        )
        candidate_snippets = LiveEvidencePacker._unique_preserve_order(
            [current_role, current_company, *summary_snippets, *achievement_snippets, *cv_snippets, *skill_snippets]
        )
        return {
            "candidate_snippets": candidate_snippets,
            "role_evidence": role_sources or candidate_snippets,
            "build_evidence": build_sources or candidate_snippets,
            "leadership_evidence": leadership_sources or candidate_snippets,
            "team_scope_evidence": team_scope_sources or candidate_snippets,
            "operating_style_evidence": operating_style_sources or candidate_snippets,
            "client_posture_evidence": client_posture_sources or candidate_snippets,
            "technical_alignment_evidence": technical_sources or candidate_snippets,
        }

    @staticmethod
    def _filter_sources_by_terms(sources: list[str], terms: set[str]) -> list[str]:
        matched: list[str] = []
        for source in list(sources or []):
            lowered = LiveEvidencePacker._normalize_text(source).lower()
            if not lowered:
                continue
            if any(term in lowered for term in terms):
                matched.append(source)
        return LiveEvidencePacker._unique_preserve_order(matched or list(sources or []))

    @staticmethod
    def _company_sources(company: dict[str, Any]) -> list[str]:
        values: list[str] = []
        for raw in (
            company.get("roleTitle"),
            company.get("positionTitle"),
            company.get("companySummary"),
            company.get("companyDescription"),
            company.get("companyCulture"),
            *(company.get("values") or []),
            *(company.get("roleRequirements") or []),
            *(company.get("roleResponsibilities") or []),
            *(company.get("recentFocus") or []),
        ):
            normalized = LiveEvidencePacker._normalize_text(raw)
            if normalized:
                values.append(normalized)
        return values

    @staticmethod
    def _company_preference_sources(company: dict[str, Any]) -> list[str]:
        values: list[str] = []
        for raw in (
            company.get("companySummary"),
            company.get("companyDescription"),
            company.get("companyCulture"),
            *(company.get("values") or []),
            *(company.get("recentFocus") or []),
        ):
            normalized = LiveEvidencePacker._normalize_text(raw)
            if normalized:
                values.append(normalized)
        return values

    @staticmethod
    def _interviewer_sources(interviewer: dict[str, Any]) -> list[str]:
        values: list[str] = []
        for raw in (
            interviewer.get("backgroundSummary"),
            interviewer.get("notes"),
            *(interviewer.get("likelyFocusAreas") or []),
            *(interviewer.get("expertise") or []),
        ):
            normalized = LiveEvidencePacker._normalize_text(raw)
            if normalized:
                values.append(normalized)
        return values

    @staticmethod
    def _split_text_snippets(value: Any) -> list[str]:
        text = str(value or "").replace("•", "\n").replace("\t", " ")
        parts: list[str] = []
        for raw_block in re.split(r"\n+", text):
            block = LiveEvidencePacker._normalize_text(raw_block)
            if not block:
                continue
            for raw_piece in re.split(r"(?<=[.!?])\s+|\s+\|\s+", block):
                piece = LiveEvidencePacker._normalize_text(raw_piece)
                if piece:
                    parts.append(piece)
        return LiveEvidencePacker._unique_preserve_order(parts)

    @staticmethod
    def _unique_preserve_order(values: list[str]) -> list[str]:
        unique: list[str] = []
        seen: set[str] = set()
        for raw in list(values or []):
            normalized = LiveEvidencePacker._normalize_text(raw)
            if not normalized:
                continue
            lowered = normalized.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            unique.append(normalized)
        return unique

    @staticmethod
    def _metric_sources(candidate: dict[str, Any], company: dict[str, Any]) -> list[str]:
        values: list[str] = []
        for raw in (
            *(candidate.get("achievements") or []),
            candidate.get("summary"),
            *(company.get("recentFocus") or []),
        ):
            normalized = LiveEvidencePacker._normalize_text(raw)
            if normalized and re.search(r"\d|%|\+|-", normalized):
                values.append(normalized)
        return values

    @staticmethod
    def _focus_terms(plan: BrainPlan) -> set[str]:
        seed = " ".join(
            [
                plan.literal_question or "",
                plan.resolved_question or "",
                *list(plan.ordered_asks or []),
                *list(plan.coverage_points or []),
                *list(plan.context_focus or []),
                plan.interviewer_need.summary or "",
                *list(plan.interviewer_need.dimensions or []),
                *[
                    getattr(intent, "decision_target", "")
                    for intent in list(plan.ask_intents or [])
                    if getattr(intent, "decision_target", "")
                ],
            ]
        )
        return {
            token
            for token in re.findall(r"[a-z0-9]+", seed.lower())
            if len(token) > 2 and token not in _FOCUS_STOPWORDS
        }

    @staticmethod
    def _profile_evidence_mode(plan: BrainPlan) -> str:
        mode = getattr(plan.response_requirement, "profile_evidence_mode", "")
        if mode:
            return str(mode).strip().lower()
        values = [
            str(getattr(intent, "profile_evidence_mode", "")).strip().lower()
            for intent in list(plan.ask_intents or [])
            if str(getattr(intent, "profile_evidence_mode", "")).strip()
        ]
        return values[0] if values else "support_if_relevant"

    @staticmethod
    def _company_evidence_mode(plan: BrainPlan) -> str:
        mode = getattr(plan.response_requirement, "company_evidence_mode", "")
        if mode:
            return str(mode).strip().lower()
        values = [
            str(getattr(intent, "company_evidence_mode", "")).strip().lower()
            for intent in list(plan.ask_intents or [])
            if str(getattr(intent, "company_evidence_mode", "")).strip()
        ]
        return values[0] if values else "support_if_relevant"

    @staticmethod
    def _evidence_priority(plan: BrainPlan) -> set[str]:
        return {
            item
            for item in [
                *list(plan.response_requirement.evidence_priority or []),
                *[
                    evidence
                    for intent in list(plan.ask_intents or [])
                    for evidence in list(intent.required_evidence_types or [])
                ],
            ]
            if item
        }

    @staticmethod
    def _bucket_focus_terms(plan: BrainPlan, bucket: str, *, base_focus: set[str]) -> set[str]:
        priority = LiveEvidencePacker._evidence_priority(plan)
        hint_terms = set(_EVIDENCE_TYPE_HINTS.get(bucket, set()))
        if bucket in priority:
            return set(base_focus) | hint_terms
        if bucket in set(plan.response_requirement.evidence_priority or []):
            return set(base_focus) | hint_terms
        if bucket in {"candidate_snippets", "company_snippets", "interviewer_snippets"}:
            return set(base_focus)
        return hint_terms if not base_focus else set(base_focus) | hint_terms

    @staticmethod
    def _rank_snippets(
        sources: list[str],
        *,
        focus_terms: set[str],
        limit: int,
        allow_zero_overlap: bool,
    ) -> list[str]:
        if limit <= 0:
            return []
        scored: list[tuple[float, str]] = []
        for idx, source in enumerate(sources):
            source_terms = {
                token
                for token in re.findall(r"[a-z0-9]+", source.lower())
                if len(token) > 2
            }
            overlap = len(source_terms & focus_terms) / max(len(focus_terms), 1)
            if focus_terms and overlap <= 0.0 and not allow_zero_overlap:
                continue
            exact_bonus = min(len(source_terms & focus_terms) * 0.05, 0.25)
            directness_bonus = 0.12 if len(source.split()) <= 8 else 0.0
            density_bonus = min(len(source.split()) / 40.0, 0.2)
            score = overlap + exact_bonus + directness_bonus + density_bonus - (idx * 0.001)
            scored.append((score, source))

        ranked = [text for _, text in sorted(scored, key=lambda item: item[0], reverse=True)]
        unique: list[str] = []
        seen: set[str] = set()
        for text in ranked:
            normalized = LiveEvidencePacker._normalize_text(text)
            if not normalized:
                continue
            lowered = normalized.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            unique.append(normalized)
            if len(unique) >= limit:
                break
        return unique

    @staticmethod
    def _select_bucket_snippets(
        sources: list[str],
        *,
        focus_terms: set[str],
        limit: int,
        allow_zero_overlap: bool,
        used_normalized: set[str] | None = None,
    ) -> list[str]:
        ranked = LiveEvidencePacker._rank_snippets(
            sources,
            focus_terms=focus_terms,
            limit=max(limit * 3, limit),
            allow_zero_overlap=allow_zero_overlap,
        )
        if not ranked:
            return []
        if not used_normalized:
            selected = ranked[:limit]
        else:
            selected = [
                text
                for text in ranked
                if LiveEvidencePacker._normalize_text(text).lower() not in used_normalized
            ][:limit]
            if not selected:
                selected = ranked[:limit]
        if used_normalized is not None:
            used_normalized.update(LiveEvidencePacker._normalize_text(text).lower() for text in selected if text)
        return selected

    @staticmethod
    def _select_metrics(
        *,
        sources: list[str],
        focus_terms: set[str],
        limit: int,
    ) -> list[str]:
        ranked = LiveEvidencePacker._rank_snippets(
            sources,
            focus_terms=focus_terms,
            limit=limit,
            allow_zero_overlap=False,
        )
        return ranked[:limit]

    @staticmethod
    def _excluded_topics(plan: BrainPlan) -> list[str]:
        excluded: list[str] = []
        minimal_mode = LiveEvidencePacker._mode_for_plan(plan) == "minimal"
        if not plan.include_profile_opening or minimal_mode:
            excluded.append("generic_profile_opening")
        if plan.metrics_policy != "required" or minimal_mode:
            excluded.append("unsupported_metrics")
        if plan.company_context_policy == "avoid" or minimal_mode:
            excluded.append("company_pitch")
        if plan.candidate_context_policy == "avoid" or minimal_mode:
            excluded.append("career_biography")
        if plan.response_family == "intro_alignment":
            excluded.append("unsupported_fit_closure")
        for item in list(plan.response_requirement.avoid or []):
            normalized = LiveEvidencePacker._normalize_text(item).lower().replace(" ", "_")
            if normalized and normalized not in excluded:
                excluded.append(normalized)
        return excluded

    @staticmethod
    def _mode_for_plan(plan: BrainPlan) -> str:
        if str(plan.plan_source or "").strip().lower() != "llm_fast":
            if (
                str(plan.question_completeness or "").strip().lower() in {"complete", "partial"}
                and (
                    len(list(plan.ordered_asks or [])) > 1
                    or len(list(plan.coverage_points or [])) > 1
                    or str(plan.response_shape or "").strip().lower() in {"direct_structured", "technical_explainer", "strategic_explainer"}
                )
                and float(plan.confidence or 0.0) >= 0.45
            ):
                return "full"
            return "minimal"
        if str(plan.question_completeness or "").strip().lower() != "complete":
            return "minimal"
        return "full"

    @staticmethod
    def _plan_hash(plan: BrainPlan) -> str:
        payload = {
            "resolved_question": plan.resolved_question,
            "ordered_asks": list(plan.ordered_asks or []),
            "ask_intents": [item.model_dump(mode="json") for item in list(plan.ask_intents or [])],
            "interviewer_need": plan.interviewer_need.model_dump(mode="json"),
            "response_requirement": plan.response_requirement.model_dump(mode="json"),
            "context_focus": list(plan.context_focus or []),
            "response_family": plan.response_family,
            "alignment_brief": list(plan.alignment_brief or []),
            "response_shape": plan.response_shape,
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
    def _normalize_text(value: Any) -> str:
        return " ".join(str(value or "").split()).strip()
