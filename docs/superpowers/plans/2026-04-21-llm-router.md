# Two-Tier LLM Router Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a two-tier LLM router — Tier 1 classifies intent with gemma3:4b via Ollama (falling back to Haiku if unavailable), Tier 2 escalates complex queries to claude-sonnet-4-6, logging every escalation to Postgres.

**Architecture:** Incoming messages hit `POST /message`, which calls Tier 1 (Ollama → Haiku fallback) to get a structured JSON classification. If complexity > 0.7, escalate=true, or intent is in the escalation set, the request is forwarded to Tier 2 (claude-sonnet-4-6) with Tier 1's partial response as context, and the escalation is logged to a Postgres `escalations` table. The endpoint returns `{response, tier_used, intent}`.

**Tech Stack:** FastAPI, SQLAlchemy asyncio, httpx, anthropic SDK (AsyncAnthropic), pydantic-settings, pytest-asyncio, unittest.mock

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/memory/postgres.py` | Modify | Add `Escalation` ORM model |
| `backend/migrations/versions/a1b2c3d4e5f6_initial_schema.py` | Create | Manual migration: all 4 tables |
| `backend/router/__init__.py` | Create | Empty package marker |
| `backend/router/intent.py` | Create | Tier 1 classifier — Ollama + Haiku fallback |
| `backend/router/escalation.py` | Create | Escalation decision, Tier 2 call, DB logging |
| `backend/router/api.py` | Create | `POST /message` FastAPI router |
| `backend/main.py` | Modify | Include the message router |
| `backend/requirements.txt` | Modify | Add `anthropic>=0.40.0` |
| `tests/test_models.py` | Modify | Add `Escalation` column test |
| `tests/test_router.py` | Create | All router tests |

---

## Task 1: Escalation ORM Model + Migration File

**Files:**
- Modify: `backend/memory/postgres.py`
- Create: `backend/migrations/versions/a1b2c3d4e5f6_initial_schema.py`
- Modify: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_models.py` (below the existing tests, and add `Escalation` to the import):

```python
from backend.memory.postgres import ApiTool, Escalation, KnowledgeItem, Reminder


def test_escalation_columns():
    cols = {c.key for c in inspect(Escalation).columns}
    assert cols == {"id", "message", "reason", "chat_id", "timestamp"}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_models.py::test_escalation_columns -v
```

Expected: `ImportError: cannot import name 'Escalation'`

- [ ] **Step 3: Add the Escalation model to `backend/memory/postgres.py`**

The full file after the edit (add the `Escalation` class at the bottom, and no other changes):

