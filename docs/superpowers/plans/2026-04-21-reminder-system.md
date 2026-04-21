# Reminder System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a complete reminder system — extraction, persistence, scheduling, and WhatsApp dispatch — on top of the existing two-tier LLM router.

**Architecture:** When `/message` receives `intent=store_reminder`, it calls a dedicated extraction function (second Tier 1 call) to parse `{reminder_text, datetime_str}`, resolves the datetime using per-chat timezone from `user_preferences`, saves to Postgres, and returns a confirmation. APScheduler polls every 60s and sends due reminders via raw httpx to the Twilio API. Incoming WhatsApp messages arrive at `POST /whatsapp`, validate the Twilio signature, and call the `message()` handler directly.

**Tech Stack:** FastAPI, SQLAlchemy async ORM, APScheduler 3.x (`AsyncIOScheduler`), dateparser, httpx (Twilio send), twilio SDK (validator only), Alembic migrations, pytest + AsyncMock.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `backend/requirements.txt` | Modify | Add apscheduler, dateparser, twilio |
| `backend/memory/postgres.py` | Modify | Add `UserPreference` ORM model |
| `backend/migrations/versions/b2c3d4e5f6a7_add_user_preferences.py` | Create | Migration for `user_preferences` table |
| `backend/reminders/__init__.py` | Create | Package marker |
| `backend/reminders/crud.py` | Create | `create_reminder`, `get_due_reminders`, `mark_sent`, `get_or_create_user_prefs` |
| `backend/reminders/extraction.py` | Create | Second Tier 1 call + dateparser parse |
| `backend/reminders/service.py` | Create | `extract_and_save` — orchestrates extraction + crud |
| `backend/router/api.py` | Modify | Branch on `store_reminder` before `should_escalate` |
| `backend/scheduler/__init__.py` | Create | Package marker |
| `backend/scheduler/reminders.py` | Create | `dispatch_due_reminders` job + `create_scheduler` |
| `backend/interfaces/__init__.py` | Create | Package marker |
| `backend/interfaces/whatsapp.py` | Create | `POST /whatsapp` webhook + TwiML reply |
| `backend/main.py` | Modify | Start/stop scheduler, include whatsapp router |
| `tests/test_reminders_crud.py` | Create | CRUD unit tests |
| `tests/test_extraction.py` | Create | Extraction + parse_datetime tests |
| `tests/test_service.py` | Create | Service unit tests |
| `tests/test_router.py` | Modify | Add store_reminder intent tests |
| `tests/test_scheduler.py` | Create | Scheduler dispatch tests |
| `tests/test_whatsapp.py` | Create | Webhook signature + TwiML tests |
| `README.md` | Modify | Smoke test setup steps |

---

## Task 1: Add dependencies

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Add the three new packages to requirements.txt**

Replace the file content with:
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
anthropic>=0.40.0
apscheduler==3.10.4
dateparser==1.2.0
twilio==9.3.5
```

- [ ] **Step 2: Install**

```bash
pip install -r backend/requirements.txt
```

Expected: packages install without conflicts.

- [ ] **Step 3: Commit**

```bash
git add backend/requirements.txt
git commit -m "chore: add apscheduler, dateparser, twilio dependencies"
```

---

## Task 2: UserPreference ORM model

**Files:**
- Modify: `backend/memory/postgres.py`

- [ ] **Step 1: Write a failing test**

Add to `tests/test_models.py`:
```python
def test_user_preference_model_has_expected_columns():
    from backend.memory.postgres import UserPreference
    cols = {c.name for c in UserPreference.__table__.columns}
    assert cols == {"chat_id", "timezone"}

def test_user_preference_default_timezone():
    from backend.memory.postgres import UserPreference
    col = UserPreference.__table__.c["timezone"]
    assert "Europe/Paris" in str(col.server_default.arg)
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/test_models.py -v -k "user_preference"
```

Expected: `ImportError` or `AttributeError` — `UserPreference` does not exist yet.

- [ ] **Step 3: Add the model to postgres.py**

Append to `backend/memory/postgres.py`:
```python
class UserPreference(Base):
    __tablename__ = "user_preferences"

    chat_id = Column(Text, primary_key=True)
    timezone = Column(Text, nullable=False, server_default=sql_text("'Europe/Paris'"))
```

- [ ] **Step 4: Run to verify it passes**

```bash
pytest tests/test_models.py -v -k "user_preference"
```

Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/memory/postgres.py tests/test_models.py
git commit -m "feat: add UserPreference ORM model"
```

