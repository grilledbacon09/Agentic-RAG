"""Multi-Agent Reasoning Trace — 구조화된 Decision Trace (CoT 아님)."""

from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from agents.agent_trace import AgentStep

if TYPE_CHECKING:
    from agents.integrations.types import DataBackend, DataProvenance

_logger = logging.getLogger(__name__)

# 비밀정보 마스킹 패턴
_SECRET_PATTERNS = (
    re.compile(r"(?i)(password|passwd|api[_-]?key|secret|token)\s*[:=]\s*\S+"),
    re.compile(r"neo4j(\+s)?://[^:\s]+:[^@\s]+@"),
    re.compile(r"KakaoAK\s+\S+"),
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _truncate(text: str, limit: int = 240) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def sanitize_trace_value(value: Any) -> Any:
    """Trace JSON 직렬화 전 비밀정보 제거."""
    if isinstance(value, str):
        out = value
        for pat in _SECRET_PATTERNS:
            out = pat.sub("[REDACTED]", out)
        return out
    if isinstance(value, dict):
        return {k: sanitize_trace_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_trace_value(v) for v in value]
    return value


@dataclass
class ReasoningTraceStep:
    step_id: str
    agent: str
    status: str  # success | skipped | failed | warning
    summary: str = ""
    input_summary: Dict[str, Any] = field(default_factory=dict)
    decision: Dict[str, Any] = field(default_factory=dict)
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    data_sources: List[str] = field(default_factory=list)
    started_at: str = ""
    duration_ms: int = 0
    duration_measured: bool = False
    input_summary_ref: str = ""
    warnings: List[str] = field(default_factory=list)
    order: int = 0

    def to_dict(self) -> Dict[str, Any]:
        raw = asdict(self)
        return sanitize_trace_value(raw)


@dataclass
class ReasoningTrace:
    """파이프라인 1회 실행의 전체 Trace (WEB 타임라인용)."""

    trace_id: str
    pipeline_status: str  # completed | emergency_stop | partial
    started_at: str
    completed_at: str = ""
    duration_ms: int = 0
    steps: List[ReasoningTraceStep] = field(default_factory=list)
    data_provenance: Dict[str, Any] = field(default_factory=dict)
    user_context: Dict[str, Any] = field(default_factory=dict)
    disclaimer: str = (
        "본 Trace는 시스템이 실제 수행한 검색·판정·검증 단계를 기록합니다. "
        "LLM 내부 추론이 아니며, PostgreSQL hit·Neo4j OK가 추천/복용 안전을 보장하지 않습니다."
    )

    def to_dict(self) -> Dict[str, Any]:
        return sanitize_trace_value(
            {
                "trace_id": self.trace_id,
                "pipeline_status": self.pipeline_status,
                "started_at": self.started_at,
                "completed_at": self.completed_at,
                "duration_ms": self.duration_ms,
                "steps": [s.to_dict() for s in self.steps],
                "data_provenance": self.data_provenance,
                "user_context": self.user_context,
                "disclaimer": self.disclaimer,
            }
        )


class ReasoningTraceCollector:
    """파이프라인 실행 중 단계별 Trace 수집."""

    def __init__(self) -> None:
        self.trace_id = str(uuid.uuid4())
        self.started_at = _utc_now_iso()
        self._t0 = time.perf_counter()
        self.steps: List[ReasoningTraceStep] = []
        self._order = 0
        self.user_context: Dict[str, Any] = {}

    def add_step(
        self,
        *,
        step_id: str,
        agent: str,
        status: str,
        summary: str,
        input_summary: Optional[Dict[str, Any]] = None,
        decision: Optional[Dict[str, Any]] = None,
        evidence: Optional[List[Dict[str, Any]]] = None,
        data_sources: Optional[List[str]] = None,
        warnings: Optional[List[str]] = None,
        duration_ms: int = 0,
        duration_measured: bool = False,
        input_summary_ref: str = "",
        started_at: Optional[str] = None,
    ) -> ReasoningTraceStep:
        self._order += 1
        step = ReasoningTraceStep(
            step_id=step_id,
            agent=agent,
            status=status,
            summary=summary,
            input_summary=input_summary or {},
            decision=decision or {},
            evidence=evidence or [],
            data_sources=data_sources or [],
            started_at=started_at or _utc_now_iso(),
            duration_ms=max(0, duration_ms),
            duration_measured=duration_measured,
            input_summary_ref=input_summary_ref,
            warnings=warnings or [],
            order=self._order,
        )
        self.steps.append(step)
        return step

    def track(
        self,
        step_id: str,
        agent: str,
    ) -> "_StepTimer":
        return _StepTimer(self, step_id, agent)

    def add_skipped_pipeline_tail(self, from_step: str) -> None:
        tail = [
            ("retrieval_agent", "Retrieval Agent"),
            ("reranker", "Reranker"),
            ("recommendation_agent", "Recommendation Agent"),
            ("validator", "Validator"),
        ]
        skip = False
        for sid, agent in tail:
            if sid == from_step:
                skip = True
            if skip:
                self.add_step(
                    step_id=sid,
                    agent=agent,
                    status="skipped",
                    summary="응급 분기로 인해 이 단계는 실행되지 않았습니다.",
                    warnings=["pipeline_short_circuit=emergency"],
                )

    def finalize(
        self,
        *,
        pipeline_status: str,
        data_provenance: Optional[Dict[str, Any]] = None,
    ) -> ReasoningTrace:
        elapsed = int((time.perf_counter() - self._t0) * 1000)
        return ReasoningTrace(
            trace_id=self.trace_id,
            pipeline_status=pipeline_status,
            started_at=self.started_at,
            completed_at=_utc_now_iso(),
            duration_ms=elapsed,
            steps=list(self.steps),
            data_provenance=data_provenance or {},
            user_context=dict(self.user_context),
        )

    def to_agent_steps(self) -> List[AgentStep]:
        """기존 format_agent_trace / debug_trace 호환."""
        out: List[AgentStep] = []
        for s in self.steps:
            messages = [s.summary] if s.summary else []
            for w in s.warnings[:4]:
                messages.append(f"⚠ {w}")
            if s.decision:
                for k, v in list(s.decision.items())[:5]:
                    messages.append(f"{k}: {v}")
            out.append(AgentStep(s.agent, f"{s.status} ({s.duration_ms}ms)", messages))
        return out


class _StepTimer:
    def __init__(self, collector: ReasoningTraceCollector, step_id: str, agent: str) -> None:
        self.collector = collector
        self.step_id = step_id
        self.agent = agent
        self.started_at = _utc_now_iso()
        self._t0 = time.perf_counter()
        self.input_summary: Dict[str, Any] = {}
        self.decision: Dict[str, Any] = {}
        self.evidence: List[Dict[str, Any]] = []
        self.data_sources: List[str] = []
        self.warnings: List[str] = []
        self.summary = ""
        self.status = "success"
        self.measured_duration_ms: Optional[int] = None
        self.input_summary_ref = "trace.user_context"

    def complete(self) -> ReasoningTraceStep:
        if self.measured_duration_ms is not None:
            ms = max(0, self.measured_duration_ms)
            measured = True
        else:
            ms = int((time.perf_counter() - self._t0) * 1000)
            measured = ms > 0
        return self.collector.add_step(
            step_id=self.step_id,
            agent=self.agent,
            status=self.status,
            summary=self.summary,
            input_summary=self.input_summary,
            decision=self.decision,
            evidence=self.evidence,
            data_sources=self.data_sources,
            warnings=self.warnings,
            duration_ms=ms,
            duration_measured=measured,
            input_summary_ref=self.input_summary_ref,
            started_at=self.started_at,
        )


def user_input_summary(user_input) -> Dict[str, Any]:
    return {
        "symptoms": list(user_input.symptoms or []),
        "current_drug_ids": list(user_input.current_drug_ids or []),
        "current_drug_names": list(user_input.current_drug_names or []),
        "allergies": list(user_input.allergies or []),
        "conditions": list(user_input.conditions or []),
        "age": user_input.age,
    }


def _field_trace_status(values: List[str]) -> Dict[str, Any]:
    cleaned = [v for v in (values or []) if str(v).strip()]
    if not cleaned:
        return {
            "status": "unknown",
            "label": "미확인",
            "values": [],
        }
    if len(cleaned) == 1 and cleaned[0].strip() in ("없음", "none", "해당없음"):
        return {
            "status": "declared_none",
            "label": "없음(사용자 진술)",
            "values": cleaned,
        }
    return {
        "status": "provided",
        "label": ", ".join(cleaned),
        "values": cleaned,
    }


def build_trace_user_context(user_input, context_text: str = "") -> Dict[str, Any]:
    """Trace 최상단 공통 입력 요약 (Web 중복 렌더링 방지용)."""
    age = user_input.age
    age_block = (
        {"status": "provided", "label": str(age), "values": [age]}
        if age is not None
        else {"status": "unknown", "label": "미확인", "values": []}
    )
    ctx = (context_text or "").strip()
    return {
        "symptoms": _field_trace_status(list(user_input.symptoms or [])),
        "current_drug_ids": _field_trace_status(list(user_input.current_drug_ids or [])),
        "current_drug_names": _field_trace_status(list(user_input.current_drug_names or [])),
        "allergies": _field_trace_status(list(user_input.allergies or [])),
        "conditions": _field_trace_status(list(user_input.conditions or [])),
        "age": age_block,
        "latest_user_text": _truncate(ctx, 400) if ctx else "",
        "display_hint": "공통 입력 요약 — Agent별 input_summary 대신 이 블록을 우선 표시",
    }


def query_evidence_from_analysis(query_analysis, context_text: str = "") -> List[Dict[str, Any]]:
    ui = query_analysis.user_input
    ev: List[Dict[str, Any]] = []
    if ui.symptoms:
        ev.append(
            {
                "kind": "symptoms",
                "detail": f"구조화 증상: {', '.join(ui.symptoms)}",
                "source": "user_input",
            }
        )
    ctx = (context_text or "").strip()
    if ctx:
        ev.append(
            {
                "kind": "context_text",
                "detail": _truncate(ctx, 200),
                "source": "conversation_turn",
            }
        )
    if query_analysis.detected_terms:
        ev.append(
            {
                "kind": "catalog_terms",
                "detail": ", ".join(query_analysis.detected_terms[:8]),
                "source": "legacy_json_catalog",
            }
        )
    if query_analysis.unknown_terms:
        ev.append(
            {
                "kind": "unknown_terms",
                "detail": ", ".join(query_analysis.unknown_terms[:8]),
                "source": "catalog_lookup",
            }
        )
    for msg in query_analysis.messages[:3]:
        ev.append({"kind": "analysis_note", "detail": msg, "source": "query_agent"})
    return ev


def clarification_decision_enriched(user_input, clarification) -> Dict[str, Any]:
    critical_missing = not (user_input.symptoms or [])
    if not clarification.needs_clarification:
        mode = "none"
    elif critical_missing:
        mode = "required"
    else:
        mode = "recommended_optional"
    return {
        "needs_clarification": clarification.needs_clarification,
        "mode": mode,
        "can_proceed_with_recommendation": not critical_missing,
        "questions": clarification.questions[:5],
        "reasons": clarification.reasons[:5],
    }


def clarification_evidence(clarification, decision: Dict[str, Any]) -> List[Dict[str, Any]]:
    ev: List[Dict[str, Any]] = []
    for r in clarification.reasons[:5]:
        ev.append({"kind": "rule", "detail": r, "source": "clarification_agent"})
    if decision.get("mode") == "recommended_optional":
        ev.append(
            {
                "kind": "branch",
                "detail": "증상은 있으나 추가 질문 권장 — 파이프라인은 추천 단계까지 진행 가능",
                "source": "clarification_agent",
            }
        )
    return ev


def safety_evidence_from_red_flag(red_flag, user_input, context_text: str = "") -> List[Dict[str, Any]]:
    ev: List[Dict[str, Any]] = []
    combined = f"{context_text} {' '.join(user_input.symptoms or [])}".strip()
    if combined:
        ev.append(
            {
                "kind": "checked_text",
                "detail": _truncate(combined, 180),
                "source": "user_input",
            }
        )
    if red_flag.matched:
        for sig in red_flag.matched[:5]:
            ev.append({"kind": "red_flag_signal", "detail": sig, "source": "red_flag_rules"})
    else:
        ev.append(
            {
                "kind": "red_flag_scan",
                "detail": "입력·증상 텍스트에서 응급 red flag 키워드 미감지 (미확인 ≠ 안전)",
                "source": "red_flag_rules",
            }
        )
    for reason in (red_flag.reasons or [])[:4]:
        ev.append({"kind": "note", "detail": reason, "source": "safety_agent"})
    return ev


def recommendation_evidence_from_decision(decision, reranked) -> List[Dict[str, Any]]:
    ev: List[Dict[str, Any]] = []
    rerank_by_id = {item.retrieval.drug.drug_id: item for item in reranked}
    for rec in decision.recommended:
        drug = rec.retrieval.drug
        item = rerank_by_id.get(drug.drug_id)
        entry: Dict[str, Any] = {
            "kind": "recommended",
            "drug_id": drug.drug_id,
            "drug_name": drug.name_ko,
            "final_score": round(rec.final_score, 3),
            "risk_level": rec.risk_level,
        }
        if drug.indications:
            entry["indications_excerpt"] = _truncate(drug.indications, 120)
        if item:
            entry["rerank_reasons"] = list(item.rerank_reasons[:4])
        ev.append(entry)
    for rej in decision.rejected[:5]:
        ev.append(
            {
                "kind": "rejected",
                "drug_id": rej.retrieval.drug.drug_id,
                "drug_name": rej.retrieval.drug.name_ko,
                "blocked": rej.blocked,
                "risk_level": rej.risk_level,
                "reason_hints": [r for r in rej.rerank_reasons if "blocked" in r or "verdict" in r][:3],
            }
        )
    return ev


def validator_evidence_from_result(validation, decision) -> List[Dict[str, Any]]:
    ev: List[Dict[str, Any]] = []
    for check in validation.checks:
        ev.append({"kind": "check", "detail": check, "source": "validator"})
    for err in validation.errors:
        ev.append({"kind": "error", "detail": err, "source": "validator"})
    if not decision.recommended:
        ev.append(
            {
                "kind": "note",
                "detail": "추천 후보 없음 — validator는 빈 목록 기준으로 검증",
                "source": "validator",
            }
        )
    return ev


def parse_retrieval_attempt(notes: List[str]) -> Dict[str, Any]:
    joined = " ".join(notes)
    lower = joined.lower()
    attempt = {
        "postgresql_attempted": "postgresql" in lower or "de" in lower or "검색 실패" in joined,
        "postgresql_succeeded": False,
        "fallback_executed": "fallback" in lower or "legacy" in lower,
        "failure_kind": None,
        "failure_detail": None,
    }
    if "missing_dependency" in lower or "no module named" in lower:
        attempt["failure_kind"] = "missing_python_dependency"
    elif "연결" in joined or "connection" in lower:
        attempt["failure_kind"] = "connection"
    elif "검색 실패" in joined:
        attempt["failure_kind"] = "search_error"
    for note in notes:
        if note.startswith("PostgreSQL 검색 실패"):
            attempt["failure_detail"] = note[:200]
            break
    return attempt


def retrieval_evidence_from_results(items, *, max_snippet: int = 120) -> List[Dict[str, Any]]:
    ev: List[Dict[str, Any]] = []
    for item in items:
        r = item if hasattr(item, "drug") else item
        drug = r.drug if hasattr(r, "drug") else r
        score = getattr(r, "score", None)
        de_score = getattr(r, "de_score", None)
        catalog_match = getattr(r, "catalog_match", "catalog")
        src = getattr(r, "retrieval_source", "legacy_json")
        entry: Dict[str, Any] = {
            "drug_id": drug.drug_id,
            "drug_name": drug.name_ko,
            "retrieval_score": round(float(score), 4) if score is not None else None,
            "de_score": round(float(de_score), 4) if de_score is not None else None,
            "catalog_match": catalog_match,
            "retrieval_source": src,
        }
        if catalog_match == "stub":
            entry["note"] = "로컬 catalog 미매칭 — 상세·성분·용법 미확인"
        snippet = getattr(r, "de_document_snippet", None)
        if snippet:
            entry["document_snippet"] = _truncate(snippet, max_snippet)
        ev.append(entry)
    return ev


def reranker_evidence_from_results(reranked) -> List[Dict[str, Any]]:
    ev: List[Dict[str, Any]] = []
    for item in reranked:
        verdict = None
        safety_backend = None
        for reason in item.rerank_reasons:
            if reason.startswith("neo4j_verdict="):
                verdict = reason.split("=", 1)[1].strip()
            if reason.startswith("safety_backend="):
                safety_backend = reason.split("=", 1)[1].strip()
        ev.append(
            {
                "drug_id": item.retrieval.drug.drug_id,
                "drug_name": item.retrieval.drug.name_ko,
                "final_score": round(item.final_score, 3),
                "risk_level": item.risk_level,
                "blocked": item.blocked,
                "needs_extra_verification": item.needs_extra_verification,
                "neo4j_verdict": verdict,
                "safety_backend": safety_backend,
                "catalog_match": item.retrieval.catalog_match,
            }
        )
    return ev


def recommendation_decision_trace(decision) -> Dict[str, Any]:
    recommended = [
        {
            "drug_id": x.retrieval.drug.drug_id,
            "drug_name": x.retrieval.drug.name_ko,
            "final_score": round(x.final_score, 3),
            "risk_level": x.risk_level,
        }
        for x in decision.recommended
    ]
    rejected = [
        {
            "drug_id": x.retrieval.drug.drug_id,
            "drug_name": x.retrieval.drug.name_ko,
            "blocked": x.blocked,
            "needs_extra_verification": x.needs_extra_verification,
            "risk_level": x.risk_level,
            "reason_hints": [r for r in x.rerank_reasons if "blocked" in r or "stub" in r or "verdict" in r][:3],
        }
        for x in decision.rejected
    ]
    return {
        "recommended_count": len(recommended),
        "rejected_count": len(rejected),
        "recommended": recommended,
        "rejected": rejected,
        "messages": list(decision.messages),
    }


def compute_retrieval_data_sources(
    retrieved,
    retrieval_backend: "DataBackend",
    retrieval_notes: List[str],
) -> List[str]:
    """실제 hit의 retrieval_source와 notes 기준 (HYBRID라도 PostgreSQL 단정 금지)."""
    from agents.integrations.types import DataBackend

    hit_sources: List[str] = []
    seen: set[str] = set()
    for r in retrieved:
        src = (getattr(r, "retrieval_source", None) or DataBackend.LEGACY_JSON.value).strip().lower()
        if src not in seen:
            seen.add(src)
            hit_sources.append(src)

    notes_l = " ".join(retrieval_notes).lower()

    if not retrieved:
        if retrieval_backend == DataBackend.UNAVAILABLE:
            if "fallback" in notes_l or "legacy" in notes_l:
                return [DataBackend.LEGACY_JSON.value]
            return [DataBackend.UNAVAILABLE.value]
        return [retrieval_backend.value]

    sources = list(hit_sources)
    if retrieval_backend == DataBackend.HYBRID:
        if DataBackend.LEGACY_JSON.value not in sources and any(
            "legacy" in n.lower() or "보충" in n for n in retrieval_notes
        ):
            sources.append(DataBackend.LEGACY_JSON.value)
    return sources


def collect_safety_backends(reranked) -> List[str]:
    backends: List[str] = []
    for item in reranked:
        for reason in item.rerank_reasons:
            if reason.startswith("safety_backend="):
                raw = reason.split("=", 1)[1].strip()
                if raw not in backends:
                    backends.append(raw)
    return backends


def apply_safety_provenance(provenance: "DataProvenance", reranked) -> None:
    from agents.integrations.types import DataBackend

    backends = collect_safety_backends(reranked)
    provenance.safety_backends = list(backends)
    if not backends:
        return
    if len(backends) == 1:
        try:
            provenance.safety = DataBackend(backends[0])
        except ValueError:
            provenance.note(f"unknown safety_backend={backends[0]}")
        return
    provenance.safety = DataBackend.HYBRID
    provenance.note(f"safety_mixed={','.join(backends)}")


def legacy_messages_query(query_analysis) -> tuple[str, List[str]]:
    return "입력 분석 완료", list(query_analysis.messages)


def legacy_messages_clarification(clarification) -> tuple[str, List[str]]:
    if clarification.needs_clarification:
        status = "추가 확인 필요"
        messages = [f"Q. {q}" for q in clarification.questions]
        messages.extend(f"Reason: {r}" for r in clarification.reasons)
        return status, messages
    return "추가 질문 불필요", ["추천에 필요한 기본 정보가 충분합니다."]


@dataclass
class PipelineTraceBridge:
    """구조화 Trace와 legacy trace_steps/on_step 이중 기록 (오류 격리)."""

    enable_structured: bool
    trace_steps: List[AgentStep]
    on_step: Optional[Callable[[AgentStep], None]]
    collector: Optional[ReasoningTraceCollector] = None
    trace_errors: List[str] = field(default_factory=list)

    @classmethod
    def create(cls, config, trace_steps: List[AgentStep], on_step) -> "PipelineTraceBridge":
        enabled = bool(getattr(config, "enable_reasoning_trace", True))
        return cls(
            enable_structured=enabled,
            trace_steps=trace_steps,
            on_step=on_step,
            collector=ReasoningTraceCollector() if enabled else None,
        )

    def _record_trace_error(self, where: str, exc: BaseException) -> None:
        self.trace_errors.append(f"{where}:{type(exc).__name__}")
        if _logger.isEnabledFor(logging.DEBUG):
            _logger.debug("reasoning_trace isolated error at %s (%s)", where, type(exc).__name__)

    def emit_legacy(self, agent: str, status_line: str, messages: List[str]) -> None:
        step = AgentStep(agent, status_line, list(messages))
        self.trace_steps.append(step)
        if self.on_step:
            try:
                self.on_step(step)
            except Exception as exc:
                self._record_trace_error("on_step", exc)

    def emit_step(
        self,
        *,
        step_id: str,
        agent: str,
        legacy_status: str,
        legacy_messages: List[str],
        populate: Optional[Callable[[_StepTimer], None]] = None,
        measured_duration_ms: Optional[int] = None,
    ) -> None:
        if self.enable_structured and self.collector is not None:
            try:
                timer = self.collector.track(step_id, agent)
                if measured_duration_ms is not None:
                    timer.measured_duration_ms = measured_duration_ms
                if populate:
                    populate(timer)
                rstep = timer.complete()
                status_with_ms = f"{legacy_status} ({rstep.duration_ms}ms)"
                emit_dual(
                    self.collector,
                    self.trace_steps,
                    self.on_step,
                    rstep,
                    legacy_messages=legacy_messages,
                    legacy_status=status_with_ms,
                )
                return
            except Exception as exc:
                self._record_trace_error(f"emit_step({step_id})", exc)
        self.emit_legacy(agent, legacy_status, legacy_messages)

    def add_skipped_pipeline_tail(self, from_step: str) -> None:
        if not self.enable_structured or self.collector is None:
            return
        try:
            self.collector.add_skipped_pipeline_tail(from_step)
        except Exception as exc:
            self._record_trace_error("add_skipped_pipeline_tail", exc)

    def finalize(self, *, pipeline_status: str, data_provenance: Dict[str, Any]) -> Optional[dict]:
        if not self.enable_structured or self.collector is None:
            return None
        try:
            trace = self.collector.finalize(
                pipeline_status=pipeline_status,
                data_provenance=data_provenance,
            )
            return trace.to_dict()
        except Exception as exc:
            self._record_trace_error("finalize", exc)
            return None


def emit_dual(
    collector: Optional[ReasoningTraceCollector],
    legacy_steps: List[AgentStep],
    on_step: Optional[Callable[[AgentStep], None]],
    step: ReasoningTraceStep,
    *,
    legacy_messages: Optional[List[str]] = None,
    legacy_status: Optional[str] = None,
) -> None:
    """구조화 step 완료 후 legacy AgentStep 동기화 (debug_trace 메시지 우선)."""
    if legacy_messages is not None:
        messages = list(legacy_messages)
    else:
        messages = [step.summary] if step.summary else []
        for w in step.warnings[:3]:
            messages.append(f"⚠ {w}")
    status = legacy_status or f"{step.status} ({step.duration_ms}ms)"
    legacy = AgentStep(step.agent, status, messages)
    legacy_steps.append(legacy)
    if on_step:
        try:
            on_step(legacy)
        except Exception:
            if _logger.isEnabledFor(logging.DEBUG):
                _logger.debug("on_step callback failed", exc_info=True)
