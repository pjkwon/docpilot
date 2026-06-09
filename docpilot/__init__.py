from __future__ import annotations

import atexit
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from docpilot.exceptions import BuilderError, DocPilotError, MappingError

load_dotenv()

_PLACEHOLDER_RE = re.compile(r"\{\{(.+?)\}\}")

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

# Maps file extension → required extra (None = included in base install)
_EXT_EXTRAS: dict[str, str | None] = {
    ".txt":  None,
    ".md":   None,
    ".rst":  None,
    ".csv":  None,
    ".hwpx": None,
    ".pdf":  "pdf",
    ".pptx": "pptx",
    ".docx": "docx",
    ".jpg":  "image",
    ".jpeg": "image",
    ".png":  "image",
    ".tiff": "image",
    ".tif":  "image",
    ".bmp":  "image",
    ".webp": "image",
}


def suggest_extras(folder: str | Path) -> dict:
    """
    Scan a data folder and suggest which docpilot extras to install.

    Returns a dict with:
      found          — {extension: file_count} for all files found
      unsupported    — {extension: file_count} for files docpilot cannot process
      required_extras — list of extras needed (e.g. ["pdf", "pptx"])
      install_command — ready-to-run pip command, or None if nothing extra needed
    """
    folder = Path(folder)
    if not folder.is_dir():
        raise DocPilotError("Not a directory", detail=str(folder))

    found: dict[str, int] = {}
    for file in folder.rglob("*"):
        if not file.is_file():
            continue
        ext = file.suffix.lower()
        found[ext] = found.get(ext, 0) + 1

    unsupported: dict[str, int] = {
        ext: count for ext, count in found.items() if ext not in _EXT_EXTRAS
    }

    required: list[str] = sorted({
        extra
        for ext in found
        if ext in _EXT_EXTRAS and (extra := _EXT_EXTRAS[ext]) is not None
    })

    install_command = (
        f'pip install "docpilot[{",".join(required)}]"' if required else None
    )

    return {
        "found": found,
        "unsupported": unsupported,
        "required_extras": required,
        "install_command": install_command,
    }
_BUILTIN_TEMPLATES = Path(__file__).parent / "templates"

_BUILTIN_METADATA: dict[str, str] = {
    "report":   "일반 보고서 — 보고서 제목, 섹션 본문, 결론",
    "gonmun":   "공문 — 수신자, 제목, 본문, 기관 정보",
    "minutes":  "회의록 — 제목, 일시, 참석자, 안건, 논의, 결정 사항",
    "proposal": "제안서 — 사업 개요, 추진 배경, 추진 근거",
}

_ASSEMBLED_CACHE: dict[str, Path] = {}


def _assemble_builtin_hwpx(name: str) -> Path:
    """Assemble a built-in HWPX template from base + per-template XML sources."""
    if name in _ASSEMBLED_CACHE:
        return _ASSEMBLED_CACHE[name]

    base_dir = _BUILTIN_TEMPLATES / "base"
    overlay_dir = _BUILTIN_TEMPLATES / name

    if not base_dir.exists() or not overlay_dir.exists():
        raise DocPilotError(
            f"Built-in template '{name}' not found",
            detail=f"Expected source at {overlay_dir}",
        )

    tmp = tempfile.NamedTemporaryFile(suffix=f"_{name}.hwpx", delete=False)
    tmp.close()
    tmp_path = Path(tmp.name)

    with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
        mimetype = base_dir / "mimetype"
        if mimetype.exists():
            zf.write(mimetype, "mimetype", compress_type=zipfile.ZIP_STORED)

        for file in sorted(base_dir.rglob("*")):
            if not file.is_file() or file.name == "mimetype":
                continue
            arcname = file.relative_to(base_dir)
            # overlay_dir files are named header.xml / section0.xml — placed in Contents/
            override = overlay_dir / file.name
            source = override if override.exists() else file
            zf.write(source, arcname.as_posix())

    _ASSEMBLED_CACHE[name] = tmp_path
    atexit.register(lambda p=tmp_path: p.unlink(missing_ok=True))
    return tmp_path


