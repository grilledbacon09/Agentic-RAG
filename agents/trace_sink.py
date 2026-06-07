"""Reasoning trace 실시간 출력 (터미널/웹 공통 인터페이스)."""

from __future__ import annotations

import sys
from typing import Optional, Protocol

from agent_trace import AgentStep, format_step_line


class TraceSink(Protocol):
    def begin(self) -> None: ...
    def step(self, line: str) -> None: ...
    def end(self) -> None: ...


class ConsoleTraceSink:
    """각 agent 단계가 끝날 때마다 즉시 터미널에 출력합니다."""

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self._started = False

    def begin(self) -> None:
        if not self.enabled:
            return
        self._started = True
        self._write("🧠 **답변 준비 중...**")

    def step(self, line: str) -> None:
        if not self.enabled or not line:
            return
        if not self._started:
            self.begin()
        self._write(line)

    def step_agent(self, step: AgentStep) -> None:
        self.step(format_step_line(step))

    def end(self) -> None:
        self._started = False

    def _write(self, text: str) -> None:
        print(text, flush=True)


class NullTraceSink:
    def begin(self) -> None:
        pass

    def step(self, line: str) -> None:
        pass

    def end(self) -> None:
        pass


def create_trace_sink(*, enabled: bool = True) -> TraceSink:
    return ConsoleTraceSink(enabled=enabled) if enabled else NullTraceSink()
