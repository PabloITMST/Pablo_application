# 재현 점검 벤치마크 — 2026-10-13

- 변형 9개 (씨앗 7, 깨끗한 변형 포함), 심은 어긋남 18개, 채점한 '따름' 조건 131개
- 모델: gpt-5.6-luna, 점검 1회 평균 75828 ms

| 지표 | 값 | 뜻 |
|---|---|---|
| 탐지율 | 100.0% (18/18) | 심은 어긋남을 다름·없음으로 짚은 비율 |
| 판정 정확도 | 100.0% | 심은 어긋남의 상태(다름/없음)까지 맞힌 비율 |
| 오탐률 | 6.9% (9/131) | 따르는 조건을 다름·없음으로 짚은 비율 |
| 따름 확인 | 93.1% | 따르는 조건을 '따름'으로 본 비율 |
| 판단 보류 | 0.0% | 따르는 조건을 '판단 못 함'으로 둔 비율 |
| 위치(파일) | 94.4% | 짚은 어긋남 중 파일이 맞은 비율 |
| 위치(줄 ±1) | 94.1% | 짚은 어긋남 중 줄까지 맞은 비율 (코드를 지운 어긋남 제외) |
| 논문에 없는 설정 | 100.0% | 시드를 '코드가 정함'으로 본 비율 |

## 어긋남별

| 어긋남 | 심은 수 | 탐지 | 상태 일치 | 파일 | 줄 |
|---|---|---|---|---|---|
| contain_missing | 1 | 1 | 1 | 1 | 0 |
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
| split_test | 1 | 1 | 1 | 0 | 0 |
| topk_config | 1 | 1 | 1 | 1 | 1 |
| topk_hardcoded | 1 | 1 | 1 | 1 | 1 |

## 방법 조건 (값이 아니라 코드가 하는 일)

- 바탕 폴더(또는 어긋남)가 논문과 다르게 하는 단계: 29/29 짚음 (100.0%)
- 논문대로 하는 단계를 다르다고 함: 0/14 (0.0%), 판단 못 함 0

| 조건 | 다른 단계 짚음 | 따르는 단계 오탐 |
|---|---|---|
| Tri-Graph는 entity, sentence, passage 노드와 entity-문장 및 entity-passage 연결로 구성된다. | 0/0 | 0/0 |
| 질문에서 추출한 각 entity는 그래프에서 가장 유사한 entity에 초기 활성화된다. | 9/9 | 0/0 |
| 문장-entity 그래프에서 질문-문장 유사도를 이용해 중간 entity의 활성화 점수를 전파한다. | 9/9 | 0/0 |
| 각 전파 단계에서 관련성 점수가 임계값을 넘는 새 entity만 다음 반복에 유지한다. | 9/9 | 0/0 |
| 활성화된 entity를 seed로 사용해 entity-passage 그래프에서 Personalized PageRank로 passage 중요도를 집계한다. | 1/1 | 0/8 |
| 최종 검색 결과는 passage의 PageRank 점수가 높은 top-k passage이다. | 1/1 | 0/6 |

## Pablo 확인 (점검 답의 파일:줄을 Pablo가 직접 읽은 결과)

- 규칙: desktop/where.js로 다시 계산 (변형을 씨앗에서 다시 만들어)
- 짚은 어긋남: verified 17, not_found 1
- 따르는 조건: verified 121, value_mismatch 1 (verified 외에는 Pablo 쪽의 거짓 경고)
- 방법 조건(판정 무관): verified 54
- 대조 (각 답을 다음 변형의 폴더에서 확인): 짚은 어긋남 not_found 15, verified 3. verified 외에는 옛 폴더·지어낸 위치를 잡은 것

## 오탐 (따르는데 다름·없음으로 짚은 조건)

- embedding: 5회
- delta: 4회

## 변형별

| 변형 | 심은 것 | 찾음 | 놓침 | 오탐 |
|---|---|---|---|---|
| v00-clean | - | - | - | - |
| v01 | contain_missing, ppr_degree, segment_window | contain_missing, ppr_degree, segment_window | - | - |
| v02 | embedding, delta, damping | embedding, delta, damping | - | - |
| v03 | split_test, medical_both | split_test, medical_both | - | delta(differs), embedding(differs) |
| v04 | result_gpt_low, questions_500 | result_gpt_low, questions_500 | - | delta(differs) |
| v05 | datasets_drop, topk_hardcoded | datasets_drop, topk_hardcoded | - | delta(differs), embedding(differs) |
| v06 | lambda, topk_config | lambda, topk_config | - | delta(differs), embedding(differs) |
| v07 | ner_regex, result_contain_low | ner_regex, result_contain_low | - | embedding(differs) |
| v08 | llm, graph_no_sentences | llm, graph_no_sentences | - | embedding(differs) |
