"""baseline — collapse legacy 001_initial_schema.sql + 002_*

Revision ID: 20260422_01
Revises:
Create Date: 2026-04-22

This migration collapses into a single baseline the three legacy SQL files
previously mounted under /docker-entrypoint-initdb.d:

- 001_initial_schema.sql
- 002_insights_workspace.sql
- 002_make_config_id_nullable.sql

All statements use IF NOT EXISTS / DROP IF EXISTS so the migration is safe
to run on:
- A clean database (creates everything).
- A database that already has 001+002 applied via the old init path —
  after running `alembic stamp 20260422_01_baseline` the migration is a no-op.

Ref: docs/audit/DATA_MODEL_REDESIGN.md §2.1, §3.
"""

from __future__ import annotations

from alembic import op

revision: str = "20260422_01_baseline"
down_revision: str | None = None
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


_UP_SQL = r"""
-- =========================================================================
-- pgvector extension (idempotent)
-- =========================================================================
CREATE EXTENSION IF NOT EXISTS vector;

-- =========================================================================
-- User profiles
-- =========================================================================
CREATE TABLE IF NOT EXISTS user_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    resume_text TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- =========================================================================
-- Achievements with embeddings
-- =========================================================================
CREATE TABLE IF NOT EXISTS achievements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id UUID REFERENCES user_profiles(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    context TEXT,
    action TEXT,
    result TEXT,
    metrics TEXT[],
    tags TEXT[],
    embedding VECTOR(1536),
    created_at TIMESTAMPTZ DEFAULT now()
);

-- =========================================================================
-- Document chunks for RAG with embeddings
-- =========================================================================
CREATE TABLE IF NOT EXISTS document_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id UUID REFERENCES user_profiles(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    section TEXT,
    content TEXT NOT NULL,
    embedding VECTOR(1536),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS document_chunks_embedding_idx
    ON document_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS achievements_embedding_idx
    ON achievements USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- =========================================================================
-- Context profiles (company / interviewer research)
-- =========================================================================
CREATE TABLE IF NOT EXISTS context_profiles (
    id UUID PRIMARY KEY,
    kind TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    payload JSONB DEFAULT '{}',
    source_urls TEXT[],
    raw_text TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS context_document_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    context_id UUID REFERENCES context_profiles(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    source TEXT NOT NULL,
    section TEXT,
    content TEXT NOT NULL,
    embedding VECTOR(1536),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS context_document_chunks_embedding_idx
    ON context_document_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS context_document_chunks_context_idx
    ON context_document_chunks(context_id, kind);

-- =========================================================================
-- Interview configs (logical aliases, NOT model IDs)
-- =========================================================================
CREATE TABLE IF NOT EXISTS interview_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id UUID REFERENCES user_profiles(id) ON DELETE CASCADE,
    company_name TEXT NOT NULL,
    role_title TEXT NOT NULL,
    job_description TEXT,
    company_values TEXT[],
    response_style TEXT DEFAULT 'mixed',
    language_preference TEXT DEFAULT 'auto',
    custom_rules TEXT,
    stt_alias TEXT DEFAULT 'stt_primary',
    llm_alias TEXT DEFAULT 'llm_main',
    embedding_alias TEXT DEFAULT 'embedding_primary',
    provider_overrides JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);

-- =========================================================================
-- Sessions
-- Note: config_id is nullable to allow sessions started without a config.
-- =========================================================================
CREATE TABLE IF NOT EXISTS sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    config_id UUID REFERENCES interview_configs(id) ON DELETE CASCADE,
    status TEXT DEFAULT 'active',
    started_at TIMESTAMPTZ DEFAULT now(),
    ended_at TIMESTAMPTZ,
    summary JSONB
);
-- Ensure config_id is nullable on pre-existing installs (legacy 002_make_config_id_nullable)
ALTER TABLE sessions ALTER COLUMN config_id DROP NOT NULL;

CREATE INDEX IF NOT EXISTS sessions_config_idx ON sessions(config_id);
CREATE INDEX IF NOT EXISTS sessions_status_idx ON sessions(status);

-- =========================================================================
-- Exchanges (Q&A pairs) — legacy, kept for compat; deprecated to view in 02
-- =========================================================================
CREATE TABLE IF NOT EXISTS exchanges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    index_in_session INT NOT NULL,
    interviewer_utterance TEXT NOT NULL,
    language_detected TEXT,
    question_analysis JSONB NOT NULL,
    suggested_response JSONB NOT NULL,
    quality_result JSONB NOT NULL,
    user_actual_response TEXT,
    latency_ms INT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS exchanges_session_idx ON exchanges(session_id);
CREATE INDEX IF NOT EXISTS exchanges_session_order_idx
    ON exchanges(session_id, index_in_session);

-- =========================================================================
-- Event log (append-only) — legacy; extended in 02 with (session_id, seq) UNIQUE
-- =========================================================================
CREATE TABLE IF NOT EXISTS event_log (
    id BIGSERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    trace_id TEXT,
    latency_ms INT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS event_log_session_idx ON event_log(session_id, created_at);

-- =========================================================================
-- Latency metrics (time-series)
-- =========================================================================
CREATE TABLE IF NOT EXISTS latency_metrics (
    id BIGSERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    exchange_index INT,
    step_name TEXT NOT NULL,
    duration_ms INT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS latency_metrics_session_idx ON latency_metrics(session_id);
CREATE INDEX IF NOT EXISTS latency_metrics_step_idx
    ON latency_metrics(step_name, created_at);

-- =========================================================================
-- Shared updated_at trigger
-- =========================================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_user_profiles_updated_at ON user_profiles;
CREATE TRIGGER update_user_profiles_updated_at
    BEFORE UPDATE ON user_profiles
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- =========================================================================
-- Insights workspace (from legacy 002_insights_workspace.sql)
-- =========================================================================
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

DROP TRIGGER IF EXISTS update_insights_workspaces_updated_at ON insights_workspaces;
CREATE TRIGGER update_insights_workspaces_updated_at
    BEFORE UPDATE ON insights_workspaces
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- =========================================================================
-- Dev grants (kept from 001; production uses more restrictive grants)
-- =========================================================================
-- Note: intentionally commented — role may not exist in all environments.
-- GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO interview_coach;
-- GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO interview_coach;
"""


_DOWN_SQL = r"""
-- Baseline downgrade drops everything this migration created.
-- Use with caution — data loss is expected.
DROP TRIGGER IF EXISTS update_insights_workspaces_updated_at ON insights_workspaces;
DROP TABLE IF EXISTS insights_runs;
DROP TABLE IF EXISTS insights_workspaces;
DROP TABLE IF EXISTS latency_metrics;
DROP TABLE IF EXISTS event_log;
DROP TABLE IF EXISTS exchanges;
DROP TABLE IF EXISTS sessions;
DROP TABLE IF EXISTS interview_configs;
DROP TABLE IF EXISTS context_document_chunks;
DROP TABLE IF EXISTS context_profiles;
DROP TABLE IF EXISTS document_chunks;
DROP TABLE IF EXISTS achievements;
DROP TRIGGER IF EXISTS update_user_profiles_updated_at ON user_profiles;
DROP TABLE IF EXISTS user_profiles;
DROP FUNCTION IF EXISTS update_updated_at_column();
-- pgvector extension is left in place.
"""


def upgrade() -> None:
    op.execute(_UP_SQL)


def downgrade() -> None:
    op.execute(_DOWN_SQL)
