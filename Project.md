# Agentic-RAG Project

증상 기반 일반의약품 복약 상담 Agentic-RAG 프로젝트.  
Multi-turn 대화 + LLM orchestrator + 규칙/Chroma hybrid retrieval + 안전성 검증 파이프라인.

---

## 1. 전체 파일 구조 및 파일별 설명

```
agentic-rAG/
├── main.py                      # FastAPI 서버 진입점 (Web 백엔드)
├── requirements.txt             # 루트(FastAPI) Python 의존성
├── Project.md                   # 본 문서
├── .env                         # OPENAI_API_KEY, USE_LLM, USE_CHROMA 등 (Git 제외)
├── .gitignore
│
├── data/                        # ★ 데모/Web/AI가 사용하는 최종 데이터셋 (Git 포함)
│   ├── drugs.json               # 약 마스터 (~4,760건, 병용금기 포함)
│   ├── symptoms.json            # 증상 마스터 (~794건)
│   └── processed/               # 전처리·export 중간 산출물
│
├── api/                         # FastAPI 라우터 (Web API)
│   ├── diagnosis.py             # POST /api/diagnosis — 1턴 Agentic RAG
│   ├── user.py                  # POST/GET /api/user/setting — 유저 설정(메모리)
│   └── medicines.py             # GET /api/medicines — 약 검색 API
│
├── agents/                      # AI 파트 (대화·RAG·추천)
│   ├── chat_main.py             # 터미널 대화형 CLI
│   ├── chat_web.py              # Gradio 웹 채팅 UI
│   ├── chat_service.py          # CLI/Web 공통 채팅 서비스 (create_chat, send_message)
│   ├── conversation_agent.py    # Multi-turn 오케스트레이터 (LLM/규칙 분기)
│   ├── llm_orchestrator.py      # LLM 턴 분석·슬롯·추천 시점 판단 (TurnPlan)
│   ├── llm_client.py            # OpenAI 클라이언트, 증상 추출·응답 polish
│   ├── conversation_formatter.py# 규칙 기반 답변 템플릿 (추천·follow-up)
│   ├── slot_extractor.py        # 한국어 자유 발화 → 증상/약/알레르기/기저질환 추출
│   ├── intent_detector.py       # 의도 분류 (추천 요청, follow-up, exit 등)
│   ├── off_topic.py             # 오프토픽(비의료) 입력 차단
│   ├── enhanced_pipeline.py     # Agentic RAG core + run_enhanced_pipeline(문자열)
│   ├── pipeline.py              # 기본(단순) RAG 파이프라인
│   ├── retriever.py             # drugs.json 규칙 점수 + Chroma hybrid 검색
│   ├── chroma_retriever.py      # ChromaDB medical_knowledge 검색 헬퍼
│   ├── recommendation_agent.py  # 추천/비추천 최종 판단
│   ├── reranker.py              # 관련도·안전성 기반 재정렬
│   ├── safety.py                # 약물별 안전성 평가
│   ├── contraindication.py      # 병용금기·금기 조건 검사
│   ├── red_flag.py              # 응급 red flag 검사
│   ├── symptom_utils.py         # 증상 DB 중복·응급 판정 유틸
│   ├── symptom_context_filter.py# Chroma 참고 문맥 신체 부위 필터
│   ├── query_agent.py           # UserInput 분석
│   ├── clarification_agent.py   # 추가 질문 필요 여부 판단
│   ├── validator.py             # 추천 결과 검증
│   ├── generator.py             # 응급 응답·텍스트 생성 헬퍼
│   ├── agent_trace.py           # Multi-Agent reasoning trace 포맷
│   ├── trace_sink.py            # 터미널 실시간 trace 출력
│   ├── loader.py                # drugs.json / symptoms.json 로드
│   ├── models.py                # UserInput, Drug, PipelineResult 등 dataclass
│   ├── config.py                # AppConfig, load_config()
│   ├── prompts.py               # LLM 시스템 프롬프트
│   ├── enhanced_main.py         # 레거시 1턴 CLI (enhanced pipeline)
│   ├── main.py                  # 레거시 1턴 CLI (basic pipeline)
│   ├── build_dataset.py         # 데이터셋 빌드 유틸
│   ├── build_chunks.py          # 청크 생성 유틸
│   ├── chunker.py               # 텍스트 청킹
│   ├── cleaner.py               # 데이터 정제
│   ├── run.ps1                  # agents 실행 헬퍼 (chat/web/enhanced 등)
│   └── requirements.txt         # agents Python 의존성
│
├── database/                    # DE(Data Engineering) 파트
│   ├── docker-compose.yml       # PostgreSQL, MinIO, ChromaDB (선택)
│   ├── .env.example             # DB/Chroma/API 키 템플릿
│   ├── readme.md                # DE 파이프라인 상세 문서
│   ├── run_export_no_docker.ps1 # ★ Docker 없이 data/*.json 생성
│   ├── run_import_team_data.ps1 # 팀 zip → Silver → Chroma → JSON (Docker 필요)
│   ├── run_full_dataset.ps1     # Docker 전체 구축 원스톱
│   ├── run_full_pipeline.ps1    # API 수집 기반 전체 파이프라인
│   ├── run.ps1                  # DE 단계별 실행 헬퍼
│   ├── schemas.py               # DE 스키마 타입
│   ├── data/                    # 팀 원본 (minio, msd_source) — Git 제외
│   └── src/
│       ├── bootstrap.py         # .env 로드, sys.path 부트스트랩
│       ├── infra/
│       │   ├── init_postresql.sql   # PostgreSQL DDL (Silver 테이블)
│       │   ├── set_client.py        # PostgreSQL·MinIO 클라이언트
│       │   ├── paths.py             # DE 경로 상수
│       │   ├── minio_part.py        # MinIO part.1 JSON 스트리밍 추출
│       │   ├── api_keys.py          # 공공데이터 API 키 조회
│       │   └── api_response.py      # API 응답 파싱
│       ├── collector/
│       │   ├── api_ingestion.py     # e약은요/DUR API 전체 수집
│       │   ├── api_collector.py     # API 샘플 수집
│       │   ├── msd_link_collector.py# MSD 증상 링크 수집
│       │   └── msd_collector.py     # MSD AI 파싱 수집
│       ├── extractor/
│       │   ├── import_team_data.py      # 팀 zip → PostgreSQL Silver
│       │   ├── export_team_data_direct.py # ★ 팀 zip → data/*.json (Docker 불필요)
│       │   ├── export_silver_to_ai.py   # PostgreSQL → data/*.json
│       │   ├── api_save_to_silver.py    # MinIO Bronze → Silver
│       │   ├── msd_save_to_silver.py    # MSD CSV → Silver
│       │   └── seed_dev_data.py         # 개발용 샘플 시드
│       ├── vectordb/
│       │   ├── create_vectordb.py   # Chroma 클라이언트·임베딩
│       │   ├── vectorizer.py      # Silver → Chroma medical_knowledge
│       │   └── test_vectordb.py     # Chroma 검색 테스트
│       └── pipeline/
│           └── preflight.py         # Docker·API·경로 사전 점검
│
└── venv/                        # Python 가상환경 (Git 제외)
```

