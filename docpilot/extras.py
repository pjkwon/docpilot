"""데이터 폴더를 훑어 필요한 smart-docgen extras를 안내한다."""
from __future__ import annotations

from pathlib import Path

from docpilot.exceptions import DocPilotError


# Maps file extension → required extra (None = included in base install)
_EXT_EXTRAS: dict[str, str | None] = {
    ".txt":  None,
    ".md":   None,
    ".rst":  None,
    ".csv":  None,
    ".hwpx": None,
    ".hwp":  "hwp",
    ".pdf":  "pdf",
    ".docx": "docx",
}


def suggest_extras(folder: str | Path) -> dict:
    """
    Scan a data folder and suggest which docpilot extras to install.

    Returns a dict with:
      found          — {extension: file_count} for all files found
      unsupported    — {extension: file_count} for files docpilot cannot process
      required_extras — list of extras needed (e.g. ["pdf", "docx"])
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
        f'pip install "smart-docgen[{",".join(required)}]"' if required else None
    )

    return {
        "found": found,
        "unsupported": unsupported,
        "required_extras": required,
        "install_command": install_command,
    }
