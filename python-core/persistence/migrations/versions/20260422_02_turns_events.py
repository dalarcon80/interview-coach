"""turns_events — add turns, segments, brain_plans, emission_contracts, emissions, evidence_packs, outbox, contract_versions; upgrade event_log

Revision ID: 20260422_02_turns_events
Revises: 20260422_01_baseline
Create Date: 2026-04-22

Introduces the event-sourced persistence layer per ADR-003 and
DATA_MODEL_REDESIGN §2.2.

New tables:
- segments           : STT events persisted (partials + finals)
- turns              : semantic windows (interviewer / candidate)
- brain_plans        : BrainPlan v2 payloads (semantic-only)
- evidence_packs     : snapshot of evidence per turn
- emission_contracts : render contract produced from BrainPlan
- emissions          : final responses (full_response primary)
- outbox             : durable write buffer (outbox pattern)
- contract_versions  : registry of active contract schemas

Event_log is extended with a per-session seq column and a UNIQUE constraint
(session_id, seq) for deterministic replay.

This migration is additive. `exchanges` remains intact during this release
as a fallback read path.

Downgrade drops all additions but preserves the baseline schema.
"""

from __future__ import annotations

from alembic import op

revision: str = "20260422_02_turns_events"
down_revision: str | None = "20260422_01_baseline"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


_UP_SQL = r"""
-- =========================================================================
-- Turns — semantic window per speaker
-- =========================================================================
CREATE TABLE IF NOT EXISTS turns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    index_in_session INT NOT NULL,
    speaker TEXT NOT NULL
        CHECK (speaker IN ('interviewer','candidate','unknown')),
    opened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at TIMESTAMPTZ,
    close_reason TEXT CHECK (close_reason IN
        ('utterance_end','silence','syntactic','timeout','manual','hybrid')),
    close_confidence REAL CHECK (close_confidence >= 0 AND close_confidence <= 1),
    final_text TEXT NOT NULL DEFAULT '',
    language TEXT,
    UNIQUE(session_id, index_in_session)
);
CREATE INDEX IF NOT EXISTS turns_session_opened_idx ON turns(session_id, opened_at);

-- =========================================================================
-- Segments — every relevant STT event persisted
-- =========================================================================
CREATE TABLE IF NOT EXISTS segments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    turn_id UUID REFERENCES turns(id) ON DELETE SET NULL,
    seq BIGINT NOT NULL,
    speaker TEXT NOT NULL,
    text TEXT NOT NULL,
    language TEXT,
    confidence REAL,
    is_final BOOLEAN NOT NULL,
    t_start_ms INT,
    t_end_ms INT,
    stt_request_id TEXT,
    provider TEXT,
    model TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(session_id, seq)
);
CREATE INDEX IF NOT EXISTS segments_turn_idx ON segments(turn_id, seq);
CREATE INDEX IF NOT EXISTS segments_session_created_idx
    ON segments(session_id, created_at);

-- =========================================================================
-- Brain plans — BrainPlan v2 payloads (semantic only)
-- =========================================================================
CREATE TABLE IF NOT EXISTS brain_plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    turn_id UUID NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
    snapshot_hash TEXT NOT NULL,
    stability TEXT NOT NULL
        CHECK (stability IN ('draft','stable_candidate','stable')),
    plan_source TEXT NOT NULL
        CHECK (plan_source IN ('llm_fast','safe_fallback','cached_stable')),
    confidence REAL CHECK (confidence >= 0 AND confidence <= 1),
    payload JSONB NOT NULL,
    schema_version INT NOT NULL DEFAULT 2,
    trace_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS brain_plans_turn_idx
    ON brain_plans(turn_id, created_at DESC);
CREATE INDEX IF NOT EXISTS brain_plans_hash_idx
    ON brain_plans(snapshot_hash);
CREATE INDEX IF NOT EXISTS brain_plans_stability_idx
    ON brain_plans(stability, created_at DESC);

-- =========================================================================
-- Evidence packs — snapshot of evidence per turn
-- =========================================================================
CREATE TABLE IF NOT EXISTS evidence_packs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    turn_id UUID NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
    payload JSONB NOT NULL,
    schema_version INT NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS evidence_packs_turn_idx ON evidence_packs(turn_id);

-- =========================================================================
-- Emission contracts — render contract
-- =========================================================================
CREATE TABLE IF NOT EXISTS emission_contracts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    turn_id UUID NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
    brain_plan_id UUID NOT NULL REFERENCES brain_plans(id) ON DELETE CASCADE,
    evidence_pack_id UUID REFERENCES evidence_packs(id) ON DELETE SET NULL,
    readiness_score REAL NOT NULL CHECK (readiness_score >= 0 AND readiness_score <= 1),
    render_shape TEXT NOT NULL,
    target_length INT NOT NULL,
    tone TEXT NOT NULL,
    language TEXT NOT NULL,
    payload JSONB NOT NULL,
    schema_version INT NOT NULL DEFAULT 1,
    trace_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS emission_contracts_turn_idx
    ON emission_contracts(turn_id, created_at DESC);

-- =========================================================================
-- Emissions — final generated responses
-- =========================================================================
CREATE TABLE IF NOT EXISTS emissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    turn_id UUID NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
    emission_contract_id UUID NOT NULL REFERENCES emission_contracts(id) ON DELETE CASCADE,
    full_response TEXT NOT NULL,
    bullets TEXT[] NOT NULL DEFAULT '{}',
    language TEXT,
    quality JSONB,
    latency_ms INT,
    latency_breakdown JSONB,
    trace_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS emissions_turn_idx ON emissions(turn_id);
CREATE INDEX IF NOT EXISTS emissions_session_created_idx
    ON emissions(session_id, created_at DESC);

-- =========================================================================
-- Outbox — durable write buffer
-- =========================================================================
CREATE TABLE IF NOT EXISTS outbox (
    id BIGSERIAL PRIMARY KEY,
    target_table TEXT NOT NULL,
    payload JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','processing','completed','failed','dead')),
    attempts INT NOT NULL DEFAULT 0,
    max_attempts INT NOT NULL DEFAULT 5,
    last_error TEXT,
    trace_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at TIMESTAMPTZ,
    next_retry_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS outbox_pending_idx
    ON outbox(status, next_retry_at) WHERE status IN ('pending','failed');
CREATE INDEX IF NOT EXISTS outbox_created_idx ON outbox(created_at);

-- =========================================================================
-- Contract versions registry
-- =========================================================================
CREATE TABLE IF NOT EXISTS contract_versions (
    name TEXT NOT NULL
        CHECK (name IN ('brain_plan','emission_contract','generated_response','event')),
    version INT NOT NULL,
    schema JSONB NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    introduced_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(name, version)
);

-- =========================================================================
-- Event log upgrade — add seq + trace_id index + UNIQUE(session_id, seq)
-- =========================================================================
-- Add seq column if missing
ALTER TABLE event_log ADD COLUMN IF NOT EXISTS seq BIGINT;

-- Backfill seq for existing rows, partitioned by session_id, ordered by id.
-- Idempotent: rows already having a seq keep it.
WITH ranked AS (
    SELECT
        id,
        ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY id) AS new_seq
    FROM event_log
    WHERE seq IS NULL
)
UPDATE event_log el
SET seq = r.new_seq
FROM ranked r
WHERE el.id = r.id;

-- Enforce NOT NULL now that backfill is done (only if not already enforced)
ALTER TABLE event_log ALTER COLUMN seq SET NOT NULL;

-- Add UNIQUE constraint (session_id, seq) if missing
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'event_log_session_seq_key'
          AND conrelid = 'event_log'::regclass
    ) THEN
        ALTER TABLE event_log
            ADD CONSTRAINT event_log_session_seq_key
            UNIQUE (session_id, seq);
    END IF;
END$$;

CREATE INDEX IF NOT EXISTS event_log_type_time_idx
    ON event_log(event_type, created_at);
CREATE INDEX IF NOT EXISTS event_log_trace_idx
    ON event_log(trace_id) WHERE trace_id IS NOT NULL;
"""


