from __future__ import annotations


class DocPilotError(Exception):
    """Base exception for all docpilot errors."""

    def __init__(self, message: str, detail: str | None = None) -> None:
        self.detail = detail
        full_message = f"{message} — {detail}" if detail else message
        super().__init__(full_message)


class IngestionError(DocPilotError):
    """Raised when a source file cannot be parsed or read."""


class MappingError(DocPilotError):
    """Raised when LLM fails to map content to template sections."""


class ContextExceededError(MappingError):
    """Raised when a request would exceed (Ollama: local pre-flight estimate) or was
    rejected for exceeding (hosted APIs: live error from the provider) the model's
    context window. Kept distinct from MappingError so callers like RagMapper can retry
    with a smaller top_k specifically for this failure, without swallowing unrelated
    errors (auth, rate limit, etc.) that a retry can't fix."""


_CONTEXT_OVERFLOW_MARKERS = (
    "context length",
    "context_length_exceeded",
    "maximum context",
    "context window",
    "too many tokens",
    "exceeds the maximum number of tokens",
    "token limit",
)


def is_context_overflow_error(message: str) -> bool:
    """Heuristic match against a provider SDK error message to tell a context-window
    rejection apart from other API failures. Providers don't share a common exception
    type for this, so this is a substring match, not a guarantee — false negatives just
    fall through to the generic MappingError path (no retry); false positives cost at
    most a couple of wasted retries before the error surfaces anyway."""
    lowered = message.lower()
    return any(marker in lowered for marker in _CONTEXT_OVERFLOW_MARKERS)


class BuilderError(DocPilotError):
    """Raised when document generation fails."""


class ConversionError(DocPilotError):
    """Raised when a file format conversion fails."""


class SearchError(DocPilotError):
    """Raised when a search or index operation fails."""


class TemplateError(DocPilotError):
    """Raised when template analysis or generation fails."""
