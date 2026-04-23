"""
Interview Coach — persistence.outbox

Durable write buffer per ADR-003. Replaces `storage/persist_queue.py`
(in-memory list) with a PostgreSQL-backed outbox and an NDJSON file
fallback for when the DB is temporarily unreachable.

Shape
=====

1. Callers invoke `await enqueue(target_table, payload, trace_id=None)`.
2. On DB reachable: INSERT into `outbox` with status='pending'.
3. On DB unreachable: append one JSON line to `.runtime/outbox.ndjson`.
4. A background worker (`OutboxWorker.start()`) polls pending rows:
   - status=pending, next_retry_at <= now() -> processing -> target INSERT
     via a pluggable `target_sinks` mapping.
   - On success: status=completed + processed_at=now().
   - On failure with attempts<max: status=pending, next_retry_at=backoff.
   - On failure with attempts>=max: status=dead.
5. Whenever the worker detects DB is reachable again, it drains the NDJSON
   file into `outbox` first (preserves order by id).

Target sinks
============

A `target_sink(target_table) -> async callable(payload)` factory is supplied
at worker construction. For F2 we only implement a generic
`session_store_sink` that routes the payload to the right INSERT based on
`target_table`. Ref: persistence/session_store.py (F2-T8).

Metrics
=======
- `outbox_pending_size` (gauge)
- `outbox_dead_size` (gauge)
- `outbox_drained_total{outcome}` (counter)
Exposed in F5.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import asyncpg

from persistence.db import get_pool

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
NDJSON_PATH = Path(
    os.environ.get("INTERVIEW_COACH_OUTBOX_NDJSON", ".runtime/outbox.ndjson")
).expanduser()

DEFAULT_MAX_ATTEMPTS = int(os.environ.get("INTERVIEW_COACH_OUTBOX_MAX_ATTEMPTS", "5"))
POLL_INTERVAL_SEC = float(os.environ.get("INTERVIEW_COACH_OUTBOX_POLL_SEC", "0.25"))
BATCH_SIZE = int(os.environ.get("INTERVIEW_COACH_OUTBOX_BATCH", "50"))


# -----------------------------------------------------------------------------
# Types
# -----------------------------------------------------------------------------
TargetSink = Callable[[dict[str, Any]], Awaitable[None]]
SinkFactory = Callable[[str], Optional[TargetSink]]


@dataclass
class OutboxRow:
    id: int
    target_table: str
    payload: dict[str, Any]
    attempts: int
    trace_id: Optional[str] = None


# =============================================================================
# Enqueue API
# =============================================================================
async def enqueue(
    target_table: str,
    payload: dict[str, Any],
    *,
    trace_id: Optional[str] = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> None:
    """Durably enqueue a payload destined for `target_table`.

    Tries the DB first. If the DB is unreachable, falls back to an append-only
    NDJSON file. The caller is never blocked by DB latency beyond asyncpg's
    configured command_timeout.
    """
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO outbox
                    (target_table, payload, status, attempts, max_attempts, trace_id, next_retry_at)
                VALUES ($1, $2::jsonb, 'pending', 0, $3, $4, now())
                """,
                target_table,
                json.dumps(payload),
                max_attempts,
                trace_id,
            )
        return
    except (asyncpg.CannotConnectNowError, asyncpg.PostgresConnectionError, OSError) as exc:
        logger.warning("[outbox] DB enqueue failed, falling back to NDJSON: %s", exc)
    except Exception as exc:  # noqa: BLE001
        # Any unexpected DB error -> also fall back to NDJSON rather than drop.
        logger.warning("[outbox] DB enqueue unexpected error, falling back to NDJSON: %s", exc)

    _append_ndjson(
        {
            "target_table": target_table,
            "payload": payload,
            "trace_id": trace_id,
            "max_attempts": max_attempts,
            "enqueued_at": time.time(),
        }
    )


# =============================================================================
# NDJSON fallback
# =============================================================================
def _append_ndjson(row: dict[str, Any]) -> None:
    NDJSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with NDJSON_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, separators=(",", ":")) + "\n")


async def drain_ndjson_into_db() -> int:
    """Move queued rows from NDJSON file into the outbox DB table.

    Returns the number of rows drained. Called at worker start and whenever
    the worker detects the DB is back online.
    """
    if not NDJSON_PATH.exists():
        return 0

    rows: list[dict[str, Any]] = []
    with NDJSON_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                logger.error("[outbox] bad NDJSON line, skipping: %s", exc)

    if not rows:
        NDJSON_PATH.unlink(missing_ok=True)
        return 0

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                for row in rows:
                    await conn.execute(
                        """
                        INSERT INTO outbox
                            (target_table, payload, status, attempts, max_attempts, trace_id, next_retry_at)
                        VALUES ($1, $2::jsonb, 'pending', 0, $3, $4, now())
                        """,
                        row["target_table"],
                        json.dumps(row["payload"]),
                        row.get("max_attempts", DEFAULT_MAX_ATTEMPTS),
                        row.get("trace_id"),
                    )
        # Only delete the NDJSON once all rows are durably in DB.
        NDJSON_PATH.unlink(missing_ok=True)
        logger.info("[outbox] drained %d NDJSON rows into DB", len(rows))
        return len(rows)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[outbox] could not drain NDJSON (DB still unreachable?): %s", exc)
        return 0


