"""템플릿 파일의 {{placeholder}} 추출과 변환."""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

from docpilot.exceptions import DocPilotError


_PLACEHOLDER_RE = re.compile(r"\{\{\??(.+?)\??\}\}")      # {{key}}, {{?key}}, {{?key?}}
_OPTIONAL_PLACEHOLDER_RE = re.compile(r"\{\{\?(.+?)\}\}")  # only {{?key}} and {{?key?}}
_DYNAMIC_LIST_RE = re.compile(r"\{\{\?([^}?]+)\?\}\}")      # only {{?key?}}
_NUMBERED_GROUP_RE = re.compile(r"^(.+?)(\d+)(.*)$")        # "단어1_뜻" → ("단어","1","_뜻")


def _read_template_text(template_path: Path) -> str | None:
    """
    Read a template file's raw markup text for placeholder scanning.

    HWPX: prefers content.hml (our own generated templates), else concatenates
    all section<N>.xml parts in order — a real HWPX can span multiple sections.
    DOCX: document.xml plus header*/footer*.xml (placeholders can live in
    headers/footers), excluding unrelated metadata parts like docProps/*.xml.
    Returns None when the format/content can't be read.
    """
    suffix = template_path.suffix.lower()

    if suffix == ".hwpx":
        with zipfile.ZipFile(template_path, "r") as zf:
            names = zf.namelist()
            candidates = [n for n in names if n.endswith("content.hml")]
            if not candidates:
                sections = [n for n in names if re.search(r"section\d+\.xml$", n)]
                candidates = sorted(
                    sections, key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1))
                )
            if not candidates:
                return None
            return "".join(zf.read(c).decode("utf-8", errors="ignore") for c in candidates)
    elif suffix == ".docx":
        with zipfile.ZipFile(template_path, "r") as zf:
            names = zf.namelist()
            candidates = [n for n in ("word/document.xml",) if n in names]
            candidates += sorted(n for n in names if re.match(r"word/(header|footer)\d*\.xml$", n))
            if not candidates:
                return None
            return "".join(zf.read(c).decode("utf-8", errors="ignore") for c in candidates)
    elif suffix == ".pdf":
        try:
            import pdfplumber
            with pdfplumber.open(template_path) as pdf:
                return "\n".join(p.extract_text() or "" for p in pdf.pages)
        except Exception:
            return None
    return None


def _extract_placeholders(template_path: Path) -> list[str]:
    """Extract {{section}} placeholder names from a template file."""
    text = _read_template_text(template_path)
    if text is None:
        return []

    clean_text = re.sub(r'<[^>]+>', '', text)
    seen: dict[str, None] = {}
    for match in _PLACEHOLDER_RE.finditer(clean_text):
        seen[match.group(1)] = None

    return list(seen)


