# 재현 점검 벤치마크 — 2026-10-13

- 변형 9개 (씨앗 7, 깨끗한 변형 포함), 심은 어긋남 18개, 채점한 '따름' 조건 131개
- 모델: gpt-5.6-luna, 점검 1회 평균 44292 ms

| 지표 | 값 | 뜻 |
|---|---|---|
| 탐지율 | 100.0% (18/18) | 심은 어긋남을 다름·없음으로 짚은 비율 |
| 판정 정확도 | 94.4% | 심은 어긋남의 상태(다름/없음)까지 맞힌 비율 |
| 오탐률 | 0.0% (0/131) | 따르는 조건을 다름·없음으로 짚은 비율 |
| 따름 확인 | 100.0% | 따르는 조건을 '따름'으로 본 비율 |
| 판단 보류 | 0.0% | 따르는 조건을 '판단 못 함'으로 둔 비율 |
| 위치(파일) | 100.0% | 짚은 어긋남 중 파일이 맞은 비율 |
| 위치(줄 ±1) | 100.0% | 짚은 어긋남 중 줄까지 맞은 비율 (코드를 지운 어긋남 제외) |
| 논문에 없는 설정 | 100.0% | 시드를 '코드가 정함'으로 본 비율 |

## 어긋남별

| 어긋남 | 심은 수 | 탐지 | 상태 일치 | 파일 | 줄 |
|---|---|---|---|---|---|
| contain_missing | 1 | 1 | 0 | 1 | 0 |
| damping | 1 | 1 | 1 | 1 | 1 |
| datasets_drop | 1 | 1 | 1 | 1 | 1 |
| delta | 1 | 1 | 1 | 1 | 1 |
| embedding | 1 | 1 | 1 | 1 | 1 |
| graph_no_sentences | 1 | 1 | 1 | 1 | 1 |
| lambda | 1 | 1 | 1 | 1 | 1 |
| llm | 1 | 1 | 1 | 1 | 1 |
| medical_both | 1 | 1 | 1 | 1 | 1 |
| ner_regex | 1 | 1 | 1 | 1 | 1 |
| ppr_degree | 1 | 1 | 1 | 1 | 1 |
| questions_500 | 1 | 1 | 1 | 1 | 1 |
| result_contain_low | 1 | 1 | 1 | 1 | 1 |
| result_gpt_low | 1 | 1 | 1 | 1 | 1 |
| segment_window | 1 | 1 | 1 | 1 | 1 |
| split_test | 1 | 1 | 1 | 1 | 1 |
| topk_config | 1 | 1 | 1 | 1 | 1 |
| topk_hardcoded | 1 | 1 | 1 | 1 | 1 |

## Pablo 확인 (점검 답의 파일:줄을 Pablo가 직접 읽은 결과)

- 규칙: desktop/where.js로 다시 계산 (변형을 씨앗에서 다시 만들어)
- 짚은 어긋남: verified 18
- 따르는 조건: verified 131 (verified 외에는 Pablo 쪽의 거짓 경고)
- 대조 (각 답을 다음 변형의 폴더에서 확인): 짚은 어긋남 not_found 15, verified 2, moved 1. verified 외에는 옛 폴더·지어낸 위치를 잡은 것

## 오탐 (따르는데 다름·없음으로 짚은 조건)

- 없음

## 변형별

| 변형 | 심은 것 | 찾음 | 놓침 | 오탐 |
|---|---|---|---|---|
| v00-clean | - | - | - | - |
| v01 | contain_missing, ppr_degree, segment_window | contain_missing, ppr_degree, segment_window | - | - |
| v02 | embedding, delta, damping | embedding, delta, damping | - | - |
| v03 | split_test, medical_both | split_test, medical_both | - | - |
| v04 | result_gpt_low, questions_500 | result_gpt_low, questions_500 | - | - |
| v05 | datasets_drop, topk_hardcoded | datasets_drop, topk_hardcoded | - | - |
| v06 | lambda, topk_config | lambda, topk_config | - | - |
| v07 | ner_regex, result_contain_low | ner_regex, result_contain_low | - | - |
| v08 | llm, graph_no_sentences | llm, graph_no_sentences | - | - |
