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
