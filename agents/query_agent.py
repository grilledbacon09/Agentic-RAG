from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List

from agents.models import Drug, Symptom, UserInput


def _normalize(text: str) -> str:
    return (text or "").strip().lower()


def _split_items(text: str) -> List[str]:
    if not text:
        return []
    separators = [",", "，", "/", "|", "\n"]
    for sep in separators[1:]:
        text = text.replace(sep, separators[0])
    return [item.strip() for item in text.split(separators[0]) if item.strip()]


@dataclass
class QueryAnalysis:
    """사용자 질의 분석 결과.

    기존 UserInput과 호환되도록 UserInput을 포함하고,
    발표/디버깅용 agent message도 같이 저장한다.
    """

    user_input: UserInput
    detected_terms: List[str] = field(default_factory=list)
    unknown_terms: List[str] = field(default_factory=list)
    messages: List[str] = field(default_factory=list)


def _collect_known_terms(drugs: Iterable[Drug], symptoms: Iterable[Symptom]) -> set[str]:
    terms: set[str] = set()

    for symptom in symptoms:
        if symptom.name:
            terms.add(_normalize(symptom.name))

    for drug in drugs:
        terms.add(_normalize(drug.drug_id))
        terms.add(_normalize(drug.name_ko))
        if drug.name_en:
            terms.add(_normalize(drug.name_en))
        for ingredient in drug.ingredient:
            terms.add(_normalize(ingredient))
        for chunk in drug.child_chunks:
            for value in chunk.metadata.get("treats", []) or []:
                terms.add(_normalize(str(value)))
            for value in chunk.metadata.get("forbidden_conditions", []) or []:
                terms.add(_normalize(str(value)))

    return {term for term in terms if term}


def analyze_query(
    raw_symptoms: str = "",
    raw_current_drug_ids: str = "",
    raw_current_drug_names: str = "",
    raw_allergies: str = "",
    raw_conditions: str = "",
    drugs: List[Drug] | None = None,
    symptoms: List[Symptom] | None = None,
) -> QueryAnalysis:
    """CLI 입력 문자열을 UserInput으로 변환하고 알려진/미확인 용어를 분석한다."""

    symptom_items = _split_items(raw_symptoms)
    current_ids = _split_items(raw_current_drug_ids)
    current_names = _split_items(raw_current_drug_names)
    allergies = _split_items(raw_allergies)
    conditions = _split_items(raw_conditions)

    user_input = UserInput(
        symptoms=symptom_items,
        current_drug_ids=current_ids,
        current_drug_names=current_names,
        allergies=allergies,
        conditions=conditions,
    )

    known_terms = _collect_known_terms(drugs or [], symptoms or [])
    all_terms = symptom_items + current_ids + current_names + allergies + conditions
    detected: List[str] = []
    unknown: List[str] = []

    for term in all_terms:
        if _normalize(term) in known_terms:
            detected.append(term)
        elif term and term != "없음":
            unknown.append(term)

    messages = [
        f"증상 {len(symptom_items)}개, 현재 복용약 ID {len(current_ids)}개, 복용약 이름 {len(current_names)}개를 추출했습니다."
    ]
    if unknown:
        messages.append(f"DB에서 직접 확인되지 않은 입력: {', '.join(unknown)}")
    else:
        messages.append("입력 항목이 현재 샘플 DB 기준으로 정상 파싱되었습니다.")

    return QueryAnalysis(
        user_input=user_input,
        detected_terms=detected,
        unknown_terms=unknown,
        messages=messages,
    )


def analyze_user_input(user_input: UserInput, drugs: List[Drug], symptoms: List[Symptom]) -> QueryAnalysis:
    """이미 만들어진 UserInput을 agent 분석 결과로 감싼다."""

    known_terms = _collect_known_terms(drugs, symptoms)
    all_terms = (
        user_input.symptoms
        + user_input.current_drug_ids
        + user_input.current_drug_names
        + user_input.allergies
        + user_input.conditions
    )
    detected = [term for term in all_terms if _normalize(term) in known_terms]
    unknown = [term for term in all_terms if term and term != "없음" and _normalize(term) not in known_terms]

    messages = [f"사용자 입력에서 총 {len(all_terms)}개 항목을 분석했습니다."]
    if unknown:
        messages.append(f"추가 확인이 필요한 항목: {', '.join(unknown)}")

    return QueryAnalysis(user_input=user_input, detected_terms=detected, unknown_terms=unknown, messages=messages)