---

## Task 3: Alembic migration for user_preferences

**Files:**
- Create: `backend/migrations/versions/b2c3d4e5f6a7_add_user_preferences.py`

- [ ] **Step 1: Create the migration file**

Create `backend/migrations/versions/b2c3d4e5f6a7_add_user_preferences.py`:
```python
"""add user_preferences table

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-21 00:00:01.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_preferences",
        sa.Column("chat_id", sa.Text(), nullable=False),
        sa.Column(
            "timezone",
            sa.Text(),
            nullable=False,
            server_default="Europe/Paris",
        ),
        sa.PrimaryKeyConstraint("chat_id"),
    )


def downgrade() -> None:
    op.drop_table("user_preferences")
```

- [ ] **Step 2: Verify Alembic sees the migration (requires running Postgres)**

```bash
alembic history
```

Expected: two revisions listed — `a1b2c3d4e5f6` and `b2c3d4e5f6a7`.

If Postgres is not running, skip this step and verify at smoke-test time.

- [ ] **Step 3: Commit**

```bash
git add backend/migrations/versions/b2c3d4e5f6a7_add_user_preferences.py
git commit -m "feat: add user_preferences migration"
```

---

## Task 4: CRUD layer

**Files:**
- Create: `backend/reminders/__init__.py`
- Create: `backend/reminders/crud.py`
- Create: `tests/test_reminders_crud.py`

- [ ] **Step 1: Create package marker**

Create `backend/reminders/__init__.py` (empty file).

- [ ] **Step 2: Write the failing tests**

Create `tests/test_reminders_crud.py`:
```python
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.reminders.crud import (
    create_reminder,
    get_due_reminders,
    get_or_create_user_prefs,
    mark_sent,
)
from backend.memory.postgres import Reminder, UserPreference


# --------------------------------------------------------------------------
# create_reminder
# --------------------------------------------------------------------------

async def test_create_reminder_adds_and_returns():
    mock_session = AsyncMock()
    mock_session.add = MagicMock()

    trigger_at = datetime(2026, 4, 22, 10, 0, tzinfo=timezone.utc)
    result = await create_reminder(mock_session, "Call Marc", trigger_at, "+33612345678")

    mock_session.add.assert_called_once()
    added = mock_session.add.call_args.args[0]
    assert isinstance(added, Reminder)
    assert added.text == "Call Marc"
    assert added.trigger_at == trigger_at
    assert added.chat_id == "+33612345678"
    mock_session.flush.assert_awaited_once()
    mock_session.refresh.assert_awaited_once_with(added)
    assert result is added


# --------------------------------------------------------------------------
# get_due_reminders
# --------------------------------------------------------------------------

async def test_get_due_reminders_returns_list():
    r1, r2 = MagicMock(spec=Reminder), MagicMock(spec=Reminder)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [r1, r2]

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    result = await get_due_reminders(mock_session)

    assert result == [r1, r2]
    mock_session.execute.assert_awaited_once()


async def test_get_due_reminders_returns_empty_list():
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    result = await get_due_reminders(mock_session)

    assert result == []


# --------------------------------------------------------------------------
# mark_sent
# --------------------------------------------------------------------------

async def test_mark_sent_executes_update():
    mock_session = AsyncMock()
    rid = uuid.uuid4()

    await mark_sent(mock_session, rid)

    mock_session.execute.assert_awaited_once()


# --------------------------------------------------------------------------
# get_or_create_user_prefs
# --------------------------------------------------------------------------

async def test_get_or_create_user_prefs_returns_preference():
    mock_pref = MagicMock(spec=UserPreference)
    mock_pref.timezone = "Europe/Paris"

    insert_result = MagicMock()
    select_result = MagicMock()
    select_result.scalar_one.return_value = mock_pref

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=[insert_result, select_result])

    result = await get_or_create_user_prefs(mock_session, "+33612345678")

    assert result is mock_pref
    assert mock_session.execute.await_count == 2
```

- [ ] **Step 3: Run to verify they fail**

```bash
pytest tests/test_reminders_crud.py -v
```

Expected: `ModuleNotFoundError: No module named 'backend.reminders.crud'`

- [ ] **Step 4: Implement crud.py**

