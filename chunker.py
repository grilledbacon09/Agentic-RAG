from __future__ import annotations

from typing import Any, Dict, List


def make_chunk(source_type: str, source_id: str, chunk_type: str, text: str, metadata: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return {
        "vector_id": f"{source_type}:{source_id}:{chunk_type}",
        "source_type": source_type,
        "source_id": source_id,
        "chunk_type": chunk_type,
        "content": text,
        "metadata": metadata or {},
    }


def chunk_drug_record(drug: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Drug record를 Vector DB 적재 가능한 chunk 리스트로 변환한다."""

    drug_id = drug.get("drug_id", "")
    chunks: List[Dict[str, Any]] = []

    if drug.get("indications"):
        chunks.append(
            make_chunk(
                "drug",
                drug_id,
                "indication",
                f"{drug.get('name_ko')} 효능/효과: {drug.get('indications')}",
                {"drug_name": drug.get("name_ko"), "field": "indications"},
            )
        )

    if drug.get("dosage"):
        chunks.append(
            make_chunk(
                "drug",
                drug_id,
                "dosage",
                f"{drug.get('name_ko')} 복용법: {drug.get('dosage')}",
                {"drug_name": drug.get("name_ko"), "field": "dosage"},
            )
        )

    if drug.get("warnings"):
        chunks.append(
            make_chunk(
                "drug",
                drug_id,
                "warning",
                f"{drug.get('name_ko')} 주의사항: {drug.get('warnings')}",
                {"drug_name": drug.get("name_ko"), "field": "warnings"},
            )
        )

    if drug.get("parent_text"):
        chunks.append(
            make_chunk(
                "drug",
                drug_id,
                "summary",
                drug.get("parent_text", ""),
                {"drug_name": drug.get("name_ko"), "field": "parent_text"},
            )
        )

    return chunks


def chunk_symptom_record(symptom: Dict[str, Any]) -> List[Dict[str, Any]]:
    symptom_id = symptom.get("symptom_id", "")
    content = " ".join(
        str(item)
        for item in [symptom.get("name"), symptom.get("context"), symptom.get("urgency"), symptom.get("action_guide")]
        if item
    )
    if not content:
        return []
    return [
        make_chunk(
            "symptom",
            symptom_id,
            "summary",
            content,
            {"symptom_name": symptom.get("name"), "is_red_flag": symptom.get("is_red_flag")},
        )
    ]


def build_chunks(drugs: List[Dict[str, Any]], symptoms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    chunks: List[Dict[str, Any]] = []
    for drug in drugs:
        chunks.extend(chunk_drug_record(drug))
    for symptom in symptoms:
        chunks.extend(chunk_symptom_record(symptom))
    return chunks
