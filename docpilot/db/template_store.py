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
    header_xml: str | Path | None = None,
    tags: list[str] | None = None,
    metadata: dict | None = None,
    sections_meta: dict | None = None,
    auto_sections_meta: bool = True,
    mapper=None,
    model: str = "claude-sonnet-4-6",
    embed_fn: EmbedFn | None = None,
) -> int:
    """
    Persist a TemplateRecord and index it for search.

    sections_meta: per-section metadata dict {name: {description, rule, ...}}.
    auto_sections_meta: if True and sections_meta is None, infer via LLM.
    If a record for this path already exists, it is replaced.
    Returns the template record ID.
    """
    path_str = str(path)

    resolved_sections = sections_meta
    if resolved_sections is None and auto_sections_meta:
        try:
            resolved_sections = generate_sections_meta(path, mapper=mapper, model=model)
        except Exception:
            resolved_sections = {}

    merged_metadata: dict = dict(metadata or {})
    if resolved_sections:
        merged_metadata["sections"] = resolved_sections

    with client.session() as db:
        existing = db.query(TemplateRecord).filter(TemplateRecord.path == path_str).first()
        if existing:
            db.delete(existing)
            db.flush()

        record = TemplateRecord(
            name=name,
            path=path_str,
            header_xml=str(header_xml) if header_xml is not None else None,
            description=description,
            tags=tags,
            metadata_=merged_metadata or None,
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
    fallback: bool = True,
) -> list[TemplateRecord]:
    """
    Hybrid template search (vector + morpheme RRF).

    Falls back to FTS-only when embed_fn is None.
    fallback=False returns [] when no search results match (skips recency fallback).
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

    if not fallback:
        return []

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


def list_all(order_by: str = "created_at") -> list[TemplateRecord]:
    """Return all saved templates, newest first by default."""
    col = getattr(TemplateRecord, order_by, TemplateRecord.created_at)
    with client.session() as db:
        rows = db.query(TemplateRecord).order_by(col.desc()).all()
        for r in rows:
            db.expunge(r)
        return rows


def delete(template_id: int) -> bool:
    """Delete a template by ID. Returns True if found and deleted."""
    with client.session() as db:
        record = db.query(TemplateRecord).filter(TemplateRecord.id == template_id).first()
        if record is None:
            return False
        db.delete(record)
    return True


def delete_by_path(path: str | Path) -> bool:
    """Delete a template by its section0.xml path. Returns True if found and deleted."""
    with client.session() as db:
        record = db.query(TemplateRecord).filter(TemplateRecord.path == str(path)).first()
        if record is None:
            return False
        db.delete(record)
    return True


def update(
    template_id: int,
    name: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    sections_meta: dict | None = None,
    embed_fn: EmbedFn | None = None,
) -> bool:
    """
    Update template metadata. Only provided fields are changed.

    sections_meta: replaces the "sections" key in metadata_ when provided.
    If description is updated and embed_fn is given, the vector index is rebuilt.
    Returns True if found and updated.
    """
    with client.session() as db:
        record = db.query(TemplateRecord).filter(TemplateRecord.id == template_id).first()
        if record is None:
            return False

        if name is not None:
            record.name = name
        if description is not None:
            record.description = description
        if tags is not None:
            record.tags = tags
        if sections_meta is not None:
            current_meta = dict(record.metadata_ or {})
            current_meta["sections"] = sections_meta
            record.metadata_ = current_meta

        db.flush()

        rebuild_index = name is not None or description is not None or tags is not None
        if rebuild_index:
            _set_morphemes(db, record.id, record.name, record.description, record.tags)
        if description is not None and embed_fn is not None:
            _set_embedding(db, record.id, embed_fn(record.description))

    return True


def generate_sections_meta(
    section_xml_path: str | Path,
    mapper=None,
    model: str = "claude-sonnet-4-6",
) -> dict:
    """
    Infer per-section metadata (description, rule) for each placeholder via LLM.

    Returns {placeholder_name: {"description": ..., "rule": ...}}.
    Uses mapper if provided, otherwise falls back to raw anthropic.
    """
    import json as _json
    import re as _re

    section_xml = Path(section_xml_path).read_text(encoding="utf-8")
    keys = list(dict.fromkeys(_re.compile(r"\{\{(.+?)\}\}").findall(section_xml)))
    if not keys:
        return {}

    keys_json = _json.dumps(keys, ensure_ascii=False)
    prompt_body = (
        f"다음은 HWPX 문서 템플릿의 플레이스홀더 목록입니다:\n{keys_json}\n\n"
        "각 플레이스홀더에 대해:\n"
        "- description: 어떤 내용을 넣어야 하는지 간단히 설명\n"
        "- rule: 형식 규칙이 있으면 기술, 없으면 빈 문자열 (예: 'YYYY년 MM월 DD일 형식')\n\n"
        "다른 텍스트 없이 아래 JSON 형식으로만 응답하세요:\n"
        '{"플레이스홀더명": {"description": "...", "rule": "..."}, ...}'
    )

    def _parse(raw: str) -> dict:
        try:
            start = raw.index("{")
            end = raw.rindex("}") + 1
            result = _json.loads(raw[start:end])
            return result if isinstance(result, dict) else {}
        except (ValueError, _json.JSONDecodeError):
            return {}

    if mapper is not None:
        from docpilot.mapping.base import TemplateSection
        mapping = mapper.map(
            content=prompt_body,
            sections=[TemplateSection(
                name="sections_meta",
                description=(
                    f"위 설명에 따라 플레이스홀더 목록 {keys_json}의 메타데이터를 "
                    "JSON 객체 문자열로 반환하세요."
                ),
            )],
        )
        return _parse(mapping.sections.get("sections_meta", "{}"))

    try:
        import anthropic
    except ImportError as e:
        raise ImportError("anthropic required: pip install anthropic") from e

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    ai = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    response = ai.messages.create(
        model=model,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt_body}],
    )
    return _parse(response.content[0].text.strip())


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
