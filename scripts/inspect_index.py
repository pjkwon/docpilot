"""
문서 인덱싱 + 벡터 임베딩 저장 확인 + 유사도 검색 테스트 스크립트.

사용법:
    uv run python scripts/inspect_index.py <문서_경로_또는_폴더>

예시:
    uv run python scripts/inspect_index.py ./data/my_doc.hwpx
    uv run python scripts/inspect_index.py ./data/
"""
from __future__ import annotations

import sys
from pathlib import Path


def main():
    if len(sys.argv) < 2:
        print("사용법: uv run python scripts/inspect_index.py <문서_경로_또는_폴더>")
        sys.exit(1)

    target = Path(sys.argv[1])
    if not target.exists():
        print(f"경로를 찾을 수 없음: {target}")
        sys.exit(1)

    # 파일 하나를 넘겼을 때는 부모 폴더를 data_folder로 사용
    data_folder = target if target.is_dir() else target.parent

    # ── 1. DB 및 임베딩 초기화 ────────────────────────────────────────────
    from docpilot.db import client, indexer
    from docpilot.db.schema import EMBEDDING_DIM
    from docpilot.search.embedding import sentence_embed_fn
    from sqlalchemy import text

    DB_URL = "sqlite:////home/nsoft-2tb/projects/docpilot/docpilot.db"
    client.init(DB_URL)
    client.create_tables()

    print("모델 로딩 중...")
    embed_fn = sentence_embed_fn()
    print(f"모델 로드 완료 (출력 차원: {EMBEDDING_DIM})\n")

    # ── 2. 인덱싱 ────────────────────────────────────────────────────────
    print(f"인덱싱 중: {data_folder}")
    doc_ids = indexer.index_folder(data_folder, embed_fn=embed_fn, force=True)
    if not doc_ids:
        print("지원되는 파일이 없거나 인덱싱 실패")
        sys.exit(1)
    print(f"인덱싱 완료 — 문서 {len(doc_ids)}개 (IDs: {doc_ids})\n")

    # ── 3. 저장 확인 ─────────────────────────────────────────────────────
    id_list = ", ".join(str(i) for i in doc_ids)

    with client.session() as db:
        docs = db.execute(text(
            f"SELECT d.id, d.source, COUNT(c.id) AS chunk_count "
            f"FROM documents d JOIN chunks c ON c.document_id = d.id "
            f"WHERE d.id IN ({id_list}) GROUP BY d.id"
        )).fetchall()

        vec_rows = db.execute(text(
            f"SELECT c.document_id, COUNT(*) AS vec_count "
            f"FROM vec_chunks v JOIN chunks c ON c.id = v.chunk_id "
            f"WHERE c.document_id IN ({id_list}) GROUP BY c.document_id"
        )).fetchall()

        fts_rows = db.execute(text(
            f"SELECT c.document_id, COUNT(*) AS fts_count "
            f"FROM fts_chunks f JOIN chunks c ON c.id = f.rowid "
            f"WHERE c.document_id IN ({id_list}) GROUP BY c.document_id"
        )).fetchall()

    vec_by_doc = {row.document_id: row.vec_count for row in vec_rows}
    fts_by_doc = {row.document_id: row.fts_count for row in fts_rows}

    print("── 저장 결과 ──────────────────────────────────────────")
    for doc in docs:
        vec_count = vec_by_doc.get(doc.id, 0)
        fts_count = fts_by_doc.get(doc.id, 0)
        vec_mark = "✓" if doc.chunk_count == vec_count else "✗ 불일치!"
        fts_mark = "✓" if doc.chunk_count == fts_count else "✗ 불일치!"
        print(f"  [{doc.id}] {Path(doc.source).name}")
        print(f"       청크 수: {doc.chunk_count}  /  임베딩: {vec_count} {vec_mark}  /  형태소: {fts_count} {fts_mark}")
    print()

    # ── 4. 유사도 검색 ───────────────────────────────────────────────────
    print("── 유사도 검색 테스트 ─────────────────────────────────")
    print("검색어를 입력하세요 (엔터만 누르면 종료):\n")

    from docpilot.search.embedding import search

    while True:
        try:
            query = input("검색어 > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not query:
            break

        results = search(query, embed_fn=embed_fn, top_k=5)
        if not results:
            print("  결과 없음\n")
            continue

        for i, r in enumerate(results, 1):
            print(f"  [{i}] score={r.score:.3f}  출처={Path(r.source).name}")
            print(f"      {r.content[:120].strip()}")
            print()


if __name__ == "__main__":
    main()
