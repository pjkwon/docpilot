from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from docpilot.exceptions import SearchError
from docpilot.search.models import DocumentResult, SearchFilter, SearchResult


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_result(
    chunk_id=1, doc_id=1, source="file.txt", content="테스트 내용", score=0.9, metadata=None
) -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id,
        document_id=doc_id,
        source=source,
        content=content,
        score=score,
        metadata=metadata,
    )


def _make_chunk(chunk_id=1, doc_id=1, source="file.txt", content="테스트 내용"):
    chunk = MagicMock()
    chunk.id = chunk_id
    chunk.document_id = doc_id
    chunk.content = content
    return chunk, source, None  # (chunk, source, metadata)


# ---------------------------------------------------------------------------
# ExactSearch
# ---------------------------------------------------------------------------

class TestExactSearch:
    def test_returns_results(self):
        from tests.mocks.db_mock import mock_db_session
        from docpilot.search import exact

        chunk, source, meta = _make_chunk(content="사업 계획 핵심 내용")
        with mock_db_session(rows=[(chunk, source, meta)]):
            results = exact.search("사업 계획")

        assert len(results) == 1
        assert results[0].source == source
        assert results[0].content == "사업 계획 핵심 내용"

    def test_empty_query_raises(self):
        from docpilot.search import exact
        with pytest.raises(SearchError, match="empty"):
            exact.search("   ")

    def test_score_positive_for_match(self):
        from docpilot.search.exact import _score
        assert _score("사업 계획 내용", "사업 계획") > 0

    def test_score_zero_for_no_match(self):
        from docpilot.search.exact import _score
        assert _score("전혀 다른 내용", "사업 계획") == 0.0


# ---------------------------------------------------------------------------
# EmbeddingSearch
# ---------------------------------------------------------------------------

class TestEmbeddingSearch:
    def test_calls_embed_fn(self):
        from docpilot.search import embedding

        embed_fn = MagicMock(return_value=[0.1] * 1536)
        mock_row = MagicMock()
        mock_row.chunk_id = 1
        mock_row.document_id = 1
        mock_row.source = "file.txt"
        mock_row.content = "내용"
        mock_row.score = 0.9
        mock_row.metadata = None

        with (
            patch("docpilot.db.client.is_sqlite", return_value=False),
            patch("docpilot.db.client.session") as mock_session,
        ):
            ctx = MagicMock()
            ctx.__enter__ = MagicMock(return_value=MagicMock(
                execute=MagicMock(return_value=MagicMock(fetchall=MagicMock(return_value=[mock_row])))
            ))
            ctx.__exit__ = MagicMock(return_value=False)
            mock_session.return_value = ctx

            results = embedding.search("쿼리", embed_fn=embed_fn, top_k=5)

        embed_fn.assert_called_once_with("쿼리")
        assert len(results) == 1

    def test_empty_query_raises(self):
        from docpilot.search import embedding
        with pytest.raises(SearchError, match="empty"):
            embedding.search("", embed_fn=lambda x: [])


# ---------------------------------------------------------------------------
# MorphemeSearch
# ---------------------------------------------------------------------------

class TestMorphemeSearch:
    def test_jaccard_similarity(self):
        from docpilot.search.morpheme import _jaccard
        assert _jaccard({"사업", "계획"}, {"사업", "목표"}) == pytest.approx(1 / 3)
        assert _jaccard(set(), {"사업"}) == 0.0
        assert _jaccard({"사업"}, {"사업"}) == pytest.approx(1.0)

    def test_empty_query_raises(self):
        from docpilot.search import morpheme
        with pytest.raises(SearchError, match="empty"):
            morpheme.search("")


# ---------------------------------------------------------------------------
# SearchFilter / _filter helpers
# ---------------------------------------------------------------------------

class TestSearchFilter:
    def test_glob_to_like(self):
        from docpilot.search._filter import _glob_to_like
        assert _glob_to_like("*.hwpx") == "%.hwpx"
        assert _glob_to_like("docs/?.txt") == "docs/_.txt"

    def test_build_sql_where_empty(self):
        from docpilot.search._filter import build_sql_where
        clause, params = build_sql_where(SearchFilter(), is_sqlite=True)
        assert clause == ""
        assert params == {}

    def test_build_sql_where_source_pattern(self):
        from docpilot.search._filter import build_sql_where
        f = SearchFilter(source_pattern="*.hwpx")
        clause, params = build_sql_where(f, is_sqlite=True)
        assert "d.source LIKE" in clause
        assert params["f_source_pattern"] == "%.hwpx"

    def test_build_sql_where_mime_type(self):
        from docpilot.search._filter import build_sql_where
        f = SearchFilter(mime_type="application/vnd.hancom.hwpx")
        clause, params = build_sql_where(f, is_sqlite=True)
        assert "d.mime_type" in clause
        assert params["f_mime_type"] == "application/vnd.hancom.hwpx"

    def test_build_sql_where_dates(self):
        from docpilot.search._filter import build_sql_where
        dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
        f = SearchFilter(created_after=dt)
        clause, params = build_sql_where(f, is_sqlite=True)
        assert "d.created_at >=" in clause
        assert "2026-01-01" in params["f_created_after"]

    def test_build_sql_where_metadata_sqlite(self):
        from docpilot.search._filter import build_sql_where
        f = SearchFilter(metadata={"dept": "sales"})
        clause, params = build_sql_where(f, is_sqlite=True)
        assert "json_extract" in clause
        assert params["f_meta_0"] == "sales"

    def test_build_sql_where_metadata_pg(self):
        from docpilot.search._filter import build_sql_where
        f = SearchFilter(metadata={"dept": "sales"})
        clause, params = build_sql_where(f, is_sqlite=False)
        assert "->>" in clause
        assert params["f_meta_0"] == "sales"

    def test_invalid_metadata_key_raises(self):
        from docpilot.search._filter import build_sql_where
        f = SearchFilter(metadata={"bad key!": "value"})
        with pytest.raises(ValueError, match="alphanumeric"):
            build_sql_where(f, is_sqlite=True)


