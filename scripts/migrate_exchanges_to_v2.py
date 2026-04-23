#!/usr/bin/env python3
"""
F2-T13 — migrate_exchanges_to_v2

For each historical `exchanges` row, create a synthetic turn + brain_plan +
emission_contract + emission in the v2 tables so that replay and UI queries
find consistent data. Legacy `exchanges` is left intact (read-only from now
on). This is a best-effort migration; the synthesis preserves the user-facing
artifacts but cannot recover the segment-level detail that the legacy path
never stored.

Usage
=====

  # From repo root, with DATABASE_URL exported:
  python scripts/migrate_exchanges_to_v2.py --dry-run
  python scripts/migrate_exchanges_to_v2.py

Idempotency
===========

Each exchange's synthesized turn carries `trace_id = f"migrated:{exchange.id}"`.
Re-runs detect this prefix and skip already-migrated exchanges.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from uuid import uuid4

# Make python-core imports work no matter where the script is run from.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "python-core"))

import asyncpg  # noqa: E402

from persistence.db import get_pool, get_database_url, close_pool  # noqa: E402

logger = logging.getLogger("migrate_exchanges_to_v2")


async def fetch_unmigrated_exchanges(conn: asyncpg.Connection, limit: int | None):
    sql = """
        SELECT e.id, e.session_id, e.index_in_session, e.interviewer_utterance,
               e.language_detected, e.question_analysis, e.suggested_response,
               e.quality_result, e.latency_ms, e.created_at
        FROM exchanges e
        WHERE NOT EXISTS (
          SELECT 1 FROM turns t
          WHERE t.session_id = e.session_id
            AND t.index_in_session = e.index_in_session
        )
        ORDER BY e.session_id, e.index_in_session
    """
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    return await conn.fetch(sql)


async def migrate_one(conn: asyncpg.Connection, ex) -> None:
    """Create turn + brain_plan + emission_contract + emission for one exchange."""
    trace_id = f"migrated:{ex['id']}"

    turn_id = uuid4()
    await conn.execute(
        """
        INSERT INTO turns
            (id, session_id, index_in_session, speaker, opened_at,
             closed_at, close_reason, close_confidence, final_text, language)
        VALUES ($1, $2, $3, 'interviewer', $4, $4, 'manual', 1.0, $5, $6)
        ON CONFLICT (session_id, index_in_session) DO NOTHING
        """,
        turn_id,
        ex["session_id"],
        ex["index_in_session"],
        ex["created_at"],
        ex["interviewer_utterance"] or "",
        ex["language_detected"],
    )

    # If insert was skipped due to conflict, fetch the existing turn id so we
    # still wire the downstream rows.
    row = await conn.fetchrow(
        "SELECT id FROM turns WHERE session_id=$1 AND index_in_session=$2",
        ex["session_id"],
        ex["index_in_session"],
    )
    turn_id = row["id"]

    plan_id = uuid4()
    await conn.execute(
        """
        INSERT INTO brain_plans
            (id, session_id, turn_id, snapshot_hash, stability, plan_source,
             confidence, payload, schema_version, trace_id, created_at)
        VALUES ($1, $2, $3, $4, 'stable', 'cached_stable', NULL, $5::jsonb, 2, $6, $7)
        """,
        plan_id,
        ex["session_id"],
        turn_id,
        f"migrated:{ex['id']}",
        ex["question_analysis"] or "{}",
        trace_id,
        ex["created_at"],
    )

    contract_id = uuid4()
    # The suggested_response JSON may include bullets/full_response/etc.
    suggested = ex["suggested_response"] or "{}"
    contract_payload = (
        '{"migrated_from_exchange":"'
        + str(ex["id"])
        + '","legacy_suggested_response":'
        + str(suggested).replace("'", "''")
        + "}"
    )
    await conn.execute(
        """
        INSERT INTO emission_contracts
            (id, session_id, turn_id, brain_plan_id, evidence_pack_id,
             readiness_score, render_shape, target_length, tone, language,
             payload, schema_version, trace_id, created_at)
        VALUES ($1, $2, $3, $4, NULL, 1.0, 'direct_structured', 200, 'balanced',
                $5, $6::jsonb, 1, $7, $8)
        """,
        contract_id,
        ex["session_id"],
        turn_id,
        plan_id,
        ex["language_detected"] or "en",
        suggested,  # store the legacy suggested_response as the payload
        trace_id,
        ex["created_at"],
    )

    # Extract a plausible full_response + bullets from suggested_response JSON.
    # asyncpg returns JSONB as str, so we parse lightly here.
    import json

    try:
        sr = json.loads(suggested) if isinstance(suggested, str) else (suggested or {})
    except json.JSONDecodeError:
        sr = {}
    full_response = sr.get("full_response") or ex["interviewer_utterance"] or ""
    bullets = sr.get("bullets") or []
    if not isinstance(bullets, list):
        bullets = []

    quality = ex["quality_result"]
    await conn.execute(
        """
        INSERT INTO emissions
            (id, session_id, turn_id, emission_contract_id,
             full_response, bullets, language, quality, latency_ms,
             latency_breakdown, trace_id, created_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, NULL, $10, $11)
        """,
        uuid4(),
        ex["session_id"],
        turn_id,
        contract_id,
        full_response,
        bullets,
        ex["language_detected"],
        quality or "{}",
        ex["latency_ms"],
        trace_id,
        ex["created_at"],
    )


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Only count; no writes.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s %(message)s",
    )

    logger.info("using DATABASE_URL=%s", os.environ.get("DATABASE_URL", "<default>"))

    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            exchanges = await fetch_unmigrated_exchanges(conn, args.limit)
            logger.info("unmigrated exchanges: %d", len(exchanges))
            if args.dry_run or not exchanges:
                return 0
            migrated = 0
            async with conn.transaction():
                for ex in exchanges:
                    await migrate_one(conn, ex)
                    migrated += 1
            logger.info("migrated %d exchanges -> v2 tables", migrated)
    finally:
        await close_pool()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
