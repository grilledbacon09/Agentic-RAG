# Drug RAG DE — 데이터 명세서

AI 파트 및 WEB 파트 연동을 위한 데이터 구조, 종류, 태그 정보를 정리한 문서입니다.

---

## 1. 아키텍처 개요

```
S3 Bronze (raw)
    ↓ Python ETL
S3 Silver (정제)
    ↓ Colab GPU 임베딩 (multilingual-e5-large)
PostgreSQL + pgvector (Gold)
    ↓
AI 파트 (LangChain Agentic RAG)
```

---

## 2. VectorDB 연결 정보

```
host:     localhost
port:     5432
dbname:   drug_rag
user:     airflow
password: .env 참고

테이블:   drug_documents
임베딩 모델: intfloat/multilingual-e5-large
임베딩 차원: 1024
쿼리 접두사: "query: {질문}"  ← 필수
```

### LangChain 연결 예시

```python
from langchain_community.vectorstores import PGVector
from langchain_huggingface import HuggingFaceEmbeddings

embeddings = HuggingFaceEmbeddings(
    model_name="intfloat/multilingual-e5-large",
    encode_kwargs={"normalize_embeddings": True},
    query_instruction="query: ",
)

CONNECTION_STRING = "postgresql+psycopg2://airflow:PASSWORD@localhost:5432/drug_rag"

vectorstore = PGVector(
    connection_string=CONNECTION_STRING,
    embedding_function=embeddings,
    collection_name="drug_documents",
)

# doc_type 필터 검색
results = vectorstore.similarity_search(
    query="두통에 먹는 약",
    k=5,
    filter={"doc_type": "drug_efficacy"},
)
```

---

## 3. drug_documents 테이블 스키마

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | SERIAL | PK |
| doc_id | TEXT | 문서 고유 ID (UNIQUE) |
| doc_type | TEXT | 문서 유형 (하단 참조) |
| chunk_index | INTEGER | 청크 번호 |
| text | TEXT | 임베딩 대상 텍스트 |
| embedding | vector(1024) | 임베딩 벡터 |
| name | TEXT | 약품명 또는 질환명 |
| source_name | TEXT | 출처명 |
| source_url | TEXT | 출처 URL |
| license | TEXT | 라이선스 |
| provider | TEXT | 제공 기관 |
| item_url | TEXT | 상세 페이지 URL |
| manufacturer | TEXT | 제조사 (약품만) |
| image_url | TEXT | 약품 이미지 URL |
| dur_type | TEXT | DUR 금기 유형 (dur_interaction만) |
| ingredient_a | TEXT | 성분A 한글명 (dur_interaction만) |
| ingredient_b | TEXT | 성분B 한글명 (dur_interaction만) |
| metadata | JSONB | 전체 메타데이터 JSON |
| created_at | TIMESTAMP | 생성 일시 |

---

## 4. doc_type 태그

| doc_type | 설명 | 건수 | 담당 Agent |
|----------|------|------|-----------|
| `drug_efficacy` | 약품 효능/적응증 | ~8,251건 | 약품 추천 |
| `drug_usage` | 용법/용량 + 복용 스케줄 | ~8,530건 | 복용 스케줄 |
| `drug_caution` | 주의사항/경고 | ~13,177건 | 병용금기·위험감지 |
| `drug_side_effect` | 부작용/이상반응 | ~1,466건 | 병용금기 |
| `dur_interaction` | 병용금기/임부금기 등 7종 | ~59,983건 | 병용금기 |
| `symptom_info` | 질환 일반 정보 | ~1,804건 | 증상 분석 |
| `symptom_redflag` | 위험증상/병원 방문 필요 | ~321건 | 위험 감지 |

---

## 5. 데이터 소스별 메타데이터

### 5-1. drug_efficacy / drug_usage / drug_caution / drug_side_effect

```json
{
  "name": "타이레놀정500밀리그램",
  "manufacturer": "한국얀센",
  "source_name": "식품의약품안전처 e약은요",
  "source_url": "https://www.data.go.kr/data/15075057/openapi.do",
  "license": "공공누리 1유형",
  "provider": "식품의약품안전처",
  "item_url": "https://nedrug.mfds.go.kr/...",
  "image_url": "https://...",
  "parent_doc_id": "public_195700020",
  "section": "efficacy",
  "etl_at": "2026-09-01T12:00:00"
}
```

**drug_usage 전용 - structured_usage 필드:**

```json
{
  "structured_usage": {
    "age_groups": ["만 15세 이상", "성인"],
    "dose": {"amount": "1~2", "unit": "정", "raw": "1회 1~2정"},
    "frequency": {"times_per_day": 3, "raw": "1일 3회"},
    "timing": [{"type": "식후", "minutes": 30}],
    "interval": {"min_hours": 4},
    "max_days": {"max_days": 3},
    "max_daily_dose": {"amount": "8", "unit": "정"},
    "raw": "원본 텍스트"
  }
}
```

**timing.type 값:**
`식후` / `식전` / `식간` / `취침전` / `공복` / `식사와함께` / `배변후` / `승차전` / `기상후`