_DOWN_SQL = r"""
DROP INDEX IF EXISTS event_log_trace_idx;
DROP INDEX IF EXISTS event_log_type_time_idx;
ALTER TABLE event_log DROP CONSTRAINT IF EXISTS event_log_session_seq_key;
ALTER TABLE event_log DROP COLUMN IF EXISTS seq;

DROP TABLE IF EXISTS contract_versions;
DROP INDEX IF EXISTS outbox_created_idx;
DROP INDEX IF EXISTS outbox_pending_idx;
DROP TABLE IF EXISTS outbox;

DROP INDEX IF EXISTS emissions_session_created_idx;
DROP INDEX IF EXISTS emissions_turn_idx;
DROP TABLE IF EXISTS emissions;

DROP INDEX IF EXISTS emission_contracts_turn_idx;
DROP TABLE IF EXISTS emission_contracts;

DROP INDEX IF EXISTS evidence_packs_turn_idx;
DROP TABLE IF EXISTS evidence_packs;

DROP INDEX IF EXISTS brain_plans_stability_idx;
DROP INDEX IF EXISTS brain_plans_hash_idx;
DROP INDEX IF EXISTS brain_plans_turn_idx;
DROP TABLE IF EXISTS brain_plans;

DROP INDEX IF EXISTS segments_session_created_idx;
DROP INDEX IF EXISTS segments_turn_idx;
DROP TABLE IF EXISTS segments;

DROP INDEX IF EXISTS turns_session_opened_idx;
DROP TABLE IF EXISTS turns;
"""


def upgrade() -> None:
    op.execute(_UP_SQL)


def downgrade() -> None:
    op.execute(_DOWN_SQL)
