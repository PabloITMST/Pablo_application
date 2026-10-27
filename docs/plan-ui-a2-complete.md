# Figma A2 최종 디자인 빠짐없이 구현 (To-do)

## Context

사용자가 "최신 main 빌드에 Figma 최신 디자인이 반영 안 된 것 같다"고 했다. 확인해 보니 원인은 둘이었다.
- 16:52 빌드(0.9.1)는 PR #10(높이 32/24/20) 병합 전에 만들어졌다.
- main에 Figma A2와 다른 곳이 많다.

그래서 Figma `Pablo UI`(IV8Epwttx5IgL1fkvrrB7v)의 페이지 `디자인 · 최종 A2`를 기준으로 남은 차이를 모두 구현한다. 대상은 다음과 같다.
- 화면 01–11
- 개념 화면 V1–V4
- 상태 모음 S1–S12

A2를 처음 구현할 때 "다르게 둔 것" 4개(`docs/plan-ui-a2.md`)도 포함한다.

사용자 결정(10/27):
- 제안 태그는 규칙 기반으로 판단한다.
- 기기 코드 로그인은 로그인 서버가 지원하는지 먼저 조사하고, 지원하면 구현한다.
- 보고서 HTML은 Markdown을 변환해 만든다.
- 입력창 줄의 단계 태그는 20 그대로 둔다(앞서 "놔두자").

## 작업 원칙

- **격리:** 다른 세션이 `Pablo_application` 폴더에서 테스트를 돌리고 있다.
  - 작업은 origin/main(326a09c)에서 만든 브랜치 `feat/a2-complete`의 워크트리 `../Pablo_application-a2c`에서 한다.
  - node_modules는 junction으로 잇고, 정리할 때는 `cmd /c rmdir`로 먼저 끊는다.
  - check는 `--user-data-dir=<임시>`로 돌린다.
  - 원래 폴더, `desktop/out`, `build/`, 앱 userData는 건드리지 않는다.
- **편집:** `viewer.py`와 `main.js`는 CRLF다. scratchpad의 `apply.py` 방식을 쓴다(한 번만 맞는 old→new, 줄끝 보존).
- **계약 유지**(`docs/plan-ui-renewal.md` §지킨 계약 + check.js):
  - 입력창의 첫 button은 송신/중지
  - `$("model")`에는 hidden 속성을 붙이지 않음
  - `#src`의 내용과 `$("dir")`의 첫 button
  - `#specs`/`#audits`/`#compares`/`#reports .link`
  - `#acct` dataset.state, `#acct .link`(첫 링크는 연결 해제), `#signin`
  - `[data-intent]` 텍스트
  - `[data-unread] b`, `[data-as]`
  - `#task-list > [data-task]`
  - `.statechip` → `#srccard` 토글
  - `#log .empty`, `#log .msg` 순서
  - 계약 텍스트를 바꿔야 할 때는 check.js 단언도 같은 커밋에서 고친다.
- **디자인에 없는 기존 기능은 지우지 않는다**(조사 보고서의 "keep" 목록). 디자인 모양 안에 자리만 옮긴다.
- **CSS:** A2 CSS 끝의 "A2 · complete" 블록에 모으고, 높이는 `--h-ctl/--h-in/--h-tag` 토큰을 쓴다.

## To-do (전부 구현, 저장소 `docs/plan-ui-a2-complete.md`에도 같은 목록을 두고 체크)

### 0. 공용 데이터 (먼저)
- [x] D1 `stagesOf(v, d)`: `tools()`(viewer.py ~2866–2895)의 단계 계산을 순수 함수로 뺀다. `auditEl`/`reportEl` 대신 술어를 쓴다. 현재 작업은 V, 다른 작업은 `M.views[id]`로 계산한다.
- [x] D2 `refsOf(entry)` + 작업별 `Map<id, entryKeys>`: 대화 기록(chat)의 intent/criterion-edit/spec*/ask/audit/changes/undo/compare 항목과 `V.actions[].criteria`를 모은다. intent 항목은 1ms 앞의 user 메시지와 한 턴으로 묶는다. 메시지 요소에 `data-refs`를 단다.
- [x] D3 `model()`(viewer.py ~152–162)에 승격된 후보 K→기준 id 대응을 더한다.
- [x] D4 계획: `model()`에 작업의 모든 plan을 `created_at`과 함께 내보낸다. main.js `chatTurn`의 user/agent 항목에 `step`(Pn.1)을 기록한다.
- [x] D5 auth 상태에 `code`(no_plan_permission 등)를 실어 S2와 S3를 구분한다(main.js ~753).
- [x] D6 host 정보: `pablo:state`의 `m.host`에 다음을 더하고, IPC `pablo:open-path`(userData·로그 폴더만 허용)를 만든다.
  - 앱 버전
  - Codex 버전
  - userData 경로
  - 로그 폴더
  - 체크포인트 크기
- [x] D7 checkpoint.js: `--numstat`으로 파일별 +/− 줄 수를 낸다(변경 카드 "+42").
- [x] D8 조건 뽑기 걸린 시간: main.js `pablo:spec`이 시간을 재서 spec 항목에 `secs`로 남긴다.
- [x] D9 진행률과 중지:
  - spec은 Python이 쪽 진행을 stderr 줄로 내보내고, controller가 이를 읽어 `pablo:progress` 이벤트로 알린다. 오래 걸리는 py 호출은 kill로 중지할 수 있게 한다.
  - audit은 agent item(파일 읽기)을 세어 알린다.
