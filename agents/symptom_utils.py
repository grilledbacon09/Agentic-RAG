from __future__ import annotations

from typing import Dict, List

from models import Symptom

EXPLICIT_RED_FLAG_CUES = (
    "갑작스",
    "터질 것",
    "터질듯",
    "터질 듯",
    "터져",
    "찢어",
    "의식 저하",
    "의식이 없",
    "실신",
    "시야 이상",
    "시야가 흐",
    "목 경직",
    "경부경직",
    "사지 마비",
    "마비",
    "벼락 두통",
    "호흡곤란",
    "숨쉬기 힘",
    "가슴 통증",
    "흉통",
    "혈변",
    "토혈",
    "39도",
    "40도",
    "고열",
)


def group_symptoms_by_name(symptom_db: List[Symptom]) -> Dict[str, List[Symptom]]:
    grouped: Dict[str, List[Symptom]] = {}
    for item in symptom_db:
        key = (item.name or "").strip()
        if not key:
            continue
        grouped.setdefault(key, []).append(item)
    return grouped


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and str(value) == "nan":
        return ""
    return str(value).strip()


def pick_canonical_symptom(group: List[Symptom]) -> Symptom | None:
    """동일 증상명이 여러 행일 때 OTC 상담용 대표 행을 고릅니다."""
    if not group:
        return None
    non_red = [s for s in group if not s.is_red_flag]
    if non_red:
        with_guide = [s for s in non_red if _as_text(s.action_guide)]
        return with_guide[0] if with_guide else non_red[0]
    return group[0]


def user_describes_explicit_red_flag(user_text: str) -> bool:
    text = (user_text or "").strip().lower()
    if not text:
        return False
    return any(cue in text for cue in EXPLICIT_RED_FLAG_CUES)


def dedupe_symptoms_for_chat(symptom_db: List[Symptom]) -> List[Symptom]:
    """채팅/안전 검사용 증상 목록: 이름당 대표 1건만 유지."""
    grouped = group_symptoms_by_name(symptom_db)
    result: List[Symptom] = []
    for name in sorted(grouped):
        canonical = pick_canonical_symptom(grouped[name])
        if canonical:
            result.append(canonical)
    return result
