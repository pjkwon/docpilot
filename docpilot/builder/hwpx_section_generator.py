from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docpilot.builder.hwpx_style_extractor import StyleCatalog

# Supported paragraph types and their Korean descriptions
PARA_TYPES = {
    "title":    "문서 제목 (1개, 필수)",
    "date":     "날짜",
    "author":   "작성자/부서",
    "heading":  "섹션 제목",
    "body":     "본문 내용",
    "table":    "표 삽입 위치",
    "empty":    "빈 줄 (구분용)",
}


@dataclass
class SectionItem:
    type: str   # title | date | author | heading | body | table | empty
    key: str    # placeholder name e.g. "보고서 제목"
    desc: str   # description passed to content-fill LLM


@dataclass
class SectionStructure:
    items: list[SectionItem]
    model: str
    input_tokens: int
    output_tokens: int
    elapsed_seconds: float

    @property
    def placeholders(self) -> list[str]:
        return [item.key for item in self.items if item.key]


def generate_structure(
    content: str,
    catalog: StyleCatalog,
    instructions: str | None = None,
    model: str = "claude-sonnet-4-6",
) -> SectionStructure:
    """Ask the LLM to decide the document structure as a list of SectionItems."""
    try:
        import anthropic
    except ImportError as e:
        raise ImportError("anthropic required: pip install anthropic") from e

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

    prompt = _build_prompt(content, catalog, instructions)
    t0 = time.time()
    response = client.messages.create(
        model=model,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    elapsed = time.time() - t0

    items = _parse(response.content[0].text)
    return SectionStructure(
        items=items,
        model=model,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        elapsed_seconds=elapsed,
    )


def _build_prompt(content: str, catalog: StyleCatalog, instructions: str | None) -> str:
    type_list = "\n".join(f'  "{k}": {v}' for k, v in PARA_TYPES.items())
    extra = f"\n## 추가 지침\n{instructions.strip()}\n" if instructions else ""
    example = json.dumps([
        {"type": "title",   "key": "보고서 제목",  "desc": "문서의 핵심 주제를 담은 제목"},
        {"type": "date",    "key": "작성일",       "desc": "YYYY년 MM월 DD일"},
        {"type": "author",  "key": "작성자",       "desc": "작성 부서 또는 담당자"},
        {"type": "empty",   "key": "",             "desc": ""},
        {"type": "heading", "key": "1. 배경 및 목적", "desc": "첫 번째 섹션 제목"},
        {"type": "body",    "key": "배경 내용",    "desc": "배경과 목적을 설명하는 본문"},
        {"type": "heading", "key": "2. 주요 내용", "desc": "두 번째 섹션 제목"},
        {"type": "body",    "key": "주요 내용",    "desc": "핵심 내용 본문"},
    ], ensure_ascii=False, indent=2)

    return f"""다음 소스 데이터를 분석하여 이 내용을 담기에 적합한 한국어 공문서/보고서의 구조를 설계하세요.

## 소스 데이터 (앞 3000자)
{content[:3000]}

{extra}
## 사용 가능한 스타일
{catalog.to_prompt_text()}

## 단락 타입
{type_list}

## 규칙
- title은 반드시 1개
- 섹션이 여러 개일 때 heading 뒤에 body를 쌍으로 구성
- key 값은 나중에 내용을 채울 때 플레이스홀더로 사용되므로 한국어 명사구로 작성
- empty는 시각적 구분이 필요한 곳에만 사용 (과도하게 쓰지 말 것)
- 소스 데이터 분량과 성격에 맞게 섹션 수 결정

## 출력 형식
반드시 아래와 같은 JSON 배열로만 응답하세요. JSON 앞뒤에 다른 텍스트 금지.

{example}"""


def _parse(raw: str) -> list[SectionItem]:
    from docpilot.exceptions import MappingError

    try:
        start = raw.index("[")
        end = raw.rindex("]") + 1
        data = json.loads(raw[start:end])
    except (ValueError, json.JSONDecodeError) as e:
        raise MappingError("section structure JSON 파싱 실패", detail=raw[:300]) from e

    items = []
    for d in data:
        items.append(SectionItem(
            type=d.get("type", "body"),
            key=d.get("key", ""),
            desc=d.get("desc", ""),
        ))

    if not any(i.type == "title" for i in items):
        raise MappingError("LLM이 title 단락을 생성하지 않았습니다", detail=raw[:300])

    return items
