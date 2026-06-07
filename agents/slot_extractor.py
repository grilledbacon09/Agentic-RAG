from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, List

from models import Drug, Symptom, UserInput

SYMPTOM_ALIASES: dict[str, str] = {
    "두통": "두통",
    "머리아픔": "두통",
    "머리가아파": "두통",
    "머리가아픔": "두통",
    "머리가지끈": "두통",
    "머리가지끈거려": "두통",
    "발열": "발열",
    "열": "발열",
    "체온": "발열",
    "고열": "발열",
    "요통": "요통",
    "허리": "요통",
    "허리아픔": "요통",
    "생리통": "생리통",
    "어깨": "사지 통증",
    "어깨가뻐근": "사지 통증",
    "어깨뻐근": "사지 통증",
    "어깨가아파": "사지 통증",
    "어깨아파": "사지 통증",
    "인후염": "인후염",
    "목아픔": "목 통증",
    "목아파": "목 통증",
    "목아픈": "목 통증",
    "목아프": "목 통증",
    "목도아픈": "목 통증",
    "목도아프": "목 통증",
    "목통증": "목 통증",
    "목이아파": "목 통증",
    "목이아픈": "목 통증",
    "목이아프": "목 통증",
    "감기": "발열",
    "통증": "통증",
    "배아픔": "통증",
    "배아파": "통증",
    "배가아파": "통증",
    "배가아픔": "통증",
    "배가아픈": "통증",
    "배아플": "통증",
    "복통": "통증",
    "복부통증": "통증",
    "속아픔": "통증",
    "속아파": "통증",
    "속이아파": "통증",
    "속이아픔": "통증",
    "속이안좋": "소화가 되지 않음, 소화불량",
    "속안좋": "소화가 되지 않음, 소화불량",
    "소화불량": "소화가 되지 않음, 소화불량",
    "소화": "소화가 되지 않음, 소화불량",
    "메스꺼": "성인의 메스꺼움 및 구토",
    "구역": "성인의 메스꺼움 및 구토",
    "복부": "통증",
}

SYMPTOM_SPECIFICITY: dict[str, int] = {
    "통증": 1,
    "두통": 10,
    "발열": 9,
    "요통": 9,
    "허리 통증": 9,
    "사지 통증": 9,
    "생리통": 9,
    "인후염": 10,
    "목 통증": 11,
    "귀통증": 10,
    "소화가 되지 않음, 소화불량": 10,
    "성인의 메스꺼움 및 구토": 10,
}

NEGATIVE_PATTERNS = (
    "없음", "없어요", "없어", "아니요", "아닙니다", "아님", "모르겠", "모름",
    "해당없", "딱히", "특별히",
)

NEGATIVE_EXACT = {
    "없", "없음", "없어", "없어요", "없습니다", "아니", "아니요", "아닙니다",
    "no", "nope", "모름", "모르겠어", "모르겠어요", "모르겠습니다",
}

SYMPTOM_HINTS = ("아파", "아프", "아픈", "안좋", "불편", "통증", "메스꺼", "구토", "열")

CONDITION_KEYWORDS: dict[str, str] = {
    "간염": "간 질환",
    "간": "간 질환",
    "위장": "위장 질환",
    "위염": "위장 질환",
    "임신": "임신",
    "수유": "수유",
    "음주": "음주",
    "술": "음주",
    "당뇨": "당뇨",
    "고혈압": "고혈압",
    "신장": "신장 질환",
    "신부전": "신장 질환",
    "심장": "심혈관계 질환",
    "기관지염": "기관지염",
    "기관지": "기관지염",
    "천식": "천식",
    "폐": "폐 질환",
}

CURRENT_MED_CUES = ("먹", "복용", "드시", "투여", "처방", "먹고있", "복용중")

INGREDIENT_NAMES = (
    "이부프로펜", "아세트아미노펜", "타이레놀", "나프록센", "덱시부프로펜",
    "케토프로펜", "아스피린", "판콜", "콜대원",
)