### data/ 하위 (데모 핵심)

| 파일 | 설명 |
|------|------|
| `data/drugs.json` | AI/Web 데모용 약 catalog (효능, 복용법, `combination_contraindication` 등) |
| `data/symptoms.json` | 증상 catalog (red flag, action_guide) |
| `data/processed/*.json` | export/정제 중간 파일 |

### database/data/ (로컬 원본, Git 제외)

| 경로 | 설명 |
|------|------|
| `database/data/msd_source/silver_data.csv` | MSD 증상 Silver CSV |
| `database/data/minio/bronze/drug_info/.../part.1` | e약은요 약 원본 |
| `database/data/minio/bronze/taboo_info/.../part.1` | DUR 병용금기 원본 (~81만 행) |

---

## 2. 입출력 동작 매커니즘

### 2.1 전체 아키텍처

```
[데모 데이터]
  data/drugs.json + data/symptoms.json
        │
        ├─► FastAPI (main.py) ──► app.state.DRUGS / SYMPTOMS
        │         │
        │         ├─ POST /api/diagnosis  (1턴, trace 문자열)
        │         ├─ GET  /api/medicines  (약 검색)
        │         └─ POST /api/user/setting (알레르기 등)
        │
        └─► agents/ (chat_main, chat_web)
                  │
                  ConversationalAgent
                    ├─ LLM orchestrator (매 턴 TurnPlan)
                    ├─ slot 수집 (증상→복용약→알레르기→기저질환)
                    └─ run_enhanced_pipeline_core (추천 시)
                          ├─ 규칙 retrieval (drugs.json)
                          ├─ Chroma hybrid (USE_CHROMA=true, Docker 시)
                          └─ generate_rag_reply_llm → 자연어 답변
```

