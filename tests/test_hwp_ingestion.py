from __future__ import annotations

import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from docpilot.exceptions import IngestionError
from docpilot.ingestion import hwp as hwp_ing
from docpilot.ingestion.models import IngestedDocument

_HWPX_CONTENT = """<?xml version="1.0" encoding="UTF-8"?>
<hml xmlns:hp="http://www.hancom.co.kr/hwpml/2012/paragraph">
  <hp:body>
    <hp:sec>
      <hp:p><hp:t>변환된 본문</hp:t></hp:p>
    </hp:sec>
  </hp:body>
</hml>""".encode("utf-8")


def _write_hwpx(path: Path) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/hwp+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("Contents/content.hml", _HWPX_CONTENT)
        zf.writestr("META-INF/container.xml", b"<container/>")


def _mock_pyhwpx(save_as_side_effect=None) -> MagicMock:
    """pyhwpx 모듈 전체를 mock. save_as_side_effect 미지정 시 아무 파일도 생성하지 않음."""
    mock_module = MagicMock()
    mock_hwp = MagicMock()
    mock_module.Hwp.return_value = mock_hwp
    if save_as_side_effect is not None:
        mock_hwp.save_as.side_effect = save_as_side_effect
    return mock_module


class TestHwpIngestion:
    def test_basic(self, tmp_path: Path):
        hwp_path = tmp_path / "sample.hwp"
        hwp_path.write_bytes(b"HWP binary fake")

        def _fake_save_as(out_path, format):
            _write_hwpx(Path(out_path))

        mock_module = _mock_pyhwpx(save_as_side_effect=_fake_save_as)

        with patch.dict("sys.modules", {"pyhwpx": mock_module}):
            doc = hwp_ing.ingest(hwp_path)

        assert isinstance(doc, IngestedDocument)
        assert doc.source == hwp_path
        assert doc.mime_type == "application/haansofthwp"
        assert "변환된 본문" in doc.content
        assert doc.metadata["converted_via"] == "pyhwpx"
        mock_module.Hwp.assert_called_once_with(visible=False)
        mock_module.Hwp.return_value.open.assert_called_once_with(str(hwp_path.resolve()))
        mock_module.Hwp.return_value.quit.assert_called_once()

    def test_file_not_found(self, tmp_path: Path):
        with pytest.raises(IngestionError, match="File not found"):
            hwp_ing.ingest(tmp_path / "missing.hwp")

    def test_wrong_extension(self, tmp_path: Path):
        bad = tmp_path / "file.hwpx"
        bad.write_bytes(b"fake")
        with pytest.raises(IngestionError, match="Expected .hwp"):
            hwp_ing.ingest(bad)

    def test_pyhwpx_not_installed(self, tmp_path: Path):
        hwp_path = tmp_path / "sample.hwp"
        hwp_path.write_bytes(b"HWP binary fake")

        with patch.dict("sys.modules", {"pyhwpx": None}):
            with pytest.raises(IngestionError, match="pyhwpx is required"):
                hwp_ing.ingest(hwp_path)

    def test_conversion_error(self, tmp_path: Path):
        hwp_path = tmp_path / "sample.hwp"
        hwp_path.write_bytes(b"HWP binary fake")

        mock_module = _mock_pyhwpx(save_as_side_effect=RuntimeError("COM error: 파일 열기 실패"))

        with patch.dict("sys.modules", {"pyhwpx": mock_module}):
            with pytest.raises(IngestionError, match="HWP → HWPX 변환 실패"):
                hwp_ing.ingest(hwp_path)

    def test_hwpx_not_created(self, tmp_path: Path):
        """save_as가 예외 없이 반환했지만 파일이 존재하지 않는 경우."""
        hwp_path = tmp_path / "sample.hwp"
        hwp_path.write_bytes(b"HWP binary fake")

        mock_module = _mock_pyhwpx()  # save_as는 아무 것도 하지 않음

        with patch.dict("sys.modules", {"pyhwpx": mock_module}):
            with pytest.raises(IngestionError, match="변환된 HWPX 파일이 생성되지 않았습니다"):
                hwp_ing.ingest(hwp_path)

    def test_non_windows(self, tmp_path: Path):
        hwp_path = tmp_path / "sample.hwp"
        hwp_path.write_bytes(b"HWP binary fake")

        with patch("sys.platform", "linux"):
            with pytest.raises(IngestionError, match="Windows 전용"):
                hwp_ing.ingest(hwp_path)

    def test_hangul_not_installed(self, tmp_path: Path):
        """한컴오피스 미설치 시 COM 에러를 명확한 메시지로 변환해야 한다."""
        hwp_path = tmp_path / "sample.hwp"
        hwp_path.write_bytes(b"HWP binary fake")

        com_error = type("com_error", (Exception,), {})
        mock_module = _mock_pyhwpx(save_as_side_effect=com_error("COM error: 클래스가 등록되지 않았습니다"))

        with patch.dict("sys.modules", {"pyhwpx": mock_module}):
            with pytest.raises(IngestionError, match="한컴오피스"):
                hwp_ing.ingest(hwp_path)

    def test_quit_called_on_failure(self, tmp_path: Path):
        """변환 실패해도 finally에서 hwp.quit()이 반드시 호출되어야 한다."""
        hwp_path = tmp_path / "sample.hwp"
        hwp_path.write_bytes(b"HWP binary fake")

        mock_module = _mock_pyhwpx(save_as_side_effect=RuntimeError("COM error"))

        with patch.dict("sys.modules", {"pyhwpx": mock_module}):
            with pytest.raises(IngestionError):
                hwp_ing.ingest(hwp_path)

        mock_module.Hwp.return_value.quit.assert_called_once()