Create `backend/reminders/crud.py`:
```python
from datetime import datetime

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.memory.postgres import Reminder, UserPreference


async def create_reminder(
    session: AsyncSession,
    text_: str,
    trigger_at: datetime,
    chat_id: str,
) -> Reminder:
    reminder = Reminder(text=text_, trigger_at=trigger_at, chat_id=chat_id)
    session.add(reminder)
    await session.flush()
    await session.refresh(reminder)
    return reminder


async def get_due_reminders(session: AsyncSession) -> list[Reminder]:
    result = await session.execute(
        select(Reminder).where(
            Reminder.trigger_at <= func.now(),
            Reminder.sent == False,  # noqa: E712
        )
    )
    return list(result.scalars().all())


async def mark_sent(session: AsyncSession, reminder_id) -> None:
    await session.execute(
        update(Reminder).where(Reminder.id == reminder_id).values(sent=True)
    )


async def get_or_create_user_prefs(
    session: AsyncSession, chat_id: str
) -> UserPreference:
    await session.execute(
        text(
            "INSERT INTO user_preferences (chat_id) "
            "VALUES (:chat_id) ON CONFLICT DO NOTHING"
        ),
        {"chat_id": chat_id},
    )
    result = await session.execute(
        select(UserPreference).where(UserPreference.chat_id == chat_id)
    )
    return result.scalar_one()
```

- [ ] **Step 5: Run to verify they pass**

```bash
pytest tests/test_reminders_crud.py -v
```

Expected: 6 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/reminders/__init__.py backend/reminders/crud.py tests/test_reminders_crud.py
git commit -m "feat: add reminder CRUD layer"
```

---

## Task 5: Extraction module

**Files:**
- Create: `backend/reminders/extraction.py`
- Create: `tests/test_extraction.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_extraction.py`:
```python
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.reminders.extraction import _parse_extraction, call_tier1_extract, parse_datetime


# --------------------------------------------------------------------------
# _parse_extraction — pure function
# --------------------------------------------------------------------------

def test_parse_extraction_happy_path():
    content = json.dumps({"reminder_text": "Call Marc", "datetime_str": "tomorrow at 10"})
    result = _parse_extraction(content)
    assert result == {"reminder_text": "Call Marc", "datetime_str": "tomorrow at 10"}


def test_parse_extraction_raises_on_bad_json():
    with pytest.raises(ValueError, match="Failed to parse extraction response"):
        _parse_extraction("not json {{")


def test_parse_extraction_raises_on_missing_field():
    with pytest.raises(ValueError, match="Failed to parse extraction response"):
        _parse_extraction(json.dumps({"reminder_text": "Call Marc"}))


# --------------------------------------------------------------------------
# parse_datetime
# --------------------------------------------------------------------------

def test_parse_datetime_returns_timezone_aware_datetime():
    dt = parse_datetime("2026-04-22 10:00", "Europe/Paris")
    assert dt.tzinfo is not None
    assert dt.year == 2026
    assert dt.month == 4
    assert dt.day == 22


def test_parse_datetime_raises_on_unparseable():
    with pytest.raises(ValueError, match="Could not parse datetime"):
        parse_datetime("xyzzy blorp snarf", "Europe/Paris")


# --------------------------------------------------------------------------
# call_tier1_extract — Ollama path
# --------------------------------------------------------------------------

async def test_call_tier1_extract_ollama_happy_path():
    payload = {"reminder_text": "Call Marc", "datetime_str": "tomorrow at 10"}
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

    with patch("backend.reminders.extraction.httpx.AsyncClient", return_value=mock_cm):
        result = await call_tier1_extract("Remind me to call Marc tomorrow at 10")

    assert result == {"reminder_text": "Call Marc", "datetime_str": "tomorrow at 10"}


# --------------------------------------------------------------------------
# call_tier1_extract — Haiku fallback
# --------------------------------------------------------------------------

async def test_call_tier1_extract_falls_back_to_haiku_on_ollama_error():
    payload = {"reminder_text": "Call Marc", "datetime_str": "tomorrow at 10"}
    mock_content = MagicMock()
    mock_content.text = json.dumps(payload)
    mock_msg = MagicMock()
    mock_msg.content = [mock_content]
    mock_anthropic_client = AsyncMock()
    mock_anthropic_client.messages.create = AsyncMock(return_value=mock_msg)

    mock_http_client = AsyncMock()
    mock_http_client.post = AsyncMock(side_effect=httpx.ConnectError("ollama down"))
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.reminders.extraction.httpx.AsyncClient", return_value=mock_cm), \
         patch("backend.reminders.extraction.AsyncAnthropic", return_value=mock_anthropic_client):
        result = await call_tier1_extract("Remind me to call Marc tomorrow at 10")

    assert result["reminder_text"] == "Call Marc"
    assert result["datetime_str"] == "tomorrow at 10"
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_extraction.py -v
```

Expected: `ModuleNotFoundError: No module named 'backend.reminders.extraction'`

- [ ] **Step 3: Implement extraction.py**

Create `backend/reminders/extraction.py`:
```python
import json
from datetime import datetime

