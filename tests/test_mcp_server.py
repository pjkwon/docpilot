"""
MCP 서버 통합 테스트 — 실제 LLM 호출 포함
ANTHROPIC_API_KEY 환경변수가 설정된 경우에만 실행됩니다.

실행 방법:
    ANTHROPIC_API_KEY=sk-ant-... pytest tests/test_mcp_server.py -v -s
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from tests.conftest import requires_llm


# ---------------------------------------------------------------------------
# HWPX 픽스처 헬퍼
# ---------------------------------------------------------------------------

_PLACEHOLDER_HML = """<?xml version="1.0" encoding="UTF-8"?>
<hml xmlns:hp="http://www.hancom.co.kr/hwpml/2012/paragraph"
     xmlns:hc="http://www.hancom.co.kr/hwpml/2012/core">
  <hp:body><hp:sec>
    <hp:p><hp:t>사업 현황 보고서</hp:t></hp:p>
    <hp:p><hp:t>1. 개요</hp:t></hp:p>
    <hp:p><hp:t>{{개요}}</hp:t></hp:p>
    <hp:p><hp:t>2. 주요 성과</hp:t></hp:p>
    <hp:p><hp:t>{{주요성과}}</hp:t></hp:p>
    <hp:p><hp:t>3. 향후 계획</hp:t></hp:p>
    <hp:p><hp:t>{{향후계획}}</hp:t></hp:p>
  </hp:sec></hp:body>
</hml>""".encode("utf-8")

_REFERENCE_HML = """<?xml version="1.0" encoding="UTF-8"?>
<hml xmlns:hp="http://www.hancom.co.kr/hwpml/2012/paragraph"
     xmlns:hc="http://www.hancom.co.kr/hwpml/2012/core">
  <hp:body><hp:sec>
    <hp:p><hp:t>2025년 4분기 사업 현황 보고서</hp:t></hp:p>
    <hp:p><hp:t>1. 개요</hp:t></hp:p>
    <hp:p><hp:t>본 보고서는 4분기 주요 사업 현황을 정리한 것입니다.</hp:t></hp:p>
    <hp:p><hp:t>2. 주요 성과</hp:t></hp:p>
    <hp:p><hp:t>신규 고객 120사 확보, 매출 목표 110% 달성.</hp:t></hp:p>
    <hp:p><hp:t>3. 향후 계획</hp:t></hp:p>
    <hp:p><hp:t>1분기 파트너 채널 확대 및 SaaS 전환 가속화 추진.</hp:t></hp:p>
  </hp:sec></hp:body>
