"""ChromaDB 의미 검색 헬퍼 (AI 파트용).

DE 파트가 구축한 medical_knowledge 컬렉션에 접근합니다.
DE/.env 의 EMBEDDING_BACKEND 설정을 그대로 따릅니다.

사용 예:
    from chroma_retriever import search_medical_knowledge

    hits = search_medical_knowledge("두통", n_results=5)
    for hit in hits:
        print(hit.distance, hit.document[:200])
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_DE_SRC = Path(__file__).resolve().parent.parent / "database" / "src"
if str(_DE_SRC) not in sys.path:
    sys.path.insert(0, str(_DE_SRC))

import bootstrap  # noqa: E402, F401
import create_vectordb  # noqa: E402


@dataclass
class ChromaSearchHit:
    id: str
    document: str
    metadata: dict[str, Any]
    distance: float


def _get_collection():
    return create_vectordb.get_client().get_collection(
        name="medical_knowledge",
        embedding_function=create_vectordb.get_embedding_function(),
    )


def search_medical_knowledge(
    query: str,
    n_results: int = 5,
    where: dict[str, Any] | None = None,
) -> list[ChromaSearchHit]:
    """의료 지식 컬렉션에서 검색을 수행합니다."""
    collection = _get_collection()
    results = collection.query(
        query_texts=[query.strip()],
        n_results=n_results,
        where=where,
    )

    if not results.get("ids") or not results["ids"][0]:
        return []

    hits: list[ChromaSearchHit] = []
    for i in range(len(results["ids"][0])):
        hits.append(
            ChromaSearchHit(
                id=results["ids"][0][i],
                document=results["documents"][0][i],
                metadata=results["metadatas"][0][i] or {},
                distance=float(results["distances"][0][i]),
            )
        )
    return hits


if __name__ == "__main__":
    import json

    query = sys.argv[1] if len(sys.argv) > 1 else "두통"
    for hit in search_medical_knowledge(query):
        print(
            json.dumps(
                {
                    "id": hit.id,
                    "distance": hit.distance,
                    "metadata": hit.metadata,
                    "document_preview": hit.document[:200],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        print("-" * 40)
