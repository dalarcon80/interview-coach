from copy import deepcopy

from fastapi.testclient import TestClient

from api.server import app, _INSIGHTS_SERVICE, _INSIGHTS_STORE


SAMPLE_PAYLOAD = {
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
        "cv_text": (
            "Technology executive with 20 years leading enterprise transformation. "
            "Led core banking modernization across 100+ applications with 40% OPEX reduction."
        ),
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
    "cv_text": (
        "Technology executive with 20 years leading enterprise transformation. "
        "Led core banking modernization across 100+ applications with 40% OPEX reduction."
    ),
    "language": "en",
}


def test_insights_endpoints_round_trip(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("adapters.llm_adapter.get_llm_adapter", lambda alias="main": None)
    _INSIGHTS_SERVICE.cv_analyzer._api_checked = False
    _INSIGHTS_SERVICE.cv_analyzer._api_available = False

    memory: dict[str, dict[str, dict]] = {"workspaces": {}, "runs": {}}

    async def fake_save_run(**kwargs):
        workspace_id = kwargs["workspace_id"] or "11111111-1111-1111-1111-111111111111"
        run_id = f"22222222-2222-2222-2222-{len(memory['runs']) + 1:012d}"
        memory["workspaces"][workspace_id] = {
            "id": workspace_id,
            "profile_id": kwargs["profile_id"],
            "target_role": kwargs["target_role"],
            "normalized_target_role": kwargs["normalized_target_role"],
            "archetype_pack_id": kwargs["archetype_pack_id"],
            "role_family_pack_id": kwargs["role_family_pack_id"],
            "seniority_pack_id": kwargs["seniority_pack_id"],
            "specialty_pack_ids": kwargs["specialty_pack_ids"],
            "support_level": kwargs["support_level"],
            "benchmark_source_fingerprint": kwargs["benchmark_source_fingerprint"],
            "workspace_state": "active",
            "current_run_id": run_id,
        }
        memory["runs"][run_id] = {
            "workspace_id": workspace_id,
            "benchmark_source": deepcopy(kwargs["benchmark_source"]),
            "input_snapshot": deepcopy(kwargs["input_snapshot"]),
            "primary_scores": deepcopy(kwargs["primary_scores"]),
            "overall_match": kwargs["overall_match"],
            "coverage_pct": kwargs["coverage_pct"],
            "confidence_score": kwargs["confidence_score"],
            "confidence_label": kwargs["confidence_label"],
            "dimension_states": deepcopy(kwargs["dimension_states"]),
            "signal_snapshot": deepcopy(kwargs["signal_snapshot"]),
            "gap_map": deepcopy(kwargs["gap_map"]),
            "question_backlog": deepcopy(kwargs["question_backlog"]),
            "evidence_cards": deepcopy(kwargs["evidence_cards"]),
            "cv_variants": deepcopy(kwargs["cv_variants"]),
            "answers": deepcopy(kwargs["answers"]),
            "approvals": deepcopy(kwargs["approvals"]),
            "support_level": kwargs["support_level"],
        }
        return workspace_id, run_id

    async def fake_get_run(*, workspace_id: str, run_id: str | None = None):
        workspace = memory["workspaces"].get(workspace_id)
        if not workspace:
            return None
        resolved_run_id = run_id or workspace["current_run_id"]
        run = memory["runs"].get(resolved_run_id)
        if not run:
            return None
        return {
            "workspace": deepcopy(workspace),
            "run": {
                "id": resolved_run_id,
                **deepcopy(run),
            },
        }

    async def fake_mark_context_saved(*, workspace_id: str, run_id: str, context_status: dict):
        memory["runs"][run_id]["approvals"]["context_index_status"] = deepcopy(context_status)

    async def fake_save_ui_state(*, workspace_id: str, ui_state: dict, workspace_state: str | None = None):
        memory["workspaces"][workspace_id]["ui_state"] = deepcopy(ui_state)
        if workspace_state:
            memory["workspaces"][workspace_id]["workspace_state"] = workspace_state
        return True

    async def fake_find_workspace(*, profile_id: str | None, target_role: str | None):
        for workspace_id, workspace in memory["workspaces"].items():
            if profile_id and workspace.get("profile_id") != profile_id:
                continue
            if target_role and workspace.get("target_role") != target_role:
                continue
            run_id = workspace["current_run_id"]
            return {
                "workspace": deepcopy(workspace),
                "run": {
                    "id": run_id,
                    **deepcopy(memory["runs"][run_id]),
                },
            }
        return None

    async def fake_get_workspace_status(*, workspace_id: str):
        workspace = memory["workspaces"].get(workspace_id)
        if not workspace:
            return None
        return {
            "workspace_id": workspace_id,
            "workspace_state": workspace.get("workspace_state", "active"),
            "current_run_id": workspace.get("current_run_id"),
            "ui_state_saved": bool(workspace.get("ui_state")),
            "last_active_at": "2026-03-31T00:00:00+00:00",
        }

    async def fake_persist(*, workspace_id: str, run_id: str, workspace: dict, apply_result: dict):
        assert workspace_id
        assert run_id
        assert workspace["benchmark_source"]["family_pack_id"]
        assert apply_result["approved_context_preview"]["summary"]
        return {
            "saved": True,
            "deleted": {"document_chunks": 1},
            "indexed": {"document_chunks": 4},
        }

    monkeypatch.setattr(_INSIGHTS_STORE, "save_run", fake_save_run)
    monkeypatch.setattr(_INSIGHTS_STORE, "get_run", fake_get_run)
    monkeypatch.setattr(_INSIGHTS_STORE, "mark_context_saved", fake_mark_context_saved)
    monkeypatch.setattr(_INSIGHTS_STORE, "save_ui_state", fake_save_ui_state)
    monkeypatch.setattr(_INSIGHTS_STORE, "find_workspace", fake_find_workspace)
    monkeypatch.setattr(_INSIGHTS_STORE, "get_workspace_status", fake_get_workspace_status)
    monkeypatch.setattr("api.server._persist_candidate_insights_context", fake_persist)

    client = TestClient(app)

    analyze = client.post("/api/insights/analyze", json=SAMPLE_PAYLOAD)
    assert analyze.status_code == 200
    analyze_body = analyze.json()
    assert analyze_body["success"] is True
    assert analyze_body["workspace_id"]
    assert analyze_body["run_id"]
    assert analyze_body["benchmark_source"]["family_pack_id"] == "data_engineering_leadership"
    assert analyze_body["primary_scores"]["role_fit"] > 0
    assert analyze_body["dimension_states"]
    assert analyze_body["required_signals"]
    assert analyze_body["approved_context_preview"]["summary"]
    assert analyze_body["cv_variants"]["master_cv"]["rendered_text"]

    workspace_id = analyze_body["workspace_id"]
    run_id = analyze_body["run_id"]

    answer = client.post(
        "/api/insights/questions/answer",
        json={
            "workspace_id": workspace_id,
            "run_id": run_id,
            "question_id": "target_role",
            "answer": "Director of Data Engineering",
        },
    )
    assert answer.status_code == 200
    answer_body = answer.json()
    assert answer_body["success"] is True
    assert answer_body["workspace_id"] == workspace_id
    assert answer_body["run_id"] != run_id

    preview = client.post(
        "/api/insights/cv/preview",
        json={
            "workspace_id": workspace_id,
            "run_id": answer_body["run_id"],
            "variant": "role_variant_cv",
        },
    )
    assert preview.status_code == 200
    assert preview.json()["variant"]["variant_id"] == "role_variant_cv"

    restore = client.get(f"/api/insights/workspace/{workspace_id}", params={"run_id": answer_body["run_id"]})
    assert restore.status_code == 200
    restore_body = restore.json()
    assert restore_body["success"] is True
    assert restore_body["workspace_id"] == workspace_id
    assert restore_body["run_id"] == answer_body["run_id"]
    assert restore_body["next_actions"]
    assert restore_body["improvement_plan"]["steps"]

    autosave = client.put(
        f"/api/insights/workspace/{workspace_id}",
        json={
            "ui_state": {
                "active_tab": "action-plan",
                "selected_variant": "role_variant_cv",
                "selected_change_ids": [],
            },
            "workspace_state": "active",
        },
    )
    assert autosave.status_code == 200
    autosave_body = autosave.json()
    assert autosave_body["success"] is True
    assert autosave_body["workspace_id"] == workspace_id
    assert autosave_body["workspace_state"] == "active"
    assert autosave_body["ui_state"]["active_tab"] == "action-plan"

    lookup = client.get(
        "/api/insights/workspace",
        params={
            "target_role": analyze_body["benchmark_source"]["target_role"],
        },
    )
    assert lookup.status_code == 200
    assert lookup.json()["success"] is True

    status = client.get(f"/api/insights/workspace/{workspace_id}/status")
    assert status.status_code == 200
    status_body = status.json()
    assert status_body["success"] is True
    assert status_body["workspace_id"] == workspace_id
    assert status_body["ui_state_saved"] is True

    apply_response = client.post(
        "/api/insights/apply",
        json={
            "workspace_id": workspace_id,
            "run_id": answer_body["run_id"],
            "approved_change_ids": [change["id"] for change in answer_body["proposed_changes"]],
            "approved_evidence_ids": [card["id"] for card in answer_body["evidence_cards"][:2]],
            "targets": ["candidate_profile", "cv_text"],
            "variant": "role_variant_cv",
        },
    )
    assert apply_response.status_code == 200
    apply_body = apply_response.json()
    assert apply_body["success"] is True
    assert apply_body["candidate_profile"]["summary"]
    assert apply_body["variant_applied"] == "role_variant_cv"
    assert apply_body["approved_context_preview"]["summary"]
    assert apply_body["score_history"]
    assert apply_body["run_id"] != answer_body["run_id"]
    assert "candidate_insights_context_id" not in apply_body
    assert apply_body["context_index_status"]["saved"] is True
    assert apply_body["context_index_status"]["indexed"]["document_chunks"] == 4

    export = client.post(
        "/api/insights/cv/export",
        json={
            "workspace_id": workspace_id,
            "run_id": answer_body["run_id"],
            "variant": "role_variant_cv",
        },
    )
    assert export.status_code == 200
    export_body = export.json()
    assert export_body["success"] is True
    assert export_body["filename"].endswith(".docx")
