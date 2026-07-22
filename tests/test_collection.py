"""collection 태그 기반 인덱싱/검색 스코프 테스트."""
from __future__ import annotations

from pathlib import Path

import pytest

from docpilot.db import client, indexer
from docpilot.db.schema import Document
from docpilot.ingestion.models import IngestedDocument
from docpilot.search import exact
from docpilot.search.models import SearchFilter


@pytest.fixture
def db(tmp_path: Path):
    client.init(f"sqlite:///{tmp_path / 'test.db'}")
    client.create_tables()
    yield
    # 다음 테스트가 새 tmp_path로 client.init()을 다시 부르므로 별도 정리 불필요


def _doc(path: str, content: str) -> IngestedDocument:
    return IngestedDocument(source=Path(path), content=content, mime_type="text/plain")


class TestIndexerCollectionTagging:
    def test_index_sets_collection(self, db):
        doc_id = indexer.index(_doc("/data/a.txt", "고유단어일치 내용"), collection="project_a")
        with client.session() as session:
            row = session.query(Document).filter(Document.id == doc_id).first()
            assert row.collection == "project_a"

    def test_index_without_collection_defaults_to_none(self, db):
        doc_id = indexer.index(_doc("/data/a.txt", "고유단어일치 내용"))
        with client.session() as session:
            row = session.query(Document).filter(Document.id == doc_id).first()
            assert row.collection is None

    def test_index_folder_unchanged_file_updates_collection_without_rechunk(self, db, tmp_path):
        folder = tmp_path / "data"
        folder.mkdir()
        (folder / "a.txt").write_text("고유단어일치 내용입니다", encoding="utf-8")

        ids_first = indexer.index_folder(folder, collection="project_a")
        assert len(ids_first) == 1
        doc_id = ids_first[0]

        with client.session() as session:
            before = session.query(Document).filter(Document.id == doc_id).first()
            assert before.collection == "project_a"
            chunk_count_before = len(before.chunks)

        # 파일 내용은 그대로 두고 collection만 바꿔서 재인덱싱 (force=False)
        ids_second = indexer.index_folder(folder, collection="project_b")
        assert ids_second == ids_first  # 같은 document id — re-chunk 안 됨

        with client.session() as session:
            after = session.query(Document).filter(Document.id == doc_id).first()
            assert after.collection == "project_b"
            assert len(after.chunks) == chunk_count_before

    def test_index_folder_same_collection_is_noop(self, db, tmp_path):
        folder = tmp_path / "data"
        folder.mkdir()
        (folder / "a.txt").write_text("고유단어일치 내용입니다", encoding="utf-8")

        ids_first = indexer.index_folder(folder, collection="project_a")
        ids_second = indexer.index_folder(folder, collection="project_a")
        assert ids_first == ids_second


class TestSearchFilterCollection:
    def test_collection_filter_scopes_results(self, db):
        indexer.index(_doc("/data/a.txt", "고유단어일치 내용 A"), collection="project_a")
        indexer.index(_doc("/data/b.txt", "고유단어일치 내용 B"), collection="project_b")

        results_a = exact.search("고유단어일치", filters=SearchFilter(collection="project_a"))
        assert len(results_a) == 1
        assert results_a[0].source == "/data/a.txt" or results_a[0].source == str(Path("/data/a.txt"))

    def test_no_collection_filter_returns_all(self, db):
        indexer.index(_doc("/data/a.txt", "고유단어일치 내용 A"), collection="project_a")
        indexer.index(_doc("/data/b.txt", "고유단어일치 내용 B"), collection="project_b")

        results = exact.search("고유단어일치")
        assert len(results) == 2

    def test_collection_filter_excludes_untagged_documents(self, db):
        indexer.index(_doc("/data/a.txt", "고유단어일치 내용 A"), collection="project_a")
        indexer.index(_doc("/data/b.txt", "고유단어일치 내용 B"))  # collection 없음

        results = exact.search("고유단어일치", filters=SearchFilter(collection="project_a"))
        assert len(results) == 1


class TestDocPilotSearchCollectionParam:
    def test_conflicting_collection_and_filters_raises(self, tmp_path):
        from docpilot import DocPilot

        pilot = DocPilot(
            api_key="sk-test",
            database_url=f"sqlite:///{tmp_path / 'test.db'}",
            embed_fn=None,
        )
        with pytest.raises(ValueError, match="conflicts"):
            pilot.search(
                "쿼리",
                mode="exact",
                collection="project_a",
                filters=SearchFilter(collection="project_b"),
            )
