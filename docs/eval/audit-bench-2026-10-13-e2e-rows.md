# 점검 카드에 펼쳐지는 행 — 2026-10-13 (e2e)

- 변형 9개, 모델 gpt-5.6-luna, 점검 1회 평균 82059 ms
- 카드당 판정 31.0행, 그중 펼쳐진 행 12.9행 (조건 밖 방법 차이 포함)

| 펼쳐진 행 | 합 | 카드당 |
|---|---|---|
| 심은 어긋남 | 21 | 2.3 |
| 바탕의 방법 차이 | 36 | 4.0 |
| 논문에 없는 설정(코드가 정함) | 23 | 2.6 |
| 따름/판단 못 함에 붙은 확인 경고 | 0 | 0.0 |
| 그 밖 (손으로 읽음) | 36 | 4.0 |

## 변형별

| 변형 | 판정 | 펼쳐짐 | 심은 어긋남 | 바탕의 방법 차이 | 논문에 없는 설정(코드가 정함) | 따름/판단 못 함에 붙은 확인 경고 | 그 밖 (손으로 읽음) |
|---|---|---|---|---|---|---|---|
| v00-clean | 31 | 11 | 0 | 4 | 3 | 0 | 4 |
| v01 | 31 | 15 | 4 | 4 | 2 | 0 | 5 |
| v02 | 31 | 14 | 3 | 4 | 2 | 0 | 5 |
| v03 | 31 | 11 | 2 | 3 | 3 | 0 | 3 |
| v04 | 31 | 12 | 3 | 4 | 3 | 0 | 2 |
| v05 | 31 | 13 | 2 | 5 | 2 | 0 | 4 |
| v06 | 31 | 12 | 2 | 4 | 3 | 0 | 3 |
| v07 | 31 | 14 | 2 | 4 | 2 | 0 | 6 |
| v08 | 31 | 14 | 3 | 4 | 3 | 0 | 4 |

## 조건별 판정 (변형 전체)

| 조건 | 분류 | 판정 |
|---|---|---|
| HotpotQA는 약 97,000개의 질의-응답 인스턴스로 구성된다. | dataset | unclear 9 |
| 2WikiMultiHopQA는 192,000개의 질문을 포함한다. | dataset | unclear 9 |
| MuSiQue는 25,000개의 질문-답변 쌍으로 구성된다. | dataset | unclear 9 |
| Medical 데이터셋은 총 4,076개의 질문으로 구성된다. | dataset | unclear 8, missing 1 |
| 각 데이터셋의 검증 세트에서 1,000개의 질문을 선택한다. | split | followed 7, differs 2 |
| 각 passage는 구두점을 사용해 문장으로 분할한다. | preprocessing | followed 7, differs 2 |
| 모든 방법은 all-mpnet-base-v2 임베딩 모델을 사용한다. | model | followed 8, differs 1 |
| 생성과 평가에는 GPT-4o-mini를 사용한다. | model | followed 8, differs 1 |
| 모든 방법의 top-k 검색값은 5이다. | hyperparameter | followed 7, differs 2 |
| 동적 pruning 임계값 δ는 4로 설정한다. | hyperparameter | followed 8, differs 1 |
| passage 초기 점수의 trade-off 계수 λ는 0.05에서 최적이다. | hyperparameter | followed 8, differs 1 |
| PageRank의 damping factor는 일반적으로 0.85이다. | hyperparameter | followed 8, differs 1 |
| Contain-Match Accuracy는 생성된 응답에 정답이 포함되는지를 검사한다. | metric | followed 8, missing 1 |
| GPT-Evaluation Accuracy는 LLM이 예측 답변과 정답의 일치 여부를 평가한다. | metric | followed 9 |
| Medical 데이터셋은 GPT-ACC.만으로 평가한다. | protocol | followed 8, differs 1 |
| 주요 비교 대상으로 KGP, G-retriever, RAPTOR, E2GraphRAG, LightRAG, HippoRAG, GFM-RAG, HippoRAG2를 사용한다. | baseline | missing 9 |
| Vanilla RAG baseline은 1, 3, 5개 passage를 검색한다. | baseline | missing 9 |
| 실험은 NVIDIA GeForce RTX 4090 D 24GB GPU에서 수행한다. | training | unclear 8, missing 1 |
| LinearRAG의 네 데이터셋별 주요 정확도 결과는 표에 보고된 값과 같다. | result | missing 9 |
| LinearRAG의 2Wiki GPT 기반 정확도는 63.70%이다. | result | followed 8, differs 1 |
| LinearRAG의 2Wiki Contain 기반 정확도는 70.20%이다. | result | followed 8, differs 1 |
| Tri-Graph는 entity, sentence, passage 노드와 entity-문장 및 entity-passage 연결로 구성된다. | method | followed 7, differs 2 |
| 질문에서 추출한 각 entity는 그래프에서 가장 유사한 entity에 초기 활성화된다. | method | differs 9 |
| 문장-entity 그래프에서 질문-문장 유사도를 이용해 중간 entity의 활성화 점수를 전파한다. | method | differs 8, missing 1 |
| 각 전파 단계에서 관련성 점수가 임계값을 넘는 새 entity만 다음 반복에 유지한다. | method | differs 9 |
| 활성화된 entity를 seed로 사용해 entity-passage 그래프에서 Personalized PageRank로 passage 중요도를 집계한다. | method | followed 8, differs 1 |
| 최종 검색 결과는 passage의 PageRank 점수가 높은 top-k passage이다. | method | followed 8, differs 1 |
| 실험의 난수 시드와 재현에 사용할 시드 개수는 명시되지 않았다. | training (논문에 없음) | chosen 9 |
| 학습률과 학습률 스케줄은 명시되지 않았다. | training (논문에 없음) | missing 6, followed 2, unclear 1 |
| 각 실험을 몇 회 반복하고 결과를 어떻게 평균내는지는 명시되지 않았다. | protocol (논문에 없음) | chosen 5, missing 4 |
| 생성 단계에서 사용할 구체적인 프롬프트 템플릿은 명시되지 않았다. | method (논문에 없음) | chosen 9 |

