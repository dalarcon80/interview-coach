"""
Interview Coach - Evidence Retriever
Retrieves evidence from profile using pgvector semantic search

## IMPLEMENTATION STATUS (C6 Audit)

**CURRENT STATE: REAL MODE ONLY - DEMO FALLBACK DISABLED**

CRITICAL: Demo mode has been DISABLED to prevent fake evidence generation.
The system now ONLY retrieves real evidence from the database.

Mode behavior:
- **REAL MODE** (default): Uses pgvector for semantic search
- **DEMO MODE**: DISABLED - returns empty evidence instead of mock data
- **AUTO MODE**: Tries REAL, returns empty if DB unavailable (no fake data)

Requirements for operation:
1. PostgreSQL + pgvector must be running (Docker Compose)
2. CV must be uploaded and embeddings stored in `document_chunks` and `achievements` tables
3. Set `DATABASE_URL` environment variable correctly

If database is unavailable or no embeddings exist, the system returns
empty evidence (which triggers a safe fallback response) instead of
 generating fake evidence.
"""
import os
from typing import Optional
from dataclasses import dataclass
from enum import Enum

from contracts.models import EvidenceChunk
from pipeline.steps.retrieval_planner import RetrievalPlan


class RetrieverMode(str, Enum):
    """Evidence retriever operation mode"""
    DEMO = "demo"  # Returns mock data
    REAL = "real"  # Uses pgvector
    AUTO = "auto"  # Tries real, falls back to demo


@dataclass
class RetrieverStatus:
    """Status of the evidence retriever"""
    mode: RetrieverMode
    database_connected: bool
    message: str