# ---------------------------------------------------------------------------
# Highlight
# ---------------------------------------------------------------------------

class TestHighlight:
    def test_no_match_returns_none_highlights(self):
        from docpilot.search.highlight import highlight
        r = _make_result(content="전혀 다른 내용")
        result = highlight(r, "사업 계획")
        assert result.highlights is None

    def test_single_term_match(self):
        from docpilot.search.highlight import highlight
        r = _make_result(content="사업 계획 문서입니다")
        result = highlight(r, "사업")
        assert result.highlights is not None
        start, end = result.highlights[0]
        assert result.content[start:end] == "사업"

    def test_multi_term_spans_merged(self):
        from docpilot.search.highlight import highlight
        r = _make_result(content="사업 계획 보고서")
        result = highlight(r, "사업 계획")
        # "사업" and "계획" are separate tokens — two spans
        assert result.highlights is not None
        assert len(result.highlights) == 2

    def test_overlapping_spans_merged(self):
        from docpilot.search.highlight import _find_spans
        spans = _find_spans("abcde", ["abc", "bcd"])
        # "abc"→(0,3) and "bcd"→(1,4) overlap → merged to (0,4)
        assert spans == [(0, 4)]

    def test_render_wraps_highlights(self):
        from docpilot.search.highlight import highlight, render
        r = _make_result(content="사업 계획 보고서")
        r = highlight(r, "사업")
        text = render(r, marker="**")
        assert "**사업**" in text

    def test_render_no_highlights_returns_content(self):
        from docpilot.search.highlight import render
        r = _make_result(content="내용")
        assert render(r) == "내용"


# ---------------------------------------------------------------------------
# group_by_document
# ---------------------------------------------------------------------------

class TestGroupByDocument:
    def _results(self):
        return [
            _make_result(chunk_id=1, doc_id=1, source="a.txt", content="청크1", score=0.9),
            _make_result(chunk_id=2, doc_id=1, source="a.txt", content="청크2", score=0.7),
            _make_result(chunk_id=3, doc_id=2, source="b.txt", content="청크3", score=0.5),
        ]

    def test_groups_by_document(self):
        from docpilot.search import group_by_document
        docs = group_by_document(self._results())
        assert len(docs) == 2

    def test_max_score(self):
        from docpilot.search import group_by_document
        docs = group_by_document(self._results(), score="max")
        doc_a = next(d for d in docs if d.source == "a.txt")
        assert doc_a.score == pytest.approx(0.9)

    def test_sum_score(self):
        from docpilot.search import group_by_document
        docs = group_by_document(self._results(), score="sum")
        doc_a = next(d for d in docs if d.source == "a.txt")
        assert doc_a.score == pytest.approx(1.6)

    def test_sorted_by_score_descending(self):
        from docpilot.search import group_by_document
        docs = group_by_document(self._results())
        assert docs[0].score >= docs[1].score

    def test_top_chunks_limit(self):
        from docpilot.search import group_by_document
        docs = group_by_document(self._results(), top_chunks=1)
        doc_a = next(d for d in docs if d.source == "a.txt")
        assert len(doc_a.top_chunks) == 1
        assert doc_a.chunk_count == 2  # total matched, not capped

    def test_chunk_count(self):
        from docpilot.search import group_by_document
        docs = group_by_document(self._results())
        doc_a = next(d for d in docs if d.source == "a.txt")
        assert doc_a.chunk_count == 2

    def test_invalid_score_raises(self):
        from docpilot.search import group_by_document
        with pytest.raises(ValueError, match="score"):
            group_by_document(self._results(), score="unknown")

    def test_empty_input(self):
        from docpilot.search import group_by_document
        assert group_by_document([]) == []


# ---------------------------------------------------------------------------
# HybridSearch
# ---------------------------------------------------------------------------

