from __future__ import annotations

from typing import List

from models import ChromaEvidence, RetrievalResult, SafetyResult, UserInput


def build_emergency_response(user_input: UserInput, safety_result: SafetyResult) -> str:
    lines: List[str] = []
    lines.append("[안전성 우선 안내]")
    lines.append("입력된 정보 기준으로 즉시 전문의 상담 또는 의료기관 방문이 우선될 수 있습니다.")

    if safety_result.red_flag_symptoms:
        lines.append(f"- 감지된 위험 증상: {', '.join(safety_result.red_flag_symptoms)}")

    if safety_result.general_warnings:
        lines.append("- 참고 정보:")
        for warning in safety_result.general_warnings:
            lines.append(f"  - {warning}")

    lines.append("")
    lines.append("약 추천보다 안전성 확인이 우선입니다.")
    return "\n".join(lines)


def build_normal_response(
    user_input: UserInput,
    results: List[RetrievalResult],
    global_safety: SafetyResult,
    per_drug_safety: List[SafetyResult],
    symptom_context: List[ChromaEvidence] | None = None,
    use_chroma: bool = True,
) -> str:
    lines: List[str] = []
    lines.append("[입력 정보]")
    lines.append(f"- 증상: {', '.join(user_input.symptoms) if user_input.symptoms else '없음'}")
    lines.append(f"- 현재 복용 약 ID: {', '.join(user_input.current_drug_ids) if user_input.current_drug_ids else '없음'}")
    lines.append(f"- 현재 복용 약 이름: {', '.join(user_input.current_drug_names) if user_input.current_drug_names else '없음'}")
    lines.append(f"- 알레르기: {', '.join(user_input.allergies) if user_input.allergies else '없음'}")
    lines.append(f"- 기저/특이 상태: {', '.join(user_input.conditions) if user_input.conditions else '없음'}")
    lines.append("")

    if use_chroma and symptom_context:
        lines.append("[ChromaDB 증상 참고]")
        for item in symptom_context:
            preview = item.document.replace("\n", " ")[:160]
            lines.append(f"- ({item.metadata.get('chunk_type', 'symptom')}) {preview}")
        lines.append("")

    if not results:
        lines.append("[검색 결과]")
        lines.append("관련 약 후보를 찾지 못했습니다.")
        return "\n".join(lines)

    lines.append("[추천 후보]")
    for idx, (result, safety) in enumerate(zip(results, per_drug_safety), start=1):
        drug = result.drug
        lines.append(f"{idx}. {drug.name_ko} ({drug.drug_id})")
        lines.append(f"   - 점수: {result.score:.1f}")
        lines.append(f"   - 적응증: {drug.indications}")
        lines.append(f"   - 복용법: {drug.dosage}")
        lines.append(f"   - 주의사항: {drug.warnings if drug.warnings else '정보 없음'}")
        lines.append(f"   - 매칭 증상: {', '.join(result.matched_symptoms) if result.matched_symptoms else '없음'}")
        lines.append(f"   - 추천 근거: {'; '.join(result.reasons) if result.reasons else '없음'}")

        if result.chroma_evidence:
            top_hit = max(result.chroma_evidence, key=lambda x: x.relevance)
            preview = top_hit.document.replace("\n", " ")[:120]
            lines.append(
                f"   - ChromaDB 근거: {top_hit.chunk_id} "
                f"(유사도 {top_hit.relevance:.2f}) {preview}"
            )

        if safety.interaction_warnings or safety.contraindication_warnings:
            lines.append("   - 안전성 경고:")
            for item in safety.interaction_warnings + safety.contraindication_warnings:
                lines.append(f"     - {item}")

        lines.append("")

    lines.append("[전체 안전성 참고]")
    if global_safety.general_warnings:
        for warning in global_safety.general_warnings:
            lines.append(f"- {warning}")
    else:
        lines.append("- symptom DB 상 추가 안전성 정보 없음")

    lines.append("")
    lines.append("[주의]")
    if use_chroma:
        lines.append("- 약물 후보는 규칙 기반 점수 + ChromaDB(medical_knowledge) 검색을 함께 사용했습니다.")
    else:
        lines.append("- 약물 후보는 JSON 기반 규칙 검색만 사용했습니다.")
    lines.append("- 실제 복약 판단은 의사/약사 상담이 우선입니다.")

    return "\n".join(lines)