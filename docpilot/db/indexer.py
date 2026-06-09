from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy.exc import IntegrityError

from docpilot.db import client
from docpilot.db.schema import Chunk, Document
from docpilot.exceptions import SearchError
from docpilot.ingestion.models import IngestedDocument

EmbedFn = Callable[[str], list[float]]

_CHUNK_SIZE = 1000
_CHUNK_OVERLAP = 200


def index(
    doc: IngestedDocument,
    embed_fn: EmbedFn | None = None,
    chunk_size: int = _CHUNK_SIZE,
    overlap: int = _CHUNK_OVERLAP,
) -> int:
    """
    Index an IngestedDocument into the database.

    Returns the document ID. Skips re-indexing if the source already exists.
    embed_fn: optional callable (text -> vector) for generating embeddings.
    """
    with client.session() as db:
        existing = (
            db.query(Document)
            .filter(Document.source == str(doc.source))
            .first()
        )
        if existing:
            return existing.id

        db_doc = Document(
            source=str(doc.source),
            mime_type=doc.mime_type,
            content=doc.content,
            metadata_=doc.metadata,
        )
        db.add(db_doc)
        db.flush()  # get db_doc.id before adding chunks

        chunks = _split(doc.content, chunk_size, overlap)
        for i, chunk_text in enumerate(chunks):
            chunk = Chunk(
                document_id=db_doc.id,
                chunk_index=i,
                content=chunk_text,
            )
            db.add(chunk)
            db.flush()

            if embed_fn:
                _set_embedding(db, chunk.id, embed_fn(chunk_text))

        return db_doc.id


def reindex(
    doc: IngestedDocument,
    embed_fn: EmbedFn | None = None,
    chunk_size: int = _CHUNK_SIZE,
    overlap: int = _CHUNK_OVERLAP,
) -> int:
    """Delete existing document and re-index from scratch."""
    with client.session() as db:
        existing = (
            db.query(Document)
            .filter(Document.source == str(doc.source))
            .first()
        )
        if existing:
            db.delete(existing)

    return index(doc, embed_fn=embed_fn, chunk_size=chunk_size, overlap=overlap)


def index_folder(
    folder: str | Path,
    embed_fn: EmbedFn | None = None,
    force: bool = False,
) -> list[int]:
    """Ingest and index all supported files in a folder. force=True re-indexes already indexed files."""
    from docpilot.ingestion import text as text_ing
    from docpilot.ingestion import pdf as pdf_ing
    from docpilot.ingestion import image as image_ing
    from docpilot.ingestion import pptx as pptx_ing
    from docpilot.ingestion import hwpx as hwpx_ing
    from docpilot.ingestion import docx as docx_ing
    from docpilot.exceptions import IngestionError

    folder = Path(folder)
    if not folder.is_dir():
        raise SearchError("Not a directory", detail=str(folder))

    ingesters = {
        **{ext: text_ing.ingest for ext in text_ing.SUPPORTED_EXTENSIONS},
        ".pdf": pdf_ing.ingest,
        **{ext: image_ing.ingest for ext in image_ing.SUPPORTED_EXTENSIONS},
        ".pptx": pptx_ing.ingest,
        ".hwpx": hwpx_ing.ingest,
        ".docx": docx_ing.ingest,
    }

    doc_ids: list[int] = []
    for file in sorted(folder.rglob("*")):
        if not file.is_file():
            continue
        ingester = ingesters.get(file.suffix.lower())
        if not ingester:
            continue
        try:
            doc = ingester(file)
            doc_id = reindex(doc, embed_fn=embed_fn) if force else index(doc, embed_fn=embed_fn)
            doc_ids.append(doc_id)
        except IngestionError as e:
            import sys
            print(f"[docpilot] skipped {file.name}: {e}", file=sys.stderr)
        except Exception as e:
            raise SearchError("Unexpected error during indexing", detail=str(e)) from e

    return doc_ids


def _split(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Split text at \\n\\n paragraph boundaries.

    Units (paragraphs) are never broken mid-way unless a single unit
    exceeds chunk_size, in which case character splitting is used as a
    fallback for that unit only.
    """
    if not text:
        return []

    units = [u for u in text.split("\n\n") if u.strip()]
    if not units:
        return []

    chunks: list[str] = []
    window: list[str] = []
    window_len = 0  # joined char count including \n\n separators

    for unit in units:
        unit_len = len(unit)

        # Single unit exceeds chunk_size — char-split fallback for this unit only
        if unit_len > chunk_size:
            if window:
                chunks.append("\n\n".join(window))
                window, window_len = [], 0
            start = 0
            while start < unit_len:
                chunks.append(unit[start:start + chunk_size])
                start += chunk_size - overlap
            continue

        # Would adding this unit overflow the window?
        sep = 2 if window else 0
        if window_len + sep + unit_len > chunk_size:
            chunks.append("\n\n".join(window))

            # Carry over trailing units within the overlap budget
            tail: list[str] = []
            tail_len = 0
            for prev in reversed(window):
                cost = len(prev) + (2 if tail else 0)
                if tail_len + cost <= overlap:
                    tail.insert(0, prev)
                    tail_len += cost
                else:
                    break

            window = tail
            window_len = tail_len
            sep = 2 if window else 0

        window_len += sep + unit_len
        window.append(unit)

    if window:
        chunks.append("\n\n".join(window))

    return chunks


def _set_embedding(db: Any, chunk_id: int, vector: list[float]) -> None:
    from sqlalchemy import text
    from docpilot.db import client

    if client.is_sqlite():
        try:
            import sqlite_vec
        except ImportError as e:
            raise SearchError("sqlite-vec required for embeddings: pip install sqlite-vec") from e
        db.execute(text("DELETE FROM vec_chunks WHERE chunk_id = :id"), {"id": chunk_id})
        db.execute(
            text("INSERT INTO vec_chunks(chunk_id, embedding) VALUES (:id, :vec)"),
            {"id": chunk_id, "vec": sqlite_vec.serialize_float32(vector)},
        )
    else:
        db.execute(
            text("UPDATE chunks SET embedding = :vec WHERE id = :id"),
            {"vec": str(vector), "id": chunk_id},
        )
