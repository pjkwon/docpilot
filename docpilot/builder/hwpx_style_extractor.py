from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class CharStyle:
    id: int
    pt: float
    bold: bool
    color: str

    def describe(self) -> str:
        parts = [f"{self.pt}pt"]
        if self.bold:
            parts.append("굵게")
        if self.color not in ("#000000", "none"):
            parts.append(f"색상:{self.color}")
        return f"id={self.id} ({', '.join(parts)})"


@dataclass
class ParaStyle:
    id: int
    align: str

    _ALIGN_KO = {
        "JUSTIFY": "양쪽정렬",
        "LEFT": "왼쪽정렬",
        "CENTER": "가운데정렬",
        "RIGHT": "오른쪽정렬",
    }

    def describe(self) -> str:
        return f"id={self.id} ({self._ALIGN_KO.get(self.align, self.align)})"


class StyleCatalog:
    def __init__(self, char_styles: list[CharStyle], para_styles: list[ParaStyle]) -> None:
        self.char_styles = char_styles
        self.para_styles = para_styles

    # --- style selectors ---

    def title_char_id(self) -> int:
        """Bold charPr nearest to 20pt — standard Korean document title size."""
        bold = [c for c in self.char_styles if c.bold]
        if not bold:
            return max(self.char_styles, key=lambda c: c.pt).id
        return min(bold, key=lambda c: abs(c.pt - 20.0)).id

    def heading_char_id(self) -> int:
        """Bold charPr nearest to 14pt — standard Korean section heading size."""
        bold = [c for c in self.char_styles if c.bold]
        if not bold:
            return self.body_char_id()
        title_id = self.title_char_id()
        candidates = [c for c in bold if c.id != title_id]
        if not candidates:
            return title_id
        return min(candidates, key=lambda c: abs(c.pt - 14.0)).id

    def body_char_id(self) -> int:
        """Non-bold charPr closest to 10pt (prefer exact match)."""
        normal = [c for c in self.char_styles if not c.bold]
        if not normal:
            return self.char_styles[0].id
        exact = [c for c in normal if c.pt == 10.0]
        if exact:
            return exact[0].id
        return min(normal, key=lambda c: abs(c.pt - 10.0)).id

    def center_para_id(self) -> int:
        center = [p for p in self.para_styles if p.align == "CENTER"]
        return center[0].id if center else 0

    def justify_para_id(self) -> int:
        justify = [p for p in self.para_styles if p.align == "JUSTIFY"]
        return justify[0].id if justify else 0

    # --- prompt helper ---

    def to_prompt_text(self) -> str:
        char_lines = "\n".join(f"  {c.describe()}" for c in self.char_styles)
        para_lines = "\n".join(f"  {p.describe()}" for p in self.para_styles)
        return (
            f"## 글자 스타일 (charPrIDRef)\n{char_lines}\n\n"
            f"## 문단 스타일 (paraPrIDRef)\n{para_lines}\n\n"
            f"추천: 제목={self.title_char_id()} / "
            f"소제목={self.heading_char_id()} / "
            f"본문={self.body_char_id()} / "
            f"가운데정렬={self.center_para_id()} / "
            f"양쪽정렬={self.justify_para_id()}"
        )


def extract(header_xml: Path) -> StyleCatalog:
    """Parse header.xml and return a StyleCatalog."""
    try:
        from lxml import etree
    except ImportError as e:
        raise ImportError("lxml required: pip install lxml") from e

    tree = etree.parse(str(header_xml))
    root = tree.getroot()
    hh = "{http://www.hancom.co.kr/hwpml/2011/head}"

    char_styles: list[CharStyle] = []
    for cp in root.iter(f"{hh}charPr"):
        cid = int(cp.get("id", "0"))
        height = int(cp.get("height", "1000"))
        bold = cp.find(f"{hh}bold") is not None
        color = cp.get("textColor", "#000000")
        char_styles.append(CharStyle(id=cid, pt=height / 100, bold=bold, color=color))

    para_styles: list[ParaStyle] = []
    seen: set[int] = set()
    for pp in root.iter(f"{hh}paraPr"):
        pid = int(pp.get("id", "0"))
        if pid in seen:
            continue
        seen.add(pid)
        align_el = pp.find(f"{hh}align")
        align = align_el.get("horizontal", "JUSTIFY") if align_el is not None else "JUSTIFY"
        para_styles.append(ParaStyle(id=pid, align=align))

    return StyleCatalog(char_styles=char_styles, para_styles=para_styles)
