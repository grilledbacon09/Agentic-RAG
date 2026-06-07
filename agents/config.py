from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class AppConfig:
    """프로젝트 전역 설정값."""

    base_dir: Path
    data_dir: Path
    de_root: Path
    top_k: int = 3
    min_retrieval_score: float = 0.1
    clarification_min_symptoms: int = 1
    enable_agent_trace: bool = False
    show_reasoning: bool = True
    use_chroma: bool = True
    chroma_top_n: int = 10
    chroma_score_weight: float = 5.0
    chroma_host: str = "localhost"
    chroma_port: int = 8000


def load_config() -> AppConfig:
    base_dir = Path(__file__).resolve().parent
    project_root = base_dir.parent
    data_dir = Path(os.getenv("DATA_DIR", project_root / "data"))
    de_root = Path(os.getenv("DE_ROOT", project_root / "database"))

    return AppConfig(
        base_dir=base_dir,
        data_dir=data_dir,
        de_root=de_root,
        top_k=int(os.getenv("TOP_K", "3")),
        min_retrieval_score=float(os.getenv("MIN_RETRIEVAL_SCORE", "0.1")),
        enable_agent_trace=os.getenv("ENABLE_AGENT_TRACE", "false").lower() in {"1", "true", "yes"},
        show_reasoning=os.getenv("SHOW_REASONING", "true").lower() in {"1", "true", "yes"},
        use_chroma=os.getenv("USE_CHROMA", "true").lower() in {"1", "true", "yes"},
        chroma_top_n=int(os.getenv("CHROMA_TOP_N", "10")),
        chroma_score_weight=float(os.getenv("CHROMA_SCORE_WEIGHT", "5.0")),
        chroma_host=os.getenv("CHROMA_HOST", "localhost"),
        chroma_port=int(os.getenv("CHROMA_PORT", "8000")),
    )