```python
from sqlalchemy import Boolean, Column, Integer, Text
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Reminder(Base):
    __tablename__ = "reminders"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=sql_text("gen_random_uuid()"))
    text = Column(Text, nullable=False)
    trigger_at = Column(TIMESTAMP(timezone=True), nullable=False)
    sent = Column(Boolean, nullable=False, server_default=sql_text("false"))
    chat_id = Column(Text, nullable=False)


class KnowledgeItem(Base):
    __tablename__ = "knowledge_items"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=sql_text("gen_random_uuid()"))
    title = Column(Text, nullable=False)
    source_type = Column(Text, nullable=False)
    source_url = Column(Text)
    date_added = Column(TIMESTAMP(timezone=True), nullable=False, server_default=sql_text("now()"))
    chunk_index = Column(Integer, nullable=False, server_default=sql_text("0"))


class ApiTool(Base):
    __tablename__ = "api_tools"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=sql_text("gen_random_uuid()"))
    name = Column(Text, nullable=False, unique=True)
    description = Column(Text, nullable=False)
    base_url = Column(Text, nullable=False)
    spec = Column(JSONB, nullable=False)
    auth_type = Column(Text, nullable=False)
    auth_secret_env = Column(Text)


class Escalation(Base):
    __tablename__ = "escalations"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=sql_text("gen_random_uuid()"))
    message = Column(Text, nullable=False)
    reason = Column(Text, nullable=False)
    chat_id = Column(Text, nullable=False)
    timestamp = Column(TIMESTAMP(timezone=True), nullable=False, server_default=sql_text("now()"))
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_models.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Write the migration file manually**

Create `backend/migrations/versions/a1b2c3d4e5f6_initial_schema.py` with this exact content.

Note: the postgres container does NOT expose port 5432 to the host, so `alembic revision --autogenerate` cannot connect. Writing the migration manually is the correct approach here.

```python
"""initial schema

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-04-21 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reminders",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("trigger_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "sent",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("chat_id", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "knowledge_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column(
            "date_added",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "chunk_index",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "api_tools",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column(
            "spec",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("auth_type", sa.Text(), nullable=False),
        sa.Column("auth_secret_env", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "escalations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("chat_id", sa.Text(), nullable=False),
        sa.Column(
            "timestamp",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("escalations")
    op.drop_table("api_tools")
    op.drop_table("knowledge_items")
    op.drop_table("reminders")
```

- [ ] **Step 6: Commit**

```bash
git add backend/memory/postgres.py \
        backend/migrations/versions/a1b2c3d4e5f6_initial_schema.py \
        tests/test_models.py
git commit -m "feat: add Escalation ORM model and initial schema migration"
```

---

## Task 2: Tier 1 Intent Classifier (`intent.py`)

**Files:**
- Create: `backend/router/__init__.py`
- Create: `backend/router/intent.py`
- Modify: `backend/requirements.txt`
- Create: `tests/test_router.py`

- [ ] **Step 1: Add anthropic to requirements**

Edit `backend/requirements.txt` — append one line:

```
anthropic>=0.40.0
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_router.py`:

```python
# tests/test_router.py
import json
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.router.intent import Tier1Response, _call_haiku_fallback, _call_ollama, call_tier1


# ---------------------------------------------------------------------------
# Tier 1 happy path — Ollama returns valid JSON
# ---------------------------------------------------------------------------

async def test_call_tier1_happy_path():
    expected = Tier1Response(
        intent="general",
        complexity=0.3,
        escalate=False,
        escalation_reason="",
        response="Hello there!",
    )
    with patch("backend.router.intent._call_ollama", AsyncMock(return_value=expected)):
        result = await call_tier1("Hello")

    assert result.intent == "general"
    assert result.complexity == 0.3
    assert result.escalate is False
    assert result.response == "Hello there!"


# ---------------------------------------------------------------------------
# Tier 1 fallback — Ollama raises, Haiku is called instead
# ---------------------------------------------------------------------------

async def test_call_tier1_falls_back_to_haiku_on_ollama_error():
    haiku_result = Tier1Response(
        intent="general",
        complexity=0.2,
        escalate=False,
        escalation_reason="",
        response="Hi from Haiku",
    )
    with patch(
        "backend.router.intent._call_ollama",
        AsyncMock(side_effect=httpx.ConnectError("ollama down")),
    ), patch(
        "backend.router.intent._call_haiku_fallback",
        AsyncMock(return_value=haiku_result),
    ):
        result = await call_tier1("Hello")

    assert result.response == "Hi from Haiku"


# ---------------------------------------------------------------------------
# _call_ollama parses the Ollama /api/chat JSON envelope correctly
# ---------------------------------------------------------------------------

async def test_call_ollama_parses_response():
    payload = {
        "intent": "recall",
        "complexity": 0.4,
        "escalate": False,
        "escalation_reason": "",
        "response": "Here is what I found.",
    }
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(
        return_value={"message": {"content": json.dumps(payload)}}
    )

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.router.intent.httpx.AsyncClient", return_value=mock_cm):
        result = await _call_ollama("What did I save yesterday?")

    assert result.intent == "recall"
    assert result.complexity == 0.4
    assert result.response == "Here is what I found."


# ---------------------------------------------------------------------------
# _call_haiku_fallback parses the Anthropic response correctly
# ---------------------------------------------------------------------------

async def test_call_haiku_fallback_parses_response():
    payload = {
        "intent": "general",
        "complexity": 0.1,
        "escalate": False,
        "escalation_reason": "",
        "response": "I can help with that.",
    }
    mock_content = MagicMock()
    mock_content.text = json.dumps(payload)

    mock_msg = MagicMock()
    mock_msg.content = [mock_content]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_msg)

    with patch("backend.router.intent.AsyncAnthropic", return_value=mock_client):
        result = await _call_haiku_fallback("Hi")

    assert result.intent == "general"
    assert result.response == "I can help with that."
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/test_router.py -v
```

Expected: `ModuleNotFoundError: No module named 'backend.router'`

- [ ] **Step 4: Create `backend/router/__init__.py`**

```python
```

(empty file — just the package marker)

- [ ] **Step 5: Create `backend/router/intent.py`**

```python
import json
from dataclasses import dataclass

import httpx
from anthropic import AsyncAnthropic

from backend.config import settings

SYSTEM_PROMPT = (
    "You are a personal assistant intent classifier. "
    "Analyze the user message and respond with ONLY valid JSON — no markdown, no explanation:\n"
    '{\n'
    '  "intent": "<one of: store_reminder, store_knowledge, query, recall, tool_call, general>",\n'
    '  "complexity": <float 0.0-1.0>,\n'
    '  "escalate": <true|false>,\n'
    '  "escalation_reason": "<empty string if not escalating>",\n'
    '  "response": "<your response to the user>"\n'
    "}"
)


@dataclass
class Tier1Response:
    intent: str
    complexity: float
    escalate: bool
    escalation_reason: str
    response: str


async def call_tier1(message: str) -> Tier1Response:
    """Call Tier 1 (Ollama gemma3:4b). Falls back to Haiku if Ollama is unavailable."""
    try:
        return await _call_ollama(message)
    except Exception:
        return await _call_haiku_fallback(message)


async def _call_ollama(message: str) -> Tier1Response:
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            f"{settings.ollama_url}/api/chat",
            json={
                "model": "gemma3:4b",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": message},
                ],
                "stream": False,
                "format": "json",
            },
        )
        r.raise_for_status()
    content = r.json()["message"]["content"]
    return _parse_response(content)


async def _call_haiku_fallback(message: str) -> Tier1Response:
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": message}],
    )
    return _parse_response(response.content[0].text)


def _parse_response(content: str) -> Tier1Response:
    data = json.loads(content)
    return Tier1Response(
        intent=data["intent"],
        complexity=float(data["complexity"]),
        escalate=bool(data["escalate"]),
        escalation_reason=data.get("escalation_reason", ""),
        response=data["response"],
    )
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/test_router.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/router/__init__.py \
        backend/router/intent.py \
        backend/requirements.txt \
        tests/test_router.py
git commit -m "feat: add Tier 1 intent classifier with Ollama + Haiku fallback"
```

---

## Task 3: Escalation Logic (`escalation.py`)

**Files:**
- Create: `backend/router/escalation.py`
- Modify: `tests/test_router.py`

- [ ] **Step 1: Write the failing tests**

First, add this import line to `tests/test_router.py` **at the top of the file, below the existing imports** (after `from backend.router.intent import ...`):

```python
from backend.router.escalation import call_tier2, log_escalation, should_escalate
```

Then append the following test functions at the bottom of `tests/test_router.py`:

```python
# ---------------------------------------------------------------------------
# should_escalate — pure function, no mocking needed
# ---------------------------------------------------------------------------

def test_should_escalate_on_high_complexity():
    r = Tier1Response(intent="general", complexity=0.8, escalate=False,
                      escalation_reason="", response="")
    assert should_escalate(r) is True


def test_should_escalate_on_escalate_flag():
    r = Tier1Response(intent="query", complexity=0.2, escalate=True,
                      escalation_reason="nuanced question", response="")
    assert should_escalate(r) is True


def test_should_not_escalate_on_low_complexity_no_flag():
    r = Tier1Response(intent="general", complexity=0.3, escalate=False,
                      escalation_reason="", response="Hello!")
    assert should_escalate(r) is False


def test_should_escalate_on_escalation_intent():
    # "synthesize" is not in the intent enum but may be returned by a model
    r = Tier1Response(intent="synthesize", complexity=0.5, escalate=False,
                      escalation_reason="", response="")
    assert should_escalate(r) is True


# ---------------------------------------------------------------------------
# log_escalation — mocks DB session
# ---------------------------------------------------------------------------

async def test_log_escalation_writes_to_db():
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()
    mock_session.commit = AsyncMock()

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.router.escalation.AsyncSessionLocal", return_value=mock_cm):
        await log_escalation("complex question", "complexity=0.80", "chat_001")

    mock_session.execute.assert_called_once()
    mock_session.commit.assert_called_once()


# ---------------------------------------------------------------------------
# call_tier2 — mocks Anthropic client
# ---------------------------------------------------------------------------

async def test_call_tier2_returns_response():
    tier1 = Tier1Response(
        intent="general", complexity=0.9, escalate=False,
        escalation_reason="", response="partial answer"
    )
    mock_content = MagicMock()
    mock_content.text = "Full detailed answer from Sonnet."

    mock_msg = MagicMock()
    mock_msg.content = [mock_content]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_msg)

    with patch("backend.router.escalation.AsyncAnthropic", return_value=mock_client):
        result = await call_tier2("What is the meaning of life?", tier1)

    assert result == "Full detailed answer from Sonnet."
    # Verify Tier 1's partial response was included as context
    call_args = mock_client.messages.create.call_args
    user_content = call_args.kwargs["messages"][0]["content"]
    assert "partial answer" in user_content
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_router.py -k "escalat or tier2" -v
```

Expected: `ImportError: cannot import name 'call_tier2' from 'backend.router.escalation'`

- [ ] **Step 3: Create `backend/router/escalation.py`**

```python
from anthropic import AsyncAnthropic
from sqlalchemy import text

from backend.config import settings
from backend.db import AsyncSessionLocal
from backend.router.intent import Tier1Response

# Intents that always trigger escalation (may be returned outside the standard enum)
ESCALATION_INTENTS = {"synthesize", "analyze", "compare"}


def should_escalate(result: Tier1Response) -> bool:
    return (
        result.complexity > 0.7
        or result.intent in ESCALATION_INTENTS
        or result.escalate
    )


async def call_tier2(message: str, tier1: Tier1Response) -> str:
    """Call claude-sonnet-4-6 with the original message and Tier 1's partial response as context."""
    context_block = (
        f"\n\n[Tier-1 analysis: {tier1.response}]" if tier1.response else ""
    )
    user_content = f"{message}{context_block}"

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": user_content}],
    )
    return response.content[0].text


