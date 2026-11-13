from __future__ import annotations

from pathlib import Path

from docpilot.builder.base import BaseBuilder, PLACEHOLDER_RE
from docpilot.exceptions import BuilderError


class PdfBuilder(BaseBuilder):
    def build(
        self,
        template: str | Path,
        sections: dict[str, str],
        output: str | Path,
    ) -> Path:
        template, output = self._validate_paths(template, output)

        if template.suffix.lower() != ".pdf":
            raise BuilderError(f"Expected .pdf template, got '{template.suffix}'")

        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.units import mm
            from reportlab.platypus import SimpleDocTemplate
        except ImportError as e:
            raise BuilderError("reportlab is required: pip install reportlab") from e

        template_sections = _parse_template(template)
        story = _build_story(template_sections, sections)

        try:
            doc = SimpleDocTemplate(
                str(output),
                pagesize=A4,
                leftMargin=25 * mm,
                rightMargin=25 * mm,
                topMargin=25 * mm,
                bottomMargin=25 * mm,
            )
            doc.build(story)
        except Exception as e:
            raise BuilderError("Failed to generate PDF", detail=str(e)) from e

        return output


def _parse_template(template: Path) -> list[dict]:
    """
    Read a PDF template as plain text (for placeholder extraction).
    The PDF template is expected to be a simple structured PDF where
    section placeholders appear as {{섹션명}} in the text content.
    """
    try:
        import pdfplumber
    except ImportError as e:
        raise BuilderError("pdfplumber is required: pip install pdfplumber") from e

    sections: list[dict] = []
    try:
        with pdfplumber.open(template) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                for line in text.splitlines():
                    sections.append({"text": line})
    except Exception as e:
        raise BuilderError("Failed to read PDF template", detail=str(e)) from e

    return sections


def _build_story(template_sections: list[dict], sections: dict[str, str]) -> list:
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, Spacer
    from reportlab.lib.units import mm

    styles = getSampleStyleSheet()
    normal = styles["Normal"]
    heading = styles["Heading2"]
    story = []

    for item in template_sections:
        line = item["text"]
        match = PLACEHOLDER_RE.search(line)
        if match:
            key = match.group(1)
            content = sections.get(key, line)
            replaced = PLACEHOLDER_RE.sub(content, line)

            story.append(Spacer(1, 4 * mm))
            for para_line in replaced.splitlines():
                if para_line.strip():
                    story.append(Paragraph(para_line, normal))
        else:
            if line.strip():
                story.append(Paragraph(line, heading if line.isupper() else normal))

    return story
