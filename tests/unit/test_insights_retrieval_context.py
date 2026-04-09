from unittest.mock import AsyncMock

import pytest

from contracts.models import QuestionAnalysis, QuestionType
from pipeline.steps.evidence_retriever import EvidenceRetriever
from pipeline.steps.live_evidence_packer import LiveEvidencePacker
from pipeline.steps.retrieval_planner import RetrievalPlanner


@pytest.mark.unit
def test_retrieval_planner_keeps_live_contexts_but_no_candidate_insights_context():
    planner = RetrievalPlanner()
    analysis = QuestionAnalysis(
        primary_type=QuestionType.BEHAVIORAL,
        key_topics=["team leadership", "delivery"],
    )

    plan = planner.plan(
        analysis=analysis,
        role_title="Director of Data Engineering",
        company_name="Slalom",
        candidate_summary="Technology executive leading modernization and data transformation.",
        question_text="Tell me about your leadership style.",
        profile_id="profile-123",
        company_context_id="company-ctx-789",
        interviewer_context_id="interviewer-ctx-101",
    )

    assert plan.profile_id == "profile-123"
    assert plan.company_context_id == "company-ctx-789"
    assert plan.interviewer_context_id == "interviewer-ctx-101"
    assert not hasattr(plan, "candidate_insights_context_id")


@pytest.mark.asyncio
async def test_evidence_retriever_queries_only_company_and_interviewer_contexts(monkeypatch):
    retriever = EvidenceRetriever()
    plan = RetrievalPlanner().plan(
        analysis=QuestionAnalysis(
            primary_type=QuestionType.BEHAVIORAL,
            key_topics=["delivery scale", "team leadership"],
        ),
        company_context_id="11111111-1111-1111-1111-111111111111",
        interviewer_context_id="22222222-2222-2222-2222-222222222222",
    )

    executed = []

    async def fake_execute_query(query, vector_value, context_id, kind):
        executed.append({"context_id": context_id, "kind": kind, "vector_value": vector_value})
        return [
            {
                "id": "chunk-1",
                "context_id": context_id,
                "kind": kind,
                "source": kind,
                "section": "summary",
                "content": f"{kind} content",
                "metadata": {"section": "summary"},
                "similarity": 0.91,
            }
        ]

    monkeypatch.setattr("storage.database.execute_query", fake_execute_query)
    embedder = AsyncMock(return_value=[0.1, 0.2, 0.3])

    results = await retriever._query_context_document_chunks(
        plan,
        embedder,
        lambda embedding: f"vector:{len(embedding)}",
    )

    assert executed
    assert {call["kind"] for call in executed} == {"company", "interviewer"}
    assert results
    assert all(result.source in {"company_context", "interviewer_context"} for result in results)


@pytest.mark.unit
def test_live_evidence_packer_ignores_insights_specific_candidate_fields():
    sources = LiveEvidencePacker._candidate_sources(
        {
            "currentRole": "Director of Data Engineering",
            "summary": "Leads data modernization and engineering delivery.",
            "skills": ["AWS", "Leadership"],
            "achievements": ["Reduced OPEX by 40% across 100+ applications."],
            "insights_context_summary": "This should stay isolated from live.",
            "insights_reusable_evidence": ["This should not leak into live evidence packing."],
        }
    )

    joined = " ".join(sources)
    assert "Leads data modernization and engineering delivery." in joined
    assert "Reduced OPEX by 40% across 100+ applications." in joined
    assert "This should stay isolated from live." not in joined
    assert "This should not leak into live evidence packing." not in joined
