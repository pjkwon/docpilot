from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from docpilot.exceptions import TemplateError
from typing import Callable

from docpilot.template_generator.extractor import ParagraphInfo, extract

# Default threshold: at least 70% of sample documents must share a section
DEFAULT_CONFIDENCE_THRESHOLD = 0.7

# 문서마다 표기가 다른 번호 매김 접두어(제N장/1./가./①/Ⅰ. 등)를 제목에서 제거해
# 같은 섹션인데 번호 스타일만 달라서 다른 heading으로 잡히는 것을 막는다.
_NUMBERING_KO = "가나다라마바사아자차카타파하"
_NUMBERING_RE = re.compile(
    r"^\s*(?:"
    r"제\s*\d+\s*(?:장|절|조|항|관|과)\s*[.):]?|"
    r"\d+[.)](?=\s|$)|"
    r"\(\d+\)|"
    r"[①-⑳]|"
    r"[Ⅰ-Ⅻ][.)]?|"
    r"[IVXLCDM]+[.)](?=\s|$)|"
    rf"[{_NUMBERING_KO}][.)](?=\s|$)|"
    rf"\([{_NUMBERING_KO}]\)"
    r")\s*"
)


def _normalize_heading(text: str) -> str:
    normalized = _NUMBERING_RE.sub("", text).strip()
    return normalized or text


@dataclass
class AnalysisResult:
    common_sections: list[str]
    confidence: float
    per_document_sections: dict[str, list[str]] = field(default_factory=dict)
    total_documents: int = 0


def analyze(
    samples: list[str | Path],
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    extractor: Callable[[Path], list[ParagraphInfo]] | None = None,
) -> AnalysisResult:
    """
    Analyze multiple sample documents to extract common section structure.

    extractor: paragraph extractor function; defaults to the HWPX extractor.
    confidence: fraction of documents that share each detected section heading.
    Only sections meeting the threshold are included in common_sections.
    """
    if extractor is None:
        extractor = extract

    if not samples:
        raise TemplateError("At least one sample document is required")

    per_doc: dict[str, list[str]] = {}

    for path in samples:
        path = Path(path)
        paragraphs = extractor(path)
        headings = [
            _normalize_heading(p.text) for p in paragraphs if p.is_heading_candidate
        ]
        per_doc[str(path)] = headings

    total = len(per_doc)
    heading_counts: dict[str, int] = {}

    for headings in per_doc.values():
        for h in set(headings):
            heading_counts[h] = heading_counts.get(h, 0) + 1

    common = [
        h for h, count in heading_counts.items()
        if count / total >= confidence_threshold
    ]

    if common:
        confidence = sum(heading_counts[h] for h in common) / (len(common) * total)
    elif heading_counts:
        best_count = max(heading_counts.values())
        confidence = best_count / total
    else:
        confidence = 0.0

    # Preserve document order for common sections
    ordered = _order_sections(common, per_doc)

    return AnalysisResult(
        common_sections=ordered,
        confidence=confidence,
        per_document_sections=per_doc,
        total_documents=total,
    )


def _order_sections(sections: list[str], per_doc: dict[str, list[str]]) -> list[str]:
    """Order sections by their average position across documents."""
    if not sections:
        return []

    section_set = set(sections)
    position_sum: dict[str, float] = {s: 0.0 for s in sections}
    count: dict[str, int] = {s: 0 for s in sections}

    for headings in per_doc.values():
        total = len(headings)
        for i, h in enumerate(headings):
            if h in section_set:
                position_sum[h] += i / max(total, 1)
                count[h] += 1

    avg_pos = {
        s: position_sum[s] / count[s] if count[s] else 0.0
        for s in sections
    }
    return sorted(sections, key=lambda s: avg_pos[s])
