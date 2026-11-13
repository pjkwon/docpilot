"""벡터 테이블 차원 — embed_fn의 실제 차원으로 생성하고, 기존 DB와 다르면 명확한 에러를 낸다."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from docpilot.db import client
from docpilot.exceptions import SearchError
from docpilot.search.embedding import embedding_dim


def _fixed_embed(dim: int):
    """dim 속성이 없는 사용자 정의 embed_fn 흉내 — 모델 로딩 없이 고정 벡터 반환."""
    def _embed(text):
        vec = [0.1] * dim
        return [vec for _ in text] if isinstance(text, list) else vec
    return _embed


def _vec_dim(db_path: Path, table: str = "vec_chunks") -> int:
    with sqlite3.connect(db_path) as conn:
        (sql,) = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
    return int(sql.split("float[")[1].split("]")[0])


class TestEmbeddingDim:
    def test_uses_dim_attribute_without_calling(self):
        def fn(text):
            raise AssertionError("dim 속성이 있으면 호출하면 안 됨")
        fn.dim = 1024

        assert embedding_dim(fn) == 1024

    def test_probes_when_no_dim_attribute(self):
        assert embedding_dim(_fixed_embed(384)) == 384

    def test_none(self):
        assert embedding_dim(None) is None

    def test_default_embed_fn_declares_dim(self):
        from docpilot.search.embedding import default_embed_fn

        assert default_embed_fn().dim == 768


class TestCreateTables:
    def test_new_db_uses_given_dim(self, tmp_path: Path):
        db = tmp_path / "t.db"
        client.init(f"sqlite:///{db}")

        client.create_tables(embedding_dim=384)

        assert _vec_dim(db) == 384
        assert _vec_dim(db, "vec_templates") == 384

    def test_new_db_without_dim_uses_default(self, tmp_path: Path):
        db = tmp_path / "t.db"
        client.init(f"sqlite:///{db}")

        client.create_tables()

        assert _vec_dim(db) == 768

    def test_dim_mismatch_with_existing_db_raises(self, tmp_path: Path):
        db = tmp_path / "t.db"
        client.init(f"sqlite:///{db}")
        client.create_tables(embedding_dim=768)

        with pytest.raises(SearchError, match="차원 불일치"):
            client.create_tables(embedding_dim=1024)

    def test_without_dim_keeps_existing_dim(self, tmp_path: Path):
        db = tmp_path / "t.db"
        client.init(f"sqlite:///{db}")
        client.create_tables(embedding_dim=384)

        client.create_tables()

        assert _vec_dim(db) == 384


def test_pilot_indexes_and_searches_with_non_default_dim(tmp_path: Path):
    from docpilot import DocPilot

    data = tmp_path / "data"
    data.mkdir()
    (data / "plan.txt").write_text("2026년 사업 계획: 신규 고객 확보", encoding="utf-8")
    pilot = DocPilot(
        api_key="sk-test", database_url=f"sqlite:///{tmp_path / 't.db'}", embed_fn=_fixed_embed(384),
    )

    pilot.index(data)

    assert pilot.search("사업 계획", mode="vector")
