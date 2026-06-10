from __future__ import annotations

import copy
import re
import shutil
import tempfile
import zipfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from docpilot.exceptions import BuilderError

if TYPE_CHECKING:
    from docpilot.builder.hwpx_section_generator import SectionItem, SectionStructure
    from docpilot.builder.hwpx_style_extractor import StyleCatalog
    from docpilot.ingestion.models import IngestedDocument

_BASE_TEMPLATE = Path(__file__).parent.parent / "templates" / "base"

EmbedFn = Callable[[str], list[float]]


class HwpxDynamicBuilder:
    """
    Generates HWPX documents from content without a pre-made template.

    Flow (per build call):
      1. Extract charPr/paraPr style catalog from header.xml
      2. LLM decides document structure → list of SectionItems with {{placeholders}}
      3. Build section0.xml and save it (to save_template or auto path in templates_dir)
      4. Index the saved template in template_store for future natural-language search
      5. Pack temporary HWPX, then LLM fills placeholder content, write final output

    Reuse:
      Every dynamically built document automatically saves and indexes its section0.xml.
      On subsequent runs the saved section0.xml can be used directly with HwpxBuilder.
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        templates_dir: str | Path | None = None,
        embed_fn: EmbedFn | None = None,
    ) -> None:
        self.model = model
        self.templates_dir = Path(templates_dir) if templates_dir else Path.home() / "docpilot_templates"
        self.embed_fn = embed_fn

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(
        self,
        content: str | list[IngestedDocument],
        header_xml: str | Path,
        output: str | Path,
        instructions: str | None = None,
        save_template: str | Path | None = None,
    ) -> Path:
        """
        Generate a new HWPX document from content.

        content        : plain text or list of IngestedDocuments
        header_xml     : path to header.xml that defines fonts/styles
        output         : destination .hwpx path
        instructions   : optional natural-language hint ("제주 학회 발표 보고서")
        save_template  : if given, save section0.xml here for later reuse
        """
        from docpilot.builder.hwpx_style_extractor import extract as extract_styles
        from docpilot.builder.hwpx_section_generator import generate_structure
        from docpilot.builder.hwpx_builder import HwpxBuilder
        from docpilot.mapping.base import TemplateSection, merge_documents
        from docpilot.mapping.claude import ClaudeMapper

        header_xml = Path(header_xml)
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)

        if not header_xml.exists():
            raise BuilderError("header.xml을 찾을 수 없습니다", detail=str(header_xml))

        content_str = content if isinstance(content, str) else merge_documents(content)

        # Step 1: style catalog
        catalog = extract_styles(header_xml)

        # Step 2: LLM → document structure
        structure = generate_structure(content_str, catalog, instructions, model=self.model)

        # Step 3: build section0.xml with {{placeholders}}
        section_xml = _build_section_xml(structure.items, catalog)

        # Step 4: save template (explicit path or auto-generated) and index for search
        dest = Path(save_template) if save_template is not None else _auto_template_path(
            self.templates_dir, structure
        )
        _save_section_template(dest, section_xml)
        _try_index_template(dest, header_xml, structure, instructions, self.embed_fn)

        # Step 5: pack into temp HWPX, fill content, write output
        with tempfile.TemporaryDirectory() as tmp:
            tmp_hwpx = Path(tmp) / "_dynamic.hwpx"
            _pack_hwpx(header_xml, section_xml, tmp_hwpx)

            sections_list = [
                TemplateSection(name=item.key, description=item.desc)
                for item in structure.items
                if item.key and item.type != "empty"
            ]

            mapper = ClaudeMapper(model=self.model)
            mapping = mapper.map(content_str, sections_list, instructions)

            HwpxBuilder().build(tmp_hwpx, mapping.sections, output)

        return output

    def build_template_only(
        self,
        content: str | list[IngestedDocument],
        header_xml: str | Path,
        save_template: str | Path,
        instructions: str | None = None,
    ) -> Path:
        """
        Only generate and save section0.xml — no content filling, no HWPX output.
        Useful for pre-creating reusable templates before data is available.
        """
        from docpilot.builder.hwpx_style_extractor import extract as extract_styles
        from docpilot.builder.hwpx_section_generator import generate_structure
        from docpilot.mapping.base import merge_documents

        header_xml = Path(header_xml)
        content_str = content if isinstance(content, str) else merge_documents(content)

        catalog = extract_styles(header_xml)
        structure = generate_structure(content_str, catalog, instructions, model=self.model)
        section_xml = _build_section_xml(structure.items, catalog)

        dest = Path(save_template)
        _save_section_template(dest, section_xml)
        _try_index_template(dest, header_xml, structure, instructions, self.embed_fn)
        return dest


# ------------------------------------------------------------------
# XML assembly (no LLM involved — deterministic)
# ------------------------------------------------------------------

def _build_section_xml(items: list[SectionItem], catalog: StyleCatalog) -> str:
    try:
        from lxml import etree
    except ImportError as e:
        raise BuilderError("lxml required: pip install lxml") from e

    base_section = _BASE_TEMPLATE / "Contents" / "section0.xml"
    if not base_section.exists():
        raise BuilderError("base section0.xml not found", detail=str(base_section))

    base_tree = etree.parse(str(base_section))
    base_root = base_tree.getroot()
    nsmap = base_root.nsmap

    hp_ns = nsmap.get("hp", "http://www.hancom.co.kr/hwpml/2011/paragraph")
    hs_ns = nsmap.get("hs", "http://www.hancom.co.kr/hwpml/2011/section")

    hp = f"{{{hp_ns}}}"
    hs = f"{{{hs_ns}}}"

    new_root = etree.Element(f"{hs}sec", nsmap=nsmap)

    # First paragraph: secPr + colPr (always copied verbatim from base)
    first_p = base_root.find(f"{hp}p")
    if first_p is None:
        raise BuilderError("secPr paragraph missing from base section0.xml")
    new_root.append(copy.deepcopy(first_p))

    # Map item type → charPrIDRef / paraPrIDRef
    type_char = {
        "title":   catalog.title_char_id(),
        "subtitle": catalog.heading_char_id(),
        "date":    catalog.body_char_id(),
        "author":  catalog.body_char_id(),
        "heading": catalog.heading_char_id(),
        "body":    catalog.body_char_id(),
        "table":   catalog.body_char_id(),
        "empty":   catalog.body_char_id(),
    }
    type_para = {
        "title":   catalog.center_para_id(),
        "subtitle": catalog.center_para_id(),
        "date":    catalog.center_para_id(),
        "author":  catalog.center_para_id(),
        "heading": catalog.justify_para_id(),
        "body":    catalog.justify_para_id(),
        "table":   catalog.justify_para_id(),
        "empty":   catalog.justify_para_id(),
    }

    # Build charPr height lookup for lineseg calculation
    height_map = {c.id: int(c.pt * 100) for c in catalog.char_styles}

    base_id = 2_000_000_001
    for i, item in enumerate(items):
        char_id = type_char.get(item.type, catalog.body_char_id())
        para_id = type_para.get(item.type, catalog.justify_para_id())
        text = f"{{{{{item.key}}}}}" if item.key else ""
        height = height_map.get(char_id, 1000)

        p = etree.SubElement(new_root, f"{hp}p", {
            "id": str(base_id + i),
            "paraPrIDRef": str(para_id),
            "styleIDRef": "0",
            "pageBreak": "0",
            "columnBreak": "0",
            "merged": "0",
        })
        run = etree.SubElement(p, f"{hp}run", {"charPrIDRef": str(char_id)})
        t = etree.SubElement(run, f"{hp}t")
        t.text = text

        lsa = etree.SubElement(p, f"{hp}linesegarray")
        etree.SubElement(lsa, f"{hp}lineseg", {
            "textpos": "0", "vertpos": "0",
            "vertsize": str(height), "textheight": str(height),
            "baseline": str(int(height * 0.85)),
            "spacing": str(int(height * 0.6)),
            "horzpos": "0", "horzsize": "42520", "flags": "393216",
        })

    xml_bytes = etree.tostring(
        new_root,
        xml_declaration=True,
        encoding="UTF-8",
        pretty_print=True,
    )
    return xml_bytes.decode("utf-8")


# ------------------------------------------------------------------
# HWPX packaging helpers
# ------------------------------------------------------------------

def _pack_hwpx(header_xml: Path, section_xml: str, output: Path) -> None:
    """Assemble base template + header.xml + section_xml into a .hwpx zip."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp) / "hwpx"
        shutil.copytree(_BASE_TEMPLATE, tmp_path)

        shutil.copy2(header_xml, tmp_path / "Contents" / "header.xml")
        (tmp_path / "Contents" / "section0.xml").write_text(section_xml, encoding="utf-8")

        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
            mimetype = tmp_path / "mimetype"
            if mimetype.exists():
                zf.write(mimetype, "mimetype", compress_type=zipfile.ZIP_STORED)
            for f in sorted(tmp_path.rglob("*")):
                if f.is_file() and f.name != "mimetype":
                    zf.write(f, f.relative_to(tmp_path))


