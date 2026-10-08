# Pablo_v2 — Intent Engine (M1) + Skill (M2)

기존 Pablo(`Documents/Pablo/Pablo`)와 별개 프로젝트입니다.

Python 3.11, stdlib + `pypdf==6.19.0`(M3.3 PDF만, `pip install -r requirements.txt`; 다른 버전이면 PDF 텍스트 추출을 거부합니다). repo root에서 `python pablo.py ...`로 실행합니다(`src/`에서는 `python -m pablo_v2`).
Host agent 사용법은 [.claude/skills/pablo/SKILL.md](.claude/skills/pablo/SKILL.md)에 있습니다.
옵션(`--json`, `--dir`, `--llm`, `--model`)은 subcommand 뒤에 붙입니다.

```
python pablo.py login [--device]      # Codex(ChatGPT) 브라우저 로그인, --device는 헤드리스용
python pablo.py status
python pablo.py demo [--llm]          # M1.1 acceptance 대화
python pablo.py say "메시지" [--llm] [--agent] [--scope task]
python pablo.py show | candidates | history | promote K4 | reject K4

python pablo.py task "<작업>" [--checks JSON]       # 완료된 check 재사용 + 빠진 SourceCheck만 생성 (없으면 Codex analyzer)
python pablo.py waive SC3 --reason "<이유>"          # 불필요한 check를 흔적과 함께 제외
python pablo.py search SC1 "<target>" "<query>" --tier 1 --found|--not-found
python pablo.py check SC1 VERIFIED "<결론>" [--sources JSON] [--stop-reason R]
python pablo.py plan T1 --steps JSON
python pablo.py act T1 "<행동>" [--step P1.1] [--why "<근거>"]   # ALLOW | WARN | BLOCK
python pablo.py decide ACT1 proceed|defer|reject [--reason "<이유>"]   # host 결정 기록
python pablo.py gate T1 "<행동>"                  # desktop host용 act: 현재 plan step + 사람이 읽는 이유(규칙/ID 없음) + 적용 intent
python pablo.py record ACT1 "<한 일>" [--not-executed] [--files ...] [--test "name=pass"] [--observe "..."] [--error "..."]
python pablo.py review EX1                       # PostReview: 관찰 + update proposal (Intent/Plan은 안 바꿈)
python pablo.py view T1 [--html]           # --html: 읽기 전용 대화형 화면 (작업 목록 | 대화 | Context Panel), view-T1.html#E1로 근거 바로 열기
python pablo.py source <url>                     # 원문 캡처 + 스냅샷 -> SRC1 (version = 정규화 텍스트 hash)
python pablo.py anchor SRC1 "<원문 구절>" [--near "<옆 문구>"]   # -> E1 (없거나 모호하면 거절)
python pablo.py link E1 SC1 supports             # supports|contradicts|verifies|implements|derived_from
python pablo.py resolve E1 | --all               # live 원문에서 다시 찾기 -> VALID | STALE | UNRESOLVED
python pablo.py evidence E1
python pablo.py source paper.pdf               # M3.3: PDF 사본 + 쪽별 텍스트(pypdf) -> SRC1 (version = 파일 bytes hash)
python pablo.py anchor SRC1 "<원문 구절>" [--page 9]   # PDF: 공백·하이픈 무시하고 매칭, 쪽/쪽 안 위치 저장
python pablo.py ask T1 "<질문>" [--source SRC1]  # M3.3: judge가 인용을 고르고 Pablo가 anchor -> 답 + [n] (못 찾은 인용은 뺀다)
```

JSON 인자는 inline 또는 `@file.json`. 출력은 `--json`이면 `{"ok": ...}`, exit 2 = Pablo가 거절.
State: `--dir`(기본 `.pablo/`)의 `intent.json`, `skill.json`. Test: `python tests/intent/test_engine.py`, `python tests/skill/test_skill.py` (`PABLO_LLM=1`이면 Codex acceptance도 실행), `python tests/skill/test_evidence.py` (`PABLO_NET=1`이면 live 문서도 확인).

