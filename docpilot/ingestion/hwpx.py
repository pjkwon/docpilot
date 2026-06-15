from __future__ import annotations

import re
import zipfile
from pathlib import Path

from docpilot.exceptions import IngestionError
from docpilot.ingestion.models import IngestedDocument


def ingest(path: str | Path) -> IngestedDocument:
    path = Path(path)

    if not path.exists():
        raise IngestionError("File not found", detail=str(path))

    if path.suffix.lower() != ".hwpx":
        raise IngestionError(f"Expected .hwpx, got '{path.suffix}'", detail=str(path))

    try:
        from lxml import etree
    except ImportError as e:
        raise IngestionError("lxml is required: pip install lxml") from e

    try:
        with zipfile.ZipFile(path, "r") as zf:
            section_xmls = _find_sections(zf)
            paragraphs: list[str] = []
            for xml_bytes in section_xmls:
                root = etree.fromstring(xml_bytes)
                paragraphs.extend(_extract_text(root))
    except zipfile.BadZipFile as e:
        raise IngestionError("Invalid HWPX file (not a ZIP)", detail=str(e)) from e
    except IngestionError:
        raise
    except Exception as e:
        raise IngestionError("Failed to parse HWPX", detail=str(e)) from e

    content = "\n".join(paragraphs)

    return IngestedDocument(
        source=path,
        content=content,
        mime_type="application/hwp+zip",
        metadata={
            "paragraph_count": len(paragraphs),
            "size_bytes": path.stat().st_size,
        },
    )


def _find_sections(zf: zipfile.ZipFile) -> list[bytes]:
    """Return body XML bytes for all sections in document order.

    HWPX comes in two layouts:
    - Single-file HML  : Contents/content.hml  (body + head in one file)
    - Multi-section    : Contents/section0.xml, section1.xml, … (one file per section)
    """
    names = zf.namelist()

    hml = [n for n in names if n.endswith("content.hml")]
    if hml:
        return [zf.read(hml[0])]

    sections = sorted(
        (n for n in names if re.search(r"section\d+\.xml$", n, re.IGNORECASE)),
        key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)),
    )
    if sections:
        return [zf.read(n) for n in sections]

    raise IngestionError("No content file found in HWPX")


def _extract_text(root) -> list[str]:
    """Extract non-empty paragraph text from an HML/section XML root.

    Uses recursive iter so text inside text boxes, table cells, footnotes,
    endnotes, and headers/footers (when embedded in the same XML) is included.
    Supports both the 2011 and 2012 Hancom namespace variants.
    """
    ns = root.nsmap.get("hp", "http://www.hancom.co.kr/hwpml/2012/paragraph")
    hp_p = f"{{{ns}}}p"
    hp_t = f"{{{ns}}}t"

    results: list[str] = []
    for para in root.iter(hp_p):
        text = "".join(el.text or "" for el in para.iter(hp_t)).strip()
        if text:
            results.append(text)
    return results
