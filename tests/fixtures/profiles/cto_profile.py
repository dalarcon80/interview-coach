"""
Interview Coach - CTO Profile Fixture
Test profile with 6 achievements and verifiable metrics
"""
import sys
from pathlib import Path

# Add python-core to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "python-core"))

from contracts.models import ResponseStyle, InterviewConfig


# CTO Profile - Test fixture
CTO_PROFILE = {
    "name": "Carlos Mendoza",
    "title": "CTO / VP of Engineering",
    "summary": """Technology executive with 15+ years of experience building and scaling 
engineering organizations. Expert in transforming early-stage startups into 
growth-ready companies through technical leadership, team building, and 
strategic technology decisions.""",
    
    "experience_years": 15,
    
    "achievements": [
        {
            "id": "ach-001",
            "title": "Scaled Engineering Team from 5 to 50",
            "context": "Joined an early-stage fintech startup as the first engineering leader",
            "action": "Built the engineering organization from 5 to 50 engineers in 18 months, establishing hiring processes, career ladders, and engineering culture",
            "result": "Delivered 3 major products and increased platform reliability to 99.9% uptime",
            "metrics": ["5 to 50 engineers", "18 months", "99.9% uptime", "3 products"],
            "tags": ["hiring", "scaling", "culture", "leadership"],
        },
        {
            "id": "ach-002",
            "title": "Led Platform Migration to Microservices",
            "context": "Monolithic application was limiting development velocity and causing frequent outages",
            "action": "Designed and executed migration to microservices architecture with Kubernetes, establishing CI/CD pipelines and observability stack",
            "result": "Reduced deployment time from 2 weeks to 30 minutes and improved system resilience",
            "metrics": ["2 weeks to 30 minutes deployment", "95% reduction in outages", "10x deployment frequency"],
            "tags": ["architecture", "kubernetes", "microservices", "devops"],
        },
        {
            "id": "ach-003",
            "title": "Built Data Platform from Scratch",
            "context": "Company needed real-time analytics and ML capabilities to serve customers",
            "action": "Architected and built data platform with Kafka, Spark, and ML pipelines, hiring specialized data engineers",
            "result": "Enabled real-time fraud detection reducing false positives by 60%",
            "metrics": ["$2M annual savings", "60% reduction in false positives", "real-time processing"],
            "tags": ["data-engineering", "ml", "real-time", "fraud-detection"],
        },
        {
            "id": "ach-004",
            "title": "Reduced Cloud Costs by 40%",
            "context": "AWS costs were growing faster than revenue, threatening unit economics",
            "action": "Led comprehensive cost optimization initiative including architecture changes, reserved instances, and FinOps practices",
            "result": "Reduced monthly cloud spend from $200K to $120K while maintaining performance",
            "metrics": ["40% cost reduction", "$80K monthly savings", "$960K annual savings"],
            "tags": ["cloud", "aws", "finops", "cost-optimization"],
        },
        {
            "id": "ach-005",
            "title": "Established Engineering Culture",
            "context": "Engineering team lacked clear processes, leading to inconsistent quality",
            "action": "Introduced engineering principles, code review practices, technical RFCs, and on-call rotations with proper compensation",
            "result": "Improved developer satisfaction scores from 3.2 to 4.5/5 and reduced voluntary turnover from 25% to 8%",
            "metrics": ["3.2 to 4.5 satisfaction", "25% to 8% turnover", "RFC process adopted"],
            "tags": ["culture", "process", "developer-experience", "retention"],
        },
        {
            "id": "ach-006",
            "title": "Led Due Diligence for Series B",
            "context": "Company preparing for $50M Series B fundraise",
            "action": "Prepared technical documentation, architecture reviews, and security audits for investor due diligence",
            "result": "Successfully closed Series B with positive technical feedback from investors",
            "metrics": ["$50M Series B", "clean technical due diligence", "no remediation required"],
            "tags": ["fundraising", "due-diligence", "security", "documentation"],
        },
    ],
    
    "skills": [
        "Technical Leadership",
        "Engineering Management",
        "System Architecture",
        "Cloud Infrastructure (AWS, GCP)",
        "Kubernetes & Microservices",
        "Data Engineering",
        "Hiring & Team Building",
        "Agile Methodologies",
        "Technical Strategy",
        "Startup Scaling",
    ],
    
    "values": [
        "Engineering Excellence",
        "Developer Experience",
        "Transparent Communication",
        "Data-Driven Decisions",
        "Continuous Learning",
    ],
}

# Default interview config for CTO profile
CTO_INTERVIEW_CONFIG = InterviewConfig(
    company_name="Tech Startup",
    role_title="CTO",
    job_description="""Looking for a CTO to lead our engineering organization through 
the next phase of growth. Must have experience scaling teams, making strategic 
technical decisions, and working closely with founders.""",
    company_values=["Innovation", "Transparency", "Customer Focus", "Excellence"],
    response_style=ResponseStyle.EXECUTIVE,
    language_preference="auto",
)


def get_cto_profile() -> dict:
    """Get the CTO test profile"""
    return CTO_PROFILE


def get_cto_achievements() -> list[dict]:
    """Get CTO achievements list"""
    return CTO_PROFILE["achievements"]


def get_cto_metrics() -> list[str]:
    """Get all metrics from CTO achievements"""
    metrics = []
    for achievement in CTO_PROFILE["achievements"]:
        metrics.extend(achievement.get("metrics", []))
    return metrics


def get_achievement_by_id(achievement_id: str) -> dict | None:
    """Get a specific achievement by ID"""
    for achievement in CTO_PROFILE["achievements"]:
        if achievement["id"] == achievement_id:
            return achievement
    return None
