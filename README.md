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
