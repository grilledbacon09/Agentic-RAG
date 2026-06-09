from __future__ import annotations

from enum import Enum

from agents.off_topic import is_off_topic, looks_like_follow_up


class UserIntent(str, Enum):
    GREETING = "greeting"
    OFF_TOPIC = "off_topic"
    PROVIDE_INFO = "provide_info"
    REQUEST_RECOMMENDATION = "request_recommendation"
    SYMPTOM_CHANGE = "symptom_change"
    FOLLOW_UP_WHY = "follow_up_why"
    FOLLOW_UP_ALTERNATIVE = "follow_up_alternative"
    FOLLOW_UP_SAFETY = "follow_up_safety"
    FOLLOW_UP_ADVISORY = "follow_up_advisory"
    RESET = "reset"
    EXIT = "exit"
    UNKNOWN = "unknown"


_SYMPTOM_CUE_KEYWORDS = (
    "아파", "아프", "아픈", "통증", "뻐근", "결림", "배", "머리", "목", "어깨", "허리", "속",
    "인후", "열", "발열", "콧물", "기침", "설사", "구토", "메스꺼", "어지", "피로", "불편",
    "시큰", "따끔", "감기", "38", "39", "40",
)

_RECOMMENDATION_CUE_KEYWORDS = (
    "추천", "어떤 약", "무슨 약", "뭐 먹", "뭘 먹", "먹어도", "먹는게", "복용",
    "괜찮", "알려줘", "도와줘", "좋을까", "감기약",
)

_ADVISORY_CUE_KEYWORDS = (
    "먹어도", "복용해도", "괜찮", "될까", "해도", "써도", "위험", "문제", "상관",
    "타이레놀", "이부프로펜", "아세트아미노펜", "38도", "39도", "40도",
)


def _has_symptom_cue(text: str) -> bool:
    return any(k in text for k in _SYMPTOM_CUE_KEYWORDS)


def _is_advisory_question(text: str) -> bool:
    if "?" in text or "？" in text:
        return True
    return any(k in text for k in _ADVISORY_CUE_KEYWORDS) and any(
        k in text for k in ("먹", "복용", "괜찮", "될까", "위험", "해도", "써도", "추천")
    )


def detect_intent(
    message: str,
    *,
    has_recommendation: bool = False,
    pending_slot: str | None = None,
) -> UserIntent:
    text = (message or "").strip().lower()

    if text in {"quit", "exit", "종료", "끝", "bye", "나가기"}:
        return UserIntent.EXIT

    if any(k in text for k in ("처음부터", "다시 시작", "리셋", "reset")):
        return UserIntent.RESET

    if has_recommendation:
        if any(k in text for k in ("왜", "이유", "근거", "뭐 때문에", "추천 안", "추천안")):
            return UserIntent.FOLLOW_UP_WHY
        if any(k in text for k in ("다른 약", "대체", "다른거", "다른 것", "2순위", "차선")):
            return UserIntent.FOLLOW_UP_ALTERNATIVE
        if any(k in text for k in ("부작용", "주의사항", "위험")) or (
            "주의" in text and "상태" not in text
        ):
            return UserIntent.FOLLOW_UP_SAFETY
        if _is_advisory_question(text) or looks_like_follow_up(text):
            return UserIntent.FOLLOW_UP_ADVISORY
        if _has_symptom_cue(text) and not any(
            k in text for k in ("왜", "다른", "부작용", "주의", "이유", "근거", "괜찮", "될까")
        ):
            return UserIntent.SYMPTOM_CHANGE
        if _has_symptom_cue(text) and any(k in text for k in _RECOMMENDATION_CUE_KEYWORDS):
            return UserIntent.SYMPTOM_CHANGE

    if _is_advisory_question(text):
        return UserIntent.FOLLOW_UP_ADVISORY

    if is_off_topic(message, pending_slot=pending_slot, has_recommendation=has_recommendation):
        return UserIntent.OFF_TOPIC

    if any(k in text for k in ("안녕", "hello", "hi", "시작")):
        return UserIntent.GREETING

    if _is_advisory_question(text) and _has_symptom_cue(text):
        return UserIntent.FOLLOW_UP_ADVISORY

    if any(k in text for k in _RECOMMENDATION_CUE_KEYWORDS):
        return UserIntent.REQUEST_RECOMMENDATION

    if _has_symptom_cue(text):
        return UserIntent.SYMPTOM_CHANGE if has_recommendation else UserIntent.PROVIDE_INFO

    return UserIntent.PROVIDE_INFO
