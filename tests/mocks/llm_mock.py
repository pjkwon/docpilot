from __future__ import annotations

from docpilot.mapping.base import BaseLLMMapper, MappingResult, TemplateSection


class MockMapper(BaseLLMMapper):
    """Deterministic mapper for tests — returns section name as content."""

    def __init__(self, model: str = "mock-model", latency: float = 0.0) -> None:
        self.model = model
        self.latency = latency
        self.calls: list[tuple[str, list[TemplateSection]]] = []

    def complete(self, prompt: str, max_tokens: int = 2048) -> str:
        return "1"

    def map(
        self,
        content: str,
        sections: list[TemplateSection],
        instructions: str | None = None,
    ) -> MappingResult:
        self.calls.append((content, sections))
        return MappingResult(
            sections={s.name: f"[{s.name} 내용]" for s in sections},
            model=self.model,
            input_tokens=len(content) // 4,
            output_tokens=50 * len(sections),
            elapsed_seconds=self.latency,
        )
