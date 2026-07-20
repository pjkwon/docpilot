from __future__ import annotations

import re
from dataclasses import dataclass

from docpilot.builder.html_table import _MD_TABLE_ROW_RE, parse_markdown_table
from docpilot.builder.hwpx_bullets import resolve_glyph

_STYLE_SCRIPT_RE = re.compile(r"<(style|script)\b.*?</\1\s*>", re.I | re.S)
_TAG_RE = re.compile(r"<(/?)(table|ul)\b[^>]*>", re.I)


@dataclass
class PlainTextBlock:
    lines: list[str]


@dataclass
class MarkdownTableBlock:
    rows: list[list[str]]


@dataclass
class HtmlTableBlock:
    table_el: object


@dataclass
class HtmlListBlock:
    list_el: object


Block = PlainTextBlock | MarkdownTableBlock | HtmlTableBlock | HtmlListBlock


def segment_blocks(text: str) -> list[Block]:
    """Segment a placeholder's replacement text, in order, into plain-text
    lines, pipe-markdown tables, and raw HTML <table>/<ul> blocks."""
    text = _STYLE_SCRIPT_RE.sub("", text)

    spans = _find_html_spans(text)
    if not spans:
        return _segment_plain(text)

    blocks: list[Block] = []
    pos = 0
    for start, end, tag in spans:
        if start > pos:
            blocks.extend(_segment_plain(text[pos:start]))
        block = _parse_html_fragment(text[start:end], tag)
        if block is not None:
            blocks.append(block)
        else:
            blocks.extend(_segment_plain(text[start:end]))
        pos = end
    if pos < len(text):
        blocks.extend(_segment_plain(text[pos:]))
    return blocks


def _parse_html_fragment(fragment: str, tag: str):
    import lxml.html
    try:
        el = lxml.html.fromstring(fragment)
    except Exception:
        return None
    if tag == "table":
        return HtmlTableBlock(table_el=el)
    return HtmlListBlock(list_el=el)


def _find_html_spans(text: str) -> list[tuple[int, int, str]]:
    """Locate top-level <table>...</table> / <ul>...</ul> spans using a
    single shared depth counter (not one per tag name) — this way a stray
    <table> encountered while already inside an outer <ul> span (or vice
    versa) is correctly folded into that outer span's interior content
    instead of spawning a spurious second top-level block."""
    spans: list[tuple[int, int, str]] = []
    depth = 0
    outer_tag = ""
    outer_start = 0
    for m in _TAG_RE.finditer(text):
        closing = bool(m.group(1))
        tag = m.group(2).lower()
        if not closing:
            if depth == 0:
                outer_tag = tag
                outer_start = m.start()
            depth += 1
        else:
            if depth == 0:
                continue
            depth -= 1
            if depth == 0:
                spans.append((outer_start, m.end(), outer_tag))
    return spans


def _segment_plain(text: str) -> list[Block]:
    blocks: list[Block] = []
    lines = text.split("\n")
    n = len(lines)
    i = 0
    text_buf: list[str] = []

    def flush_text() -> None:
        cleaned = [l for l in text_buf if l.strip()]
        if cleaned:
            blocks.append(PlainTextBlock(lines=cleaned))
        text_buf.clear()

    while i < n:
        j = i
        table_lines: list[str] = []
        while j < n and _MD_TABLE_ROW_RE.match(lines[j].strip()):
            table_lines.append(lines[j])
            j += 1
        if len(table_lines) >= 2:
            flush_text()
            rows = parse_markdown_table("\n".join(table_lines))
            if rows:
                blocks.append(MarkdownTableBlock(rows=rows))
            i = j
            continue
        text_buf.append(lines[i])
        i += 1
    flush_text()
    return blocks


def flatten_list(ul_el, depth: int = 0) -> list[tuple[str, int, str]]:
    """Depth-first walk of an HTML <ul>. Returns ordered (text, depth, glyph)
    tuples, one per <li>, in document order.

    lxml.html does NOT reparent a bare <ul> that follows a <li> as sibling
    markup (unlike a browser, which implicitly nests it inside the preceding
    <li>) — it comes back as a direct sibling of that <li>. We detect that
    case (a bare <ul> child appearing right after a <li> child) and treat it
    as nested content of that <li> anyway, to match real-world rendering
    intent.
    """
    items: list[tuple[str, int, str]] = []
    last_li = None
    for child in ul_el:
        if not isinstance(child.tag, str):
            continue
        if child.tag == "li":
            text = _own_text(child)
            glyph = resolve_glyph(child, depth)
            items.append((text, depth, glyph))
            last_li = child
            for nested in child.findall("ul"):
                items.extend(flatten_list(nested, depth + 1))
        elif child.tag == "ul" and last_li is not None:
            items.extend(flatten_list(child, depth + 1))
    return items


def _own_text(li_el) -> str:
    """The <li>'s own text, excluding any nested <ul>/<ol> subtree's text."""
    parts: list[str] = []
    if li_el.text:
        parts.append(li_el.text)
    for child in li_el:
        if not isinstance(child.tag, str):
            continue
        if child.tag in ("ul", "ol"):
            if child.tail:
                parts.append(child.tail)
            continue
        parts.extend(child.itertext())
        if child.tail:
            parts.append(child.tail)
    return re.sub(r"\s+", " ", "".join(parts)).strip()
