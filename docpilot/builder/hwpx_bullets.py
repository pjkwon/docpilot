from __future__ import annotations

import re

# disc / circle / square — matches CSS list-style-type defaults for
# nesting depth 0/1/2+. Depth >= 2 repeats the square glyph.
# U+25CB (WHITE CIRCLE) was tried first for "circle" but renders filled-in
# in 한글 at normal bullet size — its ring is too thin to survive rasterization
# at that point size. U+25E6 (WHITE BULLET) is purpose-built as a small hollow
# dot and stays visibly hollow at bullet sizes.
_BULLET_GLYPHS = ["●", "◦", "■"]  # ● ◦ ■
_STYLE_GLYPH = {"disc": _BULLET_GLYPHS[0], "circle": _BULLET_GLYPHS[1], "square": _BULLET_GLYPHS[2]}
_STYLE_RE = re.compile(r"list-style-type\s*:\s*(\w+)", re.I)

_MARGIN_STEP = 400  # HWPUNIT per nesting depth — matches real Hancom bullet paraPr samples

_DEFAULT_HH_NS = "http://www.hancom.co.kr/hwpml/2011/head"
_DEFAULT_HC_NS = "http://www.hancom.co.kr/hwpml/2011/core"
_DEFAULT_HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"


def default_glyph(depth: int) -> str:
    return _BULLET_GLYPHS[min(depth, len(_BULLET_GLYPHS) - 1)]


def resolve_glyph(li_el, depth: int) -> str:
    """Inline style="list-style-type: disc|circle|square" wins; otherwise
    fall back to the depth-based CSS default cascade."""
    style = li_el.get("style", "") or ""
    m = _STYLE_RE.search(style)
    if m:
        glyph = _STYLE_GLYPH.get(m.group(1).lower())
        if glyph:
            return glyph
    return default_glyph(depth)


def _ns(header_root, prefix: str, default: str) -> str:
    return header_root.nsmap.get(prefix, default)


def get_or_create_bullets_container(header_root):
    """Find hh:refList/hh:bullets; create it (positioned after hh:numberings,
    before hh:paraProperties — the order real Hancom-generated files use) if
    the template doesn't have one yet. None of docpilot's built-in templates
    ship with hh:bullets today."""
    hh = f"{{{_ns(header_root, 'hh', _DEFAULT_HH_NS)}}}"
    ref_list = header_root.find(f"{hh}refList")
    if ref_list is None:
        raise ValueError("hh:refList not found in header.xml")

    bullets_el = ref_list.find(f"{hh}bullets")
    if bullets_el is not None:
        return bullets_el

    from lxml import etree
    bullets_el = etree.Element(f"{hh}bullets", {"itemCnt": "0"})
    numberings_el = ref_list.find(f"{hh}numberings")
    para_props_el = ref_list.find(f"{hh}paraProperties")
    if numberings_el is not None:
        numberings_el.addnext(bullets_el)
    elif para_props_el is not None:
        para_props_el.addprevious(bullets_el)
    else:
        ref_list.append(bullets_el)
    return bullets_el


def _max_id(container, hh: str, child_tag: str) -> int:
    ids = [int(el.get("id", -1)) for el in container.findall(f"{hh}{child_tag}")]
    return max(ids, default=-1)


def ensure_bullet(header_root, bullets_el, glyph: str, id_cache: dict[str, int]) -> int:
    """Idempotent per glyph (both within one build() call via id_cache, and
    across builds by reusing a matching hh:bullet already in the template)."""
    if glyph in id_cache:
        return id_cache[glyph]

    hh = f"{{{_ns(header_root, 'hh', _DEFAULT_HH_NS)}}}"

    for existing in bullets_el.findall(f"{hh}bullet"):
        if existing.get("char") == glyph:
            bid = int(existing.get("id"))
            id_cache[glyph] = bid
            return bid

    from lxml import etree
    new_id = _max_id(bullets_el, hh, "bullet") + 1
    bullet_el = etree.SubElement(bullets_el, f"{hh}bullet", {
        "id": str(new_id), "char": glyph, "useImage": "0",
    })
    etree.SubElement(bullet_el, f"{hh}paraHead", {
        "level": "0", "align": "LEFT", "useInstWidth": "0", "autoIndent": "1",
        "widthAdjust": "0", "textOffsetType": "PERCENT", "textOffset": "50",
        "numFormat": "DIGIT", "charPrIDRef": "4294967295", "checkable": "0",
    })
    bullets_el.set("itemCnt", str(int(bullets_el.get("itemCnt", "0")) + 1))
    id_cache[glyph] = new_id
    return new_id


