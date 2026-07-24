"""로컬 임베딩 모델 검색 품질 비교 벤치마크.

15개 주제 클러스터(클러스터당 6문장, 총 90문장)로 구성된 합성 코퍼스에 대해
클러스터당 자연어 질의 1개를 던져, 같은 클러스터의 문장이 상위에 랭크되는지를
Recall@6 / MRR / nDCG@6으로 측정합니다.

클러스터 내 문장들은 같은 주제를 다른 표현으로 서술하므로(어휘 중복이 낮음),
단순 키워드 매칭이 아니라 의미 기반 검색 품질을 반영합니다.

실행:
    uv run pytest tests/test_embed_quality_bench.py -s
"""
from __future__ import annotations

import math
from typing import Callable

import pytest

# ---------------------------------------------------------------------------
# 코퍼스: (topic_id, text). 클러스터당 6문장, 같은 주제를 다른 관점/표현으로 서술.
# ---------------------------------------------------------------------------

_CORPUS: list[tuple[int, str]] = [
    # 0: 예산 삭감 (ERP 도입 사업)
    (0, "신규 ERP 도입 사업의 예산이 당초 15억 원에서 10억 원으로 삭감되었습니다."),
    (0, "이번 예산 삭감은 하반기 매출 부진에 따른 전사적 비용 절감 방침 때문입니다."),
    (0, "삭감된 예산은 IT 인프라 투자 예산에서 우선적으로 조정되었습니다."),
    (0, "예산 삭감으로 인해 ERP 구축 일정이 2개월 지연될 전망입니다."),
    (0, "재무팀은 삭감된 예산 범위 내에서 사업을 재설계하라고 요청했습니다."),
    (0, "경영진은 다음 분기 실적 개선 시 예산을 재배정하겠다고 밝혔습니다."),
    # 1: 인사 발령
    (1, "홍길동 부장이 2026년 1월 1일부로 기획팀장으로 승진 발령되었습니다."),
    (1, "이번 인사는 신년 조직 개편과 함께 이루어졌습니다."),
    (1, "홍길동 신임 팀장은 지난 3년간 영업팀에서 근무한 이력이 있습니다."),
    (1, "후임 영업팀장에는 김영희 차장이 내정되었습니다."),
    (1, "발령 대상자에게는 별도의 인수인계 기간 2주가 부여됩니다."),
    (1, "인사 발령 공지는 사내 게시판을 통해 전 직원에게 공유되었습니다."),
    # 2: 계약 조건 (신규 공급 계약)
    (2, "본 공급 계약의 총 계약 금액은 8억 원이며 부가세는 별도입니다."),
    (2, "대금은 계약금 20%, 중도금 50%, 잔금 30%로 나누어 지급됩니다."),
    (2, "계약 기간은 체결일로부터 1년이며 자동 갱신 조항이 포함되어 있습니다."),
    (2, "납품 지연 시 지체상금은 1일당 계약금액의 0.1%가 부과됩니다."),
    (2, "계약 해지는 상호 서면 통보 후 30일의 유예기간을 둡니다."),
    (2, "본 계약과 관련한 분쟁은 서울중앙지방법원을 관할로 합니다."),
    # 3: 프로젝트 일정 (신제품 출시)
    (3, "신제품 출시 프로젝트는 설계 2개월, 개발 4개월, 테스트 1개월로 계획되어 있습니다."),
    (3, "최종 출시일은 2026년 9월 1일로 확정되었습니다."),
    (3, "개발 단계에서 하드웨어 부품 수급 문제로 2주 지연이 발생했습니다."),
    (3, "테스트 단계는 품질팀과 외부 인증기관이 공동으로 진행합니다."),
    (3, "일정 지연을 만회하기 위해 테스트 기간을 병행 진행하기로 했습니다."),
    (3, "프로젝트 진행 상황은 매주 금요일 정기 보고로 공유됩니다."),
    # 4: 품질 관리 (불량률)
    (4, "품질 관리 기준에 따라 불량률은 0.1% 이하로 유지해야 합니다."),
    (4, "최근 3개월간 실제 불량률은 평균 0.08%로 기준을 충족하고 있습니다."),
    (4, "불량 발생 시 즉시 원인 분석 보고서를 제출해야 합니다."),
    (4, "품질 검사는 전수 검사가 아닌 표본 검사 방식으로 진행됩니다."),
    (4, "ISO 9001 인증 기준에 맞춰 품질 관리 체계를 정비했습니다."),
    (4, "불량률 기준을 초과할 경우 해당 라인의 가동을 일시 중단합니다."),
    # 5: 보안 정책 (외부 접속)
    (5, "보안 정책에 따라 모든 외부 접속은 VPN을 통해서만 허용됩니다."),
    (5, "VPN 접속 시 2단계 인증(OTP)이 의무적으로 적용됩니다."),
    (5, "개인 소유 기기(BYOD)를 통한 사내 시스템 접속은 원칙적으로 금지됩니다."),
    (5, "보안 정책 위반이 적발될 경우 계정이 즉시 정지됩니다."),
    (5, "재택근무자는 회사 지급 노트북으로만 VPN에 접속할 수 있습니다."),
    (5, "분기별로 전 직원 대상 보안 정책 준수 여부를 점검합니다."),
    # 6: 회의록 (예산 조정 회의)
    (6, "본 회의는 1분기 예산 조정을 안건으로 진행되었습니다."),
    (6, "참석자는 기획팀장, 재무팀장, 각 사업부 팀장 5명입니다."),
    (6, "회의 결과 마케팅 예산 10%를 R&D 예산으로 전용하기로 결정했습니다."),
    (6, "차기 회의는 2주 후 예산 집행 현황 점검을 위해 소집됩니다."),
    (6, "이의가 있는 부서는 회의록 배포 후 3일 이내에 의견을 제출해야 합니다."),
    (6, "회의록은 참석자 전원의 검토를 거쳐 최종 확정되었습니다."),
    # 7: 시장 분석 (가격 경쟁력)
    (7, "시장 분석 결과 자사 제품은 경쟁사 대비 가격 경쟁력이 20% 우위에 있습니다."),
    (7, "다만 브랜드 인지도는 경쟁사에 비해 다소 낮은 것으로 나타났습니다."),
    (7, "주요 경쟁사는 A사와 B사이며 시장 점유율 합계가 45%에 달합니다."),
    (7, "가격 우위를 활용해 중소형 고객사 대상 공략을 강화할 계획입니다."),
    (7, "경쟁사 A사는 최근 신제품 가격을 15% 인하했습니다."),
    (7, "가격 경쟁력 유지를 위해 원가 절감 태스크포스가 구성되었습니다."),
    # 8: 기술 사양 (서버 장비)
    (8, "신규 서버 장비의 사양은 CPU Intel Xeon, RAM 128GB, SSD 4TB입니다."),
    (8, "GPU는 NVIDIA A100 2장이 탑재되어 AI 연산에 최적화되어 있습니다."),
    (8, "전원은 이중화 구성으로 정전 시에도 무중단 운영이 가능합니다."),
    (8, "서버는 데이터센터 3층 랙에 설치될 예정입니다."),
    (8, "네트워크는 10Gbps 이중 회선으로 구성됩니다."),
    (8, "장비 도입 비용은 대당 약 3천만 원으로 책정되었습니다."),
    # 9: 고객 만족도
    (9, "고객 만족도 조사 결과 응답자 1,000명 중 87%가 서비스에 만족한다고 답했습니다."),
    (9, "불만족 응답자의 주요 사유는 응대 속도 지연이었습니다."),
    (9, "만족도는 전년 대비 5%포인트 상승한 수치입니다."),
    (9, "조사는 온라인 설문 방식으로 2주간 진행되었습니다."),
    (9, "고객센터는 응대 속도 개선을 위해 상담 인력을 20% 증원했습니다."),
    (9, "차기 조사는 개선 조치 효과를 확인하기 위해 6개월 후 재실시됩니다."),
    # 10: 환경/ESG (탄소 배출)
    (10, "환경 영향 평가 결과 연간 CO2 배출량을 500톤 감축하는 것을 목표로 합니다."),
    (10, "이를 위해 공장 내 노후 설비를 고효율 설비로 전면 교체합니다."),
    (10, "감축 목표 달성 시점은 2027년 말로 설정되어 있습니다."),
    (10, "탄소 배출권 거래제 대응 전담 조직도 신설되었습니다."),
    (10, "ESG 경영 방침에 따라 매년 지속가능경영보고서를 발간합니다."),
    (10, "재생에너지 사용 비율을 현재 5%에서 20%까지 끌어올릴 계획입니다."),
    # 11: 교육/훈련 (정보보안 교육)
    (11, "전 직원을 대상으로 정보 보안 교육을 분기별 1회 실시합니다."),
    (11, "교육은 온라인 이러닝과 오프라인 워크숍을 병행합니다."),
    (11, "미이수자는 다음 분기 시작 전까지 반드시 이수해야 합니다."),
    (11, "교육 내용에는 피싱 메일 대응, 비밀번호 관리 등이 포함됩니다."),
    (11, "교육 이수율은 인사 평가에 반영됩니다."),
    (11, "올해 상반기 교육 이수율은 96%를 기록했습니다."),
    # 12: 물류/공급망 (원자재 수급)
    (12, "주요 원자재인 반도체 부품의 글로벌 공급 부족으로 수급이 불안정합니다."),
    (12, "이에 따라 원자재 재고를 기존 1개월분에서 3개월분으로 확대했습니다."),
    (12, "복수 공급업체 확보를 통해 단일 업체 의존도를 낮추고 있습니다."),
    (12, "물류비 상승도 원가 부담 요인 중 하나로 지목되고 있습니다."),
    (12, "대체 원자재 사용 가능성에 대한 기술 검토가 진행 중입니다."),
    (12, "공급망 리스크 관리를 위한 전담 모니터링 체계가 구축되었습니다."),
    # 13: 법적 검토 (계약서 검토)
    (13, "법무팀 검토 결과 본 계약서는 관련 법령에 부합하며 법적 효력이 있습니다."),
    (13, "다만 손해배상 조항의 상한선을 명확히 할 필요가 있다는 의견이 제시되었습니다."),
    (13, "지적재산권 귀속 조항도 상대방 요청에 따라 일부 수정되었습니다."),
    (13, "최종 검토 의견서는 법무팀장 승인 후 사업부에 전달되었습니다."),
    (13, "계약 체결 전 상대방 법무팀과 문구 조율이 한 차례 더 필요합니다."),
    (13, "검토 소요 기간은 접수일로부터 영업일 기준 5일이었습니다."),
    # 14: 성과 지표/KPI
    (14, "올해 KPI 달성률은 94%, OKR 완료율은 88%를 기록했습니다."),
    (14, "고객 순추천지수(NPS)는 72점으로 전년 대비 6점 상승했습니다."),
    (14, "미달성 KPI는 신규 고객 확보 부문으로, 목표 대비 78% 수준입니다."),
    (14, "성과 평가 결과는 다음 달 개인별 인사 평가에 반영됩니다."),
    (14, "부서별 KPI는 분기마다 재조정되며 전사 전략과 연동됩니다."),
    (14, "내년도 KPI 목표는 이번 결과를 반영해 상향 조정될 예정입니다."),
]

