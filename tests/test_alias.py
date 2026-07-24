from __future__ import annotations

from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# extract_pairs — 실제 kiwipiepy 토큰화 사용 (규칙 기반 추출이라 목업 의미 없음)
# ---------------------------------------------------------------------------

class TestExtractPairs:
    def test_korean_first_pattern(self):
        from docpilot.search.alias import extract_pairs
        pairs = extract_pairs("에코플라스틱(Ecoplastic)을 개발했다.")
        assert ("에코플라스틱", "Ecoplastic") in pairs

    def test_latin_first_pattern(self):
        from docpilot.search.alias import extract_pairs
        pairs = extract_pairs("Ecoplastic(에코플라스틱)을 개발했다.")
        assert ("에코플라스틱", "Ecoplastic") in pairs

    def test_no_pairing_returns_empty(self):
        from docpilot.search.alias import extract_pairs
        pairs = extract_pairs("에코플라스틱을 개발했다. 예산은 10억 원이다.")
        assert pairs == []

    def test_multiple_pairs_in_one_document(self):
        from docpilot.search.alias import extract_pairs
        text = "에코플라스틱(Ecoplastic) 사업과 스마트팩토리(SmartFactory) 사업을 함께 추진한다."
        pairs = extract_pairs(text)
        assert ("에코플라스틱", "Ecoplastic") in pairs
        assert ("스마트팩토리", "SmartFactory") in pairs

    def test_empty_text_returns_empty(self):
        from docpilot.search.alias import extract_pairs
        assert extract_pairs("") == []

    def test_parenthetical_without_latin_ignored(self):
        from docpilot.search.alias import extract_pairs
        pairs = extract_pairs("본 계약(신규 공급 계약)의 총액은 8억 원이다.")
        assert pairs == []


# ---------------------------------------------------------------------------
# store_aliases
# ---------------------------------------------------------------------------

class TestStoreAliases:
    def test_inserts_new_pair(self):
        from docpilot.search.alias import store_aliases

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        store_aliases(db, [("에코플라스틱", "Ecoplastic")], source_document_id=1)

        db.add.assert_called_once()
        added = db.add.call_args[0][0]
        assert added.korean_term == "에코플라스틱"
        assert added.latin_alias == "Ecoplastic"
        assert added.source_document_id == 1
        db.flush.assert_called_once()

    def test_skips_existing_pair(self):
        from docpilot.search.alias import store_aliases

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = object()  # already exists

        store_aliases(db, [("에코플라스틱", "Ecoplastic")])

        db.add.assert_not_called()

    def test_empty_pairs_is_noop(self):
        from docpilot.search.alias import store_aliases

        db = MagicMock()
        store_aliases(db, [])

        db.add.assert_not_called()
        db.flush.assert_called_once()  # flush still called; harmless no-op on empty session


# ---------------------------------------------------------------------------
# expand_query
# ---------------------------------------------------------------------------

class TestExpandQuery:
    def test_prefix_match_returns_korean_term(self):
        from docpilot.search.alias import expand_query

        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [("에코플라스틱",)]

        terms = expand_query(db, "eco")

        assert terms == ["에코플라스틱"]

    def test_no_latin_word_in_query_skips_lookup(self):
        from docpilot.search.alias import expand_query

        db = MagicMock()
        terms = expand_query(db, "예산 삭감")

        db.query.assert_not_called()
        assert terms == []

    def test_case_insensitive(self):
        from docpilot.search.alias import expand_query

        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [("에코플라스틱",)]

        terms = expand_query(db, "ECO")

        assert terms == ["에코플라스틱"]


# ---------------------------------------------------------------------------
# 통합: 인덱싱 시 병기 1회만 존재해도, 이후 여러 청크의 다른 발화까지 검색되는지
# ---------------------------------------------------------------------------

class TestAliasEndToEnd:
    def test_eco_query_finds_document_via_single_pairing(self, pilot, tmp_path):
        """
        문서에 "에코플라스틱(Ecoplastic)" 병기가 딱 한 번만 등장하고,
        나머지는 전부 "에코플라스틱"이 조사 붙은 형태(병기 없음)로만 등장해도
        "eco" 쿼리로 검색되는지 확인.
        """
        doc = tmp_path / "product.txt"
        doc.write_text(
            "신제품 에코플라스틱(Ecoplastic)을 출시했다.\n\n"
            "에코플라스틱은 재활용 원료로 제작되었다.\n\n"
            "에코플라스틱의 생산 단가는 기존 대비 15% 낮다.\n\n"
            "예산 삭감과 인사 발령 관련 내용은 이 문서와 무관하다.",
            encoding="utf-8",
        )

        pilot.index(tmp_path)

        bm25_results = pilot.search("eco", mode="bm25")
        assert any("product.txt" in r.source for r in bm25_results)

        exact_results = pilot.search("eco", mode="exact")
        assert any("product.txt" in r.source for r in exact_results)

    def test_unrelated_query_does_not_match(self, pilot, tmp_path):
        doc = tmp_path / "product.txt"
        doc.write_text("에코플라스틱(Ecoplastic)을 출시했다.", encoding="utf-8")

        pilot.index(tmp_path)

        results = pilot.search("완전히 무관한 단어", mode="bm25", or_fallback=False)
        assert not any("product.txt" in r.source for r in results)
