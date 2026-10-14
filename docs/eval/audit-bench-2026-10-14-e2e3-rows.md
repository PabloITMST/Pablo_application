# 점검 카드에 펼쳐지는 행 — 2026-10-14 (e2e3)

- 변형 9개, 모델 gpt-5.6-luna, 점검 1회 평균 90681 ms
- 카드당 판정 25.0행, 그중 펼쳐진 행 14.0행 (조건 밖 방법 차이 포함)
- 지금 카드(8f48e1a: 종류가 없는 조건의 아직 없음만 이름을 보이며 접음)로는 14.0행

| 펼쳐진 행 | 합 | 카드당 | 지금 카드 카드당 |
|---|---|---|---|
| 심은 어긋남 | 18 | 2.0 | 2.0 |
| 바탕의 방법 차이 | 42 | 4.7 | 4.7 |
| 논문에 없는 설정(코드가 정함) | 36 | 4.0 | 4.0 |
| 따름/판단 못 함에 붙은 확인 경고 | 0 | 0.0 | 0.0 |
| 그 밖 (손으로 읽음) | 30 | 3.3 | 3.3 |

- 심은 어긋남 18개 중 지금 카드에서 펼쳐진 칸에 보이는 것 16개, 접힌 아직 없음에만 있는 것 0개
- 지금 카드가 접는 아직 없음 0행: 

## 변형별

| 변형 | 판정 | 펼쳐짐 | 심은 어긋남 | 바탕의 방법 차이 | 논문에 없는 설정(코드가 정함) | 따름/판단 못 함에 붙은 확인 경고 | 그 밖 (손으로 읽음) |
|---|---|---|---|---|---|---|---|
| v00-clean | 25 | 13 | 0 | 3 | 3 | 0 | 7 |
| v01 | 25 | 16 | 4 | 6 | 4 | 0 | 2 |
| v02 | 25 | 15 | 2 | 6 | 4 | 0 | 3 |
| v03 | 25 | 14 | 2 | 6 | 4 | 0 | 2 |
| v04 | 25 | 13 | 2 | 6 | 4 | 0 | 1 |
| v05 | 25 | 13 | 1 | 4 | 4 | 0 | 4 |
| v06 | 25 | 14 | 2 | 4 | 5 | 0 | 3 |
| v07 | 25 | 12 | 3 | 3 | 4 | 0 | 2 |
| v08 | 25 | 16 | 2 | 4 | 4 | 0 | 6 |

## 조건별 판정 (변형 전체)