# (query, relevant topic_id) - 클러스터당 1개 질의
_QUERIES: list[tuple[str, int]] = [
    ("ERP 사업 예산이 왜 줄었나요?", 0),
    ("누가 기획팀장으로 승진했나요?", 1),
    ("새 공급 계약의 대금 지급 조건은 어떻게 되나요?", 2),
    ("신제품은 언제 출시되나요?", 3),
    ("제품 불량률은 얼마나 관리되고 있나요?", 4),
    ("회사 외부에서 사내 시스템에 접속하는 방법은?", 5),
    ("1분기 예산 조정 회의에서 무엇이 결정됐나요?", 6),
    ("우리 제품 가격은 경쟁사와 비교해 어떤가요?", 7),
    ("새로 도입하는 서버 사양이 어떻게 되나요?", 8),
    ("고객들은 서비스에 얼마나 만족하나요?", 9),
    ("회사의 탄소 배출 감축 목표는 무엇인가요?", 10),
    ("직원 보안 교육은 어떻게 진행되나요?", 11),
    ("원자재 수급 상황은 어떤가요?", 12),
    ("계약서에 대한 법무팀 검토 의견은 무엇인가요?", 13),
    ("올해 KPI 달성 현황은 어떤가요?", 14),
]

_K = 6  # 클러스터당 문장 수와 동일 - 완전 recall(1.0)이 이론상 가능하도록


