from __future__ import annotations

from typing import List, Optional

from config import AppConfig, load_config
from generator import build_emergency_response, build_normal_response
from models import Drug, Symptom, UserInput
from retriever import retrieve_symptom_context, retrieve_top_k
from safety import check_symptom_red_flags, evaluate_drug_safety


def run_pipeline(
    user_input: UserInput,
    drugs: List[Drug],
    symptoms: List[Symptom],
    config: Optional[AppConfig] = None,
) -> str:
    cfg = config or load_config()
    global_safety = check_symptom_red_flags(user_input, symptoms)

    if global_safety.has_red_flag:
        return build_emergency_response(user_input, global_safety)

    symptom_context = (
        retrieve_symptom_context(user_input, top_n=2)
        if cfg.use_chroma
        else []
    )

    retrieved = retrieve_top_k(
        user_input,
        drugs,
        top_k=cfg.top_k,
        use_chroma=cfg.use_chroma,
        chroma_top_n=cfg.chroma_top_n,
        chroma_weight=cfg.chroma_score_weight,
        min_score=cfg.min_retrieval_score,
    )
    per_drug_safety = [evaluate_drug_safety(user_input, result.drug) for result in retrieved]

    return build_normal_response(
        user_input=user_input,
        results=retrieved,
        global_safety=global_safety,
        per_drug_safety=per_drug_safety,
        symptom_context=symptom_context,
        use_chroma=cfg.use_chroma,
    )
