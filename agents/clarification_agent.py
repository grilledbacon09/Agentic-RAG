from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from agents.models import UserInput


@dataclass
class ClarificationResult:
    needs_clarification: bool
    questions: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)


def generate_clarifying_questions(user_input: UserInput) -> ClarificationResult:
    """안전한 추천에 필요한 최소 정보를 확인한다.

    현재는 rule-based이며, 이후 LLM 기반 질문 생성으로 교체 가능하다.
    """

    questions: List[str] = []
    reasons: List[str] = []

    if not user_input.symptoms:
        questions.append("현재 어떤 증상이 있는지 쉼표로 입력해 주세요. 예: 두통, 발열")
        reasons.append("증상 정보가 없어 약 후보 검색이 어렵습니다.")

    if user_input.symptoms and len(user_input.symptoms) == 1:
        questions.append("증상이 언제부터 시작되었고, 열/통증의 정도는 어느 정도인가요?")
        reasons.append("단일 증상만으로는 안전한 추천 근거가 부족할 수 있습니다.")

    if not user_input.current_drug_ids and not user_input.current_drug_names:
        questions.append("현재 복용 중인 약이 있다면 약 ID 또는 약 이름을 입력해 주세요. 없으면 '없음'이라고 입력해도 됩니다.")
        reasons.append("병용금기 및 중복 성분 검사를 위해 현재 복용약 정보가 필요합니다.")

    if not user_input.allergies:
        questions.append("알레르기 또는 과민반응 이력이 있나요? 예: 페니실린, 이부프로펜")
        reasons.append("알레르기 기반 금기 검사를 위해 필요합니다.")

    if not user_input.conditions:
        questions.append("기저질환/특이상태가 있나요? 예: 음주, 간 질환, 위장질환, 임신")
        reasons.append("사용자 상태 기반 안전성 필터링을 위해 필요합니다.")

    return ClarificationResult(
        needs_clarification=bool(questions),
        questions=questions,
        reasons=reasons,
    )