## 그 밖의 펼쳐진 행 36개

- v00-clean missing [baseline] 주요 비교 대상으로 KGP, G-retriever, RAPTOR, E2GraphRAG, LightRAG, H — 나열된 비교 방법들의 구현이나 실행이 없다.
- v00-clean missing [baseline] Vanilla RAG baseline은 1, 3, 5개 passage를 검색한다. — Vanilla RAG의 1·3·5 passage 비교 실행이 없다.
- v00-clean missing [result] LinearRAG의 네 데이터셋별 주요 정확도 결과는 표에 보고된 값과 같다. — 네 데이터셋 결과 전체가 아니라 2Wiki 결과 로그만 존재한다.
- v00-clean missing [training] 학습률과 학습률 스케줄은 명시되지 않았다. — 학습 단계와 학습률·스케줄 설정이 코드에 없다.
- v01 missing [baseline] 주요 비교 대상으로 KGP, G-retriever, RAPTOR, E2GraphRAG, LightRAG, H — 열거된 비교 대상 방법들의 구현이나 실행 결과가 없습니다.
- v01 missing [baseline] Vanilla RAG baseline은 1, 3, 5개 passage를 검색한다. — 1·3·5개 passage를 비교하는 Vanilla RAG 실행이 없습니다.
- v01 missing [result] LinearRAG의 네 데이터셋별 주요 정확도 결과는 표에 보고된 값과 같다. — 네 데이터셋의 주요 정확도 표 전체가 없고 2Wiki 로그만 존재합니다.
- v01 missing [training] 학습률과 학습률 스케줄은 명시되지 않았다. — 학습률과 학습률 스케줄 설정 또는 학습 과정이 없습니다.
- v01 missing [protocol] 각 실험을 몇 회 반복하고 결과를 어떻게 평균내는지는 명시되지 않았다. — 반복 실행 및 결과 평균 처리가 없습니다.
- v02 missing [baseline] 주요 비교 대상으로 KGP, G-retriever, RAPTOR, E2GraphRAG, LightRAG, H — 열거된 데이터셋을 실행할 뿐 논문의 주요 비교 방법들은 구현·실행되지 않았다.
- v02 missing [baseline] Vanilla RAG baseline은 1, 3, 5개 passage를 검색한다. — Vanilla RAG의 1·3·5 passage 비교 실행이나 기록이 없다.
- v02 missing [result] LinearRAG의 네 데이터셋별 주요 정확도 결과는 표에 보고된 값과 같다. — 네 데이터셋별 표 결과가 아니라 2Wiki 하나의 로그만 확인된다.
- v02 missing [training] 학습률과 학습률 스케줄은 명시되지 않았다. — 학습률과 학습률 스케줄 설정이나 구현이 없다.
- v02 missing [protocol] 각 실험을 몇 회 반복하고 결과를 어떻게 평균내는지는 명시되지 않았다. — 반복 실행 횟수와 반복 결과 평균 방식이 없다.
- v03 missing [baseline] 주요 비교 대상으로 KGP, G-retriever, RAPTOR, E2GraphRAG, LightRAG, H — 열거된 주요 비교 대상 방법들의 구현이나 비교 실행이 없다.
- v03 missing [baseline] Vanilla RAG baseline은 1, 3, 5개 passage를 검색한다. — Vanilla RAG의 1·3·5 passage 비교 실행이 없다.
- v03 missing [result] LinearRAG의 네 데이터셋별 주요 정확도 결과는 표에 보고된 값과 같다. — 네 데이터셋 전체의 주요 정확도 표가 보고되지 않았고 현재 로그는 2Wiki 하나뿐이다.
- v04 missing [baseline] 주요 비교 대상으로 KGP, G-retriever, RAPTOR, E2GraphRAG, LightRAG, H — 제시된 비교 방법들의 구현이나 실행 로그가 없다.
- v04 missing [baseline] Vanilla RAG baseline은 1, 3, 5개 passage를 검색한다. — Vanilla RAG의 1·3·5 passage 검색 구현이나 결과가 없다.
- v05 missing [baseline] 주요 비교 대상으로 KGP, G-retriever, RAPTOR, E2GraphRAG, LightRAG, H — 열거된 비교 방법을 구현하거나 실행한 코드와 로그가 없다.
- v05 missing [baseline] Vanilla RAG baseline은 1, 3, 5개 passage를 검색한다. — 1·3·5 passage Vanilla RAG baseline 실행이 없다.
- v05 missing [result] LinearRAG의 네 데이터셋별 주요 정확도 결과는 표에 보고된 값과 같다. — 네 데이터셋의 주요 정확도 표가 없고 2Wiki 로그만 존재한다.
- v05 missing [training] 학습률과 학습률 스케줄은 명시되지 않았다. — 학습률과 스케줄 설정 또는 학습 단계가 없다.
- v06 missing [baseline] 주요 비교 대상으로 KGP, G-retriever, RAPTOR, E2GraphRAG, LightRAG, H — LinearRAG만 실행하며 열거된 비교 대상 방법의 구현이나 실행이 없습니다.
- v06 missing [baseline] Vanilla RAG baseline은 1, 3, 5개 passage를 검색한다. — 1·3·5 passage Vanilla RAG 검색 실행이 없습니다.
- v06 missing [result] LinearRAG의 네 데이터셋별 주요 정확도 결과는 표에 보고된 값과 같다. — 네 데이터셋 전체의 주요 정확도 표가 없고 2Wiki 로그만 존재합니다.
- v07 missing [baseline] 주요 비교 대상으로 KGP, G-retriever, RAPTOR, E2GraphRAG, LightRAG, H — 설정이나 코드에 논문의 주요 비교 대상 실행이 구현되어 있지 않다.
- v07 missing [baseline] Vanilla RAG baseline은 1, 3, 5개 passage를 검색한다. — 1·3·5 passage를 검색하는 Vanilla RAG baseline이 구현되어 있지 않다.
- v07 missing [training] 실험은 NVIDIA GeForce RTX 4090 D 24GB GPU에서 수행한다. — 4090 D 24GB GPU 사용을 나타내는 실행 정보나 설정이 없다.
- v07 missing [training] 학습률과 학습률 스케줄은 명시되지 않았다. — 학습률과 학습률 스케줄 설정이나 구현이 없다.
- v07 missing [protocol] 각 실험을 몇 회 반복하고 결과를 어떻게 평균내는지는 명시되지 않았다. — 반복 실행 및 반복 결과 평균 처리 구현이 없다.
- v07 outside [조건 밖]  — PageRank 입력 subgraph에서 sentence 노드를 제외하여 sentence 노드가 최종 ranking에 전달되지 않는다.
- v08 missing [baseline] 주요 비교 대상으로 KGP, G-retriever, RAPTOR, E2GraphRAG, LightRAG, H — 논문의 비교 방법들을 구현하거나 실행하는 코드가 없다.
- v08 missing [baseline] Vanilla RAG baseline은 1, 3, 5개 passage를 검색한다. — Vanilla RAG baseline과 1·3·5 passage 비교 실행이 없다.
- v08 missing [result] LinearRAG의 네 데이터셋별 주요 정확도 결과는 표에 보고된 값과 같다. — 네 데이터셋 전체의 주요 정확도 표가 없고 2Wiki 로그만 존재한다.
- v08 missing [training] 학습률과 학습률 스케줄은 명시되지 않았다. — 학습 과정과 학습률·스케줄 설정이 없어 코드가 선택한 값도 없다.
