from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from docpilot.search.highlight import render

_pilot = None


# ---------------------------------------------------------------------------
# 백그라운드 인덱싱 상태
# ---------------------------------------------------------------------------

class _IndexJob:
    def __init__(self, thread: threading.Thread, done_event: threading.Event, cancel_event: threading.Event) -> None:
        self.thread = thread
        self.done_event = done_event
        self.cancel_event = cancel_event
        self.count: int = 0
        self.files_done: int = 0
        self.started_at: float = 0.0
        self.error: Exception | None = None
        self.cancelled: bool = False


_index_jobs: dict[str, _IndexJob] = {}
_index_jobs_lock = threading.Lock()


def _resolve_embed_fn():
    """
    DOCPILOT_EMBED 환경변수에 따라 embed_fn을 반환합니다.

    값 형식:
      (미설정)            → default_embed_fn() — multilingual-e5-base 자동
      bge                 → bge_embed_fn()
      bge:cuda            → bge_embed_fn(device="cuda")
      openai              → openai_embed_fn()  (OPENAI_API_KEY 필요)
      openai:text-embedding-3-large → openai_embed_fn(model=...)
      voyage              → voyage_embed_fn()  (VOYAGE_API_KEY 필요)
      voyage:voyage-3-lite → voyage_embed_fn(model=...)
      sentence            → sentence_embed_fn()
      sentence:intfloat/multilingual-e5-large → sentence_embed_fn(model=...)
    """
    raw = os.environ.get("DOCPILOT_EMBED", "").strip()
    if not raw:
        return None  # DocPilot.__init__ will call default_embed_fn()

    from docpilot.search.embedding import (
        bge_embed_fn, openai_embed_fn, voyage_embed_fn, sentence_embed_fn,
    )

    provider, _, option = raw.partition(":")
    provider = provider.lower()

    match provider:
        case "bge":
            return bge_embed_fn(device=option or "cpu")
        case "openai":
            return openai_embed_fn(model=option) if option else openai_embed_fn()
        case "voyage":
            return voyage_embed_fn(model=option) if option else voyage_embed_fn()
        case "sentence":
            return sentence_embed_fn(model=option) if option else sentence_embed_fn()
        case _:
            import warnings
            warnings.warn(
                f"DOCPILOT_EMBED={raw!r} 값을 인식할 수 없습니다. "
                "기본 임베딩 모델을 사용합니다. "
                "유효한 값: bge, openai, voyage, sentence (콜론으로 옵션 구분 가능)",
                stacklevel=2,
            )
            return None


def _get_pilot():
    global _pilot
    if _pilot is None:
        from docpilot import DocPilot
        _pilot = DocPilot(
            llm=os.environ.get("DOCPILOT_LLM", "claude"),
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
            model=os.environ.get("DOCPILOT_MODEL") or None,
            database_url=os.environ.get("DOCPILOT_DATABASE_URL") or None,
            embed_fn=_resolve_embed_fn(),
        )
    return _pilot


