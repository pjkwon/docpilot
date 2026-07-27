from __future__ import annotations

import logging
import os
import time

from docpilot.exceptions import ContextExceededError, MappingError, is_context_overflow_error
from docpilot.mapping.base import BaseLLMMapper, MappingResult, TemplateSection
from docpilot.tokens import estimate_tokens_raw

logger = logging.getLogger(__name__)

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
        num_ctx: int | None = None,
        timeout: float | None = None,
        temperature: float | None = None,
    ) -> None:
        self._model = model
        self._base_url = base_url
        self._api_key = api_key
        self._max_tokens = max_tokens
        self._num_ctx = num_ctx
        self._timeout = timeout
        self._temperature = temperature

    def _temp_kwargs(self) -> dict:
        return {"temperature": self._temperature} if self._temperature is not None else {}

    def _extra_body(self) -> dict:
        # Ollama-specific request option — openai SDK has no native num_ctx param, so it
        # must be passed through extra_body's "options" dict (Ollama's own convention).
        return {"options": {"num_ctx": self._num_ctx}} if self._num_ctx else {}

    def _check_num_ctx(self, prompt: str, max_tokens: int) -> None:
        """Reject prompts that won't fit num_ctx *before* sending — Ollama itself doesn't
        error on this, it silently truncates the prompt from the front instead, which loses
        RAG context with no signal in the response (see README "Ollama 등 로컬 모델의 컨텍스트
        한도"). Estimate only — no exact tokenizer available for Ollama models over the API."""
        if self._num_ctx is None:
            return
        estimated = estimate_tokens_raw(prompt)
        if estimated + max_tokens > self._num_ctx:
            raise ContextExceededError(
                f"예상 입력 토큰({estimated:,}) + max_tokens({max_tokens:,})이 "
                f"num_ctx({self._num_ctx:,})를 초과합니다.",
                detail=(
                    "이 상태로 보내면 Ollama가 프롬프트 앞부분을 조용히 잘라내거나 "
                    "응답이 중간에 끊길 수 있습니다. num_ctx를 늘리거나 top_k/컨텍스트 "
                    "크기를 줄이세요. (추정치는 바이트 기반 휴리스틱으로 ±30% 오차 가능)"
                ),
            )

    def complete(self, prompt: str, max_tokens: int = 2048) -> str:
        try:
            from openai import OpenAI
        except ImportError as e:
            raise MappingError("openai SDK required: pip install openai") from e
        self._check_num_ctx(prompt, max_tokens)
        client = OpenAI(api_key=self._api_key, base_url=self._base_url, timeout=self._timeout)
        try:
            response = client.chat.completions.create(
                model=self._model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
                extra_body=self._extra_body(),
                **self._temp_kwargs(),
            )
        except Exception as e:
            if is_context_overflow_error(str(e)):
                raise ContextExceededError(
                    f"API가 컨텍스트 초과로 요청을 거부함 ({self._base_url})", detail=str(e)
                ) from e
            raise MappingError(f"API call failed ({self._base_url})", detail=str(e)) from e
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

        client = OpenAI(api_key=self._api_key, base_url=self._base_url, timeout=self._timeout)
        prompt = self._build_prompt(self._resolve_content(content), sections, instructions)
        self._check_num_ctx(prompt, self._max_tokens)

        start = time.perf_counter()
        try:
            response = client.chat.completions.create(
                model=self._model,
                max_tokens=self._max_tokens,
                messages=[{"role": "user", "content": prompt}],
                extra_body=self._extra_body(),
                **self._temp_kwargs(),
            )
        except Exception as e:
            if is_context_overflow_error(str(e)):
                raise ContextExceededError(
                    f"API가 컨텍스트 초과로 요청을 거부함 ({self._base_url})", detail=str(e)
                ) from e
            raise MappingError(
                f"API call failed ({self._base_url})", detail=str(e)
            ) from e
        elapsed = time.perf_counter() - start

        choice = response.choices[0]
        raw = choice.message.content or ""
        truncated = choice.finish_reason == "length"
        if truncated:
            logger.warning(
                "%s 응답이 max_tokens로 잘림: finish_reason=%s, input_tokens=%d, "
                "output_tokens=%d, 응답 끝부분=%r",
                self._base_url, choice.finish_reason, response.usage.prompt_tokens,
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


def GrokMapper(
    api_key: str | None = None,
    model: str = "grok-3",
    max_tokens: int = 8096,
    temperature: float | None = None,
) -> OpenAICompatMapper:
    key = api_key or os.environ.get("XAI_API_KEY")
    if not key:
        raise MappingError(
            "Grok API key not provided",
            detail="Pass api_key or set XAI_API_KEY env var",
        )
    return OpenAICompatMapper(
        model=model, base_url=_GROK_BASE_URL, api_key=key, max_tokens=max_tokens,
        temperature=temperature,
    )


_OLLAMA_DEFAULT_TIMEOUT = 180.0  # seconds — Ollama has no explicit context-overflow error;
# a VRAM-starved request degrades to CPU offload instead of failing (20-50x slower, can look
# hung), so this is a starting-point safety net rather than a measured value. Pass timeout=
# to OllamaMapper()/OpenAICompatMapper() directly to tune for your hardware.


def OllamaMapper(
    model: str = "llama3.2",
    base_url: str | None = None,
    max_tokens: int = 8096,
    num_ctx: int | None = None,
    timeout: float = _OLLAMA_DEFAULT_TIMEOUT,
    temperature: float | None = None,
) -> OpenAICompatMapper:
    url = base_url or os.environ.get("OLLAMA_BASE_URL", _OLLAMA_BASE_URL)
    return OpenAICompatMapper(
        model=model, base_url=url, api_key="ollama", max_tokens=max_tokens,
        num_ctx=num_ctx, timeout=timeout, temperature=temperature,
    )
