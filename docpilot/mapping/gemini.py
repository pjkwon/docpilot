from __future__ import annotations

import logging
import os
import time

from docpilot.exceptions import ContextExceededError, MappingError, is_context_overflow_error
from docpilot.mapping.base import BaseLLMMapper, MappingResult, TemplateSection

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.0-flash"


class GeminiMapper(BaseLLMMapper):
    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 8096,
    ) -> None:
        self._model = model
        self._max_tokens = max_tokens
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self._api_key:
            raise MappingError(
                "Gemini API key not provided",
                detail="Pass api_key or set GEMINI_API_KEY env var",
            )

    def complete(self, prompt: str, max_tokens: int = 2048) -> str:
        try:
            from google import genai
            from google.genai import types
        except ImportError as e:
            raise MappingError("google-genai SDK required: pip install google-genai") from e
        client = genai.Client(api_key=self._api_key)
        try:
            response = client.models.generate_content(
                model=self._model,
                contents=prompt,
                config=types.GenerateContentConfig(max_output_tokens=max_tokens),
            )
        except Exception as e:
            raise MappingError("Gemini API call failed", detail=str(e)) from e
        return response.text or ""

    def map(
        self,
        content,
        sections: list[TemplateSection],
        instructions: str | None = None,
    ) -> MappingResult:
        try:
            from google import genai
            from google.genai import types
        except ImportError as e:
            raise MappingError("google-genai SDK required: pip install google-genai") from e

        client = genai.Client(api_key=self._api_key)
        prompt = self._build_prompt(self._resolve_content(content), sections, instructions)

        start = time.perf_counter()
        try:
            response = client.models.generate_content(
                model=self._model,
                contents=prompt,
                config=types.GenerateContentConfig(max_output_tokens=self._max_tokens),
            )
        except Exception as e:
            if is_context_overflow_error(str(e)):
                raise ContextExceededError("Gemini API가 컨텍스트 초과로 요청을 거부함", detail=str(e)) from e
            raise MappingError("Gemini API call failed", detail=str(e)) from e
        elapsed = time.perf_counter() - start

        raw = response.text or ""
        candidates = getattr(response, "candidates", None) or []
        finish_reason = str(candidates[0].finish_reason) if candidates else None
        truncated = finish_reason is not None and "MAX_TOKENS" in finish_reason.upper()
        if truncated:
            usage_dbg = response.usage_metadata
            logger.warning(
                "Gemini 응답이 max_tokens로 잘림: finish_reason=%s, input_tokens=%s, "
                "output_tokens=%s, 응답 끝부분=%r",
                finish_reason, getattr(usage_dbg, "prompt_token_count", None),
                getattr(usage_dbg, "candidates_token_count", None), raw[-200:],
            )
        mapped = self._parse_response(raw, sections, truncated=truncated)

        usage = response.usage_metadata
        return MappingResult(
            sections=mapped,
            model=self._model,
            input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
            output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
            elapsed_seconds=elapsed,
            metadata={"finish_reason": finish_reason},
        )
