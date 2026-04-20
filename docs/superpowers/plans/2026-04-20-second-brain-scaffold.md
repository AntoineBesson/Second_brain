# Second Brain Scaffold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the full project scaffold — Docker services (Postgres, Qdrant, Ollama), FastAPI app with auto-migrations, SQLAlchemy models, and a `/health` endpoint that returns 503 if any service is down.

**Architecture:** A FastAPI app with async SQLAlchemy talking to Postgres, httpx for Qdrant/Ollama health probes, and Alembic running `upgrade head` automatically in the lifespan event before the app accepts requests. Docker Compose wires four services together with health-gated startup ordering.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy (asyncio), asyncpg, Alembic, pydantic-settings, httpx, pytest, pytest-asyncio, Docker Compose, Postgres 16, Qdrant latest, Ollama latest.

---

## File Map

| File | Responsibility |
|---|---|
| `docker-compose.yml` | Defines 4 services, named volumes, healthchecks, startup ordering |
| `ollama-entrypoint.sh` | Starts `ollama serve`, waits, pulls both models (no-op if cached) |
| `.env.example` | Template with all required env var names |
| `.gitignore` | Excludes `.env`, `__pycache__`, etc. |
| `alembic.ini` | Alembic config; `script_location = backend/migrations` |
| `pytest.ini` | Sets `asyncio_mode = auto` |
| `backend/Dockerfile` | Python 3.12-slim image, installs requirements, runs uvicorn |
| `backend/requirements.txt` | All pinned dependencies |
| `backend/__init__.py` | Empty package marker |
| `backend/config.py` | `Settings` via pydantic-settings; validates all env vars at startup |
| `backend/db.py` | Async SQLAlchemy engine + `AsyncSessionLocal` session factory |
| `backend/health.py` | `check_postgres()`, `check_qdrant()`, `check_ollama()` + `/health` router |
| `backend/main.py` | FastAPI app; lifespan runs migrations, registers health router |
| `backend/memory/__init__.py` | Empty package marker |
| `backend/memory/postgres.py` | ORM models: `Reminder`, `KnowledgeItem`, `ApiTool` + `Base` |
| `backend/migrations/env.py` | Alembic env; reads `DATABASE_URL`, targets `Base.metadata` |
| `backend/migrations/script.py.mako` | Standard Alembic migration template |
| `backend/migrations/versions/` | Auto-generated migration scripts (created in Task 5) |
| `tests/__init__.py` | Empty package marker |
| `tests/conftest.py` | Sets env vars before any import; pytest fixtures |
| `tests/test_config.py` | Validates Settings raises on missing required fields |
| `tests/test_models.py` | Validates model column sets without a DB |
| `tests/test_health.py` | Unit tests for all three check functions + endpoint, fully mocked |

---

## Task 1: Project skeleton

**Files:**
- Create: `.gitignore`
- Create: `pytest.ini`
- Create: `backend/__init__.py`
- Create: `backend/memory/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create `.gitignore`**

```
.env
__pycache__/
*.pyc
*.pyo
.pytest_cache/
*.egg-info/
dist/
build/
.mypy_cache/
.venv/
venv/
```

- [ ] **Step 2: Create `pytest.ini`**

```ini
[pytest]
asyncio_mode = auto
```

- [ ] **Step 3: Create package markers**

`backend/__init__.py` — empty file.
`backend/memory/__init__.py` — empty file.
`tests/__init__.py` — empty file.

- [ ] **Step 4: Create `tests/conftest.py`**

Env vars must be set before any backend import fires `Settings()`.

```python
import os

