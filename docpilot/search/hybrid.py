from __future__ import annotations

from collections.abc import Callable

from docpilot.exceptions import SearchError
from docpilot.search import morpheme
from docpilot.search.models import SearchFilter, SearchResult

EmbedFn = Callable[[str], list[float]]

_RRF_K = 60


def hybrid(
    query: str,
    embed_fn: EmbedFn | None = None,
    top_k: int = 10,
    bm25_weight: float = 1.0,
    vec_weight: float = 1.0,
    filters: SearchFilter | None = None,
    or_fallback: bool = True,
) -> list[SearchResult]:
    """
    Hybrid search: BM25 (morpheme FTS5) + vector similarity, fused with RRF.

    Falls back to BM25-only when embed_fn is None or vector search returns nothing.

    Parameters
    ----------
    query:
        Search query string.
    embed_fn:
        Embedding function (from docpilot.search.embedding). Optional.
    top_k:
        Number of results to return.
    bm25_weight:
        RRF weight for BM25 lane (default 1.0).
    vec_weight:
        RRF weight for vector lane (default 1.0).
    filters:
        Optional document-level filter criteria.
    or_fallback:
        If True, morpheme search retries with OR when AND returns nothing.
    """
    if not query.strip():
        raise SearchError("Query must not be empty")

    fetch_k = top_k * 3

    bm25_results = morpheme.search(
        query, top_k=fetch_k, or_fallback=or_fallback, filters=filters
    )

    vec_results: list[SearchResult] = []
    if embed_fn is not None:
        from docpilot.search import embedding
        vec_results = embedding.search(
            query, embed_fn=embed_fn, top_k=fetch_k, filters=filters
        )

    if not vec_results:
        return bm25_results[:top_k]

    # chunk_id → SearchResult (BM25 wins on duplicate; vec fills gaps)
    result_map: dict[int, SearchResult] = {r.chunk_id: r for r in bm25_results}
    for r in vec_results:
        result_map.setdefault(r.chunk_id, r)

    # RRF score accumulation
    scores: dict[int, float] = {}
    for rank, r in enumerate(bm25_results):
        scores[r.chunk_id] = scores.get(r.chunk_id, 0.0) + bm25_weight / (_RRF_K + rank + 1)
    for rank, r in enumerate(vec_results):
        scores[r.chunk_id] = scores.get(r.chunk_id, 0.0) + vec_weight / (_RRF_K + rank + 1)

    ranked_ids = sorted(scores, key=lambda cid: -scores[cid])[:top_k]

    merged: list[SearchResult] = []
    for cid in ranked_ids:
        r = result_map[cid]
        merged.append(
            SearchResult(
                chunk_id=r.chunk_id,
                document_id=r.document_id,
                source=r.source,
                content=r.content,
                score=scores[cid],
                metadata=r.metadata,
                highlights=r.highlights,
            )
        )
    return merged
