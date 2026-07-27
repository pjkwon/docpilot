from __future__ import annotations

import logging
import os
import time

from docpilot.exceptions import ContextExceededError, MappingError, is_context_overflow_error
from docpilot.mapping.base import BaseLLMMapper, MappingResult, TemplateSection

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-6"


class ClaudeMapper(BaseLLMMapper):
    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 8096,
    ) -> None:
        self._model = model
        self._max_tokens = max_tokens
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self._api_key:
            raise MappingError(
                "Anthropic API key not provided",
                detail="Pass api_key or set ANTHROPIC_API_KEY env var",
            )

    def complete(self, prompt: str, max_tokens: int = 2048) -> str:
        try:
            import anthropic
        except ImportError as e:
            raise MappingError("anthropic SDK required: pip install anthropic") from e
        client = anthropic.Anthropic(api_key=self._api_key)
        try:
            response = client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as e:
            raise MappingError("Claude API call failed", detail=str(e)) from e
        return response.content[0].text

    def map(self, content, sections: list[TemplateSection], instructions: str | None = None) -> MappingResult:
        try:
            import anthropic
        except ImportError as e:
            raise MappingError("anthropic SDK required: pip install anthropic") from e

        client = anthropic.Anthropic(api_key=self._api_key)
        prompt = self._build_prompt(self._resolve_content(content), sections, instructions)

        start = time.perf_counter()
        try:
            response = client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as e:
            if is_context_overflow_error(str(e)):
                raise ContextExceededError("Claude API가 컨텍스트 초과로 요청을 거부함", detail=str(e)) from e
            raise MappingError("Claude API call failed", detail=str(e)) from e
        elapsed = time.perf_counter() - start

        raw = response.content[0].text
        truncated = response.stop_reason == "max_tokens"
        if truncated:
            logger.warning(
                "Claude 응답이 max_tokens로 잘림: stop_reason=%s, input_tokens=%d, "
                "output_tokens=%d, 응답 끝부분=%r",
                response.stop_reason, response.usage.input_tokens,
                response.usage.output_tokens, raw[-200:],
            )
        mapped = self._parse_response(raw, sections, truncated=truncated)

        return MappingResult(
            sections=mapped,
            model=self._model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            elapsed_seconds=elapsed,
            metadata={"stop_reason": response.stop_reason},
        )

    def count_tokens(self, content: str | list, sections: list[TemplateSection], instructions: str | None = None) -> int:
        """Count input tokens for a mapping request without making the actual API call."""
        try:
            import anthropic
        except ImportError as e:
            raise MappingError("anthropic SDK required: pip install anthropic") from e

        client = anthropic.Anthropic(api_key=self._api_key)
        prompt = self._build_prompt(self._resolve_content(content), sections, instructions)

        try:
            response = client.messages.count_tokens(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as e:
            raise MappingError("Token counting failed", detail=str(e)) from e

        return response.input_tokens
