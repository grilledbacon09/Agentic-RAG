import pandas as pd
import psycopg2
import json
import set_client
import re
import os
from dotenv import load_dotenv
import chromadb
from chromadb.config import Settings
import create_vectordb
from sqlalchemy import create_engine
import numpy as np


load_dotenv()

# --- 1. DB에서 약 정보 가져오기 (psycopg2 사용) ---

def get_drug_data():
    conn_params = {
        "host": "localhost",
        "database": "med_db",
        "user": os.getenv('DB_USER'),
        "password": os.getenv('DB_PASSWORD'),
        "port": "5432"
    }
    try:
        engine = create_engine(
            f"postgresql+psycopg2://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
            f"@localhost:5432/med_db"
        )
        df = pd.read_sql("SELECT * FROM silver_drug_integration", engine)
        return df
    except Exception as e:
        print(f"DB 연결 및 쿼리 실패: {e}")
        return pd.DataFrame()

# 2. MinIO에서 증상 정보 가져오기
def get_symptom_data():
    conn_params = {
        "host": "localhost",
        "database": "med_db",
        "user": os.getenv('DB_USER'),
        "password": os.getenv('DB_PASSWORD'),
        "port": "5432"
    }
    try:
        engine = create_engine(
            f"postgresql+psycopg2://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
            f"@localhost:5432/med_db"
        )
        df = pd.read_sql("SELECT * FROM silver_symptom", engine)
        return df
    except Exception as e:
        print(f"DB 연결 및 쿼리 실패: {e}")
        return pd.DataFrame()

def clean_text(value):
    """
    NaN / None / 빈 문자열 방지용 함수
    """

     # None 처리
    if value is None:
        return ""

    # list / tuple / set 처리
    if isinstance(value, (list, tuple, set)):
        value = ", ".join(map(str, value))

    # dict 처리
    elif isinstance(value, dict):
        value = str(value)

    # numpy array 처리
    elif isinstance(value, np.ndarray):
        value = ", ".join(map(str, value.tolist()))

    # NaN 처리
    elif pd.isna(value):
        return ""

    value = str(value).strip()

    if value.lower() in ["nan", "none", "null", "[]", "{}"]:
        return ""

    return value

# --- 3. 데이터 chunking 프로세스 ---
def build_symptom_chunks(row) -> list[tuple]:
    name = clean_text(row.get('name'))
    cause = clean_text(row.get('cause'))
    warning = clean_text(row.get('warning_sign'))
    meet_doc = clean_text(row.get('meet_doc'))
    action_guide = clean_text(row.get('action_guide'))  # ← 버그 수정
    pre_exist = clean_text(row.get('pre_exist_condition'))
    category = clean_text(row.get('category', ''))
    is_red_flag = bool(row.get('is_red_flag', False))

    chunks = []

    # ① 진단 탐색 청크 — "이런 증상이 왜 생기나?" 질문에 대응
    if cause:
        chunks.append({
            "chunk_type": "cause",
            "text": f"[증상] {name} ({category})\n원인: {cause}",
            "metadata": {
                "data_type": "symptom",
                "chunk_type": "cause",
                "entity_id": row['symptom_id'],
                "entity_name": name,
                "category": category,
                "is_red_flag": is_red_flag,
            }
        })

    # ② 응급 판단 청크 — "지금 병원 가야 하나?" 질문에 대응
    # warning + meet_doc을 하나로 묶어 맥락 보강
    if warning or meet_doc:
        parts = []
        if warning:
            parts.append(f"경고징후: {warning}")
        if meet_doc:
            parts.append(f"병원 방문 기준: {meet_doc}")
        red_flag_prefix = "[긴급]" if is_red_flag else "[참고]"
        chunks.append({
            "chunk_type": "warning",
            "text": f"{red_flag_prefix} {name} 응급 판단\n" + "\n".join(parts),
            "metadata": {
                "data_type": "symptom",
                "chunk_type": "warning",
                "entity_id": row['symptom_id'],
                "entity_name": name,
                "category": category,
                "is_red_flag": is_red_flag,
            }
        })

    # ③ 행동 안내 청크 — "어떻게 해야 하나?" 질문에 대응
    # action_guide가 없으면 meet_doc으로 fallback
    guide_text = action_guide or meet_doc
    if guide_text:
        chunks.append({
            "chunk_type": "action",
            "text": f"[대응] {name} 행동 가이드\n{guide_text}",
            "metadata": {
                "data_type": "symptom",
                "chunk_type": "action",
                "entity_id": row['symptom_id'],
                "entity_name": name,
                "category": category,
                "is_red_flag": is_red_flag,
            }
        })

    # ④ 기저질환 청크 — "이 증상과 관련된 질환이 뭔가?" 질문에 대응
    if pre_exist and len(pre_exist) >= 30:
        chunks.append({
            "chunk_type": "pre_exist",
            "text": f"[기저질환] {name}과 관련된 기저질환 및 배경:\n{pre_exist}",
            "metadata": {
                "data_type": "symptom",
                "chunk_type": "pre_exist",
                "entity_id": row['symptom_id'],
                "entity_name": name,
                "category": category,
                "is_red_flag": is_red_flag,
            }
        })

    return chunks

