"""DocPilot 생성자 — LLM 매퍼 지연 생성.

LLM을 쓰지 않는 작업(index/search/템플릿 생성)은 API 키 없이 동작해야 하고,
키 누락은 LLM이 실제로 필요한 시점에 MappingError로 드러나야 한다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from docpilot import DocPilot
from docpilot.exceptions import MappingError
from tests.mocks.llm_mock import MockMapper

_ENV_VARS = (
    "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "XAI_API_KEY",
    "DOCPILOT_LLM", "DOCPILOT_MODEL",
)


def _stub_embed(text):
    """모델 로딩 없이 인덱싱을 통과시키는 고정 벡터 (768차원 = 기본 EMBEDDING_DIM)."""
    vec = [0.1] * 768
    return [vec for _ in text] if isinstance(text, list) else vec


@pytest.fixture()
def no_llm_env(monkeypatch):
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture()
def keyless_pilot(tmp_path: Path, no_llm_env) -> DocPilot:
    return DocPilot(
        llm="claude", database_url=f"sqlite:///{tmp_path / 'test.db'}", embed_fn=_stub_embed,
    )


def test_index_and_search_work_without_api_key(keyless_pilot, tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "plan.txt").write_text("2026년 사업 계획: 신규 고객 확보", encoding="utf-8")

    keyless_pilot.index(data)

    assert keyless_pilot.search("사업 계획", mode="bm25")


def test_generate_template_without_llm_needs_no_api_key(keyless_pilot, make_hwpx, tmp_path: Path):
    output = tmp_path / "template.hwpx"

    result = keyless_pilot.generate_template(
        [make_hwpx("a.hwpx"), make_hwpx("b.hwpx")], output=output, use_llm=False,
    )

    assert Path(result).exists()


def test_missing_api_key_surfaces_when_llm_is_needed(keyless_pilot, tmp_path: Path):
    with pytest.raises(MappingError, match="API key"):
        keyless_pilot.generate_from_content(
            content="본문", template="report", output=tmp_path / "out.hwpx",
        )


def test_unknown_llm_rejected_at_construction(tmp_path: Path):
    with pytest.raises(MappingError, match="Unknown LLM"):
        DocPilot(llm="nope", database_url=f"sqlite:///{tmp_path / 'test.db'}", embed_fn=_stub_embed)


def test_replacing_mapper_rewraps_rag_mapper(keyless_pilot):
    mock = MockMapper()

    keyless_pilot._mapper = mock

    assert keyless_pilot._mapper is mock
    assert keyless_pilot._rag_mapper._mapper is mock
