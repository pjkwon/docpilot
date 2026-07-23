from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docpilot.ingestion.models import IngestedDocument


@dataclass
class TemplateSection:
    name: str
    description: str = ""
    style_hint: str = ""
    optional: bool = False     # True if originally {{?key}}
    is_list: bool = False      # True if collapsed from {{?key1}}, {{?key2}}, ...
    group_max: int = 0         # max N found in template (only meaningful when is_list=True)
    rule: str = ""             # per-section writing rule (format, unit, style constraint, etc.)


@dataclass
class MappingResult:
    sections: dict[str, str]
    model: str
    input_tokens: int
    output_tokens: int
    elapsed_seconds: float
    metadata: dict = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def merge_documents(docs: list[IngestedDocument]) -> str:
    """Combine multiple IngestedDocuments into a single labelled string."""
    parts: list[str] = []
    for doc in docs:
        label = f"[출처: {doc.source.name}]"
        parts.append(f"{label}\n{doc.content.strip()}")
    return "\n\n".join(parts)


class BaseLLMMapper(ABC):
    """Abstract interface for LLM-based content-to-template mappers."""

    @property
    def model_name(self) -> str:
        """Human-readable model identifier, used for logging and SectionStructure."""
        return getattr(self, "_model", type(self).__name__)

    @abstractmethod
    def complete(self, prompt: str, max_tokens: int = 2048) -> str:
        """Send a single prompt and return raw text. Used for structure/selection LLM calls."""

    @abstractmethod
    def map(
        self,
        content: str | list[IngestedDocument],
        sections: list[TemplateSection],
        instructions: str | None = None,
    ) -> MappingResult:
        """
        Map source content into template sections.

        content: plain text string, or a list of IngestedDocuments to merge automatically
        sections: list of template sections to fill
        Returns: MappingResult with generated content per section
        """

    def _resolve_content(self, content: str | list[IngestedDocument]) -> str:
        if isinstance(content, str):
            return content
        return merge_documents(content)

    def _build_prompt(
        self,
        content: str,
        sections: list[TemplateSection],
        instructions: str | None = None,
    ) -> str:
        def _fmt(s: TemplateSection) -> str:
            parts: list[str] = []
            if s.is_list:
                hint = f"[목록: 줄바꿈(\\n)으로 구분, 항목 수는 소스에 따라 자유롭게 결정 — 템플릿 슬롯 {s.group_max}개, 더 많으면 행 자동 추가·더 적으면 행 자동 삭제]"
                parts.append(hint)
            elif s.optional:
                parts.append("[선택: 소스에 내용이 없으면 빈 문자열 \"\" 반환]")
            if s.style_hint:
                parts.append(f"[스타일: {s.style_hint}]")
            if s.rule:
                parts.append(f"[규칙: {s.rule}]")
            if s.description:
                parts.append(s.description)
            suffix = " ".join(parts)
            return f'- "{s.name}": {suffix}' if suffix else f'- "{s.name}"'

        required = [s for s in sections if not s.optional and not s.is_list]
        optional_s = [s for s in sections if s.optional and not s.is_list]
        list_s = [s for s in sections if s.is_list]

        section_list = "\n".join(_fmt(s) for s in sections)
        section_keys = json.dumps([s.name for s in sections], ensure_ascii=False)

        # Build example object: lists get array example, optionals get "" example
        example_dict: dict = {}
        for s in sections:
            if s.is_list:
                example_dict[s.name] = "항목1\n항목2\n항목3"
            elif s.optional:
                example_dict[s.name] = ""
            else:
                example_dict[s.name] = "..."
        example_obj = json.dumps({"sections": example_dict}, ensure_ascii=False, indent=2)

        optional_rule = ""
        if optional_s:
            optional_rule = "- [선택] 표시 섹션은 소스에 내용이 없으면 반드시 빈 문자열 \"\"로 반환하세요.\n"
        list_rule = ""
        if list_s:
            list_rule = "- [목록] 표시 섹션은 항목을 줄바꿈(\\n)으로 구분해 하나의 문자열로 반환하세요. 소스에 있는 만큼만 추출하세요.\n"

        extra = (
            f"\n## 추가 작성 지침\n{instructions.strip()}\n"
            if instructions and instructions.strip()
            else ""
        )
        return f"""다음 소스 데이터를 읽고, 주어진 모든 섹션에 들어갈 내용을 한국어로 작성하세요.

## 소스 데이터
{content}

## 작성 규칙
- 아래 섹션 목록의 모든 항목을 빠짐없이 채워야 합니다.
- 소스 데이터가 여러 출처로 구성된 경우, 모든 출처를 종합하여 작성하세요.
- 소스 데이터에 해당 섹션의 내용이 불충분하면, 문맥상 가장 적절한 내용으로 작성하세요.
- 각 섹션 내용은 완성된 문장으로 작성하세요.
- 섹션에 [스타일: ...]가 표시된 경우, 해당 서식(글꼴 크기, 표 셀 너비 등)을 참고해 적절한 분량으로 작성하세요. 내용이 짧으면 짧게, 길면 길게 — 분량은 내용에 맞게 자유롭게 결정하세요.
{optional_rule}{list_rule}{extra}
## 채워야 할 섹션
{section_list}

## 출력 형식
반드시 아래 JSON 형식으로만 응답하세요. JSON 앞뒤로 다른 텍스트를 포함하지 마세요.
섹션 키는 다음 목록과 정확히 일치해야 합니다: {section_keys}

{example_obj}"""

    def _parse_response(
        self,
        raw: str,
        sections: list[TemplateSection],
        truncated: bool = False,
    ) -> dict[str, str | list[str]]:
        """
        truncated: True only when the API itself reported the response was cut off by
        the token limit (e.g. Claude stop_reason/OpenAI finish_reason == max_tokens).
        Never inferred from the shape of the broken JSON — malformed-but-complete output
        looks identical to truncated output at this point, so the distinction must come
        from the provider's own signal, not from guessing.
        """
        from docpilot.exceptions import MappingError

        data = {}
        try:
            start = raw.find("{")
            if start != -1:
                end = raw.rfind("}") + 1
                if end > start:
                    json_str = raw[start:end]
                else:
                    json_str = raw[start:] + "\n}"
                try:
                    data = json.loads(json_str)
                except Exception:
                    # Attempt to fix trailing commas or unclosed brackets
                    import re
                    clean_str = re.sub(r',\s*([}\]])', r'\1', json_str)
                    if not clean_str.endswith("}"):
                        clean_str += "}"
                    data = json.loads(clean_str)
            else:
                data = json.loads(raw)
        except (ValueError, json.JSONDecodeError) as e:
            if truncated:
                raise MappingError(
                    "LLM 응답이 max_tokens 제한으로 잘려 JSON을 파싱하지 못함",
                    detail=f"max_tokens 값을 늘려 재시도하세요. 응답 끝부분: ...{raw[-200:]}",
                ) from e
            raise MappingError("Failed to parse LLM response as JSON", detail=raw[:200]) from e

        # Handle both {"sections": {...}} wrapping and direct dict {...} outputs
        if isinstance(data, dict):
            result = data.get("sections", data)
            if not isinstance(result, dict):
                result = data
        else:
            result = {}

        # Required sections must be present; optional/list sections default to "" / []
        required_missing = [
            s.name for s in sections
            if not s.optional and not s.is_list and s.name not in result
        ]
        if required_missing:
            if truncated:
                raise MappingError(
                    "LLM 응답이 max_tokens 제한으로 잘려 일부 섹션이 누락됨",
                    detail=f"누락된 섹션: {', '.join(required_missing)} — max_tokens 값을 늘려 재시도하세요.",
                )
            raise MappingError(
                "LLM response missing sections",
                detail=", ".join(required_missing),
            )

        out: dict[str, str | list[str]] = {}
        for s in sections:
            val = result.get(s.name, "")
            if s.is_list:
                # Value should be a newline-separated string; split into list
                if isinstance(val, list):
                    out[s.name] = [str(v).strip() for v in val if str(v).strip()]
                else:
                    out[s.name] = [v.strip() for v in str(val).split("\n") if v.strip()]
            else:
                out[s.name] = str(val)
        return out
