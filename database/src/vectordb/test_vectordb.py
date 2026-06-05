"""ChromaDB 검색 테스트.

실행 (DE 루트):
    python src/vectordb/test_vectordb.py
    python src/vectordb/test_vectordb.py 두통
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import bootstrap  # noqa: E402


def main() -> None:
    import chromadb
    import create_vectordb

    print("[*] test_vectordb.py 시작", flush=True)

    chroma_client = create_vectordb.get_client()
    print("컬렉션 목록:", chroma_client.list_collections(), flush=True)

    try:
        collection = chroma_client.get_collection(
            name="medical_knowledge",
            embedding_function=create_vectordb.get_embedding_function(),
        )
    except Exception as e:
        print(
            f"[!] medical_knowledge 컬렉션을 찾을 수 없습니다: {e}\n"
            "    먼저 `python src/vectordb/vectorizer.py`를 실행하세요.",
            flush=True,
        )
        sys.exit(1)

    print("문서 수:", collection.count(), flush=True)

    sample = collection.get(limit=3)
    print("샘플 문서:", sample.get("documents"), flush=True)

    user_query = sys.argv[1] if len(sys.argv) > 1 else input("질문: ")
    # simple/onnx 백엔드는 query: 접두어 불필요
    query = user_query

    print("\n===== vectorDB test =====\n", flush=True)
    results = collection.query(query_texts=[query], n_results=5)

    if not results["ids"] or not results["ids"][0]:
        print("[!] 검색 결과가 없습니다.", flush=True)
        return

    print("\n===== 검색 결과 =====\n", flush=True)
    for i in range(len(results["ids"][0])):
        print(f"순위: {i + 1}", flush=True)
        print(f"ID: {results['ids'][0][i]}", flush=True)
        print(f"거리: {results['distances'][0][i]}", flush=True)
        print(f"메타데이터: {results['metadatas'][0][i]}", flush=True)
        print(f"내용:\n{results['documents'][0][i][:300]}", flush=True)
        print("-" * 50, flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
