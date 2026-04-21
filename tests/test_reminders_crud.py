import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.reminders.crud import (
    create_reminder,
    get_due_reminders,
    get_or_create_user_prefs,
    mark_sent,
)
from backend.memory.postgres import Reminder, UserPreference


# --------------------------------------------------------------------------
# create_reminder
# --------------------------------------------------------------------------

async def test_create_reminder_adds_and_returns():
    mock_session = AsyncMock()
    mock_session.add = MagicMock()

    trigger_at = datetime(2026, 4, 22, 10, 0, tzinfo=timezone.utc)
    result = await create_reminder(mock_session, "Call Marc", trigger_at, "+33612345678")

    mock_session.add.assert_called_once()
    added = mock_session.add.call_args.args[0]
    assert isinstance(added, Reminder)
    assert added.text == "Call Marc"
    assert added.trigger_at == trigger_at
    assert added.chat_id == "+33612345678"
    mock_session.flush.assert_awaited_once()
    mock_session.refresh.assert_awaited_once_with(added)
    assert result is added


# --------------------------------------------------------------------------
# get_due_reminders
# --------------------------------------------------------------------------

async def test_get_due_reminders_returns_list():
    r1, r2 = MagicMock(spec=Reminder), MagicMock(spec=Reminder)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [r1, r2]

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    result = await get_due_reminders(mock_session)

    assert result == [r1, r2]
    mock_session.execute.assert_awaited_once()


async def test_get_due_reminders_returns_empty_list():
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    result = await get_due_reminders(mock_session)

    assert result == []


# --------------------------------------------------------------------------
# mark_sent
# --------------------------------------------------------------------------

async def test_mark_sent_executes_update():
    mock_session = AsyncMock()
    rid = uuid.uuid4()

    await mark_sent(mock_session, rid)

    mock_session.execute.assert_awaited_once()


# --------------------------------------------------------------------------
# get_or_create_user_prefs
# --------------------------------------------------------------------------

async def test_get_or_create_user_prefs_returns_preference():
    mock_pref = MagicMock(spec=UserPreference)
    mock_pref.timezone = "Europe/Paris"

    insert_result = MagicMock()
    select_result = MagicMock()
    select_result.scalar_one.return_value = mock_pref

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=[insert_result, select_result])

    result = await get_or_create_user_prefs(mock_session, "+33612345678")

    assert result is mock_pref
    assert mock_session.execute.await_count == 2