mcp = FastMCP(
    "docpilot",
    instructions=(
        "docpilot는 데이터 폴더와 템플릿으로 HWPX / PDF / DOCX 문서를 자동 생성하고, "
        "인덱싱된 문서를 검색할 수 있습니다.\n"
        "\n"
        "## 문서 생성 워크플로 (generate_document)\n"
        "generate_document()는 인덱싱을 직접 관리하지 않습니다. 반드시 아래 2단계로 호출하세요.\n"
        "1단계: generate_document() 첫 호출 → 백그라운드 인덱싱 시작, '잠시 후 다시 호출하세요' 반환\n"
        "2단계: 잠시 기다린 후 generate_document() 재호출 → 실제 문서 생성\n"
        "인덱싱 오류 메시지가 반환되면 generate_document(reindex=True)로 재시도하세요.\n"
        "인덱싱이 오래 걸릴 경우 index_status()로 진행 상황을 확인하세요.\n"
        "\n"
        "## 검색 워크플로 (search_documents)\n"
        "index()로 폴더를 인덱싱한 뒤 search_documents()로 질의합니다.\n"
        "인덱스는 폴더 단위로 누적되므로 여러 폴더를 인덱싱하면 전체를 한 번에 검색할 수 있습니다.\n"
        "특정 폴더·파일만 검색하려면 source_pattern 파라미터를 사용하세요.\n"
        "\n"
        "## 인덱싱 상태 확인 (index_status)\n"
        "index_status()로 인덱싱 경과 시간과 처리 파일 수를 실시간으로 확인할 수 있습니다.\n"
        "\n"
        "## 특정 파일만 인덱싱 (index files=)\n"
        "index(data_folder=..., files=[\"파일명.pdf\", \"파일명2.hwpx\"])으로 폴더 내 특정 파일만 인덱싱할 수 있습니다.\n"
        "존재하지 않는 파일명을 지정하면 인덱싱을 시작하지 않고 오류를 반환합니다.\n"
        "\n"
        "## 인덱싱 취소 (cancel_index)\n"
        "cancel_index()로 진행 중인 인덱싱을 중단할 수 있습니다. "
        "취소는 현재 처리 중인 파일이 완료된 직후 적용됩니다.\n"
        "\n"
        "## 고아 레코드 정리 (cleanup_index)\n"
        "폴더 이름 변경·파일 삭제 후 cleanup_index()를 호출하면 "
        "디스크에 존재하지 않는 파일의 인덱스 레코드를 삭제합니다.\n"
        "data_folder를 지정하면 해당 경로 하위 레코드만 검사합니다.\n"
        "\n"
        "## 커버리지 분석 (analyze_coverage)\n"
        "generate_document() 전에 analyze_coverage()로 데이터 폴더가 각 섹션을 얼마나 커버하는지 확인할 수 있습니다.\n"
        "LOW 섹션은 LLM이 추론하여 작성하므로 generate_document() 후 반드시 검토하세요.\n"
        "\n"
        "## 내장 템플릿\n"
        "report   — 일반 보고서: 보고서 제목, 작성일, 작성자/부서, "
        "섹션1 제목, 섹션1 내용, 섹션2 제목, 섹션2 내용, 표 삽입 위치, 결론, 결론 내용\n"
        "gonmun   — 공문: 기관명, 수신자, 경유, 제목, 본문1, 본문2, 표 또는 상세내용, "
        "직위 성명, 시행번호, 시행일자, 우편번호, 주소, 홈페이지, 전화번호, 팩스번호, 이메일\n"
        "minutes  — 회의록: 회의록 제목, 일시, 장소, 참석자 목록, 작성자, "
        "안건 내용, 논의 내용, 결정 사항, 향후 조치 사항\n"
        "proposal — 제안서: 사업 개요, 추진 배경, 추진 근거\n"
        "\n"
        "사용 전 ANTHROPIC_API_KEY 환경 변수가 설정되어 있어야 합니다."
    ),
)


def _start_index_job(
    folder_key: str,
    data_folder: str,
    force: bool = False,
    files: list[str] | None = None,
) -> _IndexJob:
    """백그라운드 인덱싱 스레드를 시작하고 _IndexJob을 반환한다."""
    done = threading.Event()
    cancel = threading.Event()

    def _run() -> None:
        def _on_file(n: int) -> None:
            job.files_done = n

        try:
            from docpilot.db import indexer
            pilot = _get_pilot()
            doc_ids = indexer.index_folder(
                data_folder,
                embed_fn=pilot._embed_fn,
                force=force,
                progress_fn=_on_file,
                cancel_event=cancel,
                files=files,
            )
            job.count = len(doc_ids)
        except indexer.IndexCancelledError:
            job.cancelled = True
        except Exception as exc:
            job.error = exc
        finally:
            done.set()

    t = threading.Thread(target=_run, daemon=True, name=f"docpilot-index-{folder_key}")
    job = _IndexJob(thread=t, done_event=done, cancel_event=cancel)
    job.started_at = time.time()

    with _index_jobs_lock:
        _index_jobs[folder_key] = job

    t.start()
    return job


