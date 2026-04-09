"""
Interview Coach - Ask Normalizer

Lightweight, low-latency sidecar that normalizes the interviewer ask into a
structured brief before the main analyzer/composer runs.

The v1 implementation is deterministic and same-process. It is intentionally
shadow-mode first so it can be compared against the current pipeline without
changing user-facing answer generation.
"""
from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
import re
from typing import Optional

from contracts.models import (
    AskBrief,
    AskFamily,
    AnswerContract,
    EvidencePolicy,
    MetricsPolicy,
    QuestionAnalysis,
    QuestionMode,
    QuestionType,
    ResponseMode,
    ResponseStyle,
    AnswerIntent,
    Priority,
    SubQuestion,
)


@dataclass
class AskNormalizerConfig:
    mode: str = "shadow"
    confidence_threshold: float = 0.72
    max_interviewer_turns: int = 5


class AskNormalizer:
    """Deterministic ask normalizer with a clean interface and low latency."""

    def __init__(self, config: Optional[AskNormalizerConfig] = None):
        self.config = config or AskNormalizerConfig()

    def normalize(
        self,
        question: str,
        turns: Optional[list[dict]] = None,
        *,
        delivery_mode: str = "manual",
    ) -> AskBrief:
        started = perf_counter()
        normalized_question = " ".join(str(question or "").split()).strip()
        recent_turns = turns or []
        ask_block = self._build_latest_interviewer_block(recent_turns) or normalized_question
        actionable_segments = self._prioritize_actionable_segments(
            self._extract_actionable_segments(ask_block)
        )
        actionable_segments = self._merge_related_segments(actionable_segments)
        combined_ask = "\n".join(actionable_segments).strip() or ask_block
        primary_ask = actionable_segments[0] if actionable_segments else combined_ask
        secondary_asks = actionable_segments[1:5]
        answer_family, family_why = self._classify_family(combined_ask)
        if answer_family == AskFamily.EXPERIENCE_SCOPE and len(actionable_segments) > 1:
            answer_family = AskFamily.MIXED_COMPOUND
            family_why.append("Multiple actionable experience asks detected after noise cleanup")
        (
            answer_contract,
            evidence_policy,
            metrics_policy,
            opening_strategy,
        ) = self._contract_for_family(answer_family, delivery_mode)

        confidence = self._score_confidence(combined_ask, answer_family, secondary_asks)
        latency_ms = int((perf_counter() - started) * 1000)
        fallback_used = confidence < self.config.confidence_threshold

        return AskBrief(
            primary_ask=primary_ask or normalized_question,
            secondary_asks=secondary_asks,
            answer_family=answer_family,
            answer_contract=answer_contract,
            evidence_policy=evidence_policy,
            metrics_policy=metrics_policy,
            opening_strategy=opening_strategy,
            confidence=confidence,
            why=family_why,
            shadow_mode=self.config.mode == "shadow",
            latency_ms=latency_ms,
            fallback_used=fallback_used,
        )

    def build_signature(self, question: str, turns: Optional[list[dict]] = None) -> str:
        normalized_question = " ".join(str(question or "").split()).strip()
        recent_turns = turns or []
        ask_block = self._build_latest_interviewer_block(recent_turns) or normalized_question
        actionable_segments = self._prioritize_actionable_segments(
            self._extract_actionable_segments(ask_block)
        )
        normalized = "\n".join(actionable_segments).strip() or ask_block
        return normalized.strip().lower()

    def _build_latest_interviewer_block(self, turns: list[dict]) -> str:
        if not turns:
            return ""

        block: list[str] = []
        block_seen = False
        for idx in range(len(turns) - 1, -1, -1):
            turn = turns[idx]
            speaker = str(turn.get("speaker") or turn.get("role") or "").strip().lower()
            text = " ".join(str(turn.get("text") or turn.get("content") or "").split()).strip()
            if not text:
                continue
            if speaker == "interviewer":
                block_seen = True
                block.append(text)
                if len(block) >= self.config.max_interviewer_turns:
                    break
                continue
            if block_seen:
                break
        return "\n".join(reversed(block)).strip()

    def _extract_actionable_segments(self, ask_block: str) -> list[str]:
        if not ask_block:
            return []

        cleaned: list[str] = []
        for line in ask_block.splitlines():
            normalized_line = " ".join(str(line or "").split()).strip()
            if not normalized_line:
                continue
            raw_candidates = self._split_actionable_candidates(normalized_line)
            for candidate in raw_candidates:
                text = self._normalize_segment(candidate)
                text = self._trim_to_actionable_core(text)
                if not text:
                    continue
                if self._is_noise_segment(text):
                    continue
                if not self._is_actionable_segment(text):
                    continue
                if text not in cleaned:
                    cleaned.append(text)

        if cleaned:
            return cleaned[:8]

        fallback = self._normalize_segment(" ".join(ask_block.split()))
        return [fallback] if fallback else []

    def _prioritize_actionable_segments(self, segments: list[str]) -> list[str]:
        """Preserve interviewer order, but demote broad intro prompts when mixed in."""
        if len(segments) <= 1:
            return segments

        specific_segments: list[str] = []
        broad_intro_segments: list[str] = []

        for segment in segments:
            if self._is_broad_intro_request(segment):
                broad_intro_segments.append(segment)
            else:
                specific_segments.append(segment)

        prioritized = list(specific_segments)
        prioritized.extend(broad_intro_segments)
        return prioritized[:5]

    def _merge_related_segments(self, segments: list[str]) -> list[str]:
        """Merge adjacent segments that are clearly part of the same ask."""
        if len(segments) <= 1:
            return segments

        merged: list[str] = []
        for segment in segments:
            if not merged:
                merged.append(segment)
                continue
            previous = merged[-1]
            if self._should_merge_segments(previous, segment):
                merged[-1] = self._merge_segment_pair(previous, segment)
            else:
                merged.append(segment)
        return merged[:5]

    @staticmethod
    def _normalize_segment(text: str) -> str:
        text = " ".join(str(text or "").split()).strip(" ,.-")
        patterns = [
            r"^(yeah|so|and|but|okay|ok|well)\b[\s,.-]*",
            r"^(i mean|i guess|if you want|as we go)\b[\s,.-]*",
            r"^(daniel(?:le)?(?:\s+alarc[oó]n)?)[,:-]?\s*",
            r"^(we (?:will|were) talk(?:ing)? about)\b[\s,.-]*",
            r"^(in terms of your experience)\b[\s,.-]*",
            r"^(i (?:just )?wanted to ask you(?:, like)?)\b[\s,.-]*",
            r"^(or not the role, but)\b[\s,.-]*",
            r"^(basically what you have done in your experience)\b[\s,.-]*",
            r"^(hear specifically examples of)\b[\s,.-]*",
            r"^(last question as as we go)\b[\s,.-]*",
        ]
        previous = None
        while text != previous:
            previous = text
            for pattern in patterns:
                text = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()
        return text.strip()

    @staticmethod
    def _split_actionable_candidates(text: str) -> list[str]:
        anchor_pattern = re.compile(
            r"(?i)\bwhat\b|\bhow\b|\bwhy\b|tell me|describe|explain|walk me through|"
            r"looking for|important for you|what kind of things|get a sense of|"
            r"curious to hear about|hear about|experience in|expectations? in terms of"
        )
        positions: list[int] = []
        for match in anchor_pattern.finditer(text):
            start = match.start()
            if not positions or start - positions[-1] > 8:
                positions.append(start)
        if not positions:
            return re.split(r"[?.!]+", text)

        positions.append(len(text))
        segments: list[str] = []
        for idx in range(len(positions) - 1):
            segment = text[positions[idx]:positions[idx + 1]].strip(" ,.-")
            if segment:
                segments.append(segment)
        return segments

    @staticmethod
    def _trim_to_actionable_core(text: str) -> str:
        if not text:
            return ""

        actionable_anchor = re.compile(
            r"(?i)\bwhat\b|\bhow\b|\bwhy\b|tell me|describe|explain|walk me through|"
            r"looking for|important for you|what kind of things|get a sense of|"
            r"curious to hear about|hear about|experience in|expectations? in terms of|"
            r"build(?:ing)? from|from scratch|team management|roles?\b|culture\b|"
            r"python\b|architecture\b|product\b|strategy\b|kpis?\b|outcomes?\b"
        )
        match = actionable_anchor.search(text)
        if match and match.start() > 0:
            text = text[match.start():]

        text = re.sub(r"^(get a sense of|experience in|curious to hear about|hear about)\b[\s,.-]*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s+", " ", text).strip(" ,.-")
        return text

    @staticmethod
    def _is_noise_segment(text: str) -> bool:
        lowered = text.lower()
        if len(lowered) < 10:
            return True
        if re.search(r"terrible cough|won't go away|as as we go", lowered):
            return True
        if lowered in {"sorry", "yeah", "etcetera"}:
            return True
        return False

    @staticmethod
    def _is_actionable_segment(text: str) -> bool:
        lowered = text.lower()
        actionable_patterns = [
            r"\bwhat\b",
            r"\bhow\b",
            r"\bwhy\b",
            r"\btell me\b",
            r"\bdescribe\b",
            r"\bexplain\b",
            r"\blooking for\b",
            r"\bimportant\b",
            r"\bbuild(?:ing)? from\b",
            r"\bscratch\b",
            r"\bteam\b",
            r"\brole\b",
            r"\bculture\b",
            r"\bpython\b",
            r"\barchitecture\b",
            r"\bproduct\b",
            r"\bstrategy\b",
            r"\bkpi\b",
            r"\boutcome\b",
        ]
        return any(re.search(pattern, lowered) for pattern in actionable_patterns)

    @staticmethod
    def _is_broad_intro_request(text: str) -> bool:
        lowered = text.lower()
        broad_intro_patterns = [
            r"tell me a little bit about you",
            r"start telling us about you",
            r"walk me through your background",
            r"tell me about yourself",
            r"give me a quick intro",
            r"brief intro",
        ]
        return any(re.search(pattern, lowered) for pattern in broad_intro_patterns)

    @staticmethod
    def _segment_focus_terms(text: str) -> set[str]:
        words = re.findall(r"\b[a-z][a-z0-9+\-]{3,}\b", (text or "").lower())
        stopwords = {
            "about", "also", "and", "are", "been", "being", "briefly", "companies",
            "company", "could", "does", "early", "examples", "experience", "experiences",
            "from", "have", "hear", "important", "just", "kind", "kinda", "last",
            "little", "looking", "more", "now", "question", "really", "roles", "scratch",
            "service", "services", "specifically", "start", "team", "teams", "tell",
            "that", "them", "then", "there", "they", "very", "want", "were", "what",
            "where", "with", "would", "your", "you", "product", "products",
        }
        return {word for word in words if word not in stopwords}

    def _should_merge_segments(self, previous: str, current: str) -> bool:
        if self._is_broad_intro_request(previous) or self._is_broad_intro_request(current):
            return False

        prev_terms = self._segment_focus_terms(previous)
        current_terms = self._segment_focus_terms(current)
        overlap = prev_terms & current_terms

        if overlap:
            return True

        previous_lower = previous.lower()
        current_lower = current.lower()
        paired_patterns = [
            ("team management", "teams you've managed"),
            ("build from 0", "building from 0"),
            ("build from zero", "building from zero"),
            ("what roles", "teams you've managed"),
        ]
        return any(left in previous_lower and right in current_lower for left, right in paired_patterns)

    @staticmethod
    def _merge_segment_pair(previous: str, current: str) -> str:
        previous_clean = previous.strip()
        current_clean = current.strip()
        if current_clean.lower() in previous_clean.lower():
            return previous_clean
        if previous_clean.lower() in current_clean.lower():
            return current_clean
        return f"{previous_clean}. {current_clean}"


    def _classify_family(self, ask_block: str) -> tuple[AskFamily, list[str]]:
        text = ask_block.lower()
        why: list[str] = []

        if self._matches_any(text, [r"you mentioned", r"tell me more", r"can you elaborate", r"going back to"]):
            why.append("Follow-up phrasing detected")
            return AskFamily.FOLLOW_UP_CLARIFICATION, why

        if self._matches_any(
            text,
            [
                r"what are you looking for",
                r"what('?s| is) important for you",
                r"what kind of things",
                r"what do you (absolutely )?(do not|don't) like",
                r"\bculture\b",
                r"team environment",
                r"expectations",
            ],
        ):
            why.append("Preference/culture-fit phrasing detected")
            return AskFamily.CULTURE_FIT, why

        if self._matches_any(text, [r"measure success", r"\bkpis?\b", r"\broi\b", r"\boutcomes?\b", r"\bmetrics?\b"]):
            why.append("Outcome/KPI phrasing detected")
            return AskFamily.METRICS_OUTCOMES, why

        if self._matches_any(
            text,
            [
                r"strategy",
                r"prioriti",
                r"stakeholder",
                r"business value",
                r"revenue",
                r"go-to-market",
                r"roadmap",
            ],
        ):
            why.append("Business/strategy phrasing detected")
            return AskFamily.BUSINESS_STRATEGY, why

        if self._matches_any(
            text,
            [
                r"architecture",
                r"system design",
                r"design a",
                r"architect",
                r"requirements",
                r"scalability",
                r"trade[- ]?offs?",
            ],
        ):
            why.append("Architecture/design phrasing detected")
            return AskFamily.ARCHITECTURE_DESIGN, why

        if self._matches_any(
            text,
            [
                r"what are",
                r"how does",
                r"best practices",
                r"compare",
                r"pros and cons",
                r"rag",
                r"vector",
                r"agentic",
                r"python",
                r"caching",
                r"observability",
                r"explain",
            ],
        ):
            why.append("Technical conceptual phrasing detected")
            return AskFamily.TECHNICAL_CONCEPT, why

        if self._matches_any(
            text,
            [
                r"experience",
                r"building from 0",
                r"building from zero",
                r"build from 0",
                r"build from zero",
                r"scratch",
                r"team management",
                r"teams you've managed",
                r"how big were the teams",
                r"what roles they have",
            ],
        ):
            why.append("Experience/scope phrasing detected")
            if self._looks_compound(text):
                why.append("Multiple asks detected in the same interviewer block")
                return AskFamily.MIXED_COMPOUND, why
            return AskFamily.EXPERIENCE_SCOPE, why

        if self._matches_any(
            text,
            [
                r"feature",
                r"user problem",
                r"customer problem",
                r"roadmap for",
                r"specific product",
                r"product strategy",
                r"product roadmap",
            ],
        ):
            why.append("Product/domain specific phrasing detected")
            return AskFamily.PRODUCT_SPECIFIC, why

        if self._matches_any(text, [r"tell me about a time", r"describe a time", r"give me an example"]):
            why.append("Technical experience/example phrasing detected")
            return AskFamily.TECHNICAL_EXPERIENCE, why

        if self._looks_compound(text):
            why.append("Compound interviewer block detected")
            return AskFamily.MIXED_COMPOUND, why

        why.append("No strong family match; using general direct family")
        return AskFamily.GENERAL, why

    def _contract_for_family(
        self,
        family: AskFamily,
        delivery_mode: str,
    ) -> tuple[AnswerContract, EvidencePolicy, MetricsPolicy, str]:
        if family == AskFamily.CULTURE_FIT:
            return (
                AnswerContract.PREFERENCES_AND_ANTI_PATTERNS,
                EvidencePolicy.LIGHT_PERSONAL_CONTEXT,
                MetricsPolicy.AVOID_UNLESS_REQUESTED,
                "State what matters, what you avoid, and why in plain interview language.",
            )
        if family == AskFamily.TECHNICAL_CONCEPT:
            return (
                AnswerContract.DIRECT_EXPLANATION,
                EvidencePolicy.CONCEPT_ONLY_UNLESS_HELPFUL,
                MetricsPolicy.AVOID_UNLESS_REQUESTED,
                "Explain the concept directly before adding any interview framing.",
            )
        if family == AskFamily.ARCHITECTURE_DESIGN:
            return (
                AnswerContract.ARCHITECTURE_WALKTHROUGH,
                EvidencePolicy.ARCHITECTURE_SIGNALS,
                MetricsPolicy.PREFER_IF_SUPPORTED,
                "Open with the design goal, then move through decisions and trade-offs.",
            )
        if family == AskFamily.PRODUCT_SPECIFIC:
            return (
                AnswerContract.PRODUCT_FIRST,
                EvidencePolicy.PRODUCT_DOMAIN_FIRST,
                MetricsPolicy.PREFER_IF_SUPPORTED,
                "Answer about the product or domain first, then attach relevant experience.",
            )
        if family == AskFamily.BUSINESS_STRATEGY:
            return (
                AnswerContract.BUSINESS_WITH_OUTCOMES,
                EvidencePolicy.BUSINESS_CONTEXT_WITH_SUPPORT,
                MetricsPolicy.REQUIRED,
                "Start with the strategic position and support it with outcomes.",
            )
        if family == AskFamily.METRICS_OUTCOMES:
            return (
                AnswerContract.OUTCOMES_REQUIRED,
                EvidencePolicy.REQUIRE_SUPPORTED_OUTCOMES,
                MetricsPolicy.REQUIRED,
                "Lead with the outcome definition and the metrics that prove it.",
            )
        if family == AskFamily.FOLLOW_UP_CLARIFICATION:
            return (
                AnswerContract.FOLLOW_UP_FOCUSED,
                EvidencePolicy.FOLLOW_UP_ONLY,
                MetricsPolicy.PREFER_IF_SUPPORTED,
                "Answer only the follow-up point before adding any broader context.",
            )
        if family in {AskFamily.EXPERIENCE_SCOPE, AskFamily.MIXED_COMPOUND, AskFamily.TECHNICAL_EXPERIENCE}:
            opening = (
                "Answer the main scope ask directly, then cover the remaining sub-asks in order."
                if delivery_mode == "realtime"
                else "Lead with the direct answer, then use 1-2 concrete examples in order."
            )
            return (
                AnswerContract.DIRECT_MULTI_PART,
                EvidencePolicy.EXAMPLES_FIRST,
                MetricsPolicy.PREFER_IF_SUPPORTED,
                opening,
            )
        return (
            AnswerContract.GENERAL_DIRECT,
            EvidencePolicy.BALANCED,
            MetricsPolicy.PREFER_IF_SUPPORTED,
            "Answer the main ask directly and only expand where it helps.",
        )

    def _score_confidence(
        self,
        ask_block: str,
        family: AskFamily,
        secondary_asks: list[str],
    ) -> float:
        score = 0.55
        if ask_block:
            score += 0.1
        if family != AskFamily.GENERAL:
            score += 0.1
        if secondary_asks:
            score += min(0.15, 0.05 * len(secondary_asks))
        if family in {AskFamily.CULTURE_FIT, AskFamily.TECHNICAL_CONCEPT, AskFamily.BUSINESS_STRATEGY, AskFamily.MIXED_COMPOUND}:
            score += 0.05
        return min(score, 0.95)

    @staticmethod
    def _matches_any(text: str, patterns: list[str]) -> bool:
        return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)

    @staticmethod
    def _looks_compound(text: str) -> bool:
        connectors = len(re.findall(r"\b(and|also|plus|then|y|además|también)\b", text))
        segments = len([segment for segment in re.split(r"[?.!]+", text) if segment.strip()])
        return connectors >= 2 or segments >= 2


