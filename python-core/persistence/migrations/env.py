"""
Alembic environment — Interview Coach

Resolves DATABASE_URL from env. Supports both offline (SQL generation) and
online (actual DB) modes. Uses synchronous psycopg driver for migrations
(asyncpg is used by the runtime, not by Alembic).

Ref: docs/audit/DATA_MODEL_REDESIGN.md §3.2, §3.3
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Ensure python-core/ is on path so we can import sibling modules if needed.
_PERSISTENCE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PERSISTENCE_DIR.parent))

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _get_database_url() -> str:
    """Resolve DATABASE_URL from env with sensible dev default.

    Alembic itself uses a synchronous driver (psycopg / psycopg2), so if the
    env var is the asyncpg-style URL used at runtime, we coerce it.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        url = "postgresql://interview_coach:interview_coach_dev@localhost:5433/interview_coach"
    # Coerce asyncpg style to sync (psycopg3) for Alembic.
    # psycopg3 is the modern replacement for psycopg2.
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


# Make the URL visible in the raw context (for offline mode).
config.set_main_option("sqlalchemy.url", _get_database_url())


# No ORM models — raw SQL migrations.
target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emits SQL without a DB connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (open a real DB connection)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
