from __future__ import annotations

from typing import List, Optional

from models import ConversationSession, PipelineResult, UserInput


OFF_TOPIC_MESSAGE = (
    "저는 **일반 의약품 복약 상담**만 도와드릴 수 있어요. "
    "역사·잡담 같은 주제는 다루기 어렵습니다.\n\n"
    "지금 불편하신 증상이 있으시면 편하게 말씀해 주세요. "
    "(예: \"목이 아파요\", \"두통이 있어요\")"
)

WELCOME_MESSAGE = (
    "안녕하세요! 일반 의약품 복약 상담을 도와드릴게요.\n\n"
    "지금 어떤 증상이 가장 불편하신가요? 편하게 말씀해 주세요.\n"
    "(예: \"머리가 아파요\", \"열이 나요\")"
)

SLOT_QUESTIONS = {
    "symptoms": "어떤 증상이 있으신가요? 편하게 설명해 주셔도 좋아요.",
    "current_meds": "혹시 지금 같이 드시는 약이 있으실까요? 없으시면 \"없음\"이라고 답해 주세요.",
    "allergies": "알레르기나 약 때문에 불편했던 적이 있으신가요? 없으시면 \"없음\"이면 됩니다.",
    "conditions": "간·위 같은 기저질환이나 임신, 음주처럼 참고할 상태가 있을까요?",
}


def get_next_slot(session: ConversationSession) -> Optional[str]:
    order = ("symptoms", "current_meds", "allergies", "conditions")
    ui = session.user_input

    if not ui.symptoms and "symptoms" not in session.confirmed_slots:
        return "symptoms"
    if (
        not ui.current_drug_ids
        and not ui.current_drug_names
        and "current_meds" not in session.confirmed_slots
    ):
        return "current_meds"
    if not ui.allergies and "allergies" not in session.confirmed_slots:
        return "allergies"
    if not ui.conditions and "conditions" not in session.confirmed_slots:
        return "conditions"
    return None


def is_ready_for_recommendation(session: ConversationSession) -> bool:
    ui = session.user_input
    required = ("symptoms", "current_meds", "allergies", "conditions")
    if not ui.symptoms:
        return False
    return all(slot in session.confirmed_slots for slot in required)


def _summarize_collected(user_input: UserInput) -> str:
    symptoms = ", ".join(user_input.symptoms) if user_input.symptoms else "없음"
    meds = ", ".join(user_input.current_drug_names + user_input.current_drug_ids)
    meds = meds or "없음"
    allergies = ", ".join(user_input.allergies) if user_input.allergies else "없음"
    conditions = ", ".join(user_input.conditions) if user_input.conditions else "없음"
    return (
        f"증상: {symptoms}\n"
        f"복용 중 약: {meds}\n"
        f"알레르기: {allergies}\n"
        f"기저/특이 상태: {conditions}"
    )


def format_slot_ack(session: ConversationSession, slot: str) -> str:
    ui = session.user_input
    if slot == "symptoms" and ui.symptoms:
        return f"아, {ui.symptoms[0]} 증상이시군요. 말씀해 주셔서 감사해요."
    if slot == "current_meds":
        if ui.current_drug_names or ui.current_drug_ids:
            meds = ", ".join(ui.current_drug_names + ui.current_drug_ids)
            return f"네, {meds} 복용 중이시군요. 참고할게요."
        return "네, 현재 복용 중인 약은 없으시군요."
    if slot == "allergies":
        if ui.allergies and ui.allergies != ["없음"]:
            return f"알레르기({', '.join(ui.allergies)})도 기억해 둘게요."
        return "알레르기 이력은 없으시군요. 확인했어요."
    if slot == "conditions":
        if ui.conditions and ui.conditions != ["없음"]:
            return f"네, {', '.join(ui.conditions)} 상태도 반영할게요."
        return "특별히 참고할 기저질환은 없으시군요."
    return "네, 알겠습니다."


def format_topic_change_ack(old_symptoms: List[str], new_symptoms: List[str]) -> str:
    old = ", ".join(old_symptoms) if old_symptoms else "이전 증상"
    new = ", ".join(new_symptoms) if new_symptoms else "새 증상"
    if old == new:
        return ""
    return (
        f"네, 말씀하신 내용 반영해서 **{new}** 기준으로 다시 살펴볼게요. "
        f"(이전에는 {old} 위주로 확인했었어요.)\n\n"
    )


