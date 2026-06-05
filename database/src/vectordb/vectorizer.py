"""PostgreSQL Silver 데이터 → ChromaDB 청크 적재.

실행 (DE 루트):
    python src/vectordb/vectorizer.py
"""

from __future__ import annotations

import os
import re
import sys
import traceback
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import bootstrap  # noqa: E402
import numpy as np
import pandas as pd
from sqlalchemy import create_engine


def _db_engine():
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    name = os.getenv("DB_NAME", "med_db")
    user = os.getenv("DB_USER", "postgres")
    password = os.getenv("DB_PASSWORD", "")
    return create_engine(
        f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}"
    )


def _normalize_drug_df(df: pd.DataFrame) -> pd.DataFrame:
    """구 스키마/뷰 컬럼명 차이를 통일합니다."""
    aliases = {
        "name": "name_ko",
        "efficacy": "indications",
        "usage": "dosage",
        "cautions": "warnings",
        "company": "entp_name",
    }
    for old, new in aliases.items():
        if old in df.columns and new not in df.columns:
            df[new] = df[old]
    return df


def get_drug_data() -> pd.DataFrame:
    try:
        engine = _db_engine()
        df = pd.read_sql("SELECT * FROM silver_drug_integration", engine)
        df = _normalize_drug_df(df)

        # 통합 뷰/테이블에 텍스트가 비어 있으면 silver_drug_info로 대체
        if not df.empty:
            ind = df.get("indications")
            if ind is None or ind.fillna("").astype(str).str.strip().eq("").all():
                print(
                    "[!] silver_drug_integration 적응증 비어 있음 → silver_drug_info 사용",
                    flush=True,
                )
                df = pd.read_sql("SELECT * FROM silver_drug_info", engine)
                df = _normalize_drug_df(df)

        print(f"[+] 약물 데이터: {len(df)}건", flush=True)
        if not df.empty:
            sample = df.iloc[0]
            print(
                f"    샘플 약물: {sample.get('name_ko')} / "
                f"적응증={str(sample.get('indications') or '')[:40]}",
                flush=True,
            )
        return df
    except Exception as e:
        print(f"[!] DB 연결 및 쿼리 실패 (drug): {e}", flush=True)
        return pd.DataFrame()


def get_symptom_data() -> pd.DataFrame:
    try:
        df = pd.read_sql("SELECT * FROM silver_symptom", _db_engine())
        print(f"[+] silver_symptom: {len(df)}건", flush=True)
        return df
    except Exception as e:
        print(f"[!] DB 연결 및 쿼리 실패 (symptom): {e}", flush=True)
        return pd.DataFrame()


def clean_text(value):
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        value = ", ".join(map(str, value))
    elif isinstance(value, dict):
        value = str(value)
    elif isinstance(value, np.ndarray):
        value = ", ".join(map(str, value.tolist()))
    elif pd.isna(value):
        return ""
    value = str(value).strip()
    if value.lower() in ["nan", "none", "null", "[]", "{}"]:
        return ""
    return value


def build_symptom_chunks(row) -> list[dict]:
    name = clean_text(row.get("name"))
    cause = clean_text(row.get("cause"))
    warning = clean_text(row.get("warning_sign"))
    meet_doc = clean_text(row.get("meet_doc"))
    action_guide = clean_text(row.get("action_guide"))
    pre_exist = clean_text(row.get("pre_exist_condition"))
    category = clean_text(row.get("category", ""))
    is_red_flag = bool(row.get("is_red_flag", False))
    chunks = []

    if cause:
        chunks.append({
            "chunk_type": "cause",
            "text": f"[증상] {name} ({category})\n원인: {cause}",
            "metadata": {
                "data_type": "symptom",
                "chunk_type": "cause",
                "entity_id": row["symptom_id"],
                "entity_name": name,
                "category": category,
                "is_red_flag": is_red_flag,
            },
        })

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
                "entity_id": row["symptom_id"],
                "entity_name": name,
                "category": category,
                "is_red_flag": is_red_flag,
            },
        })

    guide_text = action_guide or meet_doc
    if guide_text:
        chunks.append({
            "chunk_type": "action",
            "text": f"[대응] {name} 행동 가이드\n{guide_text}",
            "metadata": {
                "data_type": "symptom",
                "chunk_type": "action",
                "entity_id": row["symptom_id"],
                "entity_name": name,
                "category": category,
                "is_red_flag": is_red_flag,
            },
        })

    if pre_exist and len(pre_exist) >= 30:
        chunks.append({
            "chunk_type": "pre_exist",
            "text": f"[기저질환] {name}과 관련된 기저질환 및 배경:\n{pre_exist}",
            "metadata": {
                "data_type": "symptom",
                "chunk_type": "pre_exist",
                "entity_id": row["symptom_id"],
                "entity_name": name,
                "category": category,
                "is_red_flag": is_red_flag,
            },
        })

    return chunks


