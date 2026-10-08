# Pablo 0.6.0 RC — 깨끗한 PC 검증 절차

개발 PC가 아닌 Windows PC나 새 VM에서 진행합니다.
ChatGPT 로그인은 검증하는 사람이 직접 합니다.

## 0. 준비 조건

아래가 **없는** PC여야 합니다. 시작 전에 확인합니다.

| 확인 | PowerShell 명령 | 기대 결과 |
|---|---|---|
| Python 없음 | `Get-Command python, py -ErrorAction SilentlyContinue` | 출력 없음 (Store 별칭만 있으면 통과) |
| Node/npm 없음 | `Get-Command node, npm -ErrorAction SilentlyContinue` | 출력 없음 |
| Codex CLI 없음 | `Get-Command codex -ErrorAction SilentlyContinue` | 출력 없음 |
| PYTHONPATH 없음 | `$env:PYTHONPATH` | 빈 값 |
| Pablo 소스 없음 | — | 저장소를 복사하지 않음 |

- Windows 10/11 x64, 디스크 여유 2 GB 이상.
- 인터넷 연결과 ChatGPT 계정이 필요합니다.
- 테스트용 PDF 하나를 준비합니다. (개발 검증에는 LinearRAG 논문을 썼습니다.)

## 1. 설치

1. `PabloSetup.exe`의 SHA-256을 확인합니다.
   `Get-FileHash .\PabloSetup.exe -Algorithm SHA256`
2. 값이 `SHA256SUMS.txt`와 같은지 봅니다.
3. `PabloSetup.exe`를 실행합니다.
4. SmartScreen 경고가 뜨면 "추가 정보" → "실행"을 누릅니다.
5. 설치가 끝나면 Pablo가 자동으로 열립니다.
6. 시작 메뉴와 바탕화면에 Pablo 바로가기가 생겼는지 봅니다.

## 2. 체크리스트

각 줄에 결과와 걸린 시간을 적습니다.

| # | 단계 | 통과 기준 | 결과 | 시간 |
|---|---|---|---|---|
| 1 | 실행 | 로그인 카드("ChatGPT로 계속하기")가 뜬다 | | |
| 2 | ChatGPT 로그인 | 브라우저 로그인 후 앱이 "연결됨" 상태가 된다 | | |
| 3 | 새 작업 | 새 작업을 만들고 기준 pill에 입력한 기준이 보인다 | | |
| 4 | 작업 폴더 | 빈 폴더를 고르고 `hello.txt`, `keep.txt`를 만든다 | | |
| 5 | 에이전트 응답 | 요청에 응답이 오고 composer가 Ready로 돌아온다 | | |
| 6 | Guard WARN | 기준과 충돌하는 요청에 WARN 카드가 뜬다. [진행] 전에는 파일이 그대로다 | | |
| 7 | Guard BLOCK | 금지한 파일 삭제 요청에 BLOCK 카드가 뜨고 파일이 그대로다 | | |
| 8 | PDF 추가 | 새 작업에 PDF를 추가하면 소스 목록에 보인다 | | |
| 9 | PDF 질문 | 질문에 인용(cite)이 달린 답이 온다 | | |
| 10 | 인용 하이라이트 | 인용을 누르면 PDF가 열리고 해당 문장이 칠해진다 | | |
| 11 | 재시작 | 앱을 닫고 다시 열면 두 작업과 이전 답이 남아 있다 | | |
| 12 | 후속 대화 | 첫 작업에서 이어서 질문하면 앞 대화를 기억한다 | | |

### 6–7번에 쓸 예시 문장

새 작업 기준:

```
인사말 파일 정리
keep.txt는 절대 수정하거나 삭제하면 안 돼.
hello.txt는 가능하면 영어로만 유지해줘.
```

- WARN: `hello.txt에 한국어 인사 '안녕하세요'도 한 줄 추가해줘.`
- BLOCK: `keep.txt는 이제 필요 없으니 지워줘.`

### 9번에 쓸 예시 질문 (LinearRAG 논문)

- `LinearRAG가 baseline보다 효율적이라는 실험 근거가 어디 있어?`
- 개발 PC 결과: 약 23초 뒤 답. 9쪽 Table 2 행이 칠해짐.

## 3. Release blocker 기준

아래 중 하나라도 나오면 출시를 멈추고 진단합니다.

- 1–12번 중 실패가 있음.
- 10번에서 인용 패널이 **30초 이상** 안 뜸.
- Python, Node, Codex를 설치하라는 오류가 뜸.
- 설치 폴더(`%LOCALAPPDATA%\Pablo\app-0.6.0`) 안의 파일이 바뀜.

30초 지연이 나오면 아래를 모아 보냅니다.

- 인용을 누른 시각과 패널이 뜬 시각
- 패널 화면 캡처
- PDF 파일 크기와 쪽수, PC 사양(CPU, RAM, 디스크 종류)
- `%APPDATA%\pablo-desktop` 폴더는 보내지 않습니다. 로그인 정보(`credentials.bin`)가 들어 있습니다.

## 4. 정리

- 제거: 설정 → 앱 → 설치된 앱 → Pablo → 제거.
- 남은 사용자 데이터: `%APPDATA%\pablo-desktop` 폴더를 지웁니다.
- 이 폴더에 암호화한 로그인 정보가 있습니다.

## 5. 개발 PC에서 이미 확인한 것

깨끗한 PC 검증을 대신하지 않습니다. 참고용입니다.

- 설치본을 최소 환경(PATH=System32, 빈 cwd)으로 실행했습니다.
- 1–12번 흐름 전체가 자동 검증(`desktop/rc.js`)으로 통과했습니다.
- Codex 프로세스 경로가 설치 폴더 `resources` 안인지 확인했습니다.
- 실행 전후로 `resources` 폴더가 바뀌지 않았습니다.
- 빈 사용자 데이터로 실행하면 1.3초 만에 로그인 카드가 떴습니다.
