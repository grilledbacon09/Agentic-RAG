"""OpenAI 기반 대화 보조 (증상 추출·응답 자연화)."""

from __future__ import annotations

import json
import os
import re
from typing import List, Optional

from dotenv import load_dotenv
from prompts import CONVERSATION_SYSTEM_PROMPT

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))
load_dotenv(os.path.join(_PROJECT_ROOT, "database", ".env"))


def get_api_key() -> str:
    return (os.getenv("OPENAI_API_KEY") or "").strip()


def is_llm_enabled() -> bool:
    flag = os.getenv("USE_LLM", "true").lower() in {"1", "true", "yes"}
    return flag and bool(get_api_key())


def _client():
    from openai import OpenAI
    return OpenAI(api_key=get_api_key())


def extract_symptoms_llm(
    message: str,
    known_symptoms: List[str],
    *,
    model: str = "gpt-4o-mini",
) -> Optional[List[str]]:
    if not is_llm_enabled():
        return None

    sample = ", ".join(sorted(set(known_symptoms))[:80])
    prompt = (
        "사용자 문장에서 현재 불편한 의학 증상만 추출하세요. "
        "가능하면 아래 목록에 있는 이름을 우선 사용하세요. "
        "해당 없으면 빈 배열을 반환하세요.\n"
        f"후보 예시: {sample}\n"
        f"사용자: {message}\n"
        'JSON만 출력: {"symptoms":["..."]}'
    )
    try:
        resp = _client().chat.completions.create(
            model=model,
            temperature=0,
            messages=[
                {"role": "system", "content": CONVERSATION_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        text = (resp.choices[0].message.content or "").strip()
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        data = json.loads(match.group())
        symptoms = data.get("symptoms") or []
        return [s.strip() for s in symptoms if isinstance(s, str) and s.strip()]
    except Exception:
        return None


def polish_response_llm(
    draft: str,
    user_message: str,
    *,
    model: str = "gpt-4o-mini",
) -> Optional[str]:
    if not is_llm_enabled():
        return None

    prompt = (
        "아래는 의약품 복약 상담 챗봇의 초안입니다. "
        "ChatGPT처럼 자연스럽고 따뜻한 한국어로 다듬어 주세요.\n"
        "규칙:\n"
        "- 약 이름, 적응증, 복용법, 주의사항 숫자/사실은 초안과 동일하게 유지\n"
        "- 새로운 약이나 의학 사실을 추가하지 말 것\n"
        "- 2~4문단, 과도하게 길지 않게\n"
        f"사용자 최근 발화: {user_message}\n\n"
        f"초안:\n{draft}"
    )
    try:
        resp = _client().chat.completions.create(
            model=model,
            temperature=0.4,
            messages=[
                {"role": "system", "content": CONVERSATION_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        text = (resp.choices[0].message.content or "").strip()
        return text or None
    except Exception:
        return None
