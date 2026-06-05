"""DE 파트 공통 경로 상수.

실행 기준 디렉터리와 무관하게 동일한 경로를 반환합니다.
모든 스크립트는 DE 루트에서 실행하는 것을 권장합니다.

    cd DE
    python src/extractor/seed_dev_data.py
"""

from __future__ import annotations

from pathlib import Path

# DE/src/infra/paths.py → DE 루트
INFRA_DIR = Path(__file__).resolve().parent
SRC_DIR = INFRA_DIR.parent
DE_ROOT = SRC_DIR.parent
PROJECT_ROOT = DE_ROOT.parent

ENV_FILE = DE_ROOT / ".env"

DATA_DIR = DE_ROOT / "data"
MSD_SOURCE_DIR = DATA_DIR / "msd_source"
MSD_SYMPTOMS_HTML = MSD_SOURCE_DIR / "symptoms.html"
MSD_LINKS_CSV = MSD_SOURCE_DIR / "links.csv"
MSD_SILVER_CSV = MSD_SOURCE_DIR / "silver_data.csv"

TEAM_DRUG_INFO_ROOT = DATA_DIR / "minio" / "bronze" / "drug_info"
TEAM_TABOO_INFO_ROOT = DATA_DIR / "minio" / "bronze" / "taboo_info"
TEAM_SYMPTOM_JSON_ROOT = DATA_DIR / "minio" / "silver" / "symptoms"
PROCESSED_DIR = DATA_DIR / "processed"

# AI 파트 샘플 데이터 (프로젝트 루트 data/)
AI_DATA_DIR = PROJECT_ROOT / "data"
AI_SYMPTOMS_JSON = AI_DATA_DIR / "symptoms.json"
AI_DRUGS_JSON = AI_DATA_DIR / "drugs.json"

SRC_SUBDIRS = ("infra", "collector", "extractor", "vectordb")


def ensure_data_dirs() -> None:
    """파이프라인에 필요한 로컬 data 하위 폴더를 생성합니다."""
    MSD_SOURCE_DIR.mkdir(parents=True, exist_ok=True)
