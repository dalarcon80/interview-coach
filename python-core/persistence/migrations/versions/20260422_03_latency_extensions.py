"""latency_extensions — add turn_id/trace_id to latency_metrics; add exchanges_compat view

Revision ID: 20260422_03_latency_extensions
Revises: 20260422_02_turns_events
Create Date: 2026-04-22

- Extends `latency_metrics` with `turn_id` (FK to turns) and `trace_id`.
- Creates `exchanges_compat` view that projects the v2 tables back into the
  old exchanges shape so legacy readers keep working during the migration
  window. The view is read-only (not updatable).
"""

from __future__ import annotations

from alembic import op

revision: str = "20260422_03_latency_extensions"
down_revision: str | None = "20260422_02_turns_events"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


_UP_SQL = r"""
-- Add turn_id and trace_id to latency_metrics
ALTER TABLE latency_metrics
    ADD COLUMN IF NOT EXISTS turn_id UUID REFERENCES turns(id) ON DELETE CASCADE;
ALTER TABLE latency_metrics
    ADD COLUMN IF NOT EXISTS trace_id TEXT;

CREATE INDEX IF NOT EXISTS latency_metrics_turn_idx
    ON latency_metrics(turn_id);

-- Compatibility view: project v2 tables to the legacy exchanges shape so that
-- readers that still SELECT FROM exchanges receive a consistent answer while
-- migration F2-T13 repopulates the actual `exchanges` table. This view is
-- harmless because `exchanges` (the table) still exists; callers that need
-- the compat rows explicitly SELECT FROM exchanges_compat.
CREATE OR REPLACE VIEW exchanges_compat AS
SELECT
    em.id                                          AS id,
    em.session_id                                  AS session_id,
    t.index_in_session                             AS index_in_session,
    t.final_text                                   AS interviewer_utterance,
    t.language                                     AS language_detected,
    bp.payload                                     AS question_analysis,
    jsonb_build_object(
        'full_response', em.full_response,
        'bullets',       to_jsonb(em.bullets)
    )                                              AS suggested_response,
    COALESCE(em.quality, '{}'::jsonb)              AS quality_result,
    NULL::TEXT                                     AS user_actual_response,
    em.latency_ms                                  AS latency_ms,
    em.created_at                                  AS created_at
FROM emissions em
JOIN turns t        ON t.id = em.turn_id
LEFT JOIN brain_plans bp
    ON bp.turn_id = t.id
    AND bp.stability = 'stable'
    AND bp.created_at = (
        SELECT MAX(bp2.created_at)
        FROM brain_plans bp2
        WHERE bp2.turn_id = t.id
          AND bp2.stability = 'stable'
    );
"""


_DOWN_SQL = r"""
DROP VIEW IF EXISTS exchanges_compat;
DROP INDEX IF EXISTS latency_metrics_turn_idx;
ALTER TABLE latency_metrics DROP COLUMN IF EXISTS trace_id;
ALTER TABLE latency_metrics DROP COLUMN IF EXISTS turn_id;
"""


def upgrade() -> None:
    op.execute(_UP_SQL)


def downgrade() -> None:
    op.execute(_DOWN_SQL)
