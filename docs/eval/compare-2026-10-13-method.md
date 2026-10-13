# 비교군: Pablo 재현 점검 vs 같은 모델에 그냥 묻기 — 2026-10-13

- 같은 변형 9개(씨앗 7), 같은 모델 gpt-5.6-luna, 둘 다 읽기 전용 + JSON 답
- Pablo: 고정 조건 17개 + 원문 쪽을 받고 조건마다 판정. 그냥 묻기: 논문 본문 전체를 받고 "논문과 다른 곳을 모두 찾아줘"
- 찾음 = 심은 어긋남의 파일:줄(±2)을 짚고 무엇이 바뀌었는지 말함(`SAYS`). 위치만 = 줄만 맞음
- 심은 것 밖의 보고 = 어느 심은 어긋남에 대한 것도 아닌 보고. 틀린 말이라는 뜻이 아니다: 조건 목록 밖의 실제 차이일 수 있다

| 시스템 | 찾음 | 위치만 | 보고 수 | 심은 것 밖의 보고 | 변형당 | 깨끗한 변형의 보고 | 1회 시간 |
|---|---|---|---|---|---|---|---|
| Pablo 값 조건 | 18/18 (100.0%) | 18/18 | 19 | 0 | 0.0 | 0 | 44292 ms |
| Pablo +방법 | 18/18 (100.0%) | 18/18 | 70 | 48 | 5.3 | 6 | 72691 ms |
| 그냥 묻기 | 17/18 (94.4%) | 18/18 | 143 | 122 | 13.6 | 14 | 69874 ms |

## 방법 수준 차이: 바탕 폴더가 가진 8가지를 변형 9개에서 몇 번 짚었나

보고가 하는 말(코드 인용은 빼고)에 주제별 표현(`THEMES`)이 나오면 짚은 것으로 셉니다.

| 주제 | Pablo 값 조건 | Pablo +방법 | 그냥 묻기 |
|---|---|---|---|
| hybrid passage 초기화 없음 | 0/9 | 1/9 | 9/9 |
| 그래프 구조(희소 행렬·passage-sentence 간선) | 0/9 | 0/9 | 8/9 |
| δ를 임계값이 아니라 hop 수로 | 0/9 | 9/9 | 9/9 |
| LLM에 passage 본문 대신 ID | 0/9 | 6/9 | 7/9 |
| 의미 기반 entity 활성화 없음 | 0/9 | 9/9 | 9/9 |
| 질의 entity를 유사 entity에 매칭하지 않음 | 0/9 | 9/9 | 9/9 |
| 임베딩 모델을 쓰지 않음 | 0/9 | 8/9 | 9/9 |
| 생성 프롬프트 | 0/9 | 0/9 | 6/9 |
| 합 | 0/72 | 42/72 | 66/72 |

## Pablo 값 조건: 놓친 어긋남 0건

- 없음

## Pablo +방법: 놓친 어긋남 0건

- 없음

## 그냥 묻기: 놓친 어긋남 1건

- v03 medical_both

## Pablo 값 조건: 심은 것 밖의 보고 0건

- 없음

## Pablo +방법: 심은 것 밖의 보고 48건