def _m(model: str | None) -> dict:
    return {"model": model} if model else {}


def _b(base_url: str | None) -> dict:
    return {"base_url": base_url} if base_url else {}


def _ingest_instructions_doc(path: Path) -> str:
    """지침 문서를 읽어 텍스트로 반환한다. 지원하지 않는 형식이면 빈 문자열 반환."""
    from docpilot.ingestion import text as text_ing
    from docpilot.ingestion import hwpx as hwpx_ing

    ext = path.suffix.lower()

    try:
        if ext == ".hwpx":
            return hwpx_ing.ingest(path).content
        if ext in text_ing.SUPPORTED_EXTENSIONS:
            return text_ing.ingest(path).content
        if ext == ".pdf":
            from docpilot.ingestion import pdf as pdf_ing
            return pdf_ing.ingest(path).content
        if ext == ".docx":
            from docpilot.ingestion import docx as docx_ing
            return docx_ing.ingest(path).content
        if ext == ".pptx":
            from docpilot.ingestion import pptx as pptx_ing
            return pptx_ing.ingest(path).content
    except Exception:
        pass
    return ""


def _validate_hwpx(path: Path) -> None:
    """생성된 HWPX 파일의 구조 무결성을 비차단 방식으로 검사한다."""
    import logging
    import warnings

    _REQUIRED = [
        "mimetype",
        "Contents/content.hpf",
        "Contents/header.xml",
    ]

    try:
        with zipfile.ZipFile(path, "r") as zf:
            names = zf.namelist()
            missing = [f for f in _REQUIRED if f not in names]
            if missing:
                warnings.warn(
                    f"HWPX 검증 경고 — 필수 파일 누락: {', '.join(missing)}",
                    stacklevel=4,
                )

            try:
                from lxml import etree
                for name in names:
                    if name.endswith(".xml") or name.endswith(".hpf"):
                        try:
                            etree.fromstring(zf.read(name))
                        except Exception as xml_err:
                            warnings.warn(
                                f"HWPX 검증 경고 — XML 오류 in {name}: {xml_err}",
                                stacklevel=4,
                            )
            except ImportError:
                pass
    except Exception as exc:
        logging.getLogger(__name__).debug("HWPX 검증 실패 (무시됨): %s", exc)


def _extract_placeholders(template_path: Path) -> list[str]:
    """Extract {{section}} placeholder names from a template file."""
    suffix = template_path.suffix.lower()

    if suffix == ".hwpx":
        with zipfile.ZipFile(template_path, "r") as zf:
            names = zf.namelist()
            candidates = [n for n in names if n.endswith("content.hml")]
            if not candidates:
                candidates = [n for n in names if n.endswith("section0.xml")]
            if not candidates:
                return []
            text = "".join(
                zf.read(c).decode("utf-8", errors="ignore") for c in candidates
            )
    elif suffix == ".docx":
        with zipfile.ZipFile(template_path, "r") as zf:
            text = zf.read("word/document.xml").decode("utf-8", errors="ignore")
    elif suffix == ".pdf":
        try:
            import pdfplumber
            with pdfplumber.open(template_path) as pdf:
                text = "\n".join(p.extract_text() or "" for p in pdf.pages)
        except Exception:
            return []
    else:
        return []

    seen: dict[str, None] = {}
    for match in _PLACEHOLDER_RE.finditer(text):
        seen[match.group(1)] = None
    return list(seen)


