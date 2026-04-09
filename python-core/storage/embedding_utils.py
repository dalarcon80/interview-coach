"""
Interview Coach - Embedding Utilities
Embedding helpers for pgvector retrieval.

Priority:
1) Real provider embedding (OpenAI) using providers.yaml alias
2) Deterministic local hash embedding fallback
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Iterable


def _resolve_embedding_config() -> tuple[str, int]:
    """Resolve embedding model and dimensions from provider registry."""
    try:
        from adapters.provider_registry import get_registry

        cfg = get_registry().get_embedding_config(alias="primary")
        model = (cfg.model or "text-embedding-3-small").strip() or "text-embedding-3-small"
        dimensions = int((cfg.config or {}).get("dimensions", DEFAULT_DIMENSIONS))
        return model, dimensions
    except Exception:
        return "text-embedding-3-small", DEFAULT_DIMENSIONS


DEFAULT_DIMENSIONS = 1536


def hash_embedding(text: str, dimensions: int = DEFAULT_DIMENSIONS) -> list[float]:
    """
    Create a deterministic embedding using hashed token counts.
    This is a local fallback for pgvector retrieval verification.
    """
    tokens = re.findall(r"[A-Za-z0-9]+", text.lower())
    vector = [0.0] * dimensions

    if not tokens:
        return vector

    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest, "big") % dimensions
        vector[index] += 1.0

    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return vector

    return [value / norm for value in vector]


async def provider_embedding(text: str, dimensions: int | None = None) -> list[float]:
    """Generate real embedding via OpenAI if available."""
    model, resolved_dimensions = _resolve_embedding_config()
    dim = dimensions or resolved_dimensions

    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=(__import__("os").environ.get("OPENAI_API_KEY")))
    response = await client.embeddings.create(
        model=model,
        input=text,
        dimensions=dim,
    )
    return [float(v) for v in response.data[0].embedding]


async def build_query_embedding(text: str, dimensions: int = DEFAULT_DIMENSIONS) -> list[float]:
    """
    Build embedding for retrieval query.
    Uses provider embedding when OPENAI_API_KEY is present, otherwise hash fallback.
    """
    import os

    if os.getenv("OPENAI_API_KEY"):
        try:
            return await provider_embedding(text, dimensions=dimensions)
        except Exception as e:
            print(f"[Embeddings] Provider embedding failed, using hash fallback: {e}")

    return hash_embedding(text, dimensions=dimensions)


def vector_literal(vector: Iterable[float]) -> str:
    """Format a vector for pgvector SQL input."""
    return "[" + ",".join(f"{value:.6f}" for value in vector) + "]"