def _append_margin(parent, hh: str, hc: str, left: str) -> None:
    from lxml import etree
    margin = etree.SubElement(parent, f"{hh}margin")
    etree.SubElement(margin, f"{hc}intent", {"value": "0", "unit": "HWPUNIT"})
    etree.SubElement(margin, f"{hc}left", {"value": left, "unit": "HWPUNIT"})
    etree.SubElement(margin, f"{hc}right", {"value": "0", "unit": "HWPUNIT"})
    etree.SubElement(margin, f"{hc}prev", {"value": "0", "unit": "HWPUNIT"})
    etree.SubElement(margin, f"{hc}next", {"value": "0", "unit": "HWPUNIT"})
    etree.SubElement(parent, f"{hh}lineSpacing", {"type": "PERCENT", "value": "160", "unit": "HWPUNIT"})


def ensure_bullet_para_pr(header_root, bullet_id: int, depth: int,
                           id_cache: dict[tuple[int, int], int]) -> int:
    """Idempotent per (bullet_id, depth) — a bullet glyph at a given nesting
    depth needs its own hh:paraPr (heading/idRef=bullet_id, margin scaled by
    depth). Returns the new paraPrIDRef."""
    key = (bullet_id, depth)
    if key in id_cache:
        return id_cache[key]

    hh = f"{{{_ns(header_root, 'hh', _DEFAULT_HH_NS)}}}"
    hc = f"{{{_ns(header_root, 'hc', _DEFAULT_HC_NS)}}}"
    hp = f"{{{_ns(header_root, 'hp', _DEFAULT_HP_NS)}}}"

    para_props_el = header_root.find(f"{hh}refList/{hh}paraProperties")
    if para_props_el is None:
        raise ValueError("hh:paraProperties not found in header.xml")

    from lxml import etree
    new_id = _max_id(para_props_el, hh, "paraPr") + 1
    left = str(depth * _MARGIN_STEP)

    para_pr = etree.SubElement(para_props_el, f"{hh}paraPr", {
        "id": str(new_id), "tabPrIDRef": "0", "condense": "0",
        "fontLineHeight": "0", "snapToGrid": "1", "suppressLineNumbers": "0",
        "checked": "0",
    })
    etree.SubElement(para_pr, f"{hh}align", {"horizontal": "LEFT", "vertical": "BASELINE"})
    etree.SubElement(para_pr, f"{hh}heading", {"type": "BULLET", "idRef": str(bullet_id), "level": "0"})
    etree.SubElement(para_pr, f"{hh}breakSetting", {
        "breakLatinWord": "KEEP_WORD", "breakNonLatinWord": "KEEP_WORD",
        "widowOrphan": "0", "keepWithNext": "0", "keepLines": "0",
        "pageBreakBefore": "0", "lineWrap": "BREAK",
    })
    etree.SubElement(para_pr, f"{hh}autoSpacing", {"eAsianEng": "0", "eAsianNum": "0"})

    switch = etree.SubElement(para_pr, f"{hp}switch")
    case = etree.SubElement(switch, f"{hp}case", {
        f"{hp}required-namespace": "http://www.hancom.co.kr/hwpml/2016/HwpUnitChar",
    })
    _append_margin(case, hh, hc, left)
    default = etree.SubElement(switch, f"{hp}default")
    _append_margin(default, hh, hc, left)

    etree.SubElement(para_pr, f"{hh}border", {
        "borderFillIDRef": "2", "offsetLeft": "0", "offsetRight": "0",
        "offsetTop": "0", "offsetBottom": "0", "connect": "0", "ignoreMargin": "0",
    })

    para_props_el.set("itemCnt", str(int(para_props_el.get("itemCnt", "0")) + 1))
    id_cache[key] = new_id
    return new_id
