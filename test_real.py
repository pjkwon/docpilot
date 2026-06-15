"""
data/ 폴더 안의 .hwp 파일을 실제로 인제스트해서 결과를 확인하는 수동 테스트 스크립트.
실행: python test_real.py
"""
from pathlib import Path

from docpilot.ingestion import hwp as hwp_ing

DATA_DIR = Path("data")

hwp_files = list(DATA_DIR.glob("**/*.hwp"))
if not hwp_files:
    print("data/ 폴더에 .hwp 파일이 없습니다.")
else:
    for hwp_path in hwp_files:
        print(f"\n{'='*60}")
        print(f"파일: {hwp_path}")
        try:
            doc = hwp_ing.ingest(hwp_path)
            print(f"mime_type : {doc.mime_type}")
            print(f"문단 수   : {doc.metadata.get('paragraph_count', '?')}")
            print(f"원본 크기 : {hwp_path.stat().st_size} bytes (.hwp)")
            print(f"변환 크기 : {doc.metadata.get('size_bytes', '?')} bytes (.hwpx)")
            print(f"변환 방식 : {doc.metadata.get('converted_via', '?')}")
            print(f"--- 내용 미리보기 (앞 500자) ---")
            print(doc.content[:500])
        except Exception as e:
            print(f"[오류] {e}")
