from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from agents.models import Symptom, UserInput
from agents.safety import check_symptom_red_flags
from agents.symptom_utils import user_describes_explicit_red_flag


DEFAULT_RED_FLAG_KEYWORDS = {
    "가슴 통증": "심혈관계 응급 가능성",
    "흉통": "심혈관계 응급 가능성",
    "호흡곤란": "호흡기 응급 가능성",
    "숨쉬기 힘듦": "호흡기 응급 가능성",
    "의식 저하": "신경학적 응급 가능성",
    "실신": "신경학적 응급 가능성",
    "고열": "감염성 질환 악화 가능성",
    "혈변": "위장관 출혈 가능성",
    "토혈": "위장관 출혈 가능성",
    "심한 복통": "급성 복부질환 가능성",
    "터질 것": "급성 중증 두통(벼락 두통) 가능성",
    "터질듯": "급성 중증 두통(벼락 두통) 가능성",
    "벼락": "급성 중증 두통 가능성",
}


@dataclass
class RedFlagCheck:
    has_red_flag: bool
    matched: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    action: str = ""


def detect_red_flags(
    user_input: UserInput,
    symptom_db: List[Symptom],
    *,
    user_text: str = "",
) -> RedFlagCheck:
    """사용자 발화에 응급 징후가 있을 때만 red flag로 처리합니다."""

    combined_text = f"{user_text} {' '.join(user_input.symptoms)}".strip()
    safety_result = check_symptom_red_flags(
        user_input,
        symptom_db,
        user_text=combined_text,
    )
    matched = list(safety_result.red_flag_symptoms)
    reasons = list(safety_result.general_warnings)

    for keyword, reason in DEFAULT_RED_FLAG_KEYWORDS.items():
        if keyword in combined_text and keyword not in matched:
            matched.append(keyword)
            reasons.append(f"'{keyword}' 감지: {reason}")

    has_red_flag = bool(matched) or user_describes_explicit_red_flag(combined_text)
    if has_red_flag and not matched:
        matched = [s for s in user_input.symptoms if s] or ["응급 징후"]
    action = "약 추천보다 의료기관/약사 상담을 우선 권고합니다." if has_red_flag else "일반 OTC 추천 흐름 진행 가능"

    return RedFlagCheck(has_red_flag=has_red_flag, matched=matched, reasons=reasons, action=action)
