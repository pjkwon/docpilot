from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy import text

from docpilot.db import client
from docpilot.db.schema import TemplateRecord
from docpilot.exceptions import SearchError

EmbedFn = Callable[[str], list[float]]


def save(
    name: str,
    path: str | Path,
    description: str,
    tags: list[str] | None = None,
    metadata: dict | None = None,
    embed_fn: EmbedFn | None = None,
) -> int:
    """
    Persist a TemplateRecord and index it for search.

    If a record for this path already exists, it is replaced.
    Returns the template record ID.
    """
    path_str = str(path)

    with client.session() as db:
        existing = db.query(TemplateRecord).filter(TemplateRecord.path == path_str).first()
        if existing:
            db.delete(existing)
            db.flush()

        record = TemplateRecord(
            name=name,
            path=path_str,
            description=description,
            tags=tags,
            metadata_=metadata,
        )
        db.add(record)
        db.flush()

        _set_morphemes(db, record.id, name, description, tags)
        if embed_fn:
            _set_embedding(db, record.id, embed_fn(description))

        return record.id


def search(
    query: str,
    embed_fn: EmbedFn | None = None,
    top_k: int = 5,
) -> list[TemplateRecord]:
    """
    Hybrid template search (vector + morpheme RRF).

    Falls back to FTS-only when embed_fn is None.
    Returns detached TemplateRecord instances ordered by relevance.
    """
    if not query.strip():
        raise SearchError("Query must not be empty")

    if client.is_sqlite():
        vec_ids = _vec_search(query, embed_fn, top_k * 2) if embed_fn else []
        fts_ids = _fts_search(query, top_k * 2)
        merged = _rrf_merge(vec_ids, fts_ids, top_k)
    else:
        merged = []  # PostgreSQL path: fall through to recency fallback

    if merged:
        id_to_rank = {tid: rank for rank, tid in enumerate(merged)}
        with client.session() as db:
            rows = db.query(TemplateRecord).filter(TemplateRecord.id.in_(merged)).all()
            for r in rows:
                db.expunge(r)
        rows.sort(key=lambda r: id_to_rank.get(r.id, 999))
        return rows

    # Fallback: most recent records
    with client.session() as db:
        rows = (
            db.query(TemplateRecord)
            .order_by(TemplateRecord.created_at.desc())
            .limit(top_k)
            .all()
        )
        for r in rows:
            db.expunge(r)
        return rows


def generate_description(
    section_xml_path: str | Path,
    model: str = "claude-sonnet-4-6",
) -> str:
    """
    Ask the LLM to produce a natural language description of a section0.xml template.

    The returned description is suitable for embedding-based similarity search.
    It captures the document type, typical use case, and section structure.
    """
    try:
        import anthropic
    except ImportError as e:
        raise ImportError("anthropic required: pip install anthropic") from e

    section_xml = Path(section_xml_path).read_text(encoding="utf-8")

    prompt = f"""다음은 한컴오피스 HWPX 문서의 section0.xml 파일입니다.
이 파일의 플레이스홀더 키와 구조를 분석하여, 이 템플릿이 어떤 용도의 문서인지 한국어로 설명해주세요.

설명에 포함할 내용:
- 문서 종류 (예: 업무 보고서, 학술 발표, 공문, 회의록, 기획서 등)
- 주요 섹션 구성
- 전형적인 사용 상황 또는 목적

설명은 3~5문장으로 작성하고, 다른 텍스트 없이 설명만 출력하세요.

## section0.xml
{section_xml[:4000]}
"""

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    ai = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    response = ai.messages.create(
        model=model,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _set_morphemes(
    db: Any,
    template_id: int,
    name: str,
    description: str,
    tags: list[str] | None,
) -> None:
    if not client.is_sqlite():
        return
    try:
        from docpilot.search.morpheme import _tokenize
    except Exception:
        return  # kiwipiepy not installed — skip FTS5

    combined = " ".join(filter(None, [name, description] + (tags or [])))
    morphemes = " ".join(_tokenize(combined))
    if not morphemes:
        return

    db.execute(text("DELETE FROM fts_templates WHERE rowid = :id"), {"id": template_id})
    db.execute(
        text("INSERT INTO fts_templates(rowid, morphemes) VALUES (:id, :morphemes)"),
        {"id": template_id, "morphemes": morphemes},
    )


def _set_embedding(db: Any, template_id: int, vector: list[float]) -> None:
    if client.is_sqlite():
        try:
            import sqlite_vec
        except ImportError as e:
            raise SearchError("sqlite-vec required for embeddings: pip install sqlite-vec") from e
        db.execute(text("DELETE FROM vec_templates WHERE template_id = :id"), {"id": template_id})
        db.execute(
            text("INSERT INTO vec_templates(template_id, embedding) VALUES (:id, :vec)"),
            {"id": template_id, "vec": sqlite_vec.serialize_float32(vector)},
        )
    else:
        db.execute(
            text("UPDATE template_records SET embedding = :vec WHERE id = :id"),
            {"vec": str(vector), "id": template_id},
        )


def _vec_search(query: str, embed_fn: EmbedFn, top_k: int) -> list[int]:
    try:
        import sqlite_vec
    except ImportError:
        return []
    try:
        vec = embed_fn(query)
    except Exception:
        return []

    sql = text("""
        SELECT template_id
        FROM vec_templates
        WHERE embedding MATCH :vec AND k = :top_k
        ORDER BY distance
    """)
    with client.session() as db:
        rows = db.execute(sql, {"vec": sqlite_vec.serialize_float32(vec), "top_k": top_k}).fetchall()
    return [row.template_id for row in rows]


def _fts_search(query: str, top_k: int) -> list[int]:
    try:
        from docpilot.search.morpheme import _tokenize
    except Exception:
        return []

    morphemes = _tokenize(query)
    if not morphemes:
        return []

    sql = text("""
        SELECT rowid
        FROM fts_templates
        WHERE fts_templates MATCH :query
        ORDER BY rank
        LIMIT :top_k
    """)

    with client.session() as db:
        rows = db.execute(sql, {"query": " ".join(morphemes), "top_k": top_k}).fetchall()
        if not rows:
            rows = db.execute(sql, {"query": " OR ".join(morphemes), "top_k": top_k}).fetchall()
    return [row.rowid for row in rows]


def _rrf_merge(vec_ids: list[int], fts_ids: list[int], top_k: int, k: int = 60) -> list[int]:
    scores: dict[int, float] = {}
    for rank, tid in enumerate(vec_ids):
        scores[tid] = scores.get(tid, 0.0) + 1.0 / (k + rank + 1)
    for rank, tid in enumerate(fts_ids):
        scores[tid] = scores.get(tid, 0.0) + 1.0 / (k + rank + 1)
    return [tid for tid, _ in sorted(scores.items(), key=lambda x: -x[1])][:top_k]
