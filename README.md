# docpilot

데이터 폴더와 템플릿을 입력하면 LLM이 내용을 파악해 완성된 문서를 생성하는 파이썬 라이브러리입니다.

## 특징

- **다양한 입력 소스** — TXT, MD, RST, CSV, PDF (OCR 폴백 포함), PPTX, 이미지(JPG/PNG 등)
- **구조화 인제스트** — HWPX·DOCX 스타일 기반 헤딩, PPTX 불릿 계층, PDF 폰트 크기 기반 헤딩 감지, 의미 경계 청킹으로 RAG 검색 품질 향상
- **다양한 출력 포맷** — HWPX, DOCX, PDF
- **LLM 교체 가능** — Claude · OpenAI · Gemini · Grok · Ollama, 동일 인터페이스
- **하이브리드 검색 (RRF)** — 형태소 AND(FTS5·BM25) + 벡터(sqlite-vec/pgvector)를 동시 실행 후 Reciprocal Rank Fusion으로 병합. 별도 설정 없이 `multilingual-e5-base` 로컬 모델 기본 내장
- **임베딩 제공자 선택** — 기본(multilingual-e5-base 로컬) · OpenAI · Voyage AI · BGE-M3(로컬) · sentence-transformers(로컬), 동일 인터페이스
- **스타일 인식 생성 (HWPX·DOCX)** — 플레이스홀더 위치의 폰트 크기·정렬·표 셀 너비를 자동 분석해 LLM에 전달, 서식에 어울리는 내용 생성
- **템플릿 자동 생성 (HWPX·DOCX)** — 샘플 문서에서 공통 섹션 구조 추출 (샘플 스타일 자동 상속)
- **LLM 벤치마크** — 여러 LLM의 매핑 결과를 나란히 비교

## 설치

### PyPI

```bash
pip install docpilot
pip install "docpilot[mcp]"
pip install "docpilot[pdf,mcp]"
```

### GitHub 직접 설치

extras 포함 시 `패키지명[extras] @ URL` 형식을 사용합니다.

```bash
pip install "docpilot @ git+https://github.com/pjkwon/docpilot.git"
pip install "docpilot[mcp] @ git+https://github.com/pjkwon/docpilot.git"
pip install "docpilot[pdf,mcp] @ git+https://github.com/pjkwon/docpilot.git"
```

### Extras

필요한 기능에 따라 extras를 추가하세요. (아래 예시는 PyPI 기준, GitHub 설치 시 `@ git+https://github.com/wynterkwon/docpilot.git` 추가)

```bash
pip install "docpilot[pdf]"       # PDF 읽기/쓰기 (OCR 포함)
pip install "docpilot[pptx]"      # PPTX 읽기
pip install "docpilot[image]"     # 이미지 읽기 (JPG, PNG 등)
pip install "docpilot[docx]"      # DOCX 읽기/쓰기/템플릿 생성
pip install "docpilot[morpheme]"  # 형태소 기반 한국어 검색
pip install "docpilot[vec]"       # 벡터 임베딩 검색
pip install "docpilot[openai]"    # OpenAI GPT / Grok / Ollama + 임베딩
pip install "docpilot[gemini]"    # Google Gemini
pip install "docpilot[voyage]"    # Voyage AI 임베딩 (한국어 우수)
pip install "docpilot[bge]"       # BGE 로컬 임베딩 (BAAI/bge-m3, 한국어 우수)
pip install "docpilot[sentence]"  # sentence-transformers 로컬 임베딩
pip install "docpilot[postgres]"  # PostgreSQL + pgvector (대용량)
pip install "docpilot[mcp]"       # Claude 앱 MCP 서버
pip install "docpilot[all]"       # 전체 설치
```

복합 설치 예시:

```bash
pip install "docpilot[pdf,pptx,image,docx]"           # 모든 파일 형식
pip install "docpilot[openai,vec]"                     # OpenAI LLM + 임베딩 + 벡터 검색
pip install "docpilot[bge,vec]"                        # 로컬 임베딩 + 벡터 검색 (API 키 불필요)
pip install "docpilot[pdf,openai,morpheme,postgres]"   # 풀 스택
```

### 시스템 의존성

`[pdf]` extras는 Python 패키지 외에 시스템 바이너리가 필요합니다.

