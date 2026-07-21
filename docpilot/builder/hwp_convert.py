"""한글/HWP/HWPX/DOCX 간 파일 포맷 변환 (한컴오피스 COM 자동화, Windows 전용)."""
from __future__ import annotations

import contextlib
import io
import sys
import warnings
from pathlib import Path

from docpilot.exceptions import ConversionError


def _com_convert(path: Path, output: Path, save_format: str, label: str) -> Path:
    if sys.platform != "win32":
        raise ConversionError(
            f"{label} 변환은 Windows 전용입니다 (한컴오피스 COM 자동화 사용)",
            detail=f"현재 플랫폼: {sys.platform}",
        )

    try:
        import pyhwpx
    except ImportError as e:
        raise ConversionError(
            "pyhwpx가 필요합니다: pip install pyhwpx — core dependency라 "
            "정상적인 docpilot 설치 환경에서는 보통 발생하지 않는 상황입니다"
        ) from e

    output.parent.mkdir(parents=True, exist_ok=True)

    hwp = None
    _buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(_buf), contextlib.redirect_stderr(_buf):
            hwp = pyhwpx.Hwp(visible=False)
            if not hwp.open(str(path.resolve())):
                raise ConversionError(
                    "파일을 여는 데 실패했습니다 (한컴오피스가 이 형식을 가져오지 못함)",
                    detail=str(path),
                )
            if not hwp.save_as(str(output.resolve()), format=save_format):
                raise ConversionError(
                    f"{label} 형식으로 저장하는 데 실패했습니다", detail=str(output)
                )
    except ConversionError:
        raise
    except Exception as e:
        captured = _buf.getvalue().strip()
        detail = f"{e}\n{captured}" if captured else str(e)
        if type(e).__name__ == "com_error":
            raise ConversionError(
                f"{label} 변환 실패 — 한컴오피스(한글)가 설치되지 않았거나 COM 등록이 되지 않은 것으로 보입니다",
                detail=detail,
            ) from e
        raise ConversionError(f"{label} 변환 실패", detail=detail) from e
    finally:
        if hwp is not None:
            try:
                hwp.quit()
            except Exception:
                pass

    if not output.exists():
        raise ConversionError(f"변환된 {label} 파일이 생성되지 않았습니다", detail=str(output))

    return output


def convert_to_docx(path: str | Path, output: str | Path) -> Path:
    """한/글 COM 자동화로 HWP 또는 HWPX 파일을 DOCX로 변환합니다."""
    path = Path(path)
    output = Path(output)

    if not path.exists():
        raise ConversionError("파일을 찾을 수 없습니다", detail=str(path))
    if path.suffix.lower() not in (".hwp", ".hwpx"):
        raise ConversionError(
            f"지원하지 않는 입력 형식입니다: {path.suffix} (.hwp 또는 .hwpx만 가능)",
            detail=str(path),
        )

    return _com_convert(path, output, save_format="OOXML", label="DOCX")


def convert_to_hwpx(path: str | Path, output: str | Path) -> Path:
    """한/글 COM 자동화로 HWP 또는 DOCX 파일을 HWPX로 변환합니다."""
    path = Path(path)
    output = Path(output)

    if not path.exists():
        raise ConversionError("파일을 찾을 수 없습니다", detail=str(path))
    if path.suffix.lower() not in (".hwp", ".docx"):
        raise ConversionError(
            f"지원하지 않는 입력 형식입니다: {path.suffix} (.hwp 또는 .docx만 가능)",
            detail=str(path),
        )

    if path.suffix.lower() == ".docx":
        warnings.warn(
            "DOCX → HWPX 변환은 일부 한컴오피스 설치 환경에서 COM을 통한 DOCX 가져오기(Open) "
            "자체가 실패하는 알려진 이슈가 있습니다. 실패 시 한/글에서 파일 > 열기로 수동 변환하세요.",
            stacklevel=2,
        )

    return _com_convert(path, output, save_format="HWPX", label="HWPX")
