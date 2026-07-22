# smart-docgen

데이터 폴더와 템플릿을 입력하면 LLM이 내용을 파악해 완성된 문서를 생성하는 파이썬 라이브러리입니다.

## 특징

- **다양한 입력 소스** — TXT, MD, RST, CSV, HWPX, HWP, DOCX, PDF (OCR 폴백 포함)
- **구조화 인제스트** — HWPX·DOCX 스타일 기반 헤딩, PDF 폰트 크기 기반 헤딩 감지, 의미 경계 청킹으로 RAG 검색 품질 향상
- **다양한 출력 포맷** — HWPX, DOCX, PDF
- **LLM 교체 가능** — Claude · OpenAI · Gemini · Grok · Ollama, 동일 인터페이스
- **하이브리드 검색 (RRF)** — 형태소 AND(FTS5·BM25) + 벡터(sqlite-vec/pgvector)를 동시 실행 후 Reciprocal Rank Fusion으로 병합. 별도 설정 없이 `multilingual-e5-base` 로컬 모델 기본 내장
- **임베딩 제공자 선택** — 기본(multilingual-e5-base 로컬) · OpenAI · Voyage AI · BGE-M3(로컬) · sentence-transformers(로컬), 동일 인터페이스
- **스타일 인식 생성 (HWPX·DOCX)** — 플레이스홀더 위치의 폰트 크기·정렬·표 셀 너비를 자동 분석해 LLM에 전달, 서식에 어울리는 내용 생성
- **템플릿 자동 생성 (HWPX·DOCX)** — 샘플 문서에서 공통 섹션 구조 추출 (샘플 스타일 자동 상속)
- **LLM 벤치마크** — 여러 LLM의 매핑 결과를 나란히 비교
- **RAG 없이 생성** — 이미 준비된 콘텐츠(문자열·파일 경로·`IngestedDocument`)를 인덱싱·검색 없이 바로 템플릿에 채우기 (`generate_from_content`)

## 설치

### PyPI

```bash
pip install smart-docgen
pip install "smart-docgen[mcp]"
pip install "smart-docgen[pdf,mcp]"
```

### GitHub 직접 설치

extras 포함 시 `패키지명[extras] @ URL` 형식을 사용합니다.

```bash
pip install "smart-docgen @ git+https://github.com/pjkwon/docpilot.git"
pip install "smart-docgen[mcp] @ git+https://github.com/pjkwon/docpilot.git"
pip install "smart-docgen[pdf,mcp] @ git+https://github.com/pjkwon/docpilot.git"
```

> **형태소(kiwipiepy) 검색, 벡터 검색(sqlite-vec + 기본 임베딩 `multilingual-e5-base`), DOCX 읽기/쓰기(`python-docx`), 한컴오피스 COM 연동(`pyhwpx`)은 모두 core dependencies입니다.** `pip install smart-docgen`만 해도 별도 extras 없이 하이브리드 검색과 DOCX·HWP 변환이 바로 동작합니다(단, HWP↔DOCX/HWPX 변환 자체는 Windows에 한컴오피스(한글)가 실제로 설치되어 있어야 합니다 — 이건 pip으로 설치할 수 없는 별도 라이선스 프로그램입니다). 아래 extras는 그 외 파일 포맷·LLM 제공자·대체 임베딩 등 선택 기능용입니다.

### Extras

필요한 기능에 따라 extras를 추가하세요. (아래 예시는 PyPI 기준, GitHub 설치 시 `@ git+https://github.com/pjkwon/docpilot.git` 추가)

```bash
pip install "smart-docgen[pdf]"       # PDF 읽기/쓰기 (OCR 포함)
pip install "smart-docgen[openai]"    # OpenAI GPT / Grok / Ollama + 임베딩
pip install "smart-docgen[gemini]"    # Google Gemini
pip install "smart-docgen[voyage]"    # Voyage AI 임베딩 (한국어 우수)
pip install "smart-docgen[bge]"       # BGE 로컬 임베딩 (BAAI/bge-m3, 한국어 더 우수하지만 ~2GB)
pip install "smart-docgen[postgres]"  # PostgreSQL + pgvector (대용량)
pip install "smart-docgen[mcp]"       # Claude 앱 MCP 서버
pip install "smart-docgen[all]"       # 전체 설치
```

복합 설치 예시:

