"""
템플릿 추출 테스트 스크립트.

samples/ 폴더에 {{플레이스홀더}}가 있는 템플릿 파일(.hwpx/.docx)을 넣어두면
data/ 인덱스 → RAG 검색 → LLM 매핑 전 과정을 확인합니다.

사용법:
    uv run python scripts/test_mapping.py <템플릿_파일>  [<데이터_폴더>]

예시:
    uv run python scripts/test_mapping.py samples/점검보고서.hwpx
    uv run python scripts/test_mapping.py samples/점검보고서.hwpx ./data
"""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) < 2:
        # samples/ 에서 첫 번째 템플릿 파일 자동 탐색
        samples_dir = Path("samples")
        candidates = sorted(
            f for f in samples_dir.glob("*")
            if f.suffix.lower() in (".hwpx", ".docx", ".pdf")
        ) if samples_dir.is_dir() else []

        if not candidates:
            print("사용법: uv run python scripts/test_mapping.py <템플릿_파일>")
            print("       samples/ 폴더에 .hwpx/.docx 템플릿 파일을 넣어두세요.")
            sys.exit(1)

        template_path = candidates[0]
        print(f"[자동 탐색] 템플릿: {template_path}\n")
    else:
        template_path = Path(sys.argv[1])

    data_folder = Path(sys.argv[2]) if len(sys.argv) >= 3 else Path("data")

    if not template_path.exists():
        print(f"템플릿 파일을 찾을 수 없음: {template_path}")
        sys.exit(1)

    if not data_folder.is_dir():
        print(f"데이터 폴더를 찾을 수 없음: {data_folder}")
        sys.exit(1)

    # ── 1. 플레이스홀더 추출 ─────────────────────────────────────────────
    import zipfile, re
    _PLACEHOLDER_RE = re.compile(r"\{\{(.+?)\}\}")

    def _extract_placeholders(path: Path) -> list[str]:
        suffix = path.suffix.lower()
        if suffix == ".hwpx":
            with zipfile.ZipFile(path) as zf:
                names = zf.namelist()
                targets = [n for n in names if n.endswith("content.hml")] or \
                          [n for n in names if n.endswith("section0.xml")]
                text = "".join(zf.read(t).decode("utf-8", errors="ignore") for t in targets)
        elif suffix == ".docx":
            with zipfile.ZipFile(path) as zf:
                text = zf.read("word/document.xml").decode("utf-8", errors="ignore")
        else:
            return []
        seen: dict[str, None] = {}
        for m in _PLACEHOLDER_RE.finditer(text):
            seen[m.group(1)] = None
        return list(seen)

    placeholders = _extract_placeholders(template_path)
    if not placeholders:
        print(f"템플릿에서 {{{{플레이스홀더}}}}를 찾을 수 없습니다: {template_path}")
        print("템플릿 파일에 {{섹션명}} 형식의 플레이스홀더가 있는지 확인하세요.")
        sys.exit(1)

    print(f"템플릿: {template_path.name}")
    print(f"플레이스홀더 {len(placeholders)}개:")
    for p in placeholders:
        print(f"  · {{{{{p}}}}}")
    print()

    # ── 2. DB 및 임베딩 초기화 ────────────────────────────────────────────
    from docpilot.db import client, indexer
    from docpilot.search.embedding import bge_embed_fn

    DB_URL = f"sqlite:///{Path('docpilot.db').resolve()}"
    client.init(DB_URL)
    client.create_tables()

    print("임베딩 모델 로딩 중... (BAAI/bge-m3, 최초 실행 시 다운로드)")
    embed_fn = bge_embed_fn()
    print("완료\n")

    # ── 3. 인덱싱 ────────────────────────────────────────────────────────
    print(f"인덱싱 중: {data_folder}")
    doc_ids = indexer.index_folder(data_folder, embed_fn=embed_fn)
    print(f"완료 — 문서 {len(doc_ids)}개 (IDs: {doc_ids})\n")

    # ── 4. RAG 검색 (검색 결과 미리보기) ─────────────────────────────────
    from docpilot.mapping.base import TemplateSection
    from docpilot.mapping.rag import RagMapper

    sections = [TemplateSection(name=p) for p in placeholders]

    # 임시 RagMapper로 검색 결과만 확인
    class _NoOpMapper:
        pass

    rag = RagMapper(_NoOpMapper(), embed_fn=embed_fn, top_k=5)  # type: ignore
    retrieved_chunks = rag._retrieve(sections)

    print("── 검색된 청크 ─────────────────────────────────────────")
    if not retrieved_chunks:
        print("  검색 결과 없음 — data/ 폴더가 비어있거나 관련 내용이 없습니다.")
    else:
        for i, r in enumerate(retrieved_chunks, 1):
            print(f"  [{i}] score={r.score:.4f}  출처={Path(r.source).name}")
            print(f"       {r.content[:150].strip()}")
            print()
    print()

    # ── 5. LLM 매핑 ──────────────────────────────────────────────────────
    print("── LLM 매핑 시작 ───────────────────────────────────────")
    import os
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ANTHROPIC_API_KEY 환경변수가 없습니다. LLM 매핑을 건너뜁니다.")
        sys.exit(0)

    from docpilot.mapping.claude import ClaudeMapper
    mapper = ClaudeMapper(api_key=api_key)
    rag_mapper = RagMapper(mapper, embed_fn=embed_fn, top_k=5, use_reranker=True)

    print("LLM 호출 중...\n")
    try:
        result = rag_mapper.map(sections)
    except Exception as e:
        print(f"매핑 실패: {e}")
        sys.exit(1)

    print("── 매핑 결과 ───────────────────────────────────────────")
    for section_name, content in result.sections.items():
        print(f"\n[{section_name}]")
        print(content)

    print()
    print(f"모델: {result.model}  |  토큰: {result.input_tokens:,} 입력 / {result.output_tokens:,} 출력  |  {result.elapsed_seconds:.1f}초")

    # ── 6. 출력 파일 저장 (선택) ─────────────────────────────────────────
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / template_path.name

    try:
        from docpilot.builder import HwpxBuilder, DocxBuilder
        suffix = template_path.suffix.lower()
        builder = HwpxBuilder() if suffix == ".hwpx" else DocxBuilder()
        builder.build(template_path, result.sections, output_path)
        print(f"\n출력 파일: {output_path}")
    except Exception as e:
        print(f"\n출력 파일 생성 실패 (매핑 결과는 위에서 확인): {e}")


if __name__ == "__main__":
    main()
