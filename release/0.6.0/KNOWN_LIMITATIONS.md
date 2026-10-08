# Pablo 0.6.0 RC — 알려진 제한사항

이번 릴리스에서는 아래 항목을 고치지 않습니다.
기능 코드는 0.6.0 RC로 동결했습니다.

## 1. 서명하지 않은 설치 파일

- `PabloSetup.exe`와 `Pablo.exe`에 코드 서명이 없습니다.
- 처음 실행하면 SmartScreen이 "Windows의 PC 보호" 창을 띄웁니다.
- 게시자는 "알 수 없는 게시자"로 표시됩니다.
- 진행 방법: "추가 정보" → "실행"을 누릅니다.
- 설치 전에 `SHA256SUMS.txt` 값과 파일 해시를 비교합니다.
- 서명 인증서가 생기면 다시 빌드해서 서명합니다.

## 2. 읽기 요청의 Guard 지연

- 파일을 읽기만 하는 요청도 Guard 판정을 거칩니다.
- 그래서 단순 읽기 응답이 몇 초 늦을 수 있습니다.
- Guard 정책과 fast path는 M5 기준으로 동결했습니다.

## 3. Electron fuse 미설정

- Electron fuse를 바꾸지 않았습니다.
- `RunAsNode`, `--inspect` 같은 디버그 스위치가 그대로 켜져 있습니다.
- 로컬 사용자는 이 스위치로 앱 프로세스에 붙을 수 있습니다.
- 토큰은 DPAPI로 암호화해 main 프로세스에만 둡니다.
- 하지만 같은 Windows 계정의 로컬 공격자까지 막지는 못합니다.

## 4. PDF 첫 열기 지연

- 앱을 켜고 처음 인용을 열 때 가끔 늦게 뜹니다.
- 측정값은 보통 0.5–1.1초입니다.
- 개발 PC에서 30초 안에 패널이 안 뜬 경우가 한 번 있었습니다.
- 그 뒤 5회 이상 다시 돌렸지만 재현하지 못했습니다.
- 다른 PC에서 30초 이상 지연이 재현되면 release blocker로 다룹니다.

## 5. PDF 질문 문장을 저장하지 않음

- PDF 질문의 답과 인용은 재시작 후에도 남습니다.
- 질문 문장 자체는 저장하지 않습니다.
- 재시작하면 답만 보입니다.

## 6. 용량

| 항목 | 크기 |
|---|---|
| `PabloSetup.exe` | 약 290 MB |
| 설치 후 (`%LOCALAPPDATA%\Pablo`) | 약 1.1 GB |
| 그중 Codex 런타임 | 약 375 MB |
| 그중 Python 백엔드 | 약 20 MB |

- Electron, Codex, Python 런타임을 모두 함께 넣었기 때문입니다.
- 설치 폴더에 `Pablo-0.6.0-full.nupkg` 사본도 남습니다.

## 7. 자동 업데이트 없음

- Squirrel 설치기를 쓰지만 업데이트 서버가 없습니다.
- 새 버전은 새 `PabloSetup.exe`를 다시 설치합니다.

## 8. Codex 바이너리 내부 crate 라이선스

- Codex 상위 저장소는 LICENSE와 NOTICE만 제공합니다.
- `codex.exe`에 정적으로 링크한 Rust crate별 라이선스 목록은 없습니다.
- Pablo는 Codex 바이너리를 수정하지 않고 그대로 재배포합니다.
- LICENSE와 NOTICE 원문은 `THIRD_PARTY_NOTICES.txt` 섹션 A, D0, D에 있습니다.

## 9. Windows x64 전용

- Windows 10/11 x64만 지원합니다.
- macOS, Linux, ARM64 빌드는 없습니다.

## 10. 다른 PC 검증 미완료

- 개발 PC에서는 설치본 E2E가 통과했습니다.
- Python, Node, Codex CLI가 없는 깨끗한 PC 검증은 아직 하지 않았습니다.
- 절차는 `CLEAN_MACHINE_TEST.md`에 있습니다.
