from __future__ import annotations

import copy
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from docpilot.builder.base import BaseBuilder, PLACEHOLDER_RE
from docpilot.exceptions import BuilderError

# Candidate content file paths inside the HWPX ZIP (tried in order)
_CONTENT_CANDIDATES = ["Contents/content.hml", "Contents/section0.xml"]

_MD_TABLE_ROW_RE = re.compile(r"^\|.+\|$")
_MD_TABLE_SEP_RE = re.compile(r"^\|[\s:|\\-]+\|$")


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

            content_file = next(
                (tmp_path / cp for cp in _CONTENT_CANDIDATES if (tmp_path / cp).exists()),
                None,
            )
            if content_file is None:
                raise BuilderError(
                    "No content file found in HWPX (tried content.hml, section0.xml)",
                    detail=str(template),
                )

            tree = etree.parse(str(content_file))
            root = tree.getroot()

            _replace_placeholders(root, sections)

            tree.write(
                str(content_file),
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


def _is_markdown_table(text: str) -> bool:
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    if len(lines) < 2:
        return False
    return sum(1 for l in lines if _MD_TABLE_ROW_RE.match(l)) >= 2


def _parse_markdown_table(text: str) -> list[list[str]]:
    rows = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or _MD_TABLE_SEP_RE.match(line):
            continue
        if _MD_TABLE_ROW_RE.match(line):
            cells = [c.strip() for c in line[1:-1].split("|")]
            rows.append(cells)
    return rows


def _read_horz_size(root, hp_ns: str, default: int = 42520) -> int:
    hp = f"{{{hp_ns}}}"
    for ls in root.iter(f"{hp}lineseg"):
        val = ls.get("horzsize")
        if val:
            return int(val)
    return default


def _build_hwpx_table(
    rows: list[list[str]],
    hp_ns: str,
    horz_size: int,
    next_id: int,
) -> tuple:
    """Build an hp:tbl element from parsed markdown table rows.
    Returns (tbl_element, next_id_after).
    """
    from lxml import etree

    hp = f"{{{hp_ns}}}"
    n_cols = max(len(row) for row in rows) if rows else 1
    cell_margin_h = 510
    cell_margin_v = 141
    row_height = 282  # HWP default minimum; HWP auto-expands as needed

    if n_cols == 2:
        col_widths = [int(horz_size * 0.25), horz_size - int(horz_size * 0.25)]
    else:
        col_w = horz_size // n_cols
        col_widths = [col_w] * (n_cols - 1) + [horz_size - col_w * (n_cols - 1)]

    total_height = row_height * len(rows)

    tbl = etree.Element(f"{hp}tbl", {
        "id": str(next_id),
        "zOrder": "0",
        "numberingType": "TABLE",
        "textWrap": "TOP_AND_BOTTOM",
        "textFlow": "BOTH_SIDES",
        "lock": "0",
        "dropcapstyle": "None",
        "pageBreak": "CELL",
        "repeatHeader": "1",
        "rowCnt": str(len(rows)),
        "colCnt": str(n_cols),
        "cellSpacing": "0",
        "borderFillIDRef": "3",
        "noAdjust": "0",
    })
    next_id += 1

    etree.SubElement(tbl, f"{hp}sz", {
        "width": str(horz_size),
        "widthRelTo": "ABSOLUTE",
        "height": str(total_height),
        "heightRelTo": "ABSOLUTE",
        "protect": "0",
    })
    etree.SubElement(tbl, f"{hp}pos", {
        "treatAsChar": "0",
        "affectLSpacing": "0",
        "flowWithText": "1",
        "allowOverlap": "0",
        "holdAnchorAndSO": "0",
        "vertRelTo": "PARA",
        "horzRelTo": "COLUMN",
        "vertAlign": "TOP",
        "horzAlign": "LEFT",
        "vertOffset": "0",
        "horzOffset": "0",
    })
    etree.SubElement(tbl, f"{hp}outMargin", {"left": "283", "right": "283", "top": "283", "bottom": "283"})
    etree.SubElement(tbl, f"{hp}inMargin", {"left": "510", "right": "510", "top": "141", "bottom": "141"})

    for row_idx, row in enumerate(rows):
        cells = row + [""] * (n_cols - len(row))
        tr = etree.SubElement(tbl, f"{hp}tr")

        for col_idx, cell_text in enumerate(cells):
            cell_w = col_widths[col_idx]
            text_w = cell_w - cell_margin_h * 2

            tc = etree.SubElement(tr, f"{hp}tc", {
                "name": "",
                "header": "0",
                "hasMargin": "0",
                "protect": "0",
                "editable": "0",
                "dirty": "0",
                "borderFillIDRef": "3",
            })

            # subList comes FIRST inside tc (HWP schema requirement)
            sub_list = etree.SubElement(tc, f"{hp}subList", {
                "id": "",
                "textDirection": "HORIZONTAL",
                "lineWrap": "BREAK",
                "vertAlign": "CENTER",
                "linkListIDRef": "0",
                "linkListNextIDRef": "0",
                "textWidth": "0",
                "textHeight": "0",
                "hasTextRef": "0",
                "hasNumRef": "0",
            })

            p = etree.SubElement(sub_list, f"{hp}p", {
                "id": "0",
                "paraPrIDRef": "0",
                "styleIDRef": "0",
                "pageBreak": "0",
                "columnBreak": "0",
                "merged": "0",
            })

            run = etree.SubElement(p, f"{hp}run", {"charPrIDRef": "0"})
            if cell_text:
                t = etree.SubElement(run, f"{hp}t")
                t.text = cell_text

            lsa = etree.SubElement(p, f"{hp}linesegarray")
            etree.SubElement(lsa, f"{hp}lineseg", {
                "textpos": "0",
                "vertpos": "0",
                "vertsize": "1000",
                "textheight": "1000",
                "baseline": "850",
                "spacing": "600",
                "horzpos": "0",
                "horzsize": str(text_w),
                "flags": "393216",
            })

            # Cell metadata after subList
            etree.SubElement(tc, f"{hp}cellAddr", {
                "colAddr": str(col_idx),
                "rowAddr": str(row_idx),
            })
            etree.SubElement(tc, f"{hp}cellSpan", {"colSpan": "1", "rowSpan": "1"})
            etree.SubElement(tc, f"{hp}cellSz", {
                "width": str(cell_w),
                "height": str(row_height),
            })
            etree.SubElement(tc, f"{hp}cellMargin", {
                "left": str(cell_margin_h),
                "right": str(cell_margin_h),
                "top": str(cell_margin_v),
                "bottom": str(cell_margin_v),
            })

    return tbl, next_id


def _replace_placeholders(root, sections: dict[str, str | list[str]]) -> None:
    # Detect hp namespace from document root (supports both 2011 and 2012 variants)
    hp_ns = root.nsmap.get("hp", "http://www.hancom.co.kr/hwpml/2012/paragraph")
    hp_t = f"{{{hp_ns}}}t"
    hp_p = f"{{{hp_ns}}}p"
    hp_run = f"{{{hp_ns}}}run"
    hp_linesegarray = f"{{{hp_ns}}}linesegarray"
    hp_lineseg = f"{{{hp_ns}}}lineseg"

    horz_size = _read_horz_size(root, hp_ns)

    # Collect all existing IDs so generated IDs never collide
    existing_ids = {int(el.get("id", 0)) for el in root.iter(hp_p) if el.get("id")}
    next_id = max(existing_ids, default=2_000_000_000) + 1

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

        # Markdown table → real HWPX table element
        if _is_markdown_table(replaced):
            rows = _parse_markdown_table(replaced)
            if rows:
                tbl_elem, next_id = _build_hwpx_table(
                    rows, hp_ns, horz_size, next_id
                )
                run = t_elements[0].getparent()
                if run is not None:
                    # Clear text from all t elements but keep one empty <hp:t/>
                    # (HWP requires <hp:t/> sibling after <hp:tbl> in the same run)
                    for t_el in t_elements[1:]:
                        run.remove(t_el)
                    t_elements[0].text = None
                    run.insert(0, tbl_elem)
                    # Restore a minimal lineseg on the outer paragraph
                    lsa = para.find(hp_linesegarray)
                    if lsa is not None:
                        for ls in list(lsa.findall(hp_lineseg)):
                            lsa.remove(ls)
                        from lxml import etree as _etree
                        _etree.SubElement(lsa, hp_lineseg, {
                            "textpos": "0", "vertpos": "0",
                            "vertsize": "1000", "textheight": "1000",
                            "baseline": "850", "spacing": "600",
                            "horzpos": "0", "horzsize": "0", "flags": "393216",
                        })
                else:
                    t_elements[0].text = " | ".join(
                        " | ".join(c for c in row) for row in rows
                    )
            continue

        lines = replaced.split("\n")

        if len(lines) == 1:
            t_elements[0].text = lines[0]
            for el in t_elements[1:]:
                el.text = ""
            _clear_lineseg(para, hp_linesegarray, hp_lineseg)
            continue

        # Multiline: expand into one <hp:p> per line
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
            new_p = copy.deepcopy(para)
            new_p.set("id", str(next_id))
            next_id += 1
            new_t_elements = new_p.findall(f".//{hp_t}")
            if new_t_elements:
                new_t_elements[0].text = line
                for el in new_t_elements[1:]:
                    el.text = ""
            _clear_lineseg(new_p, hp_linesegarray, hp_lineseg)
            new_paras.append(new_p)

        parent.remove(para)
        for j, new_p in enumerate(new_paras):
            parent.insert(idx + j, new_p)


def _clear_lineseg(para, hp_linesegarray: str, hp_lineseg: str) -> None:
    """lineseg 자식을 제거해 HWP가 열 때 레이아웃을 재계산하도록 한다."""
    lsa = para.find(hp_linesegarray)
    if lsa is None:
        return
    for ls in list(lsa.findall(hp_lineseg)):
        lsa.remove(ls)
