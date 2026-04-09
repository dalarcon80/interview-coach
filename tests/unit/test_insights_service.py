import asyncio
import base64

import pytest

from pipeline.steps.insights_service import InsightsService


SAMPLE_CV = """
Daniel Alarcon Ramirez
Technology Director, Data & AI

Technology executive with 20 years leading enterprise transformation across software modernization and the full data lifecycle.
Global leadership scope managing 20 direct managers and 345 indirect reports across multiple regions.
Designed and scaled a subscription-based delivery model driving C-level adoption and measurable improvements in cost efficiency.

Achievements
- Expanded adoption from Top 100 portfolio to 17+ accounts.
- Led core banking modernization across 6+ enterprise clients and 100+ applications, delivering up to 40% OPEX reduction within 12 months.
- Improved time-to-impact by 30% via standardized delivery workflows.
"""


def build_payload():
    return {
        "candidate_profile": {
            "name": "Daniel Alarcon Ramirez",
            "current_role": "Technology Director, Data & AI",
            "years_experience": 20,
            "skills": ["Data Strategy", "Modernization", "Executive Stakeholder Management"],
            "education": "",
            "languages": ["Spanish", "English"],
            "certifications": [],
            "summary": "",
            "achievements": [
                "Expanded adoption from Top 100 portfolio to 17+ accounts",
                "Led core banking modernization across 100+ applications with 40% OPEX reduction",
            ],
            "target_role": "",
            "industry": "Financial Services",
            "location": "Bogota, Colombia",
            "cv_text": SAMPLE_CV,
        },
        "company_info": {
            "name": "Slalom",
            "industry": "Consulting",
            "role_title": "Director of Data Engineering",
            "role_level": "director",
            "role_requirements": [
                "Data engineering leadership",
                "Cloud platforms",
                "Client delivery",
            ],
            "role_responsibilities": [],
            "interview_focus": ["stakeholder management", "delivery excellence"],
            "job_description": "Lead a data engineering practice and complex client engagements.",
            "culture": "people first",
        },
        "interviewer_profile": {
            "name": "Meg Wynne-Jones",
            "role_title": "Talent Acquisition Leader",
            "company": "Slalom",
            "expertise": ["talent acquisition", "data roles"],
            "likely_focus_areas": ["team leadership", "cloud data platforms"],
            "notes": "",
        },
    }


def build_principal_payload():
    payload = build_payload()
    payload["candidate_profile"]["current_role"] = "Principal Data Engineering Architect"
    payload["candidate_profile"]["target_role"] = "Principal Data Engineering Architect"
    payload["company_info"]["role_title"] = "Principal Data Engineering Architect"
    payload["company_info"]["role_level"] = "principal"
    payload["company_info"]["role_requirements"] = [
        "Principal-level architecture ownership",
        "Data platform modernization",
        "Cross-team technical influence",
    ]
    return payload


def build_generic_principal_payload():
    payload = build_payload()
    payload["candidate_profile"]["current_role"] = "Principal"
    payload["candidate_profile"]["target_role"] = "Principal"
    payload["candidate_profile"]["summary"] = (
        "Principal-level technical leader focused on data platform modernization, reference architecture, "
        "and reusable engineering guardrails across regulated environments."
    )
    payload["candidate_profile"]["skills"] = [
        "Data Engineering",
        "Architecture",
        "Platform Modernization",
        "Azure",
        "Lakehouse",
    ]
    payload["candidate_profile"]["achievements"] = [
        "Defined target-state architecture for enterprise data platform modernization",
        "Improved platform latency from 8 hours to 40 minutes across 120+ pipelines",
    ]
    payload["company_info"]["role_title"] = "Principal"
    payload["company_info"]["role_level"] = "principal"
    payload["company_info"]["role_requirements"] = [
        "Principal technical leadership",
        "Architecture depth",
        "Data platform modernization",
        "Cross-team influence",
    ]
    payload["company_info"]["job_description"] = (
        "Principal role focused on platform modernization, architecture direction, and technical leadership."
    )
    return payload


def build_weak_principal_payload():
    payload = build_generic_principal_payload()
    payload["candidate_profile"]["summary"] = "Principal technical leader in data."
    payload["candidate_profile"]["achievements"] = ["Worked on modernization programs"]
    payload["candidate_profile"]["skills"] = ["Data", "Architecture"]
    payload["candidate_profile"]["cv_text"] = (
        "Principal technical leader in data and architecture. Worked on modernization programs."
    )
    return payload


