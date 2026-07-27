from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from docpilot.exceptions import ContextExceededError
from docpilot.mapping.base import BaseLLMMapper, MappingResult, TemplateSection
from docpilot.search.models import SearchFilter, SearchResult

if TYPE_CHECKING:
    from docpilot.ingestion.models import IngestedDocument

logger = logging.getLogger(__name__)

EmbedFn = Callable[[str], list[float]]

_MAX_CONTEXT_RETRIES = 2


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

    def map(
        self,
        sections: list[TemplateSection],
        instructions: str | None = None,
        top_k: int | None = None,
        filters: SearchFilter | None = None,
    ) -> MappingResult:
        effective_top_k = top_k if top_k is not None else self._top_k

        for attempt in range(_MAX_CONTEXT_RETRIES + 1):
            content = self.retrieve_content(sections, top_k=effective_top_k, filters=filters)
            try:
                return self._mapper.map(content, sections, instructions)
            except ContextExceededError:
                if attempt >= _MAX_CONTEXT_RETRIES or effective_top_k <= 1:
                    raise
                new_top_k = max(1, effective_top_k // 2)
                logger.warning(
                    "컨텍스트 초과로 top_k %d → %d로 줄여 재시도 (%d/%d)",
                    effective_top_k, new_top_k, attempt + 1, _MAX_CONTEXT_RETRIES,
                )
                effective_top_k = new_top_k

    def retrieve_content(
        self,
        sections: list[TemplateSection],
        top_k: int | None = None,
        filters: SearchFilter | None = None,
    ) -> str:
        """Retrieve and assemble relevant chunks for the given sections."""
        effective_top_k = top_k if top_k is not None else self._top_k
        return retrieve(
            sections,
            embed_fn=self._embed_fn,
            top_k=effective_top_k,
            use_reranker=self._use_reranker,
            filters=filters,
        )


def retrieve(
    sections: list[TemplateSection],
    embed_fn: EmbedFn | None = None,
    top_k: int = 10,
    use_reranker: bool = False,
    filters: SearchFilter | None = None,
) -> str:
    """
    Retrieve and assemble relevant chunks for the given sections — no LLM call.

    Standalone counterpart to ``RagMapper.retrieve_content()`` that needs no
    ``BaseLLMMapper``/API key, for callers that only want the search step (e.g. an MCP
    tool that hands the retrieved context to the calling client for generation instead
    of calling an LLM API itself).

    embed_fn: if provided, runs morpheme AND + vector search in parallel and merges via RRF.
              When omitted, runs morpheme AND with OR fallback.
    use_reranker: if True, re-scores candidates with BGE reranker (BAAI/bge-reranker-v2-m3).
                  Retrieves top_k * 3 candidates first, then reranks down to top_k.
    """
    return _assemble(_retrieve(sections, embed_fn, top_k, use_reranker, filters))


def _retrieve(
    sections: list[TemplateSection],
    embed_fn: EmbedFn | None,
    top_k: int,
    use_reranker: bool,
    filters: SearchFilter | None,
) -> list[SearchResult]:
    query = _build_query(sections)
    # Fetch more candidates when reranking so the reranker has room to reorder
    candidate_k = top_k * 3 if use_reranker else top_k

    from docpilot.exceptions import SearchError
    from docpilot.search import morpheme as mor_search

    if embed_fn is not None:
        # Hybrid: morpheme AND + vector in parallel, merged via RRF
        from docpilot.search import embedding as emb_search
        try:
            morph_results = mor_search.search(query, top_k=candidate_k, or_fallback=False, filters=filters)
        except SearchError:
            morph_results = []
        vec_results = emb_search.search(query, embed_fn, top_k=candidate_k, filters=filters)
        results = _rrf_merge(morph_results, vec_results, top_k=candidate_k)
        if not results:
            # Both empty → OR as last resort
            try:
                results = mor_search.search(query, top_k=candidate_k, or_fallback=True, filters=filters)
            except SearchError:
                return []
    else:
        try:
            results = mor_search.search(query, top_k=candidate_k, or_fallback=True, filters=filters)
        except SearchError:
            return []

    if use_reranker and results:
        from docpilot.search import reranker as reranker_mod
        results = reranker_mod.rerank(query, results, top_k)

    return results[:top_k]


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
