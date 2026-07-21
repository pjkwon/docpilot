from __future__ import annotations

import json
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

_pilot = None


def _resolve_embed_fn():
    """
    DOCPILOT_EMBED 환경변수에 따라 embed_fn을 반환합니다.

    값 형식:
      (미설정)            → default_embed_fn() — multilingual-e5-base 자동
      bge                 → bge_embed_fn()
      bge:cuda            → bge_embed_fn(device="cuda")
      openai              → openai_embed_fn()  (OPENAI_API_KEY 필요)
      openai:text-embedding-3-large → openai_embed_fn(model=...)
      voyage              → voyage_embed_fn()  (VOYAGE_API_KEY 필요)
      voyage:voyage-3-lite → voyage_embed_fn(model=...)
      sentence            → sentence_embed_fn()
      sentence:intfloat/multilingual-e5-large → sentence_embed_fn(model=...)
    """
    raw = os.environ.get("DOCPILOT_EMBED", "").strip()
    if not raw:
        return None  # DocPilot.__init__ will call default_embed_fn()

    from docpilot.search.embedding import (
        bge_embed_fn, openai_embed_fn, voyage_embed_fn, sentence_embed_fn,
    )

    provider, _, option = raw.partition(":")
    provider = provider.lower()

    match provider:
        case "bge":
            return bge_embed_fn(device=option or "cpu")
        case "openai":
            return openai_embed_fn(model=option) if option else openai_embed_fn()
        case "voyage":
            return voyage_embed_fn(model=option) if option else voyage_embed_fn()
        case "sentence":
            return sentence_embed_fn(model=option) if option else sentence_embed_fn()
        case _:
            import warnings
            warnings.warn(
                f"DOCPILOT_EMBED={raw!r} 값을 인식할 수 없습니다. "
                "기본 임베딩 모델을 사용합니다. "
                "유효한 값: bge, openai, voyage, sentence (콜론으로 옵션 구분 가능)",
                stacklevel=2,
            )
            return None


def _get_pilot():
    global _pilot
    if _pilot is None:
        from docpilot import DocPilot
        _pilot = DocPilot(
            llm=os.environ.get("DOCPILOT_LLM", "claude"),
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
            model=os.environ.get("DOCPILOT_MODEL") or None,
            database_url=os.environ.get("DOCPILOT_DATABASE_URL") or None,
            embed_fn=_resolve_embed_fn(),
        )
    return _pilot


mcp = FastMCP(
    "smart-docgen",
    instructions=(
        "smart-docgen는 RAG/인덱싱 없이 문서 포맷 변환(HWP/HWPX/DOCX)과 템플릿 기반 문서 조립을 "
        "제공합니다. 콘텐츠 작성(데이터 읽기·문장 구성)은 이 서버가 아니라 호출하는 에이전트가 "
        "직접 수행하고, 이 서버는 완성된 텍스트를 실제 문서 파일로 조립하는 역할만 합니다.\n"
        "\n"
        "## 문서 생성 워크플로 (describe_template → fill_template)\n"
        "1단계: describe_template(template) 호출 → 정확한 섹션 키, 섹션별 규칙/설명, "
        "채워야 할 예시 dict 형태를 확인합니다.\n"
        "2단계: 데이터를 직접 읽고 각 섹션에 들어갈 내용을 작성합니다.\n"
        "3단계: fill_template(template, sections, output) 호출 → 작성한 내용을 템플릿에 "
        "기계적으로 채워 실제 문서 파일(.hwpx/.docx/.pdf)을 생성합니다. LLM 호출이 없으므로 "
        "섹션 키가 정확히 일치해야 하며, 누락되거나 템플릿에 없는 키는 오류로 반환됩니다.\n"
        "\n"
        "## 포맷 변환 (convert_document)\n"
        "한컴오피스(한글) COM 자동화로 .hwp/.hwpx → .docx, .hwp → .hwpx 변환을 수행합니다. "
        "Windows + 한컴오피스 설치 환경에서만 동작합니다.\n"
        "\n"
        "## 템플릿 생성 (generate_template)\n"
        "샘플 HWPX 문서 여러 개를 분석해 재사용 가능한 {{placeholder}} 템플릿을 만듭니다.\n"
        "\n"
        "## 내장 템플릿\n"
        "report   — 일반 보고서: 보고서 제목, 작성일, 작성자/부서, "
        "섹션1 제목, 섹션1 내용, 섹션2 제목, 섹션2 내용, 표 삽입 위치, 결론, 결론 내용\n"
        "gonmun   — 공문: 기관명, 수신자, 경유, 제목, 본문1, 본문2, 표 또는 상세내용, "
        "직위 성명, 시행번호, 시행일자, 우편번호, 주소, 홈페이지, 전화번호, 팩스번호, 이메일\n"
        "minutes  — 회의록: 회의록 제목, 일시, 장소, 참석자 목록, 작성자, "
        "안건 내용, 논의 내용, 결정 사항, 향후 조치 사항\n"
        "proposal — 제안서: 사업 개요, 추진 배경, 추진 근거\n"
    ),
)


