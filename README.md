# docpilot

데이터 폴더와 템플릿을 입력하면 LLM이 내용을 파악해 완성된 문서를 생성하는 파이썬 라이브러리입니다.

## 특징

- **다양한 입력 소스** — TXT, MD, RST, CSV, PDF (OCR 폴백 포함), PPTX, 이미지(JPG/PNG 등)
- **구조화 인제스트** — HWPX·DOCX 스타일 기반 헤딩, PPTX 불릿 계층, PDF 폰트 크기 기반 헤딩 감지, 의미 경계 청킹으로 RAG 검색 품질 향상
- **다양한 출력 포맷** — HWPX, DOCX, PDF
- **LLM 교체 가능** — Claude · OpenAI · Gemini · Grok · Ollama, 동일 인터페이스
- **벡터 + 형태소 검색** — sqlite-vec 임베딩 검색 (기본), pgvector (선택), kiwipiepy 형태소 검색
- **임베딩 제공자 선택** — OpenAI · Voyage AI · BGE(로컬) · sentence-transformers(로컬), 동일 인터페이스
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
pip install "docpilot @ git+https://github.com/wynterkwon/docpilot.git"
pip install "docpilot[mcp] @ git+https://github.com/wynterkwon/docpilot.git"
pip install "docpilot[pdf,mcp] @ git+https://github.com/wynterkwon/docpilot.git"
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
)
```

## 데이터 인덱싱

지원 입력 파일 형식: `.txt`, `.md`, `.rst`, `.csv`, `.hwpx`, `.pdf`, `.pptx`, `.docx`, `.jpg`, `.png`, `.jpeg`, `.bmp`, `.tiff`, `.webp`

```python
pilot.index("./data")   # 폴더 내 모든 지원 파일을 재귀적으로 인덱싱
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

```python
# 이름으로 내장 템플릿 사용
pilot.generate(
    data_folder="./data",
    template="report",        # 파일 경로 대신 이름 지정
    output="./output/report.hwpx",
)

# 사용 가능한 내장 템플릿 목록 확인
print(DocPilot.list_templates())
# {'report': '일반 보고서 — ...', 'gonmun': '공문 — ...', 'minutes': '회의록 — ...'}
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

```python
from docpilot.search import exact, embedding, morpheme

# 키워드 정확 검색
results = exact.search("사업 계획")

# 형태소 기반 검색 — pip install "docpilot[morpheme]"
results = morpheme.search("사업 계획")

# 벡터 유사도 검색 — embed_fn을 아래 임베딩 제공자 중 선택해서 전달
from docpilot.search.embedding import openai_embed_fn
results = embedding.search("사업 계획", embed_fn=openai_embed_fn())
```

## 임베딩 제공자

docpilot은 벡터 검색(RAG)에 사용할 임베딩 제공자를 자유롭게 선택할 수 있습니다.  
`DocPilot(embed_fn=...)` 또는 `embedding.search(embed_fn=...)`에 팩토리 함수를 전달합니다.

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

| 제공자 | 팩토리 함수 | 기본 모델 | 필요 패키지 |
|--------|------------|-----------|------------|
| BGE (BAAI) | `bge_embed_fn()` | `BAAI/bge-m3` | `[bge]` |
| sentence-transformers | `sentence_embed_fn()` | `paraphrase-multilingual-MiniLM-L12-v2` | `[sentence]` |

```python
from docpilot.search.embedding import bge_embed_fn, sentence_embed_fn

# BGE — pip install "docpilot[bge]" / 한국어 포함 다국어 최상위권
embed_fn = bge_embed_fn()                                       # CPU, BAAI/bge-m3
embed_fn = bge_embed_fn(device="cuda", use_fp16=True)          # GPU 가속

# sentence-transformers — pip install "docpilot[sentence]" / 경량 다국어
embed_fn = sentence_embed_fn()                                  # 384차원, ~90MB
embed_fn = sentence_embed_fn(model="multilingual-e5-large", device="cuda")

