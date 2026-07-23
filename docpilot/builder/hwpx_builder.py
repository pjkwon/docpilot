from __future__ import annotations

import copy
import tempfile
import zipfile
from pathlib import Path

from docpilot.builder.base import BaseBuilder, PLACEHOLDER_RE
from docpilot.builder.html_blocks import (
    HtmlListBlock,
    HtmlTableBlock,
    MarkdownTableBlock,
    PlainTextBlock,
    flatten_list,
    segment_blocks,
)
from docpilot.builder.html_table import build_hwpx_table_from_cells, build_markdown_table, parse_html_table
from docpilot.builder.hwpx_bullets import ensure_bullet, ensure_bullet_para_pr, get_or_create_bullets_container
from docpilot.exceptions import BuilderError

# Candidate content file paths inside the HWPX ZIP (tried in order)
_CONTENT_CANDIDATES = ["Contents/content.hml", "Contents/section0.xml"]


class HwpxBuilder(BaseBuilder):
    def build(
        self,
        template: str | Path,
        sections: dict[str, str | list[str]],
        output: str | Path,
    ) -> Path:
        template, output = self._validate_paths(template, output)

        if template.suffix.lower() != ".hwpx":
            raise BuilderError(f"Expected .hwpx template, got '{template.suffix}'")

        try:
            from lxml import etree
        except ImportError as e:
            raise BuilderError("lxml is required: pip install lxml") from e

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _unpack(template, tmp_path)

            content_files = []
            contents_dir = tmp_path / "Contents"
            if contents_dir.exists():
                for f in sorted(contents_dir.glob("section*.xml")):
                    content_files.append(f)
                for f in sorted(contents_dir.glob("content.hml")):
                    content_files.append(f)
            
            if not content_files:
                raise BuilderError(
                    "No content files found in HWPX (section*.xml or content.hml)",
                    detail=str(template),
                )
            
            header_file = tmp_path / "Contents" / "header.xml"
            header_tree = etree.parse(str(header_file)) if header_file.exists() else None
            header_root = header_tree.getroot() if header_tree is not None else None

            header_dirty = False
            for content_file in content_files:
                tree = etree.parse(str(content_file))
                root = tree.getroot()
                
                dirty = _replace_placeholders(root, sections, header_root=header_root)
                if dirty:
                    header_dirty = True
                
                tree.write(
                    str(content_file),
                    xml_declaration=True,
                    encoding="UTF-8",
                    pretty_print=False,
                )

            if header_dirty and header_tree is not None:
                header_tree.write(
                    str(header_file),
                    xml_declaration=True,
                    encoding="UTF-8",
                    pretty_print=False,
                )

            _pack(tmp_path, output)

        return output


def _unpack(hwpx: Path, dest: Path) -> None:
    try:
        with zipfile.ZipFile(hwpx, "r") as zf:
            zf.extractall(dest)
    except zipfile.BadZipFile as e:
        raise BuilderError("Invalid HWPX file (not a ZIP)", detail=str(e)) from e


def _pack(src: Path, output: Path) -> None:
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        # mimetype must be first and uncompressed per OPC spec
        mimetype = src / "mimetype"
        if mimetype.exists():
            zf.write(mimetype, "mimetype", compress_type=zipfile.ZIP_STORED)

        for file in sorted(src.rglob("*")):
            if not file.is_file():
                continue
            if file.name == "mimetype":
                continue
            zf.write(file, file.relative_to(src))


def _read_horz_size(root, hp_ns: str, default: int = 42520) -> int:
    hp = f"{{{hp_ns}}}"
    for ls in root.iter(f"{hp}lineseg"):
        val = ls.get("horzsize")
        if val:
            return int(val)
    return default


def _clear_lineseg(para, hp_linesegarray: str, hp_lineseg: str) -> None:
    """lineseg 자식을 제거해 HWP가 열 때 레이아웃을 재계산하도록 한다."""
    lsa = para.find(hp_linesegarray)
    if lsa is None:
        return
    for ls in list(lsa.findall(hp_lineseg)):
        lsa.remove(ls)


def _make_text_para(template_para, text: str, hp_t: str, hp_linesegarray: str, hp_lineseg: str,
                     new_id: int, para_pr_id: int | None = None):
    new_p = copy.deepcopy(template_para)
    new_p.set("id", str(new_id))
    if para_pr_id is not None:
        new_p.set("paraPrIDRef", str(para_pr_id))
    t_elements = new_p.findall(f".//{hp_t}")
    if t_elements:
        t_elements[0].text = text
        for el in t_elements[1:]:
            el.text = ""
    _clear_lineseg(new_p, hp_linesegarray, hp_lineseg)
    return new_p


def _make_table_para(template_para, tbl_elem, hp_t: str, hp_linesegarray: str, hp_lineseg: str, new_id: int):
    from lxml import etree

    new_p = copy.deepcopy(template_para)
    new_p.set("id", str(new_id))
    t_elements = new_p.findall(f".//{hp_t}")
    run = t_elements[0].getparent() if t_elements else None
    if run is not None:
        # Clear text from all t elements but keep one empty <hp:t/>
        # (HWP requires <hp:t/> sibling after <hp:tbl> in the same run)
        for t_el in t_elements[1:]:
            run.remove(t_el)
        t_elements[0].text = None
        run.insert(0, tbl_elem)
    lsa = new_p.find(hp_linesegarray)
    if lsa is not None:
        for ls in list(lsa.findall(hp_lineseg)):
            lsa.remove(ls)
        etree.SubElement(lsa, hp_lineseg, {
            "textpos": "0", "vertpos": "0",
            "vertsize": "1000", "textheight": "1000",
            "baseline": "850", "spacing": "600",
            "horzpos": "0", "horzsize": "0", "flags": "393216",
        })
    return new_p


