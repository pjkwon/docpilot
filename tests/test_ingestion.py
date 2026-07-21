from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from docpilot.exceptions import IngestionError
from docpilot.ingestion import text as text_ing
from docpilot.ingestion.models import IngestedDocument


class TestTextIngestion:
    def test_basic(self, sample_txt: Path):
        doc = text_ing.ingest(sample_txt)
        assert isinstance(doc, IngestedDocument)
        assert "사업 계획서" in doc.content
        assert doc.mime_type == "text/plain"
        assert doc.source == sample_txt

    def test_file_not_found(self, tmp_path: Path):
        with pytest.raises(IngestionError, match="File not found"):
            text_ing.ingest(tmp_path / "missing.txt")

    def test_unsupported_extension(self, tmp_path: Path):
        bad = tmp_path / "file.xyz"
        bad.write_text("data")
        with pytest.raises(IngestionError, match="Unsupported extension"):
            text_ing.ingest(bad)

    def test_metadata_size(self, sample_txt: Path):
        doc = text_ing.ingest(sample_txt)
        assert doc.metadata["size_bytes"] == sample_txt.stat().st_size


class TestPdfIngestion:
    def test_text_based_pdf(self, tmp_path: Path):
        from docpilot.ingestion import pdf as pdf_ing

        mock_page = MagicMock()
        mock_page.extract_text.return_value = "A" * 200

        mock_pdf = MagicMock()
        mock_pdf.__enter__ = lambda s: s
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_pdf.pages = [mock_page]

        path = tmp_path / "sample.pdf"
        path.write_bytes(b"%PDF-1.4 fake")

        with patch("pdfplumber.open", return_value=mock_pdf):
            doc = pdf_ing.ingest(path)

        assert doc.content == "A" * 200
        assert doc.metadata["ocr"] is False

    def test_file_not_found(self, tmp_path: Path):
        from docpilot.ingestion import pdf as pdf_ing
        with pytest.raises(IngestionError, match="File not found"):
            pdf_ing.ingest(tmp_path / "missing.pdf")

    def test_wrong_extension(self, tmp_path: Path):
        from docpilot.ingestion import pdf as pdf_ing
        bad = tmp_path / "file.txt"
        bad.write_text("x")
        with pytest.raises(IngestionError, match="Expected .pdf"):
            pdf_ing.ingest(bad)


