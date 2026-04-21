# Reminder System Design

**Date:** 2026-04-21  
**Status:** Approved

---

## Overview

Build a complete reminder system on top of the existing two-tier LLM router. When a user sends a WhatsApp message classified as `store_reminder`, the system extracts the reminder text and datetime, persists them, and dispatches a WhatsApp message via Twilio when the trigger time arrives.

---

## Architecture

### File Layout

```
backend/
  reminders/
    __init__.py
    crud.py          # create_reminder, get_due_reminders, mark_sent, get_or_create_user_prefs
    service.py       # extract_and_save(text, chat_id) — orchestrates extraction + crud
    extraction.py    # call_tier1_extract(text) → {reminder_text, datetime_str}
  scheduler/
    reminders.py     # AsyncIOScheduler, 60s job, Twilio send via httpx
  interfaces/
    whatsapp.py      # POST /whatsapp webhook handler + TwiML reply
```

### Data Flow

1. User sends WhatsApp message → Twilio posts form-encoded body to `POST /whatsapp`
2. Webhook validates Twilio signature (403 on failure), extracts `Body` and `From`
3. Calls the `message()` router function directly (in-process, no HTTP round-trip)
4. Tier 1 classifies intent as `store_reminder`
5. `router/api.py` calls `extract_and_save(text, chat_id)` (module-level function in `backend/reminders/service.py`)
6. Service looks up `user_preferences` for timezone, calls extraction LLM, saves reminder to DB
7. Router returns a confirmation string (e.g. "Got it — I'll remind you to Call Marc on April 22 at 10:00")
8. Webhook wraps the response in TwiML `<Response><Message>…</Message></Response>` and returns it
9. APScheduler polls every 60s → finds due reminders → sends via Twilio → marks `sent=true`

---

## Schema Changes

### New table: `user_preferences`

```sql
CREATE TABLE user_preferences (
    chat_id  TEXT PRIMARY KEY,
    timezone TEXT NOT NULL DEFAULT 'Europe/Paris'
);
```

- ORM model `UserPreference` added to `backend/memory/postgres.py`
- New Alembic migration (second revision, depends on `a1b2c3d4e5f6`)

No changes to the existing `reminders` table (`id`, `text`, `trigger_at`, `sent`, `chat_id`).

---

## Components

### 1. CRUD layer (`backend/reminders/crud.py`)

All functions accept an `AsyncSession` parameter (sessions are never created inside CRUD — matching the existing `log_escalation` pattern).

| Function | Operation |
|---|---|
| `create_reminder(session, text, trigger_at, chat_id)` | `INSERT INTO reminders` → returns `Reminder` |
| `get_due_reminders(session)` | `SELECT WHERE trigger_at <= now() AND sent = false` → `list[Reminder]` |
| `mark_sent(session, reminder_id)` | `UPDATE SET sent = true WHERE id = :id` |
| `get_or_create_user_prefs(session, chat_id)` | `INSERT … ON CONFLICT DO NOTHING` then `SELECT` → `UserPreference` |

### 2. Extraction (`backend/reminders/extraction.py`)

Second Tier 1 call (Ollama/Haiku fallback) with a focused system prompt.

**Input:** raw message text (e.g. `"Remind me to call Marc tomorrow at 10"`)

**Output JSON from LLM:**
```json
{"reminder_text": "Call Marc", "datetime_str": "tomorrow at 10"}
```

**Datetime parsing:**
```python
dateparser.parse(
    datetime_str,
    settings={
        "TIMEZONE": user_prefs.timezone,
        "RETURN_AS_TIMEZONE_AWARE": True,
        "PREFER_DATES_FROM": "future",
    }
)
```

**Error handling:**
- Unparseable LLM JSON → `ValueError` → `/message` returns `"I couldn't understand when to set that reminder"`
- `dateparser.parse` returns `None` → same user-facing error message
- Both are non-fatal to the rest of the system

### 3. Service (`backend/reminders/service.py`)

`extract_and_save(text: str, chat_id: str) -> Reminder`

1. Open `AsyncSessionLocal`
2. `get_or_create_user_prefs(session, chat_id)` → get timezone
3. `call_tier1_extract(text)` → `{reminder_text, datetime_str}`
4. `dateparser.parse(datetime_str, settings={...})` → `trigger_at`
5. `create_reminder(session, reminder_text, trigger_at, chat_id)`
6. `session.commit()` → return saved `Reminder`