def apply_ask_brief_policy(
    question_analysis: QuestionAnalysis,
    ask_brief: Optional[AskBrief],
    *,
    delivery_mode: str = "manual",
    confidence_threshold: float = 0.72,
) -> QuestionAnalysis:
    """Promote a high-confidence AskBrief into the effective analysis contract."""
    if question_analysis is None or ask_brief is None:
        return question_analysis

    question_analysis.ask_brief = ask_brief
    question_analysis.normalizer_applied = ask_brief.confidence >= confidence_threshold and not ask_brief.fallback_used
    question_analysis.normalizer_fallback_used = ask_brief.fallback_used

    if ask_brief.confidence < confidence_threshold or ask_brief.fallback_used:
        return question_analysis

    family = ask_brief.answer_family

    type_map = {
        AskFamily.CULTURE_FIT: QuestionType.CASUAL,
        AskFamily.TECHNICAL_CONCEPT: QuestionType.TECHNICAL,
        AskFamily.TECHNICAL_EXPERIENCE: QuestionType.TECHNICAL,
        AskFamily.ARCHITECTURE_DESIGN: QuestionType.TECHNICAL,
        AskFamily.PRODUCT_SPECIFIC: QuestionType.TECHNICAL,
        AskFamily.BUSINESS_STRATEGY: QuestionType.CASUAL,
        AskFamily.METRICS_OUTCOMES: QuestionType.CASUAL,
        AskFamily.FOLLOW_UP_CLARIFICATION: QuestionType.FOLLOW_UP,
        AskFamily.MIXED_COMPOUND: QuestionType.COMPOUND,
        AskFamily.EXPERIENCE_SCOPE: QuestionType.BEHAVIORAL,
    }
    mode_map = {
        AskFamily.CULTURE_FIT: QuestionMode.EXPERIENCE_BASED,
        AskFamily.TECHNICAL_CONCEPT: QuestionMode.CONCEPTUAL,
        AskFamily.TECHNICAL_EXPERIENCE: QuestionMode.EXPERIENCE_BASED,
        AskFamily.ARCHITECTURE_DESIGN: QuestionMode.CONCEPTUAL,
        AskFamily.PRODUCT_SPECIFIC: QuestionMode.CONCEPTUAL,
        AskFamily.BUSINESS_STRATEGY: QuestionMode.MIXED,
        AskFamily.METRICS_OUTCOMES: QuestionMode.MIXED,
        AskFamily.FOLLOW_UP_CLARIFICATION: QuestionMode.MIXED,
        AskFamily.MIXED_COMPOUND: QuestionMode.MIXED,
        AskFamily.EXPERIENCE_SCOPE: QuestionMode.EXPERIENCE_BASED,
    }
    response_mode_map = {
        AskFamily.TECHNICAL_CONCEPT: ResponseMode.COACH_EXPLAINER,
        AskFamily.ARCHITECTURE_DESIGN: ResponseMode.COACH_EXPLAINER,
        AskFamily.PRODUCT_SPECIFIC: ResponseMode.COACH_EXPLAINER,
        AskFamily.BUSINESS_STRATEGY: ResponseMode.INTERVIEW_ANSWER,
        AskFamily.METRICS_OUTCOMES: ResponseMode.INTERVIEW_ANSWER,
        AskFamily.CULTURE_FIT: ResponseMode.INTERVIEW_ANSWER,
        AskFamily.EXPERIENCE_SCOPE: ResponseMode.INTERVIEW_ANSWER,
        AskFamily.MIXED_COMPOUND: ResponseMode.INTERVIEW_ANSWER,
    }
    intent_map = {
        AskFamily.CULTURE_FIT: AnswerIntent.PRINCIPLE,
        AskFamily.TECHNICAL_CONCEPT: AnswerIntent.EXPLANATION,
        AskFamily.TECHNICAL_EXPERIENCE: AnswerIntent.EXAMPLE,
        AskFamily.ARCHITECTURE_DESIGN: AnswerIntent.TRADEOFF,
        AskFamily.PRODUCT_SPECIFIC: AnswerIntent.EXPLANATION,
        AskFamily.BUSINESS_STRATEGY: AnswerIntent.BUSINESS_VALUE,
        AskFamily.METRICS_OUTCOMES: AnswerIntent.BUSINESS_VALUE,
        AskFamily.FOLLOW_UP_CLARIFICATION: AnswerIntent.MIXED,
        AskFamily.MIXED_COMPOUND: AnswerIntent.MIXED,
        AskFamily.EXPERIENCE_SCOPE: AnswerIntent.EXAMPLE,
    }
    style_map = {
        AskFamily.CULTURE_FIT: ResponseStyle.MIXED,
        AskFamily.TECHNICAL_CONCEPT: ResponseStyle.TECHNICAL,
        AskFamily.TECHNICAL_EXPERIENCE: ResponseStyle.TECHNICAL,
        AskFamily.ARCHITECTURE_DESIGN: ResponseStyle.TECHNICAL,
        AskFamily.PRODUCT_SPECIFIC: ResponseStyle.TECHNICAL,
        AskFamily.BUSINESS_STRATEGY: ResponseStyle.COMMERCIAL,
        AskFamily.METRICS_OUTCOMES: ResponseStyle.COMMERCIAL,
        AskFamily.FOLLOW_UP_CLARIFICATION: ResponseStyle.MIXED,
        AskFamily.MIXED_COMPOUND: ResponseStyle.MIXED,
        AskFamily.EXPERIENCE_SCOPE: ResponseStyle.MIXED,
    }

    question_analysis.primary_type = type_map.get(family, question_analysis.primary_type)
    question_analysis.question_mode = mode_map.get(family, question_analysis.question_mode)
    question_analysis.response_mode = response_mode_map.get(family, question_analysis.response_mode)
    question_analysis.answer_intent = intent_map.get(family, question_analysis.answer_intent)
    question_analysis.recommended_style = style_map.get(family, question_analysis.recommended_style)
    question_analysis.is_compound = family == AskFamily.MIXED_COMPOUND or len(ask_brief.secondary_asks) > 0
    question_analysis.why_metrics_required = ask_brief.metrics_policy == MetricsPolicy.REQUIRED
    question_analysis.style_reason = (
        f"AskNormalizer authoritative for {delivery_mode}: "
        f"family={family.value}, contract={ask_brief.answer_contract.value}, "
        f"confidence={ask_brief.confidence:.2f}"
    )

    sub_questions = [SubQuestion(
        text=ask_brief.primary_ask,
        type=question_analysis.primary_type,
        priority=Priority.MUST_ANSWER,
        weight=1.0,
    )]
    for idx, text in enumerate(ask_brief.secondary_asks[:4], start=1):
        sub_questions.append(
            SubQuestion(
                text=text,
                type=question_analysis.primary_type,
                priority=Priority.MUST_ANSWER if idx == 1 else Priority.SHOULD_ANSWER,
                weight=0.8 if idx == 1 else 0.6,
            )
        )
    if ask_brief.primary_ask:
        question_analysis.sub_questions = sub_questions

    response_structure_map = {
        AnswerContract.DIRECT_MULTI_PART: [
            "Answer the main ask first",
            "Cover secondary asks in order",
            "Keep any introduction brief and last",
        ],
        AnswerContract.PREFERENCES_AND_ANTI_PATTERNS: [
            "What I look for",
            "What I avoid",
            "Why it matters",
        ],
        AnswerContract.DIRECT_EXPLANATION: [
            "Direct answer",
            "Key principles or trade-offs",
            "Short practical takeaway",
        ],
        AnswerContract.ARCHITECTURE_WALKTHROUGH: [
            "Goal and constraints",
            "Major design choices",
            "Trade-offs and risks",
        ],
        AnswerContract.BUSINESS_WITH_OUTCOMES: [
            "Clear position",
            "Business reasoning",
            "Outcomes/KPI lens",
        ],
        AnswerContract.OUTCOMES_REQUIRED: [
            "Direct answer",
            "Supported outcomes",
            "Business implication",
        ],
    }
    question_analysis.response_structure = response_structure_map.get(
        ask_brief.answer_contract,
        question_analysis.response_structure,
    )
    return question_analysis