@mcp.tool()
def index(data_folder: str, reindex: bool = False, files: list[str] | None = None) -> str:
    """데이터 폴더를 검색 인덱스에 등록합니다. search() 전에 먼저 실행하세요.

    generate()는 내부적으로 인덱싱을 자동 수행하므로, 순수 검색 목적으로만
    인덱스를 쌓을 때 이 도구를 직접 사용합니다.
    인덱싱은 백그라운드에서 실행되며 즉시 반환됩니다.

    Args:
        data_folder: 인덱싱할 파일이 있는 폴더 경로 (절대 경로 권장, 하위 폴더 재귀 탐색)
        reindex: True이면 이미 인덱싱된 파일도 강제 재인덱싱 (기본값: False)
        files: 인덱싱할 파일명 목록 (예: ["report.pdf", "data.xlsx"]). 미지정 시 폴더 전체 인덱싱.
               폴더 내 존재하지 않는 파일명이 있으면 인덱싱을 시작하지 않고 오류를 반환합니다.
    """
    _fp = Path(data_folder)
    if not _fp.exists():
        return f"폴더를 찾을 수 없습니다: {data_folder}\n절대 경로로 지정했는지 확인하세요."
    if not _fp.is_dir():
        return f"지정한 경로가 폴더가 아닙니다: {data_folder}"

    if files is not None:
        existing_names = {f.name.lower() for f in _fp.rglob("*") if f.is_file()}
        missing = [f for f in files if f.lower() not in existing_names]
        if missing:
            missing_str = "\n".join(f"  · {f}" for f in missing)
            return (
                f"다음 파일을 폴더에서 찾을 수 없습니다:\n{missing_str}\n"
                f"폴더: {data_folder}\n"
                "파일명(확장자 포함)을 정확히 입력했는지 확인하세요."
            )

    folder_key = str(_fp.resolve())

    with _index_jobs_lock:
        existing = _index_jobs.get(folder_key)
        if existing and existing.thread.is_alive():
            elapsed = int(time.time() - existing.started_at)
            return (
                f"이미 인덱싱 진행 중: {data_folder}\n"
                f"경과 {elapsed}초, 처리 파일 {existing.files_done}개 — 완료 후 재시도하거나 index_status()로 확인하세요."
            )

    _start_index_job(folder_key, data_folder, force=reindex, files=files)

    if files:
        files_str = ", ".join(files)
        return (
            f"인덱싱 시작됨: {data_folder}\n"
            f"대상 파일: {files_str}\n"
            "백그라운드에서 진행 중입니다."
        )
    return (
        f"인덱싱 시작됨: {data_folder}\n"
        "백그라운드에서 진행 중입니다. "
        "generate() 호출 시 완료를 자동으로 기다립니다."
    )


@mcp.tool()
def index_status(data_folder: str | None = None) -> str:
    """인덱싱 작업의 현재 상태를 확인합니다.

    인덱싱이 오래 걸릴 경우 이 도구로 진행 상황(경과 시간·처리 파일 수)을 확인하세요.

    Args:
        data_folder: 확인할 폴더 경로 (미지정 시 전체 작업 표시)
    """
    now = time.time()
    with _index_jobs_lock:
        if data_folder:
            folder_key = str(Path(data_folder).resolve())
            jobs = [(folder_key, _index_jobs[folder_key])] if folder_key in _index_jobs else []
        else:
            jobs = list(_index_jobs.items())

    if not jobs:
        return (
            "인덱싱 기록이 없습니다.\n"
            "index() 또는 generate_document()로 먼저 인덱싱하세요."
        )

    lines = []
    for key, job in jobs:
        elapsed = int(now - job.started_at) if job.started_at else 0
        name = Path(key).name
        if job.thread.is_alive():
            cancel_hint = "  (취소 요청됨, 현재 파일 처리 후 중단)" if job.cancel_event.is_set() else ""
            lines.append(
                f"[진행 중] {name}  경과 {elapsed}초  처리 파일 {job.files_done}개{cancel_hint}"
            )
        elif job.cancelled:
            lines.append(
                f"[취소됨]  {name}  소요 {elapsed}초  처리 파일 {job.files_done}개"
            )
        elif job.error:
            lines.append(
                f"[오류]    {name}  소요 {elapsed}초 → {job.error}\n"
                "          index(reindex=True)로 재시도하세요."
            )
        else:
            lines.append(
                f"[완료]    {name}  소요 {elapsed}초  총 {job.count}개 파일"
            )
    return "\n".join(lines)


