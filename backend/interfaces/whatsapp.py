import logging
from xml.sax.saxutils import escape

from fastapi import APIRouter, Form, Header, HTTPException, Request
from fastapi.responses import Response
from twilio.request_validator import RequestValidator

from backend.config import settings
from backend.router.api import MessageRequest
from backend.router.api import message as handle_message

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/whatsapp")
async def whatsapp_webhook(
    request: Request,
    Body: str = Form(...),
    From: str = Form(...),
    x_twilio_signature: str = Header(...),
) -> Response:
    validator = RequestValidator(settings.twilio_auth_token)
    params = dict(await request.form())
    if not validator.validate(str(request.url), params, x_twilio_signature):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    chat_id = From.removeprefix("whatsapp:")
    result = await handle_message(MessageRequest(text=Body, chat_id=chat_id))

    twiml = f"<Response><Message>{escape(result.response)}</Message></Response>"
    return Response(content=twiml, media_type="text/xml")