class EvidenceRetriever:
    """
    Retrieves evidence using pgvector semantic search.
    
    In REAL mode, queries the database for semantically similar content.
    In DEMO mode, returns mock evidence for testing.
    """
    
    def __init__(
        self,
        mode: RetrieverMode = RetrieverMode.REAL,
        force_demo: bool = False,
    ):
        """
        Initialize evidence retriever.
        
        Args:
            mode: Operation mode (AUTO, DEMO, REAL) - defaults to REAL
            force_demo: DISABLED - demo mode always returns empty evidence
        """
        self.mode = mode
        # CRITICAL: force_demo is ignored - demo mode is disabled
        self.force_demo = False
        self._db_checked = False
        self._db_available = False

    @staticmethod
    def from_environment(force_demo: bool = False) -> "EvidenceRetriever":
        """
        Construct retriever using EVIDENCE_RETRIEVER_MODE env var.
        Supported values: real | auto (default: real).
        
        CRITICAL: Demo mode is disabled. If 'demo' is specified,
        it will be treated as 'real' mode.
        """
        mode_raw = os.getenv("EVIDENCE_RETRIEVER_MODE", "real").strip().lower()
        if mode_raw == "demo":
            print("[EvidenceRetriever] WARNING: Demo mode requested but disabled. Using REAL mode.")
            mode = RetrieverMode.REAL
        elif mode_raw == "auto":
            mode = RetrieverMode.AUTO
        else:
            # Default to REAL mode
            mode = RetrieverMode.REAL

        # CRITICAL: force_demo is disabled - never use fake evidence
        if force_demo:
            print("[EvidenceRetriever] WARNING: force_demo=True but demo mode is DISABLED")
            force_demo = False

        return EvidenceRetriever(mode=mode, force_demo=force_demo)
    
    async def _check_database(self) -> bool:
        """Check if database is available for real retrieval"""
        if self._db_checked:
            return self._db_available
        
        try:
            from storage.database import check_db_connection, execute_scalar

            connected = await check_db_connection()
            if not connected:
                self._db_available = False
            else:
                vector_extension = await execute_scalar(
                    "SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector')"
                )
                achievements_vector = await execute_scalar(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_schema = 'public'
                          AND table_name = 'achievements'
                          AND column_name = 'embedding'
                          AND udt_name = 'vector'
                    )
                    """
                )
                document_chunks_vector = await execute_scalar(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_schema = 'public'
                          AND table_name = 'document_chunks'
                          AND column_name = 'embedding'
                          AND udt_name = 'vector'
                    )
                    """
                )

                self._db_available = bool(
                    vector_extension and achievements_vector and document_chunks_vector
                )

                if not self._db_available:
                    print("[EvidenceRetriever] Database connected but pgvector schema is incomplete")
        except Exception as e:
            print(f"[EvidenceRetriever] Database check failed: {e}")
            self._db_available = False
        
        self._db_checked = True
        return self._db_available
    
    def get_status(self) -> RetrieverStatus:
        """Get current retriever status"""
        # CRITICAL: Demo mode is disabled - always report REAL mode intent
        if self.mode == RetrieverMode.DEMO:
            print("[EvidenceRetriever] WARNING: get_status called in DEMO mode, but demo is disabled")
        
        if self.mode == RetrieverMode.REAL or self.mode == RetrieverMode.DEMO:
            if self._db_available:
                return RetrieverStatus(
                    mode=RetrieverMode.REAL,
                    database_connected=True,
                    message="Real mode - using pgvector semantic search",
                )
            else:
                return RetrieverStatus(
                    mode=RetrieverMode.REAL,
                    database_connected=False,
                    message="Real mode - database unavailable (will return empty evidence, no fake data)",
                )
        
        # AUTO mode - also uses REAL mode (demo fallback disabled)
        if self._db_available:
            return RetrieverStatus(
                mode=RetrieverMode.REAL,
                database_connected=True,
                message="Auto mode - using pgvector (database available)",
            )
        else:
            return RetrieverStatus(
                mode=RetrieverMode.REAL,
                database_connected=False,
                message="Auto mode - database unavailable (demo fallback disabled, will return empty)",
            )
    
    async def retrieve(self, plan: RetrievalPlan) -> list[EvidenceChunk]:
        """
        Retrieve evidence according to plan.
        
        In REAL mode: Queries pgvector for semantically similar content.
        In DEMO mode: DISABLED - returns empty evidence (no fake data).
        """
        # Check database availability
        if not self.force_demo:
            await self._check_database()
        
        # Determine which implementation to use
        status = self.get_status()
        
        # CRITICAL: Demo mode is disabled - always attempt real retrieval
        if status.mode == RetrieverMode.DEMO:
            print("[EvidenceRetriever] WARNING: Demo mode was requested but is DISABLED")
            print("[EvidenceRetriever] Attempting real retrieval instead...")
            return await self._retrieve_real(plan)
        else:
            return await self._retrieve_real(plan)
    
    async def _retrieve_demo(self, plan: RetrievalPlan) -> list[EvidenceChunk]:
        """
        DEPRECATED: Demo retrieval is disabled to prevent fake evidence generation.
        
        This method now returns empty evidence instead of mock data.
        Never generate fake CV evidence - always use real database with real embeddings.
        """
        print("[EvidenceRetriever] WARNING: Demo retrieval requested but DISABLED")
        print("[EvidenceRetriever] Real database with CV embeddings is required")
        
        # Return empty evidence - no fake data
        return []
    
    async def _retrieve_real(self, plan: RetrievalPlan) -> list[EvidenceChunk]:
        """
        Real retrieval using pgvector.

        This requires:
        1. PostgreSQL with pgvector extension enabled
        2. `document_chunks` and `achievements` tables with embeddings
        3. Database connection configured

        Returns results with mode='real' in metadata when successful.
        Falls back to demo mode with explicit mode='demo' when unavailable.
        """
        from storage.embedding_utils import build_query_embedding, vector_literal

        results: list[EvidenceChunk] = []

        print(f"[EvidenceRetriever] REAL mode retrieval starting")
        print(f"[EvidenceRetriever] Plan: company_filter={plan.company_filter}, top_k={plan.top_k}")
        print(f"[EvidenceRetriever] Queries: achievements={plan.achievement_queries[:3]}, cv={plan.cv_queries[:3]}")

        try:
            achievement_results = await self._query_achievements(plan, build_query_embedding, vector_literal)
            print(f"[EvidenceRetriever] Achievements found: {len(achievement_results)}")
            results.extend(achievement_results)

            chunk_results = await self._query_document_chunks(plan, build_query_embedding, vector_literal)
            print(f"[EvidenceRetriever] Document chunks found: {len(chunk_results)}")
            results.extend(chunk_results)

            context_results = await self._query_context_document_chunks(plan, build_query_embedding, vector_literal)
            print(f"[EvidenceRetriever] Context chunks found: {len(context_results)}")
            results.extend(context_results)

            if not results:
                print("[EvidenceRetriever] REAL mode: No embeddings found, returning empty evidence")
                return []

            # Mark real results with mode
            for chunk in results:
                chunk.metadata["mode"] = "real"
                chunk.metadata["retriever_status"] = "pgvector_query"

            return results

        except Exception as e:
            print(f"[EvidenceRetriever] REAL mode failed: {e}, returning empty evidence")
            # Graceful fallback: never crash real pipeline when retrieval infra is unavailable
            return []

    async def _query_achievements(
        self,
        plan: RetrievalPlan,
        embedder,
        vector_formatter,
    ) -> list[EvidenceChunk]:
        """Query achievement embeddings using pgvector."""
        from storage.database import execute_query

        results: list[EvidenceChunk] = []

        # Build filters - embedding goes FIRST in params list, then filters
        filters = []
        
        # Profile ID filter - if specified, only retrieve from this profile
        if plan.profile_id:
            filters.append("profile_id = $2::uuid")
            print(f"[EvidenceRetriever] Achievement query with profile filter: {plan.profile_id}")
        
        # Company filter if specified
        if plan.company_filter:
            # Filter by company in context column (stores company) or tags array
            filters.append("(context ILIKE $3 OR $3::text = ANY(tags))")
            print(f"[EvidenceRetriever] Achievement query with company filter: {plan.company_filter}")

        # Build WHERE clause
        where_clause = "WHERE embedding IS NOT NULL"
        if filters:
            where_clause += " AND " + " AND ".join(filters)

        for query in plan.achievement_queries[:3]:
            embedding = await embedder(query)
            vector_value = vector_formatter(embedding)
            
            # Build params: [embedding, profile_id?, company_filter?, top_k]
            params = [vector_value]
            if plan.profile_id:
                params.append(plan.profile_id)
            if plan.company_filter:
                params.append(f"%{plan.company_filter}%")
            params.append(plan.top_k)
            
            sql = (
                "SELECT id, title, context, action, result, tags, "
                "1 - (embedding <=> $1::vector) AS similarity "
                "FROM achievements "
                f"{where_clause} "
                "ORDER BY similarity DESC "
                f"LIMIT ${len(params)}"
            )
            rows = await execute_query(sql, *params)
            
            print(f"[EvidenceRetriever] Achievement query returned {len(rows)} rows")
            
            for row in rows:
                # Handle both asyncpg Record and dict-like objects
                def safe_get(field, default=None):
                    if isinstance(row, dict):
                        return row.get(field, default)
                    try:
                        return row[field] if field in row else default
                    except Exception:
                        return default
                
                title = safe_get("title", "")
                context = safe_get("context", "")
                action = safe_get("action", "")
                result = safe_get("result", "")
                similarity = safe_get("similarity", 0.0)
                row_id = safe_get("id")
                tags = safe_get("tags") or []
                
                text = self._compose_achievement_text(title, context, action, result)
                # context column stores the company name
                company = context or ""
                # Fall back to company_filter if context is empty
                if not company and plan.company_filter:
                    company = plan.company_filter
                
                results.append(
                    EvidenceChunk(
                        text=text,
                        source="achievement",
                        relevance_score=float(similarity) if similarity else 0.0,
                        metadata={
                            "achievement_id": str(row_id) if row_id else "",
                            "query": query,
                            "similarity": float(similarity) if similarity else 0.0,
                            "company": company,
                            "tags": tags,
                        },
                    )
                )
        
        print(f"[EvidenceRetriever] Total achievements found: {len(results)}")

        return results

    async def _query_document_chunks(
        self,
        plan: RetrievalPlan,
        embedder,
        vector_formatter,
    ) -> list[EvidenceChunk]:
        """Query document chunk embeddings using pgvector."""
        from storage.database import execute_query

        results: list[EvidenceChunk] = []
        
        # Build filters - embedding goes FIRST in params list, then filters
        filters = []
        
        # Profile ID filter - if specified, only retrieve from this profile
        if plan.profile_id:
            filters.append("profile_id = $2::uuid")
            print(f"[EvidenceRetriever] Document chunks query with profile filter: {plan.profile_id}")
        
        # Company filter if specified
        if plan.company_filter:
            # Filter by company in metadata JSONB
            filters.append("metadata->>'company' ILIKE $3")

        # Build WHERE clause
        where_clause = "WHERE embedding IS NOT NULL"
        if filters:
            where_clause += " AND " + " AND ".join(filters)
        
        queries = plan.cv_queries + plan.job_desc_queries
        for query in queries[:3]:
            embedding = await embedder(query)
            vector_value = vector_formatter(embedding)
            
            # Build params: [embedding, profile_id?, company_filter?, top_k]
            params = [vector_value]
            if plan.profile_id:
                params.append(plan.profile_id)
            if plan.company_filter:
                params.append(f"%{plan.company_filter}%")
            params.append(plan.top_k)
            
            sql = (
                "SELECT id, source, section, content, metadata, "
                "1 - (embedding <=> $1::vector) AS similarity "
                "FROM document_chunks "
                f"{where_clause} "
                "ORDER BY similarity DESC "
                f"LIMIT ${len(params)}"
            )
            rows = await execute_query(sql, *params)
            
            for row in rows:
                # Handle both asyncpg Record and dict-like objects
                def safe_get(field, default=None):
                    if isinstance(row, dict):
                        return row.get(field, default)
                    try:
                        return row[field] if field in row else default
                    except Exception:
                        return default
                
                content = safe_get("content", "")
                source = safe_get("source", "cv")
                similarity = safe_get("similarity", 0.0)
                row_id = safe_get("id")
                section = safe_get("section")
                metadata = safe_get("metadata") or {}
                
                # Handle metadata as dict
                if isinstance(metadata, str):
                    metadata = {}
                elif hasattr(metadata, 'get'):
                    pass  # It's dict-like
                else:
                    metadata = {}
                
                # Include company in metadata for prompt filtering
                if not metadata.get("company") and plan.company_filter:
                    metadata["company"] = plan.company_filter
                    
                results.append(
                    EvidenceChunk(
                        text=content,
                        source=source,
                        relevance_score=float(similarity) if similarity else 0.0,
                        metadata={
                            "document_chunk_id": str(row_id) if row_id else "",
                            "section": section,
                            "query": query,
                            "similarity": float(similarity) if similarity else 0.0,
                            "company": metadata.get("company", ""),
                        },
                    )
                )

        return results

    async def _query_context_document_chunks(
        self,
        plan: RetrievalPlan,
        embedder,
        vector_formatter,
    ) -> list[EvidenceChunk]:
        """Query company/interviewer context embeddings using pgvector."""
        from storage.database import execute_query

        results: list[EvidenceChunk] = []
        context_targets: list[tuple[str, str, list[str]]] = []

        if plan.company_context_id:
            context_targets.append(
                (
                    plan.company_context_id,
                    "company",
                    (plan.job_desc_queries + plan.achievement_queries[:2])[:4],
                )
            )
        if plan.interviewer_context_id:
            context_targets.append(
                (
                    plan.interviewer_context_id,
                    "interviewer",
                    (plan.achievement_queries[:2] + plan.cv_queries[:1])[:3],
                )
            )

        if not context_targets:
            return results

        for context_id, kind, queries in context_targets:
            try:
                for query in queries:
                    embedding = await embedder(query)
                    vector_value = vector_formatter(embedding)
                    rows = await execute_query(
                        """
                        SELECT id, context_id, kind, source, section, content, metadata,
                        1 - (embedding <=> $1::vector) AS similarity
                        FROM context_document_chunks
                        WHERE context_id = $2::uuid
                          AND kind = $3
                          AND embedding IS NOT NULL
                        ORDER BY similarity DESC
                        LIMIT 5
                        """,
                        vector_value,
                        context_id,
                        kind,
                    )

                    for row in rows:
                        def safe_get(field, default=None):
                            if isinstance(row, dict):
                                return row.get(field, default)
                            try:
                                return row[field] if field in row else default
                            except Exception:
                                return default

                        content = safe_get("content", "")
                        similarity = safe_get("similarity", 0.0)
                        row_id = safe_get("id")
                        section = safe_get("section")
                        metadata = safe_get("metadata") or {}
                        if isinstance(metadata, str):
                            metadata = {}
                        elif not hasattr(metadata, "get"):
                            metadata = {}

                        results.append(
                            EvidenceChunk(
                                text=content,
                                source=f"{kind}_context",
                                relevance_score=float(similarity) if similarity else 0.0,
                                metadata={
                                    "context_document_chunk_id": str(row_id) if row_id else "",
                                    "context_id": context_id,
                                    "context_kind": kind,
                                    "section": section,
                                    "query": query,
                                    "similarity": float(similarity) if similarity else 0.0,
                                    "source_urls": metadata.get("source_urls", []) if hasattr(metadata, "get") else [],
                                },
                            )
                        )
            except Exception as exc:
                print(f"[EvidenceRetriever] Context query failed for {kind}:{context_id}: {exc}")
                continue

        return results

    def _compose_achievement_text(
        self,
        title: Optional[str],
        context: Optional[str],
        action: Optional[str],
        result: Optional[str],
    ) -> str:
        """Build a readable achievement sentence."""
        parts: list[str] = []
        if title:
            parts.append(title)
        if context:
            parts.append(context)
        if action:
            parts.append(action)
        if result:
            parts.append(result)
        return " — ".join(part for part in parts if part)


class MockEvidenceRetriever(EvidenceRetriever):
    """
    DEPRECATED: Mock retriever for testing - now returns empty evidence.
    
    Demo mode is disabled to prevent fake data generation.
    """
    
    def __init__(self):
        print("[MockEvidenceRetriever] WARNING: MockEvidenceRetriever is deprecated and returns empty evidence")
        super().__init__(mode=RetrieverMode.REAL, force_demo=False)
    
    async def retrieve(self, plan: RetrievalPlan) -> list[EvidenceChunk]:
        """Return empty evidence - demo mode disabled"""
        print("[MockEvidenceRetriever] Demo mode disabled - returning empty evidence")
        return []
