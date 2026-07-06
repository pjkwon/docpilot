"""docpilot 라이브러리를 감싸는 CLI — 문서 포맷 변환 및 플레이스홀더 템플릿 문서 생성.

사용법:
    python docpilot_cli.py convert <source> [--output PATH]
    python docpilot_cli.py generate --data FOLDER --template PATH_OR_NAME --output PATH
                                     [--reindex] [--extra-instructions TEXT]
                                     [--instructions-doc PATH] [--top-k N]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_CONVERSIONS = {
    (".hwp", ".docx"): "docx",
    (".hwpx", ".docx"): "docx",
    (".hwp", ".hwpx"): "hwpx",
}
_DEFAULT_OUTPUT_EXT = {".hwp": ".docx", ".hwpx": ".docx", ".docx": ".hwpx"}
# 알려진 이슈: 일부 한컴오피스 설치 환경에서 COM을 통한 DOCX 가져오기(Open)가 실패한다.
# docpilot README의 "알려진 이슈" 참고. 원인 불명이라 보류 중.
_KNOWN_UNSUPPORTED = {(".docx", ".hwpx")}


def cmd_convert(args: argparse.Namespace) -> int:
    from docpilot.builder.hwp_convert import convert_to_docx, convert_to_hwpx
    from docpilot.exceptions import DocPilotError

    src = Path(args.source)
    if not src.exists():
        print(f"[오류] 파일을 찾을 수 없습니다: {src}")
        return 1

    src_ext = src.suffix.lower()
    if src_ext not in _DEFAULT_OUTPUT_EXT:
        print(f"[오류] 지원하지 않는 입력 형식입니다: {src_ext} (.hwp, .hwpx, .docx만 가능)")
        return 1

    out = Path(args.output) if args.output else src.with_suffix(_DEFAULT_OUTPUT_EXT[src_ext])
    out_ext = out.suffix.lower()

    if (src_ext, out_ext) in _KNOWN_UNSUPPORTED:
        print(
            f"[미지원] {src_ext} → {out_ext} 변환은 현재 지원하지 않습니다 (알려진 이슈).\n"
            "일부 한컴오피스 설치 환경에서 COM을 통한 DOCX 가져오기(Open) 자체가 실패하는 "
            "문제가 재현되어 보류 중입니다. 한/글에서 파일 > 열기로 수동으로 열어 "
            "다른 이름으로 저장(hwpx)하세요."
        )
        return 1

    target = _CONVERSIONS.get((src_ext, out_ext))
    if target is None:
        print(f"[오류] 지원하지 않는 변환입니다: {src_ext} → {out_ext}")
        return 1

    convert_fn = convert_to_docx if target == "docx" else convert_to_hwpx
    try:
        result = convert_fn(src, out)
    except DocPilotError as e:
        print(f"[실패] {e}")
        return 1

    print(f"변환 완료: {result}")
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    import os
    import docpilot

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("[오류] ANTHROPIC_API_KEY 환경변수가 필요합니다.")
        return 1

    pilot = docpilot.DocPilot(llm="claude", api_key=api_key)

    try:
        result = pilot.generate(
            data_folder=args.data,
            template=args.template,
            output=args.output,
            reindex=args.reindex,
            extra_instructions=args.extra_instructions,
            instructions_doc=args.instructions_doc,
            top_k=args.top_k,
        )
    except Exception as e:
        print(f"[실패] {e}")
        return 1

    print(f"문서 생성 완료: {result.path}")
    print(
        f"모델: {result.model} | 입력 {result.input_tokens:,} + 출력 {result.output_tokens:,} 토큰"
        f" | {result.elapsed_seconds:.1f}초"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="docpilot CLI — 문서 변환 및 템플릿 기반 문서 생성")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_convert = sub.add_parser("convert", help="hwp/hwpx/docx 파일 포맷 변환")
    p_convert.add_argument("source", help="변환할 파일 경로")
    p_convert.add_argument("--output", help="출력 파일 경로 (미지정 시 기본 반대 포맷으로 같은 폴더에 저장)")
    p_convert.set_defaults(func=cmd_convert)

    p_generate = sub.add_parser("generate", help="데이터 폴더 + 플레이스홀더 템플릿으로 문서 생성")
    p_generate.add_argument("--data", required=True, help="데이터 폴더 경로")
    p_generate.add_argument("--template", required=True, help="템플릿 파일 경로(.hwpx/.docx/.pdf) 또는 내장 템플릿 이름")
    p_generate.add_argument("--output", required=True, help="출력 파일 경로")
    p_generate.add_argument("--reindex", action="store_true", help="데이터 폴더 강제 재인덱싱")
    p_generate.add_argument("--extra-instructions", default=None, help="추가 작성 지침 문자열")
    p_generate.add_argument("--instructions-doc", default=None, help="작성 지침으로 쓸 파일 경로 (RFP 등)")
    p_generate.add_argument("--top-k", type=int, default=10, help="RAG 검색 청크 수 (기본 10)")
    p_generate.set_defaults(func=cmd_generate)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
