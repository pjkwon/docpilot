"""
임베딩 통합 테스트 (intfloat/multilingual-e5-base, 768차원).

기존 test_search.py::TestEmbeddingSearch 는 mock 기반으로 인터페이스만 검증함.
이 파일은 실제 모델·실제 SQLite vec_chunks 를 사용해 end-to-end 를 검증함.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from docpilot.db.schema import EMBEDDING_DIM


class TestEmbedFn:
    def test_returns_correct_dimension(self, embed_fn):
        # schema.py의 EMBEDDING_DIM(768)과 모델 출력 차원이 일치하는지 확인.
        # 불일치 시 vec_chunks INSERT에서 차원 오류 발생.
        vec = embed_fn("피지컬 AI 연구용역")
        assert len(vec) == EMBEDDING_DIM

    def test_returns_floats(self, embed_fn):
        # sqlite-vec serialize_float32()에 넘기기 전 타입이 float인지 확인.
        # numpy float32가 섞이면 직렬화 오류가 날 수 있음.
        vec = embed_fn("테스트 문장")
        assert all(isinstance(v, float) for v in vec)

    def test_different_texts_differ(self, embed_fn):
        # 모델이 항상 동일한 벡터를 반환하는 퇴화 상태가 아닌지 확인.
        # 전부 0이거나 상수 벡터를 반환하면 검색이 동작하지 않음.
        v1 = embed_fn("사과")
        v2 = embed_fn("자동차")
        assert v1 != v2


class TestIndexWithEmbedding:
    def test_vec_chunks_populated_after_index(self, pilot_with_embed, tmp_path):
        # index() 호출 후 vec_chunks 가상 테이블에 실제로 행이 생성되는지 확인.
        # embed_fn이 있어도 _set_embedding() 호출이 누락되면 vec_chunks는 비어있음.
        (tmp_path / "doc.txt").write_text("피지컬 AI 연구용역 사업 계획", encoding="utf-8")
        pilot_with_embed.index(tmp_path)

        from docpilot.db import client
        from sqlalchemy import text

        with client.session() as db:
            count = db.execute(text("SELECT COUNT(*) FROM vec_chunks")).fetchone()[0]
        assert count > 0

    def test_vec_chunks_count_matches_chunks(self, pilot_with_embed, tmp_path):
        # 모든 청크에 대해 빠짐없이 임베딩이 저장됐는지 확인.
        # chunks 수 > vec_chunks 수이면 일부 청크가 검색에서 누락됨.
        (tmp_path / "doc.txt").write_text("피지컬 AI 연구용역 사업 계획", encoding="utf-8")
        pilot_with_embed.index(tmp_path)

        from docpilot.db import client
        from sqlalchemy import text

        with client.session() as db:
            chunks = db.execute(text("SELECT COUNT(*) FROM chunks")).fetchone()[0]
            vecs = db.execute(text("SELECT COUNT(*) FROM vec_chunks")).fetchone()[0]
        assert chunks == vecs


class TestVectorSearch:
    def test_returns_results(self, pilot_with_embed, tmp_path):
        # 인덱싱된 문서에 대해 벡터 검색이 결과를 반환하는지 확인.
        # vec_chunks가 비어있거나 KNN 쿼리 문법 오류 시 빈 리스트 반환.
        (tmp_path / "doc.txt").write_text("울산 피지컬 AI 스퀘어 구축 연구용역", encoding="utf-8")
        pilot_with_embed.index(tmp_path)

        from docpilot.search.embedding import search

        results = search("AI 연구", embed_fn=pilot_with_embed._embed_fn, top_k=3)
        assert len(results) > 0

    def test_result_fields_populated(self, pilot_with_embed, tmp_path):
        # SearchResult 각 필드가 올바르게 채워지는지 확인.
        # score는 거리 기반 변환값이므로 (0, 1] 범위여야 함.
        (tmp_path / "doc.txt").write_text("울산 피지컬 AI 스퀘어 구축 연구용역", encoding="utf-8")
        pilot_with_embed.index(tmp_path)

        from docpilot.search.embedding import search

        result = search("AI 연구", embed_fn=pilot_with_embed._embed_fn, top_k=1)[0]
        assert result.chunk_id > 0
        assert result.document_id > 0
        assert result.source
        assert result.content
        assert 0.0 < result.score <= 1.0

    def test_relevant_doc_ranks_higher(self, pilot_with_embed, tmp_path):
        # 쿼리와 의미적으로 가까운 문서가 상위에 랭크되는지 확인.
        # 임베딩 모델이 제대로 동작하지 않으면 무관한 문서가 1위가 될 수 있음.
        (tmp_path / "ai.txt").write_text("인공지능 머신러닝 딥러닝 연구", encoding="utf-8")
        (tmp_path / "food.txt").write_text("김치찌개 된장국 비빔밥 요리법", encoding="utf-8")
        pilot_with_embed.index(tmp_path)

        from docpilot.search.embedding import search

        results = search("AI 딥러닝", embed_fn=pilot_with_embed._embed_fn, top_k=5)
        sources = [Path(r.source).name for r in results]
        assert sources[0] == "ai.txt"
