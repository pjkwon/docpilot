from __future__ import annotations

from sqlalchemy import text

from docpilot.db import client
from docpilot.db.schema import Chunk, Document
from docpilot.exceptions import SearchError
from docpilot.search._filter import apply_orm_filter
from docpilot.search.models import SearchFilter, SearchResult


def search(
    query: str,
    top_k: int = 10,
    filters: SearchFilter | None = None,
) -> list[SearchResult]:
    """Keyword search using ILIKE (PostgreSQL) or LIKE (SQLite) across all indexed chunks."""
    if not query.strip():
        raise SearchError("Query must not be empty")

    with client.session() as db:
        q = (
            db.query(Chunk, Document.source, Document.metadata_)
            .join(Document, Chunk.document_id == Document.id)
            .filter(Chunk.content.ilike(f"%{query}%"))
        )
        if filters:
            q = apply_orm_filter(q, filters)
        rows = q.limit(top_k).all()

    return [
        SearchResult(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            source=source,
            content=chunk.content,
            score=_score(chunk.content, query),
            metadata=metadata,
        )
        for chunk, source, metadata in rows
    ]


def _score(content: str, query: str) -> float:
    """Simple frequency-based score: occurrences / total words."""
    lower_content = content.lower()
    lower_query = query.lower()
    count = lower_content.count(lower_query)
    words = max(len(content.split()), 1)
    return count / words
