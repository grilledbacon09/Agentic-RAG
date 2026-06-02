from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from agents.models import Drug
from agents.recommendation_agent import RecommendationDecision


@dataclass
class ValidationResult:
    passed: bool
    checks: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def validate_decision(decision: RecommendationDecision, all_drugs: List[Drug]) -> ValidationResult:
    """추천 결과가 DB 근거와 안전성 기준을 만족하는지 검증한다."""

    drug_ids = {drug.drug_id for drug in all_drugs}
    drug_names = {drug.name_ko for drug in all_drugs}
    checks: List[str] = []
    errors: List[str] = []

    for item in decision.recommended:
        drug = item.retrieval.drug
        if drug.drug_id not in drug_ids or drug.name_ko not in drug_names:
            errors.append(f"DB에 없는 약 추천 감지: {drug.name_ko} ({drug.drug_id})")
        else:
            checks.append(f"DB 존재 검증 완료: {drug.name_ko}")

        if item.blocked or item.risk_level == "high":
            errors.append(f"고위험/차단 후보가 추천 목록에 포함됨: {drug.name_ko}")
        else:
            checks.append(f"안전성 차단 여부 검증 완료: {drug.name_ko}")

        if not drug.dosage:
            errors.append(f"복용법 근거 누락: {drug.name_ko}")
        else:
            checks.append(f"복용법 근거 존재: {drug.name_ko}")

    if not decision.recommended:
        checks.append("추천 후보 없음: 안전성 기준에 따라 상담 권고 가능")

    return ValidationResult(passed=not errors, checks=checks, errors=errors)