import dateparser
import httpx
from anthropic import AsyncAnthropic

from backend.config import settings

HAIKU_MODEL = "claude-haiku-4-5-20251001"

EXTRACTION_SYSTEM_PROMPT = (
    "You are a reminder extraction assistant. "
    "Given a user message, extract the reminder text and the time expression. "
    "Respond with ONLY a raw JSON object — no markdown, no code fences, no explanation.\n\n"
    "{\n"
    '  "reminder_text": <the thing to be reminded about, e.g. "Call Marc">,\n'
    '  "datetime_str": <the time expression exactly as the user said it, e.g. "tomorrow at 10">\n'
    "}\n"
)


async def call_tier1_extract(text: str) -> dict:
    """Call Ollama for extraction. Falls back to Haiku on connection error."""
    try:
        return await _extract_ollama(text)
    except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError):
        return await _extract_haiku(text)


async def _extract_ollama(text: str) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            f"{settings.ollama_url}/api/chat",
            json={
                "model": "gemma3:4b",
                "messages": [
                    {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                "stream": False,
                "format": "json",
            },
        )
        r.raise_for_status()
    return _parse_extraction(r.json()["message"]["content"])


async def _extract_haiku(text: str) -> dict:
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model=HAIKU_MODEL,
        max_tokens=256,
        system=EXTRACTION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": text}],
    )
    return _parse_extraction(response.content[0].text)


def _parse_extraction(content: str) -> dict:
    try:
        data = json.loads(content)
        if "reminder_text" not in data or "datetime_str" not in data:
            raise KeyError("missing required fields")
        return {
            "reminder_text": str(data["reminder_text"]),
            "datetime_str": str(data["datetime_str"]),
        }
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError(
            f"Failed to parse extraction response: {exc!r}. Raw: {content!r}"
        ) from exc


def parse_datetime(datetime_str: str, timezone: str) -> datetime:
    dt = dateparser.parse(
        datetime_str,
        settings={
            "TIMEZONE": timezone,
            "RETURN_AS_TIMEZONE_AWARE": True,
            "PREFER_DATES_FROM": "future",
        },
    )
    if dt is None:
        raise ValueError(f"Could not parse datetime: {datetime_str!r}")
    return dt
```

- [ ] **Step 4: Run to verify they pass**

```bash
pytest tests/test_extraction.py -v
```

Expected: 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/reminders/extraction.py tests/test_extraction.py
git commit -m "feat: add reminder extraction module"
```

---

## Task 6: Service module

**Files:**
- Create: `backend/reminders/service.py`
- Create: `tests/test_service.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_service.py`:
```python
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.reminders.service import extract_and_save


async def test_extract_and_save_happy_path():
    trigger_at = datetime(2026, 4, 22, 10, 0, tzinfo=timezone.utc)
    mock_reminder = MagicMock()
    mock_reminder.text = "Call Marc"
    mock_reminder.trigger_at = trigger_at

    mock_pref = MagicMock()
    mock_pref.timezone = "Europe/Paris"

    mock_session = AsyncMock()
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.reminders.service.AsyncSessionLocal", return_value=mock_cm), \
         patch("backend.reminders.service.get_or_create_user_prefs", AsyncMock(return_value=mock_pref)), \
         patch("backend.reminders.service.call_tier1_extract", AsyncMock(return_value={"reminder_text": "Call Marc", "datetime_str": "tomorrow at 10"})), \
         patch("backend.reminders.service.parse_datetime", return_value=trigger_at), \
         patch("backend.reminders.service.create_reminder", AsyncMock(return_value=mock_reminder)):
        result = await extract_and_save("Remind me to call Marc tomorrow at 10", "+33612345678")

    assert result is mock_reminder
    mock_session.commit.assert_awaited_once()


async def test_extract_and_save_propagates_value_error_from_extraction():
    mock_pref = MagicMock()
    mock_pref.timezone = "Europe/Paris"
    mock_session = AsyncMock()
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.reminders.service.AsyncSessionLocal", return_value=mock_cm), \
         patch("backend.reminders.service.get_or_create_user_prefs", AsyncMock(return_value=mock_pref)), \
         patch("backend.reminders.service.call_tier1_extract", AsyncMock(side_effect=ValueError("bad json"))):
        with pytest.raises(ValueError, match="bad json"):
            await extract_and_save("nonsense", "+33612345678")


async def test_extract_and_save_propagates_value_error_from_parse_datetime():
    mock_pref = MagicMock()
    mock_pref.timezone = "Europe/Paris"
    mock_session = AsyncMock()
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.reminders.service.AsyncSessionLocal", return_value=mock_cm), \
         patch("backend.reminders.service.get_or_create_user_prefs", AsyncMock(return_value=mock_pref)), \
         patch("backend.reminders.service.call_tier1_extract", AsyncMock(return_value={"reminder_text": "Call Marc", "datetime_str": "xyzzy"})), \
         patch("backend.reminders.service.parse_datetime", side_effect=ValueError("Could not parse datetime")):
        with pytest.raises(ValueError, match="Could not parse datetime"):
            await extract_and_save("Remind me to call Marc xyzzy", "+33612345678")
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_service.py -v
```