```bash
pip install "smart-docgen[pdf]"                            # 전체 파일 포맷 (나머지는 이미 core)
pip install "smart-docgen[openai,bge]"                     # OpenAI LLM + 고품질 로컬 임베딩
pip install "smart-docgen[pdf,openai,postgres]"            # 풀 스택
```

### 시스템 의존성

일부 extras는 Python 패키지 외에 시스템 바이너리나 애플리케이션이 필요합니다.

| 도구 | 용도 | 관련 extras | 설치 |
|------|------|-------------|------|
| [Tesseract](https://github.com/tesseract-ocr/tesseract) | PDF(스캔본) OCR | `[pdf]` | [설치 가이드](https://tesseract-ocr.github.io/tessdoc/Installation.html) |
| [Poppler](https://poppler.freedesktop.org/) | PDF → 이미지 변환 | `[pdf]` | Windows: `winget install poppler` |
| 한컴오피스 (한글) | HWP → HWPX 변환, HWP/HWPX → DOCX 변환 (COM 자동화) | 없음 — Python 패키지(`pyhwpx`)는 core, 한글 앱 자체만 별도 설치 | Windows 전용, 별도 라이선스 필요 |

### 알려진 이슈

**DOCX → HWPX 변환 미지원.** `convert_to_hwpx()`(라이브러리) / `convert_document`(MCP)에 코드는 구현되어 있으나,
일부 한컴오피스 설치 환경에서 COM을 통한 `hwp.Open(docx파일)` 자체가 실패하는 문제가 재현되어 보류 중입니다.
`format` 힌트(자동/`OOXML`/`MSWORD`), `visible` 모드, `forceopen` 옵션을 바꿔봐도 동일하게 실패했고,
같은 파일을 한글 GUI에서 파일 > 열기로 직접 열면 정상적으로 열립니다 — COM 자동화 경로에서만 발생하는 문제로 보이며 원인은 특정하지 못했습니다.

- 라이브러리에서 `convert_to_hwpx()`를 DOCX 입력으로 호출하면 이 이슈에 대한 `UserWarning`이 뜨고 변환을 시도합니다 (환경에 따라 성공할 수도 있어 막지는 않음).
- MCP `convert_document`는 `.docx → .hwpx` 요청을 시도 없이 즉시 미지원으로 응답합니다.
- 우회: 한글에서 해당 docx를 직접 열어 "다른 이름으로 저장 → HWPX"로 수동 변환하세요.
- HWP → HWPX, HWP/HWPX → DOCX는 이 이슈와 무관하며 정상 동작합니다.

## LLM 제공자

smart-docgen은 5개 LLM 제공자를 지원합니다. `DocPilot(llm=...)` 또는 `DOCPILOT_LLM` 환경변수로 선택합니다.

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

**내장 지원** (pip extras 불필요): `.txt` `.md` `.rst` `.csv` `.hwpx` `.docx`. `.hwp`도 Python 패키지는 core라 pip extra는 불필요하지만, 한컴오피스(한글) 앱 자체가 별도로 설치되어 있어야 합니다 (COM 자동화, Windows 전용).

**extras 필요:**

| 형식 | 확장자 | 필요 extras | 비고 |
|------|--------|-------------|------|
| PDF | `.pdf` | `[pdf]` | OCR 폴백 포함 (Tesseract + Poppler 필요) |

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
| HWPX · DOCX | 스타일 이름 및 폰트 크기 기반 헤딩 감지. HWPX는 다중 섹션 문서 전체 추출 지원 (글상자·각주·표 셀 포함) |
| PDF (텍스트) | 페이지 내 폰트 크기 중앙값 대비 1.2× 이상인 라인을 `[헤딩]`으로 마킹 |
| PDF (스캔본) | OCR 평문 (폰트 메타데이터 없음) |

청킹은 `\n\n` 단락 경계를 기준으로 분리하며, 단락 중간에서 잘리지 않습니다.

### 필요 extras 확인

데이터 폴더를 미리 스캔해 어떤 extras가 필요한지 확인할 수 있습니다.

```python
from docpilot import suggest_extras

result = suggest_extras("./data")
print(result["found"])            # {'.pdf': 3, '.hwpx': 2, '.txt': 5, '.xlsx': 1}
print(result["required_extras"])  # ['pdf']
print(result["install_command"])  # pip install "smart-docgen[pdf]"
print(result["unsupported"])      # {'.xlsx': 1}  ← smart-docgen이 처리할 수 없는 형식
```

`DocPilot` 인스턴스를 통해서도 동일하게 사용할 수 있습니다.

```python
result = DocPilot.suggest_extras("./data")
```

## 템플릿 작성 방법

한글(HWPX), Word(DOCX), PDF 파일을 직접 만들고, 내용이 들어갈 위치에 `{{섹션명}}` 플레이스홀더를 삽입합니다. smart-docgen이 데이터 폴더를 검색해 각 섹션에 맞는 내용을 생성하고 플레이스홀더를 교체합니다.

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

### 가변 플레이스홀더 (동적 리스트)

항목 개수가 데이터에 따라 달라지는 섹션은 `{{?key?}}` 문법을 사용합니다. LLM이 소스 데이터를 보고 항목 수를 직접 결정해 리스트로 채웁니다.

```
{{?주요 세션별 발표 내용 요약?}}
```

기존 `{{key}}`와 달리 `{{?key?}}`는 HWPX·DOCX 빌더에서 각 항목을 별도 단락으로 클론해 삽입합니다.

#### 번호 붙은 선택 그룹

고정 최대 개수로 선택적 항목을 표현하려면 번호 접미사를 붙입니다. 예를 들어 첨부 파일 목록을 최대 3개로 제한하려면:

```
{{?첨부파일1}}
{{?첨부파일2}}
{{?첨부파일3}}
```

smart-docgen은 이 세 플레이스홀더를 자동으로 `첨부파일` 리스트(`group_max=3`)로 합쳐 처리합니다.  
실제 첨부 파일이 1개라면 두 번째·세 번째 단락은 자동으로 제거됩니다.

#### 기존 템플릿에서 변환

이미 만든 템플릿의 `{{key}}`를 `{{?key?}}`로 변환하려면:

```python
from docpilot import convert_to_list_placeholder

# 새 파일로 저장
convert_to_list_placeholder(
    "학회참석보고서_템플릿.hwpx",
    keys=["주요 세션별 발표 내용 요약"],
    output="학회참석보고서_템플릿_v2.hwpx",
)

# 여러 키를 한 번에 / output 생략 시 원본 덮어쓰기
convert_to_list_placeholder("template.docx", keys=["항목", "발표자"])
```

### 사이드카 JSON으로 섹션 메타데이터 정의

템플릿 파일을 수정하지 않고 옆에 `.json` 파일만 두면 섹션별 `description`, `rule`, `is_list` 등이 자동으로 반영됩니다.

| 템플릿 유형 | 사이드카 위치 |
|-------------|---------------|
| 파일 기반 (`report.hwpx`) | 같은 폴더의 `report.json` |
| 디렉터리 기반 (내장 템플릿) | 템플릿 폴더 안의 `sidecar.json` |

```json
{
  "name": "학회 참석 보고서",
  "description": "학회·세미나 참석 후 제출하는 보고서",
  "keywords": ["학회", "세미나", "발표"],
  "instructions": "전문 용어는 한국어로 병기하세요.",
  "sections": {
    "행사명": { "rule": "공식 행사 명칭 전체를 기재" },
    "주요 세션별 발표 내용 요약": { "is_list": true, "description": "각 세션 발표 핵심 내용 1–3문장" },
    "출장 기간": { "rule": "YYYY년 MM월 DD일 ~ MM월 DD일" }
  }
}
```

`instructions`는 전역 작성 지침으로 LLM 프롬프트에 주입됩니다. 섹션별 `rule`은 형식 규칙, `description`은 작성 가이드입니다.

사이드카 적용 우선순위: **사이드카 JSON > DB 저장 sections_meta > 템플릿 파일 기본값**

### 플레이스홀더 없는 파일을 양식으로 사용하기 (Reference Mode)

`{{섹션명}}`이 없는 일반 문서 파일도 `template`에 그대로 넘길 수 있습니다. smart-docgen이 파일 내용을 읽어 LLM으로 섹션 구조를 자동 추론하고, 해당 구조로 문서를 생성합니다.

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
| `.pdf` · `.txt` · `.md` 등 | LLM이 텍스트 추출 후 분석 | 내장 `report` 템플릿 기반 .hwpx 출력 |

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

## RAG 없이 생성하기 (generate_from_content)

이미 준비된 콘텐츠가 있다면 데이터 폴더 인덱싱·RAG 검색 없이 바로 템플릿에 채울 수 있습니다. `generate()`의 `data_folder` 자리에 `content`를 직접 넘깁니다.

```python
pilot.generate_from_content(
    content="완성된 원본 텍스트 전체",   # str
    template="report",
    output="./output/report.hwpx",
)
```

`content`는 세 가지 형태를 받습니다:

| 형태 | 설명 |
|------|------|
| `str` | 완성된 문자열을 그대로 프롬프트에 전달 |
| `list[str \| Path]` | 파일 경로 목록 — 인덱싱 없이 바로 ingest만 수행 (DB에 저장 안 함) |
| `list[IngestedDocument]` | 이미 ingest된 문서 객체 리스트 — `docpilot.ingestion.ingest_paths()`나 각 포맷 모듈의 `ingest()`로 직접 만들 수 있음 |

```python
# 파일 몇 개만 골라서 인덱싱 없이 바로 채우고 싶을 때
pilot.generate_from_content(
    content=["./notes/meeting.txt", "./notes/summary.md"],
    template="minutes",
    output="./output/minutes.hwpx",
)
```

**`generate()`와의 차이**: RAG 검색(형태소·벡터 하이브리드)이 없고, `content`로 넘긴 것을 통째로 LLM에 넣어 섹션별로 조직합니다. "무엇을 넣을지"는 호출자가 직접 고르고, "어디에 넣을지"만 LLM이 정합니다.

### 크기 가드 (max_input_tokens)

RAG의 `top_k`처럼 컨텍스트 크기를 자동으로 제한해주는 장치가 없으므로, 콘텐츠가 크면(기본 기준 입력 토큰 약 5만) 경고가 뜹니다. `max_input_tokens`를 명시하면 초과 시 문서를 만들지 않고 에러로 막습니다.

```python
pilot.generate_from_content(
    content=big_text,
    template="report",
    output="./output/report.hwpx",
    max_input_tokens=20_000,   # 넘으면 MappingError, 생성 안 함
)
```

### placeholder 없는 문서도 지원 (Reference Mode)

`template`에 `{{}}`가 없는 문서를 넘기면 `generate()`와 동일하게 LLM이 문서 구조를 추론해 임시 템플릿을 만들고 이어서 채웁니다 (구조 추론용 LLM 호출이 한 번 더 발생). 반면 `describe_template()`/`fill_template()`(MCP가 쓰는 LLM-free 함수)은 이 기능이 없어 placeholder 없는 템플릿을 그대로 거부합니다.

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

### 템플릿 저장 (`save_template`)

만든 HWPX 템플릿을 이름으로 등록하면 이후 `generate()`에서 파일 경로 없이 이름만으로 참조할 수 있습니다.

```python
# HWPX 템플릿 저장 — section0.xml·header.xml은 ~/.docpilot/templates/<name>/에 자동 추출
record_id = pilot.save_template(
    name="학회보고서",
    path="학회참석보고서_템플릿.hwpx",
    description="학회·세미나 참석 후 제출하는 보고서",
    tags=["학회", "보고서"],
    # auto_sections_meta=True (기본값): LLM이 섹션별 description/rule 자동 추론 — API 호출 발생(과금됨)
)

# 이후 이름으로 바로 사용
result = pilot.generate(
    data_folder="./data",
    template="학회보고서",          # 파일 경로 대신 저장한 이름
    output="./output/result.hwpx",
)
```

> **[주의] `auto_sections_meta=True`(기본값)은 `save_template()`을 호출할 때마다 LLM API를 호출합니다 (과금됨).**
> `sections_meta is None`이면 저장 시 LLM이 각 플레이스홀더를 분석해 `description`·`rule`을 자동 추론하고, 이 메타데이터는 이후 `generate()` 시 RAG 검색 품질과 LLM 작성 지침에 활용됩니다.
> 이 호출이 일어날 때마다 `UserWarning`이 발생합니다. API 호출 없이 저장하려면:
> ```python
> pilot.save_template(..., auto_sections_meta=False)          # 메타데이터 없이 저장
> pilot.save_template(..., sections_meta={"제목": {"description": "...", "rule": ""}})  # 직접 지정
> ```
> `save_template`은 MCP 서버에 노출되어 있지 않으므로, 이 비용은 라이브러리를 직접 호출할 때만 발생합니다.

> `.docx`·`.pdf` 템플릿은 파일 경로를 직접 `generate(template=...)`에 전달하거나, 사이드카 JSON으로 메타데이터를 정의하세요.

### 템플릿 목록

```python
# 내장 템플릿 + DB 저장 템플릿 모두 반환
print(DocPilot.list_templates())
# {'report': '일반 보고서 — ...', 'gonmun': '공문 — ...', '학회보고서': '학회·세미나 참석 후 ...'}
```

### 저수준 DB API

동적 생성된 양식은 `~/docpilot_templates/`에 자동 저장되고 DB에 인덱싱됩니다.
`template_store`로 직접 관리할 수 있습니다.

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
DocPilot.delete_template(3)                                       # DocPilot 클래스 메서드

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

> 템플릿 탐색 순서: 파일 경로 → 내장 이름(`report`/`gonmun`/`minutes`/`proposal`) → `./templates/` 폴더 → DB 저장 템플릿

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

`multilingual-e5-base` 로컬 모델이 core dependency라 `pip install smart-docgen`만으로 자동 사용됩니다. `sentence-transformers`나 `sqlite-vec`를 별도로 제거한 환경이라면 형태소 AND → OR 폴백으로 동작합니다.

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

`top_k`는 라이브러리의 `pilot.generate()` 전용 파라미터입니다 — MCP 서버는 RAG 검색을 하지 않는 `fill_template` 흐름만 제공하므로 해당 파라미터가 없습니다.

### 개별 검색 API

#### DocPilot.search() — 통합 인터페이스

인덱싱 후 `pilot.search()`로 검색할 수 있습니다. 별도 설치 없이 `pip install smart-docgen`만으로 하이브리드 검색이 바로 동작합니다.

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

# 하이라이팅 + 문서 단위 집계도 파라미터로 바로 사용 가능 (내부적으로 아래
# "결과 하이라이팅"/"문서 단위 집계" 절의 함수들을 조합해서 실행)
results = pilot.search("사업 계획", highlight=True)               # list[SearchResult], .highlights 채워짐
docs    = pilot.search("사업 계획", group_by_doc=True)             # list[DocumentResult]로 반환 타입이 바뀜
```

#### 저수준 API

```python
from docpilot.search import exact, embedding, morpheme, hybrid
from docpilot.search.embedding import default_embed_fn

# 하이브리드 — BM25 + Vector → RRF 병합
results = hybrid("사업 계획", embed_fn=default_embed_fn(), top_k=10)

# 형태소 기반 검색 — kiwipiepy는 core dependency라 별도 설치 불필요
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
    collection="project_a",                   # 인덱싱 시 지정한 collection 태그 정확 일치
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

smart-docgen은 벡터 검색(RAG)에 사용할 임베딩 제공자를 자유롭게 선택할 수 있습니다.  
`DocPilot(embed_fn=...)` 또는 `embedding.search(embed_fn=...)`에 팩토리 함수를 전달합니다.

`DocPilot()`은 별도 설정·설치 없이 `multilingual-e5-base` 로컬 모델을 기본으로 사용합니다 (core dependency).

### API 방식 (외부 서비스 호출)

| 제공자 | 팩토리 함수 | 기본 모델 | 필요 패키지 | 환경변수 |
|--------|------------|-----------|------------|---------|
| OpenAI | `openai_embed_fn()` | `text-embedding-3-small` | `[openai]` | `OPENAI_API_KEY` |
| Voyage AI | `voyage_embed_fn()` | `voyage-3` | `[voyage]` | `VOYAGE_API_KEY` |

```python
from docpilot.search.embedding import openai_embed_fn, voyage_embed_fn

# OpenAI — pip install "smart-docgen[openai]"
embed_fn = openai_embed_fn()                                    # OPENAI_API_KEY 환경변수 사용
embed_fn = openai_embed_fn(api_key="sk-...", model="text-embedding-3-large")

# Voyage AI — pip install "smart-docgen[voyage]" / 한국어 포함 다국어 우수
embed_fn = voyage_embed_fn()                                    # VOYAGE_API_KEY 환경변수 사용
embed_fn = voyage_embed_fn(api_key="pa-...", model="voyage-3")

pilot = DocPilot(llm="claude", embed_fn=embed_fn)
```

### 로컬 방식 (API 키 불필요, 모델 자동 다운로드)

| 제공자 | 팩토리 함수 | 기본 모델 | 크기 | 필요 패키지 | 비고 |
|--------|------------|-----------|------|------------|------|
| 기본 내장 | `default_embed_fn()` | `intfloat/multilingual-e5-base` | ~560MB | core (기본 설치 포함) | zero-config, 768차원 |
| BGE (BAAI) | `bge_embed_fn()` | `BAAI/bge-m3` | ~2GB | `[bge]` | 최고 품질, 1024차원 |
| sentence-transformers | `sentence_embed_fn()` | `paraphrase-multilingual-MiniLM-L12-v2` | ~470MB | core (기본 설치 포함) | 임의 sentence-transformers 모델 직접 지정 가능 — `default_embed_fn()`과 기본 모델이 다름 |

```python
from docpilot.search.embedding import default_embed_fn, bge_embed_fn, sentence_embed_fn

# 기본 — core dependency, 별도 설치·설정 불필요
# DocPilot()은 자동으로 이 함수를 사용 (명시적으로 전달할 필요 없음)
embed_fn = default_embed_fn()                                   # multilingual-e5-base, 768차원, ~560MB

# BGE — pip install "smart-docgen[bge]" / 한국어 포함 다국어 최상위권
embed_fn = bge_embed_fn()                                       # CPU, BAAI/bge-m3, 1024차원
embed_fn = bge_embed_fn(device="cuda", use_fp16=True)          # GPU 가속

# sentence-transformers — core dependency, 별도 설치 불필요 / 모델 직접 지정
embed_fn = sentence_embed_fn("intfloat/multilingual-e5-large") # 더 높은 품질
embed_fn = sentence_embed_fn("intfloat/multilingual-e5-small") # 더 가벼운 옵션
embed_fn = sentence_embed_fn()                                  # 인자 없이 호출 시 paraphrase-multilingual-MiniLM-L12-v2 (default_embed_fn()과 다른 모델)

pilot = DocPilot(llm="claude", embed_fn=embed_fn)
```

> **모델 캐시**: 로컬 모델은 첫 실행 시 HuggingFace에서 자동 다운로드되어 `~/.cache/huggingface/`에 저장됩니다. 이후 실행부터는 캐시에서 불러옵니다.

> **임베딩 차원**: 기본 임베딩 모델은 `default_embed_fn()` (multilingual-e5-base, **768차원**, `EMBEDDING_DIM` 기본값도 768). `bge_embed_fn()`으로 바꾸면 1024차원입니다. 임베딩 제공자를 변경하는 경우 `EMBEDDING_DIM`과 vec_chunks 테이블 차원이 일치해야 합니다. 기존 DB가 있다면 삭제 후 재생성하거나 `vec_chunks`를 DROP 후 `client.create_tables()`로 재생성하세요.

### multilingual-e5-base vs BGE-m3, 언제 바꿔야 할까

| | multilingual-e5-base (기본) | BAAI/bge-m3 |
|---|---|---|
| 파라미터 | ~278M | ~568M |
| 최대 컨텍스트 | 512 토큰 | 8192 토큰 |
| 용량 | ~560MB | ~2GB |

정확한 검색 품질 벤치마크 수치는 모델마다·태스크마다 달라 여기서 단정하지 않습니다. 필요하면 [MTEB 리더보드](https://huggingface.co/spaces/mteb/leaderboard)에서 두 모델을 직접 비교하세요.

다만 smart-docgen 기본 설정에서 확인 가능한 제약이 하나 있습니다. 인덱싱 기본 청크 크기는 문자 기준 1000자(`docpilot/db/indexer.py`의 `_CHUNK_SIZE`)인데, 한글은 토큰당 대략 1.5~2자라 청크에 따라 500~700토큰대가 나올 수 있습니다. e5-base는 512토큰이 한도라 이런 청크는 초과분이 **에러 없이 조용히 잘려서** 인코딩됩니다. BGE-m3는 8192토큰이라 이 문제가 없습니다. 청크가 자주 긴 데이터(회의록 전문, 긴 조항형 문서 등)를 다룬다면 BGE-m3 쪽이 안전합니다.

### 커스텀 임베딩

`Callable[[str], list[float]]` 인터페이스를 맞추면 어떤 임베딩 모델이든 연결할 수 있습니다.  
인덱싱 성능을 높이려면 리스트 입력도 지원하도록 구현하세요 — smart-docgen이 자동으로 배치 호출합니다.

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
| PostgreSQL | `postgresql://user:pw@host:5432/dbname` | `pip install "smart-docgen[postgres]"` 필요 |

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

### 검색 범위를 폴더로 제한하기 (collection)

`~/docpilot.db`는 모든 프로젝트/폴더가 공유하는 단일 DB입니다. `index()`로 폴더를 지정해도 **검색은 기본적으로 DB 전체를 대상으로** 하므로, 여러 폴더를 인덱싱했다면 서로 다른 프로젝트의 문서가 검색 결과에 섞여 나올 수 있습니다.

폴더별로 검색 범위를 나누려면 인덱싱 시 `collection` 태그를 붙이고, 검색 시 같은 태그로 필터링하세요.

```python
pilot.index("./project_a", collection="project_a")
pilot.index("./project_b", collection="project_b")

pilot.search("사업 계획", collection="project_a")  # project_a 문서만 대상
pilot.search("사업 계획")                          # collection 지정 없으면 전체 대상
```

`generate()`도 동일하게 `collection`을 받습니다. 지정하면 파일 경로 기반(`source_pattern`) 대신 `collection` 태그로 RAG 검색을 스코프하므로, 이후 파일을 이동해도 스코프가 깨지지 않습니다.

```python
pilot.generate(data_folder="./project_a", template="report", output="./out.hwpx", collection="project_a")
```

이미 인덱싱된 파일이라도(내용 변경 없이) `collection`을 다시 지정하면 재청킹·재임베딩 없이 태그만 갱신됩니다. 같은 파일 경로는 항상 하나의 `collection`에만 속합니다 — 여러 collection에 동시 소속시키는 것은 지원하지 않습니다.

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

### RAG 없이 벤치마크 (benchmark_from_content)

[generate_from_content](#rag-없이-생성하기-generate_from_content)처럼 인덱싱·RAG 검색 없이, 이미 준비된 콘텐츠로 여러 LLM을 비교합니다. `data_folder` 대신 `content`를 넘기고, `max_input_tokens`로 크기 가드를 걸 수 있습니다(생성 경로와 동일한 가드 — [크기 가드](#크기-가드-max_input_tokens) 참고).

```python
report = pilot.benchmark_from_content(
    content="비교할 원본 텍스트",
    template="./templates/report.hwpx",
    output="./output/result.hwpx",
    mappers={"claude": ClaudeMapper(), "openai": OpenAIMapper()},
)
print(report)
```

## MCP 서버

Claude 앱에서 smart-docgen 도구를 직접 사용하려면 MCP 서버를 설치하고 연결합니다.

### 설치
예시는 PyPI 기준. GitHub 레포 참조해 설치 시 `@ git+https://github.com/pjkwon/docpilot.git` 추가

```bash
pip install "smart-docgen[mcp]" //PyPI 기준
pip install "smart-docgen[mcp] @ git+https://github.com/pjkwon/docpilot.git" //GitHub 레포 참조 설치 기준 
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
    "smart-docgen": {
      "command": "smart-docgen-mcp",
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
| `describe_template` | 템플릿의 채움 구조 확인 — 정확한 섹션 키, 섹션별 규칙/설명, `fill_template`에 그대로 넘길 예시 dict 반환. LLM/RAG 호출 없이 즉시 반환 |
| `fill_template` | 작성된 섹션 내용을 템플릿에 채워 문서 생성 (.hwpx/.docx/.pdf). LLM/RAG 호출 없이 순수 기계적으로 조립 (output 미지정 시 `~/Documents/docpilot_YYYYMMDD_HHMMSS.hwpx`) |
| `generate_template` | 샘플 HWPX → 재사용 가능한 템플릿 생성 |
| `convert_document` | 한컴오피스 COM 자동화로 문서 포맷 변환. hwp/hwpx→docx, hwp→hwpx 지원 (Windows + 한컴오피스 설치 환경 전용). docx→hwpx는 미지원 — 아래 [알려진 이슈](#알려진-이슈) 참고 |

> **[변경됨] MCP 서버에는 RAG/인덱싱 도구(`index`, `search_documents`, `generate_document`, `analyze_coverage`, `estimate_cost` 등)가 없습니다.**
> 콘텐츠 작성(데이터 읽기·문장 구성)은 이 서버가 아니라 호출하는 에이전트(Claude)가 직접 수행하고,
> MCP 서버는 `describe_template`으로 확인한 섹션 키에 맞춰 작성된 텍스트를 `fill_template`으로
> 실제 문서 파일에 기계적으로 조립하는 역할만 합니다. 데이터 폴더 기반 RAG 자동 생성(`pilot.generate()`)과
> 검색(`pilot.search()`)은 라이브러리를 직접 호출할 때만 사용할 수 있습니다.

Claude 앱에서 자연어로 사용합니다.

> **[중요] "smart-docgen 사용 가능해?" 같은 질문은 하지 마세요.**
> Claude는 이런 질문에 학습 데이터 기반으로 답하므로 툴이 등록되어 있어도 "사용할 수 없다"고 답할 수 있습니다.
> MCP 서버는 Claude Desktop을 시작할 때 자동으로 실행됩니다.
> 바로 작업을 지시하거나, 툴 목록을 먼저 확인하려면 **"사용 가능한 smart-docgen 도구 목록 보여줘"** 라고 요청하세요.

```
# 툴 목록 확인 (처음 사용 시 권장)
사용 가능한 smart-docgen 도구 목록 보여줘.

# 템플릿 구조 확인 (문서 생성 전 첫 단계)
report 템플릿에 어떤 섹션이 있는지 보여줘.

# 데이터로 문서 생성 — Claude가 파일을 직접 읽고 섹션 내용을 작성한 뒤 fill_template 호출
/Users/me/data 폴더 내용을 참고해서 report 템플릿으로 보고서 만들어줘.
출력은 /Users/me/Documents/result.hwpx 로 저장해줘.

# 커스텀 템플릿 사용
/Users/me/data 폴더 내용으로 /Users/me/templates/proposal.hwpx 템플릿 써서
/Users/me/Documents/proposal_result.hwpx 로 저장해줘.

# 템플릿 자동 생성
/Users/me/samples 폴더의 hwpx 파일들로 템플릿 만들어서
/Users/me/templates/my_report.hwpx 로 저장해줘.

# HWP/HWPX → DOCX 변환
/Users/me/Documents/보고서.hwpx 파일 docx로 변환해줘.
```

> `describe_template`/`fill_template`은 LLM API를 호출하지 않습니다 — 데이터를 읽고 섹션 내용을
> 작성하는 것은 Claude 앱 자신의 추론이며, smart-docgen MCP 서버는 그 결과를 문서 파일로 조립만 합니다.
> 따라서 위 "데이터로 문서 생성" 같은 요청의 실제 작성 품질은 Claude 앱이 데이터 폴더를 얼마나
> 잘 읽고 요약하는지에 달려 있습니다 (RAG 검색으로 관련 청크만 추리는 라이브러리 `pilot.generate()`와의 차이점).

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
| (미설정) | `intfloat/multilingual-e5-base` | core (기본 설치 포함) | 기본값, 768차원 |
| `bge` | `BAAI/bge-m3` | `[bge]` | 최고 품질, 1024차원 |
| `bge:cuda` | `BAAI/bge-m3` (GPU) | `[bge]` | GPU 가속 |
| `openai` | `text-embedding-3-small` | `[openai]` | `OPENAI_API_KEY` 필요 |
| `openai:text-embedding-3-large` | text-embedding-3-large | `[openai]` | |
| `voyage` | `voyage-3` | `[voyage]` | `VOYAGE_API_KEY` 필요 |
| `sentence` | `paraphrase-multilingual-MiniLM-L12-v2` | core (기본 설치 포함) | (미설정)과 기본 모델이 다름 |
| `sentence:intfloat/multilingual-e5-large` | multilingual-e5-large | core (기본 설치 포함) | 더 높은 품질 |

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

`estimate_cost`는 라이브러리 전용 API입니다 — MCP 서버는 RAG 호출이 없는 `describe_template`/`fill_template` 흐름만 제공하므로 이 도구는 MCP에 노출되어 있지 않습니다.

### RAG 없이 비용 추정 (estimate_cost_from_content)

[generate_from_content](#rag-없이-생성하기-generate_from_content)용 비용 추정입니다. 인덱싱이 없으므로 `quick`의 의미가 조금 다릅니다 — `quick=True`는 바이트 기반 휴리스틱(API 호출 없음), `quick=False`(기본값)는 실제 `content`로 토큰 카운팅 API를 호출합니다.

```python
report = pilot.estimate_cost_from_content(
    content="비용을 추정할 원본 텍스트",
    template="report",
)
print(report)
```

## 예외 처리

모든 예외는 `DocPilotError`를 상속합니다.

```python
from docpilot.exceptions import (
    DocPilotError,
    IngestionError,
    MappingError,
    BuilderError,
    ConversionError,
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
