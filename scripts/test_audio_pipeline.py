"""
오디오 전사 txt → 문서 생성 파이프라인 테스트
실행: uv run python scripts/test_audio_pipeline.py [데이터폴더] [템플릿] [출력파일]

기본값:
  데이터폴더  = output/transcripts/
  템플릿      = minutes  (빌트인: report | gonmun | minutes | proposal)
  출력파일    = output/result.hwpx

빌트인 템플릿:
  report   — 일반 보고서 (보고서 제목, 섹션 본문, 결론)
  minutes  — 회의록 (제목, 일시, 참석자, 안건, 논의, 결정사항)
  gonmun   — 공문 (수신자, 제목, 본문, 기관 정보)
  proposal — 제안서

또는 .hwpx / .docx 파일 경로 직접 지정 가능.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

DATA_DIR   = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("output/transcripts")
TEMPLATE   = sys.argv[2]       if len(sys.argv) > 2 else "minutes"
OUTPUT     = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("output/result.hwpx")

# ── 데이터 폴더 확인 ─────────────────────────────────────────────────────────
if not DATA_DIR.is_dir():
    print(f"데이터 폴더 없음: {DATA_DIR}")
    print("먼저 transcribe.py 로 전사 파일을 생성하세요.")
    sys.exit(1)

txt_files = list(DATA_DIR.glob("*.txt")) + list(DATA_DIR.glob("*.md"))
if not txt_files:
    print(f"텍스트 파일 없음: {DATA_DIR}")
    sys.exit(1)

print(f"데이터 폴더 : {DATA_DIR}")
print(f"텍스트 파일 : {len(txt_files)}개")
for f in txt_files:
    print(f"  · {f.name} ({f.stat().st_size:,} bytes)")
print(f"템플릿      : {TEMPLATE}")
print(f"출력        : {OUTPUT}")
print()

# ── DocPilot 초기화 ──────────────────────────────────────────────────────────
import os
api_key = os.environ.get("ANTHROPIC_API_KEY")
if not api_key:
    print("[오류] ANTHROPIC_API_KEY 환경변수가 필요합니다.")
    sys.exit(1)

import docpilot
print("DocPilot 초기화 중...")
pilot = docpilot.DocPilot(llm="claude", api_key=api_key)
print("완료\n")

# ── 파이프라인 실행 ──────────────────────────────────────────────────────────
print("── 파이프라인 실행 ─────────────────────────────────────────────────────")
print("  1/3  데이터 인덱싱...")
t0 = time.perf_counter()

try:
    result = pilot.generate(
        data_folder=DATA_DIR,
        template=TEMPLATE,
        output=OUTPUT,
        reindex=True,
    )
except Exception as e:
    print(f"\n[실패] {str(e).encode('utf-8', errors='replace').decode('utf-8')}")
    sys.exit(1)

elapsed = time.perf_counter() - t0

print(f"\n── 완료 ────────────────────────────────────────────────────────────────")
print(f"출력 파일  : {OUTPUT}")
print(f"총 소요    : {elapsed:.1f}s")
print(f"모델       : {result.model}")
print(f"토큰       : 입력 {result.input_tokens:,} / 출력 {result.output_tokens:,}")
