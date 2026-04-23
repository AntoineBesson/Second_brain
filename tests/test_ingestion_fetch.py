from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import UploadFile

from backend.ingestion.fetch import fetch_bytes


async def test_fetch_bytes_upload_file():
    mock_upload = MagicMock(spec=UploadFile)
    mock_upload.read = AsyncMock(return_value=b"pdf content")
    result = await fetch_bytes(mock_upload)
    assert result == b"pdf content"
    mock_upload.read.assert_awaited_once()


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
