from __future__ import annotations

import re
from dataclasses import dataclass

_MD_TABLE_ROW_RE = re.compile(r"^\|.+\|$")
_MD_TABLE_SEP_RE = re.compile(r"^\|[\s:|\\-]+\|$")

_CELL_MARGIN_H = 510
_CELL_MARGIN_V = 141
_ROW_HEIGHT = 282  # HWP default minimum; HWP auto-expands as needed


def is_markdown_table(text: str) -> bool:
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    if len(lines) < 2:
        return False
    return sum(1 for l in lines if _MD_TABLE_ROW_RE.match(l)) >= 2


def parse_markdown_table(text: str) -> list[list[str]]:
    rows = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or _MD_TABLE_SEP_RE.match(line):
            continue
        if _MD_TABLE_ROW_RE.match(line):
            cells = [c.strip() for c in line[1:-1].split("|")]
            rows.append(cells)
    return rows


@dataclass
class HtmlCell:
    row: int
    col: int
    rowspan: int
    colspan: int
    text: str
    is_header: bool


def _int_attr(el, name: str, default: int) -> int:
    val = el.get(name)
    if not val:
        return default
    try:
        n = int(val)
    except ValueError:
        return default
    return n if n > 0 else default


def _cell_text(cell_el) -> str:
    text = "".join(cell_el.itertext())
    return re.sub(r"\s+", " ", text).strip()


def parse_html_table(table_el) -> tuple[list[HtmlCell], int, int]:
    """Resolve an HTML <table> element (with rowspan/colspan) into anchor
    cells via an occupancy grid. Positions consumed by a prior cell's
    rowspan/colspan never get their own HtmlCell (matches how real HWPX
    files represent merged cells — no ghost/continuation hp:tc)."""
    tr_els = table_el.findall(".//tr")
    occupied: set[tuple[int, int]] = set()
    cells: list[HtmlCell] = []

    for r, tr in enumerate(tr_els):
        c = 0
        for cell_el in tr:
            if cell_el.tag not in ("td", "th"):
                continue
            while (r, c) in occupied:
                c += 1
            colspan = _int_attr(cell_el, "colspan", 1)
            rowspan = _int_attr(cell_el, "rowspan", 1)
            cells.append(HtmlCell(r, c, rowspan, colspan, _cell_text(cell_el), cell_el.tag == "th"))
            for dr in range(rowspan):
                for dc in range(colspan):
                    occupied.add((r + dr, c + dc))
            c += colspan

    n_rows = len(tr_els)
    n_cols = (max(c for _, c in occupied) + 1) if occupied else 0
    return cells, n_rows, n_cols


# ---- hp:tbl construction (shared scaffold) --------------------------------


def _even_col_widths(n_cols: int, horz_size: int) -> list[int]:
    col_w = horz_size // n_cols
    return [col_w] * (n_cols - 1) + [horz_size - col_w * (n_cols - 1)]


def _tbl_element(hp: str, tbl_id: int, n_rows: int, n_cols: int, horz_size: int, total_height: int):
    from lxml import etree

    tbl = etree.Element(f"{hp}tbl", {
        "id": str(tbl_id),
        "zOrder": "0",
        "numberingType": "TABLE",
        "textWrap": "TOP_AND_BOTTOM",
        "textFlow": "BOTH_SIDES",
        "lock": "0",
        "dropcapstyle": "None",
        "pageBreak": "CELL",
        "repeatHeader": "1",
        "rowCnt": str(n_rows),
        "colCnt": str(n_cols),
        "cellSpacing": "0",
        "borderFillIDRef": "3",
        "noAdjust": "0",
    })
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
    return tbl


def _append_tc(tr, hp: str, col: int, row: int, colspan: int, rowspan: int,
                cell_w: int, cell_h: int, is_header: bool, text: str):
    from lxml import etree

    text_w = max(cell_w - _CELL_MARGIN_H * 2, 0)

    tc = etree.SubElement(tr, f"{hp}tc", {
        "name": "",
        "header": "1" if is_header else "0",
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
    if text:
        t = etree.SubElement(run, f"{hp}t")
        t.text = text

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
    etree.SubElement(tc, f"{hp}cellAddr", {"colAddr": str(col), "rowAddr": str(row)})
    etree.SubElement(tc, f"{hp}cellSpan", {"colSpan": str(colspan), "rowSpan": str(rowspan)})
    etree.SubElement(tc, f"{hp}cellSz", {"width": str(cell_w), "height": str(cell_h)})
    etree.SubElement(tc, f"{hp}cellMargin", {
        "left": str(_CELL_MARGIN_H),
        "right": str(_CELL_MARGIN_H),
        "top": str(_CELL_MARGIN_V),
        "bottom": str(_CELL_MARGIN_V),
    })
    return tc


def build_markdown_table(rows: list[list[str]], hp_ns: str, horz_size: int, next_id: int) -> tuple:
    """Build an hp:tbl element from parsed pipe-markdown table rows (uniform
    grid, no merged cells). Returns (tbl_element, next_id_after)."""
    from lxml import etree

    hp = f"{{{hp_ns}}}"
    n_cols = max(len(row) for row in rows) if rows else 1

    if n_cols == 2:
        left = int(horz_size * 0.25)
        col_widths = [left, horz_size - left]
    else:
        col_widths = _even_col_widths(n_cols, horz_size)

    total_height = _ROW_HEIGHT * len(rows)
    tbl = _tbl_element(hp, next_id, len(rows), n_cols, horz_size, total_height)
    next_id += 1

    for row_idx, row in enumerate(rows):
        cells = row + [""] * (n_cols - len(row))
        tr = etree.SubElement(tbl, f"{hp}tr")
        for col_idx, cell_text in enumerate(cells):
            _append_tc(tr, hp, col_idx, row_idx, 1, 1, col_widths[col_idx], _ROW_HEIGHT, False, cell_text)

    return tbl, next_id


def build_hwpx_table_from_cells(
    cells: list[HtmlCell],
    n_rows: int,
    n_cols: int,
    hp_ns: str,
    horz_size: int,
    next_id: int,
) -> tuple:
    """Build an hp:tbl element honoring each cell's real rowspan/colspan
    (from parse_html_table). Returns (tbl_element, next_id_after)."""
    from lxml import etree

    hp = f"{{{hp_ns}}}"
    n_cols = max(n_cols, 1)
    col_widths = _even_col_widths(n_cols, horz_size)
    total_height = _ROW_HEIGHT * max(n_rows, 1)

    tbl = _tbl_element(hp, next_id, n_rows, n_cols, horz_size, total_height)
    next_id += 1

    rows_map: dict[int, list[HtmlCell]] = {}
    for cell in cells:
        rows_map.setdefault(cell.row, []).append(cell)

    for row_idx in range(n_rows):
        tr = etree.SubElement(tbl, f"{hp}tr")
        for cell in sorted(rows_map.get(row_idx, []), key=lambda c: c.col):
            cell_w = sum(col_widths[cell.col: cell.col + cell.colspan])
            cell_h = _ROW_HEIGHT * cell.rowspan
            _append_tc(tr, hp, cell.col, cell.row, cell.colspan, cell.rowspan,
                       cell_w, cell_h, cell.is_header, cell.text)

    return tbl, next_id
