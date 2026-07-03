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


class BuilderError(DocPilotError):
    """Raised when document generation fails."""


class ConversionError(DocPilotError):
    """Raised when a file format conversion fails."""


class SearchError(DocPilotError):
    """Raised when a search or index operation fails."""


class TemplateError(DocPilotError):
    """Raised when template analysis or generation fails."""
