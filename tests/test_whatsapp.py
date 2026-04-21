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