### 2.2 경로별 입출력

#### A) Web API — `POST /api/diagnosis` (1턴, 레거시)

**입력 (JSON body)**

```json
{
  "content": "머리가 아파요"
}
```

**내부 변환**

```python
UserInput(
  symptoms=["머리가 아파요"],
  current_drug_ids=[],
  current_drug_names=[],
  allergies=[...],   # USER_DB에서 조회
  conditions=[]
)
```

**출력**

```json
{
  "role": "ai",
  "content": "[Multi-Agent Reasoning Trace]\n...\n1. 타이레놀정 ..."
}
```

- `content`는 **사용자용 상담 멘트가 아니라** debug trace 포함 **긴 텍스트**
- ChatGPT형 UX는 `chat_service` / 향후 `/api/chat` 계열 필요

---

#### B) Web API — `POST /api/user/setting`

**입력**

```json
{
  "user_id": "user_01",
  "gender": "male",
  "age_group": "20s",
  "allergies": ["페니실린"]
}
```

**출력**

```json
{
  "status": "success",
  "message": "유저 설정이 서버에 안전하게 저장되었습니다."
}
```

---

#### C) Web API — `GET /api/medicines?search=타이레놀`

**출력:** `Drug` 객체 배열 (JSON 직렬화, `loader.py` 구조)

```json
[
  {
    "drug_id": "...",
    "name_ko": "타이레놀정500mg",
    "ingredient": ["아세트아미노펜"],
    "indications": "...",
    "dosage": "...",
    "warnings": "...",
    "combination_contraindication": ["..."],
    "child_chunks": [...]
  }
]
```

---

#### D) 대화형 AI — `chat_main.py` / `chat_web.py`

**입력:** 터미널/Gradio 사용자 **자연어 문자열** (multi-turn)

**내부 상태:** `ConversationSession`

| 필드 | 설명 |
|------|------|
| `user_input` | `UserInput` (누적 슬롯) |
| `phase` | `collecting` / `clarifying` / `recommending` / `follow_up` / `emergency` / `ended` |
| `turns` | 대화 이력 |
| `confirmed_slots` | 확인된 슬롯 (`symptoms`, `current_meds`, …) |

**출력:** assistant **자연어 문자열** (`ConversationResponse.message`)

추천 시 내부 흐름:

```
run_enhanced_pipeline_core() → PipelineResult
  → format_recommendation_message() → draft
  → generate_rag_reply_llm() → 최종 message
```

---

#### E) Agentic RAG Core — `run_enhanced_pipeline_core`

**입력**

| 파라미터 | 타입 | 설명 |
|----------|------|------|
| `user_input` | `UserInput` | 증상·복용약·알레르기·기저질환 |
| `drugs` | `List[Drug]` | `data/drugs.json`에서 로드 |
| `symptoms` | `List[Symptom]` | `data/symptoms.json`에서 로드 |
| `context_text` | `str` | 최근 사용자 발화 (red flag·Chroma용) |
| `on_step` | `Callable` | reasoning trace 실시간 콜백 (선택) |

**출력:** `PipelineResult`

| 필드 | 설명 |
|------|------|
| `decision.recommended` | 1~3순위 추천 약 |
| `decision.rejected` | 제외 후보 |
| `is_emergency` | 응급 여부 |
| `emergency_message` | 응급 안내 문구 |
| `trace_steps` | Agent 단계별 trace |
| `symptom_context` | Chroma 증상 참고 청크 |

---

#### F) 데모 데이터셋 JSON 스키마

**`data/symptoms.json` (배열)**

```json
{
  "symptom_id": "S002",
  "name": "통증",
  "is_red_flag": false,
  "urgency": null,
  "context": "경고 징후 설명...",
  "action_guide": "대응 가이드..."
}
```

**`data/drugs.json` (배열)**

```json
{
  "drug_id": "196900058",
  "name_ko": "코푸시럽에스",
  "ingredient": ["..."],
  "indications": "...",
  "dosage": "...",
  "warnings": "...",
  "combination_contraindication": ["병용금기 약물명..."],
  "parent_text": "...",
  "child_chunks": [
    { "chunk_type": "indication", "text": "...", "metadata": { "treats": ["기침"] } }
  ]
}
```

- **병용금기(DUR):** `combination_contraindication` 필드 (601약에 값 존재)
- 별도 taboo.json 없음

---

#### G) Import 규칙 (Web ↔ AI 합의)

