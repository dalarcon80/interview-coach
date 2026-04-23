"""
Interview Coach — persistence.session_store

CRUD for v2 persistence tables: sessions, turns, segments, brain_plans,
evidence_packs, emission_contracts, emissions.

The hot path does NOT call this module synchronously. The pipeline emits
events -> event_writer -> event_log + outbox. The outbox worker then
drains into these tables via a sink that delegates here.

Callers (e.g. HTTP endpoints that read historical data) call these
functions directly. They are idempotent where possible: INSERT operations
use ON CONFLICT for (session_id, seq)-style uniqueness.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional
from uuid import UUID, uuid4

from persistence.db import get_pool

logger = logging.getLogger(__name__)


# =============================================================================
# Sessions
# =============================================================================
async def create_session(
    *,
    config_id: Optional[UUID] = None,
    status: str = "active",
    trace_id: Optional[str] = None,
) -> UUID:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO sessions (config_id, status, started_at)
            VALUES ($1, $2, now())
            RETURNING id
            """,
            config_id,
            status,
        )
        return row["id"]


async def end_session(session_id: UUID, *, summary: Optional[dict[str, Any]] = None) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.fetchval(
            """
            UPDATE sessions
            SET status='ended', ended_at=now(), summary=$2
            WHERE id=$1
            RETURNING id
            """,
            session_id,
            json.dumps(summary) if summary is not None else None,
        )
    return result is not None


async def get_session(session_id: UUID) -> Optional[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, config_id, status, started_at, ended_at, summary
            FROM sessions
            WHERE id=$1
            """,
            session_id,
        )
    return _row_to_dict(row)


# =============================================================================
# Turns
# =============================================================================
async def upsert_turn(
    *,
    turn_id: UUID,
    session_id: UUID,
    index_in_session: int,
    speaker: str,
    opened_at: Optional[datetime] = None,
    closed_at: Optional[datetime] = None,
    close_reason: Optional[str] = None,
    close_confidence: Optional[float] = None,
    final_text: str = "",
    language: Optional[str] = None,
) -> UUID:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO turns
                (id, session_id, index_in_session, speaker, opened_at,
                 closed_at, close_reason, close_confidence, final_text, language)
            VALUES ($1, $2, $3, $4, COALESCE($5, now()), $6, $7, $8, $9, $10)
            ON CONFLICT (session_id, index_in_session) DO UPDATE SET
                closed_at        = COALESCE(EXCLUDED.closed_at, turns.closed_at),
                close_reason     = COALESCE(EXCLUDED.close_reason, turns.close_reason),
                close_confidence = COALESCE(EXCLUDED.close_confidence, turns.close_confidence),
                final_text       = EXCLUDED.final_text,
                language         = COALESCE(EXCLUDED.language, turns.language)
            """,
            turn_id,
            session_id,
            index_in_session,
            speaker,
            opened_at,
            closed_at,
            close_reason,
            close_confidence,
            final_text,
            language,
        )
    return turn_id


async def list_closed_turns(session_id: UUID, limit: int = 50) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, session_id, index_in_session, speaker, opened_at,
                   closed_at, close_reason, close_confidence, final_text, language
            FROM turns
            WHERE session_id=$1 AND closed_at IS NOT NULL
            ORDER BY index_in_session DESC
            LIMIT $2
            """,
            session_id,
            limit,
        )
    # return in chronological order (oldest first)
    return [_row_to_dict(r) for r in reversed(rows)]


async def list_recent_turns_for_context(session_id: UUID, window: int = 4) -> list[dict[str, Any]]:
    """HR-2 compliant: last `window` closed turns, or all if fewer exist.

    Never returns empty when turns exist. Always chronological.
    """
    turns = await list_closed_turns(session_id, limit=window)
    return turns


# =============================================================================
# Segments
# =============================================================================
async def create_segment(
    *,
    session_id: UUID,
    seq: int,
    speaker: str,
    text: str,
    is_final: bool,
    turn_id: Optional[UUID] = None,
    language: Optional[str] = None,
    confidence: Optional[float] = None,
    t_start_ms: Optional[int] = None,
    t_end_ms: Optional[int] = None,
    stt_request_id: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> UUID:
    seg_id = uuid4()
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO segments
                (id, session_id, turn_id, seq, speaker, text, language, confidence,
                 is_final, t_start_ms, t_end_ms, stt_request_id, provider, model)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
            ON CONFLICT (session_id, seq) DO NOTHING
            """,
            seg_id,
            session_id,
            turn_id,
            seq,
            speaker,
            text,
            language,
            confidence,
            is_final,
            t_start_ms,
            t_end_ms,
            stt_request_id,
            provider,
            model,
        )
    return seg_id


