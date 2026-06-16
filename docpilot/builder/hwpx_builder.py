from __future__ import annotations

import copy
import shutil
import tempfile
import zipfile
from pathlib import Path

from docpilot.builder.base import BaseBuilder, PLACEHOLDER_RE
from docpilot.exceptions import BuilderError

# Candidate content file paths inside the HWPX ZIP (tried in order)
_CONTENT_CANDIDATES = ["Contents/content.hml", "Contents/section0.xml"]


class HwpxBuilder(BaseBuilder):
    def build(
        self,
        template: str | Path,
        sections: dict[str, str | list[str]],
        output: str | Path,
    ) -> Path:
        template, output = self._validate_paths(template, output)

        if template.suffix.lower() != ".hwpx":
            raise BuilderError(f"Expected .hwpx template, got '{template.suffix}'")

        try:
            from lxml import etree
        except ImportError as e:
            raise BuilderError("lxml is required: pip install lxml") from e

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _unpack(template, tmp_path)

            content_file = next(
                (tmp_path / cp for cp in _CONTENT_CANDIDATES if (tmp_path / cp).exists()),
                None,
            )
            if content_file is None:
                raise BuilderError(
                    "No content file found in HWPX (tried content.hml, section0.xml)",
                    detail=str(template),
                )

            tree = etree.parse(str(content_file))
            root = tree.getroot()

            _replace_placeholders(root, sections)

            tree.write(
                str(content_file),
                xml_declaration=True,
                encoding="UTF-8",
                pretty_print=False,
            )

            _pack(tmp_path, output)

        return output


def _unpack(hwpx: Path, dest: Path) -> None:
    try:
        with zipfile.ZipFile(hwpx, "r") as zf:
            zf.extractall(dest)
    except zipfile.BadZipFile as e:
        raise BuilderError("Invalid HWPX file (not a ZIP)", detail=str(e)) from e


def _pack(src: Path, output: Path) -> None:
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        # mimetype must be first and uncompressed per OPC spec
        mimetype = src / "mimetype"
        if mimetype.exists():
            zf.write(mimetype, "mimetype", compress_type=zipfile.ZIP_STORED)

        for file in sorted(src.rglob("*")):
            if not file.is_file():
                continue
            if file.name == "mimetype":
                continue
            zf.write(file, file.relative_to(src))


def _replace_placeholders(root, sections: dict[str, str | list[str]]) -> None:
    # Detect hp namespace from document root (supports both 2011 and 2012 variants)
    hp_ns = root.nsmap.get("hp", "http://www.hancom.co.kr/hwpml/2012/paragraph")
    hp_t = f"{{{hp_ns}}}t"
    hp_p = f"{{{hp_ns}}}p"
    hp_linesegarray = f"{{{hp_ns}}}linesegarray"
    hp_lineseg = f"{{{hp_ns}}}lineseg"

    # Collect all existing IDs so generated IDs never collide
    existing_ids = {int(el.get("id", 0)) for el in root.iter(hp_p) if el.get("id")}
    next_id = max(existing_ids, default=2_000_000_000) + 1

    for para in list(root.iter(hp_p)):
        t_elements = para.findall(f".//{hp_t}")
        if not t_elements:
            continue

        full_text = "".join((el.text or "") for el in t_elements)
        match = PLACEHOLDER_RE.search(full_text)
        if not match:
            continue

        key = match.group(1)
        if key not in sections:
            continue

        val = sections[key]
        fill = "\n".join(val) if isinstance(val, list) else val
        replaced = PLACEHOLDER_RE.sub(fill, full_text, count=1)
        lines = replaced.split("\n")

        if len(lines) == 1:
            t_elements[0].text = lines[0]
            for el in t_elements[1:]:
                el.text = ""
            _clear_lineseg(para, hp_linesegarray, hp_lineseg)
            continue

        # Multiline: expand into one <hp:p> per line
        parent = para.getparent()
        if parent is None:
            t_elements[0].text = " ".join(lines)
            for el in t_elements[1:]:
                el.text = ""
            _clear_lineseg(para, hp_linesegarray, hp_lineseg)
            continue

        idx = list(parent).index(para)

        new_paras = []
        for line in lines:
            new_p = copy.deepcopy(para)
            new_p.set("id", str(next_id))
            next_id += 1
            new_t_elements = new_p.findall(f".//{hp_t}")
            if new_t_elements:
                new_t_elements[0].text = line
                for el in new_t_elements[1:]:
                    el.text = ""
            _clear_lineseg(new_p, hp_linesegarray, hp_lineseg)
            new_paras.append(new_p)

        parent.remove(para)
        for j, new_p in enumerate(new_paras):
            parent.insert(idx + j, new_p)


def _clear_lineseg(para, hp_linesegarray: str, hp_lineseg: str) -> None:
    """lineseg 자식을 제거해 HWP가 열 때 레이아웃을 재계산하도록 한다."""
    lsa = para.find(hp_linesegarray)
    if lsa is None:
        return
    for ls in list(lsa.findall(hp_lineseg)):
        lsa.remove(ls)
