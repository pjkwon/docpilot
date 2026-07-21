from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from docpilot.exceptions import DocPilotError, IngestionError, MappingError
from docpilot.ingestion import ingest_paths
from docpilot.ingestion.models import IngestedDocument
from tests.mocks.llm_mock import MockMapper


@pytest.fixture()
def mock_pilot(pilot):
    """pilot 픽스처의 실제 LLM 매퍼를 MockMapper로 교체 — generate_from_content가
    RAG 없이 self._mapper.map()을 직접 호출하는 경로를 API 키 없이 검증할 수 있다."""
    mock = MockMapper()
    pilot._mapper = mock
    return pilot


@pytest.fixture()
def text_files(tmp_path: Path) -> list[Path]:
    folder = tmp_path / "src"
    folder.mkdir()
    a = folder / "a.txt"
    b = folder / "b.txt"
    a.write_text("A 파일 내용", encoding="utf-8")
    b.write_text("B 파일 내용", encoding="utf-8")
    return [a, b]


# ---------------------------------------------------------------------------
# docpilot.ingestion.ingest_paths()
# ---------------------------------------------------------------------------

class TestIngestPaths:
    def test_ingests_each_file(self, text_files):
        docs = ingest_paths(text_files)

        assert len(docs) == 2
        assert all(isinstance(d, IngestedDocument) for d in docs)
        assert docs[0].content == "A 파일 내용"
        assert docs[1].content == "B 파일 내용"

    def test_empty_list_returns_empty(self):
        assert ingest_paths([]) == []

    def test_unsupported_extension_raises(self, tmp_path: Path):
        bad = tmp_path / "data.xlsx"
        bad.write_bytes(b"not a real xlsx")

        with pytest.raises(IngestionError):
            ingest_paths([bad])

    def test_does_not_touch_db(self, text_files, monkeypatch):
        """index_folder()와 달리 DB 세션을 열지 않아야 한다."""
        from docpilot.db import client

        def _boom(*a, **k):
            raise AssertionError("DB session opened")
        monkeypatch.setattr(client, "session", _boom)

        docs = ingest_paths(text_files)
        assert len(docs) == 2


# ---------------------------------------------------------------------------
# DocPilot.generate_from_content() — content 입력 형태 3종
# ---------------------------------------------------------------------------

class TestGenerateFromContentInputForms:
    def test_string_content(self, mock_pilot, hwpx_template: Path, tmp_path: Path):
        output = tmp_path / "out.hwpx"
        result = mock_pilot.generate_from_content(
            content="원본 텍스트 그대로",
            template=str(hwpx_template),
            output=str(output),
        )

        assert output.exists()
        assert result.path == output
        called_content, _sections = mock_pilot._mapper.calls[0]
        assert called_content == "원본 텍스트 그대로"

    def test_path_list_content(self, mock_pilot, hwpx_template: Path, text_files, tmp_path: Path):
        output = tmp_path / "out.hwpx"
        mock_pilot.generate_from_content(
            content=text_files,
            template=str(hwpx_template),
            output=str(output),
        )

        called_content, _sections = mock_pilot._mapper.calls[0]
        assert "A 파일 내용" in called_content
        assert "B 파일 내용" in called_content
        assert "[출처: a.txt]" in called_content

    def test_ingested_document_list_content(self, mock_pilot, hwpx_template: Path, tmp_path: Path):
        docs = [
            IngestedDocument(source=Path("x.txt"), content="X 내용", mime_type="text/plain"),
            IngestedDocument(source=Path("y.txt"), content="Y 내용", mime_type="text/plain"),
        ]
        output = tmp_path / "out.hwpx"
        mock_pilot.generate_from_content(
            content=docs,
            template=str(hwpx_template),
            output=str(output),
        )

        called_content, _sections = mock_pilot._mapper.calls[0]
        assert "X 내용" in called_content and "Y 내용" in called_content

    def test_empty_path_list_raises(self, mock_pilot, hwpx_template: Path, tmp_path: Path):
        with pytest.raises(DocPilotError):
            mock_pilot.generate_from_content(
                content=[],
                template=str(hwpx_template),
                output=str(tmp_path / "out.hwpx"),
            )

    def test_no_rag_search_performed(self, mock_pilot, hwpx_template: Path, tmp_path: Path, monkeypatch):
        """RagMapper._retrieve를 건드리면 실패하게 만들어 검색 경로를 안 탄다는 걸 확인."""
        def _boom(*a, **k):
            raise AssertionError("RAG retrieval must not run in generate_from_content")
        monkeypatch.setattr(mock_pilot._rag_mapper, "_retrieve", _boom)

        mock_pilot.generate_from_content(
            content="텍스트",
            template=str(hwpx_template),
            output=str(tmp_path / "out.hwpx"),
        )  # raises above if RAG path were touched


