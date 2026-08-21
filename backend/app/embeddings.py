from __future__ import annotations

from importlib.util import find_spec
from typing import Any


DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def embedding_status() -> dict[str, Any]:
    available = find_spec("sentence_transformers") is not None
    return {
        "available": available,
        "provider": "sentence-transformers" if available else "none",
        "model": DEFAULT_EMBEDDING_MODEL,
        "local_only": True,
        "install_hint": "pip install -r backend/requirements.embedding.txt" if not available else "",
    }


def semantic_rank(query: str, documents: list[dict[str, object]], limit: int = 12) -> list[dict[str, object]]:
    if not find_spec("sentence_transformers"):
        raise RuntimeError("local_embedding_unavailable")
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(DEFAULT_EMBEDDING_MODEL)
    texts = [f"{item.get('title', '')}\n{item.get('text', '')}" for item in documents]
    vectors = model.encode([query, *texts], normalize_embeddings=True)
    query_vector = vectors[0]
    ranked = []
    for item, vector in zip(documents, vectors[1:]):
        score = float(sum(float(left) * float(right) for left, right in zip(query_vector, vector)))
        ranked.append((score, item))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    result = []
    for score, item in ranked[: max(1, min(int(limit or 12), 50))]:
        result.append({**item, "score": round(score, 6), "retrieval_method": "local-embedding"})
    return result
