from __future__ import annotations

import re

MEDICAL_CUES = (
    "아파", "아프", "아픈", "아픔", "통증", "뻐근", "결림", "뻣", "저려", "따끔", "불편",
    "배", "머리", "목", "어깨", "허리", "속", "복", "인후", "가슴", "팔", "다리", "손", "발",
    "열", "발열", "두통", "복통", "기침", "콧물", "설사", "구토", "메스꺼", "어지", "피로", "감기", "체온",
    "약", "복용", "먹", "처방", "알레르기", "임신", "음주", "술",
    "부작용", "주의", "위험", "괜찮", "될까", "추천", "해열", "진통", "정", "캡슐", "시럽",
    "타이레놀", "이부프로펜", "아세트아미노펜", "acetaminophen", "advil",
    "왜", "이유", "다른", "대체", "도", "38", "39", "40",
)

OFF_TOPIC_KEYWORDS = (
    "고구려", "조선", "역사", "정치", "대통령", "선관위", "해체", "주식", "비트코인", "연예",
    "드라마", "영화", "축구", "야구", "게임", "숙제", "연애",
    "파이썬", "python", "자바스크립트", "javascript", "코드짜", "코드 짜", "프로그래밍",
)

NEGATIVE_SHORT = ("없", "아니", "모르", "딱히", "특별히")

FOLLOW_UP_CUES = (
    "왜", "이유", "부작용", "주의", "위험", "다른 약", "다른약", "대체",
    "먹어도", "복용해도", "괜찮", "될까", "추천 안", "추천안",
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").lower())


def is_short_slot_answer(text: str) -> bool:
    norm = _normalize(text)
    return len(norm) <= 12 and any(p in norm for p in NEGATIVE_SHORT)


def is_medical_related(text: str) -> bool:
    norm = _normalize(text)
    return any(cue in norm for cue in MEDICAL_CUES)


def looks_like_follow_up(text: str) -> bool:
    norm = _normalize(text)
    return any(cue in norm for cue in FOLLOW_UP_CUES)


def has_off_topic_keyword(text: str) -> bool:
    norm = _normalize(text)
    return any(k in norm for k in OFF_TOPIC_KEYWORDS)


def is_off_topic(
    text: str,
    *,
    pending_slot: str | None = None,
    has_recommendation: bool = False,
) -> bool:
    """복약 상담과 무관한 입력인지 판별합니다."""
    raw = (text or "").strip()
    if not raw:
        return False

    if pending_slot in {"current_meds", "allergies", "conditions"}:
        return False

    if is_short_slot_answer(raw):
        return False

    if is_medical_related(raw) or looks_like_follow_up(raw):
        if has_off_topic_keyword(raw):
            return False
        return False

    if has_recommendation:
        return has_off_topic_keyword(raw)

    return has_off_topic_keyword(raw)