| file | role |
|------|------|
| `src/pablo_v2/auth.py` | Auth: Codex 로그인 / 상태 / 로그아웃 |
| `src/pablo_v2/llm.py` | LLM Provider: `CodexProvider.complete_json(prompt, schema)` |
| `src/pablo_v2/intent/models.py` | Intent Spec schema |
| `src/pablo_v2/intent/extract.py` | LLM prompt + 휴리스틱 extractor |
| `src/pablo_v2/intent/policy.py` | commit / pending / ignore 규칙 |
| `src/pablo_v2/intent/engine.py` | `IntentEngine` — M2가 호출하는 경계 |
| `src/pablo_v2/intent/render.py` | 사람용 뷰 |
| `src/pablo_v2/skill/models.py` | M2 contract: `SourceCheck`, `Plan`, `ActionProposal` |
| `src/pablo_v2/skill/judge.py` | LLM semantic judge (사실만 판정, verdict 없음) |
| `src/pablo_v2/skill/guard.py` | 결정적 규칙: research 완료 조건(R01-R04), action verdict(G01-G10) |
| `src/pablo_v2/skill/evidence.py` | M3.1 결정적 anchor: 텍스트 정규화, hash, locate, resolve(VALID/STALE/UNRESOLVED) |
| `src/pablo_v2/skill/pdf.py` | M3.3 PDF anchor: 쪽 텍스트, 매칭 key(NFKC, 공백·하이픈 제거), locate/resolve |
| `src/pablo_v2/skill/viewer.py` | 읽기 전용 대화형 화면: 작업 목록 | 대화(Research/Guard/실행을 메시지로, 인용 [1]) | Context Panel 하나(Source 캡처 원문 highlight + 원본 ↗ text fragment, Intent, Plan, 왜? Trace 교체) |
| `src/pablo_v2/skill/skill.py` | `PabloSkill` — host agent가 호출하는 경계 |
| `desktop/main.js` | M3.2.3 desktop host(Electron): viewer를 띄우고 Source panel만 `<webview>`로 실제 원문을 연다 |
| `desktop/agent.js` | M4.0 상주 `codex app-server` 하나: `initialize` → 작업마다 자기 thread(`thread/start` 또는 저장된 thread `thread/resume`) → 메시지마다 `turn/start`, delta streaming, crash 시 Error 후 다음 메시지에서 재시작 + `thread/resume`. 승인 요청은 Controller로 |
| `desktop/controller.js` | M4.2 Pablo Controller: 승인 요청 → 행동 설명 한 줄 → `gate`(Guard) → accept/decline, WARN은 대화의 [진행]/[취소]를 기다린다. 끝난 item → `record` + `review` |
| `desktop/siwc.js` | M4.1 Sign in with ChatGPT(main process 전용): PKCE + state + nonce, loopback callback, ID token(JWKS) 검증, 발급된 `client_id` 재사용, safeStorage 암호화 저장, 만료 5분 전 refresh(single flight), plan usage 확인(모델 목록 + 짧은 추론 1회), revoke 후 삭제 |
| `desktop/locate.js` | 원문에 주입하는 유일한 script: 근거 탐색(FOUND/AMBIGUOUS/NOT_FOUND), highlight, scroll, 결과 반환 |

