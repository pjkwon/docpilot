# Changelog

이 프로젝트의 주요 변경사항을 기록합니다. 형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/)를,
버전 번호는 [Semantic Versioning](https://semver.org/lang/ko/)을 따릅니다.

## [Unreleased]

### Fixed
- `suggest_extras()`가 제안하는 설치 명령이 옛 패키지명(`pip install "docpilot[...]"`)을 반환하던 버그 수정 → `smart-docgen[...]`

### Changed
- README의 MCP 서버 연결 예시(`claude_desktop_config.json`)의 `mcpServers` 키를 `docpilot` → `smart-docgen`으로 변경, 이에 맞춰 예시 프롬프트("smart-docgen 도구 목록 보여줘" 등)도 함께 수정. `docpilot-mcp` 명령어·`DOCPILOT_*` 환경변수 등 실제 코드 식별자는 변경 없음
- MCP 서버의 등록 이름(FastMCP name)과 클라이언트에 노출되는 설명(instructions) 첫 문장을 `docpilot` → `smart-docgen`으로 변경
- `.env.example`, `pyproject.toml` 주석의 잘못된 pip 설치 예시(`docpilot[postgres]`, `pip install docpilot`)를 `smart-docgen`으로 수정

## [0.1.1] - 2026-07-21

### Changed
- README에서 라이브러리(제품)를 가리키는 서술을 `docpilot` → `smart-docgen`으로 통일. import 경로·`DocPilot` 클래스명·MCP 서버/명령어명 등 코드 식별자는 변경 없음

### Added
- CHANGELOG.md 추가

## [0.1.0] - 2026-07-21

### Added
- 최초 공개 릴리스 (PyPI: `smart-docgen`)
- 다양한 입력 소스 지원: TXT, MD, RST, CSV, HWPX, HWP, DOCX, PDF(OCR 폴백 포함)
- 다양한 출력 포맷 지원: HWPX, DOCX, PDF
- LLM 교체 가능한 통합 인터페이스: Claude, OpenAI, Gemini, Grok, Ollama
- 하이브리드 검색(RRF): 형태소(FTS5·BM25) + 벡터(sqlite-vec/pgvector) 검색 결합
- 임베딩 제공자 선택 지원: 기본(multilingual-e5-base 로컬), OpenAI, Voyage AI, BGE-M3, sentence-transformers
- 스타일 인식 생성(HWPX·DOCX): 플레이스홀더 위치의 서식을 분석해 LLM 프롬프트에 반영
- 템플릿 자동 생성(HWPX·DOCX): 샘플 문서에서 공통 섹션 구조 추출
- RAG 없이 생성하는 `generate_from_content` 지원
- MCP 서버(`docpilot-mcp`) 제공 — Claude Desktop 등에서 문서 변환·템플릿 조립 도구로 사용 가능

[Unreleased]: https://github.com/pjkwon/docpilot/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/pjkwon/docpilot/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/pjkwon/docpilot/releases/tag/v0.1.0
