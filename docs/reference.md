# Pablo 개발 참고서

> 이 문서는 0.8.0까지 저장소 `README.md`였던 개발 기록입니다. 명령, 상태 파일, 점검 시나리오, 설계 결정을 마일스톤(M1–M7, 0.8) 순서로 적었습니다. 제품 소개와 설치는 [README](../README.md)에 있습니다.

## Pablo_v2 — Intent Engine (M1) + Skill (M2)

기존 Pablo(`Documents/Pablo/Pablo`)와 별개 프로젝트입니다.

Python 3.11, stdlib + `pypdf==6.19.0`(M3.3 PDF만, `pip install -r requirements.txt`; 다른 버전이면 PDF 텍스트 추출을 거부합니다). repo root에서 `python pablo.py ...`로 실행합니다(`src/`에서는 `python -m pablo_v2`).
Host agent 사용법은 [.claude/skills/pablo/SKILL.md](../.claude/skills/pablo/SKILL.md)에 있습니다.
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
| `desktop/checkpoint.js` | M7 작업 폴더 체크포인트: 상태 폴더 안 shadow git(`state/checkpoints/<task>.git`, 작업 폴더를 work tree로) — 턴 전후 tree, 바뀐 파일, diff, 되돌리기. 사용자 `.git`은 건드리지 않는다 |

Desktop (저장소 루트에서): `npm --prefix desktop install`, `npm --prefix desktop start`. 인자 없이 띄우면 앱 상태 폴더(`userData/state`)를 쓴다. 마지막 작업을 다시 열고, 작업이 없으면 빈 화면을 보여 준다. 작업은 앱에서 만든다(+ 새 작업). 첫 줄이 작업 목표(이름)이고, 나머지 줄은 그 작업만의 기준이 된다(`say --scope task`, 다른 작업에는 적용되지 않음). 작업마다 📎 PDF(M3.3 `source`)와 📁 작업 폴더(Pablo 저장소와 겹치지 않는 폴더)를 고른다. 이 선택은 `state/desktop.json`에 남는다. 입력창은 하나다. PDF만 있으면 `ask`, 폴더만 있으면 agent, 둘 다 있으면 사용자에게 묻는다. 작업 폴더가 있는 작업은 요청마다 그 요청을 plan 단계로 기록한다. Guard·실행·PostReview가 끝나면 앱이 `state`를 다시 읽어 기준/계획/왜?를 갱신한다(화면 재생성 없음). `npm --prefix desktop start -- <view.html>`은 debug/export용으로 남는다(경로는 `desktop/` 기준). App acceptance(M5.1, 실제 계정): `npm --prefix desktop run check -- --app <shot-dir>`. Check: `npm --prefix desktop run check -- ../.pablo/host2/view-T2.html` (live 문서 필요). SIWC check(offline, 가짜 OAuth/API 서버): 끝에 `--auth`. Agent check(실제 계정, 수 분): 먼저 `npm start`로 앱에서 ChatGPT에 연결하고 앱을 닫은 뒤 끝에 `--agent`. 두 번 돌리면 두 번째가 이전 thread를 resume한다. Guard check(실제 계정, 수 분, 임시 fixture 폴더): 끝에 `--guard` — ALLOW 실행, WARN은 [진행] 전까지 대기, BLOCK은 부작용 없음, record/review, 작업별 thread, 재시작 후 resume. `--guard --coverage`: git fixture에서 읽기/쓰기/삭제/이동/셸 쓰기 명령 10개를 보내고, 승인 요청 없이 실행된 명령과 바뀐 파일을 표로 찍는다. Guard를 안 거친 부작용이 하나라도 있으면 실패한다.

