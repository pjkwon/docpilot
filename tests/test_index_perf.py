"""인덱싱 성능 테스트.

기본: uv run pytest tests/test_index_perf.py -s
경로 지정: uv run pytest tests/test_index_perf.py -s --data-dir /your/folder
임베딩 포함: uv run pytest tests/test_index_perf.py -s --data-dir /your/folder --with-embed
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest


def test_index_data_folder(tmp_path: Path, perf_data_dir: Path, request) -> None:
    """데이터 폴더 파일별 인덱싱 소요 시간 측정 (격리된 임시 DB 사용)"""
    from docpilot.db import client, indexer
    from docpilot.ingestion import docx as docx_ing
    from docpilot.ingestion import hwpx as hwpx_ing
    from docpilot.ingestion import text as text_ing

    client.init(f"sqlite:///{tmp_path / 'perf.db'}")
    client.create_tables()

    # embed_fn 목업: 호출 횟수와 총 청크 수를 기록
    embed_calls = 0
    embed_chunks = 0

    use_embed = request.config.getoption("--with-embed")
    if use_embed:
        def _counting_embed(texts):
            nonlocal embed_calls, embed_chunks
            batch = isinstance(texts, list)
            inputs = texts if batch else [texts]
            embed_calls += 1
            embed_chunks += len(inputs)
            from docpilot.db.schema import EMBEDDING_DIM
            return [[0.0] * EMBEDDING_DIM] * len(inputs) if batch else [0.0] * EMBEDDING_DIM
        embed_fn = _counting_embed
    else:
        embed_fn = None

    ingesters = {
        **{ext: text_ing.ingest for ext in text_ing.SUPPORTED_EXTENSIONS},
        ".hwpx": hwpx_ing.ingest,
        ".docx": docx_ing.ingest,
    }

    files = sorted(
        f for f in perf_data_dir.rglob("*")
        if f.is_file() and f.suffix.lower() in ingesters
    )

    print(f"\n\n[인덱싱 성능]  파일 {len(files)}개  |  DB: {tmp_path / 'perf.db'}")
    print(f"  데이터 폴더: {perf_data_dir}")
    if use_embed:
        print("  embed_fn: 카운팅 목업 (더미 벡터, 호출 횟수 측정용)")
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
            indexer.index(doc, embed_fn=embed_fn)
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
    if use_embed:
        avg = embed_chunks / embed_calls if embed_calls else 0
        print(f"  embed 호출: {embed_calls}회  |  총 청크: {embed_chunks}개  |  평균 배치 크기: {avg:.1f}")

    assert ok > 0, "인덱싱된 파일이 없습니다"
