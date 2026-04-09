-- Insights V3.2 workspace persistence

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
);

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
);

CREATE INDEX IF NOT EXISTS insights_workspaces_state_idx
    ON insights_workspaces(workspace_state, updated_at DESC);

CREATE INDEX IF NOT EXISTS insights_runs_workspace_idx
    ON insights_runs(workspace_id, created_at DESC);

CREATE OR REPLACE TRIGGER update_insights_workspaces_updated_at
    BEFORE UPDATE ON insights_workspaces
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
