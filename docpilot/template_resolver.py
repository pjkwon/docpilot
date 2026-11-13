"""템플릿 이름·경로 해석, 섹션 메타데이터(sidecar/DB/스타일 힌트) 병합, Reference Mode."""
from __future__ import annotations

import atexit
import tempfile
import zipfile
from pathlib import Path

from docpilot.exceptions import DocPilotError
from docpilot.placeholders import _extract_placeholder_sections


_BUILTIN_TEMPLATES = Path(__file__).parent / "templates"


def _get_builtin_metadata() -> dict[str, str]:
    from docpilot.mapping.sidecar import load_sidecar
    result = {}
    for d in sorted(_BUILTIN_TEMPLATES.iterdir()):
        if not d.is_dir() or d.name == "base":
            continue
        sidecar = load_sidecar(d)
        if sidecar and sidecar.description:
            result[d.name] = sidecar.description
        else:
            result[d.name] = d.name
    return result


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
    except Exception:
        pass
    return ""


def _resolve_instructions(
    extra_instructions: str | None,
    sidecar_instructions: str,
    instructions_doc: str | Path | None,
) -> str | None:
    """Merge sidecar instructions + instructions_doc content into extra_instructions.

    Priority: instructions_doc is prepended last (highest priority — read in full,
    unlike sidecar/extra which are just strings), sidecar next, caller's extra_instructions last.
    """
    if sidecar_instructions:
        extra_instructions = (
            f"{sidecar_instructions}\n\n{extra_instructions}"
            if extra_instructions
            else sidecar_instructions
        )

    if instructions_doc is not None:
        doc_text = _ingest_instructions_doc(Path(instructions_doc))
        if doc_text:
            header = f"[지침 문서: {Path(instructions_doc).name}]\n{doc_text}"
            extra_instructions = (
                f"{header}\n\n{extra_instructions}" if extra_instructions
                else header
            )

    return extra_instructions


def _infer_sections_from_content(content: str, mapper) -> list[str]:
    """Use LLM to infer fillable section names from a document's text content."""
    import json
    from docpilot.mapping.base import TemplateSection

    mapping = mapper.map(
        content=content[:4000],
        sections=[
            TemplateSection(
                name="sections",
                description=(
                    "위 문서 구조를 분석해 채워야 할 섹션 이름 목록을 추출하세요. "
                    "헤딩·제목·표 컬럼·항목명 등 구조적 요소를 기반으로 하되 "
                    "내용이 들어가야 할 곳의 레이블을 우선하세요. "
                    "결과는 JSON 배열 문자열로만 반환하세요: [\"섹션1\", \"섹션2\", ...]"
                ),
            )
        ],
    )
    raw = mapping.sections.get("sections", "[]")
    if isinstance(raw, list):
        return [str(s) for s in raw if s]
    if isinstance(raw, str):
        raw_clean = raw.strip()
        if raw_clean.startswith("[") and raw_clean.endswith("]"):
            import ast
            try:
                parsed = ast.literal_eval(raw_clean)
                if isinstance(parsed, list):
                    return [str(s) for s in parsed if s]
            except Exception:
                pass
    try:
        sections = json.loads(raw)
        if isinstance(sections, list):
            return [str(s) for s in sections if s]
    except (json.JSONDecodeError, ValueError):
        pass
    return []


def _apply_reference_mode(template_path: Path, mapper) -> tuple[Path, list]:
    """
    Infer section structure via LLM from a placeholder-less reference document, then
    inject {{placeholder}}s into a temp copy of it. Costs one extra LLM call (structure
    inference) beyond the normal content-mapping call.

    Returns (new_template_path, sections). Raises DocPilotError if the content can't be
    read or the LLM fails to infer any section names.
    """
    from docpilot.mapping.base import TemplateSection
    from docpilot.template_generator.generator import _build_template, _build_docx_template

    ref_content = _ingest_instructions_doc(template_path)
    if not ref_content:
        raise DocPilotError(
            "No {{placeholders}} found and could not read template content",
            detail=str(template_path),
        )
    placeholder_names = _infer_sections_from_content(ref_content, mapper)
    if not placeholder_names:
        raise DocPilotError(
            "No {{placeholders}} found and LLM could not infer sections",
            detail=str(template_path),
        )

    ref_ext = template_path.suffix.lower()
    tpl_suffix = ref_ext if ref_ext in (".hwpx", ".docx") else ".hwpx"
    tmp = tempfile.NamedTemporaryFile(suffix=tpl_suffix, delete=False)
    tmp.close()
    tmp_tpl = Path(tmp.name)
    atexit.register(lambda p=tmp_tpl: p.unlink(missing_ok=True))

    if ref_ext == ".docx":
        _build_docx_template(template_path, placeholder_names, tmp_tpl)
    elif ref_ext == ".hwpx":
        _build_template(template_path, placeholder_names, tmp_tpl)
    else:
        # Non-buildable format (PDF, TXT …): use built-in report as base
        _build_template(_assemble_builtin_hwpx("report"), placeholder_names, tmp_tpl)

    return tmp_tpl, [TemplateSection(name=s) for s in placeholder_names]


def _sidecar_source(template: str | Path) -> Path:
    """
    Path to resolve sidecar.json against.

    Built-in templates are resolved to a temp-assembled HWPX copy for actual reading/
    building (see _assemble_builtin_hwpx), but their sidecar.json lives in the original
    templates/<name>/ directory — so sidecar lookup must use *template*, not the resolved
    template_path, or it silently finds nothing.
    """
    path = Path(template)
    if path.exists():
        return path
    if (_BUILTIN_TEMPLATES / str(template)).is_dir():
        return _BUILTIN_TEMPLATES / str(template)
    return path