_CONVERSIONS = {
    (".hwp", ".docx"): "docx",
    (".hwpx", ".docx"): "docx",
    (".hwp", ".hwpx"): "hwpx",
}
_DEFAULT_OUTPUT_EXT = {".hwp": ".docx", ".hwpx": ".docx", ".docx": ".hwpx"}

# 알려진 이슈: 일부 한컴오피스 설치 환경에서 COM을 통한 DOCX 가져오기(Open) 자체가 실패한다.
# 재현 확인됨(format 힌트·visible 모드·forceopen 옵션 무관하게 항상 실패). 원인 불명이라 보류 중.
_KNOWN_UNSUPPORTED = {(".docx", ".hwpx")}


@mcp.tool()
def convert_document(source: str, output: str | None = None) -> str:
    """한컴오피스(한글) COM 자동화로 문서 포맷을 변환합니다.

    지원 방향: .hwp/.hwpx → .docx, .hwp → .hwpx
    Windows + 한컴오피스(한글)가 설치된 환경에서만 동작합니다.

    [알려진 이슈] .docx → .hwpx는 미지원입니다. 일부 한컴오피스 설치 환경에서
    COM을 통한 DOCX 가져오기(Open) 자체가 실패하는 문제가 재현되어 보류 중입니다.
    한/글에서 파일 > 열기로 수동으로 열어 다른 이름으로 저장(hwpx)하세요.

    Args:
        source: 변환할 .hwp, .hwpx 또는 .docx 파일 경로
        output: 출력 파일 경로 (미지정 시 source와 같은 폴더에 기본 반대 포맷으로 저장 — .hwp/.hwpx는 .docx, .hwp는 .hwpx)
    """
    from docpilot.builder.hwp_convert import convert_to_docx, convert_to_hwpx
    from docpilot.exceptions import DocPilotError

    src = Path(source)
    if not src.exists():
        return f"파일을 찾을 수 없습니다: {source}"

    src_ext = src.suffix.lower()
    if src_ext not in _DEFAULT_OUTPUT_EXT:
        return f"지원하지 않는 입력 형식입니다: {src_ext} (.hwp, .hwpx, .docx만 가능)"

    out = Path(output) if output else src.with_suffix(_DEFAULT_OUTPUT_EXT[src_ext])
    out_ext = out.suffix.lower()

    if (src_ext, out_ext) in _KNOWN_UNSUPPORTED:
        return (
            f"{src_ext} → {out_ext} 변환은 현재 지원하지 않습니다 (알려진 이슈).\n"
            "일부 한컴오피스 설치 환경에서 COM을 통한 DOCX 가져오기(Open) 자체가 실패하는 "
            "문제가 재현되어 보류 중입니다. 한/글에서 파일 > 열기로 수동으로 열어 "
            "다른 이름으로 저장(hwpx)하세요."
        )

    target = _CONVERSIONS.get((src_ext, out_ext))
    if target is None:
        return f"지원하지 않는 변환입니다: {src_ext} → {out_ext}"

    convert_fn, label = (convert_to_docx, "DOCX") if target == "docx" else (convert_to_hwpx, "HWPX")

    try:
        result = convert_fn(src, out)
    except DocPilotError as e:
        return f"변환 실패: {e}"

    return f"{label} 변환 완료: {result}"


def _default_output(template: str, ext: str = ".hwpx") -> str:
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    tpl_ext = Path(template).suffix.lower()
    if tpl_ext in (".docx", ".pdf"):
        ext = tpl_ext
    docs = Path.home() / "Documents"
    docs.mkdir(exist_ok=True)
    return str(docs / f"docpilot_{ts}{ext}")


