"""HTML 표/글머리표 렌더링 기능 직접 검증 스크립트 (LLM 미경유).

data/html_table_test_2(ul_style_added).md 원문을 report 템플릿의 플레이스홀더에
그대로 넣고 HwpxBuilder를 직접 호출해 rowspan/colspan 병합 셀과 중첩 글머리표가
실제 hp:tbl / hh:bullets로 렌더링되는지 구조적으로 확인한다.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from docpilot import _assemble_builtin_hwpx  # noqa: E402
from docpilot.builder.hwpx_builder import HwpxBuilder  # noqa: E402

MD_PATH = ROOT / "data" / "html_table_test_2(ul_style_added).md"
OUTPUT = ROOT / "output" / "verify_html_render_v2.hwpx"
OUTPUT.parent.mkdir(exist_ok=True)


def _extract_placeholder_keys(template: Path) -> list[str]:
    import re
    from docpilot.builder.base import PLACEHOLDER_RE

    with zipfile.ZipFile(template) as zf:
        text = zf.read("Contents/section0.xml").decode("utf-8")
    keys = []
    seen = set()
    for m in re.finditer(r"\{\{\??([^}?]+)\??\}\}", text):
        if m.group(1) not in seen:
            seen.add(m.group(1))
            keys.append(m.group(1))
    return keys


def main() -> None:
    template = _assemble_builtin_hwpx("report")
    keys = _extract_placeholder_keys(template)
    print(f"report 템플릿 플레이스홀더: {keys}")

    raw_md = MD_PATH.read_text(encoding="utf-8")
    key = keys[0]
    sections = {k: (raw_md if k == key else f"[{k} 테스트 내용]") for k in keys}

    HwpxBuilder().build(template, sections, OUTPUT)
    print(f"빌드 완료: {OUTPUT}")

    with zipfile.ZipFile(OUTPUT) as zf:
        section_xml = zf.read("Contents/section0.xml").decode("utf-8")
        header_xml = zf.read("Contents/header.xml").decode("utf-8")

    print("\n--- 표 검증 ---")
    print(f"hp:tbl 개수: {section_xml.count('<hp:tbl ')}")
    print(f"rowSpan=\"2\" 존재: {'rowSpan=\"2\"' in section_xml}")
    print(f"colSpan=\"16\" 존재: {'colSpan=\"16\"' in section_xml}")
    print(f"colSpan=\"4\" 존재: {'colSpan=\"4\"' in section_xml}")
    print(f"header=\"1\" 셀 존재: {'header=\"1\"' in section_xml}")

    print("\n--- 글머리표 검증 ---")
    import re
    m = re.search(r'<hh:bullets itemCnt="(\d+)"', header_xml)
    print(f"hh:bullets itemCnt: {m.group(1) if m else 'NOT FOUND'}")
    bullet_chars = re.findall(r'<hh:bullet id="\d+" char="([^"]*)"', header_xml)
    print(f"등록된 글리프: {bullet_chars}")
    bullet_parapr_count = len(re.findall(r'<hh:heading type="BULLET"', header_xml))
    print(f"BULLET paraPr 개수: {bullet_parapr_count}")

    print("\n--- well-formedness (docpilot._validate_hwpx) ---")
    import warnings
    from docpilot import _validate_hwpx
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        _validate_hwpx(OUTPUT)
        if w:
            for warning in w:
                print(f"WARNING: {warning.message}")
        else:
            print("경고 없음 — 통과")


if __name__ == "__main__":
    main()