# Set before any backend module is imported so Settings() resolves correctly
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("TWILIO_ACCOUNT_SID", "test-sid")
os.environ.setdefault("TWILIO_AUTH_TOKEN", "test-token")
os.environ.setdefault("TWILIO_WHATSAPP_FROM", "whatsapp:+14155551234")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/test")
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("OLLAMA_URL", "http://localhost:11434")
```

- [ ] **Step 5: Commit**

```bash
git add .gitignore pytest.ini backend/__init__.py backend/memory/__init__.py tests/__init__.py tests/conftest.py
git commit -m "chore: project skeleton, pytest config, package markers"
```

---

## Task 2: `.env.example` and `requirements.txt`

**Files:**
- Create: `.env.example`
- Create: `backend/requirements.txt`

- [ ] **Step 1: Create `.env.example`**

```
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_WHATSAPP_FROM=whatsapp:+14155551234
DATABASE_URL=postgresql+asyncpg://secondbrain:secondbrain@postgres:5432/secondbrain
QDRANT_URL=http://qdrant:6333
OLLAMA_URL=http://ollama:11434
```

- [ ] **Step 2: Create `backend/requirements.txt`**

```
fastapi==0.115.0
uvicorn[standard]==0.30.6
sqlalchemy[asyncio]==2.0.36
asyncpg==0.29.0
alembic==1.13.3
pydantic-settings==2.5.2
httpx==0.27.2
pytest==8.3.3
pytest-asyncio==0.24.0
python-dotenv==1.0.1
```

- [ ] **Step 3: Commit**

```bash
git add .env.example backend/requirements.txt
git commit -m "chore: add env template and pinned requirements"
```

---

## Task 3: Config module

**Files:**
- Create: `backend/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
import pytest
from pydantic import ValidationError
from backend.config import Settings


def test_settings_raises_on_missing_database_url():
    with pytest.raises(ValidationError):
        Settings(
            anthropic_api_key="k",
            openai_api_key="k",
            twilio_account_sid="k",
            twilio_auth_token="k",
            twilio_whatsapp_from="whatsapp:+1",
            # database_url intentionally omitted
            qdrant_url="http://localhost:6333",
            ollama_url="http://localhost:11434",
        )


def test_settings_accepts_all_fields():
    s = Settings(
        anthropic_api_key="a",
        openai_api_key="b",
        twilio_account_sid="c",
        twilio_auth_token="d",
        twilio_whatsapp_from="whatsapp:+1",
        database_url="postgresql+asyncpg://u:p@h:5432/db",
        qdrant_url="http://localhost:6333",
        ollama_url="http://localhost:11434",
    )
    assert s.database_url == "postgresql+asyncpg://u:p@h:5432/db"
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_config.py -v
```

Expected: `ModuleNotFoundError` — `backend.config` doesn't exist yet.

- [ ] **Step 3: Create `backend/config.py`**

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str
    openai_api_key: str
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_whatsapp_from: str
    database_url: str
    qdrant_url: str
    ollama_url: str

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_config.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/config.py tests/test_config.py
git commit -m "feat: config module with pydantic-settings validation"
```

---

## Task 4: Database engine

**Files:**
- Create: `backend/db.py`

No isolated unit test — the engine is exercised by health check tests (Task 6) and integration (Task 10).

- [ ] **Step 1: Create `backend/db.py`**

```python
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.config import settings

engine = create_async_engine(settings.database_url, echo=False, future=True)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
```

- [ ] **Step 2: Commit**

```bash
git add backend/db.py
git commit -m "feat: async SQLAlchemy engine and session factory"
```

---

## Task 5: SQLAlchemy models

**Files:**
- Create: `backend/memory/postgres.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models.py
from sqlalchemy import inspect

from backend.memory.postgres import ApiTool, KnowledgeItem, Reminder


def test_reminder_columns():
    cols = {c.key for c in inspect(Reminder).columns}
    assert cols == {"id", "text", "trigger_at", "sent", "chat_id"}


def test_knowledge_item_columns():
    cols = {c.key for c in inspect(KnowledgeItem).columns}
    assert cols == {"id", "title", "source_type", "source_url", "date_added", "chunk_index"}


def test_api_tool_columns():
    cols = {c.key for c in inspect(ApiTool).columns}
    assert cols == {"id", "name", "description", "base_url", "spec", "auth_type", "auth_secret_env"}


def test_api_tool_name_is_unique():
    name_col = inspect(ApiTool).columns["name"]
    assert name_col.unique
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_models.py -v
```

Expected: `ModuleNotFoundError` — `backend.memory.postgres` doesn't exist yet.

- [ ] **Step 3: Create `backend/memory/postgres.py`**

