from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from docpilot.mapping.base import TemplateSection


@dataclass
class SidecarData:
    name: str | None = None
    description: str | None = None
    keywords: list[str] = field(default_factory=list)
    instructions: str | None = None
    sections: list[TemplateSection] | None = None


def load_sidecar(path: str | Path) -> SidecarData | None:
    """
    Load section metadata from a sidecar JSON file.

    - Directory path  → looks for sidecar.json inside (built-in templates)
    - File path       → looks for <stem>.json next to the file (user templates)

    Returns SidecarData or None if no sidecar file is found.

    Sidecar format:
    {
      "name": "공문",                          (optional, used for built-in templates)
      "description": "행정 공문",               (optional)
      "keywords": ["공문", "행정문서"],          (optional, for built-in template search)
      "instructions": "전역 규칙 (선택)",
      "sections": {
        "섹션명": {
          "description": "내용 설명",
          "rule": "YYYY-MM-DD 형식",
          "style_hint": "한 줄 이내",
          "optional": false,
          "is_list": false
        }
      }
    }
    """
    path = Path(path)

    if path.is_dir():
        sidecar_path = path / "sidecar.json"
    else:
        sidecar_path = path.with_suffix(".json")

    if not sidecar_path.exists():
        return None

    with sidecar_path.open(encoding="utf-8") as f:
        data = json.load(f)

    raw_sections: dict = data.get("sections", {})
    sections: list[TemplateSection] | None = None
    if raw_sections:
        sections = [
            TemplateSection(
                name=name,
                description=meta.get("description", ""),
                style_hint=meta.get("style_hint", ""),
                rule=meta.get("rule", ""),
                optional=bool(meta.get("optional", False)),
                is_list=bool(meta.get("is_list", False)),
                group_max=int(meta.get("group_max", 0)),
            )
            for name, meta in raw_sections.items()
        ]

    return SidecarData(
        name=data.get("name") or None,
        description=data.get("description") or None,
        keywords=data.get("keywords") or [],
        instructions=data.get("instructions") or None,
        sections=sections,
    )


def sections_meta_to_list(
    placeholder_names: list[str],
    sections_meta: dict,
) -> list[TemplateSection]:
    """
    Build a TemplateSection list from extracted placeholder names and a metadata dict.

    sections_meta format: {"name": {"description": ..., "rule": ..., "optional": ..., ...}}
    Placeholders not found in sections_meta get a bare TemplateSection(name=name).
    """
    result = []
    for name in placeholder_names:
        meta = sections_meta.get(name, {})
        result.append(
            TemplateSection(
                name=name,
                description=meta.get("description", ""),
                style_hint=meta.get("style_hint", ""),
                rule=meta.get("rule", ""),
                optional=bool(meta.get("optional", False)),
                is_list=bool(meta.get("is_list", False)),
                group_max=int(meta.get("group_max", 0)),
            )
        )
    return result