@mcp.tool()
def cancel_index(data_folder: str | None = None) -> str:
    """진행 중인 인덱싱 작업을 취소합니다.

    취소는 현재 처리 중인 파일이 완료되거나 timeout된 직후 적용됩니다.
    이미 처리된 파일은 인덱스에 그대로 유지됩니다.

    Args:
        data_folder: 취소할 폴더 경로 (미지정 시 모든 진행 중인 작업을 취소)
    """
    with _index_jobs_lock:
        if data_folder:
            folder_key = str(Path(data_folder).resolve())
            jobs = [(folder_key, _index_jobs[folder_key])] if folder_key in _index_jobs else []
        else:
            jobs = [(k, j) for k, j in _index_jobs.items() if j.thread.is_alive()]

    if not jobs:
        return "취소할 진행 중인 인덱싱 작업이 없습니다."

    cancelled = []
    for key, job in jobs:
        if job.thread.is_alive() and not job.cancel_event.is_set():
            job.cancel_event.set()
            cancelled.append(Path(key).name)
        elif job.cancel_event.is_set():
            cancelled.append(f"{Path(key).name} (이미 취소 요청됨)")

    if not cancelled:
        return "취소할 진행 중인 인덱싱 작업이 없습니다."

    names = ", ".join(cancelled)
    return (
        f"취소 요청 전송됨: {names}\n"
        "현재 처리 중인 파일이 끝나면 중단됩니다. index_status()로 상태를 확인하세요."
    )


@mcp.tool()
def cleanup_index(data_folder: str | None = None) -> str:
    """디스크에 더 이상 존재하지 않는 파일의 인덱스 레코드를 삭제합니다.

    폴더 이름을 변경하거나 파일을 삭제한 뒤 호출하면 DB의 고아 레코드를 정리할 수 있습니다.

    Args:
        data_folder: 정리할 폴더 경로 (지정 시 해당 폴더 하위 레코드만 검사, 미지정 시 DB 전체 검사)
    """
    from docpilot.db import indexer

    try:
        deleted = indexer.cleanup_orphans(folder=data_folder)
    except Exception as e:
        return f"정리 중 오류 발생: {e}"

    if not deleted:
        scope = data_folder or "전체 DB"
        return f"삭제할 고아 레코드가 없습니다 ({scope})."

    lines = [f"고아 레코드 {len(deleted)}개 삭제 완료:"]
    for path in deleted:
        lines.append(f"  · {path}")
    return "\n".join(lines)


_CONVERSIONS = {
    (".hwp", ".docx"): "docx",
    (".hwpx", ".docx"): "docx",
    (".hwp", ".hwpx"): "hwpx",
}
_DEFAULT_OUTPUT_EXT = {".hwp": ".docx", ".hwpx": ".docx", ".docx": ".hwpx"}

# 알려진 이슈: 일부 한컴오피스 설치 환경에서 COM을 통한 DOCX 가져오기(Open) 자체가 실패한다.
# 재현 확인됨(format 힌트·visible 모드·forceopen 옵션 무관하게 항상 실패). 원인 불명이라 보류 중.
_KNOWN_UNSUPPORTED = {(".docx", ".hwpx")}


