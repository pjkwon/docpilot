"""
검색 품질 평가 — 실제 data/ 폴더 문서 기반 ground truth.

실행:
  uv run pytest tests/test_search_quality.py -v
  uv run pytest tests/test_search_quality.py -v -m slow   # 명시적 slow 포함
  uv run pytest -m "not slow"                              # 빠른 CI에서 제외

임계값 기준: 현재 하이브리드(BM25+Vector) 베이스라인.
성능이 떨어지면 테스트 실패 → 회귀 감지.
성능이 올라가면 임계값을 올려서 새 베이스라인으로 고정.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from docpilot.search.eval import EvalReport, QueryCase, evaluate

# ---------------------------------------------------------------------------
# Ground truth
# 문서별로 쿼리 2개씩, 해당 문서 basename이 top-k에 반드시 포함돼야 함.
# relevant_sources는 중복 없이 1개 파일명만 지정 (단일 문서 검색 검증).
# ---------------------------------------------------------------------------

EVAL_CASES: list[QueryCase] = [
    # 2025.07.28 에코플라스틱 현장답사.docx
    # → MES 경합 제안, 사출기 PLC 데이터 수집, 제네시스 범퍼 신공장
    QueryCase(
        query="사출기 PLC 데이터 수집 MES 구축",
        relevant_sources={"2025.07.28 에코플라스틱 현장답사.docx"},
    ),
    QueryCase(
        query="제네시스 범퍼 신공장 MES 경합 제안",
        relevant_sources={"2025.07.28 에코플라스틱 현장답사.docx"},
    ),

    # 2026.01.08 에코플라스틱_서진산업MES도입_회의록.docx
    # → SCADA 연계, 설비 예지보전, 재고관리 바코드
    QueryCase(
        query="서진산업 SCADA 설비 데이터 연계",
        relevant_sources={"2026.01.08 에코플라스틱_서진산업MES도입_회의록.docx"},
    ),
    QueryCase(
        query="설비 예지보전 도입 비용 검토",
        relevant_sources={"2026.01.08 에코플라스틱_서진산업MES도입_회의록.docx"},
    ),

    # 2026.02.04 에코플라스틱 자동화설비(로딩,언로딩 로봇) 회의.docx
    # → 로딩/언로딩 로봇, 컨베이어, 도장 대차 RFID
    QueryCase(
        query="로딩 언로딩 로봇 컨베이어 도장 공정",
        relevant_sources={"2026.02.04 에코플라스틱 자동화설비(로딩,언로딩 로봇) 회의.docx"},
    ),
    QueryCase(
        query="RFID 도장 대차 위치 확인",
        relevant_sources={"2026.02.04 에코플라스틱 자동화설비(로딩,언로딩 로봇) 회의.docx"},
    ),

    # 2026.02.26 에코플라스틱 자동화설비(AMR) 회의록.docx
    # → AMR 팔레트 이송, 바코드 스캔, 불량품 처리
    QueryCase(
        query="AMR 팔레트 이송 사출품 적재",
        relevant_sources={"2026.02.26 에코플라스틱 자동화설비(AMR) 회의록.docx"},
    ),
    QueryCase(
        query="바코드 스캔 불량품 팔레트 분류",
        relevant_sources={"2026.02.26 에코플라스틱 자동화설비(AMR) 회의록.docx"},
    ),
]

# ---------------------------------------------------------------------------
# Session-scoped fixture: data/ 폴더를 한 번만 인덱싱
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).parent.parent / "data"


@pytest.fixture(scope="session")
def quality_pilot(tmp_path_factory, embed_fn):
    if not DATA_DIR.is_dir():
        pytest.skip("data/ 폴더 없음 — ground truth 평가 불가")

    from docpilot import DocPilot

    db_path = tmp_path_factory.mktemp("quality") / "quality.db"
    pilot = DocPilot(
        api_key="sk-test",
        database_url=f"sqlite:///{db_path}",
        embed_fn=embed_fn,
    )
    pilot.index(DATA_DIR)
    return pilot


# ---------------------------------------------------------------------------
# 품질 임계값 테스트
# ---------------------------------------------------------------------------

@pytest.mark.slow
class TestSearchQuality:
    """하이브리드 검색 베이스라인 지표 검증."""

    @pytest.fixture(autouse=True)
    def _report(self, quality_pilot):
        from docpilot.search.hybrid import hybrid

        def search_fn(query: str):
            return hybrid(query, embed_fn=quality_pilot._embed_fn, top_k=10)

        self.report: EvalReport = evaluate(EVAL_CASES, search_fn, ks=[1, 3, 5])
        print(f"\n{self.report}")  # pytest -s 시 출력

    def test_mrr(self):
        """MRR >= 0.85: 8개 쿼리 중 7개가 top-1 명중 수준 (실측 0.938)."""
        assert self.report.mrr >= 0.85, f"MRR={self.report.mrr:.3f} < 0.85"

    def test_recall_at_3(self):
        """R@3 >= 0.95: top-3 청크 안에 관련 문서가 거의 항상 포함 (실측 1.000)."""
        assert self.report.recall[3] >= 0.95, f"R@3={self.report.recall[3]:.3f} < 0.95"

    def test_recall_at_5(self):
        """R@5 >= 0.95: top-5 내 전수 recall (실측 1.000)."""
        assert self.report.recall[5] >= 0.95, f"R@5={self.report.recall[5]:.3f} < 0.95"

    def test_precision_at_1(self):
        """P@1 >= 0.75: top-1 결과가 관련 문서일 확률 (실측 0.875)."""
        assert self.report.precision[1] >= 0.75, f"P@1={self.report.precision[1]:.3f} < 0.75"


# ---------------------------------------------------------------------------
# eval 유틸 단위 테스트 (모델 불필요, 항상 실행)
# ---------------------------------------------------------------------------

class TestEvalFunctions:
    def _results(self, sources: list[str]):
        from docpilot.search.models import SearchResult
        return [
            SearchResult(chunk_id=i, document_id=i, source=f"/data/{s}",
                         content="내용", score=1.0 / (i + 1))
            for i, s in enumerate(sources)
        ]

    def test_precision_at_k_full_hit(self):
        from docpilot.search.eval import precision_at_k
        results = self._results(["a.txt", "b.txt", "c.txt"])
        assert precision_at_k(results, {"a.txt"}, k=1) == pytest.approx(1.0)

    def test_precision_at_k_miss(self):
        from docpilot.search.eval import precision_at_k
        results = self._results(["a.txt", "b.txt"])
        assert precision_at_k(results, {"c.txt"}, k=2) == pytest.approx(0.0)

    def test_precision_at_k_dedup(self):
        from docpilot.search.eval import precision_at_k
        # 같은 문서의 청크가 2개 → 1개로 카운트
        results = self._results(["a.txt", "a.txt", "b.txt"])
        assert precision_at_k(results, {"a.txt"}, k=3) == pytest.approx(1 / 3)

    def test_recall_at_k(self):
        from docpilot.search.eval import recall_at_k
        results = self._results(["a.txt", "b.txt", "c.txt"])
        assert recall_at_k(results, {"a.txt", "b.txt"}, k=2) == pytest.approx(1.0)

    def test_recall_partial(self):
        from docpilot.search.eval import recall_at_k
        results = self._results(["a.txt", "b.txt", "c.txt"])
        assert recall_at_k(results, {"a.txt", "d.txt"}, k=3) == pytest.approx(0.5)

    def test_mrr_first_hit(self):
        from docpilot.search.eval import mrr
        results = self._results(["x.txt", "a.txt", "b.txt"])
        assert mrr(results, {"a.txt"}) == pytest.approx(0.5)

    def test_mrr_no_hit(self):
        from docpilot.search.eval import mrr
        results = self._results(["a.txt", "b.txt"])
        assert mrr(results, {"z.txt"}) == pytest.approx(0.0)

    def test_evaluate_report_structure(self):
        from docpilot.search.eval import evaluate
        results = self._results(["a.txt", "b.txt"])
        cases = [QueryCase("쿼리1", {"a.txt"}), QueryCase("쿼리2", {"b.txt"})]
        report = evaluate(cases, search_fn=lambda q: results, ks=[1, 3])
        assert set(report.precision.keys()) == {1, 3}
        assert set(report.recall.keys()) == {1, 3}
        assert report.n_queries == 2
        assert 0.0 <= report.mrr <= 1.0
