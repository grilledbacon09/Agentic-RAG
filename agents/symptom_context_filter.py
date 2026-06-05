from __future__ import annotations

import re

from models import ChromaEvidence, UserInput

BODY_CUE_EXCLUSIONS: dict[str, tuple[str, ...]] = {
    "배": ("음낭", "생식", "회음", "음부", "고환", "음경"),
    "복": ("음낭", "생식", "회음", "음부", "고환"),
    "속": ("음낭", "생식", "회음"),
    "목": ("음낭", "생식", "회음", "음부", "고환", "복부", "배"),
    "머리": ("음낭", "생식", "회음", "음부"),
    "허리": ("음낭", "생식", "회음", "음부"),
}

RED_FLAG_DOC_CUES = ("벼락 두통", "급성 중증", "응급", "즉시 의사", "즉시 병원")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").lower())


def _body_cues(user_text: str, symptoms: list[str]) -> set[str]:
    text = _normalize(user_text + " " + " ".join(symptoms))
    cues: set[str] = set()
    for key in BODY_CUE_EXCLUSIONS:
        if key in text:
            cues.add(key)
    if "목" in text and any(k in text for k in ("아파", "아프", "통증", "인후")):
        cues.add("목")
    if "배" in text:
        cues.add("배")
    if "머리" in text:
        cues.add("머리")
    return cues


def _is_relevant_hit(
    hit: ChromaEvidence,
    *,
    user_text: str,
    user_input: UserInput,
) -> bool:
    doc = (hit.document or "").lower()
    entity = str((hit.metadata or {}).get("entity_name", "")).lower()
    combined = f"{entity} {doc}"
    cues = _body_cues(user_text, user_input.symptoms)

    for cue in cues:
        for bad in BODY_CUE_EXCLUSIONS.get(cue, ()):
            if bad in combined and bad not in _normalize(user_text):
                return False

    if any(flag in combined for flag in RED_FLAG_DOC_CUES):
        user_norm = _normalize(user_text)
        if not any(flag.replace(" ", "") in user_norm for flag in ("벼락", "갑작", "응급", "의식")):
            if hit.metadata.get("chunk_type") == "cause":
                return False

    for symptom in user_input.symptoms:
        s = symptom.strip().lower()
        if s and len(s) >= 2 and s in combined:
            return True

    if cues:
        for cue in cues:
            if cue in combined:
                return True
        return False

    return True


def filter_symptom_context(
    hits: list[ChromaEvidence],
    user_input: UserInput,
    *,
    user_text: str = "",
    top_n: int = 2,
) -> list[ChromaEvidence]:
    filtered = [
        hit for hit in hits
        if _is_relevant_hit(hit, user_text=user_text, user_input=user_input)
    ]
    if not filtered:
        return []
    filtered.sort(key=lambda h: h.relevance, reverse=True)
    return filtered[:top_n]
