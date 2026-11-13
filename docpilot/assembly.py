"""LLM 호출 없이 템플릿을 조회하고 채우는 함수들 — MCP 도구와 외부 에이전트가 사용한다."""
from __future__ import annotations

import os
import zipfile
from dataclasses import dataclass
from pathlib import Path

from docpilot.exceptions import BuilderError, DocPilotError, MappingError
from docpilot.placeholders import _extract_placeholders
from docpilot.template_resolver import _resolve_sections, _resolve_template_path


def _validate_hwpx(path: Path) -> None:
    """생성된 HWPX 파일의 구조 무결성을 비차단 방식으로 검사한다."""
    import logging
    import warnings

    _REQUIRED = [
        "mimetype",
        "Contents/content.hpf",
        "Contents/header.xml",
    ]

    try:
        with zipfile.ZipFile(path, "r") as zf:
            names = zf.namelist()
            missing = [f for f in _REQUIRED if f not in names]
            if missing:
                warnings.warn(
                    f"HWPX 검증 경고 — 필수 파일 누락: {', '.join(missing)}",
                    stacklevel=4,
                )

            try:
                from lxml import etree
                for name in names:
                    if name.endswith(".xml") or name.endswith(".hpf"):
                        try:
                            etree.fromstring(zf.read(name))
                        except Exception as xml_err:
                            warnings.warn(
                                f"HWPX 검증 경고 — XML 오류 in {name}: {xml_err}",
                                stacklevel=4,
                            )
            except ImportError:
                pass
    except Exception as exc:
        logging.getLogger(__name__).debug("HWPX 검증 실패 (무시됨): %s", exc)


def _resolve_builder(output: Path):
    from docpilot.builder import HwpxBuilder, PdfBuilder, DocxBuilder

    match output.suffix.lower():
        case ".hwpx":
            return HwpxBuilder()
        case ".pdf":
            return PdfBuilder()
        case ".docx":
            return DocxBuilder()
        case _:
            raise BuilderError(
                f"Unsupported output format '{output.suffix}'",
                detail="Supported: .hwpx, .pdf, .docx",
            )


def describe_template(template: str | Path) -> dict:
    """
    Return a template's fillable structure — no LLM/RAG call.

    Use this before fill_template() to see exact section keys, per-section rules/
    descriptions, and a ready-to-copy example dict shape.
    """
    template_path, db_sections_meta = _resolve_template_path(template)
    template_path, sections, instructions = _resolve_sections(template, template_path, db_sections_meta)

    example: dict[str, str | list[str]] = {}
    for s in sections:
        if s.is_list:
            example[s.name] = ["항목1", "항목2"]
        elif s.optional:
            example[s.name] = ""
        else:
            example[s.name] = "..."

    return {
        "template": str(template_path),
        "instructions": instructions,
        "sections": [
            {
                "name": s.name,
                "description": s.description,
                "rule": s.rule,
                "style_hint": s.style_hint,
                "optional": s.optional,
                "is_list": s.is_list,
                "group_max": s.group_max,
            }
            for s in sections
        ],
        "example": example,
    }


def fill_template(
    template: str | Path,
    sections: dict[str, str | list[str]],
    output: str | Path,
) -> Path:
    """
    Fill an already-authored section dict into a template — pure mechanical build,
    no LLM/RAG call. Validates keys against the template's actual placeholders first,
    and warns if any placeholder is left unfilled in the output.
    """
    template_path, db_sections_meta = _resolve_template_path(template)
    template_path, resolved, _ = _resolve_sections(template, template_path, db_sections_meta)
    resolved_names = {s.name for s in resolved}

    required_missing = [
        s.name for s in resolved
        if not s.optional and not s.is_list and not str(sections.get(s.name, "")).strip()
    ]
    unknown_keys = [k for k in sections if k not in resolved_names]
    if required_missing or unknown_keys:
        detail_lines = []
        if required_missing:
            detail_lines.append(f"누락된 필수 섹션: {', '.join(required_missing)}")
        if unknown_keys:
            detail_lines.append(f"템플릿에 없는 키 (오탈자 의심): {', '.join(unknown_keys)}")
        raise MappingError(
            "fill_template 입력 검증 실패 — describe_template()으로 정확한 섹션 키를 확인하세요.",
            detail="\n".join(detail_lines),
        )

    fill: dict[str, str | list[str]] = {}
    for s in resolved:
        val = sections.get(s.name, [] if s.is_list else "")
        if s.is_list and isinstance(val, str):
            val = [v.strip() for v in val.split("\n") if v.strip()]
        fill[s.name] = val

    output_path = Path(output)
    builder = _resolve_builder(output_path)
    out_path = builder.build(template_path, fill, output_path)

    if out_path.suffix.lower() == ".hwpx":
        _validate_hwpx(out_path)

    leftover = _extract_placeholders(out_path)
    if leftover:
        import warnings
        warnings.warn(
            f"생성된 문서에 채워지지 않은 플레이스홀더가 남아 있습니다: {', '.join(leftover)}",
            stacklevel=2,
        )

    return out_path