```python
from sqlalchemy import Boolean, Column, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Reminder(Base):
    __tablename__ = "reminders"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    text = Column(Text, nullable=False)
    trigger_at = Column(TIMESTAMP(timezone=True), nullable=False)
    sent = Column(Boolean, nullable=False, server_default=text("false"))
    chat_id = Column(Text, nullable=False)


class KnowledgeItem(Base):
    __tablename__ = "knowledge_items"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    title = Column(Text, nullable=False)
    source_type = Column(Text, nullable=False)
    source_url = Column(Text)
    date_added = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
    chunk_index = Column(Integer, nullable=False, server_default=text("0"))


class ApiTool(Base):
    __tablename__ = "api_tools"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name = Column(Text, nullable=False, unique=True)
    description = Column(Text, nullable=False)
    base_url = Column(Text, nullable=False)
    spec = Column(JSONB, nullable=False)
    auth_type = Column(Text, nullable=False)
    auth_secret_env = Column(Text)
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_models.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/memory/postgres.py tests/test_models.py
git commit -m "feat: SQLAlchemy ORM models — reminders, knowledge_items, api_tools"
```

---

## Task 6: Alembic setup and initial migration

**Files:**
- Create: `alembic.ini`
- Create: `backend/migrations/env.py`
- Create: `backend/migrations/script.py.mako`
- Create: `backend/migrations/versions/` (directory, gitkeep)

> **Note:** Generating the migration (`alembic revision --autogenerate`) requires a running Postgres. Do this step after `docker-compose up -d postgres` in Task 9, or run it from the Docker backend service. The migration file itself is committed so it travels with the repo.

- [ ] **Step 1: Create `alembic.ini` at project root**

```ini
[alembic]
script_location = backend/migrations
sqlalchemy.url =

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

The `sqlalchemy.url` is intentionally empty — `env.py` populates it dynamically from `DATABASE_URL`.

- [ ] **Step 2: Create `backend/migrations/env.py`**

```python
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make project root importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.config import settings
from backend.memory.postgres import Base

config = context.config

# Alembic uses sync SQLAlchemy — strip the asyncpg driver prefix
sync_url = settings.database_url.replace("+asyncpg", "")
config.set_main_option("sqlalchemy.url", sync_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 3: Create `backend/migrations/script.py.mako`**

```
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 4: Create `backend/migrations/versions/.gitkeep`**

Empty file so the `versions/` directory is tracked by git before any migrations exist.

- [ ] **Step 5: Commit the Alembic setup**

```bash
git add alembic.ini backend/migrations/
git commit -m "chore: alembic setup — env.py, ini, template"
```

- [ ] **Step 6: Generate the initial migration (requires Postgres running)**

After `docker-compose up -d postgres` (Task 9), run:

```bash
alembic revision --autogenerate -m "initial schema"
```

Expected output ends with: `Generating .../versions/<hash>_initial_schema.py ... done`

- [ ] **Step 7: Inspect the generated migration**

Open `backend/migrations/versions/<hash>_initial_schema.py`. Verify `upgrade()` contains `op.create_table` calls for `reminders`, `knowledge_items`, and `api_tools` with the correct column types.

- [ ] **Step 8: Commit the generated migration**

```bash
git add backend/migrations/versions/
git commit -m "feat: initial schema migration — reminders, knowledge_items, api_tools"
```

---

## Task 7: Health check functions

**Files:**
- Create: `backend/health.py`
- Create: `tests/test_health.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_health.py
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# --- check_postgres ---

async def test_check_postgres_ok():
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.health.AsyncSessionLocal", return_value=mock_cm):
        from backend.health import check_postgres
        result = await check_postgres()

    assert result == "ok"


async def test_check_postgres_error():
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(side_effect=Exception("connection refused"))
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.health.AsyncSessionLocal", return_value=mock_cm):
        from backend.health import check_postgres
        result = await check_postgres()

    assert result.startswith("error:")


# --- check_qdrant ---

async def test_check_qdrant_ok():
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    mock_client_cm = MagicMock()
    mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.health.httpx.AsyncClient", return_value=mock_client_cm):
        from backend.health import check_qdrant
        result = await check_qdrant()

    assert result == "ok"


async def test_check_qdrant_error():
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=Exception("refused"))

    mock_client_cm = MagicMock()
    mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.health.httpx.AsyncClient", return_value=mock_client_cm):
        from backend.health import check_qdrant
        result = await check_qdrant()

    assert result.startswith("error:")


