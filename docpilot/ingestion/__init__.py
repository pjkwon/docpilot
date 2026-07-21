from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from docpilot.ingestion.models import IngestedDocument

__all__ = ["IngestedDocument", "ingest_paths"]


def _ingesters_table() -> dict[str, Callable[[Path], IngestedDocument]]:
    """Extension -> per-format ingest() function. Shared by indexer.index_folder() and ingest_paths()."""
    from docpilot.ingestion import text as text_ing
    from docpilot.ingestion import pdf as pdf_ing
    from docpilot.ingestion import hwpx as hwpx_ing
    from docpilot.ingestion import hwp as hwp_ing
    from docpilot.ingestion import docx as docx_ing

    return {
        **{ext: text_ing.ingest for ext in text_ing.SUPPORTED_EXTENSIONS},
        ".pdf": pdf_ing.ingest,
        ".hwpx": hwpx_ing.ingest,
        ".hwp": hwp_ing.ingest,
        ".docx": docx_ing.ingest,
    }


def ingest_paths(paths: list[str | Path]) -> list[IngestedDocument]:
    """Ingest specific files directly — no chunking, no embedding, no DB storage.

    Unlike indexer.index_folder() (which walks a whole folder and silently skips
    files it doesn't recognize), this takes an explicit, caller-curated file list —
    an unsupported extension here is treated as a mistake, not noise, and raises.
    """
    from docpilot.exceptions import IngestionError

    table = _ingesters_table()
    docs: list[IngestedDocument] = []
    for p in paths:
        path = Path(p)
        ingester = table.get(path.suffix.lower())
        if ingester is None:
            raise IngestionError(
                f"Unsupported file extension: {path.suffix}",
                detail=str(path),
            )
        docs.append(ingester(path))
    return docs