async def log_escalation(message: str, reason: str, chat_id: str) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            text(
                "INSERT INTO escalations (message, reason, chat_id) "
                "VALUES (:message, :reason, :chat_id)"
            ),
            {"message": message, "reason": reason, "chat_id": chat_id},
        )
        await session.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_router.py -v
```

Expected: all tests PASS (4 from Task 2 + 6 new).

- [ ] **Step 5: Commit**

```bash
git add backend/router/escalation.py tests/test_router.py
git commit -m "feat: add escalation logic with Tier 2 call and DB logging"
```

---

## Task 4: POST /message Endpoint

**Files:**
- Create: `backend/router/api.py`
- Modify: `backend/main.py`
- Modify: `tests/test_router.py`

- [ ] **Step 1: Write the failing tests**

First, add this import line to `tests/test_router.py` **at the top of the file, below the existing imports**:

```python
from backend.router.api import MessageRequest, MessageResponse, message
```

Then append the following test functions at the bottom of `tests/test_router.py`:

```python
# ---------------------------------------------------------------------------
# POST /message — Tier 1 path (no escalation)
# ---------------------------------------------------------------------------

async def test_message_endpoint_uses_tier1_when_no_escalation():
    tier1_result = Tier1Response(
        intent="general",
        complexity=0.3,
        escalate=False,
        escalation_reason="",
        response="Hello from Tier 1",
    )
    req = MessageRequest(text="Hello", chat_id="chat_001")

    with patch("backend.router.api.call_tier1", AsyncMock(return_value=tier1_result)):
        result = await message(req)

    assert result.tier_used == 1
    assert result.response == "Hello from Tier 1"
    assert result.intent == "general"


