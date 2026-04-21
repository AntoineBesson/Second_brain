from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.scheduler.reminders import dispatch_due_reminders


async def test_dispatch_sends_message_and_marks_sent():
    mock_reminder = MagicMock()
    mock_reminder.id = "some-uuid"
    mock_reminder.text = "Call Marc"
    mock_reminder.chat_id = "+33612345678"

    mock_session = AsyncMock()
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.scheduler.reminders.AsyncSessionLocal", return_value=mock_cm), \
         patch("backend.scheduler.reminders.get_due_reminders", AsyncMock(return_value=[mock_reminder])), \
         patch("backend.scheduler.reminders.mark_sent", AsyncMock()) as mock_mark_sent, \
         patch("backend.scheduler.reminders._send_whatsapp", AsyncMock()) as mock_send:
        await dispatch_due_reminders()

    mock_send.assert_awaited_once_with("Call Marc", "+33612345678")
    mock_mark_sent.assert_awaited_once_with(mock_session, "some-uuid")
    mock_session.commit.assert_awaited_once()


async def test_dispatch_skips_mark_sent_on_twilio_failure():
    mock_reminder = MagicMock()
    mock_reminder.id = "some-uuid"
    mock_reminder.text = "Call Marc"
    mock_reminder.chat_id = "+33612345678"

    mock_session = AsyncMock()
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.scheduler.reminders.AsyncSessionLocal", return_value=mock_cm), \
         patch("backend.scheduler.reminders.get_due_reminders", AsyncMock(return_value=[mock_reminder])), \
         patch("backend.scheduler.reminders.mark_sent", AsyncMock()) as mock_mark_sent, \
         patch("backend.scheduler.reminders._send_whatsapp", AsyncMock(side_effect=Exception("Twilio 500"))):
        await dispatch_due_reminders()

    mock_mark_sent.assert_not_awaited()
    mock_session.commit.assert_not_awaited()


async def test_dispatch_continues_after_one_failure():
    """A Twilio failure on reminder 1 must not block reminder 2."""
    r1, r2 = MagicMock(), MagicMock()
    r1.id, r1.text, r1.chat_id = "id-1", "Call Marc", "+33612345678"
    r2.id, r2.text, r2.chat_id = "id-2", "Buy milk", "+33612345678"

    mock_session = AsyncMock()
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    send_calls = []

    async def fake_send(text, chat_id):
        send_calls.append(text)
        if text == "Call Marc":
            raise Exception("Twilio error")

    with patch("backend.scheduler.reminders.AsyncSessionLocal", return_value=mock_cm), \
         patch("backend.scheduler.reminders.get_due_reminders", AsyncMock(return_value=[r1, r2])), \
         patch("backend.scheduler.reminders.mark_sent", AsyncMock()) as mock_mark_sent, \
         patch("backend.scheduler.reminders._send_whatsapp", side_effect=fake_send):
        await dispatch_due_reminders()

    assert send_calls == ["Call Marc", "Buy milk"]
    mock_mark_sent.assert_awaited_once_with(mock_session, "id-2")