Expected: `ModuleNotFoundError: No module named 'backend.reminders.service'`

- [ ] **Step 3: Implement service.py**

Create `backend/reminders/service.py`:
```python
from backend.db import AsyncSessionLocal
from backend.memory.postgres import Reminder
from backend.reminders.crud import create_reminder, get_or_create_user_prefs
from backend.reminders.extraction import call_tier1_extract, parse_datetime


async def extract_and_save(text: str, chat_id: str) -> Reminder:
    """Extract reminder details from text and persist to DB.

    Raises ValueError if extraction or datetime parsing fails.
    """
    async with AsyncSessionLocal() as session:
        prefs = await get_or_create_user_prefs(session, chat_id)
        extracted = await call_tier1_extract(text)
        trigger_at = parse_datetime(extracted["datetime_str"], prefs.timezone)
        reminder = await create_reminder(session, extracted["reminder_text"], trigger_at, chat_id)
        await session.commit()
        return reminder
```

- [ ] **Step 4: Run to verify they pass**

```bash
pytest tests/test_service.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/reminders/service.py tests/test_service.py
git commit -m "feat: add reminder service (extract_and_save)"
```

---

## Task 7: Router — store_reminder branch

**Files:**
- Modify: `backend/router/api.py`
- Modify: `tests/test_router.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_router.py`:
```python
# ---------------------------------------------------------------------------
# POST /message — store_reminder intent
# ---------------------------------------------------------------------------

async def test_message_endpoint_creates_reminder_on_store_reminder_intent():
    from datetime import datetime, timezone
    tier1_result = Tier1Response(
        intent="store_reminder",
        complexity=0.3,
        escalate=False,
        escalation_reason="",
        response="",
    )
    mock_reminder = MagicMock()
    mock_reminder.text = "Call Marc"
    mock_reminder.trigger_at = datetime(2026, 4, 22, 10, 0, tzinfo=timezone.utc)
    req = MessageRequest(text="Remind me to call Marc tomorrow at 10", chat_id="+33612345678")

    with patch("backend.router.api.call_tier1", AsyncMock(return_value=tier1_result)), \
         patch("backend.router.api.extract_and_save", AsyncMock(return_value=mock_reminder)):
        result = await message(req)

    assert result.tier_used == 1
    assert result.intent == "store_reminder"
    assert "Call Marc" in result.response
    assert "April" in result.response


async def test_message_endpoint_returns_friendly_error_on_extraction_failure():
    tier1_result = Tier1Response(
        intent="store_reminder",
        complexity=0.3,
        escalate=False,
        escalation_reason="",
        response="",
    )
    req = MessageRequest(text="Remind me blah", chat_id="+33612345678")

    with patch("backend.router.api.call_tier1", AsyncMock(return_value=tier1_result)), \
         patch("backend.router.api.extract_and_save", AsyncMock(side_effect=ValueError("bad parse"))):
        result = await message(req)

    assert result.tier_used == 1
    assert result.intent == "store_reminder"
    assert "couldn't understand" in result.response


async def test_message_endpoint_does_not_escalate_store_reminder():
    """store_reminder must never call Tier 2."""
    tier1_result = Tier1Response(
        intent="store_reminder",
        complexity=0.95,  # would normally trigger escalation
        escalate=True,
        escalation_reason="",
        response="",
    )
    mock_reminder = MagicMock()
    mock_reminder.text = "Call Marc"
    from datetime import datetime, timezone
    mock_reminder.trigger_at = datetime(2026, 4, 22, 10, 0, tzinfo=timezone.utc)
    req = MessageRequest(text="Remind me to call Marc tomorrow at 10", chat_id="+33612345678")

    with patch("backend.router.api.call_tier1", AsyncMock(return_value=tier1_result)), \
         patch("backend.router.api.extract_and_save", AsyncMock(return_value=mock_reminder)), \
         patch("backend.router.api.call_tier2", AsyncMock()) as mock_t2:
        result = await message(req)

    mock_t2.assert_not_awaited()
    assert result.intent == "store_reminder"
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_router.py -v -k "store_reminder"
```

