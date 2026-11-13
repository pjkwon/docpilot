"""DocPilot — 인덱싱 → 검색 → LLM 매핑 → 문서 빌드 파이프라인."""
from __future__ import annotations

import atexit
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from docpilot.assembly import _resolve_builder, _validate_hwpx
from docpilot.exceptions import DocPilotError, MappingError
from docpilot.extras import suggest_extras
from docpilot.placeholders import convert_to_list_placeholder
from docpilot.template_resolver import (
    _get_builtin_metadata,
    _resolve_instructions,
    _resolve_sections,
    _resolve_template_path,
    _sidecar_source,
)

if TYPE_CHECKING:
    from docpilot.ingestion.models import IngestedDocument


@dataclass
class GenerateResult:
    path: Path
    model: str
    input_tokens: int
    output_tokens: int
    elapsed_seconds: float

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def __str__(self) -> str:
        return str(self.path)

    def __fspath__(self) -> str:
        return str(self.path)


_MODEL_PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-4-8":   (5.00, 25.00),
    "claude-opus-4-7":   (5.00, 25.00),
    "claude-opus-4-6":   (5.00, 25.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5":  (1.00,  5.00),
}
_EST_OUTPUT_TOKENS_PER_SECTION = 500


def _m(model: str | None) -> dict:
    return {"model": model} if model else {}


def _b(base_url: str | None) -> dict:
    return {"base_url": base_url} if base_url else {}


def _n(num_ctx: int | None) -> dict:
    return {"num_ctx": num_ctx} if num_ctx else {}


def _t(temperature: float | None) -> dict:
    return {"temperature": temperature} if temperature is not None else {}


def _estimate_tokens_from_folder(folder: Path, n_sections: int) -> int:
    """Rough token estimate from data folder file sizes. ~0.4 tokens/byte for Korean text."""
    _TEXT_EXTS = {".txt", ".md", ".rst", ".csv", ".hwpx", ".docx"}
    _BINARY_EXTS = {".pdf"}
    total_bytes = 0
    for f in folder.rglob("*"):
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        if ext in _TEXT_EXTS:
            total_bytes += f.stat().st_size
        elif ext in _BINARY_EXTS:
            total_bytes += f.stat().st_size * 3  # OCR/extracted text is larger than raw binary
    tokens_per_byte = 0.4
    raw_tokens = int(total_bytes * tokens_per_byte)
    # RAG retrieves a subset, not the full corpus — cap at ~4,000 tokens per section
    return min(raw_tokens, n_sections * 4000)


_DEFAULT_MAX_INPUT_TOKENS_WARN = 50_000


def _resolve_content(content: str | list[str | Path] | list[IngestedDocument]) -> str:
    """Resolve the content union type shared by *_from_content() methods into a single string."""
    from docpilot.ingestion.models import IngestedDocument
    from docpilot.mapping.base import merge_documents

    if isinstance(content, str):
        return content
    if content and isinstance(content[0], IngestedDocument):
        return merge_documents(content)

    from docpilot.ingestion import ingest_paths
    docs = ingest_paths(content)
    if not docs:
        raise DocPilotError("content에서 ingest 가능한 파일을 찾지 못했습니다.", detail=str(content))
    return merge_documents(docs)


def _check_content_size(content_str: str, max_input_tokens: int | None) -> None:
    """Warn or raise on a rough byte-based token estimate — *_from_content() methods send
    content in full with no RAG top_k to bound its size automatically."""
    from docpilot.tokens import estimate_tokens_raw
    estimated_tokens = estimate_tokens_raw(content_str)
    if max_input_tokens is not None:
        if estimated_tokens > max_input_tokens:
            raise MappingError(
                f"콘텐츠 예상 입력 토큰 수({estimated_tokens:,})가 "
                f"max_input_tokens({max_input_tokens:,})를 초과합니다.",
                detail="content 크기를 줄이거나 max_input_tokens를 늘리세요.",
            )
    elif estimated_tokens > _DEFAULT_MAX_INPUT_TOKENS_WARN:
        import warnings
        warnings.warn(
            f"콘텐츠 예상 입력 토큰 수가 {estimated_tokens:,}로 큽니다 "
            f"(경고 기준: {_DEFAULT_MAX_INPUT_TOKENS_WARN:,}). RAG와 달리 이 경로는 "
            "content를 통째로 프롬프트에 넣으므로 컨텍스트 초과·비용 증가 위험이 있습니다. "
            "content를 줄이거나 max_input_tokens로 명시적 상한을 거세요.",
            stacklevel=2,
        )