def _extract_placeholder_sections(template_path: Path) -> list:
    """
    Extract placeholders and return TemplateSection list with optional/list flags.

    - {{key}}  → required TemplateSection
    - {{?key}} → optional TemplateSection (optional=True)
    - {{?단어1}}, {{?단어2}}, ... → collapsed to TemplateSection(name="단어", is_list=True)
    """
    from docpilot.mapping.base import TemplateSection

    text = _read_template_text(template_path)
    if text is None:
        return []

    search_text = re.sub(r'<[^>]+>', '', text)

    # Collect all keys in first-seen order
    all_keys: list[str] = []
    seen_keys: set[str] = set()
    optional_keys: set[str] = set()
    dynamic_list_keys: set[str] = set()  # {{?key?}}

    for m in _DYNAMIC_LIST_RE.finditer(search_text):
        dynamic_list_keys.add(m.group(1))

    for m in _OPTIONAL_PLACEHOLDER_RE.finditer(search_text):
        optional_keys.add(m.group(1))

    for m in _PLACEHOLDER_RE.finditer(search_text):
        key = m.group(1)
        if key not in seen_keys:
            all_keys.append(key)
            seen_keys.add(key)

    # Detect numbered optional groups: {{?단어1}}, {{?단어2}}, ... → base "단어"
    numbered_groups: dict[str, int] = {}  # base → max N
    numbered_first_key: dict[str, str] = {}  # base → first raw key (for style_hint lookup)
    for key in all_keys:
        if key in optional_keys and key not in dynamic_list_keys:
            m = _NUMBERED_GROUP_RE.match(key)
            if m:
                base = m.group(1) + m.group(3)
                n = int(m.group(2))
                if base not in numbered_groups:
                    numbered_groups[base] = n
                    numbered_first_key[base] = key
                else:
                    numbered_groups[base] = max(numbered_groups[base], n)

    # Build TemplateSection list, collapsing numbered optional groups
    result: list[TemplateSection] = []
    emitted: set[str] = set()

    for key in all_keys:
        if key in dynamic_list_keys:
            # {{?key?}} → dynamic list (count determined by LLM from source data)
            if key not in emitted:
                emitted.add(key)
                result.append(TemplateSection(name=key, is_list=True, group_max=0))
        elif key in optional_keys:
            m = _NUMBERED_GROUP_RE.match(key)
            if m:
                base = m.group(1) + m.group(3)
                if base not in emitted:
                    emitted.add(base)
                    result.append(TemplateSection(
                        name=base,
                        optional=True,
                        is_list=True,
                        group_max=numbered_groups[base],
                    ))
                continue
            if key not in emitted:
                emitted.add(key)
                result.append(TemplateSection(name=key, optional=True))
        else:
            if key not in emitted:
                emitted.add(key)
                result.append(TemplateSection(name=key))

    return result


def convert_to_list_placeholder(
    path: str | Path,
    keys: list[str] | str,
    output: str | Path | None = None,
) -> Path:
    """
    Convert {{key}} placeholders to {{?key?}} (dynamic list) in an existing template.

    path:   source .hwpx or .docx template
    keys:   placeholder name(s) to convert (single string or list)
    output: destination path; if None, overwrites the source file in-place

    Returns the output path.
    """
    path = Path(path)
    output_path = Path(output) if output is not None else path

    if isinstance(keys, str):
        keys = [keys]
    if not keys:
        return output_path

    ext = path.suffix.lower()
    if ext == ".hwpx":
        _convert_hwpx_placeholders(path, keys, output_path)
    elif ext == ".docx":
        _convert_docx_placeholders(path, keys, output_path)
    else:
        raise DocPilotError(
            f"Unsupported format '{ext}'",
            detail="Supported: .hwpx, .docx",
        )
    return output_path


def _convert_hwpx_placeholders(path: Path, keys: list[str], output: Path) -> None:
    import io

    with zipfile.ZipFile(path, "r") as zf_in:
        names = zf_in.namelist()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf_out:
            for name in names:
                data = zf_in.read(name)
                if name.endswith("section0.xml"):
                    text = data.decode("utf-8")
                    for key in keys:
                        text = re.sub(
                            r"\{\{" + re.escape(key) + r"\}\}",
                            "{{?" + key + "?}}",
                            text,
                        )
                    data = text.encode("utf-8")
                compress = zipfile.ZIP_STORED if name == "mimetype" else zipfile.ZIP_DEFLATED
                zf_out.writestr(name, data, compress_type=compress)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(buf.getvalue())


def _convert_docx_placeholders(path: Path, keys: list[str], output: Path) -> None:
    try:
        import docx
    except ImportError as e:
        raise DocPilotError("python-docx required: pip install python-docx") from e

    pattern = re.compile(
        r"\{\{(" + "|".join(re.escape(k) for k in keys) + r")\}\}"
    )

    doc = docx.Document(str(path))

    def _convert_para(para) -> None:
        full_text = "".join(run.text for run in para.runs)
        if not pattern.search(full_text):
            return
        new_text = pattern.sub(lambda m: "{{?" + m.group(1) + "?}}", full_text)
        if para.runs:
            para.runs[0].text = new_text
            for run in para.runs[1:]:
                run.text = ""

    for para in doc.paragraphs:
        _convert_para(para)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    _convert_para(para)

    output.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output))
