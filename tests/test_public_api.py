"""패키지 최상위 공개 API와 하위 호환 이름."""
from __future__ import annotations

from pathlib import Path

import docpilot


def test_extract_placeholders_accepts_path(hwpx_template: Path):
    assert docpilot.extract_placeholders(hwpx_template) == ["서론", "결론"]


def test_extract_placeholders_accepts_builtin_template_name():
    keys = docpilot.extract_placeholders("report")

    expected = [s["name"] for s in docpilot.describe_template("report")["sections"]]
    assert keys == expected


def test_public_names_exported():
    for name in docpilot.__all__:
        assert hasattr(docpilot, name), name


def test_legacy_private_names_still_importable():
    """docpilot-ui·scripts가 예전 버전 기준으로 import하는 내부 이름 — 분리 후에도 유지돼야 한다."""
    from docpilot import (  # noqa: F401
        _assemble_builtin_hwpx,
        _extract_placeholders,
        _infer_sections_from_content,
        _ingest_instructions_doc,
        _resolve_template_path,
        _validate_hwpx,
    )
