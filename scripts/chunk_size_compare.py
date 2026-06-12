"""청크 크기별 검색 결과 비교 스크립트.

사용법:
    uv run python scripts/chunk_size_compare.py "검색 쿼리" --data-dir ./data
    uv run python scripts/chunk_size_compare.py "로봇 도입 비용" --data-dir ./data --sizes 300,500,1000,2000
    uv run python scripts/chunk_size_compare.py "로봇 도입 비용" --data-dir ./data --mode vector
    uv run python scripts/chunk_size_compare.py "로봇 도입 비용" --data-dir ./data --top-k 5
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path


def _build_index(data_dir: Path, chunk_size: int, tmp_dir: Path) -> Path:
    """주어진 청크 크기로 data_dir를 인덱싱한 DB를 tmp_dir에 생성하고 경로 반환."""
    from docpilot.db import client, indexer
    from docpilot.ingestion import docx as docx_ing
    from docpilot.ingestion import hwpx as hwpx_ing
    from docpilot.ingestion import text as text_ing

    db_path = tmp_dir / f"chunk_{chunk_size}.db"
    client.init(f"sqlite:///{db_path}")
    client.create_tables()

    ingesters = {
        **{ext: text_ing.ingest for ext in text_ing.SUPPORTED_EXTENSIONS},
        ".hwpx": hwpx_ing.ingest,
        ".docx": docx_ing.ingest,
    }

    ok = fail = 0
    for file in sorted(data_dir.rglob("*")):
        if not file.is_file():
            continue
        ingester = ingesters.get(file.suffix.lower())
        if not ingester:
            continue
        try:
            doc = ingester(file)
            indexer.index(doc, chunk_size=chunk_size, overlap=chunk_size // 5)
            ok += 1
        except Exception as e:
            fail += 1
            print(f"  [SKIP] {file.name}: {e}", file=sys.stderr)

    total_chunks = _count_chunks()
    print(f"  chunk_size={chunk_size:<5}  파일 {ok}개  →  청크 {total_chunks}개")
    return db_path


def _count_chunks() -> int:
    from sqlalchemy import text
    from docpilot.db import client
    with client.session() as db:
        return db.execute(text("SELECT COUNT(*) FROM chunks")).scalar()


def _search(query: str, mode: str, top_k: int) -> list:
    from docpilot.search import exact, morpheme
    if mode == "exact":
        return exact.search(query, top_k=top_k)
    try:
        return morpheme.search(query, top_k=top_k, or_fallback=True)
    except Exception as e:
        if "kiwipiepy" in str(e):
            return exact.search(query, top_k=top_k)
        raise


def _print_results(results: list, do_highlight: bool, query: str, preview_len: int) -> None:
    from docpilot.search.highlight import highlight, render
    for i, r in enumerate(results, 1):
        if do_highlight:
            r = highlight(r, query)
            text = render(r)
        else:
            text = r.content
        preview = text[:preview_len].replace("\n", " ")
        suffix = " ..." if len(text) > preview_len else ""
        print(f"  [{i}] score={r.score:.3f}  {Path(r.source).name}")
        print(f"      {preview}{suffix}")


def main() -> None:
    parser = argparse.ArgumentParser(description="청크 크기별 검색 결과 비교")
    parser.add_argument("query", help="검색 쿼리")
    parser.add_argument("--data-dir", default="./data", metavar="PATH", help="데이터 폴더 (기본값: ./data)")
    parser.add_argument("--sizes", default="300,500,1000,2000", help="비교할 청크 크기 (쉼표 구분, 기본값: 300,500,1000,2000)")
    parser.add_argument("--top-k", type=int, default=3, help="결과 수 (기본값: 3)")
    parser.add_argument("--mode", default="morpheme", choices=["exact", "morpheme"], help="검색 방식 (기본값: morpheme)")
    parser.add_argument("--preview", type=int, default=200, help="청크 미리보기 글자 수 (기본값: 200)")
    parser.add_argument("--no-highlight", action="store_true", help="하이라이팅 비활성화")
    args = parser.parse_args()

    data_dir = Path(args.data_dir).resolve()
    if not data_dir.is_dir():
        sys.exit(f"오류: 데이터 폴더를 찾을 수 없습니다 — {data_dir}")

    sizes = [int(s.strip()) for s in args.sizes.split(",")]

    print(f"\n쿼리: \"{args.query}\"")
    print(f"데이터 폴더: {data_dir}  |  검색 방식: {args.mode}  |  top-k: {args.top_k}")
    print()

    with tempfile.TemporaryDirectory(prefix="docpilot_chunk_") as tmp:
        tmp_dir = Path(tmp)

        print("[인덱싱]")
        db_paths: dict[int, Path] = {}
        for size in sizes:
            db_paths[size] = _build_index(data_dir, size, tmp_dir)

        print()
        sep = "─" * 68

        for size in sizes:
            from docpilot.db import client
            client.init(f"sqlite:///{db_paths[size]}")

            results = _search(args.query, args.mode, args.top_k)
            n_chunks = _count_chunks()

            print(f"{'=' * 68}")
            print(f"  chunk_size={size}  (총 청크 {n_chunks}개, top-{args.top_k})")
            print(sep)
            if results:
                _print_results(results, not args.no_highlight, args.query, args.preview)
            else:
                print("  (검색 결과 없음)")
            print()


if __name__ == "__main__":
    main()
