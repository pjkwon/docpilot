"""Audio ingestion via Whisper (OpenAI API or local faster-whisper).

Backend selection via environment variables:
    WHISPER_BACKEND  = "openai" | "local"   (default: "local")
    WHISPER_MODEL    = model name            (default: "large-v3")
    OPENAI_API_KEY   = <key>                 (required for openai backend)

Supported formats: mp3, mp4, wav, m4a, ogg, flac, webm
"""
from __future__ import annotations

import os
from pathlib import Path

from docpilot.exceptions import IngestionError
from docpilot.ingestion.models import IngestedDocument

SUPPORTED_SUFFIXES = {".mp3", ".mp4", ".wav", ".m4a", ".ogg", ".flac", ".webm"}

_BACKEND_ENV  = "WHISPER_BACKEND"
_MODEL_ENV    = "WHISPER_MODEL"
_DEFAULT_MODEL = "large-v3"


def ingest(
    path: str | Path,
    save_transcript: bool | str | Path = False,
) -> IngestedDocument:
    """Transcribe an audio file and return an IngestedDocument.

    save_transcript:
        False      — do not save (default)
        True       — save as <audio_stem>.txt next to the source file
        str/Path   — save to this exact path
    """
    path = Path(path)

    if not path.exists():
        raise IngestionError("File not found", detail=str(path))

    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise IngestionError(
            f"Unsupported audio format '{path.suffix}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_SUFFIXES))}",
            detail=str(path),
        )

    backend = os.environ.get(_BACKEND_ENV, "local").lower()
    model   = os.environ.get(_MODEL_ENV, _DEFAULT_MODEL)

    if backend == "openai":
        text = _transcribe_openai(path, model)
    elif backend == "local":
        text = _transcribe_local(path, model)
    else:
        raise IngestionError(
            f"Unknown WHISPER_BACKEND '{backend}'. Use 'openai' or 'local'."
        )

    if save_transcript is not False:
        out = path.with_suffix(".txt") if save_transcript is True else Path(save_transcript)
        out.write_text(text, encoding="utf-8")

    return IngestedDocument(
        source=path,
        content=text,
        mime_type=f"audio/{path.suffix.lstrip('.')}",
        metadata={
            "backend": backend,
            "model": model,
            "size_bytes": path.stat().st_size,
            "char_count": len(text),
        },
    )


def _transcribe_openai(path: Path, model: str) -> str:
    try:
        from openai import OpenAI
    except ImportError as e:
        raise IngestionError(
            "openai 패키지가 필요합니다: uv add docpilot[audio-openai]"
        ) from e

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise IngestionError("OPENAI_API_KEY 환경변수가 설정되지 않았습니다.")

    # OpenAI Whisper API model name is always "whisper-1" regardless of local model choice
    client = OpenAI(api_key=api_key)
    with path.open("rb") as f:
        response = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            response_format="text",
        )
    return response if isinstance(response, str) else response.text


def _transcribe_local(path: Path, model: str) -> str:
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise IngestionError(
            "faster-whisper 패키지가 필요합니다: uv add docpilot[audio-local]"
        ) from e

    wm = WhisperModel(model, device="cpu", compute_type="int8")
    segments, _ = wm.transcribe(
        str(path),
        language=None,   # auto-detect per segment (handles mixed Korean/English)
        beam_size=5,
    )
    return " ".join(seg.text.strip() for seg in segments)
