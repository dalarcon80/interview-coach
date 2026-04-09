from __future__ import annotations

import json
import uuid
from typing import Any

from storage.database import execute_one, execute_query


class InsightsStore:
    def __init__(self) -> None:
        self._schema_ready = False

    async def ensure_schema(self) -> None:
        if self._schema_ready:
            return

        await execute_query(
            """
            CREATE TABLE IF NOT EXISTS insights_workspaces (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                profile_id UUID REFERENCES user_profiles(id) ON DELETE SET NULL,
                target_role TEXT NOT NULL DEFAULT '',
                normalized_target_role TEXT NOT NULL DEFAULT '',
                archetype_pack_id TEXT NOT NULL DEFAULT '',
                role_family_pack_id TEXT NOT NULL DEFAULT '',
                seniority_pack_id TEXT NOT NULL DEFAULT '',
                specialty_pack_ids TEXT[] DEFAULT '{}',
                support_level TEXT NOT NULL DEFAULT 'unsupported',
                benchmark_source_fingerprint TEXT NOT NULL DEFAULT '',
                workspace_state TEXT NOT NULL DEFAULT 'active',
                ui_state JSONB NOT NULL DEFAULT '{}',
                current_run_id UUID,
                last_active_at TIMESTAMPTZ DEFAULT now(),
                created_at TIMESTAMPTZ DEFAULT now(),
                updated_at TIMESTAMPTZ DEFAULT now()
            )
            """
        )
        await execute_query(
            """
            ALTER TABLE insights_workspaces
            ADD COLUMN IF NOT EXISTS ui_state JSONB NOT NULL DEFAULT '{}'
            """
        )
        await execute_query(
            """
            CREATE TABLE IF NOT EXISTS insights_runs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                workspace_id UUID NOT NULL REFERENCES insights_workspaces(id) ON DELETE CASCADE,
                benchmark_source JSONB NOT NULL DEFAULT '{}',
                input_snapshot JSONB NOT NULL DEFAULT '{}',
                primary_scores JSONB NOT NULL DEFAULT '{}',
                overall_match INT NOT NULL DEFAULT 0,
                coverage_pct INT NOT NULL DEFAULT 0,
                confidence_score INT NOT NULL DEFAULT 0,
                confidence_label TEXT NOT NULL DEFAULT 'Low',
                dimension_states JSONB NOT NULL DEFAULT '[]',
                signal_snapshot JSONB NOT NULL DEFAULT '{}',
                gap_map JSONB NOT NULL DEFAULT '[]',
                question_backlog JSONB NOT NULL DEFAULT '[]',
                evidence_cards JSONB NOT NULL DEFAULT '[]',
                cv_variants JSONB NOT NULL DEFAULT '{}',
                answers JSONB NOT NULL DEFAULT '{}',
                approvals JSONB NOT NULL DEFAULT '{}',
                support_level TEXT NOT NULL DEFAULT 'unsupported',
                created_at TIMESTAMPTZ DEFAULT now()
            )
            """
        )
        await execute_query(
            """
            CREATE INDEX IF NOT EXISTS insights_workspaces_state_idx
                ON insights_workspaces(workspace_state, updated_at DESC)
            """
        )
        await execute_query(
            """
            CREATE INDEX IF NOT EXISTS insights_runs_workspace_idx
                ON insights_runs(workspace_id, created_at DESC)
            """
        )
        await execute_query(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_trigger
                    WHERE tgname = 'update_insights_workspaces_updated_at'
                ) THEN
                    CREATE TRIGGER update_insights_workspaces_updated_at
                        BEFORE UPDATE ON insights_workspaces
                        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
                END IF;
            END$$
            """
        )
        self._schema_ready = True

    async def save_run(
        self,
        *,
        workspace_id: str | None,
        profile_id: str | None,
        target_role: str,
        normalized_target_role: str,
        archetype_pack_id: str,
        role_family_pack_id: str,
        seniority_pack_id: str,
        specialty_pack_ids: list[str],
        support_level: str,
        benchmark_source_fingerprint: str,
        benchmark_source: dict[str, Any],
        input_snapshot: dict[str, Any],
        primary_scores: dict[str, Any],
        overall_match: int,
        coverage_pct: int,
        confidence_score: int,
        confidence_label: str,
        dimension_states: list[dict[str, Any]],
        signal_snapshot: dict[str, Any],
        gap_map: list[dict[str, Any]],
        question_backlog: list[dict[str, Any]],
        evidence_cards: list[dict[str, Any]],
        cv_variants: dict[str, Any],
        answers: dict[str, Any],
        approvals: dict[str, Any],
    ) -> tuple[str, str]:
        await self.ensure_schema()

        workspace_uuid = workspace_id or str(uuid.uuid4())
        run_id = str(uuid.uuid4())

        existing = await execute_one(
            "SELECT id FROM insights_workspaces WHERE id = $1::uuid",
            workspace_uuid,
        )

        if existing:
            await execute_query(
                """
                UPDATE insights_workspaces
                SET profile_id = $2::uuid,
                    target_role = $3,
                    normalized_target_role = $4,
                    archetype_pack_id = $5,
                    role_family_pack_id = $6,
                    seniority_pack_id = $7,
                    specialty_pack_ids = $8::text[],
                    support_level = $9,
                    benchmark_source_fingerprint = $10,
                    workspace_state = 'active',
                    current_run_id = $11::uuid,
                    last_active_at = NOW()
                WHERE id = $1::uuid
                """,
                workspace_uuid,
                profile_id,
                target_role,
                normalized_target_role,
                archetype_pack_id,
                role_family_pack_id,
                seniority_pack_id,
                specialty_pack_ids,
                support_level,
                benchmark_source_fingerprint,
                run_id,
            )
        else:
            await execute_query(
                """
                INSERT INTO insights_workspaces
                (id, profile_id, target_role, normalized_target_role, archetype_pack_id,
                 role_family_pack_id, seniority_pack_id, specialty_pack_ids, support_level,
                 benchmark_source_fingerprint, workspace_state, ui_state, current_run_id, last_active_at, created_at, updated_at)
                VALUES
                ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8::text[], $9, $10, 'active', '{}'::jsonb, $11::uuid, NOW(), NOW(), NOW())
                """,
                workspace_uuid,
                profile_id,
                target_role,
                normalized_target_role,
                archetype_pack_id,
                role_family_pack_id,
                seniority_pack_id,
                specialty_pack_ids,
                support_level,
                benchmark_source_fingerprint,
                run_id,
            )

        await execute_query(
            """
            INSERT INTO insights_runs
            (id, workspace_id, benchmark_source, input_snapshot, primary_scores, overall_match,
             coverage_pct, confidence_score, confidence_label, dimension_states, signal_snapshot,
             gap_map, question_backlog, evidence_cards, cv_variants, answers, approvals, support_level, created_at)
            VALUES
            ($1::uuid, $2::uuid, $3::jsonb, $4::jsonb, $5::jsonb, $6, $7, $8, $9,
             $10::jsonb, $11::jsonb, $12::jsonb, $13::jsonb, $14::jsonb, $15::jsonb, $16::jsonb, $17::jsonb, $18, NOW())
            """,
            run_id,
            workspace_uuid,
            json.dumps(benchmark_source),
            json.dumps(input_snapshot),
            json.dumps(primary_scores),
            overall_match,
            coverage_pct,
            confidence_score,
            confidence_label,
            json.dumps(dimension_states),
            json.dumps(signal_snapshot),
            json.dumps(gap_map),
            json.dumps(question_backlog),
            json.dumps(evidence_cards),
            json.dumps(cv_variants),
            json.dumps(answers),
            json.dumps(approvals),
            support_level,
        )

        return workspace_uuid, run_id

    async def get_run(self, *, workspace_id: str, run_id: str | None = None) -> dict[str, Any] | None:
        await self.ensure_schema()
        if run_id:
            row = await execute_one(
                """
                SELECT
                    w.id AS workspace_id,
                    w.profile_id AS workspace_profile_id,
                    w.target_role AS workspace_target_role,
                    w.normalized_target_role AS workspace_normalized_target_role,
                    w.archetype_pack_id AS workspace_archetype_pack_id,
                    w.role_family_pack_id AS workspace_role_family_pack_id,
                    w.seniority_pack_id AS workspace_seniority_pack_id,
                    w.specialty_pack_ids AS workspace_specialty_pack_ids,
                    w.support_level AS workspace_support_level,
                    w.benchmark_source_fingerprint AS workspace_benchmark_source_fingerprint,
                    w.workspace_state AS workspace_state,
                    w.ui_state AS workspace_ui_state,
                    w.current_run_id AS workspace_current_run_id,
                    w.last_active_at AS workspace_last_active_at,
                    w.created_at AS workspace_created_at,
                    w.updated_at AS workspace_updated_at,
                    r.id AS run_id,
                    r.benchmark_source,
                    r.input_snapshot,
                    r.primary_scores,
                    r.overall_match,
                    r.coverage_pct,
                    r.confidence_score,
                    r.confidence_label,
                    r.dimension_states,
                    r.signal_snapshot,
                    r.gap_map,
                    r.question_backlog,
                    r.evidence_cards,
                    r.cv_variants,
                    r.answers,
                    r.approvals,
                    r.support_level AS run_support_level,
                    r.created_at AS run_created_at
                FROM insights_workspaces w
                JOIN insights_runs r ON r.workspace_id = w.id
                WHERE w.id = $1::uuid AND r.id = $2::uuid
                """,
                workspace_id,
                run_id,
            )
        else:
            row = await execute_one(
                """
                SELECT
                    w.id AS workspace_id,
                    w.profile_id AS workspace_profile_id,
                    w.target_role AS workspace_target_role,
                    w.normalized_target_role AS workspace_normalized_target_role,
                    w.archetype_pack_id AS workspace_archetype_pack_id,
                    w.role_family_pack_id AS workspace_role_family_pack_id,
                    w.seniority_pack_id AS workspace_seniority_pack_id,
                    w.specialty_pack_ids AS workspace_specialty_pack_ids,
                    w.support_level AS workspace_support_level,
                    w.benchmark_source_fingerprint AS workspace_benchmark_source_fingerprint,
                    w.workspace_state AS workspace_state,
                    w.ui_state AS workspace_ui_state,
                    w.current_run_id AS workspace_current_run_id,
                    w.last_active_at AS workspace_last_active_at,
                    w.created_at AS workspace_created_at,
                    w.updated_at AS workspace_updated_at,
                    r.id AS run_id,
                    r.benchmark_source,
                    r.input_snapshot,
                    r.primary_scores,
                    r.overall_match,
                    r.coverage_pct,
                    r.confidence_score,
                    r.confidence_label,
                    r.dimension_states,
                    r.signal_snapshot,
                    r.gap_map,
                    r.question_backlog,
                    r.evidence_cards,
                    r.cv_variants,
                    r.answers,
                    r.approvals,
                    r.support_level AS run_support_level,
                    r.created_at AS run_created_at
                FROM insights_workspaces w
                JOIN insights_runs r ON r.id = w.current_run_id
                WHERE w.id = $1::uuid
                """,
                workspace_id,
            )
        if not row:
            return None

        def _json(value: Any, default: Any) -> Any:
            if value is None:
                return default
            if isinstance(value, (dict, list)):
                return value
            try:
                return json.loads(value)
            except Exception:
                return default

        return {
            "workspace": {
                "id": str(row["workspace_id"]),
                "profile_id": str(row["workspace_profile_id"]) if row["workspace_profile_id"] else None,
                "target_role": row["workspace_target_role"],
                "normalized_target_role": row["workspace_normalized_target_role"],
                "archetype_pack_id": row["workspace_archetype_pack_id"],
                "role_family_pack_id": row["workspace_role_family_pack_id"],
                "seniority_pack_id": row["workspace_seniority_pack_id"],
                "specialty_pack_ids": list(row["workspace_specialty_pack_ids"] or []),
                "support_level": row["workspace_support_level"],
                "benchmark_source_fingerprint": row["workspace_benchmark_source_fingerprint"],
                "workspace_state": row["workspace_state"],
                "ui_state": _json(row["workspace_ui_state"], {}),
                "current_run_id": str(row["workspace_current_run_id"]) if row["workspace_current_run_id"] else None,
                "last_active_at": row["workspace_last_active_at"].isoformat() if row["workspace_last_active_at"] else None,
                "created_at": row["workspace_created_at"].isoformat() if row["workspace_created_at"] else None,
                "updated_at": row["workspace_updated_at"].isoformat() if row["workspace_updated_at"] else None,
            },
            "run": {
                "id": str(row["run_id"]),
                "benchmark_source": _json(row["benchmark_source"], {}),
                "input_snapshot": _json(row["input_snapshot"], {}),
                "primary_scores": _json(row["primary_scores"], {}),
                "overall_match": row["overall_match"],
                "coverage_pct": row["coverage_pct"],
                "confidence_score": row["confidence_score"],
                "confidence_label": row["confidence_label"],
                "dimension_states": _json(row["dimension_states"], []),
                "signal_snapshot": _json(row["signal_snapshot"], {}),
                "gap_map": _json(row["gap_map"], []),
                "question_backlog": _json(row["question_backlog"], []),
                "evidence_cards": _json(row["evidence_cards"], []),
                "cv_variants": _json(row["cv_variants"], {}),
                "answers": _json(row["answers"], {}),
                "approvals": _json(row["approvals"], {}),
                "support_level": row["run_support_level"],
                "created_at": row["run_created_at"].isoformat() if row["run_created_at"] else None,
            },
        }

    async def mark_context_saved(
        self,
        *,
        workspace_id: str,
        run_id: str,
        context_status: dict[str, Any],
    ) -> None:
        await self.ensure_schema()
        row = await execute_one(
            "SELECT approvals FROM insights_runs WHERE id = $1::uuid AND workspace_id = $2::uuid",
            run_id,
            workspace_id,
        )
        approvals = {}
        if row and row["approvals"]:
            approvals = row["approvals"] if isinstance(row["approvals"], dict) else json.loads(row["approvals"])
        approvals["context_index_status"] = context_status
        await execute_query(
            "UPDATE insights_runs SET approvals = $3::jsonb WHERE id = $1::uuid AND workspace_id = $2::uuid",
            run_id,
            workspace_id,
            json.dumps(approvals),
        )

    async def save_ui_state(
        self,
        *,
        workspace_id: str,
        ui_state: dict[str, Any],
        workspace_state: str | None = None,
    ) -> bool:
        await self.ensure_schema()
        existing = await execute_one(
            "SELECT id FROM insights_workspaces WHERE id = $1::uuid",
            workspace_id,
        )
        if not existing:
            return False
        if workspace_state:
            await execute_query(
                """
                UPDATE insights_workspaces
                SET ui_state = $2::jsonb,
                    workspace_state = $3,
                    last_active_at = NOW()
                WHERE id = $1::uuid
                """,
                workspace_id,
                json.dumps(ui_state),
                workspace_state,
            )
            return True
        await execute_query(
            """
            UPDATE insights_workspaces
            SET ui_state = $2::jsonb,
                last_active_at = NOW()
            WHERE id = $1::uuid
            """,
            workspace_id,
            json.dumps(ui_state),
        )
        return True

    async def find_workspace(self, *, profile_id: str | None, target_role: str | None) -> dict[str, Any] | None:
        await self.ensure_schema()
        if not profile_id and not target_role:
            return None

        clauses: list[str] = []
        params: list[Any] = []
        param_index = 1
        if profile_id:
            clauses.append(f"w.profile_id = ${param_index}::uuid")
            params.append(profile_id)
            param_index += 1
        if target_role:
            normalized_target_role = target_role.strip().lower().replace("-", " ")
            normalized_target_role = "_".join(token for token in normalized_target_role.split() if token)
            clauses.append(
                f"(LOWER(w.target_role) = LOWER(${param_index}) OR LOWER(w.normalized_target_role) = LOWER(${param_index + 1}))"
            )
            params.append(target_role)
            params.append(normalized_target_role)
            param_index += 2
        if not clauses:
            return None

        row = await execute_one(
            f"""
            SELECT w.id
            FROM insights_workspaces w
            WHERE {' AND '.join(clauses)}
            ORDER BY w.updated_at DESC
            LIMIT 1
            """,
            *params,
        )
        if not row:
            return None
        return await self.get_run(workspace_id=str(row["id"]))

    async def get_workspace_status(self, *, workspace_id: str) -> dict[str, Any] | None:
        await self.ensure_schema()
        row = await execute_one(
            """
            SELECT
                id,
                workspace_state,
                current_run_id,
                ui_state,
                last_active_at
            FROM insights_workspaces
            WHERE id = $1::uuid
            """,
            workspace_id,
        )
        if not row:
            return None
        ui_state = row["ui_state"] if isinstance(row["ui_state"], dict) else json.loads(row["ui_state"] or "{}")
        return {
            "workspace_id": str(row["id"]),
            "workspace_state": row["workspace_state"],
            "current_run_id": str(row["current_run_id"]) if row["current_run_id"] else None,
            "ui_state_saved": bool(ui_state),
            "last_active_at": row["last_active_at"].isoformat() if row["last_active_at"] else None,
        }
