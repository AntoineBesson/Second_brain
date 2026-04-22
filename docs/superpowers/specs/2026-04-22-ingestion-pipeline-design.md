# Ingestion Pipeline Design

**Date:** 2026-04-22  
**Status:** Approved  
**Session:** 5

---

## Overview

Add a multi-source ingestion pipeline on top of the Session 4 RAG layer. Three source types are supported: PDF, URL, and YouTube. A shared `fetch_bytes` primitive handles all delivery methods (multipart upload, local path, HTTP URL). A `TaskRegistry` tracks background ingestion jobs kicked off by the WhatsApp webhook. The direct `/ingest` HTTP endpoint is synchronous; the WhatsApp path is async with user notification on completion.

---

## Module Layout

```
backend/
  ingestion/
    __init__.py
    fetch.py        # fetch_bytes(source, auth, headers) → bytes  [shared primitive]
    pdf.py          # ingest_pdf(source, filename) → int
    url.py          # ingest_url(url, min_chars) → int
    youtube.py      # ingest_youtube(url) → int
    registry.py     # TaskRegistry — create/update/get backed by in-memory dict
  router/
    ingest.py       # POST /ingest (sync) + GET /ingest/{id}/status
  interfaces/
    whatsapp.py     # updated — detect URL/media, BackgroundTask, reply immediately
  requirements.txt  # add: pymupdf, beautifulsoup4, lxml, youtube-transcript-api, yt-dlp

tests/
  test_ingestion_fetch.py
  test_ingestion_pdf.py
  test_ingestion_url.py
  test_ingestion_youtube.py
  test_ingest_router.py
```

`backend/router/api.py`: when `intent == store_knowledge` and message body contains a URL, route to `ingest_url` instead of storing raw text.  
`backend/main.py`: register the new ingest router.

---

## Components

### `fetch.py` — Shared bytes primitive

```python
async def fetch_bytes(
    source: UploadFile | str | Path,
    auth: tuple[str, str] | None = None,   # (user, password) — covers Twilio MediaUrl0
    headers: dict[str, str] | None = None,
) -> bytes
```

Dispatch:
- `UploadFile` → `await source.read()` (requires async)
- `Path` or non-HTTP `str` → `Path(source).read_bytes()`
- HTTP `str` → `httpx.get(url, auth=auth, headers=headers, ...)` (sync call in async context — acceptable for single-instance bot, consistent with `vector.py` pattern)

Shared httpx config (used by `fetch_bytes` and `url.py`):
- `timeout=30.0`, `follow_redirects=True`
- `User-Agent: SecondBrain-Bot/1.0`

Router-level callers that invoke blocking ingesters (pdf/url/youtube) wrap them with `asyncio.to_thread` to avoid blocking the event loop.

---

### `pdf.py` — `ingest_pdf(source, filename="document.pdf", auth=None) -> int`

- `fetch_bytes(source, auth=auth)` → raw bytes
- `fitz.open(stream=bytes, filetype="pdf")` → iterate pages → `page.get_text("text")`
- Join all pages with `\n\n` → `_chunk()` → `store_chunk()` per chunk
- Metadata: `source_type="pdf"`, `source_url=""`, `title=filename`, `date_added=utcnow`, `chunk_index=i`, `tags=[]`
- `fitz` not installed → `ImportError("pymupdf required: pip install pymupdf")`

---

### `url.py` — `ingest_url(url: str, min_chars: int = 500) -> int`

- `fetch_bytes(url)` → decode UTF-8 → BeautifulSoup
- Strip: `<nav>`, `<footer>`, `<header>`, `<script>`, `<style>`
- Content: `<main>` → `<article>` → `<body>` (first match)
- If `len(text) < min_chars`:
  - Try optional `playwright` import — render page, re-extract
  - If playwright not installed or still < `min_chars`: raise `ValueError("insufficient content extracted")`
- Title resolution order: `og:title` → `meta[name=title]` → `<title>` → URL
- Metadata: `source_type="url"`, `source_url=url`, `title=<resolved>`

---

### `youtube.py` — `ingest_youtube(url: str) -> int`

- Extract video ID via regex (handles `youtube.com/watch?v=`, `youtu.be/`, `youtube.com/shorts/`)
- `YouTubeTranscriptApi.get_transcript(video_id)` → list of `{text, start, duration}` dicts
- Transcript joining — produce clean chunk boundaries:
  - Within a sentence (segment text does **not** end with `.`, `?`, `!`): join with space
  - Between sentences: join with `\n`
