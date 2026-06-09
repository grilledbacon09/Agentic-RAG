from __future__ import annotations

import json
from pathlib import Path
from typing import List

from agents.models import Chunk, Drug, Symptom


def load_drugs(json_path: str | Path) -> List[Drug]:
    path = Path(json_path)
    with path.open("r", encoding="utf-8") as f:
        raw_data = json.load(f)

    drugs: List[Drug] = []
    for item in raw_data:
        child_chunks = [
            Chunk(
                chunk_type=chunk.get("chunk_type", ""),
                text=chunk.get("text", ""),
                metadata=chunk.get("metadata", {}) or {},
            )
            for chunk in item.get("child_chunks", [])
        ]

        drugs.append(
            Drug(
                drug_id=item["drug_id"],
                name_ko=item["name_ko"],
                name_en=item.get("name_en"),
                ingredient=item.get("ingredient", []) or [],
                indications=item.get("indications", "") or "",
                dosage=item.get("dosage", "") or "",
                warnings=item.get("warnings", "") or "",
                category=item.get("category"),
                updated_date=item.get("updated_date"),
                combination_contraindication=item.get("combination_contraindication", []) or [],
                parent_text=item.get("parent_text", "") or "",
                child_chunks=child_chunks,
            )
        )
    return drugs


def load_symptoms(json_path: str | Path) -> List[Symptom]:
    path = Path(json_path)
    with path.open("r", encoding="utf-8") as f:
        raw_data = json.load(f)

    symptoms: List[Symptom] = []
    for item in raw_data:
        symptoms.append(
            Symptom(
                symptom_id=item["symptom_id"],
                name=item["name"],
                is_red_flag=item.get("is_red_flag"),
                urgency=item.get("urgency"),
                context=item.get("context"),
                action_guide=item.get("action_guide"),
            )
        )
    return symptoms