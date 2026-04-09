"""
Interview Coach - CV Analyzer
Analyzes CVs and extracts structured profile data

## IMPLEMENTATION STATUS

This module supports two extraction paths:
1. **Structured extraction**: Deterministic parsing from the real CV text
2. **LLM extraction**: Optional LLM enrichment when an API key is configured

No demo candidate profiles are generated. If the CV does not provide
enough signal to build a usable profile, analysis should fail clearly.
"""
import os
from typing import Optional
from dataclasses import dataclass, field
from enum import Enum
import json
import re


class CVAnalyzerMode(str, Enum):
    """CV analyzer operation mode"""
    DEMO = "demo"
    REAL = "real"
    AUTO = "auto"


@dataclass
class CVProfile:
    """Structured CV profile data"""
    name: str = ""
    email: Optional[str] = None
    current_role: str = ""
    company: Optional[str] = None
    summary: str = ""
    years_experience: int = 0
    skills: list[str] = field(default_factory=list)
    achievements: list[str] = field(default_factory=list)
    # Company attribution for achievements - maps achievement index to company name
    achievement_companies: dict[int, str] = field(default_factory=dict)
    leadership_roles: list[str] = field(default_factory=list)
    technical_stack: list[str] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    # All companies mentioned in the CV (for reference)
    all_companies: list[str] = field(default_factory=list)


@dataclass
class CVAnalysisResult:
    """Result of CV analysis"""
    success: bool
    mode: str
    profile: CVProfile
    highlights: list[str]
    suggested_talking_points: list[str]
    analysis_summary: str
    strengths: list[str]
    gaps: list[str]
    recommendations: list[str]
    confidence: float
    error: Optional[str] = None


