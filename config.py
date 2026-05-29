from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class AppConfig:
    """프로젝트 전역 설정값.

    Vector DB 도입 전에는 rule-based/static RAG 설정만 관리하고,
    이후 OPENAI_API_KEY, VECTOR_DB_URL 등을 이 파일에 모아두면 된다.
    """

    base_dir: Path
    data_dir: Path
    top_k: int = 3
    min_retrieval_score: float = 0.1
    clarification_min_symptoms: int = 1
    enable_agent_trace: bool = True


def load_config() -> AppConfig:
    base_dir = Path(__file__).resolve().parent
    data_dir = Path(os.getenv("DATA_DIR", base_dir / "data"))
    top_k = int(os.getenv("TOP_K", "3"))
    min_score = float(os.getenv("MIN_RETRIEVAL_SCORE", "0.1"))

    return AppConfig(
        base_dir=base_dir,
        data_dir=data_dir,
        top_k=top_k,
        min_retrieval_score=min_score,
    )