# =============================================================================
# Brain plans
# =============================================================================
async def save_brain_plan(
    *,
    session_id: UUID,
    turn_id: UUID,
    snapshot_hash: str,
    stability: str,
    plan_source: str,
    payload: dict[str, Any],
    confidence: Optional[float] = None,
    trace_id: Optional[str] = None,
) -> UUID:
    plan_id = UUID(str(payload.get("id"))) if payload.get("id") else uuid4()
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO brain_plans
                (id, session_id, turn_id, snapshot_hash, stability, plan_source,
                 confidence, payload, trace_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9)
            """,
            plan_id,
            session_id,
            turn_id,
            snapshot_hash,
            stability,
            plan_source,
            confidence,
            json.dumps(payload),
            trace_id,
        )
    return plan_id


async def find_cached_stable_plan(
    *,
    turn_id: UUID,
    snapshot_hash: str,
) -> Optional[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, session_id, turn_id, snapshot_hash, stability,
                   plan_source, confidence, payload, trace_id, created_at
            FROM brain_plans
            WHERE turn_id=$1 AND snapshot_hash=$2 AND stability='stable'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            turn_id,
            snapshot_hash,
        )
    return _row_to_dict(row)


# =============================================================================
# Emission contracts / Emissions / Evidence packs
# =============================================================================
async def save_evidence_pack(
    *,
    session_id: UUID,
    turn_id: UUID,
    payload: dict[str, Any],
) -> UUID:
    pack_id = uuid4()
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO evidence_packs (id, session_id, turn_id, payload)
            VALUES ($1, $2, $3, $4::jsonb)
            """,
            pack_id,
            session_id,
            turn_id,
            json.dumps(payload),
        )
    return pack_id


async def save_emission_contract(
    *,
    session_id: UUID,
    turn_id: UUID,
    brain_plan_id: UUID,
    evidence_pack_id: Optional[UUID],
    readiness_score: float,
    render_shape: str,
    target_length: int,
    tone: str,
    language: str,
    payload: dict[str, Any],
    trace_id: Optional[str] = None,
) -> UUID:
    contract_id = UUID(str(payload.get("id"))) if payload.get("id") else uuid4()
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO emission_contracts
                (id, session_id, turn_id, brain_plan_id, evidence_pack_id,
                 readiness_score, render_shape, target_length, tone, language,
                 payload, trace_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb, $12)
            """,
            contract_id,
            session_id,
            turn_id,
            brain_plan_id,
            evidence_pack_id,
            readiness_score,
            render_shape,
            target_length,
            tone,
            language,
            json.dumps(payload),
            trace_id,
        )
    return contract_id


async def save_emission(
    *,
    session_id: UUID,
    turn_id: UUID,
    emission_contract_id: UUID,
    full_response: str,
    bullets: Optional[list[str]] = None,
    language: Optional[str] = None,
    quality: Optional[dict[str, Any]] = None,
    latency_ms: Optional[int] = None,
    latency_breakdown: Optional[dict[str, Any]] = None,
    trace_id: Optional[str] = None,
) -> UUID:
    emission_id = uuid4()
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO emissions
                (id, session_id, turn_id, emission_contract_id,
                 full_response, bullets, language, quality, latency_ms,
                 latency_breakdown, trace_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7,
                    $8::jsonb, $9, $10::jsonb, $11)
            """,
            emission_id,
            session_id,
            turn_id,
            emission_contract_id,
            full_response,
            bullets or [],
            language,
            json.dumps(quality) if quality is not None else None,
            latency_ms,
            json.dumps(latency_breakdown) if latency_breakdown is not None else None,
            trace_id,
        )
    return emission_id


