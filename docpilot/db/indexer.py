from __future__ import annotations

import hashlib
import threading
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
_MIN_CHUNK_SIZE = 200


def _compute_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def index(
    doc: IngestedDocument,
    embed_fn: EmbedFn | None = None,
    chunk_size: int = _CHUNK_SIZE,
    overlap: int = _CHUNK_OVERLAP,
    min_chunk_size: int = _MIN_CHUNK_SIZE,
    file_hash: str | None = None,
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
            file_hash=file_hash,
            metadata_=doc.metadata,
        )
        db.add(db_doc)
        db.flush()  # get db_doc.id before adding chunks

        chunks = _split(doc.content, chunk_size, overlap, min_chunk_size)
        db_chunks: list[Chunk] = []
        for i, chunk_text in enumerate(chunks):
            chunk = Chunk(
                document_id=db_doc.id,
                chunk_index=i,
                content=chunk_text,
            )
            db.add(chunk)
            db_chunks.append(chunk)

        db.flush()  # single flush — all chunks get IDs at once

        for chunk in db_chunks:
            _set_morphemes(db, chunk.id, chunk.content)

        if embed_fn and db_chunks:
            vectors = _batch_embed(embed_fn, [c.content for c in db_chunks])
            for chunk, vec in zip(db_chunks, vectors):
                _set_embedding(db, chunk.id, vec)

        return db_doc.id


def cleanup_orphans(folder: str | Path | None = None) -> list[str]:
    """Delete Document records whose source file no longer exists on disk.

    folder: if given, only check records whose source path starts with this folder.
    Returns list of deleted source paths.
    """
    folder_prefix = str(Path(folder).resolve()) if folder else None

    with client.session() as db:
        query = db.query(Document)
        if folder_prefix:
            query = query.filter(Document.source.like(folder_prefix + "%"))
        docs = query.all()

        deleted = []
        for doc in docs:
            if not Path(doc.source).exists():
                db.delete(doc)
                deleted.append(doc.source)

    return deleted


