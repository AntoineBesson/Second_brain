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
