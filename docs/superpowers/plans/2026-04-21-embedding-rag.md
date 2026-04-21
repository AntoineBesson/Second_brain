# Embedding + RAG Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add semantic vector storage and retrieval so `store_knowledge` messages are chunked into Qdrant and `query` messages retrieve relevant context before answering.

**Architecture:** `backend/memory/vector.py` exposes three pure sync functions (`embed`, `store_chunk`, `search`) plus a private `_chunk` helper. Intent orchestration lives in `router/api.py` as new branches following the existing `store_reminder` pattern. Qdrant collection `"brain"` is the sole storage layer; no Postgres mirror.

**Tech Stack:** `qdrant-client>=1.7.0` (sync), `openai>=1.0.0` (fallback embeddings), `httpx` (already present, used sync for Ollama)

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `backend/requirements.txt` | Modify | Add `qdrant-client>=1.7.0`, `openai>=1.0.0` |
| `backend/memory/vector.py` | Create | `EmbedResult` dataclass, `embed()`, `_chunk()`, `store_chunk()`, `search()`, module-level `_qdrant` client |
| `backend/router/api.py` | Modify | `store_knowledge` branch, `query` context-injection, `GET /embed-status` endpoint |
| `tests/test_vector.py` | Create | All `vector.py` unit tests |
| `tests/test_router.py` | Modify | Tests for new router branches and `/embed-status` |

---

## Task 1: Add dependencies

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Add packages**

Open `backend/requirements.txt` and add these two lines at the end:

```
qdrant-client>=1.7.0
openai>=1.0.0
```

- [ ] **Step 2: Commit**

```bash
git add backend/requirements.txt
git commit -m "chore: add qdrant-client and openai to requirements"
```

---

## Task 2: `EmbedResult` + `embed()`

**Files:**
- Create: `backend/memory/vector.py`
- Create: `tests/test_vector.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_vector.py`:

```python
import httpx
import pytest
from unittest.mock import MagicMock, patch

from backend.memory.vector import EmbedResult, embed


def test_embed_returns_ollama_vector():
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"embedding": [0.1, 0.2, 0.3]})

    mock_http_client = MagicMock()
    mock_http_client.post = MagicMock(return_value=mock_response)

    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_http_client)
    mock_ctx.__exit__ = MagicMock(return_value=False)

    with patch("backend.memory.vector.httpx.Client", return_value=mock_ctx):
        result = embed("hello world")

    assert result.vector == [0.1, 0.2, 0.3]
    assert result.model == "nomic-embed-text"
    assert result.source == "ollama"


def test_embed_falls_back_to_openai_on_ollama_error():
    mock_http_client = MagicMock()
    mock_http_client.post = MagicMock(side_effect=httpx.ConnectError("ollama down"))
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_http_client)
    mock_ctx.__exit__ = MagicMock(return_value=False)

    mock_data = MagicMock()
    mock_data.embedding = [0.4, 0.5, 0.6]
    mock_openai_resp = MagicMock()
    mock_openai_resp.data = [mock_data]
    mock_openai_client = MagicMock()
    mock_openai_client.embeddings.create = MagicMock(return_value=mock_openai_resp)

    with patch("backend.memory.vector.httpx.Client", return_value=mock_ctx), \
         patch("backend.memory.vector.OpenAI", return_value=mock_openai_client):
        result = embed("hello world")

    assert result.vector == [0.4, 0.5, 0.6]
    assert result.model == "text-embedding-3-small"
    assert result.source == "openai"


def test_embed_raises_runtime_error_when_both_fail():
    mock_http_client = MagicMock()
    mock_http_client.post = MagicMock(side_effect=httpx.ConnectError("ollama down"))
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_http_client)
    mock_ctx.__exit__ = MagicMock(return_value=False)

    mock_openai_client = MagicMock()
    mock_openai_client.embeddings.create = MagicMock(side_effect=Exception("OpenAI down"))

    with patch("backend.memory.vector.httpx.Client", return_value=mock_ctx), \
         patch("backend.memory.vector.OpenAI", return_value=mock_openai_client):
        with pytest.raises(RuntimeError, match="Embedding unavailable"):
            embed("hello world")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_vector.py -v
```