# ---------------------------------------------------------------------------
# 지표
# ---------------------------------------------------------------------------

def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _rank(query_vec: list[float], corpus_vecs: list[list[float]]) -> list[int]:
    sims = [(_cosine(query_vec, v), i) for i, v in enumerate(corpus_vecs)]
    sims.sort(key=lambda x: x[0], reverse=True)
    return [i for _, i in sims]


def _recall_at_k(ranked: list[int], relevant: set[int], k: int) -> float:
    topk = set(ranked[:k])
    return len(topk & relevant) / len(relevant)


def _reciprocal_rank(ranked: list[int], relevant: set[int]) -> float:
    for rank, idx in enumerate(ranked, start=1):
        if idx in relevant:
            return 1.0 / rank
    return 0.0


def _ndcg_at_k(ranked: list[int], relevant: set[int], k: int) -> float:
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, idx in enumerate(ranked[:k], start=1)
        if idx in relevant
    )
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(r + 1) for r in range(1, ideal_hits + 1))
    return dcg / idcg if idcg > 0.0 else 0.0


def _evaluate(embed: Callable) -> tuple[float, float, float]:
    """모델 하나에 대해 (avg Recall@K, avg MRR, avg nDCG@K)를 반환."""
    texts = [t for _, t in _CORPUS]
    corpus_vecs = embed(texts)

    recalls, rrs, ndcgs = [], [], []
    for query, topic_id in _QUERIES:
        qvec = embed(query)
        relevant = {i for i, (t, _) in enumerate(_CORPUS) if t == topic_id}
        ranked = _rank(qvec, corpus_vecs)
        recalls.append(_recall_at_k(ranked, relevant, _K))
        rrs.append(_reciprocal_rank(ranked, relevant))
        ndcgs.append(_ndcg_at_k(ranked, relevant, _K))

    n = len(_QUERIES)
    return sum(recalls) / n, sum(rrs) / n, sum(ndcgs) / n


