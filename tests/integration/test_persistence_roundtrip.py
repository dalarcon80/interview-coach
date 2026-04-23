"""
F2-T15 — test_persistence_roundtrip

Round-trip tests for the v2 persistence layer. Validate:

1. Events written via `write_event` land in event_log with monotonic seq.
2. Outbox sinks write turns/brain_plans/emission_contracts/emissions
   into the right tables.
3. The in-process seq counter re-seeds from DB after a pool restart.

Requires a reachable Postgres with the v2 schema applied. If the DB is not
reachable the test is SKIPPED.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "python-core"))

from persistence import event_writer, outbox, session_store  # noqa: E402
from persistence.db import (  # noqa: E402
    check_health,
    close_pool,
    get_pool,
    init_pool,
)


pytestmark = pytest.mark.asyncio


async def _ensure_db_or_skip() -> None:
    h = await check_health()
    await close_pool()
    if not h.connected:
        pytest.skip("DATABASE_URL unreachable; persistence round-trip test skipped")


async def _setup_session() -> UUID:
    await init_pool()
    session_id = await session_store.create_session(status="active")
    event_writer.reset_session_seq(session_id, 0)
    return session_id


async def _teardown_session(session_id: UUID) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM outbox WHERE trace_id LIKE $1",
            f"ptest:{session_id}%",
        )
        await conn.execute("DELETE FROM sessions WHERE id = $1", session_id)
    await close_pool()


async def test_event_log_monotonic_seq():
    await _ensure_db_or_skip()
    session_id = await _setup_session()
    trace_id = f"ptest:{session_id}"
    try:
        s1 = await event_writer.write_event(
            session_id=session_id,
            event_type="session.opened",
            payload={"profile": "default"},
            trace_id=trace_id,
        )
        s2 = await event_writer.write_event(
            session_id=session_id,
            event_type="stt.partial",
            payload={"text": "hi"},
            trace_id=trace_id,
        )
        s3 = await event_writer.write_event(
            session_id=session_id,
            event_type="stt.final",
            payload={"text": "hi there", "speaker": "interviewer"},
            trace_id=trace_id,
        )

        assert s1 == 1
        assert s2 == 2
        assert s3 == 3

        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT seq, event_type FROM event_log WHERE session_id=$1 "
                "ORDER BY seq",
                session_id,
            )
        assert [(r["seq"], r["event_type"]) for r in rows] == [
            (1, "session.opened"),
            (2, "stt.partial"),
            (3, "stt.final"),
        ]
    finally:
        await _teardown_session(session_id)


async def test_turn_and_emission_chain_via_outbox():
    await _ensure_db_or_skip()
    session_id = await _setup_session()
    trace_id = f"ptest:{session_id}"

    worker = outbox.OutboxWorker(session_store.build_outbox_sink_factory())
    await worker.start()
    try:
        turn_id = uuid4()
        plan_id = uuid4()
        contract_id = uuid4()

        await outbox.enqueue(
            "turns",
            {
                "id": str(turn_id),
                "session_id": str(session_id),
                "index_in_session": 0,
                "speaker": "interviewer",
                "opened_at": None,
                "closed_at": None,
                "close_reason": "utterance_end",
                "close_confidence": 0.9,
                "final_text": "Hello world?",
                "language": "en",
            },
            trace_id=trace_id,
        )
        await outbox.enqueue(
            "brain_plans",
            {
                "session_id": str(session_id),
                "turn_id": str(turn_id),
                "snapshot_hash": "roundtrip-1",
                "stability": "stable",
                "plan_source": "safe_fallback",
                "confidence": 0.8,
                "payload": {"id": str(plan_id), "version": 2},
                "trace_id": trace_id,
            },
            trace_id=trace_id,
        )
        await outbox.enqueue(
            "emission_contracts",
            {
                "session_id": str(session_id),
                "turn_id": str(turn_id),
                "brain_plan_id": str(plan_id),
                "evidence_pack_id": None,
                "readiness_score": 0.9,
                "render_shape": "direct_short",
                "target_length": 100,
                "tone": "balanced",
                "language": "en",
                "payload": {"id": str(contract_id), "version": 1},
                "trace_id": trace_id,
            },
            trace_id=trace_id,
        )
        await outbox.enqueue(
            "emissions",
            {
                "session_id": str(session_id),
                "turn_id": str(turn_id),
                "emission_contract_id": str(contract_id),
                "full_response": "Hi!",
                "bullets": ["a"],
                "language": "en",
                "quality": {"passed": True, "score": 1.0},
                "latency_ms": 42,
                "trace_id": trace_id,
            },
            trace_id=trace_id,
        )

        # Wait up to 10s for drain.
        for _ in range(100):
            st = await outbox.stats()
            if st["pending"] == 0 and st["processing"] == 0:
                break
            await asyncio.sleep(0.1)

        pool = await get_pool()
        async with pool.acquire() as conn:
            t = await conn.fetchrow("SELECT final_text FROM turns WHERE id=$1", turn_id)
            bp = await conn.fetchrow(
                "SELECT snapshot_hash FROM brain_plans WHERE turn_id=$1", turn_id
            )
            em = await conn.fetchrow(
                "SELECT full_response FROM emissions WHERE turn_id=$1", turn_id
            )
        assert t is not None and t["final_text"] == "Hello world?"
        assert bp is not None and bp["snapshot_hash"] == "roundtrip-1"
        assert em is not None and em["full_response"] == "Hi!"
    finally:
        await worker.stop()
        await _teardown_session(session_id)


async def test_seq_continues_after_pool_restart():
    await _ensure_db_or_skip()
    session_id = await _setup_session()
    trace_id = f"ptest:{session_id}"
    try:
        await event_writer.write_event(
            session_id=session_id,
            event_type="session.opened",
            payload={},
            trace_id=trace_id,
        )
        # Simulate "process restart": close pool AND drop the in-process
        # counter entirely so the next write re-seeds from MAX(seq) in DB.
        await close_pool()
        event_writer._SEQ.counters.pop(session_id, None)

        s = await event_writer.write_event(
            session_id=session_id,
            event_type="stt.final",
            payload={"text": "after restart"},
            trace_id=trace_id,
        )
        assert s == 2, f"seq should continue from 2 after re-seed, got {s}"
    finally:
        await _teardown_session(session_id)
