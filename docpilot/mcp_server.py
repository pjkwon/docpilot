from __future__ import annotations

import os
import threading
from pathlib import Path

from mcp.server.fastmcp import FastMCP

_pilot = None


# ---------------------------------------------------------------------------
# 백그라운드 인덱싱 상태
# ---------------------------------------------------------------------------

class _IndexJob:
    def __init__(self, thread: threading.Thread, done_event: threading.Event) -> None:
        self.thread = thread
        self.done_event = done_event
        self.count: int = 0
        self.error: Exception | None = None


_index_jobs: dict[str, _IndexJob] = {}
_index_jobs_lock = threading.Lock()


def _get_pilot():
    global _pilot
    if _pilot is None:
        from docpilot import DocPilot
        _pilot = DocPilot(
            llm=os.environ.get("DOCPILOT_LLM", "claude"),
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
            model=os.environ.get("DOCPILOT_MODEL") or None,
            database_url=os.environ.get("DOCPILOT_DATABASE_URL") or None,
        )
    return _pilot


mcp = FastMCP(
    "docpilot",
    instructions=(
        "docpilot는 데이터 폴더와 템플릿으로 HWPX / PDF / DOCX 문서를 자동 생성하고, "
        "인덱싱된 문서를 검색할 수 있습니다.\n"
        "내장 템플릿: report(일반 보고서), gonmun(공문), minutes(회의록), proposal(제안서).\n"
        "검색 워크플로: index()로 폴더를 인덱싱 → search()로 질의. "
        "generate()는 내부적으로 인덱싱을 자동 수행합니다.\n"
        "사용 전 ANTHROPIC_API_KEY 환경 변수가 설정되어 있어야 합니다."
    ),
)


def _start_index_job(folder_key: str, data_folder: str, force: bool = False) -> _IndexJob:
    """백그라운드 인덱싱 스레드를 시작하고 _IndexJob을 반환한다."""
    done = threading.Event()

    def _run() -> None:
        try:
            from docpilot.db import indexer
            pilot = _get_pilot()
            doc_ids = indexer.index_folder(
                data_folder,
                embed_fn=pilot._embed_fn,
                force=force,
            )
            job.count = len(doc_ids)
        except Exception as exc:
            job.error = exc
        finally:
            done.set()

    t = threading.Thread(target=_run, daemon=True, name=f"docpilot-index-{folder_key}")
    job = _IndexJob(thread=t, done_event=done)

    with _index_jobs_lock:
        _index_jobs[folder_key] = job

    t.start()
    return job


@mcp.tool()
def index(data_folder: str, reindex: bool = False) -> str:
    """데이터 폴더를 검색 인덱스에 등록합니다. search() 전에 먼저 실행하세요.

    generate()는 내부적으로 인덱싱을 자동 수행하므로, 순수 검색 목적으로만
    인덱스를 쌓을 때 이 도구를 직접 사용합니다.
    인덱싱은 백그라운드에서 실행되며 즉시 반환됩니다.

    Args:
        data_folder: 인덱싱할 파일이 있는 폴더 경로 (절대 경로 권장, 하위 폴더 재귀 탐색)
        reindex: True이면 이미 인덱싱된 파일도 강제 재인덱싱 (기본값: False)
    """
    folder_key = str(Path(data_folder).resolve())

    with _index_jobs_lock:
        existing = _index_jobs.get(folder_key)
        if existing and existing.thread.is_alive():
            return f"이미 인덱싱 진행 중: {data_folder} — 완료 후 재시도하세요."

    _start_index_job(folder_key, data_folder, force=reindex)
    return (
        f"인덱싱 시작됨: {data_folder}\n"
        "백그라운드에서 진행 중입니다. "
        "generate() 호출 시 완료를 자동으로 기다립니다."
    )