# ---------------------------------------------------------------------------
# 모델 팩토리 (설치 안 됐으면 None)
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


# ---------------------------------------------------------------------------
# 테스트
# ---------------------------------------------------------------------------

def test_quality_summary():
    """설치된 모델만 순서대로 평가하고 비교 표를 출력합니다."""
    candidates = [
        ("multilingual-MiniLM-L12-v2 (384d)", _try_minilm),
        ("multilingual-e5-base      (768d)", _try_e5_base),
        ("multilingual-e5-large     (1024d)", _try_e5_large),
        ("BAAI/bge-m3               (1024d)", _try_bge_m3),
    ]

    results: list[tuple[str, float, float, float]] = []
    for label, factory_fn in candidates:
        embed = factory_fn()
        if embed is None:
            print(f"  [건너뜀] {label}")
            continue
        recall, mrr, ndcg = _evaluate(embed)
        results.append((label, recall, mrr, ndcg))

    print(f"\n\n{'=' * 78}")
    print(f"  임베딩 모델 검색 품질 비교 - 코퍼스 {len(_CORPUS)}문장 / 질의 {len(_QUERIES)}개")
    print(f"{'=' * 78}")
    print(f"  {'모델':<34}  {'Recall@' + str(_K):>10}  {'MRR':>8}  {'nDCG@' + str(_K):>8}")
    print(f"  {'─' * 34}  {'─' * 10}  {'─' * 8}  {'─' * 8}")
    for label, recall, mrr, ndcg in results:
        print(f"  {label:<34}  {recall:>10.3f}  {mrr:>8.3f}  {ndcg:>8.3f}")
    print(f"{'=' * 78}\n")

    assert results, "평가된 모델이 없습니다 - sentence-transformers를 설치하세요"


def test_e5_base_quality():
    """intfloat/multilingual-e5-base - docpilot 기본 내장 모델."""
    from docpilot.search.embedding import default_embed_fn
    embed = default_embed_fn()
    if embed is None:
        pytest.skip("sentence-transformers 미설치")
    recall, mrr, ndcg = _evaluate(embed)
    print(f"\ne5-base: Recall@{_K}={recall:.3f}  MRR={mrr:.3f}  nDCG@{_K}={ndcg:.3f}")


def test_minilm_quality():
    """paraphrase-multilingual-MiniLM-L12-v2 - 경량 모델."""
    pytest.importorskip("sentence_transformers", reason="sentence-transformers 미설치")
    from docpilot.search.embedding import sentence_embed_fn
    embed = sentence_embed_fn("paraphrase-multilingual-MiniLM-L12-v2")
    recall, mrr, ndcg = _evaluate(embed)
    print(f"\nMiniLM: Recall@{_K}={recall:.3f}  MRR={mrr:.3f}  nDCG@{_K}={ndcg:.3f}")


def test_e5_large_quality():
    """intfloat/multilingual-e5-large - 고품질 대형 모델."""
    pytest.importorskip("sentence_transformers", reason="sentence-transformers 미설치")
    from docpilot.search.embedding import sentence_embed_fn
    embed = sentence_embed_fn("intfloat/multilingual-e5-large")
    recall, mrr, ndcg = _evaluate(embed)
    print(f"\ne5-large: Recall@{_K}={recall:.3f}  MRR={mrr:.3f}  nDCG@{_K}={ndcg:.3f}")


def test_bge_m3_quality():
    """BAAI/bge-m3 - 다국어 고품질 모델, FlagEmbedding 필요."""
    pytest.importorskip("FlagEmbedding", reason="FlagEmbedding 미설치: pip install FlagEmbedding")
    from docpilot.search.embedding import bge_embed_fn
    embed = bge_embed_fn(device="cpu")
    recall, mrr, ndcg = _evaluate(embed)
    print(f"\nbge-m3: Recall@{_K}={recall:.3f}  MRR={mrr:.3f}  nDCG@{_K}={ndcg:.3f}")