- [x] D10 내려받기 확인: arXiv 메타데이터나 HEAD 요청으로 파일 이름·출처·크기를 먼저 알려 주는 `pablo:peek-arxiv`.
- 단계 0에서 다르게 한 것(10/27):
  - D6 로그 폴더: 앱은 로그를 콘솔에만 쓰고 파일로 남기지 않는다. 그래서 `m.host.logs`는 `null`이고 화면에는 "없음"으로 보인다. `pablo:open-path("logs")`는 "로그 폴더가 없습니다…" 오류를 낸다. `open-path`는 `checkpoints`도 받는다(저장 위치의 체크포인트 크기 옆 "폴더 열기").
  - D9 spec 진행률: 조건 뽑기는 논문 전체를 한 번에 모델에 보낸다. 그래서 쪽 단위 진행은 실제로 읽은 쪽이 아니다. 스트리밍 답에 지금까지 나온 가장 큰 `page`로 어림한다(처음 0, 끝나면 전체 쪽 수). 비교표는 중지만 되고 진행률은 없다.
  - D9 audit 진행률: 파일 수는 Codex `commandExecution` 항목의 `commandActions[type=read].path`를 중복 없이 센 값이다. 판정 수는 스트리밍 답에 나온 `"status":`의 개수다(점검 항목 수가 상한).
- [x] D11 기기 코드 로그인 조사 — **불가(10/27)**: auth.openai.com의 openid-configuration은 `grant_types_supported: authorization_code, refresh_token`뿐이고 device_authorization_endpoint가 없음. SIWC 문서(developers.openai.com/siwc/token-sharing-open-source)도 PKCE + 루프백만 설명. S2의 "기기 코드로 연결"은 넣지 않는다. (원래 항목:(siwc.js, 로그인 서버): 지원하면 S2의 "기기 코드로 연결"을 구현하고, 지원하지 않으면 근거와 함께 보고한다.)

### A. 셸 (사이드바 · 머리줄 · 단계 · 보기 줄 · 대화상자)
- [x] A1 사이드바: 브랜드 줄 오른쪽에 접기 아이콘 버튼. `body.side-off`로 접고, 설정은 작업과 무관하게 `settings.side`에 기억한다.
- [x] A2 "+ 새 작업"에 단축키 표시, 검색에 단축키 표시. renderer keydown으로 Ctrl+N(새 작업), Ctrl+K(검색 포커스)를 만든다. 표시는 Windows에서 "Ctrl N"/"Ctrl K", mac에서 ⌘.
- [x] A3 검색칸을 늘 보이게 하고 placeholder를 "작업·대화·태그 찾기"로 바꾼다. 대화 글(`M.views[id].chat`)과 태그(stage 이름·대상)도 찾는다.
- [x] A4 작업이 없을 때 "아직 작업이 없습니다."
- [x] A5 작업 행: 제목 + 단계 진행 막대(D1) + "종류 · 지금 단계".
- [x] A6 계정 카드를 사이드바 아래에 고정한다(`#acct` 유지).
  - 연결됨: "ChatGPT · 연결됨 / 플랜 사용 가능 · 연결 해제 · 설정"
  - 연결 안 됨: "ChatGPT · 연결 안 됨 / 연결해야 에이전트와 논문 질문을 쓸 수 있습니다"
  - 로그인 카드, 진행 중, 오류 상태는 S1–S4(B21)의 모양으로 같은 자리에 둔다.
- [x] A7 머리줄 칩 3개, 각각 ▾. 누르면 지금의 `#srccard`가 그 구획으로 열린다(`.statechip`은 자료 칩으로 남긴다).
  - 자료: "주 논문 제목 vN · 주" / "자료 N편" / "자료 없음"
  - 폴더: "폴더 이름" / "폴더 없음"
  - 인터넷: "인터넷 차단/허용"
- [x] A8 "⋯" 메뉴. 보관/보관 풀기, 완료로 옮기기/완료 풀기, 이름 바꾸기, 보고서 내보내기를 넣고, 지금의 글자 링크는 메뉴로 옮긴다.
- [x] A9 단계 막대: 거르는 중이면 그 단계의 둘째 줄을 "거르는 중 · N"으로 바꾼다.
- [x] A10 보기 줄 오른쪽 상태 "거르기 없음". 거를 때는 칩 "단계 · X ×"를 띄우고, 같은 칩을 "대화로 거르기"(C6)에도 쓴다.
- [x] A11 첫 실행 화면: 마스코트, "무엇을 해볼까요?", 부제, 단계 카드를 둔다. 연결 상태는 DOM `#acct`의 data-state로 읽는다.
  - 단계 카드: "1. ChatGPT 계정 연결 [ChatGPT로 연결]", "2. 새 작업 만들기 [+ 새 작업]", 안내 문장
- [x] A12 새 작업을 대화상자로 바꾼다(Dim + 카드, `#goal`/`#repro`/`#kind-*`/`#create`는 유지). (백엔드는 단계 0에서 끝남: `m.reproCriteria`, `pickPdfsFree`/`pickFolderFree`/`attachPicked`)
  - 목표 + "첫 줄이 작업 이름이 됩니다"
  - 종류 카드 3개
  - 논문 재현일 때 기본 기준 목록(`REPRO_CRITERIA`를 state로 내보냄) + 단계
  - 자료: PDF 고르기, arXiv·OpenReview·DOI 칸 + 가져오기, 주 논문 칩
  - 작업 폴더: 선택 안 함 / 폴더 고르기
  - 인터넷 토글(설정 기본값)
  - "이 작업만의 기준" 칸
  - [취소][만들기]
  - 구현: 고른 값은 만든 뒤 차례로 붙인다(만들기 → add-files/add-arxiv/pick-folder 결과 경로 → set-net). 작업 없이 고르는 IPC `pablo:pick-pdfs-free`, `pablo:pick-folder-free`를 둔다.
