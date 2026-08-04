"""
NSoft 미니리포트 템플릿 + RAG 없이 바로 준비된 콘텐츠로 docx 생성 테스트
(generate_from_content 재현 스크립트)

실행:
    uv run python scripts/gen_한아정밀_미니리포트.py

사용할 LLM 제공자/모델/키는 .env의 DOCPILOT_LLM / DOCPILOT_MODEL / <PROVIDER>_API_KEY를 따릅니다.
"""
from __future__ import annotations

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent.parent
TEMPLATE = ROOT / "data" / "NSoft_미니리포트_템플릿.docx"
OUTPUT = ROOT / "output" / "한아정밀_미니리포트.docx"

CONTENT = """현장 방문 및 IT 운영 현황 정리 리포트

방문 정리 — 한아정밀(HanA Precision) 조지아 공장

방문 일시: 2025-03-14 (금) 10:00~12:00
방문 회사: 한아정밀 (HanA Precision Co., Ltd.)
면담 대상: 박준영 생산기술팀장
작성 기관: NSoft America, Inc.

1. 말씀 주신 내용 (현장 인터뷰 요약)

"현재 공장 내 별도의 IT 인력은 배치되어 있지 않고, 설비보전팀 인원이 필요할 때마다 시스템 이슈에 겸직으로 대응하고 있습니다.
서버나 네트워크 장애가 발생하면 한국 본사 전산실에 연락하는데, 시차 때문에 실질적인 원인 파악까지 보통 반나절 정도 걸립니다.
지난 1년간 시스템 문제로 라인이 두 차례 정지했고, 누적 정지 시간은 약 7시간이었습니다.
가장 걱정되는 부분은 '서버 다운 시 현장에서 할 수 있는 조치가 사실상 없다'는 점이라고 말씀하셨습니다."

2. 추가 확인이 필요한 부분 (상세 진단 필요 항목)

※ 짧은 인터뷰만으로는 파악이 어려워 향후 2차 미팅 시 실사 확인이 필요한 항목입니다.

- 2020년 도입된 생산관리 시스템의 설계 문서 및 최신 소스코드 보관 위치 (공장/본사 여부 미확인)
- 백업 프로세스의 자동화 여부 및 실제 복구 가능 데이터 범위
- 현장 무선 네트워크(AP)와 산업용 스캐너 간 간섭 발생 빈도 및 절체 대응 체계

3. 동종 제조 현장 주요 리스크 분석 및 해결 방향

백업 복원 검증 부재 및 백업망 미검증 리스크
- 인근 사례: 조지아 인근 소재 부품 D사 — 백업은 가동 중이었으나, 실제 장애 발생 시 파일 정합성 문제로 복구 실패.
- 손실 영향: 원래 수 시간 내 조치 가능했던 장애가 시스템 전체 재설치로 이어져 이틀간 라인 정지. 관련 지체 비용 약 $60,000 발생.
- 해결 방향: 정기적인 복원 테스트 체계 수립 및 RPO(목표 복구 시점) 1시간 이내 달성을 위한 백업 정책 재설계 필요.
- 실사 과제: 백업 이미지 실복원 가능 여부 및 RTO/RPO 목표치 달성 가능성 진단.

노후 서버·보안 관리 공백
- 인근 사례: 테네시 소재 부품 E사 — 보안 패치가 중단된 노후 서버에서 악성코드 감염 발생, 출하 시스템 일시 마비.
- 손실 영향: 복구까지 약 30시간 소요, 수기 출하 처리로 인한 오류 및 클레임 발생.
- 해결 방향: 노후 장비 격리 네트워크 구성, 단계적 OS 이관 로드맵 수립.
- 실사 과제: 현장 서버 보안 취약점 점검 및 저비용 격리 방안 진단.

시차 기반 본사 지원 공백
- 인근 사례: 조지아 소재 F사 — 미국 주간 근무 중 DB 오류 발생, 본사 야간 시간대와 겹쳐 약 9시간 대기.
- 손실 영향: 야간·주말 장애 시 대응 공백으로 인한 유휴 인건비 및 조업 지연.
- 해결 방향: 현지 시차 대응 가능한 원격/온사이트 지원 체계 구축, 현장 1차 대응 매뉴얼 마련.
- 실사 과제: 현장 자체 조치 가이드 범위 및 정기 예방점검 주기 진단.
"""


def main() -> None:
    from docpilot import DocPilot

    if not TEMPLATE.exists():
        print(f"[오류] 템플릿 없음: {TEMPLATE}")
        sys.exit(1)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    pilot = DocPilot()  # .env의 DOCPILOT_LLM/DOCPILOT_MODEL을 따름
    result = pilot.generate_from_content(
        content=CONTENT,
        template=str(TEMPLATE),
        output=str(OUTPUT),
    )

    print(f"[완료] {result.path}")
    print(f"model={result.model} input_tokens={result.input_tokens} output_tokens={result.output_tokens}")


if __name__ == "__main__":
    main()
