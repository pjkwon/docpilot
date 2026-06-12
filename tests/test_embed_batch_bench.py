"""임베딩 배치 처리 전후 성능 비교 벤치마크. git checkout 없이 같은 코드베이스에서 실행.

실행:
    uv run pytest tests/test_embed_batch_bench.py -s
    uv run pytest tests/test_embed_batch_bench.py -s --data-dir /your/folder
    uv run pytest tests/test_embed_batch_bench.py -s --embed-latency-ms 100
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest


def test_embed_batch_vs_per_chunk(perf_data_dir: Path, request) -> None:
    """청크별 개별 호출(이전) vs 배치 호출(현재) 속도 비교.

    실제 API 호출 없이 지연 시간을 시뮬레이션하여 배치 최적화 효과를 측정합니다.
    """
    from docpilot.db.indexer import _split, _batch_embed
    from docpilot.db.schema import EMBEDDING_DIM
    from docpilot.ingestion import docx as docx_ing
    from docpilot.ingestion import hwpx as hwpx_ing
    from docpilot.ingestion import text as text_ing

    latency_s = request.config.getoption("--embed-latency-ms") / 1000.0

    ingesters = {
        **{ext: text_ing.ingest for ext in text_ing.SUPPORTED_EXTENSIONS},
        ".hwpx": hwpx_ing.ingest,
        ".docx": docx_ing.ingest,
    }

    files = sorted(
        f for f in perf_data_dir.rglob("*")
        if f.is_file() and f.suffix.lower() in ingesters
    )

    # 파일 파싱 + 청크 분할 (두 방식 공통 전처리)
    docs_chunks: list[tuple[str, list[str]]] = []
    for file in files:
        try:
            doc = ingesters[file.suffix.lower()](file)
            chunks = _split(doc.content, chunk_size=1000, overlap=200, min_chunk_size=200)
            if chunks:
                docs_chunks.append((file.name, chunks))
        except Exception:
            pass

    total_chunks = sum(len(c) for _, c in docs_chunks)

    print(f"\n\n[임베딩 배치 처리 벤치마크]")
    print(f"  데이터 폴더: {perf_data_dir}")
    print(f"  파일: {len(docs_chunks)}개  |  총 청크: {total_chunks}개  |  API 지연 시뮬레이션: {latency_s * 1000:.0f}ms/호출")
    print("=" * 68)

    dummy_vec = [0.0] * EMBEDDING_DIM

    # ── 이전 방식: 청크마다 embed_fn 개별 호출 ──────────────────────────────
    per_chunk_calls = 0

    def _old_embed(text: str) -> list[float]:
        nonlocal per_chunk_calls
        time.sleep(latency_s)
        per_chunk_calls += 1
        return dummy_vec

    t0 = time.perf_counter()
    for _, chunks in docs_chunks:
        for chunk in chunks:
            _old_embed(chunk)
    old_elapsed = time.perf_counter() - t0

    # ── 현재 방식: 문서당 청크 전체를 배치로 1회 호출 (_batch_embed 사용) ──
    batch_calls = 0

    def _new_embed(texts: list[str]) -> list[list[float]]:
        nonlocal batch_calls
        time.sleep(latency_s)
        batch_calls += 1
        return [dummy_vec] * len(texts)

    t0 = time.perf_counter()
    for _, chunks in docs_chunks:
        _batch_embed(_new_embed, chunks)
    new_elapsed = time.perf_counter() - t0

    speedup = old_elapsed / new_elapsed if new_elapsed > 0 else float("inf")

    print(f"  이전 방식 (청크별 개별 호출):  {old_elapsed:6.2f}s  ({per_chunk_calls}회)")
    print(f"  현재 방식 (문서당 배치 호출):  {new_elapsed:6.2f}s  ({batch_calls}회)")
    print(f"  {'─' * 48}")
    print(f"  개선율: {speedup:.1f}x  ({per_chunk_calls}회 → {batch_calls}회)")
    print("=" * 68)

    assert speedup > 1.5, f"배치 방식이 충분히 빠르지 않습니다 (개선율: {speedup:.2f}x)"
