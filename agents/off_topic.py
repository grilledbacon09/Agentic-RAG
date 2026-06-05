from __future__ import annotations

import re

MEDICAL_CUES = (
    "아파", "아프", "통증", "열", "발열", "두통", "복통", "배", "머리", "목",
    "인후", "기침", "콧물", "설사", "구토", "메스꺼", "어지", "피로", "감기",
    "약", "복용", "먹어", "처방", "알레르기", "임신", "음주",
)

OFF_TOPIC_KEYWORDS = (
    "고구려", "조선", "역사", "정치", "대통령", "주식", "비트코인", "연예",
    "드라마", "영화", "축구", "야구", "게임", "숙제", "연애",
)

NEGATIVE_SHORT = ("없", "아니", "모르", "딱히", "특별히")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").lower())


def is_short_slot_answer(text: str) -> bool:
    norm = _normalize(text)
    return len(norm) <= 12 and any(p in norm for p in NEGATIVE_SHORT)


def is_medical_related(text: str) -> bool:
    norm = _normalize(text)
    return any(cue in norm for cue in MEDICAL_CUES)


def is_off_topic(text: str, *, pending_slot: str | None = None) -> bool:
    """복약 상담과 무관한 입력인지 판별합니다."""
    raw = (text or "").strip()
    if not raw:
        return False

    if pending_slot in {"current_meds", "allergies", "conditions"}:
        return False

    if is_short_slot_answer(raw):
        return False

    norm = _normalize(raw)
    if any(k in norm for k in OFF_TOPIC_KEYWORDS):
        return True

    if is_medical_related(raw):
        return False

    if len(norm) >= 6:
        return True

    return False