class TestHybridSearch:
    def _make(self, chunk_id, doc_id=1, source="f.txt", content="내용", score=0.5):
        return SearchResult(
            chunk_id=chunk_id,
            document_id=doc_id,
            source=source,
            content=content,
            score=score,
        )

    def test_empty_query_raises(self):
        from docpilot.search.hybrid import hybrid
        with pytest.raises(Exception, match="empty"):
            hybrid("   ")

    def test_bm25_only_when_no_embed_fn(self):
        """embed_fn 없으면 morpheme 결과를 그대로 반환."""
        from docpilot.search.hybrid import hybrid
        bm25_results = [self._make(1), self._make(2)]

        with patch("docpilot.search.hybrid.morpheme.search", return_value=bm25_results):
            results = hybrid("테스트", embed_fn=None, top_k=5)

        assert results == bm25_results

    def test_bm25_only_when_vector_empty(self):
        """벡터 결과가 비어있으면 BM25 결과만 반환."""
        from docpilot.search.hybrid import hybrid
        bm25_results = [self._make(1), self._make(2)]
        embed_fn = MagicMock(return_value=[0.1] * 4)

        with (
            patch("docpilot.search.hybrid.morpheme.search", return_value=bm25_results),
            patch("docpilot.search.embedding.search", return_value=[]),
        ):
            results = hybrid("테스트", embed_fn=embed_fn, top_k=5)

        assert results == bm25_results

    def test_rrf_fusion_merges_both_lanes(self):
        """두 레인 결과가 합쳐져 top_k 내에서 반환된다."""
        from docpilot.search.hybrid import hybrid
        bm25_results = [self._make(1, score=0.9), self._make(2, score=0.7)]
        vec_results = [self._make(3, score=0.95), self._make(1, score=0.8)]
        embed_fn = MagicMock(return_value=[0.1] * 4)

        with (
            patch("docpilot.search.hybrid.morpheme.search", return_value=bm25_results),
            patch("docpilot.search.embedding.search", return_value=vec_results),
        ):
            results = hybrid("테스트", embed_fn=embed_fn, top_k=10)

        chunk_ids = [r.chunk_id for r in results]
        assert 1 in chunk_ids
        assert 2 in chunk_ids
        assert 3 in chunk_ids

    def test_rrf_boosted_chunk_ranks_higher(self):
        """두 레인 모두에 나타난 청크가 한 레인만 있는 것보다 높은 점수를 받는다."""
        from docpilot.search.hybrid import hybrid
        # chunk 1: BM25 rank 0 + vector rank 0 → 최고 점수
        # chunk 2: BM25 rank 1 only
        # chunk 3: vector rank 1 only
        bm25_results = [self._make(1, score=0.9), self._make(2, score=0.8)]
        vec_results = [self._make(1, score=0.95), self._make(3, score=0.85)]
        embed_fn = MagicMock(return_value=[0.1] * 4)

        with (
            patch("docpilot.search.hybrid.morpheme.search", return_value=bm25_results),
            patch("docpilot.search.embedding.search", return_value=vec_results),
        ):
            results = hybrid("테스트", embed_fn=embed_fn, top_k=10)

        scores = {r.chunk_id: r.score for r in results}
        # chunk 1이 두 레인에 모두 있으므로 단일 레인 청크보다 점수가 높아야 함
        assert scores[1] > scores[2]
        assert scores[1] > scores[3]

    def test_top_k_limits_results(self):
        """top_k를 초과하지 않는다."""
        from docpilot.search.hybrid import hybrid
        bm25_results = [self._make(i, score=1.0 / (i + 1)) for i in range(10)]
        vec_results = [self._make(i + 10, score=1.0 / (i + 1)) for i in range(10)]
        embed_fn = MagicMock(return_value=[0.1] * 4)

        with (
            patch("docpilot.search.hybrid.morpheme.search", return_value=bm25_results),
            patch("docpilot.search.embedding.search", return_value=vec_results),
        ):
            results = hybrid("테스트", embed_fn=embed_fn, top_k=5)

        assert len(results) == 5

    def test_rrf_k_constant(self):
        """RRF 상수 k=60 기준: rank 0의 점수는 1/(60+1)."""
        from docpilot.search.hybrid import _RRF_K
        assert _RRF_K == 60

    def test_results_sorted_by_rrf_score_descending(self):
        """반환 결과는 RRF 점수 내림차순이다."""
        from docpilot.search.hybrid import hybrid
        bm25_results = [self._make(1, score=0.9), self._make(2, score=0.5)]
        vec_results = [self._make(2, score=0.95), self._make(1, score=0.4)]
        embed_fn = MagicMock(return_value=[0.1] * 4)

        with (
            patch("docpilot.search.hybrid.morpheme.search", return_value=bm25_results),
            patch("docpilot.search.embedding.search", return_value=vec_results),
        ):
            results = hybrid("테스트", embed_fn=embed_fn, top_k=10)

        for i in range(len(results) - 1):
            assert results[i].score >= results[i + 1].score
