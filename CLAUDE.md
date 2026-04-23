# Second Brain — Project Context

## Architecture
- Two-tier LLM: Tier 1 = gemma3:4b via Ollama (local), Tier 2 = claude-sonnet-4-6
- Escalation threshold: complexity > 0.7 OR intent in [synthesize, analyze, compare]
- Embeddings: nomic-embed-text via Ollama, fallback to text-embedding-3-small
- Vector DB: Qdrant (Docker)
- Structured DB: Postgres (Docker)
- Scheduler: APScheduler
- WhatsApp: Twilio webhook
- Tool registry: OpenAPI specs stored in Postgres, executed via httpx

## Key Design Decisions
- NO LangChain / LlamaIndex — raw API calls only
- All LLM responses return structured JSON with {intent, complexity, escalate, response}
- Embedding abstraction: always call `embed(text)`, never the model directly; `embed()` returns `EmbedResult(vector, model, source)` — never a bare list
- Every ingested document gets: {source_type, source_url, title, date_added, chunk_index, tags}
- Qdrant collection `"brain"` is the sole storage layer for knowledge chunks — no Postgres mirror; `knowledge_items` table left in place but unused
- Chunking is word-based (512 words, 50-word overlap), not token-based — avoids tiktoken dependency; `_chunk()` raises `ValueError` if `overlap >= size`
- `store_reminder` intent bypasses Tier 2 escalation entirely — it is a structured side-effect intent, not a reasoning task
- `store_knowledge` intent also bypasses Tier 2 escalation — chunking + embedding is a side-effect, not a reasoning task
- `query` intent calls Tier 1 twice when Qdrant has results: first call classifies intent, second call receives enriched prompt `[Retrieved context: ...]\n\nUser query: ...` and produces the actual answer; escalation runs on the second result
- Qdrant client uses lazy initialization (`_get_qdrant()` accessor, `_qdrant_client = None` sentinel) — prevents import-time network calls in test environments
- Reminder extraction uses a second dedicated Tier 1 call (Ollama/Haiku fallback) with a focused prompt returning `{reminder_text, datetime_str}`; datetime parsing uses `dateparser` with per-chat timezone
- Timezone is stored per `chat_id` in `user_preferences` table (default `Europe/Paris`); `get_or_create_user_prefs` uses `INSERT ON CONFLICT DO NOTHING` + SELECT
- Twilio WhatsApp sends use raw httpx (no Twilio SDK); the SDK is imported only for `RequestValidator` (webhook signature verification)
- APScheduler dispatches reminders individually: Twilio failure on one skips `mark_sent` for that row only (retries on next 60s tick); does not block others
- TwiML responses must XML-escape LLM output (`xml.sax.saxutils.escape`) before interpolation — applied to all TwiML paths including the ingestion processing reply
- Alembic `server_default` for string literals must include SQL quoting: `"'value'"` not `"value"`
- Ingestion ingesters (`ingest_pdf`, `ingest_url`, `ingest_youtube`) are async but call sync `httpx.get` — consistent with the `vector.py` pattern; router-level callers do not need `asyncio.to_thread`
- `fetch_bytes(source, auth, headers)` is the shared primitive for all source types: `UploadFile` → `await source.read()`, local path → `Path.read_bytes()`, HTTP URL → sync `httpx.get` with merged `_DEFAULT_HEADERS`; `isinstance(source, UploadFile)` used (not `hasattr`) — `MagicMock(spec=UploadFile)` passes `isinstance` checks
- `TaskRegistry` is an in-memory class-backed singleton (`registry = TaskRegistry()` at module level in `registry.py`); both the ingest router and whatsapp interface import the same instance
- `store_knowledge` intent auto-detects URLs with `re.search(r"https?://[^\s]+", text).rstrip(".,;:!?)\"'")` — trailing punctuation stripped before dispatch; YouTube domains `{youtube.com, www.youtube.com, youtu.be}` → `ingest_youtube`, all others → `ingest_url`; plain text falls back to chunk+store
- WhatsApp webhook: `Body: str = Form("")` (not `Form(...)`) — PDF-only Twilio messages arrive with an empty body; `MediaUrl0`/`MediaContentType0` are optional form fields
- Twilio PDF media URLs require Basic auth `(ACCOUNT_SID, AUTH_TOKEN)` — passed through `fetch_bytes(source, auth=(...))` to `httpx.get`
- `_YT_DOMAINS` set is defined at module level in both `api.py` and `whatsapp.py` — acceptable duplication across separate modules; if domains change, update both
- URL regex trailing punctuation strip (`rstrip(".,;:!?)\"'")`) is applied in both `api.py` and `whatsapp.py` before passing URLs to ingesters
- `ingest_youtube` maps both `NoTranscriptFound` and `TranscriptsDisabled` (youtube-transcript-api) and `DownloadError` (yt-dlp) to `ValueError("no captions available...")` / `ValueError("Could not fetch video metadata: ...")`
- `_playwright_extract` uses `try/finally` around `browser.close()` to prevent Chromium subprocess leak if `page.goto()` raises; playwright import is a soft import (`try/except ImportError` returns `""`)
- PyMuPDF (`fitz`) document opened with `with fitz.open(stream=raw, filetype="pdf") as doc:` — context manager guarantees close on error

