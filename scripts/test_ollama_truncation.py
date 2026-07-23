"""
Ollama(qwen2.5:7b) RAG 파이프라인에서 JSON 응답이 잘리는지 재현하는 스크립트.

data/minutes.docx 를 템플릿으로, data/2025.11.19 도장 설비 업체 화상회의.docx 를
소스로 색인 → RAG 검색 → LLM 매핑 → 문서 생성까지 실제 파이프라인을 그대로 태운다.
잘림(truncated)이 감지되면 docpilot.mapping.openai_compat 로거가 WARNING으로
finish_reason / input_tokens / output_tokens / 응답 끝부분을 출력한다.

실행:
    uv run python scripts/test_ollama_truncation.py
    uv run python scripts/test_ollama_truncation.py --model qwen2.5:7b --top-k 10
"""
from __future__ import annotations

import argparse
import logging
import shutil
import sys
import tempfile
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")

ROOT = Path(__file__).parent.parent
TEMPLATE = ROOT / "data" / "minutes.docx"
SOURCE = ROOT / "data" / "2025.11.19 도장 설비 업체 화상회의.docx"
OUTPUT = ROOT / "output" / "minutes_from_video_meeting.docx"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--model", default="qwen2.5:7b", help="Ollama 모델 태그")
    parser.add_argument(
        "--base-url", default=None,
        help="Ollama base URL (기본: OLLAMA_BASE_URL 환경변수 또는 http://localhost:11434/v1)",
    )
    parser.add_argument("--top-k", type=int, default=10, help="RAG 검색 결과 청크 개수")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    for p in (TEMPLATE, SOURCE):
        if not p.exists():
            print(f"[오류] 파일 없음: {p}")
            sys.exit(1)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    # 소스 파일만 담은 임시 data_folder — 템플릿(minutes.docx)이 검색 대상에 섞이지 않도록 분리
    tmp_dir = Path(tempfile.mkdtemp(prefix="docpilot_ollama_test_"))
    try:
        shutil.copy2(SOURCE, tmp_dir)

        import docpilot
        pilot = docpilot.DocPilot(llm="ollama", model=args.model, base_url=args.base_url)

        print(f"모델   : {args.model}")
        print(f"템플릿 : {TEMPLATE.name}")
        print(f"소스   : {SOURCE.name}")
        print(f"출력   : {OUTPUT}")
        print()

        t0 = time.perf_counter()
        try:
            result = pilot.generate(
                data_folder=tmp_dir,
                template=TEMPLATE,
                output=OUTPUT,
                reindex=True,
                top_k=args.top_k,
            )
        except Exception as e:
            elapsed = time.perf_counter() - t0
            print(f"\n[실패] ({elapsed:.1f}s) {e}")
            detail = getattr(e, "detail", None)
            if detail:
                print(f"[상세] {detail}")
            sys.exit(1)

        elapsed = time.perf_counter() - t0
        print(f"\n[완료] {result}")
        print(f"소요   : {elapsed:.1f}s")
        print(f"모델   : {result.model}")
        print(f"토큰   : 입력 {result.input_tokens:,} / 출력 {result.output_tokens:,}")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