Expected: 3 tests FAIL — `extract_and_save` not imported, branch not present.

- [ ] **Step 3: Update router/api.py**

Replace the full content of `backend/router/api.py`:
```python
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

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

- [ ] **Step 4: Run the full test suite to verify nothing regressed**

```bash
pytest tests/ -v
```

Expected: all previously passing tests still PASS, new 3 store_reminder tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/router/api.py tests/test_router.py
git commit -m "feat: handle store_reminder intent in /message endpoint"
```

---

## Task 8: Scheduler

**Files:**
- Create: `backend/scheduler/__init__.py`
- Create: `backend/scheduler/reminders.py`
- Create: `tests/test_scheduler.py`

- [ ] **Step 1: Create package marker**

Create `backend/scheduler/__init__.py` (empty file).

- [ ] **Step 2: Write the failing tests**

Create `tests/test_scheduler.py`:
```python
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.scheduler.reminders import dispatch_due_reminders


async def test_dispatch_sends_message_and_marks_sent():
    mock_reminder = MagicMock()
    mock_reminder.id = "some-uuid"
    mock_reminder.text = "Call Marc"
    mock_reminder.chat_id = "+33612345678"

    mock_session = AsyncMock()
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.scheduler.reminders.AsyncSessionLocal", return_value=mock_cm), \
         patch("backend.scheduler.reminders.get_due_reminders", AsyncMock(return_value=[mock_reminder])), \
         patch("backend.scheduler.reminders.mark_sent", AsyncMock()) as mock_mark_sent, \
         patch("backend.scheduler.reminders._send_whatsapp", AsyncMock()) as mock_send:
        await dispatch_due_reminders()

    mock_send.assert_awaited_once_with("Call Marc", "+33612345678")
    mock_mark_sent.assert_awaited_once_with(mock_session, "some-uuid")
    mock_session.commit.assert_awaited_once()


async def test_dispatch_skips_mark_sent_on_twilio_failure():
    mock_reminder = MagicMock()
    mock_reminder.id = "some-uuid"
    mock_reminder.text = "Call Marc"
    mock_reminder.chat_id = "+33612345678"

    mock_session = AsyncMock()
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.scheduler.reminders.AsyncSessionLocal", return_value=mock_cm), \
         patch("backend.scheduler.reminders.get_due_reminders", AsyncMock(return_value=[mock_reminder])), \
         patch("backend.scheduler.reminders.mark_sent", AsyncMock()) as mock_mark_sent, \
         patch("backend.scheduler.reminders._send_whatsapp", AsyncMock(side_effect=Exception("Twilio 500"))):
        await dispatch_due_reminders()

    mock_mark_sent.assert_not_awaited()
    mock_session.commit.assert_not_awaited()


async def test_dispatch_continues_after_one_failure():
    """A Twilio failure on reminder 1 must not block reminder 2."""
    r1, r2 = MagicMock(), MagicMock()
    r1.id, r1.text, r1.chat_id = "id-1", "Call Marc", "+33612345678"
    r2.id, r2.text, r2.chat_id = "id-2", "Buy milk", "+33612345678"

    mock_session = AsyncMock()
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    send_calls = []

    async def fake_send(text, chat_id):
        send_calls.append(text)
        if text == "Call Marc":
            raise Exception("Twilio error")

    with patch("backend.scheduler.reminders.AsyncSessionLocal", return_value=mock_cm), \
         patch("backend.scheduler.reminders.get_due_reminders", AsyncMock(return_value=[r1, r2])), \
         patch("backend.scheduler.reminders.mark_sent", AsyncMock()) as mock_mark_sent, \
         patch("backend.scheduler.reminders._send_whatsapp", side_effect=fake_send):
        await dispatch_due_reminders()

    assert send_calls == ["Call Marc", "Buy milk"]
    mock_mark_sent.assert_awaited_once_with(mock_session, "id-2")
```

