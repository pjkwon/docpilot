from __future__ import annotations

from docpilot.exceptions import SearchError
from docpilot.search.models import SearchResult

_MODEL = "BAAI/bge-reranker-v2-m3"
_reranker: object = None


def _get_reranker() -> object:
    global _reranker
    if _reranker is None:
        try:
            from FlagEmbedding import FlagReranker
        except ImportError as e:
            raise SearchError("FlagEmbedding required: pip install FlagEmbedding") from e
        _reranker = FlagReranker(_MODEL, use_fp16=False)
    return _reranker


def rerank(query: str, results: list[SearchResult], top_k: int) -> list[SearchResult]:
    """Re-score candidates with a cross-encoder and return top_k by relevance."""
    if not results:
        return results

    reranker = _get_reranker()
    pairs = [[query, r.content] for r in results]
    raw_scores = reranker.compute_score(pairs, normalize=True)

    # compute_score returns a float when len==1, list otherwise
    if isinstance(raw_scores, float):
        raw_scores = [raw_scores]

    ranked = sorted(zip(raw_scores, results), key=lambda x: x[0], reverse=True)
    return [
        SearchResult(
            chunk_id=r.chunk_id,
            document_id=r.document_id,
            source=r.source,
            content=r.content,
            score=float(s),
        )
        for s, r in ranked[:top_k]
    ]
