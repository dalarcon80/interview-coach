"""
Interview Coach - Retrieval Planner
Plans evidence retrieval strategy
"""
import re
from dataclasses import dataclass
from typing import Optional

from contracts.models import QuestionAnalysis, QuestionType


@dataclass
class RetrievalPlan:
    """Plan for evidence retrieval"""
    achievement_queries: list[str]
    cv_queries: list[str]
    job_desc_queries: list[str]
    top_k: int
    min_relevance: float
    # Company filtering - if specified, only retrieve evidence from this company
    company_filter: str = ""
    # Profile ID - if specified, only retrieve evidence from this profile
    profile_id: str = ""
    # Optional company/interviewer context IDs for research-backed evidence
    company_context_id: str = ""
    interviewer_context_id: str = ""


class RetrievalPlanner:
    """
    Plans retrieval strategy based on question analysis.
    """
    
    def plan(
        self,
        analysis: QuestionAnalysis,
        role_title: str = "",
        company_name: str = "",
        candidate_skills: Optional[list[str]] = None,
        company_requirements: Optional[list[str]] = None,
        candidate_summary: str = "",
        question_text: str = "",
        profile_id: str = "",
        company_context_id: str = "",
        interviewer_context_id: str = "",
    ) -> RetrievalPlan:
        """Create a retrieval plan"""
        queries: list[str] = []
        candidate_skills = candidate_skills or []
        company_requirements = company_requirements or []
        
        # Extract company filter from question if it mentions a specific company
        company_filter = self._extract_company_from_question(question_text, company_name)

        def _add_query(value: str) -> None:
            cleaned = (value or "").strip()
            if cleaned:
                queries.append(cleaned)
        
        # Generate queries from topics
        for topic in analysis.key_topics[:3]:
            _add_query(f"{topic} experience")
        
        # Add role-specific queries
        if role_title:
            _add_query(f"{role_title} responsibilities")

        # Add company+role grounding queries
        if company_name and role_title:
            _add_query(f"{company_name} {role_title} impact")

        # Add requirement-informed queries
        for requirement in company_requirements[:3]:
            _add_query(f"{requirement} example")

        # Add candidate skill grounding queries
        for skill in candidate_skills[:3]:
            _add_query(f"{skill} project outcome")

        if candidate_summary:
            summary_hint = candidate_summary.split(".")[0][:120].strip()
            if summary_hint:
                _add_query(summary_hint)

        # Deduplicate preserving order
        deduped_queries = list(dict.fromkeys(queries))

        cv_queries = [f"experience {topic}" for topic in analysis.key_topics[:2]]
        cv_queries.extend([f"skill {skill}" for skill in candidate_skills[:2]])
        cv_queries = list(dict.fromkeys([q for q in cv_queries if q.strip()]))

        job_desc_queries = []
        if role_title:
            job_desc_queries.append(f"{role_title} requirements")
        if company_name:
            job_desc_queries.append(f"{company_name} culture expectations")
        job_desc_queries.extend(company_requirements[:2])
        job_desc_queries = list(dict.fromkeys([q for q in job_desc_queries if q.strip()]))

        return RetrievalPlan(
            achievement_queries=deduped_queries[:7],
            cv_queries=cv_queries[:5],
            job_desc_queries=job_desc_queries[:5],
            top_k=5,
            min_relevance=0.5,
            company_filter=company_filter,
            profile_id=profile_id,
            company_context_id=company_context_id,
            interviewer_context_id=interviewer_context_id,
        )
    
    def _extract_company_from_question(
        self,
        question_text: str,
        current_company: str = "",
    ) -> str:
        """
        Extract company name from question if it specifically asks about a previous company.
        
        This enables evidence retrieval to be filtered by company when the question
        explicitly mentions a previous employer (e.g., "Tell me about your experience at Xertica").
        Uses case-insensitive matching and generic pattern detection.
        """
        if not question_text:
            return ""

        # Generic pattern: detect "at <CompanyName>" or "in <CompanyName>" where CompanyName
        # starts with an uppercase letter (proper noun). Case-insensitive prefix match.
        # Also handles phrases like "role in Xertica", "experience at Accenture", etc.
        patterns = [
            # "at <ProperNoun>" - most common
            r"\bat\s+([A-Z][A-Za-z0-9&.\-]+(?:\s+[A-Z][A-Za-z0-9&.\-]+)*)",
            # "in <ProperNoun>" after role/experience/work keywords
            r"(?:role|experience|work|time|position)\s+in\s+([A-Z][A-Za-z0-9&.\-]+(?:\s+[A-Z][A-Za-z0-9&.\-]+)*)",
            # "when you were at <ProperNoun>"
            r"when\s+you\s+were\s+at\s+([A-Z][A-Za-z0-9&.\-]+(?:\s+[A-Z][A-Za-z0-9&.\-]+)*)",
        ]

        # Skip words that are not company names
        skip_words = {"your", "you", "current", "now", "the", "a", "an", "previous",
                      "prior", "former", "last", "this", "that", "our", "their"}

        for pattern in patterns:
            match = re.search(pattern, question_text, re.IGNORECASE)
            if match:
                company = match.group(1).strip().rstrip(".,!?")
                if company.lower() not in skip_words and len(company) > 1:
                    return company

        return ""