@mcp.tool()
def convert_document(source: str, output: str | None = None) -> str:
    """한컴오피스(한글) COM 자동화로 문서 포맷을 변환합니다.

    지원 방향: .hwp/.hwpx → .docx, .hwp → .hwpx
    Windows + 한컴오피스(한글)가 설치된 환경에서만 동작합니다.

    [알려진 이슈] .docx → .hwpx는 미지원입니다. 일부 한컴오피스 설치 환경에서
    COM을 통한 DOCX 가져오기(Open) 자체가 실패하는 문제가 재현되어 보류 중입니다.
    한/글에서 파일 > 열기로 수동으로 열어 다른 이름으로 저장(hwpx)하세요.

    Args:
        source: 변환할 .hwp, .hwpx 또는 .docx 파일 경로
        output: 출력 파일 경로 (미지정 시 source와 같은 폴더에 기본 반대 포맷으로 저장 — .hwp/.hwpx는 .docx, .hwp는 .hwpx)
    """
    from docpilot.builder.hwp_convert import convert_to_docx, convert_to_hwpx
    from docpilot.exceptions import DocPilotError

    src = Path(source)
    if not src.exists():
        return f"파일을 찾을 수 없습니다: {source}"

    src_ext = src.suffix.lower()
    if src_ext not in _DEFAULT_OUTPUT_EXT:
        return f"지원하지 않는 입력 형식입니다: {src_ext} (.hwp, .hwpx, .docx만 가능)"

    out = Path(output) if output else src.with_suffix(_DEFAULT_OUTPUT_EXT[src_ext])
    out_ext = out.suffix.lower()

    if (src_ext, out_ext) in _KNOWN_UNSUPPORTED:
        return (
            f"{src_ext} → {out_ext} 변환은 현재 지원하지 않습니다 (알려진 이슈).\n"
            "일부 한컴오피스 설치 환경에서 COM을 통한 DOCX 가져오기(Open) 자체가 실패하는 "
            "문제가 재현되어 보류 중입니다. 한/글에서 파일 > 열기로 수동으로 열어 "
            "다른 이름으로 저장(hwpx)하세요."
        )

    target = _CONVERSIONS.get((src_ext, out_ext))
    if target is None:
        return f"지원하지 않는 변환입니다: {src_ext} → {out_ext}"

    convert_fn, label = (convert_to_docx, "DOCX") if target == "docx" else (convert_to_hwpx, "HWPX")

    try:
        result = convert_fn(src, out)
    except DocPilotError as e:
        return f"변환 실패: {e}"

    return f"{label} 변환 완료: {result}"


