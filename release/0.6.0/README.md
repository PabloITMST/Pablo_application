# Pablo 0.6.0 (Release Candidate)

Pablo는 ChatGPT 계정으로 Codex 에이전트를 쓰는 Windows 데스크톱 앱입니다.
작업 기준을 지키는지 Guard가 확인합니다.
PDF 근거를 인용과 하이라이트로 보여줍니다.

## 릴리스 정보

| 항목 | 값 |
|---|---|
| 버전 | 0.6.0 (RC) |
| 빌드 날짜 | 2026-10-08 |
| 플랫폼 | Windows 10/11 x64 |
| 설치 파일 | `PabloSetup.exe` (BYTES_PLACEHOLDER bytes) |
| SHA-256 | `SHA_PLACEHOLDER` |
| 코드 서명 | 없음 (`KNOWN_LIMITATIONS.md` 1번) |

## 이 폴더의 파일

| 파일 | 내용 |
|---|---|
| `PabloSetup.exe` | 설치 파일 |
| `SHA256SUMS.txt` | 배포 파일의 SHA-256 |
| `THIRD_PARTY_NOTICES.txt` | 함께 배포하는 오픈소스의 라이선스·NOTICE 원문 |
| `KNOWN_LIMITATIONS.md` | 알려진 제한사항 |
| `CLEAN_MACHINE_TEST.md` | 깨끗한 PC 검증 절차와 체크리스트 |

## 설치

필요한 것:

- Windows 10/11 x64
- 디스크 여유 2 GB
- 인터넷 연결과 ChatGPT 계정

Python, Node.js, Codex CLI는 필요 없습니다. 모두 설치 파일에 들어 있습니다.

1. 해시를 확인합니다.
   ```powershell
   Get-FileHash .\PabloSetup.exe -Algorithm SHA256
   ```
2. 결과가 위 SHA-256과 같은지 봅니다.
3. `PabloSetup.exe`를 실행합니다.
4. "Windows의 PC 보호" 창이 뜨면 "추가 정보" → "실행"을 누릅니다.
5. 관리자 권한 없이 현재 사용자에게만 설치합니다.
6. 설치가 끝나면 Pablo가 열립니다.

설치 위치:

| 경로 | 내용 |
|---|---|
| `%LOCALAPPDATA%\Pablo\app-0.6.0` | 앱 (읽기 전용으로 씀) |
| `%LOCALAPPDATA%\Pablo\Update.exe` | Squirrel 설치·제거 도구 |
| `%APPDATA%\pablo-desktop` | 사용자 데이터 (로그인 정보, 작업 기록) |

## 처음 쓰기

1. "ChatGPT로 계속하기"를 누릅니다.
2. 브라우저에서 ChatGPT 계정으로 로그인합니다.
3. 앱이 "연결됨"이 되면 새 작업을 만듭니다.
4. 첫 메시지에 작업 목표와 지킬 기준을 적습니다.
5. 작업 폴더를 고르고 요청합니다.
6. 기준과 충돌하면 WARN 카드가 뜹니다. [진행]을 눌러야 실행합니다.
7. 금지한 일이면 BLOCK 카드가 뜨고 실행하지 않습니다.
8. PDF를 추가하고 질문하면 인용이 달린 답이 옵니다.
9. 인용을 누르면 PDF의 해당 문장이 칠해집니다.

로그인 정보:

- Windows DPAPI로 암호화해 `credentials.bin`에 둡니다.
- 앱 화면과 renderer에는 토큰을 넘기지 않습니다.

## 제거

- 설정 → 앱 → 설치된 앱 → Pablo → 제거.
- 사용자 데이터까지 지우려면 `%APPDATA%\pablo-desktop`도 지웁니다.

## 배포 구성과 출처

| 설치 위치 (`app-0.6.0\` 기준) | 구성 요소 | 출처 | 라이선스 (`THIRD_PARTY_NOTICES.txt`) |
|---|---|---|---|
| `Pablo.exe`, `*.dll`, `*.pak`, `locales\` | Electron 41.7.1 / Chromium | npm `electron@41.7.1` | 같은 폴더 `LICENSE`, `LICENSES.chromium.html` |
| `resources\app.asar` (`main.js` 등) | Pablo 데스크톱 코드 | 이 저장소 `desktop\` | — |
| `resources\app.asar` (`node_modules\pdfjs-dist`) | pdf.js 5.6.205 | npm `pdfjs-dist@5.6.205` | 3번, 섹션 A·G |
| `resources\pablo-backend\` | Pablo 백엔드 (PyInstaller onedir) | 이 저장소 `src\pablo_v2` + `pablo.py` | — |
| `resources\pablo-backend\_internal\` | Python 3.11.9 런타임, OpenSSL, VC/UCRT DLL | python.org Windows 배포판 | 4번, 섹션 B·B2 |
| `resources\pablo-backend\_internal\` | pypdf 6.19.0 | PyPI `pypdf==6.19.0` | 5번, 섹션 C |
| `resources\x86_64-pc-windows-msvc\` | OpenAI Codex 0.152.0 (수정 없음) | npm `@openai/codex@0.152.0-win32-x64` | 1번, 섹션 A·D0·D |
| `resources\x86_64-pc-windows-msvc\codex-path\rg.exe` | ripgrep 15.2.0 | Codex 패키지에 포함 | 2번, 섹션 E |
| `..\Update.exe` | Squirrel.Windows | `electron-winstaller` | 7번, 섹션 F |
| `resources\THIRD_PARTY_NOTICES.txt` | 이 고지 파일 | — | — |
| 앱 아이콘, 화면 속 캐릭터 | Pablo 캐릭터 그림 | 프로젝트 자체 그림 (`assets/character/`) | — |

## 빌드 재현

저장소 `README.md`의 Packaging (M6) 절을 따릅니다.

```bash
npm --prefix desktop run backend
npm --prefix desktop run make
```

결과: `desktop/out/make/squirrel.windows/x64/PabloSetup.exe`
