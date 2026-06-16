from __future__ import annotations

import contextlib
import re
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from docpilot.exceptions import BuilderError

if TYPE_CHECKING:
    from docpilot.ingestion.models import IngestedDocument
    from docpilot.mapping.base import BaseLLMMapper

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_BASE_HEADER_XML = _TEMPLATES_DIR / "base" / "Contents" / "header.xml"

EmbedFn = Callable[[str], list[float]]

_PLACEHOLDER_RE = re.compile(r"\{\{(.+?)\}\}")


@dataclass
class TemplateCandidate:
    name: str
    description: str
    header_xml: Path
    section_xml: Path
    source: str  # "builtin" | "saved"
    sections_meta: dict = field(default_factory=dict)  # {name: {description, rule, ...}}
    extra_instructions: str | None = None


def build_auto(
    content: str | list[IngestedDocument],
    output: str | Path,
    instructions: str | None = None,
    header_xml: str | Path | None = None,
    embed_fn: EmbedFn | None = None,
    model: str = "claude-sonnet-4-6",
    mapper: BaseLLMMapper | None = None,
) -> Path:
    """
    Unified entry point for HWPX document generation.

    Automatically decides the build strategy based on available templates:
      1. header_xml given  → dynamic build with those styles (new section structure)
      2. instructions match built-in template → use it directly
      3. instructions match saved template (template_store) → reuse it
      4. multiple candidates → LLM picks the best fit
      5. no match → dynamic build with base styles

    Parameters
    ----------
    content      : plain text or list of IngestedDocuments
    output       : destination .hwpx path
    instructions : natural-language hint, e.g. "제주 학회 발표 보고서"
    header_xml   : force styles from this .xml or .hwpx file (skips template search)
    embed_fn     : optional embedding function for vector-based template search
    """
    from docpilot.mapping.base import merge_documents
    from docpilot.builder.hwpx_dynamic_builder import HwpxDynamicBuilder

    content_str = content if isinstance(content, str) else merge_documents(content)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    mapper = _resolve_mapper(mapper, model)

    with contextlib.ExitStack() as stack:
        # Case: explicit styles → always dynamic build (user wants new section structure)
        if header_xml is not None:
            h = Path(header_xml)
            if h.suffix.lower() == ".hwpx":
                tmp = Path(stack.enter_context(tempfile.TemporaryDirectory()))
                actual_h = extract_header_xml(h, tmp / "header.xml")
                merged = _infer_structure_hint(h, instructions, mapper)
            else:
                actual_h = h
                merged = instructions
            return HwpxDynamicBuilder(embed_fn=embed_fn, mapper=mapper).build(
                content_str, actual_h, output, merged
            )

        # No instructions → dynamic build with base styles
        if not instructions:
            return HwpxDynamicBuilder(embed_fn=embed_fn, mapper=mapper).build(
                content_str, _BASE_HEADER_XML, output, instructions
            )

        # Search for a matching template
        candidates = (
            _gather_builtin_candidates(instructions)
            + _gather_saved_candidates(instructions, embed_fn)
        )

        if not candidates:
            return HwpxDynamicBuilder(embed_fn=embed_fn, mapper=mapper).build(
                content_str, _BASE_HEADER_XML, output, instructions
            )

        if len(candidates) == 1:
            chosen = candidates[0]
        else:
            chosen = _llm_select(candidates, instructions, content_str, mapper)
            if chosen is None:
                return HwpxDynamicBuilder(embed_fn=embed_fn, mapper=mapper).build(
                    content_str, _BASE_HEADER_XML, output, instructions
                )

    return _build_with_template(content_str, chosen, output, instructions, mapper)