def _replace_placeholders(root, sections: dict[str, str | list[str]], header_root=None) -> bool:
    # Detect hp namespace from document root (supports both 2011 and 2012 variants)
    hp_ns = root.nsmap.get("hp", "http://www.hancom.co.kr/hwpml/2012/paragraph")
    hp_t = f"{{{hp_ns}}}t"
    hp_p = f"{{{hp_ns}}}p"
    hp_linesegarray = f"{{{hp_ns}}}linesegarray"
    hp_lineseg = f"{{{hp_ns}}}lineseg"

    horz_size = _read_horz_size(root, hp_ns)

    # Collect all existing IDs so generated IDs never collide
    existing_ids = {int(el.get("id", 0)) for el in root.iter(hp_p) if el.get("id")}
    next_id = max(existing_ids, default=2_000_000_000) + 1

    header_dirty = False
    bullets_el = None
    bullet_id_cache: dict[str, int] = {}
    para_pr_id_cache: dict[tuple[int, int], int] = {}

    for para in list(root.iter(hp_p)):
        t_elements = para.findall(f".//{hp_t}")
        if not t_elements:
            continue

        full_text = "".join((el.text or "") for el in t_elements)
        match = PLACEHOLDER_RE.search(full_text)
        if not match:
            continue

        key = match.group(1)
        if key not in sections:
            continue

        val = sections[key]
        fill = "\n".join(val) if isinstance(val, list) else val
        replaced = PLACEHOLDER_RE.sub(fill, full_text, count=1)

        blocks = segment_blocks(replaced)
        has_structure = any(not isinstance(b, PlainTextBlock) for b in blocks)

        if not has_structure:
            # No HTML table/list or markdown table found — exact legacy
            # single-line / multiline behavior, unchanged.
            lines = replaced.split("\n")

            if len(lines) == 1:
                t_elements[0].text = lines[0]
                for el in t_elements[1:]:
                    el.text = ""
                _clear_lineseg(para, hp_linesegarray, hp_lineseg)
                continue

            parent = para.getparent()
            if parent is None:
                t_elements[0].text = " ".join(lines)
                for el in t_elements[1:]:
                    el.text = ""
                _clear_lineseg(para, hp_linesegarray, hp_lineseg)
                continue

            idx = list(parent).index(para)
            new_paras = []
            for line in lines:
                new_paras.append(_make_text_para(para, line, hp_t, hp_linesegarray, hp_lineseg, next_id))
                next_id += 1
            parent.remove(para)
            for j, new_p in enumerate(new_paras):
                parent.insert(idx + j, new_p)
            continue

        # Heterogeneous block sequence (HTML table(s)/list(s) mixed with text)
        parent = para.getparent()
        if parent is None:
            flat_lines: list[str] = []
            for block in blocks:
                if isinstance(block, PlainTextBlock):
                    flat_lines.extend(block.lines)
            t_elements[0].text = " ".join(flat_lines)
            for el in t_elements[1:]:
                el.text = ""
            _clear_lineseg(para, hp_linesegarray, hp_lineseg)
            continue

        idx = list(parent).index(para)
        new_elements = []

        for block in blocks:
            if isinstance(block, PlainTextBlock):
                for line in block.lines:
                    new_elements.append(_make_text_para(para, line, hp_t, hp_linesegarray, hp_lineseg, next_id))
                    next_id += 1

            elif isinstance(block, MarkdownTableBlock):
                if block.rows:
                    tbl_elem, next_id = build_markdown_table(block.rows, hp_ns, horz_size, next_id)
                    new_elements.append(_make_table_para(para, tbl_elem, hp_t, hp_linesegarray, hp_lineseg, next_id))
                    next_id += 1

            elif isinstance(block, HtmlTableBlock):
                cells, n_rows, n_cols = parse_html_table(block.table_el)
                if cells:
                    tbl_elem, next_id = build_hwpx_table_from_cells(cells, n_rows, n_cols, hp_ns, horz_size, next_id)
                    new_elements.append(_make_table_para(para, tbl_elem, hp_t, hp_linesegarray, hp_lineseg, next_id))
                    next_id += 1

            elif isinstance(block, HtmlListBlock):
                for text, depth, glyph in flatten_list(block.list_el):
                    if header_root is not None:
                        if bullets_el is None:
                            bullets_el = get_or_create_bullets_container(header_root)
                        bullet_id = ensure_bullet(header_root, bullets_el, glyph, bullet_id_cache)
                        para_pr_id = ensure_bullet_para_pr(header_root, bullet_id, depth, para_pr_id_cache)
                        header_dirty = True
                        new_elements.append(_make_text_para(
                            para, text, hp_t, hp_linesegarray, hp_lineseg, next_id, para_pr_id=para_pr_id,
                        ))
                    else:
                        prefix = "  " * depth + glyph + " "
                        new_elements.append(_make_text_para(
                            para, prefix + text, hp_t, hp_linesegarray, hp_lineseg, next_id,
                        ))
                    next_id += 1

        if not new_elements:
            continue

        parent.remove(para)
        for j, new_p in enumerate(new_elements):
            parent.insert(idx + j, new_p)

    return header_dirty