# ---------------------------------------------------------------------------
# 템플릿 요구사항 — placeholder 없는 템플릿은 미지원 (reference mode는 generate() 전용)
# ---------------------------------------------------------------------------

def _make_no_placeholder_template(tmp_path: Path) -> Path:
    no_placeholder_hml = """<?xml version="1.0" encoding="UTF-8"?>
<hml xmlns:hp="http://www.hancom.co.kr/hwpml/2012/paragraph">
  <hp:body><hp:sec>
    <hp:p><hp:t>1. 개요</hp:t></hp:p>
    <hp:p><hp:t>본 문서는 참조용 예시 문서입니다.</hp:t></hp:p>
    <hp:p><hp:t>2. 결론</hp:t></hp:p>
    <hp:p><hp:t>결론 내용입니다.</hp:t></hp:p>
  </hp:sec></hp:body>
</hml>""".encode("utf-8")
    template = tmp_path / "reference.hwpx"
    with zipfile.ZipFile(template, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/hwp+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("Contents/content.hml", no_placeholder_hml)
        zf.writestr("META-INF/container.xml", b"<container/>")
    return template


class ReferenceModeMapper(MockMapper):
    """MockMapper + 섹션-구조 추론 요청("sections"라는 이름의 단일 섹션)에는
    유효한 JSON 배열을 돌려준다 — Reference Mode 성공 경로를 API 키 없이 검증하기 위함."""

    def map(self, content, sections, instructions=None):
        if len(sections) == 1 and sections[0].name == "sections":
            self.calls.append((content, sections))
            from docpilot.mapping.base import MappingResult
            return MappingResult(
                sections={"sections": '["개요", "결론"]'},
                model=self.model,
                input_tokens=10,
                output_tokens=10,
                elapsed_seconds=0.0,
            )
        return super().map(content, sections, instructions)


class TestReferenceMode:
    def test_llm_inference_failure_raises(self, mock_pilot, tmp_path: Path):
        """MockMapper는 구조 추론 요청에 유효한 JSON을 못 주므로 추론 실패로 에러가 나야 한다."""
        template = _make_no_placeholder_template(tmp_path)

        with pytest.raises(DocPilotError, match="LLM could not infer sections"):
            mock_pilot.generate_from_content(
                content="아무 내용",
                template=str(template),
                output=str(tmp_path / "out.hwpx"),
            )

    def test_successful_reference_mode_builds_document(self, pilot, tmp_path: Path):
        """구조 추론이 성공하면 추론된 섹션으로 문서가 생성되어야 한다 (LLM 호출 2회: 구조 추론 + 콘텐츠 매핑)."""
        mapper = ReferenceModeMapper()
        pilot._mapper = mapper
        template = _make_no_placeholder_template(tmp_path)
        output = tmp_path / "out.hwpx"

        result = pilot.generate_from_content(
            content="회의에서 논의된 내용을 정리한 원본 텍스트",
            template=str(template),
            output=str(output),
        )

        assert output.exists()
        assert result.path == output
        # 1번째 호출: 구조 추론("sections" 단일 섹션), 2번째 호출: 실제 콘텐츠 매핑(개요/결론)
        assert len(mapper.calls) == 2
        _, inferred_sections = mapper.calls[1]
        assert {s.name for s in inferred_sections} == {"개요", "결론"}

    def test_unreadable_reference_content_raises(self, mock_pilot, tmp_path: Path):
        """참조 문서에서 읽을 텍스트 자체가 없으면(빈 파일 등) 추론 이전에 바로 에러가 나야 한다."""
        empty_template = tmp_path / "empty.hwpx"
        with zipfile.ZipFile(empty_template, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("mimetype", "application/hwp+zip", compress_type=zipfile.ZIP_STORED)
            zf.writestr("Contents/content.hml", b'<?xml version="1.0"?><hml/>')
            zf.writestr("META-INF/container.xml", b"<container/>")

        with pytest.raises(DocPilotError, match="could not read template content"):
            mock_pilot.generate_from_content(
                content="아무 내용",
                template=str(empty_template),
                output=str(tmp_path / "out.hwpx"),
            )


def test_describe_template_still_raises_without_mapper(hwpx_template: Path, tmp_path: Path):
    """describe_template()/fill_template()은 mapper를 안 넘기므로 Reference Mode 없이
    지금처럼 placeholder 없는 템플릿을 즉시 거부해야 한다 (LLM-free 계약 유지)."""
    from docpilot import describe_template

    template = _make_no_placeholder_template(tmp_path)
    with pytest.raises(DocPilotError, match=r"\{\{placeholder\}\}"):
        describe_template(str(template))


# ---------------------------------------------------------------------------
# 크기 제한 가드
# ---------------------------------------------------------------------------

class TestSizeGuard:
    def test_within_default_threshold_no_warning(self, mock_pilot, hwpx_template: Path, tmp_path: Path, recwarn):
        # HWPX 검증 경고(테스트용 최소 스키마 — content.hpf/header.xml 없음)는 이 가드와 무관하므로 제외.
        mock_pilot.generate_from_content(
            content="짧은 내용",
            template=str(hwpx_template),
            output=str(tmp_path / "out.hwpx"),
        )
        size_warnings = [w for w in recwarn.list if "예상 입력 토큰" in str(w.message)]
        assert size_warnings == []

    def test_exceeds_default_threshold_warns_but_succeeds(self, mock_pilot, hwpx_template: Path, tmp_path: Path):
        # 기본 경고 기준(5만 토큰) ≈ 125,000바이트(0.4 tokens/byte) 이상
        big_content = "가" * 200_000
        output = tmp_path / "out.hwpx"

        with pytest.warns(UserWarning, match="예상 입력 토큰"):
            result = mock_pilot.generate_from_content(
                content=big_content,
                template=str(hwpx_template),
                output=str(output),
            )
        assert output.exists()
        assert result.path == output

    def test_exceeds_explicit_max_raises(self, mock_pilot, hwpx_template: Path, tmp_path: Path):
        with pytest.raises(MappingError):
            mock_pilot.generate_from_content(
                content="가" * 10_000,
                template=str(hwpx_template),
                output=str(tmp_path / "out.hwpx"),
                max_input_tokens=100,
            )

    def test_within_explicit_max_succeeds(self, mock_pilot, hwpx_template: Path, tmp_path: Path):
        output = tmp_path / "out.hwpx"
        mock_pilot.generate_from_content(
            content="짧은 내용",
            template=str(hwpx_template),
            output=str(output),
            max_input_tokens=1000,
        )
        assert output.exists()


# ---------------------------------------------------------------------------
# estimate_cost()/benchmark()(RAG 버전)도 이제 reference mode를 지원해야 한다
# (generate()와의 마지막 비대칭 해소)
# ---------------------------------------------------------------------------

def test_estimate_cost_supports_reference_mode(tmp_path: Path):
    from docpilot import DocPilot
    p = DocPilot(api_key="sk-test", database_url=f"sqlite:///{tmp_path / 'test.db'}")
    p._mapper = ReferenceModeMapper()
    template = _make_no_placeholder_template(tmp_path)
    data_folder = tmp_path / "data"
    data_folder.mkdir()

    report = p.estimate_cost(data_folder=str(data_folder), template=str(template), quick=True)
    assert "섹션 수" in report and "2개" in report


def test_benchmark_supports_reference_mode(tmp_path: Path):
    from docpilot import DocPilot
    p = DocPilot(api_key="sk-test", database_url=f"sqlite:///{tmp_path / 'test.db'}")
    mapper = ReferenceModeMapper()
    p._mapper = mapper
    template = _make_no_placeholder_template(tmp_path)
    data_folder = tmp_path / "data"
    data_folder.mkdir()

    report = p.benchmark(
        data_folder=str(data_folder),
        template=str(template),
        output=str(tmp_path / "out.hwpx"),
        mappers={"mock": mapper},
    )
    assert "mock" in report


# ---------------------------------------------------------------------------
# DocPilot.estimate_cost_from_content() — RAG 없이 비용 추정
# ---------------------------------------------------------------------------

class TestEstimateCostFromContent:
    def test_quick_uses_byte_heuristic_no_api_call(self, mock_pilot, hwpx_template: Path):
        """quick=True는 count_tokens()를 안 쓰므로 MockMapper(count_tokens 없음)로도 동작해야 한다."""
        report = mock_pilot.estimate_cost_from_content(
            content="비용 추정 대상 텍스트",
            template=str(hwpx_template),
            quick=True,
        )
        assert "빠른 추정" in report
        assert "RAG 없음" in report or "RAG" in report

    def test_non_quick_without_count_tokens_falls_back(self, mock_pilot, hwpx_template: Path):
        """quick=False인데 매퍼에 count_tokens가 없으면(MockMapper) 대체 메시지를 반환해야 한다."""
        report = mock_pilot.estimate_cost_from_content(
            content="비용 추정 대상 텍스트",
            template=str(hwpx_template),
            quick=False,
        )
        assert "Claude 매퍼에서만 지원됩니다" in report

    def test_no_rag_indexing_performed(self, mock_pilot, hwpx_template: Path, monkeypatch):
        from docpilot.db import indexer

        def _boom(*a, **k):
            raise AssertionError("indexing must not run in estimate_cost_from_content")
        monkeypatch.setattr(indexer, "index_folder", _boom)

        mock_pilot.estimate_cost_from_content(
            content="텍스트",
            template=str(hwpx_template),
            quick=True,
        )

    def test_supports_reference_mode(self, tmp_path: Path):
        """describe_template()과 달리 mapper가 있으므로 placeholder 없는 템플릿도 추정 가능해야 한다."""
        from docpilot import DocPilot
        p = DocPilot(api_key="sk-test", database_url=f"sqlite:///{tmp_path / 'test.db'}")
        p._mapper = ReferenceModeMapper()
        template = _make_no_placeholder_template(tmp_path)

        report = p.estimate_cost_from_content(
            content="아무 내용",
            template=str(template),
            quick=True,
        )
        assert "섹션 수" in report and "2개" in report  # ReferenceModeMapper가 추론하는 "개요", "결론"


# ---------------------------------------------------------------------------
# DocPilot.benchmark_from_content() — RAG 없이 여러 매퍼 비교
# ---------------------------------------------------------------------------

class TestBenchmarkFromContent:
    def test_runs_against_given_mapper_no_indexing(self, mock_pilot, hwpx_template: Path, tmp_path: Path, monkeypatch):
        from docpilot.db import indexer

        def _boom(*a, **k):
            raise AssertionError("indexing must not run in benchmark_from_content")
        monkeypatch.setattr(indexer, "index_folder", _boom)

        report = mock_pilot.benchmark_from_content(
            content="벤치마크 대상 텍스트",
            template=str(hwpx_template),
            output=str(tmp_path / "out.hwpx"),
            mappers={"mock": mock_pilot._mapper},
        )
        assert "mock" in report
        assert "OK" in report

    def test_size_guard_raises_before_running_mappers(self, mock_pilot, hwpx_template: Path, tmp_path: Path):
        mock = mock_pilot._mapper
        with pytest.raises(MappingError):
            mock_pilot.benchmark_from_content(
                content="가" * 10_000,
                template=str(hwpx_template),
                output=str(tmp_path / "out.hwpx"),
                mappers={"mock": mock},
                max_input_tokens=100,
            )
        assert mock.calls == []  # 가드에 걸려서 실제 매퍼 호출까지 못 가야 함
