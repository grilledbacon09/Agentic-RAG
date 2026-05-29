from __future__ import annotations

from typing import List, Set

from models import Drug, RetrievalResult, UserInput


def _normalize_text(text: str) -> str:
    return (text or "").strip().lower()


def _extract_treats_from_chunks(drug: Drug) -> Set[str]:
    treats: Set[str] = set()
    for chunk in drug.child_chunks:
        chunk_treats = chunk.metadata.get("treats", [])
        for item in chunk_treats:
            if item:
                treats.add(str(item).strip().lower())
    return treats


def score_drug(user_input: UserInput, drug: Drug) -> RetrievalResult:
    score = 0.0
    matched_symptoms: List[str] = []
    reasons: List[str] = []

    indications_text = _normalize_text(drug.indications)
    parent_text = _normalize_text(drug.parent_text)
    treats_set = _extract_treats_from_chunks(drug)

    for symptom in user_input.symptoms:
        symptom_norm = _normalize_text(symptom)
        if not symptom_norm:
            continue

        matched = False

        if symptom_norm in indications_text:
            score += 3.0
            matched = True
            reasons.append(f"indications에 '{symptom}' 포함 (+3)")

        if symptom_norm in parent_text:
            score += 1.5
            matched = True
            reasons.append(f"parent_text에 '{symptom}' 포함 (+1.5)")

        if symptom_norm in treats_set:
            score += 2.0
            matched = True
            reasons.append(f"child metadata treats에 '{symptom}' 포함 (+2)")

        if matched:
            matched_symptoms.append(symptom)

    if drug.category:
        score += 0.5
        reasons.append("category 정보 존재 (+0.5)")

    if drug.updated_date:
        score += 0.5
        reasons.append("updated_date 정보 존재 (+0.5)")

    if drug.warnings:
        score -= 0.3
        reasons.append("주의사항 존재 (-0.3)")

    return RetrievalResult(
        drug=drug,
        score=score,
        matched_symptoms=matched_symptoms,
        reasons=reasons,
    )


def retrieve_top_k(user_input: UserInput, drugs: List[Drug], top_k: int = 3) -> List[RetrievalResult]:
    scored_results = [score_drug(user_input, drug) for drug in drugs]
    scored_results = [result for result in scored_results if result.score > 0]
    scored_results.sort(key=lambda x: x.score, reverse=True)
    return scored_results[:top_k]