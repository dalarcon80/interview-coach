"""
Interview Coach - Database Connection
PostgreSQL + pgvector via asyncpg
"""
import os
from typing import Optional

import asyncpg
from asyncpg import Pool


# Global connection pool
_pool: Optional[Pool] = None


def get_database_url() -> str:
    """Get database URL from environment"""
    return os.getenv(
        "DATABASE_URL",
        "postgresql://interview_coach:interview_coach_dev@localhost:5433/interview_coach"
    )


async def get_db() -> Pool:
    """Get or create the database connection pool"""
    global _pool
    
    if _pool is None:
        _pool = await asyncpg.create_pool(
            get_database_url(),
            min_size=2,
            max_size=10,
        )
    
    return _pool


async def check_db_connection() -> bool:
    """Check if database is connected"""
    try:
        pool = await get_db()
        async with pool.acquire() as conn:
            result = await conn.fetchval("SELECT 1")
            return result == 1
    except Exception as e:
        print(f"[Database] Connection error: {e}")
        return False


async def close_db():
    """Close database connection pool"""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def execute_query(query: str, *args):
    """Execute a query and return results"""
    pool = await get_db()
    async with pool.acquire() as conn:
        return await conn.fetch(query, *args)


async def execute_one(query: str, *args):
    """Execute a query and return one result"""
    pool = await get_db()
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, *args)


async def execute_scalar(query: str, *args):
    """Execute a query and return a scalar value"""
    pool = await get_db()
    async with pool.acquire() as conn:
        return await conn.fetchval(query, *args)
