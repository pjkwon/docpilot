from __future__ import annotations

import contextlib
import io
import sys
import tempfile
from pathlib import Path

from docpilot.exceptions import IngestionError
from docpilot.ingestion.models import IngestedDocument


def ingest(path: str | Path) -> IngestedDocument:
    path = Path(path)

    if not path.exists():
        raise IngestionError("File not found", detail=str(path))

    if path.suffix.lower() != ".hwp":
        raise IngestionError(f"Expected .hwp, got '{path.suffix}'", detail=str(path))

    if sys.platform != "win32":
        raise IngestionError(
            "HWP 변환은 Windows 전용입니다 (한컴오피스 COM 자동화 사용)",
            detail=f"현재 플랫폼: {sys.platform}",
        )

    try:
        import pyhwpx
    except ImportError as e:
        raise IngestionError(
            "pyhwpx is required: pip install docpilot[hwp]"
        ) from e

    from docpilot.ingestion import hwpx as hwpx_ing

    with tempfile.TemporaryDirectory() as tmp_dir:
        hwpx_path = Path(tmp_dir) / (path.stem + ".hwpx")

        hwp = None
        _buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(_buf), contextlib.redirect_stderr(_buf):
                hwp = pyhwpx.Hwp(visible=False)
                hwp.open(str(path.resolve()))
                hwp.save_as(str(hwpx_path), format="HWPX")
        except Exception as e:
            captured = _buf.getvalue().strip()
            detail = f"{e}\n{captured}" if captured else str(e)
            if type(e).__name__ == "com_error":
                raise IngestionError(
                    "HWP → HWPX 변환 실패 — 한컴오피스(한글)가 설치되지 않았거나 COM 등록이 되지 않은 것으로 보입니다",
                    detail=detail,
                ) from e
            raise IngestionError("HWP → HWPX 변환 실패", detail=detail) from e
        finally:
            if hwp is not None:
                try:
                    hwp.quit()
                except Exception:
                    pass

        if not hwpx_path.exists():
            raise IngestionError("변환된 HWPX 파일이 생성되지 않았습니다", detail=str(hwpx_path))

        doc = hwpx_ing.ingest(hwpx_path)

    return IngestedDocument(
        source=path,
        content=doc.content,
        mime_type="application/haansofthwp",
        metadata={
            **doc.metadata,
            "converted_via": "pyhwpx",
        },
    )
