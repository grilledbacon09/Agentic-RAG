# DE (Data Engineering) 파트 README

## 목차
1. [프로젝트 개요](#1-프로젝트-개요)
2. [인프라 구성](#2-인프라-구성)
3. [전체 데이터 파이프라인](#3-전체-데이터-파이프라인)
4. [파일 구조](#4-파일-구조)
5. [파일별 역할 및 사용법](#5-파일별-역할-및-사용법)
6. [환경 설정](#6-환경-설정)
7. [실행 순서](#7-실행-순서)
8. [출력 예시](#8-출력-예시)
9. [RAG 파트 연동 가이드](#9-rag-파트-연동-가이드)
10. [알려진 이슈 및 주의사항](#10-알려진-이슈-및-주의사항)

---

## 1. 프로젝트 개요

증상 기반 약 추천 서비스를 위한 데이터 수집, 정제, 벡터 DB 구축 파이프라인입니다.

**데이터 소스**

| 소스 | 설명 | 수집 대상 |
|---|---|---|
| MSD 매뉴얼 (https://www.msdmanuals.com) | 증상별 의료 정보 | 원인, 경고징후, 대응 가이드, 기저질환 |
| 식품의약품안전처 e약은요 API | 일반의약품 개요 정보 | 효능, 용법, 주의사항, 부작용 |
| 식품의약품안전처 DUR API | 의약품 안전사용서비스 | 병용금기 정보 |

**데이터 존 (Data Zone)**
```
[Web / 공공 API]
       ↓ 수집
  Bronze Zone (MinIO)        ← 원본 데이터 그대로 보존
       ↓ 정제
  Silver Zone (PostgreSQL)   ← 구조화된 정제 데이터
       ↓ 벡터화
  ChromaDB                   ← 의미 기반 검색용 벡터 DB
```

---

## 2. 인프라 구성

`docker-compose.yml`로 전체 인프라를 한 번에 실행합니다.

```bash
docker-compose up -d
```

| 서비스 | 이미지 | 포트 | 용도 |
|---|---|---|---|
| MinIO | `minio/minio` | 9000 (API), 9001 (콘솔) | Bronze 원본 데이터 오브젝트 스토리지 |
| PostgreSQL | `ankane/pgvector` | 5432 | Silver 정제 데이터 + pgvector 확장 |
| ChromaDB | `chromadb/chroma` | 8000 | 벡터 DB (의미 기반 검색) |

**기본 계정 정보** (`.env`에서 변경 권장)

| 서비스 | 계정 | 비밀번호 |
|---|---|---|
| MinIO | admin | minio111 |
| PostgreSQL | postgres | postgres111 |

> MinIO 웹 콘솔: http://localhost:9001
> ChromaDB API: http://localhost:8000

---

## 3. 전체 데이터 파이프라인

```
[STEP 1] msd_link_collector.py
   MSD 증상 목록 HTML 파싱 → Bronze MinIO 저장
   (사전 조건: data/msd_source/symptoms.html 수동 저장 필요)

[STEP 2-A] msd_save_to_silver.py     (규칙 기반 HTML 파싱 / 빠름)
[STEP 2-B] msd_exctractor.py         (AI 기반 파싱 / 정밀, Gemini 사용)
   links.csv 기반 각 증상 페이지 크롤링
   → silver_symptom 테이블 (PostgreSQL) upsert

[STEP 3-A] api_ingestion.py          (페이지네이션 전체 수집 / 권장)
[STEP 3-B] api_collector.py          (단순 샘플 수집 / 테스트용)
   공공데이터포털 API 호출
   → Bronze MinIO 저장 (drug_info/, taboo_info/)
   → bronze_metadata 테이블에 수집 이력 기록

[STEP 4] api_save_to_silver.py
   Bronze MinIO → silver_drug_info, silver_taboo_info upsert
   → silver_drug_integration 테이블로 최종 통합

[STEP 5] vectorizer.py
   silver_symptom + silver_drug_integration 로드
   → 청크 생성 (증상 / 약물 / 증상-약 매핑)
   → ChromaDB medical_knowledge 컬렉션 적재

[STEP 6] test_vectordb.py
   ChromaDB 검색 테스트
```

---

## 4. 파일 구조

```
graduation_project/
├── docker-compose.yml              # 인프라 전체 실행 설정
│
├── src/
│   ├── infra/
│   │   ├── set_client.py           # MinIO, PostgreSQL 클라이언트 공통 모듈
│   │   └── init_postresql.sql      # PostgreSQL DDL (최초 1회 실행)
│   │
│   ├── collector/                  # Bronze Zone: 원본 수집
│   │   ├── msd_link_collector.py   # MSD 증상 링크 수집 → MinIO bronze
│   │   ├── msd_exctractor.py       # MSD AI 기반 파싱 (Gemini)
│   │   ├── api_ingestion.py        # 공공API 전체 페이지 수집 (권장)
│   │   └── api_collector.py        # 공공API 샘플 수집 (테스트용)
│   │
│   ├── extractor/                  # Silver Zone: 정제 및 저장
│   │   ├── msd_save_to_silver.py   # MSD 규칙 기반 파싱 → PostgreSQL
│   │   └── api_save_to_silver.py   # Bronze → Silver 정제 + 통합
│   │
│   └── vectordb/                   # Vector DB 구축
│       ├── create_vectordb.py      # ChromaDB 클라이언트 + E5 임베딩 함수
│       ├── vectorizer.py           # 청크 생성 + ChromaDB 적재
│       └── test_vectordb.py        # 검색 테스트
│
├── data/
│   ├── msd_source/
│   │   ├── symptoms.html           # MSD 증상 목록 페이지 (수동 저장)
│   │   └── links.csv               # 수집된 증상 URL 목록
│   ├── minio/                      # MinIO 볼륨 (Docker)
│   ├── postgres/                   # PostgreSQL 볼륨 (Docker)
│   └── chroma/                     # ChromaDB 볼륨 (Docker)
│
└── .env                            # 환경변수
```

---

## 5. 파일별 역할 및 사용법

### `infra/set_client.py`
MinIO(S3)와 PostgreSQL 클라이언트를 초기화하는 공통 모듈입니다. 모든 파일이 이 모듈을 import합니다.

```python
import set_client

# MinIO 사용
set_client.s3.put_object(Bucket="bronze", Key="file.json", Body=data)

# PostgreSQL 사용
conn = set_client.get_db_conn()
```

---

### `infra/init_postresql.sql`
PostgreSQL 테이블과 인덱스를 생성하는 DDL입니다. **최초 1회만 실행합니다.**

```bash
psql -h localhost -U postgres -d med_db -f src/infra/init_postresql.sql
```

**생성되는 테이블 및 뷰**

| 이름 | 종류 | 역할 |
|---|---|---|
| `bronze_metadata` | 테이블 | API 수집 이력 관리 |
| `silver_symptom` | 테이블 | MSD 파싱 증상 정보 |
| `silver_drug_info` | 테이블 | e약은요 API 약물 정보 |
| `silver_taboo_info` | 테이블 | DUR API 병용금기 정보 |
| `silver_drug_final` | 테이블 | 의약품 허가정보 (선택) |
| `silver_drug_integration` | 뷰 | 약물 정보 통합 (`vectorizer.py`가 참조) |

---

### `collector/msd_link_collector.py`
MSD 증상 목록 HTML을 파싱해 증상명, URL, 카테고리를 추출하고 MinIO bronze 버킷에 저장합니다.

**사전 조건**: `data/msd_source/symptoms.html` 파일이 있어야 합니다. MSD 증상 목록 페이지(https://www.msdmanuals.com/ko/home/특수-주제/증상에-대한-일반-개요)를 브라우저에서 직접 저장하세요.

```bash
python src/collector/msd_link_collector.py
```

**출력**: MinIO `bronze/msd_raw/links_YYYYMMDD.json`

---

### `extractor/msd_save_to_silver.py`
`data/msd_source/links.csv`의 URL을 순회하며 HTML 태그 기반 규칙으로 섹션을 추출해 PostgreSQL `silver_symptom` 테이블에 저장합니다.

```bash
python src/extractor/msd_save_to_silver.py
```

**추출 필드**

| 필드 | 내용 |
|---|---|
| `symptom_id` | S001, S002 형태의 고유 ID |
| `name` | 증상명 (동의어 포함, 예: `두통 (頭痛, headache)`) |
| `category` | 증상 카테고리 (예: 신경과, 소화기) |
| `is_red_flag` | 즉시 병원 방문 필요 여부 |
| `cause` | 증상 원인 |
| `warning_sign` | 경고 징후 |
| `meet_doc` | 의사 진찰이 필요한 경우 |
| `action_guide` | 치료/관리 가이드 |
| `pre_exist_condition` | 관련 기저질환 및 배경 |

---

### `collector/msd_exctractor.py`
`msd_save_to_silver.py`와 동일한 MSD 데이터를 AI(Gemini)로 더 정밀하게 파싱합니다. 규칙 기반 파싱으로 추출되지 않는 케이스를 보완할 때 사용합니다.

```bash
python src/collector/msd_exctractor.py
```

**규칙 기반 vs AI 기반 비교**

| 항목 | `msd_save_to_silver.py` | `msd_exctractor.py` |
|---|---|---|
| 방식 | HTML 태그 규칙 | Gemini AI |
| 속도 | 빠름 (1~2초/건) | 느림 (5~10초/건) |
| 비용 | 없음 | API 비용 발생 |
| 정확도 | HTML 구조 변경에 취약 | 높음 |
| 출력 | PostgreSQL 직접 upsert | CSV 로컬 저장 후 MinIO 업로드 |

> **주의**: `msd_exctractor.py`의 OpenRouter API 키가 코드에 하드코딩되어 있습니다. 실행 전 `.env`로 이동하고 `os.getenv('OPENROUTER_API_KEY')`로 교체하세요.

---

### `collector/api_ingestion.py` (권장)
공공데이터포털 API를 **전체 페이지네이션**으로 수집합니다. 502 에러 시 지수 백오프 재시도, 수집 이력을 `bronze_metadata` 테이블에 기록합니다.

```bash
python src/collector/api_ingestion.py
```

**수집 API 및 저장 경로**

| API | MinIO 경로 | 주요 데이터 |
|---|---|---|
| e약은요 (DrbEasyDrugInfoService) | `bronze/drug_info/YYYYMMDD_HHmmss.json` | 효능, 용법, 주의사항, 부작용 |
| DUR 병용금기 (DURPrdlstInfoService03) | `bronze/taboo_info/YYYYMMDD_HHmmss.json` | 병용금기 약물 쌍 정보 |

> `api_collector.py`는 페이지당 10건만 수집하는 테스트용입니다. 실제 수집에는 `api_ingestion.py`를 사용하세요.

---

### `extractor/api_save_to_silver.py`
MinIO Bronze에서 약물 데이터를 읽어 정제한 뒤 PostgreSQL Silver 테이블에 저장하고, `silver_drug_integration`으로 최종 통합합니다.

```bash
python src/extractor/api_save_to_silver.py
```

**처리 흐름**

```
bronze/drug_info/   → process_drug_info()  → silver_drug_info   ↘
                                                                   integrate_to_final() → silver_drug_integration
bronze/taboo_info/  → process_taboo_info() → silver_taboo_info  ↗
```

**`silver_drug_integration` 통합 로직**

- `silver_drug_info`를 기준으로 `silver_taboo_info`와 LEFT JOIN
- 병용금기 약물 ID를 배열(`array_agg`)로 집계 → `combination_contraindication` 컬럼
- `vectorizer.py`가 이 뷰/테이블을 `SELECT *`로 직접 참조

---

### `vectordb/create_vectordb.py`
ChromaDB 클라이언트와 `intfloat/multilingual-e5-base` 임베딩 함수를 정의합니다.

```bash
# 단독 실행: 컬렉션 초기화 + heartbeat 확인
python src/vectordb/create_vectordb.py
```

**E5 모델 prefix 규칙** (반드시 구분해야 성능이 정상으로 나옵니다)

| 상황 | prefix | 처리 위치 |
|---|---|---|
| 문서 저장 시 | `passage:` | `create_vectordb.py` `__call__` 내부에서 자동 처리 |
| 검색 쿼리 시 | `query:` | `test_vectordb.py` 쿼리 문자열에 직접 붙여야 함 |

---

### `vectordb/vectorizer.py`
PostgreSQL의 `silver_symptom`과 `silver_drug_integration`에서 데이터를 로드하고, 목적별 청크를 생성해 ChromaDB에 배치 적재합니다.

```bash
python src/vectordb/vectorizer.py
```

**생성되는 청크 유형**

| chunk_type | data_type | 데이터 출처 | 검색 목적 |
|---|---|---|---|
| `cause` | symptom | `cause` | 증상 원인 탐색 |
| `warning` | symptom | `warning_sign` + `meet_doc` | 응급 여부 판단 |
| `action` | symptom | `action_guide` | 행동 안내 |
| `pre_exist` | symptom | `pre_exist_condition` | 기저질환 연관 검색 |
| `indications` | drug | `indications` | 약물 효능 검색 |
| `warning` | drug | `warnings` | 약물 주의사항 |
| `contra` | drug | `combination_contraindication` | 병용금기 검색 |
| `dosage` | drug | `dosage` + `ingredient` | 복약 안내 |
| `symptom_drug_map` | mapping | 증상 × 약물 매핑 | **증상→약 추천** |

**청크 ID 형식**

| 유형 | ID 형식 | 예시 |
|---|---|---|
| 증상 청크 | `SYM_{symptom_id}_{chunk_type}` | `SYM_S001_cause` |
| 약물 청크 | `DRUG_{drug_id}_{chunk_type}` | `DRUG_200502128_indications` |
| 매핑 청크 | `MAP_{symptom_id}_{drug_id}` | `MAP_S001_200502128` |

---

### `vectordb/test_vectordb.py`
ChromaDB에 적재된 데이터를 대화형으로 검색 테스트합니다.

```bash
python src/vectordb/test_vectordb.py
```

**쿼리 작성 가이드**

```
# 증상으로 약 추천 (핵심 서비스)
질문: 두통

# 증상 원인 탐색
질문: 두통 원인

# 응급 여부 확인
질문: 두통 경고징후

# 병용금기 확인
질문: 아스피린 같이 먹으면 안 되는 약

# 복약 안내
질문: 타이레놀 용법
```

---

## 6. 환경 설정

**의존성 설치**

```bash
pip install beautifulsoup4 lxml requests pandas psycopg2-binary \
            sqlalchemy boto3 python-dotenv chromadb \
            torch transformers openai pydantic
```

---

## 7. 실행 순서

```bash
# 0. 인프라 실행 (최초 1회 또는 재시작 시)
docker-compose up -d

# 1. DB 테이블 초기화 (최초 1회)
psql -h localhost -U postgres -d med_db -f src/infra/init_postresql.sql

# ── MSD 증상 데이터 ──────────────────────────────────────────

# 2. MSD 증상 목록 페이지 수동 저장
#    브라우저에서 MSD 증상 목록 페이지를 data/msd_source/symptoms.html로 저장

# 3. 증상 링크 수집 → MinIO bronze
python src/collector/msd_link_collector.py

# 4-A. MSD 파싱 (규칙 기반, 빠름) → PostgreSQL silver_symptom
python src/extractor/msd_save_to_silver.py

# 4-B. MSD 파싱 (AI 기반, 정밀, 선택) → CSV 저장
# python src/collector/msd_exctractor.py

# ── 공공데이터 약물 데이터 ───────────────────────────────────

# 5. 공공데이터 API 전체 수집 → MinIO bronze
python src/collector/api_ingestion.py

# 6. Bronze → Silver 정제 + 통합
python src/extractor/api_save_to_silver.py

# ── ChromaDB 구축 ─────────────────────────────────────────────

# 7. 기존 컬렉션 삭제 (재구축 시)
python -c "
import sys; sys.path.append('src/vectordb')
import create_vectordb
create_vectordb.client.delete_collection('medical_knowledge')
print('삭제 완료')
"

# 8. 벡터 DB 구축
python src/vectordb/vectorizer.py

# 9. 검색 테스트
python src/vectordb/test_vectordb.py
```

---

## 8. 출력 예시

### `api_ingestion.py` 실행 결과

```
[*] Starting full ingestion: drug_info
    -> Progress: Page 1/423 (100/42300 items collected)
    -> Progress: Page 2/423 (200/42300 items collected)
    ...
[+] Successfully ingested ALL 42300 records for drug_info
```

### `api_save_to_silver.py` 실행 결과

```
[*] Processing: drug_info/20250531_120000.json
[*] drug_info/20250531_120000.json 파일에서 42300개의 아이템을 추출했습니다.
[*] 데이터 통합 시작
[+] silver_drug_integration 테이블 통합 완료.
```

### `vectorizer.py` 실행 결과

```
초기화 후 컬렉션 count: 0
[매핑 청크 생성] 1842건
총 청크 수: 4721
Drug chunk 수: 2134
Symptom chunk 수: 745
Vector DB 적재 시작... (총 4721건, 배치 크기: 16)
  -> [16/4721] 적재 진행 중...
  ...
--- Vector DB 적재 완료 ---
최종 DB 개수: 4721건
```

### `test_vectordb.py` 검색 결과 (정상 케이스)

```
===== vectorDB test =====
질문: 두통

===== 검색 결과 =====
순위: 1
ID: MAP_S012_200502128
거리: 0.08
메타데이터: {'chunk_type': 'symptom_drug_map', 'symptom_name': '두통', 'drug_name': '다아펜정', 'is_red_flag': False, ...}
내용:
[증상-약 매핑] 증상: 두통 → 추천 약물: 다아펜정
적응증: 이 약은 두통, 치통, 관절통, 신경통에 사용합니다.
--------------------------------------------------
```

**distance 판단 기준**

| distance 범위 | 판단 |
|---|---|
| 0.0 ~ 0.3 | 매우 관련 있음 |
| 0.3 ~ 0.6 | 관련 있음 |
| 0.6 ~ 1.0 | 약하게 관련 |
| 1.0 이상 | 관련 없음, 필터링 권장 |

---

## 9. RAG 파트 연동 가이드

### ChromaDB 컬렉션 접근

```python
import sys
sys.path.append('src/vectordb')

import chromadb
import create_vectordb

client = chromadb.HttpClient(host='localhost', port=8000)
collection = client.get_collection(
    name="medical_knowledge",
    embedding_function=create_vectordb.e5_embedding_function
)
```

### 약 추천 목적별 검색 전략

RAG 파트의 `retriever.py`에서 아래 단계 순서로 `chunk_type`을 필터링해 검색해야 합니다.

**1단계 — 응급 여부 확인** (is_red_flag 우선 처리)
```python
results = collection.query(
    query_texts=[f"query: {user_query}"],
    n_results=3,
    where={"$and": [
        {"chunk_type": {"$eq": "warning"}},
        {"is_red_flag": {"$eq": True}}
    ]}
)
# distance < 0.3이면 "즉시 병원 방문" 응답으로 분기, 약 추천 생략
```

**2단계 — 약 추천**
```python
results = collection.query(
    query_texts=[f"query: {user_query}"],
    n_results=5,
    where={"$and": [
        {"chunk_type": {"$eq": "symptom_drug_map"}},
        {"is_red_flag": {"$eq": False}}
    ]}
)
```

**3단계 — 병용금기 확인**
```python
results = collection.query(
    query_texts=[f"query: {drug_name} 병용금기"],
    n_results=5,
    where={"$and": [
        {"chunk_type": {"$eq": "contra"}},
        {"data_type": {"$eq": "drug"}}
    ]}
)
# contra_raw 메타데이터로 exact match 후처리 권장
for meta in results['metadatas'][0]:
    if target_drug in meta.get('contra_raw', ''):
        # 병용금기 확인됨
        pass
```

**4단계 — 복약 안내**
```python
results = collection.query(
    query_texts=[f"query: {drug_name} 복약"],
    n_results=1,
    where={"$and": [
        {"chunk_type": {"$eq": "dosage"}},
        {"entity_name": {"$eq": drug_name}}
    ]}
)
```

### 메타데이터 필드 참조표

| 필드 | 타입 | 존재하는 청크 | 설명 |
|---|---|---|---|
| `data_type` | str | 전체 | `symptom` / `drug` / `mapping` |
| `chunk_type` | str | 전체 | `cause` / `warning` / `action` / `pre_exist` / `indications` / `contra` / `dosage` / `symptom_drug_map` |
| `entity_id` | str | symptom, drug | `S001` / `200502128` 형태 |
| `entity_name` | str | symptom, drug | 증상명 또는 약물명 |
| `is_red_flag` | bool | symptom, mapping | 응급 여부 |
| `category` | str | symptom | 증상 카테고리 |
| `contra_raw` | str | drug(contra) | 병용금기 약물 원본 문자열 |
| `symptom_id` | str | mapping | 매핑된 증상 ID |
| `symptom_name` | str | mapping | 매핑된 증상명 |
| `drug_id` | str | mapping | 매핑된 약물 ID |
| `drug_name` | str | mapping | 매핑된 약물명 |

---

## 10. 알려진 이슈 및 주의사항

**증상-약 매핑 청크 생성 실패**
`silver_symptom.name`이 `두통 (頭痛, headache)` 형태인 경우, `build_symptom_drug_mapping_chunks()`에서 괄호를 제거한 핵심어(`두통`)가 약물 `indications` 텍스트에 포함되어야 매핑됩니다. 매핑 청크가 적게 생성될 경우 아래 SQL로 원인을 확인하세요.

```sql
-- 증상명 형태 확인
SELECT symptom_id, name FROM silver_symptom LIMIT 10;

-- 특정 증상의 매핑 여부 확인
SELECT COUNT(*) FROM silver_drug_integration
WHERE indications LIKE '%두통%';
```

**`api_ingestion.py` API 키 분리**
`API_KEY_1`(e약은요)과 `API_KEY_2`(DUR)를 `.env`에서 별도로 관리합니다. 현재 DUR 수집은 주석 처리되어 있으니, 활성화 시 `API_KEY_2`를 설정해야 합니다.

**`silver_drug_integration`은 뷰(View)**
`api_save_to_silver.py`의 `integrate_to_final()`은 실제로는 테이블에 INSERT하는 로직으로 작성되어 있습니다. `init_postresql.sql`의 뷰 방식과 충돌하므로, 둘 중 하나로 통일이 필요합니다.

- 뷰 방식: `init_postresql.sql`의 `CREATE OR REPLACE VIEW silver_drug_integration` 유지, `integrate_to_final()` 제거
- 테이블 방식: DDL을 테이블로 교체, `integrate_to_final()`의 INSERT 쿼리 컬럼명 정합성 확인

**`sys.path` 설정**
`vectorizer.py`와 `test_vectordb.py`는 `create_vectordb`와 `set_client`를 같은 경로에서 import합니다. 각 폴더에서 실행 시 경로 문제가 발생할 수 있으므로, 프로젝트 루트에서 실행하거나 `PYTHONPATH`를 설정하세요.

```bash
# 루트에서 실행
PYTHONPATH=src/infra:src/vectordb python src/vectordb/vectorizer.py
```