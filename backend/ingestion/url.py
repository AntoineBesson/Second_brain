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