class DocPilot:
    """
    Main entry point for docpilot.

    pilot = DocPilot(llm="claude")
    pilot.index(data_folder="./data")
    pilot.generate(data_folder="./data", template="research_report", output="./out.hwpx")
    """

    def __init__(
        self,
        llm: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        database_url: str | None = None,
        embed_fn=None,
        use_reranker: bool = False,
    ) -> None:
        self._llm = llm or os.environ.get("DOCPILOT_LLM", "claude")
        self._api_key = api_key
        self._embed_fn = embed_fn
        base_mapper = self._build_mapper(self._llm, api_key, model, base_url)

        from docpilot.mapping.rag import RagMapper
        self._mapper = base_mapper
        self._rag_mapper = RagMapper(base_mapper, embed_fn=embed_fn, use_reranker=use_reranker)

        from docpilot.db import client as db_client
        db_client.init(database_url)
        db_client.create_tables()

    def index(self, data_folder: str | Path) -> list[int]:
        """Ingest and index all supported files in a folder."""
        from docpilot.db import indexer
        return indexer.index_folder(data_folder, embed_fn=self._embed_fn)

    def generate(
        self,
        data_folder: str | Path,
        template: str | Path,
        output: str | Path,
        reindex: bool = False,
        extra_instructions: str | None = None,
        instructions_doc: str | Path | None = None,
    ) -> GenerateResult:
        """
        Full pipeline: index → search → map → build.

        template:           file path (.hwpx/.docx/.pdf) or built-in template name.
        output:             destination file path — extension determines builder.
        reindex:            re-index data_folder even if already indexed.
        extra_instructions: additional writing guidelines injected into the LLM prompt.
                            Use this to pass document-specific rules such as proposal
                            writing guidelines extracted from an RFP.
        """
        template_path = self._resolve_template(template)
        output_path = Path(output)

        if instructions_doc is not None:
            doc_text = _ingest_instructions_doc(Path(instructions_doc))
            if doc_text:
                header = f"[지침 문서: {Path(instructions_doc).name}]\n{doc_text}"
                extra_instructions = (
                    f"{header}\n\n{extra_instructions}" if extra_instructions
                    else header
                )

        from docpilot.db import indexer
        indexer.index_folder(data_folder, embed_fn=self._embed_fn, force=reindex)

        from docpilot.mapping.base import TemplateSection
        placeholder_names = _extract_placeholders(template_path)
        if not placeholder_names:
            raise DocPilotError(
                "No {{placeholders}} found in template",
                detail=str(template_path),
            )

        style_hints: dict[str, str] = {}
        _tpl_ext = template_path.suffix.lower()
        if _tpl_ext == ".hwpx":
            from docpilot.builder.hwpx_analyzer import extract_style_hints
            style_hints = extract_style_hints(template_path)
        elif _tpl_ext == ".docx":
            from docpilot.builder.docx_analyzer import extract_style_hints
            style_hints = extract_style_hints(template_path)

        sections = [
            TemplateSection(name=s, style_hint=style_hints.get(s, ""))
            for s in placeholder_names
        ]

        mapping_result = self._rag_mapper.map(sections, instructions=extra_instructions)

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

    def estimate_cost(
        self,
        data_folder: str | Path,
        template: str | Path,
    ) -> str:
        """
        Estimate API token cost before generating. No LLM call is made.

        Indexes the data folder, runs RAG retrieval, and calls the token-counting
        API to get an accurate input token count. Output tokens are estimated at
        500 per section. Returns a formatted cost report string.
        """
        template_path = self._resolve_template(template)

        from docpilot.db import indexer
        indexer.index_folder(data_folder, embed_fn=self._embed_fn)

        from docpilot.mapping.base import TemplateSection
        sections = [TemplateSection(name=s) for s in _extract_placeholders(template_path)]
        if not sections:
            raise DocPilotError(
                "No {{placeholders}} found in template",
                detail=str(template_path),
            )

        content = self._rag_mapper.retrieve_content(sections)

        if not hasattr(self._mapper, "count_tokens"):
            n = len(sections)
            return (
                f"섹션 수: {n}개\n"
                f"토큰 카운팅은 Claude 매퍼에서만 지원됩니다.\n"
                f"섹션당 ~3,000 입력 + ~{_EST_OUTPUT_TOKENS_PER_SECTION} 출력 토큰 기준\n"
                f"대략 {n * 3000:,} 입력 / {n * _EST_OUTPUT_TOKENS_PER_SECTION:,} 출력 예상"
            )

        input_tokens: int = self._mapper.count_tokens(content, sections)
        est_output = len(sections) * _EST_OUTPUT_TOKENS_PER_SECTION

        model: str = getattr(self._mapper, "_model", "claude-sonnet-4-6")
        in_price, out_price = _MODEL_PRICING.get(model, (3.00, 15.00))
        input_cost = input_tokens / 1_000_000 * in_price
        output_cost = est_output / 1_000_000 * out_price
        total_cost = input_cost + output_cost

        lines = [
            "=== docpilot 비용 추정 ===",
            f"모델:             {model}",
            f"섹션 수:          {len(sections)}개",
            f"입력 토큰:        {input_tokens:,}",
            f"출력 토큰 (추정): {est_output:,}  (섹션당 {_EST_OUTPUT_TOKENS_PER_SECTION} 추정)",
            f"예상 비용:        ${total_cost:.4f}",
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
    ) -> str:
        """Run mapping benchmark across multiple LLM mappers and return report."""
        from docpilot.mapping import benchmark, ClaudeMapper, OpenAIMapper
        from docpilot.mapping.base import TemplateSection

        template_path = self._resolve_template(template)
        self.index(data_folder)

        template_sections = [TemplateSection(name=s) for s in _extract_placeholders(template_path)]
        content = self._rag_mapper.retrieve_content(template_sections)

        if mappers is None:
            mappers = {"claude": ClaudeMapper(api_key=self._api_key)}
            oai_key = os.environ.get("OPENAI_API_KEY")
            if oai_key:
                mappers["openai"] = OpenAIMapper(api_key=oai_key)

        results = benchmark.run(content, template_sections, mappers)
        return benchmark.report(results)

    def _resolve_template(self, template: str | Path) -> Path:
        path = Path(template)
        if path.exists():
            return path

        name = str(template)
        if name in _BUILTIN_METADATA:
            return _assemble_builtin_hwpx(name)

        for ext in (".hwpx", ".docx", ".pdf"):
            # 1) package built-ins
            candidate = _BUILTIN_TEMPLATES / f"{template}{ext}"
            if candidate.exists():
                return candidate
            # 2) project-local ./templates/ directory
            local = Path("templates") / f"{template}{ext}"
            if local.exists():
                return local

        raise DocPilotError("Template not found", detail=str(template))

    @staticmethod
    def list_templates() -> dict[str, str]:
        """Return built-in template names and their descriptions."""
        return dict(_BUILTIN_METADATA)

    @staticmethod
    def suggest_extras(folder: str | Path) -> dict:
        """Scan a data folder and suggest which docpilot extras to install."""
        return suggest_extras(folder)

    @staticmethod
    def _build_mapper(llm: str, api_key: str | None, model: str | None, base_url: str | None):
        from docpilot.mapping import ClaudeMapper, OpenAIMapper, GeminiMapper
        from docpilot.mapping.openai_compat import GrokMapper, OllamaMapper

        match llm.lower():
            case "claude":
                return ClaudeMapper(api_key=api_key, **(_m(model)))
            case "openai":
                return OpenAIMapper(api_key=api_key, **(_m(model)))
            case "gemini":
                return GeminiMapper(api_key=api_key, **(_m(model)))
            case "grok":
                return GrokMapper(api_key=api_key, **(_m(model)))
            case "ollama":
                return OllamaMapper(**(_m(model)), **(_b(base_url)))
            case _:
                raise MappingError(
                    f"Unknown LLM '{llm}'. "
                    "Supported: claude, openai, gemini, grok, ollama"
                )

    @staticmethod
    def _build_builder(output: Path):
        from docpilot.builder import HwpxBuilder, PdfBuilder, DocxBuilder

        match output.suffix.lower():
            case ".hwpx":
                return HwpxBuilder()
            case ".pdf":
                return PdfBuilder()
            case ".docx":
                return DocxBuilder()
            case _:
                raise BuilderError(
                    f"Unsupported output format '{output.suffix}'",
                    detail="Supported: .hwpx, .pdf, .docx",
                )
