"""DB 백엔드별 저장·검색 — SQLite는 항상, PostgreSQL+pgvector는 URL을 지정했을 때만 실행.

PostgreSQL 실행 예 (pgvector 컨테이너):
    docker run -d --rm --name docpilot-pgtest -e POSTGRES_PASSWORD=pgtest -e POSTGRES_DB=docpilot \\
        -p 55432:5432 pgvector/pgvector:pg17
    DOCPILOT_TEST_PG_URL=postgresql://postgres:pgtest@localhost:55432/docpilot \\
        uv run --extra postgres pytest tests/test_db_backends.py

PostgreSQL은 테스트마다 public 스키마를 지우고 다시 만드므로 버려도 되는 DB만 지정할 것.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from docpilot.db import client, template_store

_PG_URL = os.environ.get("DOCPILOT_TEST_PG_URL")
_DIM = 8


def _embed(text):
    """텍스트마다 다른 8차원 벡터 — 같은 텍스트는 같은 벡터라 유사도 순위를 예측할 수 있다."""
    def one(t: str) -> list[float]:
        return [float(sum(ord(c) for c in t[i::_DIM]) % 97 + 1) for i in range(_DIM)]
    return [one(t) for t in text] if isinstance(text, list) else one(text)


@pytest.fixture(params=["sqlite", "postgresql"])
def db_url(request, tmp_path: Path) -> str:
    if request.param == "sqlite":
        return f"sqlite:///{tmp_path / 'test.db'}"

    if not _PG_URL:
        pytest.skip("DOCPILOT_TEST_PG_URL 미설정 — PostgreSQL 통합 테스트")
    from sqlalchemy import create_engine, text

    engine = create_engine(_PG_URL)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    return _PG_URL


def _section(tmp_path: Path, name: str) -> Path:
    path = tmp_path / f"{name}.xml"
    path.write_text("<hs:sec>{{제목}}</hs:sec>", encoding="utf-8")
    return path


def _save(tmp_path: Path, name: str, description: str) -> int:
    return template_store.save(
        name=name, path=_section(tmp_path, name), description=description,
        auto_sections_meta=False, embed_fn=_embed,
    )


def test_save_template_with_embedding(db_url, tmp_path: Path):
    client.init(db_url)
    client.create_tables(embedding_dim=_DIM)

    assert _save(tmp_path, "주간 업무 보고", "주간 업무 보고서 양식") > 0


def test_saved_template_found_by_name(db_url, tmp_path: Path):
    client.init(db_url)
    client.create_tables(embedding_dim=_DIM)
    weekly = _save(tmp_path, "주간 업무 보고", "주간 업무 보고서 양식")
    _save(tmp_path, "회의록", "회의 내용과 결정 사항 기록")

    found = template_store.search("주간 업무 보고", embed_fn=_embed, top_k=1, fallback=False)

    assert [r.id for r in found] == [weekly]


def test_pilot_index_and_search(db_url, tmp_path: Path):
    from docpilot import DocPilot

    data = tmp_path / "data"
    data.mkdir()
    (data / "plan.txt").write_text("2026년 사업 계획: 신규 고객 확보 전략", encoding="utf-8")
    pilot = DocPilot(api_key="sk-test", database_url=db_url, embed_fn=_embed)

    pilot.index(data)

    assert pilot.search("사업 계획", mode="vector")
    assert pilot.search("사업 계획", mode="hybrid")
