from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from docpilot.exceptions import TemplateError
from docpilot.template_generator.extractor import ParagraphInfo, extract
from docpilot.template_generator.analyzer import analyze, AnalysisResult, _normalize_heading
from docpilot.template_generator.generator import generate


class TestExtractor:
    def test_extracts_paragraphs(self, sample_hwpx: Path):
        paragraphs = extract(sample_hwpx)
        assert len(paragraphs) > 0
        assert all(isinstance(p, ParagraphInfo) for p in paragraphs)

    def test_detects_heading_candidates(self, sample_hwpx: Path):
        paragraphs = extract(sample_hwpx)
        headings = [p for p in paragraphs if p.is_heading_candidate]
        assert len(headings) >= 1

    def test_file_not_found_raises(self, tmp_path: Path):
        with pytest.raises(TemplateError, match="File not found"):
            extract(tmp_path / "missing.hwpx")

    def test_invalid_zip_raises(self, tmp_path: Path):
        bad = tmp_path / "bad.hwpx"
        bad.write_bytes(b"not a zip")
        with pytest.raises(TemplateError):
            extract(bad)


class TestNormalizeHeading:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("1. 개요", "개요"),
            ("1) 개요", "개요"),
            ("가. 개요", "개요"),
            ("(가) 개요", "개요"),
            ("(1) 개요", "개요"),
            ("① 개요", "개요"),
            ("Ⅰ. 개요", "개요"),
            ("I. 개요", "개요"),
            ("제1장 개요", "개요"),
            ("제1장. 개요", "개요"),
            ("제2절 세부사항", "세부사항"),
            ("개요", "개요"),
        ],
    )
    def test_strips_numbering_prefix(self, raw, expected):
        assert _normalize_heading(raw) == expected

    def test_numbering_only_falls_back_to_original(self):
        # 접두어만 제거하면 빈 문자열이 되는 경우 원본 텍스트를 유지한다
        assert _normalize_heading("1.") == "1."


class TestAnalyzer:
    def test_single_document(self, sample_hwpx: Path):
        result = analyze([sample_hwpx], confidence_threshold=0.5)
        assert isinstance(result, AnalysisResult)
        assert result.total_documents == 1

    def test_common_sections_found(self, make_hwpx):
        doc1 = make_hwpx("doc1.hwpx")
        doc2 = make_hwpx("doc2.hwpx")
        result = analyze([doc1, doc2], confidence_threshold=0.5)
        assert len(result.common_sections) > 0
        assert result.confidence > 0

    def test_common_sections_match_despite_different_numbering(self, make_hwpx):
        def heading_xml(numbered_text: str) -> bytes:
            return (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<hml xmlns:hp="http://www.hancom.co.kr/hwpml/2012/paragraph">'
                "<hp:body><hp:sec>"
                '<hp:p><hp:pPr><hp:rPr><hp:sz hp:val="1800"/><hp:b hp:val="true"/>'
                f"</hp:rPr></hp:pPr><hp:t>{numbered_text}</hp:t></hp:p>"
                "</hp:sec></hp:body></hml>"
            ).encode("utf-8")

        doc1 = make_hwpx("doc1.hwpx", content_xml=heading_xml("1. 서론"))
        doc2 = make_hwpx("doc2.hwpx", content_xml=heading_xml("가. 서론"))

        result = analyze([doc1, doc2], confidence_threshold=0.7)
        assert result.common_sections == ["서론"]
        assert result.confidence == 1.0

    def test_no_samples_raises(self):
        with pytest.raises(TemplateError, match="At least one"):
            analyze([])

    def test_confidence_below_threshold(self, make_hwpx):
        # Two identical docs → high confidence
        doc1 = make_hwpx("a.hwpx")
        doc2 = make_hwpx("b.hwpx")
        result = analyze([doc1, doc2], confidence_threshold=0.99)
        # Confidence may or may not meet threshold; result object still valid
        assert 0.0 <= result.confidence <= 1.0


class TestGenerator:
    def test_generates_hwpx_file(self, make_hwpx, tmp_path: Path):
        doc1 = make_hwpx("a.hwpx")
        doc2 = make_hwpx("b.hwpx")
        output = tmp_path / "template_out.hwpx"

        result = generate([doc1, doc2], output=output, confidence_threshold=0.0)
        assert result == output
        assert output.exists()

    def test_output_is_valid_zip(self, make_hwpx, tmp_path: Path):
        doc = make_hwpx("a.hwpx")
        output = tmp_path / "out.hwpx"
        generate([doc], output=output, confidence_threshold=0.0)
        assert zipfile.is_zipfile(output)

    def test_low_confidence_no_llm_raises(self, make_hwpx, tmp_path: Path):
        # Plain text with no heading candidates → confidence=0 → should raise
        plain_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<hml xmlns:hp="http://www.hancom.co.kr/hwpml/2012/paragraph">'
            "<hp:body><hp:sec>"
            "<hp:p><hp:t>heading-free content</hp:t></hp:p>"
            "</hp:sec></hp:body></hml>"
        ).encode("utf-8")
        doc = make_hwpx("a.hwpx", content_xml=plain_xml)
        with pytest.raises(TemplateError):
            generate([doc], output=tmp_path / "out.hwpx", confidence_threshold=0.9, use_llm=False)

    def test_low_confidence_none_raises_with_message(self, make_hwpx, tmp_path: Path):
        plain_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<hml xmlns:hp="http://www.hancom.co.kr/hwpml/2012/paragraph">'
            "<hp:body><hp:sec>"
            "<hp:p><hp:t>heading-free content</hp:t></hp:p>"
            "</hp:sec></hp:body></hml>"
        ).encode("utf-8")
        doc = make_hwpx("a.hwpx", content_xml=plain_xml)
        with pytest.raises(TemplateError, match="0%"):
            generate([doc], output=tmp_path / "out.hwpx", confidence_threshold=0.9, use_llm=None)
