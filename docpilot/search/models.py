from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SearchResult:
    chunk_id: int
    document_id: int
    source: str
    content: str
    score: float
    metadata: dict | None = None
    highlights: list[tuple[int, int]] | None = None


@dataclass
class SearchFilter:
    """Filter criteria applied before scoring."""

    source_pattern: str | None = None
    """Shell-glob style pattern matched against document source path (e.g. ``"*.hwpx"``)."""

    collection: str | None = None
    """Exact match against the document's collection tag (see ``indexer.index_folder(collection=...)``)."""

    mime_type: str | None = None
    """Exact MIME type match (e.g. ``"application/vnd.hancom.hwpx"``)."""

    metadata: dict[str, str] | None = None
    """Key-value pairs that must all match the document's JSON metadata column."""

    created_after: datetime | None = None
    created_before: datetime | None = None


@dataclass
class DocumentResult:
    """Chunk-level results aggregated to document granularity."""

    document_id: int
    source: str
    score: float
    chunk_count: int
    top_chunks: list[SearchResult]
    metadata: dict | None = None
