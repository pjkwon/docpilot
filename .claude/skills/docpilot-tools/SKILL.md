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
2. **그 외의 경우** (다른 프로젝트에 `pip install git+https://github.com/wynterkwon/docpilot.git`로
   설치해서 이 스킬 폴더만 복사해온 경우): 그 프로젝트에서 활성화된/기본 `python`을 쓴다.
3. 실행 전에 `<python> -c "import docpilot"`으로 import 가능 여부를 먼저 확인한다. 실패하면
   `pip install git+https://github.com/wynterkwon/docpilot.git`로 설치가 필요하다고 사용자에게 안내하고 멈출 것 — 임의로 설치를 진행하지 말 것.

찾은 인터프리터로 이렇게 실행한다 (`<python>`, `<skill_dir>`은 위에서 판단한 값):

```
<python> <skill_dir>/docpilot_cli.py <command> ...
```

`generate` 서브커맨드는 `ANTHROPIC_API_KEY`가 필요하다 (실제 LLM API 호출 발생, 과금됨).
`docpilot` 모듈 import 시점에 `load_dotenv()`가 자동 실행되는데, 이건 **CLI를 실행하는 시점의 현재 작업
디렉터리(CWD)에서 시작해서 상위 폴더로 올라가며** `.env`를 찾는다 (실측 확인됨 — `docpilot` 소스 위치와는
무관). Claude Code 계열 코드 에이전트는 세션 내내 사용자가 연 작업 폴더를 CWD로 유지하므로, 실질적으로는:

> **이 스킬을 쓰는 프로젝트(작업 폴더)의 루트에 `.env`를 두면 된다.** `docpilot` 레포 자체의 위치나
> 이 스킬 폴더의 위치와는 무관하다 — 항상 "지금 작업 중인 프로젝트의 루트" 기준이다.

없으면 셸에 이미 export된 OS 환경변수를 쓴다.

**`convert`만 쓸 거면 `.env`/`ANTHROPIC_API_KEY` 없어도 된다 (실측 확인됨).**
`docpilot_cli.py convert`도 내부적으로 `docpilot` 패키지를 import하므로 `load_dotenv()`는 똑같이 실행되지만,
`.env`가 없으면 그냥 조용히 넘어갈 뿐이고 `convert_to_docx`/`convert_to_hwpx`는 LLM을 전혀 안 써서
`ANTHROPIC_API_KEY`를 아예 참조하지 않는다. 아래 확인 절차는 **`generate`를 쓸 때만** 필요하다.

**`generate` 실행 전 확인 순서:**
1. 현재 작업 디렉터리(=사용자의 프로젝트 루트) 및 그 상위 디렉터리에 `.env` 파일이 있는지 확인.
2. 없으면 OS 환경변수로 설정되어 있는지 확인 (`echo $ANTHROPIC_API_KEY` 등). 절대 값을 출력해서 사용자에게 보여주지 말 것 — 존재 여부만 확인.
3. 둘 다 없으면 **직접 `.env` 파일을 만들거나 키를 추측하지 말고**, 사용자에게 `ANTHROPIC_API_KEY`를 어떻게 설정할지 물어볼 것 (`.env` 파일에 추가할지, 셸에 export할지). 키 값 자체는 사용자만 알고 있어야 한다.

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
<python> <skill_dir>/docpilot_cli.py generate --data <데이터폴더> --template <템플릿경로또는이름> --output <출력경로> \
    [--reindex] [--extra-instructions "지침"] [--instructions-doc <경로>] [--top-k 10]
```

- `--template`: `.hwpx`/`.docx`/`.pdf` 파일 경로, 또는 내장 템플릿 이름(`report`/`gonmun`/`minutes`/`proposal`, 전부 HWPX)
- `--output`: 확장자가 출력 형식을 결정 (`.hwpx`/`.docx`/`.pdf`). 템플릿이 `.docx`이고 `--output`이 `.hwpx`면 내부적으로 자동 변환 후 진행한다 (단, 위 "미지원" 이슈가 있으면 여기서도 실패할 수 있음).
- 템플릿에 `{{플레이스홀더}}`가 하나도 없으면 Reference Mode로 동작 — LLM이 문서 구조를 추론해서 임시 템플릿을 만든 뒤 생성한다.
- 데이터 폴더는 매 호출 시 자동 인덱싱된다 (변경분만, `--reindex`로 강제 가능).

출력 예시:
```
문서 생성 완료: C:\...\result.hwpx
모델: claude-... | 입력 4,412 + 출력 1,560 토큰 | 26.4초
```

## 주의사항

- `convert`는 LLM을 쓰지 않고, `generate`만 API 비용이 발생한다. 사용자가 비용에 민감해 보이면 먼저 언급할 것.
- 두 서브커맨드 모두 실패 시 exit code 1과 `[오류]`/`[실패]`/`[미지원]` 접두사가 붙은 메시지를 stdout에 출력한다. 그대로 사용자에게 전달하면 된다.
- 이 스킬은 `docpilot` 패키지에 종속적이다 — 실행할 환경에 `docpilot`이 import 가능해야 한다(이 레포 자체의 `.venv`이거나, `pip install git+https://github.com/wynterkwon/docpilot.git`로 설치한 다른 환경).