## Environment Variables (see .env.example)
ANTHROPIC_API_KEY, OPENAI_API_KEY, TWILIO_ACCOUNT_SID, 
TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM, DATABASE_URL, 
QDRANT_URL, OLLAMA_URL

## Running Locally
docker-compose up -d   # starts Postgres, Qdrant, Ollama
uvicorn backend.main:app --reload

## Test Command
pytest tests/ -v

---

## Build Status

### Session 1 — Infrastructure scaffold (complete)
- `docker-compose.yml`: postgres:16, qdrant, ollama (pulls nomic-embed-text + gemma3:4b on first start), backend
- `backend/main.py`: FastAPI app with lifespan that runs `alembic upgrade head` on startup
- `backend/config.py`: pydantic-settings, validates all env vars at startup
- `backend/db.py`: async SQLAlchemy engine + `AsyncSessionLocal`
- `backend/memory/postgres.py`: ORM models — `Reminder`, `KnowledgeItem`, `ApiTool`, `Escalation`
- `backend/migrations/versions/a1b2c3d4e5f6_initial_schema.py`: single migration covering all 4 tables
- `backend/health.py`: `GET /health` — checks postgres + qdrant + ollama concurrently, 200/503
- 35 tests passing

### Session 2 — Two-tier LLM router (complete)
- `backend/router/intent.py`: Tier 1 — calls Ollama gemma3:4b, returns `Tier1Response` dataclass, falls back to `claude-haiku-4-5-20251001` on `httpx.ConnectError / TimeoutException / HTTPStatusError`
- `backend/router/escalation.py`: `should_escalate` (complexity > 0.7, escalate flag, or intent in {synthesize, analyze, compare}), `call_tier2` (claude-sonnet-4-6, includes Tier 1 partial response as context), `log_escalation` (raw SQL INSERT into escalations table)
- `backend/router/api.py`: `POST /message` — accepts `{text, chat_id}`, returns `{response, tier_used, intent}`. Tier 1 failure → HTTP 503. Log failure → swallowed (non-blocking). Tier 2 failure → falls back to Tier 1 response.
- 35 tests passing