@mcp.tool()
def search(
    query: str,
    mode: str = "morpheme",
    top_k: int = 10,
    group_by_doc: bool = False,
    highlight: bool = True,
    source_pattern: str | None = None,
    mime_type: str | None = None,
    metadata: dict[str, str] | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
) -> str:
    """인덱싱된 문서를 검색합니다. 검색 전 index()로 폴더를 먼저 인덱싱해야 합니다.

    Args:
        query: 검색 질의 문자열
        mode: 검색 방식 — "exact"(키워드 LIKE), "morpheme"(형태소 BM25, 기본값),
              "vector"(벡터 유사도, embed_fn 구성 필요)
        top_k: 반환할 최대 결과 수 (기본값: 10)
        group_by_doc: True이면 결과를 문서 단위로 집계하여 반환 (기본값: False)
        highlight: True이면 쿼리 텀을 ** 마커로 강조 (기본값: True)
        source_pattern: 파일 경로 glob 패턴 필터 (예: "reports/*.hwpx")
        mime_type: MIME 타입 필터 (예: "application/vnd.hancom.hwpx")
        metadata: 문서 메타데이터 key-value 필터 (예: {"dept": "기획", "year": "2026"})
        created_after: 인덱싱 날짜 하한 — ISO 8601 형식 (예: "2026-01-01")
        created_before: 인덱싱 날짜 상한 — ISO 8601 형식 (예: "2026-12-31")
    """
    from datetime import datetime

    from docpilot.search import (
        SearchFilter,
        group_by_document,
        highlight as highlight_fn,
        render,
    )
    from docpilot.search import exact, morpheme
    from docpilot.search.embedding import EmbedFn

    # 날짜 파싱
    after_dt = _parse_dt(created_after) if created_after else None
    before_dt = _parse_dt(created_before) if created_before else None

    filters = SearchFilter(
        source_pattern=source_pattern,
        mime_type=mime_type,
        metadata=metadata or None,
        created_after=after_dt,
        created_before=before_dt,
    ) if any([source_pattern, mime_type, metadata, after_dt, before_dt]) else None

    # 검색 실행
    pilot = _get_pilot()
    mode = mode.lower()

    if mode == "exact":
        results = exact.search(query, top_k=top_k, filters=filters)
    elif mode == "morpheme":
        results = morpheme.search(query, top_k=top_k, or_fallback=True, filters=filters)
    elif mode == "vector":
        if pilot._embed_fn is None:
            return (
                "vector 모드는 embed_fn 설정이 필요합니다. "
                "DOCPILOT_EMBED 환경변수 또는 DocPilot(embed_fn=...) 설정을 확인하세요."
            )
        from docpilot.search import embedding as emb_mod
        results = emb_mod.search(query, embed_fn=pilot._embed_fn, top_k=top_k, filters=filters)
    else:
        return f"알 수 없는 mode: {mode!r}. 'exact' / 'morpheme' / 'vector' 중 선택하세요."

    if not results:
        return "검색 결과가 없습니다."

    # 하이라이팅
    if highlight:
        results = [highlight_fn(r, query) for r in results]

    # 문서 단위 집계
    if group_by_doc:
        docs = group_by_document(results, top_chunks=3, score="max")
        return _format_doc_results(docs, highlight)

    return _format_chunk_results(results, highlight, top_k)


# ---------------------------------------------------------------------------
# 출력 포맷 헬퍼
# ---------------------------------------------------------------------------

def _format_chunk_results(results, do_highlight: bool, top_k: int) -> str:
    lines = [f"검색 결과 {len(results)}건 (최대 {top_k})"]
    lines.append("")
    for i, r in enumerate(results, 1):
        text = render(r) if do_highlight else r.content
        preview = text[:200].replace("\n", " ")
        lines.append(f"[{i}] {r.source}  (score: {r.score:.4f})")
        lines.append(f"    {preview}")
        if len(text) > 200:
            lines[-1] += " ..."
        lines.append("")
    return "\n".join(lines).rstrip()


def _format_doc_results(docs, do_highlight: bool) -> str:
    lines = [f"검색 결과 {len(docs)}개 문서 (문서 단위 집계)"]
    lines.append("")
    for i, doc in enumerate(docs, 1):
        lines.append(f"[{i}] {doc.source}  (score: {doc.score:.4f}, 매칭 청크 {doc.chunk_count}개)")
        for j, chunk in enumerate(doc.top_chunks, 1):
            text = render(chunk) if do_highlight else chunk.content
            preview = text[:160].replace("\n", " ")
            lines.append(f"    청크{j}: {preview}" + (" ..." if len(text) > 160 else ""))
        lines.append("")
    return "\n".join(lines).rstrip()


def _parse_dt(s: str):
    from datetime import datetime, timezone
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"날짜 형식을 파싱할 수 없습니다: {s!r}  (ISO 8601 예: '2026-01-01')")


# ---------------------------------------------------------------------------
# 기존 도구
# ---------------------------------------------------------------------------

