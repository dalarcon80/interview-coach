"""
Interview Coach - Question Bank Fixtures
Real interview questions for testing (ES/EN/mixed)
Includes quality gate fail/pass cases and language policy cases
"""
from typing import Optional

# Question Bank - 13 real interview questions
QUESTION_BANK = [
    # ===========================================
    # SPANISH QUESTIONS
    # ===========================================
    {
        "id": "es-001",
        "text": "Cuéntame sobre ti y tu experiencia profesional.",
        "type": "behavioral",
        "language": "es",
        "expected_sub_questions": 2,
        "topics": ["background", "experience", "narrative"],
    },
    {
        "id": "es-002",
        "text": "¿Cuál ha sido tu mayor logro profesional y por qué?",
        "type": "behavioral",
        "language": "es",
        "expected_sub_questions": 2,
        "topics": ["achievement", "impact", "reflection"],
    },
    {
        "id": "es-003",
        "text": "¿Cómo manejas los conflictos dentro de tu equipo?",
        "type": "behavioral",
        "language": "es",
        "expected_sub_questions": 1,
        "topics": ["leadership", "conflict-resolution", "team-management"],
    },
    {
        "id": "es-004",
        "text": "Describe una situación donde tuviste que tomar una decisión técnica difícil.",
        "type": "technical",
        "language": "es",
        "expected_sub_questions": 2,
        "topics": ["technical-decision", "trade-offs", "architecture"],
    },
    
    # ===========================================
    # ENGLISH QUESTIONS
    # ===========================================
    {
        "id": "en-001",
        "text": "Tell me about yourself and your professional background.",
        "type": "behavioral",
        "language": "en",
        "expected_sub_questions": 2,
        "topics": ["background", "experience", "narrative"],
    },
    {
        "id": "en-002",
        "text": "What's been your biggest professional achievement and why?",
        "type": "behavioral",
        "language": "en",
        "expected_sub_questions": 2,
        "topics": ["achievement", "impact", "reflection"],
    },
    {
        "id": "en-003",
        "text": "Describe a time when you had to scale a team or organization.",
        "type": "behavioral",
        "language": "en",
        "expected_sub_questions": 3,
        "topics": ["scaling", "hiring", "team-building", "culture"],
    },
    {
        "id": "en-004",
        "text": "How do you approach technical debt in a fast-growing company?",
        "type": "technical",
        "language": "en",
        "expected_sub_questions": 2,
        "topics": ["technical-debt", "prioritization", "trade-offs"],
    },
    
    # ===========================================
    # COMPOUND QUESTIONS (multi-part)
    # ===========================================
    {
        "id": "compound-001",
        "text": "Estamos buscando una persona que ocupe el rol de CTO en la compañía, la cual debe poder dar estructura no solo a nivel tecnológico, sino a nivel operativo alineado con las necesidades internas y de nuestros clientes, que permita traer resultados medibles. Para eso nos gustaría saber tu experiencia, si has tenido oportunidad de crear equipos desde cero, cuéntanos más sobre ti.",
        "type": "compound",
        "language": "es",
        "expected_sub_questions": 7,
        "topics": [
            "seniority-level",
            "tech-structure",
            "operational-structure",
            "internal-clients-focus",
            "measurable-results",
            "building-from-scratch",
            "personal-narrative",
        ],
        "sub_question_priorities": {
            "seniority-level": "must_answer",
            "building-from-scratch": "must_answer",
            "measurable-results": "must_answer",
            "tech-structure": "should_answer",
            "operational-structure": "should_answer",
            "internal-clients-focus": "nice_to_have",
            "personal-narrative": "should_answer",
        },
    },
    {
        "id": "compound-002",
        "text": "We're looking for someone who can lead our engineering organization through a period of rapid growth. Can you tell us about a time when you had to balance technical excellence with business speed, how did you handle it, and what were the results?",
        "type": "compound",
        "language": "en",
        "expected_sub_questions": 4,
        "topics": [
            "leadership-experience",
            "technical-excellence",
            "business-speed",
            "balance-trade-offs",
            "results-metrics",
        ],
        "sub_question_priorities": {
            "leadership-experience": "must_answer",
            "balance-trade-offs": "must_answer",
            "results-metrics": "must_answer",
            "technical-excellence": "should_answer",
            "business-speed": "should_answer",
        },
    },
    
    # ===========================================
    # STRESS QUESTIONS
    # ===========================================
    {
        "id": "stress-001",
        "text": "What would you do if you disagreed with the CEO about a critical technical decision?",
        "type": "stress",
        "language": "en",
        "expected_sub_questions": 2,
        "topics": ["disagreement", "communication", "escalation", "compromise"],
    },
    
    # ===========================================
    # FOLLOW-UP QUESTIONS
    # ===========================================
    {
        "id": "followup-001",
        "text": "You mentioned scaling a team - can you elaborate on the hiring process you used?",
        "type": "follow_up",
        "language": "en",
        "expected_sub_questions": 1,
        "topics": ["hiring", "interviewing", "culture-fit"],
        "builds_on_exchange": 0,  # Follows first exchange
    },
    
    # ===========================================
    # MIXED LANGUAGE (bilingual)
    # ===========================================
    {
        "id": "mixed-001",
        "text": "Cuéntame sobre tu experiencia con microservices architecture y cómo lo aplicaste en producción.",
        "type": "technical",
        "language": "mixed",
        "expected_sub_questions": 2,
        "topics": ["architecture", "microservices", "production-experience"],
        "expected_final_language": "es",  # Dominant language
    },
    
    # ===========================================
    # QUALITY GATE TEST CASES
    # ===========================================
    {
        "id": "qg-fail-001",
        "text": "Test question for quality gate - response should fail due to repetition",
        "type": "behavioral",
        "language": "en",
        "should_fail_quality_gate": True,
        "fail_reason": "metric_repetition",
        "preexisting_metrics": ["15 engineers", "3x growth"],
    },
    {
        "id": "qg-fail-002",
        "text": "Test question for quality gate - response should fail due to contradiction",
        "type": "behavioral",
        "language": "en",
        "should_fail_quality_gate": True,
        "fail_reason": "contradiction",
        "preexisting_claims": ["I built the team from scratch"],
    },
    {
        "id": "qg-fail-003",
        "text": "Test question for quality gate - response should fail due to language mismatch",
        "type": "behavioral",
        "language": "es",
        "should_fail_quality_gate": True,
        "fail_reason": "language_mismatch",
        "expected_language": "es",
    },
    
    # ===========================================
    # LANGUAGE POLICY TEST CASES
    # ===========================================
    {
        "id": "lp-001",
        "text": "Completely Spanish utterance for testing",
        "type": "behavioral",
        "language": "es",
        "expected_language": "es",
        "language_method": "dominant",
        "expected_confidence": 0.95,
    },
    {
        "id": "lp-002",
        "text": "Completely English utterance for testing",
        "type": "behavioral",
        "language": "en",
        "expected_language": "en",
        "language_method": "dominant",
        "expected_confidence": 0.95,
    },
    {
        "id": "lp-003",
        "text": "Spanish utterance with English technical terms like Kubernetes and microservices",
        "type": "technical",
        "language": "mixed",
        "expected_language": "es",
        "language_method": "dominant",
        "expected_confidence": 0.85,
    },
]


def get_question_by_id(question_id: str) -> Optional[dict]:
    """Get a question by its ID"""
    for q in QUESTION_BANK:
        if q["id"] == question_id:
            return q
    return None


def get_questions_by_type(q_type: str) -> list[dict]:
    """Get all questions of a specific type"""
    return [q for q in QUESTION_BANK if q.get("type") == q_type]


def get_questions_by_language(language: str) -> list[dict]:
    """Get all questions in a specific language"""
    return [q for q in QUESTION_BANK if q.get("language") == language]


def get_quality_gate_fail_cases() -> list[dict]:
    """Get all quality gate fail test cases"""
    return [q for q in QUESTION_BANK if q.get("should_fail_quality_gate") is True]


def get_language_policy_cases() -> list[dict]:
    """Get all language policy test cases"""
    return [q for q in QUESTION_BANK if "expected_language" in q]


def get_compound_questions() -> list[dict]:
    """Get all compound (multi-part) questions"""
    return [q for q in QUESTION_BANK if q.get("type") == "compound"]
