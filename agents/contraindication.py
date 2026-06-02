from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Set

from agents.models import Drug, UserInput
from agents.safety import evaluate_drug_safety


def _norm(text: str) -> str:
    return (text or "").strip().lower()


@dataclass
class ContraindicationCheck:
    drug_id: str
    drug_name: str
    risk_level: str
    warnings: List[str] = field(default_factory=list)
    blocked: bool = False
    penalty: float = 0.0


def _current_drug_lookup(drugs: List[Drug]) -> Dict[str, Drug]:
    lookup: Dict[str, Drug] = {}
    for drug in drugs:
        lookup[_norm(drug.drug_id)] = drug
        lookup[_norm(drug.name_ko)] = drug
        if drug.name_en:
            lookup[_norm(drug.name_en)] = drug
    return lookup


def _extract_current_ingredients(user_input: UserInput, drugs: List[Drug]) -> Set[str]:
    lookup = _current_drug_lookup(drugs)
    ingredients: Set[str] = set()
    for key in user_input.current_drug_ids + user_input.current_drug_names:
        drug = lookup.get(_norm(key))
        if drug:
            for ingredient in drug.ingredient:
                ingredients.add(_norm(ingredient))
    return ingredients


def check_drug_contraindication(user_input: UserInput, candidate: Drug, all_drugs: List[Drug]) -> ContraindicationCheck:
    """후보 약 하나에 대해 병용금기/중복성분/사용자 상태 위험을 검사한다."""

    base_safety = evaluate_drug_safety(user_input, candidate)
    warnings = base_safety.interaction_warnings + base_safety.contraindication_warnings
    penalty = 0.0
    blocked = False

    if base_safety.interaction_warnings:
        penalty += 4.0
        blocked = True
    if base_safety.contraindication_warnings:
        penalty += 3.0

    current_ingredients = _extract_current_ingredients(user_input, all_drugs)
    candidate_ingredients = {_norm(item) for item in candidate.ingredient}
    duplicated = sorted(current_ingredients & candidate_ingredients)
    if duplicated:
        warnings.append(f"현재 복용약과 중복 성분 감지: {', '.join(duplicated)}")
        penalty += 3.0

    warning_text = _norm(candidate.warnings)
    for condition in user_input.conditions:
        condition_norm = _norm(condition)
        if condition_norm and condition_norm != "없음" and condition_norm in warning_text:
            penalty += 2.0

    if penalty >= 4.0:
        risk_level = "high"
    elif penalty >= 2.0:
        risk_level = "medium"
    else:
        risk_level = "low"

    return ContraindicationCheck(
        drug_id=candidate.drug_id,
        drug_name=candidate.name_ko,
        risk_level=risk_level,
        warnings=warnings,
        blocked=blocked,
        penalty=penalty,
    )


def check_all_contraindications(user_input: UserInput, candidates: List[Drug], all_drugs: List[Drug]) -> List[ContraindicationCheck]:
    return [check_drug_contraindication(user_input, drug, all_drugs) for drug in candidates]