def extract_header_xml(hwpx_path: str | Path, dest: str | Path) -> Path:
    """Extract Contents/header.xml from a .hwpx ZIP into dest path."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(hwpx_path, "r") as zf:
        dest.write_bytes(zf.read("Contents/header.xml"))
    return dest


# ------------------------------------------------------------------
# Candidate gathering
# ------------------------------------------------------------------

def _gather_builtin_candidates(instructions: str) -> list[TemplateCandidate]:
    from docpilot.mapping.sidecar import load_sidecar

    instr_lower = instructions.lower()
    results: list[TemplateCandidate] = []

    for template_dir in sorted(_TEMPLATES_DIR.iterdir()):
        if not template_dir.is_dir() or template_dir.name == "base":
            continue
        header = template_dir / "header.xml"
        section = template_dir / "section0.xml"
        if not header.exists() or not section.exists():
            continue
        sidecar = load_sidecar(template_dir)
        if sidecar is None:
            continue
        if not any(kw in instr_lower for kw in sidecar.keywords):
            continue
        sections_meta = {
            s.name: {
                "description": s.description,
                "rule": s.rule,
                "style_hint": s.style_hint,
                "optional": s.optional,
                "is_list": s.is_list,
                "group_max": s.group_max,
            }
            for s in (sidecar.sections or [])
        }
        results.append(TemplateCandidate(
            name=sidecar.name or template_dir.name,
            description=sidecar.description or "",
            header_xml=header,
            section_xml=section,
            source="builtin",
            sections_meta=sections_meta,
            extra_instructions=sidecar.instructions,
        ))
    return results


def _gather_saved_candidates(instructions: str, embed_fn: EmbedFn | None) -> list[TemplateCandidate]:
    try:
        from docpilot.db import client as db_client, template_store
        db_client._get_engine()
    except Exception:
        return []

    try:
        records = template_store.search(instructions, embed_fn=embed_fn, top_k=5, fallback=False)
    except Exception:
        return []

    results: list[TemplateCandidate] = []
    for r in records:
        section_xml = Path(r.path)
        if not section_xml.exists():
            continue
        header = Path(r.header_xml) if r.header_xml else _BASE_HEADER_XML
        if not header.exists():
            continue
        meta = r.metadata_ or {}
        results.append(TemplateCandidate(
            name=r.name,
            description=r.description,
            header_xml=header,
            section_xml=section_xml,
            source="saved",
            sections_meta=meta.get("sections", {}),
            extra_instructions=meta.get("instructions"),
        ))
    return results


# ------------------------------------------------------------------
# LLM template selection
# ------------------------------------------------------------------

def _llm_select(
    candidates: list[TemplateCandidate],
    instructions: str,
    content_str: str,
    mapper: BaseLLMMapper,
) -> TemplateCandidate | None:
    lines = [f"{i}. [{c.source}] {c.name}: {c.description}"
             for i, c in enumerate(candidates, 1)]

    prompt = f"""사용자 요청: {instructions}

소스 데이터 요약 (앞 500자):
{content_str[:500]}

다음 문서 템플릿 후보 중 사용자 요청에 가장 적합한 것의 번호를 선택하세요.
어느 것도 맞지 않으면 0을 선택하세요.

{chr(10).join(lines)}

번호만 출력하세요 (0~{len(candidates)})."""

    try:
        raw = mapper.complete(prompt, max_tokens=8)
        choice = int(raw.strip())
    except Exception:
        return candidates[0]

    if choice < 1 or choice > len(candidates):
        return None
    return candidates[choice - 1]


# ------------------------------------------------------------------
# Build with an existing template
# ------------------------------------------------------------------

def _build_with_template(
    content_str: str,
    candidate: TemplateCandidate,
    output: Path,
    instructions: str | None,
    mapper: BaseLLMMapper,
) -> Path:
    from docpilot.mapping.base import TemplateSection
    from docpilot.builder.hwpx_builder import HwpxBuilder
    from docpilot.builder.hwpx_dynamic_builder import pack_hwpx

    from docpilot.mapping.sidecar import sections_meta_to_list

    section_xml_text = candidate.section_xml.read_text(encoding="utf-8")
    placeholder_names = list(dict.fromkeys(_PLACEHOLDER_RE.findall(section_xml_text)))
    if not placeholder_names:
        raise BuilderError(
            "No placeholders found in template",
            detail=str(candidate.section_xml),
        )

    sections = sections_meta_to_list(placeholder_names, candidate.sections_meta)

    merged_instructions = _merge_instructions(instructions, candidate.extra_instructions)
    mapping = mapper.map(content_str, sections, merged_instructions)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_hwpx = Path(tmp) / "_template.hwpx"
        pack_hwpx(candidate.header_xml, section_xml_text, tmp_hwpx)
        HwpxBuilder().build(tmp_hwpx, mapping.sections, output)

    return output


def _merge_instructions(user: str | None, template: str | None) -> str | None:
    parts = [s for s in (template, user) if s and s.strip()]
    return "\n".join(parts) if parts else None


def _infer_structure_hint(hwpx_path: Path, instructions: str | None, mapper: BaseLLMMapper) -> str | None:
    """
    Extract section structure from a reference .hwpx document via LLM and merge
    with any user-provided instructions.

    Uses _infer_sections_from_content() (Reference Mode) to analyse the existing
    document, then passes the inferred section names as a structural hint to
    generate_structure() so the new template mirrors the reference layout.
    """
    try:
        from docpilot.ingestion import hwpx as hwpx_ing
        from docpilot import _infer_sections_from_content

        doc = hwpx_ing.ingest(hwpx_path)
        if not doc.content.strip():
            return instructions

        section_names = _infer_sections_from_content(doc.content, mapper)
        if not section_names:
            return instructions

        hint = f"참조 양식의 섹션 구조를 따르세요: {', '.join(section_names)}"
        return f"{instructions}\n{hint}" if instructions else hint
    except Exception:
        return instructions


def _resolve_mapper(mapper: BaseLLMMapper | None, model: str) -> BaseLLMMapper:
    if mapper is not None:
        return mapper
    from docpilot.mapping.claude import ClaudeMapper
    return ClaudeMapper(model=model)
