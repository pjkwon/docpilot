"""
MCP 서버 통합 테스트 — describe_template / fill_template 흐름.
generate_template 관련 테스트만 실제 LLM 호출을 포함합니다 (ANTHROPIC_API_KEY 필요).

실행 방법:
    pytest tests/test_mcp_server.py -v                                     # describe/fill (LLM 불필요)
    ANTHROPIC_API_KEY=sk-ant-... pytest tests/test_mcp_server.py -v -s     # generate_template 포함 전체
"""
from __future__ import annotations

import json
import re
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
    """placeholder 없는 기존 보고서 HWPX (generate_template 샘플용)"""
    return _make_hwpx(samples_folder / "reference_report.hwpx", _REFERENCE_HML)


@pytest.fixture()
def mcp_pilot(tmp_path: Path, monkeypatch):
    """generate_template처럼 _get_pilot()을 쓰는 도구용 — 각 테스트마다 격리된 DB로 _pilot을 교체."""
    from docpilot import DocPilot
    pilot = DocPilot(database_url=f"sqlite:///{tmp_path / 'mcp_test.db'}")
    monkeypatch.setattr("docpilot.mcp_server._pilot", pilot)
    return pilot


# ---------------------------------------------------------------------------
# TC-01: describe_template — 템플릿 구조 확인 (LLM/RAG 불필요)
# ---------------------------------------------------------------------------

def test_tc01a_describe_builtin_template():
    """describe_template('report')가 섹션 목록과 fill_template용 example dict를 반환해야 합니다."""
    from docpilot.mcp_server import describe_template

    result = describe_template("report")

    assert "[섹션 목록]" in result
    assert "[fill_template()의 sections 인자에 그대로 채워 넣을 예시]" in result


def test_tc01b_describe_placeholder_template(placeholder_template):
    """{{개요}} 등 실제 placeholder 이름이 섹션 키로 정확히 노출되어야 합니다."""
    from docpilot.mcp_server import describe_template

    result = describe_template(str(placeholder_template))

    for name in ("개요", "주요성과", "향후계획"):
        assert f'"{name}"' in result


# ---------------------------------------------------------------------------
# TC-02: fill_template — 작성된 섹션 내용을 기계적으로 채우기 (LLM/RAG 불필요)
# ---------------------------------------------------------------------------

def test_tc02a_fill_placeholder_template(placeholder_template, tmp_path):
    """{{placeholder}} 있는 HWPX 템플릿 → sections dict로 치환, 남는 placeholder 없어야 함."""
    from docpilot.mcp_server import fill_template

    output = tmp_path / "output" / "report_placeholder.hwpx"
    output.parent.mkdir()

    result = fill_template(
        template=str(placeholder_template),
        sections={"개요": "본 보고서는 4분기 현황을 정리한 것입니다.", "주요성과": "신규 고객 확보", "향후계획": "채널 확대"},
        output=str(output),
    )

    assert output.exists()
    assert "문서 생성 완료" in result

    with zipfile.ZipFile(output) as zf:
        names = zf.namelist()
        hml_name = next(n for n in names if n.endswith(".hml"))
        content = zf.read(hml_name).decode("utf-8")
    assert "{{" not in content, "placeholder가 치환되지 않고 남아있습니다"


def test_tc02b_fill_template_missing_required_key(placeholder_template, tmp_path):
    """필수 섹션 키가 빠지면 문서를 만들지 않고 오류를 반환해야 합니다."""
    from docpilot.mcp_server import fill_template

    output = tmp_path / "output" / "should_not_exist.hwpx"

    result = fill_template(
        template=str(placeholder_template),
        sections={"개요": "내용"},  # 주요성과, 향후계획 누락
        output=str(output),
    )

    assert "문서 생성 실패" in result
    assert not output.exists()


def test_tc02c_fill_template_unknown_key(placeholder_template, tmp_path):
    """템플릿에 없는 키(오탈자)가 섞여 있으면 오류를 반환해야 합니다."""
    from docpilot.mcp_server import fill_template

    output = tmp_path / "output" / "should_not_exist.hwpx"

    result = fill_template(
        template=str(placeholder_template),
        sections={"개요": "내용", "주요성과": "내용", "향후계획": "내용", "오탈자섹션": "내용"},
        output=str(output),
    )

    assert "문서 생성 실패" in result
    assert not output.exists()


# ---------------------------------------------------------------------------
# TC-03: 템플릿 자동 생성 (generate_template) → describe/fill로 재사용
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
def test_tc03b_generated_template_reusable(reference_template, samples_folder, tmp_path, mcp_pilot):
    """generate_template으로 만든 템플릿을 describe_template → fill_template로 재사용할 수 있어야 합니다."""
    from docpilot.mcp_server import describe_template, fill_template, generate_template

    sample2 = _make_hwpx(samples_folder / "reference_report2.hwpx", _REFERENCE_HML)
    out_template = tmp_path / "templates" / "auto_generated.hwpx"
    out_template.parent.mkdir()
    generate_template(
        samples=[str(reference_template), str(sample2)],
        output=str(out_template),
    )

    desc = describe_template(str(out_template))
    match = re.search(r"\[fill_template.*?\]\n(\{.*\})", desc, re.S)
    assert match, "describe_template 출력에 example dict가 포함되어야 합니다"
    example = json.loads(match.group(1))

    output = tmp_path / "output" / "reused.hwpx"
    output.parent.mkdir()
    result = fill_template(template=str(out_template), sections=example, output=str(output))

    assert output.exists()
    assert "문서 생성 완료" in result


# ---------------------------------------------------------------------------
# TC-04: 출력 파일 식별성 — 같은 템플릿·섹션, 다른 output 경로 (LLM/RAG 불필요)
# ---------------------------------------------------------------------------

def test_tc04_output_files_distinct(placeholder_template, tmp_path):
    """다른 output 경로로 두 번 호출하면 두 파일 모두 존재하고 서로 독립적이어야 합니다."""
    from docpilot.mcp_server import fill_template

    out_dir = tmp_path / "output"
    out_dir.mkdir()
    output_a = out_dir / "report_A.hwpx"
    output_b = out_dir / "report_B.hwpx"
    sections = {"개요": "개요 내용", "주요성과": "성과 내용", "향후계획": "계획 내용"}

    fill_template(template=str(placeholder_template), sections=sections, output=str(output_a))
    fill_template(template=str(placeholder_template), sections=sections, output=str(output_b))

    assert output_a.exists() and output_b.exists(), "두 파일 모두 존재해야 합니다"
    assert output_a.resolve() != output_b.resolve(), "경로가 달라야 합니다"


# ---------------------------------------------------------------------------
# TC-05: index 도구 — 파일 변경 시 자동 재인덱싱 (RAG 인덱싱은 라이브러리 레벨 기능, LLM 불필요)
# ---------------------------------------------------------------------------

def test_tc05_index_auto_reindex_on_change(tmp_path):
    """파일 내용 변경 시 index() 재호출로 자동 재인덱싱되어야 합니다."""
    from docpilot.db import indexer
    from docpilot.db.schema import Document
    from docpilot.db import client

    data_folder = tmp_path / "data"
    data_folder.mkdir()
    txt = data_folder / "사업계획.txt"
    txt.write_text("2026년 사업 계획서\n\n목표: 신규 고객 500사 확보", encoding="utf-8")
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
