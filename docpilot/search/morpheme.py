from __future__ import annotations

from sqlalchemy import text

from docpilot.db import client
from docpilot.db.schema import Chunk, Document
from docpilot.exceptions import SearchError
from docpilot.search.models import SearchResult


def search(query: str, top_k: int = 10, or_fallback: bool = False) -> list[SearchResult]:
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
        results = _fts_search(query_morphemes, top_k, use_or=False)
        if not results and or_fallback:
            results = _fts_search(query_morphemes, top_k, use_or=True)
        return results
    return _jaccard_search(query_morphemes, top_k)


def _fts_search(morphemes: set[str], top_k: int, use_or: bool = False) -> list[SearchResult]:
    fts_query = (" OR " if use_or else " ").join(morphemes)
    sql = text("""
        SELECT f.rowid AS chunk_id, c.document_id, d.source, c.content, rank AS score
        FROM fts_chunks f
        JOIN chunks c ON c.id = f.rowid
        JOIN documents d ON d.id = c.document_id
        WHERE fts_chunks MATCH :query
        ORDER BY rank
        LIMIT :top_k
    """)
    with client.session() as db:
        rows = db.execute(sql, {"query": fts_query, "top_k": top_k}).fetchall()
    return [
        SearchResult(
            chunk_id=row.chunk_id,
            document_id=row.document_id,
            source=row.source,
            content=row.content,
            score=-float(row.score),  # FTS5 rank is negative BM25; invert so higher = better
        )
        for row in rows
    ]


def _jaccard_search(query_morphemes: set[str], top_k: int) -> list[SearchResult]:
    with client.session() as db:
        raw_rows = (
            db.query(Chunk, Document.source)
            .join(Document, Chunk.document_id == Document.id)
            .all()
        )
        rows = [
            (chunk.id, chunk.document_id, chunk.content, source)
            for chunk, source in raw_rows
        ]

    scored: list[SearchResult] = []
    for chunk_id, document_id, content, source in rows:
        chunk_morphemes = _tokenize(content)
        score = _jaccard(query_morphemes, chunk_morphemes)
        if score > 0:
            scored.append(
                SearchResult(
                    chunk_id=chunk_id,
                    document_id=document_id,
                    source=source,
                    content=content,
                    score=score,
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