def _save_section_template(dest: Path, section_xml: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(section_xml, encoding="utf-8")


# ------------------------------------------------------------------
# Template auto-save helpers
# ------------------------------------------------------------------

def _auto_template_path(templates_dir: Path, structure: SectionStructure) -> Path:
    title_item = next((i for i in structure.items if i.type == "title" and i.key), None)
    slug = re.sub(r"[^\w가-힣]", "_", title_item.key if title_item else "template")[:30]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return templates_dir / f"{ts}_{slug}.xml"


def _template_name(structure: SectionStructure, instructions: str | None) -> str:
    if instructions:
        return instructions.strip()[:80]
    title_item = next((i for i in structure.items if i.type == "title" and i.key), None)
    return title_item.key if title_item else "문서 템플릿"


def _template_description(structure: SectionStructure, instructions: str | None) -> str:
    heading_keys = [i.key for i in structure.items if i.type == "heading" and i.key]
    body_count = sum(1 for i in structure.items if i.type == "body")
    parts: list[str] = []
    if instructions:
        parts.append(instructions.strip())
    if heading_keys:
        parts.append(f"섹션: {', '.join(heading_keys[:6])}")
    parts.append(f"본문 단락 {body_count}개")
    return ". ".join(parts)


def _template_tags(structure: SectionStructure, instructions: str | None) -> list[str] | None:
    tags: list[str] = []
    if instructions:
        tags.extend(w for w in instructions.split() if len(w) > 1)
    title_item = next((i for i in structure.items if i.type == "title" and i.key), None)
    if title_item:
        tags.append(title_item.key[:20])
    return tags[:8] if tags else None


def _try_index_template(
    dest: Path,
    header_xml: Path,
    structure: SectionStructure,
    instructions: str | None,
    embed_fn: EmbedFn | None,
) -> None:
    try:
        from docpilot.db import client as db_client, template_store
        try:
            db_client._get_engine()
        except Exception:
            db_client.init()
            db_client.create_tables()
        template_store.save(
            name=_template_name(structure, instructions),
            path=str(dest),
            header_xml=str(header_xml),
            description=_template_description(structure, instructions),
            tags=_template_tags(structure, instructions),
            embed_fn=embed_fn,
        )
    except Exception as exc:
        import sys
        print(f"[docpilot] template indexing skipped: {exc}", file=sys.stderr)
