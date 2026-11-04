"""Local embeddings with sentence-transformers: no API key, no cost, data stays on your machine.

The model is downloaded from Hugging Face on first use and cached afterwards.
"""
import os
from functools import lru_cache

MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")


@lru_cache(maxsize=1)
def _model():
    from sentence_transformers import SentenceTransformer  # heavy import, so only when embedding

    return SentenceTransformer(MODEL)


def dimensions() -> int:
    """Vector size of the chosen model (384 for all-MiniLM-L6-v2)."""
    return _model().get_sentence_embedding_dimension()


def embed(inputs: list[str]) -> list[list[float]]:
    # Normalised vectors make cosine similarity (used by the Atlas index) well behaved.
    return _model().encode(inputs, normalize_embeddings=True).tolist()