def build_drug_chunks(row) -> list[dict]:
    name = clean_text(row.get("name_ko"))
    dosage = clean_text(row.get("dosage"))
    indications = clean_text(row.get("indications"))
    warnings = clean_text(row.get("warnings"))
    ingredient = clean_text(row.get("ingredient"))
    contra = clean_text(row.get("combination_contraindication"))
    chunks = []
    min_len = 10

    if indications and len(indications) >= min_len:
        chunks.append({
            "chunk_type": "indications",
            "text": f"[약물 효능] {name}\n적응증: {indications}",
            "metadata": {
                "data_type": "drug",
                "chunk_type": "indications",
                "entity_id": str(row["drug_id"]),
                "entity_name": name,
            },
        })

    if warnings and len(warnings) >= min_len:
        chunks.append({
            "chunk_type": "warning",
            "text": f"[약물 주의] {name}\n주의사항: {warnings}",
            "metadata": {
                "data_type": "drug",
                "chunk_type": "warning",
                "entity_id": str(row["drug_id"]),
                "entity_name": name,
            },
        })

    if contra:
        chunks.append({
            "chunk_type": "contra",
            "text": f"[병용금기] {name}\n함께 복용하면 안 되는 약물: {contra}",
            "metadata": {
                "data_type": "drug",
                "chunk_type": "contra",
                "entity_id": str(row["drug_id"]),
                "entity_name": name,
                "contra_raw": str(row.get("combination_contraindication", "")),
            },
        })

    dosage_parts = []
    if dosage and len(dosage) >= min_len:
        dosage_parts.append(f"용법·용량: {dosage}")
    if ingredient and len(ingredient) >= min_len:
        dosage_parts.append(f"주성분: {ingredient}")
    if dosage_parts:
        chunks.append({
            "chunk_type": "dosage",
            "text": f"[복약 안내] {name}\n" + "\n".join(dosage_parts),
            "metadata": {
                "data_type": "drug",
                "chunk_type": "dosage",
                "entity_id": str(row["drug_id"]),
                "entity_name": name,
            },
        })

    return chunks


def build_symptom_drug_mapping_chunks(symptom_df, drug_df) -> list[dict]:
    symptom_df = symptom_df.drop_duplicates(subset=["name"])
    symptom_rows: list[tuple[str, str, str, bool]] = []
    for _, symptom in symptom_df.iterrows():
        symptom_name = clean_text(symptom.get("name"))
        if not symptom_name:
            continue
        symptom_core = re.sub(r"\(.*?\)", "", symptom_name).strip()
        if not symptom_core or len(symptom_core) < 2:
            continue
        symptom_rows.append(
            (
                str(symptom["symptom_id"]),
                symptom_core,
                symptom_name,
                bool(symptom.get("is_red_flag", False)),
            )
        )

    chunks = []
    seen_ids: set[str] = set()
    max_maps = int(os.getenv("VECTOR_MAX_MAPPING_CHUNKS", "50000"))

    for _, drug in drug_df.iterrows():
        drug_name = clean_text(drug.get("name_ko"))
        indications = clean_text(drug.get("indications"))
        if not indications or len(indications) < 8:
            continue

        for symptom_id, symptom_core, _, is_red_flag in symptom_rows:
            if symptom_core not in indications:
                continue

            chunk_id = f"MAP_{symptom_id}_{drug['drug_id']}"
            if chunk_id in seen_ids:
                continue
            seen_ids.add(chunk_id)

            chunks.append({
                "id": chunk_id,
                "text": (
                    f"[증상-약 매핑] "
                    f"증상: {symptom_core} → 추천 약물: {drug_name}\n"
                    f"적응증: {indications}"
                ),
                "metadata": {
                    "data_type": "mapping",
                    "chunk_type": "symptom_drug_map",
                    "symptom_id": symptom_id,
                    "symptom_name": symptom_core,
                    "drug_id": str(drug["drug_id"]),
                    "drug_name": drug_name,
                    "is_red_flag": is_red_flag,
                },
            })
            if len(chunks) >= max_maps:
                print(
                    f"[!] 매핑 청크 상한 도달 ({max_maps}). "
                    "VECTOR_MAX_MAPPING_CHUNKS 로 조절 가능",
                    flush=True,
                )
                print(f"[매핑 청크 생성] {len(chunks)}건", flush=True)
                return chunks

    print(f"[매핑 청크 생성] {len(chunks)}건", flush=True)
    return chunks