@pytest.fixture(autouse=True)
def force_insights_demo(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("adapters.llm_adapter.get_llm_adapter", lambda alias="main": None)


@pytest.mark.unit
def test_insights_service_generates_benchmark_workspace():
    service = InsightsService()
    payload = build_payload()

    result = asyncio.run(
        service.analyze(
            candidate_profile=payload["candidate_profile"],
            company_info=payload["company_info"],
            interviewer_profile=payload["interviewer_profile"],
            cv_text=SAMPLE_CV,
            language="en",
        )
    )

    assert result["benchmark_source"]["family_pack_id"] == "data_engineering_leadership"
    assert result["support_level"] == "curated"
    assert result["primary_scores"]["role_fit"] > 0
    assert result["primary_scores"]["profile_strength"] > 0
    assert result["coverage_pct"] > 0
    assert result["confidence"]["label"] in {"High", "Medium", "Low"}
    assert any(dimension["id"] == "role_positioning" for dimension in result["dimension_states"])
    assert result["required_signals"]
    assert result["supporting_signals"]
    assert isinstance(result["gap_map"], list)
    assert isinstance(result["evidence_cards"], list)
    assert result["questions"]
    assert result["questions"][0]["estimated_delta"]["global"] > 0
    assert result["interpretation"]
    assert result["improvement_plan"]["steps"]
    assert result["next_actions"]
    assert result["approved_context_preview"]["summary"]
    assert result["cv_variants"]["master_cv"]["rendered_text"]
    assert result["cv_variants"]["role_variant_cv"]["sections"]


@pytest.mark.unit
def test_insights_service_apply_workspace_updates_profile_and_cv():
    service = InsightsService()
    payload = build_payload()
    workspace = asyncio.run(
        service.analyze(
            candidate_profile=payload["candidate_profile"],
            company_info=payload["company_info"],
            interviewer_profile=payload["interviewer_profile"],
            cv_text=SAMPLE_CV,
            language="en",
            answers={"target_role": "Director of Data Engineering"},
        )
    )
    analysis = {
        "candidate_profile": payload["candidate_profile"],
        "cv_text": SAMPLE_CV,
        "workspace": workspace,
    }
    approved_changes = [change["id"] for change in workspace["proposed_changes"]]
    approved_evidence = [card["id"] for card in workspace["evidence_cards"][:2]]

    result = service.apply_workspace(
        analysis=analysis,
        approved_change_ids=approved_changes,
        approved_evidence_ids=approved_evidence,
        targets=["candidate_profile", "cv_text"],
        variant="role_variant_cv",
    )

    assert result["candidate_profile"]["summary"]
    assert result["candidate_profile"]["target_role"]
    assert "PROFESSIONAL SUMMARY" in result["cv_text"]
    assert result["variant_applied"] == "role_variant_cv"
    assert result["approved_context_preview"]["reusable_evidence"]
    assert result["context_index_status"]["saved"] is False


@pytest.mark.unit
def test_insights_service_builds_docx_export():
    service = InsightsService()
    payload = build_payload()
    workspace = asyncio.run(
        service.analyze(
            candidate_profile=payload["candidate_profile"],
            company_info=payload["company_info"],
            interviewer_profile=payload["interviewer_profile"],
            cv_text=SAMPLE_CV,
            language="en",
        )
    )

    export_payload = service.build_docx_export(
        variant=workspace["cv_variants"]["master_cv"],
        candidate_name=payload["candidate_profile"]["name"],
    )

    raw = base64.b64decode(export_payload["content_base64"])
    assert export_payload["filename"].endswith(".docx")
    assert export_payload["mime_type"].endswith("document")
    assert raw.startswith(b"PK")


@pytest.mark.unit
def test_insights_service_changes_family_pack_with_role_context():
    service = InsightsService()
    payload = build_payload()
    payload["company_info"]["role_title"] = "Head of Data Architecture"
    payload["company_info"]["role_requirements"] = [
        "Target-state architecture",
        "Data governance",
        "Reference architecture",
    ]

    result = asyncio.run(
        service.analyze(
            candidate_profile=payload["candidate_profile"],
            company_info=payload["company_info"],
            interviewer_profile=payload["interviewer_profile"],
            cv_text=SAMPLE_CV,
            language="en",
        )
    )

    assert result["benchmark_source"]["family_pack_id"] == "data_architecture_leadership"
    assert result["benchmark_source"]["seniority_pack_id"] == "head"
    assert any(dimension["id"] == "functional_technical_depth" for dimension in result["dimension_states"])
    assert any(question.get("dimension") for question in result["questions"])
    assert result["support_level"] == "curated"


@pytest.mark.unit
def test_insights_service_supports_principal_role_pack():
    service = InsightsService()
    payload = build_principal_payload()

    result = asyncio.run(
        service.analyze(
            candidate_profile=payload["candidate_profile"],
            company_info=payload["company_info"],
            interviewer_profile=payload["interviewer_profile"],
            cv_text=SAMPLE_CV,
            language="en",
        )
    )

    assert result["support_level"] == "curated"
    assert result["benchmark_source"]["family_pack_id"] in {
        "principal_data_engineering",
        "principal_platform_modernization",
        "principal_architecture",
        "principal_generic_technical_leadership",
    }
    assert result["benchmark_source"]["archetype_pack_id"] == "technical_leadership_principal"
    assert result["benchmark_source"]["seniority_pack_id"] == "principal"
    assert result["questions"]


@pytest.mark.unit
def test_generic_principal_role_resolves_supported_family_from_evidence():
    service = InsightsService()
    payload = build_generic_principal_payload()

    result = asyncio.run(
        service.analyze(
            candidate_profile=payload["candidate_profile"],
            company_info=payload["company_info"],
            interviewer_profile=payload["interviewer_profile"],
            cv_text=payload["candidate_profile"]["cv_text"],
            language="en",
        )
    )

    assert result["support_level"] != "unsupported"
    assert result["benchmark_source"]["seniority_pack_id"] == "principal"
    assert result["benchmark_source"]["archetype_pack_id"] == "technical_leadership_principal"
    assert result["benchmark_source"]["family_pack_id"] in {
        "principal_data_engineering",
        "principal_architecture",
        "principal_platform_modernization",
        "principal_generic_technical_leadership",
    }


@pytest.mark.unit
def test_principal_role_analyze_not_unsupported():
    service = InsightsService()
    payload = build_generic_principal_payload()

    result = asyncio.run(
        service.analyze(
            candidate_profile=payload["candidate_profile"],
            company_info=payload["company_info"],
            interviewer_profile=payload["interviewer_profile"],
            cv_text=payload["candidate_profile"]["cv_text"],
            language="en",
        )
    )

    assert result["support_level"] in {"curated", "derived"}


@pytest.mark.unit
def test_question_planner_never_returns_empty_when_open_gaps_exist():
    service = InsightsService()
    payload = build_weak_principal_payload()

    result = asyncio.run(
        service.analyze(
            candidate_profile=payload["candidate_profile"],
            company_info=payload["company_info"],
            interviewer_profile=payload["interviewer_profile"],
            cv_text=payload["candidate_profile"]["cv_text"],
            language="en",
        )
    )

    assert result["gap_map"]
    assert result["questions"]


@pytest.mark.unit
def test_dimension_states_include_missing_reasons_when_score_is_low():
    service = InsightsService()
    payload = build_weak_principal_payload()

    result = asyncio.run(
        service.analyze(
            candidate_profile=payload["candidate_profile"],
            company_info=payload["company_info"],
            interviewer_profile=payload["interviewer_profile"],
            cv_text=payload["candidate_profile"]["cv_text"],
            language="en",
        )
    )

    weak_dimensions = [dimension for dimension in result["dimension_states"] if dimension["score"] < 50 and dimension["status"] != "not_applicable"]
    assert weak_dimensions
    assert all(dimension["signals_missing"] for dimension in weak_dimensions)
    assert all(dimension["why_score_is_not_higher"] for dimension in weak_dimensions)
    assert all(dimension["next_best_action"] for dimension in weak_dimensions)


@pytest.mark.unit
def test_question_round_available_for_low_score_principal_workspace():
    service = InsightsService()
    payload = build_weak_principal_payload()

    result = asyncio.run(
        service.analyze(
            candidate_profile=payload["candidate_profile"],
            company_info=payload["company_info"],
            interviewer_profile=payload["interviewer_profile"],
            cv_text=payload["candidate_profile"]["cv_text"],
            language="en",
        )
    )

    assert 1 <= len(result["questions"]) <= 3
