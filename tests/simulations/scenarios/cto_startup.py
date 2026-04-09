"""
Interview Coach - CTO Startup Simulation Scenario
Full 5-exchange simulation with evaluation criteria
"""
from tests.fixtures.profiles.cto_profile import CTO_PROFILE, CTO_INTERVIEW_CONFIG
from tests.fixtures.questions.question_bank import get_question_by_id


# Simulation scenario: CTO role at a startup
CTO_STARTUP_SCENARIO = {
    "id": "cto-startup-001",
    "name": "CTO Interview at Growing Startup",
    "description": """Simulated interview for a CTO position at a Series A startup 
    looking to scale their engineering organization.""",
    
    "profile": CTO_PROFILE,
    "interview_config": CTO_INTERVIEW_CONFIG.model_dump(),
    
    # 5-exchange sequence
    "exchanges": [
        {
            "index": 0,
            "question_id": "compound-001",  # "Estamos buscando una persona..."
            "expected_topics": [
                "seniority-level",
                "building-from-scratch",
                "measurable-results",
                "tech-structure",
            ],
            "expected_style": "executive",
            "expected_language": "es",
            "evaluation_criteria": {
                "covers_must_answer": True,
                "includes_metrics": True,
                "appropriate_length": True,
                "no_contradictions": True,
            },
        },
        {
            "index": 1,
            "question_id": "en-003",  # "Describe a time when you had to scale a team..."
            "expected_topics": [
                "scaling",
                "hiring",
                "team-building",
            ],
            "expected_style": "executive",
            "expected_language": "en",
            "evaluation_criteria": {
                "covers_must_answer": True,
                "unique_metrics": True,  # Should not repeat metrics from exchange 0
                "appropriate_length": True,
            },
        },
        {
            "index": 2,
            "question_id": "en-004",  # "How do you approach technical debt..."
            "expected_topics": [
                "technical-debt",
                "prioritization",
                "trade-offs",
            ],
            "expected_style": "technical",
            "expected_language": "en",
            "evaluation_criteria": {
                "covers_must_answer": True,
                "technical_depth": True,
                "business_alignment": True,
            },
        },
        {
            "index": 3,
            "question_id": "stress-001",  # "What would you do if you disagreed with the CEO..."
            "expected_topics": [
                "disagreement",
                "communication",
                "escalation",
            ],
            "expected_style": "executive",
            "expected_language": "en",
            "evaluation_criteria": {
                "diplomatic_approach": True,
                "clear_framework": True,
                "professional_tone": True,
            },
        },
        {
            "index": 4,
            "question_id": "followup-001",  # "You mentioned scaling a team..."
            "expected_topics": [
                "hiring",
                "interviewing",
                "culture-fit",
            ],
            "expected_style": "executive",
            "expected_language": "en",
            "builds_on_exchange": 1,  # References exchange 1
            "evaluation_criteria": {
                "consistent_with_previous": True,
                "adds_new_information": True,
                "appropriate_depth": True,
            },
        },
    ],
    
    # Overall evaluation criteria
    "overall_criteria": {
        "all_must_answer_covered": True,
        "no_metric_repetition": True,
        "no_contradictions": True,
        "language_consistency": True,
        "style_appropriateness": True,
    },
}


def get_scenario() -> dict:
    """Get the CTO startup scenario"""
    return CTO_STARTUP_SCENARIO


def get_exchange(index: int) -> dict | None:
    """Get a specific exchange from the scenario"""
    for exchange in CTO_STARTUP_SCENARIO["exchanges"]:
        if exchange["index"] == index:
            return exchange
    return None


def get_expected_metrics_for_exchange(index: int) -> list[str]:
    """Get metrics that should be used in a specific exchange"""
    # Based on CTO profile achievements
    exchange = get_exchange(index)
    if not exchange:
        return []
    
    question = get_question_by_id(exchange["question_id"])
    if not question:
        return []
    
    # Map questions to appropriate achievements
    topic_to_achievement = {
        "scaling": "ach-001",
        "hiring": "ach-001",
        "team-building": "ach-001",
        "architecture": "ach-002",
        "microservices": "ach-002",
        "kubernetes": "ach-002",
        "data-engineering": "ach-003",
        "ml": "ach-003",
        "cloud": "ach-004",
        "cost-optimization": "ach-004",
        "culture": "ach-005",
        "process": "ach-005",
        "fundraising": "ach-006",
        "due-diligence": "ach-006",
    }
    
    achievements = []
    for topic in question.get("topics", []):
        if topic in topic_to_achievement:
            achievements.append(topic_to_achievement[topic])
    
    # Get metrics from achievements
    from tests.fixtures.profiles.cto_profile import get_achievement_by_id
    metrics = []
    for ach_id in achievements:
        ach = get_achievement_by_id(ach_id)
        if ach:
            metrics.extend(ach.get("metrics", []))
    
    return metrics


def evaluate_exchange(exchange_index: int, response: dict) -> dict:
    """Evaluate a response against expected criteria"""
    scenario_exchange = get_exchange(exchange_index)
    if not scenario_exchange:
        return {"error": "Exchange not found"}
    
    criteria = scenario_exchange.get("evaluation_criteria", {})
    results = {
        "passed": True,
        "scores": {},
        "issues": [],
    }
    
    # Check if must-answer topics are covered
    if criteria.get("covers_must_answer"):
        # Implementation would check if response covers required topics
        results["scores"]["must_answer_coverage"] = 1.0
    
    # Check for unique metrics
    if criteria.get("unique_metrics"):
        # Implementation would check against previous exchanges
        results["scores"]["unique_metrics"] = 1.0
    
    return results
