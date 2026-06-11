"""data/ 폴더 인덱싱 성능 테스트. uv run pytest tests/test_index_perf.py -s"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

DATA_DIR = Path(__file__).parent.parent / "data"

pytestmark = pytest.mark.skipif(
    not DATA_DIR.is_dir(), reason="data/ 폴더 없음"
)


def test_index_data_folder(tmp_path: Path) -> None:
    """data/ 폴더 파일별 인덱싱 소요 시간 측정 (격리된 임시 DB 사용)"""
    from docpilot.db import client, indexer
    from docpilot.ingestion import docx as docx_ing
    from docpilot.ingestion import hwpx as hwpx_ing
    from docpilot.ingestion import text as text_ing

    client.init(f"sqlite:///{tmp_path / 'perf.db'}")
    client.create_tables()

    ingesters = {
        **{ext: text_ing.ingest for ext in text_ing.SUPPORTED_EXTENSIONS},
        ".hwpx": hwpx_ing.ingest,
        ".docx": docx_ing.ingest,
    }

    files = sorted(
        f for f in DATA_DIR.rglob("*")
        if f.is_file() and f.suffix.lower() in ingesters
    )

    print(f"\n\n[인덱싱 성능]  파일 {len(files)}개  |  DB: {tmp_path / 'perf.db'}")
    print("=" * 72)

    # kiwipiepy 첫 로드 시간 격리 측정
    t = time.perf_counter()
    try:
        from docpilot.search.morpheme import _tokenize
        _tokenize("워밍업")
        print(f"  kiwipiepy 워밍업:  {time.perf_counter() - t:.2f}s")
    except Exception:
        print("  kiwipiepy 없음 — 형태소 FTS 스킵")
    print("-" * 72)

    total_start = time.perf_counter()
    ok = fail = 0

    for file in files:
        t = time.perf_counter()
        try:
            doc = ingesters[file.suffix.lower()](file)
            indexer.index(doc)
            elapsed = time.perf_counter() - t
            n_para = len([p for p in doc.content.split("\n\n") if p.strip()])
            print(f"  [OK]  {file.name:<46}  {elapsed:5.2f}s  ({n_para} 문단)")
            ok += 1
        except Exception as exc:
            elapsed = time.perf_counter() - t
            print(f"  [NG]  {file.name:<46}  {elapsed:5.2f}s  {exc}")
            fail += 1

    total = time.perf_counter() - total_start
    print("=" * 72)
    print(f"  결과: {ok}개 성공 / {fail}개 실패  |  총 소요: {total:.2f}s")

    assert ok > 0, "인덱싱된 파일이 없습니다"