- [ ] **Step 3: Run to verify they fail**

```bash
pytest tests/test_scheduler.py -v
```

Expected: `ModuleNotFoundError: No module named 'backend.scheduler.reminders'`

- [ ] **Step 4: Implement scheduler/reminders.py**

Create `backend/scheduler/reminders.py`:
```python
import logging

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from backend.config import settings
from backend.db import AsyncSessionLocal
from backend.reminders.crud import get_due_reminders, mark_sent

logger = logging.getLogger(__name__)


async def dispatch_due_reminders() -> None:
    async with AsyncSessionLocal() as session:
        reminders = await get_due_reminders(session)
        for reminder in reminders:
            try:
                await _send_whatsapp(reminder.text, reminder.chat_id)
                await mark_sent(session, reminder.id)
                await session.commit()
            except Exception as exc:
                logger.warning("Failed to dispatch reminder %s: %s", reminder.id, exc)


async def _send_whatsapp(text: str, chat_id: str) -> None:
    url = (
        f"https://api.twilio.com/2010-04-01/Accounts"
        f"/{settings.twilio_account_sid}/Messages.json"
    )
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(
            url,
            data={
                "Body": text,
                "From": settings.twilio_whatsapp_from,
                "To": f"whatsapp:{chat_id}",
            },
            auth=(settings.twilio_account_sid, settings.twilio_auth_token),
        )
        r.raise_for_status()


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(dispatch_due_reminders, "interval", seconds=60)
    return scheduler
```

- [ ] **Step 5: Run to verify they pass**

```bash
pytest tests/test_scheduler.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/scheduler/__init__.py backend/scheduler/reminders.py tests/test_scheduler.py
git commit -m "feat: add APScheduler reminder dispatcher"
```

---

## Task 9: WhatsApp webhook

**Files:**
- Create: `backend/interfaces/__init__.py`
- Create: `backend/interfaces/whatsapp.py`
- Create: `tests/test_whatsapp.py`

- [ ] **Step 1: Create package marker**

Create `backend/interfaces/__init__.py` (empty file).

- [ ] **Step 2: Write the failing tests**

Create `tests/test_whatsapp.py`:
```python
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.interfaces.whatsapp import router

app_test = FastAPI()
app_test.include_router(router)


async def test_whatsapp_webhook_valid_signature_returns_twiml():
    with patch("backend.interfaces.whatsapp.RequestValidator") as MockValidator, \
         patch("backend.interfaces.whatsapp.handle_message", new_callable=AsyncMock) as mock_handle:
        MockValidator.return_value.validate.return_value = True
        mock_handle.return_value = MagicMock(
            response="I'll remind you to Call Marc on April 22 at 10:00.",
            tier_used=1,
            intent="store_reminder",
        )

        async with AsyncClient(
            transport=ASGITransport(app=app_test), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/whatsapp",
                data={"Body": "Remind me to call Marc tomorrow at 10", "From": "whatsapp:+33612345678"},
                headers={"X-Twilio-Signature": "valid-sig"},
            )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/xml")
    assert "<Response>" in response.text
    assert "<Message>" in response.text
    assert "Call Marc" in response.text


async def test_whatsapp_webhook_invalid_signature_returns_403():
    with patch("backend.interfaces.whatsapp.RequestValidator") as MockValidator:
        MockValidator.return_value.validate.return_value = False

        async with AsyncClient(
            transport=ASGITransport(app=app_test), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/whatsapp",
                data={"Body": "Hi", "From": "whatsapp:+33612345678"},
                headers={"X-Twilio-Signature": "bad-sig"},
            )

    assert response.status_code == 403


async def test_whatsapp_webhook_strips_whatsapp_prefix_from_chat_id():
    with patch("backend.interfaces.whatsapp.RequestValidator") as MockValidator, \
         patch("backend.interfaces.whatsapp.handle_message", new_callable=AsyncMock) as mock_handle:
        MockValidator.return_value.validate.return_value = True
        mock_handle.return_value = MagicMock(response="OK", tier_used=1, intent="general")

        async with AsyncClient(
            transport=ASGITransport(app=app_test), base_url="http://test"
        ) as ac:
            await ac.post(
                "/whatsapp",
                data={"Body": "Hello", "From": "whatsapp:+33612345678"},
                headers={"X-Twilio-Signature": "valid-sig"},
            )

    call_args = mock_handle.call_args.args[0]
    assert call_args.chat_id == "+33612345678"
    assert call_args.text == "Hello"
```

