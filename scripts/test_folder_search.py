"""
지정한 폴더를 인덱싱하고 특정 단어로 검색되는지 확인하는 테스트 스크립트.

docpilot의 검색 DB(~/docpilot.db)는 기본적으로 모든 프로젝트/폴더를 공유하고
검색도 폴더로 스코프되지 않으므로, 이 스크립트는 SearchFilter(source_pattern=...)로
결과를 지정한 폴더 안 파일로만 제한한다. --no-scope로 스코프 없이(=DB 전체 대상)
검색했을 때와 비교해볼 수 있다.

실행:
    uv run python scripts/test_folder_search.py <폴더경로> <검색어> [--mode hybrid] [--top-k 10] [--reindex] [--no-scope]
    uv run python scripts/test_folder_search.py <폴더경로> <검색어> --files a.hwpx b.docx  # 특정 파일만 (오디오 등 느린 파일 제외용)
    uv run python scripts/test_folder_search.py <폴더경로> <검색어> --show-all  # 이 단어가 들어간 문서를 전부 보기

주의: 검색은 문서 단위가 아니라 청크(chunk) 단위로 top_k개를 뽑은 뒤 문서로 묶는 방식이라,
--group-by-doc만 켜고 top_k가 작으면 애초에 안 뽑힌 문서는 여전히 안 보인다.
"모든 매칭 문서 보기"가 목적이면 top_k를 충분히 크게 잡아야 하며, --show-all이 이를 대신 해준다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# sqlite-vec의 KNN 쿼리는 k<=4096 하드 제한이 있고, hybrid()는 top_k*3을 벡터 쪽
# fetch_k로 쓰므로(docpilot/search/hybrid.py) top_k가 대략 1365를 넘으면 SQL 에러가 난다.
# --show-all의 동적 top_k는 이 한도 안에서만 키운다.
_SQLITE_VEC_MAX_TOPK = 1300


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", help="검색할 데이터 폴더 경로")
    parser.add_argument("query", help="검색어")
    parser.add_argument("--mode", default="hybrid", choices=["hybrid", "bm25", "vector", "exact"], help="검색 모드 (기본 hybrid)")
    parser.add_argument("--top-k", type=int, default=10, help="최대 결과 수 (기본 10)")
    parser.add_argument("--reindex", action="store_true", help="강제 재인덱싱")
    parser.add_argument("--no-scope", action="store_true", help="폴더 스코프 없이 DB 전체 대상으로 검색 (비교용)")
    parser.add_argument("--files", nargs="+", default=None, help="이 파일명들만 인덱싱 (느린 오디오 파일 등 제외하고 빠르게 테스트할 때)")
    parser.add_argument("--group-by-doc", action="store_true", help="청크 단위 결과를 문서 단위로 묶어서 출력")
    parser.add_argument("--show-all", action="store_true", help="이 단어가 들어간 문서를 전부 보기 (--group-by-doc + top_k를 크게 강제 설정)")
    args = parser.parse_args()

    folder = Path(args.folder).resolve()
    if not folder.is_dir():
        print(f"[오류] 폴더가 아닙니다: {folder}")
        sys.exit(1)

    import docpilot
    from docpilot.search import SearchFilter
    from docpilot.search.highlight import render

    pilot = docpilot.DocPilot()

    print(f"인덱싱 중: {folder}" + (f" (파일 제한: {args.files})" if args.files else ""))
    from docpilot.db import indexer
    doc_ids = indexer.index_folder(folder, embed_fn=pilot._embed_fn, force=args.reindex, files=args.files)
    print(f"  -> {len(doc_ids)}개 문서 인덱싱됨\n")

    if args.show_all:
        args.group_by_doc = True
        # 파일 하나당 청크가 여러 개 나올 수 있으므로 넉넉히 20배 잡되,
        # sqlite-vec KNN 한도 안에서 캡. 방금 인덱싱된 파일 수 기준으로 동적 계산.
        args.top_k = max(10, min(len(doc_ids) * 20, _SQLITE_VEC_MAX_TOPK))
        print(f"--show-all: 파일 {len(doc_ids)}개 기준으로 top_k={args.top_k}로 설정\n")
    elif args.top_k > _SQLITE_VEC_MAX_TOPK:
        print(f"[경고] --top-k={args.top_k}는 sqlite-vec 한도를 넘어 {_SQLITE_VEC_MAX_TOPK}으로 낮춥니다.\n")
        args.top_k = _SQLITE_VEC_MAX_TOPK

    if args.no_scope:
        filters = None
        print("검색 스코프: 없음 (DB 전체 대상)\n")
    else:
        # source_pattern은 LIKE 리터럴 매칭 — Document.source에 저장된 것과
        # 동일한 경로 구분자를 써야 한다 (Windows: str(Path)는 백슬래시).
        import os
        pattern = str(folder) + os.sep + "*"
        filters = SearchFilter(source_pattern=pattern)
        print(f"검색 스코프: source_pattern=\"{pattern}\"\n")

    results = pilot.search(
        args.query,
        mode=args.mode,
        top_k=args.top_k,
        filters=filters,
        highlight=True,
        group_by_doc=args.group_by_doc,
    )

    if not results:
        print("검색 결과 없음.")
        return

    if args.group_by_doc:
        print(f"검색 결과 {len(results)}개 문서 (mode={args.mode}, query={args.query!r}, top_k={args.top_k})\n")
        for i, doc in enumerate(results, 1):
            print(f"[{i}] {doc.source}  (score: {doc.score:.4f}, 매칭 청크 {doc.chunk_count}개)")
            for j, chunk in enumerate(doc.top_chunks, 1):
                text = render(chunk)
                preview = text[:160].replace("\n", " ")
                suffix = " ..." if len(text) > 160 else ""
                print(f"    청크{j}: {preview}{suffix}")
            print()
    else:
        print(f"검색 결과 {len(results)}건 (mode={args.mode}, query={args.query!r})\n")
        for i, r in enumerate(results, 1):
            text = render(r)
            preview = text[:200].replace("\n", " ")
            suffix = " ..." if len(text) > 200 else ""
            print(f"[{i}] {r.source}  (score: {r.score:.4f})")
            print(f"    {preview}{suffix}\n")


if __name__ == "__main__":
    main()
