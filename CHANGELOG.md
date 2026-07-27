# Changelog

이 프로젝트의 주요 변경사항을 기록합니다. 형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/)를,
버전 번호는 [Semantic Versioning](https://semver.org/lang/ko/)을 따릅니다.

## [Unreleased]

### Added
- `DocPilot(temperature=...)` — 5개 LLM 제공자(Claude/OpenAI/Gemini/Grok/Ollama) 공통으로 샘플링 temperature 지정 가능. 미지정 시 제공자/모델 기본값 유지

## [0.2.3] - 2026-07-27

### Added
- `DocPilot(llm="ollama", num_ctx=...)` — Ollama 요청에 `num_ctx`를 실어 보내고, RAG/content로 조립된 프롬프트가 예상 토큰 기준으로 `num_ctx`를 초과하면 API 호출 전에 `ContextExceededError`로 즉시 차단 (기존엔 조용히 잘리거나 응답이 중간에 끊길 수 있었음)
- `RagMapper.map()`: `ContextExceededError` 발생 시 `top_k`를 절반씩 줄여 최대 2회 자동 재시도 (Ollama 사전 차단 + Claude/OpenAI/Gemini/Grok의 실제 API 거부 에러 양쪽 모두에 적용)
- Ollama 매퍼 기본 요청 타임아웃 180초 (`OllamaMapper(timeout=...)`로 조정 가능) — VRAM 부족 시 에러 없이 CPU로 전환되며 20~50배 느려지는 상황에 대한 안전장치

## [0.2.2] - 2026-07-24

### Added
- 로마자-한글 별칭 검색 — 인덱싱 시 문서 내 "에코플라스틱(Ecoplastic)" 같은 병기를 kiwipiepy 품사 태그 규칙으로 자동 추출해 전역 `term_aliases` 테이블에 저장(LLM 미사용). `search(mode="bm25"|"exact")`가 로마자 쿼리(`"eco"`)로도 한글 전용 청크를 검색하도록 쿼리를 확장. 구현: `docpilot.search.alias`
- `tests/test_embed_quality_bench.py`: 로컬 임베딩 모델 4종(MiniLM/e5-base/e5-large/bge-m3) 검색 품질 비교 벤치마크 — 15개 주제 클러스터 합성 코퍼스 기준 Recall@6/MRR/nDCG@6 측정, README에 결과 반영

### Fixed
- `morpheme.search()`가 순수 로마자 단독 쿼리(예: `"eco"`)에 대해 형태소가 0개 추출됐다는 이유로 무조건 `SearchError`를 던지던 버그 수정 — 별칭 확장 결과를 먼저 합친 뒤 빈 집합 여부를 판단하도록 순서 변경

## [0.2.1] - 2026-07-23

### Added
- MCP 서버에 RAG 검색 전용 도구(`retrieve_context`) 추가

### Fixed
- LLM 응답 truncation 원인 구분 (max_tokens 잘림 vs 그 외 JSON 파싱 실패)
- RAG 검색 `source_pattern` 경로 불일치로 검색 0건 반환되던 버그 수정
- HWPX 다중 섹션 빌드 미지원 버그 수정 (section0.xml 외 나머지 섹션도 채움)
- HWPX 불릿 `paraPr` 헤더 중복 생성 버그 수정
- DOCX 헤더/푸터(기본·첫 페이지·짝수 페이지) 플레이스홀더 미채움 버그 수정

## [0.2.0] - 2026-07-22

### Added
- 인덱싱/검색에 `collection` 태그 도입 — `index()`/`search()`/`generate()`에 `collection` 파라미터 추가, `SearchFilter.collection`으로 검색 범위를 특정 폴더(태그)로 제한 가능. 태그 미지정 시 기존과 동일하게 DB 전체를 대상으로 검색

### Fixed
- `suggest_extras()`가 제안하는 설치 명령이 옛 패키지명(`pip install "docpilot[...]"`)을 반환하던 버그 수정 → `smart-docgen[...]`
- `__version__`이 항상 `"0.0.0+unknown"`으로 표시되던 버그 수정 — `importlib.metadata.version("docpilot")`이 실제 배포명(`smart-docgen`)과 달라 조회에 항상 실패하고 있었음
- `exact.search()` 및 PostgreSQL Jaccard 폴백 검색이 실제 DB에서 `DetachedInstanceError`로 실패하던 버그 수정 — DB 세션의 `expire_on_commit` 기본값(`True`) 때문에 커밋 후 세션이 닫힌 뒤 ORM 객체 속성에 접근하면서 발생

### Changed
- **[Breaking]** MCP 콘솔 스크립트(실행 파일)명을 `docpilot-mcp` → `smart-docgen-mcp`로 변경. 기존에 `claude_desktop_config.json`의 `"command"`에 `docpilot-mcp`를 지정해둔 경우 `smart-docgen-mcp`로 직접 갱신해야 함 (자동 마이그레이션 없음)
- README의 MCP 서버 연결 예시(`claude_desktop_config.json`)의 `mcpServers` 키를 `docpilot` → `smart-docgen`으로 변경, 이에 맞춰 예시 프롬프트("smart-docgen 도구 목록 보여줘" 등)도 함께 수정
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