# --- check_ollama ---

async def test_check_ollama_ok():
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={
        "models": [
            {"name": "nomic-embed-text:latest"},
            {"name": "gemma3:4b"},
        ]
    })

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    mock_client_cm = MagicMock()
    mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.health.httpx.AsyncClient", return_value=mock_client_cm):
        from backend.health import check_ollama
        result = await check_ollama()

    assert result == "ok"


async def test_check_ollama_missing_model():
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={
        "models": [{"name": "nomic-embed-text:latest"}]  # gemma3:4b absent
    })

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    mock_client_cm = MagicMock()
    mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.health.httpx.AsyncClient", return_value=mock_client_cm):
        from backend.health import check_ollama
        result = await check_ollama()

    assert result.startswith("error:")
    assert "gemma3:4b" in result


async def test_check_ollama_network_error():
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=Exception("timeout"))

    mock_client_cm = MagicMock()
    mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.health.httpx.AsyncClient", return_value=mock_client_cm):
        from backend.health import check_ollama
        result = await check_ollama()

    assert result.startswith("error:")
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_health.py -v
```

Expected: `ModuleNotFoundError` — `backend.health` doesn't exist yet.

- [ ] **Step 3: Create `backend/health.py`**

```python
import asyncio

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from backend.config import settings
from backend.db import AsyncSessionLocal

router = APIRouter()

# Model names as returned by Ollama — base name only (strip `:tag` before comparing)
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
            # Strip `:tag` suffix before comparing (e.g. "nomic-embed-text:latest" → "nomic-embed-text")
            present = {m["name"].split(":")[0] for m in r.json().get("models", [])}
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
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_health.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Run full test suite**

```
pytest tests/ -v
```

Expected: all tests pass (config + models + health).

- [ ] **Step 6: Commit**

```bash
git add backend/health.py tests/test_health.py
git commit -m "feat: health check functions and /health router (503 on any failure)"
```

---

## Task 8: FastAPI app entry point

**Files:**
- Create: `backend/main.py`

- [ ] **Step 1: Create `backend/main.py`**

```python
from contextlib import asynccontextmanager

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from fastapi import FastAPI

from backend.db import engine
from backend.health import router as health_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Run pending migrations synchronously before serving any requests.
    # Blocking I/O here is intentional — no requests are in-flight at startup.
    cfg = AlembicConfig("alembic.ini")
    alembic_command.upgrade(cfg, "head")
    yield
    await engine.dispose()


app = FastAPI(title="Second Brain", lifespan=lifespan)
app.include_router(health_router)
```

- [ ] **Step 2: Verify import is clean**

```
python -c "from backend.main import app; print('OK')"
```

Expected: `OK` (no import errors).

- [ ] **Step 3: Commit**

```bash
git add backend/main.py
git commit -m "feat: FastAPI app with lifespan migration runner and /health router"
```

---

## Task 9: Dockerfile, Ollama entrypoint, and Docker Compose

**Files:**
- Create: `backend/Dockerfile`
- Create: `ollama-entrypoint.sh`
- Create: `docker-compose.yml`
- Create: `.env` (copied from `.env.example`, then filled in — not committed)

- [ ] **Step 1: Create `backend/Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Create `ollama-entrypoint.sh`**

```bash
#!/bin/sh
set -e

# Start Ollama server in background
ollama serve &
SERVE_PID=$!

# Wait until the REST API responds
echo "[ollama] Waiting for server to start..."
until curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; do
    sleep 2
done
echo "[ollama] Server ready."

# Pull models — these are no-ops if layers are already cached in ollama_data volume
echo "[ollama] Pulling nomic-embed-text..."
ollama pull nomic-embed-text

echo "[ollama] Pulling gemma3:4b..."
ollama pull gemma3:4b

echo "[ollama] All models ready."

