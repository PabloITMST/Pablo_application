# Pablo 0.8 계획 — 경쟁 서비스 대비 약점 세 가지 메우기

작성 2026-10-13. 0.7.0(PR [#1](https://github.com/PabloITMST/Pablo_application/pull/1), 브랜치 `feat/product-polish`) 위에서 이어 갑니다.
새 채팅 세션이 이 문서만 읽고 시작할 수 있게 썼습니다.

## 왜 이 세 가지인가

0.7.0의 고유한 점은 세 가지입니다. 기준이 실행을 막고, 근거가 원문 쪽에 고정되고, 논문 → 조건 → 코드 → 점검이 한 흐름으로 이어집니다.
범용 코딩 에이전트(Claude Code, Codex, Cursor)나 논문 도구(NotebookLM, Elicit)와 나란히 놓으면 약점도 분명합니다.
그중 연구자에게 바로 걸리는 세 가지를 고칩니다.

| # | 약점 | 사용자가 겪는 일 |
|---|---|---|
| W2 | 편집기가 없음 | 점검표의 `config.yaml:5`, 변경 카드의 파일 이름을 눌러도 아무것도 열리지 않는다. 코드를 보려면 다른 프로그램을 연다 |
| W3 | 자료가 좁음 | 작업당 PDF 하나. baseline 논문을 같이 볼 수 없고, 논문끼리 비교할 수 없다. 웹 문서나 arXiv 링크를 바로 넣을 수 없다 |
| W4 | 판정을 검증하지 않음 | 재현 점검의 "다름/따름"은 모델 판단이다. Pablo가 다시 확인하지 않고, 얼마나 맞는지 숫자도 없다 |

일부러 하지 않는 것도 있습니다.
- 코딩 에이전트 기능 경쟁(IDE 통합, 멀티 에이전트)은 하지 않습니다.
- 첫 읽기의 Guard 지연(약점 1)은 0.8 범위 밖입니다. README backlog에 그대로 둡니다.
- 이유는 같습니다. 고유한 세 가지를 더 단단하게 만드는 데 집중하려는 것입니다.

## 순서와 이유

1. **Phase A — W4-1 + W2-1 (같은 바탕).** 점검 결과의 파일:줄을 Pablo가 직접 읽어 확인하는 일과, 그 파일:줄을 눌러 여는 일은 둘 다 "작업 폴더 파일을 안전하게 읽는 IPC" 하나에 기댑니다. 그래서 같이 만듭니다.
2. **Phase B — W4-2 점검 벤치마크.** Phase A의 확인 결과까지 포함해서 숫자를 냅니다.
3. **Phase C — W3 자료 넓히기.** 여러 PDF, arXiv 가져오기, 논문 비교표 순서입니다.
4. **Phase D — W3 나머지와 W4-3.** 웹 자료, 논문 검색, 다른 논문의 추출 정답 세트입니다. 사용자 시간이 필요한 일이 섞여 있어 마지막에 둡니다.
5. **Release 0.8.0.** rc.js와 릴리스 문서입니다.

Phase마다 따로 커밋하고, Phase가 끝날 때마다 아래 "완료 기준"을 확인합니다.

---

## Phase A — 점검 결과를 Pablo가 확인하고, 파일:줄을 연다

### A1. 작업 폴더 파일 읽기 IPC (바탕)

- `desktop/main.js`에 `pablo:read-file(task, rel, around?)`를 둡니다.
  - 읽는 대상은 그 작업의 폴더(`desk().workspace[task] || envWorkspace`)뿐입니다.
  - `fs.realpathSync` 뒤에도 폴더 안이어야 합니다. 심볼릭 링크로 밖으로 나가는 경로는 막습니다.
  - 1 MB를 넘거나 바이너리이면 거절합니다(앞 8 KB에 NUL이 있으면 바이너리로 봅니다).
  - 반환값은 `{ path, lines: [...], truncated }`이고, 줄 수는 5,000줄까지입니다.
- 경로 정규화 함수 `where(raw)` → `{ path, from, to }`를 하나 둡니다.
  - 받아야 하는 형식: `config.yaml:5`, `config.yaml:10-11`, `logs\2wiki.log:1`, 절대 경로, `path#L5`, 줄 번호 없는 경로.
  - main과 viewer가 같은 규칙을 써야 하므로, 테스트할 수 있는 순수 함수로 둡니다(`desktop/where.js`).

### A2. 점검 결과 결정적 확인 (W4-1)

- 점검이 끝나 `chat.json`에 audit을 쓸 때(main.js `audited()` 뒤) 항목마다 Pablo가 직접 확인합니다.
  - `file`: `where`의 파일이 작업 폴더에 있는가
  - `line`: 그 줄 범위가 있는가
  - `found`: 그 줄 범위(앞뒤 2줄 여유)에 `found` 문자열이 있는가. 공백은 정규화해서 비교합니다.
  - `value`: 조건의 `spec.value`(예: "5")가 있으면 상태와 맞는가.
    - 상태가 `followed`인데 값이 found에 없으면 불일치입니다.
    - 상태가 `differs`인데 found에 그 값이 그대로 있으면 불일치입니다.
- 결과는 항목마다 `check: "verified" | "moved" | "not_found" | "no_file" | "value_mismatch" | "unchecked"`로 저장합니다.
  - `moved`: 같은 문자열이 다른 줄에 있습니다. 그 줄을 `line_found`에 남깁니다.
  - `unchecked`: `where`가 없습니다.
- 화면(viewer `audited()`)에서는 줄 옆에 작은 표시를 붙입니다.
  - `verified`: "✓ Pablo가 코드에서 확인"
  - `moved`: "위치 보정: 12줄"
  - `not_found` / `no_file`: "⚠ 모델이 댄 위치에서 찾지 못함". 이 항목은 판정이 무엇이든 접지 않고 위에 둡니다.
- 원칙: 모델이 사실을 말하고 Pablo가 규칙으로 확인합니다(`guard.py`, `review.py`와 같은 철학). 확인 규칙은 Python 테스트로 고정합니다. 계산은 main이 하지만, 규칙 함수는 JS 파일 하나로 두고 `node`로 테스트해도 됩니다.
- 재현 조건(spec)에도 같은 확인을 더합니다. `skill.spec()`에서 `value`가 비어 있지 않은데 인용 원문(`quote.exact`)에 그 값이 없으면 `spec.value_in_quote = false`로 남기고, 카드에 "값이 인용 안에 없음"을 표시합니다.

### A3. 코드 보기 패널과 파일:줄 열기 (W2-1)

- Context Panel에 `code` 모드를 더합니다(viewer.py의 `({ source, intent, plan, trace })` 옆).
  - 줄 번호, 대상 줄 강조, 그 줄로 스크롤합니다.
  - 고정폭 글꼴만 씁니다. 문법 강조 라이브러리는 0.8에서는 넣지 않습니다.
  - 머리에는 파일 경로, "VS Code에서 열기", "폴더에서 보기", 닫기가 있습니다.
- 열리는 곳:
  - 점검표의 `where`(`<code>`를 버튼으로)
  - 변경 카드의 파일 이름
  - WARN/BLOCK 카드의 파일 변경 경로
- 외부 열기:
  - `shell.openExternal("vscode://file/<abs>:<line>")`를 씁니다. 실패하면 `shell.openPath(abs)`로 연 뒤 `shell.showItemInFolder`를 씁니다.
  - IPC로 받은 경로는 반드시 작업 폴더 안인지 다시 확인합니다.
- 편집은 하지 않습니다(읽기 전용). 고치는 일은 에이전트(Guard 경유)나 외부 편집기가 합니다.

### Phase A 완료 기준

- [x] `tests/skill/test_product.py` 또는 새 node 테스트
  - `where()` 형식 8가지를 받는다. → 18가지(줄 목록 `a.py:6,15`, 여러 파일 `a.py:3; b.py:7` 포함)와 "위치 없음" 4가지.
  - 확인 규칙 6가지 상태가 나온다(verified / moved / not_found / no_file / value_mismatch / unchecked).
  - 폴더 밖 경로와 심볼릭 링크를 거절한다. → `..`, 절대 경로, junction, 바이너리, 1 MB 초과.
- [x] `check.js --ui`: 점검표의 `config.yaml:5`를 누르면 패널이 그 줄을 강조한다.
  - 일부러 틀린 `where`를 가진 픽스처 항목에는 "⚠ 찾지 못함"이 붙는다.
  - "VS Code에서 열기"를 누르면 `shell.openExternal`이 `vscode://file/...:5`를 받는다(e2e처럼 가로채서 기록).
- [x] 실제 계정 `--audit`: 결과 항목의 `check` 분포를 출력하고, top-k 항목이 `verified`인지 확인한다.
  - 2026-10-13 실측: 29항목 중 위치를 댄 7곳 모두 verified, 나머지 22개는 위치 없음(unchecked). top-k는 verified였고, 패널에서 5줄로 열렸다.
- 벤치(Phase B) 결과로 규칙을 고쳤다. 원자료 162항목을 새 규칙으로 다시 돌린 결과, 거짓 경고 38건(개념어 값 29, 줄 목록 9)이 0이 되었고, 심은 어긋남 19건은 그대로 verified였다.
  - 값 확인은 숫자와 숫자가 든 식별자에만 한다.
  - 폴더별 thread 버그가 있던 첫 실행에서는 not_found 16건이 남는다. 에이전트가 옛 폴더를 읽고 답한 것이므로 맞는 경고다.

---

## Phase B — 재현 점검 벤치마크 (W4-2)

"점검이 어긋남을 몇 % 찾고, 몇 % 잘못 짚는가"를 숫자로 냅니다.

### B1. 어긋남 심기 생성기

- 위치: `tests/eval/audit_bench.py`
- 바탕 폴더는 LinearRAG 논문을 **따르는** 재현 폴더입니다(`release/0.7.0/demo-repro`를 고쳐서 만듭니다).
  - `config.yaml`: top_k 5, 데이터셋 4개, damping 0.85, all-mpnet-base-v2, gpt-4o-mini, validation 1,000문항
  - `logs/`: 논문 값과 같은 결과 로그
  - 작은 `retrieve.py`, `eval.py`
- 어긋남 목록: 각 항목에 `{id, 조건 키워드, 파일, 바꿀 줄, 기대 상태}`가 있습니다. 10개 이상 둡니다.
  - top_k 바꾸기, 임베딩 모델 바꾸기, 데이터셋 빼기, damping 바꾸기, 문항 수 바꾸기, 결과 로그 값 낮추기, 평가 지표 함수 빼기(missing), split을 test로 바꾸기, δ 임계값 바꾸기, 코드 안에 하드코딩된 top_k(설정과 따로)
- 씨앗을 고정한 무작위로 변형 폴더 N개를 만듭니다(각각 어긋남 1–3개). 정답은 `truth.json`입니다.

### B2. 실행기와 채점

- `desktop/check.js --audit-bench [N]`(실제 계정)
  - 바탕 작업 하나에 재현 조건을 한 번 뽑아 둡니다(`spec` 비용을 한 번만 냅니다).
  - 변형 폴더마다 작업 폴더를 바꿔 🔎 재현 점검을 돌립니다.
- 채점은 Python에서 합니다(`audit_bench.py score <dir>`).
  - 정답 매칭: 조건 문장에 키워드가 들어 있는 spec check와 맞춥니다. 실패하면 사람이 볼 수 있게 남깁니다.
  - **재현율**: 심은 어긋남 중 `differs`/`missing`으로 잡은 비율
  - **오탐률**: 심지 않은 조건을 `differs`로 짚은 비율
  - **위치 정확도**: 잡은 항목 중 `check == verified`(Phase A)인 비율
  - 상태 혼동표(followed / differs / missing / unclear / chosen)
- 결과는 `release/0.8.0/eval/audit_bench.md`(표)와 `.json`(원자료)에 씁니다.
- 비용: 점검 1회에 약 1분입니다. N=12면 15분 안팎이고, 실행할 때마다 사용자 계정의 플랜 사용량을 씁니다. N을 인자로 받고, 기본값은 6입니다.

### Phase B 완료 기준

- [ ] 생성기와 채점기를 오프라인으로 테스트한다. 가짜 점검 결과로 재현율과 오탐률 계산을 검증한다.
- [ ] 실제 계정 N≥6 실행 결과표를 커밋한다. 숫자가 나쁘면 그대로 적고, 원인(조건 키워드 매칭, 모델 판정)을 나눠 적는다.
- [ ] 결과를 보고 점검 프롬프트(`skill.render_audit`)를 손볼지 결정한다. 손보면 같은 씨앗으로 다시 재서 전후를 비교한다.

---

## Phase C — 자료 넓히기 (W3)

### C1. 작업당 PDF 여러 개

- `desktop.json`의 `pdf[task]`를 `{id, title}`에서 `[{id, title}]`로 바꿉니다. 옛 형식을 읽으면 배열로 올립니다(마이그레이션).
- 도구 막대: "📎 자료: LinearRAG · HippoRAG2 · + 추가". 각 자료에 빼기 버튼을 둡니다. 빼도 근거 기록은 남습니다.
- `ask`: 판단 대상은 그 작업의 PDF 전부입니다.
  - judge 입력은 `[논문 A p.N]`처럼 논문을 구분합니다(`ASK_PROMPT`, `answer_from_pdf` → `answer_from_sources`).
  - 인용에는 `source` 번호가 붙습니다(`ASK_SCHEMA` citations에 `paper`).
  - 앵커는 그 논문의 그 쪽에서 찾습니다(`skill.ask`).
  - 입력 길이 상한을 둡니다(예: 논문당 앞 40쪽, 전체 25만 자). 넘으면 사용자에게 어떤 논문으로 물을지 고르게 합니다.
- `spec`: 논문마다 따로 뽑습니다(이미 `source_id`가 붙어 있습니다). 조건 카드와 brief에 논문 제목을 붙입니다. 재현 대상 논문 하나를 "주 논문"으로 고르면, 점검은 주 논문 조건만 대조합니다.

### C2. arXiv 링크·ID로 논문 가져오기

- "📎 + 추가"에서 파일 대신 `arXiv:2510.10114` 또는 `https://arxiv.org/abs/...`를 받습니다.
- 내려받기는 main 프로세스가 합니다. 에이전트가 하지 않습니다.
  - 대상은 `https://arxiv.org/pdf/<id>`뿐입니다. 크기 상한 50 MB, 시간 상한 60초입니다.
  - 받은 파일은 기존 `source` 경로(PDF 캡처)로 넣습니다.
  - 버전(`v4`)은 제목 옆에 남깁니다.
- 같은 논문의 새 버전을 다시 받으면 기존 `resolve`(VALID/STALE/UNRESOLVED)로 근거가 바뀌었는지 알립니다.
- CI처럼 sha256을 남겨 두면 재현 검증에 쓸 수 있습니다.

### C3. 논문 비교표

- 대상은 그 작업의 PDF 2편 이상입니다. 열은 기본값이 데이터셋, 평가 지표, 주요 결과, 효율, 한계이고, 사용자가 바꿀 수 있습니다.
- 칸마다 짧은 값과 원문 인용이 들어갑니다. 위치를 못 찾은 칸은 "근거 없음"으로 비웁니다. 지어낸 값으로 채우지 않습니다.
- 저장 방식은 기존 check와 앵커를 그대로 씁니다. 칸 하나가 check 하나이고, `spec`처럼 `matrix: {id, column, source_id}` 메타를 붙입니다. 새 저장 구조를 만들지 않습니다.
- 화면은 대화의 표 카드와 패널 확대 보기입니다. 칸을 누르면 그 논문 그 쪽이 하이라이트됩니다.
- judge는 새 프롬프트 `COMPARE_PROMPT`를 씁니다. 논문마다 한 번씩 호출하고 열 정의는 같게 둡니다. 그래야 길이 상한을 넘지 않고, 칸끼리 서로 오염되지 않습니다.

### Phase C 완료 기준

- [ ] Python: 여러 PDF `ask`(스텁 judge)에서 인용이 각 논문의 맞는 쪽에 고정된다. 옛 `desktop.json`을 마이그레이션한다. 비교표 칸이 앵커 없이는 만들어지지 않는다.
- [ ] `--ui`: 자료 두 개, 비교표 카드, 칸 클릭 → 그 논문의 패널.
- [ ] 실제 계정: LinearRAG + 비교 논문 1편(arXiv에서 가져오기)으로 비교표를 만들고, 칸 근거 위치 성공률을 출력한다.

---

## Phase D — 나머지

- **D1. 웹 문서 자료**
  - 자료 추가에서 URL을 받습니다. 캡처, 스냅샷, `locate.js` 하이라이트는 이미 있습니다(M3.1, M3.2.3).
  - `ask`를 웹 스냅샷에도 쓰도록 넓힙니다. 웹에는 쪽이 없으므로 인용에 `near`를 받아 `evidence.locate`로 고정합니다.
- **D2. 논문 검색** (선택)
  - Semantic Scholar 또는 arXiv API로 검색해서 결과를 고르면 C2로 가져옵니다.
  - 외부 API 키가 필요 없는 범위에서만 합니다. 요청 횟수 제한과 사용자 질의 전송을 화면에 밝힙니다.
- **D3. 다른 논문의 조건 추출 정답 세트** (W4-3, 사용자 시간 필요)
  - 대상은 `Downloads/evidence_guided_reproduction_capstone_plan.md`의 1차 후보입니다: Sample-specific Masks, Batch and Match, PINNs.
  - 세션이 논문에서 정답 후보(조건, 인용, 쪽)를 뽑으면 사용자가 확인하고 고칩니다.
  - 그다음 `--spec`로 재현율(정답 조건 중 고정된 비율)과 정밀도(추출 중 정답과 맞는 비율)를 잽니다.

---

## Release 0.8.0

- 버전을 0.8.0으로 올리고 `npm --prefix desktop run backend`, `package`, `rc.js`를 돌립니다.
- rc.js에 두 장면을 더합니다.
  - 점검표 → 코드 패널
  - 자료 두 개 → 비교표
- `release/0.8.0/` 문서와 시연 시나리오(0.7.0 시나리오 + 비교표 + 확인 표시)를 씁니다.
- 벤치마크 결과(Phase B)를 README에 한 줄 요약합니다. 오탐률을 숨기지 않습니다.

---

## 새 세션을 위한 메모

**시작**
1. `C:\Users\itisyijy\Desktop\Pablo\Pablo_application`에서 브랜치 `feat/0.8-research-workbench`를 씁니다. 이 문서가 그 브랜치의 첫 커밋이고, `feat/product-polish` 위에 있습니다. PR #1이 먼저 병합되면 `main` 위로 rebase합니다.
2. 환경
   - Python은 `build/venv/Scripts/python`(pypdf 6.19.0)을 씁니다. 시스템 Python에는 pypdf가 없습니다.
   - 점검을 돌릴 때는 `export PATH="$PWD/build/venv/Scripts:$PATH" PYTHONIOENCODING=utf-8`를 먼저 둡니다.
   - `LinearRAG.pdf`가 저장소 루트에 있어야 합니다(gitignore). 없으면 `%APPDATA%\pablo-desktop\state\sources\SRC1.pdf`를 복사하거나 arXiv `2510.10114v4`에서 받습니다. sha256은 `1df0bd67…de533`입니다.
3. 테스트
   - `for t in tests/*/test_*.py; do python $t; done`
   - `npm --prefix desktop run check -- --ui`, `-- <view.html> --auth`, `-- --pdf`
   - 실제 계정: `--guard`, `--agent`, `--spec`, `--audit`. 먼저 앱으로 로그인해 두어야 합니다.

**함정 (0.7.0 작업에서 실제로 겪은 것)**
- `--auth`/`--agent`에 넘기는 view HTML은 viewer를 고친 뒤 다시 만들어야 합니다(`python -m pablo_v2 view T1 --html --dir .pablo/check`). 옛 스크립트가 박혀 엉뚱하게 실패합니다.
- 실제 계정 점검이 도는 동안 `src/`나 `desktop/`을 고치지 않습니다. Python은 호출마다 새로 읽힙니다.
- 사용자 데이터(`%APPDATA%\pablo-desktop`)를 즉석 스크립트로 고치지 않습니다. 0.7.0 작업 중 `thread.json`의 실제 작업 연결을 지웠다가 Codex 세션 기록에서 복구한 적이 있습니다.
- Git Bash heredoc 안의 백슬래시 경로와 `\n`은 깎이거나 바뀝니다. 여러 줄 치환은 Edit 도구를 쓰거나, Python 패치 파일을 따로 만들어 실행합니다.
- 소스 대부분이 CRLF입니다. Python으로 고칠 때는 `newline=""`로 읽고 쓰고, 원래 줄바꿈을 지킵니다.
- 저장소 CI는 Windows + Python 3.11입니다. 3.12 이상 문법(f-string 안의 같은 따옴표, 백슬래시)을 쓰지 않습니다.
- app-server는 턴의 sandbox/approval 덮어쓰기를 다음 턴에도 유지합니다. 새 종류의 턴을 만들면 일반 턴이 매번 정책을 다시 보내는지 확인합니다(`desktop/agent.js` `send`).
- `pabloHost` 함수를 더하면 `check.js --auth`의 함수 목록도 고칩니다.
- 화면 스크립트는 viewer.py 안의 큰 문자열입니다. 문법 오류 하나가 앱 전체를 빈 화면으로 만듭니다. `test_page_script_parses`가 잡습니다.

**하지 않을 것**
- Guard 정책(G/S/D 규칙) 변경. 새 결정적 규칙(W01 같은 것)은 이유를 적고 더할 수 있습니다.
- 코딩 에이전트 기능 확장(IDE 통합, 백그라운드 에이전트).
- 사용자 저장소의 `.git` 조작.
