# Second Brain — Project Scaffold Design

**Date:** 2026-04-20  
**Scope:** Initial infrastructure scaffold — Docker services, FastAPI app skeleton, SQLAlchemy models, Alembic migrations, health endpoint.

---

## 1. Docker Compose

Four services: `postgres`, `qdrant`, `ollama`, `backend`. The `backend` service declares `depends_on` with `condition: service_healthy` for all three infrastructure services, so it will not start until each passes its healthcheck.

### Postgres
- Image: `postgres:16`
- Named volume: `postgres_data:/var/lib/postgresql/data`
- Healthcheck: `pg_isready -U $POSTGRES_USER`

### Qdrant
- Image: `qdrant/qdrant:latest`
- Named volume: `qdrant_data:/qdrant/storage`
- Healthcheck: `GET http://localhost:6333/healthz`

### Ollama
- Image: `ollama/ollama:latest`
- Named volume: `ollama_data:/root/.ollama` — model layers persist across restarts
- Custom entrypoint script (`ollama-entrypoint.sh`):
  1. Start `ollama serve` in the background
  2. Poll `GET /api/tags` until the server responds
  3. `ollama pull nomic-embed-text` — no-op if already cached in volume
  4. `ollama pull gemma3:4b` — no-op if already cached in volume
  5. `wait` on the foreground serve process
- Healthcheck: `curl -sf http://localhost:11434/api/tags | jq -e '[.models[].name] | (contains(["nomic-embed-text"]) and contains(["gemma3:4b"]))'`
  - This ensures the backend only starts after both models are fully loaded

### Backend
- Build context: `./backend`
- `depends_on`: postgres, qdrant, ollama — all `condition: service_healthy`
- Mounts `.env` for environment variables

---

## 2. Backend Structure

```
backend/
  main.py           # FastAPI app, lifespan hook, /health route
  config.py         # pydantic-settings Settings class, reads from env
  db.py             # SQLAlchemy async engine + AsyncSession factory
  memory/
    postgres.py     # ORM models: reminders, knowledge_items, api_tools
  migrations/
    env.py          # Alembic env, imports models for autogenerate
    versions/       # Generated migration scripts
  alembic.ini       # Alembic config
  Dockerfile
  requirements.txt
```

**Lifespan event** (`@asynccontextmanager` passed to `FastAPI(lifespan=...)`):
- On startup: run `alembic upgrade head` programmatically via `alembic.config.Config` + `alembic.command.upgrade` — migrations apply before the first request is served.
- On shutdown: dispose the async engine.

---

## 3. Database Models (`backend/memory/postgres.py`)

All tables use server-generated UUID primary keys (`server_default=func.gen_random_uuid()`).

### `reminders`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID | PK, server-generated |
| `text` | Text | Reminder content |
| `trigger_at` | TIMESTAMPTZ | When to fire |
| `sent` | Boolean | Default `false` |
| `chat_id` | Text | Twilio WhatsApp chat identifier |

### `knowledge_items`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID | PK, server-generated |
| `title` | Text | Document title |
| `source_type` | Text | e.g. `web`, `pdf`, `note` |
| `source_url` | Text | Origin URL or path |
| `date_added` | TIMESTAMPTZ | Default `now()` |
| `chunk_index` | Integer | Position within source document |

### `api_tools`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID | PK, server-generated |
| `name` | Text | Unique tool name |
| `description` | Text | For LLM tool-selection prompt |
| `base_url` | Text | API base URL |
| `spec` | JSONB | Full OpenAPI spec payload |
| `auth_type` | Text | e.g. `bearer`, `apikey`, `none` |
| `auth_secret_env` | Text | Name of the env var holding the secret (e.g. `"MY_TOOL_API_KEY"`); the actual secret is never stored in the DB — it is resolved at call time via `os.environ[auth_secret_env]` |

---

## 4. `/health` Endpoint

```
GET /health
→ 200 OK        if postgres + qdrant + ollama all pass
→ 503 Service Unavailable   if any check fails
```

**Response body (always JSON):**
```json
{
  "postgres": "ok",
  "qdrant":   "ok",
  "ollama":   "ok"
}
```
Failed checks return `"error: <message>"` for their value.

**Implementation:**
- All three checks run concurrently via `asyncio.gather(return_exceptions=True)`
- Postgres: execute `SELECT 1` via SQLAlchemy async session
- Qdrant: `httpx.AsyncClient().get(QDRANT_URL + "/healthz")`
- Ollama: `GET /api/tags`, assert response JSON contains both `nomic-embed-text` and `gemma3:4b` in `models[].name`
- If any result is an exception or the Ollama model assertion fails → HTTP 503

---

## 5. Environment Variables

Defined in `.env.example` at repo root. All required at runtime:

```
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_WHATSAPP_FROM=
DATABASE_URL=postgresql+asyncpg://user:password@postgres:5432/secondbrain
QDRANT_URL=http://qdrant:6333
OLLAMA_URL=http://ollama:11434
```

`config.py` uses `pydantic-settings` to load and validate all vars at startup; missing required vars raise a clear error before the app binds to a port.

---

## Out of Scope for This Scaffold

- WhatsApp webhook handler
- LLM routing / escalation logic
- Embedding pipeline
- APScheduler integration
- Tool execution via httpx
- Qdrant collection creation / vector ingestion
