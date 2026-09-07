"""
symptom dump에서 데이터 추출 후 id 제외하고 INSERT
로컬 실행: python scripts/import_symptom.py
"""
import os
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent.parent / "config" / ".env")

PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = os.getenv("PG_PORT", "5432")
PG_DB   = os.getenv("PG_DB", "drug_rag")
PG_USER = os.getenv("PG_USER", "airflow")
PG_PASS = os.getenv("PG_PASSWORD", "airflow")

conn = psycopg2.connect(
    host=PG_HOST, port=PG_PORT, dbname=PG_DB,
    user=PG_USER, password=PG_PASS
)
conn.autocommit = False

# 1. 기존 symptom 삭제
print("기존 symptom 삭제 중...")
with conn.cursor() as cur:
    cur.execute("DELETE FROM drug_documents WHERE doc_type IN ('symptom_info', 'symptom_redflag');")
    deleted = cur.rowcount
conn.commit()
print(f"삭제 완료: {deleted}건")

# 2. symptom dump DB에서 직접 읽기
#    → Colab DB dump를 로컬로 가져올 수 없으니
#      대신 S3 silver/refined/symptoms/ 에서 직접 적재

import boto3, json
from sentence_transformers import SentenceTransformer
import numpy as np

S3_BUCKET = "drug-rag-datalake-331145994962"
s3 = boto3.client("s3", region_name="ap-northeast-2")

print("임베딩 모델 로딩 중...")
model = SentenceTransformer("intfloat/multilingual-e5-large")
EMBED_DIM = model.get_sentence_embedding_dimension()
print(f"모델 로드 완료 / 차원: {EMBED_DIM}")

def list_keys(prefix):
    paginator = s3.get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(".json"):
                keys.append(obj["Key"])
    return keys

def download_json(key):
    res = s3.get_object(Bucket=S3_BUCKET, Key=key)
    return json.loads(res["Body"].read().decode("utf-8"))

from langchain_text_splitters import RecursiveCharacterTextSplitter

CHUNK_CONFIG = {
    "symptom_info":    {"size": 512, "overlap": 64},
    "symptom_redflag": {"size": 256, "overlap": 32},
}

def chunk_document(doc):
    doc_type = doc.get("doc_type", "symptom_info")
    cfg = CHUNK_CONFIG.get(doc_type, {"size": 512, "overlap": 64})
    text = doc.get("text", "")
    if not text:
        return []
    if doc_type == "symptom_redflag" or len(text) <= cfg["size"]:
        return [{"chunk_index": 0, "text": text}]
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=cfg["size"], chunk_overlap=cfg["overlap"], separators=["|", " ", ""]
    )
    return [{"chunk_index": i, "text": c} for i, c in enumerate(splitter.split_text(text))]

def upsert_chunks(docs, batch_size=32):
    rows = []
    seen = set()
    for doc in docs:
        chunks = chunk_document(doc)
        meta = doc.get("metadata", {})
        for chunk in chunks:
            doc_id = f"{doc['doc_id']}_c{chunk['chunk_index']}"
            if doc_id in seen:
                continue
            seen.add(doc_id)
            rows.append({
                "doc_id":       doc_id,
                "doc_type":     doc.get("doc_type", ""),
                "chunk_index":  chunk["chunk_index"],
                "text":         chunk["text"],
                "name":         meta.get("name", ""),
                "source_name":  meta.get("source_name", ""),
                "source_url":   meta.get("source_url", ""),
                "license":      meta.get("license", ""),
                "provider":     meta.get("provider", ""),
                "item_url":     meta.get("item_url", ""),
                "manufacturer": "",
                "image_url":    "",
                "dur_type":     "",
                "ingredient_a": "",
                "ingredient_b": "",
                "metadata":     json.dumps(meta, ensure_ascii=False),
            })
    if not rows:
        return 0

    # 기존 doc_id 스킵
    doc_ids = [r["doc_id"] for r in rows]
    with conn.cursor() as cur:
        cur.execute("SELECT doc_id FROM drug_documents WHERE doc_id = ANY(%s)", (doc_ids,))
        existing = {r[0] for r in cur.fetchall()}
    rows = [r for r in rows if r["doc_id"] not in existing]
    if not rows:
        return 0

    texts = [r["text"] for r in rows]
    passages = [f"passage: {t}" for t in texts]
    embeddings = model.encode(passages, batch_size=batch_size, normalize_embeddings=True)

    with conn.cursor() as cur:
        execute_values(cur, """
            INSERT INTO drug_documents (
                doc_id, doc_type, chunk_index, text, embedding,
                name, source_name, source_url, license, provider,
                item_url, manufacturer, image_url,
                dur_type, ingredient_a, ingredient_b, metadata
            ) VALUES %s
            ON CONFLICT (doc_id) DO NOTHING
        """, [
            (r["doc_id"], r["doc_type"], r["chunk_index"], r["text"],
             embeddings[i].tolist(),
             r["name"], r["source_name"], r["source_url"], r["license"], r["provider"],
             r["item_url"], r["manufacturer"], r["image_url"],
             r["dur_type"], r["ingredient_a"], r["ingredient_b"], r["metadata"])
            for i, r in enumerate(rows)
        ])
    conn.commit()
    return len(rows)

# 3. silver/refined/symptoms/ 적재
from tqdm import tqdm
prefix = "silver/refined/symptoms/"
keys = list_keys(prefix)
print(f"\n▶ {prefix} ({len(keys)}개 파일)")

total = 0
for key in tqdm(keys):
    try:
        data = download_json(key)
        items = data.get("items", [])
        for i in range(0, len(items), 100):
            total += upsert_chunks(items[i:i+100])
    except Exception as e:
        print(f"오류 {key}: {str(e)[:60]}")

print(f"\n✅ symptom 적재 완료: {total}건")

# 4. 결과 확인
with conn.cursor() as cur:
    cur.execute("SELECT doc_type, COUNT(*) FROM drug_documents WHERE doc_type LIKE 'symptom%' GROUP BY doc_type;")
    for row in cur.fetchall():
        print(f"  {row[0]:<25} {row[1]:>8,}건")

conn.close()