# =============================================================================
# Outbox sink factory
# =============================================================================
def build_outbox_sink_factory():
    """Create a sink factory compatible with persistence.outbox.OutboxWorker.

    Given a target_table string, returns an async callable that inserts the
    payload via the matching save_* function.
    """

    async def event_log_sink(payload: dict[str, Any]) -> None:
        """Fallback row for event_log (replays NDJSON-drained rows)."""
        from persistence.db import get_pool as _get_pool

        pool = await _get_pool()
        session_id = payload.get("session_id")
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO event_log
                    (session_id, seq, event_type, payload, trace_id, latency_ms)
                VALUES ($1, $2, $3, $4::jsonb, $5, $6)
                ON CONFLICT (session_id, seq) DO NOTHING
                """,
                UUID(session_id) if session_id else None,
                payload.get("seq"),
                payload["event_type"],
                json.dumps(payload.get("payload", {})),
                payload.get("trace_id"),
                payload.get("latency_ms"),
            )

    async def turns_sink(payload: dict[str, Any]) -> None:
        await upsert_turn(
            turn_id=UUID(payload["id"]),
            session_id=UUID(payload["session_id"]),
            index_in_session=payload["index_in_session"],
            speaker=payload["speaker"],
            opened_at=_parse_dt(payload.get("opened_at")),
            closed_at=_parse_dt(payload.get("closed_at")),
            close_reason=payload.get("close_reason"),
            close_confidence=payload.get("close_confidence"),
            final_text=payload.get("final_text", ""),
            language=payload.get("language"),
        )

    async def segments_sink(payload: dict[str, Any]) -> None:
        await create_segment(
            session_id=UUID(payload["session_id"]),
            seq=payload["seq"],
            speaker=payload["speaker"],
            text=payload["text"],
            is_final=payload["is_final"],
            turn_id=UUID(payload["turn_id"]) if payload.get("turn_id") else None,
            language=payload.get("language"),
            confidence=payload.get("confidence"),
            t_start_ms=payload.get("t_start_ms"),
            t_end_ms=payload.get("t_end_ms"),
            stt_request_id=payload.get("stt_request_id"),
            provider=payload.get("provider"),
            model=payload.get("model"),
        )

    async def brain_plans_sink(payload: dict[str, Any]) -> None:
        await save_brain_plan(
            session_id=UUID(payload["session_id"]),
            turn_id=UUID(payload["turn_id"]),
            snapshot_hash=payload["snapshot_hash"],
            stability=payload["stability"],
            plan_source=payload["plan_source"],
            payload=payload["payload"],
            confidence=payload.get("confidence"),
            trace_id=payload.get("trace_id"),
        )

    async def evidence_packs_sink(payload: dict[str, Any]) -> None:
        await save_evidence_pack(
            session_id=UUID(payload["session_id"]),
            turn_id=UUID(payload["turn_id"]),
            payload=payload["payload"],
        )

    async def emission_contracts_sink(payload: dict[str, Any]) -> None:
        await save_emission_contract(
            session_id=UUID(payload["session_id"]),
            turn_id=UUID(payload["turn_id"]),
            brain_plan_id=UUID(payload["brain_plan_id"]),
            evidence_pack_id=UUID(payload["evidence_pack_id"])
            if payload.get("evidence_pack_id")
            else None,
            readiness_score=payload["readiness_score"],
            render_shape=payload["render_shape"],
            target_length=payload["target_length"],
            tone=payload["tone"],
            language=payload["language"],
            payload=payload["payload"],
            trace_id=payload.get("trace_id"),
        )

    async def emissions_sink(payload: dict[str, Any]) -> None:
        await save_emission(
            session_id=UUID(payload["session_id"]),
            turn_id=UUID(payload["turn_id"]),
            emission_contract_id=UUID(payload["emission_contract_id"]),
            full_response=payload["full_response"],
            bullets=payload.get("bullets"),
            language=payload.get("language"),
            quality=payload.get("quality"),
            latency_ms=payload.get("latency_ms"),
            latency_breakdown=payload.get("latency_breakdown"),
            trace_id=payload.get("trace_id"),
        )

    table_to_sink = {
        "event_log": event_log_sink,
        "turns": turns_sink,
        "segments": segments_sink,
        "brain_plans": brain_plans_sink,
        "evidence_packs": evidence_packs_sink,
        "emission_contracts": emission_contracts_sink,
        "emissions": emissions_sink,
    }

    def factory(target_table: str):
        return table_to_sink.get(target_table)

    return factory


# =============================================================================
# Helpers
# =============================================================================
def _row_to_dict(row) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    return {k: v for k, v in row.items()}


def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
