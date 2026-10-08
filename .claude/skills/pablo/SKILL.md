---
name: pablo
description: Pablo planning/governance layer. Use before implementing any task that depends on external APIs, SDKs, frameworks, papers, datasets, authentication, protocols or specifications, and before executing any action that could violate the user's stated constraints. Pablo checks research, plans and actions; it never executes them.
---

# Pablo

Pablo는 실행기가 아닙니다. planning/governance layer입니다.
파일 수정, 검색, shell 실행은 host agent(너)가 합니다.
Pablo는 다음을 맡습니다.
- 사용자 Intent 보관과 제공
- Research gate와 SourceCheck 관리
- Plan 관리
- Action 제안에 대한 Guard 판정

## 호출 방법
```bash
python pablo.py <command> ... --json
```
- 다른 프로젝트에서는 `pablo.py`를 Pablo repo의 절대 경로로 바꿉니다.
- 상태는 현재 디렉터리의 `.pablo/`에 저장됩니다(`--dir`로 변경).
- 항상 `--json`을 붙이고 `ok` 필드를 확인합니다.
- exit 2는 Pablo가 거절한 경우입니다. 메시지를 읽고 지시대로 고친 뒤 다시 시도합니다.
- `say --llm`, `act`, checks 없는 `task`는 Codex를 호출합니다. 호출마다 약 10초 걸립니다.
- JSON 인자(`--checks`, `--sources`, `--steps`)는 파일에 쓰고 `@file.json`으로 넘깁니다. Windows shell은 inline JSON을 자주 깨뜨립니다.
- Codex 로그인이 안 돼 있으면 `python pablo.py status`로 확인합니다. 로그인은 사용자에게 `python pablo.py login`을 요청합니다.

## 1. Intent 기록
사용자가 목표, 제약, 선호, 결정을 말하면 그 문장을 그대로 넘깁니다.
```bash
python pablo.py say "<사용자 문장 원문>" --llm --json
```
- 사용자 문장만 넘깁니다. 너의 제안이나 요약은 Intent가 아닙니다.
- 사용자 요구를 반박하는 제안을 했다면 그 제안을 `say "<제안>" --agent`로 남깁니다. 다음 사용자 교정을 해석하는 데 쓰입니다.
- 작업 시작 전에 `show --json`으로 현재 constraint를 확인합니다. hard는 어기면 안 됩니다.

## 2. Task 시작과 Research 판단
구현 작업을 시작할 때마다 task를 엽니다.
```bash
python pablo.py task "<작업 한 줄>" --json
```
- Codex analyzer가 먼저 이전 task의 완료된 check를 재사용합니다(`reused`). 빠진 사실만 새 check로 만듭니다.
- 순수 로컬 코드 작업(이름 변경, 리팩터링)이 분명하면 `--checks '[]'`로 analyzer를 건너뜁니다.
- 외부 API, SDK, framework, 논문, dataset, 인증, protocol, specification에 기대는 작업이면 건너뛰지 않습니다.
- 직접 check를 정할 수도 있습니다: `--checks @checks.json` (`[{"requirement":"...","necessity":"REQUIRED","why_blocking":"..."}]`)
- REQUIRED는 잘못 알면 구현 방향, API 선택, 보안 방식, 평가 방식, 핵심 결과가 바뀌는 사실에만 씁니다. `why_blocking`에 바뀌는 결정을 적습니다.
- 필요 없는 check가 생기면 지우지 말고 waive합니다. 흔적이 남습니다.
```bash
python pablo.py waive SC3 --reason "<왜 필요 없는가>" --json
```

## 3. Authoritative Research
REQUIRED check가 모두 completed가 되기 전에는 Plan도 Action도 만들지 않습니다.
검색할 때마다 기록합니다.
```bash
python pablo.py search SC1 "<어디를 봤나>" "<검색어>" --tier 1 --found --json
python pablo.py search SC1 "<어디를 봤나>" "<검색어>" --tier 2 --not-found --json
```
Source tier(출처의 권위):
1. 공식 spec, 문서
2. 공식 repo, 구현
3. 공식 예제, changelog, release notes
4. 원 논문, dataset 문서
5. 신뢰할 수 있는 2차 문서
6. 커뮤니티, 일반 웹

조사가 끝나면 결과를 남깁니다.
```bash
python pablo.py check SC1 VERIFIED "<결론>" --sources '[{"tier":1,"type":"documentation","title":"...","url":"...","supports":["..."]}]' --json
python pablo.py check SC1 NOT_FOUND "<결론>" --stop-reason official_channels_exhausted --json
```
- outcome: VERIFIED, PARTIALLY_VERIFIED, NOT_FOUND, CONFLICTING
- tier 5~6만으로는 VERIFIED가 될 수 없습니다.
- "못 찾았다"와 "없다"는 다릅니다. NOT_FOUND는 공식 문서(tier 1)와 공식 repo(tier 2)를 모두 찾아본 뒤에만 기록됩니다.
- `--`로 시작하는 검색어는 옵션 뒤에 `--`를 두고 마지막에 씁니다: `search SC1 "<where>" --tier 1 --found --json -- "--device-auth"`
- 요약 도구(WebFetch 등)의 "없다"는 검색 결과가 아닙니다. not-found로 기록하기 전에 원문에서 키워드를 직접 찾습니다.
- 설치된 공식 도구가 스펙을 내보낼 수 있으면 확인합니다(예: `codex app-server generate-json-schema`). tier 2로 기록합니다.
- NOT_FOUND나 PARTIALLY_VERIFIED에 기대는 구현은 사용자에게 이렇게 알립니다: "공식 지원 근거를 확인하지 못했습니다. 아래 구현은 추정/우회 구현입니다."

