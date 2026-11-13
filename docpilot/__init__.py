"""smart-docgen — 데이터와 템플릿을 넣으면 LLM이 내용을 채운 문서(HWPX/DOCX/PDF)를 만든다.

공개 API는 이 패키지 최상위에서 import한다. 구현은 모듈별로 나뉘어 있다:
  pilot             — DocPilot (인덱싱 → 검색 → LLM 매핑 → 빌드 파이프라인)
  assembly          — LLM 없이 템플릿 조회·채우기 (describe_template / fill_template / retrieve_context)
  template_resolver — 템플릿 이름·경로 해석, 섹션 메타데이터 병합, Reference Mode
  placeholders      — {{placeholder}} 추출·변환
  extras            — 데이터 폴더에 필요한 extras 안내
"""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from dotenv import load_dotenv

try:
    __version__ = version("smart-docgen")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"

load_dotenv()

from docpilot.assembly import (
    RetrievedContext,
    describe_template,
    extract_placeholders,
    fill_template,
    retrieve_context,
)
from docpilot.extras import suggest_extras
from docpilot.pilot import DocPilot, GenerateResult
from docpilot.placeholders import convert_to_list_placeholder

# 하위 호환 — 예전 버전에서 패키지 최상위에 있던 내부 함수들. docpilot-ui·scripts 등이 아직
# 이 이름으로 import하므로 남겨 둔다. 새 코드는 위의 공개 API(extract_placeholders 등)를 쓸 것.
from docpilot.assembly import _validate_hwpx as _validate_hwpx
from docpilot.placeholders import _extract_placeholders as _extract_placeholders
from docpilot.template_resolver import (
    _assemble_builtin_hwpx as _assemble_builtin_hwpx,
    _infer_sections_from_content as _infer_sections_from_content,
    _ingest_instructions_doc as _ingest_instructions_doc,
    _resolve_template_path as _resolve_template_path,
)

__all__ = [
    "DocPilot",
    "GenerateResult",
    "RetrievedContext",
    "convert_to_list_placeholder",
    "describe_template",
    "extract_placeholders",
    "fill_template",
    "retrieve_context",
    "suggest_extras",
]
