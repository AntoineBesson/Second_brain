# Ingestion Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add PDF, URL, and YouTube ingestion to the Second Brain RAG layer, with a synchronous `/ingest` HTTP endpoint and an async WhatsApp path that returns immediately and notifies when done.

**Architecture:** Three source ingesters (pdf/url/youtube) share a `fetch_bytes` async primitive and call the existing `_chunk` + `store_chunk` from `backend/memory/vector.py`. A `TaskRegistry` class (in-memory, class-backed) tracks background jobs. The WhatsApp webhook detects media attachments and URL patterns, queues a `BackgroundTask`, and replies immediately. The direct `POST /ingest` endpoint is synchronous and blocks until done.

**Tech Stack:** PyMuPDF (fitz), BeautifulSoup4/lxml, youtube-transcript-api, yt-dlp, playwright (optional), FastAPI BackgroundTasks, httpx (sync, consistent with vector.py).

---

## File Map

**New files:**
- `backend/ingestion/__init__.py` — empty package marker
- `backend/ingestion/registry.py` — `IngestStatus` dataclass + `TaskRegistry` class + shared `registry` instance
- `backend/ingestion/fetch.py` — `fetch_bytes(source, auth, headers) -> bytes` async shared primitive
- `backend/ingestion/pdf.py` — `ingest_pdf(source, filename, auth) -> int`
- `backend/ingestion/url.py` — `ingest_url(url, min_chars) -> int` + helper functions
- `backend/ingestion/youtube.py` — `ingest_youtube(url) -> int` + `_join_transcript` + `_extract_video_id`
- `backend/router/ingest.py` — `POST /ingest` + `GET /ingest/{id}/status` + `run_ingest` background task
- `tests/test_ingestion_fetch.py`
- `tests/test_ingestion_pdf.py`
- `tests/test_ingestion_url.py`
- `tests/test_ingestion_youtube.py`
- `tests/test_ingest_router.py`

**Modified files:**
- `backend/requirements.txt` — 5 new deps
- `backend/main.py` — register ingest router
- `backend/router/api.py` — URL auto-detection in `store_knowledge` branch
- `backend/interfaces/whatsapp.py` — media/URL detection + BackgroundTasks

---

## Task 1: Add dependencies

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Add the five new packages**

Append to `backend/requirements.txt`:

```
pymupdf>=1.24.0
beautifulsoup4>=4.12.0
lxml>=5.0.0
youtube-transcript-api>=0.6.0
yt-dlp>=2024.1.0
```

- [ ] **Step 2: Commit**

```bash
git add backend/requirements.txt
git commit -m "chore: add ingestion pipeline dependencies"
```

---

## Task 2: TaskRegistry

**Files:**
- Create: `backend/ingestion/__init__.py`
- Create: `backend/ingestion/registry.py`
- Create: `tests/test_ingestion_registry.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ingestion_registry.py`:

```python
from backend.ingestion.registry import IngestStatus, TaskRegistry


def test_create_returns_uuid_and_sets_pending():
    reg = TaskRegistry()
    task_id = reg.create()
    assert len(task_id) == 36  # UUID string
    status = reg.get(task_id)
    assert status is not None
    assert status.status == "pending"
    assert status.chunks_stored is None
    assert status.error_msg is None


def test_update_changes_status_fields():
    reg = TaskRegistry()
    task_id = reg.create()
    reg.update(task_id, status="complete", chunks_stored=42)
    status = reg.get(task_id)
    assert status.status == "complete"
    assert status.chunks_stored == 42
    assert status.error_msg is None


def test_update_with_error():
    reg = TaskRegistry()
    task_id = reg.create()
    reg.update(task_id, status="error", error_msg="embedding failed")
    status = reg.get(task_id)
    assert status.status == "error"
    assert status.error_msg == "embedding failed"


def test_get_returns_none_for_unknown_id():
    reg = TaskRegistry()
    assert reg.get("nonexistent-id") is None


def test_update_unknown_id_does_not_raise():
    reg = TaskRegistry()
    reg.update("nonexistent-id", status="complete")  # should not raise


def test_multiple_tasks_are_independent():
    reg = TaskRegistry()
    id1 = reg.create()
    id2 = reg.create()
    reg.update(id1, status="complete", chunks_stored=10)
    assert reg.get(id2).status == "pending"
    assert reg.get(id1).chunks_stored == 10


def test_module_level_registry_is_task_registry_instance():
    from backend.ingestion.registry import registry
    assert isinstance(registry, TaskRegistry)
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_ingestion_registry.py -v
```

Expected: `ModuleNotFoundError: No module named 'backend.ingestion'`

- [ ] **Step 3: Create `backend/ingestion/__init__.py`**

```python
```

(Empty file.)

- [ ] **Step 4: Create `backend/ingestion/registry.py`**

```python
import uuid
from dataclasses import dataclass
from typing import Literal


@dataclass
class IngestStatus:
    status: Literal["pending", "complete", "error"]
    chunks_stored: int | None = None
    error_msg: str | None = None


class TaskRegistry:
    def __init__(self) -> None:
        self._tasks: dict[str, IngestStatus] = {}

    def create(self) -> str:
        task_id = str(uuid.uuid4())
        self._tasks[task_id] = IngestStatus(status="pending")
        return task_id

    def update(self, task_id: str, **kwargs) -> None:
        if task_id not in self._tasks:
            return
        status = self._tasks[task_id]
        for key, value in kwargs.items():
            setattr(status, key, value)

    def get(self, task_id: str) -> IngestStatus | None:
        return self._tasks.get(task_id)


registry = TaskRegistry()
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_ingestion_registry.py -v
```

Expected: 7 tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/ingestion/__init__.py backend/ingestion/registry.py tests/test_ingestion_registry.py
git commit -m "feat: add TaskRegistry for ingestion job tracking"
```

---

## Task 3: `fetch_bytes`

**Files:**
- Create: `backend/ingestion/fetch.py`
- Create: `tests/test_ingestion_fetch.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ingestion_fetch.py`:

```python
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.ingestion.fetch import fetch_bytes


async def test_fetch_bytes_upload_file():
    mock_upload = AsyncMock()
    mock_upload.read = AsyncMock(return_value=b"pdf content")
    result = await fetch_bytes(mock_upload)
    assert result == b"pdf content"


async def test_fetch_bytes_local_path_string(tmp_path):
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"local bytes")
    result = await fetch_bytes(str(f))
    assert result == b"local bytes"


async def test_fetch_bytes_local_path_object(tmp_path):
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"path bytes")
    result = await fetch_bytes(f)
    assert result == b"path bytes"


