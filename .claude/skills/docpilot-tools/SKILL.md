---
name: docpilot-tools
description: docpilot 라이브러리를 이용한 문서 포맷 변환(hwp/hwpx/docx) 및 플레이스홀더 템플릿 기반 문서 생성. "hwp를 docx로 바꿔줘", "hwpx로 변환해줘", "이 데이터로 이 템플릿 채워서 문서 만들어줘" 같은 요청에 사용.
---

이 스킬은 `docpilot` 파이썬 라이브러리를 감싼 CLI(`docpilot_cli.py`, 이 스킬과 같은 폴더에 있음)를 실행해서
두 가지 작업을 수행한다. 직접 `import docpilot`을 시도하지 말고, 반드시 아래 CLI를 Bash로 실행할 것.

## 실행 환경 — 어떤 python을 쓸지 먼저 판단할 것

`docpilot`이 import 가능한 인터프리터를 찾아야 한다. 이 스킬 폴더 자체는 어느 프로젝트에 복사돼도 동작해야
하므로 경로를 하드코딩하지 말고 아래 순서로 판단한다:

1. **이 스킬이 docpilot 레포 자체 안에 있는 경우** (`docpilot/` 소스와 `.venv/`가 현재 프로젝트 루트에 있음):
   프로젝트 루트의 `.venv/Scripts/python.exe`(Windows) 또는 `.venv/bin/python`(macOS/Linux)를 쓴다.
2. **그 외의 경우** (다른 프로젝트에 `pip install git+https://github.com/pjkwon/docpilot.git`로
   설치해서 이 스킬 폴더만 복사해온 경우): 그 프로젝트에서 활성화된/기본 `python`을 쓴다.
3. 실행 전에 `<python> -c "import docpilot"`으로 import 가능 여부를 먼저 확인한다. 실패하면
   `pip install git+https://github.com/pjkwon/docpilot.git`로 설치가 필요하다고 사용자에게 안내하고 멈출 것 — 임의로 설치를 진행하지 말 것.

찾은 인터프리터로 이렇게 실행한다 (`<python>`, `<skill_dir>`은 위에서 판단한 값):

```
<python> <skill_dir>/docpilot_cli.py <command> ...
```

## API 키 — `generate`에만 필요

`convert`는 LLM을 쓰지 않으므로 `ANTHROPIC_API_KEY`/`.env` 없이도 동작한다.

`generate`는 `ANTHROPIC_API_KEY`가 필요하다 (실제 LLM API 호출 발생, 과금됨). 우선순위:
1. CLI 실행 시점의 현재 작업 디렉터리(=사용자 프로젝트 루트)와 그 상위 폴더의 `.env` 파일 (`docpilot` import 시 자동 로드됨, `docpilot` 소스 위치와 무관 — CWD 기준)
2. 셸에 이미 export된 OS 환경변수

`generate` 실행 전, `.env`와 OS 환경변수 둘 다 없으면 **직접 `.env`를 만들거나 키를 추측하지 말고** 사용자에게
어떻게 설정할지 물어볼 것. 확인은 존재 여부만 하고 키 값 자체를 출력하지 말 것.

## 1. 문서 포맷 변환 — `convert`

한컴오피스 COM 자동화로 파일 포맷을 바꾼다. LLM 호출 없음, Windows + 한컴오피스 설치 환경 전용.

```bash
<python> <skill_dir>/docpilot_cli.py convert <source> [--output PATH]
```

지원 방향:
- `.hwp` / `.hwpx` → `.docx`
- `.hwp` → `.hwpx`

**미지원**: `.docx` → `.hwpx`. 일부 한컴오피스 설치 환경에서 COM `Open()`이 DOCX를 가져오지 못하는 문제가 재현되어 보류 중이다 (원인 불명, 레포 README의 "알려진 이슈" 참고). 이 조합을 요청받으면 스크립트가 시도 없이 바로 실패 메시지를 낸다 — 사용자에게 한글 GUI에서 파일 > 열기로 직접 열어 다른 이름으로 저장하라고 안내할 것.

`--output` 생략 시 같은 폴더에 같은 이름으로, 기본 반대 포맷(`.hwp`/`.hwpx`→`.docx`, `.hwp`→`.hwpx`)으로 저장된다.

## 2. 템플릿 기반 문서 생성 — `generate`

데이터 폴더의 내용을 RAG로 검색해 템플릿의 `{{플레이스홀더}}`를 LLM으로 채운다.

```bash
<python> <skill_dir>/docpilot_cli.py generate --data <데이터폴더> --template <템플릿경로또는이름> [--output <출력경로>] \
    [--reindex] [--extra-instructions "지침"] [--instructions-doc <경로>] [--top-k 10]
```

- `--template`: `.hwpx`/`.docx`/`.pdf` 파일 경로, 또는 내장 템플릿 이름(`report`/`gonmun`/`minutes`/`proposal`, 전부 HWPX)
- `--output`: 확장자가 출력 형식을 결정 (`.hwpx`/`.docx`/`.pdf`). 템플릿이 `.docx`이고 `--output`이 `.hwpx`면 내부적으로 자동 변환 후 진행한다 (Windows + 한컴오피스 필요, 위 "미지원" 이슈가 있으면 여기서도 실패할 수 있음). **생략 시** `~/Documents/docpilot_YYYYMMDD_HHMMSS.<ext>`에 저장 (ext는 템플릿이 `.docx`/`.pdf`면 그것을 따르고, 그 외(내장 템플릿 포함)는 `.hwpx`).
- 템플릿에 `{{플레이스홀더}}`가 하나도 없으면 Reference Mode로 동작 — LLM이 문서 구조를 추론해서 임시 템플릿을 만든 뒤 생성한다.
- 데이터 폴더는 매 호출 시 자동 인덱싱된다 (변경분만, `--reindex`로 강제 가능).
- `--top-k`: RAG로 가져올 청크 수 (기본 10). 공문·회의록처럼 짧은 문서는 낮게(5 안팎), 보고서·제안서처럼 긴 문서는 높게(15~20) 설정.

**⚠️ 인덱스가 프로젝트별로 분리되지 않는다.** `generate`는 기본적으로 `~/docpilot.db` 하나를 모든 프로젝트가
공유하고, 검색도 방금 인덱싱한 `--data` 폴더로 제한되지 않는다 — RAG 검색이 이 DB에 지금까지 인덱싱된
**모든** 문서를 대상으로 실행되므로, 다른 프로젝트에서 이 스킬로 인덱싱해둔 문서 내용이 이번 생성 결과에
섞여 들어올 수 있다. 여러 프로젝트에서 이 스킬을 반복 사용한다면:
- 프로젝트별로 `DOCPILOT_DATABASE_URL` 환경변수를 다르게 지정해 DB를 분리하거나,
- 생성 결과에 낯선/무관한 내용이 섞여 있는지 사용자에게 확인을 권할 것.

## 주의사항

- `convert`는 LLM을 쓰지 않고, `generate`만 API 비용이 발생한다. 사용자가 비용에 민감해 보이면 먼저 언급할 것.
- 두 서브커맨드 모두 실패 시 exit code 1과 `[오류]`/`[실패]`/`[미지원]` 접두사가 붙은 메시지를 stdout에 출력한다. 그대로 사용자에게 전달하면 된다.
- 이 스킬은 `docpilot` 패키지에 종속적이다 — 실행할 환경에 `docpilot`이 import 가능해야 한다(이 레포 자체의 `.venv`이거나, `pip install git+https://github.com/pjkwon/docpilot.git`로 설치한 다른 환경).
