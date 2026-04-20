import asyncio

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from backend.config import settings
from backend.db import AsyncSessionLocal

router = APIRouter()

# Required model names (used verbatim in error messages)
REQUIRED_MODELS = {"nomic-embed-text", "gemma3:4b"}


async def check_postgres() -> str:
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:
        return f"error: {exc}"


async def check_qdrant() -> str:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{settings.qdrant_url}/healthz")
            r.raise_for_status()
        return "ok"
    except Exception as exc:
        return f"error: {exc}"


async def check_ollama() -> str:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{settings.ollama_url}/api/tags")
            r.raise_for_status()
            # Collect Ollama model names as-is for exact matching
            present = {m["name"] for m in r.json().get("models", [])}
            # Also add base names (strip `:tag`) so "nomic-embed-text:latest" satisfies "nomic-embed-text"
            present |= {name.split(":")[0] for name in present}
            missing = REQUIRED_MODELS - present
            if missing:
                return f"error: missing models {sorted(missing)}"
        return "ok"
    except Exception as exc:
        return f"error: {exc}"


@router.get("/health")
async def health():
    results = await asyncio.gather(
        check_postgres(),
        check_qdrant(),
        check_ollama(),
        return_exceptions=True,
    )

    def to_str(r: object) -> str:
        return r if isinstance(r, str) else f"error: {r}"

    body = {
        "postgres": to_str(results[0]),
        "qdrant": to_str(results[1]),
        "ollama": to_str(results[2]),
    }
    status = 200 if all(v == "ok" for v in body.values()) else 503
    return JSONResponse(content=body, status_code=status)