def _resolve_template_path(template: str | Path, embed_fn=None) -> tuple[Path, dict]:
    """Return (template_path, sections_meta). sections_meta is non-empty only for DB templates."""
    path = Path(template)
    if path.exists():
        return path, {}

    name = str(template)
    if (_BUILTIN_TEMPLATES / name).is_dir():
        return _assemble_builtin_hwpx(name), {}

    for ext in (".hwpx", ".docx", ".pdf"):
        candidate = _BUILTIN_TEMPLATES / f"{template}{ext}"
        if candidate.exists():
            return candidate, {}
        local = Path("templates") / f"{template}{ext}"
        if local.exists():
            return local, {}

    # DB lookup by name
    try:
        from docpilot.db import template_store
        records = template_store.search(name, embed_fn=embed_fn, top_k=1, fallback=False)
        if records:
            record = records[0]
            section_xml_path = Path(record.path)
            if section_xml_path.exists():
                from docpilot.builder.hwpx_dynamic_builder import pack_hwpx
                _base_header = _BUILTIN_TEMPLATES / "base" / "Contents" / "header.xml"
                header = (
                    Path(record.header_xml)
                    if record.header_xml and Path(record.header_xml).exists()
                    else _base_header
                )
                tmp = tempfile.NamedTemporaryFile(suffix=".hwpx", delete=False)
                tmp.close()
                tmp_hwpx = Path(tmp.name)
                atexit.register(lambda p=tmp_hwpx: p.unlink(missing_ok=True))
                pack_hwpx(header, section_xml_path.read_text(encoding="utf-8"), tmp_hwpx)
                sections_meta = (record.metadata_ or {}).get("sections", {})
                return tmp_hwpx, sections_meta
    except Exception:
        pass

    raise DocPilotError("Template not found", detail=str(template))


def _merge_section_meta(sections: list, template_path: Path, sidecar, db_sections_meta: dict) -> list:
    """Apply sidecar.json rules, DB sections_meta, and template style hints onto *sections* in place."""
    if sidecar is not None and sidecar.sections:
        _sc_map = {s.name: s for s in sidecar.sections}
        for _sec in sections:
            _sc = _sc_map.get(_sec.name)
            if _sc is None:
                continue
            if not _sec.description and _sc.description:
                _sec.description = _sc.description
            if not _sec.rule and _sc.rule:
                _sec.rule = _sc.rule
            if not _sec.style_hint and _sc.style_hint:
                _sec.style_hint = _sc.style_hint
            if _sc.is_list:
                _sec.is_list = True
            if _sc.optional:
                _sec.optional = True
            if _sc.group_max > 0 and _sec.group_max == 0:
                _sec.group_max = _sc.group_max

    if db_sections_meta:
        for _sec in sections:
            _dm = db_sections_meta.get(_sec.name, {})
            if not _dm:
                continue
            if not _sec.description and _dm.get("description"):
                _sec.description = _dm["description"]
            if not _sec.rule and _dm.get("rule"):
                _sec.rule = _dm["rule"]
            if not _sec.style_hint and _dm.get("style_hint"):
                _sec.style_hint = _dm["style_hint"]
            if not _sec.is_list and _dm.get("is_list"):
                _sec.is_list = True
            if not _sec.optional and _dm.get("optional"):
                _sec.optional = True
            if _sec.group_max == 0 and _dm.get("group_max", 0) > 0:
                _sec.group_max = _dm["group_max"]

    style_hints: dict[str, str] = {}
    _tpl_ext = template_path.suffix.lower()
    if _tpl_ext == ".hwpx":
        from docpilot.builder.hwpx_analyzer import extract_style_hints
        style_hints = extract_style_hints(template_path)
    elif _tpl_ext == ".docx":
        from docpilot.builder.docx_analyzer import extract_style_hints
        style_hints = extract_style_hints(template_path)

    for s in sections:
        if s.style_hint:
            continue
        if s.is_list:
            for candidate in [f"{s.name}1", s.name]:
                hint = style_hints.get(candidate, "")
                if hint:
                    s.style_hint = hint
                    break
        else:
            s.style_hint = style_hints.get(s.name, "")

    return sections


def _resolve_sections(
    template: str | Path,
    template_path: Path,
    db_sections_meta: dict,
    mapper=None,
) -> tuple[Path, list, str]:
    """
    Extract + merge section metadata for a template.

    template:      the original name/path passed by the caller — used to locate sidecar.json,
                    since built-in templates resolve to a temp-assembled file (see _sidecar_source).
    template_path: the resolved, readable template file (from _resolve_template_path).
    mapper:        if given, a placeholder-less reference document triggers LLM-based section
                    inference (Reference Mode — one extra LLM call) instead of raising. If None
                    (default; used by describe_template()/fill_template(), which stay LLM-free),
                    raises DocPilotError instead.

    Returns (template_path, sections, instructions). template_path is reassigned only when
    Reference Mode ran (it then points at the generated temp template).
    """
    sections = _extract_placeholder_sections(template_path)
    if not sections:
        if mapper is None:
            raise DocPilotError(
                "템플릿에서 {{placeholder}}를 찾을 수 없습니다.",
                detail=(
                    f"{template_path} — 플레이스홀더가 없는 참조 문서는 generate_template()으로 "
                    "먼저 템플릿을 만들거나, LLM 추론을 지원하는 generate()/generate_from_content()를 "
                    "쓰세요."
                ),
            )
        template_path, sections = _apply_reference_mode(template_path, mapper)

    from docpilot.mapping.sidecar import load_sidecar
    sidecar = load_sidecar(_sidecar_source(template))
    sections = _merge_section_meta(sections, template_path, sidecar, db_sections_meta)
    instructions = sidecar.instructions if sidecar is not None else ""
    return template_path, sections, instructions
