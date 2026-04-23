from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.ingestion.pdf import ingest_pdf


async def test_ingest_pdf_returns_chunk_count():
    mock_page = MagicMock()
    mock_page.get_text = MagicMock(return_value="Hello world. This is a test page.")

    mock_doc = MagicMock()
    mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))
    mock_doc.__enter__ = MagicMock(return_value=mock_doc)
    mock_doc.__exit__ = MagicMock(return_value=None)

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
    mock_doc.__enter__ = MagicMock(return_value=mock_doc)
    mock_doc.__exit__ = MagicMock(return_value=None)

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
    mock_doc.__enter__ = MagicMock(return_value=mock_doc)
    mock_doc.__exit__ = MagicMock(return_value=None)

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
    mock_doc.__enter__ = MagicMock(return_value=mock_doc)
    mock_doc.__exit__ = MagicMock(return_value=None)

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
    mock_doc.__enter__ = MagicMock(return_value=mock_doc)
    mock_doc.__exit__ = MagicMock(return_value=None)

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
