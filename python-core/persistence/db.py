"""
Interview Coach — persistence.db

Async PostgreSQL pool using asyncpg. Replaces the legacy `storage/database.py`
with the following hardening per ADR-003 and IMPLEMENTATION_PLAN F2-T5:

- Fail-loud on startup when DB is unreachable, unless
  `INTERVIEW_COACH_DB_REQUIRED=false`.
- Single source of truth for DATABASE_URL (also honored by Alembic env.py).
- Explicit pool lifecycle with graceful shutdown.
- Health check that reports extension availability (`pgvector`).
- Structured logging rather than naked prints.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from typing import Optional

import asyncpg
from asyncpg import Pool

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Global pool (module-level) — explicit lifecycle via init_pool / close_pool
# -----------------------------------------------------------------------------
_pool: Optional[Pool] = None


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
DEFAULT_DATABASE_URL = (
    "postgresql://interview_coach:interview_coach_dev@localhost:5433/interview_coach"
)


def get_database_url() -> str:
    """Resolve DATABASE_URL from env with a dev-friendly default."""
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def db_required() -> bool:
    """Whether the backend must refuse to start without a reachable DB.

    Default is True. Opt out via `INTERVIEW_COACH_DB_REQUIRED=false` for CI
    or emergency local dev without Postgres.
    """
    raw = os.getenv("INTERVIEW_COACH_DB_REQUIRED", "true").strip().lower()
    return raw not in {"0", "false", "no"}


# -----------------------------------------------------------------------------
# Dataclasses
# -----------------------------------------------------------------------------
@dataclass
class DBHealth:
    connected: bool
    pgvector_available: bool
    version: str = ""
    error: str = ""


# -----------------------------------------------------------------------------
# Pool lifecycle
# -----------------------------------------------------------------------------
async def init_pool(
    *,
    min_size: int = 2,
    max_size: int = 10,
    command_timeout: float = 10.0,
) -> Pool:
    """Create the asyncpg pool. Idempotent."""
    global _pool
    if _pool is not None:
        return _pool

    url = get_database_url()
    logger.info("[db] connecting to %s", _safe_url(url))

    _pool = await asyncpg.create_pool(
        url,
        min_size=min_size,
        max_size=max_size,
        command_timeout=command_timeout,
    )
    return _pool


async def get_pool() -> Pool:
    """Get the pool; initialize if needed."""
    if _pool is None:
        await init_pool()
    assert _pool is not None
    return _pool


async def close_pool() -> None:
    """Close the pool. Safe to call multiple times."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


# -----------------------------------------------------------------------------
# Health + startup guard
# -----------------------------------------------------------------------------
async def check_health() -> DBHealth:
    """Return a detailed health snapshot."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            version_row = await conn.fetchrow("SELECT version() AS v")
            ext_row = await conn.fetchrow(
                "SELECT 1 AS present FROM pg_extension WHERE extname = 'vector'"
            )
            return DBHealth(
                connected=True,
                pgvector_available=bool(ext_row),
                version=str(version_row["v"]) if version_row else "",
            )
    except Exception as exc:  # noqa: BLE001
        return DBHealth(connected=False, pgvector_available=False, error=str(exc))


async def assert_startup_db_ok() -> DBHealth:
    """Enforce fail-loud startup when DB is required.

    If `INTERVIEW_COACH_DB_REQUIRED=true` (default) and the DB is not
    reachable, this function **raises** and prints a clear error. The
    intended caller is the FastAPI lifespan handler: it should catch nothing
    and let the process exit.
    """
    health = await check_health()
    if health.connected:
        logger.info(
            "[db] connected; pgvector=%s version=%s",
            health.pgvector_available,
            _short_version(health.version),
        )
        return health

    if db_required():
        msg = (
            "FATAL: DATABASE_URL unreachable and INTERVIEW_COACH_DB_REQUIRED is "
            f"not disabled. url={_safe_url(get_database_url())} error={health.error}"
        )
        logger.critical(msg)
        print(msg, file=sys.stderr, flush=True)
        raise RuntimeError(msg)

    logger.warning(
        "[db] DB unreachable but INTERVIEW_COACH_DB_REQUIRED=false; "
        "continuing in degraded mode. error=%s",
        health.error,
    )
    return health


# -----------------------------------------------------------------------------
# Thin query helpers — prefer session_store/outbox for complex operations
# -----------------------------------------------------------------------------
async def fetch(query: str, *args):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(query, *args)


async def fetchrow(query: str, *args):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, *args)


async def fetchval(query: str, *args):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(query, *args)


async def execute(query: str, *args):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.execute(query, *args)


# -----------------------------------------------------------------------------
# Utilities
# -----------------------------------------------------------------------------
def _safe_url(url: str) -> str:
    """Strip credentials from a URL for logging."""
    # postgresql://user:pass@host:port/db -> postgresql://host:port/db
    import re

    return re.sub(r"://[^@/]+@", "://", url)


def _short_version(version: str) -> str:
    """Return the first line of `SELECT version()` output for logs."""
    return (version or "").splitlines()[0][:120]
