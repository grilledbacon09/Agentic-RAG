from __future__ import annotations

from typing import Dict, List

from agents.models import Drug, SafetyResult, Symptom, UserInput
from agents.symptom_utils import (
    group_symptoms_by_name,
    pick_canonical_symptom,
    user_describes_explicit_red_flag,
)


def check_symptom_red_flags(
    user_input: UserInput,
    symptom_db: List[Symptom],
    *,
    user_text: str = "",
) -> SafetyResult:
    grouped = group_symptoms_by_name(symptom_db)
    red_flag_symptoms: List[str] = []
    general_warnings: List[str] = []

    for symptom in user_input.symptoms:
        symptom = symptom.strip()
        if not symptom:
            continue

        group = grouped.get(symptom, [])
        if not group:
            continue

        canonical = pick_canonical_symptom(group)
        if canonical is None:
            continue

        if user_describes_explicit_red_flag(user_text):
            red_flag_symptoms.append(symptom)

        if canonical.urgency:
            general_warnings.append(
                f"증상 '{symptom}'의 시급도 정보: {canonical.urgency}"
            )

        context = str(canonical.context or "").strip()
        if context and context.lower() != "nan":
            general_warnings.append(
                f"증상 '{symptom}' 주의 참고: {context[:180]}"
            )

        guide = str(canonical.action_guide or "").strip()
        if guide and guide.lower() != "nan":
            if "즉시 의사" not in guide:
                general_warnings.append(
                    f"증상 '{symptom}' 대응 가이드: {guide}"
                )

    return SafetyResult(
        has_red_flag=len(red_flag_symptoms) > 0,
        red_flag_symptoms=red_flag_symptoms,
        interaction_warnings=[],
        contraindication_warnings=[],
        general_warnings=general_warnings,
    )


def evaluate_drug_safety(user_input: UserInput, drug: Drug) -> SafetyResult:
    interaction_warnings: List[str] = []
    contraindication_warnings: List[str] = []
    general_warnings: List[str] = []

    current_drug_ids = set(user_input.current_drug_ids)
    current_drug_names = set(user_input.current_drug_names)
    allergies = set(user_input.allergies)
    conditions = set(user_input.conditions)

    for contraindicated_id in drug.combination_contraindication:
        if contraindicated_id in current_drug_ids:
            interaction_warnings.append(
                f"{drug.name_ko}는 현재 복용 중인 약 ID '{contraindicated_id}'와 병용금기 가능성이 있습니다."
            )

    warning_text = drug.warnings.strip()

    for allergy in allergies:
        if allergy and allergy != "없음" and allergy in warning_text:
            contraindication_warnings.append(
                f"{drug.name_ko} 경고문에 알레르기 관련 정보 '{allergy}'가 포함되어 있습니다."
            )

    forbidden_conditions: set[str] = set()
    for chunk in drug.child_chunks:
        for item in chunk.metadata.get("forbidden_conditions", []) or []:
            forbidden_conditions.add((item or "").strip())

    for condition in conditions:
        if not condition or condition == "없음":
            continue
        condition_norm = condition.strip()
        hard_match = any(
            condition_norm in fc or fc in condition_norm
            for fc in forbidden_conditions
            if fc and not (condition_norm == "음주" and fc == "음주")
        )
        if hard_match:
            contraindication_warnings.append(
                f"{drug.name_ko}은(는) 사용자 상태 '{condition}'에 주의가 필요합니다."
            )
        elif condition_norm == "음주" and "음주" in forbidden_conditions:
            general_warnings.append(
                f"{drug.name_ko}: 음주 시 복용 전 약사 상담을 권장합니다."
            )
        elif condition in warning_text:
            general_warnings.append(
                f"{drug.name_ko}: '{condition}' 관련 주의 문구가 있어 약사 상담을 권장합니다."
            )

    for current_name in current_drug_names:
        if current_name and current_name != "없음" and current_name in warning_text:
            interaction_warnings.append(
                f"{drug.name_ko} 경고문에 현재 복용 약 '{current_name}' 관련 주의 문구가 있습니다."
            )

    if warning_text:
        general_warnings.append(f"{drug.name_ko} 주의사항: {warning_text}")

    return SafetyResult(
        has_red_flag=False,
        red_flag_symptoms=[],
        interaction_warnings=interaction_warnings,
        contraindication_warnings=contraindication_warnings,
        general_warnings=general_warnings,
    )


def merge_safety_results(base: SafetyResult, extra: SafetyResult) -> SafetyResult:
    return SafetyResult(
        has_red_flag=base.has_red_flag or extra.has_red_flag,
        red_flag_symptoms=base.red_flag_symptoms + extra.red_flag_symptoms,
        interaction_warnings=base.interaction_warnings + extra.interaction_warnings,
        contraindication_warnings=base.contraindication_warnings + extra.contraindication_warnings,
        general_warnings=base.general_warnings + extra.general_warnings,
    )