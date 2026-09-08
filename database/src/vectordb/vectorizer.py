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


# ── 청크 분할 설정 ────────────────────────────────────────────────────
# MiniLM-L12-v2: max 128 tokens ≈ 한글 약 85자
# 여유를 두어 200자 기준으로 분할하고, 문맥 연속성을 위해 50자 overlap 유지
CHUNK_MAX_CHARS = int(os.getenv("CHUNK_MAX_CHARS", "200"))
CHUNK_OVERLAP_CHARS = int(os.getenv("CHUNK_OVERLAP_CHARS", "50"))

_SENT_SPLIT_RE = re.compile(r"(?<=[.!?다요음])\s+")


def _split_text(text: str) -> list[str]:
    """CHUNK_MAX_CHARS 초과 시 문장 단위로 분할하고 overlap 적용.

    짧으면 그대로 반환하므로 모든 필드에 무조건 적용 가능.
    """
    if len(text) <= CHUNK_MAX_CHARS:
        return [text]

    # 마침표/느낌표/물음표 뒤 공백, 또는 줄바꿈 기준 분리
    raw = _SENT_SPLIT_RE.split(text)
    sents = [s.strip() for s in re.split(r"\n", " ".join(raw)) if s.strip()]

    chunks: list[str] = []
    buf = ""
    for sent in sents:
        candidate = f"{buf} {sent}".strip() if buf else sent
        if len(candidate) <= CHUNK_MAX_CHARS:
            buf = candidate
        else:
            if buf:
                chunks.append(buf)
            # overlap: 이전 버퍼의 끝 CHUNK_OVERLAP_CHARS 자를 새 시작에 포함
            tail = buf[-CHUNK_OVERLAP_CHARS:] if len(buf) > CHUNK_OVERLAP_CHARS else buf
            buf = f"{tail} {sent}".strip() if tail else sent
            if len(buf) > CHUNK_MAX_CHARS:
                # 단일 문장이 한계를 초과하는 경우 강제 분할
                chunks.append(buf[:CHUNK_MAX_CHARS])
                buf = buf[CHUNK_MAX_CHARS - CHUNK_OVERLAP_CHARS:]
    if buf:
        chunks.append(buf)

    return chunks or [text[:CHUNK_MAX_CHARS]]


def build_symptom_chunks(row) -> list[dict]:
    name = clean_text(row.get("name"))
    cause = clean_text(row.get("cause"))
    warning = clean_text(row.get("warning_sign"))
    meet_doc = clean_text(row.get("meet_doc"))
    action_guide = clean_text(row.get("action_guide"))
    pre_exist = clean_text(row.get("pre_exist_condition"))
    category = clean_text(row.get("category", ""))
    is_red_flag = bool(row.get("is_red_flag", False))
    sym_id = row["symptom_id"]
    base_meta = {
        "data_type": "symptom",
        "entity_id": sym_id,
        "entity_name": name,
        "category": category,
        "is_red_flag": is_red_flag,
    }
    chunks = []

    # 원인 — 자연어 문장으로 변환 후 분할
    if cause:
        for i, seg in enumerate(_split_text(f"{name} 증상의 원인: {cause}")):
            chunks.append({
                "id": f"SYM_{sym_id}_cause_{i}",
                "chunk_type": "cause",
                "text": seg,
                "metadata": {**base_meta, "chunk_type": "cause", "seg": i},
            })

    # 경고 징후 / 병원 방문 기준
    if warning or meet_doc:
        parts = []
        if warning:
            parts.append(f"경고 징후: {warning}")
        if meet_doc:
            parts.append(f"병원 방문 기준: {meet_doc}")
        prefix = "긴급 " if is_red_flag else ""
        full_text = f"{prefix}{name} 응급 판단. " + " / ".join(parts)
        for i, seg in enumerate(_split_text(full_text)):
            chunks.append({
                "id": f"SYM_{sym_id}_warning_{i}",
                "chunk_type": "warning",
                "text": seg,
                "metadata": {**base_meta, "chunk_type": "warning", "seg": i},
            })

    # 대응 가이드
    guide_text = action_guide or meet_doc
    if guide_text:
        for i, seg in enumerate(_split_text(f"{name} 대응 방법: {guide_text}")):
            chunks.append({
                "id": f"SYM_{sym_id}_action_{i}",
                "chunk_type": "action",
                "text": seg,
                "metadata": {**base_meta, "chunk_type": "action", "seg": i},
            })

    # 기저질환
    if pre_exist and len(pre_exist) >= 30:
        for i, seg in enumerate(_split_text(f"{name} 관련 기저질환: {pre_exist}")):
            chunks.append({
                "id": f"SYM_{sym_id}_pre_exist_{i}",
                "chunk_type": "pre_exist",
                "text": seg,
                "metadata": {**base_meta, "chunk_type": "pre_exist", "seg": i},
            })

    return chunks