# Hand control back to the server process
wait $SERVE_PID
```

- [ ] **Step 3: Create `docker-compose.yml`**

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: secondbrain
      POSTGRES_PASSWORD: secondbrain
      POSTGRES_DB: secondbrain
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U secondbrain"]
      interval: 5s
      timeout: 5s
      retries: 10

  qdrant:
    image: qdrant/qdrant:latest
    volumes:
      - qdrant_data:/qdrant/storage
    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://localhost:6333/healthz || exit 1"]
      interval: 5s
      timeout: 5s
      retries: 10

  ollama:
    image: ollama/ollama:latest
    volumes:
      - ollama_data:/root/.ollama
      - ./ollama-entrypoint.sh:/entrypoint.sh:ro
    entrypoint: ["/bin/sh", "/entrypoint.sh"]
    healthcheck:
      test:
        - CMD-SHELL
        - >
          curl -sf http://localhost:11434/api/tags |
          python3 -c "
          import sys, json;
          d = json.load(sys.stdin);
          names = {m['name'].split(':')[0] for m in d.get('models', [])};
          sys.exit(0 if {'nomic-embed-text', 'gemma3:4b'}.issubset(names) else 1)
          "
      interval: 30s
      timeout: 15s
      retries: 20
      start_period: 300s

  backend:
    build: ./backend
    env_file: .env
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
      qdrant:
        condition: service_healthy
      ollama:
        condition: service_healthy

volumes:
  postgres_data:
  qdrant_data:
  ollama_data:
```

> `start_period: 300s` on Ollama gives gemma3:4b time to download on first run without the healthcheck counting failures. After the first run the volume cache makes restarts fast.

- [ ] **Step 4: Copy `.env.example` to `.env` and fill in secrets**

```bash
cp .env.example .env
```

Edit `.env` — the Docker Compose defaults for `DATABASE_URL`, `QDRANT_URL`, and `OLLAMA_URL` are already correct in the example. Fill in `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and Twilio credentials.

- [ ] **Step 5: Commit everything except `.env`**

```bash
git add backend/Dockerfile ollama-entrypoint.sh docker-compose.yml
git commit -m "feat: Dockerfile, Ollama entrypoint, docker-compose with health-gated startup"
```

---

## Task 10: Generate migration and verify end-to-end

This task requires Docker Desktop running.

- [ ] **Step 1: Start Postgres only (needed for autogenerate)**

```bash
docker compose up -d postgres
```

Wait for it to be healthy:

```bash
docker compose ps
```

Expected: `postgres` shows `healthy`.

- [ ] **Step 2: Install Python deps locally (for alembic CLI)**

```bash
pip install -r backend/requirements.txt
```

- [ ] **Step 3: Generate the initial migration**

```bash
alembic revision --autogenerate -m "initial schema"
```

Expected: a new file appears under `backend/migrations/versions/`.

- [ ] **Step 4: Inspect the generated migration**

Open `backend/migrations/versions/<hash>_initial_schema.py`. Confirm `upgrade()` has `op.create_table` calls for all three tables with correct column types. The JSONB column for `api_tools.spec` should appear as `sa.Column('spec', postgresql.JSONB(...), ...)`.

- [ ] **Step 5: Commit the migration**

```bash
git add backend/migrations/versions/
git commit -m "feat: initial schema migration — reminders, knowledge_items, api_tools"
```

- [ ] **Step 6: Bring all services up**

```bash
docker compose up -d
```

> First run: Ollama will pull ~2.5 GB (gemma3:4b) + ~300 MB (nomic-embed-text). The backend service will not start until Ollama's healthcheck passes. Monitor with:

```bash
docker compose logs -f ollama
```

- [ ] **Step 7: Wait for all services to be healthy**

```bash
docker compose ps
```

Expected: all four services show `healthy` or `running`. The backend will transition from `starting` to `running` once the three dependencies pass.

- [ ] **Step 8: Hit `/health` and verify 200**

```bash
curl -s http://localhost:8000/health | python3 -m json.tool
```

Expected:

```json
{
    "postgres": "ok",
    "qdrant": "ok",
    "ollama": "ok"
}
```

HTTP status must be 200. Verify with:

```bash
curl -o /dev/null -w "%{http_code}" http://localhost:8000/health
```

Expected: `200`

- [ ] **Step 9: Run unit tests one final time**

```bash
pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 10: Final commit**

```bash
git add -A
git status  # confirm only intended files are staged
git commit -m "chore: scaffold complete — all services healthy, /health returns 200"
```
