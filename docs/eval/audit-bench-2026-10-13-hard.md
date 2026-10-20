# 재현 점검 벤치마크 — 2026-10-13

- 변형 7개 (씨앗 7, 깨끗한 변형 포함), 심은 어긋남 12개, 채점한 '따름' 조건 105개
- 모델: gpt-5.6-luna, 점검 1회 평균 76687 ms

| 지표 | 값 | 뜻 |
|---|---|---|
| 탐지율 | 83.3% (10/12) | 심은 어긋남을 다름·없음으로 짚은 비율 |
| 판정 정확도 | 83.3% | 심은 어긋남의 상태(다름/없음)까지 맞힌 비율 |
| 오탐률 | 1.9% (2/105) | 따르는 조건을 다름·없음으로 짚은 비율 |
| 따름 확인 | 98.1% | 따르는 조건을 '따름'으로 본 비율 |
| 판단 보류 | 0.0% | 따르는 조건을 '판단 못 함'으로 둔 비율 |
| 위치(파일) | 100.0% | 짚은 어긋남 중 파일이 맞은 비율 |
| 위치(줄 ±1) | 100.0% | 짚은 어긋남 중 줄까지 맞은 비율 (코드를 지운 어긋남 제외) |
| 논문에 없는 설정 | 92.9% | 시드를 '코드가 정함'으로 본 비율 |

## 어긋남별

| 어긋남 | 심은 수 | 탐지 | 상태 일치 | 파일 | 줄 |
|---|---|---|---|---|---|
| contain_swapped | 1 | 1 | 1 | 1 | 1 |
| damping_inverted | 1 | 0 | 0 | 0 | 0 |
| embedding_env | 1 | 1 | 1 | 1 | 1 |
| judge_model | 1 | 1 | 1 | 1 | 1 |
| lambda_comment | 1 | 1 | 1 | 1 | 1 |
| log_questions | 1 | 1 | 1 | 1 | 1 |
| medical_case | 1 | 1 | 1 | 1 | 1 |
| questions_offbyone | 1 | 1 | 1 | 1 | 1 |
| seed_unused | 1 | 0 | 0 | 0 | 0 |
| split_hardcoded | 1 | 1 | 1 | 1 | 1 |
| topk_cli | 1 | 1 | 1 | 1 | 1 |
| topk_offbyone | 1 | 1 | 1 | 1 | 1 |

## 방법 조건 (값이 아니라 코드가 하는 일)

- 바탕 폴더(또는 어긋남)가 논문과 다르게 하는 단계: 21/21 짚음 (100.0%)
- 논문대로 하는 단계를 다르다고 함: 0/11 (0.0%), 판단 못 함 0

| 조건 | 다른 단계 짚음 | 따르는 단계 오탐 |
|---|---|---|
| Tri-Graph는 entity, sentence, passage 노드와 entity-문장 및 entity-passage 연결로 구성된다. | 0/0 | 0/0 |
| 질문에서 추출한 각 entity는 그래프에서 가장 유사한 entity에 초기 활성화된다. | 7/7 | 0/0 |
| 문장-entity 그래프에서 질문-문장 유사도를 이용해 중간 entity의 활성화 점수를 전파한다. | 7/7 | 0/0 |
| 각 전파 단계에서 관련성 점수가 임계값을 넘는 새 entity만 다음 반복에 유지한다. | 7/7 | 0/0 |
| 활성화된 entity를 seed로 사용해 entity-passage 그래프에서 Personalized PageRank로 passage 중요도를 집계한다. | 0/0 | 0/6 |
| 최종 검색 결과는 passage의 PageRank 점수가 높은 top-k passage이다. | 0/0 | 0/5 |

## Pablo 확인 (점검 답의 파일:줄을 Pablo가 직접 읽은 결과)

- 규칙: desktop/where.js로 다시 계산 (변형을 씨앗에서 다시 만들어)
- 짚은 어긋남: verified 9, not_found 1
- 따르는 조건: verified 95, value_mismatch 8 (verified 외에는 Pablo 쪽의 거짓 경고)
- 방법 조건(판정 무관): verified 42
- 대조 (각 답을 다음 변형의 폴더에서 확인): 짚은 어긋남 not_found 9, verified 1. verified 외에는 옛 폴더·지어낸 위치를 잡은 것

## 오탐 (따르는데 다름·없음으로 짚은 조건)

- embedding: 1회
- ppr: 1회

## 변형별

| 변형 | 심은 것 | 찾음 | 놓침 | 오탐 |
|---|---|---|---|---|
| v00-clean | - | - | - | - |
| v01 | medical_case, embedding_env | medical_case, embedding_env | - | - |
| v02 | lambda_comment, topk_cli | lambda_comment, topk_cli | - | - |
| v03 | questions_offbyone, topk_offbyone | questions_offbyone, topk_offbyone | - | embedding(differs) |
| v04 | seed_unused, contain_swapped | contain_swapped | seed_unused(chosen) | - |
| v05 | judge_model, split_hardcoded | judge_model, split_hardcoded | - | - |
| v06 | log_questions, damping_inverted | log_questions | damping_inverted(followed) | ppr(differs) |
