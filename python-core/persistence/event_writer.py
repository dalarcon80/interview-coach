"""
Interview Coach — persistence.event_writer

Single entry point to write pipeline events to `event_log`. All live pipeline
writes flow through here; complex destinations (segments, turns, etc.) go
via the `outbox` so the hot path is not blocked by slow writes.

Per ADR-003, `event_log` is the source of truth for replay:
- (session_id, seq) is UNIQUE.
- `seq` is assigned monotonically per session by a small in-process counter
  with a DB-backed fallback bootstrapped from SELECT MAX.

Flow
====

event -> write_event(event)
  1) Compute (session_id, seq) locally.
  2) Either:
       a) DB reachable: INSERT INTO event_log in a transaction.
       b) DB unreachable: enqueue to outbox NDJSON fallback with
          target_table='event_log'.
  3) Optionally enqueue to outbox for derived tables
     (e.g. segments, turns) if the event corresponds to a row.

No blocking LLM/STT calls happen here. This module only does JSON +
asyncpg writes.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import UUID

import asyncpg

from persistence import outbox
from persistence.db import get_pool

logger = logging.getLogger(__name__)


@dataclass
class _SeqCounter:
    """Per-session monotonic counter, seeded from DB on first use."""

    counters: dict[UUID, int] = field(default_factory=dict)
    locks: dict[UUID, asyncio.Lock] = field(default_factory=dict)

    def lock(self, session_id: UUID) -> asyncio.Lock:
        lk = self.locks.get(session_id)
        if lk is None:
            lk = asyncio.Lock()
            self.locks[session_id] = lk
        return lk

    async def next(self, session_id: UUID) -> int:
        async with self.lock(session_id):
            if session_id not in self.counters:
                # Seed from DB
                try:
                    pool = await get_pool()
                    async with pool.acquire() as conn:
                        row = await conn.fetchrow(
                            "SELECT COALESCE(MAX(seq), 0) AS n FROM event_log WHERE session_id=$1",
                            session_id,
                        )
                        self.counters[session_id] = int(row["n"])
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "[event_writer] could not seed seq from DB, starting at 0: %s",
                        exc,
                    )
                    self.counters[session_id] = 0
            self.counters[session_id] += 1
            return self.counters[session_id]

    def reset(self, session_id: UUID, value: int = 0) -> None:
        self.counters[session_id] = value


_SEQ = _SeqCounter()


async def write_event(
    *,
    session_id: Optional[UUID],
    event_type: str,
    payload: dict[str, Any],
    trace_id: Optional[str] = None,
    latency_ms: Optional[int] = None,
) -> int:
    """Write an event to event_log, durably.

    Returns the assigned seq (0 if session_id is None — session-agnostic events
    still land in event_log but don't participate in per-session ordering).
    """
    seq = 0
    if session_id is not None:
        seq = await _SEQ.next(session_id)

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO event_log
                    (session_id, seq, event_type, payload, trace_id, latency_ms)
                VALUES ($1, $2, $3, $4::jsonb, $5, $6)
                """,
                session_id,
                seq if session_id is not None else None,
                event_type,
                json.dumps(payload),
                trace_id,
                latency_ms,
            )
        return seq
    except (asyncpg.CannotConnectNowError, asyncpg.PostgresConnectionError, OSError) as exc:
        logger.warning("[event_writer] DB unreachable, falling back to outbox NDJSON: %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[event_writer] DB write failed, falling back to outbox NDJSON: %s", exc)

    # Fallback: enqueue to outbox so the event is not lost
    await outbox.enqueue(
        "event_log",
        {
            "session_id": str(session_id) if session_id else None,
            "seq": seq,
            "event_type": event_type,
            "payload": payload,
            "trace_id": trace_id,
            "latency_ms": latency_ms,
        },
        trace_id=trace_id,
    )
    return seq


def reset_session_seq(session_id: UUID, value: int = 0) -> None:
    """Reset the in-process sequence counter for a session.

    Useful in tests that create and destroy sessions, or when a session is
    explicitly restarted.
    """
    _SEQ.reset(session_id, value)