def integrate_data() -> dict:
    drug_chunk_count = 0
    symptom_chunk_count = 0

    drug_df = get_drug_data()
    symptom_df = get_symptom_data()

    ids, docs, metadatas = [], [], []

    for _, row in symptom_df.iterrows():
        for chunk in build_symptom_chunks(row):
            ids.append(f"SYM_{row['symptom_id']}_{chunk['chunk_type']}")
            docs.append(chunk["text"])
            metadatas.append(chunk["metadata"])
            symptom_chunk_count += 1

    for _, row in drug_df.iterrows():
        for chunk in build_drug_chunks(row):
            ids.append(f"DRUG_{row['drug_id']}_{chunk['chunk_type']}")
            docs.append(chunk["text"])
            metadatas.append(chunk["metadata"])
            drug_chunk_count += 1

    for chunk in build_symptom_drug_mapping_chunks(symptom_df, drug_df):
        ids.append(chunk["id"])
        docs.append(chunk["text"])
        metadatas.append(chunk["metadata"])

    print(f"총 청크 수: {len(ids)}", flush=True)
    print(f"Drug chunk 수: {drug_chunk_count}", flush=True)
    print(f"Symptom chunk 수: {symptom_chunk_count}", flush=True)
    return {"ids": ids, "documents": docs, "metadatas": metadatas}


def load_to_vector_db(ids, docs, metadatas, batch_size: int | None = None) -> None:
    if batch_size is None:
        batch_size = int(os.getenv("VECTOR_BATCH_SIZE", "32"))
    import create_vectordb

    try:
        collection = create_vectordb.init_collection()
        print(f"초기화 후 컬렉션 count: {collection.count()}", flush=True)
        total_size = len(ids)
        print(
            f"Vector DB 적재 시작... (총 {total_size}건, 배치 크기: {batch_size})",
            flush=True,
        )

        for i in range(0, total_size, batch_size):
            batch_ids = ids[i : i + batch_size]
            batch_docs = docs[i : i + batch_size]
            batch_metas = metadatas[i : i + batch_size]
            collection.upsert(
                ids=batch_ids,
                documents=batch_docs,
                metadatas=batch_metas,
            )
            print(
                f"  -> [{i + len(batch_ids)}/{total_size}] 적재 진행 중...",
                flush=True,
            )

        print("--- Vector DB 적재 완료 ---", flush=True)
        print(f"최종 DB 개수: {collection.count()}건", flush=True)
    except Exception as e:
        print(f"[!] ChromaDB 적재 중 오류 발생: {e}", flush=True)
        traceback.print_exc()


def main() -> None:
    print("[*] vectorizer.py 시작", flush=True)
    processed_data = integrate_data()

    if processed_data["ids"]:
        load_to_vector_db(
            ids=processed_data["ids"],
            docs=processed_data["documents"],
            metadatas=processed_data["metadatas"],
        )
    else:
        print(
            "[!] 생성된 청크가 없습니다. "
            "먼저 `python src/extractor/seed_dev_data.py`를 실행했는지 확인하세요.",
            flush=True,
        )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
