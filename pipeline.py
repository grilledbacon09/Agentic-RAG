from __future__ import annotations

from typing import List, Tuple

from generator import build_emergency_response, build_normal_response
from models import Drug, Symptom, UserInput
from retriever import retrieve_top_k
from safety import check_symptom_red_flags, evaluate_drug_safety


def run_pipeline(user_input: UserInput, drugs: List[Drug], symptoms: List[Symptom]) -> str:
    global_safety = check_symptom_red_flags(user_input, symptoms)

    if global_safety.has_red_flag:
        return build_emergency_response(user_input, global_safety)

    retrieved = retrieve_top_k(user_input, drugs, top_k=3)
    per_drug_safety = [evaluate_drug_safety(user_input, result.drug) for result in retrieved]

    return build_normal_response(
        user_input=user_input,
        results=retrieved,
        global_safety=global_safety,
        per_drug_safety=per_drug_safety,
    )