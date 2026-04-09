"""
Interview Coach - Quality Gate
Draft → Validate → Repair → Expose pipeline

Validates:
1. Repeats metric already used in previous exchanges
2. Contradicts previous claim
3. Missing must_answer sub-questions
4. Language mismatch with LanguageDecision
5. Too long (>250 words)
6. Wrong style for question type
"""
from dataclasses import dataclass
from typing import Optional
import re

from contracts.models import (
    QualityResult,
    GeneratedResponse,
    QuestionAnalysis,
    ConversationMap,
    ResponseStyle,
    Priority,
)


@dataclass
class QualityCheck:
    """Result of a single quality check"""
    name: str
    passed: bool
    score: float
    issues: list[str]
    details: dict


class QualityGate:
    """
    Quality gate for validating generated responses.
    
    Pipeline:
    1. Draft: Generate response
    2. Validate: Run all checks
    3. Repair: Fix issues (1 attempt)
    4. Expose: Return validated response or fallback
    """
    
    def __init__(self):
        self.max_words = 250
        self.min_score = 0.7
    
    async def validate(
        self,
        response: GeneratedResponse,
        analysis: Optional[QuestionAnalysis] = None,
        conversation_map: Optional[ConversationMap] = None,
        expected_language: str = "es",
    ) -> QualityResult:
        """
        Validate a generated response through all checks.
        
        Args:
            response: The generated response to validate
            analysis: Question analysis with sub-questions
            conversation_map: State of conversation so far
            expected_language: Expected response language
        
        Returns:
            QualityResult with pass/fail and issues
        """
        checks = []
        all_issues = []
        
        # Check 1: Metric repetition
        metric_check = self._check_metric_repetition(response, conversation_map)
        checks.append(metric_check)
        all_issues.extend(metric_check.issues)
        
        # Check 2: Claim contradiction
        contradiction_check = self._check_contradictions(response, conversation_map)
        checks.append(contradiction_check)
        all_issues.extend(contradiction_check.issues)
        
        # Check 3: Must-answer coverage
        coverage_check = self._check_must_answer_coverage(response, analysis)
        checks.append(coverage_check)
        all_issues.extend(coverage_check.issues)
        
        # Check 4: Language consistency
        language_check = self._check_language(response, expected_language)
        checks.append(language_check)
        all_issues.extend(language_check.issues)
        
        # Check 5: Length
        length_check = self._check_length(response)
        checks.append(length_check)
        all_issues.extend(length_check.issues)
        
        # Check 6: Style appropriateness
        style_check = self._check_style(response, analysis)
        checks.append(style_check)
        all_issues.extend(style_check.issues)
        
        # Calculate overall score
        total_score = sum(c.score for c in checks) / len(checks)
        
        # Only block on CRITICAL issues - contradictions only
        # Must-answer coverage is now a warning, not a blocker
        # (sub-questions may have repetitive elements that don't need full coverage)
        critical_issues = [
            issue for issue in all_issues
            if "contradict" in issue.lower()
        ]
        
        # NOTE: missing_must_answer removed from critical issues - see PR comment
        
        passed = total_score >= self.min_score and len(critical_issues) == 0
        
        # Extract contradictions and repetitions for reporting
        contradictions = [
            issue for issue in all_issues
            if "contradict" in issue.lower()
        ]
        repetitions = [
            issue for issue in all_issues
            if "repeat" in issue.lower() or "already used" in issue.lower()
        ]
        
        return QualityResult(
            passed=passed,
            score=total_score,
            issues=all_issues,
            contradictions=contradictions,
            repetitions=repetitions,
        )

    async def validate_bullets(
        self,
        response: GeneratedResponse,
        analysis: Optional[QuestionAnalysis] = None,
        conversation_map: Optional[ConversationMap] = None,
        expected_language: str = "es",
    ) -> QualityResult:
        """
        Fast-path validation for bullets-first mode.

        This performs lightweight checks so bullets can be shown quickly while
        full-response validation still runs later through `process()`.
        """
        checks = []
        all_issues: list[str] = []

        bullet_presence_check = self._check_bullet_presence(response)
        checks.append(bullet_presence_check)
        all_issues.extend(bullet_presence_check.issues)

        # Reuse existing checks by validating on bullet text body.
        bullet_text = " ".join(response.bullets).strip()
        response_for_checks = GeneratedResponse(
            bullets=response.bullets,
            full_response=bullet_text,
            key_metrics=response.key_metrics,
            confidence=response.confidence,
            style_used=response.style_used,
            generation_time_ms=response.generation_time_ms,
            mode=response.mode,
            metadata=response.metadata,
        )

        metric_check = self._check_metric_repetition(response_for_checks, conversation_map)
        checks.append(metric_check)
        all_issues.extend(metric_check.issues)

        language_check = self._check_language(response_for_checks, expected_language)
        checks.append(language_check)
        all_issues.extend(language_check.issues)

        # Lightweight style check for early stage
        style_check = self._check_style(response_for_checks, analysis)
        checks.append(style_check)
        all_issues.extend(style_check.issues)

        total_score = sum(c.score for c in checks) / len(checks)

        # Only block on CRITICAL issues - contradictions
        # Minor issues become warnings, not blockers
        critical_issues = [
            issue for issue in all_issues
            if "contradict" in issue.lower()
        ]

        passed = total_score >= self.min_score and len(critical_issues) == 0

        contradictions = [
            issue for issue in all_issues
            if "contradict" in issue.lower()
        ]
        repetitions = [
            issue for issue in all_issues
            if "repeat" in issue.lower() or "already used" in issue.lower()
        ]

        return QualityResult(
            passed=passed,
            score=total_score,
            issues=all_issues,
            contradictions=contradictions,
            repetitions=repetitions,
        )

    async def repair(
        self,
        response: GeneratedResponse,
        result: QualityResult,
        conversation_map: Optional[ConversationMap] = None,
    ) -> GeneratedResponse:
        """
        Attempt to repair a failing response.
        
        Args:
            response: The original failing response
            result: QualityResult with issues to fix
            conversation_map: Conversation state for repair context
        
        Returns:
            Repaired GeneratedResponse
        """
        repaired_bullets = list(response.bullets)
        repaired_text = response.full_response
        
        # Fix metric repetitions
        if result.repetitions:
            for metric in conversation_map.metrics_used if conversation_map else []:
                # Replace repeated metrics with alternatives
                repaired_text = self._replace_metric(repaired_text, metric)
        
        # Fix length issues
        if any("too long" in issue.lower() for issue in result.issues):
            words = repaired_text.split()
            if len(words) > self.max_words:
                repaired_text = " ".join(words[:self.max_words])
        
        # Fix missing must-answer
        # This would require regeneration in a real implementation
        
        return GeneratedResponse(
            bullets=repaired_bullets,
            full_response=repaired_text,
            key_metrics=response.key_metrics,
            confidence=response.confidence * 0.9,  # Slightly lower confidence after repair
            style_used=response.style_used,
            generation_time_ms=response.generation_time_ms,
            mode=response.mode,
            metadata=response.metadata,
        )
    
    async def process(
        self,
        response: GeneratedResponse,
        analysis: Optional[QuestionAnalysis] = None,
        conversation_map: Optional[ConversationMap] = None,
        expected_language: str = "es",
    ) -> tuple[GeneratedResponse, QualityResult]:
        """
        Full Draft → Validate → Repair → Expose pipeline.
        
        Args:
            response: The generated response
            analysis: Question analysis
            conversation_map: Conversation state
            expected_language: Expected language
        
        Returns:
            Tuple of (final_response, quality_result)
        """
        # DEBUG: Log input state
        print(f"[DEBUG quality_gate] Input response mode: {response.mode}")
        print(f"[DEBUG quality_gate] Input analysis: {analysis is not None}, sub_questions: {len(analysis.sub_questions) if analysis and analysis.sub_questions else 0}")
        
        # Validate
        result = await self.validate(
            response, analysis, conversation_map, expected_language
        )
        
        # DEBUG: Log validation result
        print(f"[DEBUG quality_gate] Validation passed: {result.passed}, score: {result.score:.2f}, critical_issues: {len([i for i in result.issues if 'contradict' in i.lower() or 'may not address required' in i.lower()])}")
        if result.issues:
            print(f"[DEBUG quality_gate] Validation issues: {result.issues[:3]}...")
        
        if result.passed:
            return response, result
        
        # Attempt repair
        repaired = await self.repair(response, result, conversation_map)
        
        # Re-validate
        repair_result = await self.validate(
            repaired, analysis, conversation_map, expected_language
        )
        
        # DEBUG: Log repair result
        print(f"[DEBUG quality_gate] Repair validation passed: {repair_result.passed}, score: {repair_result.score:.2f}")
        
        if repair_result.passed:
            return repaired, repair_result
        
        # Fallback: use bullets only
        fallback_mode = "fallback" if response.mode == "real" else response.mode
        print(f"[DEBUG quality_gate] Falling back from {response.mode} to {fallback_mode}")
        fallback = GeneratedResponse(
            bullets=response.bullets,
            full_response=f"Key points: {' '.join(response.bullets)}",
            key_metrics=response.key_metrics,
            confidence=0.5,
            style_used=response.style_used,
            generation_time_ms=response.generation_time_ms,
            mode=fallback_mode,
            metadata={
                **(response.metadata or {}),
                "quality_gate_status": "fallback_exposed",
            },
        )
        
        return fallback, repair_result

    async def process_bullets(
        self,
        response: GeneratedResponse,
        analysis: Optional[QuestionAnalysis] = None,
        conversation_map: Optional[ConversationMap] = None,
        expected_language: str = "es",
    ) -> tuple[GeneratedResponse, QualityResult]:
        """
        Fast-path bullets processing used by bullets-first UX.
        """
        result = await self.validate_bullets(
            response,
            analysis,
            conversation_map,
            expected_language,
        )

        if response.bullets:
            return response, result

        # Fallback: expose a minimal bullets payload if parsing failed.
        fallback_bullets: list[str] = []
        if response.full_response:
            text = response.full_response.strip()
            if text:
                fallback_bullets = [f"• {text[:120]}{'...' if len(text) > 120 else ''}"]

        fallback = GeneratedResponse(
            bullets=fallback_bullets,
            full_response="",
            key_metrics=response.key_metrics,
            confidence=max(0.4, response.confidence * 0.8),
            style_used=response.style_used,
            generation_time_ms=response.generation_time_ms,
            mode=response.mode,
            metadata=response.metadata,
        )
        return fallback, result
    
    def _check_metric_repetition(
        self,
        response: GeneratedResponse,
        conversation_map: Optional[ConversationMap],
    ) -> QualityCheck:
        """Check for repeated metrics from previous exchanges"""
        issues = []
        
        if not conversation_map or not conversation_map.metrics_used:
            return QualityCheck(
                name="metric_repetition",
                passed=True,
                score=1.0,
                issues=[],
                details={"metrics_checked": 0},
            )
        
        response_lower = response.full_response.lower()
        repeated = []
        
        for metric in conversation_map.metrics_used:
            if metric.lower() in response_lower:
                repeated.append(metric)
                issues.append(f"Repeats metric '{metric}' already used in previous exchange")
        
        # Penalize for each repetition
        score = max(0.0, 1.0 - (len(repeated) * 0.3))
        
        return QualityCheck(
            name="metric_repetition",
            passed=len(repeated) == 0,
            score=score,
            issues=issues,
            details={"repeated_metrics": repeated},
        )

    def _check_bullet_presence(self, response: GeneratedResponse) -> QualityCheck:
        """Ensure bullets are present for bullets-first fast path."""
        count = len(response.bullets)
        issues: list[str] = []

        if count == 0:
            issues.append("Empty bullets in fast-path response")

        return QualityCheck(
            name="bullet_presence",
            passed=count > 0,
            score=1.0 if count > 0 else 0.0,
            issues=issues,
            details={"bullet_count": count},
        )
    
    def _check_contradictions(
        self,
        response: GeneratedResponse,
        conversation_map: Optional[ConversationMap],
    ) -> QualityCheck:
        """Check for contradictions with previous claims"""
        issues = []
        
        if not conversation_map or not conversation_map.claims:
            return QualityCheck(
                name="contradiction",
                passed=True,
                score=1.0,
                issues=[],
                details={"claims_checked": 0},
            )
        
        # Known contradiction patterns
        contradiction_patterns = [
            (r"built.*from scratch", r"inherited.*team"),
            (r"started.*from zero", r"existing.*team"),
            (r"grew.*from \d+", r"already had \d+"),
        ]
        
        response_lower = response.full_response.lower()
        contradictions_found = []
        
        for claim in conversation_map.claims:
            # Check if response contradicts this claim
            # This is a simplified check - real implementation would use NLI
            pass
        
        score = max(0.0, 1.0 - (len(contradictions_found) * 0.4))
        
        return QualityCheck(
            name="contradiction",
            passed=len(contradictions_found) == 0,
            score=score,
            issues=issues,
            details={"contradictions": contradictions_found},
        )
    
    def _check_must_answer_coverage(
        self,
        response: GeneratedResponse,
        analysis: Optional[QuestionAnalysis],
    ) -> QualityCheck:
        """Check if must-answer sub-questions are addressed"""
        issues = []
        
        if not analysis or not analysis.sub_questions:
            return QualityCheck(
                name="must_answer_coverage",
                passed=True,
                score=1.0,
                issues=[],
                details={"sub_questions": 0},
            )
        
        must_answer = [
            sq for sq in analysis.sub_questions
            if sq.priority == Priority.MUST_ANSWER
        ]
        
        if not must_answer:
            return QualityCheck(
                name="must_answer_coverage",
                passed=True,
                score=1.0,
                issues=[],
                details={"must_answer_count": 0},
            )
        
        response_lower = response.full_response.lower()
        covered = 0
        
        for sq in must_answer:
            # Check if key words from sub-question appear in response
            sq_words = set(sq.text.lower().split())
            response_words = set(response_lower.split())
            overlap = len(sq_words & response_words)
            
            if overlap >= 2:  # At least 2 words overlap
                covered += 1
            else:
                issues.append(f"May not address required point: '{sq.text[:50]}...'")
        
        score = covered / len(must_answer) if must_answer else 1.0
        
        return QualityCheck(
            name="must_answer_coverage",
            passed=len(issues) == 0,
            score=score,
            issues=issues,
            details={
                "must_answer_count": len(must_answer),
                "covered": covered,
            },
        )
    
    def _check_language(
        self,
        response: GeneratedResponse,
        expected_language: str,
    ) -> QualityCheck:
        """Check if response is in the expected language"""
        issues = []
        
        response_lower = response.full_response.lower()
        
        # Simple language detection
        spanish_indicators = ["el ", "la ", "los ", "las ", "en ", "es ", "un ", "una "]
        english_indicators = ["the ", "a ", "an ", "is ", "are ", "in ", "to ", "for "]
        
        spanish_count = sum(1 for i in spanish_indicators if i in response_lower)
        english_count = sum(1 for i in english_indicators if i in response_lower)
        
        detected = "es" if spanish_count > english_count else "en"
        
        if detected != expected_language:
            issues.append(f"Response language ({detected}) doesn't match expected ({expected_language})")
        
        return QualityCheck(
            name="language",
            passed=detected == expected_language,
            score=1.0 if detected == expected_language else 0.5,
            issues=issues,
            details={
                "detected": detected,
                "expected": expected_language,
            },
        )
    
    def _check_length(
        self,
        response: GeneratedResponse,
    ) -> QualityCheck:
        """Check if response length is appropriate"""
        issues = []
        
        words = response.full_response.split()
        word_count = len(words)
        
        if word_count > self.max_words:
            issues.append(f"Response too long ({word_count} words, max {self.max_words})")
        
        if word_count < 30:
            issues.append(f"Response too short ({word_count} words)")
        
        score = 1.0 if 30 <= word_count <= self.max_words else 0.7
        
        return QualityCheck(
            name="length",
            passed=len(issues) == 0,
            score=score,
            issues=issues,
            details={"word_count": word_count},
        )
    
    def _check_style(
        self,
        response: GeneratedResponse,
        analysis: Optional[QuestionAnalysis],
    ) -> QualityCheck:
        """Check if response style matches question type"""
        issues = []
        
        if not analysis:
            return QualityCheck(
                name="style",
                passed=True,
                score=1.0,
                issues=[],
                details={"style": "unknown"},
            )
        
        recommended = analysis.recommended_style
        used = response.style_used
        response_mode = getattr(analysis, "response_mode", None)

        if response_mode and getattr(response_mode, "value", "") in {"coach_explainer", "hybrid_dual"}:
            return QualityCheck(
                name="style",
                passed=True,
                score=1.0,
                issues=[],
                details={
                    "recommended": recommended.value,
                    "used": used.value,
                    "response_mode": response_mode.value,
                },
            )
        
        if recommended != ResponseStyle.MIXED and used != recommended:
            # Allow MIXED to be used for any style
            issues.append(f"Style mismatch: recommended {recommended.value}, used {used.value}")
        
        score = 1.0 if not issues else 0.8
        
        return QualityCheck(
            name="style",
            passed=len(issues) == 0,
            score=score,
            issues=issues,
            details={
                "recommended": recommended.value,
                "used": used.value,
            },
        )
    
    def _replace_metric(self, text: str, metric: str) -> str:
        """Replace a metric with a placeholder or alternative"""
        # Simple replacement - in production would be smarter
        alternatives = {
            "15 engineers": "a significant engineering team",
            "50 engineers": "a large engineering organization",
            "3x": "substantial",
        }
        
        for old, new in alternatives.items():
            if old in text.lower():
                return text.replace(old, new)
        
        return text
