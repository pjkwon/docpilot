from __future__ import annotations

from docpilot.search.highlight import highlight, render
from docpilot.search.hybrid import hybrid
from docpilot.search.models import DocumentResult, SearchFilter, SearchResult


def group_by_document(
    results: list[SearchResult],
    *,
    top_chunks: int = 3,
    score: str = "max",
) -> list[DocumentResult]:
    """
    Aggregate chunk-level *results* into per-document ``DocumentResult`` objects.

    Parameters
    ----------
    results:
        Chunk-level search results (from any search backend).
    top_chunks:
        How many top-scoring chunks to keep per document.
    score:
        Aggregation strategy — ``"max"`` (default) or ``"sum"``.
    """
    if score not in ("max", "sum"):
        raise ValueError(f"score must be 'max' or 'sum', got {score!r}")

    docs: dict[int, list[SearchResult]] = {}
    for r in results:
        docs.setdefault(r.document_id, []).append(r)

    doc_results: list[DocumentResult] = []
    for doc_id, chunks in docs.items():
        chunks_sorted = sorted(chunks, key=lambda c: c.score, reverse=True)
        agg_score = (
            chunks_sorted[0].score
            if score == "max"
            else sum(c.score for c in chunks_sorted)
        )
        doc_results.append(
            DocumentResult(
                document_id=doc_id,
                source=chunks_sorted[0].source,
                score=agg_score,
                chunk_count=len(chunks_sorted),
                top_chunks=chunks_sorted[:top_chunks],
                metadata=chunks_sorted[0].metadata,
            )
        )

    doc_results.sort(key=lambda d: d.score, reverse=True)
    return doc_results


__all__ = [
    "SearchResult",
    "SearchFilter",
    "DocumentResult",
    "group_by_document",
    "highlight",
    "render",
    "hybrid",
]