- v00-clean `retrieve.py:7`: 질문 엔티티를 가장 유사한 그래프 엔티티에 매칭하지 않고 그대로 시작점으로 사용한다.
- v00-clean `retrieve.py:9-10`: 질문-문장 유사도 기반 전파가 아니라 단순 그래프 이웃 탐색을 수행한다.
- v00-clean `retrieve.py:8-12`: 관련성 점수 임계값으로 가지치기하지 않고 delta만큼 반복한다.
- v00-clean `run.py:16`: 임베딩 모델을 로드하지만 질문 엔티티 매칭이나 검색 계산에 사용하지 않는다.
- v00-clean `run.py:24`: 검색된 패시지의 원문 텍스트를 그래프 노드에 저장하지 않아 생성 컨텍스트에 패시지 ID만 전달한다.
- v00-clean `logs/2wikimultihopqa.log:1`: 폴더에는 2Wiki 실행 로그만 있고 나머지 세 데이터셋의 실행 로그가 없다.
- v01 `config.yaml:14`: 값은 설정되어 있지만 실제 PageRank 계산에 사용되지 않는다.
- v01 `retrieve.py:7-8`: 질문 entity를 가장 유사한 그래프 entity에 매칭하지 않고 그대로 seed로 사용한다.
- v01 `retrieve.py:9-12`: 질문-문장 유사도로 중간 entity 활성화 점수를 전파하지 않는다.
- v01 `retrieve.py:9-12`: 관련성 임계값이 아니라 delta 횟수만큼 이웃 entity를 모두 유지한다.
- v01 `run.py:16`: 임베딩 모델을 로드하지만 질문·entity 유사도 계산에 실제로 사용하지 않는다.
- v01 `run.py:24`: 검색 컨텍스트로 passage 본문이 아니라 passage ID가 전달될 가능성이 높다.
- v02 `retrieve.py:7`: 질문 entity를 가장 유사한 그래프 entity에 매칭하지 않고 입력 entity를 그대로 seed로 사용한다.
- v02 `retrieve.py:9-10`: 질문-문장 유사도를 이용한 전파가 아니라 단순 이웃 탐색을 수행한다.
- v02 `retrieve.py:5-12`: 관련성 점수 임계값으로 새 entity를 선별하지 않고 delta 횟수만큼 모든 entity 이웃을 유지한다.
- v02 `logs/2wikimultihopqa.log:1`: 실행 로그에는 2Wiki 결과만 있고 HotpotQA·MuSiQue·Medical의 실행 결과가 없다.
- v03 `retrieve.py:7-12`: 질문 entity를 가장 유사한 그래프 entity에 매칭하지 않고 그대로 seed로 사용합니다.
- v03 `retrieve.py:9-12`: 질문-문장 유사도 기반 전파가 아니라 그래프 이웃을 홉 단위로 확장합니다.
- v03 `retrieve.py:9-11`: 관련성 점수 임계값이 아니라 delta만큼의 반복과 중복 제거를 사용합니다.
- v03 `run.py:16`: 임베딩 모델을 로드하지만 검색이나 그래프 계산에 실제로 사용하지 않습니다.
- v04 `run.py:23; retrieve.py:7`: 질의에서 새로 엔티티를 추출하거나 가장 유사한 그래프 엔티티를 찾지 않고 입력 엔티티를 그대로 seed로 쓴다.
- v04 `retrieve.py:5-12`: 질의-문장 유사도로 중간 엔티티의 활성화 점수를 전파하는 계산이 없다.
- v04 `retrieve.py:8-12`: 관련성 점수 임계값 기반 pruning이 아니라 고정된 hop 횟수로 엔티티를 확장한다.
- v04 `run.py:16`: 임베딩 모델을 생성하지만 검색이나 그래프 계산에서 encoder를 사용하지 않는다.
- v04 `run.py:24; graph.py:10`: 그래프 노드에 패시지 본문을 저장하지 않아 생성 컨텍스트에 본문 대신 패시지 ID를 전달한다.
- v04 `run.py:19-20`: 실행에 필요한 data 디렉터리와 나머지 데이터셋 실행 로그가 작업 폴더에 없다.
- v05 `retrieve.py:7-12`: 질문 entity를 가장 유사한 그래프 entity에 매칭하지 않고 그대로 seed로 사용합니다.
- v05 `retrieve.py:8-11`: 질문-문장 유사도에 따른 중간 entity 점수 전파가 없습니다.
- v05 `retrieve.py:8-11`: 관련성 점수 임계값이 아니라 delta hop 수로 entity를 확장합니다.
- v05 `run.py:16`: 임베딩 모델을 생성하지만 검색이나 유사도 계산에 사용하지 않습니다.
- v05 `run.py:24`: 검색 문맥으로 passage 원문이 아니라 그래프 노드 ID를 전달합니다.
- v05 `logs/2wikimultihopqa.log:1`: 설정된 세 데이터셋 중 실행 로그는 2Wiki 하나만 존재합니다.
- v06 `run.py:23`: 질문 엔티티를 가장 유사한 그래프 엔티티에 매칭하는 과정 없이 입력 엔티티를 바로 사용한다.
- v06 `retrieve.py:8-10`: 질문-문장 유사도 기반 전파가 아니라 엔티티 이웃을 반복 탐색한다.
- v06 `retrieve.py:8`: 관련성 점수 임계값으로 가지치기하지 않고 delta만큼 고정 반복한다.
- v06 `run.py:16`: 임베딩 모델을 생성하지만 검색이나 엔티티 매칭에 사용하지 않는다.
- v06 `run.py:24`: 그래프 노드에 passage 원문을 저장하지 않아 생성 컨텍스트에 passage ID만 전달한다.
- v06 `logs/2wikimultihopqa.log:1`: 네 데이터셋을 설정했지만 실행 로그는 2Wiki 결과만 포함한다.
- v07 `retrieve.py:7-12`: 질문 entity를 가장 유사한 그래프 entity에 매칭하지 않고 그대로 seed로 사용합니다.
- v07 `retrieve.py:9-10`: 질문-문장 유사도에 따른 중간 entity 점수 전파가 없습니다.
- v07 `retrieve.py:9-12`: 관련성 점수 임계값이 아니라 고정 hop 반복으로 entity를 확장합니다.
- v07 `run.py:16`: 임베딩 모델을 생성하지만 검색 계산에는 encoder를 사용하지 않습니다.
- v07 `run.py:24`: 그래프에 passage 본문을 저장하지 않아 생성 컨텍스트에 passage 텍스트 대신 ID가 전달됩니다.
- v08 `retrieve.py:7`: 질문 entity를 가장 유사한 그래프 entity에 매칭하지 않고 동일한 entity를 바로 seed로 사용합니다.
- v08 `retrieve.py:18`: sentence-entity 그래프와 질문-문장 유사도 기반의 중간 entity 전파가 없습니다.
- v08 `retrieve.py:8-12`: 관련성 점수 임계값이 아니라 delta hop만큼 이웃 entity를 확장합니다.
- v08 `run.py:16`: 임베딩 모델을 초기화하지만 검색이나 그래프 계산에 사용하지 않습니다.
- v08 `logs\2wikimultihopqa.log:1`: 폴더에는 2Wiki 검증 로그만 있어 나머지 세 데이터셋의 실행 결과가 없습니다.

