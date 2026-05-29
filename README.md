agentic rag/
├─ data/
│  ├─ drugs.json # 의약품 정보(효능, 복용법, 주의사항 등)를 담은 샘플 데이터
│  └─ symptoms.json # 증상 정보와 위험 여부(red flag)를 담은 샘플 데이터
└─
   ├─ models.py # 의약품, 증상, 사용자 입력 등 전체 데이터 구조를 정의하는 파일
   ├─ loader.py # JSON 파일로부터 의약품 및 증상 데이터를 불러와 객체로 변환하는 모듈
   ├─ safety.py # 위험 증상(red flag)과 병용금기, 주의사항을 검사하는 안전성 판단 모듈
   ├─ retriever.py # 사용자 증상과 의약품 정보를 비교하여 관련 약 후보를 검색하고 점수화하는 모듈
   ├─ generator.py # 검색된 약 정보를 기반으로 사용자에게 보여줄 최종 응답을 생성하는 모듈
   ├─ pipeline.py # 입력 → 안전성 검사 → 약 검색 → 응답 생성까지 전체 RAG 흐름을 연결하는 핵심 파이프라인
   └─ main.py # 사용자 입력을 받아 전체 파이프라인을 실행하고 결과를 출력하는 실행 진입점

11. 실행 방법

프로젝트 루트에서:

cd project
python app/main.py

예시 입력:

증상 입력: 두통,발열
현재 복용 중인 약 ID 입력 (예: D001,D002): D002
현재 복용 중인 약 이름 입력:
알레르기 입력:
기저질환/특이상태 입력: 음주

그러면 대략 이런 식으로 나온다.

[입력 정보]
- 증상: 두통, 발열
- 현재 복용 약 ID: D002
- 현재 복용 약 이름: 없음
- 알레르기: 없음
- 기저/특이 상태: 음주

[추천 후보]
1. 타이레놀정500mg (D001)
   - 점수: ...
   - 적응증: 감기로 인한 발열 및 통증, 두통, 신경통
   - 복용법: 성인 1회 1~2정, 1일 3~4회(최대 4g)
   - 주의사항: 간 손상 위험, 매일 3잔 이상 음주자 금기
   - 매칭 증상: 두통, 발열
   - 추천 근거: ...
   - 안전성 경고:
     - 타이레놀정500mg는 현재 복용 중인 약 ID 'D002'와 병용금기 가능성이 있습니다.
     - 타이레놀정500mg 경고문에 사용자 상태 '음주' 관련 주의 문구가 있습니다.
12. 지금 코드의 특징

이 코드는 지금 단계에서 딱 필요한 구조만 넣어놨다.

이미 되는 것
DE가 준 drug 구조 반영
미래 vector DB용 child_chunks, metadata 구조 반영
symptom DB 기반 safety 확장 가능
현재는 정적 retrieval + rule 기반 경고 가능
병용금기 ID 체크 가능
아직 일부러 안 넣은 것
실제 임베딩
vector DB
LLM 자연어 생성
FastAPI
추가 질문 agent
fuzzy matching
동의어 처리
13. 지금 바로 다음으로 하면 좋은 것

다음 단계는 두 가지 중 하나다.

A. 이 코드를 그대로 FastAPI로 감싸서 웹팀이 바로 호출 가능하게 만들기
또는
B. symptom DB를 더 실제적으로 채우고 red flag 룰을 강화하기

개인적으로는 다음 턴에서
api.py까지 추가해서 FastAPI 버전으로 바로 연결 가능한 형태로 만들어주는 게 가장 좋다.


agentic rag/
├─ data/
│  ├─ raw/                                # 공공 API / MSD 원본 데이터
│  ├─ processed/                          # 정제된 정식 drug/symptom/chunk 데이터
│  └─ sample/                             # 초기 MVP용 샘플 데이터
│
├─ db/
│  ├─ postgres/                           # 정형 메타데이터 저장
│  └─ vectordb/                           # Chroma vector DB 및 embedding/index
│
├─ app/
│  ├─ core/                               # 공통 모델 및 설정
│  ├─ data/                               # 로더 / 전처리 / entity 추출
│  ├─ rag/                                # keyword / vector / hybrid retrieval
│  ├─ safety/                             # red flag / 병용금기 / guardrail
│  ├─ agents/                             # query / safety / retrieval / recommendation agent
│  ├─ generation/                         # prompt / response generation
│  ├─ pipeline/                           # static / hybrid / agentic pipeline
│  └─ api/                                # FastAPI 서버
│
├─ tests/                                 # 기능 테스트
├─ scripts/                               # 데이터 구축 및 인덱싱 스크립트
├─ docker-compose.yml                     # 전체 서비스 실행
└─ README.md