def _default_output(template: str, ext: str = ".hwpx") -> str:
    from datetime import datetime
    from pathlib import Path
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    tpl_ext = Path(template).suffix.lower()
    if tpl_ext in (".docx", ".pdf"):
        ext = tpl_ext
    docs = Path.home() / "Documents"
    docs.mkdir(exist_ok=True)
    return str(docs / f"docpilot_{ts}{ext}")


@mcp.tool()
def generate(
    data_folder: str,
    template: str,
    output: str | None = None,
    reindex: bool = False,
    extra_instructions: str | None = None,
    instructions_doc: str | None = None,
) -> str:
    """데이터 폴더와 템플릿으로 문서를 생성합니다.

    Args:
        data_folder: 데이터 파일이 있는 폴더 경로 (절대 경로 권장)
        template: 템플릿 파일 경로 또는 내장 템플릿 이름 (report / gonmun / minutes / proposal)
        output: 출력 파일 경로 — 확장자가 출력 형식을 결정합니다 (.hwpx / .pdf / .docx).
                미지정 시 ~/Documents/docpilot_YYYYMMDD_HHMMSS.hwpx 에 저장됩니다.
        reindex: True이면 데이터 폴더를 강제로 재인덱싱합니다 (기본값: False)
        extra_instructions: LLM 프롬프트에 추가할 작성 지침 문자열
        instructions_doc: 작성 지침으로 사용할 파일 경로 (RFP·제안요청서 등). 파일 내용이 자동으로 지침에 추가됩니다.
    """
    if output is None:
        output = _default_output(template)

    folder_key = str(Path(data_folder).resolve())
    with _index_jobs_lock:
        job = _index_jobs.get(folder_key)

    # 잡 없음, 또는 완료된 잡인데 reindex=True 요청 → 새 잡 시작
    if job is None or (reindex and not job.thread.is_alive()):
        _start_index_job(folder_key, data_folder, force=reindex)
        return (
            f"데이터 폴더 인덱싱을 시작했습니다: {data_folder}\n"
            "잠시 후 다시 generate()를 호출하세요."
        )

    if job.thread.is_alive():
        return "인덱싱이 진행 중입니다. 잠시 후 다시 generate()를 호출하세요."

    if job.error:
        return f"인덱싱 중 오류 발생: {job.error}"

    # 인덱싱 완료 → 문서 생성 (bg 잡이 이미 인덱싱했으므로 reindex=False)
    result = _get_pilot().generate(
        data_folder=data_folder,
        template=template,
        output=output,
        reindex=False,
        extra_instructions=extra_instructions,
        instructions_doc=instructions_doc,
    )
    return (
        f"문서 생성 완료: {result.path}\n"
        f"모델: {result.model} | "
        f"입력 {result.input_tokens:,} + 출력 {result.output_tokens:,} = "
        f"총 {result.total_tokens:,} 토큰 | "
        f"소요 {result.elapsed_seconds:.1f}초"
    )


@mcp.tool()
def generate_template(
    samples: list[str],
    output: str,
    use_llm: bool | None = None,
) -> str:
    """샘플 HWPX 문서들을 분석하여 재사용 가능한 템플릿을 생성합니다.

    Args:
        samples: 분석할 샘플 HWPX 파일 경로 목록 (2개 이상 권장)
        output: 생성할 템플릿 파일 경로 (.hwpx)
        use_llm: LLM 보조 사용 여부 (None이면 공통 구조 신뢰도에 따라 자동 결정)
    """
    result_path = _get_pilot().generate_template(
        samples=samples,
        output=output,
        use_llm=use_llm,
    )
    return f"템플릿 생성 완료: {result_path}"


@mcp.tool()
def estimate_cost(
    data_folder: str,
    template: str,
    quick: bool = True,
) -> str:
    """문서 생성 전 예상 API 토큰 비용을 추정합니다. 실제 문서는 생성하지 않습니다.

    Args:
        data_folder: 데이터 파일이 있는 폴더 경로
        template: 템플릿 파일 경로 또는 내장 템플릿 이름
        quick: True(기본값)이면 파일 크기 기반 즉시 추정 (±30% 오차, API 호출 없음).
               False이면 인덱싱 + RAG + 토큰 카운팅 API로 정확하게 추정 (수 분 소요).
    """
    return _get_pilot().estimate_cost(
        data_folder=data_folder,
        template=template,
        quick=quick,
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
