"""로컬 Ollama 모델 비교 벤치마크 — 기본값은 qwen2.5:7b vs gemma4:e4b.

data/minutes.docx 를 템플릿으로, data/2025.11.19 도장 설비 업체 화상회의.docx 를
소스로 색인 → RAG 검색까지는 한 번만 돌리고, 그 결과를 여러 Ollama 모델에 동일하게
넣어 처리시간·토큰 사용량·섹션별 생성 내용을 비교한다.

사용법:
    uv run python scripts/llm_benchmark.py
    uv run python scripts/llm_benchmark.py --models qwen2.5:7b,gemma4:e4b
    uv run python scripts/llm_benchmark.py --models gemma4:e4b --num-ctx 8192
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent.parent
TEMPLATE = ROOT / "data" / "minutes.docx"
SOURCE = ROOT / "data" / "2025.11.19 도장 설비 업체 화상회의.docx"
OUTPUT = ROOT / "output" / "llm_benchmark.hwpx"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--models", default="qwen2.5:7b,gemma4:e4b", help="비교할 Ollama 모델 태그 (쉼표 구분)"
    )
    parser.add_argument(
        "--base-url", default=None,
        help="Ollama base URL (기본: OLLAMA_BASE_URL 환경변수 또는 http://localhost:11434/v1)",
    )
    parser.add_argument(
        "--num-ctx", type=int, default=None,
        help="모델별 num_ctx (미지정 시 Ollama 서버 기본값 그대로 사용)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    for p in (TEMPLATE, SOURCE):
        if not p.exists():
            print(f"[오류] 파일 없음: {p}")
            sys.exit(1)

    model_tags = [m.strip() for m in args.models.split(",") if m.strip()]
    if len(model_tags) < 2:
        print("[오류] --models에 비교할 모델을 2개 이상 쉼표로 구분해 넘기세요.")
        sys.exit(1)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    # 소스 파일만 담은 임시 data_folder — 템플릿(minutes.docx)이 검색 대상에 섞이지 않도록 분리
    tmp_dir = Path(tempfile.mkdtemp(prefix="docpilot_llm_bench_"))
    try:
        shutil.copy2(SOURCE, tmp_dir)

        import docpilot
        from docpilot.mapping.openai_compat import OllamaMapper

        mappers = {
            tag: OllamaMapper(model=tag, base_url=args.base_url, num_ctx=args.num_ctx)
            for tag in model_tags
        }

        pilot = docpilot.DocPilot(llm="ollama", model=model_tags[0], base_url=args.base_url)

        print(f"비교 모델: {', '.join(model_tags)}")
        print(f"템플릿   : {TEMPLATE.name}")
        print(f"소스     : {SOURCE.name}")
        print()

        report = pilot.benchmark(
            data_folder=tmp_dir,
            template=TEMPLATE,
            output=OUTPUT,
            mappers=mappers,
        )
        print(report)

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
