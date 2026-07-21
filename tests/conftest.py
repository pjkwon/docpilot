from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path

import pytest

# Minimal HWPX content.hml XML with one heading and one placeholder
_HWPX_CONTENT = """<?xml version="1.0" encoding="UTF-8"?>
<hml xmlns:hp="http://www.hancom.co.kr/hwpml/2012/paragraph"
     xmlns:hc="http://www.hancom.co.kr/hwpml/2012/core">
  <hp:body>
    <hp:sec>
      <hp:p>
        <hp:pPr>
          <hp:rPr>
            <hp:sz hp:val="2000"/>
            <hp:b hp:val="true"/>
          </hp:rPr>
        </hp:pPr>
        <hp:t>서론</hp:t>
      </hp:p>
      <hp:p>
        <hp:t>{{서론}}</hp:t>
      </hp:p>
      <hp:p>
        <hp:pPr>
          <hp:rPr>
            <hp:sz hp:val="1800"/>
            <hp:b hp:val="true"/>
          </hp:rPr>
        </hp:pPr>
        <hp:t>결론</hp:t>
      </hp:p>
      <hp:p>
        <hp:t>{{결론}}</hp:t>
      </hp:p>
    </hp:sec>
  </hp:body>
</hml>""".encode("utf-8")


def _make_hwpx(path: Path, content_xml: bytes = _HWPX_CONTENT) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/hwp+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("Contents/content.hml", content_xml)
        zf.writestr("META-INF/container.xml", b"<container/>")
    return path


# Minimal but real section0.xml + header.xml pair (paraPrIDRef schema) —
# unlike _HWPX_CONTENT (content.hml, no header.xml), this exercises the
# bullet-list rendering path, which requires header.xml to attach
# hh:bullet/hh:paraPr definitions to.
_HWPX_HEADER = """<?xml version="1.0" encoding="UTF-8"?>
<hh:head xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"
         xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head"
         xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core"
         version="1.5" secCnt="1">
  <hh:refList>
    <hh:numberings itemCnt="0"/>
    <hh:paraProperties itemCnt="1">
      <hh:paraPr id="0" tabPrIDRef="0" condense="0" fontLineHeight="0" snapToGrid="1" suppressLineNumbers="0" checked="0">
        <hh:align horizontal="JUSTIFY" vertical="BASELINE"/>
        <hh:heading type="NONE" idRef="0" level="0"/>
      </hh:paraPr>
    </hh:paraProperties>
  </hh:refList>
</hh:head>""".encode("utf-8")

_HWPX_SECTION0 = """<?xml version="1.0" encoding="UTF-8"?>
<hs:sec xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"
        xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section">
  <hp:p id="1" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">
    <hp:run charPrIDRef="0"><hp:t>{{내용}}</hp:t></hp:run>
    <hp:linesegarray>
      <hp:lineseg textpos="0" vertpos="0" vertsize="1000" textheight="1000" baseline="850" spacing="600" horzpos="0" horzsize="42520" flags="393216"/>
    </hp:linesegarray>
  </hp:p>
</hs:sec>""".encode("utf-8")


def _make_hwpx_with_header(path: Path, section_xml: bytes = _HWPX_SECTION0,
                            header_xml: bytes = _HWPX_HEADER) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/hwp+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("Contents/section0.xml", section_xml)
        zf.writestr("Contents/header.xml", header_xml)
        zf.writestr("META-INF/container.xml", b"<container/>")
    return path


@pytest.fixture()
def hwpx_template_with_header(tmp_path: Path) -> Path:
    return _make_hwpx_with_header(tmp_path / "template_with_header.hwpx")


@pytest.fixture()
def sample_hwpx(tmp_path: Path) -> Path:
    return _make_hwpx(tmp_path / "sample.hwpx")


@pytest.fixture()
def sample_txt(tmp_path: Path) -> Path:
    p = tmp_path / "sample.txt"
    p.write_text("2025년 사업 계획서\n\n핵심 목표: 매출 30% 성장\n세부 계획: ...", encoding="utf-8")
    return p


@pytest.fixture()
def hwpx_template(tmp_path: Path) -> Path:
    return _make_hwpx(tmp_path / "template.hwpx")


@pytest.fixture()
def make_hwpx(tmp_path: Path):
    """Factory fixture: make_hwpx(name, xml=...) -> Path"""
    def _factory(name: str = "doc.hwpx", content_xml: bytes = _HWPX_CONTENT) -> Path:
        return _make_hwpx(tmp_path / name, content_xml)
    return _factory


# ---------------------------------------------------------------------------
# CLI 옵션
# ---------------------------------------------------------------------------

def pytest_addoption(parser):
    parser.addoption(
        "--data-dir",
        default=None,
        metavar="PATH",
        help="성능 테스트용 데이터 폴더 경로 (미지정 시 프로젝트 루트의 data/ 사용)",
    )
    parser.addoption(
        "--with-embed",
        action="store_true",
        default=False,
        help="카운팅 목업 embed_fn으로 임베딩 배치 호출 횟수도 측정",
    )
    parser.addoption(
        "--embed-latency-ms",
        type=float,
        default=50.0,
        metavar="MS",
        help="임베딩 배치 벤치마크용 API 지연 시뮬레이션 (ms, 기본값: 50)",
    )


@pytest.fixture()
def perf_data_dir(request) -> Path:
    """--data-dir CLI 인자로 지정한 경로, 없으면 프로젝트 루트 data/ 폴더."""
    custom = request.config.getoption("--data-dir")
    if custom:
        p = Path(custom)
        if not p.is_dir():
            pytest.skip(f"--data-dir 경로가 존재하지 않습니다: {p}")
        return p
    default = Path(__file__).parent.parent / "data"
    if not default.is_dir():
        pytest.skip("data/ 폴더 없음 — --data-dir PATH 로 지정하세요")
    return default


# ---------------------------------------------------------------------------
# DocPilot instance fixtures
# ---------------------------------------------------------------------------

# LLM이 필요한 테스트는 실제 키가 없으면 자동 skip
requires_llm = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)


@pytest.fixture(scope="session")
def embed_fn():
    """multilingual-e5-base 임베딩 함수 (768차원, EMBEDDING_DIM과 일치). 세션 전체에서 모델을 한 번만 로드."""
    from docpilot.search.embedding import sentence_embed_fn
    return sentence_embed_fn("intfloat/multilingual-e5-base")


@pytest.fixture()
def pilot(tmp_path: Path):
    """
    LLM 호출 없이 인덱싱·검색만 테스트할 때 사용.
    테스트마다 격리된 DB를 생성하므로 side effect 없음.
    """
    from docpilot import DocPilot
    return DocPilot(
        api_key="sk-test",  # init 검증 통과용 더미 키 — map() 호출 시엔 실제 키 필요
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
    )


@pytest.fixture()
def pilot_with_embed(tmp_path: Path, embed_fn):
    """
    임베딩 포함 인덱싱·벡터 검색 테스트용.
    embed_fn은 session-scoped라 모델 로딩 비용은 1회만 발생.
    """
    from docpilot import DocPilot
    return DocPilot(
        api_key="sk-test",
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        embed_fn=embed_fn,
    )


@pytest.fixture()
def pilot_llm(tmp_path: Path):
    """
    실제 LLM 호출이 필요한 통합 테스트용.
    ANTHROPIC_API_KEY 없으면 테스트가 자동 skip되지 않으므로,
    테스트 함수에 @requires_llm 마커를 함께 붙여서 사용.
    """
    from docpilot import DocPilot
    return DocPilot(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
    )