Desktop (저장소 루트에서): `npm --prefix desktop install`, `npm --prefix desktop start`. 인자 없이 띄우면 앱 상태 폴더(`userData/state`)를 쓴다. 마지막 작업을 다시 열고, 작업이 없으면 빈 화면을 보여 준다. 작업은 앱에서 만든다(+ 새 작업). 첫 줄이 작업 목표(이름)이고, 나머지 줄은 그 작업만의 기준이 된다(`say --scope task`, 다른 작업에는 적용되지 않음). 작업마다 📎 PDF(M3.3 `source`)와 📁 작업 폴더(Pablo 저장소와 겹치지 않는 폴더)를 고른다. 이 선택은 `state/desktop.json`에 남는다. 입력창은 하나다. PDF만 있으면 `ask`, 폴더만 있으면 agent, 둘 다 있으면 사용자에게 묻는다. 작업 폴더가 있는 작업은 요청마다 그 요청을 plan 단계로 기록한다. Guard·실행·PostReview가 끝나면 앱이 `state`를 다시 읽어 기준/계획/왜?를 갱신한다(화면 재생성 없음). `npm --prefix desktop start -- <view.html>`은 debug/export용으로 남는다(경로는 `desktop/` 기준). App acceptance(M5.1, 실제 계정): `npm --prefix desktop run check -- --app <shot-dir>`. Check: `npm --prefix desktop run check -- ../.pablo/host2/view-T2.html` (live 문서 필요). SIWC check(offline, 가짜 OAuth/API 서버): 끝에 `--auth`. Agent check(실제 계정, 수 분): 먼저 `npm start`로 앱에서 ChatGPT에 연결하고 앱을 닫은 뒤 끝에 `--agent`. 두 번 돌리면 두 번째가 이전 thread를 resume한다. Guard check(실제 계정, 수 분, 임시 fixture 폴더): 끝에 `--guard` — ALLOW 실행, WARN은 [진행] 전까지 대기, BLOCK은 부작용 없음, record/review, 작업별 thread, 재시작 후 resume. `--guard --coverage`: git fixture에서 읽기/쓰기/삭제/이동/셸 쓰기 명령 10개를 보내고, 승인 요청 없이 실행된 명령과 바뀐 파일을 표로 찍는다. Guard를 안 거친 부작용이 하나라도 있으면 실패한다.

