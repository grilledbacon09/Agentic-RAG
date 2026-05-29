from __future__ import annotations

import html
import re
from typing import Any, Dict, List


def clean_text(text: Any) -> str:
    """API/MSD 원문 텍스트를 RAG용으로 정제한다."""

    if text is None:
        return ""
    value = html.unescape(str(text))
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    value = value.replace("ㆍ", ", ").replace("·", ", ")
    return value.strip()


def normalize_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        items = value
    else:
        items = re.split(r"[,;/|]", str(value))
    return [clean_text(item) for item in items if clean_text(item)]


def clean_drug_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """외부 데이터 row를 현재 Drug schema에 가깝게 정규화한다."""

    drug_id = clean_text(record.get("drug_id") or record.get("id") or record.get("itemSeq"))
    name_ko = clean_text(record.get("name_ko") or record.get("itemName") or record.get("name"))
    ingredient = normalize_list(record.get("ingredient") or record.get("efcyQesitm") or record.get("materialName"))
    indications = clean_text(record.get("indications") or record.get("efcyQesitm"))
    dosage = clean_text(record.get("dosage") or record.get("useMethodQesitm"))
    warnings = clean_text(record.get("warnings") or record.get("atpnQesitm") or record.get("warning"))
    category = clean_text(record.get("category") or record.get("className")) or None
    updated_date = clean_text(record.get("updated_date") or record.get("updateDe")) or None

    parent_text = clean_text(
        f"{name_ko}. 성분: {', '.join(ingredient)}. 효능: {indications}. 복용법: {dosage}. 주의사항: {warnings}."
    )

    return {
        "drug_id": drug_id,
        "name_ko": name_ko,
        "name_en": clean_text(record.get("name_en")) or None,
        "ingredient": ingredient,
        "indications": indications,
        "dosage": dosage,
        "warnings": warnings,
        "category": category,
        "updated_date": updated_date,
        "combination_contraindication": normalize_list(record.get("combination_contraindication")),
        "parent_text": parent_text,
        "child_chunks": record.get("child_chunks", []),
    }


def clean_symptom_record(record: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "symptom_id": clean_text(record.get("symptom_id") or record.get("id")),
        "name": clean_text(record.get("name") or record.get("symptom")),
        "is_red_flag": record.get("is_red_flag"),
        "urgency": clean_text(record.get("urgency")) or None,
        "context": clean_text(record.get("context")) or None,
        "action_guide": clean_text(record.get("action_guide") or record.get("guide")) or None,
    }
