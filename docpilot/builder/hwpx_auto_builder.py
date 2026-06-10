from __future__ import annotations

import contextlib
import os
import re
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from docpilot.exceptions import BuilderError

if TYPE_CHECKING:
    from docpilot.ingestion.models import IngestedDocument

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_BASE_HEADER_XML = _TEMPLATES_DIR / "base" / "Contents" / "header.xml"

EmbedFn = Callable[[str], list[float]]

# Built-in templates bundled with the package
BUILTIN_TEMPLATES: dict[str, dict] = {
    "report": {
        "name": "업무/결과 보고서",
        "description": "제목·일자·작성자·배경 및 목적·주요내용·결론으로 구성된 표준 업무 보고서",
        "keywords": ["보고서", "보고", "결과보고", "업무보고", "현황", "사업보고"],
    },
    "gonmun": {
        "name": "공문",
        "description": "수신·참조·제목·본문·붙임으로 구성된 행정 공문",
        "keywords": ["공문", "행정문서", "협조요청", "통보", "공지"],
    },
    "minutes": {
        "name": "회의록",
        "description": "회의명·일시·장소·참석자·안건·논의내용·결정사항으로 구성된 회의 기록",
        "keywords": ["회의록", "회의", "미팅", "회의결과", "논의"],
    },
    "proposal": {
        "name": "제안서/기획서",
        "description": "개요·목적·추진배경·추진내용·기대효과·예산으로 구성된 제안 또는 기획 문서",
        "keywords": ["제안서", "기획서", "제안", "제안요구서", "rfp", "기획", "계획서"],
    },
}

_PLACEHOLDER_RE = re.compile(r"\{\{(.+?)\}\}")


@dataclass
class TemplateCandidate:
    name: str
    description: str
    header_xml: Path
    section_xml: Path
    source: str  # "builtin" | "saved"


def build_auto(
    content: str | list[IngestedDocument],
    output: str | Path,
    instructions: str | None = None,
    header_xml: str | Path | None = None,
    embed_fn: EmbedFn | None = None,
    model: str = "claude-sonnet-4-6",
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

    with contextlib.ExitStack() as stack:
        # Case: explicit styles → always dynamic build (user wants new section structure)
        if header_xml is not None:
            h = Path(header_xml)
            if h.suffix.lower() == ".hwpx":
                tmp = Path(stack.enter_context(tempfile.TemporaryDirectory()))
                actual_h = extract_header_xml(h, tmp / "header.xml")
            else:
                actual_h = h
            return HwpxDynamicBuilder(model=model, embed_fn=embed_fn).build(
                content_str, actual_h, output, instructions
            )

        # No instructions → dynamic build with base styles
        if not instructions:
            return HwpxDynamicBuilder(model=model, embed_fn=embed_fn).build(
                content_str, _BASE_HEADER_XML, output, instructions
            )

        # Search for a matching template
        candidates = (
            _gather_builtin_candidates(instructions)
            + _gather_saved_candidates(instructions, embed_fn)
        )

        if not candidates:
            return HwpxDynamicBuilder(model=model, embed_fn=embed_fn).build(
                content_str, _BASE_HEADER_XML, output, instructions
            )

        if len(candidates) == 1:
            chosen = candidates[0]
        else:
            chosen = _llm_select(candidates, instructions, content_str, model)
            if chosen is None:
                return HwpxDynamicBuilder(model=model, embed_fn=embed_fn).build(
                    content_str, _BASE_HEADER_XML, output, instructions
                )

    return _build_with_template(content_str, chosen, output, instructions, model)


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
    instr_lower = instructions.lower()
    results: list[TemplateCandidate] = []
    for key, info in BUILTIN_TEMPLATES.items():
        if not any(kw in instr_lower for kw in info["keywords"]):
            continue
        header = _TEMPLATES_DIR / key / "header.xml"
        section = _TEMPLATES_DIR / key / "section0.xml"
        if header.exists() and section.exists():
            results.append(TemplateCandidate(
                name=info["name"],
                description=info["description"],
                header_xml=header,
                section_xml=section,
                source="builtin",
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
        results.append(TemplateCandidate(
            name=r.name,
            description=r.description,
            header_xml=header,
            section_xml=section_xml,
            source="saved",
        ))
    return results


# ------------------------------------------------------------------
# LLM template selection
# ------------------------------------------------------------------

def _llm_select(
    candidates: list[TemplateCandidate],
    instructions: str,
    content_str: str,
    model: str,
) -> TemplateCandidate | None:
    try:
        import anthropic
    except ImportError:
        return candidates[0]  # no LLM available → take first

    lines = [f"{i}. [{c.source}] {c.name}: {c.description}"
             for i, c in enumerate(candidates, 1)]

    prompt = f"""사용자 요청: {instructions}

소스 데이터 요약 (앞 500자):
{content_str[:500]}

다음 문서 템플릿 후보 중 사용자 요청에 가장 적합한 것의 번호를 선택하세요.
어느 것도 맞지 않으면 0을 선택하세요.

{chr(10).join(lines)}

번호만 출력하세요 (0~{len(candidates)})."""

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    ai = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    try:
        response = ai.messages.create(
            model=model,
            max_tokens=8,
            messages=[{"role": "user", "content": prompt}],
        )
        choice = int(response.content[0].text.strip())
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
    model: str,
) -> Path:
    from docpilot.mapping.base import TemplateSection
    from docpilot.mapping.claude import ClaudeMapper
    from docpilot.builder.hwpx_builder import HwpxBuilder
    from docpilot.builder.hwpx_dynamic_builder import _pack_hwpx

    section_xml_text = candidate.section_xml.read_text(encoding="utf-8")
    sections = _extract_placeholders(section_xml_text)
    if not sections:
        raise BuilderError(
            "No placeholders found in template",
            detail=str(candidate.section_xml),
        )

    mapper = ClaudeMapper(model=model)
    mapping = mapper.map(content_str, sections, instructions)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_hwpx = Path(tmp) / "_template.hwpx"
        _pack_hwpx(candidate.header_xml, section_xml_text, tmp_hwpx)
        HwpxBuilder().build(tmp_hwpx, mapping.sections, output)

    return output


def _extract_placeholders(section_xml: str) -> list:
    from docpilot.mapping.base import TemplateSection
    seen: set[str] = set()
    result = []
    for key in _PLACEHOLDER_RE.findall(section_xml):
        if key not in seen:
            seen.add(key)
            result.append(TemplateSection(name=key))
    return result
