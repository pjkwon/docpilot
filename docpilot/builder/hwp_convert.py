"""HWP/HWPX → DOCX 변환 (한컴오피스 COM 자동화, Windows 전용)."""
from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path

from docpilot.exceptions import ConversionError

_SUPPORTED_INPUT = (".hwp", ".hwpx")


def convert_to_docx(path: str | Path, output: str | Path) -> Path:
    """한/글 COM 자동화로 HWP 또는 HWPX 파일을 DOCX로 변환합니다.

    Windows + 한컴오피스(한글) 설치 환경에서만 동작합니다.
    """
    path = Path(path)
    output = Path(output)

    if not path.exists():
        raise ConversionError("파일을 찾을 수 없습니다", detail=str(path))
    if path.suffix.lower() not in _SUPPORTED_INPUT:
        raise ConversionError(
            f"지원하지 않는 입력 형식입니다: {path.suffix}", detail=str(path)
        )

    if sys.platform != "win32":
        raise ConversionError(
            "HWP/HWPX → DOCX 변환은 Windows 전용입니다 (한컴오피스 COM 자동화 사용)",
            detail=f"현재 플랫폼: {sys.platform}",
        )

    try:
        import pyhwpx
    except ImportError as e:
        raise ConversionError(
            "pyhwpx가 필요합니다: pip install docpilot[hwp]"
        ) from e

    output.parent.mkdir(parents=True, exist_ok=True)

    hwp = None
    _buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(_buf), contextlib.redirect_stderr(_buf):
            hwp = pyhwpx.Hwp(visible=False)
            hwp.open(str(path.resolve()))
            hwp.save_as(str(output.resolve()), format="OOXML")
    except Exception as e:
        captured = _buf.getvalue().strip()
        detail = f"{e}\n{captured}" if captured else str(e)
        if type(e).__name__ == "com_error":
            raise ConversionError(
                "DOCX 변환 실패 — 한컴오피스(한글)가 설치되지 않았거나 COM 등록이 되지 않은 것으로 보입니다",
                detail=detail,
            ) from e
        raise ConversionError("DOCX 변환 실패", detail=detail) from e
    finally:
        if hwp is not None:
            try:
                hwp.quit()
            except Exception:
                pass

    if not output.exists():
        raise ConversionError("변환된 DOCX 파일이 생성되지 않았습니다", detail=str(output))

    return output
