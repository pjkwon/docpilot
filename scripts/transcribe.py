"""
오디오 파일 일괄 전사 스크립트
실행: uv run python scripts/transcribe.py [입력폴더] [출력폴더]
기본값: 입력=data/  출력=output/transcripts/

환경변수:
    WHISPER_BACKEND = openai | local  (기본: local)
    WHISPER_MODEL   = large-v3        (기본값)
    OPENAI_API_KEY  = <key>           (openai 백엔드 사용 시 필요)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from docpilot.ingestion import audio as audio_ing
from docpilot.ingestion.audio import SUPPORTED_SUFFIXES
from docpilot.exceptions import IngestionError

import os
BACKEND = os.environ.get("WHISPER_BACKEND", "local")
MODEL   = os.environ.get("WHISPER_MODEL", "large-v3")


def main(input_dir: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(f for f in input_dir.rglob("*") if f.suffix.lower() in SUPPORTED_SUFFIXES)
    if not files:
        print(f"오디오 파일 없음: {input_dir}")
        return

    print(f"백엔드: {BACKEND}  모델: {MODEL}")
    print(f"총 {len(files)}개 파일\n")

    ok, fail = 0, 0
    for audio_path in files:
        out_path = output_dir / audio_path.with_suffix(".txt").name
        print(f"  {audio_path.name} ...", end=" ", flush=True)
        t0 = time.perf_counter()
        try:
            audio_ing.ingest(audio_path, save_transcript=out_path)
            elapsed = time.perf_counter() - t0
            print(f"완료 ({elapsed:.1f}s) → {out_path.name}")
            ok += 1
        except IngestionError as e:
            print(f"실패: {e}")
            fail += 1

    print(f"\n완료 {ok}  실패 {fail}  출력: {output_dir}")


if __name__ == "__main__":
    args = sys.argv[1:]
    input_dir  = Path(args[0]) if len(args) > 0 else Path("data")
    output_dir = Path(args[1]) if len(args) > 1 else Path("output/transcripts")
    main(input_dir, output_dir)
