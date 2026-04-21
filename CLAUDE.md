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
- Embedding abstraction: always call `embed(text)`, never the model directly
- Every ingested document gets: {source_type, source_url, title, date_added, chunk_index}

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

### What's not built yet
- WhatsApp webhook handler (Twilio `POST /webhook`)
- Embedding pipeline (`embed(text)` abstraction, Qdrant ingestion)
- APScheduler integration (reminder dispatch)
- Tool execution (httpx calls from OpenAPI specs in `api_tools` table)
- `GET /health` does not yet check the router is wired (it only checks infra services)