| 조건 | 분류 | 판정 |
|---|---|---|
| 주요 실험은 HotpotQA, 2WikiMultiHopQA, MuSiQue, Medical의 네 데이터셋에서 수행한다. | dataset | followed 5, missing 3, unclear 1 |
| HotpotQA는 약 97,000개의 질문-답변 인스턴스로 구성된다. | dataset · fact | 점검이 묻지 않음 |
| 2WikiMultiHopQA는 약 192,000개의 질문을 포함한다. | dataset · fact | 점검이 묻지 않음 |
| MuSiQue는 약 25,000개의 질문-답변 쌍으로 구성된다. | dataset · fact | 점검이 묻지 않음 |
| Medical 데이터셋은 NCCN 임상 지침에서 구축된 4,076개 질문을 포함한다. | dataset · fact | 점검이 묻지 않음 |
| 각 데이터셋의 검증 세트에서 1,000개 질문을 선택한다. | split | followed 4, missing 2, differs 2, unclear 1 |
| 각 passage를 구두점으로 문장 분할한다. | preprocessing | followed 7, differs 1, missing 1 |
| spaCy로 코퍼스와 질의에서 명명 개체를 추출한다. | preprocessing | differs 8, followed 1 |
| 모든 방법은 all-mpnet-base-v2 임베딩 모델을 사용한다. | model | followed 8, differs 1 |
| 생성과 평가에는 GPT-4o-mini를 사용한다. | model | followed 8, differs 1 |
| 모든 방법의 top-k 검색값은 5이다. | hyperparameter | followed 7, differs 2 |
| Tri-Graph는 entity, sentence, passage 노드와 entity-문장 및 entity-passage 엣지를 포함하는 계층 그래프를 구축한다. | method | followed 8, differs 1 |
| 첫 단계는 passage 노드를 고정하고 entity-문장 부분 그래프에서 semantic bridging으로 중간 entity를 활성화한다. | method | differs 9 |
| semantic propagation은 질의-문장 유사도를 문장-entity 그래프를 통해 전파해 관련 중간 entity를 활성화한다. | method | differs 9 |
| 각 전파 단계에서 relevance score가 임계값보다 큰 새 entity만 다음 반복으로 유지한다. | method | differs 9 |
| 두 번째 단계는 활성화된 entity를 초기값으로 사용해 passage-entity 그래프에서 Personalized PageRank로 전역 중요도를 계산한다. | method | followed 8, differs 1 |
| 검색된 passage는 PPR 점수로 순위를 매기고 가장 높은 top-k passage를 선택한다. | method | followed 8, differs 1 |
| 동적 pruning 임계값 δ는 4로 설정한다. | hyperparameter | followed 8, differs 1 |
| passage 초기 점수에서 DPR 유사도와 entity 정보의 균형 계수 λ는 0.05로 설정한다. | hyperparameter | followed 8, differs 1 |
| Contain-Match Accuracy는 생성 응답에 정답이 포함되는지를 평가한다. | metric | followed 8, missing 1 |
| GPT-Evaluation Accuracy는 LLM이 예측 답변과 정답의 일치 여부를 평가한다. | metric | followed 9 |
| Medical 데이터셋은 GPT-ACC만으로 평가한다. | metric | followed 8, differs 1 |
| 비교 대상에는 zero-shot LLM, Vanilla RAG, KGP, G-Retriever, RAPTOR, E2GraphRAG, LightRAG, HippoRAG, GFM-RAG, HippoRAG2가 포함된다. | baseline · scope | 점검이 묻지 않음 |
| Vanilla RAG baseline은 1, 3, 5개 passage 검색 설정을 사용한다. | baseline · scope | 점검이 묻지 않음 |
| 실험 하드웨어는 NVIDIA GeForce RTX 4090 D 24GB GPU와 Intel Xeon Gold 6426Y CPU이다. | training · fact | 점검이 묻지 않음 |
| LinearRAG는 HotpotQA, 2Wiki, MuSiQue, Medical에서 각각 64.30, 66.50, 70.20, 63.70의 Contain-Acc. 또는 GPT-Acc. 결과를 보고한다. | result · result | differs 6, missing 3 |
| LinearRAG의 전체 파이프라인 정확도는 66.95이다. | result · result | missing 9 |
| 주요 실험의 난수 시드가 명시되지 않았다. | training (논문에 없음) | chosen 9 |
| 주요 실험의 반복 실행 횟수와 결과 집계 방식이 명시되지 않았다. | training (논문에 없음) | chosen 8, missing 1 |
| 생성 및 평가에 사용한 구체적인 프롬프트 템플릿이 명시되지 않았다. | method (논문에 없음) | chosen 9 |
| LLM 생성의 decoding 설정이 명시되지 않았다. | method (논문에 없음) | unclear 5, missing 2, chosen 2 |
| spaCy의 구체적인 모델명과 버전이 명시되지 않았다. | preprocessing (논문에 없음) | chosen 9 |

## 그 밖의 펼쳐진 행 30개