@dataclass
class RetrievedContext:
    template: str
    instructions: str
    sections: list
    context: str


def retrieve_context(
    data_folder: str | Path,
    template: str | Path,
    reindex: bool = False,
    top_k: int = 10,
    collection: str | None = None,
    embed_fn=None,
    database_url: str | None = None,
) -> RetrievedContext:
    """
    Index data_folder and retrieve relevant context for a template's sections — no LLM call.

    Use this when the caller (e.g. an MCP client) wants to author the section content itself:
    call this first to get the retrieved context text and section definitions, write the
    sections using that context, then call fill_template() to assemble the document.

    collection:  optional tag applied when indexing data_folder — see DocPilot.generate().
    embed_fn:    defaults to the same local embedding model DocPilot() uses when omitted.
                 Pass the same embed_fn used elsewhere against this DB, or vector search may
                 silently disagree with previously indexed embeddings (see DocPilot docstring).
    database_url: defaults to DOCPILOT_DATABASE_URL / ~/docpilot.db, same as DocPilot().
    """
    template_path, db_sections_meta = _resolve_template_path(template)
    template_path, sections, instructions = _resolve_sections(template, template_path, db_sections_meta)

    if embed_fn is None:
        from docpilot.search.embedding import default_embed_fn
        embed_fn = default_embed_fn()

    from docpilot.db import client as db_client
    from docpilot.search.embedding import embedding_dim
    db_client.init(database_url)
    db_client.create_tables(embedding_dim=embedding_dim(embed_fn))

    from docpilot.db import indexer
    doc_ids = indexer.index_folder(
        data_folder, embed_fn=embed_fn, force=reindex, collection=collection
    )
    if not doc_ids:
        raise DocPilotError(
            "데이터 폴더에서 인덱싱된 문서가 없습니다.",
            detail=(
                f"{data_folder} 에서 지원하는 파일을 찾지 못했거나 "
                "모든 파일의 수집(ingestion)에 실패했습니다. "
                "지원 형식: .txt .md .csv .hwpx .hwp .docx .pdf"
            ),
        )

    from docpilot.search.models import SearchFilter
    if collection is not None:
        filters = SearchFilter(collection=collection)
    else:
        filters = SearchFilter(source_pattern=f"{Path(data_folder).resolve()}{os.sep}*")

    from docpilot.mapping.rag import retrieve as rag_retrieve
    context = rag_retrieve(sections, embed_fn=embed_fn, top_k=top_k, filters=filters)

    return RetrievedContext(
        template=str(template_path),
        instructions=instructions,
        sections=sections,
        context=context,
    )


def extract_placeholders(template: str | Path) -> list[str]:
    """템플릿의 {{placeholder}} 키 목록 — 등장 순서, 중복 제거, LLM 호출 없음.

    template: 파일 경로(.hwpx/.docx/.pdf) 또는 내장/DB 템플릿 이름.
    {{?key}} 같은 선택·목록 표기를 벗긴 원래 키 이름을 그대로 돌려준다. 목록 묶음(단어1, 단어2 → 단어)과
    섹션별 규칙·설명까지 반영된 정의가 필요하면 describe_template()을 쓴다.
    """
    template_path, _ = _resolve_template_path(template)
    return _extract_placeholders(template_path)
