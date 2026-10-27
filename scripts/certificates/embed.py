"""Embeddings via any OpenAI-compatible endpoint (OpenAI, Voyage, Azure, local servers)."""
import os

from openai import OpenAI

MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS", "1536"))


def embed(inputs: list[str]) -> list[list[float]]:
    client = OpenAI(
        api_key=os.environ["EMBEDDING_API_KEY"],
        base_url=os.getenv("EMBEDDING_BASE_URL"),  # None -> OpenAI default
    )
    resp = client.embeddings.create(model=MODEL, input=inputs, dimensions=DIMENSIONS)
    return [d.embedding for d in sorted(resp.data, key=lambda d: d.index)]
