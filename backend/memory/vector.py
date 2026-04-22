import uuid
from dataclasses import dataclass

import httpx
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from backend.config import settings

_qdrant = QdrantClient(url=settings.qdrant_url)


@dataclass
class EmbedResult:
    vector: list[float]
    model: str
    source: str


def embed(text: str) -> EmbedResult:
    """Embed text via Ollama nomic-embed-text; fall back to OpenAI text-embedding-3-small."""
    try:
        return _embed_ollama(text)
    except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError):
        return _embed_openai(text)


def _embed_ollama(text: str) -> EmbedResult:
    with httpx.Client(timeout=30.0) as client:
        r = client.post(
            f"{settings.ollama_url}/api/embeddings",
            json={"model": "nomic-embed-text", "prompt": text},
        )
        r.raise_for_status()
    return EmbedResult(
        vector=r.json()["embedding"],
        model="nomic-embed-text",
        source="ollama",
    )


def _embed_openai(text: str) -> EmbedResult:
    try:
        client = OpenAI(api_key=settings.openai_api_key)
        response = client.embeddings.create(model="text-embedding-3-small", input=text)
        return EmbedResult(
            vector=response.data[0].embedding,
            model="text-embedding-3-small",
            source="openai",
        )
    except Exception as exc:
        raise RuntimeError("Embedding unavailable") from exc


def _chunk(text: str, size: int = 512, overlap: int = 50) -> list[str]:
    pass  # placeholder — implemented in Task 3


def store_chunk(text: str, metadata: dict) -> str:
    pass  # placeholder — implemented in Task 4


def search(query: str, top_k: int = 5, filter: dict | None = None) -> list[dict]:
    pass  # placeholder — implemented in Task 5
