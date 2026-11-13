from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path

from docpilot.exceptions import TemplateError

_NS = {
    "hp": "http://www.hancom.co.kr/hwpml/2012/paragraph",
    "hc": "http://www.hancom.co.kr/hwpml/2012/core",
}

# HWPX font size is stored in 1/100 pt units; 1800 = 18pt (typical heading)
_HEADING_FONT_SIZE_THRESHOLD = 1400  # 14pt and above


@dataclass
class ParagraphInfo:
    text: str
    style_id: str | None = None
    font_size: int | None = None  # in 1/100 pt units
    bold: bool = False
    indent_level: int = 0

    @property
    def is_heading_candidate(self) -> bool:
        if self.bold and self.font_size and self.font_size >= _HEADING_FONT_SIZE_THRESHOLD:
            return True
        if self.style_id and any(
            kw in self.style_id.lower() for kw in ("head", "title", "제목")
        ):
            return True
        return False


def extract(hwpx_path: str | Path) -> list[ParagraphInfo]:
    """Extract paragraph info from a single HWPX file."""
    hwpx_path = Path(hwpx_path)

    if not hwpx_path.exists():
        raise TemplateError("File not found", detail=str(hwpx_path))

    try:
        from lxml import etree
    except ImportError as e:
        raise TemplateError("lxml is required: pip install lxml") from e

    try:
        with zipfile.ZipFile(hwpx_path, "r") as zf:
            content_xml = _find_content(zf)
            root = etree.fromstring(content_xml)
    except zipfile.BadZipFile as e:
        raise TemplateError("Invalid HWPX file", detail=str(e)) from e
    except Exception as e:
        raise TemplateError("Failed to parse HWPX XML", detail=str(e)) from e

    return _parse_paragraphs(root)


def _find_content(zf: zipfile.ZipFile) -> bytes:
    candidates = [n for n in zf.namelist() if n.endswith("content.hml")]
    if not candidates:
        raise TemplateError("content.hml not found inside HWPX")
    return zf.read(candidates[0])


def _parse_paragraphs(root) -> list[ParagraphInfo]:

    hp_p = f"{{{_NS['hp']}}}p"
    hp_t = f"{{{_NS['hp']}}}t"
    hp_pPr = f"{{{_NS['hp']}}}pPr"
    hp_pStyle = f"{{{_NS['hp']}}}pStyle"
    hp_rPr = f"{{{_NS['hp']}}}rPr"
    hp_sz = f"{{{_NS['hp']}}}sz"
    hp_b = f"{{{_NS['hp']}}}b"
    hp_ind = f"{{{_NS['hp']}}}ind"

    results: list[ParagraphInfo] = []

    for para in root.iter(hp_p):
        text = "".join(el.text or "" for el in para.iter(hp_t)).strip()
        if not text:
            continue

        style_id: str | None = None
        font_size: int | None = None
        bold = False
        indent_level = 0

        pPr = para.find(f".//{hp_pPr}")
        if pPr is not None:
            pStyle = pPr.find(hp_pStyle)
            if pStyle is not None:
                style_id = pStyle.get("val") or pStyle.get(f"{{{_NS['hp']}}}val")

            ind = pPr.find(hp_ind)
            if ind is not None:
                left = ind.get("left") or ind.get(f"{{{_NS['hp']}}}left") or "0"
                try:
                    indent_level = int(left) // 720  # 720 = one indent level in HWPX
                except ValueError:
                    pass

        rPr = para.find(f".//{hp_rPr}")
        if rPr is not None:
            sz = rPr.find(hp_sz)
            if sz is not None:
                val = sz.get("val") or sz.get(f"{{{_NS['hp']}}}val")
                if val:
                    try:
                        font_size = int(val)
                    except ValueError:
                        pass

            b = rPr.find(hp_b)
            if b is not None:
                bold = b.get("val", "true").lower() != "false"

        results.append(
            ParagraphInfo(
                text=text,
                style_id=style_id,
                font_size=font_size,
                bold=bold,
                indent_level=indent_level,
            )
        )

    return results