def build_drug_chunks(row) -> list[dict]:
    name = clean_text(row.get("name_ko"))
    dosage = clean_text(row.get("dosage"))
    indications = clean_text(row.get("indications"))
    warnings = clean_text(row.get("warnings"))
    ingredient = clean_text(row.get("ingredient"))
    contra = clean_text(row.get("combination_contraindication"))
    category = clean_text(row.get("class_name") or row.get("category") or "")
    drug_id = str(row["drug_id"])
    base_meta = {"data_type": "drug", "entity_id": drug_id, "entity_name": name}
    chunks = []
    min_len = 10

    # 요약 청크 — 짧고 핵심적: 약 이름 + 성분 + 분류 + 적응증 첫 60자
    # 검색 쿼리의 첫 번째 진입점 역할
    summary_parts = [name]
    if ingredient and len(ingredient) <= 40:
        summary_parts.append(f"({ingredient})")
    if category:
        summary_parts.append(category)
    if indications:
        summary_parts.append(indications[:60])
    chunks.append({
        "id": f"DRUG_{drug_id}_summary_0",
        "chunk_type": "summary",
        "text": " ".join(summary_parts),
        "metadata": {**base_meta, "chunk_type": "summary", "seg": 0},
    })

    # 적응증 — 자연어 문장 + 분할
    if indications and len(indications) >= min_len:
        for i, seg in enumerate(_split_text(f"{name}은(는) {indications}")):
            chunks.append({
                "id": f"DRUG_{drug_id}_indications_{i}",
                "chunk_type": "indications",
                "text": seg,
                "metadata": {**base_meta, "chunk_type": "indications", "seg": i},
            })

    # 주의사항 — 분할
    if warnings and len(warnings) >= min_len:
        for i, seg in enumerate(_split_text(f"{name} 복용 시 주의사항: {warnings}")):
            chunks.append({
                "id": f"DRUG_{drug_id}_warning_{i}",
                "chunk_type": "warning",
                "text": seg,
                "metadata": {**base_meta, "chunk_type": "warning", "seg": i},
            })

    # 병용금기 — 대체로 짧으므로 분할 없이
    if contra:
        chunks.append({
            "id": f"DRUG_{drug_id}_contra_0",
            "chunk_type": "contra",
            "text": f"{name}과 함께 복용하면 안 되는 약물: {contra}",
            "metadata": {
                **base_meta,
                "chunk_type": "contra",
                "seg": 0,
                "contra_raw": str(row.get("combination_contraindication", "")),
            },
        })

    # 복약 안내
    dosage_parts = []
    if dosage and len(dosage) >= min_len:
        dosage_parts.append(f"복용법: {dosage}")
    if ingredient and len(ingredient) >= min_len:
        dosage_parts.append(f"주성분: {ingredient}")
    if dosage_parts:
        for i, seg in enumerate(_split_text(f"{name} " + " / ".join(dosage_parts))):
            chunks.append({
                "id": f"DRUG_{drug_id}_dosage_{i}",
                "chunk_type": "dosage",
                "text": seg,
                "metadata": {**base_meta, "chunk_type": "dosage", "seg": i},
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

            # 짧고 자연스러운 문장 — 전체 적응증 대신 첫 80자만 사용
            # 임베딩 품질 우선: "두통 증상에 타이레놀을 사용할 수 있다"
            ind_brief = indications[:80] if len(indications) > 80 else indications
            chunks.append({
                "id": chunk_id,
                "text": f"{drug_name}은(는) {symptom_core} 증상에 사용할 수 있다. ({ind_brief})",
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
            ids.append(chunk["id"])
            docs.append(chunk["text"])
            metadatas.append(chunk["metadata"])
            symptom_chunk_count += 1

    for _, row in drug_df.iterrows():
        for chunk in build_drug_chunks(row):
            ids.append(chunk["id"])
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