</hml>""".encode("utf-8")


def _make_hwpx(path: Path, hml: bytes) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/hwp+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("Contents/content.hml", hml)
        zf.writestr("META-INF/container.xml", b"<container/>")
    return path


# ---------------------------------------------------------------------------
# 공통 픽스처
# ---------------------------------------------------------------------------

@pytest.fixture()
def data_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "data"
    folder.mkdir()
    (folder / "사업계획.txt").write_text(
        "2026년 사업 계획서\n\n"
        "목표: 신규 고객 500사 확보, 매출 50억 달성\n\n"
        "전략 1: 클라우드 SaaS 전환\n"
        "기존 온프레미스 제품을 SaaS로 전환하여 초기 도입 장벽을 낮춘다.\n\n"
        "전략 2: 파트너 채널 확대\n"
        "국내 SI 파트너 20사와 리셀러 계약을 체결한다.\n\n"
        "예산: 개발 20억, 마케팅 10억, 운영 5억",
        encoding="utf-8",
    )
    (folder / "시장분석.txt").write_text(
        "국내 문서 자동화 시장 분석\n\n"
        "시장 규모: 2026년 기준 약 3,000억 원\n"
        "주요 경쟁사: A사 (점유율 35%), B사 (점유율 20%)\n\n"
        "기회 요인: 공공기관 디지털 전환 수요 급증\n"
        "위협 요인: 글로벌 AI 문서 도구 국내 진출",
        encoding="utf-8",
    )
    return folder


@pytest.fixture()
def samples_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "samples"
    folder.mkdir()
    return folder


@pytest.fixture()
def placeholder_template(samples_folder: Path) -> Path:
    """{{개요}}, {{주요성과}}, {{향후계획}} placeholder 있는 HWPX"""
    return _make_hwpx(samples_folder / "template_with_placeholder.hwpx", _PLACEHOLDER_HML)


@pytest.fixture()
def reference_template(samples_folder: Path) -> Path:
    """placeholder 없는 기존 보고서 HWPX (Reference Mode용)"""
    return _make_hwpx(samples_folder / "reference_report.hwpx", _REFERENCE_HML)


@pytest.fixture()
def mcp_pilot(tmp_path: Path, monkeypatch):
    """각 테스트마다 격리된 DB로 _pilot을 교체."""
    from docpilot import DocPilot
    pilot = DocPilot(database_url=f"sqlite:///{tmp_path / 'mcp_test.db'}")
    monkeypatch.setattr("docpilot.mcp_server._pilot", pilot)
    return pilot


# ---------------------------------------------------------------------------
# TC-01: 내장 템플릿으로 보고서 생성
# ---------------------------------------------------------------------------

@requires_llm
def test_tc01_generate_builtin_template(data_folder, tmp_path, mcp_pilot):
    """data_folder + 내장 'report' 템플릿 → HWPX 파일 생성 확인."""
    from docpilot.mcp_server import generate

    output = tmp_path / "output" / "report.hwpx"
    output.parent.mkdir()

    result = generate(
        data_folder=str(data_folder),
        template="report",
        output=str(output),
    )

    assert output.exists(), "출력 파일이 생성되어야 합니다"
    assert output.stat().st_size > 0, "빈 파일이 아니어야 합니다"
    assert "문서 생성 완료" in result


# ---------------------------------------------------------------------------
# TC-02a: Placeholder 있는 HWPX 템플릿으로 보고서 생성
# ---------------------------------------------------------------------------

@requires_llm
def test_tc02a_generate_placeholder_template(data_folder, placeholder_template, tmp_path, mcp_pilot):
    """{{placeholder}} 있는 HWPX 템플릿 → 섹션이 채워진 보고서 생성."""
    from docpilot.mcp_server import generate

    output = tmp_path / "output" / "report_placeholder.hwpx"
    output.parent.mkdir()

    result = generate(
        data_folder=str(data_folder),
        template=str(placeholder_template),
        output=str(output),
    )

    assert output.exists()
    assert "문서 생성 완료" in result

    # 출력 HWPX에 placeholder 문자열이 남아있지 않아야 함
    with zipfile.ZipFile(output) as zf:
        names = zf.namelist()
        hml_name = next(n for n in names if n.endswith(".hml"))
        content = zf.read(hml_name).decode("utf-8")
    assert "{{" not in content, "placeholder가 치환되지 않고 남아있습니다"


# ---------------------------------------------------------------------------
# TC-02b: Placeholder 없는 HWPX — Reference Mode
# ---------------------------------------------------------------------------

@requires_llm
def test_tc02b_generate_reference_mode(data_folder, reference_template, tmp_path, mcp_pilot):
    """placeholder 없는 기존 보고서 → Reference Mode로 구조 분석 후 새 보고서 생성."""
    from docpilot.mcp_server import generate

    output = tmp_path / "output" / "report_reference.hwpx"
    output.parent.mkdir()

    result = generate(
        data_folder=str(data_folder),
        template=str(reference_template),
        output=str(output),
    )

    assert output.exists()
    assert "문서 생성 완료" in result
    # Reference Mode는 원본 파일과 다른 내용으로 채워져야 함
    assert output.stat().st_size != reference_template.stat().st_size


# ---------------------------------------------------------------------------
# TC-03: 템플릿 자동 생성 (generate_template) → DB 등록 → 재사용
# ---------------------------------------------------------------------------

@requires_llm
def test_tc03a_generate_template_created(reference_template, samples_folder, tmp_path, mcp_pilot):
    """generate_template 호출 시 템플릿 파일이 생성되어야 합니다."""
    from docpilot.mcp_server import generate_template

    # 샘플 2개 이상 권장 → 같은 파일을 두 개 준비
    sample2 = _make_hwpx(samples_folder / "reference_report2.hwpx", _REFERENCE_HML)
    out_template = tmp_path / "templates" / "auto_generated.hwpx"
    out_template.parent.mkdir()

    result = generate_template(
        samples=[str(reference_template), str(sample2)],
        output=str(out_template),
    )

    assert out_template.exists(), "템플릿 파일이 생성되어야 합니다"
    assert "템플릿 생성 완료" in result


@requires_llm
def test_tc03b_generated_template_reusable(data_folder, reference_template, samples_folder, tmp_path, mcp_pilot):
    """generate_template으로 만든 템플릿을 generate에 바로 재사용할 수 있어야 합니다."""
    from docpilot.mcp_server import generate, generate_template

    sample2 = _make_hwpx(samples_folder / "reference_report2.hwpx", _REFERENCE_HML)
    out_template = tmp_path / "templates" / "auto_generated.hwpx"
    out_template.parent.mkdir()
    generate_template(
        samples=[str(reference_template), str(sample2)],
        output=str(out_template),
    )

    output = tmp_path / "output" / "reused.hwpx"
    output.parent.mkdir()
    result = generate(
        data_folder=str(data_folder),
        template=str(out_template),
        output=str(output),
    )

    assert output.exists()
    assert "문서 생성 완료" in result


# ---------------------------------------------------------------------------
# TC-04: 출력 파일 식별성 — 다른 경로로 두 번 생성
# ---------------------------------------------------------------------------

@requires_llm
def test_tc04_output_files_distinct(data_folder, tmp_path, mcp_pilot):
    """같은 데이터·템플릿, 다른 output 경로 → 두 파일 모두 존재하고 서로 독립적이어야 합니다."""
    from docpilot.mcp_server import generate

    out_dir = tmp_path / "output"
    out_dir.mkdir()
    output_a = out_dir / "report_A.hwpx"
    output_b = out_dir / "report_B.hwpx"

    generate(data_folder=str(data_folder), template="report", output=str(output_a))
    generate(data_folder=str(data_folder), template="report", output=str(output_b))

    assert output_a.exists() and output_b.exists(), "두 파일 모두 존재해야 합니다"
    assert output_a.resolve() != output_b.resolve(), "경로가 달라야 합니다"


# ---------------------------------------------------------------------------
# TC-05: data 폴더 내 특정 .hwpx 파일을 template으로 직접 지정
# ---------------------------------------------------------------------------

@requires_llm
def test_tc05_data_file_as_template(data_folder, tmp_path, mcp_pilot):
    """data 폴더 안의 특정 .hwpx 파일을 template으로 지정해 보고서를 생성합니다."""
    from docpilot.mcp_server import generate

    # data 폴더에 양식 파일 추가
    ref_in_data = _make_hwpx(data_folder / "양식.hwpx", _REFERENCE_HML)

    output = tmp_path / "output" / "from_data_template.hwpx"
    output.parent.mkdir()

    result = generate(
        data_folder=str(data_folder),
        template=str(ref_in_data),
        output=str(output),
    )

    assert output.exists()
    assert "문서 생성 완료" in result


# ---------------------------------------------------------------------------
# TC-06: index 도구 — 파일 변경 시 자동 재인덱싱
# ---------------------------------------------------------------------------

def test_tc06_index_auto_reindex_on_change(data_folder, tmp_path, mcp_pilot):
    """파일 내용 변경 시 index() 재호출로 자동 재인덱싱되어야 합니다. (LLM 불필요)"""
    from docpilot.db import indexer
    from docpilot.db.schema import Document
    from docpilot.db import client

    txt = data_folder / "사업계획.txt"
    original_hash = indexer._compute_hash(txt)

    # 1차 인덱싱
    ids_first = indexer.index_folder(str(data_folder))
    with client.session() as db:
        doc = db.query(Document).filter(Document.source == str(txt)).first()
        assert doc is not None
        assert doc.file_hash == original_hash

    # 파일 수정
    txt.write_text(txt.read_text(encoding="utf-8") + "\n\n추가 내용: 전략 3 신규 추가.", encoding="utf-8")
    new_hash = indexer._compute_hash(txt)
    assert new_hash != original_hash

    # 2차 인덱싱 — 변경 감지 → 자동 재인덱싱
    indexer.index_folder(str(data_folder))
    with client.session() as db:
        doc = db.query(Document).filter(Document.source == str(txt)).first()
        assert doc.file_hash == new_hash, "변경된 파일의 해시가 DB에 갱신되어야 합니다"