- v00-clean missing [dataset] 주요 실험은 HotpotQA, 2WikiMultiHopQA, MuSiQue, Medical의 네 데이터셋에서 — 네 데이터셋이 설정되어 있지만 실행 로그에는 2Wiki 결과만 있어 네 데이터셋 모두 수행된 상태는 확인되지 않습니다.
- v00-clean missing [split] 각 데이터셋의 검증 세트에서 1,000개 질문을 선택한다. — 설정과 2Wiki 로그는 맞지만 각 데이터셋의 실행 결과가 모두 없어 전체 조건의 실행 여부는 확인되지 않습니다.
- v00-clean differs [result] LinearRAG는 HotpotQA, 2Wiki, MuSiQue, Medical에서 각각 64.30, 66. — 2Wiki 로그는 논문 행의 2Wiki 값 66.50과 다르며, 63.70·70.20은 논문 표 행에서 데이터셋 또는 지표 짝이 뒤바뀌었을 가능성이 있습니다; 나머지 데이터셋 로그도 없습니다.
- v00-clean missing [result] LinearRAG의 전체 파이프라인 정확도는 66.95이다. — 전체 파이프라인 정확도 66.95를 기록하거나 계산하는 코드와 로그가 없습니다.
- v00-clean missing [training] 주요 실험의 반복 실행 횟수와 결과 집계 방식이 명시되지 않았다. — 반복 실행 횟수와 결과 집계 방식을 정하는 설정이나 구현이 없습니다.
- v00-clean missing [method] LLM 생성의 decoding 설정이 명시되지 않았다. — decoding parameter를 지정하는 코드가 없어 구체적인 decoding 설정은 확인되지 않습니다.
- v00-clean outside [조건 밖]  — 질의의 명명 개체를 실행 시 spaCy로 추출하지 않고 입력 예제의 entities 필드를 직접 사용합니다.
- v01 differs [result] LinearRAG는 HotpotQA, 2Wiki, MuSiQue, Medical에서 각각 64.30, 66. — 2Wiki 로그만 있고 GPT-ACC는 논문의 2Wiki 66.50이 아닌 63.70이며 70.20도 논문 표의 다른 데이터셋·지표와 짝이 어긋났을 가능성이 있다.
- v01 missing [result] LinearRAG의 전체 파이프라인 정확도는 66.95이다. — 전체 파이프라인 정확도 66.95를 기록하거나 계산한 근거가 없다.
- v02 differs [result] LinearRAG는 HotpotQA, 2Wiki, MuSiQue, Medical에서 각각 64.30, 66. — 로그의 2Wiki 값은 제시된 66.50과 다르고, 63.70·70.20은 제시된 다른 데이터셋 값과도 짝이 어긋나므로 논문 표 행의 데이터셋·지표 매칭 오류 가능성이 있다.
- v02 missing [result] LinearRAG의 전체 파이프라인 정확도는 66.95이다. — 전체 파이프라인 정확도 66.95를 보고한 실행 로그나 코드 집계가 없다.
- v02 missing [method] LLM 생성의 decoding 설정이 명시되지 않았다. — 논문과 코드 모두 temperature·top_p·max_tokens 등 decoding 설정을 명시하지 않는다.
- v03 differs [result] LinearRAG는 HotpotQA, 2Wiki, MuSiQue, Medical에서 각각 64.30, 66. — 2Wiki 로그는 논문 값 66.50과 다르며 63.70·70.20은 다른 데이터셋 행의 값일 가능성이 있습니다.
- v03 missing [result] LinearRAG의 전체 파이프라인 정확도는 66.95이다. — 전체 파이프라인 정확도 66.95를 기록하거나 계산하는 코드와 로그가 없습니다.
- v04 missing [result] LinearRAG의 전체 파이프라인 정확도는 66.95이다. — 전체 파이프라인 정확도 66.95를 기록한 실행 결과가 없습니다.
- v05 differs [preprocessing] spaCy로 코퍼스와 질의에서 명명 개체를 추출한다. — 질의에서 spaCy로 개체를 추출하지 않고 입력 entities를 사용합니다.
- v05 differs [hyperparameter] 모든 방법의 top-k 검색값은 5이다. — 설정값 5가 아니라 코드의 10이 실제 top-k입니다.
- v05 missing [result] LinearRAG는 HotpotQA, 2Wiki, MuSiQue, Medical에서 각각 64.30, 66. — 네 데이터셋 결과가 모두 보고되지 않았고, 2Wiki 로그 값도 제시된 66.50과 다릅니다. 논문 표의 값-데이터셋·지표 짝이 잘못되었을 가능성도 있습니다.
- v05 missing [result] LinearRAG의 전체 파이프라인 정확도는 66.95이다. — 전체 파이프라인 정확도 66.95를 확인할 로그가 없습니다.
- v06 differs [preprocessing] spaCy로 코퍼스와 질의에서 명명 개체를 추출한다. — spaCy는 코퍼스 문장에만 적용되고 질의 엔티티는 입력 필드에서 직접 받는다.
- v06 differs [result] LinearRAG는 HotpotQA, 2Wiki, MuSiQue, Medical에서 각각 64.30, 66. — 2Wiki 로그는 제시된 66.50과 다르며 63.70·70.20이 다른 지표/데이터셋 짝에서 옮겨졌을 가능성도 있다.
- v06 missing [result] LinearRAG의 전체 파이프라인 정확도는 66.95이다. — 전체 파이프라인 정확도 66.95를 보고한 로그나 코드 결과가 없다.
- v07 missing [result] LinearRAG의 전체 파이프라인 정확도는 66.95이다. — 전체 파이프라인 정확도 66.95를 기록한 로그나 코드가 없습니다.
- v07 outside [조건 밖]  — 임베딩 모델을 생성하지만 retrieval 또는 graph 계산에 전달하지 않습니다.
- v08 missing [dataset] 주요 실험은 HotpotQA, 2WikiMultiHopQA, MuSiQue, Medical의 네 데이터셋에서 — 네 데이터셋은 설정되어 있지만 실행 로그에는 2Wiki만 있어 주요 실험 전체 실행을 확인할 수 없다.
- v08 missing [split] 각 데이터셋의 검증 세트에서 1,000개 질문을 선택한다. — 설정과 2Wiki 로그는 맞지만 네 데이터셋 모두에서 실행된 근거가 없다.
- v08 missing [preprocessing] 각 passage를 구두점으로 문장 분할한다. — 구두점 문장 분할 함수는 있으나 실제 그래프 구축에서 호출되지 않는다.
- v08 differs [preprocessing] spaCy로 코퍼스와 질의에서 명명 개체를 추출한다. — 코퍼스 passage에는 spaCy NER를 적용하지만 질의에서는 미리 제공된 entities를 사용한다.
- v08 missing [result] LinearRAG는 HotpotQA, 2Wiki, MuSiQue, Medical에서 각각 64.30, 66. — 네 데이터셋 결과가 모두 없고, 2Wiki 로그도 제시된 2Wiki 66.50과 다르며 63.70/70.20은 다른 데이터셋·지표 행과 뒤섞였을 가능성이 있다.
- v08 missing [result] LinearRAG의 전체 파이프라인 정확도는 66.95이다. — 전체 파이프라인 정확도 66.95를 보고한 로그가 없다.
