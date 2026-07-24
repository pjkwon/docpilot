from __future__ import annotations

from sqlalchemy import or_, text

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
    """Keyword search using ILIKE (PostgreSQL) or LIKE (SQLite) across all indexed chunks.

    Also matches chunks containing a Korean term registered as an alias of a
    Latin word in *query* (see docpilot.search.alias) — those hits score 0
    via ``_score`` since they don't contain the literal query text, so they
    naturally sort behind exact literal matches.
    """
    if not query.strip():
        raise SearchError("Query must not be empty")

    with client.session() as db:
        alias_terms = _alias_terms(db, query)

        conditions = [Chunk.content.ilike(f"%{query}%")]
        conditions += [Chunk.content.ilike(f"%{term}%") for term in alias_terms]

        q = (
            db.query(Chunk, Document.source, Document.metadata_)
            .join(Document, Chunk.document_id == Document.id)
            .filter(or_(*conditions))
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


def _alias_terms(db, query: str) -> list[str]:
    from docpilot.search import alias as alias_mod

    try:
        return alias_mod.expand_query(db, query)
    except Exception:
        return []


def _score(content: str, query: str) -> float:
    """Simple frequency-based score: occurrences / total words."""
    lower_content = content.lower()
    lower_query = query.lower()
    count = lower_content.count(lower_query)
    words = max(len(content.split()), 1)
    return count / words