- [x] A13 보고서 내보내기 대화상자. (백엔드는 단계 0에서 끝남: `reportPreview`, `pickReportPath`, `report(task, opts)`, Python `report --sections --format --preview`)
  - 포함할 내용 체크 8개와 개수: 목표·기준, 조건, 최근 점검, 의도한 차이, 결정과 이유, 변경·되돌리기, 거절한 요청, 대화 전체
  - "함께 남는 기록(자동)"
  - 점검이 오래됐으면 경고 + [먼저 다시 점검]
  - 형식 [HTML|Markdown], 저장 위치 + 바꾸기, [취소][내보내기]
  - Python `report --sections --format html`: `render_report`의 구획을 고를 수 있게 하고 "대화 전체"를 추가한다. HTML은 Markdown을 변환해 앱 글꼴·색을 입힌 한 파일로 만든다.
- [x] A14 설정 대화상자: 왼쪽 목록(계정 · 기본값 · 셸·인코딩 · 저장 위치 · 정보). (백엔드는 단계 0에서 끝남: `m.host`, `openPath`, SETTINGS `panel:"always"`·`side`)
  - 기본값: 모델 칩, 새 작업의 인터넷 토글, 오른쪽 패널(열림+기억 / 늘 열림 / 레일), 기본 보기, 메시지 태그. SETTINGS에 `panel:"always"`를 더한다.
  - 계정: 연결 상태, 플랜, 연결 해제
  - 셸·인코딩: PowerShell 7 감지, UTF-8, 5.1 안내 상태
  - 저장 위치: 경로, 폴더 열기, 체크포인트 크기
  - 정보: 버전, Codex 버전, 로그 폴더, 제3자 고지
  - 데이터는 D6에서 온다.