def build_drug_chunks(row) -> list[tuple]:
    name = clean_text(row.get('name_ko'))
    dosage = clean_text(row.get('dosage'))
    indications = clean_text(row.get('indications'))
    warnings = clean_text(row.get('warnings'))
    ingredient = clean_text(row.get('ingredient'))
    contra = clean_text(row.get('combination_contraindication'))

    chunks = []
    MIN_LEN = 30

    # ⑤ 효능/적응증 청크
    if indications and len(indications) >= MIN_LEN:
        chunks.append({
            "chunk_type": "indications",
            "text": f"[약물 효능] {name}\n적응증: {indications}",
            "metadata": {
                "data_type": "drug",
                "chunk_type": "indications",
                "entity_id": str(row['drug_id']),
                "entity_name": name,
            }
        })

    # ⑥ 주의사항 청크 — warnings만 포함, chunk_type은 "warning"으로 통일
    if warnings and len(warnings) >= MIN_LEN:
        chunks.append({
            "chunk_type": "warning",
            "text": f"[약물 주의] {name}\n주의사항: {warnings}",
            "metadata": {
                "data_type": "drug",
                "chunk_type": "warning",
                "entity_id": str(row['drug_id']),
                "entity_name": name,
            }
        })

    # ⑦ 병용금기 청크 — 독립 분리 (향후 병용금기 기능에서 필터로 활용)
    if contra:
        chunks.append({
            "chunk_type": "contra",
            "text": f"[병용금기] {name}\n함께 복용하면 안 되는 약물: {contra}",
            "metadata": {
                "data_type": "drug",
                "chunk_type": "contra",
                "entity_id": str(row['drug_id']),
                "entity_name": name,
                # 병용금기 약물명 원본 보존 — 향후 exact match 필터에 활용
                "contra_raw": str(row.get('combination_contraindication', '')),
            }
        })

    # ⑧ 용법/용량 청크
    dosage_parts = []
    if dosage and len(dosage) >= MIN_LEN:
        dosage_parts.append(f"용법·용량: {dosage}")
    if ingredient and len(ingredient) >= MIN_LEN:
        dosage_parts.append(f"주성분: {ingredient}")
    if dosage_parts:
        chunks.append({
            "chunk_type": "dosage",
            "text": f"[복약 안내] {name}\n" + "\n".join(dosage_parts),
            "metadata": {
                "data_type": "drug",
                "chunk_type": "dosage",
                "entity_id": str(row['drug_id']),
                "entity_name": name,
            }
        })

    return chunks

# vectorizer.py에 추가