def reindex(
    doc: IngestedDocument,
    embed_fn: EmbedFn | None = None,
    chunk_size: int = _CHUNK_SIZE,
    overlap: int = _CHUNK_OVERLAP,
    min_chunk_size: int = _MIN_CHUNK_SIZE,
    file_hash: str | None = None,
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

    return index(doc, embed_fn=embed_fn, chunk_size=chunk_size, overlap=overlap, min_chunk_size=min_chunk_size, file_hash=file_hash)


class IndexCancelledError(Exception):
    """Raised when indexing is cancelled via cancel_event."""


def index_folder(
    folder: str | Path,
    embed_fn: EmbedFn | None = None,
    force: bool = False,
    progress_fn: Callable[[int], None] | None = None,
    cancel_event: threading.Event | None = None,
    file_timeout: float | None = 300.0,
    files: list[str] | None = None,
) -> list[int]:
    """Ingest and index all supported files in a folder. force=True re-indexes already indexed files.

    progress_fn: optional callback called with the running count of indexed files after each file.
    cancel_event: if set, indexing stops cleanly between files and raises IndexCancelledError.
    file_timeout: per-file ingestion timeout in seconds (default 300s). None disables timeout.
    files: if given, only index files whose name matches one of these entries (case-insensitive on Windows).
    """
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

    from docpilot.ingestion import _ingesters_table
    from docpilot.exceptions import IngestionError

    import sys

    folder = Path(folder)
    if not folder.is_dir():
        raise SearchError("Not a directory", detail=str(folder))

    ingesters = _ingesters_table()

    files_filter: set[str] | None = (
        {f.lower() for f in files} if files is not None else None
    )

    doc_ids: list[int] = []
    with ThreadPoolExecutor(max_workers=1) as executor:
        for file in sorted(folder.rglob("*")):
            if cancel_event and cancel_event.is_set():
                raise IndexCancelledError(f"cancelled after {len(doc_ids)} files")

            if not file.is_file():
                continue
            if files_filter is not None and file.name.lower() not in files_filter:
                continue
            ingester = ingesters.get(file.suffix.lower())
            if not ingester:
                continue
            try:
                file_hash = _compute_hash(file)
                if force:
                    if file_timeout is not None:
                        future = executor.submit(ingester, file)
                        try:
                            doc = future.result(timeout=file_timeout)
                        except FuturesTimeoutError:
                            print(f"[docpilot] timeout {file.name}: exceeded {file_timeout:.0f}s, skipping", file=sys.stderr)
                            continue
                    else:
                        doc = ingester(file)
                    doc_id = reindex(doc, embed_fn=embed_fn, file_hash=file_hash)
                else:
                    with client.session() as db:
                        existing = (
                            db.query(Document)
                            .filter(Document.source == str(file))
                            .first()
                        )
                        existing_id: int | None = existing.id if existing else None
                        existing_hash: str | None = existing.file_hash if existing else None
                    if existing_id is not None and existing_hash == file_hash:
                        doc_ids.append(existing_id)
                        continue
                    if file_timeout is not None:
                        future = executor.submit(ingester, file)
                        try:
                            doc = future.result(timeout=file_timeout)
                        except FuturesTimeoutError:
                            print(f"[docpilot] timeout {file.name}: exceeded {file_timeout:.0f}s, skipping", file=sys.stderr)
                            continue
                    else:
                        doc = ingester(file)
                    if existing_id is not None:
                        doc_id = reindex(doc, embed_fn=embed_fn, file_hash=file_hash)
                    else:
                        doc_id = index(doc, embed_fn=embed_fn, file_hash=file_hash)
                doc_ids.append(doc_id)
                if progress_fn:
                    progress_fn(len(doc_ids))
            except IngestionError as e:
                print(f"[docpilot] skipped {file.name}: {e}", file=sys.stderr)
            except IndexCancelledError:
                raise
            except Exception as e:
                raise SearchError("Unexpected error during indexing", detail=str(e)) from e

    return doc_ids


def _split(text: str, chunk_size: int, overlap: int, min_chunk_size: int = 0) -> list[str]:
    """Split text at \\n\\n paragraph boundaries.

    Units (paragraphs) are never broken mid-way unless a single unit
    exceeds chunk_size, in which case character splitting is used as a
    fallback for that unit only.

    Chunks below min_chunk_size are merged into the previous chunk.
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

    # Merge chunks below min_chunk_size into their predecessor
    if min_chunk_size > 0 and len(chunks) > 1:
        merged: list[str] = [chunks[0]]
        for chunk in chunks[1:]:
            if len(chunk) < min_chunk_size:
                merged[-1] = merged[-1] + "\n\n" + chunk
            else:
                merged.append(chunk)
        chunks = merged

    return chunks


def _set_morphemes(db: Any, chunk_id: int, chunk_text: str) -> None:
    if not client.is_sqlite():
        return
    try:
        from docpilot.search.morpheme import _tokenize
    except Exception:
        return  # kiwipiepy not installed — skip FTS5, indexing continues
    from sqlalchemy import text
    morphemes = " ".join(_tokenize(chunk_text))
    if not morphemes:
        return
    db.execute(text("DELETE FROM fts_chunks WHERE rowid = :id"), {"id": chunk_id})
    db.execute(
        text("INSERT INTO fts_chunks(rowid, morphemes) VALUES (:id, :morphemes)"),
        {"id": chunk_id, "morphemes": morphemes},
    )


def _batch_embed(fn: EmbedFn, texts: list[str]) -> list[list[float]]:
    """Call embed_fn with a list of texts. Falls back to per-text loop for non-batch functions."""
    if not texts:
        return []
    try:
        result = fn(texts)  # type: ignore[arg-type]
        if result and hasattr(result[0], "__iter__") and not isinstance(result[0], (str, float)):
            return [list(v) for v in result]
    except TypeError:
        pass
    return [fn(t) for t in texts]


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
