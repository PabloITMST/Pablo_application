# 점검 카드에 펼쳐지는 행 — 2026-10-14 (e2e2)

- 변형 9개, 모델 gpt-5.6-luna, 점검 1회 평균 91741 ms
- 카드당 판정 26.0행, 그중 펼쳐진 행 15.4행 (조건 밖 방법 차이 포함)
- 지금 카드(8f48e1a: 종류가 없는 조건의 아직 없음만 이름을 보이며 접음)로는 15.4행

| 펼쳐진 행 | 합 | 카드당 | 지금 카드 카드당 |
|---|---|---|---|
| 심은 어긋남 | 21 | 2.3 | 2.3 |
| 바탕의 방법 차이 | 42 | 4.7 | 4.7 |
| 논문에 없는 설정(코드가 정함) | 40 | 4.4 | 4.4 |
| 따름/판단 못 함에 붙은 확인 경고 | 1 | 0.1 | 0.1 |
| 그 밖 (손으로 읽음) | 35 | 3.9 | 3.9 |

- 심은 어긋남 18개 중 지금 카드에서 펼쳐진 칸에 보이는 것 17개, 접힌 아직 없음에만 있는 것 0개
- 지금 카드가 접는 아직 없음 0행: 

## 변형별

| 변형 | 판정 | 펼쳐짐 | 심은 어긋남 | 바탕의 방법 차이 | 논문에 없는 설정(코드가 정함) | 따름/판단 못 함에 붙은 확인 경고 | 그 밖 (손으로 읽음) |
|---|---|---|---|---|---|---|---|
| v00-clean | 26 | 14 | 0 | 5 | 5 | 0 | 4 |
| v01 | 26 | 19 | 4 | 6 | 4 | 0 | 5 |
| v02 | 26 | 15 | 2 | 5 | 5 | 0 | 3 |
| v03 | 26 | 15 | 2 | 5 | 4 | 0 | 4 |
| v04 | 26 | 14 | 2 | 4 | 5 | 1 | 2 |
| v05 | 26 | 16 | 3 | 3 | 5 | 0 | 5 |
| v06 | 26 | 15 | 2 | 5 | 4 | 0 | 4 |
| v07 | 26 | 14 | 3 | 5 | 3 | 0 | 3 |
| v08 | 26 | 17 | 3 | 4 | 5 | 0 | 5 |

## 조건별 판정 (변형 전체)

| 조건 | 분류 | 판정 |
|---|---|---|
| 주요 실험은 HotpotQA, 2WikiMultiHopQA, MuSiQue, Medical의 네 데이터셋에서 수행한다. | dataset | followed 7, missing 2 |
| HotpotQA는 약 97,000개의 질문-답변 인스턴스로 구성된다. | dataset · fact | 점검이 묻지 않음 |
| 2WikiMultiHopQA는 약 192,000개의 질문을 포함한다. | dataset · fact | 점검이 묻지 않음 |
| MuSiQue는 약 25,000개의 질문-답변 쌍으로 구성된다. | dataset · fact | 점검이 묻지 않음 |
| Medical 데이터셋은 NCCN 임상 지침에서 구축된 4,076개 질문을 포함한다. | dataset · fact | 점검이 묻지 않음 |
| 각 데이터셋의 검증 세트에서 1,000개 질문을 선택한다. | split | followed 6, differs 2, missing 1 |
| 각 passage를 구두점으로 문장 분할한다. | preprocessing | followed 7, differs 1, missing 1 |
| spaCy로 코퍼스와 질의에서 명명 개체를 추출한다. | preprocessing | differs 7, followed 2 |
| 모든 방법은 all-mpnet-base-v2 임베딩 모델을 사용한다. | model | followed 8, differs 1 |
| 생성과 평가에는 GPT-4o-mini를 사용한다. | model | followed 8, differs 1 |
| 모든 방법의 top-k 검색값은 5이다. | hyperparameter | followed 7, differs 2 |
| Tri-Graph는 entity, sentence, passage 노드와 entity-문장 및 entity-passage 엣지를 포함하는 계층 그래프를 구축한다. | method | followed 8, differs 1 |
| 첫 단계는 passage 노드를 고정하고 entity-문장 부분 그래프에서 semantic bridging으로 중간 entity를 활성화한다. | method | differs 9 |
| semantic propagation은 질의-문장 유사도를 문장-entity 그래프를 통해 전파해 관련 중간 entity를 활성화한다. | method | differs 8, missing 1 |
| 각 전파 단계에서 relevance score가 임계값보다 큰 새 entity만 다음 반복으로 유지한다. | method | differs 9 |
| 두 번째 단계는 활성화된 entity를 초기값으로 사용해 passage-entity 그래프에서 Personalized PageRank로 전역 중요도를 계산한다. | method | followed 8, differs 1 |
| 검색된 passage는 PPR 점수로 순위를 매기고 가장 높은 top-k passage를 선택한다. | method | followed 8, differs 1 |
| 동적 pruning 임계값 δ는 4로 설정한다. | hyperparameter | followed 8, differs 1 |
| passage 초기 점수에서 DPR 유사도와 entity 정보의 균형 계수 λ는 0.05로 설정한다. | hyperparameter | followed 8, differs 1 |
| Contain-Match Accuracy는 생성 응답에 정답이 포함되는지를 평가한다. | metric | followed 8, missing 1 |
| GPT-Evaluation Accuracy는 LLM이 예측 답변과 정답의 일치 여부를 평가한다. | metric | followed 9 |
| Medical 데이터셋은 GPT-ACC만으로 평가한다. | metric | followed 8, differs 1 |
| 비교 대상에는 zero-shot LLM, Vanilla RAG, KGP, G-Retriever, RAPTOR, E2GraphRAG, LightRAG, HippoRAG, GFM-RAG, HippoRAG2가 포함된다. | baseline · scope | 점검이 묻지 않음 |
| Vanilla RAG baseline은 1, 3, 5개 passage 검색 설정을 사용한다. | baseline | missing 9 |
| 실험 하드웨어는 NVIDIA GeForce RTX 4090 D 24GB GPU와 Intel Xeon Gold 6426Y CPU이다. | training · fact | 점검이 묻지 않음 |
| LinearRAG는 HotpotQA, 2Wiki, MuSiQue, Medical에서 각각 64.30, 66.50, 70.20, 63.70의 Contain-Acc. 또는 GPT-Acc. 결과를 보고한다. | result · result | differs 9 |
| LinearRAG의 전체 파이프라인 정확도는 66.95이다. | result · result | missing 9 |
| 주요 실험의 난수 시드가 명시되지 않았다. | training (논문에 없음) | chosen 9 |
| 주요 실험의 반복 실행 횟수와 결과 집계 방식이 명시되지 않았다. | training (논문에 없음) | chosen 9 |
| 생성 및 평가에 사용한 구체적인 프롬프트 템플릿이 명시되지 않았다. | method (논문에 없음) | chosen 9 |
| LLM 생성의 decoding 설정이 명시되지 않았다. | method (논문에 없음) | chosen 5, unclear 3, missing 1 |
| spaCy의 구체적인 모델명과 버전이 명시되지 않았다. | preprocessing (논문에 없음) | chosen 9 |

