from __future__ import annotations

import logging
import os
import time

from docpilot.exceptions import ContextExceededError, MappingError, is_context_overflow_error
from docpilot.mapping.base import BaseLLMMapper, MappingResult, TemplateSection

logger = logging.getLogger(__name__)

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
            if is_context_overflow_error(str(e)):
                raise ContextExceededError("OpenAI API가 컨텍스트 초과로 요청을 거부함", detail=str(e)) from e
            raise MappingError("OpenAI API call failed", detail=str(e)) from e
        elapsed = time.perf_counter() - start

        choice = response.choices[0]
        raw = choice.message.content or ""
        truncated = choice.finish_reason == "length"
        if truncated:
            logger.warning(
                "OpenAI 응답이 max_tokens로 잘림: finish_reason=%s, input_tokens=%d, "
                "output_tokens=%d, 응답 끝부분=%r",
                choice.finish_reason, response.usage.prompt_tokens,
                response.usage.completion_tokens, raw[-200:],
            )
        mapped = self._parse_response(raw, sections, truncated=truncated)

        return MappingResult(
            sections=mapped,
            model=self._model,
            input_tokens=response.usage.prompt_tokens,
            output_tokens=response.usage.completion_tokens,
            elapsed_seconds=elapsed,
            metadata={"finish_reason": choice.finish_reason},
        )