On extraction/parse error: propagate `ValueError` to caller.

### 4. Router changes (`backend/router/api.py`)

The router branches on intent *before* calling `should_escalate`. When `tier1.intent == "store_reminder"`, skip escalation entirely:
```python
if tier1.intent == "store_reminder":
    try:
        reminder = await extract_and_save(req.text, req.chat_id)
        # %-d is Linux/Docker-only (zero-stripped day). Fine for production container.
        response_text = f"Got it — I'll remind you to {reminder.text} on {reminder.trigger_at:%B %-d at %H:%M}."
    except ValueError:
        response_text = "I couldn't understand when to set that reminder."
    return MessageResponse(response=response_text, tier_used=1, intent=tier1.intent)

# existing should_escalate / call_tier2 logic follows unchanged
```

Tier 2 is never called for `store_reminder` — this is a structured side-effect intent, not a reasoning task.

### 5. Scheduler (`backend/scheduler/reminders.py`)

`AsyncIOScheduler` started in the FastAPI lifespan.

**Job: `dispatch_due_reminders()`** (interval: 60s):
1. Open `AsyncSessionLocal`
2. `get_due_reminders(session)` → list of due reminders
3. For each reminder:
   - Send WhatsApp via Twilio (raw httpx POST, no SDK)
   - On success: `mark_sent(session, reminder.id)` + `session.commit()`
   - On Twilio failure: log warning, skip `mark_sent` (retries on next tick)

**Twilio send (raw httpx):**
```
POST https://api.twilio.com/2010-04-01/Accounts/{SID}/Messages.json
  data={"Body": text, "From": TWILIO_WHATSAPP_FROM, "To": f"whatsapp:{chat_id}"}
  auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
```

**Lifespan wiring in `main.py`:**
```python
scheduler = AsyncIOScheduler()
scheduler.add_job(dispatch_due_reminders, "interval", seconds=60)
scheduler.start()
yield
scheduler.shutdown()
await engine.dispose()
```

### 6. WhatsApp webhook (`backend/interfaces/whatsapp.py`)

`POST /whatsapp` — form-encoded body from Twilio.

1. Validate `X-Twilio-Signature` using `twilio.request_validator.RequestValidator` → 403 on failure
2. Parse `Body` (message text) and `From` (e.g. `whatsapp:+33612345678`)
3. Strip `whatsapp:` prefix → `chat_id = "+33612345678"`
4. Call `message(MessageRequest(text=body, chat_id=chat_id))` directly
5. Return TwiML: `<Response><Message>{response_text}</Message></Response>` with `Content-Type: text/xml`

---

## Dependencies (additions to `requirements.txt`)

```
apscheduler==3.10.4
dateparser==1.2.0
twilio==9.3.5
```

The `twilio` package is used only for `RequestValidator` (webhook signature verification). All outbound Twilio HTTP calls use raw `httpx`, consistent with the project's no-SDK-for-API-calls convention.

---

## Testing

All tests follow the existing pattern: `unittest.mock` with `AsyncMock`, no real DB or Twilio calls.

| File | Coverage |
|---|---|
| `tests/test_reminders_crud.py` | Mock session, verify SQL params and return values for all 4 CRUD functions |
| `tests/test_extraction.py` | Mock Tier 1 call, verify dateparser output; test bad JSON and unparseable date error paths |
| `tests/test_scheduler.py` | Mock `get_due_reminders` + httpx Twilio call; verify `mark_sent` called on success, skipped on Twilio failure |
| `tests/test_whatsapp.py` | Mock `RequestValidator` + `message()`; verify TwiML reply shape; verify 403 on bad signature |

### Manual smoke test (Twilio sandbox)

1. Configure Twilio sandbox to point to your `POST /whatsapp` endpoint (ngrok or similar)
2. Send "Remind me to call Marc in 2 minutes" from WhatsApp sandbox number
3. Verify confirmation reply arrives immediately
4. Wait 2 minutes; verify reminder WhatsApp message fires
5. Verify `sent=true` in Postgres for that row

Setup steps documented in `README.md`.
