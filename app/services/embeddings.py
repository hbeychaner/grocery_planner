import logging
import math
import os
from typing import Any, Dict, List, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

_EMBED_CACHE: Dict[str, List[float]] = {}
_MAX_CACHE_SIZE = 5000
_LOCAL_MODEL: Optional[Any] = None
_LOCAL_INIT_DONE = False


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two embedding vectors without torch/numpy."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _get_local_model() -> Optional[Any]:
    """Lazily load local SentenceTransformer only when EMBEDDING_PROVIDER=local."""
    global _LOCAL_MODEL, _LOCAL_INIT_DONE
    if _LOCAL_INIT_DONE:
        return _LOCAL_MODEL
    _LOCAL_INIT_DONE = True
    try:
        from sentence_transformers import SentenceTransformer

        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        _LOCAL_MODEL = SentenceTransformer(
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
            local_files_only=True,
        )
    except Exception as exc:
        logger.debug(f"Local SentenceTransformer unavailable: {exc}")
        _LOCAL_MODEL = None
    return _LOCAL_MODEL


def _embed_via_gemini(texts: List[str]) -> Optional[List[List[float]]]:
    """Fetch embeddings from Google Gemini Embeddings API with in-memory caching."""
    if not settings.gemini_api_key:
        return None
    missing = [t for t in texts if t not in _EMBED_CACHE]
    if missing:
        try:
            from google import genai

            client = genai.Client(api_key=settings.gemini_api_key)
            # Batch in chunks of 100 to respect API batch limits
            for i in range(0, len(missing), 100):
                chunk = missing[i : i + 100]
                resp = client.models.embed_content(
                    model=settings.gemini_embedding_model,
                    contents=chunk,
                )
                embeddings = getattr(resp, "embeddings", None) or []
                for text_val, emb_obj in zip(chunk, embeddings):
                    vec = list(getattr(emb_obj, "values", None) or [])
                    if vec:
                        if len(_EMBED_CACHE) >= _MAX_CACHE_SIZE:
                            _EMBED_CACHE.clear()
                        _EMBED_CACHE[text_val] = vec
        except Exception as exc:
            logger.debug(f"Gemini embedding request failed: {exc}")
            return None

    vectors = [_EMBED_CACHE.get(t) for t in texts]
    if any(v is None for v in vectors):
        return None
    return [v for v in vectors if v is not None]


def embed_texts(texts: List[str]) -> Optional[List[List[float]]]:
    """Return normalized embedding vectors using the configured provider ('gemini' or 'local')."""
    clean = [t.strip() for t in texts]
    if not clean:
        return []
    provider = settings.embedding_provider.strip().lower()
    if provider == "gemini":
        return _embed_via_gemini(clean)

    model = _get_local_model()
    if model is not None:
        try:
            vecs = model.encode(clean, convert_to_numpy=True)
            return [v.tolist() for v in vecs]
        except Exception as exc:
            logger.debug(f"Local embedding encode failed: {exc}")
    return None


def pairwise_cosine_similarity(text_a: str, text_b: str) -> Optional[float]:
    """Compute cosine similarity between two strings, or None if embeddings are unavailable."""
    vecs = embed_texts([text_a, text_b])
    if not vecs or len(vecs) != 2:
        return None
    return _cosine_similarity(vecs[0], vecs[1])


def batch_cosine_similarities(query: str, candidates: List[str]) -> Optional[List[float]]:
    """Compute cosine similarities between one query and a list of candidate strings."""
    if not candidates:
        return []
    vecs = embed_texts([query, *candidates])
    if not vecs or len(vecs) != len(candidates) + 1:
        return None
    q_vec = vecs[0]
    return [_cosine_similarity(q_vec, cand_vec) for cand_vec in vecs[1:]]