- [ ] **Step 3: Run to verify they fail**

```bash
pytest tests/test_whatsapp.py -v
```

Expected: `ModuleNotFoundError: No module named 'backend.interfaces.whatsapp'`

- [ ] **Step 4: Implement interfaces/whatsapp.py**

Create `backend/interfaces/whatsapp.py`:
```python
import logging

from fastapi import APIRouter, Form, Header, HTTPException, Request
from fastapi.responses import Response
from twilio.request_validator import RequestValidator

from backend.config import settings
from backend.router.api import MessageRequest
from backend.router.api import message as handle_message

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/whatsapp")
async def whatsapp_webhook(
    request: Request,
    Body: str = Form(...),
    From: str = Form(...),
    x_twilio_signature: str = Header(...),
) -> Response:
    validator = RequestValidator(settings.twilio_auth_token)
    params = dict(await request.form())
    if not validator.validate(str(request.url), params, x_twilio_signature):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    chat_id = From.removeprefix("whatsapp:")
    result = await handle_message(MessageRequest(text=Body, chat_id=chat_id))

    twiml = f"<Response><Message>{result.response}</Message></Response>"
    return Response(content=twiml, media_type="text/xml")
```

- [ ] **Step 5: Run to verify they pass**

```bash
pytest tests/test_whatsapp.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/interfaces/__init__.py backend/interfaces/whatsapp.py tests/test_whatsapp.py
git commit -m "feat: add WhatsApp webhook with Twilio signature validation"
```

---

## Task 10: Wire scheduler and webhook into main.py

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Update main.py**

Replace the full content of `backend/main.py`:
```python
from contextlib import asynccontextmanager

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from fastapi import FastAPI

from backend.db import engine
from backend.health import router as health_router
from backend.interfaces.whatsapp import router as whatsapp_router
from backend.router.api import router as message_router
from backend.scheduler.reminders import create_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = AlembicConfig("alembic.ini")
    alembic_command.upgrade(cfg, "head")
    scheduler = create_scheduler()
    scheduler.start()
    yield
    scheduler.shutdown()
    await engine.dispose()


app = FastAPI(title="Second Brain", lifespan=lifespan)
app.include_router(health_router)
app.include_router(message_router)
app.include_router(whatsapp_router)
```

- [ ] **Step 2: Run the full test suite**

```bash
pytest tests/ -v
```

Expected: all tests PASS (count should be 35 existing + new tests from this session).

- [ ] **Step 3: Commit**

```bash
git add backend/main.py
git commit -m "feat: wire scheduler and WhatsApp webhook into app lifespan"
```

---

## Task 11: README — smoke test documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add smoke test section to README.md**

Append to `README.md`:
````markdown
## Reminder System — Smoke Test (Twilio Sandbox)

### Prerequisites

1. A Twilio account with the WhatsApp Sandbox enabled.
2. `ngrok` (or equivalent) to expose your local server.
3. Docker running (`docker-compose up -d`).

### Setup

1. Start the server:
   ```bash
   uvicorn backend.main:app --reload
   ```

2. Expose it publicly:
   ```bash
   ngrok http 8000
   ```
   Copy the HTTPS URL (e.g. `https://abc123.ngrok.io`).

3. In the Twilio console → Messaging → Try it out → Send a WhatsApp message,
   set the **"When a message comes in"** webhook to:
   ```
   https://abc123.ngrok.io/whatsapp
   ```
   Method: `HTTP POST`.

4. Join the sandbox from your WhatsApp by sending the sandbox join code
   to the Twilio sandbox number.

### Test

Send this message from WhatsApp to the sandbox number:
```
Remind me to call Marc in 2 minutes
```

Expected immediate reply:
```
Got it — I'll remind you to call Marc on April 21 at HH:MM.
```

Wait 2 minutes. You should receive:
```
call Marc
```

Verify in Postgres:
```sql
SELECT text, trigger_at, sent FROM reminders ORDER BY trigger_at DESC LIMIT 5;
```

The row for "call Marc" should show `sent = true`.
````

- [ ] **Step 2: Run the full test suite one final time**

```bash
pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add WhatsApp reminder smoke test instructions"
```