Expected: `ImportError: cannot import name 'EmbedResult' from 'backend.memory.vector'` (file doesn't exist yet).

- [ ] **Step 3: Create `backend/memory/vector.py` with `EmbedResult` and `embed()`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_vector.py::test_embed_returns_ollama_vector \
       tests/test_vector.py::test_embed_falls_back_to_openai_on_ollama_error \
       tests/test_vector.py::test_embed_raises_runtime_error_when_both_fail -v
```

Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add backend/memory/vector.py tests/test_vector.py
git commit -m "feat: add EmbedResult dataclass and embed() with Ollama/OpenAI fallback"
```

---

## Task 3: `_chunk()`

**Files:**
- Modify: `backend/memory/vector.py`
- Modify: `tests/test_vector.py`

- [ ] **Step 1: Add the failing tests** (append to `tests/test_vector.py`)

```python
from backend.memory.vector import _chunk


def test_chunk_returns_single_chunk_for_short_text():
    result = _chunk("hello world foo bar")
    assert result == ["hello world foo bar"]


def test_chunk_splits_with_overlap():
    # 100 words, size=60, overlap=10
    # chunk 0: words[0:60]  (60 words)
    # chunk 1: words[50:100] (50 words — last chunk is shorter)
    words = ["w"] * 100
    text = " ".join(words)
    chunks = _chunk(text, size=60, overlap=10)
    assert len(chunks) == 2
    assert len(chunks[0].split()) == 60
    assert len(chunks[1].split()) == 50
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_vector.py::test_chunk_returns_single_chunk_for_short_text \
       tests/test_vector.py::test_chunk_splits_with_overlap -v
```

Expected: both FAILED (returns `None`).

- [ ] **Step 3: Implement `_chunk()` in `backend/memory/vector.py`**

Replace the `_chunk` placeholder:

```python
def _chunk(text: str, size: int = 512, overlap: int = 50) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    if len(words) <= size:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = min(start + size, len(words))
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start += size - overlap
    return chunks
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_vector.py::test_chunk_returns_single_chunk_for_short_text \
       tests/test_vector.py::test_chunk_splits_with_overlap -v
```

Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add backend/memory/vector.py tests/test_vector.py
git commit -m "feat: add _chunk() word-window splitter with overlap"
```

---

## Task 4: `store_chunk()`

**Files:**
- Modify: `backend/memory/vector.py`
- Modify: `tests/test_vector.py`

- [ ] **Step 1: Add the failing test** (append to `tests/test_vector.py`)

```python
import uuid as uuid_mod
from backend.memory.vector import store_chunk


def test_store_chunk_embeds_and_upserts():
    mock_embed_result = EmbedResult(vector=[0.1] * 768, model="nomic-embed-text", source="ollama")
    mock_qdrant = MagicMock()
    mock_qdrant.collection_exists = MagicMock(return_value=True)
    mock_qdrant.upsert = MagicMock()

    with patch("backend.memory.vector.embed", return_value=mock_embed_result), \
         patch("backend.memory.vector._qdrant", mock_qdrant):
        result = store_chunk("some text", {"source_type": "whatsapp", "chunk_index": 0})

    # Returns a valid UUID string
    uuid_mod.UUID(result)

    mock_qdrant.upsert.assert_called_once()
    call_kwargs = mock_qdrant.upsert.call_args.kwargs
    assert call_kwargs["collection_name"] == "brain"
    point = call_kwargs["points"][0]
    assert point.payload["text"] == "some text"
    assert point.vector == [0.1] * 768
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_vector.py::test_store_chunk_embeds_and_upserts -v
```

Expected: FAILED (returns `None`, `uuid_mod.UUID(None)` raises).

- [ ] **Step 3: Implement `store_chunk()` in `backend/memory/vector.py`**

Replace the `store_chunk` placeholder:

```python
def _ensure_collection(dim: int) -> None:
    if not _qdrant.collection_exists("brain"):
        _qdrant.create_collection(
            collection_name="brain",
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )


def store_chunk(text: str, metadata: dict) -> str:
    result = embed(text)
    _ensure_collection(len(result.vector))
    point_id = str(uuid.uuid4())
    _qdrant.upsert(
        collection_name="brain",
        points=[PointStruct(id=point_id, vector=result.vector, payload={**metadata, "text": text})],
    )
    return point_id
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_vector.py::test_store_chunk_embeds_and_upserts -v
```

Expected: PASSED.

- [ ] **Step 5: Commit**

```bash
git add backend/memory/vector.py tests/test_vector.py
git commit -m "feat: add store_chunk() with auto-create collection on first use"
```

---

## Task 5: `search()`

**Files:**
- Modify: `backend/memory/vector.py`
- Modify: `tests/test_vector.py`

- [ ] **Step 1: Add the failing tests** (append to `tests/test_vector.py`)

```python
from backend.memory.vector import search


def test_search_returns_payload_list():
    mock_embed_result = EmbedResult(vector=[0.1] * 768, model="nomic-embed-text", source="ollama")

    mock_hit = MagicMock()
    mock_hit.payload = {"text": "relevant chunk", "source_type": "whatsapp"}

    mock_qdrant = MagicMock()
    mock_qdrant.collection_exists = MagicMock(return_value=True)
    mock_qdrant.search = MagicMock(return_value=[mock_hit])

    with patch("backend.memory.vector.embed", return_value=mock_embed_result), \
         patch("backend.memory.vector._qdrant", mock_qdrant):
        results = search("my query")

    assert len(results) == 1
    assert results[0]["text"] == "relevant chunk"
    mock_qdrant.search.assert_called_once_with(
        collection_name="brain",
        query_vector=[0.1] * 768,
        limit=5,
        query_filter=None,
    )


def test_search_returns_empty_when_collection_missing():
    mock_qdrant = MagicMock()
    mock_qdrant.collection_exists = MagicMock(return_value=False)

    with patch("backend.memory.vector._qdrant", mock_qdrant):
        results = search("my query")

    assert results == []
    mock_qdrant.search.assert_not_called()


def test_search_correct_chunk_in_top_3():
    """Store 3 distinct payloads; mock Qdrant to return them ranked by relevance score."""
    chunks = [
        {"text": "Python is a high-level programming language", "score": 0.9},
        {"text": "Cats sleep for 16 hours a day", "score": 0.3},
        {"text": "The Eiffel Tower is in Paris", "score": 0.2},
    ]
    mock_embed_result = EmbedResult(vector=[0.1] * 768, model="nomic-embed-text", source="ollama")

    mock_hits = []
    for c in sorted(chunks, key=lambda x: x["score"], reverse=True):
        hit = MagicMock()
        hit.payload = {"text": c["text"]}
        hit.score = c["score"]
        mock_hits.append(hit)

    mock_qdrant = MagicMock()
    mock_qdrant.collection_exists = MagicMock(return_value=True)
    mock_qdrant.search = MagicMock(return_value=mock_hits)

    with patch("backend.memory.vector.embed", return_value=mock_embed_result), \
         patch("backend.memory.vector._qdrant", mock_qdrant):
        results = search("What programming language should I learn?", top_k=3)

    texts = [r["text"] for r in results]
    assert "Python is a high-level programming language" in texts
    assert texts.index("Python is a high-level programming language") == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_vector.py::test_search_returns_payload_list \
       tests/test_vector.py::test_search_returns_empty_when_collection_missing \
       tests/test_vector.py::test_search_correct_chunk_in_top_3 -v
```

Expected: all FAILED (returns `None`).

- [ ] **Step 3: Implement `search()` in `backend/memory/vector.py`**

Replace the `search` placeholder:

```python
def search(query: str, top_k: int = 5, filter: dict | None = None) -> list[dict]:
    if not _qdrant.collection_exists("brain"):
        return []
    result = embed(query)
    hits = _qdrant.search(
        collection_name="brain",
        query_vector=result.vector,
        limit=top_k,
        query_filter=filter,
    )
    return [hit.payload for hit in hits]
```

- [ ] **Step 4: Run all vector tests**

```bash
pytest tests/test_vector.py -v
```

Expected: all 9 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add backend/memory/vector.py tests/test_vector.py
git commit -m "feat: add search() with collection-existence guard"
```

---

## Task 6: Router — `store_knowledge` branch + `GET /embed-status`

**Files:**
- Modify: `backend/router/api.py`
- Modify: `tests/test_router.py`

- [ ] **Step 1: Add the failing tests** (append to `tests/test_router.py`)

```python
# ---------------------------------------------------------------------------
# store_knowledge intent
# ---------------------------------------------------------------------------

async def test_message_endpoint_stores_chunks_on_store_knowledge_intent():
    from backend.memory.vector import EmbedResult
    tier1_result = Tier1Response(
        intent="store_knowledge",
        complexity=0.2,
        escalate=False,
        escalation_reason="",
        response="",
    )
    req = MessageRequest(text="Python is great for data science", chat_id="chat_001")

    with patch("backend.router.api.call_tier1", AsyncMock(return_value=tier1_result)), \
         patch("backend.router.api._chunk", return_value=["Python is great for data science"]), \
         patch("backend.router.api.store_chunk", return_value="fake-uuid") as mock_store:
        result = await message(req)

    assert result.response == "Saved."
    assert result.tier_used == 1
    assert result.intent == "store_knowledge"
    mock_store.assert_called_once()
    call_positional = mock_store.call_args.args
    assert call_positional[0] == "Python is great for data science"
    assert call_positional[1]["source_type"] == "whatsapp"
    assert call_positional[1]["chunk_index"] == 0


async def test_message_endpoint_returns_friendly_error_on_embed_failure():
    tier1_result = Tier1Response(
        intent="store_knowledge",
        complexity=0.2,
        escalate=False,
        escalation_reason="",
        response="",
    )
    req = MessageRequest(text="Some note", chat_id="chat_001")

    with patch("backend.router.api.call_tier1", AsyncMock(return_value=tier1_result)), \
         patch("backend.router.api._chunk", return_value=["Some note"]), \
         patch("backend.router.api.store_chunk", side_effect=RuntimeError("Embedding unavailable")):
        result = await message(req)

    assert "embedding service unavailable" in result.response.lower()
    assert result.intent == "store_knowledge"


# ---------------------------------------------------------------------------
# GET /embed-status
# ---------------------------------------------------------------------------

async def test_embed_status_returns_ollama_info():
    from backend.memory.vector import EmbedResult
    from backend.router.api import embed_status

    mock_result = EmbedResult(vector=[0.1] * 768, model="nomic-embed-text", source="ollama")
    with patch("backend.router.api.embed", return_value=mock_result):
        result = await embed_status()

    assert result == {"model": "nomic-embed-text", "source": "ollama", "dimensions": 768}


async def test_embed_status_returns_503_when_embedding_unavailable():
    from fastapi import HTTPException
    from backend.router.api import embed_status

    with patch("backend.router.api.embed", side_effect=RuntimeError("Embedding unavailable")):
        with pytest.raises(HTTPException) as exc_info:
            await embed_status()
    assert exc_info.value.status_code == 503
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_router.py::test_message_endpoint_stores_chunks_on_store_knowledge_intent \
       tests/test_router.py::test_message_endpoint_returns_friendly_error_on_embed_failure \
       tests/test_router.py::test_embed_status_returns_ollama_info \
       tests/test_router.py::test_embed_status_returns_503_when_embedding_unavailable -v
```

Expected: all FAILED (imports don't exist yet in api.py).

- [ ] **Step 3: Update `backend/router/api.py`**

Add to the existing imports at the top:

```python
from datetime import datetime, timezone

from backend.memory.vector import _chunk, embed, search, store_chunk
```

Add the `/embed-status` endpoint (before the `/message` route):

```python
@router.get("/embed-status")
async def embed_status() -> dict:
    try:
        result = embed("test")
        return {"model": result.model, "source": result.source, "dimensions": len(result.vector)}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Embedding service unavailable") from exc
```

Add the `store_knowledge` branch inside `message()`, after the `store_reminder` block and before the `should_escalate` check:

```python
    if tier1.intent == "store_knowledge":
        try:
            chunks = _chunk(req.text)
            for i, chunk in enumerate(chunks):
                store_chunk(chunk, {
                    "source_type": "whatsapp",
                    "source_url": "",
                    "title": req.text[:80],
                    "date_added": datetime.now(timezone.utc).isoformat(),
                    "chunk_index": i,
                    "tags": [],
                })
            response_text = "Saved."
        except RuntimeError:
            response_text = "Could not save — embedding service unavailable."
        except Exception:
            response_text = "Could not save — vector store unavailable."
        return MessageResponse(response=response_text, tier_used=1, intent=tier1.intent)
```

The full updated `backend/router/api.py`:

```python
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.memory.vector import _chunk, embed, search, store_chunk
from backend.reminders.service import extract_and_save
from backend.router.escalation import call_tier2, log_escalation, should_escalate
from backend.router.intent import call_tier1

logger = logging.getLogger(__name__)
router = APIRouter()


class MessageRequest(BaseModel):
    text: str
    chat_id: str


class MessageResponse(BaseModel):
    response: str
    tier_used: int
    intent: str


@router.get("/embed-status")
async def embed_status() -> dict:
    try:
        result = embed("test")
        return {"model": result.model, "source": result.source, "dimensions": len(result.vector)}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Embedding service unavailable") from exc


@router.post("/message", response_model=MessageResponse)
async def message(req: MessageRequest) -> MessageResponse:
    try:
        tier1 = await call_tier1(req.text)
    except Exception as exc:
        logger.error("Tier 1 failed: %s", exc)
        raise HTTPException(status_code=503, detail="LLM backend unavailable") from exc

    if tier1.intent == "store_reminder":
        try:
            reminder = await extract_and_save(req.text, req.chat_id)
            dt = reminder.trigger_at
            response_text = (
                f"Got it — I'll remind you to {reminder.text} "
                f"on {dt:%B} {dt.day} at {dt:%H:%M}."
            )
        except ValueError:
            response_text = "I couldn't understand when to set that reminder."
        return MessageResponse(response=response_text, tier_used=1, intent=tier1.intent)

    if tier1.intent == "store_knowledge":
        try:
            chunks = _chunk(req.text)
            for i, chunk in enumerate(chunks):
                store_chunk(chunk, {
                    "source_type": "whatsapp",
                    "source_url": "",
                    "title": req.text[:80],
                    "date_added": datetime.now(timezone.utc).isoformat(),
                    "chunk_index": i,
                    "tags": [],
                })
            response_text = "Saved."
        except RuntimeError:
            response_text = "Could not save — embedding service unavailable."
        except Exception:
            response_text = "Could not save — vector store unavailable."
        return MessageResponse(response=response_text, tier_used=1, intent=tier1.intent)

    if should_escalate(tier1):
        reason = tier1.escalation_reason or f"complexity={tier1.complexity:.2f}"

        try:
            await log_escalation(req.text, reason, req.chat_id)
        except Exception as exc:
            logger.warning("Failed to log escalation: %s", exc)

        try:
            response_text = await call_tier2(req.text, tier1)
            tier_used = 2
        except Exception as exc:
            logger.warning("Tier 2 failed, falling back to Tier 1 response: %s", exc)
            response_text = tier1.response
            tier_used = 1

        return MessageResponse(response=response_text, tier_used=tier_used, intent=tier1.intent)

    return MessageResponse(response=tier1.response, tier_used=1, intent=tier1.intent)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_router.py::test_message_endpoint_stores_chunks_on_store_knowledge_intent \
       tests/test_router.py::test_message_endpoint_returns_friendly_error_on_embed_failure \
       tests/test_router.py::test_embed_status_returns_ollama_info \
       tests/test_router.py::test_embed_status_returns_503_when_embedding_unavailable -v
```

Expected: 4 PASSED.

- [ ] **Step 5: Run the full suite to check for regressions**

```bash
pytest tests/ -v
```

Expected: all previously passing tests still PASS (61+ tests passing).

- [ ] **Step 6: Commit**

```bash
git add backend/router/api.py tests/test_router.py
git commit -m "feat: add store_knowledge branch and /embed-status endpoint"
```

---

## Task 7: Router — `query` context injection

**Files:**
- Modify: `backend/router/api.py`
- Modify: `tests/test_router.py`

- [ ] **Step 1: Add the failing tests** (append to `tests/test_router.py`)

```python
# ---------------------------------------------------------------------------
# query intent — context injection
# ---------------------------------------------------------------------------

async def test_message_endpoint_injects_context_on_query_with_results():
    tier1_initial = Tier1Response(
        intent="query",
        complexity=0.3,
        escalate=False,
        escalation_reason="",
        response="Answer without context",
    )
    tier1_enriched = Tier1Response(
        intent="query",
        complexity=0.3,
        escalate=False,
        escalation_reason="",
        response="Answer with context",
    )
    search_results = [{"text": "Python is great for data science", "source_type": "whatsapp"}]
    req = MessageRequest(text="What language for data?", chat_id="chat_001")

    call_tier1_mock = AsyncMock(side_effect=[tier1_initial, tier1_enriched])

    with patch("backend.router.api.call_tier1", call_tier1_mock), \
         patch("backend.router.api.search", return_value=search_results):
        result = await message(req)

    assert result.response == "Answer with context"
    assert call_tier1_mock.call_count == 2
    second_call_text = call_tier1_mock.call_args_list[1].args[0]
    assert "Python is great for data science" in second_call_text
    assert "What language for data?" in second_call_text


async def test_message_endpoint_skips_context_injection_when_no_results():
    tier1_result = Tier1Response(
        intent="query",
        complexity=0.3,
        escalate=False,
        escalation_reason="",
        response="Answer without context",
    )
    req = MessageRequest(text="What language for data?", chat_id="chat_001")

    call_tier1_mock = AsyncMock(return_value=tier1_result)

    with patch("backend.router.api.call_tier1", call_tier1_mock), \
         patch("backend.router.api.search", return_value=[]):
        result = await message(req)

    assert call_tier1_mock.call_count == 1
    assert result.response == "Answer without context"


async def test_message_endpoint_continues_on_search_failure():
    """If search() raises, the query proceeds without context injection."""
    tier1_result = Tier1Response(
        intent="query",
        complexity=0.3,
        escalate=False,
        escalation_reason="",
        response="Fallback answer",
    )
    req = MessageRequest(text="What language for data?", chat_id="chat_001")

    call_tier1_mock = AsyncMock(return_value=tier1_result)

    with patch("backend.router.api.call_tier1", call_tier1_mock), \
         patch("backend.router.api.search", side_effect=Exception("Qdrant down")):
        result = await message(req)

    assert call_tier1_mock.call_count == 1
    assert result.response == "Fallback answer"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_router.py::test_message_endpoint_injects_context_on_query_with_results \
       tests/test_router.py::test_message_endpoint_skips_context_injection_when_no_results \
       tests/test_router.py::test_message_endpoint_continues_on_search_failure -v
```

Expected: all FAILED (no `query` branch in router yet).

- [ ] **Step 3: Add the `query` enrichment block to `backend/router/api.py`**

Insert the following block inside `message()`, after the `store_knowledge` block and before `if should_escalate(tier1):`:

```python
    if tier1.intent == "query":
        try:
            results = search(req.text, top_k=5)
            if results:
                context_lines = "\n".join(f"- {r['text']}" for r in results)
                enriched = f"[Retrieved context:\n{context_lines}]\n\nUser query: {req.text}"
                tier1 = await call_tier1(enriched)
        except Exception as exc:
            logger.warning("Search failed, proceeding without context: %s", exc)
```

The full `message()` function after this change:

```python
@router.post("/message", response_model=MessageResponse)
async def message(req: MessageRequest) -> MessageResponse:
    try:
        tier1 = await call_tier1(req.text)
    except Exception as exc:
        logger.error("Tier 1 failed: %s", exc)
        raise HTTPException(status_code=503, detail="LLM backend unavailable") from exc

    if tier1.intent == "store_reminder":
        try:
            reminder = await extract_and_save(req.text, req.chat_id)
            dt = reminder.trigger_at
            response_text = (
                f"Got it — I'll remind you to {reminder.text} "
                f"on {dt:%B} {dt.day} at {dt:%H:%M}."
            )
        except ValueError:
            response_text = "I couldn't understand when to set that reminder."
        return MessageResponse(response=response_text, tier_used=1, intent=tier1.intent)

    if tier1.intent == "store_knowledge":
        try:
            chunks = _chunk(req.text)
            for i, chunk in enumerate(chunks):
                store_chunk(chunk, {
                    "source_type": "whatsapp",
                    "source_url": "",
                    "title": req.text[:80],
                    "date_added": datetime.now(timezone.utc).isoformat(),
                    "chunk_index": i,
                    "tags": [],
                })
            response_text = "Saved."
        except RuntimeError:
            response_text = "Could not save — embedding service unavailable."
        except Exception:
            response_text = "Could not save — vector store unavailable."
        return MessageResponse(response=response_text, tier_used=1, intent=tier1.intent)

    if tier1.intent == "query":
        try:
            results = search(req.text, top_k=5)
            if results:
                context_lines = "\n".join(f"- {r['text']}" for r in results)
                enriched = f"[Retrieved context:\n{context_lines}]\n\nUser query: {req.text}"
                tier1 = await call_tier1(enriched)
        except Exception as exc:
            logger.warning("Search failed, proceeding without context: %s", exc)

    if should_escalate(tier1):
        reason = tier1.escalation_reason or f"complexity={tier1.complexity:.2f}"

        try:
            await log_escalation(req.text, reason, req.chat_id)
        except Exception as exc:
            logger.warning("Failed to log escalation: %s", exc)

        try:
            response_text = await call_tier2(req.text, tier1)
            tier_used = 2
        except Exception as exc:
            logger.warning("Tier 2 failed, falling back to Tier 1 response: %s", exc)
            response_text = tier1.response
            tier_used = 1

        return MessageResponse(response=response_text, tier_used=tier_used, intent=tier1.intent)

    return MessageResponse(response=tier1.response, tier_used=1, intent=tier1.intent)
```

- [ ] **Step 4: Run the new tests**

```bash
pytest tests/test_router.py::test_message_endpoint_injects_context_on_query_with_results \
       tests/test_router.py::test_message_endpoint_skips_context_injection_when_no_results \
       tests/test_router.py::test_message_endpoint_continues_on_search_failure -v
```

Expected: 3 PASSED.

- [ ] **Step 5: Run the full suite**

```bash
pytest tests/ -v
```

Expected: all tests PASS (71+ total).

- [ ] **Step 6: Commit**

```bash
git add backend/router/api.py tests/test_router.py
git commit -m "feat: inject RAG context into query intent before escalation decision"
```