- A 셸에서 다르게 한 것(10/27, a2c-shell):
  - A3: 10/27 Figma 수정에 따라 검색은 "작업·자료 찾기" 그대로, 범위도 이름 · 목표 · 자료 제목이다(대화·태그로 넓히지 않음). 찾은 곳이 이름이 아니면 줄에 "자료 · …"/"목표 · …"로 굵게 보인다.
  - A6/S4: "다시 연결하는 중"은 연결된 채 에이전트가 다시 뜰 때(입력창의 data-agent가 Connecting) 계정 카드에 보인다. 입력창의 비활성 안내 "다시 연결되면 보낼 수 있습니다"는 gate()(B)에 남겼다.
  - A7/F18: 단계 막대의 동작 링크(#specs · #audits · #compares · #reports)는 디자인에 없지만 그 단계의 유일한 입구라 단계 칸에 그대로 둔다. 폴더 칩 메뉴는 전체 경로 대신 폴더 이름을 보인다(main은 이름만 넘긴다).
  - A12: 종류 기본값은 '일반' 그대로(재현 기준 3개가 저절로 붙지 않게; check.js 계약). 대화상자의 DOI는 arXiv에서 같은 제목의 첫 결과를 받는다(+ 추가 상자는 고르게 한다).
  - A13: 기본으로 고른 내용은 '대화 전체'만 뺀 전부(Python 기본값, 이전 보고서와 같음). '에이전트가 거절한 요청' 대신 보고서 구획 이름 'Pablo가 막거나 확인을 받은 작업'을 쓴다(Guard의 막음·확인이지 에이전트의 거절이 아니다).
  - A14: '오른쪽 패널'은 둘(열림 + 기억 / 레일), 모델 줄 없음(10/27). 로그는 파일이 없어(D6) '없음'으로 보인다. 체크포인트는 크기만(경로는 main이 주지 않음). 새 IPC 둘: `pablo:open-work`(⋯ · 폴더 칩 '작업 폴더 열기'), `pablo:recheck-plan`(설정 · 계정 '다시 확인').
  - B21/S2: 기기 코드 연결은 없다(D11).
  - F26: 좁은 창의 패널 덮개에서 '접기 ›'를 '닫기 ×'로 바꾸는 것은 패널 머리줄(C) 글이라 손대지 않았다.
  - S16(모델 메뉴)은 B의 입력창 코드에서 메뉴 항목만 고쳤다(현재 모델 ✓, 아래 안내 한 줄). S27 · S28 · S30 · S31은 check.js가 단언하는 기존 문구를 그대로 두고 새 상자 모양에 넣었다.

### B. 대화 (메시지 · 카드 · 보기 · 입력창 · 상태)
- [ ] B1 사용자 이름을 "나"로, 시각을 HH:mm로 바꾸고, Pablo 메시지에도 시각을 단다(chat 항목의 `at`). 단계 구분선의 시각도 HH:mm.
- [ ] B2 태그 줄: "✎ 태그"와 "📌 기준으로"를 "+ 태그" 하나로 합친다(B15 팝오버가 둘 다 맡음). 대상에 "조건 ·"과 "기준 ·"을 더한다(D2 refs).
- [ ] B3 제안 태그(규칙 기반).
  - 보낸 때 단계와 내용 단계가 다르면 "✦ 제안 · 단계" + 맞음/아님 + 이유 줄을 단다. 예: 실행 중에 조건·근거를 가리킴 → 조건 확정. 결과는 `tags[key].suggest` 또는 `ok`.
  - 기준 후보(pending)는 "✦ 제안 · 기준(가능하면)"으로 보인다.
- [ ] B4 기준 추가 알림: 주황 바탕 띠 + 체크 아이콘 + 오른쪽 "기준 보기". `[data-intent]` 텍스트는 유지한다.
- [ ] B5 보류된 기준: 항목마다 흰 카드 + 주황 왼쪽 선.
  - 제목 "결정이 필요합니다", 본문 ""…" — 이 작업의 기준으로 남길까요?"
  - [기준으로 추가 (가능하면)] [무시] 버튼
  - 기존 끝의 모음 카드(check.js:949)와 정합시킨다.
- [ ] B6 읽지 못한 줄: 회색 띠 + 정보 아이콘 + "— 요청으로만 처리했습니다" + 오른쪽 "기준으로 추가". 누르면 반드시/가능하면을 고르는 작은 메뉴가 열리고 "괜찮음"도 메뉴에 둔다(`[data-as]` 유지).
- [ ] B7 논문 답의 확인 띠: "인용 N개 · 모두 <자료> 원문에서 위치를 확인했습니다 · 위치를 못 찾은 인용 N개는 답에서 뺐습니다". webOnly 안내는 유지한다.
- [ ] B8 Guard 카드: `guard()`와 `action()`의 문구와 모양을 통일한다.
  - BLOCK: "막음" 배지 + "Pablo가 이 작업을 막았습니다", 링크 "왜?"
  - WARN: "확인 필요" 배지 + "이 작업은 현재 기준과 충돌할 수 있습니다", [진행][취소] + "의도한 차이로 기록"(조건 충돌일 때, `differ()`) + "기술 세부정보 ▸"
  - 일반 작업의 명령 WARN은 압축 카드: "확인 필요 명령: …" + 이유 + [진행][취소] + "지금 파일 보기"
- [ ] B9 변경 카드: 회색 띠 "파일 N개가 바뀌었습니다 · path +42"(D7) + [변경 보기] [되돌리기(주황 옅게)].
- [ ] B10 조건 카드.
  - 제목 "재현 조건 N개 · 논문 (주 논문)" + [다시 뽑기] + "PDF에서 조건 더하기"(카드에서도)
  - 부제 "원문에서 위치를 확인한 것만 남겼습니다 · 뺀 것 N개 · N초"(D8)
  - 필터 칩: 전체/설정/결과/범위(`spec.kind`)
  - 분류마다 접히는 회색 머리줄. 접힌 분류는 한 줄에 "▸ 이름 N"으로 모은다.
  - 행: 종류 태그 + 문장 + 쪽 칩 "p.N" + "편집 · 빼기"
  - "논문에 없는 설정 N" 머리줄 + "정하면 이 작업의 기준이 됩니다"
  - 0개(S6) 문구를 바로잡는다.
- [ ] B11 점검 카드.
  - 제목 "재현 점검 · 폴더" + "보고서로", 부제 "조건 N + 작업 기준 N · 읽기 전용으로 실행 · HH:mm"
  - 오래됨 띠 + [다시 점검] 버튼
  - 필터 칩: 전체/다름/확인 필요/아직 없음/따름. 기존 굵은 표시는 배지로 바꾼다.
  - 행 둘째 줄에 "· 논문 값 X"
  - 행 오른쪽: "의도한 차이로", "논문 표 행 보기", "정하기"
  - 제목 텍스트를 단언하는 check.js도 고친다.
- [ ] B12 비교표: 머리줄에 [항목 바꾸기](`compareForm`) + "크게 보기", 부제 "원문". 지표는 mono, 고른 칸을 강조한다. 아래에 "+ 공통 데이터셋 열"과 "+ 논문 추가"(adder → compare 다시).
- [ ] B13 단계별 보기.
  - 머리줄: 단계 + 상태 + "메시지 N · HH:mm–HH:mm" + 오른쪽 "대화 펼치기 ▸ / 접기 ▾"
  - "모델 요약 — …" + "✎ 요약 고치기 · 다시 만들기"
  - 사람이 고친 요약은 "사람이 고침" + "다시 만들어도 이 글이 유지됩니다"
  - 결정 목록에 시각을 붙인다.
  - 지금 단계는 대화를 펼쳐 둔다.
- [ ] B14 거르는 중: 띠는 지금과 같게 두고, 입력창 안내에 "(거르는 중인 단계)", 단계 막대에 A9를 더한다.
- [ ] B15 태그 편집 팝오버(320px).
  - 단계 라디오. 자동 단계에는 "자동 · 보낸 때 단계" 표시
  - 대상 칩: × 삭제, "+ 조건·기준·파일 잇기" 입력(`tags[key].targets`)
  - 표시: "결정으로 고정"과 "기준으로 만들기" 체크. 기준으로 만들기는 체크하면 글 다듬기 칸과 반드시/가능하면이 펼쳐진다(`makeCriterion`).
  - 안내 "…유지됩니다" + [완료]
- [ ] B16 대상별 보기.
  - 그룹 머리줄: 대상 칩 + "대화 N · 판정 N · 점검 …/변경 N" + 오른쪽 "접기 ▾ / 펼치기 ▸"
  - 조건 그룹에는 회색 요약 띠 "논문 값 X [p.N] · 지금 코드 file:line = v · 바꾸자는 요청 N건이 확인을 기다림"
  - 기준/조건/근거/파일/대상 없음으로 묶는다(D2).
- [ ] B17 입력창.
  - placeholder: 논문 질문일 때 "논문에 묻기…", 그 밖에는 "Pablo에게 요청하기…"
  - 보낼 곳 세그먼트를 늘 보인다. 자료나 폴더가 없는 쪽은 비활성 + 이유 툴팁.
  - 모델 칩에 테두리를 둔다.
  - 상태 글: 연결 안 됨 / 준비됨 / 작업 중 · 확인 기다림
  - 송신은 글자 버튼 "보내기"(검정), 진행 중이면 "■ 중지"(주황 옅게). 첫 button 계약은 유지한다.
- [ ] B18 S5 조건 뽑는 중 카드: 단계 진행 + "논문을 읽고 있습니다 · 9 / 20쪽" 막대 + "보통 1–3분 · 다른 일을 해도 됩니다" + [중지](D9).
- [ ] B19 S7 점검 중 카드: "파일 N개 읽음 · 조건 n / N 판정" 막대 + "읽기 전용 — 아무것도 바꾸지 않습니다" + [중지](D9).
- [ ] B20 S8 근거 위치를 못 찾음: "N쪽에서 위치를 찾지 못했습니다 — 비슷한 문장 k곳"(evidence.py에 비슷한 문장 찾기를 더함) + 추출 텍스트 + "원본 열기 ↗".
- [x] B21 S1–S4 계정 상태.
  - 연결 중: 스피너 + 취소
  - 실패: 다시 시도 + 기기 코드(D11)
  - 플랜 불가: 다른 계정으로 연결 + "플랜 안내 ↗"(D5)
  - 다시 연결 중: 스피너 + 비활성 입력 "다시 연결되면 보낼 수 있습니다"
- [ ] B22 S9 실행하지 못함 카드: [다른 모델로 다시 시도] + "기술 세부정보 ▸"를 한 카드에 둔다.
- [ ] B23 S10 자료 없이 논문 질문: "먼저 자료를 추가하세요" + [PDF 고르기][arXiv · DOI로 가져오기].
- [ ] B24 S12 내려받기 확인 카드: 파일 이름, 출처·크기, [받기][취소](D10).

### C. 오른쪽 열
- [ ] C1 탭 요약.
  - 계획: "Pn.k · i/N"
  - 근거: 마지막 근거 위치("config.yaml:5", "칸 [7]", "p.9"), 없으면 "인용 N"
  - 주의 점: 확인 기다림이 있는 탭에도 주황 점
- [ ] C2 패널 머리줄 제목을 디자인 문구로 바꾸고, 오른쪽에 "접기 ›" 글자 링크. 레일 맨 위에 "‹ 펼치기".
- [ ] C3 기준 탭. (백엔드는 단계 0에서 끝남: `criterion(task, id, "edit", text)`, Python `restate`)
  - 목표는 상자 없이 글로
  - 머리줄에 개수("반드시 지킬 것 N", "가능하면 N"으로 이름 변경)
  - 행에 뒷링크 칩 "대화 N"/"판정 N(막음/확인 필요)"(D2)
  - 마우스를 올리면 동작: ⇄ 세기 바꾸기, ✎ 고치기(새 IPC `pablo:criterion` action "edit" → Python `restate`: 지우고 같은 범위로 새 문장, 기록에는 "사용자가 고침"), 🗑 지우기(이유 입력 유지)
  - 행을 누르면 선택 표시 + 대화로 거르기
  - 기존 지운 기준·되살리기 등은 유지한다.
- [ ] C4 논문 조건 요약.
  - 분류별 숫자 칩 격자
  - "논문에 없는 설정 N개는 아직 정하지 않았습니다"
  - "조건 보기"(조건 카드로 스크롤하거나 목록 펼치기) + "다시 뽑기"(`redo` 노출)
  - 전체 목록은 "조건 보기"로 펼쳐서 보게 한다(기존 동작 유지).
- [ ] C5 의도한 차이를 별도 구획으로 두고, 행에 "대화 N".
- [ ] C6 대화로 거르기: refs(D2)로 `.filtered`를 다시 쓴다. 띠와 보기 줄 칩(A10)에 대상 이름을 보인다.
- [ ] C7 일반 작업 빈 카드: "논문이 없는 작업입니다 …" + "+ 자료 추가". S11 기준 없음: 안내 + "+ 기준 더하기" 입력(`makeCriterion`).
- [ ] C8 계획 탭.
  - "계획 · N단계 중 k"
  - 행 "Pn.1 문장 ✓/●" + "대화 N · 확인 기다림"
  - 지금 행은 회색 강조
  - 안내 문장
  - 행을 누르면 그 계획의 대화만 남긴다(D4)
  - 근거 확실성·인용·왜? 등 기존 정보는 유지한다.
- [ ] C9 왜? 탭 타임라인.
  - 사용자 요청(그 행동을 낳은 메시지) · 적용된 기준 · 근거 · 계획 단계 · 제안된 작업 · Guard 판정 · 사용자 결정(기다리는 중이면 회색) · 결과·검토(—)
  - 지금 단계는 채운 점
  - 아래 띠 "이 판단이 나온 대화 1 · 같은 기준의 판정 N" + "대화로 거르기"
  - 탭을 누르면 기다리는 행동부터 보인다.
- [ ] C10 근거(PDF).
  - 자료 고르기 칩 ▾(작업의 자료 목록)
  - 띠 "이 쪽을 인용한 대화 N · 결정 N" + "대화로 거르기"
  - 위치 문장에 [n] 포함
  - 아래 "원본 열기 ↗"(src.url 또는 파일) + "추출 텍스트로 보기"
- [ ] C11 근거(코드).
  - 파일 고르기 칩 ▾(대화·점검에 나온 파일)
  - 오른쪽 "작업 폴더 · 읽기 전용 · N줄"
  - 띠 "이 줄을 가리킨 점검 N · 대화 N" + 대화로 거르기
  - 줄 설명 문장 "N번째 줄: 점검 항목 "…"이 댄 자리입니다. 고치는 일은 에이전트나 외부 편집기에서 합니다."
- [ ] C12 비교표 칸 근거: 제목 "근거 · 논문", "N쪽에서 칸 [n]의 근거를 찾아 표시했습니다", "이 칸을 인용한 대화 N".

### F. 별도 세션이 새로 디자인하는 화면·상태
- 사용자 요청(10/27)에 따라 별도 세션 `a2-design-gaps`(local_7a4f405a-2c2a-4dbf-b844-a44c12d55dd1)가 일을 맡았다. Figma에서 아직 그려지지 않은 경우를 찾아 디자인하고, 끝나면 이 세션에 알린다.
  - 대표 사례: 설정의 계정·셸·저장 위치·정보 페이지, ⋯/칩/모델 메뉴, 사이드바 접힘, 검색, + 추가 상자, 넓은 비교표, 900px 이하 등
- [ ] F1 알림이 오면 새 섹션(`03 · 추가 화면과 상태` 예정)의 프레임을 하나씩 To-do에 F2…로 더해 구현한다. 위 A–C와 겹치면 그 항목에 합친다.
- 그동안 단계 0과 A–C는 먼저 진행한다. F 항목은 같은 브랜치에 이어서 커밋한다.

### 문서 · 정리
- [ ] E1 `docs/plan-ui-a2.md`의 "다르게 둔 것"을 해소된 것으로 고친다. README의 화면 설명이 바뀐 곳도 고친다.
- [ ] E2 Figma와 다르게 남기는 것이 생기면 이유와 함께 To-do 문서에 남긴다(예: D11이 불가능할 때).

## 진행 방식

- **단계 0 (D1–D11):** 내가 순서대로 한다. D11 조사는 맨 앞에서 병렬로 시작한다.
- **A, B, C:** A2 때처럼 워크트리 에이전트 셋이 동시에 한다.
  - viewer.py는 영역 표시 주석 사이 CSS와 각자 맡은 함수만 고친다.
  - main.js/preload.js/Python의 새 IPC는 단계 0에서 미리 만들어 둔다.
  - 합칠 때 충돌을 보고 손질 커밋을 한다.
- 영역마다 커밋을 나누고 PR 하나로 올린다.

## 확인

- 영역마다 check.js `--ui`/`--auth`에 새 단언을 더한다. 대상은 칩 3개, 단축키, 팝오버, 필터 칩, 대화상자, 뒷링크 개수, 보고서 형식 등이다.
- 그다음 로컬 CI `npm --prefix desktop run ci`를 돌린다(Python 테스트 + `--ui` + `--auth`, 격리 프로필).
- Python: 새 테스트 둘을 더한다(`report --sections/--format`, `restate`).
- 화면: `PABLO_SHOTS`로 픽스처 화면을 찍어 Figma 01–11, V2–V4, S1–S12와 하나씩 나란히 비교하고, 남는 차이를 To-do 문서에 기록한다.
- 실제 계정이 필요한 것(진행률, 내려받기 확인, 기기 코드)은 픽스처나 가짜 서버로 확인하고, 실제 확인은 사용자에게 요청한다.
- 끝나면 워크트리를 정리한다(junction 먼저).

## 단계 0 API

UI 에이전트가 코드를 읽지 않고 쓸 수 있도록 정리한 목록이다. 커밋은 2bb4cad(Python), c4d0cb4(페이지), c014334(desktop)이다. 모양은 JSON/JS 표기로 적었다. `?`는 없을 수 있다는 뜻이다.

### 페이지 함수 (viewer.py PAGE, 전역 스코프)

- `kindFor(d)` → `"repro" | "read" | "general"`
  - `d = M.desk[id]`이다. 만들 때 고른 종류가 있으면 그것을 쓴다.
  - 없으면 폴더+논문은 repro, 논문만 있으면 read, 그 밖은 general이다. `kindOf()`는 이제 `kindFor(M.desk[V.task.id])`를 부른다.
- `stagesOf(v, d, kind?)` → `{ steps: [{ key, label, state, sub }], current, can }`
  - `v = M.views[id]`, `d = M.desk[id]`이다. kind를 주지 않으면 `kindFor(d)`를 쓴다. 어느 작업에나 쓸 수 있다(사이드바 진행 막대).
  - `state`: `"done" | "current" | "todo" | "blocked" | "stale"`. `sub`은 단계 막대의 둘째 줄 글이다(예: `"정할 일 2"`).
  - `current`: 첫 todo 단계의 index다. 없으면 -1이다.
  - `can`: `{ spec, compare, audit, report }` (boolean). 각 단계 동작(`#specs/#compares/#audits/#reports`)이 생길 조건이다. 동작은 pabloHost도 있어야 생긴다.
  - key와 label:
    - repro: prep 준비 · spec 조건 확정 · run 구현·실행 · audit 재현 점검 · report 보고서
    - read: prep · ask 질문 · compare 비교표 · wrap 정리
    - general: prep · work 작업 · review 검토
  - `tools()`는 이 결과로 `#stages`를 그린다. 동작은 key로 붙인다(repro spec/audit/report, read prep/compare/wrap, general work/review).
- ref 문자열 형식
  - 기준 id: `"C4"`. 승격된 K 후보는 그 기준 id로 바뀐다.
  - check id: `"SC5"`. 조건, 논문 답, 비교표 칸이다.
  - 근거 anchor: `"E12"`
  - 근거 쪽: `"SRC1:p9"`
  - 작업 폴더 파일: `"file:config.yaml"`. 경로는 `/`로 쓰고 줄 번호는 뺀다.
  - 계획 단계: `"P3.1"`
- `refsOf(entry, v = V)` → `string[]`: chat 항목 하나가 가리키는 ref들이다.
  - intent: `items[].id`, 그리고 `pending/unread[].id`를 `v.intent.promoted`로 바꾼 것
  - criterion-edit: `id`
  - spec: `checks` + `missing`, 각각의 anchor와 쪽
  - ask, spec-*: `check`와 그 anchor·쪽
  - audit: `items[].id`, 그리고 `items/outside[].where`의 파일
  - changes, undo: `files`의 경로
  - compare: `cells`와 그 anchor·쪽
  - 모든 항목: `step`이 있으면 그것도 넣는다.
- `placePaths(where)` → `string[]`: `"config.yaml:3; src\run.py:16,25 (top_k)"`에서 `["config.yaml", "src/run.py"]`를 뽑는다.
- `turnsOf(v = V)` → `Map<intentKey, userKey>`: user 메시지보다 정확히 1 ms 뒤인 intent 항목을 그 메시지의 턴으로 묶는다(chatTurn이 그렇게 기록한다).
- `refsByKey(v = V)` → `Map<messageKey, string[]>`
  - messageKey는 conversation()의 `data-key`와 같다: `role + "@" + at`, 행동 카드는 `"act:ACT3"`.
  - user 메시지는 같은 턴 intent의 ref도 받는다. 행동 카드는 `criteria[].id`와 `step`을 받는다.
- `linksOf(v = V)` → `Map<ref, { chat: messageKey[], verdicts: [{ act, verdict, decision }] }>`
  - `chat`은 턴마다 하나다(묶인 intent는 user 키로 센다). → "대화 N"
  - `verdicts`는 행동의 `criteria[].id`와 `step`으로 모은다(ALLOW 포함, `decision`은 `"proceed" | "reject" | "defer" | null`). → "판정 N"
- `stampRefs(root = $("log"), v = V)` → 개수
  - `[data-key]` 요소마다 `data-refs`(JSON 배열)를 단다. conversation() 끝과 tagLive()에서 이미 부른다.
- `filterBy(refs, label)` → `{ kept, hid }`: "대화로 거르기"
  - `refs`는 문자열 하나 또는 배열이다. 그중 하나라도 `data-refs`에 있는 `.msg`만 남기고, 아래 메시지가 다 숨은 구분선도 숨긴다.
  - `#log[data-filter] = "refs:" + label`, `.filtered`, `#filter-banner`(`data-refs`, "<label> 대화만 보는 중 · N개 · 다른 대화 M개 숨김", [전체 보기])를 쓴다.
  - 같은 label로 다시 부르면 모두 보인다. 단계 거르기(`stageFilter`)와 같은 장치라서, 하나를 켜면 다른 하나는 꺼진다.
  - CSS는 아직 `#log > .filtered`만 숨긴다(단계별·대상별 보기 안의 메시지는 숨지 않는다).

### 뷰 모델 (`M.views[id]` = Python `model()`)

- `V.plans`: `[{ id: "P3", created_at, status: "active" | "superseded", steps: [{ id: "P3.1", action }] }]`
  - 작업의 모든 계획이다. 오래된 것부터 놓는다. `V.plan`(현재 계획, 자세한 것)은 그대로다.
- `V.intent.promoted`: `{ K12: "C4" }`
  - chat의 `pending`/`unread` 줄 가운데 사용자가 기준으로 올린 것이다.
- chat 항목에 더한 필드
  - `user.step?`, `agent.step?`: `"P3.1"`. 작업 폴더가 있는 작업의 요청만 기록하고, 예전 항목에는 없다.
  - `spec.secs`: 걸린 초
  - `changes.files[]`: `{ status, path, add, del }`. 바이너리 파일이면 `add`/`del`이 `null`이다.
  - `criterion-edit`: action `"edit"`이 생겼고 `prev?`(고치기 전 문장)를 둔다.
  - `report`: `format?: "html"`, `sections?`

### `pablo:state` (M)

- `M.reproCriteria`: `string[3]`. 재현 작업의 기본 기준 문장이다.
- `M.host`: `{ shell, noticed, fonts, version: "0.9.0", codex: "0.152.0" | null, userData: "<절대 경로>", logs: null, checkpoints: <bytes> | null }`
  - checkpoints는 30초 캐시다.
- `M.settings`: `panel`은 `"open" | "rail" | "always"`, `side`는 boolean(사이드바 접힘)이 더해졌다. 저장은 `setUi(null, "settings", {...})`로 한다.

### pabloHost (preload) — 새 것과 바뀐 것

- `cancel(what)` → boolean
  - what은 `"spec"` 또는 `"compare"`(비교표, 열 추가)다. 대기 중이거나 실행 중인 Python 호출을 끝낸다.
  - 그 호출은 `"중지했습니다."` 오류로 끝난다. 재현 점검(에이전트 턴)은 기존 `stop()`을 쓴다.
- `onAgent` 이벤트 `{ type: "progress", task, what, ... }`
  - `what: "spec"`: `page, pages`
  - `what: "audit"`: `files, judged, total`
- `openPath(which)` → true
  - which는 `"userData" | "checkpoints" | "logs"`다. logs는 늘 오류("로그 폴더가 없습니다…")다.
- `peekArxiv(text)` → `{ id, version | null, title | null, filename: "arxiv-<id>.pdf", source: "arxiv.org", bytes | null }`
  - 내려받지 않는다. 없는 번호면 "arXiv에 그 번호의 논문이 없습니다."라고 거절한다. 실제 받기는 기존 `addArxiv`가 한다.
- `pickPdfsFree()` → `[{ token, name }] | null`
- `pickFolderFree()` → `{ token, name } | null`
  - Pablo 폴더와 겹치면 고를 때 바로 오류를 낸다.
- `attachPicked(task, tokens)` → `{ added: [{ title, same }], failed: [{ file, error }], folder: name | null }`
  - 토큰은 한 번만 쓸 수 있다. PDF는 20개까지, 폴더는 하나다.
  - 순서: `newTask` → `attachPicked` → arXiv/DOI는 `addArxiv`/`lookupDoi`, 인터넷은 `setNet`.
- `reportPreview(task)` → `{ counts, stale, auto, where }`
  - `counts`: `{ criteria: { hard, soft }, conditions, audit: { at | null }, deviations, decisions, changes, refused, conversation }`
  - `stale`: 마지막 점검 뒤에 changes나 undo가 있는가
  - `auto`: `"점검 시각 2026-10-27 14:03 · git HEAD 1a2b3c4 · Pablo 0.9.0"`. 점검이 없으면 "점검 전"이고, git이 아니면 HEAD를 뺀다.
  - `where`: `"<폴더 이름>/reports"` | null
- `pickReportPath(task, format)` → `{ token, display: "<폴더>/<파일>" } | null`
  - format은 `"md" | "html"`이다. 저장 대화상자를 먼저 연다. 기본 위치는 `<작업 폴더>/reports`(없으면 작업 폴더)다.
- `report(task, opts?)` → `{ name, lines, format, display } | null`
  - `opts`: `{ sections?: [...], format?: "md" | "html", token?: <pickReportPath 토큰> | "default" }`
  - sections 값: goal_criteria, conditions, audit, deviations, decisions, changes, refused, conversation. 없으면 대화를 뺀 전부(이전과 같은 보고서)다.
  - `token: "default"`: `<작업 폴더>/reports/<이름>`에 저장한다. 작업 폴더가 없으면 오류다.
  - 토큰이 없으면 이전처럼 저장 대화상자를 연다.
- `criterion(task, id, "edit", text)`
  - text는 500자까지다. 같은 기준(세기·범위)의 문장만 바꾼다. 대화에 criterion-edit `"edit"`이 남는다.
- `authStatus()`, `onAuth` → `{ state, error?, code? }`
  - code는 siwc SAY의 키다: no_plan_permission, not_eligible, timeout, cancelled, access_denied, network, usage_limit, overloaded 등.
  - S2(실패)와 S3(플랜 불가: no_plan_permission / not_eligible)를 이것으로 가른다. 토큰은 여전히 넘어오지 않는다.

### Python CLI

- `restate C4 "<새 문장>"` → `{ item, before }`
  - 활성 기준만 바꿀 수 있다. 1–500자이고, 기록의 reason은 "사용자가 고침"이다.
- `report T1 [--sections a,b] [--format md|html] [--preview] [--now JSON]`
  - 기본: `{ text, title, format }`
  - `--preview`: `{ counts, stale, title }`
- `spec`: 진행 줄 `{"progress": {"page", "pages"}}`을 stderr로 낸다(stdout의 JSON은 그대로다).

## F. 추가 디자인 (10/27, 섹션 `03 · 추가 화면과 상태` 109:3377)

대응표 원본: `side-session-notes/.../figma-a2-gap-designs.md`. 프레임 id는 Figma `디자인 · 최종 A2` 페이지 기준이다. 담당 영역은 괄호 안에 적었다.

**화면**
- [x] F12–F15 설정 · 계정 110:3377, 셸·인코딩 110:3569, 저장 위치 110:3755, 정보 110:3934 (A, A14와 합침)
- [x] F16 사이드바 접힘(56px 레일: 새 작업 · 검색 · 작업 머리글자 · 설정)과 머리줄 ⋯ 메뉴(이름 바꾸기 · 완료로 옮기기/풀기 · 보관/풀기 · 작업 폴더 열기 · 보고서 내보내기) 112:3571 (A, A1·A8과 합침)
- [x] F17 사이드바 검색 결과: "찾은 작업 N개", 일치 글자 굵게, 완료·보관 묶음 펼침, esc 112:3910 (A)
- [x] F18 자료 칩 ▾ 펼침: PDF/WEB 배지 · 판 · 주 논문 · 행 동작은 hover만 · + 추가 112:4189 (A, A7과 합침)
- [x] F19 + 추가 상자 · arXiv 검색 결과: 체크박스 · 자료에 있음 · 고른 N개 가져오기 113:4280 (A)
- [x] F20 끌어 놓기 덮개(body.dropping) 113:4718 (A)
- [ ] F21 넓은 비교표 패널(835px) · 항목 바꾸기(6/8) · 다시 채우기 · 열 제안 · 논문 추가 메뉴 114:4805 (C, B12와 맞춤)
- [ ] F22 근거 · PDF 문장 골라 조건으로 더하기(#pick: 선택 위 떠 있는 버튼 + 종류 select · 값 · 한 줄 · 비슷한 조건 안내) 115:4998 (C)
- [ ] F23 근거 · 웹 자료(URL 줄 · 캡처 상태 줄 · 강조 문단) 115:5404 (C)
- [ ] F24 대화로 거르기 · 기준 · 근거 · 파일(거른 띠 + 거르기 메뉴) 116:5314 (B; 보기 줄 칩은 A10)
- [ ] F25 다시 뽑은 뒤 차이 카드(바뀜 · 빠짐 + 되살리기 · 새로) 116:5775 (B)
- [x] F26 좁은 창 768px: 기본 117:5726, 사이드바 서랍 117:5951, 오른쪽 패널 덮개 117:6206 (A가 @media 담당; B·C는 자기 요소가 좁은 창에서 깨지지 않게)

**상태 카드** (S1–S12와 같은 틀)
- [x] F-S13–S24 머리줄·사이드바·입력창 118:6170 (A; S22 보낼 곳 없음은 B)
- [x] F-S25–S37 자료 가져오기 · 계정 · 로그인 119:6330 (A)
- [ ] F-S38–S55 대화 카드 120:6388 (B)
- [ ] F-S56–S69 오른쪽 패널 121:6551 (C)

**디자인 세션이 짚은 어긋남의 처리**
- 계정 카드의 둘째 줄은 "플랜 사용 가능 · 설정"으로 둔다. 연결 해제는 설정 · 계정(F12)으로 옮기고, check.js의 `#acct .link`를 맞춘다. (A)
- 조건 카드의 행 동작은 마우스를 올렸을 때만 보인다. (B)
- 넓은 패널일 때 머리줄 칩은 줄바꿈한다. (A)
- 설정 목록에서 고르지 않은 항목도 r8. 검색칸 placeholder는 "작업·대화·태그 찾기". (A)
- `filterBy`로 거를 때 단계별·대상별 보기 안의 메시지도 숨긴다(단계 0 메모). (B)
