import asyncio

from pipeline.steps.cv_analyzer import CVAnalyzer, CVAnalyzerMode


SAMPLE_CV = """
DANIEL ALARCON RAMIREZ
Technology Director, Data & AI

EXECUTIVE SUMMARY

Technology executive with 20 years leading enterprise transformation across software modernization and the full data lifecycle.
Global leadership scope managing 20 direct managers and 345 indirect reports across multiple regions.

KEY ACHIEVEMENTS

- Expanded adoption from Top 100 portfolio to 17+ accounts.
- Led core banking modernization across 6+ enterprise clients and 100+ applications, delivering up to 40% OPEX reduction within 12 months.
- Improved time-to-impact by 30% via standardized delivery workflows.

AREAS OF EXPERTISE

- Operating Model & Governance
- Data Lifecycle
- Enterprise Modernization
- KPI Systems

PROFESSIONAL EXPERIENCE

Globant — Technology Director, Data & AI (Global)
2022 – Present
"""


def test_structured_cv_analyzer_extracts_real_summary_skills_and_achievements():
    analyzer = CVAnalyzer(mode=CVAnalyzerMode.DEMO)

    result = asyncio.run(analyzer.analyze(SAMPLE_CV))

    assert result.success is True
    assert result.mode == "real"
    assert result.profile.name == "Daniel Alarcon Ramirez"
    assert result.profile.current_role == "Technology Director, Data & AI"
    assert result.profile.summary.startswith("Technology executive with 20 years")
    assert "Operating Model & Governance" in result.profile.skills
    assert any("Expanded adoption from Top 100 portfolio to 17+ accounts" in item for item in result.profile.achievements)
    assert any("40% OPEX reduction" in item for item in result.profile.metrics)
    assert result.profile.company == "Globant"


def test_structured_cv_analyzer_avoids_generic_placeholder_profile_when_cv_has_structure():
    analyzer = CVAnalyzer(mode=CVAnalyzerMode.DEMO)

    result = asyncio.run(analyzer.analyze(SAMPLE_CV))

    assert "0+ years in the industry" not in result.profile.summary
    assert result.profile.skills != ["Leadership", "Strategy", "Team Building"]
    assert result.profile.achievements != ["Led teams", "Delivered projects", "Drove growth"]


def test_structured_cv_analyzer_keeps_parenthetical_skill_groups_intact():
    analyzer = CVAnalyzer(mode=CVAnalyzerMode.DEMO)

    result = asyncio.run(
        analyzer.analyze(
            """
            DANA SAMPLE
            Principal Data Architect

            EXECUTIVE SUMMARY
            Principal leader with 15 years in data platforms and modernization.

            AREAS OF EXPERTISE
            ▪ Data Lifecycle (Analytics, Risk, CX)\t▪ Multi-Region Team Leadership

            PROFESSIONAL EXPERIENCE
            Example Corp — Principal Data Architect
            2020 – Present
            """
        )
    )

    assert result.success is True
    assert "Data Lifecycle (Analytics, Risk, CX)" in result.profile.skills
    assert "Analytics" not in result.profile.skills
    assert "Risk" not in result.profile.skills
    assert "CX)" not in result.profile.skills


def test_structured_cv_analyzer_returns_unavailable_when_cv_has_insufficient_signal():
    analyzer = CVAnalyzer(mode=CVAnalyzerMode.DEMO)

    result = asyncio.run(
        analyzer.analyze(
            "linkedin.com/in/sample-profile-without-usable-candidate-identity\n"
            "contact@test.example\n"
            "http://portfolio.example.com/no-clear-role-or-company-details\n"
            "+57 300 000 0000"
        )
    )

    assert result.success is False
    assert result.mode == "unavailable"
    assert "Complete Prepare manually" in (result.error or "")
