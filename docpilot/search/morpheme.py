from __future__ import annotations

from sqlalchemy import text

from docpilot.db import client
from docpilot.db.schema import Chunk, Document
from docpilot.exceptions import SearchError
from docpilot.search._filter import apply_orm_filter, build_sql_where
from docpilot.search.models import SearchFilter, SearchResult


def search(
    query: str,
    top_k: int = 10,
    or_fallback: bool = False,
    filters: SearchFilter | None = None,
) -> list[SearchResult]:
    """
    Morpheme-based search using kiwipiepy.

    SQLite: FTS5 AND query + BM25 ranking.
      or_fallback=True: retries with OR when AND returns no results.
    PostgreSQL: full scan with Jaccard similarity fallback.
    """
    if not query.strip():
        raise SearchError("Query must not be empty")

    query_morphemes = _tokenize(query)
    if not query_morphemes:
        raise SearchError("No morphemes extracted from query", detail=query)

    if client.is_sqlite():
        results = _fts_search(query_morphemes, top_k, use_or=False, filters=filters)
        if not results and or_fallback:
            results = _fts_search(query_morphemes, top_k, use_or=True, filters=filters)
        return results
    return _jaccard_search(query_morphemes, top_k, filters=filters)


def _fts_search(
    morphemes: set[str],
    top_k: int,
    use_or: bool = False,
    filters: SearchFilter | None = None,
) -> list[SearchResult]:
    fts_query = (" OR " if use_or else " ").join(morphemes)

    extra_where, params = build_sql_where(filters, is_sqlite=True) if filters else ("", {})

    sql = text(f"""
        SELECT f.rowid AS chunk_id, c.document_id, d.source, c.content, d.metadata, rank AS score
        FROM fts_chunks f
        JOIN chunks c ON c.id = f.rowid
        JOIN documents d ON d.id = c.document_id
        WHERE fts_chunks MATCH :query{extra_where}
        ORDER BY rank
        LIMIT :top_k
    """)
    with client.session() as db:
        rows = db.execute(sql, {"query": fts_query, "top_k": top_k, **params}).fetchall()
    return [
        SearchResult(
            chunk_id=row.chunk_id,
            document_id=row.document_id,
            source=row.source,
            content=row.content,
            score=-float(row.score),  # FTS5 rank is negative BM25; invert so higher = better
            metadata=row.metadata,
        )
        for row in rows
    ]


def _jaccard_search(
    query_morphemes: set[str],
    top_k: int,
    filters: SearchFilter | None = None,
) -> list[SearchResult]:
    with client.session() as db:
        q = (
            db.query(Chunk, Document.source, Document.metadata_)
            .join(Document, Chunk.document_id == Document.id)
        )
        if filters:
            q = apply_orm_filter(q, filters)
        raw_rows = q.all()

    scored: list[SearchResult] = []
    for chunk, source, metadata in raw_rows:
        chunk_morphemes = _tokenize(chunk.content)
        score = _jaccard(query_morphemes, chunk_morphemes)
        if score > 0:
            scored.append(
                SearchResult(
                    chunk_id=chunk.id,
                    document_id=chunk.document_id,
                    source=source,
                    content=chunk.content,
                    score=score,
                    metadata=metadata,
                )
            )

    scored.sort(key=lambda r: r.score, reverse=True)
    return scored[:top_k]


_kiwi: object = None


def _get_kiwi() -> object:
    global _kiwi
    if _kiwi is None:
        try:
            from kiwipiepy import Kiwi
        except ImportError as e:
            raise SearchError("kiwipiepy is required: pip install kiwipiepy") from e
        _kiwi = Kiwi()
    return _kiwi


def _tokenize(text: str) -> set[str]:
    kiwi = _get_kiwi()
    tokens = kiwi.tokenize(text)
    content_tags = {"NNG", "NNP", "VV", "VA", "XR"}
    return {token.form for token in tokens if token.tag in content_tags}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