| 실행 위치 | import 방식 |
|-----------|-------------|
| **프로젝트 루트** (`uvicorn main:app`) | Web: `main.py`에 `agents/`를 `sys.path` 추가 후 `from models import ...` |
| **agents/ 폴더** (`python chat_main.py`) | `from models import ...` (로컬 import) |

---

### 2.3 환경 변수 (`.env`)

| 변수 | 기본(데모) | 설명 |
|------|------------|------|
| `OPENAI_API_KEY` | (필수) | LLM 대화·orchestrator |
| `USE_LLM` | `true` | LLM 사용 |
| `USE_LLM_ORCHESTRATOR` | `true` | ChatGPT형 턴 orchestrator |
| `USE_CHROMA` | `false` | Docker 없을 때 OFF (JSON 규칙 검색만) |
| `SHOW_REASONING` | `true` | 터미널 trace (Windows cp949 이슈 시 `false`) |

---

## 3. 데모 실행 스크립트 예시

### 3.1 사전 준비 (1회)

```powershell
cd "C:\Users\user\Desktop\agentic rag"
python -m venv venv
.\venv\Scripts\pip.exe install -r requirements.txt
.\venv\Scripts\pip.exe install -r agents\requirements.txt
```

루트 `.env` 예시:

```env
OPENAI_API_KEY=sk-...
USE_LLM=true
USE_LLM_ORCHESTRATOR=true
USE_CHROMA=false
SHOW_REASONING=false
```

---

### 3.2 데이터셋 구축 (Docker 없이 — 현재 데모 방식)

```powershell
cd database
.\run_export_no_docker.ps1
# 또는: .\run.ps1 json
```

- 입력: `database/data/msd_source/`, `database/data/minio/bronze/`
- 출력: `data/drugs.json`, `data/symptoms.json`

---

### 3.3 터미널 대화형 채팅 (데모 권장)

```powershell
cd agents
..\venv\Scripts\python.exe chat_main.py
```

**데모 시나리오 예시**

```
You: 기관지염이 있고 기침이 심해요
You: 약 안 먹어요
You: 알레르기 없음
You: 추천해 주세요
You: 왜 이 약인가요?
You: 종료
```

---

### 3.4 Gradio 웹 채팅 UI

```powershell
cd agents
..\venv\Scripts\pip.exe install gradio
..\venv\Scripts\python.exe chat_web.py
# 브라우저: http://127.0.0.1:7860
```

또는:

```powershell
cd agents
.\run.ps1 web
```

---

### 3.5 FastAPI Web 백엔드

```powershell
cd "C:\Users\user\Desktop\agentic rag"
.\venv\Scripts\uvicorn.exe main:app --reload --host 0.0.0.0 --port 8000
```

**API 호출 예시**

```powershell
# 진단 (1턴)
curl -X POST http://localhost:8000/api/diagnosis `
  -H "Content-Type: application/json" `
  -d "{\"content\": \"기침이 심해요\"}"

# 약 검색
curl "http://localhost:8000/api/medicines?search=레티콜"

# 유저 설정
curl -X POST http://localhost:8000/api/user/setting `
  -H "Content-Type: application/json" `
  -d "{\"user_id\":\"user_01\",\"gender\":\"\",\"age_group\":\"\",\"allergies\":[]}"
```

---

### 3.6 레거시 1턴 CLI (비교용)

```powershell
cd agents
..\venv\Scripts\python.exe enhanced_main.py   # trace 문자열 출력
..\venv\Scripts\python.exe main.py            # basic pipeline
```

---

### 3.7 (선택) Docker + Chroma full stack

Docker Desktop 실행 후:

```powershell
cd database
.\run_full_dataset.ps1
```

루트 `.env`에서 `USE_CHROMA=true` 설정 후 채팅/API 재시작.

---

## 부록: 현재 데모 데이터셋 규모

| 항목 | 규모 |
|------|------|
| `data/drugs.json` | ~4,760건 |
| `data/symptoms.json` | ~794건 |
| 병용금기 반영 약 | ~601건 (`combination_contraindication`) |
| Chroma | Docker 없이 **OFF** (JSON 규칙 retrieval) |

---

## 부록: Web 팀 전달 요약

- **데모 데이터 위치:** Git 루트 `data/drugs.json`, `data/symptoms.json`
- **병용금기:** `drugs.json` → `combination_contraindication` 필드
- **현재 Web API:** `POST /api/diagnosis` (1턴 trace) / ChatGPT형 multi-turn은 `chat_service` 기반 API 추가 예정
- **`database/data/`:** DE 원본, Web에서 직접 참조 불필요