# ---------------------------------------------------------------------------
# POST /message — Tier 2 path (escalation triggered)
# ---------------------------------------------------------------------------

async def test_message_endpoint_escalates_to_tier2():
    tier1_result = Tier1Response(
        intent="general",
        complexity=0.9,
        escalate=False,
        escalation_reason="",
        response="Partial from Tier 1",
    )
    req = MessageRequest(text="Analyze the nature of consciousness", chat_id="chat_002")

    mock_log = AsyncMock()
    with patch("backend.router.api.call_tier1", AsyncMock(return_value=tier1_result)), \
         patch("backend.router.api.call_tier2", AsyncMock(return_value="Deep Sonnet answer")), \
         patch("backend.router.api.log_escalation", mock_log):
        result = await message(req)

    assert result.tier_used == 2
    assert result.response == "Deep Sonnet answer"
    assert result.intent == "general"
    mock_log.assert_awaited_once()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_router.py -k "message_endpoint" -v
```

Expected: `ImportError: cannot import name 'message' from 'backend.router.api'`

- [ ] **Step 3: Create `backend/router/api.py`**

```python
from fastapi import APIRouter
from pydantic import BaseModel

from backend.router.escalation import call_tier2, log_escalation, should_escalate
from backend.router.intent import call_tier1

router = APIRouter()


class MessageRequest(BaseModel):
    text: str
    chat_id: str


class MessageResponse(BaseModel):
    response: str
    tier_used: int
    intent: str


@router.post("/message", response_model=MessageResponse)
async def message(req: MessageRequest) -> MessageResponse:
    tier1 = await call_tier1(req.text)

    if should_escalate(tier1):
        reason = tier1.escalation_reason or f"complexity={tier1.complexity:.2f}"
        await log_escalation(req.text, reason, req.chat_id)
        response_text = await call_tier2(req.text, tier1)
        return MessageResponse(response=response_text, tier_used=2, intent=tier1.intent)

    return MessageResponse(response=tier1.response, tier_used=1, intent=tier1.intent)
```

- [ ] **Step 4: Wire the message router into `backend/main.py`**

Full file after edit:

```python
from contextlib import asynccontextmanager

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from fastapi import FastAPI

from backend.db import engine
from backend.health import router as health_router
from backend.router.api import router as message_router


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
app.include_router(message_router)
```

- [ ] **Step 5: Run the full test suite**

```bash
pytest tests/ -v
```

Expected: all tests PASS. Count: 5 (models) + 2 (config) + 9 (health) + 12 (router) = 28 total.

If any test fails, fix it before committing.

- [ ] **Step 6: Commit**

```bash
git add backend/router/api.py backend/main.py tests/test_router.py
git commit -m "feat: add POST /message endpoint wired to two-tier LLM router"
```
