from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Chunk:
    chunk_type: str
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Drug:
    drug_id: str
    name_ko: str
    name_en: Optional[str]
    ingredient: List[str]
    indications: str
    dosage: str
    warnings: str
    category: Optional[str]
    updated_date: Optional[str]
    combination_contraindication: List[str]
    parent_text: str
    child_chunks: List[Chunk] = field(default_factory=list)


@dataclass
class Symptom:
    symptom_id: str
    name: str
    is_red_flag: Optional[bool]
    urgency: Optional[str]
    context: Optional[str]
    action_guide: Optional[str]


@dataclass
class UserInput:
    symptoms: List[str]
    current_drug_ids: List[str] = field(default_factory=list)
    current_drug_names: List[str] = field(default_factory=list)
    allergies: List[str] = field(default_factory=list)
    conditions: List[str] = field(default_factory=list)
    age: Optional[int] = None


@dataclass
class SafetyResult:
    has_red_flag: bool
    red_flag_symptoms: List[str] = field(default_factory=list)
    interaction_warnings: List[str] = field(default_factory=list)
    contraindication_warnings: List[str] = field(default_factory=list)
    general_warnings: List[str] = field(default_factory=list)


@dataclass
class RetrievalResult:
    drug: Drug
    score: float
    matched_symptoms: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)