## 4. Plan
Research 결과를 보고 계획을 세웁니다. 계획을 먼저 정하고 근거를 끼워 맞추지 않습니다.
```bash
python pablo.py plan T1 --steps '[{"action":"...","basis":["SC1","C1"]}]' --json
```
- `basis`에는 그 step이 존재하는 이유가 되는 SourceCheck와 Intent ID를 넣습니다.
- VERIFIED가 아닌 check에 기대는 step은 Pablo가 `unverified`로 표시합니다.
- 다시 `plan`을 호출하면 이전 plan은 superseded가 됩니다.

## 5. Action 전 Guard
의미 있는 행동(파일 생성/수정, 의존성 추가, 외부 호출, 설정 변경)을 실행하기 전에 호출합니다.
```bash
python pablo.py act T1 "<하려는 행동>" --step P1.1 --json
python pablo.py act T1 "<하려는 행동>" --step P1.1 --why "<constraint를 벗어나는 이유, 근거 SC ID 포함>" --json
```
- **BLOCK:** 실행하지 않습니다. 이유를 사용자에게 알리고 방향을 바꾸거나 사용자 결정을 기다립니다.
- **WARN:** `reasons`를 읽고 판단합니다. 진행한다면 사용자에게 무엇을 감수하는지 한 줄로 알립니다.
- **ALLOW:** 실행합니다. G03이 있으면 그 step이 추정 구현이라는 사실을 함께 알립니다.
- plan step을 그대로 따르는 행동에는 `--why`가 필요 없습니다.
- plan step과 다른 행동에는 `--why`가 필요합니다. 없거나 관련 없으면 WARN(D01)입니다.
- SourceCheck 결론과 어긋나는 행동에는 `--why`와 그 결론을 뒷받침하는 SC ID가 필요합니다. VERIFIED 결론과 모순되면 BLOCK(S01)입니다.
- "더 쉬워서", "빨라서"는 근거가 되지 않습니다.
- Guard는 사용자 Intent와 별개로 System Policy를 항상 적용합니다.
  - SP1: REQUIRED research가 끝나기 전에는 계획/행동하지 않는다.
  - SP2: 검증된 공식 메커니즘을 근거 없이 비공식 대안으로 바꾸지 않는다.
  - SP3: 문서화된 소유 경계 밖에서 credential에 접근하지 않는다.

판정 뒤에는 host 결정을 남깁니다.
```bash
python pablo.py decide ACT3 proceed --reason "<감수하는 위험>" --json
python pablo.py decide ACT3 defer --reason "<언제 다시 볼지>" --json
python pablo.py decide ACT3 reject --reason "<대신 할 것>" --json
```
- BLOCK은 proceed할 수 없습니다. WARN을 proceed하려면 reason이 필요합니다.

## 6. 실행 결과 기록과 Post Review
행동을 실행했거나 하지 않기로 했으면 결과를 남깁니다. defer, reject도 남깁니다.
```bash
python pablo.py record ACT3 "<실제로 한 일>" --files src/a.py src/b.py --test "tests/x=pass" --observe "<새로 안 사실>" --json
python pablo.py record ACT4 "<왜 안 했나>" --not-executed --json
python pablo.py review EX1 --json
```
- 제안보다 많이 했거나 다른 파일을 고쳤으면 summary와 `--files`에 그대로 적습니다. 숨기지 않습니다.
- diff는 넘기지 않습니다. 경로와 요약만 넘깁니다.
- 조사 도구가 틀렸던 일(요약이 "없다"고 했는데 원문에 있던 경우 등)은 `--observe`로 남깁니다. research issue가 됩니다.
- 실행 중 알게 된 환경 제약이나 사용자에게 물을 것도 `--observe`로 남깁니다.
- review는 Intent와 Plan을 바꾸지 않습니다. `intent_update_proposals`, `plan_update_proposals`를 읽고 사용자와 정합니다.
- `action_alignment`: aligned, partial, deviated, failed, not_executed
- `plan_step_status`: completed, partial, unchanged, blocked

## 7. Evidence Anchor
SourceCheck 결론의 근거가 된 원문 구절에 Evidence ID를 붙입니다.
```bash
python pablo.py source https://learn.chatgpt.com/docs/app-server --json
python pablo.py anchor SRC1 "account/rateLimits/read" --near "fetch ChatGPT rate limits" --json
python pablo.py link E1 SC2 supports --json
python pablo.py resolve E1 --json
```
- 원문은 Pablo가 직접 가져옵니다. 페이지 텍스트를 요약하거나 붙여 넣지 않습니다.
- `anchor`의 문구는 원문 그대로 씁니다. 바꿔 쓰거나 요약하면 거절됩니다.
- 같은 문구가 여러 곳에 있으면 거절됩니다. 원하는 위치 옆의 문구를 `--near`로 줍니다.
- relation: supports, contradicts, verifies, implements, derived_from
- 사용자에게 근거를 말할 때는 E ID를 함께 적습니다. 나중에 다시 검색해 위치를 추측하지 않습니다.
- `resolve`가 STALE이나 UNRESOLVED면 원문이 바뀐 것입니다. 그 근거에 기대기 전에 다시 조사합니다.
- VALID는 문구가 원문에 있다는 뜻입니다. 그 문구가 결론을 뒷받침하는지는 따로 판단해야 합니다.
- 사용자가 근거를 직접 보려면 `view T1 --html`을 실행하고 출력된 파일 경로 뒤에 `#E1`을 붙여 전달합니다.

## 상태 보기
```bash
python pablo.py view T1        # 사람이 보는 task 요약
python pablo.py view T1 --html # 읽기 전용 대화형 화면 (대화 + Source/Intent/Plan/Trace 패널)
python pablo.py show           # 사람이 보는 Intent
```