---

### 5-2. dur_interaction

```json
{
  "dur_type": "combination_ban",
  "dur_desc": "병용금기",
  "ingredient_a_kor": "이트라코나졸",
  "ingredient_a_eng": "Itraconazole",
  "ingredient_b_kor": "심바스타틴",
  "ingredient_b_eng": "Simvastatin",
  "item_name": "코니트라캡슐(이트라코나졸)",
  "item_seq": "200000913",
  "manufacturer": "코오롱제약(주)",
  "mixture_item_name": "리피스탄정(심바스타틴)",
  "mixture_manufacturer": "(주)테라젠이텍스",
  "reason": "횡문근융해증",
  "notification_date": "20090303",
  "source_name": "식품의약품안전처 DUR",
  "license": "공공누리 1유형",
  "provider": "식품의약품안전처"
}
```

**dur_type 값:**

| dur_type | 설명 |
|----------|------|
| `combination_ban` | 병용금기 |
| `pregnancy_ban` | 임부금기 |
| `elderly_caution` | 노인주의 |
| `dose_caution` | 용량주의 |
| `effect_duplicate` | 효능군중복 |
| `age_specific_ban` | 특정연령대금기 |
| `dosing_period_caution` | 투여기간주의 |

---

### 5-3. symptom_info / symptom_redflag

```json
{
  "name": "감기",
  "system_code": "HH",
  "system_name": "호흡기",
  "item_url": "https://health.kdca.go.kr/...",
  "brd_sid": "5423",
  "has_redflag": false,
  "source_name": "국가건강정보포털",
  "source_url": "https://health.kdca.go.kr",
  "license": "공공누리 4유형",
  "provider": "질병관리청",
  "parent_doc_id": "portal_HH_감기"
}
```

**system_code 값:**

| system_code | system_name |
|------------|------------|
| `NE` | 뇌신경 |
| `JU` | 정신건강 |
| `KO` | 귀코목 |
| `KU` | 구강 |
| `BB` | 뼈근육 |
| `PB` | 피부 |
| `NB` | 내분비 |
| `HH` | 호흡기 |
| `SO` | 순환기 |
| `SW` | 소화기 |
| `MH` | 면역 |
| `SA` | 비뇨기 |
| `SS` | 생식기 |

---

## 6. Agent별 검색 전략

```python
# 증상 분석 Agent
vectorstore.similarity_search(query, filter={"doc_type": "symptom_info"})

# 위험 감지 Agent
vectorstore.similarity_search(query, filter={"doc_type": "symptom_redflag"})

# 약품 추천 Agent
vectorstore.similarity_search(query, filter={"doc_type": "drug_efficacy"})

# 복용 스케줄 Agent
vectorstore.similarity_search(query, filter={"doc_type": "drug_usage"})
# → metadata.structured_usage 필드로 스케줄 생성

# 병용금기 Agent (성분명 기반)
vectorstore.similarity_search(
    query,
    filter={"doc_type": "dur_interaction", "dur_type": "combination_ban"}
)
# 또는 SQL 직접 조회
cur.execute("""
    SELECT * FROM drug_documents
    WHERE doc_type = 'dur_interaction'
    AND ingredient_a ILIKE %s
""", (f"%{성분명}%",))
```

---

## 7. 출처 및 라이선스

| 소스 | 라이선스 | 상업 이용 |
|------|---------|---------|
| 식품의약품안전처 e약은요 | 공공누리 1유형 | ✅ 가능 |
| 식품의약품안전처 DUR | 공공누리 1유형 | ✅ 가능 |
| 국가건강정보포털 | 공공누리 4유형 | ⚠️ 출처표시+비상업+변경금지 |
| 약학정보원 | 비상업적 참조 목적 | ⚠️ 비상업 한정 |

---

## 8. S3 데이터 레이크 구조

```
s3://drug-rag-datalake-331145994962/
├── bronze/                          ← raw 수집 데이터
│   ├── api/
│   │   ├── public_data/             ← e약은요 API
│   │   └── dur/                     ← DUR API
│   └── crawl/
│       ├── health_portal/           ← 국가건강정보포털
│       └── health_kr/               ← 약학정보원
├── silver/                          ← 정제 데이터
│   ├── drugs/
│   │   ├── public_drug/
│   │   └── health_kr_drug/
│   ├── dur_interactions/
│   │   ├── combination_ban/
│   │   ├── pregnancy_ban/
│   │   ├── elderly_caution/
│   │   ├── dose_caution/
│   │   ├── effect_duplicate/
│   │   ├── age_specific_ban/
│   │   └── dosing_period_caution/
│   ├── symptoms/
│   │   ├── health_portal/
│   │   └── health_kr_disease/
│   └── refined/                     ← doc_type 세분화
│       ├── drugs/
│       ├── dur/
│       └── symptoms/
└── gold/
    └── pgvector_dump/               ← pg_dump 백업
        └── YYYY-MM-DD/
            └── drug_rag_pgvector.dump
```
