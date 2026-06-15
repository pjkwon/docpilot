"""로컬 임베딩 모델 지연 시간 비교 벤치마크.

단건 / 배치(10건, 50건) 기준으로 cold start, warm 단건, 배치 처리 속도를 측정합니다.

실행:
    uv run pytest tests/test_embed_model_bench.py -s
    uv run pytest tests/test_embed_model_bench.py -s -k e5        # e5만
    uv run pytest tests/test_embed_model_bench.py -s -k bge       # bge만
    uv run pytest tests/test_embed_model_bench.py -s -k minilm    # MiniLM만
"""
from __future__ import annotations

import time
from typing import Callable

import pytest

# 벤치마크에 쓸 한국어 샘플 텍스트
_SAMPLES = [
    "2025년 사업 계획서 핵심 목표는 매출 30% 성장과 신규 고객 확보입니다.",
    "본 제안서는 AI 기반 문서 자동화 솔루션 도입에 관한 내용을 담고 있습니다.",
    "회의록: 참석자 홍길동, 김철수. 안건: 1분기 예산 조정 및 인력 배치 계획.",
    "연구 결과에 따르면 자연어 처리 기술의 정확도가 전년 대비 15% 향상되었습니다.",
    "공문 수신: 기획재정부 장관. 제목: 2026년 예산안 편성 지침 요청의 건.",
    "추진 배경: 디지털 전환 가속화에 따라 업무 효율화 필요성이 증대되고 있습니다.",
    "결론: 본 사업은 3년간 총 50억 원의 예산이 투입되며 단계적으로 추진됩니다.",
    "향후 조치 사항: 관련 부서 협의 완료 후 최종 보고서를 제출할 예정입니다.",
    "기술 사양: CPU Intel i9, RAM 64GB, SSD 2TB, GPU NVIDIA RTX 4090.",
    "본 계약은 갑과 을 사이에 체결되며 유효 기간은 계약일로부터 1년입니다.",
    "시장 분석 결과 경쟁사 대비 가격 경쟁력이 20% 우위에 있는 것으로 나타났습니다.",
    "교육 프로그램 커리큘럼: 기초 이론 4주, 실습 8주, 프로젝트 발표 2주.",
    "보안 정책에 따라 모든 외부 접속은 VPN을 통해서만 허용됩니다.",
    "인사 발령: 홍길동 부장을 기획팀장으로 2026년 1월 1일부로 임명합니다.",
    "품질 관리 기준: 불량률 0.1% 이하, 납기 준수율 99% 이상을 목표로 합니다.",
    "환경 영향 평가: CO2 배출량 연간 500톤 감소 목표를 설정하였습니다.",
    "재무제표 분석: 영업이익률 12%, 부채비율 45%, 유동비율 180%.",
    "고객 만족도 조사: 응답자 1,000명 중 87%가 서비스에 만족한다고 답변했습니다.",
    "법적 검토 의견: 본 계약서는 관련 법령에 부합하며 법적 효력이 있습니다.",
    "프로젝트 일정: 설계 2개월, 개발 4개월, 테스트 1개월, 배포 1개월.",
    "투자 분석: NPV 양수, IRR 15%로 투자 타당성이 충분히 확보되었습니다.",
    "운영 매뉴얼: 장비 시작 전 안전 점검 체크리스트를 반드시 확인하십시오.",
    "연간 보고서: 총 매출 1,200억 원, 순이익 180억 원, 전년 대비 22% 증가.",
    "기관 소개: 본 기관은 1985년 설립되어 40년간 공공 서비스를 제공해 왔습니다.",
    "결정 사항: 신규 ERP 시스템 도입을 2026년 2분기에 시작하기로 최종 결정함.",
    "위험 요소: 환율 변동, 원자재 가격 상승, 글로벌 공급망 불안정 등이 있습니다.",
    "성과 지표: KPI 달성률 94%, OKR 완료율 88%, NPS 점수 72점.",
    "업무 분장: 기획팀은 전략 수립, 운영팀은 실행, 지원팀은 행정을 담당합니다.",
    "제품 사양서: 무게 1.2kg, 크기 30x20x5cm, 소비전력 45W, 배터리 12시간.",
    "승인 요청: 아래와 같이 예산 집행 계획을 수립하였으니 검토 후 승인 바랍니다.",
    "데이터 분석: 월별 사용자 증가율 평균 8.3%, 이탈률 월 2.1% 수준입니다.",
    "인프라 구성: 웹 서버 4대, DB 서버 2대, 로드밸런서 1대로 구성됩니다.",
    "교육 계획: 전 직원 대상 정보 보안 교육을 분기별 1회 실시합니다.",
    "평가 기준: 가격 40%, 기술력 35%, 납기 15%, 업체 신뢰도 10%.",
    "사업 목표: 국내 시장 점유율 25% 달성 및 동남아 시장 진출을 추진합니다.",
    "개선 방향: 프로세스 자동화로 업무 처리 시간을 현재 대비 40% 단축합니다.",
    "검토 의견: 제출된 사업계획서는 전반적으로 충실하나 재무 계획 보완이 필요합니다.",
    "조직 개편: 기존 5개 팀을 3개 본부 9개 팀 체계로 개편하여 운영합니다.",
    "계약 조건: 계약금 30%, 중도금 40%, 잔금 30%로 3회에 나누어 지급합니다.",
    "기술 동향: 생성형 AI 시장은 2030년까지 연평균 37% 성장할 것으로 전망됩니다.",
    "운영 현황: 전국 15개 지점에서 총 320명의 직원이 근무하고 있습니다.",
    "예산 현황: 총 배정 예산 중 68%를 집행하였으며 잔액은 다음 분기로 이월합니다.",
    "협력 방안: MOU 체결을 통해 기술 공유 및 공동 연구 개발을 추진합니다.",
    "모니터링 결과: 시스템 가동률 99.7%, 평균 응답 시간 120ms로 안정적입니다.",
    "후속 조치: 지적 사항에 대한 개선 계획을 30일 이내에 제출하시기 바랍니다.",
    "표준화 방안: ISO 9001 기준에 따라 품질 관리 체계를 전면 재정비합니다.",
    "수요 예측: 내년도 수요량은 올해 대비 15% 증가한 12만 개로 추정됩니다.",
    "비용 분석: 고정비 35%, 변동비 65% 구조로 손익분기점은 월 매출 8억 원입니다.",
    "전략 방향: 핵심 사업 집중, 비효율 사업 정리, 신성장 동력 발굴을 추진합니다.",
    "완료 보고: 1단계 사업이 계획 대비 98% 수준으로 완료되었음을 보고드립니다.",
]

