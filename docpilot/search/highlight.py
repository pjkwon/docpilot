from __future__ import annotations

import re

from docpilot.search.models import SearchResult


def highlight(result: SearchResult, query: str) -> SearchResult:
    """
    Return a copy of *result* with ``highlights`` set to non-overlapping
    ``(start, end)`` byte-index spans of query terms found in ``result.content``.
    """
    terms = _split_terms(query)
    spans = _find_spans(result.content, terms)
    return SearchResult(
        chunk_id=result.chunk_id,
        document_id=result.document_id,
        source=result.source,
        content=result.content,
        score=result.score,
        metadata=result.metadata,
        highlights=spans or None,
    )


def render(result: SearchResult, marker: str = "**") -> str:
    """
    Return ``result.content`` with highlighted spans wrapped in *marker*.

    Example::

        render(r, "**")  →  "이것은 **사업 계획** 문서입니다"
    """
    if not result.highlights:
        return result.content

    content = result.content
    parts: list[str] = []
    prev = 0
    for start, end in sorted(result.highlights):
        parts.append(content[prev:start])
        parts.append(f"{marker}{content[start:end]}{marker}")
        prev = end
    parts.append(content[prev:])
    return "".join(parts)


def _split_terms(query: str) -> list[str]:
    return [t for t in re.split(r"\s+", query.strip()) if t]


def _find_spans(content: str, terms: list[str]) -> list[tuple[int, int]]:
    """Find all non-overlapping spans; merge overlapping ones."""
    spans: list[list[int]] = []
    lower = content.lower()
    for term in terms:
        t = term.lower()
        pos = 0
        while True:
            idx = lower.find(t, pos)
            if idx == -1:
                break
            spans.append([idx, idx + len(t)])
            pos = idx + 1

    spans.sort()
    merged: list[list[int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(s, e) for s, e in merged]
