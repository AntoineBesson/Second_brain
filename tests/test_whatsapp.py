from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.interfaces.whatsapp import router

app_test = FastAPI()
app_test.include_router(router)


async def test_whatsapp_webhook_valid_signature_returns_twiml():
    with patch("backend.interfaces.whatsapp.RequestValidator") as MockValidator, \
         patch("backend.interfaces.whatsapp.handle_message", new_callable=AsyncMock) as mock_handle:
        MockValidator.return_value.validate.return_value = True
        mock_handle.return_value = MagicMock(
            response="I'll remind you to Call Marc on April 22 at 10:00.",
            tier_used=1,
            intent="store_reminder",
        )

        async with AsyncClient(
            transport=ASGITransport(app=app_test), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/whatsapp",
                data={"Body": "Remind me to call Marc tomorrow at 10", "From": "whatsapp:+33612345678"},
                headers={"X-Twilio-Signature": "valid-sig"},
            )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/xml")
    assert "<Response>" in response.text
    assert "<Message>" in response.text
    assert "Call Marc" in response.text


async def test_whatsapp_webhook_invalid_signature_returns_403():
    with patch("backend.interfaces.whatsapp.RequestValidator") as MockValidator:
        MockValidator.return_value.validate.return_value = False

        async with AsyncClient(
            transport=ASGITransport(app=app_test), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/whatsapp",
                data={"Body": "Hi", "From": "whatsapp:+33612345678"},
                headers={"X-Twilio-Signature": "bad-sig"},
            )

    assert response.status_code == 403


async def test_whatsapp_webhook_strips_whatsapp_prefix_from_chat_id():
    with patch("backend.interfaces.whatsapp.RequestValidator") as MockValidator, \
         patch("backend.interfaces.whatsapp.handle_message", new_callable=AsyncMock) as mock_handle:
        MockValidator.return_value.validate.return_value = True
        mock_handle.return_value = MagicMock(response="OK", tier_used=1, intent="general")

        async with AsyncClient(
            transport=ASGITransport(app=app_test), base_url="http://test"
        ) as ac:
            await ac.post(
                "/whatsapp",
                data={"Body": "Hello", "From": "whatsapp:+33612345678"},
                headers={"X-Twilio-Signature": "valid-sig"},
            )

    call_args = mock_handle.call_args.args[0]
    assert call_args.chat_id == "+33612345678"
    assert call_args.text == "Hello"


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
    pdf_call = mock_run_ingest.call_args
    assert pdf_call.args[1] == "pdf"
    assert pdf_call.kwargs.get("auth") is not None


async def test_whatsapp_url_in_body_enqueues_background_task():
    with patch("backend.interfaces.whatsapp.RequestValidator") as MockValidator, \
         patch("backend.interfaces.whatsapp.registry") as mock_registry, \
         patch("backend.interfaces.whatsapp.run_ingest") as mock_run_ingest:
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
    call_args = mock_run_ingest.call_args
    assert call_args.args[1] == "url"


async def test_whatsapp_youtube_url_in_body_enqueues_background_task():
    with patch("backend.interfaces.whatsapp.RequestValidator") as MockValidator, \
         patch("backend.interfaces.whatsapp.registry") as mock_registry, \
         patch("backend.interfaces.whatsapp.run_ingest") as mock_run_ingest:
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
    call_args = mock_run_ingest.call_args
    assert call_args.args[1] == "youtube"


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