def build_symptom_drug_mapping_chunks(symptom_df, drug_df) -> list[dict]:
    """
    증상의 indications 텍스트와 약물의 indications를 매칭해
    증상-약 연결 청크를 생성합니다.
    """
    symptom_df = symptom_df.drop_duplicates(subset=['name'])
    chunks = []
    seen_ids = set()  # 중복 청크 방지

    for _, drug in drug_df.iterrows():
        drug_name = clean_text(drug.get('name_ko'))
        indications = clean_text(drug.get('indications'))
        if not indications or len(indications) < 30:
            continue

        for _, symptom in symptom_df.iterrows():
            symptom_name = clean_text(symptom.get('name'))
            if not symptom_name:
                continue

            # 증상명에서 괄호 제거 후 핵심어만 추출해서 비교
            symptom_core = re.sub(r'\(.*?\)', '', symptom_name).strip()
            if not symptom_core or symptom_core not in indications:
                continue

            chunk_id = f"MAP_{symptom['symptom_id']}_{drug['drug_id']}"
            if chunk_id in seen_ids:  # 중복 방지
                continue
            seen_ids.add(chunk_id)

            # 청크 텍스트에 증상 정보를 풍부하게 포함
            chunk_text = (
                f"[증상-약 매핑] "
                f"증상: {symptom_core} → 추천 약물: {drug_name}\n"
                f"적응증: {indications}"
            )
            chunks.append({
                "id": chunk_id,
                "text": chunk_text,
                "metadata": {
                    "data_type": "mapping",
                    "chunk_type": "symptom_drug_map",
                    "symptom_id": symptom['symptom_id'],
                    "symptom_name": symptom_core,
                    "drug_id": str(drug['drug_id']),
                    "drug_name": drug_name,
                    "is_red_flag": bool(symptom.get('is_red_flag', False)),
                }
            })

    print(f"[매핑 청크 생성] {len(chunks)}건")
    return chunks


# --- 4. 데이터 통합 프로세스 ---
def integrate_data():
    
    drug_chunk_count = 0
    symptom_chunk_count = 0
    
    drug_df = get_drug_data()
    symptom_df = get_symptom_data()
    

    ids, docs, metadatas = [], [], []

    for _, row in symptom_df.iterrows():
        for chunk in build_symptom_chunks(row):
            chunk_id = f"SYM_{row['symptom_id']}_{chunk['chunk_type']}"
            ids.append(chunk_id)
            docs.append(chunk["text"])
            metadatas.append(chunk["metadata"])
            
            symptom_chunk_count += 1
            

    for _, row in drug_df.iterrows():
        for chunk in build_drug_chunks(row):
            chunk_id = f"DRUG_{row['drug_id']}_{chunk['chunk_type']}"
            ids.append(chunk_id)
            docs.append(chunk["text"])
            metadatas.append(chunk["metadata"])
            
            drug_chunk_count += 1
    
    # 증상-약 매핑 청크
    mapping_chunks = build_symptom_drug_mapping_chunks(symptom_df, drug_df)
    for chunk in mapping_chunks:
        ids.append(chunk["id"])
        docs.append(chunk["text"])
        metadatas.append(chunk["metadata"])

    print(f"총 청크 수: {len(ids)}")
    print(f"Drug chunk 수: {drug_chunk_count}")
    print(f"Symptom chunk 수: {symptom_chunk_count}")
    return {"ids": ids, "documents": docs, "metadatas": metadatas}
    

# --- 4. ChromaDB 적재 함수 ---
def load_to_vector_db(ids, docs, metadatas, batch_size=16):
    try:
        collection = create_vectordb.init_collection()
        print("초기화 후 컬렉션 count:", collection.count())  # 반드시 0이 나와야 함
        total_size = len(ids)
        print(f"Vector DB 적재 시작... (총 {total_size}건, 배치 크기: {batch_size})")

        # 데이터를 batch_size만큼 나누어서 반복 처리
        for i in range(0, total_size, batch_size):
            batch_ids = ids[i : i + batch_size]
            batch_docs = docs[i : i + batch_size]
            batch_metas = metadatas[i : i + batch_size]
            
            collection.upsert(
                ids=batch_ids,
                documents=batch_docs,
                metadatas=batch_metas
            )
            print(f"  -> [{i + len(batch_ids)}/{total_size}] 적재 진행 중...")

        print("--- Vector DB 적재 완료 ---")
        print(f"최종 DB 개수: {collection.count()}건")

    except Exception as e:
        print(f"ChromaDB 적재 중 오류 발생: {e}")

# --- 5. 최종 실행 ---
if __name__ == "__main__":
    # 1. 데이터 통합 (Transformation)
    processed_data = integrate_data()
    
    # 2. 적재 (Loading)
    if processed_data["ids"]:
        # 이전에 만든 load_to_chroma 함수를 호출
        load_to_vector_db(
            ids=processed_data["ids"],
            docs=processed_data["documents"],
            metadatas=processed_data["metadatas"]
        )