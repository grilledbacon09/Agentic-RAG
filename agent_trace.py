from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class AgentStep:
    agent_name: str
    status: str
    messages: List[str] = field(default_factory=list)


def format_agent_trace(steps: List[AgentStep]) -> str:
    lines: List[str] = ["[Multi-Agent Reasoning Trace]"]
    for step in steps:
        lines.append(f"[{step.agent_name}] {step.status}")
        for message in step.messages:
            lines.append(f"- {message}")
        lines.append("")
    return "\n".join(lines).rstrip()