def format_recommendation_message(
    result: PipelineResult,
    *,
    topic_ack: str = "",
) -> str:
    if result.is_emergency:
        return result.emergency_message

    decision = result.decision
    lines: List[str] = []

    if topic_ack:
        lines.append(topic_ack.rstrip())

    symptoms = ", ".join(result.user_input.symptoms) if result.user_input.symptoms else "말씀해 주신 증상"
    lines.append(f"지금 말씀해 주신 **{symptoms}** 기준으로 일반의약품 후보를 살펴봤어요.")
    lines.append("")

    if result.symptom_context:
        tip = result.symptom_context[0].document.replace("\n", " ")[:100]
        lines.append(f"참고로, 증상 관련 안내 자료에서 이런 내용도 확인됐어요: {tip}")
        lines.append("")

    if not decision.recommended:
        lines.append(
            "지금 정보로는 안전하게 추천드릴 만한 일반의약품을 찾기 어려워요. "
            "증상이 계속되거나 심해지면 약사·의료진 상담을 권해드려요."
        )
        return "\n".join(lines)

    top = decision.recommended[0]
    drug = top.retrieval.drug
    matched = ", ".join(top.retrieval.matched_symptoms) if top.retrieval.matched_symptoms else symptoms
    lines.append(f"**1순위로 {drug.name_ko}** 을(를) 고려해 볼 수 있어요.")
    if matched:
        lines.append(f"(증상 연관: {matched})")
    lines.append("")
    lines.append(f"**왜 이 약인가요?** {drug.indications}")
    lines.append(f"**복용법** {drug.dosage}")
    if drug.warnings:
        lines.append(f"**주의** {drug.warnings}")
    if top.risk_level in {"medium", "high"}:
        lines.append(
            "**안내** 현재 상태(음주·기저질환 등)를 고려하면 주의가 필요할 수 있어요. "
            "복용 전 약사 상담을 권해드려요."
        )

    if len(decision.recommended) > 1:
        others = ", ".join(item.retrieval.drug.name_ko for item in decision.recommended[1:])
        lines.append(f"\n다른 후보로는 {others}도 있어요. \"다른 약은요?\"라고 물어보시면 설명해 드릴게요.")

    lines.append("")
    lines.append("궁금한 점 있으면 이어서 물어보세요. (예: 왜 이 약인가요? / 부작용은?)")
    lines.append("")
    lines.append("_※ 참고용 안내이며, 실제 복약은 의사·약사 상담이 우선입니다._")
    return "\n".join(lines)


def format_follow_up_why(result: PipelineResult) -> str:
    if not result.decision.recommended:
        return "아직 추천된 약이 없어 근거를 설명드리기 어렵습니다."
    top = result.decision.recommended[0]
    drug = top.retrieval.drug
    reasons = top.rerank_reasons or top.retrieval.reasons
    lines = [f"**{drug.name_ko}** 을(를) 1순위로 본 핵심 이유는 아래와 같아요.", ""]
    for reason in reasons[:4]:
        lines.append(f"• {reason}")
    if top.retrieval.chroma_evidence:
        hit = max(top.retrieval.chroma_evidence, key=lambda x: x.relevance)
        lines.append(f"• 의료 지식 DB에서도 관련 근거를 찾았어요 ({hit.chunk_id})")
    return "\n".join(lines)


def format_follow_up_alternative(result: PipelineResult) -> str:
    recs = result.decision.recommended
    if len(recs) < 2:
        rejected = result.decision.rejected[:2]
        if not rejected:
            return "현재 기준으로 제시할 대체 후보가 충분하지 않습니다."
        alt = rejected[0]
        drug = alt.retrieval.drug
        return (
            f"1순위 외 참고 후보로 {drug.name_ko}을(를) 검토할 수 있으나, "
            f"위험도({alt.risk_level}) 또는 점수({alt.final_score:.1f}) 때문에 우선순위가 낮습니다.\n"
            f"적응증: {drug.indications}"
        )
    alt = recs[1]
    drug = alt.retrieval.drug
    return (
        f"대안 후보로 {drug.name_ko}을(를) 고려할 수 있습니다.\n"
        f"· 적응증: {drug.indications}\n"
        f"· 복용법: {drug.dosage}\n"
        f"· 주의: {drug.warnings or '정보 없음'}"
    )


def format_follow_up_safety(result: PipelineResult) -> str:
    if not result.decision.recommended:
        return "추천 약이 없어 주의사항을 안내드리기 어렵습니다."
    drug = result.decision.recommended[0].retrieval.drug
    lines = [
        f"{drug.name_ko} 복용 시 참고할 주의사항입니다.",
        "",
        drug.warnings or "등록된 주의사항 텍스트가 없습니다.",
        "",
        "현재 복용 중인 약, 알레르기, 기저질환과의 상호작용도 함께 고려해야 합니다.",
    ]
    return "\n".join(lines)
