"""LLM 턴 오케스트레이션 — ChatGPT형 유연 대화."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import List, Optional

from llm_client import _client, is_llm_enabled
from models import ConversationSession, PipelineResult
from prompts import CONVERSATION_SYSTEM_PROMPT


@dataclass
class TurnPlan:
    is_off_topic: bool = False
    is_emergency: bool = False
    symptoms: List[str] = field(default_factory=list)
    current_drug_names: List[str] = field(default_factory=list)
    allergies: List[str] = field(default_factory=list)
    conditions: List[str] = field(default_factory=list)
    slots_answered: List[str] = field(default_factory=list)
    run_recommendation: bool = False
    reply: str = ""
    reasoning: str = ""


def _parse_json(text: str) -> Optional[dict]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return None


def _recent_dialogue(session: ConversationSession, limit: int = 8) -> str:
    lines: List[str] = []
    for turn in session.turns[-limit:]:
        role = "사용자" if turn.role == "user" else "상담사"
        lines.append(f"{role}: {turn.content.strip()}")
    return "\n".join(lines)


def build_session_context(session: ConversationSession) -> str:
    ui = session.user_input
    return (
        f"대화 단계: {session.phase.value}\n"
        f"대기 중인 슬롯: {session.pending_slot or '없음'}\n"
        f"확인된 슬롯: {', '.join(sorted(session.confirmed_slots)) or '없음'}\n"
        f"증상: {', '.join(ui.symptoms) or '미입력'}\n"
        f"복용 중 약: {', '.join(ui.current_drug_names + ui.current_drug_ids) or '미입력'}\n"
        f"알레르기: {', '.join(ui.allergies) or '미입력'}\n"
        f"기저/특이 상태: {', '.join(ui.conditions) or '미입력'}\n"
        f"\n[최근 대화]\n{_recent_dialogue(session)}"
    )


def orchestrate_turn_llm(
    user_message: str,
    session: ConversationSession,
    *,
    has_recommendation: bool = False,
    model: str = "gpt-4o-mini",
) -> Optional[TurnPlan]:
    if not is_llm_enabled():
        return None

    rec_hint = ""
    if has_recommendation:
        rec_hint = "이미 약 추천이 완료된 follow-up 대화입니다. 질문에 맞게 설명하세요."

    prompt = f"""{rec_hint}

[현재 세션]
{build_session_context(session)}

[사용자 이번 발화]
{user_message}

위 맥락에서 사용자 발화를 분석하고 JSON만 출력하세요.

{{
  "is_off_topic": false,
  "is_emergency": false,
  "symptoms": ["추출된 증상"],
  "current_drug_names": ["복용 중인 약/성분명"],
  "allergies": ["알레르기만. 복용 중인 약은 넣지 말 것"],
  "conditions": ["기저질환·임신·음주 등"],
  "slots_answered": ["symptoms"|"current_meds"|"allergies"|"conditions"],
  "run_recommendation": false,
  "reply": "사용자에게 보여줄 자연스러운 한국어 답변",
  "reasoning": "내부 판단 한 줄"
}}

규칙:
1. 정치·역사·코딩 등 비의료 주제 → is_off_topic=true, reply에서 정중히 거절 후 상담 유도
2. "먹고있어/복용중" 약물 → current_drug_names (알레르기 아님)
3. "타이레놀 같이?", "괜찮을까?" 같은 질문 → reply에서 일반 OTC 상담 관점으로 설명 (확정적 처방 금지)
4. 슬롯 질문에 엉뚱한 답(예: 복용약 질문에 기관지염) → conditions에 반영하고 reply에서 자연스럽게 이해했다고 말한 뒤 부족한 정보 1가지만 추가 질문
5. 증상·복용약·알레르기·기저상태가 충분하면 run_recommendation=true
6. 응급 징후(벼락 두통, 의식저하 등) → is_emergency=true
7. reply는 ChatGPT처럼 따뜻하고 구체적으로. 같은 질문 기계적으로 반복하지 말 것
8. slots_answered: 이번 발화로 채워진 슬롯만
"""

    try:
        resp = _client().chat.completions.create(
            model=model,
            temperature=0.3,
            messages=[
                {"role": "system", "content": CONVERSATION_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        data = _parse_json((resp.choices[0].message.content or "").strip())
        if not data:
            return None
        return TurnPlan(
            is_off_topic=bool(data.get("is_off_topic")),
            is_emergency=bool(data.get("is_emergency")),
            symptoms=[str(s).strip() for s in (data.get("symptoms") or []) if str(s).strip()],
            current_drug_names=[
                str(s).strip() for s in (data.get("current_drug_names") or []) if str(s).strip()
            ],
            allergies=[str(s).strip() for s in (data.get("allergies") or []) if str(s).strip()],
            conditions=[str(s).strip() for s in (data.get("conditions") or []) if str(s).strip()],
            slots_answered=[
                str(s).strip()
                for s in (data.get("slots_answered") or [])
                if str(s).strip() in {"symptoms", "current_meds", "allergies", "conditions"}
            ],
            run_recommendation=bool(data.get("run_recommendation")),
            reply=str(data.get("reply") or "").strip(),
            reasoning=str(data.get("reasoning") or "").strip(),
        )
    except Exception:
        return None


def generate_rag_reply_llm(
    user_message: str,
    session: ConversationSession,
    pipeline_result: PipelineResult,
    draft_message: str,
    *,
    model: str = "gpt-4o-mini",
) -> Optional[str]:
    if not is_llm_enabled():
        return None

    prompt = f"""아래 [RAG 초안]은 검색·안전성 파이프라인 결과입니다. 이 사실만 근거로 사용자에게 자연스럽게 답하세요.

규칙:
- 약 이름·용량·주의사항은 초안과 동일하게 유지
- 새 약/새 의학 사실 추가 금지
- 2~4문단, ChatGPT처럼 대화체

[세션]
{build_session_context(session)}

[사용자]
{user_message}

[RAG 초안]
{draft_message}
"""
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