ALLERGY_KEYWORDS = (
    "페니실린", "아스피린", "이부프로펜", "아세트아미노펜", "항생제", "약 알레르기",
)


@dataclass
class SlotExtractionResult:
    user_input: UserInput
    extracted_symptoms: List[str] = field(default_factory=list)
    extracted_drugs: List[str] = field(default_factory=list)
    extracted_allergies: List[str] = field(default_factory=list)
    extracted_conditions: List[str] = field(default_factory=list)
    is_negative_answer: bool = False
    wants_recommendation: bool = False
    messages: List[str] = field(default_factory=list)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").lower())


def _is_negative(text: str) -> bool:
    norm = _normalize(text)
    if any(h in norm for h in SYMPTOM_HINTS):
        return False
    if norm in NEGATIVE_EXACT:
        return True
    if len(norm) <= 10:
        return norm.startswith("없") or norm.startswith("아니") or norm.startswith("모르")
    return any(p.replace(" ", "") == norm for p in NEGATIVE_PATTERNS)


def _unique(items: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for item in items:
        key = item.strip()
        if key and key not in seen:
            seen.add(key)
            result.append(key)
    return result


def _extract_symptoms(text: str, symptoms: List[Symptom]) -> List[str]:
    norm = _normalize(text)
    found: List[str] = []

    known = sorted([s.name for s in symptoms if s.name], key=len, reverse=True)
    for name in known:
        if _normalize(name) in norm:
            found.append(name)

    for alias, canonical in SYMPTOM_ALIASES.items():
        if alias in norm and canonical not in found:
            found.append(canonical)

    if "목" in norm and any(k in norm for k in ("아파", "아프", "아픈", "통증", "따끔")):
        if "목 통증" not in found:
            found.append("목 통증")

    if re.search(r"3[89](?:\.\d+)?\s*도|40\s*도", text):
        if "발열" not in found:
            found.append("발열")

    return _unique(found)


def pick_primary_symptoms(symptoms: List[str], user_text: str = "") -> List[str]:
    """여러 증상이 잡힐 때 가장 구체적인 하나만 남깁니다."""
    found = _unique(symptoms)
    if not found:
        return []
    if len(found) == 1:
        return found

    norm = _normalize(user_text)
    if "목" in norm:
        for preferred in ("목 통증", "인후염"):
            if preferred in found:
                return [preferred]
    if any(k in norm for k in ("배", "복", "속")):
        for preferred in ("소화가 되지 않음, 소화불량", "성인의 메스꺼움 및 구토", "통증"):
            if preferred in found:
                return [preferred]

    best = max(found, key=lambda s: SYMPTOM_SPECIFICITY.get(s, 5))
    return [best]


def _extract_drugs(text: str, drugs: List[Drug]) -> tuple[List[str], List[str]]:
    norm = _normalize(text)
    ids: List[str] = []
    names: List[str] = []

    for drug in drugs:
        if drug.drug_id and _normalize(drug.drug_id) in norm:
            ids.append(drug.drug_id)
        if drug.name_ko and _normalize(drug.name_ko) in norm:
            names.append(drug.name_ko)

    if any(cue in norm for cue in CURRENT_MED_CUES):
        for ing in INGREDIENT_NAMES:
            if ing in text and ing not in names:
                names.append(ing)

    return _unique(ids), _unique(names)


def _extract_allergies(text: str) -> List[str]:
    norm = _normalize(text)
    if any(cue in norm for cue in CURRENT_MED_CUES):
        return []
    found = [kw for kw in ALLERGY_KEYWORDS if kw in text]
    if "알레르기" in text and not found and not _is_negative(text):
        snippet = text.split("알레르기", 1)[-1].strip(" :은는이가")
        if snippet and not _is_negative(snippet):
            found.append(snippet[:40])
    return _unique(found)


def _extract_conditions(text: str) -> List[str]:
    found: List[str] = []
    for key, label in sorted(CONDITION_KEYWORDS.items(), key=lambda x: len(x[0]), reverse=True):
        if key in text:
            found.append(label)
    return _unique(found)


def _wants_recommendation(text: str) -> bool:
    keywords = (
        "추천", "어떤 약", "무슨 약", "뭐 먹", "뭘 먹", "복용", "사도 될",
        "괜찮", "알려줘", "알려 주", "도와줘", "도와 주",
    )
    return any(k in text for k in keywords)


def merge_user_input(base: UserInput, patch: UserInput) -> UserInput:
    return UserInput(
        symptoms=_unique(base.symptoms + patch.symptoms),
        current_drug_ids=_unique(base.current_drug_ids + patch.current_drug_ids),
        current_drug_names=_unique(base.current_drug_names + patch.current_drug_names),
        allergies=_unique(base.allergies + patch.allergies),
        conditions=_unique(base.conditions + patch.conditions),
        age=patch.age or base.age,
    )


def replace_primary_symptoms(
    base: UserInput,
    new_symptoms: List[str],
    *,
    user_text: str = "",
) -> UserInput:
    """대화 중 주 증상이 바뀌었을 때 증상 목록을 교체합니다."""
    picked = pick_primary_symptoms(new_symptoms, user_text)
    if not picked:
        return base
    return UserInput(
        symptoms=picked,
        current_drug_ids=list(base.current_drug_ids),
        current_drug_names=list(base.current_drug_names),
        allergies=list(base.allergies),
        conditions=list(base.conditions),
        age=base.age,
    )


def extract_slots_from_message(
    message: str,
    drugs: List[Drug],
    symptoms: List[Symptom],
    pending_slot: str | None = None,
) -> SlotExtractionResult:
    """자유 발화에서 증상/약물/알레르기/기저질환 슬롯을 추출합니다."""
    text = (message or "").strip()
    negative = _is_negative(text)

    extracted_symptoms = pick_primary_symptoms(
        _extract_symptoms(text, symptoms),
        text,
    )
    drug_ids, drug_names = _extract_drugs(text, drugs)
    extracted_allergies = _extract_allergies(text)
    extracted_conditions = _extract_conditions(text)

    patch = UserInput(symptoms=[])

    if extracted_symptoms:
        patch.symptoms = extracted_symptoms

    if drug_ids or drug_names:
        patch.current_drug_ids = drug_ids
        patch.current_drug_names = drug_names
    elif pending_slot == "current_meds" and not negative and len(text) >= 2:
        if any(cue in _normalize(text) for cue in CURRENT_MED_CUES) or extracted_symptoms:
            patch.current_drug_names = [text[:80]]

    if extracted_allergies:
        patch.allergies = extracted_allergies
    elif pending_slot == "allergies" and negative:
        patch.allergies = ["없음"]

    if extracted_conditions:
        patch.conditions = extracted_conditions
    elif pending_slot == "conditions" and negative:
        patch.conditions = ["없음"]
    elif pending_slot == "conditions" and not negative and len(text) >= 2:
        patch.conditions = [text[:80]]

    if pending_slot == "current_meds" and negative:
        patch.current_drug_ids = ["없음"]
        patch.current_drug_names = ["없음"]

    messages: List[str] = []
    if extracted_symptoms:
        messages.append(f"증상 추출: {', '.join(extracted_symptoms)}")
    if drug_names or drug_ids:
        messages.append(
            f"복용약 추출: {', '.join(drug_names + drug_ids)}"
        )
    if patch.allergies:
        messages.append(f"알레르기 반영: {', '.join(patch.allergies)}")
    if patch.conditions:
        messages.append(f"기저상태 반영: {', '.join(patch.conditions)}")

    return SlotExtractionResult(
        user_input=patch,
        extracted_symptoms=extracted_symptoms,
        extracted_drugs=drug_names + drug_ids,
        extracted_allergies=patch.allergies,
        extracted_conditions=patch.conditions,
        is_negative_answer=negative,
        wants_recommendation=_wants_recommendation(text),
        messages=messages,
    )
