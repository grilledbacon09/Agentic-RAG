"""ChromaDB 클라이언트 및 임베딩 함수.

Windows 저메모리 환경 기본값: simple (모델 다운로드/로딩 없음)
고사양 환경: sentence-transformers 또는 e5

.env 예시:
    EMBEDDING_BACKEND=simple
    EMBEDDING_DIM=384
    CHROMA_HOST=localhost
    CHROMA_PORT=8000
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
from pathlib import Path

import numpy as np

_SRC = Path(__file__).resolve().parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import bootstrap  # noqa: E402
import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions

CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))

# simple: 메모리 거의 0MB | onnx: ~80MB | sentence-transformers: ~500MB+
EMBEDDING_BACKEND = os.getenv("EMBEDDING_BACKEND", "simple")
EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2"
)
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "384"))

_client = None
_embedding_fn = None


class SimpleHashedEmbeddingFunction(embedding_functions.EmbeddingFunction):
    """모델 없이 한글 문자 n-gram 해시 벡터를 만드는 초경량 임베딩.

    개발/저메모리 환경용. 동일 키워드(예: 두통)가 포함된 문서와 높은 유사도.
    """

    def __init__(self, dim: int = 384):
        self.dim = dim
        print(
            f"[*] simple 임베딩 사용 (dim={dim}, 모델 로딩 없음)",
            flush=True,
        )

    def _tokenize(self, text: str) -> list[str]:
        text = (text or "").lower().strip()
        tokens: list[str] = []
        # 공백 단위
        tokens.extend(re.findall(r"[\w가-힣]+", text, flags=re.UNICODE))
        # 한글 문자 trigram (띄어쓰기 없는 키워드 매칭용)
        hangul = re.sub(r"[^가-힣]", "", text)
        for i in range(max(0, len(hangul) - 2)):
            tokens.append(hangul[i : i + 3])
        return tokens or [text[:1] or "?"]

    def _embed_one(self, text: str) -> list[float]:
        vec = np.zeros(self.dim, dtype=np.float32)
        for token in self._tokenize(text):
            digest = hashlib.md5(token.encode("utf-8")).hexdigest()
            idx = int(digest, 16) % self.dim
            vec[idx] += 1.0
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec /= norm
        return vec.tolist()

    def __call__(self, input):
        return [self._embed_one(text) for text in input]


def build_embedding_function():
    backend = EMBEDDING_BACKEND.lower()
    model = EMBEDDING_MODEL

    print(f"[*] 임베딩 백엔드={backend}", flush=True)

    if backend == "simple":
        return SimpleHashedEmbeddingFunction(dim=EMBEDDING_DIM)

    if backend == "onnx":
        print("[*] ONNX MiniLM 로딩 (~80MB)", flush=True)
        return embedding_functions.ONNXMiniLM_L6_V2()

    if backend == "fastembed":
        return embedding_functions.FastEmbedEmbeddingFunction(model_name=model)

    if backend == "sentence-transformers":
        print(f"[*] sentence-transformers 로딩: {model}", flush=True)
        try:
            return embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=model,
            )
        except Exception as e:
            raise RuntimeError(
                "sentence-transformers 초기화 실패. "
                "메모리가 부족하면 .env에서 EMBEDDING_BACKEND=simple 로 변경하세요.\n"
                f"원인: {e}"
            ) from e

    if backend in ("e5", "transformers-e5"):
        return _build_e5_embedding(model)

    raise ValueError(
        f"지원하지 않는 EMBEDDING_BACKEND: {backend}. "
        "simple | onnx | sentence-transformers | e5 중 선택"
    )


def _build_e5_embedding(model_name: str):
    import torch
    import torch.nn.functional as F
    from transformers import AutoModel, AutoTokenizer

    class E5Embedding(embedding_functions.EmbeddingFunction):
        def __init__(self):
            print(f"[*] E5 모델 로딩: {model_name}", flush=True)
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
            self.model = AutoModel.from_pretrained(
                model_name, low_cpu_mem_usage=True
            )
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            self.model.to(self.device)
            self.model.eval()

        def __call__(self, input):
            all_embeddings = []
            for i in range(0, len(input), 4):
                batch = input[i : i + 4]
                processed = [
                    t if t.startswith(("query:", "passage:")) else f"passage: {t}"
                    for t in batch
                ]
                encoded = self.tokenizer(
                    processed,
                    max_length=256,
                    padding=True,
                    truncation=True,
                    return_tensors="pt",
                ).to(self.device)
                with torch.no_grad():
                    out = self.model(**encoded)
                emb = out.last_hidden_state.masked_fill(
                    ~encoded["attention_mask"][..., None].bool(), 0.0
                )
                emb = emb.sum(1) / encoded["attention_mask"].sum(1)[..., None]
                emb = F.normalize(emb, p=2, dim=1)
                all_embeddings.extend(emb.cpu().numpy().tolist())
            return all_embeddings

    return E5Embedding()


class _LazyEmbeddingFunction(embedding_functions.EmbeddingFunction):
    def __init__(self):
        self._impl = None

    def _get_impl(self):
        if self._impl is None:
            self._impl = build_embedding_function()
            print("[+] 임베딩 준비 완료", flush=True)
        return self._impl

    def __call__(self, input):
        return self._get_impl()(input)


e5_embedding_function = _LazyEmbeddingFunction()


def get_embedding_function():
    global _embedding_fn
    if _embedding_fn is None:
        _embedding_fn = _LazyEmbeddingFunction()
    return _embedding_fn


def get_client() -> chromadb.HttpClient:
    global _client
    if _client is None:
        _client = chromadb.HttpClient(
            host=CHROMA_HOST,
            port=CHROMA_PORT,
            settings=Settings(
                allow_reset=True,
                anonymized_telemetry=False,
            ),
        )
    return _client


def init_collection():
    chroma_client = get_client()
    try:
        chroma_client.delete_collection("medical_knowledge")
        print("[*] 기존 medical_knowledge 컬렉션 삭제", flush=True)
    except Exception:
        pass

    return chroma_client.create_collection(
        name="medical_knowledge",
        embedding_function=get_embedding_function(),
        metadata={"hnsw:space": "cosine"},
    )


def __getattr__(name: str):
    if name == "client":
        return get_client()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if __name__ == "__main__":
    init_collection()
    print(f"[+] Heartbeat: {get_client().heartbeat()}", flush=True)