class CVAnalyzer:
    """
    Analyzes CVs to extract structured profile data.

    In REAL mode, uses LLM for intelligent parsing when available.
    In DEMO mode, keeps backward compatibility by using deterministic
    structured extraction from the real CV text. It never returns
    synthetic candidate profiles.
    """

    @staticmethod
    def from_environment() -> "CVAnalyzer":
        """
        Construct analyzer using CV_ANALYZER_MODE env var.
        Supported values: auto | real | demo (default: auto).
        `demo` remains accepted for backward compatibility but does not
        generate demo candidate data.
        """
        mode_raw = os.getenv("CV_ANALYZER_MODE", "auto").strip().lower()
        if mode_raw == "real":
            mode = CVAnalyzerMode.REAL
        elif mode_raw == "demo":
            mode = CVAnalyzerMode.DEMO
        else:
            mode = CVAnalyzerMode.AUTO

        return CVAnalyzer(mode=mode)
    
    def __init__(self, mode: CVAnalyzerMode = CVAnalyzerMode.AUTO):
        self.mode = mode
        self._api_checked = False
        self._api_available = False
        self._provider = None
    
    def _check_api_availability(self) -> bool:
        """Check if LLM API is available"""
        if self._api_checked:
            return self._api_available
        
        if os.getenv("ANTHROPIC_API_KEY"):
            self._api_available = True
            self._provider = "anthropic"
        elif os.getenv("OPENAI_API_KEY"):
            self._api_available = True
            self._provider = "openai"
        
        self._api_checked = True
        return self._api_available
    
    def get_mode(self) -> str:
        """Get current operation mode label exposed to callers."""
        return "real" if self._api_available else "real"
    
    async def analyze(self, cv_text: str) -> CVAnalysisResult:
        """
        Analyze CV text and extract structured data.
        
        Args:
            cv_text: Raw CV/resume text
            
        Returns:
            CVAnalysisResult with extracted profile data
        """
        if not cv_text or len(cv_text.strip()) < 50:
            return CVAnalysisResult(
                success=False,
                mode="error",
                profile=CVProfile(),
                highlights=[],
                suggested_talking_points=[],
                analysis_summary="",
                strengths=[],
                gaps=[],
                recommendations=[],
                confidence=0.0,
                error="CV text too short for analysis"
            )
        
        # Check API availability
        self._check_api_availability()
        
        if self._api_available and self.mode != CVAnalyzerMode.DEMO:
            return await self._analyze_real(cv_text)
        return await self._analyze_demo(cv_text)
    
    async def _analyze_demo(self, cv_text: str) -> CVAnalysisResult:
        """
        Deterministic structured extraction without LLM.
        """
        lines = [line.strip() for line in cv_text.splitlines() if line.strip()]
        potential_name = self._extract_name(lines)
        email = self._extract_email(cv_text)
        years = self._extract_years_experience(cv_text)
        company, current_role = self._extract_current_experience(lines)
        summary = self._extract_summary(cv_text)
        role_titles = self._extract_role_titles(cv_text)
        all_companies = self._extract_companies(cv_text)
        if not company and all_companies:
            company = all_companies[0]
        skills = self._extract_skills(cv_text)
        achievements = self._extract_achievements(cv_text)
        technical_stack = self._extract_technical_stack(cv_text)
        metrics = self._extract_metrics(cv_text, achievements, years)

        if not current_role:
            current_role = role_titles[0] if role_titles else ""
        if not summary:
            summary = self._build_summary_from_profile(current_role=current_role, years=years, achievements=achievements)

        profile = CVProfile(
            name=potential_name,
            email=email,
            current_role=current_role,
            company=company,
            summary=summary,
            years_experience=years,
            skills=skills,
            achievements=achievements,
            achievement_companies={},
            leadership_roles=role_titles[:3],
            technical_stack=technical_stack,
            metrics=metrics,
            all_companies=all_companies,
        )

        strengths = self._build_strengths(profile)
        recommendations = self._build_recommendations(profile)
        gaps = self._build_gaps(profile)

        result = CVAnalysisResult(
            success=True,
            mode="real",
            profile=profile,
            highlights=strengths,
            suggested_talking_points=recommendations,
            analysis_summary=(
                f"Structured CV extraction completed for {profile.name or 'the candidate'} "
                f"using deterministic parsing."
            ),
            strengths=strengths,
            gaps=gaps,
            recommendations=recommendations,
            confidence=0.68 if achievements or skills else 0.45,
        )
        if not self._has_minimum_profile_signal(result.profile):
            return CVAnalysisResult(
                success=False,
                mode="unavailable",
                profile=CVProfile(),
                highlights=[],
                suggested_talking_points=[],
                analysis_summary="",
                strengths=[],
                gaps=[],
                recommendations=[],
                confidence=0.0,
                error="Could not extract enough real candidate data from the CV. Complete Prepare manually.",
            )
        return result

    @staticmethod
    def _has_minimum_profile_signal(profile: CVProfile) -> bool:
        return bool(
            profile.name.strip()
            and (
                profile.current_role.strip()
                or profile.summary.strip()
                or profile.company
                or profile.skills
                or profile.achievements
            )
        )

    @staticmethod
    def _extract_name(lines: list[str]) -> str:
        for line in lines[:4]:
            if (
                len(line) <= 60
                and not re.search(r"@|\+?\d{3,}", line)
                and not any(token in line.lower() for token in ("linkedin", "http", "|"))
            ):
                return line.title() if line.isupper() else line
        return ""

    @staticmethod
    def _extract_email(cv_text: str) -> Optional[str]:
        match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", cv_text)
        return match.group(0) if match else None

    @staticmethod
    def _extract_years_experience(cv_text: str) -> int:
        match = re.search(r"(\d{1,2})\+?\s*years?\s*(?:of\s+)?experience", cv_text, re.IGNORECASE)
        return int(match.group(1)) if match else 0

    @staticmethod
    def _extract_current_experience(lines: list[str]) -> tuple[Optional[str], str]:
        for index, line in enumerate(lines[:24]):
            if "—" in line or " - " in line:
                left, right = re.split(r"\s+[—-]\s+", line, maxsplit=1)
                company = left.strip() or None
                role = re.split(r"\s+\(", right, maxsplit=1)[0].strip()
                if role and not CVAnalyzer._looks_like_heading(company or ""):
                    return company, role
            if index == 1 and len(line) <= 80 and not re.search(r"@|\+?\d{3,}", line):
                return None, line
        return None, ""

    @staticmethod
    def _extract_summary(cv_text: str) -> str:
        patterns = [
            r"EXECUTIVE SUMMARY\s+(.*?)(?:\n\s*\n[A-Z][A-Z\s&/]{3,}|\Z)",
            r"PROFESSIONAL SUMMARY\s+(.*?)(?:\n\s*\n[A-Z][A-Z\s&/]{3,}|\Z)",
            r"SUMMARY\s+(.*?)(?:\n\s*\n[A-Z][A-Z\s&/]{3,}|\Z)",
        ]
        for pattern in patterns:
            match = re.search(pattern, cv_text, re.IGNORECASE | re.DOTALL)
            if match:
                summary = CVAnalyzer._normalize_snippet(match.group(1))
                if summary:
                    return summary

        for paragraph in re.split(r"\n\s*\n", cv_text):
            normalized = CVAnalyzer._normalize_snippet(paragraph)
            if len(normalized) >= 80 and not normalized.isupper():
                return normalized
        return ""

    @staticmethod
    def _extract_role_titles(cv_text: str) -> list[str]:
        pattern = re.compile(
            r"\b(?:Technology Director|Director|Head|Manager|Lead|Principal|Staff|Architect|Consultant|Engineer)\b(?:[^,\n|()]*)",
            re.IGNORECASE,
        )
        seen: list[str] = []
        for match in pattern.findall(cv_text):
            normalized = CVAnalyzer._normalize_snippet(match)
            if normalized and normalized.lower() not in {item.lower() for item in seen}:
                seen.append(normalized)
            if len(seen) >= 5:
                break
        return seen

    @staticmethod
    def _extract_companies(cv_text: str) -> list[str]:
        matches = re.findall(r"^([A-Z][^\n—-]{1,60})\s+[—-]\s+[^\n]+$", cv_text, re.MULTILINE)
        companies: list[str] = []
        for match in matches:
            normalized = CVAnalyzer._normalize_snippet(match)
            if (
                normalized
                and not CVAnalyzer._looks_like_heading(normalized)
                and normalized.lower() not in {item.lower() for item in companies}
            ):
                companies.append(normalized)
        return companies

    @staticmethod
    def _extract_section_bullets(cv_text: str, section_names: list[str], limit: int) -> list[str]:
        section_pattern = "|".join(re.escape(name) for name in section_names)
        match = re.search(
            rf"(?:{section_pattern})\s+(.*?)(?:\n\s*\n[A-Z][A-Z\s&/]{3,}|\Z)",
            cv_text,
            re.IGNORECASE | re.DOTALL,
        )
        candidates: list[str] = []
        if match:
            block = match.group(1)
            for raw_line in block.splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                if re.search(r"[▪•]", line):
                    parts = [part.strip() for part in re.split(r"[▪•]\s*", line) if part.strip()]
                    candidates.extend(parts)
                    continue
                if re.match(r"^-\s+", line):
                    candidates.append(re.sub(r"^-\s+", "", line))
        if not candidates:
            candidates.extend(re.findall(r"^[▪•\-]\s*(.+)$", cv_text, re.MULTILINE))
        result: list[str] = []
        for item in candidates:
            normalized = CVAnalyzer._normalize_snippet(item)
            if normalized and normalized.lower() not in {entry.lower() for entry in result}:
                result.append(normalized)
            if len(result) >= limit:
                break
        return result

    @staticmethod
    def _extract_skills(cv_text: str) -> list[str]:
        bullets = CVAnalyzer._extract_section_bullets(
            cv_text,
            ["AREAS OF EXPERTISE", "CORE SKILLS", "KEY SKILLS", "SKILLS"],
            limit=10,
        )
        if bullets:
            skills: list[str] = []
            for bullet in bullets:
                for token in re.split(r"\t|•|\|| {2,}|;", bullet):
                    normalized = CVAnalyzer._normalize_snippet(token)
                    if normalized and normalized.lower() not in {item.lower() for item in skills}:
                        skills.append(normalized)
                    if len(skills) >= 10:
                        return skills
            if skills:
                return skills

        keyword_order = [
            "AWS",
            "Azure",
            "GCP",
            "Python",
            "Spark",
            "dbt",
            "Terraform",
            "Generative AI",
            "GenAI",
            "Data Engineering",
            "Data Architecture",
            "Modernization",
            "Consulting",
            "Core Banking Modernization",
        ]
        detected: list[str] = []
        lowered = cv_text.lower()
        for keyword in keyword_order:
            if keyword.lower() in lowered:
                detected.append(keyword)
        return detected[:8]

    @staticmethod
    def _extract_achievements(cv_text: str) -> list[str]:
        achievements = CVAnalyzer._extract_section_bullets(
            cv_text,
            ["KEY ACHIEVEMENTS", "ACHIEVEMENTS", "OUTCOMES", "RESULTS"],
            limit=6,
        )
        if achievements:
            return achievements

        sentences = re.split(r"(?<=[.!?])\s+", cv_text.replace("\n", " "))
        ranked: list[str] = []
        for sentence in sentences:
            normalized = CVAnalyzer._normalize_snippet(sentence)
            if not normalized:
                continue
            if re.search(r"\d|%|accounts?|clients?|applications?|reduction|improved|expanded|led|built", normalized, re.IGNORECASE):
                ranked.append(normalized)
            if len(ranked) >= 5:
                break
        return ranked[:5]

    @staticmethod
    def _extract_technical_stack(cv_text: str) -> list[str]:
        stack_keywords = [
            "AWS",
            "Azure",
            "GCP",
            "Spark",
            "Python",
            "dbt",
            "Terraform",
            "Databricks",
            "Snowflake",
            "GenAI",
            "AI",
            "Data",
            "Cloud",
        ]
        lowered = cv_text.lower()
        stack = [keyword for keyword in stack_keywords if keyword.lower() in lowered]
        return stack[:8]

    @staticmethod
    def _extract_metrics(cv_text: str, achievements: list[str], years: int) -> list[str]:
        metrics = re.findall(
            r"(?:\bup to\s+)?\d+%[^\n.]*|\b\d+\+?\s+(?:accounts?|clients?|applications?|assets?|projects?|initiatives?|reports?)\b[^\n.]*",
            cv_text,
            re.IGNORECASE,
        )
        normalized: list[str] = []
        for metric in [*achievements, *metrics]:
            item = CVAnalyzer._normalize_snippet(metric)
            if item and re.search(r"\d", item) and item.lower() not in {entry.lower() for entry in normalized}:
                normalized.append(item)
            if len(normalized) >= 6:
                break
        if not normalized and years:
            normalized.append(f"{years}+ years experience")
        return normalized

    @staticmethod
    def _build_summary_from_profile(*, current_role: str, years: int, achievements: list[str]) -> str:
        lead = current_role.strip()
        if achievements:
            if lead and years:
                return f"{lead} with {years}+ years of experience focused on {achievements[0].rstrip('.')}."
            if lead:
                return f"{lead} focused on {achievements[0].rstrip('.')}."
            if years:
                return f"{years}+ years of experience focused on {achievements[0].rstrip('.')}."
            return achievements[0].rstrip(".")
        if years:
            if lead:
                return f"{lead} with {years}+ years of experience across technology transformation and delivery."
            return f"{years}+ years of experience across technology transformation and delivery."
        return lead

    @staticmethod
    def _build_strengths(profile: CVProfile) -> list[str]:
        strengths: list[str] = []
        if profile.years_experience:
            strengths.append(f"{profile.years_experience}+ years of experience")
        if profile.current_role:
            strengths.append(f"Current role identified as {profile.current_role}")
        if profile.achievements:
            strengths.append("Achievement evidence extracted from the CV")
        if profile.skills:
            strengths.append("Core skills detected from expertise and experience sections")
        return strengths[:4]

    @staticmethod
    def _build_recommendations(profile: CVProfile) -> list[str]:
        recommendations: list[str] = []
        if profile.achievements:
            recommendations.append("Use the strongest quantified achievements when answering impact questions")
        else:
            recommendations.append("Add quantified outcomes to strengthen evidence for interview answers")
        if profile.current_role:
            recommendations.append("Anchor answers in your current role and leadership scope")
        if profile.technical_stack:
            recommendations.append("Name the architecture, cloud, and platform choices behind the outcomes")
        recommendations.append("Review extracted skills and achievements before using them in live coaching")
        return recommendations[:4]

    @staticmethod
    def _build_gaps(profile: CVProfile) -> list[str]:
        gaps: list[str] = []
        if not profile.achievements:
            gaps.append("No clear achievement bullets were detected from the CV text")
        if not profile.skills:
            gaps.append("No structured skills section was detected from the CV text")
        if not profile.summary:
            gaps.append("No clear summary section was detected from the CV text")
        return gaps[:3]

    @staticmethod
    def _normalize_snippet(value: str) -> str:
        snippet = re.sub(r"\s+", " ", str(value or "").replace("▪", " ").replace("•", " ").strip())
        return snippet.strip(" -\t")

    @staticmethod
    def _looks_like_heading(value: str) -> bool:
        normalized = CVAnalyzer._normalize_snippet(value)
        if not normalized:
            return True
        alpha = re.sub(r"[^A-Za-z]+", "", normalized)
        if alpha and alpha.isupper():
            return True
        return normalized.lower() in {
            "executive summary",
            "professional summary",
            "summary",
            "key achievements",
            "achievements",
            "areas of expertise",
            "core skills",
            "skills",
            "professional experience",
            "education",
            "certifications",
            "languages",
        }
    
    async def _analyze_real(self, cv_text: str) -> CVAnalysisResult:
        """
        Real analysis using LLM.
        """
        try:
            from adapters.llm_adapter import get_llm_adapter
            
            adapter = get_llm_adapter()
            if adapter is None:
                return await self._analyze_demo(cv_text)
            
            # Build prompt for CV analysis
            system_prompt = """You are an expert CV analyzer. Extract structured information from the provided CV/resume.

Return ONLY valid JSON with this exact structure:
{
  "name": "Full Name",
  "email": "email@example.com or null",
  "current_role": "Current job title",
  "company": "Current company or null",
  "summary": "2-3 sentence professional summary",
  "years_experience": 10,
  "skills": ["skill1", "skill2", ...],
  "achievements": ["achievement1", "achievement2", ...],
  "achievement_companies": {"0": "company_name", "1": "company_name", ...},
  "all_companies": ["company1", "company2", ...],
  "leadership_roles": ["role1", "role2", ...],
  "technical_stack": ["tech1", "tech2", ...],
  "metrics": ["metric1", "metric2", ...],
  "analysis_summary": "Short paragraph summary",
  "strengths": ["strength1", "strength2"],
  "gaps": ["gap1", "gap2"],
  "recommendations": ["recommendation1", "recommendation2"]
}

CRITICAL: For achievement_companies, map each achievement (by index) to the company it was from.
If an achievement's company is unknown, use "Unknown" as the value.
For all_companies, list ALL companies mentioned anywhere in the CV.

Be concise and accurate. Extract only information clearly present in the CV."""

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Analyze this CV:\n\n{cv_text}"}
            ]
            
            config = {"temperature": 0.1, "max_tokens": 1024}
            response = await adapter.generate(messages, config)
            
            # Parse JSON response
            # Handle potential markdown code blocks
            json_text = response.strip()
            if json_text.startswith("```"):
                # Remove markdown code block
                lines = json_text.split("\n")
                json_text = "\n".join(lines[1:-1])
            
            data = json.loads(json_text)
            
            # Parse achievement companies - convert string keys to int
            achievement_companies_raw = data.get("achievement_companies", {})
            achievement_companies = {}
            for k, v in achievement_companies_raw.items():
                try:
                    achievement_companies[int(k)] = v
                except (ValueError, TypeError):
                    pass
            
            profile = CVProfile(
                name=data.get("name", ""),
                email=data.get("email"),
                current_role=data.get("current_role", ""),
                company=data.get("company"),
                summary=data.get("summary", ""),
                years_experience=data.get("years_experience", 0),
                skills=data.get("skills", []),
                achievements=data.get("achievements", []),
                achievement_companies=achievement_companies,
                all_companies=data.get("all_companies", []),
                leadership_roles=data.get("leadership_roles", []),
                technical_stack=data.get("technical_stack", []),
                metrics=data.get("metrics", []),
            )
            
            highlights = data.get("highlights") or data.get("strengths") or profile.achievements[:5]
            strengths = data.get("strengths") or profile.skills[:5]
            gaps = data.get("gaps") or []
            recommendations = data.get("recommendations") or [
                f"Discuss {profile.current_role} experience",
                f"Highlight {profile.years_experience} years in the industry",
                "Share specific achievements with metrics",
            ]

            return CVAnalysisResult(
                success=True,
                mode="real",
                profile=profile,
                highlights=highlights,
                suggested_talking_points=recommendations,
                analysis_summary=data.get("analysis_summary") or profile.summary,
                strengths=strengths,
                gaps=gaps,
                recommendations=recommendations,
                confidence=0.9,
            )
            
        except json.JSONDecodeError as e:
            result = await self._analyze_demo(cv_text)
            result.error = f"LLM response parse error: {str(e)}"
            return result
        except Exception as e:
            result = await self._analyze_demo(cv_text)
            result.error = str(e)
            return result