## 그 밖의 펼쳐진 행 35개

- v00-clean differs [preprocessing] spaCy로 코퍼스와 질의에서 명명 개체를 추출한다. — 코퍼스에는 spaCy NER를 적용하지만 질의는 spaCy로 추출하지 않고 입력 entities를 그대로 사용한다.
- v00-clean missing [baseline] Vanilla RAG baseline은 1, 3, 5개 passage 검색 설정을 사용한다. — Vanilla RAG baseline의 1·3·5 passage 설정이나 실행 코드가 없다.
- v00-clean differs [result] LinearRAG는 HotpotQA, 2Wiki, MuSiQue, Medical에서 각각 64.30, 66. — 기록된 2Wiki 결과가 논문의 LinearRAG 값 66.50과 일치하지 않으며 나머지 데이터셋 로그도 없다.
- v00-clean missing [result] LinearRAG의 전체 파이프라인 정확도는 66.95이다. — 전체 파이프라인 정확도 66.95를 산출하거나 보고한 로그가 없다.
- v01 differs [preprocessing] spaCy로 코퍼스와 질의에서 명명 개체를 추출한다. — 코퍼스 문장은 spaCy로 처리하지만 질의에서는 추출하지 않고 사전 제공된 entities를 사용합니다.
- v01 missing [baseline] Vanilla RAG baseline은 1, 3, 5개 passage 검색 설정을 사용한다. — 1·3·5 passage Vanilla RAG baseline을 구현하거나 실행한 흔적이 없습니다.
- v01 differs [result] LinearRAG는 HotpotQA, 2Wiki, MuSiQue, Medical에서 각각 64.30, 66. — 2Wiki 로그 값이 논문의 66.50과 다르고 나머지 세 데이터셋 결과도 없습니다.
- v01 missing [result] LinearRAG의 전체 파이프라인 정확도는 66.95이다. — 전체 파이프라인 정확도 66.95를 계산하거나 보고한 로그가 없습니다.
- v01 missing [method] LLM 생성의 decoding 설정이 명시되지 않았다. — temperature, max_tokens 등 decoding 설정을 명시하지 않습니다.
- v02 missing [baseline] Vanilla RAG baseline은 1, 3, 5개 passage 검색 설정을 사용한다. — 1·3·5 passage Vanilla RAG baseline을 구현하거나 실행한 근거가 없다.
- v02 differs [result] LinearRAG는 HotpotQA, 2Wiki, MuSiQue, Medical에서 각각 64.30, 66. — 네 데이터셋의 논문 보고값 전체가 없고, 기록된 2Wiki GPT-ACC 63.70도 논문값 66.50과 다르다.
- v02 missing [result] LinearRAG의 전체 파이프라인 정확도는 66.95이다. — 전체 파이프라인 정확도 66.95를 기록한 로그나 계산 코드가 없다.
- v03 missing [baseline] Vanilla RAG baseline은 1, 3, 5개 passage 검색 설정을 사용한다. — Vanilla RAG baseline의 1·3·5 passage 비교 구현이나 로그가 없다.
- v03 differs [result] LinearRAG는 HotpotQA, 2Wiki, MuSiQue, Medical에서 각각 64.30, 66. — 2Wiki 로그 값이 논문 기준 66.50과 다르고 나머지 세 데이터셋 결과도 보고되지 않았다.
- v03 missing [result] LinearRAG의 전체 파이프라인 정확도는 66.95이다. — 전체 파이프라인 정확도 66.95를 기록하거나 계산한 결과가 없다.
- v03 outside [조건 밖]  — 실행 로그와 설정 파일의 데이터 split이 서로 다르다.
- v04 missing [baseline] Vanilla RAG baseline은 1, 3, 5개 passage 검색 설정을 사용한다. — Vanilla RAG baseline과 1·3·5 passage 설정 구현이나 로그가 없다.
- v04 missing [result] LinearRAG의 전체 파이프라인 정확도는 66.95이다. — 전체 파이프라인 정확도 66.95를 계산하거나 보고한 코드·로그가 없다.
- v05 differs [preprocessing] spaCy로 코퍼스와 질의에서 명명 개체를 추출한다. — spaCy는 문장에서만 호출되고 질의의 명명 개체는 spaCy로 추출하지 않는다.
- v05 missing [baseline] Vanilla RAG baseline은 1, 3, 5개 passage 검색 설정을 사용한다. — 1·3·5 passage Vanilla RAG baseline 구현이나 실행 흔적이 없다.
- v05 differs [result] LinearRAG는 HotpotQA, 2Wiki, MuSiQue, Medical에서 각각 64.30, 66. — 네 데이터셋 결과가 모두 보고되지 않았고 2Wiki의 보고값도 논문의 66.50과 다르다.
- v05 missing [result] LinearRAG의 전체 파이프라인 정확도는 66.95이다. — 전체 파이프라인 정확도 66.95를 기록한 로그나 코드가 없다.
- v05 outside [조건 밖]  — 설정한 all-mpnet-base-v2 임베더를 실제 검색 계산에 사용하지 않는다.
- v06 differs [preprocessing] spaCy로 코퍼스와 질의에서 명명 개체를 추출한다. — 코퍼스 문장에서는 spaCy 개체를 추출하지만 질의에서는 미리 제공된 entities를 사용한다.
- v06 missing [baseline] Vanilla RAG baseline은 1, 3, 5개 passage 검색 설정을 사용한다. — 1·3·5 passage Vanilla RAG baseline 구현이나 실행 설정이 없다.
- v06 differs [result] LinearRAG는 HotpotQA, 2Wiki, MuSiQue, Medical에서 각각 64.30, 66. — 네 데이터셋 결과가 모두 보고되지 않았고, 보고된 2Wiki 값도 논문의 66.50과 다르다.
- v06 missing [result] LinearRAG의 전체 파이프라인 정확도는 66.95이다. — 전체 파이프라인 정확도 66.95를 산출하거나 기록한 로그가 없다.
- v07 missing [dataset] 주요 실험은 HotpotQA, 2WikiMultiHopQA, MuSiQue, Medical의 네 데이터셋에서 — 설정에는 네 데이터셋이 있으나 실행 로그는 2Wiki 하나만 존재한다.
- v07 missing [baseline] Vanilla RAG baseline은 1, 3, 5개 passage 검색 설정을 사용한다. — 1·3·5 passage Vanilla RAG baseline 구현이나 실행 로그가 없다.
- v07 missing [result] LinearRAG의 전체 파이프라인 정확도는 66.95이다. — 전체 파이프라인 정확도 66.95를 계산하거나 기록하는 코드와 로그가 없다.
- v08 differs [preprocessing] spaCy로 코퍼스와 질의에서 명명 개체를 추출한다. — 코퍼스에는 spaCy를 적용하지만 질의에서는 미리 제공된 entities를 사용하고 spaCy로 추출하지 않습니다.
- v08 missing [baseline] Vanilla RAG baseline은 1, 3, 5개 passage 검색 설정을 사용한다. — Vanilla RAG의 1·3·5 passage 비교 baseline 코드나 로그가 없습니다.
- v08 differs [result] LinearRAG는 HotpotQA, 2Wiki, MuSiQue, Medical에서 각각 64.30, 66. — 2Wiki 로그값이 논문의 66.50과 다르고 나머지 세 데이터셋 결과도 보고되지 않았습니다.
- v08 missing [result] LinearRAG의 전체 파이프라인 정확도는 66.95이다. — 전체 파이프라인 정확도 66.95를 계산하거나 기록하는 코드와 로그가 없습니다.
- v08 outside [조건 밖]  — PPR의 damping 계수 0.85가 별도 설정으로 사용됩니다.