@mcp.tool()
def search_documents(
    query: str,
    data_folder: str | None = None,
    mode: str = "hybrid",
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

    index()가 백그라운드에서 실행 중이면 완료를 기다리도록 안내합니다.
    data_folder를 지정하면 해당 폴더의 인덱싱 완료 여부만 확인하고,
    지정하지 않으면 진행 중인 인덱싱 잡이 있는지 전체를 확인합니다.

    Args:
        query: 검색 질의 문자열
        data_folder: index()에 사용한 폴더 경로 (인덱싱 완료 확인용, 선택)
        mode: 검색 방식 — "hybrid"(BM25+Vector RRF, 기본값), "morpheme"(형태소 BM25),
              "exact"(키워드 LIKE), "vector"(벡터 유사도, embed_fn 구성 필요)
        top_k: 반환할 최대 결과 수 (기본값: 10)
        group_by_doc: True이면 결과를 문서 단위로 집계하여 반환 (기본값: False)
        highlight: True이면 쿼리 텀을 ** 마커로 강조 (기본값: True)
        source_pattern: 파일 경로 glob 패턴 필터 (예: "reports/*.hwpx")
        mime_type: MIME 타입 필터 (예: "application/vnd.hancom.hwpx")
        metadata: 문서 메타데이터 key-value 필터 (예: {"dept": "기획", "year": "2026"})
        created_after: 인덱싱 날짜 하한 — ISO 8601 형식 (예: "2026-01-01")
        created_before: 인덱싱 날짜 상한 — ISO 8601 형식 (예: "2026-12-31")
    """
    # 인덱싱 완료 여부 확인
    with _index_jobs_lock:
        if data_folder:
            folder_key = str(Path(data_folder).resolve())
            job = _index_jobs.get(folder_key)
            if job is None:
                return (
                    f"'{data_folder}' 폴더가 아직 인덱싱되지 않았습니다. "
                    "먼저 index()를 호출하세요."
                )
            if job.thread.is_alive():
                elapsed = int(time.time() - job.started_at)
                return (
                    f"인덱싱 진행 중입니다 (경과 {elapsed}초, 처리 파일 {job.files_done}개). "
                    "잠시 후 다시 search_documents()를 호출하세요."
                )
            if job.error:
                return (
                    f"인덱싱 중 오류가 발생했습니다: {job.error}\n"
                    "index(reindex=True)로 재시도하세요."
                )
        else:
            running = [k for k, j in _index_jobs.items() if j.thread.is_alive()]
            if running:
                folders = ", ".join(Path(k).name for k in running)
                return f"인덱싱이 진행 중입니다 ({folders}). 잠시 후 다시 search_documents()를 호출하세요."

    from datetime import datetime

    from docpilot.search import (
        SearchFilter,
        group_by_document,
        highlight as highlight_fn,
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
        try:
            results = morpheme.search(query, top_k=top_k, or_fallback=True, filters=filters)
        except Exception as e:
            if "kiwipiepy" in str(e):
                results = exact.search(query, top_k=top_k, filters=filters)
                if not results:
                    return (
                        "검색 결과가 없습니다.\n"
                        "[참고] kiwipiepy 미설치로 exact 검색으로 대체되었습니다. "
                        "형태소 검색을 사용하려면: pip install \"docpilot[morpheme]\""
                    )
                highlight = False  # exact 결과엔 형태소 하이라이팅 불필요
            else:
                raise
    elif mode == "vector":
        if pilot._embed_fn is None:
            return (
                "vector 모드는 embed_fn 설정이 필요합니다. "
                "DOCPILOT_EMBED 환경변수 또는 DocPilot(embed_fn=...) 설정을 확인하세요."
            )
        from docpilot.search import embedding as emb_mod
        results = emb_mod.search(query, embed_fn=pilot._embed_fn, top_k=top_k, filters=filters)
    elif mode == "hybrid":
        from docpilot.search.hybrid import hybrid as hybrid_search
        try:
            results = hybrid_search(
                query, embed_fn=pilot._embed_fn, top_k=top_k, filters=filters, or_fallback=True
            )
        except Exception as e:
            if "kiwipiepy" in str(e):
                results = exact.search(query, top_k=top_k, filters=filters)
                if not results:
                    return (
                        "검색 결과가 없습니다.\n"
                        "[참고] kiwipiepy 미설치로 exact 검색으로 대체되었습니다. "
                        "형태소 검색을 사용하려면: pip install \"docpilot[morpheme]\""
                    )
                highlight = False
            else:
                raise
    else:
        return f"알 수 없는 mode: {mode!r}. 'hybrid' / 'morpheme' / 'exact' / 'vector' 중 선택하세요."

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
def generate_document(
    data_folder: str,
    template: str,
    output: str | None = None,
    reindex: bool = False,
    extra_instructions: str | None = None,
    instructions_doc: str | None = None,
    top_k: int = 10,
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
        top_k: RAG 검색에서 가져올 청크 수 (기본값: 10). 짧은 문서(공문 등)는 낮게, 긴 보고서·제안서는 높게 설정하세요.
    """
    if output is None:
        output = _default_output(template)

    # 폴더 존재 여부 사전 검증
    _fp = Path(data_folder)
    if not _fp.exists():
        return (
            f"폴더를 찾을 수 없습니다: {data_folder}\n"
            "절대 경로로 지정했는지 확인하세요."
        )
    if not _fp.is_dir():
        return f"지정한 경로가 폴더가 아닙니다: {data_folder}"

    # 내장 템플릿(.hwpx)인데 output이 .docx/.pdf이면 LLM 호출 전에 조기 차단
    _BUILTIN_NAMES = {"report", "gonmun", "minutes", "proposal"}
    _out_ext = Path(output).suffix.lower()
    _tpl_is_builtin = str(template) in _BUILTIN_NAMES
    _tpl_ext = Path(str(template)).suffix.lower() if not _tpl_is_builtin else ".hwpx"
    if _tpl_ext != _out_ext and _out_ext in (".docx", ".pdf"):
        expected = _tpl_ext if _tpl_ext in (".hwpx", ".docx", ".pdf") else ".hwpx"
        return (
            f"템플릿 형식({_tpl_ext or '.hwpx'})과 출력 형식({_out_ext})이 일치하지 않습니다.\n"
            f"output 확장자를 {expected}로 변경하거나, "
            f"출력 형식에 맞는 템플릿 파일을 직접 지정하세요.\n"
            "내장 템플릿(report/gonmun/minutes/proposal)은 HWPX 전용입니다."
        )

    folder_key = str(_fp.resolve())
    with _index_jobs_lock:
        job = _index_jobs.get(folder_key)

    # 잡 없음, 또는 완료된 잡인데 reindex=True 요청 → 새 잡 시작
    if job is None or (reindex and not job.thread.is_alive()):
        _start_index_job(folder_key, data_folder, force=reindex)
        return (
            f"데이터 폴더 인덱싱을 시작했습니다: {data_folder}\n"
            "잠시 후 다시 generate_document()를 호출하세요.\n"
            "index_status()로 진행 상황을 확인할 수 있습니다."
        )

    if job.thread.is_alive():
        elapsed = int(time.time() - job.started_at)
        return (
            f"인덱싱 진행 중입니다 (경과 {elapsed}초, 처리 파일 {job.files_done}개). "
            "잠시 후 다시 generate_document()를 호출하세요."
        )

    if job.error:
        return (
            f"인덱싱 중 오류 발생: {job.error}\n"
            "generate_document(reindex=True)로 재시도하세요."
        )

    # 인덱싱 완료 → 문서 생성 (bg 잡이 이미 인덱싱했으므로 reindex=False)
    result = _get_pilot().generate(
        data_folder=data_folder,
        template=template,
        output=output,
        reindex=False,
        extra_instructions=extra_instructions,
        instructions_doc=instructions_doc,
        top_k=top_k,
    )
    msg = (
        f"문서 생성 완료: {result.path}\n"
        f"모델: {result.model} | "
        f"입력 {result.input_tokens:,} + 출력 {result.output_tokens:,} = "
        f"총 {result.total_tokens:,} 토큰 | "
        f"소요 {result.elapsed_seconds:.1f}초"
    )
    if result.output_tokens > result.input_tokens:
        msg += (
            "\n[경고] 출력 토큰이 입력 토큰보다 많습니다. "
            "데이터 폴더의 내용이 부족해 LLM이 내용을 추론하여 작성했을 수 있습니다. "
            "문서 내용을 반드시 검토하세요."
        )
    return msg


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


@mcp.tool()
def analyze_coverage(
    data_folder: str,
    template: str,
    top_k: int = 3,
) -> str:
    """템플릿 섹션별로 데이터 폴더의 커버리지를 분석합니다.

    generate() 전에 호출하여 LLM이 데이터 기반으로 작성 가능한지,
    추론이 필요한 섹션이 있는지 미리 파악할 수 있습니다.
    index() 또는 generate() 첫 호출로 인덱싱이 완료된 후에 사용하세요.

    Args:
        data_folder: 분석할 데이터 파일이 있는 폴더 경로
        template: 템플릿 파일 경로 또는 내장 템플릿 이름 (report/gonmun/minutes/proposal)
        top_k: 섹션별 검색 결과 수 — 등급 기준값 (기본값: 3)
    """
    _BUILTIN_NAMES = {"report", "gonmun", "minutes", "proposal"}

    # 1. 템플릿 섹션 추출
    if str(template) in _BUILTIN_NAMES:
        from docpilot import _assemble_builtin_hwpx, _extract_placeholders
        tpl_path = _assemble_builtin_hwpx(str(template))
        sections = _extract_placeholders(tpl_path)
    else:
        tpl_path = Path(template)
        if not tpl_path.exists():
            return f"템플릿 파일을 찾을 수 없습니다: {template}"
        from docpilot import _extract_placeholders
        sections = _extract_placeholders(tpl_path)

    if not sections:
        return (
            f"템플릿에서 섹션({{{{...}}}})을 추출할 수 없습니다: {template}\n"
            "플레이스홀더가 없는 Reference Mode 템플릿은 analyze_coverage를 지원하지 않습니다."
        )

    # 2. 인덱싱 상태 확인
    folder_key = str(Path(data_folder).resolve())
    with _index_jobs_lock:
        job = _index_jobs.get(folder_key)

    if job is not None and job.thread.is_alive():
        return "인덱싱 진행 중입니다. 완료 후 다시 analyze_coverage()를 호출하세요."
    if job is not None and job.error:
        return f"인덱싱 오류: {job.error}\nindex(reindex=True)로 재시도하세요."

    from docpilot.db import client as db_client
    from docpilot.db.schema import Document
    with db_client.session() as db:
        doc_count = db.query(Document).count()
    if doc_count == 0:
        return (
            "인덱싱된 문서가 없습니다.\n"
            "먼저 index() 또는 generate()로 데이터 폴더를 인덱싱하세요."
        )

    # 3. 섹션별 검색
    pilot = _get_pilot()
    from docpilot.search import exact as exact_search

    section_scores: list[tuple[str, int, float]] = []
    for section_name in sections:
        try:
            from docpilot.search.hybrid import hybrid as hybrid_fn
            results = hybrid_fn(
                section_name,
                embed_fn=pilot._embed_fn,
                top_k=top_k,
                or_fallback=True,
            )
        except Exception:
            results = exact_search.search(section_name, top_k=top_k)

        count = len(results)
        top_score = results[0].score if results else 0.0
        section_scores.append((section_name, count, top_score))

    # 4. 등급 산정 및 리포트 생성
    def _grade(count: int) -> str:
        if count >= top_k:
            return "HIGH"
        if count >= 1:
            return "MED"
        return "LOW"

    graded = [(name, _grade(cnt), cnt, score) for name, cnt, score in section_scores]
    high = [g for g in graded if g[1] == "HIGH"]
    med  = [g for g in graded if g[1] == "MED"]
    low  = [g for g in graded if g[1] == "LOW"]

    tpl_label = str(template) if str(template) in _BUILTIN_NAMES else Path(template).name
    lines = [
        "데이터 커버리지 분석",
        f"  데이터 폴더: {data_folder}",
        f"  템플릿:     {tpl_label}  (인덱싱 문서 {doc_count}개)",
        f"  총 {len(sections)}개 섹션 — HIGH {len(high)} | MED {len(med)} | LOW {len(low)}",
        "",
        "섹션별 커버리지",
        "─" * 50,
    ]
    for name, grade, count, score in graded:
        chunk_str = f"{count}청크" if count > 0 else "0청크"
        score_str = f"  score {score:.4f}" if count > 0 else ""
        lines.append(f"[{grade:4s}] {name:<22s}  {chunk_str}{score_str}")

    lines.append("")
    if not low:
        lines.append("[권고] 모든 섹션에 관련 데이터가 있습니다. generate()를 실행하세요.")
    else:
        lines.append(f"[권고] LOW 섹션 {len(low)}개 — LLM이 내용을 추론할 가능성이 높습니다.")
        lines.append(f"  LOW 섹션: {', '.join(g[0] for g in low)}")
        lines.append("  · 해당 내용이 포함된 파일을 데이터 폴더에 추가하거나")
        lines.append("  · LLM이 추론 작성하도록 허용하고 generate() 후 문서를 직접 검토하세요.")

    return "\n".join(lines)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