BATCH_SIZES = [1, 10, 50]


def _measure(
    name: str,
    factory: Callable,
    n_trials: int = 3,
) -> None:
    print(f"\n{'─' * 60}")
    print(f"  모델: {name}")
    print(f"{'─' * 60}")

    # cold start (모델 첫 로드 + 첫 추론)
    t0 = time.perf_counter()
    embed = factory()
    embed(_SAMPLES[0])
    cold = time.perf_counter() - t0
    print(f"  cold start (로드 + 첫 추론): {cold:.2f}s")

    # warm 단건
    times = []
    for _ in range(n_trials):
        t0 = time.perf_counter()
        embed(_SAMPLES[0])
        times.append(time.perf_counter() - t0)
    avg = sum(times) / len(times)
    print(f"  단건 ({n_trials}회 평균):           {avg * 1000:.1f}ms")

    # 배치
    for bs in BATCH_SIZES:
        batch = _SAMPLES[:bs]
        times = []
        for _ in range(n_trials):
            t0 = time.perf_counter()
            embed(batch)
            times.append(time.perf_counter() - t0)
        avg_batch = sum(times) / len(times)
        per_item = avg_batch / bs
        print(f"  배치 {bs:2d}건 ({n_trials}회 평균):        {avg_batch * 1000:.1f}ms  ({per_item * 1000:.1f}ms/건)")


# ---------------------------------------------------------------------------
# 모델별 테스트
# ---------------------------------------------------------------------------