@mcp.tool()
def describe_template(template: str) -> str:
    """템플릿의 채움 구조를 확인합니다. LLM/RAG 호출이 없어 즉시 반환됩니다.

    fill_template() 호출 전에 반드시 사용하세요 — 정확한 섹션 키, 섹션별 작성 규칙/설명,
    목록(가변) 섹션 여부, 그리고 fill_template에 그대로 넘길 수 있는 예시 dict 형태를 알려줍니다.

    Args:
        template: 템플릿 파일 경로 또는 내장 템플릿 이름 (report/gonmun/minutes/proposal)
    """
    from docpilot import describe_template as _describe_template
    from docpilot.exceptions import DocPilotError

    try:
        info = _describe_template(template)
    except DocPilotError as e:
        return f"템플릿 구조 확인 실패: {e}"

    lines = [f"템플릿: {info['template']}"]
    if info["instructions"]:
        lines.append(f"\n[전역 작성 지침]\n{info['instructions']}")

    lines.append("\n[섹션 목록]")
    for s in info["sections"]:
        tags = []
        if s["is_list"]:
            tags.append(f"목록·최대 {s['group_max']}개" if s["group_max"] else "목록·가변개수")
        if s["optional"]:
            tags.append("선택")
        tag_str = f"  [{', '.join(tags)}]" if tags else ""
        lines.append(f'- "{s["name"]}"{tag_str}')
        if s["rule"]:
            lines.append(f"    규칙: {s['rule']}")
        if s["description"]:
            lines.append(f"    설명: {s['description']}")
        if s["style_hint"]:
            lines.append(f"    스타일 힌트(분량 가늠용): {s['style_hint']}")

    example_json = json.dumps(info["example"], ensure_ascii=False, indent=2)
    lines.append(f"\n[fill_template()의 sections 인자에 그대로 채워 넣을 예시]\n{example_json}")

    return "\n".join(lines)


@mcp.tool()
def fill_template(
    template: str,
    sections: dict[str, str | list[str]],
    output: str | None = None,
) -> str:
    """작성된 섹션 내용을 템플릿에 채워 문서를 생성합니다. LLM/RAG 호출 없이 순수 기계적으로 조립됩니다.

    콘텐츠는 이 도구를 호출하기 전에 직접 작성하세요 — 데이터를 읽고 각 섹션에 들어갈
    텍스트를 완성한 뒤 sections dict로 전달합니다. 정확한 섹션 키는 describe_template()으로
    먼저 확인하세요. 키가 누락되었거나 템플릿에 없는 키가 있으면 문서를 만들지 않고 오류를 반환합니다.

    Args:
        template: 템플릿 파일 경로 또는 내장 템플릿 이름 (report/gonmun/minutes/proposal)
        sections: {"섹션명": "내용", ...} — 목록 섹션은 list[str] 또는 개행(\\n)으로 구분한 문자열
        output: 출력 파일 경로 — 확장자가 출력 형식을 결정합니다 (.hwpx / .pdf / .docx).
                미지정 시 ~/Documents/docpilot_YYYYMMDD_HHMMSS.hwpx 에 저장됩니다.
    """
    from docpilot import fill_template as _fill_template
    from docpilot.exceptions import DocPilotError

    if output is None:
        output = _default_output(template)

    try:
        out_path = _fill_template(template, sections, output)
    except DocPilotError as e:
        return f"문서 생성 실패: {e}"

    return f"문서 생성 완료: {out_path}"


@mcp.tool()
def generate_template(
    samples: list[str],
    output: str,
    use_llm: bool | None = None,
) -> str:
    """샘플 HWPX 문서들을 분석하여 재사용 가능한 템플릿을 생성합니다.

    Args:
        samples: 분석할 샘플 HWPX 파일 경로 목록 (2개 이상 권장)
        output: 생성할 템플릿 파일 경로 (.hwpx)
        use_llm: LLM 보조 사용 여부 (None이면 공통 구조 신뢰도에 따라 자동 결정)
    """
    result_path = _get_pilot().generate_template(
        samples=samples,
        output=output,
        use_llm=use_llm,
    )
    return f"템플릿 생성 완료: {result_path}"


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