# =============================================================================
# Worker
# =============================================================================
class OutboxWorker:
    """Background drain of the outbox -> target sinks."""

    def __init__(self, sink_factory: SinkFactory, *, poll_sec: float = POLL_INTERVAL_SEC):
        self._sink_factory = sink_factory
        self._poll_sec = poll_sec
        self._task: Optional[asyncio.Task[None]] = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        await drain_ndjson_into_db()
        self._task = asyncio.create_task(self._run())
        logger.info("[outbox] worker started (poll=%.2fs batch=%d)", self._poll_sec, BATCH_SIZE)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        while self._running:
            try:
                n = await self._drain_batch()
                if n == 0:
                    await asyncio.sleep(self._poll_sec)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.error("[outbox] worker loop error: %s", exc)
                await asyncio.sleep(self._poll_sec * 4)

    async def _drain_batch(self) -> int:
        """Process up to BATCH_SIZE pending rows. Returns count processed."""
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                rows = await conn.fetch(
                    """
                    SELECT id, target_table, payload, attempts, trace_id
                    FROM outbox
                    WHERE status IN ('pending','failed')
                      AND next_retry_at <= now()
                    ORDER BY id
                    LIMIT $1
                    FOR UPDATE SKIP LOCKED
                    """,
                    BATCH_SIZE,
                )
                if not rows:
                    return 0
                ids = [r["id"] for r in rows]
                await conn.execute(
                    "UPDATE outbox SET status='processing' WHERE id = ANY($1::bigint[])",
                    ids,
                )

        processed = 0
        for row in rows:
            outbox_row = OutboxRow(
                id=row["id"],
                target_table=row["target_table"],
                payload=_coerce_payload(row["payload"]),
                attempts=row["attempts"],
                trace_id=row["trace_id"],
            )
            await self._apply_one(outbox_row)
            processed += 1

        # Periodically also drain any NDJSON that accumulated.
        await drain_ndjson_into_db()
        return processed

    async def _apply_one(self, row: OutboxRow) -> None:
        sink = self._sink_factory(row.target_table)
        if sink is None:
            await self._mark_dead(row.id, f"no sink registered for target_table={row.target_table}")
            return
        try:
            await sink(row.payload)
            await self._mark_completed(row.id)
        except Exception as exc:  # noqa: BLE001
            await self._mark_failure(row.id, row.attempts, str(exc))

    async def _mark_completed(self, row_id: int) -> None:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE outbox
                SET status='completed', processed_at=now(), last_error=NULL
                WHERE id=$1
                """,
                row_id,
            )

    async def _mark_failure(self, row_id: int, attempts: int, error: str) -> None:
        new_attempts = attempts + 1
        backoff_sec = min(60, 2 ** min(new_attempts, 6))
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE outbox
                SET status = CASE
                    WHEN attempts + 1 >= max_attempts THEN 'dead'
                    ELSE 'pending'
                END,
                    attempts = $2,
                    last_error = $3,
                    next_retry_at = now() + make_interval(secs => $4)
                WHERE id = $1
                """,
                row_id,
                new_attempts,
                error[:2000],
                float(backoff_sec),
            )
        logger.warning(
            "[outbox] row %d attempt %d failed (backoff=%ss): %s",
            row_id,
            new_attempts,
            backoff_sec,
            error,
        )

    async def _mark_dead(self, row_id: int, error: str) -> None:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE outbox
                SET status='dead', last_error=$2
                WHERE id=$1
                """,
                row_id,
                error[:2000],
            )
        logger.error("[outbox] row %d dead: %s", row_id, error)


# =============================================================================
# Helpers
# =============================================================================
def _coerce_payload(payload: Any) -> dict[str, Any]:
    """asyncpg returns JSONB as a str. Normalize to a dict."""
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        return json.loads(payload)
    return dict(payload) if payload is not None else {}


async def stats() -> dict[str, int]:
    """Quick counts for health endpoints / Prometheus."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT status, COUNT(*)::bigint AS n
            FROM outbox
            GROUP BY status
            """
        )
    out = {"pending": 0, "processing": 0, "completed": 0, "failed": 0, "dead": 0}
    for r in rows:
        out[r["status"]] = int(r["n"])
    return out
