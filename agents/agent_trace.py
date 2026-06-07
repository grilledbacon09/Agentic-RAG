from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class AgentStep:
    agent_name: str
    status: str
    messages: List[str] = field(default_factory=list)


_AGENT_LABELS = {
    "Query Agent": "입력 분석",
    "Clarification Agent": "정보 충분성 확인",
    "Safety Agent": "응급·안전 검사",
    "ChromaDB": "의료 지식 검색",
    "Retrieval Agent": "약 후보 검색",
    "Reranker": "점수·위험도 재정렬",
    "Reranker Agent": "점수·위험도 재정렬",
    "Recommendation Agent": "최종 추천 결정",
    "Validator": "결과 검증",
    "Validator Agent": "결과 검증",
}


def format_step_line(step: AgentStep, *, max_messages: int = 2) -> str:
    label = _AGENT_LABELS.get(step.agent_name, step.agent_name)
    lines = [f"• **{label}** — {step.status}"]
    shown = 0
    for message in step.messages:
        if shown >= max_messages:
            lines.append(f"  · … 외 {len(step.messages) - shown}건")
            break
        compact = message.replace("\n", " ").strip()
        if len(compact) > 120:
            compact = compact[:117] + "..."
        if compact:
            lines.append(f"  · {compact}")
            shown += 1
    return "\n".join(lines)


def format_agent_trace(steps: List[AgentStep]) -> str:
    lines: List[str] = ["[Multi-Agent Reasoning Trace]"]
    for step in steps:
        lines.append(f"[{step.agent_name}] {step.status}")
        for message in step.messages:
            lines.append(f"- {message}")
        lines.append("")
    return "\n".join(lines).rstrip()


def format_reasoning_for_user(steps: List[AgentStep], *, max_items: int = 4) -> str:
    if not steps:
        return ""
    lines: List[str] = ["🧠 **답변 준비 과정**"]
    for step in steps:
        block = format_step_line(step, max_messages=max_items)
        for line in block.splitlines():
            lines.append(line)
    return "\n".join(lines)


def format_turn_reasoning_lines(
    *,
    intent: str = "",
    phase: str = "",
    notes: List[str] | None = None,
) -> List[str]:
    lines: List[str] = []
    if intent:
        lines.append(f"• **의도 파악** — {intent}")
    if phase:
        lines.append(f"• **대화 단계** — {phase}")
    for note in notes or []:
        lines.append(f"  · {note}")
    return lines


def format_turn_reasoning(
    *,
    intent: str = "",
    phase: str = "",
    notes: List[str] | None = None,
) -> str:
    body = format_turn_reasoning_lines(intent=intent, phase=phase, notes=notes)
    if not body:
        return ""
    return "🧠 **답변 준비 과정**\n" + "\n".join(body)
