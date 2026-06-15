from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from docpilot.mapping.base import BaseLLMMapper, MappingResult, TemplateSection
from docpilot.search.models import SearchResult

if TYPE_CHECKING:
    from docpilot.ingestion.models import IngestedDocument

EmbedFn = Callable[[str], list[float]]


class RagMapper:
    """
    Wraps any BaseLLMMapper with retrieval-augmented generation.

    Retrieves relevant chunks from the indexed DB for the given sections,
    then delegates to the underlying mapper with the assembled context.

    embed_fn: if provided, runs morpheme AND + vector search in parallel and merges via RRF.
              When omitted, runs morpheme AND with OR fallback.
    top_k: number of chunks to return after retrieval (and reranking if enabled).
    use_reranker: if True, re-scores candidates with BGE reranker (BAAI/bge-reranker-v2-m3).
                  Retrieves top_k * 3 candidates first, then reranks down to top_k.
    """

    def __init__(
        self,
        mapper: BaseLLMMapper,
        embed_fn: EmbedFn | None = None,
        top_k: int = 10,
        use_reranker: bool = False,
    ) -> None:
        self._mapper = mapper
        self._embed_fn = embed_fn
        self._top_k = top_k
        self._use_reranker = use_reranker

    def complete(self, prompt: str, max_tokens: int = 2048) -> str:
        return self._mapper.complete(prompt, max_tokens)

    def map(self, sections: list[TemplateSection], instructions: str | None = None, top_k: int | None = None) -> MappingResult:
        content = self.retrieve_content(sections, top_k=top_k)
        return self._mapper.map(content, sections, instructions)

    def retrieve_content(self, sections: list[TemplateSection], top_k: int | None = None) -> str:
        """Retrieve and assemble relevant chunks for the given sections."""
        return _assemble(self._retrieve(sections, top_k=top_k))

    def _retrieve(self, sections: list[TemplateSection], top_k: int | None = None) -> list[SearchResult]:
        query = _build_query(sections)
        effective_top_k = top_k if top_k is not None else self._top_k
        # Fetch more candidates when reranking so the reranker has room to reorder
        candidate_k = effective_top_k * 3 if self._use_reranker else effective_top_k

        from docpilot.exceptions import SearchError
        from docpilot.search import morpheme as mor_search

        if self._embed_fn is not None:
            # Hybrid: morpheme AND + vector in parallel, merged via RRF
            from docpilot.search import embedding as emb_search
            try:
                morph_results = mor_search.search(query, top_k=candidate_k, or_fallback=False)
            except SearchError:
                morph_results = []
            vec_results = emb_search.search(query, self._embed_fn, top_k=candidate_k)
            results = _rrf_merge(morph_results, vec_results, top_k=candidate_k)
            if not results:
                # Both empty → OR as last resort
                try:
                    results = mor_search.search(query, top_k=candidate_k, or_fallback=True)
                except SearchError:
                    return []
        else:
            try:
                results = mor_search.search(query, top_k=candidate_k, or_fallback=True)
            except SearchError:
                return []

        if self._use_reranker and results:
            from docpilot.search import reranker as reranker_mod
            results = reranker_mod.rerank(query, results, effective_top_k)

        return results[:effective_top_k]


def _rrf_merge(
    results_a: list[SearchResult],
    results_b: list[SearchResult],
    top_k: int,
    k: int = 60,
) -> list[SearchResult]:
    """Reciprocal Rank Fusion: score = Σ 1/(k + rank). k=60 is the standard default."""
    scores: dict[int, float] = {}
    by_id: dict[int, SearchResult] = {}

    for rank, r in enumerate(results_a, 1):
        scores[r.chunk_id] = scores.get(r.chunk_id, 0.0) + 1.0 / (k + rank)
        by_id[r.chunk_id] = r

    for rank, r in enumerate(results_b, 1):
        scores[r.chunk_id] = scores.get(r.chunk_id, 0.0) + 1.0 / (k + rank)
        by_id.setdefault(r.chunk_id, r)

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [
        SearchResult(
            chunk_id=by_id[cid].chunk_id,
            document_id=by_id[cid].document_id,
            source=by_id[cid].source,
            content=by_id[cid].content,
            score=rrf_score,
        )
        for cid, rrf_score in ranked[:top_k]
    ]


def _build_query(sections: list[TemplateSection]) -> str:
    # Prefer section names (short, keyword-focused) over descriptions.
    # Descriptions are verbose and inflate the morpheme count, making FTS5 AND too strict.
    parts: list[str] = []
    for s in sections:
        parts.append(s.name if s.name else s.description)
    return " ".join(parts)


def _assemble(results: list[SearchResult]) -> str:
    # Group chunks by source, preserving retrieval order within each source
    seen: dict[str, list[str]] = {}
    for r in results:
        seen.setdefault(r.source, []).append(r.content)

    parts: list[str] = []
    for source, chunks in seen.items():
        from pathlib import Path
        label = f"[출처: {Path(source).name}]"
        parts.append(f"{label}\n" + "\n".join(chunks))

    return "\n\n".join(parts)
