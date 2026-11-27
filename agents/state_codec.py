"""JSON-only, allowlisted codec for the recommendation used by follow-up turns.

The worker is recreated per request, so the agent's previous pipeline result must
be stored alongside ConversationSession. Never deserialize Python pickle or
import class names supplied by a database payload.
"""
from dataclasses import fields, is_dataclass
from enum import Enum
from agents.models import Chunk, Drug, UserInput, SafetyResult, ChromaEvidence, RetrievalResult, PipelineResult
from agents.agent_trace import AgentStep
from agents.recommendation_agent import RecommendationDecision
from agents.reranker import RerankedResult
from agents.validator import ValidationResult
from agents.integrations.types import DataBackend, DataProvenance

_types = {cls.__name__: cls for cls in (Chunk, Drug, UserInput, SafetyResult, ChromaEvidence,
    RetrievalResult, PipelineResult, AgentStep, RecommendationDecision, RerankedResult,
    ValidationResult, DataProvenance, DataBackend)}


def encode(value):
    if isinstance(value, Enum):
        if type(value).__name__ not in _types:
            raise ValueError('Unsupported state enum')
        return {'kind': 'enum', 'type': type(value).__name__, 'value': value.value}
    if is_dataclass(value):
        if type(value).__name__ not in _types:
            raise ValueError('Unsupported state type')
        return {'kind': 'record', 'type': type(value).__name__,
                'fields': {f.name: encode(getattr(value, f.name)) for f in fields(value)}}
    if isinstance(value, dict):
        return {'kind': 'dict', 'items': {key: encode(item) for key, item in value.items()}}
    if isinstance(value, (list, tuple)):
        return [encode(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError('Unsupported state value')


def decode(value):
    if isinstance(value, list):
        return [decode(item) for item in value]
    if not isinstance(value, dict):
        return value
    if value.get('kind') == 'dict':
        return {key: decode(item) for key, item in value['items'].items()}
    cls = _types.get(value.get('type'))
    if cls is None:
        raise ValueError('Unsupported state type')
    if value['kind'] == 'enum' and issubclass(cls, Enum):
        return cls(value['value'])
    if value['kind'] == 'record' and is_dataclass(cls):
        return cls(**{key: decode(item) for key, item in value['fields'].items()})
    raise ValueError('Invalid state encoding')
