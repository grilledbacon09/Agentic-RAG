"""DE 스크립트 공통 부트스트랩.

각 진입 스크립트 상단에서 src 디렉터리를 sys.path에 추가한 뒤
`import bootstrap`으로 호출합니다.
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent
DE_ROOT = SRC_DIR.parent
# graduation_project/.env  (DE_ROOT → Agentic-RAG/ → graduation_project/)
_REPO_ROOT = DE_ROOT.parent.parent

for sub in ("infra", "collector", "extractor", "vectordb", "pipeline"):
    path = str(SRC_DIR / sub)
    if path not in sys.path:
        sys.path.insert(0, path)

from dotenv import load_dotenv

load_dotenv(_REPO_ROOT / ".env")