def test_e5_base():
    """intfloat/multilingual-e5-base — docpilot 기본 내장 모델 (768차원, ~560MB)"""
    from docpilot.search.embedding import default_embed_fn
    _measure("multilingual-e5-base (default)", default_embed_fn)


def test_minilm():
    """paraphrase-multilingual-MiniLM-L12-v2 — 경량 모델 (384차원, ~470MB)"""
    pytest.importorskip("sentence_transformers", reason="sentence-transformers 미설치")
    from docpilot.search.embedding import sentence_embed_fn
    _measure(
        "multilingual-MiniLM-L12-v2",
        lambda: sentence_embed_fn("paraphrase-multilingual-MiniLM-L12-v2"),
    )


def test_e5_large():
    """intfloat/multilingual-e5-large — 고품질 대형 모델 (1024차원, ~2.2GB)"""
    pytest.importorskip("sentence_transformers", reason="sentence-transformers 미설치")
    from docpilot.search.embedding import sentence_embed_fn
    _measure(
        "multilingual-e5-large",
        lambda: sentence_embed_fn("intfloat/multilingual-e5-large"),
    )


def test_bge_m3():
    """BAAI/bge-m3 — 다국어 고품질 모델 (1024차원, ~2.3GB), FlagEmbedding 필요"""
    pytest.importorskip("FlagEmbedding", reason="FlagEmbedding 미설치: pip install FlagEmbedding")
    from docpilot.search.embedding import bge_embed_fn
    _measure("BAAI/bge-m3", lambda: bge_embed_fn(device="cpu"))


def test_summary():
    """설치된 모델만 순서대로 실행하고 비교 표를 출력합니다."""
    results: list[tuple[str, float, float, float]] = []

    candidates = [
        ("multilingual-MiniLM-L12-v2 (384d)", _try_minilm),
        ("multilingual-e5-base      (768d)", _try_e5_base),
        ("multilingual-e5-large     (1024d)", _try_e5_large),
        ("BAAI/bge-m3               (1024d)", _try_bge_m3),
    ]

    for label, factory_fn in candidates:
        result = factory_fn()
        if result is None:
            print(f"  [건너뜀] {label}")
            continue
        embed = result
        # warm-up
        embed(_SAMPLES[0])
        # 단건
        t0 = time.perf_counter()
        for _ in range(5):
            embed(_SAMPLES[0])
        single_ms = (time.perf_counter() - t0) / 5 * 1000
        # 배치 10건
        t0 = time.perf_counter()
        for _ in range(3):
            embed(_SAMPLES[:10])
        batch10_ms = (time.perf_counter() - t0) / 3 * 1000
        results.append((label, single_ms, batch10_ms, batch10_ms / 10))

    print(f"\n\n{'=' * 72}")
    print(f"  임베딩 모델 비교 (CPU)")
    print(f"{'=' * 72}")
    print(f"  {'모델':<34}  {'단건':>8}  {'배치10건':>10}  {'건당':>8}")
    print(f"  {'─' * 34}  {'─' * 8}  {'─' * 10}  {'─' * 8}")
    for label, single, batch, per in results:
        print(f"  {label:<34}  {single:>7.1f}ms  {batch:>9.1f}ms  {per:>7.1f}ms")
    print(f"{'=' * 72}\n")

    assert results, "측정된 모델이 없습니다 — sentence-transformers를 설치하세요"


# ---------------------------------------------------------------------------
# 헬퍼: 설치 여부에 따라 None 반환
# ---------------------------------------------------------------------------

def _try_e5_base():
    try:
        from docpilot.search.embedding import default_embed_fn
        return default_embed_fn()
    except Exception:
        return None


def _try_minilm():
    try:
        from docpilot.search.embedding import sentence_embed_fn
        return sentence_embed_fn("paraphrase-multilingual-MiniLM-L12-v2")
    except Exception:
        return None


def _try_e5_large():
    try:
        from docpilot.search.embedding import sentence_embed_fn
        return sentence_embed_fn("intfloat/multilingual-e5-large")
    except Exception:
        return None


def _try_bge_m3():
    try:
        from docpilot.search.embedding import bge_embed_fn
        return bge_embed_fn(device="cpu")
    except Exception:
        return None