| 도구 | 용도 | 설치 |
|------|------|------|
| [Tesseract](https://github.com/tesseract-ocr/tesseract) | PDF OCR | [설치 가이드](https://tesseract-ocr.github.io/tessdoc/Installation.html) |
| [Poppler](https://poppler.freedesktop.org/) | PDF → 이미지 변환 | Windows: `winget install poppler` |

## LLM 제공자

docpilot은 5개 LLM 제공자를 지원합니다. `DocPilot(llm=...)` 또는 `DOCPILOT_LLM` 환경변수로 선택합니다.

| 제공자 | `llm=` 값 | 기본 모델 | 필요 환경변수 | 추가 패키지 |
|--------|-----------|-----------|--------------|-------------|
| Anthropic Claude | `"claude"` | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` | **기본 포함** |
| OpenAI | `"openai"` | `gpt-4o` | `OPENAI_API_KEY` | `[openai]` |
| Google Gemini | `"gemini"` | `gemini-2.0-flash` | `GEMINI_API_KEY` | `[gemini]` |
| xAI Grok | `"grok"` | `grok-3` | `XAI_API_KEY` | `[openai]` |
| Ollama (로컬) | `"ollama"` | `llama3.2` | 불필요 | `[openai]` |

### API 키 설정

프로젝트 루트에 `.env` 파일을 생성합니다 (`.env.example` 참고).

```bash
# 사용하는 LLM의 키만 설정하면 됩니다
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=AIza...
XAI_API_KEY=xai-...

# LLM 제공자 선택 (기본값: claude)
DOCPILOT_LLM=claude
```

코드에서 직접 전달하면 환경변수보다 우선합니다.

```python
pilot = DocPilot(llm="claude", api_key="sk-ant-...")
```

### 제공자별 사용 예시

```python
# Claude (기본 — 별도 패키지 설치 불필요)
pilot = DocPilot(llm="claude", api_key="sk-ant-...")

# OpenAI
pilot = DocPilot(llm="openai", api_key="sk-...")

# Gemini
pilot = DocPilot(llm="gemini", api_key="AIza...")

# Grok
pilot = DocPilot(llm="grok", api_key="xai-...")

# Ollama — 로컬 서버 사용, API 키 불필요
pilot = DocPilot(llm="ollama", model="llama3.2")
pilot = DocPilot(llm="ollama", model="mistral", base_url="http://192.168.0.10:11434/v1")
```

### 기본 모델 변경

```python
pilot = DocPilot(llm="claude", model="claude-opus-4-8")
pilot = DocPilot(llm="openai", model="gpt-4-turbo")
pilot = DocPilot(llm="gemini", model="gemini-1.5-pro")
pilot = DocPilot(llm="grok",   model="grok-3-mini")
pilot = DocPilot(llm="ollama", model="deepseek-r1:7b")
```

> **`DocPilot(llm=...)`은 `generate()` 파이프라인 전용입니다.**  
> `build_auto()` · `HwpxDynamicBuilder`는 내부에서 LLM을 독립적으로 호출합니다.  
> 기본값은 Claude이며, `mapper=` 파라미터로 다른 제공자로 전환할 수 있습니다.  
> 자세한 내용은 [동적 문서 생성 (build_auto)](#동적-문서-생성-build_auto) 참조.

## 빠른 시작

```python
from docpilot import DocPilot

# ANTHROPIC_API_KEY 환경변수가 설정되어 있으면 인자 생략 가능
pilot = DocPilot()
pilot.index("./data")       # 데이터 폴더 인덱싱

pilot.generate(
    data_folder="./data",
    template="report",          # 내장 템플릿 이름 또는 파일 경로
    output="./output/report.hwpx",
    top_k=10,                   # RAG 검색 청크 수 (기본값: 10)
)
```

## 데이터 인덱싱

지원 입력 파일 형식: `.txt`, `.md`, `.rst`, `.csv`, `.hwpx`, `.pdf`, `.pptx`, `.docx`, `.jpg`, `.png`, `.jpeg`, `.bmp`, `.tiff`, `.webp`

```python
pilot.index("./data")   # 폴더 내 모든 지원 파일을 재귀적으로 인덱싱
```

파일을 추가하거나 수정하면 다음 `index()` / `generate()` 호출 시 **자동으로 변경분만 재인덱싱**됩니다 (SHA-256 해시 비교). 파일 내용이 그대로라면 재인덱싱을 건너뜁니다.

전체 강제 재인덱싱이 필요한 경우:

```python
pilot.index("./data", reindex=True)   # 전체 강제 재인덱싱
```

### 포맷별 구조 추출

| 포맷 | 구조 정보 |
|------|-----------|
| HWPX · DOCX | 스타일 이름 및 폰트 크기 기반 헤딩 감지 |
| PPTX | 슬라이드 제목 + 불릿 들여쓰기 계층 (level 0–8) 보존 |
| PDF (텍스트) | 페이지 내 폰트 크기 중앙값 대비 1.2× 이상인 라인을 `[헤딩]`으로 마킹 |
| PDF (스캔본) · 이미지 | OCR 평문 (폰트 메타데이터 없음) |

청킹은 `\n\n` 단락 경계를 기준으로 분리하며, 단락 중간에서 잘리지 않습니다.

### 필요 extras 확인

데이터 폴더를 미리 스캔해 어떤 extras가 필요한지 확인할 수 있습니다.

```python
from docpilot import suggest_extras

result = suggest_extras("./data")
print(result["found"])            # {'.pdf': 3, '.hwpx': 2, '.txt': 5, '.xlsx': 1}
print(result["required_extras"])  # ['pdf']
print(result["install_command"])  # pip install "docpilot[pdf]"
print(result["unsupported"])      # {'.xlsx': 1}  ← docpilot이 처리할 수 없는 형식
```

`DocPilot` 인스턴스를 통해서도 동일하게 사용할 수 있습니다.

```python
result = DocPilot.suggest_extras("./data")
```

## 템플릿 작성 방법

한글(HWPX), Word(DOCX), PDF 파일을 직접 만들고, 내용이 들어갈 위치에 `{{섹션명}}` 플레이스홀더를 삽입합니다. docpilot이 데이터 폴더를 검색해 각 섹션에 맞는 내용을 생성하고 플레이스홀더를 교체합니다.

```
{{서론}}

{{연구 목적}}

{{결론}}
```

### 플레이스홀더 이름이 RAG 검색어가 됩니다

플레이스홀더 이름은 자유롭게 지정할 수 있으며, 이름 자체가 데이터 폴더 검색에 사용됩니다. **이름이 구체적일수록 관련성 높은 내용이 생성됩니다.**

```
{{내용1}}          → "내용1"로 검색 — 무엇을 찾아야 할지 모름
{{2024년 매출 현황}} → "2024년 매출 현황"으로 검색 — 관련 데이터를 정확히 찾음
```

섹션 이름은 한국어·영어 모두 사용 가능합니다.

### 스타일 인식 생성 (HWPX·DOCX)

HWPX 또는 DOCX 템플릿을 사용하면 `{{플레이스홀더}}`가 위치한 문단의 서식 정보를 자동으로 분석해 LLM 프롬프트에 포함합니다.

| 추출 정보 | HWPX | DOCX |
|-----------|------|------|
| 폰트 크기 | `charPr.height` → pt | run/스타일 상속 체인 → pt |
| 한글 글꼴 | `fontRef.hangul` | `w:rFonts[@w:eastAsia]` |
| 정렬 | `paraPr.align` | `para.alignment` / 스타일 상속 |
| 표 셀 너비 | `hp:cellSz.width` → mm | `w:tcW[@w:type="dxa"]` → mm |
| 볼드/이탤릭 | `hh:bold`, `hh:italic` | run/스타일 상속 체인 |

LLM은 이 정보를 참고해 서식에 어울리는 분량으로 내용을 작성합니다. 줄 수는 강제하지 않으며, 내용이 짧으면 짧게 · 길면 길게 자유롭게 생성됩니다.

```
## 채워야 할 섹션 (LLM 프롬프트 예시)
- "제목": [스타일: 16pt 볼드, CENTER]
- "본문": [스타일: 10pt 맑은 고딕, JUSTIFY, 표 셀 너비 60mm]
- "결론": [스타일: 10pt 맑은 고딕, JUSTIFY]
```

LLM이 생성한 내용에 `\n`이 포함되면 해당 위치에 단락이 자동으로 분리되어 삽입됩니다 (HWPX·DOCX 공통).

템플릿을 직접 만들 때는 플레이스홀더를 실제 내용이 들어갈 위치에 삽입하면 해당 위치의 스타일이 자동으로 추출됩니다. `generate_template()`으로 자동 생성한 템플릿도 샘플 문서의 본문 스타일을 복제하므로 동일하게 적용됩니다.

### 플레이스홀더 없는 파일을 양식으로 사용하기 (Reference Mode)

`{{섹션명}}`이 없는 일반 문서 파일도 `template`에 그대로 넘길 수 있습니다. docpilot이 파일 내용을 읽어 LLM으로 섹션 구조를 자동 추론하고, 해당 구조로 문서를 생성합니다.

```python
# 플레이스홀더 없는 기존 문서를 양식 참조로 사용
pilot.generate(
    data_folder="./data",
    template="./reference/existing_report.hwpx",  # {{}} 없어도 OK
    output="./output/new_report.hwpx",
)
```

입력 파일 형식에 따라 동작이 다릅니다:

| 템플릿 형식 | 섹션 추론 | 출력 양식 베이스 |
|-------------|-----------|----------------|
| `.hwpx` | LLM이 문서 구조 분석 | 원본 .hwpx 구조·스타일 유지 |
| `.docx` | LLM이 문서 구조 분석 | 원본 .docx 구조·스타일 유지 |
| `.pdf` | LLM이 텍스트 추출 후 분석 | 내장 `report` 템플릿 기반 .hwpx 출력 |
| `.pptx` · `.txt` · `.md` 등 | LLM이 텍스트 추출 후 분석 | 내장 `report` 템플릿 기반 .hwpx 출력 |

> **참고** PDF·텍스트 형식은 원본 서식 구조를 재현할 수 없어 내장 보고서 양식을 베이스로 사용합니다. 원본 서식을 살리려면 `.hwpx` 또는 `.docx` 파일을 사용하세요.

## 작성 지침 문서 (RFP·제안요청서)

제안요청서나 작성 요령이 담긴 파일을 `instructions_doc`으로 넘기면, LLM이 해당 파일 전체를 읽어 지침으로 활용합니다. `data` 폴더의 RAG 검색과 달리 파일 내용이 **온전히** 프롬프트에 포함됩니다.

```python
pilot.generate(
    data_folder="./data",          # 실질 내용 재료
    template="proposal",
    output="./output/proposal.hwpx",
    instructions_doc="./rfp.hwpx", # 제안요청서 — 지침으로 자동 주입
)
```

`extra_instructions`(직접 작성한 문자열)와 함께 쓰면 두 내용이 합쳐져서 LLM에 전달됩니다. 지원 형식: `.hwpx`, `.docx`, `.pdf`, `.txt`, `.md` 등.

## 내장 템플릿

설치 즉시 사용할 수 있는 한글(HWPX) 템플릿이 포함되어 있습니다. 이름으로 참조하면 됩니다.

| 이름 | 용도 | 주요 플레이스홀더 |
|------|------|-----------------|
| `report` | 일반 보고서 | 보고서 제목, 작성일, 작성자/부서, 섹션1 제목, 섹션1 내용, 섹션2 제목, 섹션2 내용, 표 삽입 위치, 결론, 결론 내용 |
| `gonmun` | 공문 | 기관명, 수신자, 경유, 제목, 본문1·2, 직위 성명, 시행번호 등 |
| `minutes` | 회의록 | 회의록 제목, 일시, 장소, 참석자, 안건, 논의, 결정 사항 |
| `proposal` | 제안서/기획서 | 제안 제목, 목적, 추진배경, 추진내용, 기대효과, 예산 등 |

```python
# 이름으로 내장 템플릿 사용
pilot.generate(
    data_folder="./data",
    template="report",        # 파일 경로 대신 이름 지정
    output="./output/report.hwpx",
)

# 사용 가능한 내장 템플릿 목록 확인
print(DocPilot.list_templates())
# {'report': '일반 보고서 — ...', 'gonmun': '공문 — ...', 'minutes': '회의록 — ...', 'proposal': '제안서/기획서 — ...'}
```

## 동적 문서 생성 (build_auto)

`build_auto()`는 템플릿 없이 소스 데이터만으로 HWPX 문서를 생성하는 단일 진입점입니다.
`instructions`에 원하는 문서 형식을 자연어로 지정하면 아래 순서로 자동 결정합니다.

```
1. instructions가 내장 템플릿 키워드에 매칭 → 해당 템플릿 재사용
2. 이전에 저장된 템플릿 중 유사한 것 검색 → 재사용
3. 복수 후보가 나오면 LLM이 최적 선택
4. 매칭 없음 → 기본 스타일로 section0.xml 동적 생성 후 저장
```

동적 생성된 모든 문서는 자동으로 `~/docpilot_templates/`에 양식이 저장되어 이후 검색·재사용이 가능합니다.

```python
from docpilot.builder import build_auto
from docpilot.search.embedding import bge_embed_fn

embed = bge_embed_fn()  # 벡터 검색까지 원할 때 (없어도 됨)

# 케이스 1: 내장 보고서 양식으로 작성 ("보고서" 키워드 → report 템플릿 자동 선택)
build_auto("./data", "output.hwpx", instructions="업무 보고서로 작성", embed_fn=embed)

# 케이스 2: 내장/저장 양식에 없는 형식 → section0.xml 동적 생성 + 자동 저장
build_auto("./data", "output.hwpx", instructions="제안요구서 형식으로 작성", embed_fn=embed)

# 케이스 3: 이전에 저장된 양식 재사용
build_auto("./data", "output.hwpx", instructions="제주 학회 때 썼던 보고서 양식으로", embed_fn=embed)

# 케이스 4: 기존 .hwpx의 스타일 + 섹션 구조를 참고해 새 양식 생성
# → header.xml(스타일)과 문서 구조를 함께 분석해 새 section0.xml 생성
build_auto("./data", "output.hwpx", header_xml="./reference/old_report.hwpx")

# 케이스 5: 후보가 여럿일 때 LLM이 가장 적합한 것을 자동 선택
build_auto("./data", "output.hwpx", instructions="학회 발표 결과 보고서", embed_fn=embed)
```

### LLM 제공자 선택 (mapper=)

`build_auto()`와 `HwpxDynamicBuilder`는 기본적으로 Claude를 사용합니다.
`mapper=`에 원하는 mapper 인스턴스를 전달하면 어떤 LLM이든 사용할 수 있습니다.

```python
from docpilot.builder import build_auto
from docpilot.mapping.gemini import GeminiMapper
from docpilot.mapping.openai_compat import OllamaMapper

# Gemini로 동적 생성
build_auto(
    "./data", "output.hwpx",
    instructions="업무 보고서",
    mapper=GeminiMapper(api_key="AIza..."),
)

# Ollama (로컬) 사용 — API 키 불필요
build_auto(
    "./data", "output.hwpx",
    instructions="회의록 형식으로",
    mapper=OllamaMapper(model="llama3.2"),
)

# HwpxDynamicBuilder 직접 사용 시도 동일하게 적용
from docpilot.builder import HwpxDynamicBuilder
from docpilot.mapping.claude import ClaudeMapper

builder = HwpxDynamicBuilder(
    mapper=ClaudeMapper(model="claude-opus-4-8"),  # 고성능 모델 지정
)
builder.build("소스 텍스트", "header.xml", "output.hwpx", instructions="학회 발표 보고서")
```

### 기존 .hwpx에서 스타일만 가져오기

`header_xml`에 `.hwpx` 파일을 넘기면 `extract_header_xml()`로 스타일을 추출하고,
`_infer_sections_from_content()`(Reference Mode)로 기존 문서의 섹션 구조도 분석해
새 section0.xml 생성에 반영합니다.

```python
from docpilot.builder import build_auto, extract_header_xml

# header_xml에 .hwpx를 직접 넘기면 자동 처리
build_auto("./data", "output.hwpx", header_xml="./reference/old_report.hwpx")

# header.xml만 따로 추출해 HwpxDynamicBuilder에서 쓰고 싶을 때
extract_header_xml("./reference/old_report.hwpx", dest="./my_header.xml")
```

## 저장 템플릿 관리

동적 생성된 양식은 `~/docpilot_templates/`에 자동 저장되고 DB에 인덱싱됩니다.
`template_store` API로 직접 관리할 수 있습니다.

```python
from docpilot.db import template_store

# 목록 조회
for t in template_store.list_all():
    print(t.id, t.name, t.created_at.strftime("%Y-%m-%d"))

# 자연어로 검색
results = template_store.search("제주 학회 발표 보고서 양식", embed_fn=embed)

# 삭제
template_store.delete(3)                                          # ID로
template_store.delete_by_path("~/docpilot_templates/20260610_보고서_제목.xml")

# 이름·설명·태그 수정 (설명 변경 시 embed_fn 넘기면 벡터 재인덱싱)
template_store.update(3, name="제주 학회 발표 보고서", embed_fn=embed)

# LLM으로 더 풍부한 설명 생성 후 업데이트 (검색 품질 향상)
desc = template_store.generate_description("~/docpilot_templates/20260610_보고서_제목.xml")
template_store.update(3, description=desc, embed_fn=embed)
```

## 템플릿 자동 생성

자신의 기존 문서에서 반복 구조를 분석해 새 템플릿을 생성할 수 있습니다. 여러 샘플 문서를 넣으면 공통 섹션 패턴을 추출해 `{{섹션명}}` 플레이스홀더가 삽입된 템플릿을 만들어 줍니다. **출력 파일 확장자가 포맷을 결정합니다** (`.hwpx` 또는 `.docx`).

```python
# HWPX 샘플 → HWPX 템플릿
pilot.generate_template(
    samples=["./archive/report_2023.hwpx", "./archive/report_2024.hwpx"],
    output="./templates/my_report.hwpx",
)

# DOCX 샘플 → DOCX 템플릿
pilot.generate_template(
    samples=["./archive/report_2023.docx", "./archive/report_2024.docx"],
    output="./templates/my_report.docx",
)
```

`./templates/` 폴더에 저장하면 이후 파일 경로 없이 이름으로 바로 참조할 수 있습니다.

```python
# 이름으로 참조 (./templates/ 폴더에서 .hwpx → .docx 순서로 탐색)
pilot.generate(data_folder="./data", template="my_report", output="./out.hwpx")
pilot.generate(data_folder="./data", template="my_report", output="./out.docx")
```

> 템플릿 탐색 순서: 파일 경로 → 내장 이름(`report`/`gonmun`/`minutes`) → `./templates/` 폴더

공통 섹션 신뢰도가 낮으면 LLM 보조를 활성화해 더 정확하게 추출합니다.

```python
pilot.generate_template(samples=[...], output="./templates/my_report.hwpx", use_llm=True)
pilot.generate_template(samples=[...], output="./templates/my_report.docx", use_llm=True)
```

## 검색 방식

### RagMapper 하이브리드 검색 전략

`DocPilot.generate()` 내부의 `RagMapper`는 다음 순서로 검색합니다.

```
형태소 AND (FTS5·BM25)  ─┐
                          ├─ Reciprocal Rank Fusion → top_k 반환
벡터 검색 (cosine)       ─┘

둘 다 결과 없으면 → 형태소 OR (최후 수단)
```

형태소 exact match로 찾은 청크와 의미적으로 유사한 청크(유의어 포함)를 함께 포착해 순위를 병합합니다.

`pip install "docpilot[vec]"` 설치 시 `multilingual-e5-base` 로컬 모델이 자동으로 사용됩니다. 벡터 기능 없이 설치하면 형태소 AND → OR 폴백으로 동작합니다.

#### top_k 조정 — 문서 유형별 컨텍스트 튜닝

`generate()`의 `top_k`는 LLM에 전달할 RAG 검색 청크 수를 결정합니다 (기본값: 10).
문서 유형에 따라 조정하면 생성 품질과 비용을 최적화할 수 있습니다.

```python
# 공문 — 짧고 구조적, 적은 컨텍스트로 충분
pilot.generate(data_folder="./data", template="gonmun",   output="./out.hwpx", top_k=5)

# 보고서 — 기본값
pilot.generate(data_folder="./data", template="report",   output="./out.hwpx", top_k=10)

# 제안서 — 많은 배경 자료가 필요
pilot.generate(data_folder="./data", template="proposal", output="./out.hwpx", top_k=20)
```

MCP에서도 동일하게 `top_k` 파라미터를 `generate_document()` 툴에 전달할 수 있습니다.

### 개별 검색 API

#### DocPilot.search() — 통합 인터페이스

인덱싱 후 `pilot.search()`로 검색할 수 있습니다. `pip install "docpilot[vec]"` 환경에서는 별도 설정 없이 하이브리드 검색이 동작합니다.

```python
# 기본: embed_fn 지정 불필요 — multilingual-e5-base 자동 사용
pilot = DocPilot()
pilot.index("./data")
results = pilot.search("사업 계획", top_k=10)  # BM25 + Vector RRF

# 모드 선택
results = pilot.search("사업 계획", mode="bm25")    # 형태소 BM25만
results = pilot.search("사업 계획", mode="vector")  # 벡터만
results = pilot.search("사업 계획", mode="exact")   # ILIKE 키워드만

# 다른 임베딩 모델 사용 시
from docpilot.search.embedding import bge_embed_fn
pilot = DocPilot(embed_fn=bge_embed_fn())  # BGE-M3 (최고 품질, 2GB)
```

#### 저수준 API

```python
from docpilot.search import exact, embedding, morpheme, hybrid
from docpilot.search.embedding import default_embed_fn

# 하이브리드 — BM25 + Vector → RRF 병합
results = hybrid("사업 계획", embed_fn=default_embed_fn(), top_k=10)

# 형태소 기반 검색 — pip install "docpilot[morpheme]"
# SQLite: FTS5 역인덱스 + BM25 랭킹 / PostgreSQL: Jaccard 유사도
results = morpheme.search("사업 계획", or_fallback=True)

# 벡터 유사도 검색
from docpilot.search.embedding import openai_embed_fn
results = embedding.search("사업 계획", embed_fn=openai_embed_fn())

# 키워드 정확 검색
results = exact.search("사업 계획")
```

### 검색 필터 (SearchFilter)

네 검색 함수 모두 `filters` 파라미터를 받습니다. 필터 조건은 AND로 결합됩니다.

```python
from docpilot.search import SearchFilter, hybrid, exact, morpheme

f = SearchFilter(
    source_pattern="reports/*.hwpx",          # 파일 경로 glob 패턴 (*, ? 지원)
    mime_type="application/vnd.hancom.hwpx",  # MIME 타입 정확 일치
    metadata={"dept": "기획", "year": "2026"},# 문서 메타데이터 key-value 필터
    created_after=datetime(2026, 1, 1),       # 인덱싱 날짜 범위
    created_before=datetime(2026, 12, 31),
)

results = hybrid("사업 계획", embed_fn=..., filters=f)
results = exact.search("사업 계획", filters=f)
results = morpheme.search("사업 계획", filters=f)
results = embedding.search("사업 계획", embed_fn=..., filters=f)
```

### 결과 하이라이팅

```python
from docpilot.search import highlight, render, exact

results = exact.search("사업 계획")

# highlights: 매칭 텀의 (start, end) 인덱스 목록 — 오버랩 스팬은 자동 병합
results = [highlight(r, "사업 계획") for r in results]

# render()로 마커 문자열 삽입 (기본값 **)
for r in results:
    print(render(r))          # "이것은 **사업** **계획** 문서입니다"
    print(render(r, "=="))    # "이것은 ==사업== ==계획== 문서입니다"
    print(r.highlights)       # [(4, 6), (7, 9)]
```

### 문서 단위 집계 (group_by_document)

청크 단위 결과를 문서 단위로 집계합니다. 같은 문서에서 여러 청크가 매칭되어도 문서 하나로 묶어 스코어를 집계합니다.

```python
from docpilot.search import group_by_document, embedding
from docpilot.search.embedding import bge_embed_fn

chunk_results = embedding.search("사업 계획", embed_fn=bge_embed_fn(), top_k=30)

docs = group_by_document(
    chunk_results,
    top_chunks=3,     # 문서당 보여줄 최고점 청크 수 (기본 3)
    score="max",      # "max" 또는 "sum" (기본 "max")
)

for doc in docs:
    print(doc.source, doc.score, doc.chunk_count)
    for chunk in doc.top_chunks:
        print(" ", chunk.content[:80])
```

`DocumentResult` 필드:

| 필드 | 설명 |
|------|------|
| `document_id` | 문서 ID |
| `source` | 원본 파일 경로 |
| `score` | 집계 스코어 (max 또는 sum) |
| `chunk_count` | 매칭된 총 청크 수 |
| `top_chunks` | 상위 청크 `SearchResult` 목록 |
| `metadata` | 문서 메타데이터 |

### 검색 품질 평가 (eval)

`docpilot.search.eval`은 Precision@K · Recall@K · MRR을 계산하는 순수 함수 모음입니다.  
ground truth 케이스를 정의하면 검색 변경 전후 지표를 비교하거나, 테스트 임계값으로 회귀를 감지할 수 있습니다.

```python
from docpilot.search.eval import QueryCase, evaluate
from docpilot.search.hybrid import hybrid
from docpilot.search.embedding import default_embed_fn

embed = default_embed_fn()

cases = [
    QueryCase("사출기 PLC 데이터 수집 MES", {"현장답사.docx"}),
    QueryCase("AMR 팔레트 이송 사출품", {"AMR_회의록.docx"}),
]

report = evaluate(
    cases,
    search_fn=lambda q: hybrid(q, embed_fn=embed, top_k=10),
    ks=[1, 3, 5],
)
print(report)
# EvalReport (n=2)
#   P@1=1.000  R@1=1.000
#   P@3=0.333  R@3=1.000
#   P@5=0.200  R@5=1.000
#   MRR=1.000
```

`relevant_sources`는 `SearchResult.source`의 **basename**으로 매칭합니다.  
같은 문서에서 여러 청크가 나와도 한 번만 카운트합니다(중복 제거).

| 함수 | 설명 |
|------|------|
| `precision_at_k(results, relevant, k)` | top-k 내 유니크 관련 문서 수 / k |
| `recall_at_k(results, relevant, k)` | top-k 내 유니크 관련 문서 수 / 전체 관련 문서 수 |
| `mrr(results, relevant)` | 첫 번째 관련 청크의 역순위 |
| `evaluate(cases, search_fn, ks)` | 전체 케이스 평균 → `EvalReport` 반환 |

## 임베딩 제공자

docpilot은 벡터 검색(RAG)에 사용할 임베딩 제공자를 자유롭게 선택할 수 있습니다.  
`DocPilot(embed_fn=...)` 또는 `embedding.search(embed_fn=...)`에 팩토리 함수를 전달합니다.

`pip install "docpilot[vec]"` 설치 시 `DocPilot()`은 별도 설정 없이 `multilingual-e5-base` 로컬 모델을 기본으로 사용합니다.

### API 방식 (외부 서비스 호출)

| 제공자 | 팩토리 함수 | 기본 모델 | 필요 패키지 | 환경변수 |
|--------|------------|-----------|------------|---------|
| OpenAI | `openai_embed_fn()` | `text-embedding-3-small` | `[openai]` | `OPENAI_API_KEY` |
| Voyage AI | `voyage_embed_fn()` | `voyage-3` | `[voyage]` | `VOYAGE_API_KEY` |

```python
from docpilot.search.embedding import openai_embed_fn, voyage_embed_fn

# OpenAI — pip install "docpilot[openai]"
embed_fn = openai_embed_fn()                                    # OPENAI_API_KEY 환경변수 사용
embed_fn = openai_embed_fn(api_key="sk-...", model="text-embedding-3-large")

# Voyage AI — pip install "docpilot[voyage]" / 한국어 포함 다국어 우수
embed_fn = voyage_embed_fn()                                    # VOYAGE_API_KEY 환경변수 사용
embed_fn = voyage_embed_fn(api_key="pa-...", model="voyage-3")

pilot = DocPilot(llm="claude", embed_fn=embed_fn)
```

### 로컬 방식 (API 키 불필요, 모델 자동 다운로드)

| 제공자 | 팩토리 함수 | 기본 모델 | 크기 | 필요 패키지 | 비고 |
|--------|------------|-----------|------|------------|------|
| 기본 내장 | `default_embed_fn()` | `intfloat/multilingual-e5-base` | ~560MB | `[vec]` | zero-config, 768차원 |
| BGE (BAAI) | `bge_embed_fn()` | `BAAI/bge-m3` | ~2GB | `[bge]` | 최고 품질, 1024차원 |
| sentence-transformers | `sentence_embed_fn()` | `intfloat/multilingual-e5-base` | ~560MB | `[sentence]` | 모델 지정 가능 |

```python
from docpilot.search.embedding import default_embed_fn, bge_embed_fn, sentence_embed_fn

# 기본 — pip install "docpilot[vec]" / 설정 불필요
# DocPilot()은 자동으로 이 함수를 사용 (명시적으로 전달할 필요 없음)
embed_fn = default_embed_fn()                                   # multilingual-e5-base, 768차원, ~560MB

# BGE — pip install "docpilot[bge]" / 한국어 포함 다국어 최상위권
embed_fn = bge_embed_fn()                                       # CPU, BAAI/bge-m3, 1024차원
embed_fn = bge_embed_fn(device="cuda", use_fp16=True)          # GPU 가속

# sentence-transformers — pip install "docpilot[sentence]" / 모델 직접 지정
embed_fn = sentence_embed_fn("intfloat/multilingual-e5-large") # 더 높은 품질
embed_fn = sentence_embed_fn("intfloat/multilingual-e5-small") # 더 가벼운 옵션

pilot = DocPilot(llm="claude", embed_fn=embed_fn)
```

> **모델 캐시**: 로컬 모델은 첫 실행 시 HuggingFace에서 자동 다운로드되어 `~/.cache/huggingface/`에 저장됩니다. 이후 실행부터는 캐시에서 불러옵니다.

> **임베딩 차원**: 기본 임베딩 모델은 `bge_embed_fn()` (BAAI/bge-m3, **1024차원**)입니다. 임베딩 제공자를 변경하거나 처음 설정하는 경우, `EMBEDDING_DIM`과 vec_chunks 테이블 차원이 일치해야 합니다. 기존 DB가 있다면 삭제 후 재생성하거나 `vec_chunks`를 DROP 후 `client.create_tables()`로 재생성하세요.

### 커스텀 임베딩

`Callable[[str], list[float]]` 인터페이스를 맞추면 어떤 임베딩 모델이든 연결할 수 있습니다.  
인덱싱 성능을 높이려면 리스트 입력도 지원하도록 구현하세요 — docpilot이 자동으로 배치 호출합니다.

```python
# 기본: 단일 텍스트만 처리 (인덱싱 시 청크 수만큼 반복 호출)
def my_embed_fn(text: str) -> list[float]:
    ...
    return vector

# 권장: 배치도 지원 (인덱싱 시 전체 청크를 한 번에 처리)
def my_embed_fn(text: str | list[str]) -> list[float] | list[list[float]]:
    inputs = text if isinstance(text, list) else [text]
    vectors = ...  # 배치 임베딩
    return vectors if isinstance(text, list) else vectors[0]

pilot = DocPilot(llm="claude", embed_fn=my_embed_fn)
```

> **배치 처리**: 기본 제공 팩토리 함수(`openai_embed_fn`, `voyage_embed_fn`, `bge_embed_fn`, `sentence_embed_fn`)는 모두 배치 호출을 지원합니다. 문서 인덱싱 시 전체 청크를 API 1회 호출로 처리하므로, 단일 호출 방식 대비 청크 수에 비례해 속도가 향상됩니다.

## 데이터베이스 설정

기본값은 로컬 SQLite 파일입니다. 대용량 처리 시 PostgreSQL로 전환할 수 있습니다.

| 방식 | URL 형식 | 비고 |
|------|----------|------|
| SQLite (기본) | `sqlite:////home/yourname/docpilot.db` | 서버 불필요, **절대 경로 권장** |
| PostgreSQL | `postgresql://user:pw@host:5432/dbname` | `pip install "docpilot[postgres]"` 필요 |

```python
pilot = DocPilot(
    llm="openai",
    api_key="sk-...",
    database_url="postgresql://user:pw@localhost:5432/docpilot",
)
```

### 데이터 폴더 주의사항

`index()` / `generate()` 의 `data_folder`는 **문서 파일만 있는 전용 폴더**를 지정하세요. `rglob("*")`로 하위 폴더까지 재귀 탐색하기 때문에, 프로젝트 루트나 `.venv`가 포함된 경로를 넘기면 수백 개의 패키지 내부 파일이 인덱싱됩니다.

```bash
mkdir data
# 인덱싱할 문서만 data/ 에 넣고
pilot.index("./data")   # ✓
pilot.index(".")        # ✗ 프로젝트 전체가 인덱싱됨
```

## 벤치마크

동일한 데이터와 템플릿을 여러 LLM에 넣어 속도, 토큰 사용량, 섹션별 작성 내용을 나란히 비교합니다. `mappers`에 넣은 LLM 수만큼 실제 API가 호출되므로 각 LLM의 API 키와 패키지가 준비되어 있어야 합니다.

```python
from docpilot.mapping import ClaudeMapper, OpenAIMapper, GeminiMapper
from docpilot.mapping.openai_compat import GrokMapper, OllamaMapper

report = pilot.benchmark(
    data_folder="./data",
    template="./templates/report.hwpx",
    output="./output/result.hwpx",
    mappers={
        "claude": ClaudeMapper(),
        "openai": OpenAIMapper(),
        "gemini": GeminiMapper(),
        "grok":   GrokMapper(),
        "ollama": OllamaMapper(model="llama3.2"),
    },
)
print(report)
```

출력 예시:

```
모델                  처리시간(s)    입력토큰    출력토큰      총토큰  상태
--------------------------------------------------------------------
claude                      2.31      1200        400        1600  OK
openai                      1.85      1180        380        1560  OK
gemini                      0.00         0          0           0  오류: API key missing
--------------------------------------------------------------------

## 섹션별 내용 비교

### 결론
[claude]
본 보고서는 ...

[openai]
종합적으로 검토한 결과 ...
```

API 키 누락이나 호출 실패가 발생한 LLM은 오류 상태로 표시되고, 나머지 LLM의 결과는 정상 출력됩니다.

## MCP 서버

Claude 앱에서 docpilot 도구를 직접 사용하려면 MCP 서버를 설치하고 연결합니다.

### 설치
예시는 PyPI 기준. GitHub 레포 참조해 설치 시 `@ git+https://github.com/pjkwon/docpilot.git` 추가

```bash
pip install "docpilot[mcp]" //PyPI 기준
pip install "docpilot[mcp] @ git+https://github.com/pjkwon/docpilot.git" //GitHub 레포 참조 설치 기준 
```

### Claude Desktop 연결
`ANTHROPIC_API_KEY`는 [console.anthropic.com](https://console.anthropic.com)에서 발급받습니다.

`claude_desktop_config.json`에 아래 블록을 추가합니다.

- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows** (.exe로 설치한 경우 ): `%APPDATA%\Claude\claude_desktop_config.json`  
- **Windows** (Microsoft Store/MSIX로 설치한 경우): `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "docpilot": {
      "command": "docpilot-mcp",
      "env": {
        "ANTHROPIC_API_KEY": "sk-ant-...",
        "DOCPILOT_DATABASE_URL": "sqlite:////Users/yourname/docpilot.db",
        "DOCPILOT_EMBED": "bge"
      }
    }
  }
}
```

`DOCPILOT_EMBED` 미지정 시 `multilingual-e5-base`(기본값)가 사용됩니다. BGE-M3 등 다른 모델을 원할 때만 지정합니다.

> **경로는 모두 절대 경로로 지정하세요.** Claude Desktop이 MCP 서버를 실행하는 작업 디렉터리는 사용자 프로젝트 폴더가 아닙니다. `DOCPILOT_DATABASE_URL` 미지정 시 기본값은 `~/docpilot.db`(홈 디렉터리)입니다. `generate` 도구의 `data_folder`, `output`, 커스텀 템플릿 경로도 절대 경로로 전달해야 합니다.

### macOS 파일 접근 권한

macOS는 앱별로 `~/Documents`, `~/Desktop`, `~/Downloads` 접근을 별도로 허가받아야 합니다. MCP 서버는 Claude Desktop의 자식 프로세스이므로 Claude Desktop에 권한이 없으면 해당 폴더의 파일을 읽거나 쓸 수 없습니다.

**시스템 환경설정 → 개인 정보 보호 및 보안 → 파일 및 폴더** (또는 **전체 디스크 접근**)에서 Claude에 필요한 폴더 권한을 부여하세요.

홈 디렉터리 바로 아래(`~/docpilot.db`, `~/data/` 등)는 별도 허가 없이 접근 가능합니다.

설정 저장 후 Claude Desktop을 재시작하면 다음 도구가 활성화됩니다.

| 도구 | 설명 |
|------|------|
| `index` | 데이터 폴더를 검색 인덱스에 등록 (변경된 파일만 자동 재인덱싱) |
| `index_status` | 인덱싱 진행 상황 확인 — 경과 시간·처리 파일 수 실시간 조회 |
| `search_documents` | 인덱싱된 문서 검색 (필터·하이라이팅·문서 단위 집계 지원) |
| `generate_document` | 데이터 폴더 + 템플릿 → 문서 생성 (output 미지정 시 `~/Documents/docpilot_YYYYMMDD_HHMMSS.hwpx`) |
| `generate_template` | 샘플 HWPX → 재사용 가능한 템플릿 생성 |
| `estimate_cost` | 생성 전 API 토큰 비용 추정 |
| `analyze_coverage` | 섹션별 데이터 커버리지 분석 — LOW 섹션은 LLM이 추론 작성할 가능성이 높음 |

Claude 앱에서 자연어로 사용합니다.

> **[중요] "docpilot 사용 가능해?" 같은 질문은 하지 마세요.**
> Claude는 이런 질문에 학습 데이터 기반으로 답하므로 툴이 등록되어 있어도 "사용할 수 없다"고 답할 수 있습니다.
> MCP 서버는 Claude Desktop을 시작할 때 자동으로 실행됩니다.
> 바로 작업을 지시하거나, 툴 목록을 먼저 확인하려면 **"사용 가능한 docpilot 도구 목록 보여줘"** 라고 요청하세요.

```
# 툴 목록 확인 (처음 사용 시 권장)
사용 가능한 docpilot 도구 목록 보여줘.

# 폴더 인덱싱
/Users/me/data 폴더 인덱싱해줘.

# 기본 검색
사업 계획 관련 문서 찾아줘.

# 필터 검색 — HWPX 파일만, 기획팀 문서만
reports 폴더 안 hwpx 파일 중 기획팀 사업 계획 관련 내용 찾아줘.
(source_pattern: "reports/*.hwpx", metadata: {"dept": "기획"})

# 문서 단위로 집계해서 상위 문서 보여줘
사업 계획 관련 내용을 문서 단위로 묶어서 top 5 보여줘.
(group_by_doc: true)

# 내장 템플릿으로 문서 생성
/Users/me/data 폴더 내용으로 report 템플릿 써서 보고서 만들어줘.
출력은 /Users/me/Documents/result.hwpx 로 저장해줘.

# 커스텀 템플릿 사용
/Users/me/data 폴더 내용으로 /Users/me/templates/proposal.hwpx 템플릿 써서
/Users/me/Documents/proposal_result.hwpx 로 저장해줘.

# 템플릿 자동 생성
/Users/me/samples 폴더의 hwpx 파일들로 템플릿 만들어서
/Users/me/templates/my_report.hwpx 로 저장해줘.

# 인덱싱 상태 확인 (인덱싱이 오래 걸릴 때)
인덱싱 상태 확인해줘.
index_status로 /Users/me/data 폴더 인덱싱 얼마나 됐는지 봐줘.

# 데이터 커버리지 확인 (generate_document 전 권장)
/Users/me/data 폴더가 report 템플릿 섹션을 얼마나 커버하는지 분석해줘.
```

#### search_documents 도구 파라미터

| 파라미터 | 타입 | 기본값 | 설명 |
|----------|------|--------|------|
| `query` | string | — | 검색 질의 |
| `data_folder` | string | null | index()에 사용한 폴더 경로 — 인덱싱 완료 여부 확인용 (미지정 시 전체 잡 확인) |
| `mode` | string | `"morpheme"` | `"exact"` / `"morpheme"` / `"vector"` |
| `top_k` | int | 10 | 최대 반환 결과 수 |
| `group_by_doc` | bool | false | true이면 문서 단위 집계 |
| `highlight` | bool | true | 쿼리 텀 `**강조**` |
| `source_pattern` | string | null | 파일 경로 glob (예: `"reports/*.hwpx"`) |
| `mime_type` | string | null | MIME 타입 정확 일치 |
| `metadata` | object | null | 문서 메타데이터 key-value 필터 |
| `created_after` | string | null | 인덱싱 날짜 하한 (ISO 8601) |
| `created_before` | string | null | 인덱싱 날짜 상한 (ISO 8601) |

#### analyze_coverage 도구 파라미터

섹션별 데이터 커버리지를 분석해 `generate_document()` 전에 LLM 추론 가능성을 미리 파악합니다.
인덱싱 완료 후 호출하세요 (`index()` 또는 `generate_document()` 첫 호출 후).

| 파라미터 | 타입 | 기본값 | 설명 |
|----------|------|--------|------|
| `data_folder` | string | — | 분석할 데이터 파일이 있는 폴더 경로 |
| `template` | string | — | 템플릿 파일 경로 또는 내장 템플릿 이름 |
| `top_k` | int | 3 | 섹션별 검색 결과 수 — 등급 기준값 (≥top_k → HIGH, 1~top_k-1 → MED, 0 → LOW) |

결과 예시:
```
데이터 커버리지 분석
  데이터 폴더: /Users/me/data
  템플릿:     report  (인덱싱 문서 3개)
  총 10개 섹션 — HIGH 6 | MED 2 | LOW 2

섹션별 커버리지
──────────────────────────────────────────────────
[HIGH] 보고서 제목                3청크  score 0.0312
[MED ] 결론                      1청크  score 0.0165
[LOW ] 표 삽입 위치              0청크

[권고] LOW 섹션 2개 — LLM이 내용을 추론할 가능성이 높습니다.
  LOW 섹션: 표 삽입 위치, 작성일
  · 해당 내용이 포함된 파일을 데이터 폴더에 추가하거나
  · LLM이 추론 작성하도록 허용하고 generate() 후 문서를 직접 검토하세요.
```

### 환경변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `ANTHROPIC_API_KEY` | — | Claude API 키 (필수) |
| `DOCPILOT_LLM` | `claude` | LLM 제공자 (`claude` / `openai` / `gemini` / `grok` / `ollama`) |
| `DOCPILOT_MODEL` | 제공자 기본 | 특정 모델 지정 (예: `claude-opus-4-8`) |
| `DOCPILOT_DATABASE_URL` | `~/docpilot.db` | DB 연결 문자열 (절대 경로 권장) |
| `DOCPILOT_EMBED` | (자동) | 임베딩 모델 선택. 미설정 시 `multilingual-e5-base` 자동 사용 |

**`DOCPILOT_EMBED` 값 형식:**

| 값 | 모델 | 필요 패키지 | 비고 |
|----|------|------------|------|
| (미설정) | `intfloat/multilingual-e5-base` | `[vec]` | 기본값, 768차원 |
| `bge` | `BAAI/bge-m3` | `[bge]` | 최고 품질, 1024차원 |
| `bge:cuda` | `BAAI/bge-m3` (GPU) | `[bge]` | GPU 가속 |
| `openai` | `text-embedding-3-small` | `[openai]` | `OPENAI_API_KEY` 필요 |
| `openai:text-embedding-3-large` | text-embedding-3-large | `[openai]` | |
| `voyage` | `voyage-3` | `[voyage]` | `VOYAGE_API_KEY` 필요 |
| `sentence` | `intfloat/multilingual-e5-base` | `[sentence]` | |
| `sentence:intfloat/multilingual-e5-large` | multilingual-e5-large | `[sentence]` | 더 높은 품질 |

## 비용 추정

실제 문서 생성 전 예상 API 비용을 확인할 수 있습니다. LLM 완성 호출 없이 token-counting API만 사용하므로 추정 자체의 비용은 거의 없습니다.

> **참고**: `llm="claude"` (기본값) 일 때는 Anthropic token-counting API로 정확한 입력 토큰 수를 계산합니다. `openai`·`gemini` 등 다른 제공자로 전환한 경우에는 섹션당 고정값(~3,000 토큰)을 사용한 대략 추정치만 반환됩니다.

```python
report = pilot.estimate_cost(
    data_folder="./data",
    template="report",
)
print(report)
```

출력 예시:

```
=== docpilot 비용 추정 ===
모델:             claude-sonnet-4-6
섹션 수:          5개
입력 토큰:        12,450
출력 토큰 (추정): 2,500  (섹션당 500 추정)
예상 비용:        $0.0498
  입력 $3.00/1M  →  $0.0374
  출력 $15.00/1M  →  $0.0375
```

MCP 서버에서는 `estimate_cost` 도구로 동일하게 사용할 수 있습니다. MCP 서버 기본 설정(`DOCPILOT_LLM=claude`)이라면 Claude 앱에서 "비용 예상해줘"라고 자연어로 요청해도 정상 동작합니다. 제한이 생기는 건 `DOCPILOT_LLM`을 OpenAI · Gemini 등 다른 제공자로 바꿨을 때만입니다.

## 예외 처리

모든 예외는 `DocPilotError`를 상속합니다.

```python
from docpilot.exceptions import (
    DocPilotError,
    IngestionError,
    MappingError,
    BuilderError,
    SearchError,
    TemplateError,
)

try:
    pilot.generate(...)
except MappingError as e:
    print(e.detail)   # 상세 오류 메시지
except DocPilotError as e:
    print(e)
```

## 라이선스

MIT
