"""
data/ 폴더 안의 .hwp 파일을 실제로 인제스트해서 결과를 확인하는 수동 테스트 스크립트.
변환된 .hwpx 파일은 output/ 폴더에 저장됩니다.
실행: uv run python test_real.py
"""
import contextlib
import io
import sys
from pathlib import Path

DATA_DIR = Path("data")
OUTPUT_DIR = Path("output")

hwp_files = list(DATA_DIR.glob("**/*.hwp"))
if not hwp_files:
    print("data/ 폴더에 .hwp 파일이 없습니다.")
    sys.exit(0)

OUTPUT_DIR.mkdir(exist_ok=True)

import pyhwpx
from docpilot.ingestion import hwpx as hwpx_ing

for hwp_path in hwp_files:
    print(f"\n{'='*60}")
    print(f"파일: {hwp_path}")

    hwpx_out = OUTPUT_DIR / (hwp_path.stem + ".hwpx")

    hwp = None
    _buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(_buf), contextlib.redirect_stderr(_buf):
            hwp = pyhwpx.Hwp(visible=False)
            hwp.open(str(hwp_path.resolve()))
            hwp.save_as(str(hwpx_out.resolve()), format="HWPX")
        print(f"hwpx 저장 : {hwpx_out}")
    except Exception as e:
        captured = _buf.getvalue().strip()
        print(f"[변환 오류] {e}" + (f"\n{captured}" if captured else ""))
        continue
    finally:
        if hwp is not None:
            try:
                hwp.quit()
            except Exception:
                pass

    try:
        doc = hwpx_ing.ingest(hwpx_out)
        print(f"문단 수   : {doc.metadata.get('paragraph_count', '?')}")
        print(f"원본 크기 : {hwp_path.stat().st_size} bytes (.hwp)")
        print(f"변환 크기 : {hwpx_out.stat().st_size} bytes (.hwpx)")
        print(f"--- 내용 미리보기 (앞 500자) ---")
        print(doc.content[:500])
    except Exception as e:
        print(f"[파싱 오류] {e}")
