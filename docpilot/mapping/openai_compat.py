from __future__ import annotations

import os
import time

from docpilot.exceptions import MappingError
from docpilot.mapping.base import BaseLLMMapper, MappingResult, TemplateSection

_GROK_BASE_URL = "https://api.x.ai/v1"
_OLLAMA_BASE_URL = "http://localhost:11434/v1"


class OpenAICompatMapper(BaseLLMMapper):
    """
    Mapper for any OpenAI-compatible API endpoint.
    Works with Grok (xAI), Ollama, LM Studio, and others.
    """

    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: str = "not-required",
        max_tokens: int = 8096,
    ) -> None:
        self._model = model
        self._base_url = base_url
        self._api_key = api_key
        self._max_tokens = max_tokens

    def complete(self, prompt: str, max_tokens: int = 2048) -> str:
        try:
            from openai import OpenAI
        except ImportError as e:
            raise MappingError("openai SDK required: pip install openai") from e
        client = OpenAI(api_key=self._api_key, base_url=self._base_url)
        try:
            response = client.chat.completions.create(
                model=self._model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as e:
            raise MappingError(f"API call failed ({self._base_url})", detail=str(e)) from e
        return response.choices[0].message.content or ""

    def map(self, content, sections: list[TemplateSection]) -> MappingResult:
        try:
            from openai import OpenAI
        except ImportError as e:
            raise MappingError("openai SDK required: pip install openai") from e

        client = OpenAI(api_key=self._api_key, base_url=self._base_url)
        prompt = self._build_prompt(self._resolve_content(content), sections)

        start = time.perf_counter()
        try:
            response = client.chat.completions.create(
                model=self._model,
                max_tokens=self._max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as e:
            raise MappingError(
                f"API call failed ({self._base_url})", detail=str(e)
            ) from e
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


def GrokMapper(
    api_key: str | None = None,
    model: str = "grok-3",
    max_tokens: int = 8096,
) -> OpenAICompatMapper:
    key = api_key or os.environ.get("XAI_API_KEY")
    if not key:
        raise MappingError(
            "Grok API key not provided",
            detail="Pass api_key or set XAI_API_KEY env var",
        )
    return OpenAICompatMapper(model=model, base_url=_GROK_BASE_URL, api_key=key, max_tokens=max_tokens)


def OllamaMapper(
    model: str = "llama3.2",
    base_url: str | None = None,
    max_tokens: int = 8096,
) -> OpenAICompatMapper:
    url = base_url or os.environ.get("OLLAMA_BASE_URL", _OLLAMA_BASE_URL)
    return OpenAICompatMapper(model=model, base_url=url, api_key="ollama", max_tokens=max_tokens)