_SUPPORTED_LLMS = ("claude", "openai", "gemini", "grok", "ollama")


class DocPilot:
    """
    Main entry point for docpilot.

    pilot = DocPilot(llm="claude")
    pilot.index(data_folder="./data")
    pilot.generate(data_folder="./data", template="research_report", output="./out.hwpx")

    The ``embed_fn`` passed here is reused for both indexing and search (self._embed_fn),
    so a single instance always keeps them consistent. Creating separate instances with
    different ``embed_fn`` values against the same DB — or calling ``indexer``/``embedding``
    functions directly instead of through this class — can silently break vector search if
    the models don't match (see README "임베딩 제공자").
    """

    def __init__(
        self,
        llm: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        num_ctx: int | None = None,
        temperature: float | None = None,
        database_url: str | None = None,
        embed_fn=None,
        use_reranker: bool = False,
    ) -> None:
        """
        num_ctx: Ollama-only — the context window (input+output token budget) the server
            loaded the model with. Ollama defaults to a small value (often 4096) regardless
            of what the model actually supports, and silently truncates prompts that exceed
            it rather than erroring — see README "Ollama 등 로컬 모델의 컨텍스트 한도". Pass the
            same value your Ollama server was started/configured with (check via `ollama ps`)
            so docpilot can (a) forward it as a per-request option and (b) reject oversized
            RAG/content prompts before sending them, instead of silently losing context.
        temperature: sampling temperature forwarded to whichever provider is active. None
            (default) leaves the provider/model's own default untouched. Lower it (e.g. 0)
            for more deterministic, structured output — useful since the JSON-mapping prompt
            can otherwise produce inconsistent results run to run (observed with local
            Ollama models especially; see llm_benchmark_report.md).
        """
        self._llm = llm or os.environ.get("DOCPILOT_LLM", "claude")
        if self._llm.lower() not in _SUPPORTED_LLMS:
            raise MappingError(
                f"Unknown LLM '{self._llm}'. Supported: {', '.join(_SUPPORTED_LLMS)}"
            )
        self._api_key = api_key
        if embed_fn is None:
            from docpilot.search.embedding import default_embed_fn
            embed_fn = default_embed_fn()  # None when sentence-transformers not installed
        self._embed_fn = embed_fn
        self._use_reranker = use_reranker

        # LLM 매퍼(와 API 키 검증)는 처음 필요해질 때 만든다 — index()/search()/
        # generate_template(use_llm=False)처럼 LLM을 쓰지 않는 작업은 API 키 없이도 동작해야 한다.
        model = model or os.environ.get("DOCPILOT_MODEL")
        self._mapper_args = (self._llm, api_key, model, base_url, num_ctx, temperature)
        self._mapper_instance = None
        self._rag_mapper_instance = None

        from docpilot.db import client as db_client
        from docpilot.search.embedding import embedding_dim
        db_client.init(database_url)
        # 벡터 테이블을 embed_fn의 실제 차원으로 만든다 (기존 DB와 다르면 SearchError)
        db_client.create_tables(embedding_dim=embedding_dim(embed_fn))

    @property
    def _mapper(self):
        """LLM 매퍼 — 첫 접근 시 생성되며, API 키 누락은 이때 MappingError로 드러난다."""
        if self._mapper_instance is None:
            self._mapper_instance = self._build_mapper(*self._mapper_args)
        return self._mapper_instance

    @_mapper.setter
    def _mapper(self, mapper) -> None:
        self._mapper_instance = mapper
        self._rag_mapper_instance = None  # 다음 접근 때 새 매퍼로 다시 감싼다

    @property
    def _rag_mapper(self):
        if self._rag_mapper_instance is None:
            from docpilot.mapping.rag import RagMapper
            self._rag_mapper_instance = RagMapper(
                self._mapper, embed_fn=self._embed_fn, use_reranker=self._use_reranker,
            )
        return self._rag_mapper_instance

    def index(self, data_folder: str | Path, collection: str | None = None) -> list[int]:
        """Ingest and index all supported files in a folder.

        collection: optional tag to scope later searches (see SearchFilter.collection).
        """
        from docpilot.db import indexer
        return indexer.index_folder(data_folder, embed_fn=self._embed_fn, collection=collection)

    def search(
        self,
        query: str,
        top_k: int = 10,
        mode: str = "hybrid",
        filters=None,
        or_fallback: bool = True,
        highlight: bool = False,
        group_by_doc: bool = False,
        collection: str | None = None,
    ):
        """
        Search indexed documents.

        mode:
            ``"hybrid"``  — BM25 + Vector fused with RRF (default; falls back to BM25 when no embed_fn).
            ``"bm25"``    — Morpheme FTS5 / BM25 only.
            ``"vector"``  — Vector similarity only (embed_fn required).
            ``"exact"``   — ILIKE keyword match.
        filters:
            ``SearchFilter`` instance for source/MIME/metadata/date constraints.
        or_fallback:
            For BM25/hybrid — retry with OR logic when AND returns no results.
        highlight:
            If True, populate each result's ``.highlights`` spans for *query* terms.
            Render the marked-up text with ``docpilot.search.highlight.render(result)``.
        group_by_doc:
            If True, aggregate chunk-level results into per-document ``DocumentResult``
            objects — returns ``list[DocumentResult]`` instead of ``list[SearchResult]``.
            Uses ``score="max"`` (best single chunk wins; favors documents where matches
            are concentrated in one chunk). For ``score="sum"`` (favors documents where
            the query recurs across many chunks) call
            ``docpilot.search.group_by_document(results, score="sum")`` directly instead.
        collection:
            Convenience shorthand for ``filters.collection`` — scopes the search to documents
            indexed with this tag. Raises ``ValueError`` if *filters* already sets a different
            ``collection``.

        "bm25"/"hybrid" modes fall back to "exact" and emit a ``UserWarning`` when
        kiwipiepy isn't installed, instead of raising.
        """
        import warnings
        from dataclasses import replace as _dc_replace
        from docpilot.exceptions import SearchError
        from docpilot.search import exact, morpheme
        from docpilot.search.models import SearchFilter

        if collection is not None:
            if filters is None:
                filters = SearchFilter(collection=collection)
            elif filters.collection is None:
                filters = _dc_replace(filters, collection=collection)
            elif filters.collection != collection:
                raise ValueError(
                    f"collection={collection!r} conflicts with filters.collection={filters.collection!r}"
                )

        try:
            match mode:
                case "exact":
                    results = exact.search(query, top_k=top_k, filters=filters)
                case "bm25":
                    results = morpheme.search(query, top_k=top_k, or_fallback=or_fallback, filters=filters)
                case "vector":
                    if self._embed_fn is None:
                        raise SearchError(
                            "vector 모드는 embed_fn 설정이 필요합니다",
                            detail="DOCPILOT_EMBED 환경변수 또는 DocPilot(embed_fn=...) 설정을 확인하세요",
                        )
                    from docpilot.search import embedding
                    results = embedding.search(query, embed_fn=self._embed_fn, top_k=top_k, filters=filters)
                case _:  # "hybrid"
                    from docpilot.search.hybrid import hybrid
                    results = hybrid(
                        query,
                        embed_fn=self._embed_fn,
                        top_k=top_k,
                        filters=filters,
                        or_fallback=or_fallback,
                    )
        except SearchError as e:
            if mode in ("bm25", "hybrid") and "kiwipiepy" in str(e):
                warnings.warn(
                    f"kiwipiepy 미설치로 exact 검색으로 대체합니다 (형태소 검색을 쓰려면 "
                    f"pip install kiwipiepy — 기본 설치에 포함되므로 보통은 발생하지 않는 상황입니다): {e}",
                    stacklevel=2,
                )
                results = exact.search(query, top_k=top_k, filters=filters)
            else:
                raise

        if highlight:
            from docpilot.search import highlight as highlight_fn
            results = [highlight_fn(r, query) for r in results]

        if group_by_doc:
            from docpilot.search import group_by_document
            return group_by_document(results, top_chunks=3, score="max")

        return results

    def generate(
        self,
        data_folder: str | Path,
        template: str | Path,
        output: str | Path,
        reindex: bool = False,
        extra_instructions: str | None = None,
        instructions_doc: str | Path | None = None,
        top_k: int = 10,
        collection: str | None = None,
    ) -> GenerateResult:
        """
        Full pipeline: index → search → map → build.

        template:           file path (.hwpx/.docx/.pdf) or built-in template name.
        output:             destination file path — extension determines builder.
        reindex:            re-index data_folder even if already indexed.
        extra_instructions: additional writing guidelines injected into the LLM prompt.
                            Use this to pass document-specific rules such as proposal
                            writing guidelines extracted from an RFP.
        collection:         optional tag applied when indexing data_folder. When given, RAG
                            retrieval is scoped by this tag instead of the data_folder path,
                            so it keeps working even if files are later moved.
        """
        template_path, _db_sections_meta = self._resolve_template(template)
        output_path = Path(output)

        if template_path.suffix.lower() == ".docx" and output_path.suffix.lower() == ".hwpx":
            from docpilot.builder.hwp_convert import convert_to_hwpx
            _tmp = tempfile.NamedTemporaryFile(suffix=".hwpx", delete=False)
            _tmp.close()
            _tmp_path = Path(_tmp.name)
            atexit.register(lambda p=_tmp_path: p.unlink(missing_ok=True))
            template_path = convert_to_hwpx(template_path, _tmp_path)

        from docpilot.mapping.sidecar import load_sidecar
        _sidecar = load_sidecar(_sidecar_source(template))
        extra_instructions = _resolve_instructions(
            extra_instructions,
            _sidecar.instructions if _sidecar is not None else "",
            instructions_doc,
        )

        from docpilot.db import indexer
        doc_ids = indexer.index_folder(
            data_folder, embed_fn=self._embed_fn, force=reindex, collection=collection
        )
        if not doc_ids:
            raise DocPilotError(
                "데이터 폴더에서 인덱싱된 문서가 없습니다.",
                detail=(
                    f"{data_folder} 에서 지원하는 파일을 찾지 못했거나 "
                    "모든 파일의 수집(ingestion)에 실패했습니다. "
                    "지원 형식: .txt .md .csv .hwpx .hwp .docx .pdf"
                ),
            )

        template_path, sections, _ = _resolve_sections(
            template, template_path, _db_sections_meta, mapper=self._mapper,
        )

        from docpilot.search.models import SearchFilter
        if collection is not None:
            filters = SearchFilter(collection=collection)
        else:
            filters = SearchFilter(source_pattern=f"{Path(data_folder).resolve()}{os.sep}*")
        mapping_result = self._rag_mapper.map(sections, instructions=extra_instructions, top_k=top_k, filters=filters)

        builder = self._build_builder(output_path)
        out_path = builder.build(template_path, mapping_result.sections, output_path)

        if out_path.suffix.lower() == ".hwpx":
            _validate_hwpx(out_path)

        return GenerateResult(
            path=out_path,
            model=mapping_result.model,
            input_tokens=mapping_result.input_tokens,
            output_tokens=mapping_result.output_tokens,
            elapsed_seconds=mapping_result.elapsed_seconds,
        )

    def generate_from_content(
        self,
        content: str | list[str | Path] | list[IngestedDocument],
        template: str | Path,
        output: str | Path,
        extra_instructions: str | None = None,
        instructions_doc: str | Path | None = None,
        max_input_tokens: int | None = None,
    ) -> GenerateResult:
        """
        Fill a template from already-prepared content — no RAG retrieval, no data folder.

        content:            a finished string, a list of IngestedDocuments, or a list of file
                             paths (ingested directly, no chunking/embedding/DB storage).
        template:            {{placeholder}} template, or a placeholder-less reference document —
                             the latter costs one extra LLM call to infer section structure
                             (Reference Mode, same as generate()).
        max_input_tokens:    if set, raises MappingError when the estimated input token count
                             exceeds it. If unset, only warns — RAG's top_k has no equivalent
                             here, so there's no automatic context-size limit.
        """
        template_path, db_sections_meta = self._resolve_template(template)
        output_path = Path(output)

        if template_path.suffix.lower() == ".docx" and output_path.suffix.lower() == ".hwpx":
            from docpilot.builder.hwp_convert import convert_to_hwpx
            _tmp = tempfile.NamedTemporaryFile(suffix=".hwpx", delete=False)
            _tmp.close()
            _tmp_path = Path(_tmp.name)
            atexit.register(lambda p=_tmp_path: p.unlink(missing_ok=True))
            template_path = convert_to_hwpx(template_path, _tmp_path)

        template_path, sections, sidecar_instructions = _resolve_sections(
            template, template_path, db_sections_meta, mapper=self._mapper,
        )
        extra_instructions = _resolve_instructions(extra_instructions, sidecar_instructions, instructions_doc)

        content_str = _resolve_content(content)
        _check_content_size(content_str, max_input_tokens)

        mapping_result = self._mapper.map(content_str, sections, instructions=extra_instructions)

        builder = self._build_builder(output_path)
        out_path = builder.build(template_path, mapping_result.sections, output_path)

        if out_path.suffix.lower() == ".hwpx":
            _validate_hwpx(out_path)

        return GenerateResult(
            path=out_path,
            model=mapping_result.model,
            input_tokens=mapping_result.input_tokens,
            output_tokens=mapping_result.output_tokens,
            elapsed_seconds=mapping_result.elapsed_seconds,
        )

    def generate_template(
        self,
        samples: list[str | Path],
        output: str | Path,
        use_llm: bool | None = None,
    ) -> Path:
        """Generate an HWPX template from sample documents."""
        from docpilot.template_generator import generate
        return generate(
            samples=samples,
            output=output,
            use_llm=use_llm,
            llm_mapper=self._mapper if use_llm else None,
        )

    def save_template(
        self,
        name: str,
        path: str | Path,
        description: str = "",
        tags: list[str] | None = None,
        sections_meta: dict | None = None,
        auto_sections_meta: bool = True,
    ) -> int:
        """
        Save an HWPX template to the DB so it can be found by name in generate().

        Extracts section0.xml and header.xml from the .hwpx ZIP into
        ~/.docpilot/templates/<name>/ for persistent access across sessions.

        auto_sections_meta: if True (default) and sections_meta is None, ask the LLM to
            infer per-section description/rule for each placeholder — this makes a
            billed API call every time save_template() is called without explicit
            sections_meta. Pass auto_sections_meta=False or sections_meta={} to skip it
            (a UserWarning is also raised when the automatic call is about to run).

        Returns the saved template record ID.
        """
        import zipfile
        from docpilot.db import template_store

        path = Path(path)
        if not path.exists():
            raise DocPilotError("Template file not found", detail=str(path))
        if path.suffix.lower() != ".hwpx":
            raise DocPilotError(
                "save_template() only supports .hwpx files",
                detail=f"Got '{path.suffix}'. Pass .docx/.pdf paths directly to generate().",
            )

        store_dir = Path.home() / ".docpilot" / "templates" / name
        store_dir.mkdir(parents=True, exist_ok=True)
        section_xml_path = store_dir / "section0.xml"
        header_xml_path = store_dir / "header.xml"

        with zipfile.ZipFile(path, "r") as zf:
            names = zf.namelist()
            section_candidates = [n for n in names if n.endswith("section0.xml")]
            if not section_candidates:
                raise DocPilotError("No section0.xml in HWPX", detail=str(path))
            section_xml_path.write_bytes(zf.read(section_candidates[0]))
            if "Contents/header.xml" in names:
                header_xml_path.write_bytes(zf.read("Contents/header.xml"))
            else:
                header_xml_path = None

        return template_store.save(
            name=name,
            path=str(section_xml_path),
            description=description or name,
            header_xml=str(header_xml_path) if header_xml_path else None,
            tags=tags,
            sections_meta=sections_meta,
            auto_sections_meta=auto_sections_meta,
            # 매퍼는 LLM 자동 추론을 실제로 할 때만 넘긴다 — 아니면 API 키 없이도 저장되어야 함
            mapper=self._mapper if (sections_meta is None and auto_sections_meta) else None,
            embed_fn=self._embed_fn,
        )

    def estimate_cost(
        self,
        data_folder: str | Path,
        template: str | Path,
        quick: bool = False,
        collection: str | None = None,
    ) -> str:
        """
        Estimate API token cost before generating.

        quick=True (default in MCP): file-size based estimate, no indexing or API call.
        quick=False: full indexing + RAG retrieval + token-counting API for accuracy.
        """
        template_path, db_sections_meta = self._resolve_template(template)
        template_path, sections, _ = _resolve_sections(
            template, template_path, db_sections_meta, mapper=self._mapper,
        )

        model: str = getattr(self._mapper, "_model", "claude-sonnet-4-6")
        in_price, out_price = _MODEL_PRICING.get(model, (3.00, 15.00))
        est_output = len(sections) * _EST_OUTPUT_TOKENS_PER_SECTION

        if quick:
            input_tokens = _estimate_tokens_from_folder(Path(data_folder), len(sections))
            input_cost = input_tokens / 1_000_000 * in_price
            output_cost = est_output / 1_000_000 * out_price
            lines = [
                "=== docpilot 비용 추정 (빠른 추정) ===",
                f"모델:             {model}",
                f"섹션 수:          {len(sections)}개",
                f"입력 토큰 (추정): {input_tokens:,}  (파일 크기 기반, ±30% 오차)",
                f"출력 토큰 (추정): {est_output:,}  (섹션당 {_EST_OUTPUT_TOKENS_PER_SECTION} 추정)",
                f"예상 비용:        ${input_cost + output_cost:.4f}",
                f"  입력 ${in_price:.2f}/1M  →  ${input_cost:.4f}",
                f"  출력 ${out_price:.2f}/1M  →  ${output_cost:.4f}",
                "",
                "정확한 추정: estimate_cost(quick=False) — 인덱싱 + 토큰 카운팅 API 사용",
            ]
            return "\n".join(lines)

        from docpilot.db import indexer
        indexer.index_folder(data_folder, embed_fn=self._embed_fn, collection=collection)
        content = self._rag_mapper.retrieve_content(sections)

        if not hasattr(self._mapper, "count_tokens"):
            n = len(sections)
            return (
                f"섹션 수: {n}개\n"
                f"토큰 카운팅은 Claude 매퍼에서만 지원됩니다.\n"
                f"섹션당 ~3,000 입력 + ~{_EST_OUTPUT_TOKENS_PER_SECTION} 출력 토큰 기준\n"
                f"대략 {n * 3000:,} 입력 / {n * _EST_OUTPUT_TOKENS_PER_SECTION:,} 출력 예상"
            )

        input_tokens = self._mapper.count_tokens(content, sections)
        input_cost = input_tokens / 1_000_000 * in_price
        output_cost = est_output / 1_000_000 * out_price

        lines = [
            "=== docpilot 비용 추정 ===",
            f"모델:             {model}",
            f"섹션 수:          {len(sections)}개",
            f"입력 토큰:        {input_tokens:,}",
            f"출력 토큰 (추정): {est_output:,}  (섹션당 {_EST_OUTPUT_TOKENS_PER_SECTION} 추정)",
            f"예상 비용:        ${input_cost + output_cost:.4f}",
            f"  입력 ${in_price:.2f}/1M  →  ${input_cost:.4f}",
            f"  출력 ${out_price:.2f}/1M  →  ${output_cost:.4f}",
        ]
        return "\n".join(lines)

    def estimate_cost_from_content(
        self,
        content: str | list[str | Path] | list[IngestedDocument],
        template: str | Path,
        quick: bool = False,
    ) -> str:
        """
        Estimate API token cost for generate_from_content() — no indexing, no RAG retrieval.

        quick=True: byte-based heuristic, no API call.
        quick=False (default): real token-counting API call against the actual content.
        """
        template_path, db_sections_meta = self._resolve_template(template)
        template_path, sections, _ = _resolve_sections(
            template, template_path, db_sections_meta, mapper=self._mapper,
        )
        content_str = _resolve_content(content)

        model: str = getattr(self._mapper, "_model", "claude-sonnet-4-6")
        in_price, out_price = _MODEL_PRICING.get(model, (3.00, 15.00))
        est_output = len(sections) * _EST_OUTPUT_TOKENS_PER_SECTION

        if quick:
            from docpilot.tokens import estimate_tokens_raw
            input_tokens = estimate_tokens_raw(content_str)
            input_cost = input_tokens / 1_000_000 * in_price
            output_cost = est_output / 1_000_000 * out_price
            lines = [
                "=== docpilot 비용 추정 (빠른 추정, RAG 없음) ===",
                f"모델:             {model}",
                f"섹션 수:          {len(sections)}개",
                f"입력 토큰 (추정): {input_tokens:,}  (바이트 기반, ±30% 오차)",
                f"출력 토큰 (추정): {est_output:,}  (섹션당 {_EST_OUTPUT_TOKENS_PER_SECTION} 추정)",
                f"예상 비용:        ${input_cost + output_cost:.4f}",
                f"  입력 ${in_price:.2f}/1M  →  ${input_cost:.4f}",
                f"  출력 ${out_price:.2f}/1M  →  ${output_cost:.4f}",
                "",
                "정확한 추정: estimate_cost_from_content(quick=False) — 토큰 카운팅 API 사용",
            ]
            return "\n".join(lines)

        if not hasattr(self._mapper, "count_tokens"):
            n = len(sections)
            return (
                f"섹션 수: {n}개\n"
                f"토큰 카운팅은 Claude 매퍼에서만 지원됩니다.\n"
                f"섹션당 ~3,000 입력 + ~{_EST_OUTPUT_TOKENS_PER_SECTION} 출력 토큰 기준\n"
                f"대략 {n * 3000:,} 입력 / {n * _EST_OUTPUT_TOKENS_PER_SECTION:,} 출력 예상"
            )

        input_tokens = self._mapper.count_tokens(content_str, sections)
        input_cost = input_tokens / 1_000_000 * in_price
        output_cost = est_output / 1_000_000 * out_price

        lines = [
            "=== docpilot 비용 추정 (RAG 없음) ===",
            f"모델:             {model}",
            f"섹션 수:          {len(sections)}개",
            f"입력 토큰:        {input_tokens:,}",
            f"출력 토큰 (추정): {est_output:,}  (섹션당 {_EST_OUTPUT_TOKENS_PER_SECTION} 추정)",
            f"예상 비용:        ${input_cost + output_cost:.4f}",
            f"  입력 ${in_price:.2f}/1M  →  ${input_cost:.4f}",
            f"  출력 ${out_price:.2f}/1M  →  ${output_cost:.4f}",
        ]
        return "\n".join(lines)

    def benchmark(
        self,
        data_folder: str | Path,
        template: str | Path,
        output: str | Path,
        mappers: dict | None = None,
        collection: str | None = None,
    ) -> str:
        """Run mapping benchmark across multiple LLM mappers and return report."""
        from docpilot.mapping import benchmark, ClaudeMapper, OpenAIMapper

        template_path, db_sections_meta = self._resolve_template(template)
        self.index(data_folder, collection=collection)

        template_path, template_sections, _ = _resolve_sections(
            template, template_path, db_sections_meta, mapper=self._mapper,
        )
        content = self._rag_mapper.retrieve_content(template_sections)

        if mappers is None:
            mappers = {"claude": ClaudeMapper(api_key=self._api_key)}
            oai_key = os.environ.get("OPENAI_API_KEY")
            if oai_key:
                mappers["openai"] = OpenAIMapper(api_key=oai_key)

        results = benchmark.run(content, template_sections, mappers)
        return benchmark.report(results)

    def benchmark_from_content(
        self,
        content: str | list[str | Path] | list[IngestedDocument],
        template: str | Path,
        output: str | Path,
        mappers: dict | None = None,
        max_input_tokens: int | None = None,
    ) -> str:
        """Run mapping benchmark across multiple LLM mappers — no indexing, no RAG retrieval."""
        from docpilot.mapping import benchmark, ClaudeMapper, OpenAIMapper

        template_path, db_sections_meta = self._resolve_template(template)
        template_path, template_sections, _ = _resolve_sections(
            template, template_path, db_sections_meta, mapper=self._mapper,
        )
        content_str = _resolve_content(content)
        _check_content_size(content_str, max_input_tokens)

        if mappers is None:
            mappers = {"claude": ClaudeMapper(api_key=self._api_key)}
            oai_key = os.environ.get("OPENAI_API_KEY")
            if oai_key:
                mappers["openai"] = OpenAIMapper(api_key=oai_key)

        results = benchmark.run(content_str, template_sections, mappers)
        return benchmark.report(results)

    def _resolve_template(self, template: str | Path) -> tuple[Path, dict]:
        """Return (template_path, sections_meta). sections_meta is non-empty only for DB templates."""
        return _resolve_template_path(template, self._embed_fn)

    @staticmethod
    def list_templates() -> dict[str, str]:
        """Return available template names and their descriptions (built-in + DB-saved)."""
        result = _get_builtin_metadata()
        try:
            from docpilot.db import template_store
            for record in template_store.list_all():
                if record.name not in result:
                    result[record.name] = record.description
        except Exception:
            pass
        return result

    @staticmethod
    def delete_template(template_id: int) -> bool:
        """Delete a saved template by ID. Returns True if found and deleted."""
        from docpilot.db import template_store
        return template_store.delete(template_id)

    @staticmethod
    def delete_template_by_path(path: str | Path) -> bool:
        """Delete a saved template by its section0.xml path. Returns True if found and deleted."""
        from docpilot.db import template_store
        return template_store.delete_by_path(path)

    @staticmethod
    def convert_to_list_placeholder(
        path: str | Path,
        keys: list[str] | str,
        output: str | Path | None = None,
    ) -> Path:
        """
        Convert {{key}} placeholders to {{?key?}} (dynamic list) in a template file.

        keys:   placeholder name(s) to convert
        output: destination path; if None, overwrites source in-place
        """
        return convert_to_list_placeholder(path, keys, output)

    @staticmethod
    def suggest_extras(folder: str | Path) -> dict:
        """Scan a data folder and suggest which docpilot extras to install."""
        return suggest_extras(folder)

    @staticmethod
    def _build_mapper(
        llm: str,
        api_key: str | None,
        model: str | None,
        base_url: str | None,
        num_ctx: int | None = None,
        temperature: float | None = None,
    ):
        from docpilot.mapping import ClaudeMapper, OpenAIMapper, GeminiMapper
        from docpilot.mapping.openai_compat import GrokMapper, OllamaMapper

        match llm.lower():
            case "claude":
                return ClaudeMapper(api_key=api_key, **(_m(model)), **(_t(temperature)))
            case "openai":
                return OpenAIMapper(api_key=api_key, **(_m(model)), **(_t(temperature)))
            case "gemini":
                return GeminiMapper(api_key=api_key, **(_m(model)), **(_t(temperature)))
            case "grok":
                return GrokMapper(api_key=api_key, **(_m(model)), **(_t(temperature)))
            case "ollama":
                return OllamaMapper(
                    **(_m(model)), **(_b(base_url)), **(_n(num_ctx)), **(_t(temperature)),
                )
            case _:
                raise MappingError(
                    f"Unknown LLM '{llm}'. "
                    "Supported: claude, openai, gemini, grok, ollama"
                )

    @staticmethod
    def _build_builder(output: Path):
        return _resolve_builder(output)