## 그냥 묻기: 심은 것 밖의 보고 122건

- v00-clean `graph.py:7-19, run.py:20-25`: 검색된 passage의 실제 본문을 생성 모델에 전달하지 않고 passage ID만 전달합니다.
- v00-clean `retrieve.py:5-12`: Stage 1의 의미 기반 entity activation이 구현되지 않았습니다.
- v00-clean `run.py:23, retrieve.py:5-8`: 질문에서 entity를 SpaCy로 추출하고 유사한 corpus entity에 매칭하는 과정이 빠졌습니다.
- v00-clean `config.yaml:11-12, retrieve.py:5-12`: 동적 pruning의 의미가 다릅니다.
- v00-clean `retrieve.py:18-22`: Stage 2 passage 초기화의 hybrid scoring이 구현되지 않았습니다.
- v00-clean `graph.py:7-18`: 논문의 두 sparse adjacency matrix 대신 일반 NetworkX 무방향 그래프를 사용합니다.
- v00-clean `graph.py:13-14`: graph에 논문에 정의되지 않은 passage-sentence edge가 추가됩니다.
- v00-clean `run.py:8, run.py:16, retrieve.py 전체`: 논문에서 요구하는 sentence·passage embedding 계산이 빠졌습니다.
- v00-clean `run.py:24-25`: 생성 프롬프트가 논문의 RAG 설정을 충분히 재현하지 않습니다.
- v00-clean `run.py:18-30, logs/2wikimultihopqa.log:1`: 논문의 네 데이터셋 전체 실험이 실행·기록되지 않았습니다.
- v00-clean `config.yaml:4, run.py:18-30`: baseline 비교 실험이 구현되지 않았습니다.
- v00-clean `전체 파일, 특히 run.py:18-30`: ablation 및 추가 실험이 빠졌습니다.
- v00-clean `run.py:18-31, logs/2wikimultihopqa.log:1`: 효율성 측정과 token consumption 기록이 빠졌습니다.
- v00-clean `전체 파일, logs/2wikimultihopqa.log:1`: 논문의 hardware 조건이 코드나 로그에서 검증·기록되지 않습니다.
- v01 `graph.py:14`: Tri-Graph에 불필요한 passage-sentence 간선이 추가됨
- v01 `graph.py:10-13, run.py:24`: Sentence와 passage의 원문이 그래프 노드에 저장되지 않음
- v01 `run.py:23, retrieve.py:5-8`: 질의 entity 초기화가 논문 방식과 다르고 entity 유사도 매칭이 없음
- v01 `retrieve.py:5-12`: Stage 1의 query-sentence relevance와 semantic propagation이 누락됨
- v01 `retrieve.py:5-12, config.yaml:11-12`: dynamic pruning이 논문과 다름
- v01 `run.py:8, run.py:16; retrieve.py 전체`: 논문에서 요구한 embedding 계산이 구현되지 않음
- v01 `run.py:24`: 검색 결과 context가 논문 실험의 원문 passage가 아님
- v01 `config.yaml:4; run.py:18-30; logs/2wikimultihopqa.log:1`: 네 개 데이터셋 전체 실험 로그가 없음
- v01 `run.py:25`: 논문 실험의 생성 프롬프트 조건이 재현되지 않음
- v02 `graph.py:11-18`: Tri-Graph에 논문에 없는 passage-sentence 간선을 추가함
- v02 `retrieve.py:5-12`: Stage 1이 semantic bridging을 구현하지 않음
- v02 `run.py:23; retrieve.py:5-8`: 질의 엔티티의 nearest-entity 매칭이 빠짐
- v02 `retrieve.py:8-10; graph.py:14-18`: Stage 1의 탐색 그래프와 결과가 논문 구조와 다름
- v02 `retrieve.py:21`: Passage 초기화 점수가 논문 수식과 다름
- v02 `retrieve.py:21`: Entity 초기화 점수가 다름
- v02 `graph.py:9-18; run.py:24`: Passage 텍스트가 그래프 노드에 저장되지 않음
- v02 `run.py:16; retrieve.py:15-23`: 검색에 실제 임베딩 기반 유사도 계산이 빠짐
- v02 `run.py:18-31; 전체 프로젝트`: 논문에 명시된 실험 범위가 대부분 누락됨
- v02 `logs/2wikimultihopqa.log:1`: 실행 로그가 2Wiki 결과만 포함함
- v03 `run.py:19`: 질문 수 자체는 1,000개로 설정되어 있으나, validation set을 보장하지 않습니다.
- v03 `run.py:23; retrieve.py:5-12`: 질문 엔티티를 SpaCy로 추출하지 않습니다.
- v03 `run.py:16; config.yaml:2`: 임베딩 모델이 실제 검색에 사용되지 않습니다.
- v03 `retrieve.py:5-12`: 1단계 활성화가 semantic bridging이 아니라 단순 그래프 홉 확장입니다.
- v03 `retrieve.py:5-12; config.yaml:11-12`: dynamic pruning의 delta 의미가 다릅니다.
- v03 `retrieve.py:15-23`: 패시지 초기화 점수가 논문의 식 (7)과 다릅니다.
- v03 `retrieve.py:21-22`: PPR seed와 초기화가 논문과 다릅니다.
- v03 `graph.py:13-18`: Tri-Graph에 패시지-문장 간 추가 간선을 넣습니다.
- v03 `graph.py:9-10; run.py:24`: 그래프의 패시지 텍스트가 저장되지 않습니다.
- v03 `run.py:24-25`: 검색 결과의 생성 프롬프트가 논문의 RAG 생성 조건을 재현하지 않습니다.
- v03 `전체 작업 폴더; run.py:18-31`: 논문에서 요구한 baseline 비교가 없습니다.
- v03 `전체 작업 폴더; config.yaml`: ablation 실험이 없습니다.
- v03 `evaluate.py:15-18; 전체 작업 폴더`: 검색 품질 평가가 없습니다.
- v03 `config.yaml:10-14; 전체 작업 폴더`: 하이퍼파라미터 민감도 실험이 없습니다.
- v03 `config.yaml:2; 전체 작업 폴더`: 임베딩 backbone 비교 실험이 없습니다.
- v03 `전체 작업 폴더; logs/2wikimultihopqa.log:1`: 대규모 효율성 실험이 없습니다.
- v03 `전체 작업 폴더`: 논문이 보고한 하드웨어 조건을 재현하는 설정이나 기록이 없습니다.
- v03 `run.py:18-31; logs/2wikimultihopqa.log:1`: 인덱싱 및 검색 시간과 토큰 사용량을 측정하지 않습니다.
- v04 `logs/2wikimultihopqa.log:1`: 실행 로그의 질문 수가 설정 파일과 불일치합니다.
- v04 `graph.py:14`: Tri-Graph에 논문에 없는 passage-sentence 직접 간선이 추가됩니다.
- v04 `graph.py:10`: passage 노드에 원문 텍스트가 저장되지 않습니다.
- v04 `run.py:24`: 검색 시 원문 passage 대신 passage ID가 LLM에 전달됩니다.
- v04 `retrieve.py:5-12`: Stage 1의 semantic bridging이 구현되지 않았습니다.
- v04 `retrieve.py:5-12`: 쿼리 entity를 전체 entity 중 가장 유사한 entity에 매칭하는 과정이 없습니다.
- v04 `run.py:16, retrieve.py:5-23`: sentence embedding과 query-sentence 유사도 계산이 전혀 사용되지 않습니다.
- v04 `retrieve.py:5-12`: dynamic pruning의 의미와 구현이 다릅니다.
- v04 `retrieve.py:21-22`: Stage 2의 hybrid passage initialization이 구현되지 않았습니다.
- v04 `graph.py:7-18, retrieve.py:20-22`: PPR 입력 그래프와 personalization이 논문의 정의와 다릅니다.
- v04 `retrieve.py:9`: 쿼리 entity가 그래프에 존재하지 않을 때 예외 처리가 없습니다.
- v04 `run.py:18-30`: 논문의 전체 baseline 비교 실험이 구현되어 있지 않습니다.
- v04 `evaluate.py:15-19, run.py:27`: retrieval quality 평가가 누락되었습니다.
- v04 `전체 프로젝트 파일 및 run.py:18-30`: ablation, hyperparameter, backbone, large-scale efficiency, case study 실험이 누락되었습니다.
- v05 `retrieve.py:5-12`: Stage 1의 semantic bridging이 구현되지 않았습니다.
- v05 `config.yaml:11-12; retrieve.py:5-12`: 동적 pruning의 δ를 잘못 사용합니다.
- v05 `run.py:23; retrieve.py:5`: 질문 엔티티를 논문 방식으로 추출하거나 nearest graph entity에 매칭하지 않습니다.
- v05 `run.py:16; retrieve.py:15-23`: all-mpnet-base-v2 임베딩 모델이 실제로 사용되지 않습니다.
- v05 `graph.py:14`: Tri-Graph에 논문에 없는 passage-sentence 직접 edge가 추가됩니다.
- v05 `graph.py:7-19`: 그래프가 sparse adjacency matrix가 아니라 NetworkX 무방향 그래프로 구현됩니다.
- v05 `retrieve.py:21-22`: Stage 2의 hybrid passage initialization이 구현되지 않았습니다.
- v05 `graph.py:7; retrieve.py:20-22`: Personalized PageRank의 graph와 personalization이 논문과 다릅니다.
- v05 `run.py:20,24`: 검색된 passage의 원문이 generation context에 전달되지 않습니다.
- v05 `run.py:25`: generation prompt가 논문의 RAG 평가 조건을 충분히 재현하지 않습니다.
- v05 `logs/2wikimultihopqa.log:1; run.py:18-30`: 논문의 네 데이터셋 전체 결과를 생성하거나 기록하지 않습니다.
- v05 `전체 파일; 특히 run.py:18-30`: 논문의 baseline 비교 실험이 빠져 있습니다.
- v05 `전체 파일`: 논문의 retrieval quality 평가가 빠져 있습니다.
- v05 `전체 파일`: 논문의 ablation study가 빠져 있습니다.
- v05 `전체 파일`: 논문의 hyperparameter sensitivity 실험이 빠져 있습니다.
- v05 `전체 파일`: 논문의 backbone/embedding 비교 실험이 빠져 있습니다.
- v05 `전체 파일`: 논문의 efficiency 및 large-scale scalability 실험이 빠져 있습니다.
- v06 `run.py:23`: 질의 엔티티 추출 방식이 다릅니다.
- v06 `retrieve.py:5-12`: Stage 1의 엔티티 활성화가 semantic bridging으로 구현되지 않았습니다.
- v06 `retrieve.py:5-12`: 동적 pruning 조건이 다릅니다.
- v06 `config.yaml:12, retrieve.py:18`: δ의 코드 의미가 논문과 다릅니다.
- v06 `run.py:16, retrieve.py:15-23`: sentence/entity embedding 계산이 빠졌습니다.
- v06 `graph.py:10`: Passage 노드의 텍스트가 그래프에 저장되지 않습니다.
- v06 `run.py:24`: LLM에 원문 passage 대신 passage ID가 전달됩니다.
- v06 `graph.py:14`: 그래프의 간선 구조가 논문과 다릅니다.
- v06 `retrieve.py:21-22`: PPR passage 초기화가 구현되지 않았습니다.
- v06 `retrieve.py:21`: 엔티티 초기화 점수가 다릅니다.
- v06 `retrieve.py:21-22`: PPR의 초기화·정규화가 논문의 식과 일치하지 않습니다.
- v06 `run.py:25`: 검색된 context에 질의와 generation 지시가 충분히 반영되지 않습니다.
- v06 `run.py:19-20`: 실험 데이터가 작업 폴더에 없습니다.
- v06 `logs/2wikimultihopqa.log:1`: 실행 로그가 논문의 전체 실험을 포함하지 않습니다.
- v06 `run.py:28-30, logs/2wikimultihopqa.log:1`: 효율성 측정 및 토큰 사용량 로그가 빠졌습니다.
- v06 `config.yaml:2, run.py:8, run.py:16`: 재현 설정의 핵심 임베딩 모델이 실제로 적용되지 않습니다.
- v06 `logs/2wikimultihopqa.log:1`: 로그 결과만으로는 실제 논문 실험 조건을 검증할 수 없습니다.
- v07 `run.py:23; retrieve.py:15-18`: 질의 엔티티를 의미 유사도로 검색하지 않고 데이터에 이미 들어 있는 `ex["entities"]`를 그대로 사용합니다.
- v07 `retrieve.py:5-12`: 의미 기반 엔티티 활성화가 구현되어 있지 않습니다.
- v07 `retrieve.py:7-12; graph.py:14-18`: 활성화 탐색은 사실상 첫 단계에서 중단됩니다.
- v07 `retrieve.py:5-12; config.yaml:11-12`: `delta`를 논문의 동적 pruning 임계값으로 사용하지 않습니다.
- v07 `run.py:8,16; retrieve.py 전체`: 논문에서 사용한 임베딩 모델이 로드되지만 검색에 전혀 사용되지 않습니다.
- v07 `retrieve.py:17-22`: 패시지 초기화 점수의 하이브리드 공식이 구현되지 않았습니다.
- v07 `retrieve.py:18,21-22`: PPR 엔티티 초기화가 유사도 점수가 아닌 이진값입니다.
- v07 `graph.py:8-18; retrieve.py:20-22`: 그래프 구조와 PPR 대상이 논문과 다릅니다.
- v07 `logs/2wikimultihopqa.log:1; run.py:18-30`: 네 데이터셋 전체에 대한 실행 로그가 제공되지 않았습니다.
- v08 `run.py:16, retrieve.py:5-23`: Sentence/entity embedding과 semantic similarity 계산이 실제로 사용되지 않습니다.
- v08 `run.py:23, retrieve.py:5-12`: Stage 1의 query entity 초기화가 논문과 다릅니다.
- v08 `retrieve.py:5-12`: Semantic bridging 기반 entity activation이 구현되지 않았습니다.
- v08 `retrieve.py:5-12, config.yaml:11-12`: Dynamic pruning이 threshold 방식으로 구현되지 않았습니다.
- v08 `retrieve.py:19-23`: Stage 2 PPR의 hybrid passage initialization이 누락되었습니다.
- v08 `retrieve.py:20-22`: Passage retrieval에 사용되는 그래프와 초기화가 논문의 entity activation 결과를 보존하지 않습니다.
- v08 `run.py:24-25`: 생성 프롬프트가 논문 실험 조건을 충분히 반영하지 않습니다.
- v08 `run.py:18-31`: 논문의 baseline 비교 실험이 구현되어 있지 않습니다.
- v08 `run.py:18-31, logs/2wikimultihopqa.log:1`: 효율성 측정 조건과 결과 기록이 빠져 있습니다.
- v08 `run.py:18-31, config.yaml:1-15`: 논문의 ablation 실험이 빠져 있습니다.
- v08 `run.py:18-31, logs/2wikimultihopqa.log:1`: 추가 retrieval-quality 실험이 빠져 있습니다.
- v08 `config.yaml:2,10,12, run.py:16-31`: hyperparameter sensitivity 및 embedding backbone 비교가 빠져 있습니다.
- v08 `run.py:18-31, logs/2wikimultihopqa.log:1`: 대규모 ATLAS-Wiki 효율성 실험이 빠져 있습니다.
- v08 `logs/2wikimultihopqa.log:1`: 실행 로그가 논문에서 요구한 전체 실험을 포함하지 않습니다.
