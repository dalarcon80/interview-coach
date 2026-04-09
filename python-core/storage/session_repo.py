"""
Interview Coach - Session Repository
Database operations for sessions and exchanges
"""
from datetime import datetime
from typing import Optional
import json

from storage.database import get_db, execute_query, execute_one, execute_scalar


class SessionRepository:
    """Repository for session and exchange data"""
    
    async def create_session(
        self,
        config_id: Optional[str] = None,
        status: str = "active",
    ) -> str:
        """Create a new session and return its ID"""
        pool = await get_db()
        async with pool.acquire() as conn:
            # Handle nullable config_id - convert empty string to None
            effective_config_id = config_id if config_id else None
            row = await conn.fetchrow(
                """
                INSERT INTO sessions (config_id, status, started_at)
                VALUES ($1, $2, NOW())
                RETURNING id
                """,
                effective_config_id,
                status,
            )
            return str(row["id"])
    
    async def get_session(self, session_id: str) -> Optional[dict]:
        """Get a session by ID"""
        row = await execute_one(
            """
            SELECT id, config_id, status, started_at, ended_at, summary
            FROM sessions
            WHERE id = $1
            """,
            session_id,
        )
        return dict(row) if row else None
    
    async def end_session(
        self,
        session_id: str,
        summary: Optional[dict] = None,
    ) -> bool:
        """End a session"""
        result = await execute_scalar(
            """
            UPDATE sessions
            SET status = 'ended', ended_at = NOW(), summary = $2
            WHERE id = $1
            RETURNING id
            """,
            session_id,
            json.dumps(summary) if summary else None,
        )
        return result is not None
    
    async def create_exchange(
        self,
        session_id: str,
        index: int,
        interviewer_utterance: str,
        language_detected: str,
        question_analysis: dict,
        suggested_response: dict,
        quality_result: dict,
        latency_ms: int = 0,
    ) -> str:
        """Create an exchange and return its ID"""
        pool = await get_db()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO exchanges (
                    session_id, index_in_session, interviewer_utterance,
                    language_detected, question_analysis, suggested_response,
                    quality_result, latency_ms, created_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
                RETURNING id
                """,
                session_id,
                index,
                interviewer_utterance,
                language_detected,
                json.dumps(question_analysis),
                json.dumps(suggested_response),
                json.dumps(quality_result),
                latency_ms,
            )
            return str(row["id"])
    
    async def get_exchanges(self, session_id: str) -> list[dict]:
        """Get all exchanges for a session"""
        rows = await execute_query(
            """
            SELECT id, index_in_session, interviewer_utterance, language_detected,
                   question_analysis, suggested_response, quality_result,
                   user_actual_response, latency_ms, created_at
            FROM exchanges
            WHERE session_id = $1
            ORDER BY index_in_session
            """,
            session_id,
        )
        return [dict(row) for row in rows]
    
    async def get_recent_exchanges(self, session_id: str, limit: int = 4) -> list[dict]:
        """Get recent exchanges for a session (last N exchanges)"""
        rows = await execute_query(
            """
            SELECT id, index_in_session, interviewer_utterance, language_detected,
                   question_analysis, suggested_response, quality_result,
                   user_actual_response, latency_ms, created_at
            FROM exchanges
            WHERE session_id = $1
            ORDER BY index_in_session DESC
            LIMIT $2
            """,
            session_id,
            limit,
        )
        # Return in chronological order (oldest first)
        return list(reversed([dict(row) for row in rows]))
    
    async def update_exchange_response(
        self,
        exchange_id: str,
        user_actual_response: str,
    ) -> bool:
        """Update an exchange with the user's actual response"""
        result = await execute_scalar(
            """
            UPDATE exchanges
            SET user_actual_response = $2
            WHERE id = $1
            RETURNING id
            """,
            exchange_id,
            user_actual_response,
        )
        return result is not None
    
    async def log_event(
        self,
        session_id: str,
        event_type: str,
        payload: dict,
        trace_id: Optional[str] = None,
        latency_ms: Optional[int] = None,
    ) -> int:
        """Log an event for replay/audit"""
        result = await execute_scalar(
            """
            INSERT INTO event_log (session_id, event_type, payload, trace_id, latency_ms)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            session_id,
            event_type,
            json.dumps(payload),
            trace_id,
            latency_ms,
        )
        return result or 0
    
    async def record_latency_metric(
        self,
        session_id: str,
        step_name: str,
        duration_ms: int,
        exchange_index: Optional[int] = None,
    ) -> int:
        """Record a latency metric"""
        result = await execute_scalar(
            """
            INSERT INTO latency_metrics (session_id, exchange_index, step_name, duration_ms)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            session_id,
            exchange_index,
            step_name,
            duration_ms,
        )
        return result or 0
    
    async def get_latency_metrics(
        self,
        session_id: str,
    ) -> list[dict]:
        """Get latency metrics for a session"""
        rows = await execute_query(
            """
            SELECT id, exchange_index, step_name, duration_ms, created_at
            FROM latency_metrics
            WHERE session_id = $1
            ORDER BY created_at
            """,
            session_id,
        )
        return [dict(row) for row in rows]


# Global repository instance
_repo: Optional[SessionRepository] = None


def get_session_repository() -> SessionRepository:
    """Get or create the global session repository"""
    global _repo
    if _repo is None:
        _repo = SessionRepository()
    return _repo
