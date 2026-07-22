from __future__ import annotations

import re

from sqlalchemy.orm import Query

from docpilot.db.schema import Document
from docpilot.search.models import SearchFilter


def apply_orm_filter(q: Query, f: SearchFilter) -> Query:
    """Apply *f* to an ORM query that already joins the Document table."""
    if f.source_pattern:
        q = q.filter(Document.source.like(_glob_to_like(f.source_pattern)))
    if f.collection:
        q = q.filter(Document.collection == f.collection)
    if f.mime_type:
        q = q.filter(Document.mime_type == f.mime_type)
    if f.created_after:
        q = q.filter(Document.created_at >= f.created_after)
    if f.created_before:
        q = q.filter(Document.created_at <= f.created_before)
    if f.metadata:
        for key, value in f.metadata.items():
            _validate_key(key)
            q = q.filter(Document.metadata_[key].as_string() == str(value))
    return q


def build_sql_where(f: SearchFilter, *, is_sqlite: bool) -> tuple[str, dict]:
    """
    Return ``(extra_where, params)`` to inject into raw SQL strings.

    The returned clause starts with ``" AND "`` when non-empty, so it can be
    appended directly to an existing WHERE clause.
    """
    clauses: list[str] = []
    params: dict = {}

    if f.source_pattern:
        clauses.append("d.source LIKE :f_source_pattern")
        params["f_source_pattern"] = _glob_to_like(f.source_pattern)

    if f.collection:
        clauses.append("d.collection = :f_collection")
        params["f_collection"] = f.collection

    if f.mime_type:
        clauses.append("d.mime_type = :f_mime_type")
        params["f_mime_type"] = f.mime_type

    if f.created_after:
        clauses.append("d.created_at >= :f_created_after")
        params["f_created_after"] = f.created_after.isoformat()

    if f.created_before:
        clauses.append("d.created_at <= :f_created_before")
        params["f_created_before"] = f.created_before.isoformat()

    if f.metadata:
        for i, (key, value) in enumerate(f.metadata.items()):
            _validate_key(key)
            if is_sqlite:
                clauses.append(f"json_extract(d.metadata, '$.{key}') = :f_meta_{i}")
            else:
                clauses.append(f"d.metadata->>'{key}' = :f_meta_{i}")
            params[f"f_meta_{i}"] = str(value)

    if not clauses:
        return "", params
    return " AND " + " AND ".join(clauses), params


_KEY_RE = re.compile(r"^[A-Za-z0-9_]+$")


def _validate_key(key: str) -> None:
    if not _KEY_RE.match(key):
        raise ValueError(f"metadata key must be alphanumeric/underscore: {key!r}")


def _glob_to_like(pattern: str) -> str:
    return pattern.replace("*", "%").replace("?", "_")