Desktop은 `codex login`을 쓰지 않는다. Continue with ChatGPT → 시스템 브라우저 승인 → Connected · Plan usage enabled → `codex app-server`를 SIWC access token(`ACCESS_TOKEN`, `openai_chatgpt_plan` provider)과 Pablo 전용 `CODEX_HOME`으로 띄운다. 토큰은 main process에만 있고 renderer는 `{state, error}`만 받는다. userData(`%APPDATA%/pablo-desktop`): `host.json`(host id, 발급된 client_id, 계정 — 비밀 아님), `credentials.bin`(토큰, DPAPI 암호화), `thread.json`(작업(state 폴더#task id)별 thread id·cwd·sandbox, 고른 모델), `codex/`(app-server 상태, Windows는 `config.toml`에 `[windows] sandbox = "unelevated"` — 없으면 셸 읽기가 전부 "blocked by policy"). 모델 목록은 계정 카탈로그(`/v1/models`, `visibility:"list"`)를 `display_name`으로 보여 준다. 모델이 붐비면(serverOverloaded) 자동으로 다시 보내지 않는다. 아무 행동도 실행되지 않은 실패에만 "다른 모델로 다시 시도" 링크를 보여 준다. 토큰 갱신이나 401이면 app-server를 새 토큰으로 다시 띄우고 `thread/resume`한다. 연결 해제는 refresh token을 revoke하고 credential·thread를 지운 뒤 agent를 멈춘다. 대화는 기본으로 읽기 전용 sandbox이고 승인 요청은 거절한다. `PABLO_WORKSPACE=<버릴 수 있는 폴더>`를 주면 그 폴더에서만 `workspace-write` + `untrusted`로 돌고, 모든 승인 요청이 Pablo Guard를 거친다: ALLOW는 조용히 실행, WARN은 "이 작업은 현재 기준과 충돌할 가능성이 있습니다. [진행] [취소]", BLOCK은 이유와 함께 거절. 실행/거절 모두 ExecutionRecord + PostReview를 남긴다. Task 범위 제약이 project 제약과 conflict면 그 task에서만 덮는다(soft만; hard는 deviation). 다른 task와 전역 상태는 그대로다. Pablo 저장소나 프로젝트 폴더(또는 그 상위)는 workspace로 받지 않는다. 작업 폴더 밖 권한 요청은 Guard 없이 거절한다. `pablo login`/`codex exec` 경로(`auth.py`, `llm.py`)는 CLI fallback으로 남는다. 브라우저로 그냥 열면 기존 캡처 원문 + ↗ 동작 그대로다.

M3.3 PDF Evidence: PDF를 캡처한 대화에서는 composer 질문이 `ask`로 간다. 답의 [n]을 누르면 Source panel이 pdf.js(`pdfjs-dist`)로 캡처한 PDF를 그 쪽에서 그리고, 인용 문장이나 표의 한 행(그 행 text item bbox의 합)을 칠한다. 위치를 못 찾으면(NOT_FOUND/AMBIGUOUS/오류) 추출 텍스트 snapshot으로 돌아간다. PDF와 pdf.js 파일은 `pablo://`(기본 session, 화이트리스트, 읽기 전용)로만 읽는다. 평가: `python tests/skill/test_pdf.py`, `python tests/eval/linearrag_eval.py`(keyword baseline), `npm --prefix desktop run check -- --pdf [shot-dir]`(A: gold 19개 → 쪽/하이라이트/noise/latency, offline), 끝에 `--ask`를 붙이면 실제 계정으로 10문항을 composer에 넣고 B 평가 표를 찍는다. Gold: `tests/eval/linearrag_gold.json`. M3.3.1: 정량 주장과 표 수치를 함께 인용하면 답이 수치를 직접 대조하고 어긋남을 밝힌다(ask 프롬프트의 일반 규칙). 채점은 `consistency`(불일치를 말했나)와 `need_all`(양쪽 근거를 다 인용했나)을 본다.

Packaging (M6, Windows x64, 서명 없음): build venv를 한 번 만든다. `python -m venv build/venv`, `build/venv/Scripts/python -m pip install -r requirements-build.txt`. 그다음 `npm --prefix desktop run backend`(PyInstaller onedir → `build/dist/pablo-backend`), `npm --prefix desktop run package`(→ `desktop/out/Pablo-win32-x64/Pablo.exe`), `npm --prefix desktop run make`(→ `desktop/out/make/squirrel.windows/x64/PabloSetup.exe`). 설치본은 `resources/`의 backend와 고정된 Codex(`@openai/codex@0.152.0-win32-x64`)만 실행한다. 시스템 Python·PATH의 codex·저장소는 쓰지 않는다. 쓰기는 userData(`%APPDATA%/pablo-desktop`)에만 한다. Release check(실제 계정, 수 분, 먼저 앱에서 로그인): `ELECTRON_RUN_AS_NODE=1 desktop/node_modules/electron/dist/electron.exe desktop/rc.js <Pablo.exe> <shot-dir>`. 빈 PATH·임시 userData로 A(WARN/BLOCK/review)·B(PDF p.9 하이라이트)·C(0.8: 시연 폴더 재현 점검 → top-k 행의 파일:줄 → 코드 패널)·D(0.8: PDF 두 편 → 비교표 → 칸의 쪽, 두 번째 논문은 `--paper2=<pdf>`, 기본은 D3 정답 세트의 논문)·재시작 복원을 확인한다.

## M7 제품 다듬기 (desktop, 0.7.0)

릴리스 문서·시연 시나리오·알려진 제한·깨끗한 PC 체크리스트는 `release/0.7.0/`에 있다. 시연용 재현 폴더는 `release/0.7.0/demo-repro/`(일부러 논문과 다른 값: top_k 10, Medical 없음, 2Wiki 61.20). 0.8.0(아래의 "0.8" 항목들)의 문서는 `release/0.8.0/`에 있고, 시연 폴더는 0.7.0 것을 그대로 쓴다.

- 대화 기록: `state/chat.json`(main.js만 쓴다, `viewer.py`가 읽는다)에 사용자 메시지, 에이전트 답(중지/오류 포함), PDF 질문과 답한 check id, 변경/되돌리기가 남는다. 앱을 다시 열면 기록과 Guard 카드가 일어난 순서대로 하나의 대화로 보인다.
- 중지: 에이전트가 일하는 동안 보내기 버튼이 ■가 된다. `turn/interrupt`로 턴을 끝내고, 열린 WARN 카드는 취소로 답한다. 답 아래에 "중지했습니다."가 남는다.
- WARN/BLOCK 카드는 바뀌는 내용 자체를 보여 준다: 파일 변경은 diff(Guard가 읽는 1500자보다 길게, 새 파일은 +, 지운 파일은 −), 명령은 셸 래퍼를 뺀 명령.
- 🌐 인터넷(작업마다, 기본 차단): Codex의 workspace sandbox는 네트워크가 꺼져 있다(실측: 연결 거부). 허용하면 턴마다 `sandboxPolicy: {type: "workspaceWrite", networkAccess: true}`를 보낸다(실측: HTTPS 200). 허용해도 명령은 하나하나 Guard를 거친다. 승인된 명령도 작업 폴더와 TEMP 밖에는 쓰지 못한다(실측: Permission denied). `npm --prefix desktop run check -- --guard --sandbox`(실제 계정, `PABLO_NET=1`이면 허용)로 다시 잴 수 있다.
- 체크포인트와 되돌리기: 작업 폴더가 있는 턴은 시작 전과 끝난 뒤의 폴더를 shadow git tree로 남긴다. 바뀐 파일이 있으면 대화에 "📝 파일 N개가 바뀌었습니다" 카드가 붙고 [변경 보기](diff)와 [되돌리기]를 준다. 그 뒤에 같은 파일이 다시 바뀌었으면 덮어쓰지 않고 거절한다. 되돌린 사실은 다음 요청 때 에이전트에게 한 번 알린다. `node_modules/`, 가상환경, 캐시, 가중치·배열 데이터(`*.pt`, `*.ckpt`, `*.safetensors`, `*.npy`, `*.parquet` 등)는 체크포인트에 넣지 않는다. git이 없으면 이 기능만 꺼진다.
- 에이전트에게 주는 근거(`pablo brief T1`): 그 작업의 기준(반드시/가능하면)과 Pablo가 원문에서 위치를 확인한 사실(인용 [n]은 "LinearRAG p.9" 같은 출처로 바꿈)을 요청 앞에 붙인다. 같은 thread에 같은 내용은 다시 보내지 않는다(`thread.json`에 hash). 그 사실들의 check는 요청이 되는 plan 단계의 basis가 되어 Guard가 근거로 읽는다. 진행 중 WARN/BLOCK 카드에도 관련 근거 [n]이 붙어 누르면 원문이 열린다.
- 대화 속 기준: 앱에서 보낸 메시지는 문장별로 `say --request --task T1`을 거친다. "X 해줘"는 목표가 되지 않는다(요청은 plan 단계). 요청과 함께 쓴 금지·조건("…알려줘. 파일은 읽지 마.")은 그 요청에만 딸린 것으로 보고 남기지 않는다. "절대/앞으로/항상/가능하면" 같은 지속 표시가 있거나 기준만 따로 말한 메시지만 그 작업의 intent가 된다(`extract.standing_criteria`). 패키징한 앱의 rc 실행에서 "파일은 읽지 마"가 hard 기준으로 남던 것을 보고 이렇게 바꿨다. 에이전트가 시작하기 전에 기록되므로 같은 턴의 Guard와 brief가 바로 쓴다. 대화에 "📌 작업 기준에 추가했습니다"가 붙는다. 휴리스틱 금지 표현에 "~지 마", "~지 말고", "안 돼", "금지"를 더했다.
- 보류된 기준(B4): "PyTorch가 좀 편할 것 같긴 한데"처럼 애매하게 말한 기준은 M1 정책대로 보류(pending)된다. 앱은 그 메시지 아래와 대화 끝 "결정이 필요합니다" 카드에 [기준으로 추가] / [무시]를 보여 준다(`promote` / `reject`). 정한 뒤에는 버튼이 사라진다.
- 작업 범위: `--task`로 말한 작업을 기준에 직접 남긴다(Candidate features `task`). 예전 작업으로 돌아가 말해도 그 작업에만 적용된다. 작업 이름 없이 말한 기준(CLI `say`)은 작업 목록 순서로 구간을 정하고, 기록 시각은 밀리초까지 남긴다(같은 초에 만든 두 작업이 구간을 나눠 갖던 문제).
- 논문 재현 조건(A2, `spec T1 [--source SRC1]`, 앱 도구 막대 "📋 재현 조건 뽑기"): judge가 논문에서 데이터셋, 분할, 전처리, 모델, 하이퍼파라미터, 학습, 지표, 비교 대상, 보고된 결과, 평가 규칙을 원문 발췌와 쪽으로 뽑는다. Pablo가 그 쪽에서 위치를 찾은 것만 VERIFIED check(tier 4, `spec` 필드)로 남기고 못 찾은 것은 뺀다(ReproAgent는 바꿔 쓴 근거도 허용한다 — 여기서는 거절). 논문에 없는 설정(시드 등)은 pending check로 남는다. 다시 뽑으면 이전 목록을 대체한다. 이 조건들은 brief로 에이전트에 가고("근거 없이 바꾸지 말 것"), Guard는 검증된 결론과 모순되는 행동을 S01로 막는다. 대화에는 분류별 조건 카드([n] → PDF 쪽 하이라이트)가, 기준 패널에는 "논문 조건"이 보인다.
- 재현 작업(A3): 새 작업에서 "논문 재현 작업"을 고르면 세 기준이 그 작업의 hard 기준으로 함께 들어간다 — 평가(test) 데이터는 학습·튜닝·모델 선택에 쓰지 않는다, 논문에 적힌 설정값은 근거 없이 바꾸지 않는다, 결과 수치는 실행 결과에서만 가져온다.
- 재현 점검(A5/A6, `audit T1`, 앱 도구 막대 "🔎 재현 점검"): 작업 폴더가 있는 작업에서, 에이전트가 코드·설정·실행 로그를 읽고 논문 조건(쪽 포함), 논문에 없는 설정, 작업 기준을 하나씩 판정한다(따름/다름/아직 없음/판단 못 함/코드가 정함, 파일:줄과 그 자리의 값). 보고된 결과는 로그의 값과 대조한다. 답은 `outputSchema`로 받은 JSON이고 대화에는 표로 남는다(다름이 맨 위, 따르는 항목은 접힘, 조건마다 [n] → 논문 쪽). 이 턴은 `readOnly` 샌드박스 + `approvalPolicy: never`라 아무것도 바꿀 수 없어서 읽기마다 Guard를 거치지 않는다. app-server는 턴의 sandbox/approval 덮어쓰기를 이후 턴에도 유지하므로, 일반 턴은 매번 `workspaceWrite` + `untrusted`를 다시 보낸다(쓰기는 항상 Guard). 실측 시나리오: `npm --prefix desktop run check -- <shot-dir> --audit`.
- 점검 결과 확인(0.8 A2, `desktop/where.js`): 점검이 끝나면 Pablo가 항목마다 모델이 댄 파일:줄을 직접 연다. 파일이 작업 폴더에 있는지, 그 줄(앞뒤 2줄)에 `found`가 있는지(공백 정규화, `a / b`·`a; b`·`...`로 나눈 조각은 순서대로, 조각 끝은 토큰 경계라 `llm: gpt-4o`는 `gpt-4o-mini` 줄에서 찾은 것으로 치지 않음; `...`로 끊었거나 main이 300자에서 자른 끝은 예외), 없으면 같은 파일 다른 줄에 있는지, 그리고 조건의 논문 값이 판정과 맞는지(따름인데 값이 없음, 다름인데 값이 그대로 있음)를 본다. 값 확인은 숫자와 숫자가 든 식별자(`GPT-4o-mini`, `all-mpnet-base-v2`)에만 한다. "punctuation", "Personalized PageRank" 같은 개념은 코드가 이름 없이 구현하기 때문이다(0.8 벤치에서 거짓 경고 29건). 여러 줄(`a.py:6,15`, `a.py:5-6,18`)과 여러 파일(`a.py:3; b.py:7`)은 모든 범위를 이어 한 텍스트로 보고 찾는다. 결과는 `chat.json` 항목의 `check`(verified/moved/not_found/no_file/value_mismatch/unchecked)와 `line_found`이다. 표에는 "✓ Pablo가 코드에서 확인", "위치 보정: 12줄", "⚠ 모델이 댄 위치에서 찾지 못함", "⚠ 논문 값(5)이 이 자리에 없음"이 붙고, ⚠ 항목은 판정과 상관없이 접지 않고 맨 위에 둔다. 재현 조건을 뽑을 때도 모델이 읽은 값이 고정한 인용 안에 없으면 `spec.value_in_quote = false`로 남기고 카드에 표시한다. 숫자는 값으로 비교한다("1,000" = 1000, "63.70%" = 63.7, "2wiki"의 2는 숫자가 아님). 같은 규칙이 Python(`skill.has_value`)과 JS(`where.hasValue`)에 있고 테스트가 한 표로 둘을 대조한다.
- 코드 패널(0.8 A3): 점검표의 파일:줄, 변경 카드의 파일 이름, WARN/BLOCK 카드의 "지금 파일 보기"를 누르면 오른쪽 패널에 그 파일이 줄 번호와 함께 열리고 그 줄이 강조된다(읽기 전용, 고치는 일은 에이전트나 외부 편집기). "VS Code에서 열기"(`vscode://file/<경로>:<줄>`, 안 되면 기본 프로그램, 그다음 폴더)와 "폴더에서 보기"가 있다. 파일은 main의 `pablo:read-file`/`pablo:open-file`로만 읽고, 그 작업의 폴더 안(심볼릭 링크·junction을 따라간 뒤에도), 텍스트, 1 MB 이하만 연다. 화면에는 폴더 기준 상대 경로만 간다. 받는 위치 형식: `a.py:5`, `a.py:10-11`, `a.py:5:3`, `logs\x.log:1`, 절대 경로, `a.py#L5-L7`, `a.py (line 5)`, `a.py 5행`, 줄 없는 경로.
- 여러 논문(0.8 C1): 작업마다 PDF를 여러 편 둔다(`desktop.json`의 `pdf[task]`가 목록이다. 0.7의 `{id, title}` 하나는 목록 하나로 읽고, 다음 저장 때 목록으로 쓴다). 도구 막대 "📎 자료: LinearRAG v4 (주 논문) × · HippoRAG2 주 논문으로 × · + 추가". 빼도 그 논문에서 찾은 근거 기록은 남는다.
  - 논문 질문: 작업의 논문 전부에 한 번에 묻는다(`ask T1 "<q>" --source SRC1 --source SRC2`). judge에는 `[A p.N]`처럼 논문을 구분해 주고, 인용마다 어느 논문인지 받는다. 그 논문의 그 쪽에서 위치를 찾으므로, 두 논문에 같은 문장이 있어도 답이 인용한 논문에 고정된다. 길이 상한은 논문당 앞 40쪽, 전체 25만 자다. 넘으면 "○○에만 묻기" 버튼으로 고르게 한다.
  - 재현 조건: 주 논문 한 편에서만 뽑는다. 다른 논문에서 다시 뽑으면 이전 조건은 waived로 남고 새 조건이 대체한다. 두 논문의 설정을 Guard·brief·재현 점검이 함께 강제하지 않게 하려는 것이다(비교 논문의 top-k가 재현을 막으면 안 된다). 조건 카드에는 논문 제목이 붙는다.
- arXiv 가져오기(0.8 C2): "+ 추가"에 `arXiv:2510.10114`, `https://arxiv.org/abs/2510.10114v4` 같은 번호나 링크를 넣는다. 내려받기는 main이 한다(에이전트는 하지 않음). 대상은 `https://arxiv.org/pdf/<id>`뿐이다. 리다이렉트는 같은 출처 안에서만 직접 따라가고, 50 MB·60초 상한을 두며, `%PDF`로 시작해야 받는다. 제목과 버전은 PDF 자체(`/Title`, 1쪽의 arXiv 도장)에서 읽고, 버전과 sha256은 그 논문 항목에 남는다. 논문마다 파일 하나(`state/papers/arxiv-<id>.pdf`)라서 새 버전을 받으면 새 source가 되고, 이전 버전 근거를 `resolve --source`로 새 파일에 대조해 "그대로 / 문맥 바뀜 / 찾을 수 없음"으로 알린다.
- 비교표(0.8 C3, `compare T1 --source SRC1 --source SRC2 [--columns JSON]`, 도구 막대 "📊 비교표"): 행은 논문이고 열은 항목이다. 기본 항목은 데이터셋, 평가 지표, 주요 결과, 효율, 한계이고 바꿀 수 있다. judge는 논문마다 한 번씩, 같은 열로, 다른 논문 없이 읽는다(`COMPARE_PROMPT`). 칸마다 짧은 값과 원문 인용을 받고, Pablo가 그 논문에서 인용의 위치를 찾은 칸만 채운다. 못 찾은 칸은 "근거 없음"으로 비우고, 모델이 댄 값은 툴팁에만 둔다. 칸 하나가 check 하나다(`matrix: {id, column, source_id}` + 앵커). 비교표는 비교용이라 Guard와 brief는 이 칸을 읽지 않는다. 대화의 표 카드와 패널 확대 보기가 있고, 칸의 [n]을 누르면 그 논문의 그 쪽이 열린다.
- 대규모 재작성(A4, Guard W01, LLM 없음): 40줄 이상인 기존 파일의 절반 넘는 줄을 지우는 편집은 WARN. controller가 편집 전 파일과 diff로 잰다(ReproAgent repair regression guard에서 가져온 생각, 기준은 연구 스크립트에 맞게 낮춤).
- Judge 재사용(D5): 행동·계획 단계·적용 기준·근거가 모두 같으면 이전 judge 분석을 그대로 쓰고 판정은 규칙이 다시 낸다(`ActionProposal.analysis_key`/`analysis_from`). 반복 읽기에서 모델 호출이 빠진다. Guard를 건너뛰지 않는다.
- 계획 단계: 요청의 단계가 완료된 뒤에도 같은 요청의 후속 행동(추가 수정, 테스트 실행)은 그 단계를 따른다(`current_step`). 예전에는 "no plan step" WARN이 행동마다 붙었다.
- Guard check(`--guard`)는 C–H를 brief 없이(`PABLO_BRIEF=0`, Guard가 안전망인 경우) 돌리고, 마지막에 brief를 켠 새 작업에서 에이전트가 hard 기준을 스스로 지키는지 본다(실측: "기준상 삭제하지 않겠습니다", Guard에 행동이 가지 않음).
- 보낼 곳: PDF와 작업 폴더가 둘 다 있으면 메시지마다 "어디에서 처리할까요?"를 묻던 것을 없앴다. 작업마다 `desktop.json`의 `route`를 따른다(기본 에이전트 — 논문 조건은 brief로 이미 안다. 또는 논문 질문). 도구 막대 "💬 보낼 곳"에서 바꾼다.
- 처음 상태를 읽기 전에 보낸 메시지가 "먼저 자료나 작업 폴더를 정해 주세요"로 빠지던 경합을 고쳤다.
- 실제 계정 check: `--spec`(LinearRAG에서 조건 추출 — 실측 25개 고정, 0개 탈락, 논문에 없는 설정 4개, 43초), `--audit`(위 재현 점검), `--shot <view.html> [selector]`(저장된 화면 캡처, offline).
- 로컬 CI: `npm --prefix desktop run ci`. GitHub workflow의 Python 테스트 루프(`build/venv`가 있으면 그것)와 `check -- --ui`를 차례로 돌린다. `-- --python`, `-- --ui`로 한쪽만 돌린다. Actions를 못 쓸 때 쓴다.
- Check: `npm --prefix desktop run check -- --ui`(offline: 대화 순서, diff/명령 카드, 중지 표시, 체크포인트 diff·되돌리기·거절·CRLF 보존, 점검 확인 표시, 점검표·변경 카드 → 코드 패널, VS Code 열기 가로채기, 폴더 밖 경로 거절, 자료 두 편·비교표 카드·칸 → 그 논문의 쪽·넓은 패널, 주 논문 바꾸기, 가짜 arxiv.org로 가져오기·새 버전·거절 4가지, 자료 빼기). `--agent`에 중지 시나리오를 더했다. Python: `python tests/skill/test_product.py` (화면 스크립트를 `node --check`로도 검사한다 — 문법 오류 하나가 앱 전체를 빈 화면으로 만든다).

## Backlog (infra)

- 읽기 명령도 Guard를 거친다(`untrusted`). M5.0 실측: 읽기 ALLOW 10.9초, 읽기 WARN 6.0초+사용자 클릭, 수정 WARN 약 19초(클릭 포함), BLOCK 10.1초. judge가 단순 읽기(`Get-Item`)를 soft 제약과 엮어 WARN을 내기도 한다. 결정적 read-only fast path(`Get-Content`/`Get-ChildItem`/`git status`/`git diff` 허용 목록)는 검토 후 보류했다: `-Command` 문자열은 `;`·파이프·리다이렉트·`$()`로 연결될 수 있고, `git status`/`git diff`는 저장소 설정(fsmonitor, diff/textconv driver)으로 코드를 실행할 수 있으며, Guard를 건너뛰면 "X는 읽지 마" 같은 intent 제약 검사도 빠져 정책 변경이 된다. backlog로 남긴다.
  - 0.8 (540f1e3, 실제 `--guard` 근거): 단순 읽기 세 번(`Get-Content`, `git diff`/`git status`, `Get-Item`)이 judge의 "계획 이탈"(D01)로 WARN을 받아, 읽기 명령으로만 된 명령에는 **계획 이탈 규칙(G01/G02/D01)만** 걸지 않는다. Guard를 건너뛰는 fast path가 아니다: judge는 그대로 보고, "X는 읽지 마" 같은 기준 충돌(G04/G05/G07)과 출처 충돌(S 규칙) 판정도 그대로다. 읽기로 보는 것은 리디렉션·`--output`·스크립트 블록·`$()` 없이 읽기 cmdlet과 git 읽기 하위 명령(diff/status/log/show 등, branch는 목록 보기만)으로만 된 명령이다. 위의 저장소 설정(fsmonitor 등) 위험은 이 변경 전과 같다(judge가 ALLOW하던 읽기는 전에도 그대로 실행됐다).
- Intent scope 소유자: 앱에서 말한 기준은 이제 작업 id를 남긴다(Candidate features `task`). 작업 이름 없이 말한 CLI `say`는 여전히 작업 목록 순서 구간이다. Host agent도 `--task`를 쓰게 SKILL.md를 바꿀지 검토한다.
- 인증/호출 경로 전환: 상주 `codex app-server`는 M4.0에서 desktop에 붙였다(`desktop/agent.js`). M4.1에서 in-app Sign in with ChatGPT와 토큰 갱신 시 재시작 + `thread/resume`을 붙였다. M4.2에서 승인 요청에 Guard를 붙였다(`desktop/controller.js`). 근거: https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server
