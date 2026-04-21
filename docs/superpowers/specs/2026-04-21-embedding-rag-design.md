# Embedding + RAG Layer — Design Spec

**Date:** 2026-04-21  
**Status:** Approved  
**Session:** 4

---

## Overview

Add a semantic memory layer to the Second Brain: store text knowledge as vector embeddings in Qdrant and retrieve relevant chunks as context when the user asks a question.

---

## Architecture

Follows Option A: `backend/memory/vector.py` exposes three pure functions; all intent-based orchestration lives in `router/api.py` as new branches (same pattern as `store_reminder`).

```
User message
    └── POST /message
            ├── store_knowledge → _chunk() → store_chunk() × N → "Saved."
            ├── query           → search() → inject context → call_tier1(enriched) → normal escalation
            └── (all other intents unchanged)
```

Storage: Qdrant collection `"brain"` only. No Postgres mirror. The existing `knowledge_items` table is left in place but unused by this layer.

---

## Components

### `backend/memory/vector.py`

Three public functions. No async — `qdrant-client` sync calls are fast enough.

#### `embed(text: str) -> EmbedResult`

Returns `EmbedResult(vector: list[float], model: str, source: str)`.

- Primary: `POST {ollama_url}/api/embeddings`, model `nomic-embed-text` → 768-dim
- Fallback (on `httpx.ConnectError / TimeoutException / HTTPStatusError`): OpenAI `text-embedding-3-small` → 1536-dim
- Both fail: raises `RuntimeError("Embedding unavailable")`

#### `store_chunk(text: str, metadata: dict) -> str`

1. Calls `embed(text)`
2. Creates Qdrant collection `"brain"` on first use (vector size from embedding length, distance=Cosine). Skips if already exists.
3. Upserts one point: payload = `{**metadata, "text": text}`, id = `str(uuid.uuid4())`
4. Returns the UUID string

Expected metadata keys: `source_type`, `source_url`, `title`, `date_added`, `chunk_index`, `tags`. No enforcement — callers own validation.

#### `search(query: str, top_k: int = 5, filter: dict | None = None) -> list[dict]`

1. Calls `embed(query)`
2. Runs `qdrant_client.search("brain", query_vector, limit=top_k, query_filter=filter)`
3. Returns list of payload dicts (metadata + `"text"` key), ordered by score descending
4. Returns `[]` if collection does not exist yet

Module-level Qdrant client initialized once from `settings.qdrant_url`.

#### `_chunk(text: str, size: int = 512, overlap: int = 50) -> list[str]`

Private. Splits on whitespace into word tokens, yields sliding windows of `size` words with `overlap`-word overlap. Returns at least one chunk even for short text.

---

### `router/api.py` — New intent branches

#### `store_knowledge` branch (before escalation check, after `store_reminder`)

```
tier1.intent == "store_knowledge"
  → chunks = _chunk(req.text)
  → for i, chunk in enumerate(chunks):
       metadata = {
           source_type: "whatsapp",
           source_url: "",
           title: req.text[:80],
           date_added: utcnow().isoformat(),
           chunk_index: i,
           tags: [],
       }
       store_chunk(chunk, metadata)
  → return MessageResponse(response="Saved.", tier_used=1, intent="store_knowledge")
```

No Tier 2 escalation. Embedding failure → friendly error response (does not raise 503).

#### `query` enrichment (before escalation check)

```
tier1.intent == "query"
  → results = search(req.text, top_k=5)   [Qdrant failure: log + skip]
  → if results:
       context_block = "[Retrieved context:\n" + "\n".join(f"- {r['text']}" for r in results) + "]\n\nUser query: " + req.text
       tier1 = await call_tier1(context_block)   [second Tier 1 call with enriched message]
  → normal escalation logic on final tier1 result
```

If `search` raises, log the error and continue with the original `tier1` result (graceful degradation).

---

### `GET /embed-status`

New route in `router/api.py`.

Calls `embed("test")`. Returns:
```json
{"model": "nomic-embed-text", "source": "ollama", "dimensions": 768}
```
or on Ollama failure:
```json
{"model": "text-embedding-3-small", "source": "openai", "dimensions": 1536}
```
On both failures: HTTP 503 `{"detail": "Embedding service unavailable"}`.

---

## Data Flow

```
store_knowledge:
  text → _chunk() → [chunk_0, chunk_1, ...] → embed(chunk_i) → qdrant upsert

query:
  text → search(text) → [payload_0, ..., payload_4] → prepend context → call_tier1(enriched)
       → should_escalate? → call_tier2 or return tier1.response
```

---

## Error Handling

| Failure | Behaviour |
|---|---|
| Both embedding backends fail on `store_chunk` | Return `"Could not save — embedding service unavailable."` |
| Qdrant unreachable during `search` | Log warning, skip context injection, continue with bare query |
| Qdrant unreachable during `store_chunk` | Return `"Could not save — vector store unavailable."` |
| Collection missing on `search` | Return `[]` (no error) |
| Collection missing on `store_chunk` | Auto-create, then upsert |

---

## Testing (`tests/test_vector.py`)

All Ollama, OpenAI, and Qdrant calls are mocked.

1. `embed()` returns Ollama vector on success — correct model/source/dimensions
2. `embed()` falls back to OpenAI on Ollama `ConnectError`
3. `embed()` raises `RuntimeError` when both backends fail
4. `store_chunk()` calls `embed` + qdrant upsert, returns a UUID string
5. `search()` embeds query + calls qdrant search, returns payload list ordered by score
6. `search()` returns `[]` when collection does not exist (qdrant raises `UnexpectedResponse`)
7. Integration: store 3 distinct chunks with mocked scores, query semantically related to one → correct chunk in top 3 results
8. Router `store_knowledge` branch stores N chunks and returns `"Saved."`
9. Router `query` branch: when search returns results, second `call_tier1` is called with enriched message containing context
10. Router `query` branch: when search returns empty, `call_tier1` is called only once (original message)

---

## Dependencies

New packages required:
- `qdrant-client` (Qdrant Python SDK, sync)
- `openai` (OpenAI SDK for fallback embeddings)

Both are pure-Python, no native extensions. Add to `requirements.txt` / `pyproject.toml`.

---

## Out of Scope

- Postgres `knowledge_items` table: left in place, not written to by this layer
- Tag extraction: `tags` defaults to `[]`; user-supplied tags are a future feature
- Multi-collection support: single `"brain"` collection for now
- `GET /health` Qdrant check: already present from Session 1; no change needed