pilot = DocPilot(llm="claude", embed_fn=embed_fn)
```

> **모델 캐시**: 로컬 모델은 첫 실행 시 HuggingFace에서 자동 다운로드되어 `~/.cache/huggingface/`에 저장됩니다. 이후 실행부터는 캐시에서 불러옵니다.

> **임베딩 차원**: `sentence_embed_fn()` 기본 모델은 **384차원** 벡터를 출력합니다. 임베딩 제공자를 변경하거나 처음 설정하는 경우, `EMBEDDING_DIM`과 vec_chunks 테이블 차원이 일치해야 합니다. 기존 DB가 있다면 `vec_chunks`를 DROP 후 `client.create_tables()`로 재생성하세요.

### 커스텀 임베딩

`Callable[[str], list[float]]` 인터페이스를 맞추면 어떤 임베딩 모델이든 연결할 수 있습니다.

```python
# 예시: 직접 구현한 임베딩 함수
def my_embed_fn(text: str) -> list[float]:
    ...
    return vector  # list[float]

pilot = DocPilot(llm="claude", embed_fn=my_embed_fn)
```

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
예시는 PyPI 기준. GitHub 설치 시 `@ git+https://github.com/wynterkwon/docpilot.git` 추가

```bash
pip install "docpilot[mcp]"
```

### Claude Desktop 연결

`claude_desktop_config.json`에 아래 블록을 추가합니다.

- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "docpilot": {
      "command": "docpilot-mcp",
      "env": {
        "ANTHROPIC_API_KEY": "sk-ant-...",
        "DOCPILOT_DATABASE_URL": "sqlite:////Users/yourname/docpilot.db"
      }
    }
  }
}
```

> **경로는 모두 절대 경로로 지정하세요.** Claude Desktop이 MCP 서버를 실행하는 작업 디렉터리는 사용자 프로젝트 폴더가 아닙니다. `DOCPILOT_DATABASE_URL` 미지정 시 기본값은 `~/docpilot.db`(홈 디렉터리)입니다. `generate` 도구의 `data_folder`, `output`, 커스텀 템플릿 경로도 절대 경로로 전달해야 합니다.

### macOS 파일 접근 권한

macOS는 앱별로 `~/Documents`, `~/Desktop`, `~/Downloads` 접근을 별도로 허가받아야 합니다. MCP 서버는 Claude Desktop의 자식 프로세스이므로 Claude Desktop에 권한이 없으면 해당 폴더의 파일을 읽거나 쓸 수 없습니다.

**시스템 환경설정 → 개인 정보 보호 및 보안 → 파일 및 폴더** (또는 **전체 디스크 접근**)에서 Claude에 필요한 폴더 권한을 부여하세요.

홈 디렉터리 바로 아래(`~/docpilot.db`, `~/data/` 등)는 별도 허가 없이 접근 가능합니다.

설정 저장 후 Claude Desktop을 재시작하면 다음 도구가 활성화됩니다.

| 도구 | 설명 |
|------|------|
| `generate` | 데이터 폴더 + 템플릿 → 문서 생성 |
| `generate_template` | 샘플 HWPX → 재사용 가능한 템플릿 생성 |
| `estimate_cost` | 생성 전 API 토큰 비용 추정 |

Claude 앱에서 자연어로 사용합니다.

```
# 내장 템플릿 사용 — 이름만 지정
/Users/me/data 폴더 내용으로 report 템플릿 써서 보고서 만들어줘.
출력은 /Users/me/Documents/result.hwpx 로 저장해줘.

# 커스텀 템플릿 사용 — 절대 경로로 지정
/Users/me/data 폴더 내용으로 /Users/me/templates/proposal.hwpx 템플릿 써서
/Users/me/Documents/proposal_result.hwpx 로 저장해줘.

# 템플릿 자동 생성
/Users/me/samples 폴더의 hwpx 파일들로 템플릿 만들어서
/Users/me/templates/my_report.hwpx 로 저장해줘.
```

### 환경변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `ANTHROPIC_API_KEY` | — | Claude API 키 (필수) |
| `DOCPILOT_LLM` | `claude` | LLM 제공자 (`claude` / `openai` / `gemini` / `grok` / `ollama`) |
| `DOCPILOT_MODEL` | 제공자 기본 | 특정 모델 지정 (예: `claude-opus-4-8`) |
| `DOCPILOT_DATABASE_URL` | `~/docpilot.db` | DB 연결 문자열 (절대 경로 권장) |

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
