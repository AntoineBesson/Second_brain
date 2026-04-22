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