async def test_fetch_bytes_http_url():
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.content = b"remote content"

    with patch("backend.ingestion.fetch.httpx.get", return_value=mock_response) as mock_get:
        result = await fetch_bytes("https://example.com/doc.pdf")

    assert result == b"remote content"
    mock_get.assert_called_once()
    assert mock_get.call_args.args[0] == "https://example.com/doc.pdf"


async def test_fetch_bytes_http_url_with_auth():
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.content = b"auth content"

    with patch("backend.ingestion.fetch.httpx.get", return_value=mock_response) as mock_get:
        result = await fetch_bytes("https://api.twilio.com/media.pdf", auth=("ACXXX", "secret"))

    assert result == b"auth content"
    assert mock_get.call_args.kwargs["auth"] == ("ACXXX", "secret")


async def test_fetch_bytes_http_url_merges_default_user_agent():
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.content = b"bytes"

    with patch("backend.ingestion.fetch.httpx.get", return_value=mock_response) as mock_get:
        await fetch_bytes("https://example.com/page")

    sent_headers = mock_get.call_args.kwargs["headers"]
    assert "User-Agent" in sent_headers
    assert "SecondBrain" in sent_headers["User-Agent"]


async def test_fetch_bytes_http_url_caller_headers_override_default():
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.content = b"bytes"

    with patch("backend.ingestion.fetch.httpx.get", return_value=mock_response) as mock_get:
        await fetch_bytes("https://example.com/page", headers={"X-Custom": "value"})

    sent_headers = mock_get.call_args.kwargs["headers"]
    assert sent_headers["X-Custom"] == "value"
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_ingestion_fetch.py -v
```

Expected: `ModuleNotFoundError: No module named 'backend.ingestion.fetch'`

- [ ] **Step 3: Create `backend/ingestion/fetch.py`**

```python
from pathlib import Path

import httpx
from fastapi import UploadFile

_DEFAULT_HEADERS = {"User-Agent": "SecondBrain-Bot/1.0"}
_TIMEOUT = 30.0


