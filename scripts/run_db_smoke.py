#!/usr/bin/env python3
"""
F2-T14 — run_db_smoke.py

End-to-end smoke test for the v2 persistence layer:
1. Opens pool, asserts startup health (fail-loud).
2. Creates a synthetic 3-turn session writing through event_writer + outbox.
3. Starts the outbox worker, waits for it to drain.
4. Asserts expected row counts in each v2 table.
5. Cleans up the synthetic session.

Usage
=====
  DATABASE_URL=... python scripts/run_db_smoke.py
  # exit 0 on success, non-zero on any failed assertion.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from uuid import UUID, uuid4

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "python-core"))

from persistence import outbox, session_store  # noqa: E402
from persistence.db import assert_startup_db_ok, close_pool, get_pool  # noqa: E402
from persistence.event_writer import write_event  # noqa: E402

logger = logging.getLogger("run_db_smoke")


async def _assert_counts(session_id: UUID) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        sessions_n = await conn.fetchval(
            "SELECT COUNT(*) FROM sessions WHERE id=$1", session_id
        )
        segments_n = await conn.fetchval(
            "SELECT COUNT(*) FROM segments WHERE session_id=$1", session_id
        )
        turns_n = await conn.fetchval(
            "SELECT COUNT(*) FROM turns WHERE session_id=$1", session_id
        )
        bp_n = await conn.fetchval(
            "SELECT COUNT(*) FROM brain_plans WHERE session_id=$1", session_id
        )
        ec_n = await conn.fetchval(
            "SELECT COUNT(*) FROM emission_contracts WHERE session_id=$1", session_id
        )
        em_n = await conn.fetchval(
            "SELECT COUNT(*) FROM emissions WHERE session_id=$1", session_id
        )
        evs_n = await conn.fetchval(
            "SELECT COUNT(*) FROM event_log WHERE session_id=$1", session_id
        )

    logger.info(
        "counts: sessions=%d segments=%d turns=%d brain_plans=%d "
        "emission_contracts=%d emissions=%d event_log=%d",
        sessions_n,
        segments_n,
        turns_n,
        bp_n,
        ec_n,
        em_n,
        evs_n,
    )

    assert sessions_n == 1, f"sessions should be 1, got {sessions_n}"
    assert segments_n >= 6, f"segments >= 6, got {segments_n}"
    assert turns_n == 3, f"turns should be 3, got {turns_n}"
    assert bp_n == 3, f"brain_plans should be 3, got {bp_n}"
    assert ec_n == 3, f"emission_contracts should be 3, got {ec_n}"
    assert em_n == 3, f"emissions should be 3, got {em_n}"
    assert evs_n >= 15, f"event_log >= 15, got {evs_n}"


async def _cleanup(session_id: UUID) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        # ON DELETE CASCADE from sessions cleans up the dependent rows.
        await conn.execute(
            "DELETE FROM outbox WHERE trace_id LIKE $1", f"smoke:{session_id}%"
        )
        await conn.execute("DELETE FROM sessions WHERE id=$1", session_id)


async def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s %(message)s",
    )

    await assert_startup_db_ok()

    # 1) Start outbox worker with the session_store sink factory.
    sink_factory = session_store.build_outbox_sink_factory()
    worker = outbox.OutboxWorker(sink_factory)
    await worker.start()

    session_id = await session_store.create_session(status="active")
    logger.info("smoke session_id=%s", session_id)

    try:
        trace_id = f"smoke:{session_id}"
        seg_seq = 0

        for i in range(3):  # 3 turns
            turn_id = uuid4()
            # Two partials (is_final=false) + one final per turn -> 6 segments total.
            for _ in range(2):
                seg_seq += 1
                await write_event(
                    session_id=session_id,
                    event_type="stt.partial",
                    payload={
                        "turn_index": i,
                        "text": f"partial text {seg_seq}",
                        "language": "en",
                    },
                    trace_id=trace_id,
                )
                await outbox.enqueue(
                    "segments",
                    {
                        "session_id": str(session_id),
                        "seq": seg_seq,
                        "speaker": "interviewer",
                        "text": f"partial text {seg_seq}",
                        "is_final": False,
                        "turn_id": str(turn_id),
                        "language": "en",
                    },
                    trace_id=trace_id,
                )
            seg_seq += 1
            final_text = f"What do you think about topic {i}?"
            await write_event(
                session_id=session_id,
                event_type="stt.final",
                payload={
                    "turn_index": i,
                    "text": final_text,
                    "speaker": "interviewer",
                    "language": "en",
                    "confidence": 0.95,
                },
                trace_id=trace_id,
            )
            await outbox.enqueue(
                "segments",
                {
                    "session_id": str(session_id),
                    "seq": seg_seq,
                    "speaker": "interviewer",
                    "text": final_text,
                    "is_final": True,
                    "turn_id": str(turn_id),
                    "language": "en",
                    "confidence": 0.95,
                },
                trace_id=trace_id,
            )
            # Create turn (closed).
            await outbox.enqueue(
                "turns",
                {
                    "id": str(turn_id),
                    "session_id": str(session_id),
                    "index_in_session": i,
                    "speaker": "interviewer",
                    "opened_at": None,
                    "closed_at": None,
                    "close_reason": "utterance_end",
                    "close_confidence": 0.92,
                    "final_text": final_text,
                    "language": "en",
                },
                trace_id=trace_id,
            )
            # Brain plan (stable).
            plan_id = str(uuid4())
            plan_payload = {
                "id": plan_id,
                "version": 2,
                "session_id": str(session_id),
                "turn_id": str(turn_id),
                "ask": {"primary_ask": final_text, "family": "general"},
                "intent": {"summary": "smoke test intent"},
                "answer_blueprint": {"must_cover": ["smoke"]},
                "trace_id": trace_id,
            }
            await outbox.enqueue(
                "brain_plans",
                {
                    "session_id": str(session_id),
                    "turn_id": str(turn_id),
                    "snapshot_hash": f"smoke-hash-{i}",
                    "stability": "stable",
                    "plan_source": "safe_fallback",
                    "confidence": 0.9,
                    "payload": plan_payload,
                    "trace_id": trace_id,
                },
                trace_id=trace_id,
            )
            await write_event(
                session_id=session_id,
                event_type="brain.plan.created",
                payload={"plan_id": plan_id, "source": "safe_fallback"},
                trace_id=trace_id,
            )
            # Emission contract.
            contract_id = str(uuid4())
            contract_payload = {
                "id": contract_id,
                "version": 1,
                "render_shape": "direct_short",
                "target_length_words": 120,
                "tone": "balanced",
                "language": "en",
                "must_cover": ["smoke"],
                "avoid": [],
                "style_guard": {"style": "mixed"},
                "emit_readiness_score": 0.9,
            }
            await outbox.enqueue(
                "emission_contracts",
                {
                    "session_id": str(session_id),
                    "turn_id": str(turn_id),
                    "brain_plan_id": plan_id,
                    "evidence_pack_id": None,
                    "readiness_score": 0.9,
                    "render_shape": "direct_short",
                    "target_length": 120,
                    "tone": "balanced",
                    "language": "en",
                    "payload": contract_payload,
                    "trace_id": trace_id,
                },
                trace_id=trace_id,
            )
            await write_event(
                session_id=session_id,
                event_type="emit.contract.created",
                payload={"contract_id": contract_id, "readiness_score": 0.9},
                trace_id=trace_id,
            )
            # Emission.
            await outbox.enqueue(
                "emissions",
                {
                    "session_id": str(session_id),
                    "turn_id": str(turn_id),
                    "emission_contract_id": contract_id,
                    "full_response": f"Smoke response {i}",
                    "bullets": [f"bullet a {i}", f"bullet b {i}"],
                    "language": "en",
                    "quality": {"passed": True, "score": 0.9},
                    "latency_ms": 123,
                    "trace_id": trace_id,
                },
                trace_id=trace_id,
            )
            await write_event(
                session_id=session_id,
                event_type="emit.response",
                payload={"latency_ms": 123, "full_response_len": 20},
                trace_id=trace_id,
            )

        # Wait for the worker to drain.
        for _ in range(50):
            stats = await outbox.stats()
            if stats["pending"] == 0 and stats["processing"] == 0:
                break
            await asyncio.sleep(0.1)

        await _assert_counts(session_id)
        logger.info("SMOKE OK")
        return 0
    finally:
        await worker.stop()
        await _cleanup(session_id)
        await close_pool()


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except AssertionError as e:
        logger.error("SMOKE FAILED: %s", e)
        raise SystemExit(1)
