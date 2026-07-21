from __future__ import annotations

import os
import time

from docpilot.exceptions import MappingError
from docpilot.mapping.base import BaseLLMMapper, MappingResult, TemplateSection

DEFAULT_MODEL = "gpt-4o"


class OpenAIMapper(BaseLLMMapper):
    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 8096,
    ) -> None:
        self._model = model
        self._max_tokens = max_tokens
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self._api_key:
            raise MappingError(
                "OpenAI API key not provided",
                detail="Pass api_key or set OPENAI_API_KEY env var",
            )

    def complete(self, prompt: str, max_tokens: int = 2048) -> str:
        try:
            from openai import OpenAI
        except ImportError as e:
            raise MappingError("openai SDK required: pip install openai") from e
        client = OpenAI(api_key=self._api_key)
        try:
            response = client.chat.completions.create(
                model=self._model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as e:
            raise MappingError("OpenAI API call failed", detail=str(e)) from e
        return response.choices[0].message.content or ""

    def map(
        self,
        content,
        sections: list[TemplateSection],
        instructions: str | None = None,
    ) -> MappingResult:
        try:
            from openai import OpenAI
        except ImportError as e:
            raise MappingError("openai SDK required: pip install openai") from e

        client = OpenAI(api_key=self._api_key)
        prompt = self._build_prompt(self._resolve_content(content), sections, instructions)

        start = time.perf_counter()
        try:
            response = client.chat.completions.create(
                model=self._model,
                max_tokens=self._max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as e:
            raise MappingError("OpenAI API call failed", detail=str(e)) from e
        elapsed = time.perf_counter() - start

        raw = response.choices[0].message.content or ""
        mapped = self._parse_response(raw, sections)

        return MappingResult(
            sections=mapped,
            model=self._model,
            input_tokens=response.usage.prompt_tokens,
            output_tokens=response.usage.completion_tokens,
            elapsed_seconds=elapsed,
        )