async def fetch_bytes(
    source: UploadFile | str | Path,
    auth: tuple[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> bytes:
    """Return raw bytes from an UploadFile, local path, or HTTP URL.

    auth is forwarded as HTTP Basic auth — used for Twilio MediaUrl0 which
    requires (ACCOUNT_SID, AUTH_TOKEN).
    """
    merged_headers = {**_DEFAULT_HEADERS, **(headers or {})}

    if isinstance(source, UploadFile):
        return await source.read()

    if isinstance(source, Path) or (
        isinstance(source, str) and not source.startswith("http")
    ):
        return Path(source).read_bytes()

    # HTTP URL
    r = httpx.get(
        source,
        auth=auth,
        headers=merged_headers,
        timeout=_TIMEOUT,
        follow_redirects=True,
    )
    r.raise_for_status()
    return r.content
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_ingestion_fetch.py -v
```

Expected: 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/ingestion/fetch.py tests/test_ingestion_fetch.py
git commit -m "feat: add fetch_bytes shared bytes primitive"
```

---

## Task 4: `ingest_pdf`

**Files:**
- Create: `backend/ingestion/pdf.py`
- Create: `tests/test_ingestion_pdf.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ingestion_pdf.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.ingestion.pdf import ingest_pdf


async def test_ingest_pdf_returns_chunk_count():
    mock_page = MagicMock()
    mock_page.get_text = MagicMock(return_value="Hello world. This is a test page.")

    mock_doc = MagicMock()
    mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))
    mock_doc.close = MagicMock()

    mock_fitz = MagicMock()
    mock_fitz.open = MagicMock(return_value=mock_doc)

    with patch("backend.ingestion.pdf.fetch_bytes", AsyncMock(return_value=b"pdf")), \
         patch("backend.ingestion.pdf.fitz", mock_fitz), \
         patch("backend.ingestion.pdf.store_chunk", return_value="uuid") as mock_store:
        result = await ingest_pdf(b"pdf", filename="test.pdf")

    assert result == 1
    assert mock_store.call_count == 1


async def test_ingest_pdf_sets_correct_metadata():
    mock_page = MagicMock()
    mock_page.get_text = MagicMock(return_value="Some text from the page.")

    mock_doc = MagicMock()
    mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))
    mock_doc.close = MagicMock()

    mock_fitz = MagicMock()
    mock_fitz.open = MagicMock(return_value=mock_doc)

    with patch("backend.ingestion.pdf.fetch_bytes", AsyncMock(return_value=b"pdf")), \
         patch("backend.ingestion.pdf.fitz", mock_fitz), \
         patch("backend.ingestion.pdf.store_chunk", return_value="uuid") as mock_store:
        await ingest_pdf(b"pdf", filename="report.pdf")

    meta = mock_store.call_args.args[1]
    assert meta["source_type"] == "pdf"
    assert meta["title"] == "report.pdf"
    assert meta["source_url"] == ""
    assert meta["chunk_index"] == 0
    assert meta["tags"] == []
    assert "date_added" in meta


async def test_ingest_pdf_chunk_indices_increment():
    # 600 words → 2 chunks (size=512, overlap=50)
    words = " ".join(["word"] * 600)
    mock_page = MagicMock()
    mock_page.get_text = MagicMock(return_value=words)

    mock_doc = MagicMock()
    mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))
    mock_doc.close = MagicMock()

    mock_fitz = MagicMock()
    mock_fitz.open = MagicMock(return_value=mock_doc)

    with patch("backend.ingestion.pdf.fetch_bytes", AsyncMock(return_value=b"pdf")), \
         patch("backend.ingestion.pdf.fitz", mock_fitz), \
         patch("backend.ingestion.pdf.store_chunk", return_value="uuid") as mock_store:
        result = await ingest_pdf(b"pdf", filename="big.pdf")

    indices = [call.args[1]["chunk_index"] for call in mock_store.call_args_list]
    assert indices == list(range(result))
    assert result == 2


async def test_ingest_pdf_passes_auth_to_fetch_bytes():
    mock_page = MagicMock()
    mock_page.get_text = MagicMock(return_value="text")

    mock_doc = MagicMock()
    mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))
    mock_doc.close = MagicMock()

    mock_fitz = MagicMock()
    mock_fitz.open = MagicMock(return_value=mock_doc)

    mock_fetch = AsyncMock(return_value=b"pdf")
    with patch("backend.ingestion.pdf.fetch_bytes", mock_fetch), \
         patch("backend.ingestion.pdf.fitz", mock_fitz), \
         patch("backend.ingestion.pdf.store_chunk", return_value="uuid"):
        await ingest_pdf("https://example.com/doc.pdf", auth=("sid", "token"))

    assert mock_fetch.call_args.kwargs["auth"] == ("sid", "token")


async def test_ingest_pdf_raises_import_error_when_fitz_missing():
    with patch("backend.ingestion.pdf.fitz", None):
        with pytest.raises(ImportError, match="pymupdf required"):
            await ingest_pdf(b"pdf", filename="test.pdf")


async def test_ingest_pdf_joins_pages_with_double_newline():
    page1 = MagicMock()
    page1.get_text = MagicMock(return_value="First page.")
    page2 = MagicMock()
    page2.get_text = MagicMock(return_value="Second page.")

    mock_doc = MagicMock()
    mock_doc.__iter__ = MagicMock(return_value=iter([page1, page2]))
    mock_doc.close = MagicMock()

    mock_fitz = MagicMock()
    mock_fitz.open = MagicMock(return_value=mock_doc)

    stored_texts = []

    def capture_store(text, meta):
        stored_texts.append(text)
        return "uuid"

    with patch("backend.ingestion.pdf.fetch_bytes", AsyncMock(return_value=b"pdf")), \
         patch("backend.ingestion.pdf.fitz", mock_fitz), \
         patch("backend.ingestion.pdf.store_chunk", side_effect=capture_store):
        await ingest_pdf(b"pdf", filename="two_pages.pdf")

    assert "First page." in stored_texts[0]
    assert "Second page." in stored_texts[0]
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_ingestion_pdf.py -v
```

Expected: `ModuleNotFoundError: No module named 'backend.ingestion.pdf'`

- [ ] **Step 3: Create `backend/ingestion/pdf.py`**

```python
from datetime import datetime, timezone

from backend.ingestion.fetch import fetch_bytes
from backend.memory.vector import _chunk, store_chunk

try:
    import fitz
except ImportError:
    fitz = None  # type: ignore


async def ingest_pdf(
    source,
    filename: str = "document.pdf",
    auth: tuple[str, str] | None = None,
) -> int:
    """Extract text from a PDF and store chunks in Qdrant.

    source: UploadFile, local path str/Path, or HTTP URL str.
    Returns number of chunks stored.
    """
    if fitz is None:
        raise ImportError("pymupdf required: pip install pymupdf")

    raw = await fetch_bytes(source, auth=auth)
    doc = fitz.open(stream=raw, filetype="pdf")
    pages = [page.get_text("text") for page in doc]
    doc.close()

    full_text = "\n\n".join(pages)
    chunks = _chunk(full_text)
    now = datetime.now(timezone.utc).isoformat()

    for i, chunk in enumerate(chunks):
        store_chunk(chunk, {
            "source_type": "pdf",
            "source_url": "",
            "title": filename,
            "date_added": now,
            "chunk_index": i,
            "tags": [],
        })

    return len(chunks)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_ingestion_pdf.py -v
```

Expected: 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/ingestion/pdf.py tests/test_ingestion_pdf.py
git commit -m "feat: add PDF ingester"
```

---

## Task 5: `ingest_url`

**Files:**
- Create: `backend/ingestion/url.py`
- Create: `tests/test_ingestion_url.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ingestion_url.py`:

```python
from unittest.mock import MagicMock, patch

import pytest

from backend.ingestion.url import _extract_title, _extract_content, ingest_url


# --- Title extraction ---

def _soup(html: str):
    from bs4 import BeautifulSoup
    return BeautifulSoup(html, "lxml")


def test_extract_title_prefers_og_title():
    soup = _soup("""
        <html><head>
          <meta property="og:title" content="OG Title" />
          <meta name="title" content="Meta Title" />
          <title>HTML Title</title>
        </head></html>
    """)
    assert _extract_title(soup, "https://example.com") == "OG Title"


def test_extract_title_falls_back_to_meta_name_title():
    soup = _soup("""
        <html><head>
          <meta name="title" content="Meta Title" />
          <title>HTML Title</title>
        </head></html>
    """)
    assert _extract_title(soup, "https://example.com") == "Meta Title"


def test_extract_title_falls_back_to_title_tag():
    soup = _soup("""
        <html><head><title>HTML Title</title></head></html>
    """)
    assert _extract_title(soup, "https://example.com") == "HTML Title"


def test_extract_title_falls_back_to_url():
    soup = _soup("<html><head></head></html>")
    assert _extract_title(soup, "https://example.com/page") == "https://example.com/page"


# --- Content extraction ---

def test_extract_content_uses_main_tag():
    soup = _soup("""
        <html><body>
          <nav>Nav stuff</nav>
          <main>Main content here.</main>
          <footer>Footer</footer>
        </body></html>
    """)
    text = _extract_content(soup)
    assert "Main content here." in text
    assert "Nav stuff" not in text
    assert "Footer" not in text


def test_extract_content_falls_back_to_article():
    soup = _soup("""
        <html><body>
          <header>Header</header>
          <article>Article content.</article>
        </body></html>
    """)
    text = _extract_content(soup)
    assert "Article content." in text
    assert "Header" not in text


def test_extract_content_strips_script_and_style():
    soup = _soup("""
        <html><body>
          <main>Real text. <script>var x = 1;</script> <style>.a{}</style></main>
        </body></html>
    """)
    text = _extract_content(soup)
    assert "Real text." in text
    assert "var x" not in text
    assert ".a{}" not in text


# --- ingest_url ---

def _mock_httpx_response(html: str):
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.text = html
    return mock_resp


async def test_ingest_url_returns_chunk_count():
    words = " ".join(["word"] * 600)
    html = f"<html><head><title>Test</title></head><body><main>{words}</main></body></html>"

    with patch("backend.ingestion.url.httpx.get", return_value=_mock_httpx_response(html)), \
         patch("backend.ingestion.url.store_chunk", return_value="uuid") as mock_store:
        result = await ingest_url("https://example.com")

    assert result == mock_store.call_count
    assert result >= 1


async def test_ingest_url_sets_correct_metadata():
    html = """
        <html><head>
          <meta property="og:title" content="My Article" />
        </head><body><main>""" + " ".join(["word"] * 600) + """</main></body></html>
    """
    with patch("backend.ingestion.url.httpx.get", return_value=_mock_httpx_response(html)), \
         patch("backend.ingestion.url.store_chunk", return_value="uuid") as mock_store:
        await ingest_url("https://example.com/article")

    meta = mock_store.call_args_list[0].args[1]
    assert meta["source_type"] == "url"
    assert meta["source_url"] == "https://example.com/article"
    assert meta["title"] == "My Article"
    assert meta["chunk_index"] == 0


async def test_ingest_url_raises_when_content_too_short_and_no_playwright():
    html = "<html><body><main>Short.</main></body></html>"

    with patch("backend.ingestion.url.httpx.get", return_value=_mock_httpx_response(html)), \
         patch("backend.ingestion.url._playwright_extract", return_value=""):
        with pytest.raises(ValueError, match="insufficient content"):
            await ingest_url("https://example.com", min_chars=500)


async def test_ingest_url_uses_playwright_content_when_initial_too_short():
    short_html = "<html><body><main>Short.</main></body></html>"
    playwright_text = " ".join(["word"] * 600)  # enough content

    with patch("backend.ingestion.url.httpx.get", return_value=_mock_httpx_response(short_html)), \
         patch("backend.ingestion.url._playwright_extract", return_value=playwright_text), \
         patch("backend.ingestion.url.store_chunk", return_value="uuid") as mock_store:
        result = await ingest_url("https://example.com", min_chars=500)

    assert result >= 1
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_ingestion_url.py -v
```

Expected: `ModuleNotFoundError: No module named 'backend.ingestion.url'`

- [ ] **Step 3: Create `backend/ingestion/url.py`**

```python
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup

from backend.memory.vector import _chunk, store_chunk

_HEADERS = {"User-Agent": "SecondBrain-Bot/1.0"}
_TIMEOUT = 30.0
_STRIP_TAGS = ["nav", "footer", "header", "script", "style"]


def _extract_title(soup: BeautifulSoup, url: str) -> str:
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        return og["content"]
    meta = soup.find("meta", attrs={"name": "title"})
    if meta and meta.get("content"):
        return meta["content"]
    title_tag = soup.find("title")
    if title_tag and title_tag.string:
        return title_tag.string.strip()
    return url


def _extract_content(soup: BeautifulSoup) -> str:
    for tag in soup.find_all(_STRIP_TAGS):
        tag.decompose()
    for candidate in ["main", "article", "body"]:
        el = soup.find(candidate)
        if el:
            return el.get_text(separator=" ", strip=True)
    return ""


def _playwright_extract(url: str) -> str:
    """Try to render the page with Playwright and extract text.

    Returns empty string if playwright is not installed.
    Raises playwright errors if the browser fails mid-render.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return ""

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url, timeout=30000)
        html = page.content()
        browser.close()

    soup = BeautifulSoup(html, "lxml")
    return _extract_content(soup)


async def ingest_url(url: str, min_chars: int = 500) -> int:
    """Fetch a URL, extract main text, and store chunks in Qdrant.

    Returns number of chunks stored.
    Raises ValueError if insufficient text is extracted.
    """
    r = httpx.get(url, headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "lxml")
    title = _extract_title(soup, url)
    text = _extract_content(soup)

    if len(text) < min_chars:
        text = _playwright_extract(url)

    if len(text) < min_chars:
        raise ValueError("insufficient content extracted")

    chunks = _chunk(text)
    now = datetime.now(timezone.utc).isoformat()
    for i, chunk in enumerate(chunks):
        store_chunk(chunk, {
            "source_type": "url",
            "source_url": url,
            "title": title,
            "date_added": now,
            "chunk_index": i,
            "tags": [],
        })
    return len(chunks)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_ingestion_url.py -v
```

Expected: 11 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/ingestion/url.py tests/test_ingestion_url.py
git commit -m "feat: add URL ingester with og:title extraction and optional Playwright fallback"
```

---

## Task 6: `ingest_youtube`

**Files:**
- Create: `backend/ingestion/youtube.py`
- Create: `tests/test_ingestion_youtube.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ingestion_youtube.py`:

```python
from unittest.mock import MagicMock, patch

import pytest

from backend.ingestion.youtube import _extract_video_id, _join_transcript, ingest_youtube


# --- Video ID extraction ---

def test_extract_video_id_watch_url():
    assert _extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_extract_video_id_short_url():
    assert _extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_extract_video_id_shorts_url():
    assert _extract_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_extract_video_id_raises_on_invalid_url():
    with pytest.raises(ValueError, match="Could not extract"):
        _extract_video_id("https://example.com/not-youtube")


# --- Transcript joining ---

def test_join_transcript_spaces_within_sentence():
    segments = [
        {"text": "Hello"},
        {"text": "world."},
    ]
    result = _join_transcript(segments)
    assert result == "Hello world."


def test_join_transcript_newline_between_sentences():
    segments = [
        {"text": "First sentence."},
        {"text": "Second sentence."},
    ]
    result = _join_transcript(segments)
    assert result == "First sentence.\nSecond sentence."


def test_join_transcript_groups_mid_sentence_segments():
    segments = [
        {"text": "This is"},
        {"text": "a long"},
        {"text": "sentence."},
        {"text": "New sentence?"},
    ]
    result = _join_transcript(segments)
    assert result == "This is a long sentence.\nNew sentence?"


def test_join_transcript_handles_question_and_exclamation():
    segments = [
        {"text": "Is this right?"},
        {"text": "Yes!"},
        {"text": "Great."},
    ]
    result = _join_transcript(segments)
    assert result == "Is this right?\nYes!\nGreat."


def test_join_transcript_skips_empty_segments():
    segments = [
        {"text": "Hello."},
        {"text": ""},
        {"text": "World."},
    ]
    result = _join_transcript(segments)
    assert result == "Hello.\nWorld."


# --- ingest_youtube ---

async def test_ingest_youtube_returns_chunk_count():
    segments = [{"text": "word."} for _ in range(600)]
    mock_ydl = MagicMock()
    mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
    mock_ydl.__exit__ = MagicMock(return_value=False)
    mock_ydl.extract_info = MagicMock(return_value={"title": "My Video"})

    with patch("backend.ingestion.youtube.YouTubeTranscriptApi") as mock_api, \
         patch("backend.ingestion.youtube.YoutubeDL", return_value=mock_ydl), \
         patch("backend.ingestion.youtube.store_chunk", return_value="uuid") as mock_store:
        mock_api.get_transcript = MagicMock(return_value=segments)
        result = await ingest_youtube("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    assert result == mock_store.call_count
    assert result >= 1


async def test_ingest_youtube_sets_correct_metadata():
    segments = [{"text": "word."} for _ in range(600)]
    mock_ydl = MagicMock()
    mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
    mock_ydl.__exit__ = MagicMock(return_value=False)
    mock_ydl.extract_info = MagicMock(return_value={"title": "Test Video Title"})

    with patch("backend.ingestion.youtube.YouTubeTranscriptApi") as mock_api, \
         patch("backend.ingestion.youtube.YoutubeDL", return_value=mock_ydl), \
         patch("backend.ingestion.youtube.store_chunk", return_value="uuid") as mock_store:
        mock_api.get_transcript = MagicMock(return_value=segments)
        await ingest_youtube("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    meta = mock_store.call_args_list[0].args[1]
    assert meta["source_type"] == "youtube"
    assert meta["source_url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert meta["title"] == "Test Video Title"
    assert meta["chunk_index"] == 0


async def test_ingest_youtube_raises_on_no_captions():
    from youtube_transcript_api import NoTranscriptFound

    with patch("backend.ingestion.youtube.YouTubeTranscriptApi") as mock_api:
        mock_api.get_transcript = MagicMock(
            side_effect=NoTranscriptFound("dQw4w9WgXcQ", [], None)
        )
        with pytest.raises(ValueError, match="no captions available"):
            await ingest_youtube("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_ingestion_youtube.py -v
```

Expected: `ModuleNotFoundError: No module named 'backend.ingestion.youtube'`

- [ ] **Step 3: Create `backend/ingestion/youtube.py`**

```python
import re
from datetime import datetime, timezone

from youtube_transcript_api import (
    NoTranscriptFound,
    TranscriptsDisabled,
    YouTubeTranscriptApi,
)
from yt_dlp import YoutubeDL

from backend.memory.vector import _chunk, store_chunk

_YT_PATTERNS = [
    r"youtube\.com/watch\?v=([A-Za-z0-9_-]{11})",
    r"youtu\.be/([A-Za-z0-9_-]{11})",
    r"youtube\.com/shorts/([A-Za-z0-9_-]{11})",
]


def _extract_video_id(url: str) -> str:
    for pattern in _YT_PATTERNS:
        m = re.search(pattern, url)
        if m:
            return m.group(1)
    raise ValueError(f"Could not extract YouTube video ID from: {url}")


def _join_transcript(segments: list[dict]) -> str:
    """Join transcript segments into sentences.

    Segments not ending with .?! are joined with spaces.
    A newline is inserted between complete sentences.
    """
    lines: list[str] = []
    current: list[str] = []

    for seg in segments:
        text = seg["text"].strip()
        if not text:
            continue
        current.append(text)
        if text[-1] in ".?!":
            lines.append(" ".join(current))
            current = []

    if current:
        lines.append(" ".join(current))

    return "\n".join(lines)


async def ingest_youtube(url: str) -> int:
    """Fetch a YouTube transcript and store chunks in Qdrant.

    Returns number of chunks stored.
    Raises ValueError if no captions are available.
    """
    video_id = _extract_video_id(url)

    try:
        segments = YouTubeTranscriptApi.get_transcript(video_id)
    except (NoTranscriptFound, TranscriptsDisabled) as exc:
        raise ValueError("no captions available for this video") from exc

    with YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
        info = ydl.extract_info(url, download=False)
    title = info.get("title", url)

    text = _join_transcript(segments)
    chunks = _chunk(text)
    now = datetime.now(timezone.utc).isoformat()

    for i, chunk in enumerate(chunks):
        store_chunk(chunk, {
            "source_type": "youtube",
            "source_url": url,
            "title": title,
            "date_added": now,
            "chunk_index": i,
            "tags": [],
        })

    return len(chunks)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_ingestion_youtube.py -v
```

Expected: 12 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/ingestion/youtube.py tests/test_ingestion_youtube.py
git commit -m "feat: add YouTube ingester with sentence-grouped transcript"
```

---

## Task 7: `POST /ingest` endpoint

**Files:**
- Create: `backend/router/ingest.py`
- Create: `tests/test_ingest_router.py` (partial — sync endpoint tests only)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ingest_router.py`:

```python
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.router.ingest import router

app_test = FastAPI()
app_test.include_router(router)


async def test_post_ingest_json_url():
    with patch("backend.router.ingest.ingest_url", AsyncMock(return_value=12)):
        async with AsyncClient(transport=ASGITransport(app=app_test), base_url="http://test") as ac:
            resp = await ac.post(
                "/ingest",
                json={"type": "url", "url": "https://example.com"},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["chunks_stored"] == 12
    assert body["source"] == "https://example.com"


async def test_post_ingest_json_youtube():
    with patch("backend.router.ingest.ingest_youtube", AsyncMock(return_value=7)):
        async with AsyncClient(transport=ASGITransport(app=app_test), base_url="http://test") as ac:
            resp = await ac.post(
                "/ingest",
                json={"type": "youtube", "url": "https://youtu.be/dQw4w9WgXcQ"},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["chunks_stored"] == 7
    assert body["source"] == "https://youtu.be/dQw4w9WgXcQ"


async def test_post_ingest_json_pdf_url():
    with patch("backend.router.ingest.ingest_pdf", AsyncMock(return_value=5)):
        async with AsyncClient(transport=ASGITransport(app=app_test), base_url="http://test") as ac:
            resp = await ac.post(
                "/ingest",
                json={"type": "pdf", "url": "https://example.com/doc.pdf"},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["chunks_stored"] == 5
    assert body["source"] == "doc.pdf"


async def test_post_ingest_multipart_url():
    with patch("backend.router.ingest.ingest_url", AsyncMock(return_value=8)):
        async with AsyncClient(transport=ASGITransport(app=app_test), base_url="http://test") as ac:
            resp = await ac.post(
                "/ingest",
                data={"type": "url", "url": "https://example.com/article"},
            )
    assert resp.status_code == 200
    assert resp.json()["chunks_stored"] == 8


async def test_post_ingest_returns_500_on_ingestion_failure():
    with patch("backend.router.ingest.ingest_url", AsyncMock(side_effect=ValueError("insufficient content"))):
        async with AsyncClient(transport=ASGITransport(app=app_test), base_url="http://test") as ac:
            resp = await ac.post(
                "/ingest",
                json={"type": "url", "url": "https://example.com"},
            )
    assert resp.status_code == 500


async def test_post_ingest_returns_422_on_unknown_type():
    async with AsyncClient(transport=ASGITransport(app=app_test), base_url="http://test") as ac:
        resp = await ac.post(
            "/ingest",
            json={"type": "docx", "url": "https://example.com"},
        )
    assert resp.status_code == 422


async def test_post_ingest_returns_422_when_url_missing_for_url_type():
    async with AsyncClient(transport=ASGITransport(app=app_test), base_url="http://test") as ac:
        resp = await ac.post(
            "/ingest",
            json={"type": "url"},
        )
    assert resp.status_code == 422
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_ingest_router.py -v
```

Expected: `ModuleNotFoundError: No module named 'backend.router.ingest'`

- [ ] **Step 3: Create `backend/router/ingest.py`**

```python
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from backend.ingestion.pdf import ingest_pdf
from backend.ingestion.registry import IngestStatus, registry
from backend.ingestion.url import ingest_url
from backend.ingestion.youtube import ingest_youtube
from backend.scheduler.reminders import _send_whatsapp

logger = logging.getLogger(__name__)
router = APIRouter()


async def run_ingest(
    task_id: str,
    source_type: str,
    source: str,
    chat_id: str,
    auth: tuple[str, str] | None = None,
) -> None:
    """Background task: run ingestion and notify the user via WhatsApp when done."""
    try:
        if source_type == "pdf":
            filename = source.split("/")[-1].split("?")[0] or "document.pdf"
            n = await ingest_pdf(source, filename=filename, auth=auth)
            label = "PDF"
        elif source_type == "url":
            n = await ingest_url(source)
            label = "URL"
        elif source_type == "youtube":
            n = await ingest_youtube(source)
            label = "video"
        else:
            raise ValueError(f"Unknown source type: {source_type}")

        registry.update(task_id, status="complete", chunks_stored=n)
        await _send_whatsapp(f"Done — ingested {n} chunks from your {label}.", chat_id)
    except Exception as exc:
        logger.error("Ingestion failed for task %s: %s", task_id, exc)
        registry.update(task_id, status="error", error_msg=str(exc))
        await _send_whatsapp(f"Sorry, ingestion failed: {exc}", chat_id)


@router.post("/ingest")
async def ingest(request: Request) -> dict:
    """Synchronous ingestion endpoint. Accepts JSON or multipart/form-data.

    JSON body: {"type": "pdf"|"url"|"youtube", "url": "...", "path": "..."}
    Form data: type=pdf, file=<UploadFile>, url=..., path=...
    Returns: {"chunks_stored": N, "source": "..."}
    """
    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" in content_type:
        form = await request.form()
        ingest_type = form.get("type")
        url = form.get("url")
        path = form.get("path")
        upload = form.get("file")
    else:
        body = await request.json()
        ingest_type = body.get("type")
        url = body.get("url")
        path = body.get("path")
        upload = None

    try:
        if ingest_type == "pdf":
            source = upload or url or path
            if not source:
                raise HTTPException(status_code=422, detail="PDF requires file, url, or path")
            if upload:
                filename = getattr(upload, "filename", None) or "document.pdf"
            elif url:
                filename = url.split("/")[-1].split("?")[0] or "document.pdf"
            else:
                filename = Path(path).name if path else "document.pdf"
            n = await ingest_pdf(source, filename=filename)
            return {"chunks_stored": n, "source": filename}

        elif ingest_type == "url":
            if not url:
                raise HTTPException(status_code=422, detail="URL ingestion requires 'url'")
            n = await ingest_url(url)
            return {"chunks_stored": n, "source": url}

        elif ingest_type == "youtube":
            if not url:
                raise HTTPException(status_code=422, detail="YouTube ingestion requires 'url'")
            n = await ingest_youtube(url)
            return {"chunks_stored": n, "source": url}

        else:
            raise HTTPException(status_code=422, detail=f"Unknown ingestion type: {ingest_type!r}")

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/ingest/{task_id}/status")
async def ingest_status(task_id: str) -> dict:
    status = registry.get(task_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        "status": status.status,
        "chunks_stored": status.chunks_stored,
        "error_msg": status.error_msg,
    }
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_ingest_router.py -v
```

Expected: 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/router/ingest.py tests/test_ingest_router.py
git commit -m "feat: add POST /ingest synchronous endpoint and run_ingest background task"
```

---

## Task 8: `GET /ingest/{id}/status` tests + register router in `main.py`

**Files:**
- Modify: `tests/test_ingest_router.py` — add status endpoint tests
- Modify: `backend/main.py` — register ingest router

- [ ] **Step 1: Add `run_ingest` unit tests and status endpoint tests to `tests/test_ingest_router.py`**

Append these tests to the existing `tests/test_ingest_router.py`:

```python
# --- run_ingest background task ---

async def test_run_ingest_updates_registry_to_complete_on_success():
    from backend.ingestion.registry import registry
    task_id = registry.create()

    with patch("backend.router.ingest.ingest_url", AsyncMock(return_value=9)), \
         patch("backend.router.ingest._send_whatsapp", AsyncMock()) as mock_send:
        from backend.router.ingest import run_ingest
        await run_ingest(task_id, "url", "https://example.com", "+33612345678")

    status = registry.get(task_id)
    assert status.status == "complete"
    assert status.chunks_stored == 9
    mock_send.assert_awaited_once()
    assert "9" in mock_send.call_args.args[0]


async def test_run_ingest_updates_registry_to_error_on_failure():
    from backend.ingestion.registry import registry
    task_id = registry.create()

    with patch("backend.router.ingest.ingest_url", AsyncMock(side_effect=ValueError("insufficient content"))), \
         patch("backend.router.ingest._send_whatsapp", AsyncMock()) as mock_send:
        from backend.router.ingest import run_ingest
        await run_ingest(task_id, "url", "https://example.com", "+33612345678")

    status = registry.get(task_id)
    assert status.status == "error"
    assert "insufficient content" in status.error_msg
    mock_send.assert_awaited_once()
    assert "failed" in mock_send.call_args.args[0].lower()


async def test_run_ingest_pdf_passes_auth_to_ingester():
    from backend.ingestion.registry import registry
    task_id = registry.create()

    mock_ingest_pdf = AsyncMock(return_value=3)
    with patch("backend.router.ingest.ingest_pdf", mock_ingest_pdf), \
         patch("backend.router.ingest._send_whatsapp", AsyncMock()):
        from backend.router.ingest import run_ingest
        await run_ingest(task_id, "pdf", "https://api.twilio.com/media.pdf", "+33612345678",
                         auth=("ACXXX", "token"))

    assert mock_ingest_pdf.call_args.kwargs["auth"] == ("ACXXX", "token")


# --- Status endpoint ---

async def test_get_ingest_status_pending():
    from backend.ingestion.registry import registry
    task_id = registry.create()

    async with AsyncClient(transport=ASGITransport(app=app_test), base_url="http://test") as ac:
        resp = await ac.get(f"/ingest/{task_id}/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    assert body["chunks_stored"] is None
    assert body["error_msg"] is None


async def test_get_ingest_status_complete():
    from backend.ingestion.registry import registry
    task_id = registry.create()
    registry.update(task_id, status="complete", chunks_stored=42)

    async with AsyncClient(transport=ASGITransport(app=app_test), base_url="http://test") as ac:
        resp = await ac.get(f"/ingest/{task_id}/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "complete"
    assert body["chunks_stored"] == 42


async def test_get_ingest_status_error():
    from backend.ingestion.registry import registry
    task_id = registry.create()
    registry.update(task_id, status="error", error_msg="embedding failed")

    async with AsyncClient(transport=ASGITransport(app=app_test), base_url="http://test") as ac:
        resp = await ac.get(f"/ingest/{task_id}/status")

    body = resp.json()
    assert body["status"] == "error"
    assert body["error_msg"] == "embedding failed"


async def test_get_ingest_status_unknown_id_returns_404():
    async with AsyncClient(transport=ASGITransport(app=app_test), base_url="http://test") as ac:
        resp = await ac.get("/ingest/00000000-0000-0000-0000-000000000000/status")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run to verify they pass (endpoint already implemented)**

```bash
pytest tests/test_ingest_router.py -v
```

Expected: all 11 tests PASS

- [ ] **Step 3: Register ingest router in `backend/main.py`**

Current `backend/main.py`:
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
```

Add `from backend.router.ingest import router as ingest_router` after the existing imports and `app.include_router(ingest_router)` after the existing `include_router` calls:

```python
from contextlib import asynccontextmanager

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from fastapi import FastAPI

from backend.db import engine
from backend.health import router as health_router
from backend.interfaces.whatsapp import router as whatsapp_router
from backend.router.api import router as message_router
from backend.router.ingest import router as ingest_router
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
app.include_router(ingest_router)
```

- [ ] **Step 4: Run the full test suite**

```bash
pytest tests/ -v
```

Expected: all existing tests still pass + the 11 ingest router tests pass

- [ ] **Step 5: Commit**

```bash
git add tests/test_ingest_router.py backend/main.py
git commit -m "feat: register ingest router and add status endpoint tests"
```

---

## Task 9: URL auto-detection in `store_knowledge` (`api.py`)

**Files:**
- Modify: `backend/router/api.py`
- Modify: `tests/test_router.py` — add URL detection tests

- [ ] **Step 1: Write the failing tests**

Append these tests to `tests/test_router.py`:

```python
# ---------------------------------------------------------------------------
# store_knowledge — URL auto-detection
# ---------------------------------------------------------------------------

async def test_store_knowledge_routes_to_ingest_url_when_url_in_text():
    tier1_result = Tier1Response(
        intent="store_knowledge",
        complexity=0.2,
        escalate=False,
        escalation_reason="",
        response="",
    )
    req = MessageRequest(text="Save this https://example.com/article", chat_id="chat_001")

    with patch("backend.router.api.call_tier1", AsyncMock(return_value=tier1_result)), \
         patch("backend.router.api.ingest_url", AsyncMock(return_value=5)) as mock_ingest:
        result = await message(req)

    mock_ingest.assert_awaited_once_with("https://example.com/article")
    assert "5" in result.response
    assert result.intent == "store_knowledge"


async def test_store_knowledge_routes_to_ingest_youtube_for_youtube_url():
    tier1_result = Tier1Response(
        intent="store_knowledge",
        complexity=0.2,
        escalate=False,
        escalation_reason="",
        response="",
    )
    req = MessageRequest(
        text="Watch this https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        chat_id="chat_001",
    )

    with patch("backend.router.api.call_tier1", AsyncMock(return_value=tier1_result)), \
         patch("backend.router.api.ingest_youtube", AsyncMock(return_value=8)) as mock_yt:
        result = await message(req)

    mock_yt.assert_awaited_once_with("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert "8" in result.response


async def test_store_knowledge_falls_back_to_text_when_no_url():
    tier1_result = Tier1Response(
        intent="store_knowledge",
        complexity=0.2,
        escalate=False,
        escalation_reason="",
        response="",
    )
    req = MessageRequest(text="Python is great for data science", chat_id="chat_001")

    with patch("backend.router.api.call_tier1", AsyncMock(return_value=tier1_result)), \
         patch("backend.router.api._chunk", return_value=["Python is great for data science"]), \
         patch("backend.router.api.store_chunk", return_value="uuid") as mock_store:
        result = await message(req)

    mock_store.assert_called_once()
    assert result.response == "Saved."


async def test_store_knowledge_url_ingestion_error_returns_friendly_message():
    tier1_result = Tier1Response(
        intent="store_knowledge",
        complexity=0.2,
        escalate=False,
        escalation_reason="",
        response="",
    )
    req = MessageRequest(text="Save https://example.com", chat_id="chat_001")

    with patch("backend.router.api.call_tier1", AsyncMock(return_value=tier1_result)), \
         patch("backend.router.api.ingest_url", AsyncMock(side_effect=ValueError("insufficient content"))):
        result = await message(req)

    assert "Could not ingest" in result.response
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_router.py -k "store_knowledge_routes" -v
```

Expected: `ImportError` or `AttributeError` — `ingest_url` not imported in `api.py`

- [ ] **Step 3: Update `backend/router/api.py`**

Add these imports after the existing imports at the top:

```python
import re
from urllib.parse import urlparse
```

And add after the existing ingestion imports:

```python
from backend.ingestion.url import ingest_url
from backend.ingestion.youtube import ingest_youtube
```

Replace the `store_knowledge` branch (lines 56–73 of the current file):

```python
    if tier1.intent == "store_knowledge":
        url_match = re.search(r"https?://[^\s]+", req.text)
        if url_match:
            url = url_match.group(0)
            _YT_DOMAINS = {"youtube.com", "www.youtube.com", "youtu.be"}
            source_type = "youtube" if urlparse(url).netloc in _YT_DOMAINS else "url"
            try:
                if source_type == "youtube":
                    n = await ingest_youtube(url)
                else:
                    n = await ingest_url(url)
                response_text = f"Saved — ingested {n} chunks from {url}."
            except Exception as exc:
                response_text = f"Could not ingest URL: {exc}"
        else:
            try:
                chunks = _chunk(req.text)
                for i, chunk in enumerate(chunks):
                    store_chunk(chunk, {
                        "source_type": "whatsapp",
                        "source_url": "",
                        "title": req.text[:80],
                        "date_added": datetime.now(timezone.utc).isoformat(),
                        "chunk_index": i,
                        "tags": [],
                    })
                response_text = "Saved."
            except RuntimeError:
                response_text = "Could not save — embedding service unavailable."
            except Exception:
                response_text = "Could not save — vector store unavailable."
        return MessageResponse(response=response_text, tier_used=1, intent=tier1.intent)
```

- [ ] **Step 4: Run the new tests**

```bash
pytest tests/test_router.py -v
```

Expected: all tests PASS (including the 4 new ones)

- [ ] **Step 5: Commit**

```bash
git add backend/router/api.py tests/test_router.py
git commit -m "feat: auto-detect URL in store_knowledge intent and route to URL/YouTube ingester"
```

---

## Task 10: WhatsApp media/URL detection + BackgroundTask

**Files:**
- Modify: `backend/interfaces/whatsapp.py`
- Modify: `tests/test_whatsapp.py` — add ingestion path tests

- [ ] **Step 1: Write the failing tests**

Append these tests to `tests/test_whatsapp.py`:

```python
# ---------------------------------------------------------------------------
# WhatsApp — PDF media attachment → background ingestion
# ---------------------------------------------------------------------------

async def test_whatsapp_pdf_attachment_enqueues_background_task():
    with patch("backend.interfaces.whatsapp.RequestValidator") as MockValidator, \
         patch("backend.interfaces.whatsapp.registry") as mock_registry, \
         patch("backend.interfaces.whatsapp.run_ingest") as mock_run_ingest:
        MockValidator.return_value.validate.return_value = True
        mock_registry.create.return_value = "task-uuid-123"

        async with AsyncClient(
            transport=ASGITransport(app=app_test), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/whatsapp",
                data={
                    "Body": "",
                    "From": "whatsapp:+33612345678",
                    "MediaUrl0": "https://api.twilio.com/media/abc123",
                    "MediaContentType0": "application/pdf",
                },
                headers={"X-Twilio-Signature": "valid-sig"},
            )

    assert response.status_code == 200
    assert "processing" in response.text.lower()
    mock_registry.create.assert_called_once()


async def test_whatsapp_url_in_body_enqueues_background_task():
    with patch("backend.interfaces.whatsapp.RequestValidator") as MockValidator, \
         patch("backend.interfaces.whatsapp.registry") as mock_registry, \
         patch("backend.interfaces.whatsapp.run_ingest"):
        MockValidator.return_value.validate.return_value = True
        mock_registry.create.return_value = "task-uuid-456"

        async with AsyncClient(
            transport=ASGITransport(app=app_test), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/whatsapp",
                data={
                    "Body": "Check this out https://example.com/article",
                    "From": "whatsapp:+33612345678",
                },
                headers={"X-Twilio-Signature": "valid-sig"},
            )

    assert response.status_code == 200
    assert "processing" in response.text.lower()
    mock_registry.create.assert_called_once()


async def test_whatsapp_youtube_url_in_body_enqueues_background_task():
    with patch("backend.interfaces.whatsapp.RequestValidator") as MockValidator, \
         patch("backend.interfaces.whatsapp.registry") as mock_registry, \
         patch("backend.interfaces.whatsapp.run_ingest"):
        MockValidator.return_value.validate.return_value = True
        mock_registry.create.return_value = "task-uuid-789"

        async with AsyncClient(
            transport=ASGITransport(app=app_test), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/whatsapp",
                data={
                    "Body": "Watch this https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    "From": "whatsapp:+33612345678",
                },
                headers={"X-Twilio-Signature": "valid-sig"},
            )

    assert response.status_code == 200
    assert "processing" in response.text.lower()
    mock_registry.create.assert_called_once()


async def test_whatsapp_plain_text_still_goes_to_message_handler():
    with patch("backend.interfaces.whatsapp.RequestValidator") as MockValidator, \
         patch("backend.interfaces.whatsapp.handle_message", new_callable=AsyncMock) as mock_handle:
        MockValidator.return_value.validate.return_value = True
        mock_handle.return_value = MagicMock(response="Hello!", tier_used=1, intent="general")

        async with AsyncClient(
            transport=ASGITransport(app=app_test), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/whatsapp",
                data={"Body": "Hello there", "From": "whatsapp:+33612345678"},
                headers={"X-Twilio-Signature": "valid-sig"},
            )

    assert response.status_code == 200
    mock_handle.assert_awaited_once()
    assert "Hello!" in response.text
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_whatsapp.py -v
```

Expected: existing 3 tests pass, new 4 tests fail with import or signature errors

- [ ] **Step 3: Replace `backend/interfaces/whatsapp.py`**

```python
import re
from urllib.parse import urlparse
from xml.sax.saxutils import escape

import logging

from fastapi import APIRouter, BackgroundTasks, Form, Header, HTTPException, Request
from fastapi.responses import Response
from twilio.request_validator import RequestValidator

from backend.config import settings
from backend.ingestion.registry import registry
from backend.router.api import MessageRequest
from backend.router.api import message as handle_message
from backend.router.ingest import run_ingest

logger = logging.getLogger(__name__)

logger = logging.getLogger(__name__)
router = APIRouter()

_URL_RE = re.compile(r"https?://[^\s]+")
_YT_DOMAINS = {"youtube.com", "www.youtube.com", "youtu.be"}
_PROCESSING_MSG = "Got it, I'm processing that — I'll let you know when it's ready."


def _classify_url(url: str) -> str:
    return "youtube" if urlparse(url).netloc in _YT_DOMAINS else "url"


@router.post("/whatsapp")
async def whatsapp_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    Body: str = Form(""),
    From: str = Form(...),
    x_twilio_signature: str = Header(...),
    MediaUrl0: str | None = Form(None),
    MediaContentType0: str | None = Form(None),
) -> Response:
    validator = RequestValidator(settings.twilio_auth_token)
    params = dict(await request.form())
    if not validator.validate(str(request.url), params, x_twilio_signature):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    chat_id = From.removeprefix("whatsapp:")

    # PDF media attachment from Twilio
    if MediaUrl0 and MediaContentType0 == "application/pdf":
        task_id = registry.create()
        background_tasks.add_task(
            run_ingest,
            task_id,
            "pdf",
            MediaUrl0,
            chat_id,
            auth=(settings.twilio_account_sid, settings.twilio_auth_token),
        )
        twiml = f"<Response><Message>{escape(_PROCESSING_MSG)}</Message></Response>"
        return Response(content=twiml, media_type="text/xml")

    # URL detected in message body
    url_match = _URL_RE.search(Body)
    if url_match:
        url = url_match.group(0)
        source_type = _classify_url(url)
        task_id = registry.create()
        background_tasks.add_task(run_ingest, task_id, source_type, url, chat_id)
        twiml = f"<Response><Message>{escape(_PROCESSING_MSG)}</Message></Response>"
        return Response(content=twiml, media_type="text/xml")

    # Normal message flow
    result = await handle_message(MessageRequest(text=Body, chat_id=chat_id))
    twiml = f"<Response><Message>{escape(result.response)}</Message></Response>"
    return Response(content=twiml, media_type="text/xml")
```

- [ ] **Step 4: Run the WhatsApp tests**

```bash
pytest tests/test_whatsapp.py -v
```

Expected: all 7 tests PASS

- [ ] **Step 5: Run the full test suite**

```bash
pytest tests/ -v
```

Expected: all tests PASS. Count should be 78 (existing) + 7 (registry) + 7 (fetch) + 6 (pdf) + 11 (url) + 12 (youtube) + 11 (ingest router) + 4 (router url detection) + 4 (whatsapp ingestion) = ~120 tests.

- [ ] **Step 6: Commit**

```bash
git add backend/interfaces/whatsapp.py tests/test_whatsapp.py
git commit -m "feat: detect PDF attachments and URLs in WhatsApp webhook, queue background ingestion"
```
