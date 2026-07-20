from __future__ import annotations

from pathlib import Path

import pytest

from docpilot.builder.hwpx_builder import HwpxBuilder
from docpilot.exceptions import BuilderError

SECTIONS = {"서론": "서론 내용입니다.", "결론": "결론 내용입니다."}


class TestHwpxBuilder:
    def test_build_produces_file(self, hwpx_template: Path, tmp_path: Path):
        output = tmp_path / "output.hwpx"
        builder = HwpxBuilder()
        result = builder.build(hwpx_template, SECTIONS, output)
        assert result == output
        assert output.exists()
        assert output.stat().st_size > 0

    def test_placeholders_replaced(self, hwpx_template: Path, tmp_path: Path):
        import zipfile
        output = tmp_path / "output.hwpx"
        HwpxBuilder().build(hwpx_template, SECTIONS, output)

        with zipfile.ZipFile(output, "r") as zf:
            candidates = [n for n in zf.namelist() if n.endswith("content.hml")]
            content = zf.read(candidates[0]).decode("utf-8")

        assert "서론 내용입니다." in content
        assert "{{서론}}" not in content

    def test_template_not_found_raises(self, tmp_path: Path):
        with pytest.raises(BuilderError, match="not found"):
            HwpxBuilder().build(tmp_path / "missing.hwpx", SECTIONS, tmp_path / "out.hwpx")

    def test_wrong_extension_raises(self, tmp_path: Path):
        bad = tmp_path / "template.docx"
        bad.write_bytes(b"fake")
        with pytest.raises(BuilderError, match="Expected .hwpx"):
            HwpxBuilder().build(bad, SECTIONS, tmp_path / "out.hwpx")

    def test_html_table_rowspan_colspan_becomes_merged_cells(self, hwpx_template: Path, tmp_path: Path):
        import zipfile

        html = """
        <table border="1">
          <tr><td rowspan="2">A</td><td>B</td><td>C</td></tr>
          <tr><td>D</td><td>E</td></tr>
        </table>
        """
        output = tmp_path / "output.hwpx"
        HwpxBuilder().build(hwpx_template, {"서론": html, "결론": "결론 내용입니다."}, output)

        with zipfile.ZipFile(output, "r") as zf:
            content = zf.read("Contents/content.hml").decode("utf-8")

        assert "<hp:tbl" in content
        assert 'rowSpan="2"' in content
        assert 'colSpan="1"' in content  # untouched cells still explicit 1x1

    def test_html_list_degrades_to_glyph_prefix_without_header(self, hwpx_template: Path, tmp_path: Path):
        import zipfile

        html = "<ul><li>1단계</li><ul><li style=\"list-style-type: circle;\">2단계</li></ul></ul>"
        output = tmp_path / "output.hwpx"
        HwpxBuilder().build(hwpx_template, {"서론": html, "결론": "결론 내용입니다."}, output)

        with zipfile.ZipFile(output, "r") as zf:
            content = zf.read("Contents/content.hml").decode("utf-8")

        assert "●" in content and "1단계" in content
        assert "◦" in content and "2단계" in content

    def test_html_list_creates_real_bullets_with_header(self, hwpx_template_with_header: Path, tmp_path: Path):
        import zipfile

        html = "<ul><li>1단계</li><ul><li style=\"list-style-type: circle;\">2단계</li></ul></ul>"
        output = tmp_path / "output.hwpx"
        HwpxBuilder().build(hwpx_template_with_header, {"내용": html}, output)

        with zipfile.ZipFile(output, "r") as zf:
            section = zf.read("Contents/section0.xml").decode("utf-8")
            header = zf.read("Contents/header.xml").decode("utf-8")

        assert '<hh:bullets itemCnt="2">' in header
        assert 'char="●"' in header and 'char="◦"' in header
        assert header.count('type="BULLET"') == 2
        assert "1단계" in section and "2단계" in section
        # the run text itself must not carry a literal bullet glyph — HWP draws it from header.xml
        assert "●" not in section

    def test_mixed_text_and_table_in_one_placeholder(self, hwpx_template: Path, tmp_path: Path):
        import zipfile

        mixed = "앞 문단\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n\n뒤 문단"
        output = tmp_path / "output.hwpx"
        HwpxBuilder().build(hwpx_template, {"서론": mixed, "결론": "결론 내용입니다."}, output)

        with zipfile.ZipFile(output, "r") as zf:
            content = zf.read("Contents/content.hml").decode("utf-8")

        assert "앞 문단" in content
        assert "<hp:tbl" in content
        assert "뒤 문단" in content
        assert content.index("앞 문단") < content.index("<hp:tbl") < content.index("뒤 문단")


class TestDocxBuilder:
    def test_build_produces_file(self, tmp_path: Path):
        docx = pytest.importorskip("docx")
        from docx import Document
        from docpilot.builder.docx_builder import DocxBuilder

        template = tmp_path / "template.docx"
        doc = Document()
        doc.add_paragraph("{{서론}}")
        doc.add_paragraph("{{결론}}")
        doc.save(str(template))

        output = tmp_path / "output.docx"
        DocxBuilder().build(template, SECTIONS, output)

        assert output.exists()
        result_doc = Document(str(output))
        texts = [p.text for p in result_doc.paragraphs]
        assert "서론 내용입니다." in texts
        assert "결론 내용입니다." in texts