### Session 3 — Reminder system (complete)
- `backend/memory/postgres.py`: added `UserPreference` model (`chat_id PK`, `timezone TEXT DEFAULT 'Europe/Paris'`)
- `backend/migrations/versions/b2c3d4e5f6a7_add_user_preferences.py`: migration for `user_preferences` table
- `backend/reminders/crud.py`: `create_reminder`, `get_due_reminders`, `mark_sent`, `get_or_create_user_prefs`
- `backend/reminders/extraction.py`: second Tier 1 call → `{reminder_text, datetime_str}`, `parse_datetime` (dateparser, timezone-aware)
- `backend/reminders/service.py`: `extract_and_save(text, chat_id)` — orchestrates extraction + CRUD
- `backend/router/api.py`: `store_reminder` branch before escalation logic; returns formatted confirmation or friendly error
- `backend/scheduler/reminders.py`: `AsyncIOScheduler` 60s job, `_send_whatsapp` (raw httpx), `create_scheduler`
- `backend/interfaces/whatsapp.py`: `POST /whatsapp` — Twilio signature validation, TwiML reply with XML-escaped response
- `backend/main.py`: scheduler started/stopped in lifespan, whatsapp router registered
- 61 tests passing

### Session 4 — Embedding + RAG layer (complete)
- `backend/memory/vector.py`: `EmbedResult` dataclass, `embed()` (Ollama nomic-embed-text → OpenAI text-embedding-3-small fallback), `_chunk()` (word-window, 512/50), `store_chunk()` (embed + Qdrant upsert, auto-creates collection), `search()` (embed query + Qdrant search, returns payload dicts), `_get_qdrant()` lazy accessor
- `backend/router/api.py`: `store_knowledge` branch (chunk → store, bypasses escalation), `query` enrichment (search → inject context → second Tier 1 call), `GET /embed-status` (returns active embedding model + dimensions)
- `backend/requirements.txt`: added `qdrant-client>=1.7.0`, `openai>=1.0.0`
- 78 tests passing

### Session 5 — Ingestion pipeline (complete)
- `backend/ingestion/__init__.py`: empty package marker
- `backend/ingestion/registry.py`: `IngestStatus` dataclass, `TaskRegistry` (in-memory, class-backed), module-level `registry` singleton
- `backend/ingestion/fetch.py`: `fetch_bytes(source, auth, headers) → bytes` — shared primitive for UploadFile / local path / HTTP URL
- `backend/ingestion/pdf.py`: `ingest_pdf(source, filename, auth) → int` — PyMuPDF page extraction → `_chunk` → `store_chunk`; fitz context manager; `ImportError` hint if pymupdf missing
- `backend/ingestion/url.py`: `ingest_url(url, min_chars=500) → int` — httpx + BeautifulSoup; og:title → meta[name=title] → `<title>` → URL title chain; strips nav/footer/header/script/style; optional Playwright fallback; `ValueError` if content still too short
- `backend/ingestion/youtube.py`: `ingest_youtube(url) → int` — youtube-transcript-api + yt-dlp; sentence-grouped transcript (space within sentence, `\n` between); `_extract_video_id` handles watch/youtu.be/shorts; maps transcript/metadata errors to `ValueError`
- `backend/router/ingest.py`: `POST /ingest` (sync, JSON or multipart), `GET /ingest/{id}/status` (404 on unknown), `run_ingest` background task (updates registry, notifies via WhatsApp on complete or error)
- `backend/interfaces/whatsapp.py`: rewritten — detects Twilio PDF attachment (`MediaUrl0` + `MediaContentType0==application/pdf`) and HTTP URLs in body; queues `BackgroundTask`; replies immediately with processing confirmation; plain messages pass through unchanged
- `backend/router/api.py`: `store_knowledge` branch updated — URL auto-detection with trailing punctuation strip; YouTube vs generic URL dispatch; falls back to chunk+store for plain text
- `backend/main.py`: ingest router registered
- `backend/requirements.txt`: added `pymupdf`, `beautifulsoup4`, `lxml`, `youtube-transcript-api`, `yt-dlp`
- 144 tests passing

### What's not built yet
- Tool execution (httpx calls from OpenAPI specs in `api_tools` table)
- `GET /health` does not yet check the router is wired (it only checks infra services)