Desktop은 `codex login`을 쓰지 않는다. Continue with ChatGPT → 시스템 브라우저 승인 → Connected · Plan usage enabled → `codex app-server`를 SIWC access token(`ACCESS_TOKEN`, `openai_chatgpt_plan` provider)과 Pablo 전용 `CODEX_HOME`으로 띄운다. 토큰은 main process에만 있고 renderer는 `{state, error}`만 받는다. userData(`%APPDATA%/pablo-desktop`): `host.json`(host id, 발급된 client_id, 계정 — 비밀 아님), `credentials.bin`(토큰, DPAPI 암호화), `thread.json`(작업(state 폴더#task id)별 thread id·cwd·sandbox, 고른 모델), `codex/`(app-server 상태, Windows는 `config.toml`에 `[windows] sandbox = "unelevated"` — 없으면 셸 읽기가 전부 "blocked by policy"). 모델 목록은 계정 카탈로그(`/v1/models`, `visibility:"list"`)를 `display_name`으로 보여 준다. 모델이 붐비면(serverOverloaded) 자동으로 다시 보내지 않는다. 아무 행동도 실행되지 않은 실패에만 "다른 모델로 다시 시도" 링크를 보여 준다. 토큰 갱신이나 401이면 app-server를 새 토큰으로 다시 띄우고 `thread/resume`한다. 연결 해제는 refresh token을 revoke하고 credential·thread를 지운 뒤 agent를 멈춘다. 대화는 기본으로 읽기 전용 sandbox이고 승인 요청은 거절한다. `PABLO_WORKSPACE=<버릴 수 있는 폴더>`를 주면 그 폴더에서만 `workspace-write` + `untrusted`로 돌고, 모든 승인 요청이 Pablo Guard를 거친다: ALLOW는 조용히 실행, WARN은 "이 작업은 현재 기준과 충돌할 가능성이 있습니다. [진행] [취소]", BLOCK은 이유와 함께 거절. 실행/거절 모두 ExecutionRecord + PostReview를 남긴다. Task 범위 제약이 project 제약과 conflict면 그 task에서만 덮는다(soft만; hard는 deviation). 다른 task와 전역 상태는 그대로다. Pablo 저장소나 프로젝트 폴더(또는 그 상위)는 workspace로 받지 않는다. 작업 폴더 밖 권한 요청은 Guard 없이 거절한다. `pablo login`/`codex exec` 경로(`auth.py`, `llm.py`)는 CLI fallback으로 남는다. 브라우저로 그냥 열면 기존 캡처 원문 + ↗ 동작 그대로다.

M3.3 PDF Evidence: PDF를 캡처한 대화에서는 composer 질문이 `ask`로 간다. 답의 [n]을 누르면 Source panel이 pdf.js(`pdfjs-dist`)로 캡처한 PDF를 그 쪽에서 그리고, 인용 문장이나 표의 한 행(그 행 text item bbox의 합)을 칠한다. 위치를 못 찾으면(NOT_FOUND/AMBIGUOUS/오류) 추출 텍스트 snapshot으로 돌아간다. PDF와 pdf.js 파일은 `pablo://`(기본 session, 화이트리스트, 읽기 전용)로만 읽는다. 평가: `python tests/skill/test_pdf.py`, `python tests/eval/linearrag_eval.py`(keyword baseline), `npm --prefix desktop run check -- --pdf [shot-dir]`(A: gold 19개 → 쪽/하이라이트/noise/latency, offline), 끝에 `--ask`를 붙이면 실제 계정으로 10문항을 composer에 넣고 B 평가 표를 찍는다. Gold: `tests/eval/linearrag_gold.json`. M3.3.1: 정량 주장과 표 수치를 함께 인용하면 답이 수치를 직접 대조하고 어긋남을 밝힌다(ask 프롬프트의 일반 규칙). 채점은 `consistency`(불일치를 말했나)와 `need_all`(양쪽 근거를 다 인용했나)을 본다.

Packaging (M6, Windows x64, 서명 없음): build venv를 한 번 만든다. `python -m venv build/venv`, `build/venv/Scripts/python -m pip install -r requirements-build.txt`. 그다음 `npm --prefix desktop run backend`(PyInstaller onedir → `build/dist/pablo-backend`), `npm --prefix desktop run package`(→ `desktop/out/Pablo-win32-x64/Pablo.exe`), `npm --prefix desktop run make`(→ `desktop/out/make/squirrel.windows/x64/PabloSetup.exe`). 설치본은 `resources/`의 backend와 고정된 Codex(`@openai/codex@0.152.0-win32-x64`)만 실행한다. 시스템 Python·PATH의 codex·저장소는 쓰지 않는다. 쓰기는 userData(`%APPDATA%/pablo-desktop`)에만 한다. Release check(실제 계정, 수 분, 먼저 앱에서 로그인): `ELECTRON_RUN_AS_NODE=1 desktop/node_modules/electron/dist/electron.exe desktop/rc.js <Pablo.exe> <shot-dir>`. 빈 PATH·임시 userData로 A(WARN/BLOCK/review)·B(PDF p.9 하이라이트)·재시작 복원을 확인한다.

## Backlog (infra)

- 읽기 명령도 Guard를 거친다(`untrusted`). M5.0 실측: 읽기 ALLOW 10.9초, 읽기 WARN 6.0초+사용자 클릭, 수정 WARN 약 19초(클릭 포함), BLOCK 10.1초. judge가 단순 읽기(`Get-Item`)를 soft 제약과 엮어 WARN을 내기도 한다. 결정적 read-only fast path(`Get-Content`/`Get-ChildItem`/`git status`/`git diff` 허용 목록)는 검토 후 보류했다: `-Command` 문자열은 `;`·파이프·리다이렉트·`$()`로 연결될 수 있고, `git status`/`git diff`는 저장소 설정(fsmonitor, diff/textconv driver)으로 코드를 실행할 수 있으며, Guard를 건너뛰면 "X는 읽지 마" 같은 intent 제약 검사도 빠져 정책 변경이 된다. backlog로 남긴다.
- Intent scope 소유자 명시: 지금은 task 생성 시각 구간 + 명시 참조로 scope를 정한다(`PabloSkill.intent_applies`). 임시 구현이다. 작업이 겹치면 깨진다. Intent/Candidate에 `scope_ref`(task_id)를 저장하는 방향을 검토한다. M1 schema 변경이 필요하다.
- 인증/호출 경로 전환: 상주 `codex app-server`는 M4.0에서 desktop에 붙였다(`desktop/agent.js`). M4.1에서 in-app Sign in with ChatGPT와 토큰 갱신 시 재시작 + `thread/resume`을 붙였다. M4.2에서 승인 요청에 Guard를 붙였다(`desktop/controller.js`). 근거: https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server
