"""
F2-T16 — test_outbox_resilience

Validates that when the DB write fails transiently, the outbox's NDJSON
fallback captures the event and `drain_ndjson_into_db()` replays it into
the DB once the DB is reachable again.

Approach: we do NOT actually take down Postgres. We point
`NDJSON_PATH` at a temp file, manually simulate a DB failure by appending
to that file via `_append_ndjson`, then call `drain_ndjson_into_db()` to
assert the row shows up in `outbox`.

Requires a reachable Postgres. Skips otherwise.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "python-core"))

from persistence import outbox, session_store  # noqa: E402
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
        pytest.skip("DATABASE_URL unreachable")


async def _setup_session() -> UUID:
    await init_pool()
    return await session_store.create_session(status="active")


async def _teardown_session(session_id: UUID) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM outbox WHERE trace_id LIKE $1",
            f"resilience:{session_id}%",
        )
        await conn.execute("DELETE FROM sessions WHERE id = $1", session_id)
    await close_pool()


async def test_ndjson_fallback_drains_into_db(tmp_path):
    await _ensure_db_or_skip()
    session_id = await _setup_session()
    trace_id = f"resilience:{session_id}"

    # Point the NDJSON fallback at a temp file for this test.
    original_path = outbox.NDJSON_PATH
    temp_file = tmp_path / "outbox.ndjson"
    outbox.NDJSON_PATH = temp_file

    try:
        # Simulate a DB-down enqueue by directly appending to NDJSON.
        for i in range(3):
            outbox._append_ndjson(
                {
                    "target_table": "turns",
                    "payload": {
                        "id": str(uuid4()),
                        "session_id": str(session_id),
                        "index_in_session": i,
                        "speaker": "interviewer",
                        "opened_at": None,
                        "closed_at": None,
                        "close_reason": "utterance_end",
                        "close_confidence": 0.9,
                        "final_text": f"turn {i}",
                        "language": "en",
                    },
                    "trace_id": trace_id,
                    "max_attempts": 5,
                    "enqueued_at": 0.0,
                }
            )
        assert temp_file.exists()
        # The file has exactly 3 lines
        assert temp_file.read_text().count("\n") == 3

        # Now drain the NDJSON into the DB.
        drained = await outbox.drain_ndjson_into_db()
        assert drained == 3
        assert not temp_file.exists(), "NDJSON should be deleted after drain"

        # Verify the outbox table now has 3 pending rows for this trace.
        pool = await get_pool()
        async with pool.acquire() as conn:
            n = await conn.fetchval(
                "SELECT COUNT(*) FROM outbox WHERE trace_id=$1",
                trace_id,
            )
        assert n == 3
    finally:
        outbox.NDJSON_PATH = original_path
        await _teardown_session(session_id)


async def test_outbox_exports_stats_shape():
    await _ensure_db_or_skip()
    await init_pool()
    try:
        s = await outbox.stats()
        assert set(s.keys()) == {"pending", "processing", "completed", "failed", "dead"}
        for v in s.values():
            assert isinstance(v, int)
    finally:
        await close_pool()


async def test_ndjson_append_is_valid_json_per_line(tmp_path):
    """Regression: every line must be parseable JSON. Ensures future consumers
    (the worker, a replay tool) can rely on it."""
    temp = tmp_path / "lines.ndjson"
    original_path = outbox.NDJSON_PATH
    outbox.NDJSON_PATH = temp
    try:
        outbox._append_ndjson({"target_table": "event_log", "payload": {"a": 1}})
        outbox._append_ndjson({"target_table": "event_log", "payload": {"b": 2}})
        rows = [json.loads(ln) for ln in temp.read_text().splitlines() if ln]
        assert len(rows) == 2
        assert rows[0]["payload"] == {"a": 1}
        assert rows[1]["payload"] == {"b": 2}
    finally:
        outbox.NDJSON_PATH = original_path