- Title via `yt_dlp.YoutubeDL({"quiet": True}).extract_info(url, download=False)["title"]`
- No captions → `ValueError("no captions available for this video")`
- Metadata: `source_type="youtube"`, `source_url=url`, `title=video_title`

---

### `registry.py` — `TaskRegistry`

```python
@dataclass
class IngestStatus:
    status: Literal["pending", "complete", "error"]
    chunks_stored: int | None = None
    error_msg: str | None = None

class TaskRegistry:
    def create(self) -> str           # new UUID, status=pending
    def update(self, id, **kwargs)    # merge fields
    def get(self, id) -> IngestStatus | None
```

Single shared instance at module level: `registry = TaskRegistry()`. Both the ingest router and WhatsApp interface import this instance.

---

### `router/ingest.py`

**`POST /ingest`** — synchronous, accepts either:
- `multipart/form-data`: fields `type`, optional `file` (UploadFile), optional `url`, optional `path`
- `application/json`: `{"type": "pdf"|"url"|"youtube", "url": "...", "path": "..."}`

Routes to the appropriate ingester, returns:
```json
{"chunks_stored": 42, "source": "https://..."}
```

Errors: `422` for bad input, `500` for ingestion failure.

**`GET /ingest/{id}/status`** — looks up registry, returns 404 if unknown:
```json
{"status": "complete", "chunks_stored": 42, "error_msg": null}
```

---

### `interfaces/whatsapp.py` — updates

On incoming Twilio webhook:

1. Check `MediaUrl0` / `MediaContentType0` — if `application/pdf`: use `ingest_pdf` with Twilio Basic auth `(ACCOUNT_SID, AUTH_TOKEN)`
2. Else check message body for `https?://` — YouTube domains → `ingest_youtube`, else → `ingest_url`
3. If match: `task_id = registry.create()` → `BackgroundTasks.add_task(run_ingest, task_id, source, chat_id)` → return TwiML `"Got it, I'm processing that — I'll let you know when it's ready."`
4. `run_ingest` on success: `registry.update(task_id, status="complete", chunks_stored=n)` → `_send_whatsapp(chat_id, "Done — ingested {n} chunks from your PDF/URL/video.")`
5. `run_ingest` on failure: `registry.update(task_id, status="error", error_msg=str(e))` → `_send_whatsapp(chat_id, "Sorry, ingestion failed: {e}")`

Non-URL, non-media messages pass through to the existing `/message` flow unchanged.

---

## New Dependencies

| Package | Purpose | Optional |
|---|---|---|
| `pymupdf` | PDF text extraction (fitz) | No |
| `beautifulsoup4` | HTML parsing | No |
| `lxml` | Fast BS4 parser | No |
| `youtube-transcript-api` | YouTube captions | No |
| `yt-dlp` | YouTube video metadata (title) | No |
| `playwright` | JS-heavy page rendering | Yes — soft import |

---

## Error Handling

| Scenario | Behaviour |
|---|---|
| `fitz` not installed | `ImportError` with install hint |
| PDF fetch fails (bad URL, auth error) | `httpx.HTTPStatusError` bubbles up |
| URL text < `min_chars`, no playwright | `ValueError("insufficient content extracted")` |
| YouTube no captions | `ValueError("no captions available for this video")` |
| Embedding unavailable | `RuntimeError` from `store_chunk` bubbles up |
| WhatsApp background task fails | Registry set to `error`, user notified via WhatsApp |

---

## Testing Strategy

All external I/O mocked — no real network, no real Qdrant, no real Ollama.

| File | Coverage |
|---|---|
| `test_ingestion_fetch.py` | UploadFile, local path, HTTP URL, auth params forwarded |
| `test_ingestion_pdf.py` | fitz mock, metadata correctness, chunk_index sequence, ImportError |
| `test_ingestion_url.py` | og:title priority chain (4 cases), nav/footer stripped, min_chars threshold, ValueError |
| `test_ingestion_youtube.py` | sentence grouping logic, title via yt-dlp, NoTranscriptFound → ValueError |
| `test_ingest_router.py` | JSON body, multipart, status endpoint (200/404), WhatsApp BackgroundTask enqueue, run_ingest success/failure |
