"""PostgreSQL Silver → AI 파트 data/*.json 동기화.

vectorizer 이후 AI 규칙 기반 검색이 전체 카탈로그를 사용할 수 있게 합니다.

실행 (DE 루트):
    python src/extractor/export_silver_to_ai.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import bootstrap  # noqa: E402
import pandas as pd
from paths import AI_DRUGS_JSON, AI_SYMPTOMS_JSON, PROJECT_ROOT
from sqlalchemy import create_engine

import os


def _db_engine():
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    name = os.getenv("DB_NAME", "med_db")
    user = os.getenv("DB_USER", "postgres")
    password = os.getenv("DB_PASSWORD", "")
    return create_engine(
        f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}"
    )


def _split_ingredient(text: str) -> list[str]:
    if not text:
        return []
    parts = re.split(r"[,;/]| 및 ", text)
    return [p.strip() for p in parts if p.strip()]


def _split_contra(text: str) -> list[str]:
    if not text:
        return []
    return [p.strip() for p in re.split(r"[,;]", text) if p.strip()]


def _symptom_core(name: str) -> str:
    return re.sub(r"\(.*?\)", "", (name or "")).strip()


def _extract_treats(indications: str, symptom_names: list[str]) -> list[str]:
    treats: list[str] = []
    text = indications or ""
    for name in symptom_names:
        core = _symptom_core(name)
        if core and core in text and core not in treats:
            treats.append(core)
    return treats


def _build_drug_record(row, symptom_names: list[str]) -> dict:
    drug_id = str(row.get("drug_id", "")).strip()
    name = str(row.get("name_ko") or "").strip()
    indications = str(row.get("indications") or "").strip()
    dosage = str(row.get("dosage") or "").strip()
    warnings = str(row.get("warnings") or "").strip()
    ingredient = _split_ingredient(str(row.get("ingredient") or ""))
    contra = _split_contra(str(row.get("combination_contraindication") or ""))
    treats = _extract_treats(indications, symptom_names)

    parent_text = (
        f"{name}. 성분: {', '.join(ingredient) or '미상'}. "
        f"효능: {indications}. 복용법: {dosage}. 주의사항: {warnings}."
    )

    child_chunks: list[dict] = []
    if indications:
        child_chunks.append({
            "chunk_type": "indication",
            "text": f"{indications}에 사용된다.",
            "metadata": {"treats": treats},
        })
    if dosage:
        child_chunks.append({
            "chunk_type": "dosage",
            "text": dosage,
            "metadata": {"age_group": ["adult"]},
        })
    if warnings:
        child_chunks.append({
            "chunk_type": "warning",
            "text": warnings,
            "metadata": {"forbidden_conditions": [], "severity": "medium"},
        })

    return {
        "drug_id": drug_id,
        "name_ko": name,
        "name_en": None,
        "ingredient": ingredient,
        "indications": indications,
        "dosage": dosage,
        "warnings": warnings,
        "category": row.get("class_name"),
        "updated_date": None,
        "combination_contraindication": contra,
        "parent_text": parent_text,
        "child_chunks": child_chunks,
    }


def export_drugs(engine, symptom_names: list[str]) -> list[dict]:
    df = pd.read_sql(
        """
        SELECT drug_id, name_ko, class_name, ingredient, indications,
               dosage, warnings, combination_contraindication
        FROM silver_drug_integration
        WHERE name_ko IS NOT NULL AND TRIM(name_ko) <> ''
        ORDER BY drug_id
        """,
        engine,
    )
    records = [_build_drug_record(row, symptom_names) for _, row in df.iterrows()]
    print(f"[+] 약물 export: {len(records)}건", flush=True)
    return records


def export_symptoms(engine) -> list[dict]:
    df = pd.read_sql(
        """
        SELECT symptom_id, name, is_red_flag, action_guide, warning_sign
        FROM silver_symptom
        WHERE name IS NOT NULL AND TRIM(name) <> ''
        ORDER BY symptom_id
        """,
        engine,
    )
    records: list[dict] = []
    for _, row in df.iterrows():
        core = _symptom_core(str(row.get("name") or ""))
        records.append({
            "symptom_id": row["symptom_id"],
            "name": core or row["name"],
            "is_red_flag": bool(row.get("is_red_flag")),
            "urgency": None,
            "context": row.get("warning_sign"),
            "action_guide": row.get("action_guide"),
        })
    print(f"[+] 증상 export: {len(records)}건", flush=True)
    return records


def _save_json(path: Path, data: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = path.with_suffix(path.suffix + ".bak")
    if path.exists():
        path.replace(backup)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[+] 저장: {path}", flush=True)


def main() -> None:
    engine = _db_engine()
    symptoms = export_symptoms(engine)
    symptom_names = [s["name"] for s in symptoms]
    drugs = export_drugs(engine, symptom_names)

    if not drugs:
        raise RuntimeError(
            "export할 약물이 없습니다. api_ingestion → api_save_to_silver 를 먼저 실행하세요."
        )

    _save_json(AI_DRUGS_JSON, drugs)
    _save_json(AI_SYMPTOMS_JSON, symptoms)
    print(f"[+] AI 데이터 동기화 완료 ({PROJECT_ROOT / 'data'})", flush=True)


if __name__ == "__main__":
    main()
