"""
0617_제주학회_발표정리.md → 보고서 HWPX 생성

실행:
    uv run python scripts/gen_학회보고서.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT   = Path(__file__).parent.parent
SOURCE = ROOT / "data" / "0617_제주학회_발표정리.md"
OUTPUT = ROOT / "output" / "0617_제주학회_발표정리.hwpx"

EXTRA_INSTRUCTIONS = (
    "학회 발표 정리 내용을 기반으로 공식 출장·학회 참석 보고서 형식으로 작성하세요. "
    "발표 순서와 핵심 내용, 질의응답 요약을 포함하되 간결하고 명확하게 기술하세요. "
    "경어체(~하였습니다, ~입니다)로 작성하세요."
)


def main() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("[오류] ANTHROPIC_API_KEY 환경변수가 필요합니다.")
        sys.exit(1)

    if not SOURCE.exists():
        print(f"[오류] 소스 파일 없음: {SOURCE}")
        sys.exit(1)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    import docpilot
    pilot = docpilot.DocPilot(llm="claude", api_key=api_key)

    tmp_dir = tempfile.mkdtemp(prefix="docpilot_학회_")
    try:
        shutil.copy2(SOURCE, tmp_dir)
        print(f"소스   : {SOURCE.name}")
        print(f"출력   : {OUTPUT}")
        print(f"템플릿 : report (내장)")
        print()

        t0 = time.perf_counter()
        result = pilot.generate(
            data_folder=tmp_dir,
            template="report",
            output=OUTPUT,
            reindex=True,
            extra_instructions=EXTRA_INSTRUCTIONS,
        )
        elapsed = time.perf_counter() - t0

        print(f"완료   : {OUTPUT}")
        print(f"소요   : {elapsed:.1f}s")
        print(f"모델   : {result.model}")
        print(f"토큰   : 입력 {result.input_tokens:,} / 출력 {result.output_tokens:,}")

    except Exception as e:
        print(f"\n[실패] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
